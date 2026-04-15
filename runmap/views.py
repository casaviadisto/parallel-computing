# runmap/views.py

import json
import tempfile
import os
import cv2
import requests as http_requests
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.filters import OrderingFilter, SearchFilter
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db import transaction
from django.contrib.gis.geos import Point, LineString

from .models import Route
from .serializers import RouteSerializer, UserSerializer
from .services import (
    extract_contour,
    project_to_gps,
    project_with_affine,
    match_route_with_osrm,
    generate_route,
)
from .exceptions import RouteGenerationError, ContourExtractionError


class RouteFilter(django_filters.FilterSet):
    radius_min = django_filters.NumberFilter(field_name='radius', lookup_expr='gte')
    radius_max = django_filters.NumberFilter(field_name='radius', lookup_expr='lte')
    created_after = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')

    class Meta:
        model = Route
        fields = {
            'user': ['exact'],
            'name': ['exact'],
        }


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        try:
            return super().update(request, *args, **kwargs)
        except Exception:
            return Response(
                {"error": "Конфлікт даних при оновленні користувача"},
                status=status.HTTP_409_CONFLICT
            )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RouteViewSet(viewsets.ModelViewSet):
    queryset = Route.objects.all()
    serializer_class = RouteSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_class = RouteFilter
    search_fields = ['name']
    ordering_fields = ['created_at', 'radius', 'name']
    ordering = ['-created_at']

    def create(self, request, *args, **kwargs):
        image_file = request.FILES.get('image')
        if not image_file:
            return Response(
                {"error": "Зображення є обов'язковим для генерації маршруту"},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        corners_str = request.data.get('corners')
        profile = request.data.get('profile', 'foot')

        try:
            with transaction.atomic():
                route = serializer.save()  # объект создан, start_point может быть None

                image_path = default_storage.path(route.image.name)

                if corners_str:
                    # Новый режим: аффинное проецирование по углам
                    try:
                        corners = json.loads(corners_str)
                    except json.JSONDecodeError:
                        raise ValueError("Невірний формат JSON у 'corners'")

                    if len(corners) < 3:
                        raise ValueError("Потрібно мінімум 3 точки у 'corners'")

                    img = cv2.imread(image_path)
                    if img is None:
                        raise ValueError("Не вдалося прочитати зображення")
                    height, width = img.shape[:2]

                    pixel_points = extract_contour(image_path)
                    gps_contour = project_with_affine(
                        pixel_points, width, height, corners, input_order='latlon'
                    )
                    route_coords = match_route_with_osrm(gps_contour, profile)
                    line = LineString(route_coords, srid=4326)

                    # Автоматически вычисляем центр и радиус
                    if line:
                        centroid = line.centroid
                        route.start_point = Point(centroid.x, centroid.y, srid=4326)
                        # Грубая оценка радиуса
                        extent = line.envelope.extent  # (xmin, ymin, xmax, ymax)
                        if extent:
                            import math
                            width_m = abs(extent[2] - extent[0]) * 111320 * math.cos(math.radians(centroid.y))
                            height_m = abs(extent[3] - extent[1]) * 111320
                            route.radius = math.sqrt(width_m ** 2 + height_m ** 2) / 2
                        else:
                            route.radius = 1000.0
                else:
                    # Старый режим: центр + радиус
                    lat = serializer.validated_data.get('lat')
                    lon = serializer.validated_data.get('lon')
                    radius = serializer.validated_data.get('radius', 1000.0)
                    if lat is None or lon is None:
                        return Response(
                            {"error": "Для старого режиму потрібні lat та lon"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    route.start_point = Point(lon, lat, srid=4326)
                    route.radius = radius
                    line = generate_route(
                        image_path=image_path,
                        center_lat=lat,
                        center_lon=lon,
                        radius_meters=radius,
                        profile=profile
                    )

                route.path = line
                route.save()

        except Exception as e:
            return Response({"error": f"Внутрішня помилка сервера: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(self.get_serializer(route).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def preview_contour(self, request):
        image = request.FILES.get('image')
        if not image:
            return Response({"error": "Зображення не передано"}, status=status.HTTP_400_BAD_REQUEST)

        corners_str = request.data.get('corners')

        if corners_str:
            # ── НОВЫЙ РЕЖИМ: аффинное проецирование по углам ─────────────────────────
            profile = request.data.get('profile', 'foot')
            try:
                corners = json.loads(corners_str)
            except json.JSONDecodeError:
                return Response({"error": "Невірний формат JSON у 'corners'"},
                                status=status.HTTP_400_BAD_REQUEST)
            if len(corners) < 3:
                return Response({"error": "Потрібно мінімум 3 точки у 'corners'"},
                                status=status.HTTP_400_BAD_REQUEST)

            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                for chunk in image.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                img = cv2.imread(tmp_path)
                if img is None:
                    return Response({"error": "Не вдалося прочитати зображення"},
                                    status=status.HTTP_400_BAD_REQUEST)
                height, width = img.shape[:2]

                pixel_points = extract_contour(tmp_path)
                gps_contour = project_with_affine(
                    pixel_points, width, height, corners, input_order='latlon'
                )

                # Опциональное построение маршрута
                include_route = request.data.get('route', '').lower() == 'true'
                route_geojson = None
                if include_route:
                    route_coords = match_route_with_osrm(gps_contour, profile)
                    route_geojson = {"type": "LineString", "coordinates": route_coords}

                contour_geojson = {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lat, lon in gps_contour]
                }

                result = {"contour": contour_geojson}
                if route_geojson:
                    result["route"] = route_geojson
                return Response(result, status=status.HTTP_200_OK)

            except ContourExtractionError as e:
                return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            except RouteGenerationError as e:
                return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            finally:
                os.unlink(tmp_path)

        else:
            # ── СТАРЫЙ РЕЖИМ: центр + радиус (обратная совместимость) ───────────────
            try:
                lat = float(request.data.get('lat'))
                lon = float(request.data.get('lon'))
                radius = float(request.data.get('radius', 1000))
            except (TypeError, ValueError):
                return Response({"error": "lat, lon та radius мають бути числами"},
                                status=status.HTTP_400_BAD_REQUEST)

            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                for chunk in image.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                pixel_points = extract_contour(tmp_path)
                gps_points = project_to_gps(pixel_points, lat, lon, radius)
            except ContourExtractionError as e:
                return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            finally:
                os.unlink(tmp_path)

            return Response({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lat, lon in gps_points]
                },
                "properties": {"point_count": len(gps_points)}
            }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def preview_route(self, request):
        """
        Новый эндпоинт для предпросмотра контура и маршрута по дорогам.
        Принимает:
            - image: файл изображения
            - corners: JSON-строка с массивом из 3 (или 4) точек в формате [[lat1,lon1], [lat2,lon2], [lat3,lon3]]
            - profile: 'foot' или 'bike' (по умолчанию 'foot')
        Возвращает:
            {
                "contour": GeoJSON LineString,
                "route": GeoJSON LineString
            }
        """
        image = request.FILES.get('image')
        corners_str = request.data.get('corners')
        profile = request.data.get('profile', 'foot')

        if not image:
            return Response({"error": "Зображення не передано"}, status=status.HTTP_400_BAD_REQUEST)
        if not corners_str:
            return Response({"error": "Параметр 'corners' обов'язковий"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            corners = json.loads(corners_str)
        except json.JSONDecodeError:
            return Response({"error": "Невірний формат JSON у 'corners'"}, status=status.HTTP_400_BAD_REQUEST)

        if len(corners) < 3:
            return Response({"error": "Потрібно мінімум 3 точки у 'corners'"}, status=status.HTTP_400_BAD_REQUEST)

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            for chunk in image.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            img = cv2.imread(tmp_path)
            if img is None:
                return Response({"error": "Не вдалося прочитати зображення"}, status=status.HTTP_400_BAD_REQUEST)
            height, width = img.shape[:2]

            pixel_points = extract_contour(tmp_path)

            # Проецируем контур (corners в формате lat, lon)
            gps_contour = project_with_affine(pixel_points, width, height, corners, input_order='latlon')

            route_coords = match_route_with_osrm(gps_contour, profile)

            contour_geojson = {
                "type": "LineString",
                "coordinates": [[lon, lat] for lat, lon in gps_contour]
            }
            route_geojson = {
                "type": "LineString",
                "coordinates": route_coords
            }

            return Response({
                "contour": contour_geojson,
                "route": route_geojson
            }, status=status.HTTP_200_OK)

        except ContourExtractionError as e:
            return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except RouteGenerationError as e:
            return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except Exception as e:
            return Response({"error": f"Внутрішня помилка: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            os.unlink(tmp_path)