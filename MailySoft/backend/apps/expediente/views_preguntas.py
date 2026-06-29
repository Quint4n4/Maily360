"""
Vistas de las preguntas extra configurables de la Historia Clínica (Fase 2).

Extraído de expediente/views.py. CRUD de MedicalHistoryQuestion (catálogo por
clínica de preguntas adicionales de HC). Vistas delgadas.
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import MedicalHistoryQuestionPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.selectors import (
    medical_history_question_get,
    medical_history_questions_list,
)
from apps.expediente.serializers import (
    MedicalHistoryQuestionInputSerializer,
    MedicalHistoryQuestionOutputSerializer,
)
from apps.expediente.services import (
    medical_history_question_create,
    medical_history_question_deactivate,
    medical_history_question_update,
)


class MedicalHistoryQuestionListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/preguntas-hc/ — lista preguntas extra del tenant.
    POST /api/v1/expediente/preguntas-hc/ — crea una pregunta nueva.

    Anti-IDOR: el TenantManager garantiza aislamiento por tenant automáticamente.

    Query params para GET:
        include_inactive: bool — si True, incluye preguntas inactivas.
                                  Default: False (solo activas).
    """

    permission_classes = [IsAuthenticated, MedicalHistoryQuestionPermission]

    def get(self, request: Request) -> Response:
        """Lista las preguntas extra de la clínica (activas por defecto)."""
        only_active = request.query_params.get("include_inactive", "").lower() not in (
            "true", "1", "yes"
        )
        qs = medical_history_questions_list(only_active=only_active)
        return Response(MedicalHistoryQuestionOutputSerializer(qs, many=True).data)

    def post(self, request: Request) -> Response:
        """Crea una pregunta extra para el formulario de HC de la clínica."""
        s = MedicalHistoryQuestionInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            question = medical_history_question_create(
                tenant=tenant,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            MedicalHistoryQuestionOutputSerializer(question).data,
            status=status.HTTP_201_CREATED,
        )


class MedicalHistoryQuestionDetailApi(TenantAPIView):
    """PATCH  /api/v1/expediente/preguntas-hc/<question_id>/ — edita pregunta.
    DELETE /api/v1/expediente/preguntas-hc/<question_id>/ — desactiva pregunta.

    Anti-IDOR: toda lectura por id pasa por el selector (TenantManager filtra).
    Recurso de otro tenant → DoesNotExist → 404 (no 403).
    """

    permission_classes = [IsAuthenticated, MedicalHistoryQuestionPermission]

    def patch(self, request: Request, question_id: uuid.UUID) -> Response:
        """Edita campos mutables de la pregunta (label, field_type, options, section, order, is_required)."""
        from apps.expediente.models import MedicalHistoryQuestion  # noqa: PLC0415

        try:
            question = medical_history_question_get(question_id=question_id)
        except MedicalHistoryQuestion.DoesNotExist:
            return Response(
                {"detail": "Pregunta no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = MedicalHistoryQuestionInputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        try:
            question = medical_history_question_update(
                question=question,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(MedicalHistoryQuestionOutputSerializer(question).data)

    def delete(self, request: Request, question_id: uuid.UUID) -> Response:
        """Desactiva la pregunta (baja lógica — D-EC-5, idempotente)."""
        from apps.expediente.models import MedicalHistoryQuestion  # noqa: PLC0415

        try:
            question = medical_history_question_get(question_id=question_id)
        except MedicalHistoryQuestion.DoesNotExist:
            return Response(
                {"detail": "Pregunta no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            medical_history_question_deactivate(
                question=question,
                user=request.user,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)
