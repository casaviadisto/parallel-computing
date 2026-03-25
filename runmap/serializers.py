from rest_framework import serializers


class UserSerializer(serializers.Serializer):
    # Serializer (не ModelSerializer) — валідує вручну без прив'язки до моделі
    id       = serializers.IntegerField(read_only=True)
    username = serializers.CharField(max_length=150)
    email    = serializers.EmailField(required=False, default="")


class RouteSerializer(serializers.Serializer):
    id         = serializers.IntegerField(read_only=True)
    name       = serializers.CharField(max_length=255)
    user_id    = serializers.IntegerField()
    lat        = serializers.FloatField(write_only=True)
    lon        = serializers.FloatField(write_only=True)
    start_lat  = serializers.FloatField(read_only=True)
    start_lon  = serializers.FloatField(read_only=True)
    radius     = serializers.FloatField()
    image      = serializers.ImageField(required=False)
    path       = serializers.ListField(read_only=True, required=False)
    created_at = serializers.CharField(read_only=True)

    def validate_user_id(self, value):
        # Перевіряємо що користувач існує
        from .models import get_user_by_id
        if not get_user_by_id(value):
            raise serializers.ValidationError(f"Користувач з id={value} не існує")
        return value