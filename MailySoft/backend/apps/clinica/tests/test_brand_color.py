"""
Tests para el campo brand_color en ClinicSettings — Fase 1 PDF unificado.

Cubre:
- Modelo: default "#9A7B1E" en nuevas instancias.
- Modelo: validate_hex_color acepta formatos válidos.
- Modelo: validate_hex_color rechaza formatos inválidos.
- Service clinic_settings_upsert: persiste brand_color correctamente.
- API GET configuracion/: brand_color aparece en la respuesta.
- API PUT configuracion/: owner/admin pueden escribir brand_color válido.
- API PUT configuracion/: brand_color inválido → 400.

Patrón: AAA. Tests de modelo sin BD son unitarios; tests de API usan db.
"""

from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.clinica.models import ClinicSettings, validate_hex_color
from apps.clinica.services import clinic_settings_upsert
from tests.factories import (
    ClinicSettingsFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

SETTINGS_URL = "/api/v1/clinica/configuracion/"


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Inyecta tenant en el middleware y TenantManager para tests con force_authenticate."""
    with (
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


# ---------------------------------------------------------------------------
# Tests unitarios de validate_hex_color (sin BD)
# ---------------------------------------------------------------------------


def test_validate_hex_color_accepts_valid_color() -> None:
    """Colores #RRGGBB válidos no lanzan excepción."""
    for color in ("#9A7B1E", "#FFFFFF", "#000000", "#3a7bd5", "#ABC123"):
        validate_hex_color(color)  # No debe lanzar


def test_validate_hex_color_accepts_empty_string() -> None:
    """String vacío se acepta (el campo permite blank=True para uso parcial)."""
    validate_hex_color("")  # No debe lanzar


def test_validate_hex_color_rejects_without_hash() -> None:
    """Sin '#' inicial → ValidationError."""
    with pytest.raises(DjangoValidationError):
        validate_hex_color("9A7B1E")


def test_validate_hex_color_rejects_short_hex() -> None:
    """Color corto #RGB (3 dígitos) → ValidationError."""
    with pytest.raises(DjangoValidationError):
        validate_hex_color("#FFF")


def test_validate_hex_color_rejects_invalid_chars() -> None:
    """Caracteres no hexadecimales → ValidationError."""
    with pytest.raises(DjangoValidationError):
        validate_hex_color("#ZZZZZZ")


def test_validate_hex_color_rejects_plain_text() -> None:
    """Texto plano como "azul" → ValidationError."""
    with pytest.raises(DjangoValidationError):
        validate_hex_color("azul")


def test_validate_hex_color_rejects_eight_digit_hex() -> None:
    """Color de 8 dígitos (#RRGGBBAA) → ValidationError (solo #RRGGBB)."""
    with pytest.raises(DjangoValidationError):
        validate_hex_color("#9A7B1EFF")


# ---------------------------------------------------------------------------
# Tests de modelo (con BD) — default y persistencia
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinic_settings_brand_color_default() -> None:
    """brand_color tiene el valor por defecto '#9A7B1E' en instancias nuevas."""
    settings = ClinicSettingsFactory()

    # Recarga desde BD para confirmar que el default se persistió.
    db_settings = ClinicSettings.objects.get(pk=settings.pk)
    assert db_settings.brand_color == "#9A7B1E"


@pytest.mark.django_db
def test_clinic_settings_brand_color_persists_custom_color() -> None:
    """Un color válido distinto al default se guarda correctamente."""
    settings = ClinicSettingsFactory(brand_color="#3A7BD5")

    db_settings = ClinicSettings.objects.get(pk=settings.pk)
    assert db_settings.brand_color == "#3A7BD5"


# ---------------------------------------------------------------------------
# Tests de servicio
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_service_upsert_sets_brand_color() -> None:
    """clinic_settings_upsert persiste brand_color cuando se pasa explícitamente."""
    tenant = TenantFactory()
    user = UserFactory()

    settings = clinic_settings_upsert(
        tenant=tenant,
        user=user,
        brand_color="#1A2B3C",
    )

    assert settings.brand_color == "#1A2B3C"
    db = ClinicSettings.objects.get(pk=settings.pk)
    assert db.brand_color == "#1A2B3C"


@pytest.mark.django_db
def test_service_upsert_updates_brand_color() -> None:
    """clinic_settings_upsert actualiza brand_color en un settings existente."""
    tenant = TenantFactory()
    user = UserFactory()
    ClinicSettingsFactory(tenant=tenant, brand_color="#9A7B1E")

    settings = clinic_settings_upsert(
        tenant=tenant,
        user=user,
        brand_color="#FF5733",
        _partial_fields=frozenset({"brand_color"}),
    )

    assert settings.brand_color == "#FF5733"


# ---------------------------------------------------------------------------
# Tests de API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_get_settings_includes_brand_color(api_client: Any) -> None:
    """GET configuracion/ incluye brand_color en la respuesta."""
    from rest_framework.test import APIClient

    client = APIClient()
    tenant = TenantFactory()
    user = UserFactory()
    membership = TenantMembershipFactory(
        tenant=tenant,
        user=user,
        role="owner",
    )
    ClinicSettingsFactory(tenant=tenant, brand_color="#3A7BD5")

    client.force_authenticate(user=user)
    with _tenant_context(tenant):
        response = client.get(SETTINGS_URL)

    assert response.status_code == 200
    assert "brand_color" in response.data
    assert response.data["brand_color"] == "#3A7BD5"


@pytest.mark.django_db
def test_api_put_settings_owner_can_set_brand_color(api_client: Any) -> None:
    """PUT configuracion/ como owner persiste un brand_color válido."""
    from rest_framework.test import APIClient

    client = APIClient()
    tenant = TenantFactory()
    user = UserFactory()
    TenantMembershipFactory(tenant=tenant, user=user, role="owner")
    ClinicSettingsFactory(tenant=tenant)

    client.force_authenticate(user=user)
    with _tenant_context(tenant):
        response = client.put(
            SETTINGS_URL,
            data={"brand_color": "#1A2B3C"},
            format="json",
        )

    assert response.status_code == 200
    assert response.data["brand_color"] == "#1A2B3C"


@pytest.mark.django_db
def test_api_put_settings_invalid_brand_color_returns_400(api_client: Any) -> None:
    """PUT configuracion/ con brand_color inválido devuelve 400."""
    from rest_framework.test import APIClient

    client = APIClient()
    tenant = TenantFactory()
    user = UserFactory()
    TenantMembershipFactory(tenant=tenant, user=user, role="owner")
    ClinicSettingsFactory(tenant=tenant)

    client.force_authenticate(user=user)
    with _tenant_context(tenant):
        response = client.put(
            SETTINGS_URL,
            data={"brand_color": "azul"},
            format="json",
        )

    assert response.status_code == 400
    assert "brand_color" in response.data


@pytest.mark.django_db
def test_api_put_settings_doctor_cannot_set_brand_color(api_client: Any) -> None:
    """PUT configuracion/ como doctor devuelve 403 (solo owner/admin pueden escribir config)."""
    from rest_framework.test import APIClient

    client = APIClient()
    tenant = TenantFactory()
    user = UserFactory()
    TenantMembershipFactory(tenant=tenant, user=user, role="doctor")
    ClinicSettingsFactory(tenant=tenant)

    client.force_authenticate(user=user)
    with _tenant_context(tenant):
        response = client.put(
            SETTINGS_URL,
            data={"brand_color": "#1A2B3C"},
            format="json",
        )

    assert response.status_code == 403
