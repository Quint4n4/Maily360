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

from apps.agenda.models import AgendaBlock, AgendaItemNote, Appointment, AppointmentType
from apps.agenda.selectors import (
    agenda_block_get,
    agenda_block_list,
    agenda_config_get,
    agenda_item_note_get,
    agenda_item_note_list,
    appointment_get,
    appointment_list,
    appointment_type_get,
    appointment_type_list,
)
from apps.agenda.serializers import (
    AgendaBlockOutputSerializer,
    AgendaItemNoteOutputSerializer,
    AppointmentOutputSerializer,
    AppointmentTypeOutputSerializer,
    TenantAgendaConfigOutputSerializer,
)
from apps.agenda.services import (
    agenda_block_create,
    agenda_block_delete,
    agenda_block_update,
    agenda_config_update,
    agenda_item_note_create,
    agenda_item_note_delete,
    appointment_change_status,
    appointment_create,
    appointment_reschedule,
    appointment_type_create,
    appointment_type_deactivate,
    appointment_type_update,
    appointment_update,
)
from apps.core.permissions import (
    AgendaConfigPermission,
    AgendaItemNotePermission,
    AppointmentPermission,
    AppointmentStatusPermission,
    AppointmentTypePermission,
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

    permission_classes = [IsAuthenticated, AppointmentPermission]

    class InputSerializer(serializers.Serializer):
        """Campos para crear una cita (POST).

        NOTA: `status` NO está aquí. El estado inicial siempre es SCHEDULED.
        Solo AppointmentChangeStatusApi cambia el estado.
        """

        patient_id = serializers.UUIDField()
        doctor_id = serializers.UUIDField()
        consultorio_id = serializers.UUIDField(required=False, allow_null=True, default=None)
        appointment_type_id = serializers.UUIDField(required=False, allow_null=True, default=None)
        starts_at = serializers.DateTimeField()
        ends_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
        reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
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

    permission_classes = [IsAuthenticated, AppointmentPermission]

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

    permission_classes = [IsAuthenticated, AppointmentStatusPermission]

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

    permission_classes = [IsAuthenticated, AppointmentPermission]

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

    permission_classes = [IsAuthenticated, AgendaConfigPermission]

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


# ---------------------------------------------------------------------------
# AppointmentType — catálogo configurable de tipos de cita
# ---------------------------------------------------------------------------


class AppointmentTypeListCreateApi(TenantAPIView):
    """GET  /api/v1/agenda/tipos-cita/   — lista de tipos de cita (sin paginar).
    POST /api/v1/agenda/tipos-cita/   — crea un tipo de cita.
    """

    permission_classes = [IsAuthenticated, AppointmentTypePermission]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=80)
        color_hex = serializers.RegexField(
            regex=r"^#[0-9A-Fa-f]{6}$",
            max_length=7,
            required=False,
            allow_blank=True,
            default="",
            error_messages={"invalid": "El color debe tener formato #RRGGBB (ej: #3B82F6)."},
        )

    def get(self, request: Request) -> Response:
        """Lista de tipos de cita del tenant (todos si only_active=false)."""
        only_active = request.query_params.get("only_active", "true").lower() != "false"
        qs = appointment_type_list(only_active=only_active)
        return Response(AppointmentTypeOutputSerializer(qs, many=True).data)

    def post(self, request: Request) -> Response:
        """Crea un tipo de cita en el tenant del request."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            appointment_type = appointment_type_create(
                tenant=tenant,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            AppointmentTypeOutputSerializer(appointment_type).data,
            status=status.HTTP_201_CREATED,
        )


class AppointmentTypeDetailApi(TenantAPIView):
    """PATCH  /api/v1/agenda/tipos-cita/<id>/  — actualización parcial.
    DELETE /api/v1/agenda/tipos-cita/<id>/  — desactivación (soft).
    """

    permission_classes = [IsAuthenticated, AppointmentTypePermission]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=80, required=False)
        color_hex = serializers.RegexField(
            regex=r"^#[0-9A-Fa-f]{6}$",
            max_length=7,
            required=False,
            allow_blank=True,
            error_messages={"invalid": "El color debe tener formato #RRGGBB (ej: #3B82F6)."},
        )

    def _get_or_404(self, type_id: uuid.UUID) -> "tuple[AppointmentType | None, Response | None]":
        try:
            return appointment_type_get(type_id=type_id), None
        except AppointmentType.DoesNotExist:
            return None, Response(
                {"detail": "Tipo de cita no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def patch(self, request: Request, type_id: uuid.UUID) -> Response:
        appointment_type, error = self._get_or_404(type_id)
        if error is not None:
            return error

        s = self.InputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = appointment_type_update(
            appointment_type=appointment_type,  # type: ignore[arg-type]
            user=request.user,
            **s.validated_data,
        )
        return Response(AppointmentTypeOutputSerializer(updated).data)

    def delete(self, request: Request, type_id: uuid.UUID) -> Response:
        appointment_type, error = self._get_or_404(type_id)
        if error is not None:
            return error
        appointment_type_deactivate(appointment_type=appointment_type, user=request.user)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# AgendaBlock — reuniones y bloqueos
# ---------------------------------------------------------------------------


class AgendaBlockListCreateApi(TenantAPIView):
    """GET  /api/v1/agenda/eventos/   — eventos (reuniones/bloqueos) en un rango.
    POST /api/v1/agenda/eventos/   — crea un evento de agenda.
    """

    permission_classes = [IsAuthenticated, AppointmentPermission]

    class InputSerializer(serializers.Serializer):
        kind = serializers.ChoiceField(choices=AgendaBlock.Kind.choices)
        title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
        doctor_id = serializers.UUIDField(required=False, allow_null=True, default=None)
        consultorio_id = serializers.UUIDField(required=False, allow_null=True, default=None)
        starts_at = serializers.DateTimeField()
        ends_at = serializers.DateTimeField()
        all_day = serializers.BooleanField(required=False, default=False)
        notes = serializers.CharField(required=False, allow_blank=True, default="")

    def get(self, request: Request) -> Response:
        """Lista de eventos del tenant que solapan el rango [date_from, date_to]."""

        class _FilterSerializer(serializers.Serializer):
            date_from = serializers.DateTimeField(required=False)
            date_to = serializers.DateTimeField(required=False)

        filter_s = _FilterSerializer(data=request.query_params)
        filter_s.is_valid(raise_exception=True)
        qs = agenda_block_list(**filter_s.validated_data)
        return Response(AgendaBlockOutputSerializer(qs, many=True).data)

    def post(self, request: Request) -> Response:
        """Crea un evento (reunión o bloqueo) en el tenant del request."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            block = agenda_block_create(
                tenant=tenant,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            AgendaBlockOutputSerializer(block).data,
            status=status.HTTP_201_CREATED,
        )


