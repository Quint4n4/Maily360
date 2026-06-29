"""
Tests del módulo de Cotizaciones — C-1, C-2, C-3.

Cubre:
  C-1  — QuotePermission: matriz de roles (doctor SÍ, nurse → 403).
  C-2  — QuotePdfApi: Accept: application/pdf → 200; sin header → 406.
  C-3  — appointment_create con quote_id válido lo vincula; quote_id de otro
          paciente o no-accepted → ValidationError (400 en la API).

Patrón: AAA. Todas tocan BD → fixture db.
Mocks mínimos: solo el contexto de tenant (igual que test_apis.py).
"""

from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Generator
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.agenda.services import appointment_create
from apps.finanzas.models import Quote
from tests.factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    QuoteFactory,
    QuoteItemFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

QUOTES_URL = "/api/v1/finanzas/cotizaciones/"


def _quote_pdf_url(quote_id: Any) -> str:
    return f"/api/v1/finanzas/cotizaciones/{quote_id}/pdf/"


def _quote_pdf_via_async(client: Any, quote_id: Any, tenant: Any) -> Any:
    """Flujo async del PDF de cotización: encola (202) -> tarea (mock build) -> descarga."""
    from apps.pdfs.tasks import generate_pdf

    with _tenant_context(tenant):
        req = client.get(_quote_pdf_url(quote_id))
    assert req.status_code == 202, req.content
    job_id = req.json()["job_id"]
    with patch("apps.finanzas.pdf.quote_pdf_build", return_value=b"%PDF-test"):
        generate_pdf(job_id)
    with _tenant_context(tenant):
        return client.get(
            f"/api/v1/pdfs/job/{job_id}/file/", HTTP_ACCEPT="application/pdf"
        )


def _quote_send_url(quote_id: Any) -> str:
    return f"/api/v1/finanzas/cotizaciones/{quote_id}/enviar/"


def _quote_accept_url(quote_id: Any) -> str:
    return f"/api/v1/finanzas/cotizaciones/{quote_id}/aceptar/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula TenantMiddleware para un tenant durante el request."""
    with (
        patch("apps.finanzas.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


@contextmanager
def _agenda_tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula TenantMiddleware en el contexto de las vistas de agenda."""
    with (
        patch("apps.agenda.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _member_client(tenant: Any, role: str) -> APIClient:
    """APIClient autenticado como miembro con rol indicado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _accepted_quote(tenant: Any, patient: Any) -> Quote:
    """Crea una Quote ACCEPTED con un QuoteItem para el paciente dado."""
    quote = QuoteFactory(
        tenant=tenant,
        patient=patient,
        status=Quote.Status.ACCEPTED,
        subtotal=Decimal("500.00"),
        discount_total=Decimal("0.00"),
        total=Decimal("500.00"),
    )
    QuoteItemFactory(
        quote=quote,
        tenant=tenant,
        description="Consulta general",
        unit_price=Decimal("500.00"),
        line_total=Decimal("500.00"),
    )
    return quote


# ===========================================================================
# C-1 — QuotePermission: matriz de roles
# ===========================================================================


class TestQuotePermission:
    """Verifica que QuotePermission permite doctor y bloquea nurse."""

    def test_unauthenticated_rejected(self, db: None) -> None:
        """Sin token → 401."""
        tenant = TenantFactory()
        with _tenant_context(tenant):
            resp = APIClient().get(QUOTES_URL)
        assert resp.status_code == 401

    def test_doctor_can_list_quotes(self, db: None) -> None:
        """Doctor SÍ puede listar cotizaciones (C-1)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "doctor")
        with _tenant_context(tenant):
            resp = client.get(QUOTES_URL)
        assert resp.status_code == 200

    def test_reception_can_list_quotes(self, db: None) -> None:
        tenant = TenantFactory()
        client = _member_client(tenant, "reception")
        with _tenant_context(tenant):
            resp = client.get(QUOTES_URL)
        assert resp.status_code == 200

    def test_finance_cannot_list_quotes(self, db: None) -> None:
        """Finanzas queda FUERA del módulo de cotizaciones (decisión C-1)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")
        with _tenant_context(tenant):
            resp = client.get(QUOTES_URL)
        assert resp.status_code == 403

    def test_nurse_cannot_list_quotes(self, db: None) -> None:
        """Nurse NO puede listar cotizaciones (no tiene rol financiero)."""
        tenant = TenantFactory()
        client = _member_client(tenant, "nurse")
        with _tenant_context(tenant):
            resp = client.get(QUOTES_URL)
        assert resp.status_code == 403

    def test_doctor_can_accept_quote(self, db: None) -> None:
        """Doctor SÍ puede aceptar una cotización (cierra venta en consulta)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        quote = QuoteFactory(
            tenant=tenant,
            patient=patient,
            status=Quote.Status.SENT,
            total=Decimal("500.00"),
        )
        QuoteItemFactory(quote=quote, tenant=tenant, line_total=Decimal("500.00"))

        # Usamos un cliente doctor CON membership en el tenant.
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        client = APIClient()
        client.force_authenticate(user=user)

        with _tenant_context(tenant):
            resp = client.post(_quote_accept_url(quote.id))
        assert resp.status_code == 200
        quote.refresh_from_db()
        assert quote.status == Quote.Status.ACCEPTED

    def test_nurse_cannot_accept_quote(self, db: None) -> None:
        """Nurse → 403 al intentar aceptar una cotización."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        quote = QuoteFactory(tenant=tenant, patient=patient, status=Quote.Status.SENT)

        client = _member_client(tenant, "nurse")
        with _tenant_context(tenant):
            resp = client.post(_quote_accept_url(quote.id))
        assert resp.status_code == 403

    def test_readonly_cannot_create_quote(self, db: None) -> None:
        """Readonly puede VER pero no crear cotizaciones."""
        tenant = TenantFactory()
        client = _member_client(tenant, "readonly")
        with _tenant_context(tenant):
            resp = client.post(QUOTES_URL, data={"patient_id": "x", "items": []}, format="json")
        assert resp.status_code == 403


# ===========================================================================
# C-2 — QuotePdfApi
# ===========================================================================


class TestQuotePdfApi:
    """Flujo async del PDF de cotización (encolar -> tarea Celery -> descarga)."""

    def test_enqueue_returns_202(self, db: None) -> None:
        """GET encola y devuelve 202 {job_id, status}."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        quote = _accepted_quote(tenant, patient)
        client = _member_client(tenant, "owner")
        with _tenant_context(tenant):
            resp = client.get(_quote_pdf_url(quote.id))
        assert resp.status_code == 202
        assert "job_id" in resp.json()

    def test_pdf_descarga_200(self, db: None) -> None:
        """Encolar -> correr la tarea (mock build) -> descargar el PDF (200)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        quote = _accepted_quote(tenant, patient)
        client = _member_client(tenant, "owner")
        resp = _quote_pdf_via_async(client, quote.id, tenant)
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"

    def test_pdf_requires_auth(self, db: None) -> None:
        """Sin autenticación -> 401."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        quote = _accepted_quote(tenant, patient)
        with _tenant_context(tenant):
            resp = APIClient().get(_quote_pdf_url(quote.id))
        assert resp.status_code == 401

    def test_pdf_nurse_gets_403(self, db: None) -> None:
        """Nurse no tiene permiso sobre cotizaciones -> 403."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        quote = _accepted_quote(tenant, patient)
        client = _member_client(tenant, "nurse")
        with _tenant_context(tenant):
            resp = client.get(_quote_pdf_url(quote.id))
        assert resp.status_code == 403

    def test_pdf_unknown_quote_returns_404(self, db: None) -> None:
        """UUID que no existe -> 404."""
        import uuid

        tenant = TenantFactory()
        client = _member_client(tenant, "owner")
        with _tenant_context(tenant):
            resp = client.get(_quote_pdf_url(uuid.uuid4()))
        assert resp.status_code == 404


# ===========================================================================
# C-3 — appointment_create con quote_id
# ===========================================================================


class TestAppointmentCreateWithQuote:
    """Tests del servicio appointment_create con el parámetro quote_id (C-3)."""

    def _setup_tenant_and_doctor(self) -> tuple[Any, Any, Any, Any]:
        """Crea tenant, doctor, patient y usuario doctor, con TenantAgendaConfig."""
        from tests.factories import TenantAgendaConfigFactory

        tenant = TenantFactory()
        TenantAgendaConfigFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        user = doctor.membership.user
        return tenant, doctor, patient, user

    def _starts_at(self) -> Any:
        """Datetime base para citas (horario sin colisiones)."""
        from django.utils import timezone
        import datetime

        return timezone.now() + datetime.timedelta(days=1)

    def test_valid_accepted_quote_links_to_appointment(self, db: None) -> None:
        """quote_id válido (mismo paciente, ACCEPTED) → cita creada con FK a quote."""
        tenant, doctor, patient, user = self._setup_tenant_and_doctor()
        quote = _accepted_quote(tenant, patient)

        # Inyectar tenant activo para el service (usa TenantManager).
        with patch("apps.core.managers.get_current_tenant", return_value=tenant), \
             patch("apps.core.managers.is_tenant_context_active", return_value=True):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=self._starts_at(),
                quote_id=quote.id,
            )

        assert appt.quote_id == quote.id
        assert appt.quote.status == Quote.Status.ACCEPTED

    def test_quote_id_none_creates_appointment_without_quote(self, db: None) -> None:
        """quote_id=None → cita creada sin FK de cotización."""
        tenant, doctor, patient, user = self._setup_tenant_and_doctor()

        with patch("apps.core.managers.get_current_tenant", return_value=tenant), \
             patch("apps.core.managers.is_tenant_context_active", return_value=True):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=self._starts_at(),
                quote_id=None,
            )

        assert appt.quote_id is None

    def test_quote_from_other_patient_raises_validation_error(self, db: None) -> None:
        """quote_id de otro paciente → ValidationError (C-3)."""
        tenant, doctor, patient, user = self._setup_tenant_and_doctor()
        other_patient = PatientFactory(tenant=tenant)
        quote = _accepted_quote(tenant, other_patient)  # paciente distinto

        with patch("apps.core.managers.get_current_tenant", return_value=tenant), \
             patch("apps.core.managers.is_tenant_context_active", return_value=True):
            with pytest.raises(ValidationError, match="no corresponde al paciente"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=self._starts_at(),
                    quote_id=quote.id,
                )

    def test_quote_not_accepted_raises_validation_error(self, db: None) -> None:
        """quote_id de cotización en estado DRAFT → ValidationError (C-3)."""
        tenant, doctor, patient, user = self._setup_tenant_and_doctor()
        draft_quote = QuoteFactory(
            tenant=tenant,
            patient=patient,
            status=Quote.Status.DRAFT,
        )

        with patch("apps.core.managers.get_current_tenant", return_value=tenant), \
             patch("apps.core.managers.is_tenant_context_active", return_value=True):
            with pytest.raises(ValidationError, match="aceptada"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=self._starts_at(),
                    quote_id=draft_quote.id,
                )

    def test_quote_sent_not_accepted_raises_validation_error(self, db: None) -> None:
        """quote_id en SENT (no ACCEPTED) → ValidationError (C-3)."""
        tenant, doctor, patient, user = self._setup_tenant_and_doctor()
        sent_quote = QuoteFactory(
            tenant=tenant,
            patient=patient,
            status=Quote.Status.SENT,
        )

        with patch("apps.core.managers.get_current_tenant", return_value=tenant), \
             patch("apps.core.managers.is_tenant_context_active", return_value=True):
            with pytest.raises(ValidationError, match="aceptada"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=self._starts_at(),
                    quote_id=sent_quote.id,
                )

    def test_quote_of_different_tenant_raises_validation_error(self, db: None) -> None:
        """quote_id de otro tenant → ValidationError (TenantManager bloquea la query).

        El TenantManager filtra por tenant activo. Cuando la quote es de otro tenant,
        Quote.objects.get() lanza DoesNotExist, que el service convierte a ValidationError
        "Cotización no encontrada". Esto implementa el aislamiento multi-tenant a nivel ORM:
        el recurso ajeno es invisible (404/not-found), no accesible.
        """
        tenant, doctor, patient, user = self._setup_tenant_and_doctor()
        other_tenant = TenantFactory()
        other_patient = PatientFactory(tenant=other_tenant)
        cross_quote = QuoteFactory(
            tenant=other_tenant,
            patient=other_patient,
            status=Quote.Status.ACCEPTED,
        )

        with patch("apps.core.managers.get_current_tenant", return_value=tenant), \
             patch("apps.core.managers.is_tenant_context_active", return_value=True):
            with pytest.raises(ValidationError, match="no encontrada"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=self._starts_at(),
                    quote_id=cross_quote.id,
                )


