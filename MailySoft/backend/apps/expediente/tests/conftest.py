"""
Fixtures locales para los tests de la app expediente (A1, A2, A3 y A4).

reset_tenant_context (autouse): limpia el thread-local de tenant entre tests.
tenant_ctx: activa el thread-local para que el TenantManager filtre.
api_tenant_ctx: simula el TenantMiddleware completo para tests de API.
               Parchea get_current_tenant en todas las vistas y managers
               del módulo expediente (incluyendo vistas de A4).

Mismo patrón que apps/notificaciones/tests/conftest.py.
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
    """Simula el efecto completo del TenantMiddleware para tests con force_authenticate.

    Parchea get_current_tenant en el módulo de vistas (usado por AllergyListCreateApi
    y MedicalHistoryApi para el PUT/audit_record) y en el TenantManager/managers.
    """
    with (
        # get_current_tenant se importa en CADA módulo de vistas (las vistas se
        # dividieron por recurso en views_*). Hay que parchearlo en todos para
        # que cualquier endpoint vea el tenant del test.
        patch("apps.expediente.views_alergias.get_current_tenant", return_value=tenant),
        patch("apps.expediente.views_historia.get_current_tenant", return_value=tenant),
        patch("apps.expediente.views_signos.get_current_tenant", return_value=tenant),
        patch("apps.expediente.views_evoluciones.get_current_tenant", return_value=tenant),
        patch("apps.expediente.views_imagenes.get_current_tenant", return_value=tenant),
        patch("apps.expediente.views_libro.get_current_tenant", return_value=tenant),
        patch("apps.expediente.views_preguntas.get_current_tenant", return_value=tenant),
        patch("apps.expediente.views_resumen.get_current_tenant", return_value=tenant),
        patch("apps.expediente.views_calendarizacion.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield
