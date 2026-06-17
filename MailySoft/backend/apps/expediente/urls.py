"""
URLs de la app expediente (sub-fases A1, A2, A3 y A4).

Se incluyen en config/urls.py bajo el prefijo api/v1/.

Rutas A1:
    expediente/<patient_id>/alergias/   AllergyListCreateApi  GET list / POST create
    expediente/alergias/<id>/           AllergyResolveApi     DELETE resolve (baja lógica)

Rutas A2:
    expediente/<patient_id>/historia/   MedicalHistoryApi     GET / PUT (upsert)

Rutas A3 — Signos Vitales (Append-only):
    expediente/<patient_id>/signos/series/  VitalSignsSeriesApi       GET series (gráficas)
    expediente/<patient_id>/signos/         VitalSignsListCreateApi   GET list / POST create

Rutas A4 — Notas de Evolución (Inmutables) y Diagnósticos:
    expediente/<patient_id>/evoluciones/          EvolutionNoteListCreateApi GET list / POST create
    expediente/evoluciones/<id>/addendum/         AddendumCreateApi          POST create
    expediente/<patient_id>/diagnosticos/         DiagnosisListCreateApi     GET list / POST create
    expediente/diagnosticos/<id>/resolver/        DiagnosisResolveApi        POST resolver

ORDEN: las rutas estáticas van DESPUÉS de las anidadas por UUID.
Las rutas de series van ANTES de las de lista para evitar confusión de segmentos.
Las rutas de acciones específicas (addendum/, resolver/) van ANTES de las anidadas
por patient_id para evitar colisiones con el router de Django.
"""

from django.urls import path

from apps.expediente.views import (
    AddendumCreateApi,
    AllergyListCreateApi,
    AllergyResolveApi,
    DiagnosisListCreateApi,
    DiagnosisResolveApi,
    EvolutionImageDeleteApi,
    EvolutionImageListCreateApi,
    EvolutionNoteListCreateApi,
    MedicalHistoryApi,
    NursingInstructionListApi,
    VitalSignsListCreateApi,
    VitalSignsSeriesApi,
)

urlpatterns = [
    # A1 — Alergias
    path(
        "expediente/<uuid:patient_id>/alergias/",
        AllergyListCreateApi.as_view(),
        name="allergy-list-create",
    ),
    path(
        "expediente/alergias/<uuid:allergy_id>/",
        AllergyResolveApi.as_view(),
        name="allergy-resolve",
    ),
    # A2 — Historia Clínica
    path(
        "expediente/<uuid:patient_id>/historia/",
        MedicalHistoryApi.as_view(),
        name="medical-history",
    ),
    # A3 — Signos Vitales (Append-only: solo GET y POST)
    # 'signos/series/' va ANTES de 'signos/' para evitar ambigüedad.
    path(
        "expediente/<uuid:patient_id>/signos/series/",
        VitalSignsSeriesApi.as_view(),
        name="vital-signs-series",
    ),
    path(
        "expediente/<uuid:patient_id>/signos/",
        VitalSignsListCreateApi.as_view(),
        name="vital-signs-list-create",
    ),
    # A4 — Notas de Evolución (Inmutables: solo GET y POST)
    # Las rutas de acciones específicas van ANTES para evitar colisiones.
    path(
        "expediente/evoluciones/<uuid:evolution_id>/addendum/",
        AddendumCreateApi.as_view(),
        name="evolution-addendum-create",
    ),
    path(
        "expediente/<uuid:patient_id>/evoluciones/",
        EvolutionNoteListCreateApi.as_view(),
        name="evolution-list-create",
    ),
    # A4 — Diagnósticos
    path(
        "expediente/diagnosticos/<uuid:diagnosis_id>/resolver/",
        DiagnosisResolveApi.as_view(),
        name="diagnosis-resolve",
    ),
    path(
        "expediente/<uuid:patient_id>/diagnosticos/",
        DiagnosisListCreateApi.as_view(),
        name="diagnosis-list-create",
    ),
    # A4 — Indicaciones de enfermería (sub-vista especializada, solo GET)
    path(
        "expediente/<uuid:patient_id>/indicaciones-enfermeria/",
        NursingInstructionListApi.as_view(),
        name="nursing-instructions-list",
    ),
    # Imágenes de evolución — acciones sobre imagen individual van ANTES del listado
    path(
        "expediente/imagenes/<uuid:image_id>/",
        EvolutionImageDeleteApi.as_view(),
        name="evolution-image-delete",
    ),
    path(
        "expediente/evoluciones/<uuid:evolution_id>/imagenes/",
        EvolutionImageListCreateApi.as_view(),
        name="evolution-image-list-create",
    ),
]
