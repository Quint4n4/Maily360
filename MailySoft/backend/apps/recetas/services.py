"""
Services de la app recetas — sub-fases B1.1 y B1.2.

Toda escritura del catálogo y de recetas pasa por aquí. Las vistas son delgadas.

Convención: keyword-only args, nombrado acción+entidad.

Decisiones respetadas:
  DR-1 — receta inmutable + anulación con motivo.
  DR-2 — catálogo global + custom por tenant.
  DR-5 — sin borrado físico.
  DR-6 — permisos: el médico emite; el servicio verifica doctor_get_for_user.
  DR-7 — seguridad clínica: el catálogo SOLO almacena identificación farmacéutica.
          La dosis/indicación la escribe el médico en PrescriptionItem.
          La receta congela los signos vitales en vitals_snapshot.

API pública (B1.1):
    medication_create — crea un Medication custom para el tenant activo.

API pública (B1.2):
    prescription_create — emite una receta inmutable con sus ítems.
    prescription_cancel — anula una receta con motivo (baja lógica).

Folio consecutivo por tenant (B1.2 — decisión de diseño):
    Se usa SELECT FOR UPDATE sobre las recetas del tenant dentro de
    transaction.atomic para obtener max(folio)+1 de forma segura ante
    concurrencia. Esto serializa las creaciones simultáneas del mismo tenant
    (cada INSERT espera a que el anterior haga COMMIT), lo cual es aceptable
    porque las recetas no tienen el volumen de inserciones de un log.
    El folio arranca en 1 si el tenant no tiene recetas previas.

REGLA DE PRIVACIDAD (NOM-024):
    Los registros de auditoría NUNCA incluyen PII clínica.
    resource_repr en AuditLog = folio de la receta (número, sin nombre del
    paciente ni medicamentos). Los logs de diagnóstico usan exclusivamente IDs.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.recetas.models import (
    ControlledGroup,
    ItemKind,
    Medication,
    MedicationForm,
    Prescription,
    PrescriptionFormat,
    PrescriptionItem,
    PrescriptionStatus,
    SECTIONS_KEYS,
)
from apps.tenancy.models import Tenant

# ---------------------------------------------------------------------------
# F6 — Vigencia de medicamentos controlados (configurable vía settings)
# ---------------------------------------------------------------------------

#: Vigencia en horas para cada grupo. Configurable en settings como
#: CONTROLLED_VALIDITY_HOURS = {"I": 24, "II": 720, ...}.
#: Grupo I (estupefacientes experimentales): 24 horas.
#: Grupos II–V (psicotrópicos y opioides): 30 días = 720 horas.
_CONTROLLED_VALIDITY_HOURS_DEFAULT: dict[str, int] = {
    ControlledGroup.I: 24,
    ControlledGroup.II: 720,   # 30 días
    ControlledGroup.III: 720,
    ControlledGroup.IV: 720,
    ControlledGroup.V: 720,
}

#: Orden de restrictividad de los grupos (más restrictivo primero).
#: Se usa para determinar cuál grupo manda la vigencia cuando hay varios.
_GROUP_RESTRICTIVENESS: list[str] = [
    ControlledGroup.I,
    ControlledGroup.II,
    ControlledGroup.III,
    ControlledGroup.IV,
    ControlledGroup.V,
]


def _get_controlled_validity_hours() -> dict[str, int]:
    """Devuelve el mapa de vigencia desde settings o los defaults.

    Permite override en settings.py: CONTROLLED_VALIDITY_HOURS = {"I": 24, ...}
    """
    overrides: dict[str, int] = getattr(
        django_settings, "CONTROLLED_VALIDITY_HOURS", {}
    ) or {}
    merged = dict(_CONTROLLED_VALIDITY_HOURS_DEFAULT)
    merged.update(overrides)
    return merged


def _most_restrictive_group(groups: set[str]) -> str | None:
    """Retorna el grupo más restrictivo (más corta vigencia) del conjunto dado.

    Args:
        groups: conjunto de valores de ControlledGroup presentes en la receta
                (ya filtrados para excluir 'none').

    Returns:
        El grupo más restrictivo como string, o None si el conjunto está vacío.
    """
    for group in _GROUP_RESTRICTIVENESS:
        if group in groups:
            return group
    return None


def _calculate_valid_until(
    *,
    issued_at: datetime,
    groups: set[str],
) -> datetime | None:
    """Calcula valid_until según el grupo más restrictivo.

    Args:
        issued_at: fecha/hora de emisión de la receta.
        groups:    grupos controlados presentes (excluye 'none').

    Returns:
        datetime de expiración, o None si no hay grupos controlados.
    """
    top_group = _most_restrictive_group(groups)
    if top_group is None:
        return None
    hours = _get_controlled_validity_hours().get(top_group, 720)
    return issued_at + timedelta(hours=hours)

logger = logging.getLogger("apps.recetas.services")


@transaction.atomic
def medication_create(
    *,
    tenant: Tenant,
    user: Any,
    generic_name: str,
    form: str,
    commercial_name: str = "",
    concentration: str = "",
    presentation: str = "",
    kind: str = "medicamento",
) -> Medication:
    """Crea un medicamento custom para la clínica indicada.

    Valida:
    - generic_name no vacío (requerido).
    - form es un valor válido de MedicationForm (choices — defensa en profundidad
      aunque el serializer ya lo valida).
    - tenant no es None.

    No valida concentration/presentation en contenido (texto libre del médico).

    La dosis, indicación o contraindicación NUNCA se almacena aquí (DR-7).

    Bitácora: MEDICATION_CREATE con resource_repr = str(med.id) (nunca PII).

    Args:
        tenant:          Clínica del contexto activo.
        user:            Usuario que crea el medicamento (snapshot de actor en audit).
        generic_name:    Nombre genérico requerido.
        form:            Forma farmacéutica (valor de MedicationForm).
        commercial_name: Nombre comercial (opcional).
        concentration:   Concentración estándar (opcional).
        presentation:    Presentación comercial (opcional).
        kind:            Tipo de ítem: medicamento, suero o terapia (COFEPRIS F2).

    Returns:
        Instancia de Medication creada.

    Raises:
        ValidationError: si generic_name está vacío, form es inválido o tenant es None.
    """
    if tenant is None:
        raise ValidationError("medication_create requiere un tenant explícito.")

    generic_name = generic_name.strip()
    if not generic_name:
        raise ValidationError("El nombre genérico del medicamento no puede estar vacío.")

    valid_forms = {choice[0] for choice in MedicationForm.choices}
    if form not in valid_forms:
        raise ValidationError(
            f"Forma farmacéutica '{form}' inválida. "
            f"Valores aceptados: {', '.join(sorted(valid_forms))}."
        )

    valid_kinds = {choice[0] for choice in ItemKind.choices}
    if kind not in valid_kinds:
        raise ValidationError(
            f"Tipo de ítem '{kind}' inválido. "
            f"Valores aceptados: {', '.join(sorted(valid_kinds))}."
        )

    med = Medication.objects.create(
        tenant=tenant,
        created_by=user,
        generic_name=generic_name,
        commercial_name=commercial_name.strip(),
        form=form,
        concentration=concentration.strip(),
        presentation=presentation.strip(),
        kind=kind,
        is_active=True,
    )

    # actor_role: toma el rol del request adjuntado en TenantAPIView.check_permissions.
    # En contextos fuera de HTTP (Celery, management commands) este atributo no existe.
    actor_role: str = getattr(user, "active_role", "") or ""

    audit_record(
        action=ActionType.MEDICATION_CREATE,
        resource_type="Medication",
        actor=user,
        tenant=tenant,
        resource_id=med.id,
        resource_repr=str(med.id),  # NUNCA el nombre (privacidad clínica)
        description="Medicamento custom creado.",
        actor_role=actor_role,
    )

    logger.info(
        "medication_create: id=%s tenant=%s",
        med.id,
        tenant.id,
    )

    return med


# ---------------------------------------------------------------------------
# prescription_create (B1.2)
# ---------------------------------------------------------------------------


@transaction.atomic
def prescription_create(
    *,
    tenant: Tenant,
    user: Any,
    patient_id: Any,
    items_data: list[dict[str, Any]],
    appointment_id: Any = None,
    evolution_note_id: Any = None,
    recommendations: str = "",
    diagnosis: str = "",
    controlled_folio: str = "",
) -> Prescription:
    """Emite una receta médica inmutable para un paciente.

    Reglas de negocio:
    - El usuario debe tener un perfil de Doctor activo en el tenant.
      Si no lo tiene, lanza PermissionDenied (HTTP 403).
    - El paciente debe pertenecer al tenant (anti-IDOR a nivel de servicio).
    - El paciente no puede estar fallecido (is_deceased=True → 400).
    - La receta debe tener al menos 1 ítem.
    - Cada ítem debe tener `medication_name` no vacío.
    - Si se provee appointment_id, debe pertenecer al mismo tenant.
    - Si se provee evolution_note_id, debe pertenecer al mismo tenant.

    F6 — Medicamentos controlados:
    - Se copia el controlled_group del catálogo a cada ítem (snapshot DR-7).
    - Si la receta es controlada (algún ítem controlled_group != 'none'):
      * controlled_folio es OBLIGATORIO → ValidationError 400 si falta.
      * valid_until se calcula según el grupo más restrictivo:
        Grupo I → 24 horas desde issued_at.
        Grupos II–V → 30 días desde issued_at.
    - Si la receta no es controlada: valid_until = None.
    - Auditoría reforzada: PRESCRIPTION_CONTROLLED_CREATE para recetas controladas.

    Folio consecutivo (thread-safe):
        Dentro de la misma transaction.atomic se hace SELECT FOR UPDATE sobre
        las recetas del tenant para serializar el max(folio)+1.

    Snapshot de signos vitales (DR-7):
        Llama vital_signs_latest del expediente. Si hay toma, guarda un JSON
        con los campos relevantes. Si no hay, vitals_snapshot = None.

    Bitácora (NOM-024): PRESCRIPTION_CREATE o PRESCRIPTION_CONTROLLED_CREATE
    con resource_repr = folio (sin PII).

    Args:
        tenant:            Clínica del contexto activo.
        user:              Usuario que emite la receta (debe tener Doctor activo).
        patient_id:        UUID del paciente.
        items_data:        Lista de dicts con campos del ítem (ver PrescriptionItem).
        appointment_id:    UUID de la cita asociada (opcional).
        evolution_note_id: UUID de la nota de evolución asociada (opcional).
        recommendations:   Texto de recomendaciones al paciente (opcional).
        diagnosis:         Diagnóstico del paciente (opcional, recomendado COFEPRIS F2).
        controlled_folio:  Folio del recetario especial COFEPRIS (requerido si la receta
                           contiene medicamentos controlados; el médico lo ingresa).

    Returns:
        Instancia de Prescription creada con sus ítems.

    Raises:
        ValidationError:  si el paciente no existe, está fallecido, no hay ítems,
                          algún ítem está incompleto, o la receta es controlada
                          y no se proporcionó controlled_folio.
        PermissionDenied: si el usuario no tiene Doctor activo en el tenant.
    """
    import uuid as uuid_module

    from apps.expediente.selectors import vital_signs_latest
    from apps.pacientes.models import Patient
    from apps.personal.selectors import doctor_get_for_user

    # --- Verificar que el usuario tiene Doctor activo en el tenant (M-2) ---
    # Error de AUTORIZACIÓN → PermissionDenied (HTTP 403), no ValidationError (400).
    doctor = doctor_get_for_user(user=user, tenant_id=tenant.id)
    if doctor is None:
        raise PermissionDenied(
            "Solo un médico puede emitir recetas. "
            "El usuario no tiene un perfil de médico activo en esta clínica."
        )

    # --- Verificar que el paciente existe y pertenece al tenant ---
    try:
        patient = Patient.objects.get(id=patient_id, tenant=tenant)
    except Patient.DoesNotExist:
        raise ValidationError("Paciente no encontrado en esta clínica.")

    # Defensa anti-IDOR adicional: tenant explícito
    if patient.tenant_id != tenant.id:
        raise ValidationError("Paciente no encontrado en esta clínica.")

    # --- Verificar que el paciente no está fallecido ---
    if getattr(patient, "is_deceased", False):
        raise ValidationError(
            "No se puede emitir una receta para un paciente fallecido."
        )

    # --- Validar ítems ---
    if not items_data:
        raise ValidationError(
            "La receta debe contener al menos un medicamento (ítem)."
        )

    for idx, item in enumerate(items_data, start=1):
        med_name = str(item.get("medication_name", "")).strip()
        if not med_name:
            raise ValidationError(
                f"El ítem #{idx} requiere un nombre de medicamento (medication_name)."
            )
        # COFEPRIS F2: validación condicional en el service (defensa en profundidad).
        # El serializer ya la aplica; aquí la repetimos para paths que llamen al service
        # directamente (Celery, tests, management commands).
        item_kind = str(item.get("kind", "medicamento"))
        if item_kind == "medicamento":
            missing_cofepris: list[str] = []
            if not str(item.get("dose", "")).strip():
                missing_cofepris.append("dose")
            if not str(item.get("frequency", "")).strip():
                missing_cofepris.append("frequency")
            if not str(item.get("route", "")).strip():
                missing_cofepris.append("route")
            if not str(item.get("duration", "")).strip():
                missing_cofepris.append("duration")
            if missing_cofepris:
                raise ValidationError(
                    f"El ítem #{idx} (medicamento) requiere los campos COFEPRIS: "
                    f"{', '.join(missing_cofepris)}."
                )

    # --- Resolver appointment (opcional, validar tenant y que pertenezca al mismo paciente — M-1) ---
    appointment = None
    if appointment_id is not None:
        from apps.agenda.models import Appointment

        try:
            appointment = Appointment.objects.get(id=appointment_id, tenant=tenant)
        except Appointment.DoesNotExist:
            raise ValidationError("La cita indicada no existe en esta clínica.")

        # M-1: la cita debe pertenecer al mismo paciente de la receta.
        if appointment.patient_id != patient.id:
            raise ValidationError(
                "La cita no pertenece al paciente de esta receta."
            )

    # --- Resolver evolution_note (opcional, validar tenant y que pertenezca al mismo paciente — M-1) ---
    evolution_note = None
    if evolution_note_id is not None:
        from apps.expediente.models import EvolutionNote

        try:
            evolution_note = EvolutionNote.objects.get(
                id=evolution_note_id, tenant=tenant
            )
        except EvolutionNote.DoesNotExist:
            raise ValidationError(
                "La nota de evolución indicada no existe en esta clínica."
            )

        # M-1: la nota de evolución debe pertenecer al mismo paciente de la receta.
        if evolution_note.patient_id != patient.id:
            raise ValidationError(
                "La nota de evolución no pertenece al paciente de esta receta."
            )

    # --- Generar folio consecutivo (SELECT FOR UPDATE — thread-safe) ---
    # Bloqueamos las filas del tenant para que dos creates simultáneos
    # no obtengan el mismo max(folio). El lock se libera con el COMMIT
    # de la transacción externa (atomic).
    max_folio_result = (
        Prescription.all_objects.select_for_update()
        .filter(tenant=tenant)
        .aggregate(max_folio=Max("folio"))
    )
    next_folio: int = (max_folio_result["max_folio"] or 0) + 1

    # --- Snapshot de signos vitales (DR-7) ---
    vitals_snapshot = None
    latest_vitals = vital_signs_latest(patient=patient)
    if latest_vitals is not None:
        imc: Decimal | None = None
        if latest_vitals.weight_kg is not None and latest_vitals.height_m not in (
            None,
            0,
        ):
            imc = (
                Decimal(str(latest_vitals.weight_kg))
                / (Decimal(str(latest_vitals.height_m)) ** 2)
            ).quantize(Decimal("0.01"))

        vitals_snapshot = {
            "weight_kg": float(latest_vitals.weight_kg) if latest_vitals.weight_kg is not None else None,
            "height_m": float(latest_vitals.height_m) if latest_vitals.height_m is not None else None,
            "imc": float(imc) if imc is not None else None,
            "heart_rate": latest_vitals.heart_rate,
            "resp_rate": latest_vitals.resp_rate,
            "systolic": latest_vitals.systolic,
            "diastolic": latest_vitals.diastolic,
            "temperature_c": float(latest_vitals.temperature_c) if latest_vitals.temperature_c is not None else None,
            "oxygen_saturation": latest_vitals.oxygen_saturation,
            "glucose": latest_vitals.glucose,
            "measured_at": latest_vitals.measured_at.isoformat(),
        }

    # --- F6: resolver controlled_group snapshot por ítem desde el catálogo ---
    # Para cada ítem se determina el grupo controlado en este orden de prioridad:
    #   1. Si trae global_medication_id → lee controlled_group del catálogo global.
    #   2. Si trae medication_id (custom) → lee controlled_group de ese Medication.
    #   3. Si trae controlled_group explícito en el dict → lo usa directamente.
    #   4. Fallback: 'none'.
    # Siempre es un snapshot (DR-7): inmutable aunque el catálogo cambie.
    from apps.recetas.models import GlobalMedication

    valid_groups = {c[0] for c in ControlledGroup.choices}
    item_resolved_groups: list[str] = []  # group por cada ítem (pre-CREATE)

    for idx, item_data in enumerate(items_data, start=1):
        raw_global_id = item_data.get("global_medication_id")
        raw_med_id = item_data.get("medication_id")
        raw_group = str(item_data.get("controlled_group", ControlledGroup.NONE)).strip()

        resolved_group = ControlledGroup.NONE

        if raw_global_id is not None:
            try:
                gm = GlobalMedication.objects.only("controlled_group").get(id=raw_global_id)
                resolved_group = gm.controlled_group
            except GlobalMedication.DoesNotExist:
                pass  # snapshot conserva 'none'; la FK queda inválida (se validará en create)

        elif raw_med_id is not None:
            try:
                cm = Medication.objects.only("controlled_group", "tenant_id").get(
                    id=raw_med_id, tenant=tenant
                )
                resolved_group = cm.controlled_group
            except Medication.DoesNotExist:
                raise ValidationError(
                    f"El ítem #{idx}: el medicamento personalizado indicado "
                    "no existe o no pertenece a esta clínica."
                )

        elif raw_group in valid_groups and raw_group != ControlledGroup.NONE:
            # Valor explícito: solo se acepta si no hay FK (texto libre sin catálogo).
            resolved_group = raw_group

        item_resolved_groups.append(resolved_group)

    # --- F6: determinar si la receta es controlada ---
    controlled_groups_present: set[str] = {
        g for g in item_resolved_groups if g != ControlledGroup.NONE
    }
    is_controlled_rx: bool = bool(controlled_groups_present)

    # --- F6: validar controlled_folio si hay medicamentos controlados ---
    controlled_folio_clean: str = controlled_folio.strip() if controlled_folio else ""
    if is_controlled_rx and not controlled_folio_clean:
        raise ValidationError(
            "La receta contiene medicamentos controlados (COFEPRIS). "
            "Es obligatorio ingresar el folio del recetario especial (controlled_folio) "
            "emitido por COFEPRIS. Sin este folio la receta no puede ser emitida."
        )

    # --- F6: calcular vigencia según grupo más restrictivo ---
    issued_at_ts = timezone.now()
    valid_until_dt = _calculate_valid_until(
        issued_at=issued_at_ts,
        groups=controlled_groups_present,
    ) if is_controlled_rx else None

    # --- Crear la receta ---
    prescription = Prescription.objects.create(
        tenant=tenant,
        created_by=user,
        patient=patient,
        doctor=doctor,
        appointment=appointment,
        evolution_note=evolution_note,
        folio=next_folio,
        issued_at=issued_at_ts,
        diagnosis=diagnosis.strip(),
        recommendations=recommendations.strip(),
        vitals_snapshot=vitals_snapshot,
        status=PrescriptionStatus.ACTIVE,
        # F6
        controlled_folio=controlled_folio_clean,
        valid_until=valid_until_dt,
    )

    # --- Crear los ítems en orden (con snapshot de controlled_group — F6/DR-7) ---
    for order, (item_data, resolved_group) in enumerate(
        zip(items_data, item_resolved_groups), start=1
    ):
        raw_medication_id = item_data.get("medication_id")

        # Si ya validamos el medication_id arriba en la resolución de grupos, no
        # necesitamos volver a validar. Solo casos donde raw_medication_id esté
        # presente pero NO había global_medication_id (ya cubierto arriba).
        # La excepción se lanzaría en la resolución, así que aquí es seguro continuar.

        PrescriptionItem.objects.create(
            tenant=tenant,
            created_by=user,
            prescription=prescription,
            order=order,
            kind=str(item_data.get("kind", "medicamento")),
            medication_name=str(item_data.get("medication_name", "")).strip(),
            medication_presentation=str(item_data.get("medication_presentation", "")).strip(),
            medication_form=str(item_data.get("medication_form", "")).strip(),
            medication_concentration=str(item_data.get("medication_concentration", "")).strip(),
            global_medication_id=item_data.get("global_medication_id"),
            medication_id=raw_medication_id,
            # COFEPRIS F2: renglón estructurado
            dose=str(item_data.get("dose", "")).strip(),
            frequency=str(item_data.get("frequency", "")).strip(),
            route=str(item_data.get("route", "")).strip(),
            duration=str(item_data.get("duration", "")).strip(),
            # Nota/observación (antes obligatorio, ahora opcional)
            indication=str(item_data.get("indication", "")).strip(),
            quantity=str(item_data.get("quantity", "")).strip(),
            # F6: snapshot del grupo COFEPRIS (DR-7)
            controlled_group=resolved_group,
        )

    # --- Bitácora (NOM-024) — reforzada para recetas controladas (F6) ---
    actor_role: str = getattr(user, "active_role", "") or ""
    top_group = _most_restrictive_group(controlled_groups_present) or ""
    audit_action = (
        ActionType.PRESCRIPTION_CONTROLLED_CREATE
        if is_controlled_rx
        else ActionType.PRESCRIPTION_CREATE
    )
    audit_description = (
        f"Receta médica con medicamento controlado emitida (grupo {top_group})."
        if is_controlled_rx
        else "Receta médica emitida."
    )
    audit_record(
        action=audit_action,
        resource_type="Prescription",
        actor=user,
        tenant=tenant,
        resource_id=prescription.id,
        resource_repr=f"folio={next_folio}",  # NUNCA nombre del paciente ni medicamentos
        description=audit_description,
        actor_role=actor_role,
        metadata={
            "folio": next_folio,
            "doctor_id": str(doctor.id),
            "items_count": len(items_data),
            "controlled": is_controlled_rx,
            **({"controlled_group_top": top_group} if is_controlled_rx else {}),
        },
    )

    logger.info(
        "prescription_create: id=%s folio=%s tenant=%s doctor=%s",
        prescription.id,
        next_folio,
        tenant.id,
        doctor.id,
    )

    return prescription


# ---------------------------------------------------------------------------
# prescription_cancel (B1.2)
# ---------------------------------------------------------------------------


@transaction.atomic
def prescription_cancel(
    *,
    prescription: Prescription,
    user: Any,
    tenant: Tenant,
    reason: str,
) -> Prescription:
    """Anula una receta médica (baja lógica con motivo).

    Reglas de negocio:
    - La receta ya debe pertenecer al tenant (el selector garantiza esto; el
      servicio valida explícitamente como defensa en profundidad).
    - La receta no puede estar ya anulada (400 si status=cancelled).
    - El actor debe ser: el médico emisor (prescription.doctor) OR owner/admin.
      Otro médico no puede anular una receta ajena.
    - `reason` es requerido (no puede estar vacío).

    Bitácora (NOM-024): PRESCRIPTION_CANCEL con resource_repr = folio.

    Args:
        prescription: Instancia de Prescription a anular (del selector).
        user:         Usuario que anula.
        tenant:       Tenant del contexto (defensa en profundidad).
        reason:       Motivo de la anulación (requerido).

    Returns:
        Instancia de Prescription con status=cancelled.

    Raises:
        ValidationError: si la receta ya está anulada, el motivo está vacío,
            o el usuario no tiene permiso para anular esa receta.
    """
    from apps.personal.selectors import doctor_get_for_user
    from apps.tenancy.models import TenantMembership

    # --- Defensa en profundidad: la receta debe pertenecer al tenant ---
    if prescription.tenant_id != tenant.id:
        raise ValidationError("Receta no encontrada.")

    # --- No se puede anular dos veces ---
    if prescription.status == PrescriptionStatus.CANCELLED:
        raise ValidationError("La receta ya fue anulada.")

    # --- Validar motivo ---
    reason = reason.strip()
    if not reason:
        raise ValidationError("El motivo de anulación es requerido.")

    # --- Validar autorización: solo el médico emisor o owner/admin puede anular ---
    active_role: str = getattr(user, "active_role", "") or ""
    is_manager = active_role in (
        TenantMembership.Role.OWNER,
        TenantMembership.Role.ADMIN,
    )

    if not is_manager:
        # El doctor que anula debe ser el mismo que emitió la receta.
        # Error de AUTORIZACIÓN → PermissionDenied (HTTP 403), no ValidationError (400). (M-2)
        doctor = doctor_get_for_user(user=user, tenant_id=tenant.id)
        if doctor is None or doctor.id != prescription.doctor_id:
            raise PermissionDenied(
                "Solo el médico emisor o un administrador puede anular esta receta."
            )

    # --- Anular ---
    prescription.status = PrescriptionStatus.CANCELLED
    prescription.cancelled_at = timezone.now()
    prescription.cancelled_by = user
    prescription.cancellation_reason = reason
    prescription.save(
        update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_reason", "updated_at"]
    )

    # --- Bitácora (NOM-024) ---
    actor_role: str = getattr(user, "active_role", "") or ""
    audit_record(
        action=ActionType.PRESCRIPTION_CANCEL,
        resource_type="Prescription",
        actor=user,
        tenant=tenant,
        resource_id=prescription.id,
        resource_repr=f"folio={prescription.folio}",  # NUNCA PII
        description="Receta médica anulada.",
        actor_role=actor_role,
        metadata={
            "folio": prescription.folio,
            "doctor_id": str(prescription.doctor_id),
        },
    )

    logger.info(
        "prescription_cancel: id=%s folio=%s tenant=%s by=%s",
        prescription.id,
        prescription.folio,
        tenant.id,
        getattr(user, "pk", "?"),
    )

    return prescription


# ---------------------------------------------------------------------------
# PrescriptionFormat services (F3)
# ---------------------------------------------------------------------------

#: Campos que nunca se modifican vía PATCH (inmutables en update).
_FORMAT_IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "updated_at", "deleted_at", "is_active"}
)


@transaction.atomic
def prescription_format_create(
    *,
    tenant: Tenant,
    user: Any,
    name: str,
    base_layout: str = "standard",
    accent_color: str = "#9A7B1E",
    font: str = "helvetica",
    sections: dict[str, bool] | None = None,
    letterhead_mode: str = "digital",
    is_default: bool = False,
    doctor_id: Any = None,
) -> PrescriptionFormat:
    """Crea un PrescriptionFormat para el tenant.

    Valida:
    - name no vacío.
    - accent_color con regex #RRGGBB.
    - base_layout, font, letterhead_mode contra choices.
    - sections contra la whitelist (keys en SECTIONS_KEYS, valores bool).
    - Si doctor_id viene, el Doctor debe pertenecer al mismo tenant (anti-IDOR).
    - Si is_default=True, desmarca el anterior default del tenant dentro de la
      misma transacción.

    Bitácora: FORMAT_CREATE.

    Args:
        tenant:          Clínica del contexto activo.
        user:            Usuario que crea el formato.
        name:            Nombre descriptivo del formato.
        base_layout:     Layout base ("standard", "compact", "digital").
        accent_color:    Color de acento en hex (#RRGGBB).
        font:            Tipografía ("helvetica", "times").
        sections:        Dict de flags de secciones (keys en SECTIONS_KEYS, vals bool).
        letterhead_mode: Modo de membrete ("digital" | "preprinted").
        is_default:      Si True, establece como default (y desmarca el anterior).
        doctor_id:       UUID del Doctor (FK opcional). Debe pertenecer al tenant.

    Returns:
        Instancia de PrescriptionFormat creada.

    Raises:
        ValidationError: si algún campo es inválido.
    """
    from apps.personal.models import Doctor

    name = name.strip()
    if not name:
        raise ValidationError("El nombre del formato no puede estar vacío.")

    _validate_format_fields(
        accent_color=accent_color,
        base_layout=base_layout,
        font=font,
        letterhead_mode=letterhead_mode,
        sections=sections or {},
    )

    # Resolver doctor (FK opcional, validar tenant — defensa en profundidad).
    doctor = None
    if doctor_id is not None:
        try:
            doctor = Doctor.objects.get(id=doctor_id, tenant=tenant, deleted_at__isnull=True)
        except Doctor.DoesNotExist:
            raise ValidationError(
                "El médico indicado no existe o no pertenece a esta clínica."
            )
        if doctor.tenant_id != tenant.id:
            raise ValidationError(
                "El médico indicado no pertenece a esta clínica."
            )

    # Si is_default=True, desmarcar el anterior default del tenant.
    if is_default:
        PrescriptionFormat.all_objects.filter(
            tenant=tenant,
            is_default=True,
            deleted_at__isnull=True,
        ).update(is_default=False)

    fmt = PrescriptionFormat.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        base_layout=base_layout,
        accent_color=accent_color,
        font=font,
        sections=sections or {},
        letterhead_mode=letterhead_mode,
        is_default=is_default,
        doctor=doctor,
        is_authorized=False,  # siempre False al crear; admin lo activa luego
        is_active=True,
    )

    actor_role: str = getattr(user, "active_role", "") or ""
    audit_record(
        action=ActionType.FORMAT_CREATE,
        resource_type="PrescriptionFormat",
        actor=user,
        tenant=tenant,
        resource_id=fmt.id,
        resource_repr=f"format={fmt.id}",
        description="Formato de receta creado.",
        actor_role=actor_role,
        metadata={"name": fmt.name, "base_layout": fmt.base_layout},
    )

    logger.info(
        "prescription_format_create: id=%s name=%r tenant=%s",
        fmt.id,
        fmt.name,
        tenant.id,
    )

    return fmt


@transaction.atomic
def prescription_format_update(
    *,
    fmt: PrescriptionFormat,
    user: Any,
    tenant: Tenant,
    is_admin: bool = False,
    **fields: Any,
) -> PrescriptionFormat:
    """Actualiza un PrescriptionFormat.

    Reglas:
    - Los campos en _FORMAT_IMMUTABLE_FIELDS no se pueden modificar.
    - is_authorized solo lo puede cambiar un owner/admin (is_admin=True).
    - Si is_default=True, desmarca el anterior default del tenant.
    - Valida los campos que se cambien (accent_color, sections, choices).
    - El formato debe pertenecer al tenant (defensa en profundidad).

    Args:
        fmt:      Instancia de PrescriptionFormat a actualizar (del selector).
        user:     Usuario que actualiza.
        tenant:   Tenant del contexto (defensa en profundidad).
        is_admin: True si el usuario es owner o admin.
        **fields: Campos a actualizar.

    Returns:
        Instancia actualizada.

    Raises:
        ValidationError: si campo inmutable, is_authorized sin permisos, o
            cualquier campo tiene valor inválido.
    """
    # Defensa en profundidad: el formato debe pertenecer al tenant.
    if fmt.tenant_id != tenant.id:
        raise ValidationError("Formato no encontrado.")

    bad = set(fields) & _FORMAT_IMMUTABLE_FIELDS
    if bad:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(bad))}."
        )

    # is_authorized solo puede cambiarlo un admin/owner.
    if "is_authorized" in fields and not is_admin:
        raise ValidationError(
            "Solo un administrador puede autorizar el formato personal de un médico."
        )

    # Validaciones de campos recibidos.
    _validate_format_fields(
        accent_color=fields.get("accent_color", fmt.accent_color),
        base_layout=fields.get("base_layout", fmt.base_layout),
        font=fields.get("font", fmt.font),
        letterhead_mode=fields.get("letterhead_mode", fmt.letterhead_mode),
        sections=fields.get("sections", fmt.sections or {}),
    )

    # Si se marca como default, desmarcar el anterior.
    if fields.get("is_default"):
        PrescriptionFormat.all_objects.filter(
            tenant=tenant,
            is_default=True,
            deleted_at__isnull=True,
        ).exclude(id=fmt.id).update(is_default=False)

    # Resolver nuevo doctor_id si viene.
    has_doctor_id = "doctor_id" in fields
    new_doctor_id = fields.pop("doctor_id", None)
    if has_doctor_id:
        if new_doctor_id is None:
            fmt.doctor = None
        else:
            from apps.personal.models import Doctor

            try:
                doctor = Doctor.objects.get(
                    id=new_doctor_id, tenant=tenant, deleted_at__isnull=True
                )
            except Doctor.DoesNotExist:
                raise ValidationError(
                    "El médico indicado no existe o no pertenece a esta clínica."
                )
            if doctor.tenant_id != tenant.id:
                raise ValidationError(
                    "El médico indicado no pertenece a esta clínica."
                )
            fmt.doctor = doctor

    for key, value in fields.items():
        setattr(fmt, key, value)

    update_fields_set = set(fields.keys())
    if has_doctor_id:
        update_fields_set.add("doctor")
    update_fields = list(update_fields_set) + ["updated_at"]

    fmt.full_clean()
    fmt.save(update_fields=update_fields)

    actor_role: str = getattr(user, "active_role", "") or ""
    audit_record(
        action=ActionType.FORMAT_UPDATE,
        resource_type="PrescriptionFormat",
        actor=user,
        tenant=tenant,
        resource_id=fmt.id,
        resource_repr=f"format={fmt.id}",
        description="Formato de receta actualizado.",
        actor_role=actor_role,
        metadata={"changed_fields": list(fields.keys())},
    )

    logger.info(
        "prescription_format_update: id=%s tenant=%s",
        fmt.id,
        tenant.id,
    )

    return fmt


@transaction.atomic
def prescription_format_delete(
    *,
    fmt: PrescriptionFormat,
    user: Any,
    tenant: Tenant,
) -> PrescriptionFormat:
    """Baja lógica de un PrescriptionFormat (is_active=False + deleted_at).

    El formato se conserva en BD (DR-5); solo se oculta de los listados normales.
    Si era el default del tenant, queda sin default (la resolución caerá al
    formato de fábrica).

    Args:
        fmt:    Instancia de PrescriptionFormat a dar de baja.
        user:   Usuario que realiza la baja.
        tenant: Tenant del contexto (defensa en profundidad).

    Returns:
        Instancia actualizada con is_active=False.

    Raises:
        ValidationError: si el formato ya está inactivo o no pertenece al tenant.
    """
    if fmt.tenant_id != tenant.id:
        raise ValidationError("Formato no encontrado.")

    if not fmt.is_active:
        raise ValidationError("El formato ya está inactivo.")

    from django.utils import timezone as _tz

    fmt.is_active = False
    fmt.is_default = False
    fmt.deleted_at = _tz.now()
    fmt.save(update_fields=["is_active", "is_default", "deleted_at", "updated_at"])

    actor_role: str = getattr(user, "active_role", "") or ""
    audit_record(
        action=ActionType.FORMAT_DELETE,
        resource_type="PrescriptionFormat",
        actor=user,
        tenant=tenant,
        resource_id=fmt.id,
        resource_repr=f"format={fmt.id}",
        description="Formato de receta dado de baja.",
        actor_role=actor_role,
    )

    logger.info(
        "prescription_format_delete: id=%s tenant=%s",
        fmt.id,
        tenant.id,
    )

    return fmt


# ---------------------------------------------------------------------------
# Helpers internos de validación F3
# ---------------------------------------------------------------------------


def _validate_format_fields(
    *,
    accent_color: str,
    base_layout: str,
    font: str,
    letterhead_mode: str,
    sections: dict[str, bool],
) -> None:
    """Valida los campos de PrescriptionFormat. Lanza ValidationError si falla.

    Usado en prescription_format_create y prescription_format_update.
    El serializer ya valida, pero esta función da defensa en profundidad para
    llamadas directas desde Celery/commands/tests.
    """
    import re as _re

    _HEX = _re.compile(r"^#[0-9A-Fa-f]{6}$")
    if accent_color and not _HEX.match(accent_color):
        raise ValidationError(
            "El color de acento debe tener el formato #RRGGBB (ej: #9A7B1E)."
        )

    valid_layouts = {c[0] for c in PrescriptionFormat.BaseLayout.choices}
    if base_layout not in valid_layouts:
        raise ValidationError(
            f"base_layout '{base_layout}' inválido. Valores: {', '.join(sorted(valid_layouts))}."
        )

    valid_fonts = {c[0] for c in PrescriptionFormat.FontChoice.choices}
    if font not in valid_fonts:
        raise ValidationError(
            f"font '{font}' inválido. Valores: {', '.join(sorted(valid_fonts))}."
        )

    valid_modes = {c[0] for c in PrescriptionFormat.LetterheadMode.choices}
    if letterhead_mode not in valid_modes:
        raise ValidationError(
            f"letterhead_mode '{letterhead_mode}' inválido. "
            f"Valores: {', '.join(sorted(valid_modes))}."
        )

    unknown_keys = set(sections.keys()) - SECTIONS_KEYS
    if unknown_keys:
        raise ValidationError(
            f"Claves desconocidas en sections: {', '.join(sorted(unknown_keys))}. "
            f"Permitidas: {', '.join(sorted(SECTIONS_KEYS))}."
        )
    for key, val in sections.items():
        if not isinstance(val, bool):
            raise ValidationError(
                f"El valor de sections.{key} debe ser booleano."
            )
