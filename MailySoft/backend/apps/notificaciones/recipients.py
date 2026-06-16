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
