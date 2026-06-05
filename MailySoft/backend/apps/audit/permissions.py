"""
Permisos para la app audit.

AuditLogPermission — solo owner y admin pueden ver la bitácora de su clínica.
Médicos, enfermería, recepción, finanzas y solo-lectura quedan excluidos.

Platform staff accede a la bitácora completa vía Django Admin (all_objects).
"""

from typing import ClassVar

from apps.core.permissions import HasClinicRole, MANAGE_ROLES


class AuditLogPermission(HasClinicRole):
    """Solo owner y admin pueden consultar la bitácora.

    Matriz:
        GET → MANAGE_ROLES (owner, admin).
        Ningún otro método HTTP está habilitado (la bitácora es solo-lectura).
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": MANAGE_ROLES,
    }
