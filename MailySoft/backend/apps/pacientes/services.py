"""
Services de la app pacientes.

Toda escritura/modificación de pacientes pasa por aquí. Las vistas son delgadas:
parsean el request, llaman al service, devuelven la respuesta.

Convención: keyword-only args en toda firma, nombrado acción+entidad.
"""

import datetime
from typing import Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.pacientes.models import Patient, PatientSequence, Sex
from apps.tenancy.models import Tenant

User = get_user_model()


# ---------------------------------------------------------------------------
# Helper privado: consecutivo seguro
# ---------------------------------------------------------------------------


def _next_record_number(tenant: Tenant) -> str:
    """Genera el siguiente número de expediente para el tenant dado.

    Usa SELECT FOR UPDATE sobre PatientSequence para evitar colisiones
    cuando dos requests crean pacientes de forma concurrente.

    FIX-B2: asegura que tenant no sea None y que se llame dentro de transacción.
    FIX-B1: si dos requests simultáneos intentan crear la primera fila de secuencia,
    el UniqueConstraint en BD + get_or_create garantizan exactamente una fila.
    Si get_or_create falla con IntegrityError por race condition extrema, el caller
    (patient_create) debe envolver en transaction.atomic() y reintentar.

    DEBE llamarse SIEMPRE dentro de transaction.atomic().

    Formato actual: EXP-{year}-{seq:05d}
    Ejemplos: EXP-2026-00001, EXP-2026-00042

    # TODO(3c): leer formato desde TenantAgendaConfig.record_number_format
    # cuando se implemente el Paso 3c. Por ahora se usa el default hardcodeado.
    # También manejar record_number_reset_yearly para reiniciar el consecutivo
    # anualmente si el tenant así lo configura.

    Args:
        tenant: Tenant para el que se genera el consecutivo.

    Returns:
        String con el número de expediente formateado.

    Raises:
        AssertionError: si tenant es None o no tiene pk (llamada incorrecta).
        RuntimeError: si se llama fuera de un bloque transaction.atomic().
    """
    # FIX-B2: guardia de precondición.
    assert tenant is not None and tenant.pk is not None, (
        "_next_record_number requiere un tenant persistido (pk no None)."
    )
    # FIX-B2: verificar que se está dentro de una transacción atómica.
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError(
            "_next_record_number debe llamarse dentro de transaction.atomic()."
        )

    # all_objects: bypasa el TenantManager para que funcione incluso en contextos
    # sin tenant activo. El SELECT FOR UPDATE es el mecanismo de seguridad real aquí.
    # FIX-B1: get_or_create garantiza exactamente una fila por tenant.
    # Si dos requests compiten en la primera creación, uno obtendrá IntegrityError
    # (capturado por transaction.atomic() + savepoint interno) y el otro seguirá.
    seq_obj, _ = PatientSequence.all_objects.select_for_update().get_or_create(
        tenant=tenant,
        defaults={"last_number": 0, "created_by": None},
    )
    seq_obj.last_number += 1
    seq_obj.save(update_fields=["last_number", "updated_at"])

    year: int = timezone.now().year
    # TODO(3c): leer formato de TenantAgendaConfig.record_number_format
    return f"EXP-{year}-{seq_obj.last_number:05d}"


# ---------------------------------------------------------------------------
# patient_create
# ---------------------------------------------------------------------------


