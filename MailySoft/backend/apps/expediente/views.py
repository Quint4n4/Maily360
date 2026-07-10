"""
Vistas de la app expediente (sub-fases A1, A2, A3 y A4).

NOTA (refactor): las vistas se dividieron por recurso en módulos hermanos.
Este archivo solo las RE-EXPORTA para que urls.py y los tests sigan importando
desde `apps.expediente.views` sin cambios:

    views_alergias     — alergias (A1).
    views_historia     — historia clínica (A2).
    views_signos       — signos vitales (A3).
    views_evoluciones  — notas de evolución + diagnósticos (A4).
    views_imagenes     — imágenes de evolución + indicaciones de enfermería (A4).
    views_libro        — libro clínico (JSON + PDF).
    views_preguntas    — preguntas extra de HC (Fase 2).
    views_resumen      — resumen clínico por consulta (borrador, crear, PDF, listar).
    views_calendarizacion — calendarización de tratamientos (esquema de protocolos, Fases 1 y 4).
    views_plan_integral — Plan Integral de Longevidad (borrador, crear/listar, PDF, Fase 1).

Convención de cada módulo: vistas delgadas (parsean el request, llaman un
selector/service, devuelven Response; cero lógica de negocio; heredan de
TenantAPIView).

Endpoints A1:
    GET    /api/v1/expediente/<patient_id>/alergias/   — lista alergias del paciente.
    POST   /api/v1/expediente/<patient_id>/alergias/   — registra una alergia nueva.
    DELETE /api/v1/expediente/alergias/<id>/           — baja lógica (resolve).

Endpoints A2:
    GET /api/v1/expediente/<patient_id>/historia/  — devuelve la HC (o estructura vacía).
    PUT /api/v1/expediente/<patient_id>/historia/  — upsert de la HC.

Endpoints A3:
    GET  /api/v1/expediente/<patient_id>/signos/         — lista tomas (-measured_at).
    POST /api/v1/expediente/<patient_id>/signos/         — registra una toma nueva.
    GET  /api/v1/expediente/<patient_id>/signos/series/  — datos de series para gráficas.

Endpoints A4:
    GET  /api/v1/expediente/<patient_id>/evoluciones/          — lista notas de evolución.
    POST /api/v1/expediente/<patient_id>/evoluciones/          — crea nota (cita ATTENDED).
    POST /api/v1/expediente/evoluciones/<id>/addendum/         — agrega addendum.
    GET  /api/v1/expediente/<patient_id>/diagnosticos/         — lista diagnósticos.
    POST /api/v1/expediente/<patient_id>/diagnosticos/         — crea diagnóstico.
    POST /api/v1/expediente/diagnosticos/<id>/resolver/        — marca como resuelto.

IMPORTANTE — Inmutabilidad (D-EC-1):
    EvolutionNote es INMUTABLE: no existen PATCH, PUT ni DELETE.
    Los métodos no ruteados devuelven 405.

Anti-IDOR (ALTO-1):
    Todos los IDs en la URL se resuelven por TenantManager o con validación
    explícita de tenant. Recurso de otro tenant → 404 con mismo mensaje.
    NUNCA 403 para recursos ajenos (evita oracle de existencia cross-tenant).

Manejo de bitácora (ALTO-2 ruidoso):
    audit_record devuelve None en fallo de BD de auditoría. El GET de evoluciones
    registra EVOLUTION_READ y si falla → logger.critical pero el acceso continúa
    (disponibilidad clínica > registro estricto — mismo trade-off que HC y signos).
"""

from apps.expediente.views_alergias import (  # noqa: F401
    AllergyListCreateApi,
    AllergyResolveApi,
)
from apps.expediente.views_calendarizacion import (  # noqa: F401
    TreatmentPlanDetailApi,
    TreatmentPlanFromPackageApi,
    TreatmentPlanListCreateApi,
    TreatmentPlanPdfApi,
    TreatmentPlanQuoteApi,
    TreatmentSessionScheduleApi,
)
from apps.expediente.views_catalogos import (  # noqa: F401
    DocumentTemplateDetailApi,
    DocumentTemplateListCreateApi,
    LabAnalyteDetailApi,
    LabAnalyteListCreateApi,
)
from apps.expediente.views_evoluciones import (  # noqa: F401
    AddendumCreateApi,
    DiagnosisListCreateApi,
    DiagnosisResolveApi,
    EvolutionNoteListCreateApi,
)
from apps.expediente.views_historia import MedicalHistoryApi  # noqa: F401
from apps.expediente.views_imagenes import (  # noqa: F401
    EvolutionImageDeleteApi,
    EvolutionImageListCreateApi,
    NursingInstructionListApi,
)
from apps.expediente.views_libro import (  # noqa: F401
    PatientBookApi,
    PatientBookPdfApi,
)
from apps.expediente.views_plan_integral import (  # noqa: F401
    LongevityPlanDraftApi,
    LongevityPlanListCreateApi,
    LongevityPlanPdfApi,
)
from apps.expediente.views_preguntas import (  # noqa: F401
    MedicalHistoryQuestionDetailApi,
    MedicalHistoryQuestionListCreateApi,
)
from apps.expediente.views_resumen import (  # noqa: F401
    ClinicalSummaryCreateApi,
    ClinicalSummaryDraftApi,
    ClinicalSummaryPdfApi,
    PatientClinicalSummaryListApi,
)
from apps.expediente.views_signos import (  # noqa: F401
    VitalSignsListCreateApi,
    VitalSignsSeriesApi,
)
