"""
Services de la app personal.

Toda escritura/modificación de doctores, consultorios y horarios pasa por aquí.
Las vistas son delgadas: parsean el request, llaman al service, devuelven la respuesta.

Convención: keyword-only args en toda firma, nombrado acción+entidad.
"""

import datetime
import uuid
from typing import Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.personal.models import Consultorio, Doctor, DoctorSchedule
from apps.tenancy.models import Tenant, TenantMembership

User = get_user_model()

# ---------------------------------------------------------------------------
# Campos inmutables de Doctor que no se pueden actualizar vía doctor_update
# ---------------------------------------------------------------------------

_DOCTOR_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "membership",
        "membership_id",
        "tenant",
        "tenant_id",
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        # FIX-F1: is_active no se puede cambiar vía doctor_update (solo vía doctor_deactivate).
        # Evita backdoor de activación/desactivación por PATCH.
        "is_active",
    }
)

# ---------------------------------------------------------------------------
# Campos inmutables de Consultorio
# ---------------------------------------------------------------------------

_CONSULTORIO_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {"tenant", "tenant_id", "id", "created_at", "deleted_at"}
)


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


def doctor_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    membership: TenantMembership,
    cedula_profesional: str = "",
    specialty: str = "",
    default_appointment_duration: int = 30,
    bio_short: str = "",
) -> Doctor:
    """Crea un perfil de médico para una membresía existente.

    Valida:
    - Que membership.role == 'doctor'.
    - Que membership.tenant == tenant (no se puede asignar una membresía de otra clínica).
    - Que no exista ya un Doctor para esa membresía (el OneToOne lo bloquea en BD,
      pero aquí damos un error legible antes del IntegrityError).

    Args:
        tenant:                        Clínica a la que pertenece el médico.
        user:                          Usuario que crea el registro (auditoría).
        membership:                    TenantMembership del médico. Role debe ser 'doctor'.
        cedula_profesional:            Cédula profesional SEP (opcional).
        specialty:                     Especialidad médica texto libre (opcional).
        default_appointment_duration:  Duración default de cita en minutos (default 30).
        bio_short:                     Semblanza corta (opcional, máx 255 caracteres).

    Returns:
        Instancia Doctor recién creada.

    Raises:
        ValidationError: si el role no es 'doctor', la membresía no pertenece al tenant,
                         o ya existe un perfil de médico para esa membresía.
    """
    if membership.role != TenantMembership.Role.DOCTOR:
        raise ValidationError("La membresía debe tener rol de médico.")

    if membership.tenant_id != tenant.id:
        raise ValidationError(
            "La membresía no pertenece a esta clínica. "
            "No se puede crear un perfil de médico con una membresía de otro tenant."
        )

    # FIX-F6: excluir registros soft-deleted del chequeo de duplicado.
    # Consistente con consultorio_create (deleted_at__isnull=True).
    # Esto permite re-crear el perfil de Doctor si fue soft-deleted previamente.
    if Doctor.all_objects.filter(membership=membership, deleted_at__isnull=True).exists():
        raise ValidationError(
            "Ya existe un perfil de médico para este usuario en esta clínica."
        )

    doctor = Doctor.objects.create(
        tenant=tenant,
        created_by=user,
        membership=membership,
        cedula_profesional=cedula_profesional,
        specialty=specialty,
        default_appointment_duration=default_appointment_duration,
        bio_short=bio_short,
    )

    audit_record(
        action=ActionType.DOCTOR_CREATE,
        resource_type="Doctor",
        actor=user,
        tenant=tenant,
        resource_id=doctor.id,
        resource_repr=str(doctor),
    )
    return doctor


