import tempfile, os, requests as http_requests
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

from .models import Route
from .serializers import RouteSerializer, UserSerializer
from .services import generate_route, extract_contour, project_to_gps
from .exceptions import RouteGenerationError, ContourExtractionError


class RouteFilter(django_filters.FilterSet):
    """Фільтри для маршрутів."""
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

    # Підключаємо фільтрацію і сортування
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_class = RouteFilter
    search_fields = ['name']
    ordering_fields = ['created_at', 'radius', 'name']
    ordering = ['-created_at']

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if not request.FILES.get('image'):
            return Response(
                {"error": "Зображення є обов'язковим для генерації маршруту"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Початок транзакції: якщо буде помилка, запис у БД не створиться
            with transaction.atomic():
                route = serializer.save()

                image_path = default_storage.path(route.image.name)
                center_lon, center_lat = route.start_point.x, route.start_point.y

                line = generate_route(
                    image_path=image_path,
                    center_lat=center_lat,
                    center_lon=center_lon,
                    radius_meters=route.radius,
                    profile="foot"
                )
                route.path = line
                route.save()

        except RouteGenerationError as e:
            # route.delete() більше не потрібен, транзакція відкотилася сама
            return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        except http_requests.exceptions.RequestException:
            return Response(
                {"error": "Помилка зв'язку із сервісом маршрутизації OSRM. Спробуйте пізніше."},
                status=status.HTTP_502_BAD_GATEWAY
            )

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

        try:
            lat = float(request.data.get('lat'))
            lon = float(request.data.get('lon'))
            radius = float(request.data.get('radius', 1000))
        except (TypeError, ValueError):
            return Response({"error": "lat, lon та radius мають бути числами"}, status=status.HTTP_400_BAD_REQUEST)

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



# Фільтрація:
#
# GET /api/routes/?user=1                          → маршрути конкретного користувача
# GET /api/routes/?radius_min=500&radius_max=2000  → маршрути з радіусом 500-2000м
# GET /api/routes/?created_after=2026-01-01        → маршрути після дати
# GET /api/routes/?search=кіт                      → пошук по назві
#
#
# Сортування:
#
# GET /api/routes/?ordering=radius         → від меншого радіуса до більшого
# GET /api/routes/?ordering=-created_at    → від новіших до старіших
#
#
# Пагінація (працює автоматично):
#
# GET /api/routes/?page=2                  → друга сторінка