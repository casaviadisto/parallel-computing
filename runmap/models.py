from django.contrib.gis.db import models  # важливо: не зі звичайного django.db
from django.contrib.auth.models import User


class Route(models.Model):
    name = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='routes')

    # Параметри генерації
    start_point = models.PointField(null=True, blank=True)  # GPS-точка старту
    radius = models.FloatField(help_text="Радіус у метрах")
    image = models.ImageField(upload_to='route_images/', null=True, blank=True)

    # Результат генерації
    path = models.LineStringField(null=True, blank=True)  # null, бо заповниться після генерації

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.user.username})"