from django.contrib import admin
from .models import Route


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    # Поля, які будуть відображатися у вигляді таблиці
    list_display = ('id', 'name', 'user', 'radius', 'created_at')

    # Панель фільтрів збоку
    list_filter = ('user', 'created_at')

    # Поле пошуку
    search_fields = ('name',)

    # Сортування за замовчуванням
    ordering = ('-created_at',)