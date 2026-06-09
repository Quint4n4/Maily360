"""
URLs de la app agenda.

Se incluyen en config/urls.py bajo el prefijo api/v1/.

Rutas:
    agenda/citas/                                   AppointmentListCreateApi
    agenda/citas/<appointment_id>/                  AppointmentDetailApi
    agenda/citas/<appointment_id>/estado/           AppointmentChangeStatusApi
    agenda/citas/<appointment_id>/reagendar/        AppointmentRescheduleApi
    agenda/config/                                  AgendaConfigApi
"""

from django.urls import path

from apps.agenda.views import (
    AgendaBlockDetailApi,
    AgendaBlockListCreateApi,
    AgendaConfigApi,
    AppointmentChangeStatusApi,
    AppointmentDetailApi,
    AppointmentListCreateApi,
    AppointmentRescheduleApi,
    AppointmentTypeDetailApi,
    AppointmentTypeListCreateApi,
)

urlpatterns = [
    # Citas
    path(
        "agenda/citas/",
        AppointmentListCreateApi.as_view(),
        name="appointment-list-create",
    ),
    path(
        "agenda/citas/<uuid:appointment_id>/",
        AppointmentDetailApi.as_view(),
        name="appointment-detail",
    ),
    # Máquina de estados — ÚNICO endpoint para cambiar status
    path(
        "agenda/citas/<uuid:appointment_id>/estado/",
        AppointmentChangeStatusApi.as_view(),
        name="appointment-change-status",
    ),
    # Reagendamiento (horario)
    path(
        "agenda/citas/<uuid:appointment_id>/reagendar/",
        AppointmentRescheduleApi.as_view(),
        name="appointment-reschedule",
    ),
    # Configuración de agenda de la clínica
    path(
        "agenda/config/",
        AgendaConfigApi.as_view(),
        name="agenda-config",
    ),
    # Tipos de cita (catálogo configurable con color)
    path(
        "agenda/tipos-cita/",
        AppointmentTypeListCreateApi.as_view(),
        name="appointment-type-list-create",
    ),
    path(
        "agenda/tipos-cita/<uuid:type_id>/",
        AppointmentTypeDetailApi.as_view(),
        name="appointment-type-detail",
    ),
    # Eventos de agenda (reuniones / bloqueos)
    path(
        "agenda/eventos/",
        AgendaBlockListCreateApi.as_view(),
        name="agenda-block-list-create",
    ),
    path(
        "agenda/eventos/<uuid:block_id>/",
        AgendaBlockDetailApi.as_view(),
        name="agenda-block-detail",
    ),
]
