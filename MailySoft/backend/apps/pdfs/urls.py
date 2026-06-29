"""Rutas compartidas de PDFs asíncronos (estado + descarga)."""

from django.urls import path

from apps.pdfs.views import PdfJobFileApi, PdfJobStatusApi

urlpatterns = [
    path(
        "pdfs/job/<uuid:job_id>/file/",
        PdfJobFileApi.as_view(),
        name="pdf-job-file",
    ),
    path(
        "pdfs/job/<uuid:job_id>/",
        PdfJobStatusApi.as_view(),
        name="pdf-job-status",
    ),
]
