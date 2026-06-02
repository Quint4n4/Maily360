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
    AgendaConfigApi,
    AppointmentChangeStatusApi,
    AppointmentDetailApi,
    AppointmentListCreateApi,
    AppointmentRescheduleApi,
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
]
