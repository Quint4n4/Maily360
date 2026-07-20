"""
Services de la app personal.

Toda escritura/modificación de doctores, consultorios y horarios pasa por aquí.
Las vistas son delgadas: parsean el request, llaman al service, devuelven la respuesta.

Convención: keyword-only args en toda firma, nombrado acción+entidad.
"""

import datetime
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.clinica.models import Sucursal
from apps.clinica.sucursal_scope import allowed_sucursales, resolve_write_sucursal
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
        raise ValidationError("Ya existe un perfil de médico para este usuario en esta clínica.")

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

    Autorización (cierre de hueco — Clúster C, escalada;
    docs/design/sucursales-hallazgos-seguridad.md): los consultorios son
    PRIVADOS por sede (A5). Igual que `doctor_set_sucursales`, si `user` NO es
    owner del tenant, la diferencia simétrica entre los consultorios ACTUALES
    del doctor y los NUEVOS —lo que se agrega MÁS lo que se quita— solo puede
    tocar consultorios cuya SEDE esté en `allowed_sucursales(user=user,
    tenant=doctor.tenant)`. Antes de este fix, un admin de Centro podía asignar
    o quitar un consultorio de Norte a cualquier médico sin tener acceso a Norte.

    Args:
        doctor:           Instancia Doctor a modificar.
        user:             Usuario que realiza el cambio (auditoría y
                          autorización de sede — el "actor" de la operación).
        consultorio_ids:  Lista de UUIDs de Consultorio. Puede ser vacía para
                          eliminar todas las restricciones.

    Returns:
        La instancia Doctor con la relación M2M actualizada.

    Raises:
        ValidationError: si algún consultorio no existe, no pertenece al tenant
                         del doctor, está desactivado; si `user` no tiene una
                         membresía activa en el tenant del doctor; o si `user`
                         (no owner) intenta asignar o quitar un consultorio de
                         una sede fuera de su alcance (`allowed_sucursales`).
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
            raise ValidationError(f"Los siguientes consultorios están inactivos: {names}.")
    else:
        consultorios = []

    # Autorización (cierre de hueco — Clúster C, escalada; mismo patrón que
    # doctor_set_sucursales y membership_sucursales_set): los consultorios son
    # PRIVADOS por sede (A5), así que un actor que NO sea owner solo puede
    # agregar o quitar consultorios cuya SEDE esté en su propio alcance
    # (allowed_sucursales). Sin esto, un admin de Centro podía asignar (o
    # quitar) un consultorio de Norte a cualquier médico sin tener él mismo
    # acceso a Norte. La sede None (legado) siempre pasa, igual que en el resto.
    actor_membership = (
        TenantMembership.objects.filter(
            user=user,
            tenant=doctor.tenant,
            is_active=True,
            deleted_at__isnull=True,
        )
        .order_by("created_at")
        .first()
    )
    if actor_membership is None:
        raise ValidationError("No tienes una membresía activa en esta clínica.")

    if actor_membership.role != TenantMembership.Role.OWNER:
        current_map: dict[uuid.UUID, uuid.UUID | None] = dict(
            doctor.consultorios.values_list("id", "sucursal_id")
        )
        new_map: dict[uuid.UUID, uuid.UUID | None] = {c.id: c.sucursal_id for c in consultorios}
        touched_consultorio_ids = set(current_map) ^ set(new_map)
        touched_sucursal_ids: set[uuid.UUID] = set()
        for cid in touched_consultorio_ids:
            sid = current_map[cid] if cid in current_map else new_map[cid]
            if sid is not None:
                touched_sucursal_ids.add(sid)
        actor_allowed_ids: set[uuid.UUID] = set(
            allowed_sucursales(user=user, tenant=doctor.tenant).values_list("id", flat=True)
        )
        forbidden = touched_sucursal_ids - actor_allowed_ids
        if forbidden:
            raise ValidationError(
                "No puedes asignar ni quitar consultorios de sedes en las que "
                "tú mismo no tienes acceso."
            )

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


