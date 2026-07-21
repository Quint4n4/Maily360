"""
Tests de descuentos por renglón (monto/porcentaje) y descuento GENERAL de
cotizaciones — decisión del dueño, 2026-07-21.

Contexto del bug reportado: antes, `QuoteItem.discount` era SIEMPRE un monto
fijo en $ (`line_total = quantity * unit_price - discount`). El dueño reportó
que "los descuentos no funcionan": el personal capturaba 10 esperando 10% de
descuento y el sistema restaba $10. Ahora cada renglón elige `discount_type`
('amount' | 'percent') y además existe un descuento GENERAL
(`Quote.global_discount_type` / `global_discount_value`) sobre la suma de los
renglones ya descontados.

Cubre:
  - Renglón por PORCENTAJE y por MONTO (fórmula correcta).
  - Descuento (de renglón o general) que excede la base → se recorta a 0,
    NUNCA queda negativo ni se rechaza.
  - Validación de rango: porcentaje fuera de 0-100 y monto negativo → 400.
  - Descuento GENERAL sobre la suma de renglones ya descontados.
  - Regresión: una cotización creada SIN los campos nuevos da EXACTAMENTE
    los mismos totales que el comportamiento anterior a este cambio.
  - Redondeo a 2 decimales correcto en porcentajes con decimales (33.33%).
  - El PDF de la cotización renderiza (sin mock) con descuentos mixtos.

Patrón: AAA. Todas tocan BD → fixture db.
"""

from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.finanzas.models import DiscountType
from apps.finanzas.services import quote_create
from tests.factories import (
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

QUOTES_URL = "/api/v1/finanzas/cotizaciones/"


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula TenantMiddleware para un tenant durante el request."""
    with (
        patch("apps.finanzas.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _member_client(tenant: Any, role: str) -> APIClient:
    """APIClient autenticado como miembro con rol indicado (igual que test_cotizaciones.py)."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ===========================================================================
# Renglón: descuento por PORCENTAJE o MONTO
# ===========================================================================


class TestQuoteItemDiscountFormula:
    def test_percent_discount_on_line(self, db: None) -> None:
        """percent=10 sobre base 1000 -> descuento 100, line_total 900."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[
                {
                    "description": "Servicio",
                    "quantity": "1",
                    "unit_price": "1000.00",
                    "discount_type": "percent",
                    "discount": "10",
                }
            ],
        )

        item = quote.items.get()
        assert item.discount_type == DiscountType.PERCENT
        assert item.discount_amount == Decimal("100.00")
        assert item.line_total == Decimal("900.00")

    def test_amount_discount_on_line(self, db: None) -> None:
        """amount=150 sobre base 1000 -> line_total 850."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[
                {
                    "description": "Servicio",
                    "quantity": "1",
                    "unit_price": "1000.00",
                    "discount_type": "amount",
                    "discount": "150",
                }
            ],
        )

        item = quote.items.get()
        assert item.discount_amount == Decimal("150.00")
        assert item.line_total == Decimal("850.00")

    def test_discount_exceeding_base_clips_to_zero(self, db: None) -> None:
        """Un descuento (monto) que excede la base NO se rechaza: line_total queda en 0."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[
                {
                    "description": "Servicio",
                    "quantity": "1",
                    "unit_price": "1000.00",
                    "discount_type": "amount",
                    "discount": "5000",
                }
            ],
        )

        item = quote.items.get()
        assert item.line_total == Decimal("0.00")
        assert item.discount_amount == Decimal("1000.00")  # recortado a la base, no a 5000

    def test_default_discount_type_is_amount(self, db: None) -> None:
        """Sin discount_type en el item -> se asume 'amount' (compatibilidad retro)."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[{"description": "Servicio", "unit_price": "1000.00", "discount": "100"}],
        )

        item = quote.items.get()
        assert item.discount_type == DiscountType.AMOUNT
        assert item.discount_amount == Decimal("100.00")
        assert item.line_total == Decimal("900.00")

    def test_percent_over_100_raises_validation_error(self, db: None) -> None:
        """percent fuera de 0-100 -> ValidationError (400 en la API, ver TestQuoteDiscountApi)."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError):
            quote_create(
                tenant=tenant,
                user=user,
                patient=patient,
                items=[
                    {
                        "description": "Servicio",
                        "unit_price": "1000.00",
                        "discount_type": "percent",
                        "discount": "150",
                    }
                ],
            )

    def test_negative_amount_raises_validation_error(self, db: None) -> None:
        """amount negativo -> ValidationError (400 en la API)."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError):
            quote_create(
                tenant=tenant,
                user=user,
                patient=patient,
                items=[
                    {
                        "description": "Servicio",
                        "unit_price": "1000.00",
                        "discount_type": "amount",
                        "discount": "-10",
                    }
                ],
            )


# ===========================================================================
# Descuento GENERAL de la cotización
# ===========================================================================


class TestQuoteGlobalDiscount:
    def test_global_percent_discount_on_total(self, db: None) -> None:
        """Suma de renglones ya descontados (900) + general percent=10 -> total 810."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[
                {
                    "description": "Servicio",
                    "unit_price": "1000.00",
                    "discount_type": "percent",
                    "discount": "10",
                }
            ],
            global_discount_type="percent",
            global_discount_value=Decimal("10"),
        )

        assert quote.subtotal == Decimal("1000.00")
        assert quote.total == Decimal("810.00")
        # discount_total = descuento de renglón (100) + general (90) = 190
        assert quote.discount_total == Decimal("190.00")

    def test_global_discount_exceeding_total_clips_to_zero(self, db: None) -> None:
        """Descuento general (monto) que excede la suma de renglones -> total 0."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[{"description": "Servicio", "unit_price": "500.00"}],
            global_discount_type="amount",
            global_discount_value=Decimal("5000"),
        )

        assert quote.total == Decimal("0.00")
        assert quote.discount_total == Decimal("500.00")  # recortado a la suma de renglones

    def test_global_discount_default_is_zero_amount(self, db: None) -> None:
        """Sin parámetros de descuento general -> 'amount'/0 (compatibilidad retro)."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[{"description": "Servicio", "unit_price": "500.00"}],
        )

        assert quote.global_discount_type == DiscountType.AMOUNT
        assert quote.global_discount_value == Decimal("0.00")
        assert quote.total == Decimal("500.00")


# ===========================================================================
# API: validación de rango -> 400
# ===========================================================================


class TestQuoteDiscountApi:
    """Confirma que el rango inválido, de renglón o general, responde 400 end-to-end."""

    def test_item_percent_out_of_range_returns_400(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "owner")

        payload = {
            "patient_id": str(patient.id),
            "items": [
                {
                    "description": "Servicio",
                    "unit_price": "1000.00",
                    "discount_type": "percent",
                    "discount": "150",
                }
            ],
        }
        with _tenant_context(tenant):
            resp = client.post(QUOTES_URL, data=payload, format="json")
        assert resp.status_code == 400, resp.content

    def test_item_negative_amount_returns_400(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "owner")

        payload = {
            "patient_id": str(patient.id),
            "items": [
                {
                    "description": "Servicio",
                    "unit_price": "1000.00",
                    "discount_type": "amount",
                    "discount": "-10",
                }
            ],
        }
        with _tenant_context(tenant):
            resp = client.post(QUOTES_URL, data=payload, format="json")
        assert resp.status_code == 400, resp.content

    def test_global_percent_out_of_range_returns_400(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "owner")

        payload = {
            "patient_id": str(patient.id),
            "items": [{"description": "Servicio", "unit_price": "500.00"}],
            "global_discount_type": "percent",
            "global_discount_value": "150",
        }
        with _tenant_context(tenant):
            resp = client.post(QUOTES_URL, data=payload, format="json")
        assert resp.status_code == 400, resp.content

    def test_global_negative_amount_returns_400(self, db: None) -> None:
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "owner")

        payload = {
            "patient_id": str(patient.id),
            "items": [{"description": "Servicio", "unit_price": "500.00"}],
            "global_discount_type": "amount",
            "global_discount_value": "-1",
        }
        with _tenant_context(tenant):
            resp = client.post(QUOTES_URL, data=payload, format="json")
        assert resp.status_code == 400, resp.content

    def test_valid_percent_discounts_return_201(self, db: None) -> None:
        """Camino feliz: renglón + general por porcentaje -> 201 con totales correctos."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "owner")

        payload = {
            "patient_id": str(patient.id),
            "items": [
                {
                    "description": "Servicio",
                    "quantity": "1",
                    "unit_price": "1000.00",
                    "discount_type": "percent",
                    "discount": "10",
                }
            ],
            "global_discount_type": "percent",
            "global_discount_value": "10",
        }
        with _tenant_context(tenant):
            resp = client.post(QUOTES_URL, data=payload, format="json")
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["subtotal"] == "1000.00"
        assert body["total"] == "810.00"
        assert body["discount_total"] == "190.00"
        assert body["global_discount_type"] == "percent"
        assert body["global_discount_value"] == "10.00"
        assert body["global_discount_amount"] == "90.00"
        assert body["items"][0]["discount_type"] == "percent"
        assert body["items"][0]["discount_amount"] == "100.00"


# ===========================================================================
# Regresión: cotización SIN los campos nuevos da los mismos totales que antes
# ===========================================================================


class TestQuoteDiscountRegression:
    def test_quote_without_new_fields_same_totals_as_before(self, db: None) -> None:
        """Mismo payload/aserciones que test_quote_create_computes_totals (test_services.py):
        el comportamiento documentado ANTES de introducir discount_type/descuento general
        no debe cambiar para una cotización que no usa los campos nuevos.
        """
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[
                {"description": "Consulta", "quantity": "1", "unit_price": "500", "discount": "0"},
                {"description": "Estudio", "quantity": "2", "unit_price": "250", "discount": "50"},
            ],
        )

        assert quote.subtotal == Decimal("1000.00")  # 500 + 2*250
        assert quote.discount_total == Decimal("50.00")
        assert quote.total == Decimal("950.00")
        assert quote.global_discount_type == DiscountType.AMOUNT
        assert quote.global_discount_value == Decimal("0.00")
        for item in quote.items.all():
            assert item.discount_type == DiscountType.AMOUNT
            assert item.discount_amount == item.discount


# ===========================================================================
# Redondeo a 2 decimales en porcentajes con decimales
# ===========================================================================


class TestQuoteDiscountRounding:
    def test_percent_with_decimals_rounds_correctly(self, db: None) -> None:
        """33.33% sobre 349.00 -> 349.00 * 33.33 / 100 = 116.3217 -> redondeado a 116.32."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[
                {
                    "description": "Servicio",
                    "quantity": "1",
                    "unit_price": "349.00",
                    "discount_type": "percent",
                    "discount": "33.33",
                }
            ],
        )

        item = quote.items.get()
        assert item.discount_amount == Decimal("116.32")
        assert item.line_total == Decimal("232.68")


# ===========================================================================
# PDF: renderiza (sin mock) con descuentos mixtos de renglón + general
# ===========================================================================


class TestQuotePdfWithDiscounts:
    def test_pdf_renders_with_percent_line_and_global_discount(self, db: None) -> None:
        """Renglón por porcentaje + descuento general -> el PDF real produce bytes válidos.

        Sin mock: ejerce la plantilla `finanzas/cotizacion.html` de verdad
        (discount_cell/has_line_discounts/has_global_discount/global_discount_label),
        para atrapar errores de sintaxis de template que un mock no detectaría.
        """
        from apps.finanzas.models import Quote
        from apps.finanzas.pdf import quote_pdf_build

        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[
                {
                    "description": "Consulta",
                    "unit_price": "1000.00",
                    "discount_type": "percent",
                    "discount": "10",
                },
                {
                    "description": "Estudio",
                    "unit_price": "300.00",
                    "discount_type": "amount",
                    "discount": "50",
                },
            ],
            global_discount_type="percent",
            global_discount_value=Decimal("5"),
        )
        quote = Quote.objects.select_related("patient").prefetch_related("items").get(id=quote.id)

        pdf_bytes = quote_pdf_build(quote=quote, clinic_settings=None)

        assert pdf_bytes.startswith(b"%PDF")
