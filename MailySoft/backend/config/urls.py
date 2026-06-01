"""
URLs raíz de Maily Soft.

Los módulos de cada app registran sus propias URLs en apps/<dominio>/urls.py
y se incluyen aquí con prefijo /api/v1/.
"""

from django.contrib import admin
from django.urls import include, path  # noqa: F401  (include se usa al sumar apps)
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

urlpatterns = [
    # Admin de Django
    path("admin/", admin.site.urls),
    # OpenAPI schema y docs (solo en DEBUG — ver producción: restringir con permiso)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Auth (SimpleJWT) — endpoints explícitos
    path("api/v1/auth/login/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/v1/auth/verify/", TokenVerifyView.as_view(), name="token_verify"),
    # Apps del dominio (se registran aquí conforme se agregan)
    # path("api/v1/", include("apps.core.urls")),
]
