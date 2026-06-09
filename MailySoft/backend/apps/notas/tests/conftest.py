"""
Fixtures locales para los tests de la app notas.

reset_tenant_context (autouse): limpia el thread-local de tenant entre tests.
Mismo patrón que apps/agenda/tests/conftest.py.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.core.tenant_context import clear_current_tenant, set_current_tenant, set_tenant_context_active


@pytest.fixture(autouse=True)
def reset_tenant_context() -> Generator[None, None, None]:
    """Limpia el contexto de tenant antes y después de cada test."""
    clear_current_tenant()
    yield
    clear_current_tenant()


@pytest.fixture
def api_client() -> APIClient:
    """Cliente DRF no autenticado."""
    return APIClient()


@contextmanager
def tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Activa el thread-local de tenant para que el TenantManager filtre."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


@contextmanager
def api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Simula el efecto completo del TenantMiddleware para tests con force_authenticate.

    Mockea get_current_tenant en el módulo de la vista de notas y en el
    TenantManager para inyectar el tenant directamente, igual que los tests
    existentes de agenda.
    """
    with (
        patch("apps.notas.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield
