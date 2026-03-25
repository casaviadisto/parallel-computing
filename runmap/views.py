from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import tempfile, os

from .serializers import UserSerializer, RouteSerializer
from .models import (
    get_all_users, get_user_by_id, create_user, update_user, delete_user,
    get_all_routes, get_route_by_id, create_route, update_route_path, delete_route
)
from .services import generate_route, extract_contour, project_to_gps


# ── Користувачі ───────────────────────────────────────────────────────────────

class UserListView(APIView):
    """GET /api/users/ та POST /api/users/"""

    def get(self, request):
        users = get_all_users()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = UserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = create_user(
            username=serializer.validated_data['username'],
            email=serializer.validated_data.get('email', '')
        )
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    """GET /api/users/{id}/, PATCH /api/users/{id}/, DELETE /api/users/{id}/"""

    def get(self, request, pk):
        user = get_user_by_id(pk)
        if not user:
            return Response({"error": "Користувача не знайдено"}, status=404)
        return Response(UserSerializer(user).data)

    def patch(self, request, pk):
        user = get_user_by_id(pk)
        if not user:
            return Response({"error": "Користувача не знайдено"}, status=404)
        serializer = UserSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = update_user(pk, serializer.validated_data)
        return Response(UserSerializer(updated).data)

    def delete(self, request, pk):
        if not delete_user(pk):
            return Response({"error": "Користувача не знайдено"}, status=404)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Маршрути ──────────────────────────────────────────────────────────────────

class RouteListView(APIView):
    """GET /api/routes/ та POST /api/routes/"""
    parser_classes = [MultiPartParser]

    def get(self, request):
        routes = get_all_routes()
        serializer = RouteSerializer(routes, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = RouteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # Зберігаємо зображення на диск (для OpenCV)
        image_path = None
        if 'image' in request.FILES:
            image_file = request.FILES['image']
            save_path = f"route_images/{image_file.name}"
            default_storage.save(save_path, ContentFile(image_file.read()))
            image_path = default_storage.path(save_path)

        # Створюємо запис у пам'яті
        route = create_route(
            name=d['name'],
            user_id=d['user_id'],
            start_lat=d['lat'],
            start_lon=d['lon'],
            radius=d['radius'],
            image_path=image_path,
        )

        # Генеруємо маршрут
        try:
            coordinates = generate_route(
                image_path=image_path,
                center_lat=d['lat'],
                center_lon=d['lon'],
                radius_meters=d['radius'],
                profile="foot"
            )
            update_route_path(route['id'], coordinates)
            route['path'] = coordinates
        except Exception as e:
            delete_route(route['id'])
            return Response(
                {"error": f"Помилка генерації: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(RouteSerializer(route).data, status=status.HTTP_201_CREATED)


class RouteDetailView(APIView):
    """GET /api/routes/{id}/, DELETE /api/routes/{id}/"""

    def get(self, request, pk):
        route = get_route_by_id(pk)
        if not route:
            return Response({"error": "Маршрут не знайдено"}, status=404)
        return Response(RouteSerializer(route).data)

    def delete(self, request, pk):
        if not delete_route(pk):
            return Response({"error": "Маршрут не знайдено"}, status=404)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PreviewContourView(APIView):
    """POST /api/routes/preview_contour/"""
    parser_classes = [MultiPartParser]

    def post(self, request):
        image = request.FILES.get('image')
        lat = float(request.data.get('lat'))
        lon = float(request.data.get('lon'))
        radius = float(request.data.get('radius', 1000))

        if not image:
            return Response({"error": "Зображення не передано"}, status=400)

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            for chunk in image.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            pixel_points = extract_contour(tmp_path)
            gps_points = project_to_gps(pixel_points, lat, lon, radius)
        finally:
            os.unlink(tmp_path)

        return Response({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lat, lon in gps_points]
            },
            "properties": {"point_count": len(gps_points)}
        })


class RouteGeoJSONView(APIView):
    """GET /api/routes/{id}/geojson/"""

    def get(self, request, pk):
        route = get_route_by_id(pk)
        if not route:
            return Response({"error": "Маршрут не знайдено"}, status=404)

        # Convert path to GeoJSON format
        coordinates = route.get('path', [])
        if not coordinates or not isinstance(coordinates[0], (list, tuple)):
            coordinates = []

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coordinates
                    },
                    "properties": {
                        "id": route['id'],
                        "name": route['name'],
                        "user_id": route['user_id'],
                        "radius": route['radius'],
                        "created_at": str(route['created_at'])
                    }
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [route['start_lon'], route['start_lat']]
                    },
                    "properties": {
                        "name": f"{route['name']} (Start)",
                        "type": "start_point"
                    }
                }
            ]
        }

        return Response(geojson)
