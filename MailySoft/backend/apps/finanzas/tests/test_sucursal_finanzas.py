"""
Tests de Fase 3 — Finanzas por sucursal (cuenta compartida / caja privada).

Cubre:
1. Backfill (finanzas/migrations/0008): Charge/Quote/Payment heredan la
   sucursal de su cita relacionada (directa o vía allocations/Appointment.quote);
   si no hay, caen a la "Sucursal Principal" del tenant. Idempotente.
2. Services: charge_create/payment_register/quote_create guardan la sucursal
   DONDE SE GENERÓ; quote_accept genera cargos que heredan quote.sucursal;
   validación de aislamiento (sucursal de otro tenant → ValidationError).
3. ESTADO DE CUENTA DEL PACIENTE = COMPARTIDO: un paciente con un cargo en la
   Sucursal A y otro en la B muestra AMBOS al consultarlo (caso
   "Acapulco→CDMX"), con la columna `sucursal` informativa por movimiento.
4. REPORTES/CAJA DE LA SEDE = PRIVADOS: dashboard, reporte de periodo, cierre
   diario, retención/RFM y el listado GENERAL de cargos/pagos se acotan al
   alcance de sucursales del usuario — un rol acotado a Centro NO ve datos de
   Norte, ni siquiera omitiendo el header. El dueño ve consolidado sin sede
   activa, o por sede con el header.
5. Aislamiento cross-tenant intacto (vía TenantManager, sin cambios aquí;
   verificado con un check ligero).

Patrón: AAA + factory_boy. HTTP: mismo patrón de 3 parches que
apps/agenda/tests/test_sucursal_scoping.py (vistas de finanzas +
apps.clinica.sucursal_scope + apps.core.managers).
"""

import datetime
import importlib
from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from django.apps import apps as real_apps
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.finanzas.models import CfdiDocument, Charge, Quote
from apps.finanzas.services import (
    cfdi_cancel,
    cfdi_issue,
    charge_create,
    payment_register,
    quote_accept,
    quote_create,
)
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AppointmentFactory,
    CfdiDocumentFactory,
    ChargeFactory,
    ClinicFiscalConfigFactory,
    ConsultorioFactory,
    DoctorFactory,
    MembershipSucursalFactory,
    PatientFactory,
    PaymentFactory,
    QuoteFactory,
    QuoteItemFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

ZERO = Decimal("0.00")

DASHBOARD_URL = "/api/v1/finanzas/dashboard/"
REPORT_URL = "/api/v1/finanzas/reporte/"
DAILY_URL = "/api/v1/finanzas/cierre-diario/"
RETENTION_URL = "/api/v1/finanzas/retencion/"
CHARGES_URL = "/api/v1/finanzas/cargos/"
PAYMENTS_URL = "/api/v1/finanzas/pagos/"
CFDI_URL = "/api/v1/finanzas/cfdi/"


def _statement_url(patient_id: Any) -> str:
    return f"/api/v1/finanzas/estado-cuenta/{patient_id}/"


def _charge_url(charge_id: Any) -> str:
    return f"/api/v1/finanzas/cargos/{charge_id}/"


def _payment_url(payment_id: Any) -> str:
    return f"/api/v1/finanzas/pagos/{payment_id}/"


def _quote_url(quote_id: Any) -> str:
    return f"/api/v1/finanzas/cotizaciones/{quote_id}/"


def _quote_send_url(quote_id: Any) -> str:
    return f"/api/v1/finanzas/cotizaciones/{quote_id}/enviar/"


def _quote_accept_url(quote_id: Any) -> str:
    return f"/api/v1/finanzas/cotizaciones/{quote_id}/aceptar/"


def _quote_pdf_url(quote_id: Any) -> str:
    return f"/api/v1/finanzas/cotizaciones/{quote_id}/pdf/"


def _cfdi_url(cfdi_id: Any) -> str:
    return f"/api/v1/finanzas/cfdi/{cfdi_id}/"


def _cfdi_cancel_url(cfdi_id: Any) -> str:
    return f"/api/v1/finanzas/cfdi/{cfdi_id}/cancelar/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Activa el contexto de tenant para llamar services/selectors directo."""
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


