# runmap/services.py

import math
import cv2
import numpy as np
import requests
from affine import Affine
from django.contrib.gis.geos import LineString
from django.conf import settings
from .exceptions import RouteGenerationError, ContourExtractionError


# ── 1. Извлечение контура ─────────────────────────────────────────────────────
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

    # Замыкаем контур, если нужно
    if points and points[0] != points[-1]:
        points.append(points[0])
    return points


# ── 2. Аффинное проецирование ─────────────────────────────────────────────────
def compute_affine_from_corners(pixel_corners, geo_corners):
    """
    Вычисляет Affine-трансформацию из пиксельных координат в географические (lon, lat).
    pixel_corners: список из 3 точек в пикселях [(0,0), (width,0), (0,height)]
    geo_corners: соответствующие точки в GPS [(lon1,lat1), (lon2,lat2), (lon3,lat3)]
    Возвращает объект Affine.
    """
    src = np.array(pixel_corners)
    dst = np.array(geo_corners)
    # Добавляем столбец единиц
    A = np.hstack([src, np.ones((3, 1))])
    # Решаем A * M = dst, M имеет форму (3,2)
    M, _, _, _ = np.linalg.lstsq(A, dst, rcond=None)

    # Коэффициенты для lon (первый столбец dst)
    a, b, c = M[0, 0], M[1, 0], M[2, 0]
    # Коэффициенты для lat (второй столбец dst)
    d, e, f = M[0, 1], M[1, 1], M[2, 1]

    return Affine(a, b, c, d, e, f)


def project_with_affine(pixel_points, width, height, corners, input_order='latlon'):
    if not pixel_points:
        return []

    if input_order == 'latlon':
        def convert(pt):
            return (pt[1], pt[0])
    else:
        def convert(pt):
            return (pt[0], pt[1])

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


# ── 3. Старая функция проецирования (центр + радиус) ─────────────────────────
def project_to_gps(pixel_points, center_lat, center_lon, radius_meters):
    if not pixel_points:
        return []

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
        norm_y = -((y - y_min) / y_range * 2 - 1)
        lat = center_lat + norm_y * radius_meters * lat_per_meter
        lon = center_lon + norm_x * radius_meters * lon_per_meter
        gps_points.append((lat, lon))
    return gps_points


# ── 4. Маршрутизация через OSRM ───────────────────────────────────────────────
def match_route_with_osrm(gps_points, profile="foot"):
    """
    Строит маршрут по дорогам через OSRM.
    gps_points: список (lat, lon)
    profile: 'foot' или 'bike'
    Возвращает список координат [[lon, lat], ...] в формате GeoJSON.
    """
    if not gps_points:
        raise RouteGenerationError("Нет точек для маршрутизации")

    MAX_POINTS = 99
    if len(gps_points) > MAX_POINTS:
        # Прореживаем точки равномерно
        indices = [int(i * (len(gps_points) - 1) / (MAX_POINTS - 1)) for i in range(MAX_POINTS)]
        gps_points = [gps_points[i] for i in indices]

    coords_str = ";".join(f"{lon},{lat}" for lat, lon in gps_points)

    # Берём URL из настроек
    base_url = getattr(settings, 'OSRM_BASE_URL', 'http://router.project-osrm.org')
    url = f"{base_url}/route/v1/{profile}/{coords_str}"

    params = {
        "geometries": "geojson",
        "overview": "full",
        "annotations": "false",
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        raise RouteGenerationError("Таймаут при обращении к OSRM")
    except requests.exceptions.RequestException as e:
        raise RouteGenerationError(f"Ошибка связи с OSRM: {str(e)}")

    if data.get("code") != "Ok":
        raise RouteGenerationError(f"OSRM помилка: {data.get('code')} — {data.get('message', '')}")

    if not data.get("routes"):
        raise RouteGenerationError("OSRM не вернул маршрутов")

    return data["routes"][0]["geometry"]["coordinates"]


# ── 5. Главная функция генерации (старый режим) ───────────────────────────────
def generate_route(image_path, center_lat, center_lon, radius_meters=1000, profile="foot"):
    """
    Полный пайплайн для старого режима: изображение → контур → GPS (центр+радиус) → дороги.
    """
    try:
        pixel_points = extract_contour(image_path)
        if not pixel_points:
            raise RouteGenerationError("Не удалось извлечь контур")

        gps_points = project_to_gps(pixel_points, center_lat, center_lon, radius_meters)
        if not gps_points:
            raise RouteGenerationError("Не удалось спроецировать контур")

        matched_points = match_route_with_osrm(gps_points, profile)
        return LineString(matched_points, srid=4326)
    except ContourExtractionError:
        raise
    except RouteGenerationError:
        raise
    except Exception as e:
        raise RouteGenerationError(f"Помилка генерації маршруту: {str(e)}")


# ── 6. Новая функция для аффинного режима (для удобства) ─────────────────────
def generate_route_affine(image_path, corners, profile="foot", input_order='latlon'):
    """
    Полный пайплайн для нового режима: изображение → контур → аффинное проецирование → дороги.
    """
    try:
        # Получаем размеры изображения
        img = cv2.imread(image_path)
        if img is None:
            raise RouteGenerationError("Не вдалося прочитати зображення")
        height, width = img.shape[:2]

        # Извлекаем контур
        pixel_points = extract_contour(image_path)
        if not pixel_points:
            raise RouteGenerationError("Не удалось извлечь контур")

        # Проецируем
        gps_contour = project_with_affine(pixel_points, width, height, corners, input_order)
        if not gps_contour:
            raise RouteGenerationError("Не удалось спроецировать контур")

        # Строим маршрут
        route_coords = match_route_with_osrm(gps_contour, profile)
        return LineString(route_coords, srid=4326)
    except ContourExtractionError:
        raise
    except RouteGenerationError:
        raise
    except Exception as e:
        raise RouteGenerationError(f"Помилка генерації маршруту: {str(e)}")