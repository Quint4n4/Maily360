"""
Configuración global de pytest para Maily Soft backend.

Fixtures compartidas entre todos los tests del proyecto.
Fixtures específicas de un dominio van en apps/<dominio>/tests/conftest.py.
"""

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest
from rest_framework.test import APIClient

from apps.core.tenant_context import clear_current_tenant
from tests.factories import PlatformStaffFactory, TenantFactory, TenantMembershipFactory, UserFactory

if TYPE_CHECKING:
    from apps.authn.models import User
    from apps.tenancy.models import Tenant, TenantMembership


# ---------------------------------------------------------------------------
# Limpieza del contexto de tenant (autouse — se aplica a TODOS los tests)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_tenant_context() -> Generator[None, None, None]:
    """Garantiza que cada test arranca con el thread-local limpio.

    Sin esto, un test que llame set_current_tenant() contaminaría los
    tests siguientes que corran en el mismo hilo del worker.
    """
    clear_current_tenant()
    yield
    clear_current_tenant()


# ---------------------------------------------------------------------------
# Actores
# ---------------------------------------------------------------------------


@pytest.fixture
def user(db: None) -> "User":
    """Usuario normal sin privilegios especiales."""
    return UserFactory()


@pytest.fixture
def platform_staff(db: None) -> "User":
    """Usuario del equipo interno de Maily Soft."""
    return PlatformStaffFactory()


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant(db: None) -> "Tenant":
    """Clínica activa."""
    return TenantFactory()


@pytest.fixture
def tenant_b(db: None) -> "Tenant":
    """Segunda clínica — útil para tests de aislamiento cross-tenant."""
    return TenantFactory()


# ---------------------------------------------------------------------------
# Membresía
# ---------------------------------------------------------------------------


@pytest.fixture
def membership(db: None, user: "User", tenant: "Tenant") -> "TenantMembership":
    """Membresía owner del user en el tenant principal."""
    return TenantMembershipFactory(user=user, tenant=tenant, role="owner")


# ---------------------------------------------------------------------------
# Clientes HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client() -> APIClient:
    """Cliente DRF no autenticado."""
    return APIClient()


@pytest.fixture
def auth_client(api_client: APIClient, user: "User") -> APIClient:
    """Cliente DRF autenticado como el user fixture (sin membresía)."""
    api_client.force_authenticate(user=user)
    return api_client