def doctor_set_sucursales(
    *,
    doctor: Doctor,
    user: "User",  # type: ignore[valid-type]
    sucursal_ids: list[uuid.UUID],
) -> Doctor:
    """Fija (reemplaza) la lista de sucursales asignadas al médico (multi-sede — Fase 1).

    Una lista vacía elimina todas las restricciones de sucursal para ese
    médico (puede atender en cualquier sede del tenant — compatibilidad retro).

    Valida:
    - Que cada sucursal exista y pertenezca al mismo tenant que el doctor.
    - Que cada sucursal esté activa (no se asigna una sede desactivada).

    Usa doctor.sucursales.set(), atómico: mismo patrón que doctor_set_consultorios.

    Autorización (cierre de hueco — Clúster C, escalada;
    docs/design/sucursales-hallazgos-seguridad.md): mismo patrón anti-escalada
    que `apps.clinica.services.membership_sucursales_set`. Si `user` NO es
    owner del tenant, la diferencia simétrica entre las sedes ACTUALES del
    doctor y las NUEVAS (`sucursal_ids`) —lo que se agrega MÁS lo que se
    quita— debe estar contenida en `allowed_sucursales(user=user,
    tenant=doctor.tenant)`. Antes de este fix, un admin de Centro podía
    reasignar en qué sedes atiende CUALQUIER médico del tenant, incluida
    Norte, sin tener él mismo acceso a Norte (VERIFICADO en la auditoría).
    No aplica la regla anti-lockout de `membership_sucursales_set`: esto fija
    en qué sedes ATIENDE un médico, no el alcance operativo de una membresía
    de usuario, así que vaciar la lista no puede autobloquear a nadie.

    Args:
        doctor:       Instancia Doctor a modificar.
        user:         Usuario que realiza el cambio (auditoría y autorización
                      de sede — el "actor" de la operación).
        sucursal_ids: Lista de UUIDs de Sucursal. Puede ser vacía.

    Returns:
        La instancia Doctor con la relación M2M actualizada.

    Raises:
        ValidationError: si alguna sucursal no existe, no pertenece al tenant
                         del doctor, está desactivada; si `user` no tiene una
                         membresía activa en el tenant del doctor; o si
                         `user` (no owner) intenta otorgar o quitar una sede
                         fuera de su propio alcance (`allowed_sucursales`).
    """
    unique_ids: set[uuid.UUID] = set(sucursal_ids)

    if unique_ids:
        sucursales = list(
            Sucursal.all_objects.filter(
                id__in=unique_ids,
                tenant_id=doctor.tenant_id,
                deleted_at__isnull=True,
            )
        )

        found_ids = {s.id for s in sucursales}
        missing = unique_ids - found_ids
        if missing:
            raise ValidationError(
                "Una o más sucursales no existen en esta clínica: "
                f"{', '.join(str(i) for i in missing)}."
            )

        inactive = [s for s in sucursales if not s.is_active]
        if inactive:
            names = ", ".join(s.name for s in inactive)
            raise ValidationError(f"Las siguientes sucursales están inactivas: {names}.")
    else:
        sucursales = []

    actor_membership = (
        TenantMembership.objects.filter(
            user=user,
            tenant=doctor.tenant,
            is_active=True,
            deleted_at__isnull=True,
        )
        .order_by("created_at")
        .first()
    )
    if actor_membership is None:
        raise ValidationError("No tienes una membresía activa en esta clínica.")

    if actor_membership.role != TenantMembership.Role.OWNER:
        current_ids: set[uuid.UUID] = set(doctor.sucursales.values_list("id", flat=True))
        actor_allowed_ids: set[uuid.UUID] = set(
            allowed_sucursales(user=user, tenant=doctor.tenant).values_list("id", flat=True)
        )
        touched = unique_ids.symmetric_difference(current_ids)
        forbidden = touched - actor_allowed_ids
        if forbidden:
            raise ValidationError(
                "No puedes otorgar ni quitar sedes en las que tú mismo no tienes acceso."
            )

    doctor.sucursales.set(sucursales)

    audit_record(
        action=ActionType.DOCTOR_SUCURSALES,
        resource_type="Doctor",
        actor=user,
        tenant=doctor.tenant,
        resource_id=doctor.id,
        resource_repr=str(doctor),
        metadata={
            "sucursal_ids": [str(s_id) for s_id in sucursal_ids],
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
    sucursal_id: uuid.UUID | None = None,
    active_sucursal_id: uuid.UUID | None = None,
) -> Consultorio:
    """Crea un consultorio en el tenant dado.

    Valida que el nombre sea único en el tenant antes del intento de INSERT
    para dar un error legible antes del IntegrityError del UniqueConstraint.

    Multi-sede (cierre de hueco A5 — seguridad;
    docs/design/sucursales-hallazgos-seguridad.md): la sucursal se resuelve
    con `resolve_write_sucursal` (misma precedencia y autorización que
    `schedule_create`/`appointment_create`: sucursal_id explícito > sede
    activa del request > predeterminada del tenant), NO con un selector
    tenant-scoped simple. Antes de este fix, la vista resolvía la sucursal
    con `sucursal_get` (solo valida que sea del tenant, NO que el actor
    tenga acceso a ella) y aceptaba un `sucursal_id` explícito de una sede
    ajena al actor.

    Args:
        tenant:             Clínica a la que pertenece el consultorio.
        user:               Usuario que crea el registro (auditoría y
                            autorización de sede).
        name:               Nombre del consultorio. Único por clínica.
        location:           Ubicación física (opcional).
        color_hex:          Color hexadecimal para calendario (opcional, ej: "#3B82F6").
        sucursal_id:        Sucursal EXPLÍCITA indicada por el cliente
                            (opcional). Máxima precedencia en la resolución.
        active_sucursal_id: Sucursal activa del request (header
                            X-Sucursal-Id), que la vista resuelve con
                            `resolve_active_sucursal` y pasa aquí.

    Returns:
        Instancia Consultorio recién creada.

    Raises:
        ValidationError: si ya existe un consultorio con ese nombre en el
                         tenant, si `sucursal_id` fue indicado explícitamente
                         pero no existe en este tenant, o si la sede resuelta
                         no está entre las sucursales permitidas de `user`.
    """
    duplicate_exists = Consultorio.all_objects.filter(
        tenant=tenant,
        name=name,
        deleted_at__isnull=True,
    ).exists()
    if duplicate_exists:
        raise ValidationError(f"Ya existe un consultorio con el nombre '{name}' en esta clínica.")

    sucursal: Sucursal | None = resolve_write_sucursal(
        tenant=tenant,
        user=user,
        sucursal_id=sucursal_id,
        active_sucursal_id=active_sucursal_id,
    )

    consultorio = Consultorio.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        location=location,
        color_hex=color_hex,
        sucursal=sucursal,
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

    new_name: str | None = fields.get("name")  # type: ignore[assignment]
    if new_name is not None and new_name != consultorio.name:
        duplicate_exists = (
            Consultorio.all_objects.filter(
                tenant=consultorio.tenant,
                name=new_name,
                deleted_at__isnull=True,
            )
            .exclude(id=consultorio.id)
            .exists()
        )
        if duplicate_exists:
            raise ValidationError(
                f"Ya existe un consultorio con el nombre '{new_name}' en esta clínica."
            )

    # Defensa en profundidad (multi-sede — Fase 1): si se cambia la sucursal,
    # revalidar que pertenezca al mismo tenant aunque la vista ya la haya
    # resuelto con un selector tenant-scoped.
    if "sucursal" in fields:
        new_sucursal: Sucursal | None = fields["sucursal"]  # type: ignore[assignment]
        if new_sucursal is not None and new_sucursal.tenant_id != consultorio.tenant_id:
            raise ValidationError("La sucursal no pertenece a esta clínica.")

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
    consultorio: Consultorio | None = None,
    valid_from: datetime.date | None = None,
    valid_until: datetime.date | None = None,
    sucursal_id: uuid.UUID | None = None,
    active_sucursal_id: uuid.UUID | None = None,
) -> DoctorSchedule:
    """Crea un bloque de horario para un médico.

    Valida:
    - Que end_time > start_time (consistencia de horario).
    - Que el doctor pertenezca al tenant actual.
    - Multi-sede (Fase 2): que el médico atienda en la sucursal resuelta
      (si tiene sucursales asignadas — mismo patrón que appointment_create).

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
        sucursal_id:        Sucursal EXPLÍCITA del horario (multi-sede — Fase 2,
                            opcional). Máxima precedencia en la resolución.
        active_sucursal_id: Sucursal activa del request (header X-Sucursal-Id),
                            que la vista resuelve y pasa aquí.

    Returns:
        Instancia DoctorSchedule recién creada.

    Raises:
        ValidationError: si end_time <= start_time, si el doctor no pertenece
                         al tenant, o si el médico no atiende en la sucursal
                         resuelta.
    """
    if end_time <= start_time:
        raise ValidationError(
            {"end_time": "La hora de fin debe ser posterior a la hora de inicio."}
        )

    if doctor.tenant_id != tenant.id:
        raise ValidationError("El médico no pertenece a esta clínica.")

    # FIX-F3: validar que el consultorio (si se provee) pertenece al mismo tenant.
    # Previene asignar un consultorio de otra clínica al horario.
    if consultorio is not None and consultorio.tenant_id != tenant.id:
        raise ValidationError("El consultorio no pertenece a esta clínica.")

    # FIX-F4: validar rango de vigencia.
    if valid_from is not None and valid_until is not None and valid_until < valid_from:
        raise ValidationError(
            {"valid_until": "La fecha de fin de vigencia debe ser posterior a la fecha de inicio."}
        )

    # Multi-sede (Fase 2): resolver la sucursal del horario con la misma
    # precedencia que appointment_create (sucursal_id > consultorio.sucursal
    # > sucursal activa del request > predeterminada del tenant). Puede ser
    # None (compatibilidad retro: tenant sin sucursales configuradas todavía).
    sucursal: Sucursal | None = resolve_write_sucursal(
        tenant=tenant,
        user=user,
        sucursal_id=sucursal_id,
        consultorio_sucursal_id=consultorio.sucursal_id if consultorio is not None else None,
        active_sucursal_id=active_sucursal_id,
    )

    assigned_sucursal_ids = set(doctor.sucursales.values_list("id", flat=True))
    if assigned_sucursal_ids and (sucursal is None or sucursal.id not in assigned_sucursal_ids):
        raise ValidationError("El médico no atiende en esa sucursal.")

    schedule = DoctorSchedule(
        tenant=tenant,
        created_by=user,
        doctor=doctor,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        consultorio=consultorio,
        sucursal=sucursal,
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
