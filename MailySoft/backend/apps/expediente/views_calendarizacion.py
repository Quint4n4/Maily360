"""
Vistas de la Calendarización de tratamientos (esquema de protocolos por
sesiones) — Fases 1 y 4.

Vive en el expediente del paciente. Contrato FIJO con el frontend:

    GET    /api/v1/expediente/<patient_id>/calendarizaciones/
        TreatmentPlanListCreateApi.get  — lista paginada.
    POST   /api/v1/expediente/<patient_id>/calendarizaciones/
        TreatmentPlanListCreateApi.post — crea. 201 detalle.
    GET    /api/v1/expediente/calendarizaciones/<plan_id>/
        TreatmentPlanDetailApi.get      — 200 detalle.
    PUT    /api/v1/expediente/calendarizaciones/<plan_id>/
        TreatmentPlanDetailApi.put      — 200 detalle (reemplaza).
    DELETE /api/v1/expediente/calendarizaciones/<plan_id>/
        TreatmentPlanDetailApi.delete   — 204 (baja lógica).
    GET    /api/v1/expediente/calendarizaciones/<plan_id>/pdf/
        TreatmentPlanPdfApi.get         — 202 {job_id, status} (encola).
    POST   /api/v1/expediente/calendarizaciones/<plan_id>/cotizacion/
        TreatmentPlanQuoteApi.post      — genera cotización (Fase 2). 201 {quote_id, status, total}.
    POST   /api/v1/expediente/<patient_id>/calendarizaciones/desde-paquete/
        TreatmentPlanFromPackageApi.post — crea esquema desde un paquete (Fase 3). 201 detalle.
    POST   /api/v1/expediente/calendarizaciones/sesiones/<session_id>/agendar/
        TreatmentSessionScheduleApi.post   — agenda/reagenda. 200 sesión.
    DELETE /api/v1/expediente/calendarizaciones/sesiones/<session_id>/agendar/
        TreatmentSessionScheduleApi.delete — quita de agenda. 200 sesión.

Permisos: TreatmentPlanPermission (owner, admin, doctor) en TODOS los
endpoints — mismo criterio que ClinicalSummaryPermission (documento
clínico con precios, entregado al paciente para firma física).

Anti-IDOR: todos los IDs de la URL se resuelven por selector (TenantManager).
Recurso de otro tenant → 404 (nunca 403).
"""

import logging
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.clinica.sucursal_scope import resolve_active_sucursal, resolve_write_sucursal
from apps.core.permissions import TreatmentPlanPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.expediente.models import TreatmentPlan, TreatmentSession
from apps.expediente.selectors import (
    treatment_plan_get,
    treatment_plan_list,
    treatment_session_get,
)
from apps.expediente.serializers import (
    TreatmentPlanInputSerializer,
    TreatmentPlanListItemSerializer,
    TreatmentPlanOutputSerializer,
    TreatmentSessionOutputSerializer,
    TreatmentSessionScheduleInputSerializer,
)
from apps.expediente.services_calendarizacion import (
    quote_create_from_treatment_plan,
    treatment_plan_create,
    treatment_plan_create_from_package,
    treatment_plan_delete,
    treatment_plan_replace,
    treatment_session_schedule,
    treatment_session_unschedule,
)
from apps.finanzas.models import TreatmentPackage
from apps.finanzas.selectors import package_get
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.pdfs.services import pdf_job_enqueue
from apps.personal.models import Consultorio, Doctor

logger = logging.getLogger("apps.expediente.views_calendarizacion")

_PATIENT_NOT_FOUND = Response(
    {"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND
)
_PLAN_NOT_FOUND = Response(
    {"detail": "Esquema de tratamientos no encontrado."}, status=status.HTTP_404_NOT_FOUND
)
_SESSION_NOT_FOUND = Response(
    {"detail": "Sesión de tratamiento no encontrada."}, status=status.HTTP_404_NOT_FOUND
)
_DOCTOR_NOT_FOUND = Response(
    {"detail": "Médico no encontrado en esta clínica."}, status=status.HTTP_404_NOT_FOUND
)
_CONSULTORIO_NOT_FOUND = Response(
    {"detail": "Consultorio no encontrado en esta clínica."}, status=status.HTTP_404_NOT_FOUND
)
_PACKAGE_NOT_FOUND = Response(
    {"detail": "Paquete de tratamientos no encontrado."}, status=status.HTTP_404_NOT_FOUND
)
_NO_TENANT = Response(
    {"detail": "No se encontró un tenant activo para este request."},
    status=status.HTTP_403_FORBIDDEN,
)


def _resolve_doctor(doctor_id: uuid.UUID | None) -> tuple[Doctor | None, bool]:
    """Resuelve el médico opcional por id (filtrado por tenant activo).

    Returns:
        (doctor, found): found=False si se pidió un doctor_id que no existe
        en el tenant activo (la vista responde 404 en ese caso).
    """
    if doctor_id is None:
        return None, True
    doctor = Doctor.objects.filter(id=doctor_id).first()
    return doctor, doctor is not None


def _resolve_consultorio(consultorio_id: uuid.UUID | None) -> tuple[Consultorio | None, bool]:
    """Resuelve el consultorio opcional por id (filtrado por tenant activo).

    Returns:
        (consultorio, found): found=False si se pidió un consultorio_id que
        no existe en el tenant activo (la vista responde 404 en ese caso).
    """
    if consultorio_id is None:
        return None, True
    consultorio = Consultorio.objects.filter(id=consultorio_id).first()
    return consultorio, consultorio is not None


class TreatmentPlanListCreateApi(TenantAPIView):
    """GET  /api/v1/expediente/<patient_id>/calendarizaciones/ — lista paginada.
    POST /api/v1/expediente/<patient_id>/calendarizaciones/ — crea. 201 detalle.
    """

    permission_classes = [IsAuthenticated, TreatmentPlanPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Lista los esquemas de tratamientos del paciente (paginado)."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return _PATIENT_NOT_FOUND

        qs = treatment_plan_list(patient=patient)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            TreatmentPlanListItemSerializer(page, many=True).data
        )

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Crea un esquema de calendarización de tratamientos."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return _PATIENT_NOT_FOUND

        s = TreatmentPlanInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        doctor, found = _resolve_doctor(s.validated_data.get("doctor_id"))
        if not found:
            return _DOCTOR_NOT_FOUND
        consultorio, found = _resolve_consultorio(s.validated_data.get("consultorio_id"))
        if not found:
            return _CONSULTORIO_NOT_FOUND

        actor_role: str = getattr(request, "active_role", "") or ""

        try:
            plan = treatment_plan_create(
                patient=patient,
                actor=request.user,
                title=s.validated_data.get("title", ""),
                notes=s.validated_data.get("notes", ""),
                status=s.validated_data.get(
                    "status", TreatmentPlan._meta.get_field("status").default
                ),
                items=s.validated_data["items"],
                doctor=doctor,
                consultorio=consultorio,
                actor_role=actor_role,
            )
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(TreatmentPlanOutputSerializer(plan).data, status=status.HTTP_201_CREATED)


class TreatmentPlanFromPackageApi(TenantAPIView):
    """POST /api/v1/expediente/<patient_id>/calendarizaciones/desde-paquete/

    Crea un esquema de calendarización NUEVO a partir de un paquete de
    tratamientos del catálogo (Fase 3). Body: {package_id}. 201 detalle.
    """

    permission_classes = [IsAuthenticated, TreatmentPlanPermission]

    class InputSerializer(serializers.Serializer):
        package_id = serializers.UUIDField()

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Crea un esquema de calendarización nuevo copiando las líneas del paquete."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return _PATIENT_NOT_FOUND

        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            package = package_get(package_id=s.validated_data["package_id"])
        except TreatmentPackage.DoesNotExist:
            return _PACKAGE_NOT_FOUND

        actor_role: str = getattr(request, "active_role", "") or ""

        try:
            plan = treatment_plan_create_from_package(
                patient=patient,
                actor=request.user,
                package=package,
                actor_role=actor_role,
            )
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(TreatmentPlanOutputSerializer(plan).data, status=status.HTTP_201_CREATED)


class TreatmentPlanDetailApi(TenantAPIView):
    """GET    /api/v1/expediente/calendarizaciones/<plan_id>/ — detalle.
    PUT    /api/v1/expediente/calendarizaciones/<plan_id>/ — reemplaza.
    DELETE /api/v1/expediente/calendarizaciones/<plan_id>/ — baja lógica.
    """

    permission_classes = [IsAuthenticated, TreatmentPlanPermission]

    def get(self, request: Request, plan_id: uuid.UUID) -> Response:
        """Devuelve el detalle del esquema (items + sesiones anidadas)."""
        try:
            plan = treatment_plan_get(plan_id=plan_id)
        except TreatmentPlan.DoesNotExist:
            return _PLAN_NOT_FOUND

        return Response(TreatmentPlanOutputSerializer(plan).data, status=status.HTTP_200_OK)

    def put(self, request: Request, plan_id: uuid.UUID) -> Response:
        """Reemplaza el contenido del esquema (title/notes/status/doctor/items)."""
        try:
            plan = treatment_plan_get(plan_id=plan_id)
        except TreatmentPlan.DoesNotExist:
            return _PLAN_NOT_FOUND

        s = TreatmentPlanInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        doctor, found = _resolve_doctor(s.validated_data.get("doctor_id"))
        if not found:
            return _DOCTOR_NOT_FOUND
        consultorio, found = _resolve_consultorio(s.validated_data.get("consultorio_id"))
        if not found:
            return _CONSULTORIO_NOT_FOUND

        actor_role: str = getattr(request, "active_role", "") or ""

        try:
            plan = treatment_plan_replace(
                plan=plan,
                actor=request.user,
                title=s.validated_data.get("title", ""),
                notes=s.validated_data.get("notes", ""),
                status=s.validated_data.get(
                    "status", TreatmentPlan._meta.get_field("status").default
                ),
                items=s.validated_data["items"],
                doctor=doctor,
                consultorio=consultorio,
                actor_role=actor_role,
            )
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(TreatmentPlanOutputSerializer(plan).data, status=status.HTTP_200_OK)

    def delete(self, request: Request, plan_id: uuid.UUID) -> Response:
        """Da de baja lógica el esquema."""
        try:
            plan = treatment_plan_get(plan_id=plan_id)
        except TreatmentPlan.DoesNotExist:
            return _PLAN_NOT_FOUND

        actor_role: str = getattr(request, "active_role", "") or ""

        try:
            treatment_plan_delete(plan=plan, actor=request.user, actor_role=actor_role)
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


class TreatmentPlanPdfApi(TenantAPIView):
    """GET /api/v1/expediente/calendarizaciones/<plan_id>/pdf/ — encola el PDF.

    El PDF se genera en SEGUNDO PLANO (Celery, infra apps.pdfs). Devuelve
    202 {job_id, status}; el frontend hace polling de GET /pdfs/job/<job_id>/
    y descarga con .../file/.

    cache_key="" (siempre-fresco): el esquema puede cambiar (sesiones
    marcadas como aplicadas), así que cada pedido genera un PDF nuevo.
    """

    permission_classes = [IsAuthenticated, TreatmentPlanPermission]

    def get(self, request: Request, plan_id: uuid.UUID) -> Response:
        """Encola la generación del PDF del esquema de tratamientos."""
        try:
            plan = treatment_plan_get(plan_id=plan_id)
        except TreatmentPlan.DoesNotExist:
            return _PLAN_NOT_FOUND

        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        folio_short = str(plan.id).replace("-", "")[:8].upper()
        job = pdf_job_enqueue(
            tenant=tenant,
            kind="treatment_plan",
            params={"plan_id": str(plan.id)},
            user=request.user,
            cache_key="",
            filename=f"calendarizacion-{folio_short}.pdf",
        )
        return Response(
            {"job_id": str(job.id), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )


class TreatmentPlanQuoteApi(TenantAPIView):
    """POST /api/v1/expediente/calendarizaciones/<plan_id>/cotizacion/

    Genera una cotización (borrador) a partir del esquema de calendarización
    (Fase 2). 201 {quote_id, status, total}. Cada llamada genera una
    cotización NUEVA y reapunta `plan.quote` — ver
    `services_calendarizacion.quote_create_from_treatment_plan`.
    """

    permission_classes = [IsAuthenticated, TreatmentPlanPermission]

    def post(self, request: Request, plan_id: uuid.UUID) -> Response:
        """Genera la cotización y la liga al esquema."""
        try:
            plan = treatment_plan_get(plan_id=plan_id)
        except TreatmentPlan.DoesNotExist:
            return _PLAN_NOT_FOUND

        actor_role: str = getattr(request, "active_role", "") or ""

        # Multi-sede — Fase 3: la cotización se genera en la sede activa del
        # request (header X-Sucursal-Id), cayendo a la sede predeterminada
        # del tenant si no hay header. None si el tenant no tiene sucursales.
        active_sucursal = resolve_active_sucursal(request)
        sucursal = resolve_write_sucursal(
            tenant=plan.tenant,
            user=request.user,
            sucursal_id=None,
            active_sucursal_id=active_sucursal.id if active_sucursal is not None else None,
        )

        try:
            quote = quote_create_from_treatment_plan(
                plan=plan, user=request.user, actor_role=actor_role, sucursal=sucursal
            )
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "quote_id": str(quote.id),
                "status": quote.status,
                "total": str(quote.total),
            },
            status=status.HTTP_201_CREATED,
        )


