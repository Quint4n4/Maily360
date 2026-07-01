"""
URLs raíz de Maily Soft.

Los módulos de cada app registran sus propias URLs en apps/<dominio>/urls.py
y se incluyen aquí con prefijo /api/v1/.
"""

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path  # noqa: F401  (include se usa al sumar apps)
from rest_framework_simplejwt.views import TokenVerifyView

from apps.authn.views import CookieTokenRefreshView, LogoutView, MailyTokenObtainPairView


def healthz(_request) -> HttpResponse:
    """Sonda de salud para el healthcheck de Railway (sin DB, exenta de SSL redirect)."""
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    # Sonda de salud (Railway) — respuesta simple 200.
    path("healthz/", healthz, name="healthz"),
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
    # PDFs asíncronos — endpoints compartidos de estado/descarga
    path("api/v1/", include("apps.pdfs.urls")),
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
    # el almacenamiento (Cloudinary/S3), NUNCA Django.
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


# ---------------------------------------------------------------------------
# SPA (producción): el backend sirve el frontend React en el MISMO origen.
# Cualquier ruta que NO sea /api, /admin, /static o /media devuelve index.html
# para que React Router maneje el enrutado del lado del cliente. Solo se activa
# cuando el build del frontend fue copiado (settings.FRONTEND_DIST_DIR existe),
# es decir en el contenedor de Railway; en desarrollo no hace nada.
# ---------------------------------------------------------------------------
import os  # noqa: E402

if os.path.isdir(settings.FRONTEND_DIST_DIR):
    from django.urls import re_path  # noqa: E402
    from django.views.generic import TemplateView  # noqa: E402

    urlpatterns += [
        re_path(
            r"^(?!api/|admin/|static/|media/).*$",
            TemplateView.as_view(template_name="index.html"),
            name="spa",
        ),
    ]
