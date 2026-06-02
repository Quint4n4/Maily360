"""
Almacenamiento thread-local del tenant del request en curso.

Uso:
    set_current_tenant(tenant)         # en el middleware, al inicio del request
    get_current_tenant()               # en managers y servicios
    clear_current_tenant()             # en el middleware, al finalizar el request (finally)
    set_tenant_context_active(True)    # en el middleware, marca "estamos en un request HTTP"
    is_tenant_context_active()         # en el manager, distingue request de Celery/migraciones

Distinción importante (FIX-2):
    - Fuera de request (Celery, management commands, migraciones):
      context_active=False → el TenantManager NO filtra por tenant.
    - Dentro de request (context_active=True):
      * tenant != None → filtra por ese tenant.
      * tenant is None → devuelve QuerySet vacío (falla segura: usuario autenticado sin tenant).
"""

import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
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
