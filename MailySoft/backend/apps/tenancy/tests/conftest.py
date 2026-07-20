"""
Fixtures locales para los tests de la app tenancy.

Replica el mismo patrón que apps/pacientes/tests/conftest.py:
limpieza del tenant thread-local y cliente DRF sin autenticar.
"""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

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
    - get_current_tenant en apps.clinica.sucursal_scope (multi-sede) → lo usan
      `sucursal_scope_ids`/`resolve_active_sucursal`, que las vistas de
      tenancy llaman directamente (mismo patrón que
      apps/agenda/tests/test_sucursal_scoping.py::_api_tenant_ctx).

    `fake_membership.id` se fija a un UUID concreto (no el MagicMock
    autogenerado por defecto): jerarquía de roles (2026-07-16) —
    `MemberListCreateApi.get` ahora lee `request.membership.id` para el
    criterio "el viewer siempre se ve a sí mismo" (`viewer_membership_id` en
    `apps.tenancy.selectors.membership_list`). Un `MagicMock` sin `.id`
    configurado no es un UUID válido: al pasar por `Q(id=...)`,
    `list(MagicMock())` se evalúa por defecto como `[]` (protocolo iterable
    autoconfigurado de MagicMock) y Django truena al intentar convertirlo a
    UUID. No corresponde a ninguna fila real en BD (este helper no recibe el
    `user` de la prueba) — alcanza para que el tipo sea válido; las pruebas
    que verifican "el actor se ve a sí mismo" usan el flujo con membresía
    real de BD (`apps/tenancy/tests/test_sucursal_scoping.py::_api_tenant_ctx`).
    """
    fake_membership = MagicMock()
    fake_membership.id = uuid.uuid4()
    fake_membership.role = role
    fake_membership.tenant = tenant

    with (
        patch("apps.core.views.resolve_membership_for_user", return_value=fake_membership),
        patch("apps.tenancy.views.get_current_tenant", return_value=tenant),
        patch("apps.tenancy.selectors.get_current_tenant", return_value=tenant),
        patch("apps.clinica.sucursal_scope.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield
