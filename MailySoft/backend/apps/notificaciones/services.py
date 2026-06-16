"""
Services de la app notificaciones.

Toda escritura de notificaciones pasa por aquí. Las vistas son delgadas.

Convención: keyword-only args, nombrado acción+entidad.

API pública (la consumen otras apps en el reparto):
    notification_fanout      — crea N notificaciones (una por destinatario).
    notification_create      — crea UNA notificación (atajo de fanout).

API de lectura/estado (la consumen las vistas de esta app):
    notification_mark_read       — marca una como leída (idempotente).
    notification_mark_all_read   — marca todas las del usuario como leídas.

Reglas críticas:
  1. Nunca te notificas a ti mismo: el `actor` se excluye del reparto.
  2. Se deduplican destinatarios repetidos (un usuario recibe máx. 1 aviso por evento).
  3. Marcar como leída solo lo puede hacer el destinatario (recipient).
  4. Marcar como leída es idempotente: si ya estaba leída, no cambia read_at.
"""

import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.notificaciones.models import Notification
from apps.tenancy.models import Tenant

logger = logging.getLogger("apps.notificaciones.services")


# ---------------------------------------------------------------------------
# Reparto / creación
# ---------------------------------------------------------------------------


@transaction.atomic
def notification_fanout(
    *,
    tenant: Tenant,
    recipients: Iterable[Any],
    kind: str,
    title: str,
    body: str = "",
    actor: Any | None = None,
    target_type: str = "",
    target_id: UUID | None = None,
) -> list[Notification]:
    """Crea una notificación por cada destinatario (fan-out on write).

    Excluye al `actor` (nadie se notifica a sí mismo) y deduplica destinatarios
    repetidos. Si tras filtrar no queda nadie, no crea nada y retorna [].

    Args:
        tenant:      Clínica en la que viven las notificaciones.
        recipients:  Iterable de usuarios destino (objetos User).
        kind:        Tipo de notificación (NotificationKind).
        title:       Texto principal ya armado para mostrar.
        body:        Texto secundario opcional.
        actor:       Usuario que disparó el evento. Se excluye de los destinatarios.
        target_type: Tipo de objeto destino para el enlace (NotificationTarget) o "".
        target_id:   UUID del objeto destino, o None.

    Returns:
        Lista de Notification creadas (puede estar vacía).
    """
    actor_id = getattr(actor, "pk", None)

    # Deduplicar por pk y excluir al actor (no auto-notificación).
    unique_recipients: dict[Any, Any] = {}
    for user in recipients:
        pk = getattr(user, "pk", None)
        if pk is None or pk == actor_id:
            continue
        unique_recipients.setdefault(pk, user)

    if not unique_recipients:
        return []

    objs = [
        Notification(
            tenant=tenant,
            created_by=actor,
            recipient=user,
            actor=actor,
            kind=kind,
            title=title,
            body=body,
            target_type=target_type,
            target_id=target_id,
        )
        for user in unique_recipients.values()
    ]
    created = Notification.objects.bulk_create(objs)
    logger.info(
        "notification_fanout: %d avisos creados (kind=%s, tenant=%s)",
        len(created),
        kind,
        tenant.pk,
    )
    return created


def notification_create(
    *,
    tenant: Tenant,
    recipient: Any,
    kind: str,
    title: str,
    body: str = "",
    actor: Any | None = None,
    target_type: str = "",
    target_id: UUID | None = None,
) -> Notification | None:
    """Crea UNA notificación para un destinatario (atajo de notification_fanout).

    Retorna None si el destinatario es el propio actor (no auto-notificación).
    """
    created = notification_fanout(
        tenant=tenant,
        recipients=[recipient],
        kind=kind,
        title=title,
        body=body,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
    )
    return created[0] if created else None


# ---------------------------------------------------------------------------
# Estado (leída / no leída)
# ---------------------------------------------------------------------------


@transaction.atomic
def notification_mark_read(*, notification: Notification, user: Any) -> Notification:
    """Marca una notificación como leída (idempotente).

    Solo el destinatario puede marcarla. Si ya estaba leída, no cambia read_at.

    Args:
        notification: Notificación a marcar.
        user:         Usuario que la marca (debe ser el recipient).

    Returns:
        La notificación (con read_at poblado).

    Raises:
        Notification.DoesNotExist: si el usuario no es el destinatario
            (se trata como "no encontrada" para no revelar su existencia).
    """
    if notification.recipient_id != user.pk:
        raise Notification.DoesNotExist("La notificación no existe o no pertenece a este usuario.")

    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])

    return notification


@transaction.atomic
def notification_mark_all_read(*, tenant: Tenant, user: Any) -> int:
    """Marca como leídas todas las notificaciones no leídas del usuario.

    Args:
        tenant: Tenant del contexto activo.
        user:   Usuario dueño de las notificaciones.

    Returns:
        Cantidad de notificaciones que pasaron de no leída a leída.
    """
    return Notification.objects.filter(
        tenant=tenant,
        recipient=user,
        read_at__isnull=True,
    ).update(read_at=timezone.now())
