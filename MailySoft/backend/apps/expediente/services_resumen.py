"""
Services del Resumen Clínico por consulta (documento entregable al paciente).

A diferencia del Libro Clínico (uso interno, completo, apps.expediente.pdf_jobs),
el Resumen Clínico es un documento SINTÉTICO de UNA consulta que se entrega al
paciente. Nace de una EvolutionNote (consulta) y se auto-rellena desde el
expediente (HC + evolución); el médico edita el texto sugerido antes de
guardarlo como constancia.

API pública:
    clinical_summary_draft  — arma el borrador auto-rellenado (NO persiste).
    clinical_summary_create — guarda la constancia (persiste + audita).

Convención: keyword-only args, nombrado acción+entidad (D-EC style del módulo).

REGLA DE PRIVACIDAD (igual que el resto del expediente — NOM-024/LFPDPPP):
    resource_repr en AuditLog SIEMPRE es el UUID del registro, NUNCA contenido
    clínico. Los logger.* usan exclusivamente IDs, nunca texto clínico.
"""

import logging
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils import timezone

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.expediente.models import ClinicalSummary, EvolutionNote
from apps.expediente.selectors import medical_history_get_for_patient
from apps.pacientes.models import Sex
from apps.tenancy.models import Tenant

logger = logging.getLogger("apps.expediente.services_resumen")

# ---------------------------------------------------------------------------
# Etiquetas legibles de los bloques JSON de MedicalHistory (D-EC-4/D-EC-7).
# Mismas claves que apps/expediente/validators.py — no se reimporta la
# whitelist (el validador solo se usa en escritura); aquí basta con etiquetar
# lo que exista en el dict, ignorando claves desconocidas.
# ---------------------------------------------------------------------------

_AHF_LABELS: dict[str, str] = {
    "diabetes": "Diabetes",
    "hipertension_arterial": "Hipertensión arterial",
    "cardiopatias": "Cardiopatías",
    "hepatopatias": "Hepatopatías",
    "urologicos": "Padecimientos urológicos",
    "neurologicos": "Padecimientos neurológicos",
    "respiratorias": "Enfermedades respiratorias",
    "cancer": "Cáncer",
    "alergicas": "Enfermedades alérgicas",
    "metabolicas": "Enfermedades metabólicas",
    "sanguineas": "Enfermedades de la sangre",
    "articulares": "Padecimientos articulares",
    "inmunologicas": "Enfermedades inmunológicas",
    "malformaciones": "Malformaciones congénitas",
    "dermatologicas": "Enfermedades dermatológicas",
    "otros": "Otros antecedentes heredofamiliares",
}

_APP_LABELS: dict[str, str] = {
    "enfermedades_infancia": "Enfermedades de la infancia",
    "diabetes": "Diabetes",
    "hipertension": "Hipertensión",
    "respiratorias": "Enfermedades respiratorias",
    "oftalmico": "Padecimientos oftálmicos",
    "cardiovasculares": "Enfermedades cardiovasculares",
    "neurologicos": "Padecimientos neurológicos",
    "gastrointestinales": "Enfermedades gastrointestinales",
    "hepatopatias": "Hepatopatías",
    "metabolicas": "Enfermedades metabólicas",
    "urologicos": "Padecimientos urológicos",
    "circulatorio": "Padecimientos circulatorios",
    "traumaticas": "Antecedentes traumáticos",
    "articulares": "Padecimientos articulares",
    "dermatologicas": "Enfermedades dermatológicas",
    "quirurgicos": "Antecedentes quirúrgicos",
    "transfusionales": "Antecedentes transfusionales",
    "vectores": "Exposición a vectores",
    "autoinmunes": "Enfermedades autoinmunes",
    "emocionales": "Antecedentes emocionales/psiquiátricos",
    "adicciones": "Adicciones",
    "hospitalizaciones_previas": "Hospitalizaciones previas",
    "pesticidas": "Exposición a pesticidas",
    "dx_cancer": "Diagnóstico de cáncer",
    "otros": "Otros antecedentes personales patológicos",
}

