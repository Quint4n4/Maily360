"""
Permisos para la app audit.

AuditLogPermission — SOLO el owner puede ver la bitácora de su clínica.
Todos los demás roles (admin, médicos, enfermería, recepción, finanzas y
solo-lectura) quedan excluidos.

Platform staff accede a la bitácora completa vía Django Admin (all_objects).

Multi-sede (decisión del dueño, 2026-07-16): la bitácora NO se acota por sede
(el modelo AuditLog no tiene campo `sucursal`). Para no exponer la actividad de
una sede a un "administrador de sucursal" de OTRA sede, la bitácora completa la
ve ÚNICAMENTE el dueño (que supervisa toda la operación). Antes era owner+admin,
lo que dejaba a un admin de una sede ver las acciones de todas las demás.
"""

from typing import ClassVar

from apps.core.permissions import HasClinicRole, Role

#: Bitácora: solo el dueño (owner). Ver el docstring del módulo.
AUDIT_ROLES: frozenset[str] = frozenset({Role.OWNER})


class AuditLogPermission(HasClinicRole):
    """Solo el owner puede consultar la bitácora.

    Matriz:
        GET → AUDIT_ROLES (solo owner).
        Ningún otro método HTTP está habilitado (la bitácora es solo-lectura).
    """

    policy: ClassVar[dict[str, frozenset[str]]] = {
        "GET": AUDIT_ROLES,
    }
