"""
URLs del panel interno de plataforma.

Se incluyen en config/urls.py bajo el prefijo api/v1/plataforma/.

Rutas (roles permitidos entre paréntesis; SA=super_admin, sales, eng=engineering):
    plataforma/metricas/                           GET   PlatformMetricasApi
    plataforma/clinicas/                           GET   PlatformClinicasListApi   (SA, sales, eng)
    plataforma/clinicas/                           POST  PlatformClinicasListApi   (SA, sales)
    plataforma/clinicas/<tenant_id>/                GET   PlatformClinicaDetailApi  (SA, sales, eng)
    plataforma/clinicas/<tenant_id>/estado/         POST  PlatformClinicaEstadoApi  (SA, sales)
    plataforma/clinicas/<tenant_id>/suscripcion/    POST  PlatformClinicaSuscripcionApi (SA, sales)
    plataforma/usuarios/                           GET   PlatformUsuariosListApi   (SA)
    plataforma/usuarios/                           POST  PlatformUsuariosListApi   (SA)
    plataforma/usuarios/<user_id>/                  PATCH PlatformStaffDetailApi   (SA)
    plataforma/usuarios/<user_id>/reset-password/   POST  PlatformStaffPasswordResetApi (SA)
    plataforma/auditoria/                          GET   PlatformAuditoriaListApi  (SA, eng)
    plataforma/sistema/                            GET   PlatformSistemaApi        (SA, eng)
    plataforma/planes/                             GET   PlatformPlanesListApi     (SA, sales)
    plataforma/planes/                             POST  PlatformPlanesListApi     (SA)
    plataforma/planes/<plan_id>/                    PATCH PlatformPlanDetailApi    (SA)
    plataforma/suscripciones/                      GET   PlatformSuscripcionesListApi   (SA, sales)
    plataforma/suscripciones/resumen/              GET   PlatformSuscripcionesResumenApi (SA, sales)
"""

from django.urls import path

from apps.plataforma.views import (
    PlatformAuditoriaListApi,
    PlatformClinicaDetailApi,
    PlatformClinicaEstadoApi,
    PlatformClinicasListApi,
    PlatformClinicaSuscripcionApi,
    PlatformMetricasApi,
    PlatformPlanDetailApi,
    PlatformPlanesListApi,
    PlatformSistemaApi,
    PlatformStaffDetailApi,
    PlatformStaffPasswordResetApi,
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
        "plataforma/usuarios/<uuid:user_id>/",
        PlatformStaffDetailApi.as_view(),
        name="platform-staff-detail",
    ),
    path(
        "plataforma/usuarios/<uuid:user_id>/reset-password/",
        PlatformStaffPasswordResetApi.as_view(),
        name="platform-staff-password-reset",
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
    path(
        "plataforma/planes/<uuid:plan_id>/",
        PlatformPlanDetailApi.as_view(),
        name="platform-plan-detail",
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
