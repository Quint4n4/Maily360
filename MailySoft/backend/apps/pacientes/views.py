"""
Vistas de la app pacientes.

Vistas delgadas: parsean el request, llaman un selector o service, devuelven Response.
Cero lógica de negocio aquí.

Hereda de TenantAPIView (FIX-A2) en lugar de APIView. Esto garantiza que el tenant
se resuelva DESPUÉS de que DRF autentica el JWT y request.user esté poblado.
El tenant se obtiene con get_current_tenant() (lo pone TenantAPIView.initial()).

Manejo de errores:
- Patient.DoesNotExist → 404 (no 403; no se debe revelar si el recurso existe en otro tenant).
- ValidationError (django.core.exceptions) → 400.
"""

import re
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.models import ActionType
from apps.audit.services import audit_record
from apps.core.files import validate_avatar
from apps.core.permissions import PatientPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.pacientes.models import BloodType, Education, MaritalStatus, Patient, Sex
from apps.pacientes.selectors import patient_get, patient_list
from apps.pacientes.serializers import PatientOutputSerializer
from apps.pacientes.services import (
    patient_clear_avatar,
    patient_create,
    patient_create_quick,
    patient_deactivate,
    patient_set_avatar,
    patient_set_classification,
    patient_update,
)

# ---------------------------------------------------------------------------
# Validadores reutilizables
# ---------------------------------------------------------------------------

# FIX-B7: regex RENAPO para CURP (case-insensitive; se normaliza a mayúsculas antes de guardar).
_CURP_RE = re.compile(r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z\d]\d$", re.IGNORECASE)

# FIX-B8: regex razonable para teléfono (internacional o local, 7-20 caracteres útiles).
_PHONE_RE = re.compile(r"^\+?[\d\s\-\(\)]{7,20}$")


def _validate_curp(value: str) -> str:
    """Valida y normaliza una CURP al formato RENAPO.

    Permite vacío. Si se provee, debe coincidir con el patrón oficial.

    Args:
        value: cadena a validar.

    Returns:
        CURP en mayúsculas si es válida, o cadena vacía.

    Raises:
        serializers.ValidationError: si la CURP no cumple el formato RENAPO.
    """
    if not value:
        return ""
    normalized = value.upper()
    if not _CURP_RE.match(normalized):
        raise serializers.ValidationError(
            "CURP inválida. Debe tener el formato RENAPO: "
            "4 letras + 6 dígitos (fecha) + H/M + 5 letras + 1 letra/dígito + 1 dígito."
        )
    return normalized


def _validate_phone(value: str) -> str:
    """Valida que el teléfono tenga un formato razonable.

    Args:
        value: cadena a validar.

    Returns:
        El valor sin modificar si pasa la validación.

    Raises:
        serializers.ValidationError: si el teléfono no cumple el formato esperado.
    """
    if not _PHONE_RE.match(value):
        raise serializers.ValidationError(
            "Teléfono inválido. Use formato nacional (5512345678) "
            "o internacional (+52 55 1234 5678), 7-20 caracteres."
        )
    return value


_VALID_SEGMENTS = frozenset(
    {"all", "recent", "week", "month", "date", "potential", "favorites", "vip"}
)


class PatientListCreateApi(TenantAPIView):
    """GET /api/v1/pacientes/ — lista paginada de pacientes activos.
    POST /api/v1/pacientes/ — crea un paciente nuevo.
    """

    permission_classes = [IsAuthenticated, PatientPermission]

    class FilterSerializer(serializers.Serializer):
        """Parámetros de query para GET /pacientes/."""

        search = serializers.CharField(default="", allow_blank=True, required=False)
        segment = serializers.ChoiceField(
            choices=[
                ("all", "Todos"),
                ("recent", "Recientes"),
                ("week", "Esta semana"),
                ("month", "Este mes"),
                ("date", "Rango de fechas"),
                ("potential", "Potenciales"),
                ("favorites", "Favoritos"),
                ("vip", "VIP"),
            ],
            default="all",
            required=False,
        )
        date_from = serializers.DateField(required=False, allow_null=True)
        date_to = serializers.DateField(required=False, allow_null=True)
        # Filtro por etiqueta del catálogo (chip dinámico en el panel).
        category = serializers.UUIDField(required=False, allow_null=True)

        def validate(self, attrs: dict) -> dict:  # type: ignore[override]
            if attrs.get("segment") == "date":
                if not attrs.get("date_from") or not attrs.get("date_to"):
                    raise serializers.ValidationError(
                        "Los parámetros date_from y date_to son obligatorios "
                        "cuando segment='date'."
                    )
            return attrs

    class InputSerializer(serializers.Serializer):
        first_name = serializers.CharField(max_length=120)
        paternal_surname = serializers.CharField(max_length=120)
        maternal_surname = serializers.CharField(max_length=120, default="", allow_blank=True)
        date_of_birth = serializers.DateField()
        sex = serializers.ChoiceField(choices=Sex.choices)
        # FIX-B8: validación de teléfono
        phone = serializers.CharField(max_length=20)
        # FIX-B7: validación de CURP con regex RENAPO
        curp = serializers.CharField(max_length=18, default="", allow_blank=True)
        email = serializers.EmailField(default="", allow_blank=True)
        notes = serializers.CharField(default="", allow_blank=True, max_length=5000)

        def validate_curp(self, value: str) -> str:
            return _validate_curp(value)

        def validate_phone(self, value: str) -> str:
            return _validate_phone(value)

    def get(self, request: Request) -> Response:
        """Lista paginada de pacientes activos del tenant actual, con filtros y segmentos."""
        f = self.FilterSerializer(data=request.query_params)
        f.is_valid(raise_exception=True)
        fd = f.validated_data

        qs = patient_list(
            search=fd.get("search", ""),
            segment=fd.get("segment", "all"),
            date_from=fd.get("date_from"),
            date_to=fd.get("date_to"),
            category_id=fd.get("category"),
        )

        # FIX-B6: el paginator siempre pagina; si qs está vacío devuelve página vacía,
        # nunca serializa todos los registros sin paginar.
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = PatientOutputSerializer(page, many=True, context={"request": request})
            return paginator.get_paginated_response(serializer.data)

        # Fallback: si paginate_queryset devuelve None (no debería ocurrir con
        # PAGE_SIZE configurado en settings) devolvemos un error explícito en
        # lugar de serializar registros sin límite.
        return Response(
            {"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea un nuevo paciente en el tenant del request."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            patient = patient_create(
                tenant=tenant,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            # FIX-B4: usar exc.messages (siempre lista), no exc.message.
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            PatientOutputSerializer(patient, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class PatientQuickCreateApi(TenantAPIView):
    """POST /api/v1/pacientes/rapido/ — alta PROVISIONAL con datos mínimos.

    Pensado para agendar al vuelo desde la agenda cuando el paciente aún no existe.
    Crea el expediente con solo el nombre (teléfono opcional) y lo marca como
    provisional para que la UI alerte que faltan los datos personales.
    """

    permission_classes = [IsAuthenticated, PatientPermission]

    class InputSerializer(serializers.Serializer):
        first_name = serializers.CharField(max_length=120)
        paternal_surname = serializers.CharField(max_length=120)
        maternal_surname = serializers.CharField(max_length=120, default="", allow_blank=True)
        phone = serializers.CharField(max_length=20, required=False, default="", allow_blank=True)

        def validate_phone(self, value: str) -> str:
            # Teléfono opcional en provisional; si se provee, valida formato.
            if not value:
                return ""
            return _validate_phone(value)

    def post(self, request: Request) -> Response:
        """Crea un expediente provisional en el tenant del request."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            patient = patient_create_quick(
                tenant=tenant,
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            PatientOutputSerializer(patient, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class PatientDetailApi(TenantAPIView):
    """GET    /api/v1/pacientes/<uuid>/  — detalle de un paciente.
    PATCH  /api/v1/pacientes/<uuid>/  — actualización parcial.
    DELETE /api/v1/pacientes/<uuid>/  — desactivación (soft).
    """

    permission_classes = [IsAuthenticated, PatientPermission]

    class InputSerializer(serializers.Serializer):
        """Valida los datos de entrada del PATCH de Patient.

        ALTO-2 (D-EC-7): rechaza campos no declarados y valida la coherencia
        is_deceased/deceased_at (misma lógica que PatientNom004InputSerializer,
        ahora consolidada aquí como fuente única de verdad — MEDIO-4).

        MEDIO-2: phone_secondary valida el mismo formato que phone (si se provee).

        FIX-B3: is_active ELIMINADO — la activación/desactivación solo ocurre
        vía DELETE (patient_deactivate). Los campos inmutables tampoco se exponen.
        """

        first_name = serializers.CharField(max_length=120, required=False)
        paternal_surname = serializers.CharField(max_length=120, required=False)
        maternal_surname = serializers.CharField(max_length=120, required=False, allow_blank=True)
        date_of_birth = serializers.DateField(required=False)
        sex = serializers.ChoiceField(choices=Sex.choices, required=False)
        # FIX-B8: validación de teléfono
        phone = serializers.CharField(max_length=20, required=False)
        # FIX-B7: validación de CURP con regex RENAPO
        curp = serializers.CharField(max_length=18, required=False, allow_blank=True)
        email = serializers.EmailField(required=False, allow_blank=True)
        notes = serializers.CharField(required=False, allow_blank=True, max_length=5000)
        # Campos NOM-004 expediente A1 (plan §3.1) — todos opcionales en PATCH.
        address_street = serializers.CharField(max_length=255, required=False, allow_blank=True)
        address_neighborhood = serializers.CharField(
            max_length=120, required=False, allow_blank=True
        )
        city = serializers.CharField(max_length=120, required=False, allow_blank=True)
        state = serializers.CharField(max_length=120, required=False, allow_blank=True)
        postal_code = serializers.RegexField(
            regex=r"^\d{5}$",
            required=False,
            allow_blank=True,
            error_messages={
                "invalid": "El código postal debe ser exactamente 5 dígitos numéricos."
            },
        )
        birthplace = serializers.CharField(max_length=160, required=False, allow_blank=True)
        marital_status = serializers.ChoiceField(
            choices=[("", "Sin especificar")] + list(MaritalStatus.choices),
            required=False,
            allow_blank=True,
        )
        education = serializers.ChoiceField(
            choices=[("", "Sin especificar")] + list(Education.choices),
            required=False,
            allow_blank=True,
        )
        occupation = serializers.CharField(max_length=120, required=False, allow_blank=True)
        religion = serializers.CharField(max_length=80, required=False, allow_blank=True)
        blood_type = serializers.ChoiceField(
            choices=[("", "Sin especificar")] + list(BloodType.choices),
            required=False,
            allow_blank=True,
        )
        # MEDIO-2: phone_secondary con validación de formato (misma regex que phone).
        phone_secondary = serializers.CharField(max_length=20, required=False, allow_blank=True)
        phone_label = serializers.CharField(max_length=40, required=False, allow_blank=True)
        is_deceased = serializers.BooleanField(required=False)
        deceased_at = serializers.DateField(required=False, allow_null=True)
        custom_consultation_fee = serializers.DecimalField(
            max_digits=10, decimal_places=2, required=False, allow_null=True
        )
        category = serializers.CharField(max_length=60, required=False, allow_blank=True)
        # Etiquetas del catálogo asignadas al paciente (reemplaza el set completo).
        category_ids = serializers.ListField(
            child=serializers.UUIDField(), required=False, allow_empty=True
        )

        def validate_curp(self, value: str) -> str:
            return _validate_curp(value)

        def validate_phone(self, value: str) -> str:
            return _validate_phone(value)

        def validate_phone_secondary(self, value: str) -> str:
            """MEDIO-2: valida el formato del teléfono secundario. Permite vacío."""
            if not value:
                return value
            return _validate_phone(value)

        def validate(self, attrs: dict) -> dict:  # type: ignore[override]
            """ALTO-2 (D-EC-7): rechaza campos desconocidos y valida is_deceased/deceased_at."""
            # Rechazar campos no declarados (whitelist).
            declared = set(self.fields.keys())
            received = set(self.initial_data.keys())  # type: ignore[union-attr]
            unknown = received - declared
            if unknown:
                raise serializers.ValidationError(
                    {field: ["Campo no permitido."] for field in sorted(unknown)}
                )

            # Coherencia is_deceased / deceased_at.
            is_deceased = attrs.get("is_deceased")
            deceased_at = attrs.get("deceased_at")

            if is_deceased is True and deceased_at is None:
                raise serializers.ValidationError(
                    {"deceased_at": "La fecha de defunción es obligatoria cuando is_deceased=True."}
                )
            if is_deceased is False:
                # Limpiar la fecha si se revierte el estado (corrección administrativa).
                attrs["deceased_at"] = None

            return attrs

    def _get_patient_or_404(
        self, patient_id: uuid.UUID
    ) -> "tuple[Patient | None, Response | None]":
        """Recupera el paciente o devuelve una respuesta 404."""
        try:
            patient = patient_get(patient_id=patient_id)
            return patient, None
        except Patient.DoesNotExist:
            return None, Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Retorna el detalle de un paciente. Registra PATIENT_READ en la bitácora (NOM-024)."""
        patient, error_response = self._get_patient_or_404(patient_id)
        if error_response is not None:
            return error_response

        # NOM-024: registrar acceso al expediente individual del paciente.
        # Se registra DESPUÉS de obtener el paciente (objeto existe) y ANTES de serializar.
        # La auditoría NO debe impedir la respuesta (audit_record absorbe excepciones).
        audit_record(
            action=ActionType.PATIENT_READ,
            resource_type="Patient",
            actor=request.user,
            tenant=get_current_tenant(),
            resource_id=patient.id,  # type: ignore[union-attr]
            resource_repr=patient.record_number,  # identificador no-PII (LFPDPPP)
            actor_role=getattr(request, "active_role", "") or "",
        )

        return Response(PatientOutputSerializer(patient, context={"request": request}).data)

    def patch(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Actualización parcial de un paciente."""
        patient, error_response = self._get_patient_or_404(patient_id)
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
            updated_patient = patient_update(
                patient=patient,  # type: ignore[arg-type]
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            # FIX-B4: usar exc.messages (siempre lista), no exc.message.
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(PatientOutputSerializer(updated_patient, context={"request": request}).data)

    def delete(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Desactiva (soft) un paciente. No lo borra de la base de datos."""
        patient, error_response = self._get_patient_or_404(patient_id)
        if error_response is not None:
            return error_response

        patient_deactivate(patient=patient, _user=request.user)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)


class PatientAvatarApi(TenantAPIView):
    """POST   /api/v1/pacientes/<id>/avatar/  — sube/reemplaza la foto del paciente.
    DELETE /api/v1/pacientes/<id>/avatar/  — elimina la foto.

    Recibe multipart/form-data con el campo `avatar`. La imagen se valida
    (tamaño, formato real) antes de guardarse.
    """

    permission_classes = [IsAuthenticated, PatientPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Sube o reemplaza la foto del paciente."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response({"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        image = request.FILES.get("avatar")
        if image is None:
            return Response(
                {"detail": "No se envió ninguna imagen (campo 'avatar')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_avatar(image)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        patient = patient_set_avatar(patient=patient, user=request.user, image=image)
        return Response(PatientOutputSerializer(patient, context={"request": request}).data)

    def delete(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Elimina la foto del paciente."""
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response({"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        patient = patient_clear_avatar(patient=patient, user=request.user)
        return Response(PatientOutputSerializer(patient, context={"request": request}).data)


class PatientClassifyApi(TenantAPIView):
    """POST /api/v1/pacientes/<uuid:patient_id>/clasificacion/

    Marca o desmarca un paciente como favorito y/o VIP.
    Solo actualiza los flags que se envíen en el cuerpo. Un campo ausente
    (no enviado) no modifica el flag correspondiente.

    Permisos: mismos roles que POST de pacientes (owner, admin, doctor, nurse, reception).
    """

    permission_classes = [IsAuthenticated, PatientPermission]

    class InputSerializer(serializers.Serializer):
        is_favorite = serializers.BooleanField(required=False)
        is_vip = serializers.BooleanField(required=False)

    def post(self, request: Request, patient_id: uuid.UUID) -> Response:
        """Clasifica un paciente actualizando is_favorite y/o is_vip."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        updated_patient = patient_set_classification(
            patient=patient,
            user=request.user,
            is_favorite=s.validated_data.get("is_favorite"),
            is_vip=s.validated_data.get("is_vip"),
        )
        return Response(
            PatientOutputSerializer(updated_patient, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )
