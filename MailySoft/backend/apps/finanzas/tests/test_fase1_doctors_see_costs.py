"""
Tests de la Fase 1 — estado de cuenta en el expediente del paciente.

Cubre:
  1. Flag doctors_see_costs en ClinicSettings:
       - Default False al crear.
       - owner/admin puede escribirlo (PUT de ClinicSettingsApi).
       - Roles no-admin (p. ej. reception) NO pueden escribirlo.
  2. Permiso condicional PatientStatementPermission / ChargeListPermission:
       - doctor SIN flag → 403 en estado de cuenta y GET de cargos.
       - doctor CON flag → 200 en estado de cuenta y GET de cargos.
       - finance → 200 siempre (independiente del flag).
       - nurse (sin acceso financiero, sin flag) → 403.
       - POST de cargo no se amplía al doctor aunque el flag esté activo.
  3. Filtro ?appointment en ChargeListCreateApi:
       - Devuelve solo los cargos de esa cita.
       - Ignora cargos de otras citas del mismo paciente.
       - UUID inválido → 400.

Patrón: AAA. Todas las clases usan la fixture db (pytest-django).
"""

import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Generator
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from tests.factories import (
    AppointmentFactory,
    ChargeFactory,
    ClinicSettingsFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Constantes de URL
# ---------------------------------------------------------------------------

CHARGES_URL = "/api/v1/finanzas/cargos/"
CLINIC_CONFIG_URL = "/api/v1/clinica/configuracion/"


def _statement_url(patient_id: Any) -> str:
    return f"/api/v1/finanzas/estado-cuenta/{patient_id}/"


# ---------------------------------------------------------------------------
# Helpers de test
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el efecto del TenantMiddleware para un tenant durante el request.

    Parchea todos los puntos donde se resuelve el tenant:
    - apps.finanzas.views: para los endpoints de finanzas.
    - apps.clinica.views: para el endpoint de configuración de clínica.
    - apps.core.managers: para que el TenantManager filtre correctamente.
    - apps.core.tenant_context: para el fallback del permiso PatientStatementPermission
      (la función _tenant_doctors_see_costs usa get_current_tenant desde tenant_context).
    """
    with (
        patch("apps.finanzas.views.get_current_tenant", return_value=tenant),
        patch("apps.clinica.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
        # Fallback del permiso condicional (import tardío dentro de la función).
        patch("apps.core.tenant_context.get_current_tenant", return_value=tenant),
    ):
        yield


def _member_client(tenant: Any, role: str) -> APIClient:
    """APIClient autenticado como un miembro del tenant con el rol indicado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _owner_client(tenant: Any) -> APIClient:
    return _member_client(tenant, "owner")


def _admin_client(tenant: Any) -> APIClient:
    return _member_client(tenant, "admin")


# ===========================================================================
# 1. Flag doctors_see_costs en ClinicSettings
# ===========================================================================


class TestDoctorsSeesCostsFlag:
    """Verifica el comportamiento del flag en el endpoint de config de clínica."""

    def test_flag_defaults_to_false(self, db: None) -> None:
        """Al crear un ClinicSettings, doctors_see_costs debe ser False."""
        settings = ClinicSettingsFactory()
        assert settings.doctors_see_costs is False

    def test_owner_can_set_flag_true(self, db: None) -> None:
        """owner puede activar doctors_see_costs via PUT de configuración."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant)
        client = _owner_client(tenant)

        with _tenant_context(tenant):
            resp = client.put(
                CLINIC_CONFIG_URL,
                data={"doctors_see_costs": True},
                format="json",
            )

        assert resp.status_code == 200, resp.json()
        assert resp.json()["doctors_see_costs"] is True

    def test_admin_can_set_flag_true(self, db: None) -> None:
        """admin también puede activar el flag."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant)
        client = _admin_client(tenant)

        with _tenant_context(tenant):
            resp = client.put(
                CLINIC_CONFIG_URL,
                data={"doctors_see_costs": True},
                format="json",
            )

        assert resp.status_code == 200, resp.json()
        assert resp.json()["doctors_see_costs"] is True

    def test_reception_cannot_write_flag(self, db: None) -> None:
        """reception no puede escribir la configuración de clínica (403)."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant)
        client = _member_client(tenant, "reception")

        with _tenant_context(tenant):
            resp = client.put(
                CLINIC_CONFIG_URL,
                data={"doctors_see_costs": True},
                format="json",
            )

        assert resp.status_code == 403

    def test_doctor_cannot_write_flag(self, db: None) -> None:
        """doctor no puede escribir la configuración de clínica (403)."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant)
        client = _member_client(tenant, "doctor")

        with _tenant_context(tenant):
            resp = client.put(
                CLINIC_CONFIG_URL,
                data={"doctors_see_costs": True},
                format="json",
            )

        assert resp.status_code == 403

    def test_flag_appears_in_output_for_owner(self, db: None) -> None:
        """El campo doctors_see_costs aparece en la respuesta GET de config."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=True)
        client = _owner_client(tenant)

        with _tenant_context(tenant):
            resp = client.get(CLINIC_CONFIG_URL)

        assert resp.status_code == 200
        assert "doctors_see_costs" in resp.json()
        assert resp.json()["doctors_see_costs"] is True

    def test_owner_can_disable_flag(self, db: None) -> None:
        """owner puede desactivar el flag (True → False)."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=True)
        client = _owner_client(tenant)

        with _tenant_context(tenant):
            resp = client.put(
                CLINIC_CONFIG_URL,
                data={"doctors_see_costs": False},
                format="json",
            )

        assert resp.status_code == 200
        assert resp.json()["doctors_see_costs"] is False


# ===========================================================================
# 2. Permiso condicional: estado de cuenta
# ===========================================================================


class TestAccountStatementPermissions:
    """Verifica PatientStatementPermission en AccountStatementApi."""

    def test_finance_can_view_statement_without_flag(self, db: None) -> None:
        """finance siempre puede ver el estado de cuenta, sin importar el flag."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        # Sin ClinicSettings (flag False implícito)
        client = _member_client(tenant, "finance")

        with _tenant_context(tenant):
            resp = client.get(_statement_url(patient.id))

        assert resp.status_code == 200

    def test_owner_can_view_statement_without_flag(self, db: None) -> None:
        """owner siempre puede ver el estado de cuenta."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _owner_client(tenant)

        with _tenant_context(tenant):
            resp = client.get(_statement_url(patient.id))

        assert resp.status_code == 200

    def test_reception_can_view_statement_without_flag(self, db: None) -> None:
        """reception está en FINANCE_VIEW_ROLES: ve estado de cuenta siempre."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _member_client(tenant, "reception")

        with _tenant_context(tenant):
            resp = client.get(_statement_url(patient.id))

        assert resp.status_code == 200

    def test_doctor_without_flag_gets_403(self, db: None) -> None:
        """doctor SIN flag doctors_see_costs → 403 en estado de cuenta."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=False)
        client = _member_client(tenant, "doctor")

        with _tenant_context(tenant):
            resp = client.get(_statement_url(patient.id))

        assert resp.status_code == 403

    def test_doctor_with_flag_gets_200(self, db: None) -> None:
        """doctor CON flag doctors_see_costs → 200 en estado de cuenta."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=True)
        client = _member_client(tenant, "doctor")

        with _tenant_context(tenant):
            resp = client.get(_statement_url(patient.id))

        assert resp.status_code == 200

    def test_nurse_without_flag_gets_403(self, db: None) -> None:
        """nurse no está en FINANCE_VIEW_ROLES ni es doctor: siempre 403."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=True)
        client = _member_client(tenant, "nurse")

        with _tenant_context(tenant):
            resp = client.get(_statement_url(patient.id))

        assert resp.status_code == 403

    def test_doctor_without_clinic_settings_gets_403(self, db: None) -> None:
        """Si no existe ClinicSettings (flag = None), doctor recibe 403."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        # No creamos ClinicSettings → flag = False implícito
        client = _member_client(tenant, "doctor")

        with _tenant_context(tenant):
            resp = client.get(_statement_url(patient.id))

        assert resp.status_code == 403

    def test_unauthenticated_gets_401(self, db: None) -> None:
        """Sin autenticación → 401."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with _tenant_context(tenant):
            resp = APIClient().get(_statement_url(patient.id))

        assert resp.status_code == 401


# ===========================================================================
# 3. Permiso condicional: GET de cargos
# ===========================================================================


class TestChargeListPermissions:
    """Verifica ChargeListPermission en ChargeListCreateApi (GET)."""

    def test_finance_can_list_charges_without_flag(self, db: None) -> None:
        """finance siempre puede listar cargos."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL)

        assert resp.status_code == 200

    def test_doctor_without_flag_cannot_list_charges(self, db: None) -> None:
        """doctor SIN flag → 403 en GET /finanzas/cargos/."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=False)
        client = _member_client(tenant, "doctor")

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL)

        assert resp.status_code == 403

    def test_doctor_with_flag_can_list_charges(self, db: None) -> None:
        """doctor CON flag → 200 en GET /finanzas/cargos/."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=True)
        client = _member_client(tenant, "doctor")

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL)

        assert resp.status_code == 200

    def test_doctor_with_flag_cannot_create_charge(self, db: None) -> None:
        """El flag solo abre GET, NO POST. doctor sigue sin poder crear cargos."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=True)
        client = _member_client(tenant, "doctor")

        with _tenant_context(tenant):
            resp = client.post(
                CHARGES_URL,
                data={
                    "patient_id": str(patient.id),
                    "description": "Intento inválido",
                    "amount": "500.00",
                },
                format="json",
            )

        assert resp.status_code == 403

    def test_nurse_with_flag_cannot_list_charges(self, db: None) -> None:
        """nurse no es FINANCE_VIEW ni doctor: 403 aunque el flag esté activo."""
        tenant = TenantFactory()
        ClinicSettingsFactory(tenant=tenant, doctors_see_costs=True)
        client = _member_client(tenant, "nurse")

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL)

        assert resp.status_code == 403

    def test_readonly_can_list_charges_without_flag(self, db: None) -> None:
        """readonly está en FINANCE_VIEW_ROLES: puede listar cargos siempre."""
        tenant = TenantFactory()
        client = _member_client(tenant, "readonly")

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL)

        assert resp.status_code == 200


