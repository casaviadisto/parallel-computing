from rest_framework import viewsets, status
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from .models import Route
from .serializers import RouteSerializer, UserSerializer
from .services import generate_route, extract_contour, project_to_gps
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
import tempfile, os, requests as http_requests


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            # 422 — дані отримані, але семантично некоректні
            # (наприклад, username вже існує)
            return Response(serializer.errors, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        try:
            return super().update(request, *args, **kwargs)
        except Exception:
            # 409 — конфлікт (наприклад, спроба встановити вже зайнятий username)
            return Response(
                {"error": "Конфлікт даних при оновленні користувача"},
                status=status.HTTP_409_CONFLICT
            )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()  # автоматично повертає 404 якщо не знайдено
        self.perform_destroy(instance)
        # 204 — успішно видалено, тіло відповіді порожнє
        return Response(status=status.HTTP_204_NO_CONTENT)


class RouteViewSet(viewsets.ModelViewSet):
    queryset = Route.objects.all()
    serializer_class = RouteSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            # 422 — запит синтаксично правильний, але дані не валідні
            return Response(serializer.errors, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if not request.FILES.get('image'):
            # 400 — відсутнє обов'язкове поле
            return Response(
                {"error": "Зображення є обов'язковим для генерації маршруту"},
                status=status.HTTP_400_BAD_REQUEST
            )

        route = serializer.save()

        try:
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

        except ValueError as e:
            route.delete()
            # 422 — дані валідні, але обробка неможлива
            # (наприклад, контур не знайдено на зображенні)
            return Response(
                {"error": str(e)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        except http_requests.exceptions.Timeout:
            route.delete()
            # 504 — зовнішній сервіс (OSRM) не відповів вчасно
            return Response(
                {"error": "Сервіс маршрутизації OSRM не відповідає. Спробуйте пізніше."},
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )

        except http_requests.exceptions.HTTPError as e:
            route.delete()
            # 502 — OSRM повернув помилку
            return Response(
                {"error": f"Помилка сервісу маршрутизації: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY
            )

        except Exception as e:
            route.delete()
            # 500 — непередбачена внутрішня помилка
            return Response(
                {"error": f"Внутрішня помилка сервера: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 201 — ресурс успішно створено
        return Response(self.get_serializer(route).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()  # 404 якщо не знайдено — автоматично
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def preview_contour(self, request):
        image = request.FILES.get('image')
        if not image:
            return Response(
                {"error": "Зображення не передано"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            lat = float(request.data.get('lat'))
            lon = float(request.data.get('lon'))
            radius = float(request.data.get('radius', 1000))
        except (TypeError, ValueError):
            return Response(
                {"error": "lat, lon та radius мають бути числами"},
                status=status.HTTP_400_BAD_REQUEST
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            for chunk in image.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            pixel_points = extract_contour(tmp_path)
            gps_points = project_to_gps(pixel_points, lat, lon, radius)
        except ValueError as e:
            # 422 — зображення отримане, але контур не знайдено
            return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        finally:
            os.unlink(tmp_path)

        # 200 — успішна відповідь (дані повернуто, нічого не створено)
        return Response({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lat, lon in gps_points]
            },
            "properties": {"point_count": len(gps_points)}
        }, status=status.HTTP_200_OK)