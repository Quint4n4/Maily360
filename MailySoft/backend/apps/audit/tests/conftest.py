"""
Fixtures locales para los tests de la app audit.

El fixture autouse reset_tenant_context limpia el thread-local de tenant
Y de contexto HTTP en cada test para evitar contaminación entre tests
que corran en el mismo hilo del worker de pytest.
"""

from collections.abc import Generator

import pytest
from rest_framework.test import APIClient

from apps.core.tenant_context import clear_current_tenant, clear_request_context


@pytest.fixture(autouse=True)
def reset_tenant_context() -> Generator[None, None, None]:
    """Limpia el contexto de tenant y de request antes y después de cada test."""
    clear_current_tenant()
    clear_request_context()
    yield
    clear_current_tenant()
    clear_request_context()


@pytest.fixture
def api_client() -> APIClient:
    """Cliente DRF no autenticado."""
    return APIClient()
