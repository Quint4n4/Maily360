"""
Vistas de la app clinica — Mi Consultorio.

Vistas delgadas: parsean request, llaman un selector o service, devuelven Response.
Cero lógica de negocio aquí.

Hereda de TenantAPIView para garantizar resolución de tenant y permisos correctos.

Manejo de errores:
    - <Modelo>.DoesNotExist → 404 (nunca 403; no se revela si el recurso existe en otro tenant).
    - ValidationError (django.core.exceptions) → 400 con exc.messages.
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.clinica.models import (
    ClinicTeamMember,
    ClinicTemplate,
    DoctorCredential,
    DoctorUniversity,
    PatientCategory,
    Sucursal,
)
from apps.clinica.permissions import (
    ClinicSettingsPermission,
    ClinicTeamPermission,
    ClinicTemplatePermission,
    DoctorProfilePermission,
    MembershipSucursalPermission,
    PatientCategoryPermission,
    SucursalPermission,
)
from apps.clinica.selectors import (
    clinic_settings_get,
    clinic_team_get,
    clinic_team_list,
    clinic_template_get,
    clinic_template_list,
    doctor_credential_get,
    doctor_credential_list,
    doctor_credentials_for_tenant,
    doctor_university_get,
    doctor_university_list,
    membership_sucursales_list,
    patient_category_get,
    patient_category_list,
    sucursal_get,
)
from apps.clinica.serializers import (
    ClinicSettingsInputSerializer,
    ClinicSettingsOutputSerializer,
    ClinicTeamMemberInputSerializer,
    ClinicTeamMemberOutputSerializer,
    ClinicTeamMemberPatchSerializer,
    ClinicTemplateInputSerializer,
    ClinicTemplateOutputSerializer,
    ClinicTemplatePatchSerializer,
    DoctorCredentialInputSerializer,
    DoctorCredentialOutputSerializer,
    DoctorCredentialValidationInputSerializer,
    DoctorProfileImageInputSerializer,
    DoctorUniversityInputSerializer,
    DoctorUniversityOutputSerializer,
    MembershipSucursalesInputSerializer,
    PatientCategoryInputSerializer,
    PatientCategoryOutputSerializer,
    SucursalInputSerializer,
    SucursalMiniOutputSerializer,
    SucursalOutputSerializer,
    SucursalPatchSerializer,
)
from apps.clinica.services import (
    clinic_settings_upsert,
    clinic_team_member_activate,
    clinic_team_member_create,
    clinic_team_member_deactivate,
    clinic_team_member_delete,
    clinic_team_member_update,
    doctor_credential_create,
    doctor_credential_delete,
    doctor_credential_set_validation,
    doctor_credential_update,
    doctor_university_create,
    doctor_university_delete,
    doctor_update_profile_images,
    membership_sucursales_set,
    patient_category_create,
    patient_category_deactivate,
    sucursal_activate,
    sucursal_create,
    sucursal_deactivate,
    sucursal_set_default,
    sucursal_update,
    template_create,
    template_deactivate,
    template_update,
)
from apps.clinica.sucursal_scope import actor_sucursal_ids, allowed_sucursales
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.personal.models import Doctor
from apps.personal.selectors import doctor_get
from apps.tenancy.models import TenantMembership
from apps.tenancy.selectors import membership_get

# ---------------------------------------------------------------------------
# ClinicSettings — GET/PUT configuracion/
# ---------------------------------------------------------------------------


class ClinicSettingsApi(TenantAPIView):
    """GET /api/v1/clinica/configuracion/   — obtiene la configuración de la clínica.
    PUT /api/v1/clinica/configuracion/   — crea o actualiza la configuración (upsert).

    Las imágenes (logo, letterhead_full, letterhead_half) se envían como multipart.
    El PUT es idempotente: si no existe config la crea; si existe la actualiza.
    Los campos no enviados en PUT se mantienen como estaban (partial update).
    """

    permission_classes = [IsAuthenticated, ClinicSettingsPermission]

    def get(self, request: Request) -> Response:
        """Retorna la configuración actual de la clínica o 204 si aún no existe."""
        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        settings = clinic_settings_get(tenant_id=tenant.id)
        if settings is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(ClinicSettingsOutputSerializer(settings).data)

    def put(self, request: Request) -> Response:
        """Crea o actualiza la configuración de la clínica (upsert parcial).

        Solo actualiza los campos presentes en el payload.
        Imágenes solo se reemplazan si se envían en el request.
        """
        s = ClinicSettingsInputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            settings = clinic_settings_upsert(
                tenant=tenant,
                user=request.user,
                _partial_fields=frozenset(s.validated_data.keys()),
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(ClinicSettingsOutputSerializer(settings).data)


# ---------------------------------------------------------------------------
# ClinicTemplate — GET/POST plantillas/ y GET/PATCH/DELETE plantillas/<id>/
# ---------------------------------------------------------------------------


class ClinicTemplateListCreateApi(TenantAPIView):
    """GET  /api/v1/clinica/plantillas/   — lista de plantillas (filtrable por kind).
    POST /api/v1/clinica/plantillas/   — crea una plantilla nueva.
    """

    permission_classes = [IsAuthenticated, ClinicTemplatePermission]

    def get(self, request: Request) -> Response:
        """Lista paginada de plantillas activas del tenant.

        Query param `kind` filtra por tipo (recipe/document/consent).
        """
        kind: str | None = request.query_params.get("kind") or None

        qs = clinic_template_list(kind=kind)

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                ClinicTemplateOutputSerializer(page, many=True).data
            )

        return Response(
            {"detail": "Paginación no disponible."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea una plantilla clínica en el tenant del request."""
        s = ClinicTemplateInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            template = template_create(
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
            ClinicTemplateOutputSerializer(template).data,
            status=status.HTTP_201_CREATED,
        )


