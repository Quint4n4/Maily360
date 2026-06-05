"""
Almacenamiento thread-local del tenant del request en curso.

Uso:
    set_current_tenant(tenant)            # en el middleware / TenantAPIView, al inicio del request
    get_current_tenant()                  # en managers y servicios
    clear_current_tenant()                # en el middleware, al finalizar el request (finally)
    set_tenant_context_active(True)       # en el middleware, marca "estamos en un request HTTP"
    is_tenant_context_active()            # en el manager, distingue request de Celery/migraciones
    resolve_membership_for_user(user)     # resuelve la TenantMembership activa del usuario
    resolve_tenant_for_user(user)         # helper reutilizable (middleware + TenantAPIView)

Distinción importante (FIX-2):
    - Fuera de request (Celery, management commands, migraciones):
      context_active=False → el TenantManager NO filtra por tenant.
    - Dentro de request (context_active=True):
      * tenant != None → filtra por ese tenant.
      * tenant is None → devuelve QuerySet vacío (falla segura: usuario autenticado sin tenant).

Arquitectura de resolución de tenant (FIX-A2):
    - Para sesión Django (admin): el TenantMiddleware llama a resolve_tenant_for_user
      con request.user (ya poblado por AuthenticationMiddleware antes del middleware).
    - Para JWT (DRF API): TenantAPIView.check_permissions() llama a
      resolve_membership_for_user con request.user DESPUÉS de que DRF resuelve la
      autenticación JWT.
    La función resolve_membership_for_user es la única fuente de verdad para ambos caminos.

Estados de tenant permitidos (FIX-C):
    trial     → acceso completo (modelo de negocio: 2 meses de prueba gratis).
    active    → acceso completo (suscripción activa).
    suspended → bloqueado (impago u otras razones administrativas).
"""

import logging
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

    from apps.tenancy.models import Tenant, TenantMembership

_state = threading.local()
logger = logging.getLogger(__name__)


def set_current_tenant(tenant: Optional["Tenant"]) -> None:
    """Guarda el tenant activo en el almacenamiento thread-local."""
    _state.tenant = tenant


def get_current_tenant() -> Optional["Tenant"]:
    """Devuelve el tenant activo o None si no hay contexto de request."""
    return getattr(_state, "tenant", None)


def clear_current_tenant() -> None:
    """Limpia el tenant y el flag de contexto del thread-local. Llamar siempre en finally."""
    if hasattr(_state, "tenant"):
        delattr(_state, "tenant")
    _state.context_active = False


def set_tenant_context_active(active: bool) -> None:
    """Marca si el hilo actual está procesando un request HTTP.

    True  → estamos dentro de un request (el manager debe fallar seguro si no hay tenant).
    False → fuera de request (Celery, migraciones, management commands → sin filtro de tenant).
    """
    _state.context_active = active


def is_tenant_context_active() -> bool:
    """Devuelve True solo si el hilo está procesando un request HTTP."""
    return bool(getattr(_state, "context_active", False))


def resolve_membership_for_user(
    user: Optional["AbstractBaseUser"],
) -> Optional["TenantMembership"]:
    """Resuelve la TenantMembership activa para un usuario autenticado.

    Es la fuente de verdad para obtener tanto el tenant como el rol clínico del
    usuario actual. Una sola query — el resultado puede usarse para derivar ambos:
        m = resolve_membership_for_user(user)
        tenant = m.tenant if m else None
        role   = m.role   if m else None

    Reglas de resolución:
    - Solo membresías is_active=True.
    - Solo tenants con status in ["active", "trial"] (FIX-C: trial tiene acceso
      completo durante el periodo de prueba; suspended queda bloqueado).
    - Excluye membresías soft-deleted (deleted_at IS NOT NULL).
    - Orden determinista por created_at para reproducibilidad entre múltiples clínicas.
    - Devuelve None si el usuario no está autenticado o no tiene membresía válida.

    Args:
        user: instancia del usuario de Django o None.

    Returns:
        La instancia de TenantMembership más antigua que cumple los criterios, o None.
    """
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        return None
    if not hasattr(user, "memberships"):
        # Guardia: User puede no tener memberships si el modelo aún no está migrado
        # (primera ejecución en CI o entorno sin migraciones aplicadas).
        # En producción esto indica un modelo roto o una migración faltante.
        logger.warning(
            "resolve_membership_for_user: user pk=%s no tiene el related manager "
            "'memberships'. Verifica que TenantMembership.user apunte al modelo "
            "de usuario correcto y que las migraciones estén aplicadas.",
            getattr(user, "pk", "?"),
        )
        return None

    # trial y active tienen acceso completo.
    # suspended (impago u otras razones administrativas) queda bloqueado.
    return (
        user.memberships.filter(  # type: ignore[union-attr]
            is_active=True,
            tenant__status__in=["active", "trial"],
            deleted_at__isnull=True,
        )
        .select_related("tenant")
        .order_by("created_at")
        .first()
    )


def resolve_tenant_for_user(user: Optional["AbstractBaseUser"]) -> Optional["Tenant"]:
    """Resuelve el tenant activo para un usuario autenticado.

    Delega en resolve_membership_for_user para evitar duplicar la query.

    Usada por:
    - TenantMiddleware (sesión Django / admin): request.user ya está poblado.
    - TenantAPIView.initial() (JWT): se llama DESPUÉS de que DRF autentica el token.

    Args:
        user: usuario de Django o None.

    Returns:
        Instancia de Tenant o None.
    """
    membership = resolve_membership_for_user(user)
    return membership.tenant if membership is not None else None
