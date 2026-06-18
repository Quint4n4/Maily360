"""
Vistas de la app recetas — sub-fases B1.1 y B1.2.

Vistas delgadas: parsean el request, llaman un selector o service, devuelven Response.
Cero lógica de negocio aquí. Heredan de TenantAPIView.

Endpoints B1.1:
    GET  /api/v1/recetas/medicamentos/buscar/?q=  — autocompletar (global + custom).
    POST /api/v1/recetas/medicamentos/            — crear medicamento custom (médico).

Endpoints B1.2:
    GET  /api/v1/expediente/<patient_id>/recetas/ — historial del paciente (paginado).
    POST /api/v1/expediente/<patient_id>/recetas/ — crear receta (solo médico activo).
    GET  /api/v1/recetas/<prescription_id>/       — detalle completo.
    POST /api/v1/recetas/<prescription_id>/anular/ — anular con motivo.

Anti-IDOR:
    Selectors usan TenantManager; recurso de otro tenant → 404, nunca 403.

Permisos:
    MedicationPermission: GET = CLINICAL_READ, POST = {owner, admin, doctor}.
    PrescriptionPermission: GET = CLINICAL_READ, POST = {owner, admin, doctor}.
    La validación fina de "solo el médico puede crear" la hace prescription_create.
    La validación fina de "solo el emisor o admin/owner puede anular" la hace
    prescription_cancel.
"""

import logging
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.core.permissions import MedicationPermission, PrescriptionPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.recetas.selectors import (
    SEARCH_LIMIT,
    medication_search,
    prescription_get,
    prescription_list,
)
from apps.recetas.serializers import (
    MedicationCreateInputSerializer,
    MedicationCreateOutputSerializer,
    MedicationSearchOutputSerializer,
    PrescriptionCancelInputSerializer,
    PrescriptionCreateInputSerializer,
    PrescriptionDetailOutputSerializer,
    PrescriptionListOutputSerializer,
)
from apps.recetas.services import medication_create, prescription_cancel, prescription_create

logger = logging.getLogger("apps.recetas.views")


