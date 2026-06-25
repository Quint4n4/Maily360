"""
Tests de services.py del dominio finanzas.

Cubre:
- concept_create / concept_update / concept_deactivate (unicidad, inmutables).
- quote_create + quote_accept (genera cargos por línea) + quote_send.
- charge_create / charge_cancel (validaciones de monto y de pagos aplicados).
- payment_register (parcialidades: actualiza amount_paid y status del cargo).
- cfdi_issue / cfdi_cancel con el PAC simulado (folio consecutivo, estados).
- Aislamiento de tenant: _ensure_same_tenant rechaza relaciones cross-tenant.

Patrón: AAA. Todas tocan BD → fixture db.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.finanzas.models import (
    CfdiDocument,
    Charge,
    Payment,
    PaymentAllocation,
    Quote,
)
from apps.finanzas.services import (
    cfdi_cancel,
    cfdi_issue,
    charge_cancel,
    charge_create,
    clinic_fiscal_config_update,
    concept_create,
    concept_deactivate,
    concept_update,
    payment_register,
    quote_accept,
    quote_create,
    quote_send,
)
from tests.factories import (
    ClinicFiscalConfigFactory,
    PatientFactory,
    TenantFactory,
    UserFactory,
)


# ===========================================================================
# Conceptos
# ===========================================================================


class TestConceptServices:
    def test_concept_create_persists(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        concept = concept_create(
            tenant=tenant, user=user, name="Consulta general", base_price=Decimal("450.00")
        )

        assert concept.id is not None
        assert concept.base_price == Decimal("450.00")

    def test_concept_create_duplicate_name_raises(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept_create(tenant=tenant, user=user, name="Radiografía")

        with pytest.raises(ValidationError):
            concept_create(tenant=tenant, user=user, name="Radiografía")

    def test_concept_update_immutable_field_raises(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept = concept_create(tenant=tenant, user=user, name="Terapia")

        with pytest.raises(ValidationError):
            concept_update(concept=concept, user=user, tenant_id=TenantFactory().id)

    def test_concept_deactivate_sets_inactive(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        concept = concept_create(tenant=tenant, user=user, name="Limpieza")

        concept_deactivate(concept=concept, user=user)

        assert concept.is_active is False


# ===========================================================================
# Cotizaciones
# ===========================================================================


class TestQuoteServices:
    def test_quote_create_computes_totals(self, db: None) -> None:
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

        assert quote.status == Quote.Status.DRAFT
        assert quote.subtotal == Decimal("1000.00")  # 500 + 2*250
        assert quote.discount_total == Decimal("50.00")
        assert quote.total == Decimal("950.00")
        assert quote.items.count() == 2

    def test_quote_create_requires_items(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError):
            quote_create(tenant=tenant, user=user, patient=patient, items=[])

    def test_quote_create_rejects_cross_tenant_patient(self, db: None) -> None:
        tenant = TenantFactory()
        other_patient = PatientFactory(tenant=TenantFactory())
        user = UserFactory()

        with pytest.raises(ValidationError):
            quote_create(
                tenant=tenant,
                user=user,
                patient=other_patient,
                items=[{"description": "X", "unit_price": "100"}],
            )

    def test_quote_accept_generates_charges(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        quote = quote_create(
            tenant=tenant,
            user=user,
            patient=patient,
            items=[
                {"description": "Consulta", "unit_price": "500"},
                {"description": "Estudio", "unit_price": "300"},
            ],
        )

        quote_accept(quote=quote, user=user)

        charges = Charge.all_objects.filter(quote=quote)
        assert quote.status == Quote.Status.ACCEPTED
        assert charges.count() == 2
        assert {c.amount for c in charges} == {Decimal("500.00"), Decimal("300.00")}

    def test_quote_send_only_from_draft(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        quote = quote_create(
            tenant=tenant, user=user, patient=patient,
            items=[{"description": "X", "unit_price": "100"}],
        )
        quote_send(quote=quote, user=user)
        assert quote.status == Quote.Status.SENT

        with pytest.raises(ValidationError):
            quote_send(quote=quote, user=user)


# ===========================================================================
# Cargos
# ===========================================================================


class TestChargeServices:
    def test_charge_create_persists(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        charge = charge_create(
            tenant=tenant, user=user, patient=patient,
            amount=Decimal("750.00"), description="Consulta urgente",
        )

        assert charge.status == Charge.Status.PENDING
        assert charge.balance == Decimal("750.00")

    def test_charge_create_rejects_non_positive_amount(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError):
            charge_create(
                tenant=tenant, user=user, patient=patient,
                amount=Decimal("0.00"), description="Cero",
            )

    def test_charge_cancel_rejects_if_paid(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        charge = charge_create(
            tenant=tenant, user=user, patient=patient,
            amount=Decimal("500.00"), description="Consulta",
        )
        payment_register(
            tenant=tenant, user=user, patient=patient, amount=Decimal("500.00"),
            allocations=[{"charge_id": str(charge.id), "amount": "500.00"}],
        )
        charge.refresh_from_db()

        with pytest.raises(ValidationError):
            charge_cancel(charge=charge, user=user)


# ===========================================================================
# Pagos
# ===========================================================================


class TestPaymentServices:
    def test_payment_register_full_marks_charge_paid(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        charge = charge_create(
            tenant=tenant, user=user, patient=patient,
            amount=Decimal("500.00"), description="Consulta",
        )

        payment_register(
            tenant=tenant, user=user, patient=patient, amount=Decimal("500.00"),
            allocations=[{"charge_id": str(charge.id), "amount": "500.00"}],
        )

        charge.refresh_from_db()
        assert charge.status == Charge.Status.PAID
        assert charge.amount_paid == Decimal("500.00")

    def test_payment_register_partial_marks_charge_partial(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        charge = charge_create(
            tenant=tenant, user=user, patient=patient,
            amount=Decimal("500.00"), description="Consulta",
        )

        payment_register(
            tenant=tenant, user=user, patient=patient, amount=Decimal("200.00"),
            allocations=[{"charge_id": str(charge.id), "amount": "200.00"}],
        )

        charge.refresh_from_db()
        assert charge.status == Charge.Status.PARTIAL
        assert charge.balance == Decimal("300.00")
        assert PaymentAllocation.all_objects.filter(charge=charge).count() == 1

    def test_payment_allocation_cannot_exceed_balance(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        charge = charge_create(
            tenant=tenant, user=user, patient=patient,
            amount=Decimal("100.00"), description="Consulta",
        )

        with pytest.raises(ValidationError):
            payment_register(
                tenant=tenant, user=user, patient=patient, amount=Decimal("200.00"),
                allocations=[{"charge_id": str(charge.id), "amount": "200.00"}],
            )

    def test_payment_register_rejects_non_positive(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError):
            payment_register(
                tenant=tenant, user=user, patient=patient, amount=Decimal("0.00"),
            )


# ===========================================================================
# CFDI (PAC simulado)
# ===========================================================================


class TestCfdiServices:
    def test_cfdi_issue_stamps_with_simulated_pac(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicFiscalConfigFactory(tenant=tenant)
        payment = payment_register(
            tenant=tenant, user=user, patient=patient, amount=Decimal("500.00"),
        )

        cfdi = cfdi_issue(
            tenant=tenant, user=user, payment=payment,
            receptor_rfc="XAXX010101000", receptor_name="Público en general",
        )

        assert cfdi.status == CfdiDocument.Status.STAMPED
        assert cfdi.uuid_sat != ""
        assert cfdi.pdf_url.endswith(".pdf")
        assert cfdi.folio == 1

    def test_cfdi_issue_requires_fiscal_config(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        payment = payment_register(
            tenant=tenant, user=user, patient=patient, amount=Decimal("500.00"),
        )

        with pytest.raises(ValidationError):
            cfdi_issue(
                tenant=tenant, user=user, payment=payment,
                receptor_rfc="XAXX010101000", receptor_name="X",
            )

    def test_cfdi_cancel_marks_cancelled(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicFiscalConfigFactory(tenant=tenant)
        payment = payment_register(
            tenant=tenant, user=user, patient=patient, amount=Decimal("500.00"),
        )
        cfdi = cfdi_issue(
            tenant=tenant, user=user, payment=payment,
            receptor_rfc="XAXX010101000", receptor_name="X",
        )

        cfdi_cancel(cfdi=cfdi, user=user, reason="02")

        assert cfdi.status == CfdiDocument.Status.CANCELLED
        assert cfdi.cancelled_at is not None

    def test_cfdi_folio_is_consecutive(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicFiscalConfigFactory(tenant=tenant)
        p1 = payment_register(tenant=tenant, user=user, patient=patient, amount=Decimal("100.00"))
        p2 = payment_register(tenant=tenant, user=user, patient=patient, amount=Decimal("200.00"))

        c1 = cfdi_issue(tenant=tenant, user=user, payment=p1, receptor_rfc="XAXX010101000", receptor_name="X")
        c2 = cfdi_issue(tenant=tenant, user=user, payment=p2, receptor_rfc="XAXX010101000", receptor_name="X")

        assert (c1.folio, c2.folio) == (1, 2)


# ===========================================================================
# Configuración fiscal
# ===========================================================================


class TestFiscalConfigServices:
    def test_fiscal_config_update_creates_and_sets_rfc(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        config = clinic_fiscal_config_update(
            tenant=tenant, user=user, rfc="MARP850101AB1", legal_name="Clínica X",
        )

        assert config.rfc == "MARP850101AB1"
        assert config.legal_name == "Clínica X"

    def test_fiscal_config_update_rejects_next_folio(self, db: None) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with pytest.raises(ValidationError):
            clinic_fiscal_config_update(tenant=tenant, user=user, next_folio=99)
