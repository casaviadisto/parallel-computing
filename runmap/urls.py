from django.urls import path
from .views import (
    UserListView, UserDetailView,
    RouteListView, RouteDetailView,
    PreviewContourView, RouteGeoJSONView
)

urlpatterns = [
    path('users/', UserListView.as_view()),
    path('users/<int:pk>/', UserDetailView.as_view()),
    path('routes/', RouteListView.as_view()),
    path('routes/<int:pk>/', RouteDetailView.as_view()),
    path('routes/preview_contour/', PreviewContourView.as_view()),
    path('routes/<int:pk>/geojson/', RouteGeoJSONView.as_view()),

]
