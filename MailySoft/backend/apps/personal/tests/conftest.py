"""
Fixtures locales para los tests de la app personal.

El fixture autouse reset_tenant_context garantiza limpieza del thread-local
entre tests cuando se activa el contexto de tenant explícitamente.
"""

from collections.abc import Generator

import pytest
from rest_framework.test import APIClient

from apps.core.tenant_context import clear_current_tenant


@pytest.fixture(autouse=True)
def reset_tenant_context() -> Generator[None, None, None]:
    """Limpia el contexto de tenant antes y después de cada test.

    Evita que un test contamine el siguiente cuando corren en el mismo hilo.
    """
    clear_current_tenant()
    yield
    clear_current_tenant()


@pytest.fixture
def api_client() -> APIClient:
    """Cliente DRF no autenticado."""
    return APIClient()
