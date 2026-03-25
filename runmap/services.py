import math
import cv2
import requests
from django.contrib.gis.geos import LineString

from .exceptions import RouteGenerationError, ContourExtractionError


# ── 1. Вилучення контуру з зображення (OpenCV) ──────────────────────────────

def extract_contour(image_path: str) -> list[tuple[float, float]]:
    """
    Витягує найбільший контур із зображення.
    Повертає список піксельних точок [(x1,y1), (x2,y2), ...].
    """
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ContourExtractionError(f"Не вдалося відкрити зображення: {image_path}")

    # Розмиття для зменшення шуму
    blurred = cv2.GaussianBlur(img, (5, 5), 0)

    # Автоматичний поріг + знаходження країв
    edges = cv2.Canny(blurred, 50, 150)

    # Знаходимо всі контури
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ContourExtractionError("Контури на зображенні не знайдено")

    # Беремо найбільший контур за площею
    largest = max(contours, key=cv2.contourArea)

    # Спрощуємо контур щоб не було зайвих точок (важливо для OSRM)
    epsilon = 0.002 * cv2.arcLength(largest, closed=True)
    simplified = cv2.approxPolyDP(largest, epsilon, closed=True)

    # Перетворюємо у плоский список (x, y)
    points = [(int(p[0][0]), int(p[0][1])) for p in simplified]

    # Замикаємо контур (остання точка = перша)
    if points[0] != points[-1]:
        points.append(points[0])

    return points


# ── 2. Проєкція пікселів → GPS ───────────────────────────────────────────────

def project_to_gps(
    pixel_points: list[tuple[float, float]],
    center_lat: float,
    center_lon: float,
    radius_meters: float
) -> list[tuple[float, float]]:

    xs = [p[0] for p in pixel_points]
    ys = [p[1] for p in pixel_points]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_range = (x_max - x_min) or 1
    y_range = (y_max - y_min) or 1

    lat_per_meter = 1 / 111_320
    lon_per_meter = 1 / (111_320 * math.cos(math.radians(center_lat)))

    gps_points = []
    for x, y in pixel_points:
        norm_x = (x - x_min) / x_range * 2 - 1
        # ✓ Інвертуємо Y: в пікселях 0=верх, в GPS більший lat=північ
        norm_y = -((y - y_min) / y_range * 2 - 1)

        lat = center_lat + norm_y * radius_meters * lat_per_meter
        lon = center_lon + norm_x * radius_meters * lon_per_meter

        gps_points.append((lat, lon))

    return gps_points


# ── 3. Маршрутизація через OSRM ──────────────────────────────────────────────

def match_route_with_osrm(
        gps_points: list[tuple[float, float]],
        profile: str = "foot"
) -> list[tuple[float, float]]:
    MAX_POINTS = 99
    if len(gps_points) > MAX_POINTS:
        indices = [int(i * (len(gps_points) - 1) / (MAX_POINTS - 1)) for i in range(MAX_POINTS)]
        gps_points = [gps_points[i] for i in indices]

    coords_str = ";".join(f"{lon},{lat}" for lat, lon in gps_points)

    # Використовуємо route замість match — він менш строгий до точності точок
    url = f"http://router.project-osrm.org/route/v1/{profile}/{coords_str}"

    params = {
        "geometries": "geojson",
        "overview": "full",
        "annotations": "false",
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if data.get("code") != "Ok":
        raise RouteGenerationError(f"OSRM помилка: {data.get('code')} — {data.get('message', '')}")

    # route повертає routes[0], а не matchings[0]
    return data["routes"][0]["geometry"]["coordinates"]


# ── 4. Головна функція ────────────────────────────────────────────────────────

def generate_route(
    image_path: str,
    center_lat: float,
    center_lon: float,
    radius_meters: float = 1000,
    profile: str = "foot"
) -> LineString:
    """
    Повний пайплайн: зображення → контур → GPS → дороги → LineString.
    """
    try:
        pixel_points = extract_contour(image_path)
        gps_points = project_to_gps(pixel_points, center_lat, center_lon, radius_meters)
        matched_points = match_route_with_osrm(gps_points, profile)
        return LineString(matched_points, srid=4326)
    except ContourExtractionError:
        raise  # Прокидаємо далі, щоб views.py зловив як ContourExtractionError
    except Exception as e:
        raise RouteGenerationError(f"Помилка генерації маршруту: {str(e)}")