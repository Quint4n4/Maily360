"""
Almacenamiento thread-local del tenant del request en curso.

Uso:
    set_current_tenant(tenant)         # en el middleware / TenantAPIView, al inicio del request
    get_current_tenant()               # en managers y servicios
    clear_current_tenant()             # en el middleware, al finalizar el request (finally)
    set_tenant_context_active(True)    # en el middleware, marca "estamos en un request HTTP"
    is_tenant_context_active()         # en el manager, distingue request de Celery/migraciones
    resolve_tenant_for_user(user)      # helper reutilizable (middleware + TenantAPIView)

Distinción importante (FIX-2):
    - Fuera de request (Celery, management commands, migraciones):
      context_active=False → el TenantManager NO filtra por tenant.
    - Dentro de request (context_active=True):
      * tenant != None → filtra por ese tenant.
      * tenant is None → devuelve QuerySet vacío (falla segura: usuario autenticado sin tenant).

Arquitectura de resolución de tenant (FIX-A2):
    - Para sesión Django (admin): el TenantMiddleware llama a resolve_tenant_for_user
      con request.user (ya poblado por AuthenticationMiddleware antes del middleware).
    - Para JWT (DRF API): TenantAPIView.initial() llama a resolve_tenant_for_user
      con request.user DESPUÉS de que DRF resuelve la autenticación JWT.
    La función resolve_tenant_for_user es la única fuente de verdad para ambos caminos.
"""

import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

    from apps.tenancy.models import Tenant

_state = threading.local()


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


def resolve_tenant_for_user(user: Optional["AbstractBaseUser"]) -> Optional["Tenant"]:
    """Resuelve el tenant activo para un usuario autenticado.

    Única fuente de verdad para la resolución de tenant. Usada por:
    - TenantMiddleware (sesión Django / admin): request.user ya está poblado.
    - TenantAPIView.initial() (JWT): se llama DESPUÉS de que DRF autentica el token.

    Reglas:
    - Solo membresías is_active=True.
    - Solo tenants con status="active".
    - Excluye membresías soft-deleted (deleted_at IS NOT NULL).
    - Orden determinista por created_at para reproducibilidad.
    - Devuelve None si el usuario no está autenticado o no tiene membresía válida.

    Args:
        user: usuario de Django o None.

    Returns:
        Instancia de Tenant o None.
    """
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        return None
    if not hasattr(user, "memberships"):
        # Guardia: User puede no tener memberships si el modelo aún no está migrado
        # (primera ejecución en CI o entorno sin migraciones aplicadas).
        return None

    membership = (
        user.memberships.filter(  # type: ignore[union-attr]
            is_active=True,
            tenant__status="active",
            deleted_at__isnull=True,
        )
        .select_related("tenant")
        .order_by("created_at")
        .first()
    )
    return membership.tenant if membership is not None else None