def patient_create(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]  # settings.AUTH_USER_MODEL
    first_name: str,
    paternal_surname: str,
    maternal_surname: str = "",
    date_of_birth: datetime.date,
    sex: str,
    phone: str,
    curp: str = "",
    email: str = "",
    notes: str = "",
) -> Patient:
    """Crea un nuevo paciente en el tenant dado.

    Genera el número de expediente automáticamente usando el mecanismo de
    PatientSequence (SELECT FOR UPDATE) dentro de una transacción atómica.

    Valida:
    - Que el valor de `sex` sea uno de los choices definidos (M/F/X).
    - Que si se provee CURP, no exista ya en el mismo tenant.

    FIX-B1: envuelve toda la creación en transaction.atomic(). Si salta
    IntegrityError por race condition en el record_number único, propaga un
    error de dominio claro.

    Args:
        tenant:            Clínica a la que pertenece el paciente.
        user:              Usuario que crea el registro (para auditoría).
        first_name:        Nombre(s) del paciente.
        paternal_surname:  Apellido paterno.
        maternal_surname:  Apellido materno (opcional, default "").
        date_of_birth:     Fecha de nacimiento.
        sex:               Sexo del paciente: 'M', 'F', o 'X'.
        phone:             Teléfono de contacto.
        curp:              CURP (opcional, default ""). Si se provee, debe ser único en el tenant.
        email:             Correo electrónico (opcional, default "").
        notes:             Notas internas (opcional, default "").

    Returns:
        La instancia Patient recién creada y guardada.

    Raises:
        ValidationError: si el sexo es inválido o la CURP ya existe en el tenant.
    """
    # Validar el sex antes de crear para dar un error claro.
    valid_sex_values = [choice[0] for choice in Sex.choices]
    if sex not in valid_sex_values:
        raise ValidationError(
            f"Sexo inválido '{sex}'. Debe ser uno de: {', '.join(valid_sex_values)}."
        )

    # FIX-B1: transacción atómica garantiza que _next_record_number y Patient.create
    # ocurren atómicamente. Si el record_number único viola integridad por concurrencia,
    # se captura y se relanza con un error de dominio comprensible.
    try:
        with transaction.atomic():
            # Validar unicidad de CURP dentro del tenant (si se provee).
            if curp:
                duplicate_exists = Patient.all_objects.filter(
                    tenant=tenant,
                    curp=curp,
                    deleted_at__isnull=True,
                ).exists()
                if duplicate_exists:
                    raise ValidationError("Ya existe un paciente con esa CURP en esta clínica.")

            record_number = _next_record_number(tenant)

            patient = Patient.objects.create(
                tenant=tenant,
                created_by=user,
                first_name=first_name,
                paternal_surname=paternal_surname,
                maternal_surname=maternal_surname,
                date_of_birth=date_of_birth,
                sex=sex,
                phone=phone,
                curp=curp,
                email=email,
                record_number=record_number,
                notes=notes,
            )
    except IntegrityError as exc:
        # Puede ocurrir en concurrencia extrema si dos request colisionan en record_number.
        # En ese caso la operación debe reintentarse (la capa de aplicación o el cliente
        # debe reintentar la petición). Aquí elevamos como ValidationError para dar
        # un mensaje limpio al cliente.
        raise ValidationError(
            "Error de concurrencia al generar el número de expediente. Por favor, intente de nuevo."
        ) from exc

    audit_record(
        action=ActionType.PATIENT_CREATE,
        resource_type="Patient",
        actor=user,
        tenant=tenant,
        resource_id=patient.id,
        resource_repr=patient.record_number,  # identificador no-PII (minimización LFPDPPP)
    )
    return patient


# ---------------------------------------------------------------------------
# patient_create_quick — alta provisional desde la agenda
# ---------------------------------------------------------------------------


def patient_create_quick(
    *,
    tenant: Tenant,
    user: "User",  # type: ignore[valid-type]
    first_name: str,
    paternal_surname: str,
    maternal_surname: str = "",
    phone: str = "",
) -> Patient:
    """Crea un expediente PROVISIONAL con datos mínimos (al vuelo desde la agenda).

    Pensado para recepción: agenda con solo el nombre. Marca is_provisional=True
    para que la UI alerte que falta completar fecha de nacimiento, sexo, etc.
    El número de expediente se genera igual que en patient_create.

    No exige fecha de nacimiento ni sexo (quedan vacíos hasta que se complete el
    expediente vía patient_update, que limpia la bandera automáticamente).

    Args:
        tenant:           Clínica del paciente.
        user:             Usuario que crea (auditoría).
        first_name:       Nombre(s).
        paternal_surname: Apellido paterno.
        maternal_surname: Apellido materno (opcional).
        phone:            Teléfono (opcional en provisional).

    Returns:
        El Patient provisional recién creado.

    Raises:
        ValidationError: ante un error de concurrencia en el consecutivo.
    """
    try:
        with transaction.atomic():
            record_number = _next_record_number(tenant)
            patient = Patient.objects.create(
                tenant=tenant,
                created_by=user,
                first_name=first_name,
                paternal_surname=paternal_surname,
                maternal_surname=maternal_surname,
                date_of_birth=None,
                sex="",
                phone=phone,
                record_number=record_number,
                is_provisional=True,
            )
    except IntegrityError as exc:
        raise ValidationError(
            "Error de concurrencia al generar el número de expediente. Por favor, intente de nuevo."
        ) from exc

    audit_record(
        action=ActionType.PATIENT_CREATE,
        resource_type="Patient",
        actor=user,
        tenant=tenant,
        resource_id=patient.id,
        resource_repr=patient.record_number,
        metadata={"provisional": True},
    )
    return patient


