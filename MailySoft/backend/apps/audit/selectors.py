"""
Selectors de la app audit — lecturas de la bitácora.

Solo lectura. Toda modificación de AuditLog está prohibida por diseño.
"""

import datetime
import uuid
from typing import Optional

from django.db.models import QuerySet

from apps.audit.models import AuditLog


def audit_log_list(
    *,
    actor_id: Optional[uuid.UUID] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[uuid.UUID] = None,
    action: Optional[str] = None,
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
) -> QuerySet[AuditLog]:
    """Devuelve un QuerySet de AuditLog filtrado por los parámetros opcionales.

    El QuerySet usa el TenantManager (objects), que filtra automáticamente por el
    tenant activo del request. Platform staff consulta vía all_objects directamente.

    El orden es siempre -created_at (el más reciente primero).

    Args:
        actor_id:      UUID del actor a filtrar.
        resource_type: Tipo de recurso ("Patient", "Appointment", etc.).
        resource_id:   UUID del recurso específico.
        action:        Tipo de acción (valor de ActionType).
        date_from:     Fecha de inicio del rango (inclusive).
        date_to:       Fecha de fin del rango (inclusive).

    Returns:
        QuerySet[AuditLog] filtrado y ordenado por -created_at.
    """
    # TenantManager filtra por tenant del request activo.
    qs: QuerySet[AuditLog] = (
        AuditLog.objects.select_related("actor", "tenant").order_by("-created_at")
    )

    if actor_id is not None:
        qs = qs.filter(actor_id=actor_id)

    if resource_type is not None:
        qs = qs.filter(resource_type=resource_type)

    if resource_id is not None:
        qs = qs.filter(resource_id=resource_id)

    if action is not None:
        qs = qs.filter(action=action)

    if date_from is not None:
        qs = qs.filter(created_at__date__gte=date_from)

    if date_to is not None:
        qs = qs.filter(created_at__date__lte=date_to)

    return qs
