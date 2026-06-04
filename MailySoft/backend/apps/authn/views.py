"""
Vistas de la app authn.

MeApi — GET /api/v1/me/ — perfil del usuario autenticado.

Decisión de diseño: hereda de APIView (NO de TenantAPIView).
Razón: /me/ es sobre identidad del usuario, debe funcionar incluso cuando
el usuario no tiene tenant activo (staff de plataforma sin membership,
usuarios recién creados, etc.). El tenant se resuelve manualmente con
resolve_tenant_for_user(), sin depender del contexto thread-local de tenant.

Flujo:
    1. DRF valida el JWT → request.user poblado.
    2. Resolvemos tenant activo vía resolve_tenant_for_user().
    3. Consultamos las membresías activas vía user_active_memberships().
    4. Localizamos la membership activa (la que coincide con el tenant resuelto).
    5. Serializamos y devolvemos el payload completo.
"""

from typing import Optional

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.models import User
from apps.authn.selectors import user_active_memberships
from apps.authn.serializers import MeSerializer
from apps.core.tenant_context import resolve_tenant_for_user
from apps.tenancy.models import Tenant, TenantMembership


class MeApi(APIView):
    """GET /api/v1/me/ — retorna el perfil completo del usuario autenticado.

    Incluye: datos personales, flags de plataforma, tenant activo, rol activo
    y lista de todas las membresías activas (para soportar multi-clínica).

    Responde 200 siempre que el token sea válido, incluso si el usuario no
    tiene tenant activo (active_tenant y active_role serán null en ese caso).
    Responde 401 si el token es inválido o está ausente.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Retorna el perfil del usuario autenticado."""
        user: User = request.user  # type: ignore[assignment]

        # 1. Resolver el tenant activo del usuario.
        # resolve_tenant_for_user consulta directamente la BD sin depender del
        # thread-local, lo que hace este endpoint seguro fuera de TenantAPIView.
        active_tenant: Optional[Tenant] = resolve_tenant_for_user(user)

        # 2. Obtener todas las membresías activas del usuario (con select_related).
        memberships_qs = user_active_memberships(user=user)
        memberships: list[TenantMembership] = list(memberships_qs)

        # 3. Localizar la membership que corresponde al tenant activo.
        # Esto evita una segunda query: reutiliza el queryset ya evaluado.
        active_membership: Optional[TenantMembership] = None
        if active_tenant is not None:
            for m in memberships:
                if m.tenant_id == active_tenant.id:
                    active_membership = m
                    break

        # 4. Serializar y devolver.
        serializer = MeSerializer(
            user,
            context={
                "active_tenant": active_tenant,
                "active_membership": active_membership,
                "memberships": memberships,
            },
        )
        return Response(serializer.data)