class AgendaBlockDetailApi(TenantAPIView):
    """PATCH  /api/v1/agenda/eventos/<id>/  — edita un evento (título, fecha/hora, notas).
    DELETE /api/v1/agenda/eventos/<id>/  — elimina un evento de agenda.
    """

    permission_classes = [IsAuthenticated, AppointmentPermission]

    class InputSerializer(serializers.Serializer):
        title = serializers.CharField(max_length=120, required=False, allow_blank=True)
        starts_at = serializers.DateTimeField(required=False)
        ends_at = serializers.DateTimeField(required=False)
        all_day = serializers.BooleanField(required=False)
        notes = serializers.CharField(required=False, allow_blank=True)

    def _get_or_404(self, block_id: uuid.UUID) -> "tuple[AgendaBlock | None, Response | None]":
        try:
            return agenda_block_get(block_id=block_id), None
        except AgendaBlock.DoesNotExist:
            return None, Response({"detail": "Evento no encontrado."}, status=status.HTTP_404_NOT_FOUND)

    def patch(self, request: Request, block_id: uuid.UUID) -> Response:
        block, error = self._get_or_404(block_id)
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
            updated = agenda_block_update(
                agenda_block=block,  # type: ignore[arg-type]
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AgendaBlockOutputSerializer(updated).data)

    def delete(self, request: Request, block_id: uuid.UUID) -> Response:
        block, error = self._get_or_404(block_id)
        if error is not None:
            return error

        agenda_block_delete(agenda_block=block, user=request.user)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# AgendaItemNote — hilo de notas colaborativas de citas y eventos
