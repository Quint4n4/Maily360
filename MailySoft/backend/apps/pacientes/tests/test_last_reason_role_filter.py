"""
Tests de regresión — fuga de dato clínico por rol en Patient.last_reason (FIX crítico).

Contexto del bug (auditoría de seguridad):
    apps/pacientes/serializers.py exponía `last_reason` (motivo de la última cita
    cancelada/reagendada del paciente) a TODOS los roles porque
    PatientPermission.GET = ALL_ROLES. Pero Appointment.reason es información
    clínica y AppointmentPermission.GET excluye deliberadamente a Role.FINANCE.
    Un usuario `finance` podía ver motivos clínicos vía GET /pacientes/ aunque
    el endpoint de citas se los niegue.

Corrección: PatientOutputSerializer.get_last_reason ahora es fail-closed y solo
expone el motivo si `request.active_role` está en
apps.core.permissions.APPOINTMENT_VIEW_ROLES (el MISMO conjunto que usa
AppointmentPermission.GET).

Patrón: AAA. Todas tocan BD → fixture db.
"""

from typing import Any

import pytest

from apps.agenda.models import Appointment
from apps.pacientes.serializers import PatientOutputSerializer
from tests.factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    TenantFactory,
)

from .test_apis import LIST_URL, _make_member_client, _tenant_context

_MOTIVO_CLINICO = "Dolor de muela persistente"


def _cancelled_appointment_with_reason(tenant: Any, patient: Any, reason: str) -> Appointment:
    """Crea una cita cancelada con un motivo clínico, para poblar last_reason."""
    doctor = DoctorFactory(tenant=tenant)
    return AppointmentFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        consultorio=None,
        status=Appointment.Status.CANCELLED,
        reason=reason,
    )


# ===========================================================================
# GET /api/v1/pacientes/ — last_reason filtrado por rol
# ===========================================================================


class TestLastReasonHiddenFromFinance:
    """El rol finance NUNCA debe recibir last_reason, aunque el paciente tenga
    una cita cancelada con motivo (mismo criterio que AppointmentPermission.GET,
    que excluye a FINANCE por tratarse de información clínica)."""

    def test_last_reason_is_none_for_finance_role_in_list(self, db: None) -> None:
        """GET /pacientes/ con rol finance → last_reason es None."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment_with_reason(tenant, patient, _MOTIVO_CLINICO)
        client = _make_member_client(tenant, role="finance")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "potential"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 1
        assert results[0]["id"] == str(patient.id)
        assert results[0]["last_reason"] is None

    def test_last_reason_is_none_for_finance_role_in_detail(self, db: None) -> None:
        """GET /pacientes/<id>/ con rol finance → last_reason es None."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment_with_reason(tenant, patient, _MOTIVO_CLINICO)
        client = _make_member_client(tenant, role="finance")

        # Act
        with _tenant_context(tenant):
            response = client.get(f"/api/v1/pacientes/{patient.id}/")

        # Assert
        assert response.status_code == 200
        # En el detalle individual no hay anotación (patient_get no anota),
        # así que ya era None por diseño; el test documenta ese comportamiento
        # y protege contra una futura anotación en patient_get que reabra el bug.
        assert response.json()["last_reason"] is None


