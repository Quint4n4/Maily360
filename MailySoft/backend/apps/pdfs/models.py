"""Modelo genérico de trabajo de PDF asíncrono."""

import uuid

from django.db import models

from apps.core.models import TenantAwareModel


def pdf_job_path(instance: "PdfJob", filename: str) -> str:
    """Ruta de subida del PDF generado, aislada por tenant y por kind (BAJO-2)."""
    return f"tenants/{instance.tenant_id}/pdfs/{instance.kind}/{uuid.uuid4().hex}.pdf"


class PdfJob(TenantAwareModel):
    """Trabajo de generación asíncrona de un PDF (genérico, cualquier módulo).

    La generación con WeasyPrint se mueve a una tarea de Celery para no bloquear
    los workers de la API (riesgo P0). Cada `kind` registra su generador en el
    registry (apps.pdfs.registry); `params` lleva los datos (ids como str, modo,
    fechas…) para reconstruir el PDF en el worker.

    Caché:
      - cache_key != "" → único por (tenant, kind, cache_key); si está DONE se reusa
        el PDF (para salidas INMUTABLES, p. ej. una receta).
      - cache_key == "" → cada pedido crea un job nuevo y se regenera (para salidas
        MUTABLES: libro clínico, reportes financieros, que cambian con el tiempo).

    No tiene CRUD de usuario: lo crea el servicio (al pedir el PDF) y lo actualiza
    la tarea Celery.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PROCESSING = "processing", "Procesando"
        DONE = "done", "Listo"
        FAILED = "failed", "Falló"

    #: Tipo de PDF (registrado en el registry): "book", "quote", "finance_report"…
    kind = models.CharField(max_length=40, db_index=True)
    #: Clave de caché de la salida; vacía = sin caché (regenerar siempre).
    cache_key = models.CharField(max_length=200, blank=True, default="")
    #: Parámetros JSON-serializables para reconstruir el PDF (ids como str, modo…).
    params = models.JSONField(default=dict)
    #: Nombre de archivo sugerido para la descarga (lo fija el builder).
    filename = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    file = models.FileField(
        upload_to=pdf_job_path,
        max_length=255,
        null=True,
        blank=True,
        help_text="PDF generado; None hasta que la tarea termina.",
    )
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "pdfs_pdf_jobs"
        ordering = ["-created_at"]
        constraints = [
            # Caché: único por (tenant, kind, cache_key) SOLO cuando hay cache_key.
            # Los jobs sin caché (cache_key="") no chocan entre sí.
            models.UniqueConstraint(
                fields=["tenant", "kind", "cache_key"],
                condition=~models.Q(cache_key=""),
                name="pdf_job_cache_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "kind", "status"],
                name="pdf_job_kind_status_idx",
            ),
        ]
