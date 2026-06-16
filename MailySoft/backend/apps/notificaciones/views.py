"""
Vistas de la app notificaciones.

Vistas delgadas: parsean el request, llaman un selector o service, devuelven Response.
Cero lógica de negocio aquí. Heredan de TenantAPIView (resolución de tenant + RLS).

Manejo de errores:
  Notification.DoesNotExist → 404 (no 403; no revelar existencia en otro tenant
                              ni de otro usuario).

Decisión de permisos:
  NotificationPermission abre GET/POST a ALL_ROLES porque la notificación es
  PRIVADA de su destinatario: el selector filtra recipient=request.user y el
  service notification_mark_read verifica recipient==user. El permiso HTTP solo
  garantiza autenticación + membresía activa.
"""

import uuid

from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import NotificationPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.notificaciones.models import Notification
from apps.notificaciones.selectors import (
    notification_get,
    notification_list_for_user,
    notification_unread_count,
)
from apps.notificaciones.serializers import NotificationOutputSerializer
from apps.notificaciones.services import (
    notification_mark_all_read,
    notification_mark_read,
)
from apps.tenancy.models import Tenant


def _tenant_or_403(request: Request) -> "tuple[Tenant | None, Response | None]":
    """Obtiene el tenant del contexto o devuelve 403."""
    tenant = get_current_tenant()
    if tenant is None:
        return None, Response(
            {"detail": "No se encontró un tenant activo para este request."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return tenant, None


class NotificationListApi(TenantAPIView):
    """GET /api/v1/notificaciones/  — mis notificaciones (paginadas).

    Query params:
        only_unread: bool — si true, solo las no leídas.
    """

    permission_classes = [IsAuthenticated, NotificationPermission]

    def get(self, request: Request) -> Response:
        """Lista paginada de notificaciones del usuario, más recientes primero."""
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        class _FilterSerializer(serializers.Serializer):
            only_unread = serializers.BooleanField(required=False, default=False)

        filter_s = _FilterSerializer(data=request.query_params)
        filter_s.is_valid(raise_exception=True)

        qs = notification_list_for_user(
            user=request.user,
            tenant=tenant,
            only_unread=filter_s.validated_data["only_unread"],
        )

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                NotificationOutputSerializer(page, many=True).data
            )

        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class NotificationUnreadCountApi(TenantAPIView):
    """GET /api/v1/notificaciones/conteo/  — cuántas no leídas tengo.

    Endpoint barato (un COUNT) pensado para que el frontend lo consulte cada ~30s
    y pinte el badge de la campana sin traer la lista completa.
    """

    permission_classes = [IsAuthenticated, NotificationPermission]

    def get(self, request: Request) -> Response:
        """Devuelve {"unread": N}."""
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        unread = notification_unread_count(user=request.user, tenant=tenant)
        return Response({"unread": unread})


class NotificationMarkAllReadApi(TenantAPIView):
    """POST /api/v1/notificaciones/leidas/  — marcar TODAS como leídas."""

    permission_classes = [IsAuthenticated, NotificationPermission]

    def post(self, request: Request) -> Response:
        """Marca todas las no leídas del usuario como leídas. Devuelve {"updated": N}."""
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        updated = notification_mark_all_read(tenant=tenant, user=request.user)
        return Response({"updated": updated})


class NotificationMarkReadApi(TenantAPIView):
    """POST /api/v1/notificaciones/<notification_id>/leida/  — marcar UNA como leída."""

    permission_classes = [IsAuthenticated, NotificationPermission]

    def post(self, request: Request, notification_id: uuid.UUID) -> Response:
        """Marca la notificación como leída (idempotente)."""
        tenant, error = _tenant_or_403(request)
        if error is not None:
            return error

        try:
            notification = notification_get(notification_id=notification_id, user=request.user)
            notification = notification_mark_read(notification=notification, user=request.user)
        except Notification.DoesNotExist:
            return Response(
                {"detail": "Notificación no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(NotificationOutputSerializer(notification).data)