# ===========================================================================
# C-3 — AppointmentOutputSerializer devuelve resumen de quote
# ===========================================================================


class TestAppointmentSerializerWithQuote:
    """Verifica que el serializer incluye el campo `quote` con sus campos."""

    def test_serializer_includes_quote_fields(self, db: None) -> None:
        """Appointment con quote vinculado → serializer devuelve id/total/status/display."""
        from apps.agenda.serializers import AppointmentOutputSerializer

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        quote = _accepted_quote(tenant, patient)
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            quote=quote,
        )

        # Prefetchamos igual que hace el selector.
        from apps.agenda.models import Appointment

        appt_qs = Appointment.objects.select_related(
            "patient", "doctor__membership__user", "consultorio", "quote"
        ).prefetch_related("reminders").get(id=appt.id)

        data = AppointmentOutputSerializer(appt_qs).data
        assert "quote" in data
        q = data["quote"]
        assert str(q["id"]) == str(quote.id)
        assert q["status"] == Quote.Status.ACCEPTED
        assert q["status_display"] == "Aceptada"
        assert q["total"] == str(quote.total)

    def test_serializer_quote_null_when_no_quote(self, db: None) -> None:
        """Appointment sin quote → campo 'quote' es null."""
        from apps.agenda.serializers import AppointmentOutputSerializer

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(tenant=tenant, patient=patient, doctor=doctor, quote=None)

        from apps.agenda.models import Appointment

        appt_qs = Appointment.objects.select_related(
            "patient", "doctor__membership__user", "consultorio", "quote"
        ).prefetch_related("reminders").get(id=appt.id)

        data = AppointmentOutputSerializer(appt_qs).data
        assert data["quote"] is None