_EXPLORACION_LABELS: dict[str, str] = {
    "cerebro": "Cerebro",
    "sistema_nervioso": "Sistema nervioso",
    "ocular": "Ocular",
    "endocrino": "Endocrino",
    "corazon": "Corazón",
    "circulatorio": "Circulatorio",
    "respiratorio": "Respiratorio",
    "hepatico": "Hepático",
    "pancreas": "Páncreas",
    "renal": "Renal",
    "gastrointestinal": "Gastrointestinal",
    "osteoarticular": "Osteoarticular",
    "tendomuscular": "Tendomuscular",
    "reproductor": "Reproductor",
    "inmunologico": "Inmunológico",
    "extremidades": "Extremidades",
    "piel_tegumentos": "Piel y tegumentos",
    "otros": "Otros",
}

# Valores considerados "sin antecedente" — no se incluyen en el borrador.
_NEGADO_VALUES: frozenset[str] = frozenset({"", "negado", "no", "ninguno", "ninguna"})

# Estados de exploración que SÍ se reportan en el borrador (D-EC-7 semáforo).
_EXPLORACION_ESTADOS_RELEVANTES: frozenset[str] = frozenset({"observacion", "alterado"})


def _is_relevant(value: Any) -> bool:
    """True si un valor de antecedente NO es 'Negado'/vacío/None."""
    if value is None:
        return False
    text = str(value).strip()
    return text.lower() not in _NEGADO_VALUES


def _relevant_block_entries(data: dict[str, Any], labels: dict[str, str]) -> list[str]:
    """Construye 'Etiqueta: valor' para las claves relevantes de un bloque JSON.

    Solo incluye claves declaradas en `labels` (evita colar claves desconocidas
    o de control como `numero_hermanos`, que se maneja aparte).
    """
    entries: list[str] = []
    for key, label in labels.items():
        if key not in data:
            continue
        value = data[key]
        if _is_relevant(value):
            entries.append(f"{label}: {str(value).strip()}")
    return entries