def doctor_update(
    *,
    doctor: Doctor,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> Doctor:
    """Actualiza campos permitidos de un médico existente.

    No permite modificar membership, tenant ni campos de auditoría.
    La desactivación solo ocurre vía doctor_deactivate.

    Args:
        doctor: Instancia Doctor a actualizar.
        user:   Usuario que realiza el cambio (para futura auditoría).
        **fields: Campos y valores a actualizar. Los campos inmutables se rechazan.

    Returns:
        La instancia Doctor actualizada.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable.
    """
    attempted_immutable = _DOCTOR_IMMUTABLE_FIELDS.intersection(fields.keys())
    if attempted_immutable:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(attempted_immutable))}."
        )

    for field_name, value in fields.items():
        setattr(doctor, field_name, value)

    update_fields = list(fields.keys()) + ["updated_at"]
    doctor.save(update_fields=update_fields)

    audit_record(
        action=ActionType.DOCTOR_UPDATE,
        resource_type="Doctor",
        actor=user,
        tenant=doctor.tenant,
        resource_id=doctor.id,
        resource_repr=str(doctor),
        metadata={"changed_fields": sorted(fields.keys())},
    )
    return doctor


def doctor_deactivate(
    *,
    doctor: Doctor,
    user: "User",  # type: ignore[valid-type]
) -> Doctor:
    """Desactiva un médico (soft disable — NO borra el registro).

    Pone is_active=False. El perfil permanece en la base de datos.

    Args:
        doctor: Instancia Doctor a desactivar.
        user:   Usuario que realiza la acción (para futura auditoría).

    Returns:
        La instancia Doctor con is_active=False.
    """
    doctor.is_active = False
    doctor.save(update_fields=["is_active", "updated_at"])

    audit_record(
        action=ActionType.DOCTOR_DEACTIVATE,
        resource_type="Doctor",
        actor=user,
        tenant=doctor.tenant,
        resource_id=doctor.id,
        resource_repr=str(doctor),
    )
    return doctor


def doctor_set_consultorios(
    *,
    doctor: Doctor,
    user: "User",  # type: ignore[valid-type]
    consultorio_ids: list[uuid.UUID],
) -> Doctor:
    """Fija (reemplaza) la lista de consultorios asignados al médico.

    Una lista vacía elimina todas las restricciones de consultorio para ese
    médico (puede usar cualquier consultorio del tenant).

    Valida:
    - Que cada consultorio exista y pertenezca al mismo tenant que el doctor.
    - Que cada consultorio esté activo (un médico no puede atender en un
      consultorio desactivado).

    Usa doctor.consultorios.set() que es atómico: primero borra las asignaciones
    anteriores y luego inserta las nuevas en una sola operación.

    Args:
        doctor:           Instancia Doctor a modificar.
        user:             Usuario que realiza el cambio (para auditoría).
        consultorio_ids:  Lista de UUIDs de Consultorio. Puede ser vacía para
                          eliminar todas las restricciones.

    Returns:
        La instancia Doctor con la relación M2M actualizada.

    Raises:
        ValidationError: si algún consultorio no existe, no pertenece al tenant
                         del doctor, o está desactivado.
    """
    if consultorio_ids:
        # Recuperar los consultorios activos del mismo tenant en una sola query.
        consultorios = list(
            Consultorio.all_objects.filter(
                id__in=consultorio_ids,
                tenant_id=doctor.tenant_id,
                deleted_at__isnull=True,
            )
        )

        # Verificar que todos los IDs solicitados fueron encontrados.
        found_ids = {c.id for c in consultorios}
        missing = set(consultorio_ids) - found_ids
        if missing:
            raise ValidationError(
                "Uno o más consultorios no existen en esta clínica: "
                f"{', '.join(str(i) for i in missing)}."
            )

        # Verificar que todos estén activos.
        inactive = [c for c in consultorios if not c.is_active]
        if inactive:
            names = ", ".join(c.name for c in inactive)
            raise ValidationError(
                f"Los siguientes consultorios están inactivos: {names}."
            )
    else:
        consultorios = []

    doctor.consultorios.set(consultorios)

    audit_record(
        action=ActionType.DOCTOR_CONSULTORIOS,
        resource_type="Doctor",
        actor=user,
        tenant=doctor.tenant,
        resource_id=doctor.id,
        resource_repr=str(doctor),
        metadata={
            "consultorio_ids": [str(c_id) for c_id in consultorio_ids],
        },
    )
    return doctor


