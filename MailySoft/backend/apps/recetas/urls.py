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

ORDEN: rutas de acción específica (/anular/) van ANTES del detalle para evitar
       colisión. Medicamentos van antes de recetas para evitar ambigüedad.
       La ruta de historial sigue el patrón expediente/<patient_id>/<recurso>/
       establecido por la app expediente.
"""

from django.urls import path

from apps.recetas.views import (
    MedicationCreateApi,
    MedicationSearchApi,
    PrescriptionCancelApi,
    PrescriptionDetailApi,
    PrescriptionListCreateApi,
    PrescriptionPdfApi,
)

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
    # B1.3 — PDF de la receta (va ANTES del detalle para evitar colisión con el suffix /pdf/)
    path(
        "recetas/<uuid:prescription_id>/pdf/",
        PrescriptionPdfApi.as_view(),
        name="prescription-pdf",
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
]
