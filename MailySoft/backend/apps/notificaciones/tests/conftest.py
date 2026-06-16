"""
Fixtures locales para los tests de la app notificaciones.

reset_tenant_context (autouse): limpia el thread-local de tenant entre tests.
tenant_ctx: activa el thread-local para que el TenantManager filtre (selectors/services
            que usan .objects).
api_tenant_ctx: simula el TenantMiddleware completo para tests de API con
                force_authenticate (mockea get_current_tenant en la view + manager).
Mismo patrón que apps/notas/tests/conftest.py.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.core.tenant_context import (
    clear_current_tenant,
    set_current_tenant,
    set_tenant_context_active,
)


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
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


@contextmanager
def api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Simula el efecto completo del TenantMiddleware para tests con force_authenticate."""
    with (
        patch("apps.notificaciones.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield
