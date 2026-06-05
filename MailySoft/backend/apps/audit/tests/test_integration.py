"""
Tests de integración: verifican que los services de negocio REALMENTE escriben
entradas en la bitácora de auditoría.

Estrategia: contar AuditLog.all_objects antes y después de llamar al service.
Si el conteo no sube, el service no está auditando (bug).

Se usa all_objects (manager sin filtro de tenant) para contar todos los logs
creados, independientemente del contexto de tenant activo.

Casos especiales:
  - test_login_failed_writes_audit: dispara user_login_failed vía señal.
  - test_login_writes_audit: hace POST real al endpoint de login con JWT.
  - test_audit_metadata_has_no_pii: verifica que el log de patient_update
    NO contiene teléfono/CURP/nombre en metadata (solo changed_fields).

Anti-empalme de agenda: todos los AppointmentFactory.create_batch o
appointment_create se crean con horarios únicos por diseño de la factory
(Sequence que avanza 1 hora por call) o con starts_at explícito y diferente.

Patrón: AAA. Todos tocan BD → fixture db.
"""

import datetime
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from django.contrib.auth.signals import user_login_failed
from rest_framework.test import APIClient

from apps.agenda.models import Appointment
from apps.agenda.services import appointment_change_status, appointment_create
from apps.audit.models import ActionType, AuditLog
from apps.audit.signals import handle_login_failed
from apps.core.tenant_context import (
    set_current_tenant,
    set_tenant_context_active,
)
from apps.pacientes.services import patient_create, patient_deactivate, patient_update
from apps.personal.services import doctor_create
from tests.factories import (
    AppointmentFactory,
    ConsultorioFactory,
    DoctorFactory,
    DoctorScheduleFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_logs() -> int:
    """Cuenta todos los AuditLog en BD sin filtro de tenant."""
    return AuditLog.all_objects.count()


def _latest_log_for_action(action: str) -> "AuditLog | None":
    """Devuelve el log más reciente para una acción dada (sin filtro de tenant)."""
    return AuditLog.all_objects.filter(action=action).order_by("-created_at").first()


def _activate_tenant(tenant: Any) -> None:
    """Activa el contexto de tenant en el thread-local."""
    set_current_tenant(tenant)
    set_tenant_context_active(True)


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Context manager que simula TenantMiddleware/TenantAPIView para los mocks."""
    with (
        patch(
            "apps.core.managers.get_current_tenant",
            return_value=tenant,
        ),
        patch(
            "apps.core.managers.is_tenant_context_active",
            return_value=True,
        ),
    ):
        _activate_tenant(tenant)
        yield


# ===========================================================================
# Pacientes
# ===========================================================================


class TestPatientServicesAudit:
    """Los services de pacientes escriben el log correcto en la bitácora."""

    def test_patient_create_writes_audit(self, db: None) -> None:
        """patient_create genera un log PATIENT_CREATE con el resource_id correcto."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        _activate_tenant(tenant)
        before = _count_logs()

        # Act
        patient = patient_create(
            tenant=tenant,
            user=user,
            first_name="Carmen",
            paternal_surname="Salinas",
            maternal_surname="Pérez",
            date_of_birth=datetime.date(1985, 3, 20),
            sex="F",
            phone="5512340100",
        )

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.PATIENT_CREATE)
        assert log is not None
        assert log.resource_id == patient.id
        assert log.resource_type == "Patient"
        assert log.tenant_id == tenant.id
        assert log.actor_id == user.id

    def test_patient_update_writes_audit_with_changed_fields(
        self, db: None
    ) -> None:
        """patient_update genera un log PATIENT_UPDATE con metadata.changed_fields."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        _activate_tenant(tenant)
        patient = PatientFactory(tenant=tenant)
        before = _count_logs()

        # Act
        patient_update(
            patient=patient,
            user=user,
            first_name="NuevoNombre",
            phone="5512340200",
        )

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.PATIENT_UPDATE)
        assert log is not None
        assert log.resource_id == patient.id
        assert "changed_fields" in log.metadata
        # Los campos modificados deben estar en changed_fields (ordenados)
        changed = log.metadata["changed_fields"]
        assert "first_name" in changed
        assert "phone" in changed

    def test_patient_deactivate_writes_audit(self, db: None) -> None:
        """patient_deactivate genera un log PATIENT_DEACTIVATE."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        _activate_tenant(tenant)
        patient = PatientFactory(tenant=tenant, is_active=True)
        before = _count_logs()

        # Act
        patient_deactivate(patient=patient, _user=user)

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.PATIENT_DEACTIVATE)
        assert log is not None
        assert log.resource_id == patient.id
        assert log.actor_id == user.id

    def test_patient_detail_get_writes_patient_read_via_api(
        self, db: None
    ) -> None:
        """GET /api/v1/pacientes/<id>/ genera un log PATIENT_READ con el actor correcto."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=True)
        patient = PatientFactory(tenant=tenant)
        before = _count_logs()

        client = APIClient()
        client.force_authenticate(user=user)

        # Act — simular el contexto de tenant que TenantAPIView inyectaría
        with (
            patch("apps.pacientes.views.get_current_tenant", return_value=tenant),
            patch("apps.core.managers.get_current_tenant", return_value=tenant),
            patch("apps.core.managers.is_tenant_context_active", return_value=True),
        ):
            _activate_tenant(tenant)
            response = client.get(f"/api/v1/pacientes/{patient.id}/")

        # Assert
        assert response.status_code == 200
        assert _count_logs() == before + 1

        log = _latest_log_for_action(ActionType.PATIENT_READ)
        assert log is not None
        assert log.resource_id == patient.id
        assert log.actor_id == user.id


# ===========================================================================
# No-PII en metadata
# ===========================================================================


class TestAuditMetadataHasNoPii:
    """Verificar que los logs de actualización de paciente no contienen PII en metadata."""

    def test_audit_metadata_has_no_pii_after_patient_update(
        self, db: None
    ) -> None:
        """El log de PATIENT_UPDATE solo contiene changed_fields en metadata.

        No debe contener teléfono, CURP, nombre ni otros datos personales.
        Si este test falla, hay una fuga de PII en la bitácora (bug crítico).
        """
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        _activate_tenant(tenant)
        patient = PatientFactory(
            tenant=tenant,
            curp="SAPM850320HDFXXX01",
            phone="5599887766",
            first_name="Secreto",
        )

        # Act
        patient_update(
            patient=patient,
            user=user,
            first_name="NombreActualizado",
            phone="5512340300",
        )

        # Assert
        log = _latest_log_for_action(ActionType.PATIENT_UPDATE)
        assert log is not None

        metadata_str = str(log.metadata)
        # La metadata no debe contener valores de PII del paciente
        assert "5599887766" not in metadata_str, "BUG: teléfono anterior en metadata"
        assert "5512340300" not in metadata_str, "BUG: teléfono nuevo en metadata"
        assert "Secreto" not in metadata_str, "BUG: nombre anterior en metadata"
        assert "NombreActualizado" not in metadata_str, "BUG: nombre nuevo en metadata"
        assert "SAPM850320" not in metadata_str, "BUG: CURP en metadata"

        # Solo debe contener changed_fields (lista de nombres de campos)
        assert "changed_fields" in log.metadata
        assert isinstance(log.metadata["changed_fields"], list)


# ===========================================================================
# Citas
# ===========================================================================


class TestAppointmentServicesAudit:
    """Los services de agenda escriben el log correcto en la bitácora."""

    def test_appointment_create_writes_audit(self, db: None) -> None:
        """appointment_create genera un log APPOINTMENT_CREATE."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        _activate_tenant(tenant)

        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        before = _count_logs()

        # Act — horario a futuro lejano para evitar conflictos con otras factories
        starts_at = datetime.datetime(2035, 6, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        appointment = appointment_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            doctor_id=doctor.id,
            starts_at=starts_at,
            reason="Consulta de integración",
        )

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.APPOINTMENT_CREATE)
        assert log is not None
        assert log.resource_id == appointment.id
        assert log.resource_type == "Appointment"
        assert log.actor_id == user.id

    def test_appointment_change_status_writes_audit_with_old_new_status(
        self, db: None
    ) -> None:
        """appointment_change_status genera APPOINTMENT_STATUS con old/new_status en metadata."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        _activate_tenant(tenant)

        # Crear cita con horario único para este test
        starts_at = datetime.datetime(2035, 7, 15, 14, 0, 0, tzinfo=datetime.timezone.utc)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appointment = appointment_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            doctor_id=doctor.id,
            starts_at=starts_at,
            reason="Cita para test de status",
        )
        before = _count_logs()

        # Act — cambiar de SCHEDULED a CONFIRMED
        appointment_change_status(
            appointment=appointment,
            user=user,
            new_status=Appointment.Status.CONFIRMED,
        )

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.APPOINTMENT_STATUS)
        assert log is not None
        assert log.resource_id == appointment.id
        assert log.metadata.get("old_status") == Appointment.Status.SCHEDULED
        assert log.metadata.get("new_status") == Appointment.Status.CONFIRMED


# ===========================================================================
# Personal — Doctor
# ===========================================================================


class TestDoctorServicesAudit:
    """Los services de personal escriben el log correcto en la bitácora."""

    def test_doctor_create_writes_audit(self, db: None) -> None:
        """doctor_create genera un log DOCTOR_CREATE con el resource_id correcto."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        _activate_tenant(tenant)

        # Crear membresía de médico para poder crear el Doctor
        membership = TenantMembershipFactory(
            tenant=tenant, role="doctor", is_active=True
        )
        before = _count_logs()

        # Act
        doctor = doctor_create(
            tenant=tenant,
            user=user,
            membership=membership,
            specialty="Cardiología",
        )

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.DOCTOR_CREATE)
        assert log is not None
        assert log.resource_id == doctor.id
        assert log.resource_type == "Doctor"
        assert log.actor_id == user.id
        assert log.tenant_id == tenant.id


# ===========================================================================
# Autenticación — Login y Login fallido
# ===========================================================================


class TestLoginAudit:
    """Los eventos de login exitoso y fallido se registran en la bitácora."""

    def test_login_writes_audit(self, db: None) -> None:
        """POST /api/v1/auth/login/ exitoso genera un log LOGIN."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory(email="login_test@clinic.test")
        user.set_password("pass-segura-456")
        user.save(update_fields=["password"])
        TenantMembershipFactory(user=user, tenant=tenant, role="owner", is_active=True)

        client = APIClient()
        before = _count_logs()

        # Act
        response = client.post(
            "/api/v1/auth/login/",
            {"email": "login_test@clinic.test", "password": "pass-segura-456"},
            format="json",
        )

        # Assert
        assert response.status_code == 200, f"Login falló: {response.data}"
        assert _count_logs() > before

        log = _latest_log_for_action(ActionType.LOGIN)
        assert log is not None
        assert log.actor_id == user.id

    def test_login_failed_writes_audit(self, db: None) -> None:
        """POST /api/v1/auth/login/ con password incorrecta genera LOGIN_FAILED."""
        # Arrange
        UserFactory(email="fail_test@clinic.test")
        client = APIClient()
        before = _count_logs()

        # Act
        response = client.post(
            "/api/v1/auth/login/",
            {"email": "fail_test@clinic.test", "password": "clave-INCORRECTA"},
            format="json",
        )

        # Assert — el login falla (401) y se genera LOGIN_FAILED
        assert response.status_code == 401
        assert _count_logs() > before

        log = _latest_log_for_action(ActionType.LOGIN_FAILED)
        assert log is not None
        # El actor es None en un intento fallido (usuario no resuelto)
        assert log.actor_id is None
        # El tenant también es None
        assert log.tenant_id is None

    def test_login_failed_does_not_store_password(self, db: None) -> None:
        """El log de LOGIN_FAILED NO contiene la contraseña en ningún campo.

        Si este test falla, hay una fuga de credenciales en la bitácora (bug crítico).
        """
        # Arrange
        password_secret = "mi-clave-ultrasecreta-999"
        client = APIClient()

        # Act
        client.post(
            "/api/v1/auth/login/",
            {"email": "noexiste@clinic.test", "password": password_secret},
            format="json",
        )

        # Assert — buscar la contraseña en TODOS los campos del log
        log = _latest_log_for_action(ActionType.LOGIN_FAILED)
        if log is None:
            pytest.skip("No se creó log LOGIN_FAILED — revisar señal handle_login_failed")

        fields_to_check = {
            "description": log.description,
            "metadata": str(log.metadata),
            "resource_repr": log.resource_repr,
            "actor_role": log.actor_role,
            "request_id": log.request_id,
            "user_agent": log.user_agent,
        }

        for field_name, field_value in fields_to_check.items():
            assert password_secret not in str(field_value), (
                f"BUG DE SEGURIDAD: la contraseña aparece en el campo '{field_name}' "
                f"del log de LOGIN_FAILED"
            )

    def test_login_failed_via_signal_directly(self, db: None) -> None:
        """La señal handle_login_failed crea un log LOGIN_FAILED directamente."""
        # Arrange — simular una petición mínima sin HTTP real
        before = _count_logs()

        class FakeRequest:
            META = {
                "REMOTE_ADDR": "10.0.0.1",
                "HTTP_USER_AGENT": "TestAgent/1.0",
            }

        credentials = {"username": "hacker@bad.com", "password": "intento"}

        # Act — disparar la señal directamente
        handle_login_failed(
            sender=object,
            credentials=credentials,
            request=FakeRequest(),
        )

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.LOGIN_FAILED)
        assert log is not None
        # La contraseña NO debe estar en ningún campo
        assert "intento" not in str(log.metadata)
        assert "intento" not in log.description
        # El email NO se guarda en claro (PII): se guarda un hash corto (email_hint).
        assert "hacker@bad.com" not in str(log.metadata)
        assert "hacker@bad.com" not in log.description
        import hashlib
        expected_hint = hashlib.sha256("hacker@bad.com".encode()).hexdigest()[:16]
        assert log.metadata.get("email_hint") == expected_hint

    def test_login_failed_via_signal_with_x_forwarded_for(self, db: None) -> None:
        """handle_login_failed lee la IP del header X-Forwarded-For cuando está presente.

        Cubre la rama de signals.py línea 59: ip_address = x_forwarded.split(",")[0].strip()
        """
        # Arrange
        before = _count_logs()

        class FakeRequestWithProxy:
            META = {
                "HTTP_X_FORWARDED_FOR": "203.0.113.5, 10.0.0.1",
                "REMOTE_ADDR": "10.0.0.1",
                "HTTP_USER_AGENT": "ProxyAgent/2.0",
            }

        credentials = {"username": "proxied@test.com", "password": "ignorada"}

        # Act
        handle_login_failed(
            sender=object,
            credentials=credentials,
            request=FakeRequestWithProxy(),
        )

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.LOGIN_FAILED)
        assert log is not None
        # La IP debe ser la primera del X-Forwarded-For (el cliente real)
        assert log.ip_address == "203.0.113.5"

    def test_login_failed_via_signal_without_request(self, db: None) -> None:
        """handle_login_failed con request=None crea log sin ip/user_agent.

        Cubre la rama del signals.py donde ip_address y user_agent están vacíos
        (request is None) y el bloque 'if ip_address or user_agent' NO se ejecuta.
        """
        # Arrange
        before = _count_logs()
        credentials = {"username": "norequest@test.com", "password": "ignorada"}

        # Act — request=None simula el caso de llamada sin contexto HTTP
        handle_login_failed(
            sender=object,
            credentials=credentials,
            request=None,
        )

        # Assert
        assert _count_logs() == before + 1
        log = _latest_log_for_action(ActionType.LOGIN_FAILED)
        assert log is not None
        assert log.ip_address is None
        assert log.user_agent == ""