class _PrescriptionPagination(PageNumberPagination):
    """Paginación para el historial de recetas.

    page_size=20 con máximo 100. Las recetas incluyen texto clínico;
    páginas más pequeñas reducen la carga de serialización.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MedicationSearchApi(TenantAPIView):
    """GET /api/v1/recetas/medicamentos/buscar/?q=<texto>

    Autocompletado de medicamentos. Une catálogo global + custom del tenant.
    Requiere ?q= con al menos 1 carácter (si q vacío devuelve []).

    Parámetros:
        q:     Texto de búsqueda (icontains en generic_name y commercial_name).
        limit: Número máximo de resultados (default=25, máx=50).

    Respuesta 200:
        Lista de medicamentos con `source` = "global" | "custom".

    Auditoría (B1.1 audit M2 — exclusión deliberada):
        El autocompletado NO se registra en AuditLog. Buscar en un catálogo de
        medicamentos no es acceso al expediente de un paciente (los READ clínicos
        —historia, signos, evolución, diagnósticos— sí se auditan en `apps/expediente`).
        Auditar cada tecleo del buscador inflaría el log sin valor forense. La
        trazabilidad clínica recae sobre la RECETA (PRESCRIPTION_CREATE/READ/CANCEL,
        sub-fase B1.2) y sobre el alta de medicamentos custom (MEDICATION_CREATE).
    """

    permission_classes = [IsAuthenticated, MedicationPermission]

    def get(self, request: Request) -> Response:
        q: str = request.query_params.get("q", "")

        # Parsear y validar limit del query param.
        try:
            limit = int(request.query_params.get("limit", SEARCH_LIMIT))
            limit = max(1, min(limit, 50))  # clamp entre 1 y 50
        except (ValueError, TypeError):
            limit = SEARCH_LIMIT

        results = medication_search(q=q, limit=limit)
        out = MedicationSearchOutputSerializer(results, many=True)
        return Response(out.data, status=status.HTTP_200_OK)


class MedicationCreateApi(TenantAPIView):
    """POST /api/v1/recetas/medicamentos/

    Crea un medicamento custom para el tenant activo.
    Solo owner, admin y doctor pueden crear (MedicationPermission).

    Cuerpo:
        generic_name  (requerido)
        form          (requerido, choices de MedicationForm)
        commercial_name (opcional)
        concentration   (opcional)
        presentation    (opcional)

    Respuesta 201: Medication recién creado.
    """

    permission_classes = [IsAuthenticated, MedicationPermission]

    def post(self, request: Request) -> Response:
        serializer = MedicationCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = get_current_tenant()

        try:
            med = medication_create(
                tenant=tenant,
                user=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out = MedicationCreateOutputSerializer(med)
        return Response(out.data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# B1.2 — Recetas médicas
# ---------------------------------------------------------------------------


class PrescriptionListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/<patient_id>/recetas/ — historial paginado.
    POST /api/v1/expediente/<patient_id>/recetas/ — emitir receta nueva.

    GET:
        Lista todas las recetas del paciente (activas y anuladas) en -issued_at.
        Registra PRESCRIPTION_READ en AuditLog (NOM-024). Si falla → logger.critical
        pero el acceso continúa (disponibilidad clínica > registro estricto).

    POST:
        El actor DEBE tener perfil de Doctor activo en el tenant (prescription_create
        llama doctor_get_for_user y lanza ValidationError si no lo tiene → 403).
        El doctor es el del perfil activo del usuario (no se acepta doctor_id en body).
        Responde 201 con el detalle completo de la receta recién creada.

    Anti-IDOR: patient_get usa TenantManager; paciente de otro tenant → 404.
    """

    permission_classes = [IsAuthenticated, PrescriptionPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista el historial de recetas del paciente, paginado."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tenant = get_current_tenant()

        # Bitácora (NOM-024): PRESCRIPTION_READ
        # B-1: resource_repr usa prefijo "patient_uuid=" para coherencia con el
        # formato del detalle (folio=...) — sigue siendo UUID, no PII.
        audit_result = audit_record(
            action=ActionType.PRESCRIPTION_READ,
            resource_type="Prescription",
            actor=request.user,
            tenant=tenant,
            resource_id=None,
            resource_repr=f"patient_uuid={patient.id}",
            metadata={"patient_id": str(patient.id)},
        )
        if audit_result is None:
            logger.critical(
                "ACCESO A RECETAS SIN REGISTRO EN BITÁCORA — "
                "acción PRESCRIPTION_READ no pudo guardarse. "
                "tenant_id=%s patient_id=%s actor_id=%s.",
                str(tenant.id) if tenant is not None else "None",
                str(patient.id),
                str(getattr(request.user, "pk", "anon")),
            )

        qs = prescription_list(patient=patient)
        paginator = _PrescriptionPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                PrescriptionListOutputSerializer(page, many=True).data
            )
        return Response(
            {"detail": "Paginación no disponible."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Emite una receta médica nueva para el paciente."""
        try:
            patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = PrescriptionCreateInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()

        # Inyectar active_role en el usuario para que el service lo lea en audit
        request.user.active_role = getattr(request, "active_role", "")  # type: ignore[union-attr]

        try:
            prescription = prescription_create(
                tenant=tenant,
                user=request.user,
                patient_id=patient_id,
                items_data=s.validated_data["items"],
                appointment_id=s.validated_data.get("appointment_id"),
                evolution_note_id=s.validated_data.get("evolution_note_id"),
                recommendations=s.validated_data.get("recommendations", ""),
            )
        except DjangoValidationError as exc:
            # Solo capturamos errores de DATOS (400). Los errores de autorización
            # (PermissionDenied de DRF) se dejan propagar para que DRF los convierta
            # en 403 automáticamente. (M-2)
            msg = exc.message if hasattr(exc, "message") else str(exc)
            return Response(
                {"detail": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Refrescar con selects completos para la respuesta
        from apps.recetas.selectors import prescription_get as _prescription_get
        full = _prescription_get(prescription_id=prescription.id)
        return Response(
            PrescriptionDetailOutputSerializer(full).data,
            status=status.HTTP_201_CREATED,
        )


class PrescriptionDetailApi(TenantAPIView):
    """GET /api/v1/recetas/<prescription_id>/ — detalle completo de una receta.

    Incluye: folio, fechas, doctor, paciente UUID, ítems ordenados,
    vitals_snapshot, estado de anulación.

    Diseñado para el flujo "copiar de previa": el frontend hace GET de este
    endpoint y prellena el formulario de la nueva receta con los datos.

    Registra PRESCRIPTION_READ en AuditLog (NOM-024).
    Anti-IDOR: prescription_get usa TenantManager → 404 para recursos ajenos.
    """

    permission_classes = [IsAuthenticated, PrescriptionPermission]

    def get(self, request: Request, prescription_id: uuid.UUID) -> Response:
        """Detalle completo de la receta."""
        from apps.recetas.models import Prescription

        try:
            prescription = prescription_get(prescription_id=prescription_id)
        except Prescription.DoesNotExist:
            return Response(
                {"detail": "Receta no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tenant = get_current_tenant()
        audit_record(
            action=ActionType.PRESCRIPTION_READ,
            resource_type="Prescription",
            actor=request.user,
            tenant=tenant,
            resource_id=prescription.id,
            resource_repr=f"folio={prescription.folio}",
            metadata={"folio": prescription.folio},
        )

        return Response(
            PrescriptionDetailOutputSerializer(prescription).data,
            status=status.HTTP_200_OK,
        )


class PdfRenderer(BaseRenderer):
    """Renderer que permite a DRF negociar `application/pdf`.

    La vista del PDF devuelve un `HttpResponse` crudo (no un `Response` de DRF),
    pero DRF igual ejecuta la negociación de contenido al entrar: sin un renderer
    que declare `application/pdf`, un cliente que mande `Accept: application/pdf`
    (como el frontend al descargar el PDF) recibe 406. Este renderer cierra ese
    hueco; su `render` no se usa porque la vista responde con HttpResponse directo.
    """

    media_type = "application/pdf"
    format = "pdf"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):  # type: ignore[no-untyped-def]
        return data


class PrescriptionPdfApi(TenantAPIView):
    """GET /api/v1/recetas/<prescription_id>/pdf/ — PDF de la receta con membrete.

    Genera el PDF de la receta en tiempo real usando xhtml2pdf y lo devuelve
    como respuesta con Content-Type application/pdf.

    Diseño:
        - Permiso: CLINICAL_READ (mismo que leer el detalle). Recepción y finanzas
          NO tienen acceso al PDF de la receta (DR-6). El PDF es un documento
          clínico completo y tiene el mismo nivel de sensibilidad que el detalle.
        - Devuelve `inline; filename="receta-<folio>.pdf"` para abrirse en el
          navegador sin forzar descarga (el frontend decide si descargar o previsualizar).
        - Bitácora: PRESCRIPTION_PDF con resource_repr = folio (sin PII).
        - Anti-IDOR: prescription_get usa TenantManager; receta de otro tenant → 404.
        - Si la generación del PDF falla (RuntimeError de xhtml2pdf), devuelve 500
          con un mensaje genérico y registra el error en el logger.
    """

    permission_classes = [IsAuthenticated, PrescriptionPermission]
    # Permite negociar Accept: application/pdf (el frontend lo pide así) → evita 406.
    renderer_classes = [PdfRenderer]

    def get(self, request: Request, prescription_id: uuid.UUID) -> HttpResponse:
        """Genera y devuelve el PDF de la receta."""
        from apps.recetas.models import Prescription
        from apps.recetas.pdf import prescription_pdf_build

        try:
            prescription = prescription_get(prescription_id=prescription_id)
        except Prescription.DoesNotExist:
            return HttpResponse(
                content=b"Receta no encontrada.",
                status=404,
            )

        tenant = get_current_tenant()

        # Bitácora NOM-024: PRESCRIPTION_PDF — sin PII, solo folio.
        audit_record(
            action=ActionType.PRESCRIPTION_PDF,
            resource_type="Prescription",
            actor=request.user,
            tenant=tenant,
            resource_id=prescription.id,
            resource_repr=f"folio={prescription.folio}",
            metadata={"folio": prescription.folio},
        )

        try:
            pdf_bytes = prescription_pdf_build(prescription=prescription)
        except RuntimeError as exc:
            logger.error(
                "PrescriptionPdfApi: error al generar PDF — prescription_id=%s — %s",
                prescription_id,
                exc,
            )
            return HttpResponse(
                content=b"Error al generar el PDF. Intente nuevamente.",
                status=500,
            )

        filename = f"receta-{prescription.folio}.pdf"
        response = HttpResponse(content=pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        # Headers de seguridad (MEDIO-4): el SecurityMiddleware de Django no los
        # añade a HttpResponse directo (solo a respuestas que pasan por el stack
        # completo de middleware). Se añaden explícitamente aquí.
        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class PrescriptionCancelApi(TenantAPIView):
    """POST /api/v1/recetas/<prescription_id>/anular/ — anular receta con motivo.

    Solo el médico emisor o un owner/admin puede anular.
    La receta no puede estar ya anulada.
    El motivo es requerido.

    Responde 200 con el estado actualizado de la receta.
    """

    permission_classes = [IsAuthenticated, PrescriptionPermission]

    def post(self, request: Request, prescription_id: uuid.UUID) -> Response:
        """Anula la receta médica."""
        from apps.recetas.models import Prescription

        try:
            prescription = prescription_get(prescription_id=prescription_id)
        except Prescription.DoesNotExist:
            return Response(
                {"detail": "Receta no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = PrescriptionCancelInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()

        # Inyectar active_role para que el service evalúe owner/admin vs doctor
        request.user.active_role = getattr(request, "active_role", "")  # type: ignore[union-attr]

        try:
            updated = prescription_cancel(
                prescription=prescription,
                user=request.user,
                tenant=tenant,
                reason=s.validated_data["reason"],
            )
        except DjangoValidationError as exc:
            # Solo capturamos errores de DATOS (400). Los errores de autorización
            # (PermissionDenied de DRF) se dejan propagar para que DRF los convierta
            # en 403 automáticamente. (M-2)
            msg = exc.message if hasattr(exc, "message") else str(exc)
            return Response(
                {"detail": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            PrescriptionDetailOutputSerializer(updated).data,
            status=status.HTTP_200_OK,
        )