class TreatmentSessionScheduleApi(TenantAPIView):
    """POST   /api/v1/expediente/calendarizaciones/sesiones/<session_id>/agendar/
        Agenda o reagenda la sesión como una cita real de agenda. 200 sesión.
    DELETE /api/v1/expediente/calendarizaciones/sesiones/<session_id>/agendar/
        Quita la sesión de la agenda (cancela su cita ligada). 200 sesión.

    Fase 4 — reutiliza apps.agenda.services por completo (anti-empalme,
    reglas de doctor/consultorio); ver services_calendarizacion.
    treatment_session_schedule para la decisión exacta de
    crear/reagendar/cancelar+crear.

    Multi-sede (cierre de A8, docs/design/sucursales-hallazgos-seguridad.md):
    POST valida la sede DESTINO (con `resolve_write_sucursal`, mismo helper
    que el resto de la app) antes de tocar la cita, y el service valida la
    sede ORIGEN de la cita ya agendada. DELETE valida la sede de la cita
    ligada antes de cancelarla. Un actor acotado a una sede no puede
    agendar/mover/cancelar citas de otra sede aunque conozca el `session_id`
    (el estado de cuenta del paciente es compartido entre sedes por diseño).
    """

    permission_classes = [IsAuthenticated, TreatmentPlanPermission]

    def post(self, request: Request, session_id: uuid.UUID) -> Response:
        """Agenda (o reagenda) la sesión como cita real de agenda."""
        try:
            session = treatment_session_get(session_id=session_id)
        except TreatmentSession.DoesNotExist:
            return _SESSION_NOT_FOUND

        s = TreatmentSessionScheduleInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        doctor, found = _resolve_doctor(data.get("doctor_id"))
        if not found:
            return _DOCTOR_NOT_FOUND
        consultorio, found = _resolve_consultorio(data.get("consultorio_id"))
        if not found:
            return _CONSULTORIO_NOT_FOUND

        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        # Multi-sede — cierre de A8 (docs/design/sucursales-hallazgos-
        # seguridad.md): la sede DESTINO se resuelve con la MISMA precedencia
        # que usa apps.agenda.services (consultorio elegido > sede activa del
        # header > sede predeterminada del tenant) y se valida contra las
        # sedes permitidas del actor ANTES de invocar el service. Esto cierra
        # el hueco de `appointment_reschedule` (que hoy no valida sede) SIN
        # reimplementar su lógica: reutiliza el mismo helper compartido que
        # ya usa `TreatmentPlanQuoteApi` más arriba en este archivo.
        active_sucursal = resolve_active_sucursal(request)
        try:
            resolve_write_sucursal(
                tenant=tenant,
                user=request.user,
                sucursal_id=None,
                consultorio_sucursal_id=(
                    consultorio.sucursal_id if consultorio is not None else None
                ),
                active_sucursal_id=active_sucursal.id if active_sucursal is not None else None,
            )
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        actor_role: str = getattr(request, "active_role", "") or ""

        try:
            session = treatment_session_schedule(
                session=session,
                actor=request.user,
                actor_role=actor_role,
                doctor_id=doctor.id if doctor is not None else None,
                consultorio_id=consultorio.id if consultorio is not None else None,
                starts_at=data["starts_at"],
                ends_at=data["ends_at"],
                scheduled_date=data["scheduled_date"],
                scheduled_time=data["scheduled_time"],
                duration_minutes=data["duration_minutes"],
                active_sucursal_id=active_sucursal.id if active_sucursal is not None else None,
            )
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(TreatmentSessionOutputSerializer(session).data, status=status.HTTP_200_OK)

    def delete(self, request: Request, session_id: uuid.UUID) -> Response:
        """Quita la sesión de la agenda: cancela su cita ligada (si tiene)."""
        try:
            session = treatment_session_get(session_id=session_id)
        except TreatmentSession.DoesNotExist:
            return _SESSION_NOT_FOUND

        actor_role: str = getattr(request, "active_role", "") or ""

        try:
            session = treatment_session_unschedule(
                session=session, actor=request.user, actor_role=actor_role
            )
        except DjangoValidationError as exc:
            detail = exc.messages if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(TreatmentSessionOutputSerializer(session).data, status=status.HTTP_200_OK)
