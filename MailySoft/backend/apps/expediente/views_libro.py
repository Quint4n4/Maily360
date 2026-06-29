"""
Vistas del Libro Clínico del paciente (JSON paginado + PDF WeasyPrint).

Extraído de expediente/views.py. Vistas delgadas: resuelven el paciente
(anti-IDOR), registran bitácora NOM-024 y delegan en book_build/book_build_all.
"""

import logging
import uuid

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.core.permissions import EvolutionPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.selectors import book_build
from apps.expediente.serializers import PatientBookSerializer
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.pdfs.services import pdf_job_enqueue

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


class PatientBookPdfApi(TenantAPIView):
    """GET /api/v1/expediente/<patient_id>/libro/pdf/ — encola el PDF del libro.

    El PDF se genera en SEGUNDO PLANO (Celery, infra apps.pdfs) para no bloquear
    los workers de la API (riesgo P0). Devuelve 202 {job_id, status}; el frontend
    hace polling de GET /pdfs/job/<job_id>/ y descarga con .../file/ al estar "done".

    El libro clínico es MUTABLE (los datos cambian con cada consulta), así que NO se
    cachea: cada pedido genera un PDF fresco (cache_key="").

    Parámetros de query:
        modo      — "completo" | "hc" | "ultimo" (default "completo").
        imagenes  — "1" (default) | "0". Incluir/omitir imágenes (D-LIB-2).

    Permiso EvolutionPermission (solo roles clínicos). Anti-IDOR por tenant (404).
    Bitácora PATIENT_BOOK_PDF al SOLICITAR (NOM-024 / D-LIB-4).
    """

    permission_classes = [IsAuthenticated, EvolutionPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Encola la generación del PDF del libro clínico."""
        from apps.expediente.pdf import VALID_BOOK_MODES  # noqa: PLC0415

        # --- Resolver paciente (anti-IDOR) ---
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # --- Parsear parámetros de query ---
        modo: str = request.query_params.get("modo", "completo").lower().strip()
        if modo not in VALID_BOOK_MODES:
            return Response(
                {
                    "detail": f"Parámetro 'modo' inválido: '{modo}'. "
                    "Valores válidos: completo, hc, ultimo."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        imagenes_param: str = request.query_params.get("imagenes", "1").strip()
        incluir_imagenes: bool = imagenes_param not in ("0", "false", "no")

        tenant = get_current_tenant()

        # --- Bitácora NOM-024 (D-LIB-4) — al SOLICITAR el PDF ---
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

        # --- Encolar la generación (libro mutable → sin caché) ---
        job = pdf_job_enqueue(
            tenant=tenant,
            kind="book",
            params={
                "patient_id": str(patient.id),
                "modo": modo,
                "incluir_imagenes": incluir_imagenes,
            },
            user=request.user,
            cache_key="",
            filename=f"libro-{patient.record_number}-{modo}.pdf",
        )
        return Response(
            {"job_id": str(job.id), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )
