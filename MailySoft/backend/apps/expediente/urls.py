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

Rutas — Resumen Clínico por consulta (documento entregable al paciente):
    expediente/evoluciones/<evolution_id>/resumen/borrador/
        ClinicalSummaryDraftApi        GET borrador (no persiste)
    expediente/evoluciones/<evolution_id>/resumen/
        ClinicalSummaryCreateApi       POST crea (constancia)
    expediente/resumenes/<summary_id>/pdf/
        ClinicalSummaryPdfApi          GET encola PDF (202)
    expediente/<patient_id>/resumenes/
        PatientClinicalSummaryListApi  GET lista paginada

Rutas — Plan Integral de Longevidad y Medicina Regenerativa (constancia
entregable al paciente, nace del paciente — Fase 1):
    expediente/<patient_id>/plan-integral/borrador/
        LongevityPlanDraftApi          GET borrador (no persiste)
    expediente/<patient_id>/plan-integral/
        LongevityPlanListCreateApi     GET lista paginada / POST crea (constancia)
    expediente/plan-integral/<plan_id>/pdf/
        LongevityPlanPdfApi            GET encola PDF (202)

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
    ClinicalSummaryCreateApi,
    ClinicalSummaryDraftApi,
    ClinicalSummaryPdfApi,
    DiagnosisListCreateApi,
    DiagnosisResolveApi,
    DocumentTemplateDetailApi,
    DocumentTemplateListCreateApi,
    EvolutionImageDeleteApi,
    EvolutionImageListCreateApi,
    EvolutionNoteListCreateApi,
    LabAnalyteDetailApi,
    LabAnalyteListCreateApi,
    LongevityPlanDraftApi,
    LongevityPlanListCreateApi,
    LongevityPlanPdfApi,
    MedicalHistoryApi,
    MedicalHistoryQuestionDetailApi,
    MedicalHistoryQuestionListCreateApi,
    NursingInstructionListApi,
    PatientBookApi,
    PatientBookPdfApi,
    PatientClinicalSummaryListApi,
    TreatmentPlanDetailApi,
    TreatmentPlanFromPackageApi,
    TreatmentPlanListCreateApi,
    TreatmentPlanPdfApi,
    TreatmentPlanQuoteApi,
    TreatmentSessionScheduleApi,
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
    # Resumen Clínico por consulta (documento entregable al paciente).
    # 'resumen/borrador/' va ANTES de 'resumen/' (misma convención de acciones
    # específicas antes de la ruta base).
    path(
        "expediente/evoluciones/<uuid:evolution_id>/resumen/borrador/",
        ClinicalSummaryDraftApi.as_view(),
        name="clinical-summary-draft",
    ),
    path(
        "expediente/evoluciones/<uuid:evolution_id>/resumen/",
        ClinicalSummaryCreateApi.as_view(),
        name="clinical-summary-create",
    ),
    path(
        "expediente/resumenes/<uuid:summary_id>/pdf/",
        ClinicalSummaryPdfApi.as_view(),
        name="clinical-summary-pdf",
    ),
    path(
        "expediente/<uuid:patient_id>/resumenes/",
        PatientClinicalSummaryListApi.as_view(),
        name="clinical-summary-list",
    ),
    # Plan Integral de Longevidad y Medicina Regenerativa (constancia entregable,
    # documento entregable al paciente, análogo al Resumen Clínico — Fase 1).
    # 'plan-integral/borrador/' va ANTES de 'plan-integral/' (misma convención
    # de acciones específicas antes de la ruta base). La ruta del PDF usa el
    # prefijo literal 'plan-integral/' (sin patient_id) — no colisiona con
    # '<uuid:patient_id>/plan-integral/' porque "plan-integral" no matchea <uuid>.
    path(
        "expediente/<uuid:patient_id>/plan-integral/borrador/",
        LongevityPlanDraftApi.as_view(),
        name="longevity-plan-draft",
    ),
    path(
        "expediente/plan-integral/<uuid:plan_id>/pdf/",
        LongevityPlanPdfApi.as_view(),
        name="longevity-plan-pdf",
    ),
    path(
        "expediente/<uuid:patient_id>/plan-integral/",
        LongevityPlanListCreateApi.as_view(),
        name="longevity-plan-list-create",
    ),
    # Calendarización de tratamientos (esquema de protocolos, Fases 1-4).
    # 'calendarizaciones/<plan_id>/pdf/', '.../cotizacion/' y
    # 'calendarizaciones/sesiones/<id>/agendar/' van ANTES que la ruta de
    # detalle genérica, siguiendo la misma convención de acciones específicas
    # antes de la ruta base usada en el resto del archivo.
    path(
        "expediente/calendarizaciones/<uuid:plan_id>/pdf/",
        TreatmentPlanPdfApi.as_view(),
        name="treatment-plan-pdf",
    ),
    path(
        "expediente/calendarizaciones/<uuid:plan_id>/cotizacion/",
        TreatmentPlanQuoteApi.as_view(),
        name="treatment-plan-quote",
    ),
    path(
        "expediente/calendarizaciones/sesiones/<uuid:session_id>/agendar/",
        TreatmentSessionScheduleApi.as_view(),
        name="treatment-session-schedule",
    ),
    path(
        "expediente/calendarizaciones/<uuid:plan_id>/",
        TreatmentPlanDetailApi.as_view(),
        name="treatment-plan-detail",
    ),
    # 'desde-paquete/' (Fase 3) va ANTES de la ruta de lista/creación genérica
    # por la misma convención de acciones específicas primero.
    path(
        "expediente/<uuid:patient_id>/calendarizaciones/desde-paquete/",
        TreatmentPlanFromPackageApi.as_view(),
        name="treatment-plan-from-package",
    ),
    path(
        "expediente/<uuid:patient_id>/calendarizaciones/",
        TreatmentPlanListCreateApi.as_view(),
        name="treatment-plan-list-create",
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
    # Libro Clínico — Fase 1 (GET JSON, solo lectura, roles clínicos)
    # La ruta del PDF va ANTES para evitar que el router confunda "pdf" con otro recurso.
    path(
        "expediente/<uuid:patient_id>/libro/pdf/",
        PatientBookPdfApi.as_view(),
        name="patient-book-pdf",
    ),
    path(
        "expediente/<uuid:patient_id>/libro/",
        PatientBookApi.as_view(),
        name="patient-book",
    ),
    # Fase 2 — Preguntas extra configurables de HC
    # La ruta de detalle va ANTES de la de listado para evitar colisiones de segmentos.
    path(
        "expediente/preguntas-hc/<uuid:question_id>/",
        MedicalHistoryQuestionDetailApi.as_view(),
        name="mhq-detail",
    ),
    path(
        "expediente/preguntas-hc/",
        MedicalHistoryQuestionListCreateApi.as_view(),
        name="mhq-list-create",
    ),
    # Catálogo de plantillas de documento (Plan Integral de Longevidad — Fase 2).
    # La ruta de detalle va ANTES de la de listado para evitar colisiones de segmentos.
    path(
        "expediente/plantillas-documento/<uuid:template_id>/",
        DocumentTemplateDetailApi.as_view(),
        name="document-template-detail",
    ),
    path(
        "expediente/plantillas-documento/",
        DocumentTemplateListCreateApi.as_view(),
        name="document-template-list-create",
    ),
    # Catálogo de analitos de laboratorio (Plan Integral de Longevidad — Fase 3).
    path(
        "expediente/analitos/<uuid:analyte_id>/",
        LabAnalyteDetailApi.as_view(),
        name="lab-analyte-detail",
    ),
    path(
        "expediente/analitos/",
        LabAnalyteListCreateApi.as_view(),
        name="lab-analyte-list-create",
    ),
]
