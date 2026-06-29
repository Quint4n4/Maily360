"""
URLs de la app recetas — sub-fases B1.1 y B1.2.

Se incluyen en config/urls.py bajo el prefijo api/v1/.

Rutas B1.1:
    recetas/medicamentos/buscar/  MedicationSearchApi  GET autocompletado
    recetas/medicamentos/         MedicationCreateApi  POST crear custom

Rutas B1.2:
    expediente/<patient_id>/recetas/          PrescriptionListCreateApi  GET historial / POST crear
    recetas/<prescription_id>/anular/         PrescriptionCancelApi      POST anular
    recetas/<prescription_id>/                PrescriptionDetailApi      GET detalle

F5 — Endpoint público (sin auth):
    verificar-receta/<prescription_id>/       PrescriptionVerifyApi  GET verificar QR

ORDEN: rutas de acción específica (/anular/) van ANTES del detalle para evitar
       colisión. Medicamentos van antes de recetas para evitar ambigüedad.
       La ruta de historial sigue el patrón expediente/<patient_id>/<recurso>/
       establecido por la app expediente.
       La ruta pública de verificación usa el prefijo "verificar-receta/" para
       distinguirla semánticamente del resto de la API y facilitar el rate-limiting
       selectivo en el reverse proxy.
"""

from django.urls import path

from apps.recetas.views import (
    MedicationCreateApi,
    MedicationSearchApi,
    PrescriptionCancelApi,
    PrescriptionDetailApi,
    PrescriptionFormatDetailApi,
    PrescriptionFormatListCreateApi,
    PrescriptionListCreateApi,
    PrescriptionPdfJobFileApi,
    PrescriptionPdfJobStatusApi,
    PrescriptionPdfRequestApi,
)
from apps.recetas.views_public import PrescriptionVerifyApi

urlpatterns = [
    # B1.1 — Catálogo de medicamentos
    # La ruta de búsqueda va ANTES de la de creación (evita colisión).
    path(
        "recetas/medicamentos/buscar/",
        MedicationSearchApi.as_view(),
        name="medication-search",
    ),
    path(
        "recetas/medicamentos/",
        MedicationCreateApi.as_view(),
        name="medication-create",
    ),
    # B1.2 — Recetas médicas
    # Historial por paciente (sigue patrón expediente/<patient_id>/<recurso>/)
    path(
        "expediente/<uuid:patient_id>/recetas/",
        PrescriptionListCreateApi.as_view(),
        name="prescription-list-create",
    ),
    # B1.3 — PDF de la receta (ASÍNCRONO con Celery). Las rutas de job van ANTES
    # del detalle/anular para evitar colisión con recetas/<uuid>/.
    path(
        "recetas/pdf-job/<uuid:job_id>/file/",
        PrescriptionPdfJobFileApi.as_view(),
        name="prescription-pdf-job-file",
    ),
    path(
        "recetas/pdf-job/<uuid:job_id>/",
        PrescriptionPdfJobStatusApi.as_view(),
        name="prescription-pdf-job-status",
    ),
    path(
        "recetas/<uuid:prescription_id>/pdf/",
        PrescriptionPdfRequestApi.as_view(),
        name="prescription-pdf-request",
    ),
    # Acción de anulación va ANTES del detalle para evitar conflicto de URL
    path(
        "recetas/<uuid:prescription_id>/anular/",
        PrescriptionCancelApi.as_view(),
        name="prescription-cancel",
    ),
    # Detalle completo (incluye items, snapshot, info para "copiar de previa")
    path(
        "recetas/<uuid:prescription_id>/",
        PrescriptionDetailApi.as_view(),
        name="prescription-detail",
    ),
    # F3 — PrescriptionFormat CRUD
    # Lista + creación van ANTES del detalle para evitar colisión.
    path(
        "recetas/formatos/",
        PrescriptionFormatListCreateApi.as_view(),
        name="prescription-format-list-create",
    ),
    path(
        "recetas/formatos/<uuid:format_id>/",
        PrescriptionFormatDetailApi.as_view(),
        name="prescription-format-detail",
    ),
    # F5 — Verificación pública de autenticidad (sin auth, throttle propio)
    # ORDEN: va al final para no interferir con las rutas privadas de /recetas/.
    path(
        "verificar-receta/<uuid:prescription_id>/",
        PrescriptionVerifyApi.as_view(),
        name="prescription-verify-public",
    ),
]
