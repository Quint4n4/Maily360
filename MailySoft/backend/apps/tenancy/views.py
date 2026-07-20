"""
Vistas de la app tenancy — gestión de miembros de la clínica.

Vistas delgadas: parsean, llaman al service/selector, devuelven Response.
Solo owner y admin (MemberPermission). Hereda de TenantAPIView para que el
tenant activo se resuelva tras autenticar el JWT.

Scoping por sucursal (multi-sede — cierre del clúster F, ver
docs/design/sucursales-hallazgos-seguridad.md): esta app usa DOS criterios
de sucursal distintos, cada uno con su propio propósito — no se mezclan:
    - `sucursal_scope_ids(request)` (VISTA de listado): la lista de equipo
      se acota a la sede ACTIVA del selector (header X-Sucursal-Id), igual
      que agenda/finanzas. Los owner siempre aparecen en el listado.
    - `allowed_sucursales(user, tenant)` (PERMISO): el detalle/avatar de un
      miembro se acota a lo que el actor puede TOCAR, sin importar qué sede
      tenga seleccionada en el header — si se usara `sucursal_scope_ids`
      aquí, el dueño parado en Centro no podría editar a alguien de Norte.

Jerarquía de roles (decisión del dueño 2026-07-16 —
`TenantMembership.operational_roles()`): un actor NO owner (el
"administrador de sucursal") nunca ve, ni puede tocar de ninguna forma
(detalle/PATCH/avatar), a un owner ni a otro admin — solo a personal con rol
operacional, más a sí mismo en el listado. `MemberListCreateApi.get` calcula
si el viewer es owner y su propia membresía (de `request.membership`, ya
resuelto por `TenantAPIView`) y se los pasa al selector.
`_member_get_or_404` aplica el mismo criterio como defensa en profundidad:
si el actor no es owner y el target no tiene rol operacional, responde 404
en vez de revelar que el recurso existe.

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

from apps.clinica.sucursal_scope import (
    allowed_sucursales,
    resolve_active_sucursal,
    sucursal_scope_ids,
)
from apps.core.files import validate_avatar
from apps.core.permissions import MemberPermission
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.tenancy.models import TenantMembership
from apps.tenancy.selectors import membership_get_in_scope, membership_list
from apps.tenancy.serializers import MemberOutputSerializer
from apps.tenancy.services import (
    member_clear_avatar,
    member_create,
    member_set_avatar,
    member_update,
)


def _member_not_found() -> Response:
    """Respuesta 404 fresca (no reutilizar la instancia entre requests)."""
    return Response({"detail": "Miembro no encontrado."}, status=status.HTTP_404_NOT_FOUND)


def _member_get_or_404(
    request: Request, membership_id: uuid.UUID
) -> "tuple[TenantMembership | None, Response | None]":
    """Resuelve una membresía acotada a `allowed_sucursales` del actor (PERMISO).

    Compartido por `MemberDetailApi` y `MemberAvatarApi`: el detalle y el
    avatar de un miembro se acotan a lo que el actor puede TOCAR (owner:
    todas; cualquier otro rol: solo sus sedes vía MembershipSucursal, con el
    mismo fallback a la sede default que `allowed_sucursales`), NUNCA al
    scope de un listado (`sucursal_scope_ids`). Fuera de alcance, o de otro
    tenant, produce 404 "Miembro no encontrado" (nunca revela que existe en
    otra sede o en otro negocio).

    Defensa en profundidad — jerarquía de roles (decisión del dueño
    2026-07-16): además del scope de sede, si el actor NO es owner y el
    target tiene un rol NO operacional (ya es OWNER o ADMIN) también
    responde 404 — mismo criterio que `_authorize_write_on_member`
    (apps.tenancy.services), pero resuelto ANTES de tocar el service, para
    que ni el detalle, ni el PATCH, ni el avatar de un owner/admin ajeno se
    revelen a un administrador de sucursal.
    """
    tenant = get_current_tenant()
    if tenant is None:
        return None, _member_not_found()

    allowed_ids = list(
        allowed_sucursales(user=request.user, tenant=tenant).values_list("id", flat=True)
    )
    try:
        membership = membership_get_in_scope(membership_id=membership_id, sucursal_ids=allowed_ids)
    except TenantMembership.DoesNotExist:
        return None, _member_not_found()

    actor_membership = getattr(request, "membership", None)
    actor_is_owner = (
        actor_membership is not None and actor_membership.role == TenantMembership.Role.OWNER
    )
    if not actor_is_owner and membership.role not in TenantMembership.operational_roles():
        return None, _member_not_found()

    return membership, None


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
        """Lista de miembros del tenant, acotada a la sede activa del selector.

        Usa `sucursal_scope_ids(request)` (mismo criterio que agenda/
        finanzas): con header X-Sucursal-Id, solo esa sede; sin header, el
        alcance permitido del actor (owner: sin filtro, ve a todos).

        Jerarquía de roles (decisión del dueño 2026-07-16): un viewer owner
        ve a todos, sin importar la sede activa (D1, sin cambios). Un viewer
        NO owner (administrador de sucursal) nunca ve a otros owners ni a
        otros admins — solo personal con rol operacional de sus sedes, más a
        sí mismo. `request.membership` ya lo resolvió `TenantAPIView` (una
        sola query por request, sin N+1 adicional aquí).
        """
        viewer_membership = request.membership  # type: ignore[attr-defined]
        viewer_is_owner = (
            viewer_membership is not None and viewer_membership.role == TenantMembership.Role.OWNER
        )
        qs = membership_list(
            sucursal_ids=sucursal_scope_ids(request),
            viewer_is_owner=viewer_is_owner,
            viewer_membership_id=viewer_membership.id if viewer_membership is not None else None,
        )
        return Response(MemberOutputSerializer(qs, many=True).data)

    def post(self, request: Request) -> Response:
        """Crea un miembro en el tenant del request.

        La sede del nuevo miembro se resuelve a partir de la sede activa del
        selector (`resolve_active_sucursal`); si no hay ninguna, `member_create`
        decide (todas las sedes del actor si no es owner, o ninguna si lo es
        — ver su docstring).
        """
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {"detail": "No se encontró un tenant activo para este request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        active_sucursal = resolve_active_sucursal(request)

        try:
            membership = member_create(
                tenant=tenant,
                actor=request.user,
                active_sucursal_id=active_sucursal.id if active_sucursal is not None else None,
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

    def patch(self, request: Request, membership_id: uuid.UUID) -> Response:
        """Actualiza rol y/o estado de bloqueo de un miembro."""
        membership, error = _member_get_or_404(request, membership_id)
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
        membership, error = _member_get_or_404(request, membership_id)
        if error is not None:
            return error

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

        membership = member_set_avatar(membership=membership, actor=request.user, image=image)  # type: ignore[arg-type]
        return Response(MemberOutputSerializer(membership).data)

    def delete(self, request: Request, membership_id: uuid.UUID) -> Response:
        """Elimina la foto del miembro."""
        membership, error = _member_get_or_404(request, membership_id)
        if error is not None:
            return error

        membership = member_clear_avatar(membership=membership, actor=request.user)  # type: ignore[arg-type]
        return Response(MemberOutputSerializer(membership).data)