# ===========================================================================
# 4. Filtro ?appointment en GET /finanzas/cargos/
# ===========================================================================


class TestChargeFilterByAppointment:
    """Verifica que ?appointment=<uuid> filtra correctamente los cargos."""

    def test_filter_returns_only_charges_of_that_appointment(self, db: None) -> None:
        """Solo se devuelven los cargos con appointment=<id>; los sin cita se excluyen."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        appointment = AppointmentFactory(tenant=tenant, patient=patient)

        # Cargo ligado a la cita
        charge_with_appt = ChargeFactory(
            tenant=tenant,
            patient=patient,
            appointment=appointment,
        )
        # Cargo sin cita del mismo paciente
        ChargeFactory(tenant=tenant, patient=patient, appointment=None)

        client = _member_client(tenant, "finance")

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL, {"appointment": str(appointment.id)})

        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["results"]]
        assert str(charge_with_appt.id) in ids
        assert len(ids) == 1

    def test_filter_excludes_charges_of_other_appointment(self, db: None) -> None:
        """Cargos de otra cita no aparecen al filtrar por appointment."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        appt_a = AppointmentFactory(tenant=tenant, patient=patient)
        appt_b = AppointmentFactory(tenant=tenant, patient=patient)

        charge_a = ChargeFactory(tenant=tenant, patient=patient, appointment=appt_a)
        ChargeFactory(tenant=tenant, patient=patient, appointment=appt_b)

        client = _member_client(tenant, "finance")

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL, {"appointment": str(appt_a.id)})

        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["results"]]
        assert str(charge_a.id) in ids
        assert len(ids) == 1

    def test_invalid_appointment_uuid_returns_400(self, db: None) -> None:
        """Si ?appointment no es un UUID válido → 400 Bad Request."""
        tenant = TenantFactory()
        client = _member_client(tenant, "finance")

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL, {"appointment": "not-a-uuid"})

        assert resp.status_code == 400
        assert "appointment" in resp.json()["detail"].lower()

    def test_appointment_filter_returns_empty_for_unknown_appointment(self, db: None) -> None:
        """UUID válido pero sin cargos → lista vacía (no error)."""
        tenant = TenantFactory()
        PatientFactory(tenant=tenant)
        client = _member_client(tenant, "finance")
        unknown_id = uuid.uuid4()

        with _tenant_context(tenant):
            resp = client.get(CHARGES_URL, {"appointment": str(unknown_id)})

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_filter_combined_with_patient_id(self, db: None) -> None:
        """Filtros ?patient_id y ?appointment se pueden combinar."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        appointment = AppointmentFactory(tenant=tenant, patient=patient)

        target = ChargeFactory(
            tenant=tenant,
            patient=patient,
            appointment=appointment,
        )
        # Cargo de otro paciente con la misma cita (imposible en prod, pero defensivo)
        other_patient = PatientFactory(tenant=tenant)
        ChargeFactory(tenant=tenant, patient=other_patient, appointment=appointment)

        client = _member_client(tenant, "finance")

        with _tenant_context(tenant):
            resp = client.get(
                CHARGES_URL,
                {"patient_id": str(patient.id), "appointment": str(appointment.id)},
            )

        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["results"]]
        assert str(target.id) in ids
        assert len(ids) == 1
