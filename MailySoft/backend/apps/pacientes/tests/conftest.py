"""
Fixtures locales para los tests de la app pacientes.

La raíz tests/conftest.py define fixtures compartidas para el directorio tests/.
Como pytest aplica conftest.py por árbol de directorios, re-exportamos aquí los
fixtures que las APIs necesitan (api_client, auth_client) y la limpieza de tenant.

El fixture autouse reset_tenant_context ya está en tests/conftest.py pero, al
correr desde apps/pacientes/tests/, ese conftest no aplica. Lo redefinimos aquí
para garantizar la limpieza del thread-local en todos los tests de este módulo.
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
