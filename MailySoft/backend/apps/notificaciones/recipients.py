"""
Resolución de destinatarios para el reparto de notificaciones.

Funciones que devuelven listas de usuarios (User) a partir de roles/membresías
del tenant. Las apps de dominio (notas, agenda) las usan para decidir a quién
notificar antes de llamar a notification_fanout.

Diseño: este módulo solo conoce TenantMembership (roles). El mapeo específico de
dominio (doctor de una cita, médicos de un consultorio) lo arma cada app con sus
propios modelos y pasa los User resultantes al fanout.
"""

from collections.abc import Iterable
from typing import Any

from apps.tenancy.models import TenantMembership

Role = TenantMembership.Role

#: Staff clínico que recibe avisos amplios (reuniones de toda la clínica).
#: Excluye finance y readonly (perfiles administrativos/observadores).
STAFF_ROLES: tuple[str, ...] = (
    Role.OWNER,
    Role.ADMIN,
    Role.DOCTOR,
    Role.NURSE,
    Role.RECEPTION,
)

#: Roles que pueden DIRIGIR una nota a un rol (Note scope=role).
#: El broadcast a toda la clínica (scope=all) sigue siendo exclusivo del owner.
ROLE_NOTE_SENDERS: frozenset[str] = frozenset(
    {Role.OWNER, Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTION}
)


def users_with_roles(*, tenant: Any, roles: Iterable[str]) -> list[Any]:
    """Usuarios con membresía activa en el tenant cuyo rol esté en `roles`.

    Args:
        tenant: Clínica donde se buscan las membresías.
        roles:  Iterable de roles a incluir.

    Returns:
        Lista de User (puede estar vacía). Sin duplicados (una membresía por
        usuario y tenant).
    """
    memberships = TenantMembership.objects.filter(
        tenant=tenant,
        role__in=list(roles),
        is_active=True,
        deleted_at__isnull=True,
    ).select_related("user")
    return [m.user for m in memberships]


def users_with_role(*, tenant: Any, role: str) -> list[Any]:
    """Usuarios con membresía activa en el tenant y el rol dado."""
    return users_with_roles(tenant=tenant, roles=[role])


def clinic_staff_users(*, tenant: Any) -> list[Any]:
    """Todo el staff clínico del tenant (STAFF_ROLES)."""
    return users_with_roles(tenant=tenant, roles=STAFF_ROLES)


def all_tenant_users(*, tenant: Any) -> list[Any]:
    """Todos los usuarios con membresía activa en el tenant (cualquier rol).

    Se usa para el aviso a toda la clínica (Note scope=all), que alcanza incluso
    a finance y readonly.
    """
    return users_with_roles(
        tenant=tenant,
        roles=[
            Role.OWNER,
            Role.ADMIN,
            Role.DOCTOR,
            Role.NURSE,
            Role.RECEPTION,
            Role.FINANCE,
            Role.READONLY,
        ],
    )


def filter_recipients_by_sucursal(
    *, tenant: Any, recipients: list[Any], sucursal_id: Any
) -> list[Any]:
    """Filtra destinatarios de campana a los MIEMBROS de esa sede.

    Cierre de hueco de sedes (notificaciones/campana — 2026-07-16): un evento
    PRIVADO de una sucursal (una cita, un bloqueo, un aviso de sede) solo debe
    sonar la campana a quienes TRABAJAN en esa sede.

    IMPORTANTE — el DUEÑO queda EXCLUIDO de las campanas de una sede específica
    (2026-07-16, feedback del dueño): el owner "puede ver" TODAS las sedes
    (`allowed_sucursales`), pero un aviso *de sucursal* es para el personal de
    esa sucursal, no para el dueño. El dueño lo sigue VIENDO en la lista de
    Notas (supervisión bajo demanda), pero no recibe la campana de cada aviso
    interno de cada sede. Para los NO-owner, "miembro de la sede" = la sede está
    en su `allowed_sucursales` (sus MembershipSucursal, o la predeterminada si
    no tiene asignación).

    `sucursal_id=None` ("de toda la clínica" / sin sede) NO filtra: se notifica
    a todos los destinatarios originales, incluido el dueño (un aviso a todas
    las sedes sí es para todos).

    Import perezoso de `allowed_sucursales` para no crear un ciclo
    notificaciones→clinica a nivel de módulo.

    Args:
        tenant:      Tenant del evento.
        recipients:  Usuarios candidatos ya resueltos (por rol/dominio).
        sucursal_id: Sede a la que quedó acotado el evento, o None.

    Returns:
        Subconjunto de `recipients` que son miembros de `sucursal_id`, sin los
        owners (o la lista completa si `sucursal_id` es None).
    """
    if sucursal_id is None:
        return recipients

    from apps.clinica.sucursal_scope import allowed_sucursales

    # Owners: excluidos de la campana de una sede específica (ven el aviso en la
    # lista, pero no reciben la notificación). Una sola query para todos.
    owner_user_ids: set[Any] = set(
        TenantMembership.objects.filter(
            tenant=tenant,
            role=Role.OWNER,
            is_active=True,
            deleted_at__isnull=True,
        ).values_list("user_id", flat=True)
    )

    return [
        recipient
        for recipient in recipients
        if recipient.pk not in owner_user_ids
        and allowed_sucursales(user=recipient, tenant=tenant).filter(id=sucursal_id).exists()
    ]