class ClinicTemplateDetailApi(TenantAPIView):
    """GET    /api/v1/clinica/plantillas/<id>/  — detalle de una plantilla.
    PATCH  /api/v1/clinica/plantillas/<id>/  — actualización parcial.
    DELETE /api/v1/clinica/plantillas/<id>/  — baja lógica (is_active=False).
    """

    permission_classes = [IsAuthenticated, ClinicTemplatePermission]

    def _get_template_or_404(
        self, template_id: uuid.UUID
    ) -> "tuple[ClinicTemplate | None, Response | None]":
        try:
            t = clinic_template_get(template_id=template_id)
            return t, None
        except ClinicTemplate.DoesNotExist:
            return None, Response(
                {"detail": "Plantilla no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, template_id: uuid.UUID) -> Response:
        tmpl, err = self._get_template_or_404(template_id)
        if err:
            return err
        return Response(ClinicTemplateOutputSerializer(tmpl).data)

    def patch(self, request: Request, template_id: uuid.UUID) -> Response:
        tmpl, err = self._get_template_or_404(template_id)
        if err:
            return err

        s = ClinicTemplatePatchSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated = template_update(
                template=tmpl,  # type: ignore[arg-type]
                user=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(ClinicTemplateOutputSerializer(updated).data)

    def delete(self, request: Request, template_id: uuid.UUID) -> Response:
        tmpl, err = self._get_template_or_404(template_id)
        if err:
            return err

        template_deactivate(template=tmpl, user=request.user)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# PatientCategory — GET/POST categorias/ y DELETE categorias/<id>/
# ---------------------------------------------------------------------------


class PatientCategoryListCreateApi(TenantAPIView):
    """GET  /api/v1/clinica/categorias/  — lista de categorías activas.
    POST /api/v1/clinica/categorias/  — crea una categoría nueva.
    """

    permission_classes = [IsAuthenticated, PatientCategoryPermission]

    def get(self, request: Request) -> Response:
        """Lista paginada de categorías activas del tenant."""
        qs = patient_category_list()

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                PatientCategoryOutputSerializer(page, many=True).data
            )

        return Response(
            {"detail": "Paginación no disponible."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea una categoría de paciente en el tenant del request."""
        s = PatientCategoryInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            category = patient_category_create(
                tenant=tenant,
                user=request.user,
                name=s.validated_data["name"],
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            PatientCategoryOutputSerializer(category).data,
            status=status.HTTP_201_CREATED,
        )


class PatientCategoryDetailApi(TenantAPIView):
    """DELETE /api/v1/clinica/categorias/<id>/  — baja lógica de una categoría."""

    permission_classes = [IsAuthenticated, PatientCategoryPermission]

    def _get_category_or_404(
        self, category_id: uuid.UUID
    ) -> "tuple[PatientCategory | None, Response | None]":
        try:
            cat = patient_category_get(category_id=category_id)
            return cat, None
        except PatientCategory.DoesNotExist:
            return None, Response(
                {"detail": "Categoría no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def delete(self, request: Request, category_id: uuid.UUID) -> Response:
        cat, err = self._get_category_or_404(category_id)
        if err:
            return err

        patient_category_deactivate(
            category=cat,  # type: ignore[arg-type]
            user=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Doctor — perfil ampliado (sello, foto, cédulas adicionales)
# ---------------------------------------------------------------------------


class DoctorProfileApi(TenantAPIView):
    """PATCH /api/v1/clinica/doctores/<doctor_id>/perfil/
        — sube sello, foto y/o actualiza cédulas adicionales del médico.

    Acceso: owner, admin o el propio médico.
    Si el actor es doctor (no owner/admin), el service valida que el doctor
    del perfil sea el mismo que el actor. Esa granularidad se aplica
    en el service, no en el permiso HTTP (que solo checa el rol).
    """

    permission_classes = [IsAuthenticated, DoctorProfilePermission]

    def _get_doctor_or_404(self, doctor_id: uuid.UUID) -> "tuple[Doctor | None, Response | None]":
        try:
            d = doctor_get(doctor_id=doctor_id)
            return d, None
        except Doctor.DoesNotExist:
            return None, Response(
                {"detail": "Médico no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def patch(self, request: Request, doctor_id: uuid.UUID) -> Response:
        """Actualiza sello, foto o cédulas adicionales del médico."""
        doctor, err = self._get_doctor_or_404(doctor_id)
        if err:
            return err

        s = DoctorProfileImageInputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Granularidad: si el actor es doctor (no admin/owner), solo puede
        # modificar su propio perfil.
        actor_role: str | None = getattr(request, "active_role", None)
        if actor_role == "doctor":
            # Verificar que el doctor del perfil coincide con el membership del actor.
            membership = getattr(request, "membership", None)
            if membership is None or str(doctor.membership_id) != str(membership.id):
                return Response(
                    {"detail": "Solo puedes modificar tu propio perfil médico."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            updated = doctor_update_profile_images(
                doctor=doctor,  # type: ignore[arg-type]
                user=request.user,
                sello=s.validated_data.get("sello"),
                foto=s.validated_data.get("foto"),
                cedulas_adicionales=s.validated_data.get("cedulas_adicionales"),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Re-serializar con el serializer de personal (no necesita uno propio).
        from apps.personal.selectors import doctor_get as doctor_get_full
        from apps.personal.serializers import DoctorOutputSerializer

        refreshed = doctor_get_full(doctor_id=updated.id)  # type: ignore[arg-type]
        return Response(DoctorOutputSerializer(refreshed).data)


# ---------------------------------------------------------------------------
# DoctorUniversity — GET/POST doctores/<id>/universidades/ y DELETE <uid>/
# ---------------------------------------------------------------------------


class DoctorUniversityListCreateApi(TenantAPIView):
    """GET  /api/v1/clinica/doctores/<doctor_id>/universidades/  — logos de universidades.
    POST /api/v1/clinica/doctores/<doctor_id>/universidades/  — agrega una universidad.
    """

    permission_classes = [IsAuthenticated, DoctorProfilePermission]

    def _get_doctor_or_404(self, doctor_id: uuid.UUID) -> "tuple[Doctor | None, Response | None]":
        try:
            d = doctor_get(doctor_id=doctor_id)
            return d, None
        except Doctor.DoesNotExist:
            return None, Response(
                {"detail": "Médico no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, doctor_id: uuid.UUID) -> Response:
        """Lista las universidades del médico."""
        _, err = self._get_doctor_or_404(doctor_id)
        if err:
            return err

        qs = doctor_university_list(doctor_id=doctor_id)
        return Response(DoctorUniversityOutputSerializer(qs, many=True).data)

    def post(self, request: Request, doctor_id: uuid.UUID) -> Response:
        """Agrega un logo de universidad al médico."""
        doctor, err = self._get_doctor_or_404(doctor_id)
        if err:
            return err

        # Guard M-1: un doctor solo puede agregar universidades a su propio perfil.
        actor_role: str | None = getattr(request, "active_role", None)
        if actor_role == "doctor":
            membership = getattr(request, "membership", None)
            if membership is None or str(doctor.membership_id) != str(membership.id):
                return Response(
                    {"detail": "Solo puedes agregar universidades a tu propio perfil médico."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        s = DoctorUniversityInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            university = doctor_university_create(
                tenant=tenant,
                user=request.user,
                doctor=doctor,  # type: ignore[arg-type]
                logo=s.validated_data["logo"],
                name=s.validated_data.get("name", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            DoctorUniversityOutputSerializer(university).data,
            status=status.HTTP_201_CREATED,
        )


class DoctorUniversityDetailApi(TenantAPIView):
    """DELETE /api/v1/clinica/universidades/<university_id>/  — elimina un logo."""

    permission_classes = [IsAuthenticated, DoctorProfilePermission]

    def _get_university_or_404(
        self, university_id: uuid.UUID
    ) -> "tuple[DoctorUniversity | None, Response | None]":
        try:
            u = doctor_university_get(university_id=university_id)
            return u, None
        except DoctorUniversity.DoesNotExist:
            return None, Response(
                {"detail": "Universidad no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def delete(self, request: Request, university_id: uuid.UUID) -> Response:
        """Elimina físicamente el logo de universidad."""
        univ, err = self._get_university_or_404(university_id)
        if err:
            return err

        # Guard M-1: un doctor solo puede eliminar universidades de su propio perfil.
        actor_role: str | None = getattr(request, "active_role", None)
        if actor_role == "doctor":
            membership = getattr(request, "membership", None)
            if membership is None or str(univ.doctor.membership_id) != str(membership.id):
                return Response(
                    {"detail": "Solo puedes eliminar universidades de tu propio perfil médico."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        doctor_university_delete(
            university=univ,  # type: ignore[arg-type]
            user=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# DoctorCredential — GET/POST doctores/<id>/credenciales/ y DELETE credenciales/<id>/
# ---------------------------------------------------------------------------


class DoctorCredentialListCreateApi(TenantAPIView):
    """GET  /api/v1/clinica/doctores/<doctor_id>/credenciales/  — lista de credenciales.
    POST /api/v1/clinica/doctores/<doctor_id>/credenciales/  — agrega una credencial.

    Acceso: owner/admin siempre. Doctor solo si es el mismo médico (Guard M-1).
    Las credenciales son datos COFEPRIS — no datos clínicos del paciente.
    Acepta multipart/form-data para el campo `logo` (imagen de la institución).
    """

    permission_classes = [IsAuthenticated, DoctorProfilePermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_doctor_or_404(self, doctor_id: uuid.UUID) -> "tuple[Doctor | None, Response | None]":
        try:
            d = doctor_get(doctor_id=doctor_id)
            return d, None
        except Doctor.DoesNotExist:
            return None, Response(
                {"detail": "Médico no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, doctor_id: uuid.UUID) -> Response:
        """Lista las credenciales activas del médico."""
        _, err = self._get_doctor_or_404(doctor_id)
        if err:
            return err

        qs = doctor_credential_list(doctor_id=doctor_id)
        return Response(DoctorCredentialOutputSerializer(qs, many=True).data)

    def post(self, request: Request, doctor_id: uuid.UUID) -> Response:
        """Agrega una credencial académica al médico."""
        doctor, err = self._get_doctor_or_404(doctor_id)
        if err:
            return err

        # Guard M-1: un doctor solo puede agregar credenciales a su propio perfil.
        actor_role: str | None = getattr(request, "active_role", None)
        if actor_role == "doctor":
            membership = getattr(request, "membership", None)
            if membership is None or str(doctor.membership_id) != str(membership.id):
                return Response(
                    {"detail": "Solo puedes agregar credenciales a tu propio perfil médico."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        s = DoctorCredentialInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            credential = doctor_credential_create(
                tenant=tenant,
                user=request.user,
                doctor=doctor,  # type: ignore[arg-type]
                title=s.validated_data["title"],
                institution=s.validated_data["institution"],
                kind=s.validated_data["kind"],
                credential_number=s.validated_data.get("credential_number", ""),
                order=s.validated_data.get("order", 0),
                logo=s.validated_data.get("logo"),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            DoctorCredentialOutputSerializer(credential).data,
            status=status.HTTP_201_CREATED,
        )


class DoctorCredentialDetailApi(TenantAPIView):
    """PATCH  /api/v1/clinica/credenciales/<credential_id>/  — edita la credencial (incl. logo).
    DELETE /api/v1/clinica/credenciales/<credential_id>/  — baja lógica de credencial.

    PATCH acepta multipart/form-data: edición parcial de los campos y reemplazo del
    logo de la institución. DELETE hace baja lógica (is_active=False): las credenciales
    son documentos con implicaciones legales COFEPRIS y se conservan para auditoría.
    """

    permission_classes = [IsAuthenticated, DoctorProfilePermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_credential_or_404(
        self, credential_id: uuid.UUID
    ) -> "tuple[DoctorCredential | None, Response | None]":
        try:
            cred = doctor_credential_get(credential_id=credential_id)
            return cred, None
        except DoctorCredential.DoesNotExist:
            return None, Response(
                {"detail": "Credencial no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def patch(self, request: Request, credential_id: uuid.UUID) -> Response:
        """Edita (parcial) una credencial del médico, incluido su logo (multipart)."""
        cred, err = self._get_credential_or_404(credential_id)
        if err:
            return err

        # Guard M-1: un doctor solo puede editar credenciales de su propio perfil.
        actor_role: str | None = getattr(request, "active_role", None)
        if actor_role == "doctor":
            membership = getattr(request, "membership", None)
            if membership is None or str(cred.doctor.membership_id) != str(membership.id):
                return Response(
                    {"detail": "Solo puedes editar credenciales de tu propio perfil médico."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        s = DoctorCredentialInputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        try:
            credential = doctor_credential_update(
                credential=cred,  # type: ignore[arg-type]
                user=request.user,
                title=s.validated_data.get("title"),
                institution=s.validated_data.get("institution"),
                kind=s.validated_data.get("kind"),
                credential_number=s.validated_data.get("credential_number"),
                order=s.validated_data.get("order"),
                logo=s.validated_data.get("logo"),
                logo_provided="logo" in s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(DoctorCredentialOutputSerializer(credential).data)

    def delete(self, request: Request, credential_id: uuid.UUID) -> Response:
        """Da de baja (is_active=False) una credencial del médico."""
        cred, err = self._get_credential_or_404(credential_id)
        if err:
            return err

        # Guard M-1: un doctor solo puede dar de baja credenciales de su propio perfil.
        actor_role: str | None = getattr(request, "active_role", None)
        if actor_role == "doctor":
            membership = getattr(request, "membership", None)
            if membership is None or str(cred.doctor.membership_id) != str(membership.id):
                return Response(
                    {"detail": "Solo puedes dar de baja credenciales de tu propio perfil médico."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        doctor_credential_delete(
            credential=cred,  # type: ignore[arg-type]
            user=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class DoctorCredentialTenantListApi(TenantAPIView):
    """GET /api/v1/clinica/credenciales/  — bandeja de validación (todo el tenant).

    Lista las credenciales de TODOS los médicos de la clínica para que el
    administrador las valide. Filtro opcional ?status=pendiente|validada|rechazada.
    Solo owner/admin (un médico ve solo las suyas en /doctores/<id>/credenciales/).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        actor_role: str | None = getattr(request, "active_role", None)
        if actor_role not in ("owner", "admin"):
            return Response(
                {"detail": "Solo un administrador puede ver la bandeja de validación."},
                status=status.HTTP_403_FORBIDDEN,
            )
        estado = request.query_params.get("status") or None
        if estado and estado not in ("pendiente", "validada", "rechazada"):
            return Response(
                {"detail": "Estado de validación inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = doctor_credentials_for_tenant(status=estado)
        return Response(DoctorCredentialOutputSerializer(qs, many=True).data)


class DoctorCredentialValidationApi(TenantAPIView):
    """PATCH /api/v1/clinica/credenciales/<credential_id>/validar/  — valida o rechaza.

    Acción administrativa (solo owner/admin): status='validada'|'rechazada' + note.
    Solo las credenciales validadas aparecen en la receta.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, credential_id: uuid.UUID) -> Response:
        actor_role: str | None = getattr(request, "active_role", None)
        if actor_role not in ("owner", "admin"):
            return Response(
                {"detail": "Solo un administrador puede validar o rechazar credenciales."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            cred = doctor_credential_get(credential_id=credential_id)
        except DoctorCredential.DoesNotExist:
            return Response(
                {"detail": "Credencial no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = DoctorCredentialValidationInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cred = doctor_credential_set_validation(
                credential=cred,
                user=request.user,
                status=s.validated_data["status"],
                note=s.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(DoctorCredentialOutputSerializer(cred).data)


# ---------------------------------------------------------------------------
# ClinicTeamMember — GET/POST equipo/ y GET/PATCH/DELETE equipo/<id>/ (Fase 4)
# ---------------------------------------------------------------------------


class ClinicTeamMemberListCreateApi(TenantAPIView):
    """GET  /api/v1/clinica/equipo/ — lista paginada del equipo de la clínica.
    POST /api/v1/clinica/equipo/ — crea un miembro del equipo (owner/admin).
    """

    permission_classes = [IsAuthenticated, ClinicTeamPermission]

    def get(self, request: Request) -> Response:
        """Lista paginada del equipo/departamentos del tenant.

        Query param `only_active` (default true).
        """
        only_active = request.query_params.get("only_active", "true").lower() != "false"

        qs = clinic_team_list(only_active=only_active)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(
                ClinicTeamMemberOutputSerializer(page, many=True).data
            )

        return Response(
            {"detail": "Paginación no disponible."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea un miembro del equipo en el tenant del request."""
        s = ClinicTeamMemberInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            member = clinic_team_member_create(tenant=tenant, user=request.user, **s.validated_data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ClinicTeamMemberOutputSerializer(member).data, status=status.HTTP_201_CREATED
        )


class ClinicTeamMemberDetailApi(TenantAPIView):
    """GET/PATCH/DELETE /api/v1/clinica/equipo/<id>/."""

    permission_classes = [IsAuthenticated, ClinicTeamPermission]

    def _get_or_404(
        self, member_id: uuid.UUID
    ) -> "tuple[ClinicTeamMember | None, Response | None]":
        try:
            return clinic_team_get(member_id=member_id), None
        except ClinicTeamMember.DoesNotExist:
            return None, Response(
                {"detail": "Miembro del equipo no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def get(self, request: Request, member_id: uuid.UUID) -> Response:
        member, err = self._get_or_404(member_id)
        if err is not None:
            return err
        return Response(ClinicTeamMemberOutputSerializer(member).data)

    def patch(self, request: Request, member_id: uuid.UUID) -> Response:
        member, err = self._get_or_404(member_id)
        if err is not None:
            return err

        s = ClinicTeamMemberPatchSerializer(data=request.data, partial=True)
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
                    member = clinic_team_member_activate(member=member, user=request.user)  # type: ignore[arg-type]
                else:
                    member = clinic_team_member_deactivate(member=member, user=request.user)  # type: ignore[arg-type]
            if data:
                member = clinic_team_member_update(member=member, user=request.user, **data)  # type: ignore[arg-type]
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ClinicTeamMemberOutputSerializer(member).data)

    def delete(self, request: Request, member_id: uuid.UUID) -> Response:
        member, err = self._get_or_404(member_id)
        if err is not None:
            return err
        clinic_team_member_delete(member=member, user=request.user)  # type: ignore[arg-type]
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Sucursal — GET/POST sucursales/ y GET/PATCH/DELETE sucursales/<id>/ (Fase 1)
# ---------------------------------------------------------------------------


class SucursalListCreateApi(TenantAPIView):
    """GET  /api/v1/clinica/sucursales/ — sucursales permitidas del usuario (selector).
    POST /api/v1/clinica/sucursales/ — crea una sucursal (owner/admin).

    GET devuelve `allowed_sucursales(user, tenant)`: owner ve TODAS las
    sucursales activas del tenant; cualquier otro rol (admin incluido) solo
    las suyas (MembershipSucursal), o la sede default como fallback
    anti-lockout si no tiene ninguna asignación. Este es el mismo criterio
    que usa `resolve_active_sucursal` para validar el header X-Sucursal-Id
    — así el selector del frontend nunca ofrece una sede que luego el
    backend rechazaría.
    """

    permission_classes = [IsAuthenticated, SucursalPermission]

    def get(self, request: Request) -> Response:
        """Lista paginada de las sucursales activas que el usuario puede operar."""
        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        qs = allowed_sucursales(user=request.user, tenant=tenant)

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(SucursalOutputSerializer(page, many=True).data)

        return Response(
            {"detail": "Paginación no disponible."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def post(self, request: Request) -> Response:
        """Crea una sucursal en el tenant del request (owner/admin)."""
        s = SucursalInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            sucursal = sucursal_create(tenant=tenant, user=request.user, **s.validated_data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            SucursalOutputSerializer(sucursal).data,
            status=status.HTTP_201_CREATED,
        )


class SucursalDetailApi(TenantAPIView):
    """GET    /api/v1/clinica/sucursales/<id>/ — detalle de una sucursal.
    PATCH  /api/v1/clinica/sucursales/<id>/ — actualización parcial (owner/admin).
    DELETE /api/v1/clinica/sucursales/<id>/ — baja lógica (is_active=False, owner/admin).

    PATCH separa is_active/is_default del resto de los campos: se enrutan a
    sucursal_activate/sucursal_deactivate/sucursal_set_default en vez de al
    service de update genérico (regla de campos sensibles del proyecto).

    `_get_or_404` acota el id contra `actor_sucursal_ids` (owner: todas; el
    resto de los roles: solo su `MembershipSucursal`, sea la sede activa o
    no) — no solo contra el tenant. Cierra el Clúster C de la auditoría de
    seguridad (docs/design/sucursales-hallazgos-seguridad.md): antes, un
    admin acotado a Centro podía PATCH/DELETE la sucursal Norte (renombrar,
    marcar default, e incluso desactivarla) con solo conocer su id.
    """

    permission_classes = [IsAuthenticated, SucursalPermission]

    def _get_or_404(
        self, request: Request, sucursal_id: uuid.UUID
    ) -> "tuple[Sucursal | None, Response | None]":
        try:
            sucursal = sucursal_get(sucursal_id=sucursal_id)
        except Sucursal.DoesNotExist:
            return None, Response(
                {"detail": "Sucursal no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tenant = get_current_tenant()
        if tenant is None:
            return None, Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        scope_ids = actor_sucursal_ids(user=request.user, tenant=tenant)
        if scope_ids is not None and sucursal.id not in scope_ids:
            # Existe en el tenant pero fuera del alcance del actor: 404, no
            # 403 — nunca revela que la sucursal existe en otra sede.
            return None, Response(
                {"detail": "Sucursal no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return sucursal, None

    def get(self, request: Request, sucursal_id: uuid.UUID) -> Response:
        sucursal, err = self._get_or_404(request, sucursal_id)
        if err is not None:
            return err
        return Response(SucursalOutputSerializer(sucursal).data)

    def patch(self, request: Request, sucursal_id: uuid.UUID) -> Response:
        sucursal, err = self._get_or_404(request, sucursal_id)
        if err is not None:
            return err

        s = SucursalPatchSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = dict(s.validated_data)
        is_active = data.pop("is_active", None)
        is_default = data.pop("is_default", None)

        try:
            if is_active is not None:
                if is_active:
                    sucursal = sucursal_activate(sucursal=sucursal, user=request.user)  # type: ignore[arg-type]
                else:
                    sucursal = sucursal_deactivate(sucursal=sucursal, user=request.user)  # type: ignore[arg-type]
            if is_default is True:
                sucursal = sucursal_set_default(sucursal=sucursal, user=request.user)  # type: ignore[arg-type]
            if data:
                sucursal = sucursal_update(sucursal=sucursal, user=request.user, **data)  # type: ignore[arg-type]
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SucursalOutputSerializer(sucursal).data)

    def delete(self, request: Request, sucursal_id: uuid.UUID) -> Response:
        sucursal, err = self._get_or_404(request, sucursal_id)
        if err is not None:
            return err

        try:
            sucursal_deactivate(sucursal=sucursal, user=request.user)  # type: ignore[arg-type]
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# MembershipSucursal — GET/PUT membresias/<id>/sucursales/ (Fase 4)
# ---------------------------------------------------------------------------


class MembershipSucursalesApi(TenantAPIView):
    """GET /api/v1/clinica/membresias/<membership_id>/sucursales/
        — sucursales asignadas a un miembro de la clínica.
    PUT /api/v1/clinica/membresias/<membership_id>/sucursales/
        — reemplaza el conjunto completo de sucursales asignadas.

    Es el endpoint que habilita crear un "administrador de sucursal" desde la
    app: asignarle a un admin solo una sede lo acota a operar/ver solo esa
    sede (apps.clinica.sucursal_scope.allowed_sucursales). Solo owner y admin
    pueden llegar aquí (MembershipSucursalPermission); la regla fina de que
    un admin solo puede tocar sedes que él mismo tiene asignadas —y las
    guardas anti-lockout— se valida en el service `membership_sucursales_set`.

    `membership_id` se resuelve con el selector tenant-scoped de tenancy
    (`membership_get`): una membresía de otro tenant produce DoesNotExist →
    404 (nunca se revela si existe en otro negocio).
    """

    permission_classes = [IsAuthenticated, MembershipSucursalPermission]

    def _get_membership_or_404(
        self, membership_id: uuid.UUID
    ) -> "tuple[TenantMembership | None, Response | None]":
        try:
            return membership_get(membership_id=membership_id), None
        except TenantMembership.DoesNotExist:
            return None, Response(
                {"detail": "Miembro no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def _serialize(self, membership: TenantMembership) -> dict[str, object]:
        qs = membership_sucursales_list(membership=membership)
        return {
            "membership_id": str(membership.id),
            "sucursales": SucursalMiniOutputSerializer(qs, many=True).data,
        }

    def get(self, request: Request, membership_id: uuid.UUID) -> Response:
        """Lista las sucursales actualmente asignadas al miembro."""
        membership, err = self._get_membership_or_404(membership_id)
        if err is not None:
            return err
        return Response(self._serialize(membership))  # type: ignore[arg-type]

    def put(self, request: Request, membership_id: uuid.UUID) -> Response:
        """Reemplaza el conjunto de sucursales asignadas al miembro."""
        membership, err = self._get_membership_or_404(membership_id)
        if err is not None:
            return err

        s = MembershipSucursalesInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            membership = membership_sucursales_set(
                tenant=tenant,
                actor=request.user,
                membership=membership,  # type: ignore[arg-type]
                sucursal_ids=s.validated_data["sucursal_ids"],
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self._serialize(membership))
