"""Generador del PDF del libro clínico para la infra de PDFs asíncronos (apps.pdfs).

Registrado como kind "book" en ExpedienteConfig.ready(). Corre en el worker de
Celery (con el contexto de tenant ya activado por la tarea generate_pdf).
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
