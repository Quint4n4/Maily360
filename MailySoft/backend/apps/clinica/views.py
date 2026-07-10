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
)
from apps.clinica.permissions import (
    ClinicSettingsPermission,
    ClinicTeamPermission,
    ClinicTemplatePermission,
    DoctorProfilePermission,
    PatientCategoryPermission,
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
    patient_category_get,
    patient_category_list,
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
    PatientCategoryInputSerializer,
    PatientCategoryOutputSerializer,
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
    patient_category_create,
    patient_category_deactivate,
    template_create,
    template_deactivate,
    template_update,
)
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.personal.models import Doctor
from apps.personal.selectors import doctor_get

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
