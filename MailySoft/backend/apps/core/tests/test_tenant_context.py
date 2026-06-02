"""
Tests para apps/core/tenant_context.py

Cubre: set_current_tenant, get_current_tenant, clear_current_tenant,
y el aislamiento entre hilos (regla crítica de thread-safety).
"""

import threading
from typing import Optional

import pytest

from apps.core.tenant_context import (
    clear_current_tenant,
    get_current_tenant,
    set_current_tenant,
)
from tests.factories import TenantFactory


# ---------------------------------------------------------------------------
# Comportamiento básico (sin BD: el thread-local no necesita DB)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_current_tenant_returns_none_by_default() -> None:
    """Arrange: thread-local limpio (fixture autouse lo garantiza).
    Act: llamar get_current_tenant sin haber seteado nada.
    Assert: debe devolver None.
    """
    # Arrange — el fixture autouse reset_tenant_context ya limpió el estado.

    # Act
    result = get_current_tenant()

    # Assert
    assert result is None


@pytest.mark.django_db
def test_set_and_get_current_tenant() -> None:
    """Arrange: crear un tenant real.
    Act: guardar en thread-local y recuperarlo.
    Assert: el objeto devuelto es exactamente el mismo tenant.
    """
    # Arrange
    tenant = TenantFactory()

    # Act
    set_current_tenant(tenant)
    result = get_current_tenant()

    # Assert
    assert result is tenant
    assert result.id == tenant.id


@pytest.mark.django_db
def test_clear_current_tenant() -> None:
    """Arrange: tenant en thread-local.
    Act: clear_current_tenant().
    Assert: get_current_tenant() devuelve None después de limpiar.
    """
    # Arrange
    tenant = TenantFactory()
    set_current_tenant(tenant)
    assert get_current_tenant() is not None  # precondición

    # Act
    clear_current_tenant()

    # Assert
    assert get_current_tenant() is None


def test_clear_current_tenant_is_idempotent() -> None:
    """clear_current_tenant() no debe lanzar si el thread-local ya está limpio."""
    # Arrange — ya limpio por autouse

    # Act + Assert (no debe lanzar)
    clear_current_tenant()
    clear_current_tenant()
    assert get_current_tenant() is None


@pytest.mark.django_db
def test_set_current_tenant_accepts_none() -> None:
    """set_current_tenant(None) debe ser válido (modo admin/migraciones)."""
    # Arrange
    tenant = TenantFactory()
    set_current_tenant(tenant)

    # Act
    set_current_tenant(None)

    # Assert
    assert get_current_tenant() is None


@pytest.mark.django_db
def test_thread_isolation() -> None:
    """Dos hilos deben mantener tenants distintos al mismo tiempo.

    Este test es CLAVE: verifica que el almacenamiento sea thread-local
    real y no una variable global que contaminaría peticiones concurrentes.
    """
    # Arrange
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()

    results: dict[str, Optional[object]] = {}
    errors: list[Exception] = []

    barrier = threading.Barrier(2)  # sincroniza los dos hilos en el punto crítico

    def hilo_a() -> None:
        try:
            set_current_tenant(tenant_a)
            barrier.wait()  # espera hasta que hilo_b también haya seteado su tenant
            results["a"] = get_current_tenant()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def hilo_b() -> None:
        try:
            set_current_tenant(tenant_b)
            barrier.wait()  # espera hasta que hilo_a también haya seteado su tenant
            results["b"] = get_current_tenant()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    # Act
    t_a = threading.Thread(target=hilo_a)
    t_b = threading.Thread(target=hilo_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=5)
    t_b.join(timeout=5)

    # Assert
    assert not errors, f"Los hilos lanzaron excepciones: {errors}"
    assert results["a"] is tenant_a, "Hilo A debería ver solo su propio tenant"
    assert results["b"] is tenant_b, "Hilo B debería ver solo su propio tenant"
    assert results["a"] is not results["b"], "Los hilos NO deben compartir el mismo tenant"
