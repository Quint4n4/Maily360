"""
Tests para apps/core/pdf/branding.py — build_brand_context.

Cubre:
- Devuelve todas las llaves esperadas con ClinicSettings válido.
- Devuelve todas las llaves con valores por defecto seguros cuando
  clinic_settings=None (clínica sin configuración).
- Prioriza commercial_name sobre tenant.name para clinic_name.
- Usa tenant.name cuando commercial_name está vacío.
- brand_color: usa el valor del settings cuando está presente.
- brand_color: usa el default "#9A7B1E" cuando brand_color está vacío.
- brand_color: defiende silenciosamente un valor inválido (devuelve default).
- brand_color_svg: '#' escapado como '%23'.
- Clínica sin logo: logo_b64 = "", logo_w = 0, watermark_b64 = "".

Patrón: AAA. Tests unitarios puros — NO tocan BD (no se crea ningún modelo).
Se usan objetos en memoria (SimpleNamespace) para simular ClinicSettings.
"""

import types
from typing import Any

import pytest

from apps.core.pdf.branding import build_brand_context, _DEFAULT_BRAND_COLOR

# Llaves que SIEMPRE deben estar presentes en el contexto devuelto.
EXPECTED_KEYS = frozenset(
    {
        "logo_b64",
        "logo_mime",
        "logo_w",
        "logo_h",
        "clinic_name",
        "address",
        "address_2",
        "phone",
        "mobile",
        "email",
        "website",
        "brand_color",
        "brand_color_svg",
        "watermark_b64",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_settings(**kwargs: Any) -> types.SimpleNamespace:
    """Crea un objeto en memoria que simula ClinicSettings.

    Todos los campos son los defaults de ClinicSettings; los kwargs los sobreescriben.
    """
    defaults: dict[str, Any] = {
        "id": "fake-id",
        "logo": None,
        "commercial_name": "",
        "address": "",
        "address_2": "",
        "phone": "",
        "mobile": "",
        "email": "",
        "website": "",
        "brand_color": "#9A7B1E",
        "tenant": types.SimpleNamespace(name="Clínica Demo"),
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Contrato de llaves
# ---------------------------------------------------------------------------


def test_build_brand_context_returns_all_expected_keys() -> None:
    """Con ClinicSettings válido devuelve exactamente las llaves del contrato."""
    settings = _make_fake_settings()
    ctx = build_brand_context(clinic_settings=settings)

    missing = EXPECTED_KEYS - set(ctx.keys())
    assert not missing, f"Llaves faltantes en el contexto: {missing}"


def test_build_brand_context_none_returns_all_expected_keys() -> None:
    """Con clinic_settings=None (clínica sin configurar) devuelve las mismas llaves."""
    ctx = build_brand_context(clinic_settings=None)

    missing = EXPECTED_KEYS - set(ctx.keys())
    assert not missing, f"Llaves faltantes en contexto vacío: {missing}"


# ---------------------------------------------------------------------------
# clinic_name
# ---------------------------------------------------------------------------


def test_build_brand_context_commercial_name_takes_priority() -> None:
    """commercial_name tiene prioridad sobre tenant.name."""
    settings = _make_fake_settings(
        commercial_name="Clínica Comercial S.A.",
        tenant=types.SimpleNamespace(name="Tenant Legal Name"),
    )
    ctx = build_brand_context(clinic_settings=settings)

    assert ctx["clinic_name"] == "Clínica Comercial S.A."


def test_build_brand_context_falls_back_to_tenant_name() -> None:
    """Cuando commercial_name está vacío usa tenant.name."""
    settings = _make_fake_settings(
        commercial_name="",
        tenant=types.SimpleNamespace(name="Mi Clínica Tenant"),
    )
    ctx = build_brand_context(clinic_settings=settings)

    assert ctx["clinic_name"] == "Mi Clínica Tenant"


def test_build_brand_context_none_clinic_name_empty() -> None:
    """Con clinic_settings=None, clinic_name es string vacío."""
    ctx = build_brand_context(clinic_settings=None)

    assert ctx["clinic_name"] == ""


# ---------------------------------------------------------------------------
# brand_color
# ---------------------------------------------------------------------------


def test_build_brand_context_uses_brand_color_from_settings() -> None:
    """brand_color se toma del ClinicSettings cuando está presente y es válido."""
    settings = _make_fake_settings(brand_color="#1A2B3C")
    ctx = build_brand_context(clinic_settings=settings)

    assert ctx["brand_color"] == "#1A2B3C"


def test_build_brand_context_empty_brand_color_uses_default() -> None:
    """brand_color vacío ("") → usa el color por defecto."""
    settings = _make_fake_settings(brand_color="")
    ctx = build_brand_context(clinic_settings=settings)

    assert ctx["brand_color"] == _DEFAULT_BRAND_COLOR


def test_build_brand_context_invalid_brand_color_uses_default() -> None:
    """brand_color inválido (no #RRGGBB) → fallback defensivo al color por defecto."""
    settings = _make_fake_settings(brand_color="azul")
    ctx = build_brand_context(clinic_settings=settings)

    assert ctx["brand_color"] == _DEFAULT_BRAND_COLOR


def test_build_brand_context_brand_color_svg_escapes_hash() -> None:
    """brand_color_svg debe tener '%23' en lugar de '#'."""
    settings = _make_fake_settings(brand_color="#3A7BD5")
    ctx = build_brand_context(clinic_settings=settings)

    assert ctx["brand_color_svg"] == "%233A7BD5"
    assert "#" not in ctx["brand_color_svg"]


def test_build_brand_context_none_brand_color_is_default() -> None:
    """Con clinic_settings=None, brand_color es el color por defecto."""
    ctx = build_brand_context(clinic_settings=None)

    assert ctx["brand_color"] == _DEFAULT_BRAND_COLOR
    assert ctx["brand_color_svg"] == _DEFAULT_BRAND_COLOR.replace("#", "%23")


# ---------------------------------------------------------------------------
# Logo ausente
# ---------------------------------------------------------------------------


def test_build_brand_context_no_logo_returns_empty_logo_fields() -> None:
    """Cuando no hay logo, los campos logo_* y watermark_b64 son vacíos/cero."""
    settings = _make_fake_settings(logo=None)
    ctx = build_brand_context(clinic_settings=settings)

    assert ctx["logo_b64"] == ""
    assert ctx["logo_mime"] == ""
    assert ctx["logo_w"] == 0
    assert ctx["logo_h"] == 0
    assert ctx["watermark_b64"] == ""


# ---------------------------------------------------------------------------
# Campos de contacto
# ---------------------------------------------------------------------------


def test_build_brand_context_contact_fields_propagated() -> None:
    """Los campos de contacto se propagan correctamente al contexto."""
    settings = _make_fake_settings(
        address="Av. Reforma 123",
        address_2="Col. Centro",
        phone="5512345678",
        mobile="5598765432",
        email="clinica@demo.mx",
        website="https://clinica.mx",
    )
    ctx = build_brand_context(clinic_settings=settings)

    assert ctx["address"] == "Av. Reforma 123"
    assert ctx["address_2"] == "Col. Centro"
    assert ctx["phone"] == "5512345678"
    assert ctx["mobile"] == "5598765432"
    assert ctx["email"] == "clinica@demo.mx"
    assert ctx["website"] == "https://clinica.mx"
