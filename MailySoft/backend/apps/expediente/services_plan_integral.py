"""
Services del Plan Integral de Longevidad y Medicina Regenerativa (Fase 1-4).

Constancia entregable al paciente, análoga al Resumen Clínico
(services_resumen.py) pero COMPUESTA de módulos ya existentes del expediente
en lugar de nacer de una consulta:

    alergias              — apps.expediente.selectors.allergy_list.
    antecedentes / tratamientos_actuales / condiciones a mejorar
                           — apps.expediente.selectors.medical_history_get_for_patient.
    esquema de tratamientos — apps.expediente.selectors.treatment_plan_get/list
                              (opcional; snapshot al momento de crear).
    lab_results/gabinete_studies — capturados por el médico en el POST (Fase 3);
                              lab_results puede referenciar apps.expediente.LabAnalyte
                              (opcional) para heredar su rango de referencia.
    equipo                 — apps.clinica.selectors.clinic_team_list (Fase 4;
                              config-driven, snapshoteado SIEMPRE del catálogo
                              vigente, el cliente nunca lo envía).

API pública:
    longevity_plan_draft  — arma el borrador auto-rellenado (NO persiste).
    longevity_plan_create — guarda la constancia (persiste + audita).

Convención: keyword-only args, nombrado acción+entidad.

REGLA DE PRIVACIDAD (igual que el resto del expediente — NOM-024/LFPDPPP):
    resource_repr en AuditLog SIEMPRE es el UUID del registro, NUNCA contenido
    clínico. Los logger.* usan exclusivamente IDs, nunca texto clínico.
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.expediente.models import LabAnalyte, LongevityPlan, TreatmentPlan
from apps.expediente.selectors import (
    allergy_list,
    lab_analyte_get,
    medical_history_get_for_patient,
    treatment_plan_get,
    treatment_plan_list,
)
from apps.expediente.services_resumen import _EXPLORACION_LABELS
from apps.pacientes.models import Patient
from apps.tenancy.models import Tenant

logger = logging.getLogger("apps.expediente.services_plan_integral")

# Roles clínicos que pueden generar el Plan Integral de Longevidad.
# Defensa en profundidad: LongevityPlanPermission ya restringe el endpoint
# HTTP a este mismo conjunto, pero el service puede invocarse desde
# management commands/tests sin contexto HTTP. Cadena vacía ("" — no se
# proporcionó rol) se permite pasar.
_ALLOWED_ACTOR_ROLES: frozenset[str] = frozenset({"owner", "admin", "doctor"})

# Estado de exploracion_fisica_basal (MedicalHistory) que SÍ se sugiere como
# "condición a mejorar" en el borrador. Distinto de los estados de
# EvolutionNote.exploracion_fisica (alterado/observacion) usados en el
# Resumen Clínico — este es el bloque basal de la HC (sin_alteraciones |
# con_alteraciones).
_EXPLORACION_BASAL_ALTERADO = "con_alteraciones"


def _validate_actor_role(*, actor_role: str) -> None:
    """Valida que el rol activo del actor pueda operar el Plan Integral.

    Raises:
        ValidationError: si actor_role viene poblado con un rol no permitido.
    """
    if actor_role and actor_role not in _ALLOWED_ACTOR_ROLES:
        raise ValidationError("Tu rol no tiene permiso para operar el Plan Integral de Longevidad.")


def _age_years(*, date_of_birth: Any | None, reference_date: Any) -> int | None:
    """Edad en años cumplidos a `reference_date`. None si falta la fecha de nacimiento."""
    if date_of_birth is None:
        return None
    years = reference_date.year - date_of_birth.year
    if (reference_date.month, reference_date.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return max(years, 0)


def _build_encabezado(*, patient: Patient) -> dict[str, Any]:
    """Datos de encabezado para el borrador (no persisten, solo lectura)."""
    from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
    from apps.core.pdf.branding import build_brand_context  # noqa: PLC0415

    clinic_settings = clinic_settings_get(tenant_id=patient.tenant_id)
    brand = build_brand_context(clinic_settings=clinic_settings)

    hoy = timezone.localtime(timezone.now()).date()
    edad = _age_years(date_of_birth=getattr(patient, "date_of_birth", None), reference_date=hoy)

    # Nombres de llave alineados al contrato consumido por el frontend
    # (web-soft/src/types/planIntegral.ts): clinica_nombre/paciente_nombre/
    # paciente_edad/fecha (distinto de ClinicalSummaryEncabezadoSerializer,
    # que usa clinic_name/patient_name/edad — ese contrato es de otro módulo).
    return {
        "clinica_nombre": brand["clinic_name"],
        "paciente_nombre": patient.full_name,
        "paciente_edad": edad,
        "fecha": hoy.isoformat(),
    }


def _build_alergias_texto(*, patient: Patient) -> str:
    """Texto sugerido de alergias vigentes: 'Sustancia (reacción) [severidad]; ...'."""
    allergies = list(allergy_list(patient=patient, only_active=True))
    if not allergies:
        return "Negadas."

    parts: list[str] = []
    for allergy in allergies:
        piece = allergy.substance
        if allergy.reaction:
            piece += f" ({allergy.reaction})"
        if allergy.severity:
            piece += f" [{allergy.severity}]"
        parts.append(piece)
    return "; ".join(parts)


def _build_condiciones_mejorar(*, medical_history: Any | None) -> str:
    """Sugiere condiciones a mejorar desde exploracion_fisica_basal (HC)."""
    if medical_history is None:
        return ""

    exploracion: dict[str, Any] = medical_history.exploracion_fisica_basal or {}
    lines: list[str] = []
    for sistema, datos in exploracion.items():
        if not isinstance(datos, dict):
            continue
        if datos.get("estado") != _EXPLORACION_BASAL_ALTERADO:
            continue
        label = _EXPLORACION_LABELS.get(sistema, sistema.replace("_", " ").capitalize())
        detalle = (datos.get("detalle") or "").strip()
        lines.append(f"{label}: {detalle}" if detalle else f"{label}.")

    return "\n".join(lines)


def _treatment_plan_snapshot(*, treatment_plan: TreatmentPlan) -> list[dict[str, Any]]:
    """Snapshot de los items del esquema: [{description, quantity, clinical_description}].

    Reusa `treatment_plan.items.all()` (prefetched por treatment_plan_get) —
    no dispara N+1.
    """
    snapshot: list[dict[str, Any]] = []
    for item in treatment_plan.items.all():
        clinical_description = ""
        if item.service_concept is not None:
            clinical_description = item.service_concept.clinical_description or ""
        snapshot.append(
            {
                "description": item.description,
                "quantity": item.quantity,
                "clinical_description": clinical_description,
            }
        )
    return snapshot


def _resolve_treatment_plan_for_patient(
    *, treatment_plan_id: uuid.UUID, patient: Patient
) -> TreatmentPlan:
    """Resuelve un TreatmentPlan por id, validando que sea del mismo paciente.

    Usa el selector (TenantManager, anti-IDOR): un id de otro tenant lanza
    DoesNotExist tal cual. Se valida además que pertenezca al `patient`
    indicado (defensa en profundidad: un esquema de otro paciente del MISMO
    tenant no debe colarse en el Plan Integral).

    Raises:
        TreatmentPlan.DoesNotExist: si el esquema no existe en el tenant activo.
        ValidationError: si el esquema es de otro paciente.
    """
    treatment_plan = treatment_plan_get(plan_id=treatment_plan_id)
    if treatment_plan.patient_id != patient.id:
        raise ValidationError("El esquema de tratamientos no pertenece a este paciente.")
    return treatment_plan


def _compute_out_of_range(*, result: Any, ref_low: Any, ref_high: Any) -> bool:
    """True si `result` es numérico y cae fuera de [ref_low, ref_high].

    Si `result` no se puede interpretar como número (p. ej. "Negativo",
    "Pendiente") o no hay ningún límite de referencia poblado, retorna False
    — no hay forma de evaluar el rango.
    """
    try:
        result_value = Decimal(str(result).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return False

    if ref_low is not None and result_value < Decimal(str(ref_low)):
        return True
    if ref_high is not None and result_value > Decimal(str(ref_high)):
        return True
    return False


def _fmt_ref(value: Any) -> str | None:
    """Normaliza un límite de referencia para el snapshot/PDF.

    `LabAnalyte.ref_low/ref_high` es Decimal(…, decimal_places=4), así que el
    serializer lo emite con ceros de relleno ("70.0000"). En una constancia que
    se entrega al paciente eso se ve poco profesional; aquí quitamos los ceros de
    más ("70.0000" -> "70", "5.70" -> "5.7") sin notación exponencial.
    """
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    # normalize() puede dejar exponente (p. ej. Decimal('1E+2')); f-string 'f' lo evita.
    return f"{d:f}"


def _build_lab_results_snapshot(
    *, tenant: Tenant, lab_results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Snapshotea `lab_results`: resuelve `analyte_id` (si viene) y calcula `out_of_range`.

    Si el ítem trae `analyte_id`, se usa como fuente del rango de referencia
    SOLO cuando el capturador no mandó `ref_low`/`ref_high` explícitos (el
    médico puede anular el rango del catálogo a mano).

    Raises:
        ValidationError: si `analyte_id` no existe o no pertenece al tenant activo.
    """
    snapshot: list[dict[str, Any]] = []
    for item in lab_results:
        analyte_id = item.get("analyte_id")
        ref_low = item.get("ref_low")
        ref_high = item.get("ref_high")

        if analyte_id is not None:
            try:
                analyte = lab_analyte_get(analyte_id=analyte_id)
            except LabAnalyte.DoesNotExist as exc:
                raise ValidationError(
                    "El analito de laboratorio indicado no existe en esta clínica."
                ) from exc
            if analyte.tenant_id != tenant.id:
                raise ValidationError(
                    "El analito de laboratorio indicado no pertenece a esta clínica."
                )
            if ref_low is None:
                ref_low = analyte.ref_low
            if ref_high is None:
                ref_high = analyte.ref_high

        result = item.get("result", "")
        snapshot.append(
            {
                "analyte_id": str(analyte_id) if analyte_id is not None else None,
                "name": item.get("name", ""),
                "unit": item.get("unit", ""),
                "ref_low": _fmt_ref(ref_low),
                "ref_high": _fmt_ref(ref_high),
                "result": result,
                "out_of_range": _compute_out_of_range(
                    result=result, ref_low=ref_low, ref_high=ref_high
                ),
            }
        )
    return snapshot


