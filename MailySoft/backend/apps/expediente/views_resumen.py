"""
Vistas del Resumen Clínico por consulta (documento entregable al paciente).

Distinto del Libro Clínico (views_libro.py, uso interno y completo): el
Resumen Clínico es un documento SINTÉTICO de UNA consulta, editable por el
médico antes de guardarse como constancia (médico + fecha) y generar su PDF
con el membrete de la clínica.

Endpoints (contrato fijo con el frontend):
    GET  /api/v1/expediente/evoluciones/<evolution_id>/resumen/borrador/
         ClinicalSummaryDraftApi  — arma el borrador auto-rellenado. NO persiste.
    POST /api/v1/expediente/evoluciones/<evolution_id>/resumen/
         ClinicalSummaryCreateApi — guarda la constancia. 201.
    GET  /api/v1/expediente/resumenes/<summary_id>/pdf/
         ClinicalSummaryPdfApi    — encola el PDF (202 {job_id, status}).
    GET  /api/v1/expediente/<patient_id>/resumenes/
         PatientClinicalSummaryListApi — lista paginada de resúmenes del paciente.

Permisos: ClinicalSummaryPermission (owner, admin, doctor) en los 4 endpoints —
es contenido pre-firma que se entrega al paciente, no un registro de solo
consulta (a diferencia de EvolutionPermission.GET, que es CLINICAL_READ).

Anti-IDOR: todos los IDs de la URL se resuelven por selector (TenantManager) o
con validación explícita de tenant. Recurso de otro tenant → 404 (nunca 403).
"""

import logging
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import ClinicalSummaryPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.models import ClinicalSummary, EvolutionNote
from apps.expediente.selectors import clinical_summary_get, clinical_summary_list
from apps.expediente.serializers import (
    ClinicalSummaryDraftOutputSerializer,
    ClinicalSummaryInputSerializer,
    ClinicalSummaryOutputSerializer,
)
from apps.expediente.services_resumen import clinical_summary_create, clinical_summary_draft
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.pdfs.services import pdf_job_enqueue

logger = logging.getLogger("apps.expediente.views_resumen")

_EVOLUTION_NOT_FOUND = Response(
    {"detail": "Nota de evolución no encontrada."},
    status=status.HTTP_404_NOT_FOUND,
)
_SUMMARY_NOT_FOUND = Response(
    {"detail": "Resumen clínico no encontrado."},
    status=status.HTTP_404_NOT_FOUND,
)
_NO_TENANT = Response(
    {"detail": "No se encontró un tenant activo para este request."},
    status=status.HTTP_403_FORBIDDEN,
)


def _get_evolution_or_none(evolution_id: uuid.UUID) -> EvolutionNote | None:
    """Resuelve la evolución por id usando el selector (anti-IDOR)."""
    from apps.expediente.selectors import evolution_note_get  # noqa: PLC0415

    try:
        return evolution_note_get(evolution_id=evolution_id)
    except EvolutionNote.DoesNotExist:
        return None


class ClinicalSummaryDraftApi(TenantAPIView):
    """GET /api/v1/expediente/evoluciones/<evolution_id>/resumen/borrador/

    Arma el borrador del Resumen Clínico auto-rellenado desde el expediente
    (HC + evolución + signos vitales de la consulta). NO persiste nada — el
    frontend precarga el formulario con esta respuesta y el médico la edita
    antes de guardar con ClinicalSummaryCreateApi.

    Respuesta: {"encabezado": {...}, "secciones": {...}} (ver
    ClinicalSummaryDraftOutputSerializer).
    """

    permission_classes = [IsAuthenticated, ClinicalSummaryPermission]

    def get(self, request: Request, evolution_id: uuid.UUID) -> Response:
        """Devuelve el borrador auto-rellenado de la consulta indicada."""
        evolution = _get_evolution_or_none(evolution_id)
        if evolution is None:
            return _EVOLUTION_NOT_FOUND

        draft = clinical_summary_draft(evolution=evolution)
        return Response(
            ClinicalSummaryDraftOutputSerializer(draft).data,
            status=status.HTTP_200_OK,
        )


class ClinicalSummaryCreateApi(TenantAPIView):
    """POST /api/v1/expediente/evoluciones/<evolution_id>/resumen/

    Guarda el Resumen Clínico como constancia (médico + fecha). El texto de
    cada sección llega ya editado por el médico (el borrador es solo una
    sugerencia inicial que arma el frontend).

    Responde 201 con {id, created_at, doctor_name, evolution_id}.
    """

    permission_classes = [IsAuthenticated, ClinicalSummaryPermission]

    def post(self, request: Request, evolution_id: uuid.UUID) -> Response:
        """Crea el resumen clínico de la consulta indicada."""
        evolution = _get_evolution_or_none(evolution_id)
        if evolution is None:
            return _EVOLUTION_NOT_FOUND

        s = ClinicalSummaryInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        actor_role: str = getattr(request, "active_role", "") or ""

        try:
            summary = clinical_summary_create(
                tenant=tenant,
                evolution=evolution,
                actor=request.user,
                actor_role=actor_role,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ClinicalSummaryOutputSerializer(summary).data,
            status=status.HTTP_201_CREATED,
        )


class ClinicalSummaryPdfApi(TenantAPIView):
    """GET /api/v1/expediente/resumenes/<summary_id>/pdf/ — encola el PDF.

    El PDF se genera en SEGUNDO PLANO (Celery, infra apps.pdfs) para no
    bloquear los workers de la API. Devuelve 202 {job_id, status}; el frontend
    hace polling de GET /pdfs/job/<job_id>/ y descarga con .../file/.

    El resumen es una CONSTANCIA (no se edita tras crear), pero cada pedido
    genera un PDF fresco (cache_key="") por simplicidad y consistencia con
    el resto de los PDFs asíncronos del proyecto.
    """

    permission_classes = [IsAuthenticated, ClinicalSummaryPermission]

    def get(self, request: Request, summary_id: uuid.UUID) -> Response:
        """Encola la generación del PDF del resumen clínico."""
        try:
            summary = clinical_summary_get(summary_id=summary_id)
        except ClinicalSummary.DoesNotExist:
            return _SUMMARY_NOT_FOUND

        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        folio_short = str(summary.id).replace("-", "")[:8].upper()
        job = pdf_job_enqueue(
            tenant=tenant,
            kind="resumen_clinico",
            params={"summary_id": str(summary.id)},
            user=request.user,
            cache_key="",
            filename=f"resumen-clinico-{folio_short}.pdf",
        )
        return Response(
            {"job_id": str(job.id), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )


class PatientClinicalSummaryListApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/resumenes/ — lista paginada.

    Devuelve los resúmenes clínicos del paciente, más reciente primero.
    """

    permission_classes = [IsAuthenticated, ClinicalSummaryPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista los resúmenes clínicos del paciente (paginado)."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = clinical_summary_list(patient=patient)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            ClinicalSummaryOutputSerializer(page, many=True).data
        )