class TestLastReasonVisibleForClinicalRoles:
    """Los roles con acceso a citas (AppointmentPermission.GET) sí deben ver
    el motivo: owner, admin, doctor, nurse, reception, readonly."""

    @pytest.mark.parametrize("role", ["doctor", "reception", "nurse", "owner", "admin", "readonly"])
    def test_last_reason_shows_motivo_for_appointment_view_roles(self, db: None, role: str) -> None:
        """GET /pacientes/ con un rol de APPOINTMENT_VIEW_ROLES → last_reason presente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment_with_reason(tenant, patient, _MOTIVO_CLINICO)
        client = _make_member_client(tenant, role=role)

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "potential"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 1
        assert results[0]["last_reason"] == _MOTIVO_CLINICO


class TestLastReasonSerializerFailClosed:
    """Unit tests directos del serializer (sin pasar por la API) para el
    comportamiento fail-closed cuando no hay request/rol en el contexto."""

    def test_get_last_reason_returns_none_without_request_in_context(self, db: None) -> None:
        """Sin 'request' en el contexto (p. ej. serialización desde un script
        o management command) → None, nunca el dato crudo."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        patient.last_reason = _MOTIVO_CLINICO  # simula la anotación del selector

        # Act
        serializer = PatientOutputSerializer(patient)  # sin context

        # Assert
        assert serializer.data["last_reason"] is None

    def test_get_last_reason_returns_none_when_active_role_missing(self, db: None) -> None:
        """Con 'request' en el contexto pero sin active_role resuelto → None."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        patient.last_reason = _MOTIVO_CLINICO

        class _FakeRequest:
            """Doble simple sin el atributo active_role."""

        # Act
        serializer = PatientOutputSerializer(patient, context={"request": _FakeRequest()})

        # Assert
        assert serializer.data["last_reason"] is None

    def test_get_last_reason_returns_value_when_role_authorized(self, db: None) -> None:
        """Con active_role autorizado (p. ej. doctor) → expone el motivo."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        patient.last_reason = _MOTIVO_CLINICO

        class _FakeRequest:
            active_role = "doctor"

        # Act
        serializer = PatientOutputSerializer(patient, context={"request": _FakeRequest()})

        # Assert
        assert serializer.data["last_reason"] == _MOTIVO_CLINICO

    def test_get_last_reason_returns_none_when_role_is_finance(self, db: None) -> None:
        """Con active_role='finance' explícito → None (fail-closed reforzado)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        patient.last_reason = _MOTIVO_CLINICO

        class _FakeRequest:
            active_role = "finance"

        # Act
        serializer = PatientOutputSerializer(patient, context={"request": _FakeRequest()})

        # Assert
        assert serializer.data["last_reason"] is None


# ===========================================================================
# Aislamiento cross-tenant (cinturón y tirantes)
# ===========================================================================


class TestLastReasonCrossTenantIsolation:
    """Un paciente del tenant A nunca debe recibir el last_reason de una cita
    del tenant B, ni siquiera con un rol autorizado a verlo."""

    def test_patient_never_receives_last_reason_from_other_tenant_appointment(
        self, db: None
    ) -> None:
        """El paciente del tenant A tiene last_reason=None; el motivo del
        paciente del tenant B ('SECRETO-TENANT-B') nunca aparece en la
        respuesta del tenant A, aunque el rol (doctor) sí tendría permiso
        para ver motivos de cita."""
        # Arrange — tenant A: paciente SIN citas.
        tenant_a = TenantFactory()
        patient_a = PatientFactory(tenant=tenant_a, is_active=True)

        # tenant B: paciente distinto con cita cancelada y motivo sensible.
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b, is_active=True)
        _cancelled_appointment_with_reason(tenant_b, patient_b, "SECRETO-TENANT-B")

        client = _make_member_client(tenant_a, role="doctor")

        # Act — listar pacientes en el contexto del tenant A.
        with _tenant_context(tenant_a):
            response = client.get(LIST_URL)

        # Assert — solo aparece el paciente de A, y su last_reason es None;
        # el motivo del tenant B jamás llega a la respuesta.
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 1
        assert results[0]["id"] == str(patient_a.id)
        assert results[0]["last_reason"] is None
        body_text = response.content.decode("utf-8")
        assert "SECRETO-TENANT-B" not in body_text

    def test_last_reason_annotation_scoped_to_own_patient_even_with_shared_tenant_role(
        self, db: None
    ) -> None:
        """Doble verificación a nivel selector: dos pacientes del MISMO tenant,
        cada uno con su propio motivo, nunca se cruzan entre sí."""
        from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
        from apps.pacientes.selectors import patient_list

        # Arrange
        tenant = TenantFactory()
        patient_1 = PatientFactory(tenant=tenant, is_active=True)
        patient_2 = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment_with_reason(tenant, patient_1, "Motivo de paciente 1")
        _cancelled_appointment_with_reason(tenant, patient_2, "Motivo de paciente 2")

        set_current_tenant(tenant)
        set_tenant_context_active(True)
        try:
            # Act
            qs = patient_list(segment="potential")
            r1 = qs.get(id=patient_1.id)
            r2 = qs.get(id=patient_2.id)

            # Assert — cada quien con el suyo, nunca el del otro.
            assert r1.last_reason == "Motivo de paciente 1"
            assert r2.last_reason == "Motivo de paciente 2"
        finally:
            set_current_tenant(None)
            set_tenant_context_active(False)
