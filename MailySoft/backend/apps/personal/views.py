"""
Vistas de la app personal.

Vistas delgadas: parsean el request, llaman un selector o service, devuelven Response.
Cero lógica de negocio aquí.

Hereda de TenantAPIView en lugar de APIView. Esto garantiza que el tenant se resuelva
DESPUÉS de que DRF autentica el JWT y request.user esté poblado. Ver apps/core/views.py.

Manejo de errores:
- <Modelo>.DoesNotExist → 404 (no 403; no se revela si el recurso existe en otro tenant).
- ValidationError (django.core.exceptions) → 400 con exc.messages.
"""

import datetime
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant
from apps.personal.models import Consultorio, Doctor, DoctorSchedule, Weekday
from apps.personal.selectors import (
    consultorio_get,
    consultorio_list,
    doctor_get,
    doctor_list,
    schedule_get,
    schedule_list_for_doctor,
)
from apps.personal.serializers import (
    ConsultorioOutputSerializer,
    DoctorOutputSerializer,
    DoctorScheduleOutputSerializer,
)
from apps.personal.services import (
    consultorio_create,
    consultorio_deactivate,
    consultorio_update,
    doctor_create,
    doctor_deactivate,
    doctor_update,
    schedule_create,
    schedule_deactivate,
)
from apps.core.views import TenantAPIView
from apps.tenancy.models import TenantMembership


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


