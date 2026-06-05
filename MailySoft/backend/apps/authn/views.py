"""
Vistas de la app authn.

MeApi — GET /api/v1/me/ — perfil del usuario autenticado.
MailyTokenObtainPairView — POST /api/v1/auth/login/ — login con auditoría.

Decisión de diseño — MailyTokenObtainPairView:
    SimpleJWT NO dispara django.contrib.auth.signals.user_logged_in por defecto
    (solo lo hace si LoginView de django.contrib.auth es el flujo). Para registrar
    eventos LOGIN y LOGIN_FAILED de forma confiable con JWT, se usa un view custom
    que envuelve TokenObtainPairView:
      - Éxito (200): llama audit_record(action=LOGIN, ...) con el usuario resuelto.
      - Fallo (401): llama audit_record(action=LOGIN_FAILED, ...) sin usuario.
    La señal user_login_failed de Django también se dispara (conectada en AuditConfig.ready()),
    por lo que en LOGIN_FAILED hay doble-disparo si el backend de auth llama a authenticate().
    Para evitar duplicados, la señal registra el evento y el view custom lo omite en fallo
    (solo la señal maneja LOGIN_FAILED). El view custom solo registra LOGIN exitoso.

MeApi: hereda de APIView (NO de TenantAPIView).
    Razón: /me/ es sobre identidad del usuario, debe funcionar incluso cuando
    el usuario no tiene tenant activo. El tenant se resuelve manualmente con
    resolve_tenant_for_user(), sin depender del contexto thread-local de tenant.

Flujo MeApi:
    1. DRF valida el JWT → request.user poblado.
    2. Resolvemos tenant activo vía resolve_tenant_for_user().
    3. Consultamos las membresías activas vía user_active_memberships().
    4. Localizamos la membership activa (la que coincide con el tenant resuelto).
    5. Serializamos y devolvemos el payload completo.
"""

import logging
from typing import Any, Optional

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.authn.models import User
from apps.authn.selectors import user_active_memberships
from apps.authn.serializers import MeSerializer
from apps.core.tenant_context import resolve_membership_for_user, resolve_tenant_for_user
from apps.tenancy.models import Tenant, TenantMembership

logger = logging.getLogger("apps.authn.views")


class MailyTokenObtainPairView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — login JWT con auditoría de acceso.

    Registra:
      - LOGIN exitoso: después de que SimpleJWT devuelve 200.
      - LOGIN_FAILED: delegado a la señal user_login_failed (handle_login_failed),
        que SimpleJWT dispara internamente al llamar authenticate().

    Decisión: el view solo registra el LOGIN exitoso. El LOGIN_FAILED lo maneja
    la señal conectada en AuditConfig.ready() para evitar duplicados.
    """

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Delega a SimpleJWT y, en caso de éxito, registra el evento LOGIN."""
        response: Response = super().post(request, *args, **kwargs)

        # Solo registrar LOGIN si la autenticación fue exitosa (200 OK).
        if response.status_code == 200:
            self._audit_login_success(request)

        return response

    def _audit_login_success(self, request: Request) -> None:
        """Registra el evento LOGIN exitoso en la bitácora."""
        try:
            from apps.audit.models import ActionType
            from apps.audit.services import audit_record
            from apps.core.tenant_context import set_request_context

            # Poblar contexto HTTP para que audit_record lea ip/user_agent.
            x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            ip: str = x_forwarded.split(",")[0].strip() if x_forwarded else request.META.get("REMOTE_ADDR", "")
            user_agent: str = request.META.get("HTTP_USER_AGENT", "")[:512]
            raw_request_id: str = request.META.get("HTTP_X_REQUEST_ID", "")
            import uuid as _uuid
            request_id: str = raw_request_id if raw_request_id else _uuid.uuid4().hex
            set_request_context(ip=ip, user_agent=user_agent, request_id=request_id)

            # Resolver el usuario por su email/username SIN re-autenticar.
            # SimpleJWT ya validó las credenciales (status=200), por lo que el
            # usuario existe y está activo. Re-llamar authenticate() dispararía
            # un LOGIN_FAILED espurio si el estado cambió entre ambas llamadas y
            # duplicaría el trabajo de hashing — por eso solo lo buscamos.
            from apps.authn.models import User as _User

            username_field = _User.USERNAME_FIELD
            email_value = request.data.get(username_field, "")
            try:
                user = _User.objects.get(**{username_field: email_value})
            except _User.DoesNotExist:
                logger.warning(
                    "MailyTokenObtainPairView: status=200 pero no se halló el usuario %s.",
                    email_value,
                )
                return

            # Resolver tenant para el usuario autenticado.
            membership = resolve_membership_for_user(user)
            tenant = membership.tenant if membership is not None else None
            actor_role: str = membership.role if membership is not None else ""

            audit_record(
                action=ActionType.LOGIN,
                resource_type="User",
                actor=user,
                tenant=tenant,
                resource_id=user.pk,
                resource_repr=str(getattr(user, "email", user.pk)),
                actor_role=actor_role,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "MailyTokenObtainPairView._audit_login_success: error al auditar LOGIN — %s",
                exc,
                exc_info=True,
            )


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
