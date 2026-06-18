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
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.recetas.models import Medication, MedicationForm, Prescription, PrescriptionItem, PrescriptionStatus
from apps.tenancy.models import Tenant

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

    med = Medication.objects.create(
        tenant=tenant,
        created_by=user,
        generic_name=generic_name,
        commercial_name=commercial_name.strip(),
        form=form,
        concentration=concentration.strip(),
        presentation=presentation.strip(),
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
) -> Prescription:
    """Emite una receta médica inmutable para un paciente.

    Reglas de negocio:
    - El usuario debe tener un perfil de Doctor activo en el tenant.
      Si no lo tiene, lanza ValidationError("Solo un médico puede emitir recetas.").
    - El paciente debe pertenecer al tenant (anti-IDOR a nivel de servicio).
    - El paciente no puede estar fallecido (is_deceased=True → 400).
    - La receta debe tener al menos 1 ítem.
    - Cada ítem debe tener `indication` y `medication_name` no vacíos.
    - Si se provee appointment_id, debe pertenecer al mismo tenant.
    - Si se provee evolution_note_id, debe pertenecer al mismo tenant.

    Folio consecutivo (thread-safe):
        Dentro de la misma transaction.atomic se hace SELECT FOR UPDATE sobre
        las recetas del tenant para serializar el max(folio)+1. Esto garantiza
        unicidad sin un modelo de contador separado.

    Snapshot de signos vitales (DR-7):
        Llama vital_signs_latest del expediente. Si hay toma, guarda un JSON
        con los campos relevantes. Si no hay, vitals_snapshot = None.

    Bitácora (NOM-024): PRESCRIPTION_CREATE con resource_repr = folio (sin PII).

    Args:
        tenant:           Clínica del contexto activo.
        user:             Usuario que emite la receta (debe tener Doctor activo).
        patient_id:       UUID del paciente.
        items_data:       Lista de dicts con campos del ítem (ver PrescriptionItem).
        appointment_id:   UUID de la cita asociada (opcional).
        evolution_note_id: UUID de la nota de evolución asociada (opcional).
        recommendations:  Texto de recomendaciones al paciente (opcional).

    Returns:
        Instancia de Prescription creada con sus ítems.

    Raises:
        ValidationError: si el usuario no tiene Doctor activo, el paciente no
            existe en el tenant, el paciente está fallecido, no hay ítems,
            o algún ítem está incompleto.
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
        indication = str(item.get("indication", "")).strip()
        if not med_name:
            raise ValidationError(
                f"El ítem #{idx} requiere un nombre de medicamento (medication_name)."
            )
        if not indication:
            raise ValidationError(
                f"El ítem #{idx} requiere la indicación (indication)."
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

    # --- Crear la receta ---
    prescription = Prescription.objects.create(
        tenant=tenant,
        created_by=user,
        patient=patient,
        doctor=doctor,
        appointment=appointment,
        evolution_note=evolution_note,
        folio=next_folio,
        issued_at=timezone.now(),
        recommendations=recommendations.strip(),
        vitals_snapshot=vitals_snapshot,
        status=PrescriptionStatus.ACTIVE,
    )

    # --- Crear los ítems en orden ---
    for order, item_data in enumerate(items_data, start=1):
        # B-3: si viene medication_id (FK a Medication custom), validar que pertenezca
        # al tenant. global_medication_id es global y no requiere validación de tenant.
        raw_medication_id = item_data.get("medication_id")
        if raw_medication_id is not None:
            from apps.recetas.selectors import medication_get

            try:
                medication_get(medication_id=raw_medication_id)
            except Medication.DoesNotExist:
                raise ValidationError(
                    f"El ítem #{order}: el medicamento personalizado indicado "
                    "no existe o no pertenece a esta clínica."
                )

        PrescriptionItem.objects.create(
            tenant=tenant,
            created_by=user,
            prescription=prescription,
            order=order,
            medication_name=str(item_data.get("medication_name", "")).strip(),
            medication_presentation=str(item_data.get("medication_presentation", "")).strip(),
            medication_form=str(item_data.get("medication_form", "")).strip(),
            medication_concentration=str(item_data.get("medication_concentration", "")).strip(),
            global_medication_id=item_data.get("global_medication_id"),
            medication_id=raw_medication_id,
            indication=str(item_data.get("indication", "")).strip(),
            quantity=str(item_data.get("quantity", "")).strip(),
        )

    # --- Bitácora (NOM-024) ---
    actor_role: str = getattr(user, "active_role", "") or ""
    audit_record(
        action=ActionType.PRESCRIPTION_CREATE,
        resource_type="Prescription",
        actor=user,
        tenant=tenant,
        resource_id=prescription.id,
        resource_repr=f"folio={next_folio}",  # NUNCA nombre del paciente ni medicamentos
        description="Receta médica emitida.",
        actor_role=actor_role,
        metadata={
            "folio": next_folio,
            "doctor_id": str(doctor.id),
            "items_count": len(items_data),
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
