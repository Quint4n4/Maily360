"""
URLs raíz de Maily Soft.

Los módulos de cada app registran sus propias URLs en apps/<dominio>/urls.py
y se incluyen aquí con prefijo /api/v1/.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path  # noqa: F401  (include se usa al sumar apps)
from rest_framework_simplejwt.views import TokenVerifyView

from apps.authn.views import CookieTokenRefreshView, LogoutView, MailyTokenObtainPairView

urlpatterns = [
    # Admin de Django
    path("admin/", admin.site.urls),
    # Auth — patrón híbrido: access en JSON, refresh en cookie httpOnly.
    # MailyTokenObtainPairView: login con auditoría + setea cookie maily_refresh.
    # CookieTokenRefreshView: rota el access leyendo el refresh de cookie (no del body).
    # LogoutView: invalida el refresh con blacklist + borra la cookie.
    path("api/v1/auth/login/", MailyTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/refresh/", CookieTokenRefreshView.as_view(), name="token_refresh"),
    path("api/v1/auth/logout/", LogoutView.as_view(), name="token_logout"),
    path("api/v1/auth/verify/", TokenVerifyView.as_view(), name="token_verify"),
    # Apps del dominio (se registran aquí conforme se agregan)
    # path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.authn.urls")),
    path("api/v1/", include("apps.tenancy.urls")),
    path("api/v1/", include("apps.pacientes.urls")),
    path("api/v1/", include("apps.personal.urls")),
    path("api/v1/", include("apps.agenda.urls")),
    path("api/v1/", include("apps.finanzas.urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/", include("apps.notas.urls")),
    path("api/v1/", include("apps.notificaciones.urls")),
    path("api/v1/", include("apps.expediente.urls")),
    # Mi Consultorio — configuración de la clínica (Fase B base)
    path("api/v1/", include("apps.clinica.urls")),
    # Panel interno de plataforma (cross-tenant, equipo Maily)
    path("api/v1/", include("apps.plataforma.urls")),
    # Recetas médicas (Fase B1)
    path("api/v1/", include("apps.recetas.urls")),
]

# FIX-8: exponer la documentación OpenAPI SOLO en desarrollo.
# En producción (DEBUG=False) estos endpoints NO están disponibles,
# evitando la enumeración de la API por actores maliciosos.
if settings.DEBUG:
    from drf_spectacular.views import (
        SpectacularAPIView,
        SpectacularRedocView,
        SpectacularSwaggerView,
    )

    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
        path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    ]

    # Servir archivos subidos (avatares) en desarrollo. En producción los sirve
    # el almacenamiento (S3) o el servidor web, NUNCA Django.
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
