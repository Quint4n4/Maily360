"""
Selectors de la app notificaciones.

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra por tenant activo + excluye soft-deleted.
Además filtramos siempre por recipient=user: una notificación es privada de
su destinatario.

Convención: keyword-only args, nombrado acción+entidad.

REGLA: toda lectura por id usa notification_get; NUNCA Notification.objects.get
inline en la view.
"""

import uuid
from typing import Any

from django.db.models import QuerySet

from apps.notificaciones.models import Notification
from apps.tenancy.models import Tenant


def notification_get(*, notification_id: uuid.UUID, user: Any) -> Notification:
    """Retorna una notificación del usuario por su UUID (filtrada por tenant y recipient).

    Filtra por tenant (TenantManager) Y por recipient=user: una notificación de
    otro tenant o de otro usuario devuelve DoesNotExist directamente en la query
    (no se carga en memoria). La view captura el DoesNotExist y devuelve 404
    (nunca 403 — no se revela existencia). Defensa en profundidad: el service
    notification_mark_read vuelve a verificar recipient.

    Args:
        notification_id: UUID de la notificación.
        user:            Usuario dueño (debe ser el recipient).

    Returns:
        Instancia de Notification con el actor precargado (evita N+1).

    Raises:
        Notification.DoesNotExist: si no existe, es de otro tenant, o no es del usuario.
    """
    return Notification.objects.select_related("actor").get(id=notification_id, recipient=user)


def notification_list_for_user(
    *,
    user: Any,
    tenant: Tenant,
    only_unread: bool = False,
) -> QuerySet[Notification]:
    """Retorna el QuerySet de notificaciones del usuario en el tenant.

    Defensa en profundidad: filtra explícitamente por tenant y recipient, además
    del filtrado automático del TenantManager.

    Args:
        user:        Usuario dueño de las notificaciones.
        tenant:      Tenant (clínica) del contexto activo.
        only_unread: Si True, solo las no leídas (read_at IS NULL).

    Returns:
        QuerySet[Notification] ordenado por -created_at (Meta.ordering).
    """
    qs: QuerySet[Notification] = Notification.objects.select_related("actor").filter(
        tenant=tenant,
        recipient=user,
    )
    if only_unread:
        qs = qs.filter(read_at__isnull=True)
    return qs


def notification_unread_count(*, user: Any, tenant: Tenant) -> int:
    """Retorna cuántas notificaciones no leídas tiene el usuario en el tenant.

    Args:
        user:   Usuario dueño de las notificaciones.
        tenant: Tenant del contexto activo.

    Returns:
        Entero con el número de notificaciones no leídas.
    """
    return Notification.objects.filter(
        tenant=tenant,
        recipient=user,
        read_at__isnull=True,
    ).count()
