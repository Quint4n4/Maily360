"""
URLs del panel interno de plataforma.

Se incluyen en config/urls.py bajo el prefijo api/v1/plataforma/.

Rutas:
    plataforma/metricas/                      GET  PlatformMetricasApi
    plataforma/clinicas/                      GET  PlatformClinicasListApi   (super_admin, sales, engineering)
    plataforma/clinicas/                      POST PlatformClinicasListApi   (super_admin, sales)
    plataforma/clinicas/<tenant_id>/          GET  PlatformClinicaDetailApi  (super_admin, sales, engineering)
    plataforma/clinicas/<tenant_id>/estado/   POST PlatformClinicaEstadoApi  (super_admin, sales)
    plataforma/clinicas/<tenant_id>/suscripcion/ POST PlatformClinicaSuscripcionApi (super_admin, sales)
    plataforma/usuarios/                      GET  PlatformUsuariosListApi   (super_admin)
    plataforma/auditoria/                     GET  PlatformAuditoriaListApi  (super_admin, engineering)
    plataforma/sistema/                       GET  PlatformSistemaApi        (super_admin, engineering)
    plataforma/planes/                        GET  PlatformPlanesListApi     (super_admin, sales)
    plataforma/suscripciones/                 GET  PlatformSuscripcionesListApi   (super_admin, sales)
    plataforma/suscripciones/resumen/         GET  PlatformSuscripcionesResumenApi (super_admin, sales)
"""

from django.urls import path

from apps.plataforma.views import (
    PlatformAuditoriaListApi,
    PlatformClinicaDetailApi,
    PlatformClinicaEstadoApi,
    PlatformClinicasListApi,
    PlatformClinicaSuscripcionApi,
    PlatformMetricasApi,
    PlatformPlanesListApi,
    PlatformSistemaApi,
    PlatformSuscripcionesListApi,
    PlatformSuscripcionesResumenApi,
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
        "plataforma/clinicas/<uuid:tenant_id>/suscripcion/",
        PlatformClinicaSuscripcionApi.as_view(),
        name="platform-clinica-suscripcion",
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
    path(
        "plataforma/planes/",
        PlatformPlanesListApi.as_view(),
        name="platform-planes-list",
    ),
    # /suscripciones/resumen/ ANTES que el patrón sin sufijo — Django prueba
    # los path() en orden y "resumen/" no colisiona con la lista (no lleva
    # parámetro), pero se declara primero por claridad/consistencia con el
    # patrón de rutas fijas-antes-que-dinámicas del resto del proyecto.
    path(
        "plataforma/suscripciones/resumen/",
        PlatformSuscripcionesResumenApi.as_view(),
        name="platform-suscripciones-resumen",
    ),
    path(
        "plataforma/suscripciones/",
        PlatformSuscripcionesListApi.as_view(),
        name="platform-suscripciones-list",
    ),
]
