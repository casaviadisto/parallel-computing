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
    # Приймаємо lat/lon як окремі числа
    lat = serializers.FloatField(write_only=True)
    lon = serializers.FloatField(write_only=True)

    class Meta:
        model = Route
        geo_field = 'path'
        fields = ['id', 'name', 'user', 'lat', 'lon', 'start_point',
                  'radius', 'image', 'path', 'created_at']
        read_only_fields = ['path', 'created_at', 'start_point']

    def create(self, validated_data):
        lat = validated_data.pop('lat')
        lon = validated_data.pop('lon')
        validated_data['start_point'] = Point(lon, lat, srid=4326)
        return super().create(validated_data)