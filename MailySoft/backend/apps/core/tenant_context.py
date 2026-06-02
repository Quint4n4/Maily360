"""
Almacenamiento thread-local del tenant del request en curso.

Uso:
    set_current_tenant(tenant)  # en el middleware, al inicio del request
    get_current_tenant()        # en managers y servicios
    clear_current_tenant()      # en el middleware, al finalizar el request (finally)

En contextos sin request (Celery, management commands, migraciones) get_current_tenant()
devuelve None — en esos casos el TenantManager NO filtra por tenant.
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
    """Limpia el tenant del thread-local. Llamar siempre en finally."""
    if hasattr(_state, "tenant"):
        delattr(_state, "tenant")