# ---------------------------------------------------------------------------
# patient_update
# ---------------------------------------------------------------------------

# Campos que NO se pueden actualizar vía patient_update.
# FIX-B3: is_active y updated_at se agregan a los campos inmutables.
# is_active solo cambia vía patient_deactivate.
# is_provisional NO se setea por el cliente: se gestiona automáticamente aquí.
_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {"record_number", "tenant", "tenant_id", "id", "created_at", "deleted_at", "is_active", "is_provisional", "updated_at"}
)


def patient_update(
    *,
    patient: Patient,
    user: "User",  # type: ignore[valid-type]
    **fields: object,
) -> Patient:
    """Actualiza campos permitidos de un paciente existente.

    No permite modificar record_number, tenant, is_active ni los campos de auditoría.
    Si se cambia la CURP, revalida unicidad dentro del tenant.

    FIX-B3: is_active es inmutable aquí; la desactivación solo ocurre en patient_deactivate.
    FIX-B11: user tipado como User (no Any).

    Args:
        patient: Instancia Patient a actualizar (ya recuperada por el selector).
        user:    Usuario que realiza el cambio (para futura auditoría).
        **fields: Campos y valores a actualizar. Los campos inmutables se rechazan.

    Returns:
        La instancia Patient actualizada.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable, si se
                         provee un sex inválido, o si la nueva CURP ya existe
                         en el tenant.
    """
    # Rechazar explícitamente intentos de modificar campos inmutables.
    attempted_immutable = _IMMUTABLE_FIELDS.intersection(fields.keys())
    if attempted_immutable:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(attempted_immutable))}."
        )

    # Validar sex si se está cambiando.
    if "sex" in fields:
        valid_sex_values = [choice[0] for choice in Sex.choices]
        if fields["sex"] not in valid_sex_values:
            raise ValidationError(
                f"Sexo inválido '{fields['sex']}'. Debe ser uno de: {', '.join(valid_sex_values)}."
            )

    # Revalidar CURP si se está cambiando.
    new_curp: Optional[str] = fields.get("curp")  # type: ignore[assignment]
    if new_curp is not None and new_curp != "" and new_curp != patient.curp:
        duplicate_exists = Patient.all_objects.filter(
            tenant=patient.tenant,
            curp=new_curp,
            deleted_at__isnull=True,
        ).exclude(id=patient.id).exists()
        if duplicate_exists:
            raise ValidationError("Ya existe un paciente con esa CURP en esta clínica.")

    # Aplicar campos.
    for field_name, value in fields.items():
        setattr(patient, field_name, value)

    update_fields = list(fields.keys())

    # Auto-completar: si un expediente provisional ya tiene fecha de nacimiento,
    # sexo y teléfono, deja de ser provisional y la alerta desaparece.
    if patient.is_provisional and patient.date_of_birth and patient.sex and patient.phone:
        patient.is_provisional = False
        update_fields.append("is_provisional")

    # updated_at se gestiona automáticamente (auto_now=True en BaseModel).
    update_fields.append("updated_at")
    patient.save(update_fields=update_fields)

    audit_record(
        action=ActionType.PATIENT_UPDATE,
        resource_type="Patient",
        actor=user,
        tenant=patient.tenant,
        resource_id=patient.id,
        resource_repr=patient.record_number,  # identificador no-PII (minimización LFPDPPP)
        metadata={"changed_fields": sorted(fields.keys())},
    )
    return patient


# ---------------------------------------------------------------------------
# Avatar
# ---------------------------------------------------------------------------


def patient_set_avatar(*, patient: Patient, user: "User", image: object) -> Patient:  # type: ignore[valid-type]
    """Asigna (o reemplaza) la foto del paciente. La imagen ya viene validada por la vista."""
    if patient.avatar:
        patient.avatar.delete(save=False)  # borra el archivo anterior (evita huérfanos)
    patient.avatar = image  # type: ignore[assignment]
    patient.save(update_fields=["avatar", "updated_at"])
    audit_record(
        action=ActionType.PATIENT_UPDATE,
        resource_type="Patient",
        actor=user,
        tenant=patient.tenant,
        resource_id=patient.id,
        resource_repr=patient.record_number,
        metadata={"changed_fields": ["avatar"]},
    )
    return patient


def patient_clear_avatar(*, patient: Patient, user: "User") -> Patient:  # type: ignore[valid-type]
    """Elimina la foto del paciente."""
    if patient.avatar:
        patient.avatar.delete(save=False)
    patient.avatar = None  # type: ignore[assignment]
    patient.save(update_fields=["avatar", "updated_at"])
    audit_record(
        action=ActionType.PATIENT_UPDATE,
        resource_type="Patient",
        actor=user,
        tenant=patient.tenant,
        resource_id=patient.id,
        resource_repr=patient.record_number,
        metadata={"changed_fields": ["avatar"], "cleared": True},
    )
    return patient


# ---------------------------------------------------------------------------
# patient_set_classification
# ---------------------------------------------------------------------------


def patient_set_classification(
    *,
    patient: Patient,
    user: "User",  # type: ignore[valid-type]
    is_favorite: Optional[bool] = None,
    is_vip: Optional[bool] = None,
) -> Patient:
    """Actualiza las clasificaciones de un paciente (favorito y/o VIP).

    Solo modifica los flags que no sean None. Si ambos son None no hace
    ninguna escritura ni auditoría y devuelve el paciente sin cambios.

    Usa save(update_fields=[...]) para actualizar únicamente los campos
    modificados, minimizando el impacto en columnas indexadas.

    Args:
        patient:     Instancia Patient a clasificar (ya recuperada por selector).
        user:        Usuario que realiza la acción (para auditoría).
        is_favorite: True/False para marcar/desmarcar como favorito. None = sin cambio.
        is_vip:      True/False para marcar/desmarcar como VIP. None = sin cambio.

    Returns:
        La instancia Patient (actualizada si hubo cambios, sin modificar si no).
    """
    update_fields: list[str] = []

    if is_favorite is not None:
        patient.is_favorite = is_favorite
        update_fields.append("is_favorite")

    if is_vip is not None:
        patient.is_vip = is_vip
        update_fields.append("is_vip")

    if not update_fields:
        # Nada que cambiar: devolvemos sin tocar la BD.
        return patient

    update_fields.append("updated_at")
    patient.save(update_fields=update_fields)

    audit_record(
        action=ActionType.PATIENT_UPDATE,
        resource_type="Patient",
        actor=user,
        tenant=patient.tenant,
        resource_id=patient.id,
        resource_repr=patient.record_number,
        metadata={"changed_fields": sorted(f for f in update_fields if f != "updated_at")},
    )
    return patient


# ---------------------------------------------------------------------------
# patient_deactivate
# ---------------------------------------------------------------------------


def patient_deactivate(
    *,
    patient: Patient,
    _user: "User",  # type: ignore[valid-type]  # FIX-B11: prefijo _ = no usado aún (audit pendiente)
) -> Patient:
    """Desactiva un paciente (soft disable — NO borra el registro).

    Pone is_active=False. El expediente permanece en la base de datos y es
    recuperable por un administrador. Para borrado lógico completo usar
    deleted_at (no expuesto en esta API).

    Args:
        patient: Instancia Patient a desactivar.
        _user:   Usuario que realiza la acción.
                 Prefijo _ indica que aún no se usa (se conectará a la
                 bitácora de auditoría cuando exista apps/audit).

    Returns:
        La instancia Patient con is_active=False.
    """
    patient.is_active = False
    patient.save(update_fields=["is_active", "updated_at"])

    audit_record(
        action=ActionType.PATIENT_DEACTIVATE,
        resource_type="Patient",
        actor=_user,
        tenant=patient.tenant,
        resource_id=patient.id,
        resource_repr=patient.record_number,  # identificador no-PII (minimización LFPDPPP)
    )
    return patient