# ---------------------------------------------------------------------------
# Consultorio
# ---------------------------------------------------------------------------


def consultorio_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    name: str,
    location: str = "",
    color_hex: str = "",
) -> Consultorio:
    """Crea un consultorio en el tenant dado.

    Valida que el nombre sea único en el tenant antes del intento de INSERT
    para dar un error legible antes del IntegrityError del UniqueConstraint.

    Args:
        tenant:    Clínica a la que pertenece el consultorio.
        user:      Usuario que crea el registro (auditoría).
        name:      Nombre del consultorio. Único por clínica.
        location:  Ubicación física (opcional).
        color_hex: Color hexadecimal para calendario (opcional, ej: "#3B82F6").

    Returns:
        Instancia Consultorio recién creada.

    Raises:
        ValidationError: si ya existe un consultorio con ese nombre en el tenant.
    """
    duplicate_exists = Consultorio.all_objects.filter(
        tenant=tenant,
        name=name,
        deleted_at__isnull=True,
    ).exists()
    if duplicate_exists:
        raise ValidationError(
            f"Ya existe un consultorio con el nombre '{name}' en esta clínica."
        )

    consultorio = Consultorio.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        location=location,
        color_hex=color_hex,
    )

    audit_record(
        action=ActionType.CONSULTORIO_CREATE,
        resource_type="Consultorio",
        actor=user,
        tenant=tenant,
        resource_id=consultorio.id,
        resource_repr=str(consultorio),
    )
    return consultorio


def consultorio_update(
    *,
    consultorio: Consultorio,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> Consultorio:
    """Actualiza campos permitidos de un consultorio existente.

    Si se cambia el nombre, revalida unicidad dentro del tenant.

    Args:
        consultorio: Instancia Consultorio a actualizar.
        user:        Usuario que realiza el cambio (para futura auditoría).
        **fields:    Campos y valores a actualizar.

    Returns:
        La instancia Consultorio actualizada.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable, o si
                         el nuevo nombre ya existe en el tenant.
    """
    attempted_immutable = _CONSULTORIO_IMMUTABLE_FIELDS.intersection(fields.keys())
    if attempted_immutable:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(attempted_immutable))}."
        )

    new_name: Optional[str] = fields.get("name")  # type: ignore[assignment]
    if new_name is not None and new_name != consultorio.name:
        duplicate_exists = Consultorio.all_objects.filter(
            tenant=consultorio.tenant,
            name=new_name,
            deleted_at__isnull=True,
        ).exclude(id=consultorio.id).exists()
        if duplicate_exists:
            raise ValidationError(
                f"Ya existe un consultorio con el nombre '{new_name}' en esta clínica."
            )

    for field_name, value in fields.items():
        setattr(consultorio, field_name, value)

    update_fields = list(fields.keys()) + ["updated_at"]
    consultorio.save(update_fields=update_fields)

    audit_record(
        action=ActionType.CONSULTORIO_UPDATE,
        resource_type="Consultorio",
        actor=user,
        tenant=consultorio.tenant,
        resource_id=consultorio.id,
        resource_repr=str(consultorio),
        metadata={"changed_fields": sorted(fields.keys())},
    )
    return consultorio


def consultorio_deactivate(
    *,
    consultorio: Consultorio,
    user: "User",  # type: ignore[valid-type]
) -> Consultorio:
    """Desactiva un consultorio (soft disable — NO borra el registro).

    Args:
        consultorio: Instancia Consultorio a desactivar.
        user:        Usuario que realiza la acción (para futura auditoría).

    Returns:
        La instancia Consultorio con is_active=False.
    """
    consultorio.is_active = False
    consultorio.save(update_fields=["is_active", "updated_at"])

    audit_record(
        action=ActionType.CONSULTORIO_DEACTIVATE,
        resource_type="Consultorio",
        actor=user,
        tenant=consultorio.tenant,
        resource_id=consultorio.id,
        resource_repr=str(consultorio),
    )
    return consultorio


