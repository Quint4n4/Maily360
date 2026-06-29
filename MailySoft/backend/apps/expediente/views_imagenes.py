"""
Vistas de extras de la evolución: imágenes (adjuntar/listar/borrar) e
indicaciones de enfermería (listar).

Extraído de expediente/views.py. Ambas son sub-vistas especializadas de la
nota de evolución (A4). Vistas delgadas.
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import EvolutionPermission, NursingInstructionPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.models import EvolutionImage, EvolutionNote
from apps.expediente.selectors import (
    evolution_image_get,
    evolution_images_list,
    evolution_note_get,
    evolution_nursing_instructions_for_patient,
)
from apps.expediente.serializers import (
    EvolutionImageInputSerializer,
    EvolutionImageOutputSerializer,
    NursingInstructionOutputSerializer,
)
from apps.expediente.services import evolution_image_add, evolution_image_remove
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get


class NursingInstructionListApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/indicaciones-enfermeria/

    Devuelve las notas de evolución del paciente que tienen indicaciones de
    enfermería (campo `indicaciones_enfermeria` no vacío), ordenadas por
    -created_at (más reciente primero), limitadas a los últimos 20 registros.

    Caso de uso principal: la enfermera consulta las indicaciones del médico
    para un paciente antes de o durante la atención.

    Anti-IDOR (ALTO-1):
        patient_id se resuelve por TenantManager. Un patient_id de otro tenant
        → 404 con el mismo mensaje. NUNCA 403 (no revelar existencia cross-tenant).

    Paginación:
        El selector ya aplica limit=20. La respuesta NO usa envoltura de
        paginación (la cantidad máxima es fija y conocida); devuelve lista directa.
        Si en el futuro se necesitara paginación completa, cambiar a PageNumberPagination.

    Permisos:
        GET → CLINICAL_READ: owner, admin, doctor, nurse, readonly.
        Recepción y finanzas NO tienen acceso (contenido clínico sensible).
    """

    permission_classes = [IsAuthenticated, NursingInstructionPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista las indicaciones de enfermería del paciente (máx. últimas 20).

        Responde 404 si el paciente no existe o es de otro tenant (anti-IDOR).
        Responde 200 con lista (puede ser [] si no hay indicaciones aún).
        """
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = evolution_nursing_instructions_for_patient(patient=patient)
        return Response(
            NursingInstructionOutputSerializer(qs, many=True).data,
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Imágenes de Evolución
# ---------------------------------------------------------------------------


class EvolutionImageListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/evoluciones/<evolution_id>/imagenes/ — lista imágenes.
    POST /api/v1/expediente/evoluciones/<evolution_id>/imagenes/ — sube imagen.

    GET: devuelve las imágenes activas de la nota (excluye soft-deleted).
         Permiso: CLINICAL_READ (EvolutionPermission.GET).

    POST: valida el archivo multipart con Pillow (barrera real en el service),
          crea el registro. Responde 201 con la imagen serializada.
          Permiso: escritura clínica (EvolutionPermission.POST = owner/admin/doctor).

    Anti-IDOR: evolution_id se resuelve con el TenantManager → 404 si es de otro
    tenant. Mismo mensaje para existente-pero-otro-tenant que para inexistente.

    Multipart: el cliente debe enviar Content-Type: multipart/form-data con
    el campo 'image' como archivo binario.
    """

    permission_classes = [IsAuthenticated, EvolutionPermission]

    def get(self, request: Request, evolution_id: uuid.UUID) -> Response:
        """Lista las imágenes activas de la nota de evolución."""
        try:
            evolution = evolution_note_get(evolution_id=evolution_id)
        except EvolutionNote.DoesNotExist:
            return Response(
                {"detail": "Nota de evolución no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = evolution_images_list(evolution=evolution)
        return Response(
            EvolutionImageOutputSerializer(
                qs, many=True, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request, evolution_id: uuid.UUID) -> Response:
        """Sube una imagen a la nota de evolución (multipart/form-data).

        El campo 'image' debe ser un archivo binario JPEG, PNG o WEBP.
        La validación de contenido real la hace validate_evolution_image() en el
        service (Pillow). El serializer aquí solo verifica que el campo exista.
        """
        try:
            evolution = evolution_note_get(evolution_id=evolution_id)
        except EvolutionNote.DoesNotExist:
            return Response(
                {"detail": "Nota de evolución no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = EvolutionImageInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            evo_image = evolution_image_add(
                tenant=tenant,
                user=request.user,
                evolution=evolution,
                image=s.validated_data["image"],
                caption=s.validated_data.get("caption", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            EvolutionImageOutputSerializer(evo_image, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class EvolutionImageDeleteApi(TenantAPIView):
    """DELETE /api/v1/expediente/imagenes/<image_id>/ — baja lógica de imagen.

    No borra el archivo físico ni el registro (D-EC-5). Pone deleted_at = ahora.
    Responde 204 No Content en éxito.

    Anti-IDOR: image_id se resuelve con el TenantManager → 404 si es de otro
    tenant. NUNCA 403 para recursos ajenos (no revelar existencia cross-tenant).

    Permiso: escritura clínica (EvolutionPermission.DELETE = owner/admin/doctor).
    """

    permission_classes = [IsAuthenticated, EvolutionPermission]

    def delete(self, request: Request, image_id: uuid.UUID) -> Response:
        """Baja lógica de la imagen (sin borrado físico, D-EC-5)."""
        try:
            evo_image = evolution_image_get(image_id=image_id)
        except EvolutionImage.DoesNotExist:
            return Response(
                {"detail": "Imagen no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            evolution_image_remove(image=evo_image, user=request.user)
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)
