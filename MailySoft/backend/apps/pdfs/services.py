"""Servicios de la app pdfs — encolar trabajos de PDF."""

from typing import Any

from django.db import transaction

from apps.pdfs.models import PdfJob
from apps.pdfs.tasks import generate_pdf


def pdf_job_enqueue(
    *,
    tenant: Any,
    kind: str,
    params: dict[str, Any],
    user: Any = None,
    cache_key: str = "",
    filename: str = "",
) -> PdfJob:
    """Crea (o reusa) un trabajo de PDF y encola su generación en Celery.

    - cache_key != "": get_or_create por (tenant, kind, cache_key). Si está DONE se
      reusa (caché de salida inmutable). Cualquier otro estado se re-encola.
    - cache_key == "": SIEMPRE crea un job nuevo (salida mutable: se regenera fresco).

    `params` debe ser JSON-serializable (ids como str). La tarea es idempotente y
    se encola con transaction.on_commit para que el worker vea la fila comprometida.
    """
    if cache_key:
        job, created = PdfJob.objects.get_or_create(
            tenant=tenant,
            kind=kind,
            cache_key=cache_key,
            defaults={
                "params": params,
                "filename": filename,
                "created_by": user,
                "status": PdfJob.Status.PENDING,
            },
        )
    else:
        job = PdfJob.objects.create(
            tenant=tenant,
            kind=kind,
            params=params,
            filename=filename,
            created_by=user,
            status=PdfJob.Status.PENDING,
        )
        created = True

    # Re-encolar SIEMPRE que el PDF no esté listo (robustez): si un job quedó
    # PENDING/PROCESSING pero su mensaje se perdió (worker caído/reinicio), un
    # re-pedido lo vuelve a encolar. La tarea es idempotente (si ya está DONE no
    # regenera), así que re-encolar es seguro. Solo un job DONE se reusa (caché).
    needs_enqueue = job.status != PdfJob.Status.DONE

    if not created and job.status == PdfJob.Status.FAILED:
        # Reintentar un job fallido: limpiar estado antes de re-encolar.
        job.status = PdfJob.Status.PENDING
        job.error = ""
        job.file = None
        job.save(update_fields=["status", "error", "file", "updated_at"])

    if needs_enqueue:
        transaction.on_commit(lambda: generate_pdf.delay(str(job.id)))
    return job
