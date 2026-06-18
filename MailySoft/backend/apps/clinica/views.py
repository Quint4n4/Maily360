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
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.clinica.models import ClinicSettings, ClinicTemplate, DoctorUniversity, PatientCategory
from apps.clinica.permissions import (
    ClinicSettingsPermission,
    ClinicTemplatePermission,
    DoctorProfilePermission,
    PatientCategoryPermission,
)
from apps.clinica.selectors import (
    clinic_settings_get,
    clinic_template_get,
    clinic_template_list,
    doctor_university_get,
    doctor_university_list,
    patient_category_get,
    patient_category_list,
)
from apps.clinica.serializers import (
    ClinicSettingsInputSerializer,
    ClinicSettingsOutputSerializer,
    ClinicTemplateInputSerializer,
    ClinicTemplatePatchSerializer,
    ClinicTemplateOutputSerializer,
    DoctorProfileImageInputSerializer,
    DoctorUniversityInputSerializer,
    DoctorUniversityOutputSerializer,
    PatientCategoryInputSerializer,
    PatientCategoryOutputSerializer,
)
from apps.clinica.services import (
    clinic_settings_upsert,
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

    def _get_doctor_or_404(
        self, doctor_id: uuid.UUID
    ) -> "tuple[Doctor | None, Response | None]":
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
        from apps.personal.serializers import DoctorOutputSerializer
        from apps.personal.selectors import doctor_get as doctor_get_full

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

    def _get_doctor_or_404(
        self, doctor_id: uuid.UUID
    ) -> "tuple[Doctor | None, Response | None]":
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
