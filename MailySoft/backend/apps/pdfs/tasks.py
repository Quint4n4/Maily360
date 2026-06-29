"""
Tarea Celery genérica de generación de PDFs.

generate_pdf — genera CUALQUIER PDF en segundo plano (P0). Despacha por `kind`
    al generador registrado (apps.pdfs.registry) para no bloquear los workers HTTP.

CONTEXTO DE TENANT EN CELERY:
    El worker corre SIN request HTTP, así que carga el job con all_objects (por su
    UUID) y SETEA el thread-local de tenant antes de generar, para que el builder
    (selectors del módulo) y RLS resuelvan el tenant correcto.

IDEMPOTENCIA:
    Si el job ya está DONE, no hace nada (protege contra at-least-once).

ERRORES:
    Una falla del generador NO reintenta (suele ser determinista): el job queda
    FAILED con el detalle, y el usuario puede pedir el PDF de nuevo (el servicio
    re-encola). El error se registra en el logger.
"""

import logging

from celery import shared_task
from django.core.files.base import ContentFile

from apps.core.tenant_context import (
    clear_current_tenant,
    set_current_tenant,
    set_tenant_context_active,
)
from apps.pdfs.models import PdfJob

logger = logging.getLogger("apps.pdfs.tasks")


@shared_task
def generate_pdf(job_id: str) -> str:
    """Genera el PDF del job (despachando por kind) y lo guarda en el storage.

    Returns:
        "done" | "failed" | "skipped:done" | "not_found".
    """
    from apps.pdfs.registry import get_pdf_kind  # noqa: PLC0415

    try:
        job = PdfJob.all_objects.select_related("tenant").get(id=job_id)
    except PdfJob.DoesNotExist:
        logger.warning("generate_pdf: job %s no existe.", job_id)
        return "not_found"

    if job.status == PdfJob.Status.DONE:
        return "skipped:done"

    # El worker no tiene contexto HTTP: activamos el tenant del job para que los
    # selectors del builder y RLS resuelvan correctamente.
    set_current_tenant(job.tenant)
    set_tenant_context_active(True)
    try:
        job.status = PdfJob.Status.PROCESSING
        job.save(update_fields=["status", "updated_at"])

        spec = get_pdf_kind(job.kind)
        pdf_bytes, filename = spec.builder(params=job.params, tenant=job.tenant)

        job.file.save(
            filename or f"{job.kind}.pdf",
            ContentFile(pdf_bytes),
            save=False,
        )
        if filename:
            job.filename = filename
        job.status = PdfJob.Status.DONE
        job.error = ""
        job.save(update_fields=["file", "filename", "status", "error", "updated_at"])
        return "done"
    except Exception as exc:  # noqa: BLE001
        job.status = PdfJob.Status.FAILED
        job.error = str(exc)[:1000]
        job.save(update_fields=["status", "error", "updated_at"])
        logger.error(
            "generate_pdf: error generando el PDF del job %s (kind=%s) — %s",
            job_id,
            job.kind,
            exc,
            exc_info=True,
        )
        return "failed"
    finally:
        clear_current_tenant()
        set_tenant_context_active(False)
