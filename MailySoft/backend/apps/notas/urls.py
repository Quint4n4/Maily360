"""
URLs de la app notas.

Se incluyen en config/urls.py bajo el prefijo api/v1/.

Rutas:
    notas/                              NoteListCreateApi      GET list + POST create
    notas/<note_id>/                    NoteDetailApi          PATCH + DELETE
    notas/<note_id>/done/              NoteToggleDoneApi      POST toggle
    notas/recordatorios/               NoteRemindersApi       GET by range

ORDEN IMPORTANTE: 'recordatorios/' debe ir ANTES de '<note_id>/' para que
Django no trate "recordatorios" como un UUID y devuelva 404.
"""

from django.urls import path

from apps.notas.views import (
    NoteDetailApi,
    NoteListCreateApi,
    NoteRemindersApi,
    NoteToggleDoneApi,
)

urlpatterns = [
    # Recordatorios por rango — DEBE ir antes de <note_id>/ para evitar colisión
    path(
        "notas/recordatorios/",
        NoteRemindersApi.as_view(),
        name="note-reminders",
    ),
    # Lista + creación
    path(
        "notas/",
        NoteListCreateApi.as_view(),
        name="note-list-create",
    ),
    # Detalle (PATCH + DELETE)
    path(
        "notas/<uuid:note_id>/",
        NoteDetailApi.as_view(),
        name="note-detail",
    ),
    # Toggle done
    path(
        "notas/<uuid:note_id>/done/",
        NoteToggleDoneApi.as_view(),
        name="note-toggle-done",
    ),
]
