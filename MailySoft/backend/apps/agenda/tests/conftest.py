"""
Fixtures locales para los tests de la app agenda.

reset_tenant_context (autouse): limpia el thread-local de tenant entre tests
para evitar contaminación cuando los tests activan el contexto explícitamente
(tests de selectors y services).
"""

from collections.abc import Generator

import pytest
from rest_framework.test import APIClient

from apps.core.tenant_context import clear_current_tenant


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