def _build_gabinete_studies_snapshot(
    *, gabinete_studies: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Snapshotea `gabinete_studies`: [{name, conclusion}], sin cálculo adicional."""
    return [
        {"name": item.get("name", ""), "conclusion": item.get("conclusion", "")}
        for item in gabinete_studies
    ]


def longevity_plan_draft(
    *, patient: Patient, treatment_plan_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Arma el borrador del Plan Integral auto-rellenado desde el expediente.

    NO persiste nada — es una lectura compuesta (alergias + HC + esquema
    opcional) que el médico edita en el frontend antes de llamar a
    longevity_plan_create.

    Args:
        patient:           Paciente del que se arma el plan.
        treatment_plan_id: UUID de un esquema de calendarización ya existente
            del paciente (opcional). Si viene, su snapshot se incluye en
            "esquema"; si no, "esquema" queda en [].

    Returns:
        Dict con "encabezado", "secciones", "esquema", "planes_disponibles",
        "lab_results" (siempre []), "gabinete_studies" (siempre []) y
        "equipo" (catálogo vigente de apps.clinica.ClinicTeamMember), listo
        para el OutputSerializer del borrador.

    Raises:
        TreatmentPlan.DoesNotExist: si treatment_plan_id no existe en el tenant activo.
        ValidationError: si treatment_plan_id es de otro paciente.
    """
    medical_history = medical_history_get_for_patient(patient=patient)
    encabezado = _build_encabezado(patient=patient)

    secciones = {
        "alergias": _build_alergias_texto(patient=patient),
        "antecedentes": (medical_history.antecedentes_importancia if medical_history else "") or "",
        "tratamientos_actuales": (medical_history.tratamientos_actuales if medical_history else "")
        or "",
        "condiciones_mejorar": _build_condiciones_mejorar(medical_history=medical_history),
        "estudios": "",
        "reporte_medico": "",
        "interconsulta": "",
        "seguimiento": "",
    }

    esquema: list[dict[str, Any]] = []
    if treatment_plan_id is not None:
        treatment_plan = _resolve_treatment_plan_for_patient(
            treatment_plan_id=treatment_plan_id, patient=patient
        )
        esquema = _treatment_plan_snapshot(treatment_plan=treatment_plan)

    planes_disponibles = [
        {
            "id": plan.id,
            "title": plan.title,
            "created_at": plan.created_at,
            "items_count": len(plan.items.all()),
        }
        for plan in treatment_plan_list(patient=patient)
    ]

    from apps.clinica.selectors import clinic_team_list  # noqa: PLC0415

    equipo = [
        {"departamento": member.departamento, "nombre": member.nombre}
        for member in clinic_team_list(only_active=True)
    ]

    return {
        "encabezado": encabezado,
        "secciones": secciones,
        "esquema": esquema,
        "planes_disponibles": planes_disponibles,
        "lab_results": [],
        "gabinete_studies": [],
        "equipo": equipo,
    }


def longevity_plan_create(
    *,
    tenant: Tenant,
    patient: Patient,
    actor: Any,
    actor_role: str = "",
    treatment_plan_id: uuid.UUID | None = None,
    alergias: str = "",
    antecedentes: str = "",
    tratamientos_actuales: str = "",
    condiciones_mejorar: str = "",
    estudios: str = "",
    reporte_medico: str = "",
    interconsulta: str = "",
    seguimiento: str = "",
    lab_results: list[dict[str, Any]] | None = None,
    gabinete_studies: list[dict[str, Any]] | None = None,
) -> LongevityPlan:
    """Guarda el Plan Integral de Longevidad como constancia entregable.

    El texto de cada sección llega YA EDITADO por el médico (el borrador de
    longevity_plan_draft es solo una sugerencia inicial del frontend).

    Valida (defensa en profundidad):
      - tenant no es None.
      - patient pertenece al tenant activo.
      - actor_role (si viene poblado) está en el conjunto de roles permitidos.
      - si treatment_plan_id viene: el esquema pertenece al mismo tenant y al
        mismo paciente; se toma un SNAPSHOT de sus items (independiente de
        cambios/borrado posteriores del esquema).
      - cada `lab_results[i].analyte_id` (si viene) pertenece al mismo tenant.

    Regla del médico (igual que clinical_summary_create): si actor_role ==
    "doctor", el `doctor` del plan es el Doctor del actor en este tenant (o
    None si el actor no tiene perfil de médico activo). Owner/admin generan
    el plan sin doctor fijo (None) — no en nombre de un médico específico,
    a diferencia del Resumen Clínico (que sí fija el doctor de la evolución).

    `equipo` (Fase 4) NUNCA se recibe del cliente: se snapshotea SIEMPRE del
    catálogo vigente `apps.clinica.selectors.clinic_team_list` — config-driven.

    Registra LONGEVITY_PLAN_CREATE en AuditLog (NOM-024).
    resource_repr = str(plan.id) — NUNCA PII.

    Args:
        tenant:                Clínica del contexto activo. No puede ser None.
        patient:                Paciente al que pertenece el plan.
        actor:                  Usuario que genera/guarda el plan.
        actor_role:              Rol activo del usuario ('doctor', 'owner', ...).
        treatment_plan_id:       UUID de un esquema de calendarización a snapshotear (opcional).
        alergias..seguimiento:   Texto final de cada sección (editado por el
            médico a partir del borrador).
        lab_results:             Resultados de laboratorio capturados por el
            médico (Fase 3): [{analyte_id?, name, unit, ref_low, ref_high,
            result}]. `out_of_range` se calcula aquí, nunca se acepta del cliente.
        gabinete_studies:        Estudios de gabinete capturados por el médico
            (Fase 3): [{name, conclusion}].

    Returns:
        La instancia LongevityPlan recién creada.

    Raises:
        ValidationError: si el tenant/paciente/esquema/analito no son
            consistentes o el rol del actor no está permitido.
        TreatmentPlan.DoesNotExist: si treatment_plan_id no existe en el tenant activo.
    """
    _validate_actor_role(actor_role=actor_role)

    if tenant is None:
        raise ValidationError(
            "Se requiere un tenant activo para guardar el Plan Integral de Longevidad."
        )

    if patient.tenant_id != tenant.id:
        raise ValidationError("El paciente no pertenece a esta clínica.")

    doctor = None
    if actor_role == "doctor":
        from apps.personal.selectors import doctor_get_for_user  # noqa: PLC0415

        doctor = doctor_get_for_user(user=actor, tenant_id=tenant.id)

    treatment_plan: TreatmentPlan | None = None
    esquema: list[dict[str, Any]] = []
    if treatment_plan_id is not None:
        treatment_plan = _resolve_treatment_plan_for_patient(
            treatment_plan_id=treatment_plan_id, patient=patient
        )
        if treatment_plan.tenant_id != tenant.id:
            raise ValidationError("El esquema de tratamientos no pertenece a esta clínica.")
        esquema = _treatment_plan_snapshot(treatment_plan=treatment_plan)

    lab_results_snapshot = _build_lab_results_snapshot(tenant=tenant, lab_results=lab_results or [])
    gabinete_studies_snapshot = _build_gabinete_studies_snapshot(
        gabinete_studies=gabinete_studies or []
    )

    from apps.clinica.selectors import clinic_team_list  # noqa: PLC0415

    equipo_snapshot = [
        {"departamento": member.departamento, "nombre": member.nombre}
        for member in clinic_team_list(only_active=True)
    ]

    plan = LongevityPlan.objects.create(
        tenant=tenant,
        created_by=actor,
        patient=patient,
        doctor=doctor,
        treatment_plan=treatment_plan,
        alergias=alergias,
        antecedentes=antecedentes,
        tratamientos_actuales=tratamientos_actuales,
        condiciones_mejorar=condiciones_mejorar,
        estudios=estudios,
        reporte_medico=reporte_medico,
        interconsulta=interconsulta,
        seguimiento=seguimiento,
        esquema=esquema,
        lab_results=lab_results_snapshot,
        gabinete_studies=gabinete_studies_snapshot,
        equipo=equipo_snapshot,
    )

    logger.info(
        "longevity_plan_create: plan %s creado para paciente %s (tenant=%s)",
        plan.pk,
        patient.pk,
        tenant.pk,
    )

    audit_record(
        action=ActionType.LONGEVITY_PLAN_CREATE,
        resource_type="LongevityPlan",
        actor=actor,
        tenant=tenant,
        resource_id=plan.id,
        resource_repr=str(plan.id),
        metadata={
            "patient_id": str(patient.id),
            "treatment_plan_id": str(treatment_plan_id) if treatment_plan_id else None,
        },
    )

    return plan
