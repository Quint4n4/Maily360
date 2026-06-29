"""Caché de Redis para las lecturas pesadas de finanzas (P1 — dashboard).

Invalidación por tenant mediante VERSIÓN: cada tenant tiene un contador
`finance:ver:<tenant_id>`; las claves de caché incluyen esa versión. Al crear/
editar/borrar un Payment/Charge/Quote se incrementa la versión → todas las claves
viejas quedan inalcanzables (y expiran por TTL). No usa `delete_pattern`, así que
funciona en cualquier backend de caché. El TTL es una red de seguridad.

Seguridad multi-tenant: la clave SIEMPRE incluye el `tenant_id`, así un tenant
nunca lee el dashboard cacheado de otro.
"""

from typing import Any, Callable

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save

DASHBOARD_TTL = 300  # 5 min — red de seguridad; la invalidación por escritura es la principal


def _version_key(tenant_id: Any) -> str:
    return f"finance:ver:{tenant_id}"


def finance_cache_version(tenant_id: Any) -> int:
    """Versión de caché actual del tenant (1 si aún no existe)."""
    version = cache.get(_version_key(tenant_id))
    if version is None:
        cache.set(_version_key(tenant_id), 1, None)
        return 1
    return int(version)


def finance_cache_invalidate(tenant_id: Any) -> None:
    """Invalida TODO el caché de finanzas del tenant (incrementa su versión)."""
    if not tenant_id:
        return
    try:
        cache.incr(_version_key(tenant_id))
    except ValueError:
        # La clave no existía: inicializa en 2 (la v1 implícita queda invalidada).
        cache.set(_version_key(tenant_id), 2, None)


def finance_cache_get_or_set(
    *, tenant_id: Any, suffix: str, ttl: int, compute: Callable[[], Any]
) -> Any:
    """Devuelve el valor cacheado (clave versionada por tenant) o lo computa y guarda."""
    version = finance_cache_version(tenant_id)
    key = f"finance:{tenant_id}:v{version}:{suffix}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = compute()
    cache.set(key, result, ttl)
    return result


def _invalidate_on_change(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Receiver: invalida el caché de finanzas del tenant del objeto modificado."""
    finance_cache_invalidate(getattr(instance, "tenant_id", None))


def connect_finance_cache_signals() -> None:
    """Conecta la invalidación a los cambios de Payment/Charge/Quote.

    Se llama desde FinanzasConfig.ready(). dispatch_uid evita conexiones duplicadas.
    """
    from apps.finanzas.models import Charge, Payment, Quote

    for model in (Payment, Charge, Quote):
        post_save.connect(
            _invalidate_on_change,
            sender=model,
            dispatch_uid=f"finance_cache_save_{model.__name__}",
        )
        post_delete.connect(
            _invalidate_on_change,
            sender=model,
            dispatch_uid=f"finance_cache_del_{model.__name__}",
        )