# ---------------------------------------------------------------------------
# DoctorSchedule
# ---------------------------------------------------------------------------


def schedule_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    doctor: Doctor,
    day_of_week: int,
    start_time: datetime.time,
    end_time: datetime.time,
    consultorio: Optional[Consultorio] = None,
    valid_from: Optional[datetime.date] = None,
    valid_until: Optional[datetime.date] = None,
) -> DoctorSchedule:
    """Crea un bloque de horario para un médico.

    Valida:
    - Que end_time > start_time (consistencia de horario).
    - Que el doctor pertenezca al tenant actual.

    NOTA: En v1 no se valida solapamiento entre bloques de horario del mismo día.
    TODO(v2): validar que no existan bloques solapados para el mismo doctor/día.
              Consultar la implementación de anti-empalme del service de citas
              (agenda) como referencia para la query de detección.

    Los tiempos se almacenan en hora LOCAL del tenant (ver docstring de DoctorSchedule).

    Args:
        tenant:      Clínica a la que pertenece el horario.
        user:        Usuario que crea el registro (auditoría).
        doctor:      Médico al que pertenece el horario.
        day_of_week: Día de semana (0=Lunes, 6=Domingo).
        start_time:  Hora de inicio en hora local del tenant.
        end_time:    Hora de fin en hora local del tenant. Debe ser > start_time.
        consultorio: Consultorio asignado (opcional).
        valid_from:  Fecha de inicio de vigencia (opcional).
        valid_until: Fecha de fin de vigencia (opcional).

    Returns:
        Instancia DoctorSchedule recién creada.

    Raises:
        ValidationError: si end_time <= start_time, o si el doctor no pertenece al tenant.
    """
    if end_time <= start_time:
        raise ValidationError(
            {"end_time": "La hora de fin debe ser posterior a la hora de inicio."}
        )

    if doctor.tenant_id != tenant.id:
        raise ValidationError(
            "El médico no pertenece a esta clínica."
        )

    # FIX-F3: validar que el consultorio (si se provee) pertenece al mismo tenant.
    # Previene asignar un consultorio de otra clínica al horario.
    if consultorio is not None and consultorio.tenant_id != tenant.id:
        raise ValidationError("El consultorio no pertenece a esta clínica.")

    # FIX-F4: validar rango de vigencia.
    if valid_from is not None and valid_until is not None and valid_until < valid_from:
        raise ValidationError(
            {"valid_until": "La fecha de fin de vigencia debe ser posterior a la fecha de inicio."}
        )

    schedule = DoctorSchedule(
        tenant=tenant,
        created_by=user,
        doctor=doctor,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        consultorio=consultorio,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    # Llamar full_clean() para ejecutar también el clean() del modelo como defensa en profundidad.
    schedule.full_clean(exclude=["tenant", "created_by"])
    schedule.save()

    audit_record(
        action=ActionType.SCHEDULE_CREATE,
        resource_type="DoctorSchedule",
        actor=user,
        tenant=tenant,
        resource_id=schedule.id,
        resource_repr=str(schedule),
        metadata={"day_of_week": day_of_week},
    )
    return schedule


def schedule_deactivate(
    *,
    schedule: DoctorSchedule,
    user: "User",  # type: ignore[valid-type]
) -> DoctorSchedule:
    """Desactiva un bloque de horario (soft delete vía is_active=False).

    Consistente con el patrón de soft-delete del resto del proyecto.
    El horario permanece en la base de datos para historial.

    Args:
        schedule: Instancia DoctorSchedule a desactivar.
        user:     Usuario que realiza la acción (para futura auditoría).

    Returns:
        La instancia DoctorSchedule con is_active=False.
    """
    schedule.is_active = False
    schedule.save(update_fields=["is_active", "updated_at"])

    audit_record(
        action=ActionType.SCHEDULE_DEACTIVATE,
        resource_type="DoctorSchedule",
        actor=user,
        tenant=schedule.tenant,
        resource_id=schedule.id,
        resource_repr=str(schedule),
    )
    return schedule
