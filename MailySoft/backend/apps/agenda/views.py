"""
Vistas de la app agenda.

Vistas delgadas: parsean el request, llaman un selector o service, devuelven Response.
Cero lógica de negocio aquí.

Hereda de TenantAPIView para resolución de tenant + context RLS vía JWT.

Manejo de errores:
- Appointment.DoesNotExist     → 404 (no 403; no revelar existencia en otro tenant).
- ValidationError (django)     → 400 con exc.messages.
- TenantAgendaConfig.DoesNotExist → no puede ocurrir (agenda_config_get usa get_or_create).

REGLA CRÍTICA: `status` NUNCA se acepta en el InputSerializer del PATCH genérico.
Solo AppointmentChangeStatusApi lo acepta.
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.agenda.models import Appointment
from apps.agenda.selectors import agenda_config_get, appointment_get, appointment_list
from apps.agenda.serializers import (
    AppointmentOutputSerializer,
    TenantAgendaConfigOutputSerializer,
)
from apps.agenda.services import (
    agenda_config_update,
    appointment_change_status,
    appointment_create,
    appointment_reschedule,
    appointment_update,
)
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView


# ---------------------------------------------------------------------------
# AppointmentListCreateApi
# ---------------------------------------------------------------------------


class AppointmentListCreateApi(TenantAPIView):
    """GET  /api/v1/agenda/citas/    — lista paginada de citas con filtros.
    POST /api/v1/agenda/citas/    — crea una cita nueva.
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        """Campos para crear una cita (POST).

        NOTA: `status` NO está aquí. El estado inicial siempre es SCHEDULED.
        Solo AppointmentChangeStatusApi cambia el estado.
        """

        patient_id = serializers.UUIDField()
        doctor_id = serializers.UUIDField()
        consultorio_id = serializers.UUIDField(required=False, allow_null=True, default=None)
        starts_at = serializers.DateTimeField()
        ends_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
        reason = serializers.CharField(max_length=255)
        specialty = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
        notes = serializers.CharField(required=False, allow_blank=True, default="")

    def get(self, request: Request) -> Response:
        """Lista paginada de citas del tenant con filtros opcionales.

        Query params:
            doctor_id:      UUID del médico.
            patient_id:     UUID del paciente.
            consultorio_id: UUID del consultorio.
            status:         Estado de la cita (scheduled|confirmed|arrived|...).
            date_from:      ISO datetime UTC inicio de rango.
            date_to:        ISO datetime UTC fin de rango.
        """
        # Parsear filtros de query params
        class _FilterSerializer(serializers.Serializer):
            doctor_id = serializers.UUIDField(required=False)
            patient_id = serializers.UUIDField(required=False)
            consultorio_id = serializers.UUIDField(required=False)
            status = serializers.ChoiceField(
                choices=Appointment.Status.choices, required=False
            )
            date_from = serializers.DateTimeField(required=False)
            date_to = serializers.DateTimeField(required=False)

        filter_s = _FilterSerializer(data=request.query_params)
        filter_s.is_valid(raise_exception=True)

        qs = appointment_list(**filter_s.validated_data)

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                AppointmentOutputSerializer(page, many=True).data
            )

        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea una cita nueva en el tenant del request."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            appointment = appointment_create(
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
            AppointmentOutputSerializer(appointment).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# AppointmentDetailApi
# ---------------------------------------------------------------------------