@contextmanager
def _api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Inyecta el tenant para requests HTTP reales (mismo patrón que agenda).

    Parchea get_current_tenant en apps.finanzas.views, apps.clinica.sucursal_scope
    (de donde sucursal_scope_ids/resolve_active_sucursal lo leen) y apps.core.managers.
    """
    with (
        patch("apps.finanzas.views.get_current_tenant", return_value=tenant),
        patch("apps.clinica.sucursal_scope.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _member(tenant: Any, role: str) -> Any:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _member_scoped_to(tenant: Any, role: str, sucursal: Any) -> Any:
    """Crea un usuario con `role` acotado a UNA sola sucursal vía MembershipSucursal."""
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=sucursal)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _dt(date: datetime.date) -> datetime.datetime:
    return datetime.datetime(date.year, date.month, date.day, 12, 0, 0, tzinfo=datetime.UTC)


def _D(value: Any) -> Decimal:
    """Convierte un monto JSON (string o número, según COERCE_DECIMAL_TO_STRING) a Decimal."""
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# 1. Backfill — finanzas/migrations/0008
# ---------------------------------------------------------------------------


def _load_backfill() -> Any:
    module = importlib.import_module(
        "apps.finanzas.migrations.0008_backfill_charge_payment_quote_sucursal"
    )
    return module.backfill_finanzas_sucursal


def _load_cfdi_backfill() -> Any:
    module = importlib.import_module("apps.finanzas.migrations.0010_backfill_cfdidocument_sucursal")
    return module.backfill_cfdi_sucursal


class TestBackfillChargePaymentQuoteSucursal:
    def test_charge_hereda_de_su_cita(self, db: Any) -> None:
        tenant = TenantFactory()
        principal = SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        appt = AppointmentFactory(tenant=tenant, consultorio=consultorio_norte, sucursal=norte)
        charge = ChargeFactory(tenant=tenant, appointment=appt, sucursal=None)

        backfill = _load_backfill()
        backfill(real_apps, None)

        charge.refresh_from_db()
        assert charge.sucursal_id == norte.id
        assert principal.id != norte.id  # sanity: no cayó al fallback por error

    def test_charge_sin_cita_cae_a_principal(self, db: Any) -> None:
        tenant = TenantFactory()
        principal = SucursalFactory(tenant=tenant, is_default=True)
        charge = ChargeFactory(tenant=tenant, appointment=None, sucursal=None)

        backfill = _load_backfill()
        backfill(real_apps, None)

        charge.refresh_from_db()
        assert charge.sucursal_id == principal.id

    def test_quote_hereda_de_cita_ligada(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        quote = QuoteFactory(tenant=tenant, sucursal=None)
        AppointmentFactory(
            tenant=tenant, consultorio=consultorio_norte, sucursal=norte, quote=quote
        )

        backfill = _load_backfill()
        backfill(real_apps, None)

        quote.refresh_from_db()
        assert quote.sucursal_id == norte.id

    def test_quote_sin_cita_cae_a_principal(self, db: Any) -> None:
        tenant = TenantFactory()
        principal = SucursalFactory(tenant=tenant, is_default=True)
        quote = QuoteFactory(tenant=tenant, sucursal=None)

        backfill = _load_backfill()
        backfill(real_apps, None)

        quote.refresh_from_db()
        assert quote.sucursal_id == principal.id

    def test_payment_hereda_del_charge_que_liquida(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        charge = ChargeFactory(
            tenant=tenant, patient=patient, sucursal=norte, amount=Decimal("300.00")
        )
        payment = PaymentFactory(
            tenant=tenant, patient=patient, sucursal=None, amount=Decimal("300.00")
        )
        with _tenant_ctx(tenant):
            from apps.finanzas.models import PaymentAllocation

            PaymentAllocation.objects.create(
                tenant=tenant, payment=payment, charge=charge, amount=Decimal("300.00")
            )

        backfill = _load_backfill()
        backfill(real_apps, None)

        payment.refresh_from_db()
        assert payment.sucursal_id == norte.id

    def test_payment_sin_allocation_cae_a_principal(self, db: Any) -> None:
        tenant = TenantFactory()
        principal = SucursalFactory(tenant=tenant, is_default=True)
        payment = PaymentFactory(tenant=tenant, sucursal=None)

        backfill = _load_backfill()
        backfill(real_apps, None)

        payment.refresh_from_db()
        assert payment.sucursal_id == principal.id

    def test_idempotente_no_reasigna_ya_backfillado(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_default=True)
        otra = SucursalFactory(tenant=tenant)
        charge = ChargeFactory(tenant=tenant, sucursal=otra)

        backfill = _load_backfill()
        backfill(real_apps, None)
        backfill(real_apps, None)

        charge.refresh_from_db()
        assert charge.sucursal_id == otra.id


# ---------------------------------------------------------------------------
# 2. Services — sucursal DONDE SE GENERÓ
# ---------------------------------------------------------------------------


class TestServicesGuardanSucursal:
    def test_charge_create_guarda_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            charge = charge_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                amount=Decimal("100.00"),
                description="Consulta",
                sucursal=sucursal,
            )

        assert charge.sucursal_id == sucursal.id

    def test_charge_create_rechaza_sucursal_de_otro_tenant(self, db: Any) -> None:
        tenant = TenantFactory()
        otro_tenant = TenantFactory()
        sucursal_ajena = SucursalFactory(tenant=otro_tenant)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant), pytest.raises(ValidationError):
            charge_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                amount=Decimal("100.00"),
                description="Consulta",
                sucursal=sucursal_ajena,
            )

    def test_payment_register_guarda_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        ChargeFactory(tenant=tenant, patient=patient, amount=Decimal("200.00"))

        with _tenant_ctx(tenant):
            payment = payment_register(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                amount=Decimal("200.00"),
                sucursal=sucursal,
            )

        assert payment.sucursal_id == sucursal.id

    def test_quote_create_guarda_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            quote = quote_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                items=[{"description": "Tratamiento", "quantity": 1, "unit_price": "500.00"}],
                sucursal=sucursal,
            )

        assert quote.sucursal_id == sucursal.id

    def test_quote_accept_charges_heredan_sucursal_de_la_cotizacion(self, db: Any) -> None:
        """Los cargos generados al aceptar una cotización heredan la sede
        DONDE SE GENERÓ la cotización, no la sede activa de quien la acepta."""
        tenant = TenantFactory()
        sucursal_cotizacion = SucursalFactory(tenant=tenant, name="Acapulco")
        SucursalFactory(tenant=tenant, name="CDMX")  # sede activa de quien acepta (irrelevante)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            quote = quote_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                items=[{"description": "Tratamiento", "quantity": 1, "unit_price": "500.00"}],
                sucursal=sucursal_cotizacion,
            )
            quote_accept(quote=quote, user=UserFactory())

        charge = Charge.all_objects.get(quote=quote)
        assert charge.sucursal_id == sucursal_cotizacion.id


# ---------------------------------------------------------------------------
# 3. Estado de cuenta del paciente — COMPARTIDO (caso Acapulco→CDMX)
# ---------------------------------------------------------------------------


class TestEstadoDeCuentaCompartido:
    def test_paciente_con_cargos_en_dos_sedes_muestra_ambos(self, db: Any) -> None:
        """Caso Acapulco→CDMX: paciente cobrado en dos sedes distintas ve
        AMBOS movimientos en su estado de cuenta, sin importar desde qué sede
        se consulte."""
        tenant = TenantFactory()
        acapulco = SucursalFactory(tenant=tenant, name="Acapulco")
        cdmx = SucursalFactory(tenant=tenant, name="CDMX")
        patient = PatientFactory(tenant=tenant)
        ChargeFactory(
            tenant=tenant,
            patient=patient,
            sucursal=acapulco,
            amount=Decimal("300.00"),
            description="Consulta Acapulco",
            issued_at=_dt(datetime.date.today()),
        )
        ChargeFactory(
            tenant=tenant,
            patient=patient,
            sucursal=cdmx,
            amount=Decimal("500.00"),
            description="Consulta CDMX",
            issued_at=_dt(datetime.date.today()),
        )

        finance_user = _member_scoped_to(tenant, TenantMembership.Role.FINANCE, cdmx)
        client = _auth_client(finance_user)

        # Consulta desde la sede activa CDMX: el estado de cuenta del
        # paciente NO se filtra por sede — debe traer AMBOS cargos.
        with _api_tenant_ctx(tenant):
            resp = client.get(_statement_url(patient.id), headers={"X-Sucursal-Id": str(cdmx.id)})

        assert resp.status_code == 200, resp.content
        body = resp.json()
        descriptions = {m["description"] for m in body["movements"]}
        assert descriptions == {"Consulta Acapulco", "Consulta CDMX"}
        assert _D(body["total_charged"]) == Decimal("800.00")

        # Las columnas de sede vienen informadas por movimiento.
        by_desc = {m["description"]: m["sucursal"] for m in body["movements"]}
        assert by_desc["Consulta Acapulco"]["name"] == "Acapulco"
        assert by_desc["Consulta CDMX"]["name"] == "CDMX"

    def test_finance_general_charge_list_por_patient_id_no_se_acota(self, db: Any) -> None:
        """El listado GENERAL de cargos (ChargeListCreateApi), cuando se
        consulta CON patient_id, tampoco se acota por sede (mismo criterio
        que el estado de cuenta)."""
        tenant = TenantFactory()
        acapulco = SucursalFactory(tenant=tenant, name="Acapulco")
        cdmx = SucursalFactory(tenant=tenant, name="CDMX")
        patient = PatientFactory(tenant=tenant)
        ChargeFactory(tenant=tenant, patient=patient, sucursal=acapulco)
        ChargeFactory(tenant=tenant, patient=patient, sucursal=cdmx)

        finance_user = _member_scoped_to(tenant, TenantMembership.Role.FINANCE, cdmx)
        client = _auth_client(finance_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CHARGES_URL, {"patient_id": str(patient.id)})

        assert resp.status_code == 200, resp.content
        assert resp.json()["count"] == 2


# ---------------------------------------------------------------------------
# 4. Reportes/caja — PRIVADOS por sede
# ---------------------------------------------------------------------------


class TestReportesPrivadosPorSede:
    def _seed_two_sedes(self, tenant: Any, centro: Any, norte: Any) -> None:
        today = datetime.date.today()
        p1 = PatientFactory(tenant=tenant)
        p2 = PatientFactory(tenant=tenant)
        ChargeFactory(
            tenant=tenant,
            patient=p1,
            sucursal=centro,
            amount=Decimal("1000.00"),
            issued_at=_dt(today),
        )
        PaymentFactory(
            tenant=tenant,
            patient=p1,
            sucursal=centro,
            amount=Decimal("1000.00"),
            received_at=_dt(today),
        )
        ChargeFactory(
            tenant=tenant,
            patient=p2,
            sucursal=norte,
            amount=Decimal("2000.00"),
            issued_at=_dt(today),
        )
        PaymentFactory(
            tenant=tenant,
            patient=p2,
            sucursal=norte,
            amount=Decimal("2000.00"),
            received_at=_dt(today),
        )

    def test_admin_finanzas_acotado_a_centro_no_ve_ingresos_de_norte_dashboard(
        self, db: Any
    ) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        self._seed_two_sedes(tenant, centro, norte)

        finance_user = _member_scoped_to(tenant, TenantMembership.Role.FINANCE, centro)
        client = _auth_client(finance_user)

        # SIN header: sucursal_scope_ids acota igual a [centro.id].
        with _api_tenant_ctx(tenant):
            resp = client.get(DASHBOARD_URL)

        assert resp.status_code == 200, resp.content
        assert _D(resp.json()["kpis"]["total_income"]) == Decimal("1000.00")

    def test_admin_finanzas_acotado_a_centro_no_ve_cierre_de_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        self._seed_two_sedes(tenant, centro, norte)

        finance_user = _member_scoped_to(tenant, TenantMembership.Role.FINANCE, centro)
        client = _auth_client(finance_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(DAILY_URL)

        assert resp.status_code == 200, resp.content
        assert _D(resp.json()["production"]) == Decimal("1000.00")
        assert _D(resp.json()["collection"]) == Decimal("1000.00")

    def test_admin_finanzas_acotado_a_centro_no_ve_reporte_de_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        self._seed_two_sedes(tenant, centro, norte)

        finance_user = _member_scoped_to(tenant, TenantMembership.Role.FINANCE, centro)
        client = _auth_client(finance_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(REPORT_URL)

        assert resp.status_code == 200, resp.content
        assert _D(resp.json()["production"]) == Decimal("1000.00")

    def test_finance_general_charge_and_payment_list_se_acotan_sin_header(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        self._seed_two_sedes(tenant, centro, norte)

        finance_user = _member_scoped_to(tenant, TenantMembership.Role.FINANCE, centro)
        client = _auth_client(finance_user)

        with _api_tenant_ctx(tenant):
            charges_resp = client.get(CHARGES_URL)
            payments_resp = client.get(PAYMENTS_URL)

        assert charges_resp.status_code == 200, charges_resp.content
        assert payments_resp.status_code == 200, payments_resp.content
        assert charges_resp.json()["count"] == 1
        assert payments_resp.json()["count"] == 1
        assert charges_resp.json()["results"][0]["sucursal"]["name"] == "Centro"

    def test_owner_ve_consolidado_sin_sede_activa(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        self._seed_two_sedes(tenant, centro, norte)

        owner = _member(tenant, TenantMembership.Role.OWNER)
        client = _auth_client(owner)

        with _api_tenant_ctx(tenant):
            resp = client.get(DASHBOARD_URL)

        assert resp.status_code == 200, resp.content
        assert _D(resp.json()["kpis"]["total_income"]) == Decimal("3000.00")

    def test_owner_ve_por_sede_con_header_activo(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        self._seed_two_sedes(tenant, centro, norte)

        owner = _member(tenant, TenantMembership.Role.OWNER)
        client = _auth_client(owner)

        with _api_tenant_ctx(tenant):
            resp = client.get(DASHBOARD_URL, headers={"X-Sucursal-Id": str(norte.id)})

        assert resp.status_code == 200, resp.content
        assert _D(resp.json()["kpis"]["total_income"]) == Decimal("2000.00")

    def test_retention_panel_se_acota_por_sede(self, db: Any) -> None:
        """RFM: las visitas ATTENDED de un paciente en Norte no cuentan para
        el panel de retención de un admin acotado a Centro."""
        from apps.agenda.models import Appointment

        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)
        patient_centro = PatientFactory(tenant=tenant)
        patient_norte = PatientFactory(tenant=tenant)

        now = datetime.datetime.now(tz=datetime.UTC)
        with _tenant_ctx(tenant):
            AppointmentFactory(
                tenant=tenant,
                patient=patient_centro,
                doctor=doctor,
                sucursal=centro,
                status=Appointment.Status.ATTENDED,
                starts_at=now - datetime.timedelta(days=5),
            )
            AppointmentFactory(
                tenant=tenant,
                patient=patient_norte,
                doctor=doctor,
                sucursal=norte,
                status=Appointment.Status.ATTENDED,
                starts_at=now - datetime.timedelta(days=5),
            )

        finance_user = _member_scoped_to(tenant, TenantMembership.Role.FINANCE, centro)
        client = _auth_client(finance_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(RETENTION_URL)

        assert resp.status_code == 200, resp.content
        body = resp.json()
        # "nuevo" cuenta a los pacientes con 1a visita atendida < 90 días:
        # solo el de Centro debe figurar en la segmentación de esta sede.
        assert body["segments"]["nuevo"] == 1


# ---------------------------------------------------------------------------
# 4b. "Admin de sucursal" — mismo aislamiento que un rol operativo acotado
# (bug corregido: antes cualquier admin veía/operaba TODAS las sedes sin
# importar su MembershipSucursal; ver
# docs/design/sucursales-arquitectura-analisis.md §12)
# ---------------------------------------------------------------------------


class TestAdminDeSucursalFinanzas:
    def test_admin_acotado_a_centro_no_ve_dashboard_de_norte_sin_header(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        TestReportesPrivadosPorSede()._seed_two_sedes(tenant, centro, norte)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(DASHBOARD_URL)

        assert resp.status_code == 200, resp.content
        assert _D(resp.json()["kpis"]["total_income"]) == Decimal("1000.00")

    def test_admin_acotado_a_centro_pide_cierre_de_norte_con_header_403(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        TestReportesPrivadosPorSede()._seed_two_sedes(tenant, centro, norte)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(DAILY_URL, headers={"X-Sucursal-Id": str(norte.id)})

        assert resp.status_code == 403

    def test_admin_acotado_a_centro_no_puede_crear_cargo_en_sede_default_ajena(
        self, db: Any
    ) -> None:
        """CIERRE DEL HUECO (resolve_write_sucursal): la sede PREDETERMINADA
        del tenant es Norte, pero el admin solo está asignado a Centro. Sin
        header, `resolve_write_sucursal` NO debe caer silenciosamente en la
        default ajena — debe rechazar la escritura."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        SucursalFactory(tenant=tenant, name="Norte", is_default=True)
        patient = PatientFactory(tenant=tenant)

        # Admin acotado SOLO a Centro (no a la sede default, que es Norte).
        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.post(
                CHARGES_URL,
                data={
                    "patient_id": str(patient.id),
                    "amount": "100.00",
                    "description": "Consulta",
                },
                format="json",
            )

        assert resp.status_code == 400, resp.content
        assert not Charge.all_objects.filter(patient=patient).exists()

    def test_admin_acotado_a_centro_puede_crear_cargo_con_header_de_centro(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        SucursalFactory(tenant=tenant, name="Norte", is_default=True)
        patient = PatientFactory(tenant=tenant)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.post(
                CHARGES_URL,
                data={
                    "patient_id": str(patient.id),
                    "amount": "100.00",
                    "description": "Consulta",
                },
                format="json",
                headers={"X-Sucursal-Id": str(centro.id)},
            )

        assert resp.status_code == 201, resp.content
        assert resp.json()["sucursal"]["id"] == str(centro.id)


# ---------------------------------------------------------------------------
# 5. Aislamiento cross-tenant (verificación ligera)
# ---------------------------------------------------------------------------


class TestAislamientoCrossTenantIntacto:
    def test_charge_de_otro_tenant_no_aparece_en_dashboard(self, db: Any) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        sucursal_a = SucursalFactory(tenant=tenant_a)
        ChargeFactory(
            tenant=tenant_a,
            sucursal=sucursal_a,
            amount=Decimal("100.00"),
            issued_at=_dt(datetime.date.today()),
        )
        ChargeFactory(
            tenant=tenant_b,
            amount=Decimal("999.00"),
            issued_at=_dt(datetime.date.today()),
        )

        owner_a = _member(tenant_a, TenantMembership.Role.OWNER)
        client = _auth_client(owner_a)

        with _api_tenant_ctx(tenant_a):
            resp = client.get(DASHBOARD_URL)

        assert resp.status_code == 200, resp.content
        assert _D(resp.json()["kpis"]["total_charged"]) == Decimal("100.00")


# ---------------------------------------------------------------------------
# 6. A7 — Cargos: cancelar/leer por id acotado por sede
# (docs/design/sucursales-hallazgos-seguridad.md)
# ---------------------------------------------------------------------------


class TestCargosCancelarPorIdAcotado:
    """El detalle/cancelación por id de un cargo debe acotarse EXACTAMENTE
    igual que el listado GENERAL de cargos: un admin acotado a una sede no
    debe poder leer ni anular un cargo de otra sede por su id, aunque lo haya
    obtenido del estado de cuenta compartido del paciente."""

    def test_admin_centro_no_puede_cancelar_cargo_de_norte_por_id(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        charge_norte = ChargeFactory(tenant=tenant, sucursal=norte, amount=Decimal("500.00"))

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.delete(_charge_url(charge_norte.id))

        assert resp.status_code == 404, resp.content
        charge_norte.refresh_from_db()
        assert charge_norte.status == Charge.Status.PENDING

    def test_admin_centro_no_puede_leer_cargo_de_norte_por_id(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        charge_norte = ChargeFactory(tenant=tenant, sucursal=norte)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(_charge_url(charge_norte.id))

        assert resp.status_code == 404, resp.content

    def test_admin_centro_puede_cancelar_cargo_de_su_propia_sede(self, db: Any) -> None:
        """Control positivo: el cierre del hueco no rompe la operación normal."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        charge_centro = ChargeFactory(tenant=tenant, sucursal=centro, amount=Decimal("500.00"))

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.delete(_charge_url(charge_centro.id))

        assert resp.status_code == 204, resp.content
        charge_centro.refresh_from_db()
        assert charge_centro.status == Charge.Status.CANCELLED


class TestPagosDetallePorIdAcotado:
    """A7 aplicado a PAGOS: el detalle de un pago por id debe acotarse por
    sede igual que cargos/cotizaciones/CFDI. Un admin acotado a Centro no debe
    poder leer un pago de Norte por su id (el id se obtiene del estado de
    cuenta compartido del paciente)."""

    def test_admin_centro_no_puede_leer_pago_de_norte_por_id(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        pago_norte = PaymentFactory(tenant=tenant, sucursal=norte, amount=Decimal("500.00"))

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(_payment_url(pago_norte.id))

        assert resp.status_code == 404, resp.content

    def test_admin_centro_puede_leer_pago_de_su_propia_sede(self, db: Any) -> None:
        """Control positivo: el cierre del hueco no rompe la operación normal."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        pago_centro = PaymentFactory(tenant=tenant, sucursal=centro, amount=Decimal("500.00"))

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(_payment_url(pago_centro.id))

        assert resp.status_code == 200, resp.content
        assert resp.json()["id"] == str(pago_centro.id)

    def test_owner_puede_leer_pago_de_cualquier_sede(self, db: Any) -> None:
        """El dueño ve el consolidado: puede leer un pago de cualquier sede."""
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        pago_norte = PaymentFactory(tenant=tenant, sucursal=norte, amount=Decimal("500.00"))

        owner = _member_scoped_to(tenant, TenantMembership.Role.OWNER, norte)
        client = _auth_client(owner)

        with _api_tenant_ctx(tenant):
            resp = client.get(_payment_url(pago_norte.id))

        assert resp.status_code == 200, resp.content


# ---------------------------------------------------------------------------
# 7. A6 — Cotizaciones: ciclo de vida (enviar/aceptar/rechazar) acotado
# (docs/design/sucursales-hallazgos-seguridad.md)
# ---------------------------------------------------------------------------


class TestCotizacionesCicloVidaAcotado:
    """Aceptar una cotización CREA `Charge` en la sede de la cotización: sin
    el cierre de A6, un admin de Centro podía generar ingresos en la caja de
    Norte con solo conocer el id de la cotización."""

    def _quote_con_item(
        self,
        tenant: Any,
        sucursal: Any,
        *,
        patient: Any = None,
        status: str = Quote.Status.SENT,
    ) -> Any:
        quote = QuoteFactory(
            tenant=tenant,
            patient=patient or PatientFactory(tenant=tenant),
            sucursal=sucursal,
            status=status,
        )
        QuoteItemFactory(
            quote=quote,
            quantity=Decimal("1.00"),
            unit_price=Decimal("500.00"),
            discount=Decimal("0.00"),
            line_total=Decimal("500.00"),
        )
        return quote

    def test_admin_centro_no_puede_aceptar_cotizacion_de_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        quote_norte = self._quote_con_item(tenant, norte)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.post(_quote_accept_url(quote_norte.id))

        assert resp.status_code == 404, resp.content
        quote_norte.refresh_from_db()
        assert quote_norte.status == Quote.Status.SENT
        assert not Charge.all_objects.filter(quote=quote_norte).exists()

    def test_admin_centro_no_puede_enviar_cotizacion_de_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        quote_norte = self._quote_con_item(tenant, norte, status=Quote.Status.DRAFT)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.post(_quote_send_url(quote_norte.id))

        assert resp.status_code == 404, resp.content
        quote_norte.refresh_from_db()
        assert quote_norte.status == Quote.Status.DRAFT

    def test_admin_centro_no_puede_rechazar_cotizacion_de_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        quote_norte = self._quote_con_item(tenant, norte, status=Quote.Status.DRAFT)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.patch(
                _quote_url(quote_norte.id), data={"status": "rejected"}, format="json"
            )

        assert resp.status_code == 404, resp.content
        quote_norte.refresh_from_db()
        assert quote_norte.status == Quote.Status.DRAFT

    def test_admin_centro_puede_aceptar_cotizacion_de_su_sede(self, db: Any) -> None:
        """Control positivo: el cierre del hueco no rompe la operación normal."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        quote_centro = self._quote_con_item(tenant, centro)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.post(_quote_accept_url(quote_centro.id))

        assert resp.status_code == 200, resp.content
        quote_centro.refresh_from_db()
        assert quote_centro.status == Quote.Status.ACCEPTED

    def test_admin_centro_no_puede_generar_pdf_de_cotizacion_de_norte(self, db: Any) -> None:
        """El PDF de la cotización revela montos/paciente/conceptos: debe
        acotarse por sede igual que el detalle y las acciones (mismo A6)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        quote_norte = self._quote_con_item(tenant, norte)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(_quote_pdf_url(quote_norte.id))

        assert resp.status_code == 404, resp.content

    def test_admin_centro_puede_generar_pdf_de_cotizacion_de_su_sede(self, db: Any) -> None:
        """Control positivo: el actor sí puede generar el PDF de su propia sede."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        quote_centro = self._quote_con_item(tenant, centro)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(_quote_pdf_url(quote_centro.id))

        assert resp.status_code == 202, resp.content


# ---------------------------------------------------------------------------
# 8. Clúster D — CFDI: listado/detalle/timbrado/cancelación acotados por sede
# (docs/design/sucursales-hallazgos-seguridad.md)
# ---------------------------------------------------------------------------


class TestCfdiAcotadoPorSede:
    def test_admin_centro_no_ve_cfdi_de_norte_en_listado(self, db: Any) -> None:
        """Reproduce PoC-1 del hallazgo: GET /finanzas/cfdi/ sin header NO
        debe traer comprobantes de una sede ajena."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        CfdiDocumentFactory(tenant=tenant, sucursal=centro, folio=1)
        CfdiDocumentFactory(tenant=tenant, sucursal=norte, folio=2)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CFDI_URL)

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["sucursal"]["name"] == "Centro"

    def test_cfdi_list_por_patient_id_no_se_acota(self, db: Any) -> None:
        """El historial fiscal del paciente es compartido entre sedes, mismo
        criterio que cargos/pagos/cotizaciones (no lo rompas)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        patient = PatientFactory(tenant=tenant)
        CfdiDocumentFactory(tenant=tenant, patient=patient, sucursal=centro, folio=1)
        CfdiDocumentFactory(tenant=tenant, patient=patient, sucursal=norte, folio=2)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CFDI_URL, {"patient_id": str(patient.id)})

        assert resp.status_code == 200, resp.content
        assert resp.json()["count"] == 2

    def test_admin_centro_no_puede_ver_detalle_cfdi_de_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        cfdi_norte = CfdiDocumentFactory(tenant=tenant, sucursal=norte)

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(_cfdi_url(cfdi_norte.id))

        assert resp.status_code == 404, resp.content

    def test_admin_centro_no_puede_cancelar_cfdi_de_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        cfdi_norte = CfdiDocumentFactory(
            tenant=tenant,
            sucursal=norte,
            status=CfdiDocument.Status.STAMPED,
            uuid_sat="00000000-0000-0000-0000-000000000001",
        )

        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.post(
                _cfdi_cancel_url(cfdi_norte.id), data={"reason": "02"}, format="json"
            )

        assert resp.status_code == 404, resp.content
        cfdi_norte.refresh_from_db()
        assert cfdi_norte.status == CfdiDocument.Status.STAMPED

    def test_cfdi_issue_hereda_sucursal_del_pago(self, db: Any) -> None:
        tenant = TenantFactory()
        sucursal = SucursalFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        ClinicFiscalConfigFactory(tenant=tenant)
        # owner: siempre tiene acceso a todas las sedes (allowed_sucursales),
        # así que _ensure_sucursal_allowed no lo bloquea.
        user = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            charge_create(
                tenant=tenant,
                user=user,
                patient=patient,
                amount=Decimal("500.00"),
                description="Consulta",
                sucursal=sucursal,
            )
            payment = payment_register(
                tenant=tenant,
                user=user,
                patient=patient,
                amount=Decimal("500.00"),
                sucursal=sucursal,
            )
            cfdi = cfdi_issue(
                tenant=tenant,
                user=user,
                payment=payment,
                receptor_rfc="XAXX010101000",
                receptor_name="X",
            )

        assert cfdi.sucursal_id == sucursal.id

    def test_cfdi_issue_rechaza_timbrar_pago_de_sede_ajena(self, db: Any) -> None:
        """Integridad fiscal (clúster D): un admin acotado a Centro no debe
        poder timbrar un CFDI a partir de un pago recibido en Norte."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        patient = PatientFactory(tenant=tenant)
        ClinicFiscalConfigFactory(tenant=tenant)
        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)

        with _tenant_ctx(tenant):
            charge_create(
                tenant=tenant,
                user=admin_user,
                patient=patient,
                amount=Decimal("500.00"),
                description="Consulta",
                sucursal=norte,
            )
            payment = payment_register(
                tenant=tenant,
                user=admin_user,
                patient=patient,
                amount=Decimal("500.00"),
                sucursal=norte,
            )

            with pytest.raises(ValidationError):
                cfdi_issue(
                    tenant=tenant,
                    user=admin_user,
                    payment=payment,
                    receptor_rfc="XAXX010101000",
                    receptor_name="X",
                )

        assert not CfdiDocument.all_objects.filter(payment=payment).exists()

    def test_cfdi_cancel_rechaza_cancelar_cfdi_de_sede_ajena(self, db: Any) -> None:
        """Defensa en profundidad a nivel de servicio (independiente del 404
        de la vista): un admin acotado a Centro no debe poder cancelar el
        CFDI de Norte llamando al servicio directamente."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        cfdi_norte = CfdiDocumentFactory(
            tenant=tenant,
            sucursal=norte,
            status=CfdiDocument.Status.STAMPED,
            uuid_sat="00000000-0000-0000-0000-000000000002",
        )
        admin_user = _member_scoped_to(tenant, TenantMembership.Role.ADMIN, centro)

        with _tenant_ctx(tenant), pytest.raises(ValidationError):
            cfdi_cancel(cfdi=cfdi_norte, user=admin_user, reason="02")

        cfdi_norte.refresh_from_db()
        assert cfdi_norte.status == CfdiDocument.Status.STAMPED


# ---------------------------------------------------------------------------
# 9. Backfill — finanzas/migrations/0010 (CfdiDocument.sucursal)
# ---------------------------------------------------------------------------


class TestBackfillCfdiSucursal:
    def test_cfdi_hereda_de_su_pago(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        payment = PaymentFactory(tenant=tenant, sucursal=norte)
        cfdi = CfdiDocumentFactory(tenant=tenant, payment=payment, sucursal=None)

        backfill = _load_cfdi_backfill()
        backfill(real_apps, None)

        cfdi.refresh_from_db()
        assert cfdi.sucursal_id == norte.id

    def test_cfdi_sin_pago_cae_a_principal(self, db: Any) -> None:
        tenant = TenantFactory()
        principal = SucursalFactory(tenant=tenant, is_default=True)
        cfdi = CfdiDocumentFactory(tenant=tenant, payment=None, sucursal=None)

        backfill = _load_cfdi_backfill()
        backfill(real_apps, None)

        cfdi.refresh_from_db()
        assert cfdi.sucursal_id == principal.id

    def test_cfdi_con_pago_sin_sucursal_cae_a_principal(self, db: Any) -> None:
        tenant = TenantFactory()
        principal = SucursalFactory(tenant=tenant, is_default=True)
        payment = PaymentFactory(tenant=tenant, sucursal=None)
        cfdi = CfdiDocumentFactory(tenant=tenant, payment=payment, sucursal=None)

        backfill = _load_cfdi_backfill()
        backfill(real_apps, None)

        cfdi.refresh_from_db()
        assert cfdi.sucursal_id == principal.id

    def test_idempotente_no_reasigna_ya_backfillado(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_default=True)
        otra = SucursalFactory(tenant=tenant)
        cfdi = CfdiDocumentFactory(tenant=tenant, sucursal=otra)

        backfill = _load_cfdi_backfill()
        backfill(real_apps, None)
        backfill(real_apps, None)

        cfdi.refresh_from_db()
        assert cfdi.sucursal_id == otra.id
