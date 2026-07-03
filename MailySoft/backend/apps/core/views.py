"""
Vistas base de Maily Soft.

TenantAPIView — base para TODAS las vistas de la API que requieren contexto de tenant.

Diseño (FIX-A):
    La resolución de membresía y tenant se hace en check_permissions(), NO en initial().
    Esto preserva el flujo completo de DRF en super().initial():
        - perform_authentication()  → request.user poblado con el JWT
        - perform_content_negotiation() → format_kwarg, renderers
        - determine_version()           → versioning
        - check_permissions()   ← aquí sobreescribimos (request.user ya disponible)
        - check_throttles()

    Así drf-spectacular, content negotiation y versioning funcionan sin interferencia.

    El flujo garantizado es:
        middleware.set_tenant_context_active(True)
        → middleware.set_current_tenant(None)   ← user aún es AnonymousUser aquí
        → TenantAPIView.initial() (sin override, DRF estándar):
            perform_authentication()            ← DRF autentica JWT → request.user poblado
            perform_content_negotiation()
            determine_version()
            check_permissions()  ← override nuestro:
                early-return si anónimo (sin query)
                resolve_membership_for_user(user)  ← UNA sola query
                request.membership  = membership
                request.active_role = role
                set_current_tenant(tenant)
                set_tenant_context_active(True)
                apply_tenant_guc(tenant.id) si tenant no es None
                    (set_config con is_local=False en modo "session" —
                    default— o is_local=True/SET LOCAL en modo "local";
                    ver apps/core/tenant_context.py y
                    docs/design/pgbouncer-rls-escalabilidad.md)
                super().check_permissions(request)  ← evalúa permission_classes
            check_throttles()
        → handler (get/post/patch/delete)
        → middleware.finally: clear_current_tenant() + limpiar GUC
          (en modo "local" el GUC ya desapareció solo al hacer commit/rollback
          de la transaction.atomic() que TenantMiddleware abrió alrededor de
          get_response(); la limpieza del finally es cinturón y tirantes)

Nota sobre platform staff sin membresía:
    Un usuario con is_platform_staff=True pero sin TenantMembership tendrá
    request.active_role = None y será denegado (403) en cualquier endpoint de
    clínica protegido por HasClinicRole. Esto es correcto en v1: el staff de
    plataforma opera vía el admin de Django, no vía la API de clínica.
"""

import uuid as _uuid_module

from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.core.tenant_context import (
    apply_tenant_guc,
    resolve_membership_for_user,
    set_current_tenant,
    set_request_context,
    set_tenant_context_active,
)

# ---------------------------------------------------------------------------
# Enforcement de "cambio de contraseña obligatorio" (Fase 4, plataforma).
# ---------------------------------------------------------------------------
#
# DECISIÓN DE ARQUITECTURA: el candado vive en las DOS vistas base que
# concentran TODO endpoint de negocio (TenantAPIView para clínica,
# PlatformAPIView para el panel de plataforma — ver apps/plataforma/views.py).
# Es el punto más central posible sin tocar cada vista una por una:
#   - Toda vista de clínica hereda de TenantAPIView.
#   - Toda vista de plataforma hereda de PlatformAPIView (que a su vez hereda
#     de APIView, NO de TenantAPIView — por eso el check se duplica ahí, ver
#     su propio initial()).
# Los endpoints de authn (me/, login/, refresh/, logout/, change-password/)
# heredan de APIView directo (no de TenantAPIView/PlatformAPIView) por diseño
# — así quedan exentos SIN necesidad de una whitelist explícita de rutas: el
# candado nunca se ejecuta para ellos porque no pasan por este código.
#
# Se corta en PermissionDenied (403) con un body de código estable
# ("password_change_required") para que el frontend intercepte y redirija a
# la pantalla de cambio de contraseña sin tener que parsear el mensaje humano.


class PasswordChangeRequired(PermissionDenied):
    """403 con código estable para el frontend: `must_change_password=True`."""

    default_detail = "Debes cambiar tu contraseña temporal antes de continuar."
    default_code = "password_change_required"

    def __init__(self) -> None:
        super().__init__(detail={"detail": self.default_detail, "code": self.default_code})