# ---------------------------------------------------------------------------


class AppointmentNotesApi(TenantAPIView):
    """GET  /api/v1/agenda/citas/<appointment_id>/notas/  — lista el hilo de notas.
    POST /api/v1/agenda/citas/<appointment_id>/notas/  — agrega una nota al hilo.

    Antes de listar/crear verifica que la cita exista en el tenant (404 si no).
    No se pagina: el hilo de una cita es corto (diseño D-B).
    """

    permission_classes = [IsAuthenticated, AgendaItemNotePermission]

    class InputSerializer(serializers.Serializer):
        body = serializers.CharField()

    def _get_appointment_or_404(
        self, appointment_id: uuid.UUID
    ) -> "tuple[Appointment | None, Response | None]":
        try:
            return appointment_get(appointment_id=appointment_id), None
        except Appointment.DoesNotExist:
            return None, Response(
                {"detail": "Cita no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, appointment_id: uuid.UUID) -> Response:
        """Lista todas las notas del hilo de una cita, ordenadas por created_at ASC."""
        appointment, error = self._get_appointment_or_404(appointment_id)
        if error is not None:
            return error

        notes = agenda_item_note_list(appointment_id=appointment_id)
        return Response(AgendaItemNoteOutputSerializer(notes, many=True).data)

    def post(self, request: Request, appointment_id: uuid.UUID) -> Response:
        """Agrega una nota al hilo de una cita."""
        appointment, error = self._get_appointment_or_404(appointment_id)
        if error is not None:
            return error

        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            note = agenda_item_note_create(
                tenant=tenant,
                user=request.user,
                body=s.validated_data["body"],
                appointment_id=appointment_id,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            AgendaItemNoteOutputSerializer(note).data,
            status=status.HTTP_201_CREATED,
        )


class AgendaBlockNotesApi(TenantAPIView):
    """GET  /api/v1/agenda/eventos/<block_id>/notas/  — lista el hilo de notas.
    POST /api/v1/agenda/eventos/<block_id>/notas/  — agrega una nota al hilo.

    Antes de listar/crear verifica que el evento exista en el tenant (404 si no).
    No se pagina: el hilo de un evento es corto (diseño D-B).
    """

    permission_classes = [IsAuthenticated, AgendaItemNotePermission]

    class InputSerializer(serializers.Serializer):
        body = serializers.CharField()

    def _get_block_or_404(
        self, block_id: uuid.UUID
    ) -> "tuple[AgendaBlock | None, Response | None]":
        try:
            return agenda_block_get(block_id=block_id), None
        except AgendaBlock.DoesNotExist:
            return None, Response(
                {"detail": "Evento no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, block_id: uuid.UUID) -> Response:
        """Lista todas las notas del hilo de un evento, ordenadas por created_at ASC."""
        block, error = self._get_block_or_404(block_id)
        if error is not None:
            return error

        notes = agenda_item_note_list(block_id=block_id)
        return Response(AgendaItemNoteOutputSerializer(notes, many=True).data)

    def post(self, request: Request, block_id: uuid.UUID) -> Response:
        """Agrega una nota al hilo de un evento de agenda."""
        block, error = self._get_block_or_404(block_id)
        if error is not None:
            return error

        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            note = agenda_item_note_create(
                tenant=tenant,
                user=request.user,
                body=s.validated_data["body"],
                block_id=block_id,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            AgendaItemNoteOutputSerializer(note).data,
            status=status.HTTP_201_CREATED,
        )


class AgendaItemNoteDetailApi(TenantAPIView):
    """DELETE /api/v1/agenda/notas/<note_id>/  — elimina (soft) una nota del hilo.

    404 si la nota no existe o es de otro tenant.
    El service valida quién puede borrar (author / owner / admin).
    """

    permission_classes = [IsAuthenticated, AgendaItemNotePermission]

    def delete(self, request: Request, note_id: uuid.UUID) -> Response:
        """Soft-delete de una nota del hilo de agenda."""
        try:
            note = agenda_item_note_get(note_id=note_id)
        except AgendaItemNote.DoesNotExist:
            return Response(
                {"detail": "Nota no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            agenda_item_note_delete(note=note, user=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)
