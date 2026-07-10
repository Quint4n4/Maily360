"""
Vistas del Plan Integral de Longevidad y Medicina Regenerativa (Fase 1).

Constancia entregable al paciente, análoga al Resumen Clínico (views_resumen.py)
pero que nace del PACIENTE (no de una consulta) y compone alergias + HC +,
opcionalmente, un esquema de calendarización de tratamientos.

Endpoints (contrato fijo con el frontend):
    GET  /api/v1/expediente/<patient_id>/plan-integral/borrador/
         LongevityPlanDraftApi        — arma el borrador auto-rellenado. NO persiste.
         Query param opcional: treatment_plan_id=<uuid>.
    GET  /api/v1/expediente/<patient_id>/plan-integral/
         LongevityPlanListCreateApi   — lista paginada.
    POST /api/v1/expediente/<patient_id>/plan-integral/
         LongevityPlanListCreateApi   — guarda la constancia. 201.
    GET  /api/v1/expediente/plan-integral/<plan_id>/pdf/
         LongevityPlanPdfApi          — encola el PDF (202 {job_id, status}).

Permisos: LongevityPlanPermission (owner, admin, doctor) en los 4 endpoints —
es contenido pre-firma que se entrega al paciente, no un registro de solo
consulta (mismo criterio que ClinicalSummaryPermission/TreatmentPlanPermission).

Anti-IDOR: todos los IDs de la URL/query se resuelven por selector (TenantManager)
o con validación explícita de tenant/paciente. Recurso de otro tenant → 404
(nunca 403). Un treatment_plan_id de otro PACIENTE del mismo tenant → 400
(ValidationError del service; no es un caso de tenant cruzado).
"""

import logging
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import LongevityPlanPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.models import LongevityPlan, TreatmentPlan
from apps.expediente.selectors import longevity_plan_get, longevity_plan_list
from apps.expediente.serializers import (
    LongevityPlanDraftOutputSerializer,
    LongevityPlanInputSerializer,
    LongevityPlanOutputSerializer,
)
from apps.expediente.services_plan_integral import longevity_plan_create, longevity_plan_draft
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.pdfs.services import pdf_job_enqueue

logger = logging.getLogger("apps.expediente.views_plan_integral")

_PATIENT_NOT_FOUND = Response(
    {"detail": "Paciente no encontrado."},
    status=status.HTTP_404_NOT_FOUND,
)
_PLAN_NOT_FOUND = Response(
    {"detail": "Plan Integral de Longevidad no encontrado."},
    status=status.HTTP_404_NOT_FOUND,
)
_TREATMENT_PLAN_NOT_FOUND = Response(
    {"detail": "Esquema de calendarización no encontrado."},
    status=status.HTTP_404_NOT_FOUND,
)
_NO_TENANT = Response(
    {"detail": "No se encontró un tenant activo para este request."},
    status=status.HTTP_403_FORBIDDEN,
)


def _parse_treatment_plan_id(raw: str | None) -> "tuple[uuid.UUID | None, Response | None]":
    """Parsea el query param treatment_plan_id. None si no vino.

    Returns:
        (uuid_o_None, None) si es válido, o (None, Response(400)) si el
        formato es inválido.
    """
    if not raw:
        return None, None
    try:
        return uuid.UUID(raw), None
    except ValueError:
        return None, Response(
            {"detail": "treatment_plan_id no es un UUID válido."},
            status=status.HTTP_400_BAD_REQUEST,
        )


class LongevityPlanDraftApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/plan-integral/borrador/

    Arma el borrador del Plan Integral auto-rellenado desde el expediente
    (alergias + HC + esquema opcional). NO persiste nada — el frontend
    precarga el formulario con esta respuesta y el médico la edita antes de
    guardar con LongevityPlanListCreateApi.post.

    Query param opcional: treatment_plan_id=<uuid> — precarga el snapshot de
    un esquema de calendarización existente del paciente.

    Respuesta: {"encabezado": {...}, "secciones": {...}, "esquema": [...],
    "planes_disponibles": [...]} (ver LongevityPlanDraftOutputSerializer).
    """

    permission_classes = [IsAuthenticated, LongevityPlanPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Devuelve el borrador auto-rellenado del paciente indicado."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return _PATIENT_NOT_FOUND

        treatment_plan_id, err = _parse_treatment_plan_id(
            request.query_params.get("treatment_plan_id")
        )
        if err is not None:
            return err

        try:
            draft = longevity_plan_draft(patient=patient, treatment_plan_id=treatment_plan_id)
        except TreatmentPlan.DoesNotExist:
            return _TREATMENT_PLAN_NOT_FOUND
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            LongevityPlanDraftOutputSerializer(draft).data,
            status=status.HTTP_200_OK,
        )


class LongevityPlanListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/<patient_id>/plan-integral/ — lista paginada.
    POST /api/v1/expediente/<patient_id>/plan-integral/ — guarda la constancia. 201.
    """

    permission_classes = [IsAuthenticated, LongevityPlanPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista los Planes Integrales de Longevidad del paciente (paginado)."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return _PATIENT_NOT_FOUND

        qs = longevity_plan_list(patient=patient)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(LongevityPlanOutputSerializer(page, many=True).data)

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Crea el Plan Integral de Longevidad del paciente indicado."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return _PATIENT_NOT_FOUND

        s = LongevityPlanInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        actor_role: str = getattr(request, "active_role", "") or ""

        try:
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=request.user,
                actor_role=actor_role,
                **s.validated_data,
            )
        except TreatmentPlan.DoesNotExist:
            return _TREATMENT_PLAN_NOT_FOUND
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            LongevityPlanOutputSerializer(plan).data,
            status=status.HTTP_201_CREATED,
        )


class LongevityPlanPdfApi(TenantAPIView):
    """GET /api/v1/expediente/plan-integral/<plan_id>/pdf/ — encola el PDF.

    El PDF se genera en SEGUNDO PLANO (Celery, infra apps.pdfs) para no
    bloquear los workers de la API. Devuelve 202 {job_id, status}; el frontend
    hace polling de GET /pdfs/job/<job_id>/ y descarga con .../file/.

    El plan es una CONSTANCIA (no se edita tras crear), pero cada pedido
    genera un PDF fresco (cache_key="") por simplicidad y consistencia con
    el resto de los PDFs asíncronos del proyecto.
    """

    permission_classes = [IsAuthenticated, LongevityPlanPermission]

    def get(self, request: Request, plan_id: uuid.UUID) -> Response:
        """Encola la generación del PDF del Plan Integral de Longevidad."""
        try:
            plan = longevity_plan_get(plan_id=plan_id)
        except LongevityPlan.DoesNotExist:
            return _PLAN_NOT_FOUND

        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        folio_short = str(plan.id).replace("-", "")[:8].upper()
        job = pdf_job_enqueue(
            tenant=tenant,
            kind="plan_integral",
            params={"plan_id": str(plan.id)},
            user=request.user,
            cache_key="",
            filename=f"plan-integral-{folio_short}.pdf",
        )
        return Response(
            {"job_id": str(job.id), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )
