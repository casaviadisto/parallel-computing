from rest_framework.routers import DefaultRouter
from .views import RouteViewSet, UserViewSet

router = DefaultRouter()
router.register(r'routes', RouteViewSet, basename='route')
router.register(r'users', UserViewSet, basename='user')

urlpatterns = router.urls