# runmap/services.py

import math
import cv2
import numpy as np
import requests
from affine import Affine
from django.contrib.gis.geos import LineString, Point
from django.contrib.gis.db.models.functions import Distance
from django.conf import settings
from .exceptions import RouteGenerationError, ContourExtractionError


# ── 1. Отримання контуру ─────────────────────────────────────────────────────
def extract_contour(image_path: str) -> list[tuple[float, float]]:
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ContourExtractionError(f"Не вдалося відкрити зображення: {image_path}")

    blurred = cv2.GaussianBlur(img, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ContourExtractionError("Контури на зображенні не знайдено")

    largest = max(contours, key=cv2.contourArea)
    epsilon = 0.002 * cv2.arcLength(largest, closed=True)
    simplified = cv2.approxPolyDP(largest, epsilon, closed=True)
    points = [(int(p[0][0]), int(p[0][1])) for p in simplified]

    if points and points[0] != points[-1]:
        points.append(points[0])
    return points


# ── 2. Спрощення GPS-контуру (Дуглас-Пекер) ─────────────────────────────────
def simplify_contour(points, epsilon=0.0001):
    """
    Спрощує список точок (lat, lon) за алгоритмом Дугласа-Пекера.
    epsilon – максимальне відхилення в градусах (0.00001° ≈ 1.1 м).
    """
    if len(points) <= 2:
        return points

    dmax = 0.0
    index = 0
    end = len(points) - 1
    for i in range(1, end):
        d = _perpendicular_distance(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d

    if dmax > epsilon:
        left = simplify_contour(points[:index + 1], epsilon)
        right = simplify_contour(points[index:], epsilon)
        return left[:-1] + right
    else:
        return [points[0], points[end]]


def _perpendicular_distance(point, line_start, line_end):
    lat, lon = point
    lat1, lon1 = line_start
    lat2, lon2 = line_end
    dx = lon2 - lon1
    dy = lat2 - lat1
    norm = math.hypot(dx, dy)
    if norm == 0:
        return math.hypot(lat - lat1, lon - lon1)
    area = abs((lon - lon1) * (lat2 - lat1) - (lat - lat1) * (lon2 - lon1))
    return area / norm


# ── 3. Афінне проектування ───────────────────────────────────────────────────
def compute_affine_from_corners(pixel_corners, geo_corners):
    src = np.array(pixel_corners)
    dst = np.array(geo_corners)
    A = np.hstack([src, np.ones((3, 1))])
    M, _, _, _ = np.linalg.lstsq(A, dst, rcond=None)
    a, b, c = M[0, 0], M[1, 0], M[2, 0]
    d, e, f = M[0, 1], M[1, 1], M[2, 1]
    return Affine(a, b, c, d, e, f)


def project_with_affine(pixel_points, width, height, corners, input_order='latlon'):
    if not pixel_points:
        return []
    def convert(pt):
        return (pt[1], pt[0]) if input_order == 'latlon' else (pt[0], pt[1])
    if len(corners) >= 4:
        pts = [corners[0], corners[1], corners[3]]
    else:
        pts = corners[:3]
    geo_corners = [convert(pt) for pt in pts]
    pixel_corners = [(0, 0), (width, 0), (0, height)]
    aff = compute_affine_from_corners(pixel_corners, geo_corners)
    gps_points = []
    for x, y in pixel_points:
        lon, lat = aff * (x, y)
        gps_points.append((lat, lon))
    return gps_points


# ── 4. Стара функція проектування (центр + радіус) ───────────────────────────
def project_to_gps(pixel_points, center_lat, center_lon, radius_meters):
    if not pixel_points:
        return []
    xs = [p[0] for p in pixel_points]
    ys = [p[1] for p in pixel_points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_range = (x_max - x_min) or 1
    y_range = (y_max - y_min) or 1
    lat_per_m = 1 / 111_320
    lon_per_m = 1 / (111_320 * math.cos(math.radians(center_lat)))
    gps = []
    for x, y in pixel_points:
        norm_x = (x - x_min) / x_range * 2 - 1
        norm_y = -((y - y_min) / y_range * 2 - 1)
        gps.append((
            center_lat + norm_y * radius_meters * lat_per_m,
            center_lon + norm_x * radius_meters * lon_per_m
        ))
    return gps


# ── 5. Прив’язка точок до найближчої дороги (PostGIS або OSRM Nearest) ─────
def snap_to_road_point(lat, lon):
    """
    Повертає найближчу точку на дорожній мережі у форматі (lat, lon).
    Спочатку пробує PostGIS (таблиця roads), потім OSRM /nearest як запасний варіант.
    """
    # 5.1 Спроба через PostGIS (якщо є таблиця roads)
    try:
        from django.contrib.gis.db.models import GeometryField
        from runmap.models import Road  # приклад моделі дороги
        point = Point(lon, lat, srid=4326)
        # Знаходимо найближчий сегмент дороги (за відстанню)
        road = Road.objects.filter(geom__isnull=False).annotate(
            distance=Distance('geom', point)
        ).order_by('distance').first()
        if road:
            # Повертаємо точку на дорозі, найближчу до point
            snapped = road.geom.closest_point(point)
            return (snapped.y, snapped.x)  # lat, lon
    except Exception:
        pass  # Якщо моделі немає або помилка, переходимо до OSRM

    # 5.2 Запасний варіант – OSRM Nearest API (один запит на точку)
    base_url = getattr(settings, 'OSRM_BASE_URL', 'http://127.0.0.1:5000')
    url = f"{base_url}/nearest/v1/foot/{lon},{lat}"
    try:
        resp = requests.get(url, params={"number": 1}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == "Ok" and data.get("waypoints"):
            loc = data["waypoints"][0]["location"]
            return (loc[1], loc[0])  # lat, lon
    except Exception:
        pass  # Якщо не вдалося, повертаємо оригінальну точку
    return (lat, lon)


def snap_contour_to_roads(gps_points):
    """Прив’язує всі точки контуру до найближчих доріг."""
    return [snap_to_road_point(lat, lon) for lat, lon in gps_points]


# ── 6. Маршрутизація через OSRM Route API (оптимізована) ─────────────────────
def match_route_with_osrm(gps_points, profile="foot"):
    """
    Будує маршрут дорогами через Route API.
    Попередньо контур спрощується, а точки прив’язуються до доріг.
    """
    if not gps_points:
        raise RouteGenerationError("Немає точок для маршрутизації")

    # Агресивне спрощення – залишаємо лише ключові точки (5–20)
    # epsilon підбирайте під масштаб: 0.0002 ≈ 22 м
    simplified = simplify_contour(gps_points, epsilon=0.0002)

    # Прив'язуємо всі ключові точки до доріг
    snapped = snap_contour_to_roads(simplified)

    # Обмежуємо кількість точок для OSRM (не більше 100)
    MAX_POINTS = 99
    if len(snapped) > MAX_POINTS:
        indices = [int(i * (len(snapped) - 1) / (MAX_POINTS - 1)) for i in range(MAX_POINTS)]
        snapped = [snapped[i] for i in indices]

    coords_str = ";".join(f"{lon},{lat}" for lat, lon in snapped)

    base_url = getattr(settings, 'OSRM_BASE_URL', 'http://127.0.0.1:5000')
    url = f"{base_url}/route/v1/{profile}/{coords_str}"
    params = {
        "geometries": "geojson",
        "overview": "full",
        "annotations": "false",
        "continue_straight": "false",  # не продовжувати прямо, а йти за точками
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        raise RouteGenerationError("Таймаут при зверненні до OSRM")
    except requests.exceptions.RequestException as e:
        raise RouteGenerationError(f"Помилка зв'язку з OSRM: {str(e)}")

    if data.get("code") != "Ok":
        raise RouteGenerationError(
            f"OSRM помилка: {data.get('code')} — {data.get('message', '')}"
        )
    if not data.get("routes"):
        raise RouteGenerationError("OSRM не повернув маршрутів")

    return data["routes"][0]["geometry"]["coordinates"]


# ── 7. Генерація маршрутів (старі інтерфейси) ────────────────────────────────
def generate_route(image_path, center_lat, center_lon, radius_meters=1000, profile="foot"):
    try:
        pixel_points = extract_contour(image_path)
        gps_points = project_to_gps(pixel_points, center_lat, center_lon, radius_meters)
        matched = match_route_with_osrm(gps_points, profile)
        return LineString(matched, srid=4326)
    except Exception as e:
        if not isinstance(e, (ContourExtractionError, RouteGenerationError)):
            raise RouteGenerationError(f"Помилка генерації: {e}")
        raise


def generate_route_affine(image_path, corners, profile="foot", input_order='latlon'):
    try:
        img = cv2.imread(image_path)
        if img is None:
            raise RouteGenerationError("Не вдалося прочитати зображення")
        height, width = img.shape[:2]
        pixel_points = extract_contour(image_path)
        gps_contour = project_with_affine(pixel_points, width, height, corners, input_order)
        matched = match_route_with_osrm(gps_contour, profile)
        return LineString(matched, srid=4326)
    except Exception as e:
        if not isinstance(e, (ContourExtractionError, RouteGenerationError)):
            raise RouteGenerationError(f"Помилка генерації: {e}")
        raise