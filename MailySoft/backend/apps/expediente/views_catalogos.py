"""
Vistas de los catálogos que alimentan el Plan Integral de Longevidad.

DocumentTemplate (Fase 2) — plantillas de texto reutilizables.
LabAnalyte (Fase 3)       — analitos de laboratorio con rango de referencia.

Vistas delgadas: parsean request, llaman un selector o service, devuelven
Response. Cero lógica de negocio aquí.

Manejo de errores:
    - <Modelo>.DoesNotExist → 404 (nunca 403; no se revela si el recurso
      existe en otro tenant).
    - ValidationError (django.core.exceptions) → 400 con exc.messages.

Patrón de PATCH (igual que apps.finanzas.views.ConceptDetailApi): is_active
se enruta a un service dedicado (activate/deactivate), NUNCA al update
genérico — regla de campos sensibles (django-clean-architecture).
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import DocumentTemplatePermission, LabAnalytePermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.models import DocumentTemplate, LabAnalyte
from apps.expediente.selectors import (
    document_template_get,
    document_template_list,
    lab_analyte_get,
    lab_analyte_list,
)
from apps.expediente.serializers import (
    DocumentTemplateInputSerializer,
    DocumentTemplateOutputSerializer,
    DocumentTemplatePatchSerializer,
    LabAnalyteInputSerializer,
    LabAnalyteOutputSerializer,
    LabAnalytePatchSerializer,
)
from apps.expediente.services_catalogos import (
    document_template_activate,
    document_template_create,
    document_template_deactivate,
    document_template_delete,
    document_template_update,
    lab_analyte_activate,
    lab_analyte_create,
    lab_analyte_deactivate,
    lab_analyte_delete,
    lab_analyte_update,
)

_NO_TENANT = Response(
    {"detail": "No se encontró un tenant activo para este request."},
    status=status.HTTP_403_FORBIDDEN,
)


# ---------------------------------------------------------------------------
# DocumentTemplate — GET/POST plantillas-documento/ y GET/PATCH/DELETE .../<id>/
# ---------------------------------------------------------------------------


class DocumentTemplateListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/plantillas-documento/ — lista paginada del catálogo.
    POST /api/v1/expediente/plantillas-documento/ — crea una plantilla (owner/admin).
    """

    permission_classes = [IsAuthenticated, DocumentTemplatePermission]

    def get(self, request: Request) -> Response:
        """Lista paginada de plantillas de documento del tenant.

        Query params: `section` (opcional), `only_active` (default true).
        """
        section = request.query_params.get("section") or None
        only_active = request.query_params.get("only_active", "true").lower() != "false"

        qs = document_template_list(section=section, only_active=only_active)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            DocumentTemplateOutputSerializer(page, many=True).data
        )

    def post(self, request: Request) -> Response:
        """Crea una plantilla de documento en el tenant del request."""
        s = DocumentTemplateInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        try:
            template = document_template_create(
                tenant=tenant, user=request.user, **s.validated_data
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            DocumentTemplateOutputSerializer(template).data, status=status.HTTP_201_CREATED
        )


class DocumentTemplateDetailApi(TenantAPIView):
    """GET/PATCH/DELETE /api/v1/expediente/plantillas-documento/<id>/."""

    permission_classes = [IsAuthenticated, DocumentTemplatePermission]

    def _get_or_404(
        self, template_id: uuid.UUID
    ) -> "tuple[DocumentTemplate | None, Response | None]":
        try:
            return document_template_get(template_id=template_id), None
        except DocumentTemplate.DoesNotExist:
            return None, Response(
                {"detail": "Plantilla no encontrada."}, status=status.HTTP_404_NOT_FOUND
            )

    def get(self, request: Request, template_id: uuid.UUID) -> Response:
        template, err = self._get_or_404(template_id)
        if err is not None:
            return err
        return Response(DocumentTemplateOutputSerializer(template).data)

    def patch(self, request: Request, template_id: uuid.UUID) -> Response:
        template, err = self._get_or_404(template_id)
        if err is not None:
            return err

        s = DocumentTemplatePatchSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = dict(s.validated_data)
        is_active = data.pop("is_active", None)
        try:
            if is_active is not None:
                if is_active:
                    template = document_template_activate(template=template, user=request.user)  # type: ignore[arg-type]
                else:
                    template = document_template_deactivate(template=template, user=request.user)  # type: ignore[arg-type]
            if data:
                template = document_template_update(template=template, user=request.user, **data)  # type: ignore[arg-type]
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(DocumentTemplateOutputSerializer(template).data)

    def delete(self, request: Request, template_id: uuid.UUID) -> Response:
        template, err = self._get_or_404(template_id)
        if err is not None:
            return err
        document_template_delete(template=template, user=request.user)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# LabAnalyte — GET/POST analitos/ y GET/PATCH/DELETE analitos/<id>/
# ---------------------------------------------------------------------------


class LabAnalyteListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/analitos/ — lista paginada del catálogo.
    POST /api/v1/expediente/analitos/ — crea un analito (owner/admin).
    """

    permission_classes = [IsAuthenticated, LabAnalytePermission]

    def get(self, request: Request) -> Response:
        """Lista paginada de analitos de laboratorio del tenant.

        Query param: `only_active` (default true).
        """
        only_active = request.query_params.get("only_active", "true").lower() != "false"

        qs = lab_analyte_list(only_active=only_active)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(LabAnalyteOutputSerializer(page, many=True).data)

    def post(self, request: Request) -> Response:
        """Crea un analito de laboratorio en el tenant del request."""
        s = LabAnalyteInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        try:
            analyte = lab_analyte_create(tenant=tenant, user=request.user, **s.validated_data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(LabAnalyteOutputSerializer(analyte).data, status=status.HTTP_201_CREATED)


class LabAnalyteDetailApi(TenantAPIView):
    """GET/PATCH/DELETE /api/v1/expediente/analitos/<id>/."""

    permission_classes = [IsAuthenticated, LabAnalytePermission]

    def _get_or_404(self, analyte_id: uuid.UUID) -> "tuple[LabAnalyte | None, Response | None]":
        try:
            return lab_analyte_get(analyte_id=analyte_id), None
        except LabAnalyte.DoesNotExist:
            return None, Response(
                {"detail": "Analito no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

    def get(self, request: Request, analyte_id: uuid.UUID) -> Response:
        analyte, err = self._get_or_404(analyte_id)
        if err is not None:
            return err
        return Response(LabAnalyteOutputSerializer(analyte).data)

    def patch(self, request: Request, analyte_id: uuid.UUID) -> Response:
        analyte, err = self._get_or_404(analyte_id)
        if err is not None:
            return err

        s = LabAnalytePatchSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = dict(s.validated_data)
        is_active = data.pop("is_active", None)
        try:
            if is_active is not None:
                if is_active:
                    analyte = lab_analyte_activate(analyte=analyte, user=request.user)  # type: ignore[arg-type]
                else:
                    analyte = lab_analyte_deactivate(analyte=analyte, user=request.user)  # type: ignore[arg-type]
            if data:
                analyte = lab_analyte_update(analyte=analyte, user=request.user, **data)  # type: ignore[arg-type]
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(LabAnalyteOutputSerializer(analyte).data)

    def delete(self, request: Request, analyte_id: uuid.UUID) -> Response:
        analyte, err = self._get_or_404(analyte_id)
        if err is not None:
            return err
        lab_analyte_delete(analyte=analyte, user=request.user)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)
