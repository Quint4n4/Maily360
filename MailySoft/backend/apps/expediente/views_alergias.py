"""
Vistas de alergias del paciente (A1).

Extraído de expediente/views.py. Lista/crea alergias y hace baja lógica
(resolve). Vistas delgadas.
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import AllergyPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.models import Allergy
from apps.expediente.selectors import allergy_get, allergy_list
from apps.expediente.serializers import (
    AllergyInputSerializer,
    AllergyOutputSerializer,
)
from apps.expediente.services import allergy_create, allergy_resolve
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get


class AllergyListCreateApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/alergias/  — lista alergias del paciente.
    POST /api/v1/expediente/<patient_id>/alergias/  — registra una alergia nueva.

    Query params para GET:
        include_resolved: bool — si True, incluye también las resueltas (is_active=False).
                                  Default: False (solo vigentes).
    """

    permission_classes = [IsAuthenticated, AllergyPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista las alergias del paciente (vigentes por defecto)."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Parsear include_resolved del query param (D-EC-5: podemos ver las resueltas).
        include_resolved_raw: str = request.query_params.get("include_resolved", "false")
        include_resolved: bool = include_resolved_raw.lower() in ("true", "1", "yes")
        only_active: bool = not include_resolved

        qs = allergy_list(patient=patient, only_active=only_active)
        return Response(AllergyOutputSerializer(qs, many=True).data)

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Registra una alergia nueva para el paciente."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = AllergyInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            allergy = allergy_create(
                tenant=tenant,
                user=request.user,
                patient=patient,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            AllergyOutputSerializer(allergy).data,
            status=status.HTTP_201_CREATED,
        )


class AllergyResolveApi(TenantAPIView):
    """DELETE /api/v1/expediente/alergias/<id>/  — baja lógica de la alergia.

    No borra el registro (D-EC-5). Pone is_active=False (resuelta clínicamente).
    Responde 204 No Content en éxito.
    """

    permission_classes = [IsAuthenticated, AllergyPermission]

    def delete(self, request: Request, allergy_id: uuid.UUID) -> Response:
        """Marca la alergia como resuelta (baja lógica, sin borrado físico)."""
        try:
            allergy = allergy_get(allergy_id=allergy_id)
        except Allergy.DoesNotExist:
            return Response(
                {"detail": "Alergia no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        allergy_resolve(allergy=allergy, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