def enforce_password_change(request: Request) -> None:
    """Corta la request con 403 si el usuario autenticado tiene must_change_password=True.

    Se llama desde TenantAPIView.check_permissions() y desde
    PlatformAPIView.initial(), DESPUÉS de confirmar que el usuario está
    autenticado (evita tocar request.user.must_change_password sobre un
    AnonymousUser, que no tiene ese atributo).

    Raises:
        PasswordChangeRequired: si el usuario debe cambiar su contraseña.
    """
    if getattr(request.user, "must_change_password", False):
        raise PasswordChangeRequired()


class TenantAPIView(APIView):
    """Vista base DRF con resolución de tenant para peticiones JWT.

    Todas las vistas de la API que accedan a datos de tenant deben heredar
    de esta clase en lugar de APIView.

    Ver el módulo docstring arriba para el flujo completo.
    """

    def check_permissions(self, request: Request) -> None:  # type: ignore[override]
        """Resuelve la membresía del usuario y fija el contexto de tenant ANTES de
        evaluar las permission_classes de DRF.

        Se sobreescribe check_permissions (no initial) para preservar el flujo
        estándar de DRF: format negotiation, content negotiation y versioning
        se ejecutan dentro de super().initial() sin interferencia.

        Cuando super().initial() llama a check_permissions(), perform_authentication()
        ya corrió, por lo que request.user está poblado con el usuario real del JWT.

        Early-return para anónimos:
            Si el usuario no está autenticado, delegamos directamente a
            super().check_permissions() sin resolver la membresía. IsAuthenticated
            (en permission_classes) cortará el request con 401, sin tocar la BD.

        Una única query a la BD resuelve tanto el tenant (para el thread-local
        y el GUC de RLS) como el rol clínico activo (para los permisos DRF).
        """
        # Early-return para requests no autenticados: evita una query innecesaria.
        # IsAuthenticated en permission_classes devolverá 401.
        if not getattr(request.user, "is_authenticated", False):
            super().check_permissions(request)
            return

        # Candado de contraseña temporal (Fase 4): corta ANTES de resolver la
        # membresía. Un usuario con must_change_password=True no debe poder
        # operar ningún endpoint de negocio de clínica hasta que la cambie.
        enforce_password_change(request)

        # Resolver membresía para que HasClinicRole pueda leer request.active_role.
        membership = resolve_membership_for_user(request.user)

        # Adjuntar al request para acceso sin query adicional en los permisos
        # y en los handlers de la vista.
        request.membership = membership  # type: ignore[attr-defined]
        request.active_role = (  # type: ignore[attr-defined]
            membership.role if membership is not None else None
        )

        # Propagar tenant al thread-local (para el TenantManager / ORM).
        tenant = membership.tenant if membership is not None else None
        set_current_tenant(tenant)
        set_tenant_context_active(True)

        # Propagar a PostgreSQL para que la política RLS use el tenant correcto.
        # Solo cuando hay tenant: evita la query si el usuario no tiene membresía.
        # apply_tenant_guc() decide session (FIX-A1, nivel sesión/conexión) vs.
        # local (SET LOCAL, requiere la transacción abierta por TenantMiddleware
        # en modo "local") según settings.DB_TENANT_GUC_MODE — ver su docstring
        # en apps/core/tenant_context.py.
        if tenant is not None:
            apply_tenant_guc(tenant.id)

        # Poblar el contexto de request HTTP (ip/user_agent/request_id) en thread-local.
        # El helper audit_record() lo consume sin acoplar los services a HTTP.
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip: str = (
            x_forwarded.split(",")[0].strip()
            if x_forwarded
            else request.META.get("REMOTE_ADDR", "")
        )
        user_agent: str = request.META.get("HTTP_USER_AGENT", "")[:512]
        raw_request_id: str = request.META.get("HTTP_X_REQUEST_ID", "")
        request_id: str = raw_request_id if raw_request_id else _uuid_module.uuid4().hex
        set_request_context(ip=ip, user_agent=user_agent, request_id=request_id)

        # Evaluar permission_classes (IsAuthenticated + HasClinicRole, etc.).
        # En este punto request.active_role ya está disponible para HasClinicRole.
        super().check_permissions(request)
