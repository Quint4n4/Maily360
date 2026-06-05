"""
Fixtures locales para los tests de la app authn.

reset_tenant_context (autouse): limpia el thread-local de tenant y de contexto
HTTP entre tests para evitar contaminación cuando los tests activan el contexto
explícitamente (auditoría de login lo hace via set_request_context).

disable_throttling (autouse): desactiva los rate-limits de DRF durante los tests.
    Los tests de vistas de authn realizan múltiples peticiones al endpoint de login;
    sin este fixture, a partir del 7mo request el anon throttle devuelve 429 y los
    tests fallan con un error spurio.  En los tests de seguridad reales (OWASP) el
    throttle se prueba en tests de integración dedicados, no en tests unitarios.

api_client: Cliente DRF no autenticado.  Re-definido aquí porque pytest resuelve
conftest.py por árbol de directorios y el conftest raíz (tests/conftest.py) no
aplica cuando se corre directamente desde apps/authn/tests/.
"""

from collections.abc import Generator
from typing import Iterator

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


@pytest.fixture(autouse=True)
def disable_throttling(settings: pytest.FixtureRequest) -> Iterator[None]:  # type: ignore[type-arg]
    """Desactiva el throttling de DRF para todos los tests de authn.

    Sin esto, al correr más de 6 tests que llamen al endpoint de login en la
    misma sesión de pytest, el anon rate-limit (60/minute) devuelve 429 y los
    tests fallan por error spurio de infraestructura, no por fallo de código.

    El throttle real (60/minute) se prueba en tests de integración/carga
    separados, no en los tests unitarios del módulo.
    """
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # type: ignore[index]
    yield


@pytest.fixture
def api_client() -> APIClient:
    """Cliente DRF no autenticado."""
    return APIClient()
