"""
Fixtures locales para los tests de la app finanzas.

Re-exporta la limpieza del contexto de tenant y un api_client no autenticado,
igual que apps/pacientes/tests/conftest.py (pytest aplica conftest por árbol).
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
