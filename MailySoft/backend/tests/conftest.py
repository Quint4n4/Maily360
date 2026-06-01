"""
Configuración global de pytest para Maily Soft backend.

Fixtures compartidas entre todos los tests del proyecto.
Fixtures específicas de un dominio van en apps/<dominio>/tests/conftest.py.
"""

import pytest
from django.test import Client


@pytest.fixture
def api_client() -> Client:
    """Cliente HTTP para tests de API (sin autenticar)."""
    from rest_framework.test import APIClient

    return APIClient()  # type: ignore[return-value]


@pytest.fixture
def authenticated_client(api_client: Client) -> Client:
    """
    Cliente autenticado.

    TODO (Paso 2): Crear UserFactory y autenticar con JWT real.
    Por ahora devuelve el cliente sin autenticar; actualizar cuando
    el modelo User esté listo.
    """
    return api_client
