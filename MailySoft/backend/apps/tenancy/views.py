"""
Vistas de la app tenancy — gestión de miembros de la clínica.

Vistas delgadas: parsean, llaman al service/selector, devuelven Response.
Solo owner y admin (MemberPermission). Hereda de TenantAPIView para que el
tenant activo se resuelva tras autenticar el JWT.

Endpoints:
    GET  /api/v1/miembros/                 — lista de miembros (sin paginar; son pocos).
    POST /api/v1/miembros/                 — alta de miembro (usuario + membresía).
    PATCH /api/v1/miembros/<id>/           — cambiar rol y/o bloquear/reactivar.
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.files import validate_avatar
from apps.core.permissions import MemberPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.tenancy.models import TenantMembership
from apps.tenancy.selectors import membership_get, membership_list
from apps.tenancy.serializers import MemberOutputSerializer
from apps.tenancy.services import (
    member_clear_avatar,
    member_create,
    member_set_avatar,
    member_update,
)


class MemberListCreateApi(TenantAPIView):
    """GET  /api/v1/miembros/  — lista de miembros de la clínica.
    POST /api/v1/miembros/  — alta de un miembro (cuenta + membresía con rol).
    """

    permission_classes = [IsAuthenticated, MemberPermission]

    class InputSerializer(serializers.Serializer):
        email = serializers.EmailField()
        first_name = serializers.CharField(max_length=120)
        last_name = serializers.CharField(max_length=120, default="", allow_blank=True)
        password = serializers.CharField(max_length=128, write_only=True)
        role = serializers.ChoiceField(choices=TenantMembership.Role.choices)

    def get(self, request: Request) -> Response:
        """Lista de miembros del tenant (sin paginar — son pocos)."""
        qs = membership_list()
        return Response(MemberOutputSerializer(qs, many=True).data)

    def post(self, request: Request) -> Response:
        """Crea un miembro en el tenant del request."""
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            membership = member_create(
                tenant=tenant,
                actor=request.user,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            MemberOutputSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )


class MemberDetailApi(TenantAPIView):
    """PATCH /api/v1/miembros/<uuid:membership_id>/ — cambia rol y/o bloqueo."""

    permission_classes = [IsAuthenticated, MemberPermission]

    class InputSerializer(serializers.Serializer):
        first_name = serializers.CharField(max_length=120, required=False)
        last_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
        role = serializers.ChoiceField(choices=TenantMembership.Role.choices, required=False)
        # Restablecer contraseña: nunca se lee, solo se escribe.
        password = serializers.CharField(max_length=128, required=False, write_only=True)
        # blocked True = bloquear la cuenta (no puede iniciar sesión); False = reactivar.
        blocked = serializers.BooleanField(required=False)

    def _get_membership_or_404(
        self, membership_id: uuid.UUID
    ) -> "tuple[TenantMembership | None, Response | None]":
        try:
            membership = membership_get(membership_id=membership_id)
            return membership, None
        except TenantMembership.DoesNotExist:
            return None, Response(
                {"detail": "Miembro no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def patch(self, request: Request, membership_id: uuid.UUID) -> Response:
        """Actualiza rol y/o estado de bloqueo de un miembro."""
        membership, error = self._get_membership_or_404(membership_id)
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
            updated = member_update(
                membership=membership,  # type: ignore[arg-type]
                actor=request.user,
                first_name=s.validated_data.get("first_name"),
                last_name=s.validated_data.get("last_name"),
                role=s.validated_data.get("role"),
                password=s.validated_data.get("password"),
                blocked=s.validated_data.get("blocked"),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(MemberOutputSerializer(updated).data)


class MemberAvatarApi(TenantAPIView):
    """POST   /api/v1/miembros/<id>/avatar/  — sube/reemplaza la foto del miembro.
    DELETE /api/v1/miembros/<id>/avatar/  — elimina la foto.

    Recibe multipart/form-data con el campo `avatar` (validado antes de guardar).
    """

    permission_classes = [IsAuthenticated, MemberPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request, membership_id: uuid.UUID) -> Response:
        """Sube o reemplaza la foto del miembro."""
        try:
            membership = membership_get(membership_id=membership_id)
        except TenantMembership.DoesNotExist:
            return Response({"detail": "Miembro no encontrado."}, status=status.HTTP_404_NOT_FOUND)

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

        membership = member_set_avatar(membership=membership, actor=request.user, image=image)
        return Response(MemberOutputSerializer(membership).data)

    def delete(self, request: Request, membership_id: uuid.UUID) -> Response:
        """Elimina la foto del miembro."""
        try:
            membership = membership_get(membership_id=membership_id)
        except TenantMembership.DoesNotExist:
            return Response({"detail": "Miembro no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        membership = member_clear_avatar(membership=membership, actor=request.user)
        return Response(MemberOutputSerializer(membership).data)
