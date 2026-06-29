"""
Tareas Celery de la app recetas.

generate_prescription_pdf — genera el PDF de una receta en SEGUNDO PLANO (P0).
    Mueve WeasyPrint fuera del request HTTP para no bloquear los workers de la API.

CONTEXTO DE TENANT EN CELERY:
    El worker corre SIN request HTTP, así que carga el job con all_objects (por su
    UUID interno) y luego SETEA el thread-local de tenant para que el TenantManager
    resuelva el formato/clínica de la receta. RLS lo refuerza en PostgreSQL.

IDEMPOTENCIA:
    Si el job ya está DONE, la tarea no hace nada (protege contra at-least-once).

ERRORES:
    Una falla de WeasyPrint NO reintenta (suele ser determinista): el job queda
    FAILED con el detalle, y el usuario puede pedir el PDF de nuevo (el servicio
    re-encola un job FAILED). El error se registra en el logger.
"""

import logging
import uuid as uuid_module

from celery import shared_task
from django.core.files.base import ContentFile

from apps.core.tenant_context import (
    clear_current_tenant,
    set_current_tenant,
    set_tenant_context_active,
)
from apps.recetas.models import PrescriptionPdfJob

logger = logging.getLogger("apps.recetas.tasks")


@shared_task
def generate_prescription_pdf(job_id: str) -> str:
    """Genera el PDF de la receta del job y lo guarda en el storage.

    Args:
        job_id: UUID (str) del PrescriptionPdfJob a procesar.

    Returns:
        "done" | "failed" | "skipped:done" | "not_found".
    """
    from apps.recetas.pdf import prescription_pdf_build  # noqa: PLC0415
    from apps.recetas.selectors import prescription_format_resolve  # noqa: PLC0415

    try:
        job = PrescriptionPdfJob.all_objects.select_related(
            "prescription", "tenant"
        ).get(id=job_id)
    except PrescriptionPdfJob.DoesNotExist:
        logger.warning("generate_prescription_pdf: job %s no existe.", job_id)
        return "not_found"

    if job.status == PrescriptionPdfJob.Status.DONE:
        return "skipped:done"

    # El worker no tiene contexto HTTP: activamos el tenant del job para que el
    # TenantManager (formato/clínica) y RLS resuelvan correctamente.
    set_current_tenant(job.tenant)
    set_tenant_context_active(True)
    try:
        job.status = PrescriptionPdfJob.Status.PROCESSING
        job.save(update_fields=["status", "updated_at"])

        prescription = job.prescription

        format_override_id: uuid_module.UUID | None = None
        if job.format_id:
            try:
                format_override_id = uuid_module.UUID(job.format_id)
            except ValueError:
                format_override_id = None

        resolved_fmt = prescription_format_resolve(
            prescription=prescription,
            format_override_id=format_override_id,
            layout_override=job.layout or None,
        )
        pdf_bytes = prescription_pdf_build(
            prescription=prescription,
            format_override=resolved_fmt,
        )

        job.file.save(
            f"receta-{prescription.folio}.pdf",
            ContentFile(pdf_bytes),
            save=False,
        )
        job.status = PrescriptionPdfJob.Status.DONE
        job.error = ""
        job.save(update_fields=["file", "status", "error", "updated_at"])
        return "done"
    except Exception as exc:  # noqa: BLE001
        job.status = PrescriptionPdfJob.Status.FAILED
        job.error = str(exc)[:1000]
        job.save(update_fields=["status", "error", "updated_at"])
        logger.error(
            "generate_prescription_pdf: error generando el PDF del job %s — %s",
            job_id,
            exc,
            exc_info=True,
        )
        return "failed"
    finally:
        clear_current_tenant()
        set_tenant_context_active(False)
