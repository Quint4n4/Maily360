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
from apps.core.permissions import MedicationPermission, PrescriptionFormatPermission, PrescriptionPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.recetas.selectors import (
    SEARCH_LIMIT,
    medication_search,
    prescription_format_get,
    prescription_format_list,
    prescription_get,
    prescription_list,
    prescription_pdf_job_get,
)
from apps.recetas.serializers import (
    MedicationCreateInputSerializer,
    MedicationCreateOutputSerializer,
    MedicationSearchOutputSerializer,
    PrescriptionCancelInputSerializer,
    PrescriptionCreateInputSerializer,
    PrescriptionDetailOutputSerializer,
    PrescriptionFormatCreateInputSerializer,
    PrescriptionFormatOutputSerializer,
    PrescriptionFormatUpdateInputSerializer,
    PrescriptionListOutputSerializer,
)
from apps.recetas.services import (
    medication_create,
    prescription_cancel,
    prescription_create,
    prescription_format_create,
    prescription_format_delete,
    prescription_format_update,
    prescription_pdf_job_enqueue,
)

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

        # COFEPRIS F2: filtro opcional por kind (medicamento|suero|terapia).
        kind_param: str | None = request.query_params.get("kind") or None

        results = medication_search(q=q, limit=limit, kind=kind_param)
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
                diagnosis=s.validated_data.get("diagnosis", ""),
                # F6: folio del recetario especial COFEPRIS (vacío si no es controlada)
                controlled_folio=s.validated_data.get("controlled_folio", ""),
                # Signos vitales capturados por el médico en la receta (opcional).
                # None si el cliente no los envía → el servicio usa la última toma.
                vitals=s.validated_data.get("vitals") or None,
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