class AppointmentDetailApi(TenantAPIView):
    """GET    /api/v1/agenda/citas/<appointment_id>/   — detalle de una cita.
    PATCH  /api/v1/agenda/citas/<appointment_id>/   — actualización parcial (sin status ni horario).
    DELETE /api/v1/agenda/citas/<appointment_id>/   — cancela la cita (no borra).
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        """Campos editables de una cita por PATCH.

        EXCLUIDO EXPLÍCITAMENTE:
        - `status`: solo via AppointmentChangeStatusApi.
        - `starts_at` / `ends_at`: solo via AppointmentRescheduleApi.
        - `patient_id`, `doctor_id`: FK de identidad inmutables en v1.
        - `consultorio_id`: solo via AppointmentRescheduleApi en v1.
        """

        reason = serializers.CharField(max_length=255, required=False)
        specialty = serializers.CharField(max_length=100, required=False, allow_blank=True)
        notes = serializers.CharField(required=False, allow_blank=True)

    def _get_appointment_or_404(
        self, appointment_id: uuid.UUID
    ) -> "tuple[Appointment | None, Response | None]":
        """Recupera la cita via selector o devuelve 404."""
        try:
            appointment = appointment_get(appointment_id=appointment_id)
            return appointment, None
        except Appointment.DoesNotExist:
            return None, Response(
                {"detail": "Cita no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, appointment_id: uuid.UUID) -> Response:
        """Retorna el detalle de una cita."""
        appointment, error = self._get_appointment_or_404(appointment_id)
        if error is not None:
            return error

        return Response(AppointmentOutputSerializer(appointment).data)

    def patch(self, request: Request, appointment_id: uuid.UUID) -> Response:
        """Actualización parcial de campos editables (reason, notes, specialty).

        NO acepta status (use /estado/), ni horario (use /reagendar/).
        """
        appointment, error = self._get_appointment_or_404(appointment_id)
        if error is not None:
            return error

        s = self.InputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            appointment = appointment_update(
                appointment=appointment,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(AppointmentOutputSerializer(appointment).data)

    def delete(self, request: Request, appointment_id: uuid.UUID) -> Response:
        """Cancela una cita. NO la borra — llama appointment_change_status(CANCELLED)."""
        appointment, error = self._get_appointment_or_404(appointment_id)
        if error is not None:
            return error

        reason: str = request.data.get("reason", "") if request.data else ""

        try:
            appointment_change_status(
                appointment=appointment,
                user=request.user,
                new_status=Appointment.Status.CANCELLED,
                reason=reason,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# AppointmentChangeStatusApi
# ---------------------------------------------------------------------------


class AppointmentChangeStatusApi(TenantAPIView):
    """POST /api/v1/agenda/citas/<appointment_id>/estado/

    ÚNICO endpoint para cambiar el estado de una cita.
    Valida la transición contra la máquina de estados.
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        status = serializers.ChoiceField(choices=Appointment.Status.choices)
        reason = serializers.CharField(required=False, allow_blank=True, default="")

    def post(self, request: Request, appointment_id: uuid.UUID) -> Response:
        """Cambia el estado de una cita validando la transición."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            appointment = appointment_get(appointment_id=appointment_id)
        except Appointment.DoesNotExist:
            return Response(
                {"detail": "Cita no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            updated = appointment_change_status(
                appointment=appointment,
                user=request.user,
                new_status=s.validated_data["status"],
                reason=s.validated_data.get("reason", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(AppointmentOutputSerializer(updated).data)


# ---------------------------------------------------------------------------
# AppointmentRescheduleApi
# ---------------------------------------------------------------------------


class AppointmentRescheduleApi(TenantAPIView):
    """POST /api/v1/agenda/citas/<appointment_id>/reagendar/

    Modifica el horario de una cita SCHEDULED o CONFIRMED.
    Revalida anti-empalme excluyendo la propia cita.
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        starts_at = serializers.DateTimeField()
        ends_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
        consultorio_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def post(self, request: Request, appointment_id: uuid.UUID) -> Response:
        """Reagenda una cita (nuevo horario y opcionalmente nuevo consultorio)."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            appointment = appointment_get(appointment_id=appointment_id)
        except Appointment.DoesNotExist:
            return Response(
                {"detail": "Cita no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            updated = appointment_reschedule(
                appointment=appointment,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(AppointmentOutputSerializer(updated).data)


# ---------------------------------------------------------------------------
# AgendaConfigApi
# ---------------------------------------------------------------------------


class AgendaConfigApi(TenantAPIView):
    """GET   /api/v1/agenda/config/   — ver configuración de agenda de la clínica.
    PATCH /api/v1/agenda/config/   — actualizar configuración.
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        """Campos editables de TenantAgendaConfig.

        EXCLUIDO: id, tenant, created_at, updated_at, deleted_at (inmutables).
        """

        record_number_format = serializers.CharField(max_length=50, required=False)
        record_number_reset_yearly = serializers.BooleanField(required=False)
        default_appointment_duration = serializers.IntegerField(
            min_value=1, max_value=480, required=False
        )
        reminder_offsets_minutes = serializers.ListField(
            child=serializers.IntegerField(min_value=1),
            required=False,
            allow_empty=True,
        )
        reminders_enabled = serializers.BooleanField(required=False)

    def get(self, request: Request) -> Response:
        """Retorna la configuración de agenda del tenant del request."""
        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        config = agenda_config_get(tenant=tenant)
        return Response(TenantAgendaConfigOutputSerializer(config).data)

    def patch(self, request: Request) -> Response:
        """Actualiza la configuración de agenda del tenant."""
        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        s = self.InputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            config = agenda_config_update(
                tenant=tenant,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(TenantAgendaConfigOutputSerializer(config).data)
