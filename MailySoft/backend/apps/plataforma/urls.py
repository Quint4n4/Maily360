"""
URLs del panel interno de plataforma.

Se incluyen en config/urls.py bajo el prefijo api/v1/plataforma/.

Rutas:
    plataforma/metricas/                      GET  PlatformMetricasApi
    plataforma/clinicas/                      GET  PlatformClinicasListApi   (super_admin, sales, engineering)
    plataforma/clinicas/                      POST PlatformClinicasListApi   (super_admin, sales)
    plataforma/clinicas/<tenant_id>/          GET  PlatformClinicaDetailApi  (super_admin, sales, engineering)
    plataforma/clinicas/<tenant_id>/estado/   POST PlatformClinicaEstadoApi  (super_admin, sales)
    plataforma/usuarios/                      GET  PlatformUsuariosListApi   (super_admin)
    plataforma/auditoria/                     GET  PlatformAuditoriaListApi  (super_admin, engineering)
    plataforma/sistema/                       GET  PlatformSistemaApi        (super_admin, engineering)
"""

from django.urls import path

from apps.plataforma.views import (
    PlatformAuditoriaListApi,
    PlatformClinicaDetailApi,
    PlatformClinicaEstadoApi,
    PlatformClinicasListApi,
    PlatformMetricasApi,
    PlatformSistemaApi,
    PlatformUsuariosListApi,
)

urlpatterns = [
    path(
        "plataforma/metricas/",
        PlatformMetricasApi.as_view(),
        name="platform-metricas",
    ),
    path(
        "plataforma/clinicas/",
        PlatformClinicasListApi.as_view(),
        name="platform-clinicas-list",
    ),
    path(
        "plataforma/clinicas/<uuid:tenant_id>/",
        PlatformClinicaDetailApi.as_view(),
        name="platform-clinica-detail",
    ),
    path(
        "plataforma/clinicas/<uuid:tenant_id>/estado/",
        PlatformClinicaEstadoApi.as_view(),
        name="platform-clinica-estado",
    ),
    path(
        "plataforma/usuarios/",
        PlatformUsuariosListApi.as_view(),
        name="platform-usuarios-list",
    ),
    path(
        "plataforma/auditoria/",
        PlatformAuditoriaListApi.as_view(),
        name="platform-auditoria-list",
    ),
    path(
        "plataforma/sistema/",
        PlatformSistemaApi.as_view(),
        name="platform-sistema",
    ),
]