class DoctorListCreateApi(TenantAPIView):
    """GET  /api/v1/personal/doctores/       — lista paginada de doctores activos.
    POST /api/v1/personal/doctores/       — crea un nuevo perfil de médico.
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        membership_id = serializers.UUIDField(
            help_text="UUID de la TenantMembership con role='doctor'.",
        )
        cedula_profesional = serializers.CharField(
            max_length=30,
            default="",
            allow_blank=True,
        )
        specialty = serializers.CharField(
            max_length=100,
            default="",
            allow_blank=True,
        )
        default_appointment_duration = serializers.IntegerField(
            min_value=5,
            max_value=480,
            default=30,
        )
        bio_short = serializers.CharField(
            max_length=255,
            default="",
            allow_blank=True,
        )

    def get(self, request: Request) -> Response:
        """Lista paginada de doctores activos del tenant actual."""
        search: str = request.query_params.get("search", "")
        only_active_param: str = request.query_params.get("only_active", "true")
        only_active: bool = only_active_param.lower() != "false"

        qs = doctor_list(search=search, only_active=only_active)

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = DoctorOutputSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea un perfil de médico en el tenant del request."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            membership = TenantMembership.objects.get(
                id=s.validated_data["membership_id"],
                tenant=tenant,
            )
        except TenantMembership.DoesNotExist:
            return Response(
                {"detail": "Membresía no encontrada en este tenant."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            doctor = doctor_create(
                tenant=tenant,
                user=request.user,
                membership=membership,
                cedula_profesional=s.validated_data.get("cedula_profesional", ""),
                specialty=s.validated_data.get("specialty", ""),
                default_appointment_duration=s.validated_data.get(
                    "default_appointment_duration", 30
                ),
                bio_short=s.validated_data.get("bio_short", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            DoctorOutputSerializer(doctor).data,
            status=status.HTTP_201_CREATED,
        )


class DoctorDetailApi(TenantAPIView):
    """GET    /api/v1/personal/doctores/<uuid:doctor_id>/  — detalle de un médico.
    PATCH  /api/v1/personal/doctores/<uuid:doctor_id>/  — actualización parcial.
    DELETE /api/v1/personal/doctores/<uuid:doctor_id>/  — desactivación (soft).
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        cedula_profesional = serializers.CharField(
            max_length=30,
            required=False,
            allow_blank=True,
        )
        specialty = serializers.CharField(
            max_length=100,
            required=False,
            allow_blank=True,
        )
        default_appointment_duration = serializers.IntegerField(
            min_value=5,
            max_value=480,
            required=False,
        )
        bio_short = serializers.CharField(
            max_length=255,
            required=False,
            allow_blank=True,
        )
        # FIX-F1: is_active se eliminó de este serializer.
        # La (des)activación solo ocurre vía DELETE → doctor_deactivate.
        # Cualquier intento de cambiar is_active vía PATCH es rechazado
        # por _DOCTOR_IMMUTABLE_FIELDS en doctor_update (services.py).

    def _get_doctor_or_404(
        self, doctor_id: uuid.UUID
    ) -> "tuple[Doctor | None, Response | None]":
        try:
            doctor = doctor_get(doctor_id=doctor_id)
            return doctor, None
        except Doctor.DoesNotExist:
            return None, Response(
                {"detail": "Médico no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, doctor_id: uuid.UUID) -> Response:
        doctor, error_response = self._get_doctor_or_404(doctor_id)
        if error_response is not None:
            return error_response
        return Response(DoctorOutputSerializer(doctor).data)

    def patch(self, request: Request, doctor_id: uuid.UUID) -> Response:
        doctor, error_response = self._get_doctor_or_404(doctor_id)
        if error_response is not None:
            return error_response

        s = self.InputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated_doctor = doctor_update(
                doctor=doctor,  # type: ignore[arg-type]
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(DoctorOutputSerializer(updated_doctor).data)

    def delete(self, request: Request, doctor_id: uuid.UUID) -> Response:
        doctor, error_response = self._get_doctor_or_404(doctor_id)
        if error_response is not None:
            return error_response

        doctor_deactivate(doctor=doctor, user=request.user)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Consultorio
# ---------------------------------------------------------------------------


class ConsultorioListCreateApi(TenantAPIView):
    """GET  /api/v1/personal/consultorios/  — lista paginada de consultorios activos.
    POST /api/v1/personal/consultorios/  — crea un consultorio nuevo.
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=100)
        location = serializers.CharField(
            max_length=200,
            default="",
            allow_blank=True,
        )
        # FIX-F5: RegexField en lugar de CharField para validar formato #RRGGBB.
        color_hex = serializers.RegexField(
            regex=r"^#[0-9A-Fa-f]{6}$",
            max_length=7,
            default="",
            allow_blank=True,
            error_messages={"invalid": "El color debe tener formato #RRGGBB (ej: #3B82F6)."},
        )

    def get(self, request: Request) -> Response:
        """Lista paginada de consultorios del tenant actual."""
        only_active_param: str = request.query_params.get("only_active", "true")
        only_active: bool = only_active_param.lower() != "false"

        qs = consultorio_list(only_active=only_active)

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = ConsultorioOutputSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea un consultorio en el tenant del request."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            consultorio = consultorio_create(
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
            ConsultorioOutputSerializer(consultorio).data,
            status=status.HTTP_201_CREATED,
        )


class ConsultorioDetailApi(TenantAPIView):
    """GET    /api/v1/personal/consultorios/<uuid:consultorio_id>/  — detalle.
    PATCH  /api/v1/personal/consultorios/<uuid:consultorio_id>/  — actualización parcial.
    DELETE /api/v1/personal/consultorios/<uuid:consultorio_id>/  — desactivación (soft).
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=100, required=False)
        location = serializers.CharField(
            max_length=200,
            required=False,
            allow_blank=True,
        )
        # FIX-F5: RegexField para validar formato #RRGGBB en PATCH.
        color_hex = serializers.RegexField(
            regex=r"^#[0-9A-Fa-f]{6}$",
            max_length=7,
            required=False,
            allow_blank=True,
            error_messages={"invalid": "El color debe tener formato #RRGGBB (ej: #3B82F6)."},
        )

    def _get_consultorio_or_404(
        self, consultorio_id: uuid.UUID
    ) -> "tuple[Consultorio | None, Response | None]":
        try:
            consultorio = consultorio_get(consultorio_id=consultorio_id)
            return consultorio, None
        except Consultorio.DoesNotExist:
            return None, Response(
                {"detail": "Consultorio no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, consultorio_id: uuid.UUID) -> Response:
        consultorio, error_response = self._get_consultorio_or_404(consultorio_id)
        if error_response is not None:
            return error_response
        return Response(ConsultorioOutputSerializer(consultorio).data)

    def patch(self, request: Request, consultorio_id: uuid.UUID) -> Response:
        consultorio, error_response = self._get_consultorio_or_404(consultorio_id)
        if error_response is not None:
            return error_response

        s = self.InputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated_consultorio = consultorio_update(
                consultorio=consultorio,  # type: ignore[arg-type]
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(ConsultorioOutputSerializer(updated_consultorio).data)

    def delete(self, request: Request, consultorio_id: uuid.UUID) -> Response:
        consultorio, error_response = self._get_consultorio_or_404(consultorio_id)
        if error_response is not None:
            return error_response

        consultorio_deactivate(
            consultorio=consultorio,  # type: ignore[arg-type]
            user=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# DoctorSchedule
# ---------------------------------------------------------------------------


class DoctorScheduleListCreateApi(TenantAPIView):
    """GET  /api/v1/personal/doctores/<uuid:doctor_id>/horarios/  — horarios de un médico.
    POST /api/v1/personal/doctores/<uuid:doctor_id>/horarios/  — crea un horario.
    """

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        day_of_week = serializers.ChoiceField(choices=Weekday.choices)
        start_time = serializers.TimeField()
        end_time = serializers.TimeField()
        consultorio_id = serializers.UUIDField(
            required=False,
            allow_null=True,
            default=None,
        )
        valid_from = serializers.DateField(required=False, allow_null=True, default=None)
        valid_until = serializers.DateField(required=False, allow_null=True, default=None)

    def _get_doctor_or_404(
        self, doctor_id: uuid.UUID
    ) -> "tuple[Doctor | None, Response | None]":
        try:
            doctor = doctor_get(doctor_id=doctor_id)
            return doctor, None
        except Doctor.DoesNotExist:
            return None, Response(
                {"detail": "Médico no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, doctor_id: uuid.UUID) -> Response:
        """Lista los horarios activos del médico indicado."""
        doctor, error_response = self._get_doctor_or_404(doctor_id)
        if error_response is not None:
            return error_response

        qs = schedule_list_for_doctor(doctor=doctor)  # type: ignore[arg-type]

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = DoctorScheduleOutputSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request, doctor_id: uuid.UUID) -> Response:
        """Crea un bloque de horario para el médico indicado."""
        doctor, error_response = self._get_doctor_or_404(doctor_id)
        if error_response is not None:
            return error_response

        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Resolver el consultorio si se proveyó un ID.
        consultorio: "Consultorio | None" = None
        consultorio_id: "uuid.UUID | None" = s.validated_data.get("consultorio_id")
        if consultorio_id is not None:
            try:
                consultorio = consultorio_get(consultorio_id=consultorio_id)
            except Consultorio.DoesNotExist:
                return Response(
                    {"detail": "Consultorio no encontrado en este tenant."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        try:
            schedule = schedule_create(
                tenant=tenant,
                user=request.user,
                doctor=doctor,  # type: ignore[arg-type]
                day_of_week=s.validated_data["day_of_week"],
                start_time=s.validated_data["start_time"],
                end_time=s.validated_data["end_time"],
                consultorio=consultorio,
                valid_from=s.validated_data.get("valid_from"),
                valid_until=s.validated_data.get("valid_until"),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            DoctorScheduleOutputSerializer(schedule).data,
            status=status.HTTP_201_CREATED,
        )


class DoctorScheduleDetailApi(TenantAPIView):
    """DELETE /api/v1/personal/horarios/<uuid:schedule_id>/  — desactiva un horario (soft).
    """

    permission_classes = [IsAuthenticated]

    def _get_schedule_or_404(
        self, schedule_id: uuid.UUID
    ) -> "tuple[DoctorSchedule | None, Response | None]":
        # FIX-F2: schedule_get usa TenantManager (.objects) para filtrar por tenant
        # activo; previene IDOR — un schedule de otro tenant devuelve 404, no 403.
        try:
            schedule = schedule_get(schedule_id=schedule_id)
            return schedule, None
        except DoctorSchedule.DoesNotExist:
            return None, Response(
                {"detail": "Horario no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def delete(self, request: Request, schedule_id: uuid.UUID) -> Response:
        """Desactiva (soft) un bloque de horario."""
        schedule, error_response = self._get_schedule_or_404(schedule_id)
        if error_response is not None:
            return error_response

        schedule_deactivate(
            schedule=schedule,  # type: ignore[arg-type]
            user=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
