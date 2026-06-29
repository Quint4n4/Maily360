"""
Vistas del Libro Clínico del paciente (JSON paginado + PDF WeasyPrint).

Extraído de expediente/views.py. Vistas delgadas: resuelven el paciente
(anti-IDOR), registran bitácora NOM-024 y delegan en book_build/book_build_all.
"""

import logging
import uuid

from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.core.permissions import EvolutionPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.selectors import book_build, book_build_all
from apps.expediente.serializers import PatientBookSerializer
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get

logger = logging.getLogger("apps.expediente.views_libro")


class PatientBookApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/libro/

    Devuelve el libro clínico completo del paciente en JSON, paginado por
    capítulos (evoluciones), ordenado más reciente primero (D-LIB-3).

    Permisos:
        Solo roles clínicos (EvolutionPermission.GET = CLINICAL_READ):
        owner, admin, doctor, nurse, readonly.
        Recepción y finanzas NO tienen acceso (D-LIB-6).
        Se reusa EXACTAMENTE el mismo permiso que la vista EvolutionNoteListCreateApi.

    Paginación:
        ?page=N           — número de página (1-based, default=1).
        ?page_size=N      — evoluciones por página (default=10, máx=50).

    Bitácora (NOM-024):
        Registra PATIENT_BOOK_VIEW con resource_repr=patient.record_number (no-PII).
        Si audit_record falla → logger.critical pero el acceso continúa
        (mismo trade-off que el resto del expediente: disponibilidad > registro estricto).

    Anti-IDOR:
        patient_id se resuelve via patient_get (TenantManager) → 404 si es de otro tenant.

    Anti-N+1:
        book_build hace UN queryset con todos los prefetch necesarios para la
        página actual; no genera queries adicionales durante la serialización.
    """

    permission_classes = [IsAuthenticated, EvolutionPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Arma y devuelve el libro clínico del paciente (paginado)."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # --- Paginación: parsear parámetros de query ---
        try:
            page: int = int(request.query_params.get("page", 1))
        except (ValueError, TypeError):
            page = 1

        try:
            page_size: int = int(request.query_params.get("page_size", 10))
        except (ValueError, TypeError):
            page_size = 10

        # --- Bitácora NOM-024 (PATIENT_BOOK_VIEW) ---
        tenant = get_current_tenant()
        audit_result = audit_record(
            action=ActionType.PATIENT_BOOK_VIEW,
            resource_type="PatientBook",
            actor=request.user,
            tenant=tenant,
            resource_id=patient.id,
            # resource_repr = record_number (no-PII: es el número de expediente,
            # no el nombre del paciente — cumple NOM-024 §5.3).
            resource_repr=patient.record_number,
            metadata={
                "patient_id": str(patient.id),
                "page": page,
                "page_size": page_size,
            },
        )
        if audit_result is None:
            logger.critical(
                "ACCESO A EXPEDIENTE SIN REGISTRO EN BITÁCORA — "
                "acción PATIENT_BOOK_VIEW no pudo guardarse. "
                "tenant_id=%s patient_id=%s actor_id=%s. "
                "Revisar disponibilidad de BD de auditoría.",
                str(tenant.id) if tenant is not None else "None",
                str(patient.id),
                str(getattr(request.user, "pk", "anon")),
            )
            # El acceso continúa (disponibilidad clínica > registro estricto).

        # --- Armar el libro (selector: solo lecturas, anti-N+1) ---
        book = book_build(patient=patient, page=page, page_size=page_size)

        return Response(
            PatientBookSerializer(book, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# PDF del Libro Clínico del Paciente (Fase 3 — D-LIB-5, D-LIB-6)
# ---------------------------------------------------------------------------


class _PdfRenderer(BaseRenderer):
    """Renderer que permite a DRF negociar `application/pdf`.

    La vista devuelve un HttpResponse directo; DRF igual ejecuta la
    negociación de contenido al entrar. Sin este renderer, un cliente
    que mande `Accept: application/pdf` recibiría 406. Mismo patrón
    que apps/recetas/views.PdfRenderer.
    """

    media_type = "application/pdf"
    format = "pdf"
    charset = None

    def render(self, data: object, accepted_media_type: object = None, renderer_context: object = None) -> object:
        return data


class PatientBookPdfApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/libro/pdf/

    Genera el PDF del libro clínico del paciente con WeasyPrint y lo
    devuelve como descarga autenticada (Bearer, no URL pública — D-LIB-6).

    Parámetros de query:
        modo      — "completo" | "hc" | "ultimo" (default "completo").
                    completo: portada + HC + TODOS los capítulos.
                    hc:       portada + HC + alergias (para 1ª consulta).
                    ultimo:   portada + ÚLTIMO capítulo + sus recetas.
        imagenes  — "1" (default) | "0". Incluir/omitir imágenes (D-LIB-2).

    Permiso:
        Mismo que PatientBookApi y EvolutionNoteListCreateApi: solo roles clínicos
        (EvolutionPermission). Recepción y finanzas → 403 (D-LIB-6).

    Anti-IDOR:
        patient_id se resuelve vía patient_get (TenantManager) → 404 si es de
        otro tenant. NUNCA 403 para recursos ajenos.

    Bitácora (NOM-024 / D-LIB-4):
        Registra PATIENT_BOOK_PDF con resource_repr=patient.record_number (no-PII)
        y metadata={modo, imagenes}. Si audit_record falla → logger.critical pero
        el PDF se sigue generando (disponibilidad clínica > registro estricto).

    Descarga:
        Content-Disposition: attachment; filename="libro-<record_number>-<modo>.pdf"
        Cabeceras de seguridad: X-Frame-Options: DENY, X-Content-Type-Options: nosniff.

    Errores:
        404 — paciente no encontrado / de otro tenant.
        400 — parámetro modo inválido (fuera de {completo, hc, ultimo}).
        500 — WeasyPrint falló (RuntimeError); se registra en logger.error.
    """

    permission_classes = [IsAuthenticated, EvolutionPermission]
    renderer_classes = [_PdfRenderer]

    def get(self, request: Request, patient_id: uuid.UUID) -> HttpResponse:
        """Genera y devuelve el PDF del libro clínico."""
        from apps.expediente.pdf import VALID_BOOK_MODES, libro_pdf_build  # noqa: PLC0415

        # --- Resolver paciente (anti-IDOR) ---
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return HttpResponse(
                content=b"Paciente no encontrado.",
                status=404,
            )

        # --- Parsear parámetros de query ---
        modo: str = request.query_params.get("modo", "completo").lower().strip()
        if modo not in VALID_BOOK_MODES:
            return HttpResponse(
                content=f"Parámetro 'modo' inválido: '{modo}'. "
                f"Valores válidos: completo, hc, ultimo.".encode(),
                status=400,
            )

        imagenes_param: str = request.query_params.get("imagenes", "1").strip()
        incluir_imagenes: bool = imagenes_param not in ("0", "false", "no")

        tenant = get_current_tenant()

        # --- Bitácora NOM-024 (D-LIB-4) ---
        audit_result = audit_record(
            action=ActionType.PATIENT_BOOK_PDF,
            resource_type="PatientBook",
            actor=request.user,
            tenant=tenant,
            resource_id=patient.id,
            resource_repr=patient.record_number,
            metadata={
                "patient_id": str(patient.id),
                "modo": modo,
                "imagenes": int(incluir_imagenes),
            },
        )
        if audit_result is None:
            logger.critical(
                "ACCESO A EXPEDIENTE SIN REGISTRO EN BITÁCORA — "
                "acción PATIENT_BOOK_PDF no pudo guardarse. "
                "tenant_id=%s patient_id=%s actor_id=%s modo=%s. "
                "Revisar disponibilidad de BD de auditoría.",
                str(tenant.id) if tenant is not None else "None",
                str(patient.id),
                str(getattr(request.user, "pk", "anon")),
                modo,
            )

        # --- Armar el libro completo (sin paginación) ---
        book = book_build_all(patient=patient, modo=modo)

        # --- Generar PDF ---
        try:
            pdf_bytes = libro_pdf_build(
                patient=book.patient,
                clinic_settings=book.clinic_settings,
                medical_history=book.medical_history,
                allergies=book.allergies,
                capitulos=book.capitulos,
                capitulos_count=book.capitulos_count,
                modo=modo,
                incluir_imagenes=incluir_imagenes,
            )
        except RuntimeError as exc:
            logger.error(
                "PatientBookPdfApi: error al generar PDF — patient_id=%s modo=%s — %s",
                patient_id,
                modo,
                exc,
            )
            return HttpResponse(
                content=b"Error al generar el PDF del libro. Intente nuevamente.",
                status=500,
            )

        filename = f"libro-{patient.record_number}-{modo}.pdf"
        response = HttpResponse(content=pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        # Cabeceras de seguridad (mismo patrón que PrescriptionPdfApi).
        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"
        return response
