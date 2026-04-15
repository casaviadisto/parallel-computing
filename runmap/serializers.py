# runmap/serializers.py

from rest_framework_gis.serializers import GeoFeatureModelSerializer
from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from .models import Route


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']


class RouteSerializer(GeoFeatureModelSerializer):
    lat = serializers.FloatField(write_only=True, required=False)
    lon = serializers.FloatField(write_only=True, required=False)
    radius = serializers.FloatField(write_only=True, required=False, default=1000.0)

    class Meta:
        model = Route
        geo_field = 'path'
        fields = ['id', 'name', 'user', 'lat', 'lon', 'start_point',
                  'radius', 'image', 'path', 'created_at']
        read_only_fields = ['path', 'created_at', 'start_point']

    def create(self, validated_data):
        lat = validated_data.pop('lat', None)
        lon = validated_data.pop('lon', None)
        radius = validated_data.pop('radius', 1000.0)

        # Если переданы lat/lon – создаём start_point
        if lat is not None and lon is not None:
            validated_data['start_point'] = Point(lon, lat, srid=4326)
        else:
            # Иначе start_point будет заполнен позже (при наличии corners)
            validated_data['start_point'] = None

        validated_data['radius'] = radius
        return super().create(validated_data)