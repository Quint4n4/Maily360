"""
Tipos de cita configurables por clínica (AppointmentType).

CRUD de las categorías de cita (nombre + color) que tiñen las tarjetas de la
agenda. Extraído de agenda/services.py para mantener el service principal
enfocado en el ciclo de vida de las citas.

Convención: keyword-only args, nombrado acción+entidad, auditoría NOM-024.
"""

from django.contrib.auth import get_user_model

from apps.agenda.models import AppointmentType
from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.tenancy.models import Tenant

User = get_user_model()

_APPOINTMENT_TYPE_EDITABLE: frozenset[str] = frozenset({"name", "color_hex"})


def appointment_type_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    name: str,
    color_hex: str = "",
) -> AppointmentType:
    """Crea un tipo de cita (categoría con color) para el tenant."""
    appointment_type = AppointmentType.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        color_hex=color_hex,
        is_active=True,
    )
    audit_record(
        action=ActionType.APPOINTMENT_TYPE_CREATE,
        resource_type="AppointmentType",
        actor=user,
        tenant=tenant,
        resource_id=appointment_type.id,
        resource_repr=appointment_type.name,
    )
    return appointment_type


def appointment_type_update(
    *,
    appointment_type: AppointmentType,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> AppointmentType:
    """Actualiza nombre y/o color de un tipo de cita."""
    changed = [f for f in fields if f in _APPOINTMENT_TYPE_EDITABLE]
    for field_name in changed:
        setattr(appointment_type, field_name, fields[field_name])
    if changed:
        appointment_type.save(update_fields=[*changed, "updated_at"])
        audit_record(
            action=ActionType.APPOINTMENT_TYPE_UPDATE,
            resource_type="AppointmentType",
            actor=user,
            tenant=appointment_type.tenant,
            resource_id=appointment_type.id,
            resource_repr=appointment_type.name,
            metadata={"changed": sorted(changed)},
        )
    return appointment_type


def appointment_type_deactivate(
    *,
    appointment_type: AppointmentType,
    user: "User",  # type: ignore[valid-type]
) -> AppointmentType:
    """Desactiva (soft) un tipo de cita: deja de aparecer al agendar."""
    appointment_type.is_active = False
    appointment_type.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.APPOINTMENT_TYPE_DEACTIVATE,
        resource_type="AppointmentType",
        actor=user,
        tenant=appointment_type.tenant,
        resource_id=appointment_type.id,
        resource_repr=appointment_type.name,
    )
    return appointment_type
