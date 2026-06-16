"""
URLs de la app agenda.

Se incluyen en config/urls.py bajo el prefijo api/v1/.

Rutas:
    agenda/citas/                                          AppointmentListCreateApi
    agenda/citas/<appointment_id>/                         AppointmentDetailApi
    agenda/citas/<appointment_id>/estado/                  AppointmentChangeStatusApi
    agenda/citas/<appointment_id>/reagendar/               AppointmentRescheduleApi
    agenda/config/                                         AgendaConfigApi
    agenda/citas/<appointment_id>/notas/                   AppointmentNotesApi
    agenda/eventos/<block_id>/notas/                       AgendaBlockNotesApi
    agenda/notas/<note_id>/                                AgendaItemNoteDetailApi
"""

from django.urls import path

from apps.agenda.views import (
    AgendaBlockDetailApi,
    AgendaBlockListCreateApi,
    AgendaBlockNotesApi,
    AgendaConfigApi,
    AgendaDisponibilidadApi,
    AgendaItemNoteDetailApi,
    AppointmentChangeStatusApi,
    AppointmentDetailApi,
    AppointmentListCreateApi,
    AppointmentNotesApi,
    AppointmentReactivateApi,
    AppointmentRescheduleApi,
    AppointmentSeriesCreateApi,
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
    # Serie (multi-cita) — antes de <uuid> para que "serie" no se interprete como id.
    path(
        "agenda/citas/serie/",
        AppointmentSeriesCreateApi.as_view(),
        name="appointment-series-create",
    ),
    # Disponibilidad (horarios ocupados) — para armar series sin choques.
    path(
        "agenda/disponibilidad/",
        AgendaDisponibilidadApi.as_view(),
        name="agenda-disponibilidad",
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
    # Reactivar una cita cancelada (mismo horario)
    path(
        "agenda/citas/<uuid:appointment_id>/reactivar/",
        AppointmentReactivateApi.as_view(),
        name="appointment-reactivate",
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
    # Notas colaborativas del hilo de citas y eventos (Fase 5)
    path(
        "agenda/citas/<uuid:appointment_id>/notas/",
        AppointmentNotesApi.as_view(),
        name="appointment-notes",
    ),
    path(
        "agenda/eventos/<uuid:block_id>/notas/",
        AgendaBlockNotesApi.as_view(),
        name="agenda-block-notes",
    ),
    path(
        "agenda/notas/<uuid:note_id>/",
        AgendaItemNoteDetailApi.as_view(),
        name="agenda-item-note-detail",
    ),
]