def _age_years(*, date_of_birth: Any | None, reference_date: Any) -> int | None:
    """Edad en años cumplidos a `reference_date`. None si falta la fecha de nacimiento."""
    if date_of_birth is None:
        return None
    years = reference_date.year - date_of_birth.year
    if (reference_date.month, reference_date.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return max(years, 0)


def _sexo_adjetivo(sex: str) -> str:
    """Adjetivo de género para la frase de identificación. Vacío si no aplica."""
    if sex == Sex.MALE:
        return "masculino"
    if sex == Sex.FEMALE:
        return "femenino"
    return ""


def _build_identificacion(*, patient: Any, reference_date: Any) -> str:
    """Frase de identificación: sexo + edad calculada a la fecha de la consulta."""
    edad = _age_years(
        date_of_birth=getattr(patient, "date_of_birth", None), reference_date=reference_date
    )
    adjetivo = _sexo_adjetivo(getattr(patient, "sex", "") or "")

    partes = ["Se trata de paciente"]
    if adjetivo:
        partes.append(adjetivo)
    if edad is not None:
        partes.append(f"de {edad} años,")
    else:
        partes[-1] = f"{partes[-1]},"
    partes.append("que acude a cita médica.")
    return " ".join(partes)


def _build_antecedentes(*, medical_history: Any | None) -> str:
    """Concatena solo los antecedentes RELEVANTES (no 'Negado') de la HC."""
    if medical_history is None:
        return "Sin antecedentes de importancia referidos."

    ahf_data: dict[str, Any] = medical_history.heredo_familiares or {}
    app_data: dict[str, Any] = medical_history.personales_patologicos or {}

    ahf_entries = _relevant_block_entries(ahf_data, _AHF_LABELS)
    numero_hermanos = ahf_data.get("numero_hermanos")
    if isinstance(numero_hermanos, int) and numero_hermanos > 0:
        ahf_entries.insert(0, f"Número de hermanos: {numero_hermanos}")

    app_entries = _relevant_block_entries(app_data, _APP_LABELS)

    parts: list[str] = []
    if ahf_entries:
        parts.append("ANTECEDENTES HEREDOFAMILIARES: " + "; ".join(ahf_entries) + ".")
    if app_entries:
        parts.append("ANTECEDENTES PERSONALES PATOLÓGICOS: " + "; ".join(app_entries) + ".")

    if not parts:
        return "Sin antecedentes de importancia referidos."
    return " ".join(parts)


def _build_padecimiento_actual(*, evolution: EvolutionNote, medical_history: Any | None) -> str:
    """Padecimiento actual: interrogatorio de la evolución o, si vacío, el de la HC."""
    interrogatorio = (evolution.interrogatorio or "").strip()
    if interrogatorio:
        return interrogatorio
    if medical_history is not None:
        return (medical_history.padecimiento_actual or "").strip()
    return ""


def _build_exploracion_fisica(*, evolution: EvolutionNote) -> str:
    """Exploración física en prosa: solo sistemas 'observacion'/'alterado'."""
    exploracion: dict[str, Any] = evolution.exploracion_fisica or {}
    lines: list[str] = []
    for sistema, datos in exploracion.items():
        if not isinstance(datos, dict):
            continue
        estado = datos.get("estado", "no_evaluado")
        if estado not in _EXPLORACION_ESTADOS_RELEVANTES:
            continue
        label = _EXPLORACION_LABELS.get(sistema, sistema.replace("_", " ").capitalize())
        detalle = (datos.get("detalle") or "").strip()
        estado_label = "Con alteraciones" if estado == "alterado" else "En observación"
        if detalle:
            lines.append(f"{label}: {detalle} ({estado_label}).")
        else:
            lines.append(f"{label}: {estado_label}.")

    if not lines:
        return "Exploración física sin alteraciones aparentes."
    return "\n".join(lines)


def _build_diagnostico_manejo(*, evolution: EvolutionNote) -> str:
    """Diagnósticos (texto libre + estructurados) + manejo/tratamiento."""
    parts: list[str] = []

    diagnosticos_texto = (evolution.diagnosticos_texto or "").strip()
    if diagnosticos_texto:
        parts.append(diagnosticos_texto)

    # evolution.diagnoses viene prefetched por evolution_note_get.
    dx_lines: list[str] = []
    for dx in evolution.diagnoses.all():
        description = (getattr(dx, "description", "") or "").strip()
        if not description:
            continue
        cie_code = (getattr(dx, "cie_code", "") or "").strip()
        dx_lines.append(f"{description} [{cie_code}]" if cie_code else description)
    if dx_lines:
        parts.append("; ".join(dx_lines) + ".")

    tratamiento = (evolution.tratamiento or "").strip()
    if tratamiento:
        parts.append(f"Manejo: {tratamiento}")

    return "\n".join(parts)


def _build_indicaciones(*, evolution: EvolutionNote) -> str:
    """Indicaciones al paciente: plan_recomendaciones + indicaciones_enfermeria."""
    parts = [
        (evolution.plan_recomendaciones or "").strip(),
        (evolution.indicaciones_enfermeria or "").strip(),
    ]
    return "\n".join(p for p in parts if p)


def _build_encabezado(*, evolution: EvolutionNote) -> dict[str, Any]:
    """Datos de encabezado para el borrador (no persisten, solo lectura)."""
    from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
    from apps.core.pdf.branding import build_brand_context  # noqa: PLC0415

    patient = evolution.patient
    appointment = evolution.appointment
    vital_signs = evolution.vital_signs

    clinic_settings = clinic_settings_get(tenant_id=evolution.tenant_id)
    brand = build_brand_context(clinic_settings=clinic_settings)

    fecha_consulta = timezone.localtime(appointment.starts_at).date()
    edad = _age_years(
        date_of_birth=getattr(patient, "date_of_birth", None), reference_date=fecha_consulta
    )

    ta: str | None = None
    fc: int | None = None
    fr: int | None = None
    temp_c: Any | None = None
    peso_kg: Any | None = None
    talla_m: Any | None = None
    if vital_signs is not None:
        peso_kg = vital_signs.weight_kg
        talla_m = vital_signs.height_m
        fc = vital_signs.heart_rate
        fr = vital_signs.resp_rate
        temp_c = vital_signs.temperature_c
        if vital_signs.systolic is not None and vital_signs.diastolic is not None:
            ta = f"{vital_signs.systolic}/{vital_signs.diastolic}"

    return {
        "clinic_name": brand["clinic_name"],
        "patient_name": patient.full_name,
        "edad": edad,
        "sexo": patient.sex,
        "fecha": fecha_consulta.isoformat(),
        "peso_kg": peso_kg,
        "talla_m": talla_m,
        "ta": ta,
        "fc": fc,
        "fr": fr,
        "temp_c": temp_c,
    }


def clinical_summary_draft(*, evolution: EvolutionNote) -> dict[str, Any]:
    """Arma el borrador del Resumen Clínico auto-rellenado desde el expediente.

    NO persiste nada — es una lectura compuesta (HC + evolución + signos) que
    el médico edita en el frontend antes de llamar a clinical_summary_create.

    Args:
        evolution: Nota de evolución (consulta) ya resuelta por selector
            (evolution_note_get), con patient/appointment/doctor/vital_signs/
            diagnoses precargados.

    Returns:
        Dict con las llaves "encabezado" y "secciones", listo para el
        OutputSerializer del borrador.
    """
    medical_history = medical_history_get_for_patient(patient=evolution.patient)
    encabezado = _build_encabezado(evolution=evolution)

    secciones = {
        "identificacion": _build_identificacion(
            patient=evolution.patient,
            reference_date=timezone.localtime(evolution.appointment.starts_at).date(),
        ),
        "antecedentes": _build_antecedentes(medical_history=medical_history),
        "padecimiento_actual": _build_padecimiento_actual(
            evolution=evolution, medical_history=medical_history
        ),
        "exploracion_fisica": _build_exploracion_fisica(evolution=evolution),
        "diagnostico_manejo": _build_diagnostico_manejo(evolution=evolution),
        "indicaciones": _build_indicaciones(evolution=evolution),
    }

    return {"encabezado": encabezado, "secciones": secciones}


def clinical_summary_create(
    *,
    tenant: Tenant,
    evolution: EvolutionNote,
    actor: Any,
    actor_role: str = "",
    identificacion: str = "",
    antecedentes: str = "",
    padecimiento_actual: str = "",
    exploracion_fisica: str = "",
    diagnostico_manejo: str = "",
    indicaciones: str = "",
) -> ClinicalSummary:
    """Guarda el Resumen Clínico como constancia (médico + fecha).

    El texto de cada sección llega YA EDITADO por el médico (el borrador de
    clinical_summary_draft es solo una sugerencia inicial del frontend).

    Valida (defensa en profundidad, igual que evolution_note_create):
      - tenant no es None.
      - evolution pertenece al tenant activo.
      - Regla del médico: si actor_role == 'doctor', el actor debe ser el
        médico de la evolución (mismo criterio que D-EC-2/ALTO-1 en
        evolution_note_create). Owner/admin pueden generar el resumen en
        nombre de cualquier médico.

    Registra CLINICAL_SUMMARY_CREATE en AuditLog (NOM-024).
    resource_repr = str(summary.id) — NUNCA PII.

    Args:
        tenant:               Clínica del contexto activo. No puede ser None.
        evolution:             Nota de evolución (consulta) base del resumen.
        actor:                 Usuario que genera/guarda el resumen.
        actor_role:            Rol activo del usuario ('doctor', 'owner', ...).
        identificacion..indicaciones: Texto final de cada sección (editado
            por el médico a partir del borrador).

    Returns:
        La instancia ClinicalSummary recién creada.

    Raises:
        ValidationError: si el tenant/evolution no son consistentes o la
            regla del médico no se cumple.
    """
    if tenant is None:
        raise ValidationError("Se requiere un tenant activo para guardar un resumen clínico.")

    if evolution.tenant_id != tenant.id:
        raise ValidationError("La nota de evolución no pertenece a esta clínica.")

    if actor_role == "doctor":
        try:
            membership_user_id = evolution.doctor.membership.user_id
        except (AttributeError, ObjectDoesNotExist) as exc:
            raise ValidationError(
                "El médico de la evolución no tiene perfil de membresía válido."
            ) from exc
        if membership_user_id != getattr(actor, "pk", None):
            raise ValidationError(
                "Un médico solo puede generar el resumen clínico de sus propias consultas."
            )

    summary = ClinicalSummary.objects.create(
        tenant=tenant,
        created_by=actor,
        patient=evolution.patient,
        evolution=evolution,
        doctor=evolution.doctor,
        identificacion=identificacion,
        antecedentes=antecedentes,
        padecimiento_actual=padecimiento_actual,
        exploracion_fisica=exploracion_fisica,
        diagnostico_manejo=diagnostico_manejo,
        indicaciones=indicaciones,
    )

    logger.info(
        "clinical_summary_create: resumen %s creado para evolución %s (tenant=%s)",
        summary.pk,
        evolution.pk,
        tenant.pk,
    )

    audit_record(
        action=ActionType.CLINICAL_SUMMARY_CREATE,
        resource_type="ClinicalSummary",
        actor=actor,
        tenant=tenant,
        resource_id=summary.id,
        resource_repr=str(summary.id),
        metadata={
            "evolution_id": str(evolution.id),
            "patient_id": str(evolution.patient_id),
        },
    )

    return summary
