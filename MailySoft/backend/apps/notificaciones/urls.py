"""
URLs de la app notificaciones.

Se incluyen en config/urls.py bajo el prefijo api/v1/.

Rutas:
    notificaciones/                       NotificationListApi          GET list
    notificaciones/conteo/                NotificationUnreadCountApi   GET unread count
    notificaciones/leidas/                NotificationMarkAllReadApi   POST mark all read
    notificaciones/<id>/leida/            NotificationMarkReadApi      POST mark one read

ORDEN: las rutas estáticas ('conteo/', 'leidas/') van ANTES de la que captura
<uuid:notification_id> para evitar cualquier colisión de resolución.
"""

from django.urls import path

from apps.notificaciones.views import (
    NotificationListApi,
    NotificationMarkAllReadApi,
    NotificationMarkReadApi,
    NotificationUnreadCountApi,
)

urlpatterns = [
    path(
        "notificaciones/conteo/",
        NotificationUnreadCountApi.as_view(),
        name="notification-unread-count",
    ),
    path(
        "notificaciones/leidas/",
        NotificationMarkAllReadApi.as_view(),
        name="notification-mark-all-read",
    ),
    path(
        "notificaciones/",
        NotificationListApi.as_view(),
        name="notification-list",
    ),
    path(
        "notificaciones/<uuid:notification_id>/leida/",
        NotificationMarkReadApi.as_view(),
        name="notification-mark-read",
    ),
]
