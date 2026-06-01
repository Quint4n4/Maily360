"""
URLs raíz de Maily Soft.

Los módulos de cada app registran sus propias URLs en apps/<dominio>/urls.py
y se incluyen aquí con prefijo /api/v1/.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    # Admin de Django
    path("admin/", admin.site.urls),
    # OpenAPI schema y docs (solo en DEBUG — ver producción: restringir con permiso)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Auth (SimpleJWT)
    path("api/v1/auth/", include("rest_framework_simplejwt.urls")),
    # Apps del dominio (se registran aquí conforme se agregan)
    # path("api/v1/", include("apps.core.urls")),
]
