"""
Serializers de la app authn.

Regla: serializers solo dan forma a la salida (lectura). Cero lógica de negocio.

Jerarquía de serializers para /me/:
    _TenantBriefSerializer   — forma compacta de un Tenant (id, name, slug, status).
    _MembershipSerializer    — una membresía del user (tenant + role + is_active).
    MeSerializer             — payload completo del endpoint /me/.
"""

from typing import Optional

from rest_framework import serializers

from apps.authn.models import User
from apps.tenancy.models import Tenant, TenantMembership


class _TenantBriefSerializer(serializers.ModelSerializer):
    """Representación compacta de un Tenant para incrustar en /me/.

    Solo expone los campos que el frontend necesita para identificar la clínica
    y decidir redirecciones: id, name, slug, status.
    No expone trial_ends_at, timezone ni campos de auditoría.
    """

    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "status"]
        read_only_fields = fields


class _MembershipSerializer(serializers.ModelSerializer):
    """Serializer de una TenantMembership para la lista de membresías del usuario.

    Incluye:
    - tenant: representación compacta via _TenantBriefSerializer.
    - role: valor del choice (clave de texto).
    - role_display: etiqueta legible del rol en español.
    - is_active: si la membresía está activa.
    """

    tenant = _TenantBriefSerializer(read_only=True)
    role_display = serializers.SerializerMethodField()

    class Meta:
        model = TenantMembership
        fields = ["tenant", "role", "role_display", "is_active"]
        read_only_fields = fields

    def get_role_display(self, obj: TenantMembership) -> str:
        """Devuelve la etiqueta legible del rol (p. ej. 'Recepción')."""
        return TenantMembership.Role(obj.role).label


class MeSerializer(serializers.Serializer):
    """Serializer de salida del endpoint GET /api/v1/me/.

    Contrato de respuesta completo:
    - Datos del usuario autenticado.
    - Tenant activo (resuelto por resolve_tenant_for_user); null si no hay tenant.
    - Rol activo en el tenant; null si no hay tenant activo.
    - Lista de todas las membresías activas (para soportar usuarios multi-clínica).

    Este serializer NO es un ModelSerializer: el payload mezcla User,
    TenantMembership y datos calculados, por lo que es más claro y explícito
    construirlo como Serializer plano con campos SerializerMethodField.
    """

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    avatar = serializers.ImageField(read_only=True)
    is_platform_staff = serializers.BooleanField(read_only=True)
    platform_role = serializers.CharField(read_only=True)

    # Tenant activo: puede ser null para platform staff sin membership
    active_tenant = serializers.SerializerMethodField()
    # Rol en el tenant activo: null si no hay tenant activo
    active_role = serializers.SerializerMethodField()
    active_role_display = serializers.SerializerMethodField()
    # Todas las membresías activas del usuario
    memberships = serializers.SerializerMethodField()

    def get_active_tenant(self, obj: User) -> Optional[dict]:
        """Retorna la representación del tenant activo o null."""
        tenant: Optional[Tenant] = self.context.get("active_tenant")
        if tenant is None:
            return None
        return _TenantBriefSerializer(tenant).data  # type: ignore[return-value]

    def get_active_role(self, obj: User) -> Optional[str]:
        """Retorna el rol del usuario en el tenant activo o null."""
        active_membership: Optional[TenantMembership] = self.context.get("active_membership")
        if active_membership is None:
            return None
        return active_membership.role

    def get_active_role_display(self, obj: User) -> Optional[str]:
        """Retorna la etiqueta legible del rol activo o null."""
        active_membership: Optional[TenantMembership] = self.context.get("active_membership")
        if active_membership is None:
            return None
        return TenantMembership.Role(active_membership.role).label

    def get_memberships(self, obj: User) -> list:
        """Retorna la lista serializada de todas las membresías activas del usuario."""
        memberships: list[TenantMembership] = self.context.get("memberships", [])
        return _MembershipSerializer(memberships, many=True).data  # type: ignore[return-value]
