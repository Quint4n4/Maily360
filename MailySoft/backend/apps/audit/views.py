"""
Vistas de la app audit.

AuditLogListApi — GET /api/v1/audit/logs/
    Lista paginada de la bitácora del tenant activo.
    Solo lectura. Permisos: owner y admin.

Vista delgada: parsea query params, llama al selector, pagina, serializa.
Cero lógica de negocio aquí.
"""

import uuid
from typing import Optional

from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.permissions import AuditLogPermission
from apps.audit.selectors import audit_log_list
from apps.audit.serializers import AuditLogOutputSerializer
from apps.core.views import TenantAPIView


class _AuditLogPagination(PageNumberPagination):
    """Paginación de la bitácora con tope explícito.

    Sin max_page_size, un owner/admin podría pedir ?page_size=1000000 y
    descargar millones de filas (la bitácora retiene 10 años) — vector de DoS.
    """

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class AuditLogListApi(TenantAPIView):
    """GET /api/v1/audit/logs/ — lista paginada de la bitácora del tenant.

    Solo lectura. No acepta POST, PATCH ni DELETE (la bitácora es append-only).

    Query params opcionales:
        actor_id      — UUID del actor a filtrar.
        resource_type — Tipo de recurso ("Patient", "Appointment", ...).
        resource_id   — UUID del recurso específico.
        action        — Tipo de acción (ActionType value).
        date_from     — Fecha de inicio YYYY-MM-DD (inclusive).
        date_to       — Fecha de fin YYYY-MM-DD (inclusive).
        page          — Número de página (PageNumberPagination).
        page_size     — Tamaño de página (respeta PAGE_SIZE máximo de settings).
    """

    permission_classes = [IsAuthenticated, AuditLogPermission]

    def get(self, request: Request) -> Response:
        """Devuelve la bitácora paginada del tenant activo."""
        params = request.query_params

        actor_id: Optional[uuid.UUID] = None
        raw_actor = params.get("actor_id", "")
        if raw_actor:
            try:
                actor_id = uuid.UUID(raw_actor)
            except ValueError:
                pass

        resource_id: Optional[uuid.UUID] = None
        raw_resource_id = params.get("resource_id", "")
        if raw_resource_id:
            try:
                resource_id = uuid.UUID(raw_resource_id)
            except ValueError:
                pass

        resource_type: Optional[str] = params.get("resource_type") or None
        action: Optional[str] = params.get("action") or None

        date_from = None
        date_to = None
        try:
            from datetime import date as _date
            raw_from = params.get("date_from", "")
            if raw_from:
                date_from = _date.fromisoformat(raw_from)
            raw_to = params.get("date_to", "")
            if raw_to:
                date_to = _date.fromisoformat(raw_to)
        except ValueError:
            pass

        qs = audit_log_list(
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            date_from=date_from,
            date_to=date_to,
        )

        paginator = _AuditLogPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = AuditLogOutputSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        # Fallback: nunca servir la bitácora completa sin paginar (puede ser
        # millones de filas). Si la paginación no se configuró, es error de servidor.
        return Response(
            {"detail": "Paginación no disponible."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
