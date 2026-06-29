"""Selectors de la app pdfs — lecturas de trabajos de PDF."""

from typing import Any

from apps.pdfs.models import PdfJob


def pdf_job_get(*, job_id: Any) -> PdfJob:
    """Devuelve el PdfJob por id. El TenantManager filtra por tenant del request:
    un job de otro tenant → DoesNotExist → 404 (anti-IDOR)."""
    return PdfJob.objects.get(id=job_id)
