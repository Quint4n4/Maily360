"""
Fixtures locales para los tests de la app tenancy.

Replica el mismo patrón que apps/pacientes/tests/conftest.py:
limpieza del tenant thread-local y cliente DRF sin autenticar.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from rest_framework.test import APIClient
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Helper: inyectar tenant + rol en TenantAPIView sin JWT real
# ---------------------------------------------------------------------------


@contextmanager
def role_context(tenant: Any, role: str) -> Generator[None, None, None]:
    """Simula el efecto completo del TenantAPIView + TenantMiddleware para un tenant y rol.

    Mockeamos:
    - resolve_membership_for_user (apps.core.views) → devuelve membership fake con role/tenant.
    - get_current_tenant en las vistas de tenancy → devuelve el tenant.
    - get_current_tenant en el TenantManager → filtra queries por tenant.
    - is_tenant_context_active → True para que el manager aplique el filtro.
    """
    fake_membership = MagicMock()
    fake_membership.role = role
    fake_membership.tenant = tenant

    with (
        patch("apps.core.views.resolve_membership_for_user", return_value=fake_membership),
        patch("apps.tenancy.views.get_current_tenant", return_value=tenant),
        patch("apps.tenancy.selectors.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield
