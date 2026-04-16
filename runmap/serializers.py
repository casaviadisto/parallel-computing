# runmap/serializers.py

from rest_framework_gis.serializers import GeoFeatureModelSerializer
from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from .models import Route


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password']
        )
        return user

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

        # Якщо передани lat/lon – створюєм start_point
        if lat is not None and lon is not None:
            validated_data['start_point'] = Point(lon, lat, srid=4326)
        else:
            # Інакше start_point буде заповнений пізніше (при наявності corners)
            validated_data['start_point'] = None

        validated_data['radius'] = radius
        return super().create(validated_data)