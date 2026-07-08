"""Generadores de PDF de expediente para la infra de PDFs asíncronos (apps.pdfs).

Registrados en ExpedienteConfig.ready(). Corren en el worker de Celery (con el
contexto de tenant ya activado por la tarea generate_pdf).

Kinds registrados:
    "book"            — build_book_pdf, libro clínico completo/hc/último capítulo.
    "resumen_clinico" — build_resumen_clinico_pdf, resumen clínico por consulta.
    "treatment_plan"  — build_treatment_plan_pdf, esquema de calendarización
                         de tratamientos (Fases 1 y 4).
"""

from typing import Any


def build_book_pdf(*, params: dict[str, Any], tenant: Any) -> tuple[bytes, str]:
    """Construye el PDF del libro clínico desde los params del job.

    params: {patient_id: str, modo: str, incluir_imagenes: bool}.
    Devuelve (pdf_bytes, filename).
    """
    from apps.expediente.pdf import libro_pdf_build  # noqa: PLC0415
    from apps.expediente.selectors import book_build_all  # noqa: PLC0415
    from apps.pacientes.selectors import patient_get  # noqa: PLC0415

    patient = patient_get(patient_id=params["patient_id"])
    modo: str = params["modo"]
    incluir_imagenes: bool = bool(params.get("incluir_imagenes", True))

    book = book_build_all(patient=patient, modo=modo)
    pdf_bytes = libro_pdf_build(
        patient=book.patient,
        clinic_settings=book.clinic_settings,
        medical_history=book.medical_history,
        allergies=book.allergies,
        capitulos=book.capitulos,
        capitulos_count=book.capitulos_count,
        modo=modo,
        incluir_imagenes=incluir_imagenes,
    )
    filename = f"libro-{patient.record_number}-{modo}.pdf"
    return pdf_bytes, filename


def build_resumen_clinico_pdf(*, params: dict[str, Any], tenant: Any) -> tuple[bytes, str]:
    """Construye el PDF del Resumen Clínico desde los params del job.

    params: {summary_id: str}. Devuelve (pdf_bytes, filename).
    """
    from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
    from apps.expediente.pdf import resumen_clinico_pdf_build  # noqa: PLC0415
    from apps.expediente.selectors import clinical_summary_get  # noqa: PLC0415

    summary = clinical_summary_get(summary_id=params["summary_id"])
    clinic_settings = clinic_settings_get(tenant_id=tenant.id) if tenant is not None else None
    pdf_bytes = resumen_clinico_pdf_build(summary=summary, clinic_settings=clinic_settings)

    folio_short = str(summary.id).replace("-", "")[:8].upper()
    filename = f"resumen-clinico-{folio_short}.pdf"
    return pdf_bytes, filename


def build_treatment_plan_pdf(*, params: dict[str, Any], tenant: Any) -> tuple[bytes, str]:
    """Construye el PDF de la Calendarización de tratamientos desde los params del job.

    params: {plan_id: str}. Devuelve (pdf_bytes, filename).
    """
    from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
    from apps.expediente.pdf import treatment_plan_pdf_build  # noqa: PLC0415
    from apps.expediente.selectors import treatment_plan_get  # noqa: PLC0415

    plan = treatment_plan_get(plan_id=params["plan_id"])
    clinic_settings = clinic_settings_get(tenant_id=tenant.id) if tenant is not None else None
    pdf_bytes = treatment_plan_pdf_build(plan=plan, clinic_settings=clinic_settings)

    folio_short = str(plan.id).replace("-", "")[:8].upper()
    filename = f"calendarizacion-{folio_short}.pdf"
    return pdf_bytes, filename