class PrescriptionPdfRequestApi(TenantAPIView):
    """GET /api/v1/recetas/<prescription_id>/pdf/ — encola (o reusa) la generación del PDF.

    El PDF se genera en SEGUNDO PLANO (Celery) para no bloquear los workers de la
    API (riesgo P0). Devuelve {job_id, status}. El frontend hace polling de
    GET /recetas/pdf-job/<job_id>/ y descarga con .../file/ cuando status="done".

    Caché: si la receta (inmutable) ya tiene su PDF, status llega "done" de una vez.
    Permiso CLINICAL_READ (mismo que el detalle). Anti-IDOR por tenant. Bitácora
    PRESCRIPTION_PDF (sin PII, solo folio) al solicitar.
    """

    permission_classes = [IsAuthenticated, PrescriptionPermission]

    def get(self, request: Request, prescription_id: uuid.UUID) -> Response:
        """Encola (o reusa del caché) la generación del PDF de la receta."""
        from apps.recetas.models import Prescription
        from apps.recetas.pdf import VALID_LAYOUTS

        try:
            prescription = prescription_get(prescription_id=prescription_id)
        except Prescription.DoesNotExist:
            return Response(
                {"detail": "Receta no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tenant = get_current_tenant()
        audit_record(
            action=ActionType.PRESCRIPTION_PDF,
            resource_type="Prescription",
            actor=request.user,
            tenant=tenant,
            resource_id=prescription.id,
            resource_repr=f"folio={prescription.folio}",
            metadata={"folio": prescription.folio},
        )

        # Mismo contrato de parámetros que antes: ?formato= (layout) / ?format_id=.
        layout = (request.query_params.get("formato", "") or "").lower().strip()
        if layout and layout not in VALID_LAYOUTS:
            layout = ""
        format_id = (request.query_params.get("format_id", "") or "").strip()

        job = prescription_pdf_job_enqueue(
            prescription=prescription,
            user=request.user,
            layout=layout,
            format_id=format_id,
        )
        return Response(
            {"job_id": str(job.id), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )


class PrescriptionPdfJobStatusApi(TenantAPIView):
    """GET /api/v1/recetas/pdf-job/<job_id>/ — estado del trabajo de PDF.

    Devuelve {status} (pending/processing/done/failed). El frontend lo consulta
    cada ~2 s hasta done (o failed). Anti-IDOR por tenant.
    """

    permission_classes = [IsAuthenticated, PrescriptionPermission]

    def get(self, request: Request, job_id: uuid.UUID) -> Response:
        """Retorna el estado del trabajo de PDF."""
        from apps.recetas.models import PrescriptionPdfJob

        try:
            job = prescription_pdf_job_get(job_id=job_id)
        except PrescriptionPdfJob.DoesNotExist:
            return Response(
                {"detail": "Trabajo de PDF no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body: dict[str, object] = {"status": job.status}
        if job.status == PrescriptionPdfJob.Status.FAILED:
            body["detail"] = "No se pudo generar el PDF. Intenta de nuevo."
        return Response(body)


class PrescriptionPdfJobFileApi(TenantAPIView):
    """GET /api/v1/recetas/pdf-job/<job_id>/file/ — descarga el PDF generado.

    Sirve el PDF (autenticado con Bearer) solo cuando el trabajo está "done"; si
    aún no → 409. Mismos headers de seguridad que el endpoint síncrono anterior
    (X-Frame-Options DENY, X-Content-Type-Options nosniff, Content-Disposition inline).
    """

    permission_classes = [IsAuthenticated, PrescriptionPermission]
    renderer_classes = [PdfRenderer]

    def get(self, request: Request, job_id: uuid.UUID) -> HttpResponse:
        """Devuelve el PDF del trabajo si está listo."""
        from apps.recetas.models import PrescriptionPdfJob

        try:
            job = prescription_pdf_job_get(job_id=job_id)
        except PrescriptionPdfJob.DoesNotExist:
            return HttpResponse(content=b"Trabajo de PDF no encontrado.", status=404)

        if job.status != PrescriptionPdfJob.Status.DONE or not job.file:
            return HttpResponse(content=b"El PDF aun no esta listo.", status=409)

        pdf_bytes = job.file.read()
        filename = f"receta-{job.prescription.folio}.pdf"
        response = HttpResponse(content=pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
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


# ---------------------------------------------------------------------------
# F3 — PrescriptionFormat CRUD
# ---------------------------------------------------------------------------


class PrescriptionFormatListCreateApi(TenantAPIView):
    """GET  /api/v1/recetas/formatos/  — lista formatos del tenant.
    POST /api/v1/recetas/formatos/  — crea un formato nuevo.

    GET:
        Devuelve todos los PrescriptionFormat activos del tenant, ordenados
        por -is_default, name. Sin paginación (los formatos son pocos por tenant).

    POST:
        Crea un nuevo formato. El campo is_authorized solo lo puede establecer
        un owner/admin; cuando lo envía un médico, se ignora (siempre False).
        Si is_default=True, el servicio desmarca el anterior default del tenant.

    Permisos: PrescriptionFormatPermission (GET=ALL_ROLES, POST=owner/admin/doctor).
    Anti-IDOR: el TenantManager filtra por tenant activo.
    """

    permission_classes = [IsAuthenticated, PrescriptionFormatPermission]

    def get(self, request: Request) -> Response:
        """Lista los formatos activos del tenant."""
        qs = prescription_format_list(tenant=get_current_tenant())
        out = PrescriptionFormatOutputSerializer(qs, many=True)
        return Response(out.data, status=status.HTTP_200_OK)

    def post(self, request: Request) -> Response:
        """Crea un nuevo formato de receta."""
        s = PrescriptionFormatCreateInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        active_role: str = getattr(request, "active_role", "") or ""
        is_admin = active_role in ("owner", "admin")

        # Inyectar active_role para auditoría
        request.user.active_role = active_role  # type: ignore[union-attr]

        # is_authorized solo admin puede activarlo; médico siempre crea con False
        data = dict(s.validated_data)
        if not is_admin:
            data.pop("is_authorized", None)

        try:
            fmt = prescription_format_create(
                tenant=tenant,
                user=request.user,
                **data,
            )
        except Exception as exc:
            from django.core.exceptions import ValidationError as DjVE
            if isinstance(exc, DjVE):
                msg = exc.message if hasattr(exc, "message") else str(exc)
                return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
            raise

        return Response(
            PrescriptionFormatOutputSerializer(fmt).data,
            status=status.HTTP_201_CREATED,
        )


class PrescriptionFormatDetailApi(TenantAPIView):
    """GET   /api/v1/recetas/formatos/<format_id>/ — detalle.
    PATCH /api/v1/recetas/formatos/<format_id>/ — actualizar.
    DELETE /api/v1/recetas/formatos/<format_id>/ — baja lógica.

    GET:
        Devuelve el detalle del formato. Disponible para todos los roles.

    PATCH:
        Actualiza campos del formato. is_authorized solo lo cambia owner/admin.
        is_active y campos de identidad son inmutables.

    DELETE:
        Baja lógica (is_active=False + deleted_at). Solo owner/admin.
        Si era el default del tenant, queda sin default.

    Anti-IDOR: prescription_format_get usa TenantManager; formato de otro tenant → 404.
    """

    permission_classes = [IsAuthenticated, PrescriptionFormatPermission]

    def get(self, request: Request, format_id: uuid.UUID) -> Response:
        """Detalle del formato."""
        from apps.recetas.models import PrescriptionFormat

        try:
            fmt = prescription_format_get(format_id=format_id)
        except PrescriptionFormat.DoesNotExist:
            return Response(
                {"detail": "Formato no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            PrescriptionFormatOutputSerializer(fmt).data,
            status=status.HTTP_200_OK,
        )

    def patch(self, request: Request, format_id: uuid.UUID) -> Response:
        """Actualiza parcialmente un formato de receta."""
        from apps.recetas.models import PrescriptionFormat

        try:
            fmt = prescription_format_get(format_id=format_id)
        except PrescriptionFormat.DoesNotExist:
            return Response(
                {"detail": "Formato no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = PrescriptionFormatUpdateInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se enviaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant = get_current_tenant()
        active_role: str = getattr(request, "active_role", "") or ""
        is_admin = active_role in ("owner", "admin")
        request.user.active_role = active_role  # type: ignore[union-attr]

        try:
            updated = prescription_format_update(
                fmt=fmt,
                user=request.user,
                tenant=tenant,
                is_admin=is_admin,
                **s.validated_data,
            )
        except Exception as exc:
            from django.core.exceptions import ValidationError as DjVE
            if isinstance(exc, DjVE):
                msg = exc.message if hasattr(exc, "message") else str(exc)
                return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
            raise

        return Response(
            PrescriptionFormatOutputSerializer(updated).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request: Request, format_id: uuid.UUID) -> Response:
        """Baja lógica de un formato de receta."""
        from apps.recetas.models import PrescriptionFormat

        try:
            fmt = prescription_format_get(format_id=format_id)
        except PrescriptionFormat.DoesNotExist:
            return Response(
                {"detail": "Formato no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tenant = get_current_tenant()
        request.user.active_role = getattr(request, "active_role", "") or ""  # type: ignore[union-attr]

        try:
            prescription_format_delete(fmt=fmt, user=request.user, tenant=tenant)
        except Exception as exc:
            from django.core.exceptions import ValidationError as DjVE
            if isinstance(exc, DjVE):
                msg = exc.message if hasattr(exc, "message") else str(exc)
                return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
            raise

        return Response(status=status.HTTP_204_NO_CONTENT)
