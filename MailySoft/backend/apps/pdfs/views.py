"""
Vistas compartidas de la app pdfs: estado (polling) y descarga del PDF generado.

Cero lógica de negocio. El endpoint de ENCOLAR vive en cada módulo (con su permiso
y su resolución del recurso); aquí solo se consulta el estado y se sirve el archivo,
revalidando el permiso registrado para el `kind` del job (defensa en profundidad).
"""

import uuid

from django.http import HttpResponse
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.views import TenantAPIView
from apps.pdfs.models import PdfJob
from apps.pdfs.registry import get_pdf_kind
from apps.pdfs.selectors import pdf_job_get


class PdfRenderer(BaseRenderer):
    """Renderer que permite a DRF negociar `application/pdf` (la vista responde
    con un HttpResponse crudo; sin esto, Accept: application/pdf daría 406)."""

    media_type = "application/pdf"
    format = "pdf"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):  # type: ignore[no-untyped-def]
        return data


def _kind_permission_ok(request: Request, view: TenantAPIView, job: PdfJob) -> bool:
    """Revalida el permiso role-based registrado para el kind del job."""
    try:
        spec = get_pdf_kind(job.kind)
    except KeyError:
        return False
    return bool(spec.permission().has_permission(request, view))


class PdfJobStatusApi(TenantAPIView):
    """GET /api/v1/pdfs/job/<job_id>/ — estado del trabajo de PDF.

    Devuelve {status} (pending/processing/done/failed). El frontend lo consulta
    cada ~2 s hasta done (o failed). Anti-IDOR por tenant + permiso del kind.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, job_id: uuid.UUID) -> Response:
        """Retorna el estado del trabajo de PDF."""
        try:
            job = pdf_job_get(job_id=job_id)
        except PdfJob.DoesNotExist:
            return Response(
                {"detail": "Trabajo de PDF no encontrado."},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        if not _kind_permission_ok(request, self, job):
            # 404 (no 403) para no revelar la existencia de un job ajeno.
            return Response(
                {"detail": "Trabajo de PDF no encontrado."},
                status=http_status.HTTP_404_NOT_FOUND,
            )

        body: dict[str, object] = {"status": job.status}
        if job.status == PdfJob.Status.FAILED:
            body["detail"] = "No se pudo generar el PDF. Intenta de nuevo."
        return Response(body)


class PdfJobFileApi(TenantAPIView):
    """GET /api/v1/pdfs/job/<job_id>/file/ — descarga el PDF generado.

    Sirve el PDF (autenticado con Bearer) solo cuando el job está "done"; si aún
    no → 409. Headers de seguridad: X-Frame-Options DENY, X-Content-Type-Options
    nosniff, Content-Disposition inline. Anti-IDOR por tenant + permiso del kind.
    """

    permission_classes = [IsAuthenticated]
    renderer_classes = [PdfRenderer]

    def get(self, request: Request, job_id: uuid.UUID) -> HttpResponse:
        """Devuelve el PDF del job si está listo."""
        try:
            job = pdf_job_get(job_id=job_id)
        except PdfJob.DoesNotExist:
            return HttpResponse(content=b"Trabajo de PDF no encontrado.", status=404)
        if not _kind_permission_ok(request, self, job):
            return HttpResponse(content=b"Trabajo de PDF no encontrado.", status=404)

        if job.status != PdfJob.Status.DONE or not job.file:
            return HttpResponse(content=b"El PDF aun no esta listo.", status=409)

        pdf_bytes = job.file.read()
        filename = job.filename or f"{job.kind}.pdf"
        response = HttpResponse(content=pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"
        return response
