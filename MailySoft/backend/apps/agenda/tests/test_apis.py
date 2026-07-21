"""
Tests de las APIs de la app agenda (views.py).

Cubre:
- Autenticación requerida (401) en todos los endpoints principales.
- TestAppointmentJWTIsolation: JWT real, GET /citas/ solo retorna citas del tenant propio.
- POST /agenda/citas/ → 201 creación correcta.
- POST /agenda/citas/<id>/estado/ → 200 transición válida; 400 transición inválida.
- PATCH /agenda/citas/<id>/ con status en el body → el estado NO cambia (regla 1).
- DELETE /agenda/citas/<id>/ → status=cancelled, no borrado físico (204).
- GET /agenda/citas/<id>/ de otro tenant → 404 (no 403, no revelar existencia).

Patrón: AAA. Todas tocan BD → fixture db.

Nota sobre contexto de tenant con force_authenticate:
  Mismo patrón que personal/pacientes — se mockea get_current_tenant en el módulo
  de la vista de agenda y el TenantManager para inyectar el tenant directamente.
  Para el flujo JWT REAL (TestAppointmentJWTIsolation) se usa token obtenido
  vía POST /api/v1/auth/login/ sin ningún mock.
"""

import datetime
import uuid as uuid_module
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.agenda.models import Appointment
from apps.agenda.selectors import agenda_config_get
from tests.factories import (
    AppointmentFactory,
    ConsultorioFactory,
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Helper adicional con membresía
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Constantes de URLs
# ---------------------------------------------------------------------------

CITAS_LIST_URL = "/api/v1/agenda/citas/"
AGENDA_CONFIG_URL = "/api/v1/agenda/config/"

_BASE_DT = datetime.datetime(2030, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _cita_detail_url(appt_id: Any) -> str:
    return f"/api/v1/agenda/citas/{appt_id}/"


def _cita_estado_url(appt_id: Any) -> str:
    return f"/api/v1/agenda/citas/{appt_id}/estado/"


def _cita_reagendar_url(appt_id: Any) -> str:
    return f"/api/v1/agenda/citas/{appt_id}/reagendar/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el efecto completo del TenantMiddleware para tests con force_authenticate."""
    with (
        patch(
            "apps.agenda.views.get_current_tenant",
            return_value=tenant,
        ),
        patch(
            "apps.core.managers.get_current_tenant",
            return_value=tenant,
        ),
        patch(
            "apps.core.managers.is_tenant_context_active",
            return_value=True,
        ),
    ):
        yield


def _make_auth_client(user: Any) -> APIClient:
    """Devuelve un APIClient autenticado como `user`."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_member_client(tenant: Any, role: str = "owner") -> APIClient:
    """Crea un user con TenantMembership del rol indicado y devuelve un cliente autenticado.

    Necesario desde que se activó el enforcement de permisos por rol (AppointmentPermission,
    AppointmentStatusPermission, AgendaConfigPermission). Sin membership activa en el tenant,
    TenantAPIView adjunta active_role=None y HasClinicRole deniega la solicitud con 403.

    Args:
        tenant: el Tenant al que pertenece la membresía.
        role:   rol clínico requerido para la operación que se va a testear.

    Returns:
        APIClient autenticado como el user creado.
    """
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return _make_auth_client(user)


def _get_jwt_token(user: Any, password: str = "password-segura-123") -> str:
    """Obtiene un JWT real vía POST /api/v1/auth/login/."""
    login_client = APIClient()
    response = login_client.post(
        "/api/v1/auth/login/",
        data={"email": user.email, "password": password},
        format="json",
    )
    assert response.status_code == 200, f"Login fallido para {user.email}: {response.json()}"
    return response.json()["access"]


# ===========================================================================
# Autenticación requerida (401)
# ===========================================================================


class TestAgendaEndpointsRequireAuth:
    """Todos los endpoints de agenda requieren autenticación."""

    def test_list_appointments_requires_auth(self, db: None, api_client: APIClient) -> None:
        """GET /agenda/citas/ sin token devuelve 401."""
        response = api_client.get(CITAS_LIST_URL)
        assert response.status_code == 401

    def test_create_appointment_requires_auth(self, db: None, api_client: APIClient) -> None:
        """POST /agenda/citas/ sin token devuelve 401."""
        response = api_client.post(CITAS_LIST_URL, data={}, format="json")
        assert response.status_code == 401

    def test_get_appointment_detail_requires_auth(self, db: None, api_client: APIClient) -> None:
        """GET /agenda/citas/<id>/ sin token devuelve 401."""
        response = api_client.get(_cita_detail_url(uuid_module.uuid4()))
        assert response.status_code == 401

    def test_change_status_requires_auth(self, db: None, api_client: APIClient) -> None:
        """POST /agenda/citas/<id>/estado/ sin token devuelve 401."""
        response = api_client.post(_cita_estado_url(uuid_module.uuid4()), data={}, format="json")
        assert response.status_code == 401

    def test_agenda_config_requires_auth(self, db: None, api_client: APIClient) -> None:
        """GET /agenda/config/ sin token devuelve 401."""
        response = api_client.get(AGENDA_CONFIG_URL)
        assert response.status_code == 401


# ===========================================================================
# POST /agenda/citas/ — creación
# ===========================================================================


class TestAppointmentCreateApi:
    """POST /agenda/citas/ — creación de cita mediante API."""

    def test_create_appointment_via_api_201(self, db: None) -> None:
        """POST válido crea la cita y devuelve 201 con datos de la cita.

        Ajuste Paso 4: el user tiene rol 'reception' (incluido en POST de AppointmentPermission).
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        starts = _BASE_DT
        ends = starts + datetime.timedelta(hours=1)

        payload = {
            "patient_id": str(patient.id),
            "doctor_id": str(doctor.id),
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "reason": "Consulta inicial",
        }

        # Act
        with _tenant_context(tenant):
            response = client.post(CITAS_LIST_URL, data=payload, format="json")

        # Assert
        assert (
            response.status_code == 201
        ), f"Esperado 201, obtenido {response.status_code}: {response.json()}"
        data = response.json()
        assert data["status"] == Appointment.Status.SCHEDULED
        assert data["reason"] == "Consulta inicial"
        assert "id" in data

    def test_create_appointment_without_tenant_returns_403(self, db: None) -> None:
        """Sin tenant activo (contexto no inyectado) la vista retorna 403.

        Nota: con el enforcement de roles, este test sigue funcionando porque
        un user sin membership tiene active_role=None → HasClinicRole devuelve 403
        antes de llegar al check de tenant en la vista. El comportamiento observable
        (403) es idéntico.
        """
        # Arrange — user sin membership (active_role=None → 403 por HasClinicRole)
        user = UserFactory()
        client = _make_auth_client(user)

        # Act — sin mock de tenant
        response = client.post(
            CITAS_LIST_URL,
            data={
                "patient_id": str(uuid_module.uuid4()),
                "doctor_id": str(uuid_module.uuid4()),
                "starts_at": _BASE_DT.isoformat(),
                "reason": "Test",
            },
            format="json",
        )

        # Assert
        assert response.status_code == 403

    def test_create_appointment_missing_required_fields_returns_400(self, db: None) -> None:
        """POST sin campos requeridos (reason, patient_id) devuelve 400.

        Ajuste Paso 4: el user tiene rol 'reception' para pasar AppointmentPermission (POST).
        El 400 viene del InputSerializer, no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act — falta reason
        with _tenant_context(tenant):
            response = client.post(
                CITAS_LIST_URL,
                data={
                    "patient_id": str(uuid_module.uuid4()),
                    "doctor_id": str(uuid_module.uuid4()),
                    "starts_at": _BASE_DT.isoformat(),
                    # reason falta
                },
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_create_appointment_ends_before_starts_returns_400(self, db: None) -> None:
        """POST con ends_at < starts_at devuelve 400 (ValidationError del service).

        Ajuste Paso 4: el user tiene rol 'reception' para pasar AppointmentPermission (POST).
        El 400 viene del servicio (validación de rango), no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        starts = _BASE_DT
        bad_ends = starts - datetime.timedelta(hours=1)

        # Act
        with _tenant_context(tenant):
            response = client.post(
                CITAS_LIST_URL,
                data={
                    "patient_id": str(patient.id),
                    "doctor_id": str(doctor.id),
                    "starts_at": starts.isoformat(),
                    "ends_at": bad_ends.isoformat(),
                    "reason": "Inválido",
                },
                format="json",
            )

        # Assert
        assert response.status_code == 400


# ===========================================================================
# GET /agenda/citas/ — listado (autenticado)
# ===========================================================================


class TestAppointmentListApi:
    """GET /agenda/citas/ con autenticación."""

    def test_list_appointments_returns_200(self, db: None) -> None:
        """Usuario autenticado con tenant inyectado recibe 200 y lista paginada.

        Ajuste Paso 4: el user tiene rol 'readonly' (mínimo para GET en AppointmentPermission).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(CITAS_LIST_URL)

        # Assert
        assert response.status_code == 200

    def test_list_appointments_returns_only_own_tenant_citas(self, db: None) -> None:
        """GET /citas/ con tenant inyectado devuelve solo las citas de ese tenant.

        Ajuste Paso 4: el user tiene membresía en tenant_a (rol readonly) para
        pasar AppointmentPermission (GET). El aislamiento lo garantiza el ORM.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_a = DoctorFactory(tenant=tenant_a)
        patient_a = PatientFactory(tenant=tenant_a)
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_b = PatientFactory(tenant=tenant_b)

        AppointmentFactory.create_batch(
            2,
            tenant=tenant_a,
            doctor=doctor_a,
            patient=patient_a,
            consultorio=None,
        )
        AppointmentFactory(
            tenant=tenant_b,
            doctor=doctor_b,
            patient=patient_b,
            consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(days=1),
        )

        client = _make_member_client(tenant_a, role="readonly")

        # Act — con contexto del tenant_a
        with _tenant_context(tenant_a):
            response = client.get(CITAS_LIST_URL)

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 2, (
            f"Esperadas 2 citas del tenant A, obtenidas {len(results)}. "
            "Si son 3, hay fuga cross-tenant."
        )


# ===========================================================================
# POST /agenda/citas/<id>/estado/ — cambio de estado
# ===========================================================================


class TestAppointmentChangeStatusApi:
    """POST /agenda/citas/<id>/estado/ — máquina de estados vía API."""

    def test_change_status_valid_transition_returns_200(self, db: None) -> None:
        """Transición válida (scheduled→confirmed) devuelve 200 con el nuevo estado.

        Ajuste Paso 4: el user tiene rol 'reception' (incluido en POST de
        AppointmentStatusPermission según la matriz de roles).
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _cita_estado_url(appt.id),
                data={"status": Appointment.Status.CONFIRMED},
                format="json",
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == Appointment.Status.CONFIRMED

    def test_change_status_invalid_transition_returns_400(self, db: None) -> None:
        """Transición inválida (scheduled→attended) devuelve 400.

        Ajuste Paso 4: el user tiene rol 'nurse' (incluido en POST de
        AppointmentStatusPermission). El 400 viene del servicio (máquina de estados).
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant, role="nurse")

        # Act — scheduled → attended es inválido
        with _tenant_context(tenant):
            response = client.post(
                _cita_estado_url(appt.id),
                data={"status": Appointment.Status.ATTENDED},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_nurse_no_puede_cancelar_cita_returns_403(self, db: None) -> None:
        """Seguridad: enfermería NO puede cancelar una cita (scheduled→cancelled = 403)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant, role="nurse")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _cita_estado_url(appt.id),
                data={"status": Appointment.Status.CANCELLED},
                format="json",
            )

        # Assert — enfermería bloqueada; la cita no cambió
        assert response.status_code == 403
        appt.refresh_from_db()
        assert appt.status == Appointment.Status.SCHEDULED

    def test_reception_si_puede_cancelar_cita_returns_200(self, db: None) -> None:
        """Recepción SÍ puede cancelar (scheduled→cancelled = 200)."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _cita_estado_url(appt.id),
                data={"status": Appointment.Status.CANCELLED},
                format="json",
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == Appointment.Status.CANCELLED

    def test_change_status_nonexistent_appointment_returns_404(self, db: None) -> None:
        """UUID inexistente devuelve 404.

        Ajuste Paso 4: el user tiene rol 'reception' para pasar AppointmentStatusPermission.
        El 404 viene del selector (UUID no existe), no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        fake_id = uuid_module.uuid4()

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _cita_estado_url(fake_id),
                data={"status": Appointment.Status.CONFIRMED},
                format="json",
            )

        # Assert
        assert response.status_code == 404

    def test_change_status_invalid_status_value_returns_400(self, db: None) -> None:
        """Valor de status no válido devuelve 400 (error de serializer).

        Ajuste Paso 4: el user tiene rol 'reception' para pasar AppointmentStatusPermission.
        El 400 viene del serializer (ChoiceField), no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _cita_estado_url(appt.id),
                data={"status": "volando"},  # valor inválido
                format="json",
            )

        # Assert
        assert response.status_code == 400


# ===========================================================================
# PATCH /agenda/citas/<id>/ — campos editables; status NO cambia
# ===========================================================================


class TestAppointmentPatchApi:
    """PATCH /agenda/citas/<id>/ — actualización de campos editables."""

    def test_patch_appointment_cannot_change_status(self, db: None) -> None:
        """PATCH con {status: confirmed} NO cambia el estado (status no está en InputSerializer).

        El InputSerializer del PATCH solo acepta reason/specialty/notes.
        Enviar status lo ignora (partial=True → campo no reconocido se omite)
        y devuelve 400 porque s.validated_data queda vacío.

        Ajuste Paso 4: el user tiene rol 'reception' (incluido en PATCH de AppointmentPermission).
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant, role="reception")

        # Act — enviar solo status en el PATCH
        with _tenant_context(tenant):
            response = client.patch(
                _cita_detail_url(appt.id),
                data={"status": Appointment.Status.CONFIRMED},
                format="json",
            )

        # Assert — 400 (campo ignorado → validated_data vacío → "No se proporcionaron campos")
        assert response.status_code == 400

        # El status NO cambió en BD
        appt.refresh_from_db()
        assert appt.status == Appointment.Status.SCHEDULED

    def test_patch_appointment_allowed_field_updates_correctly(self, db: None) -> None:
        """PATCH con reason/notes válidos actualiza esos campos y devuelve 200.

        Ajuste Paso 4: el user tiene rol 'doctor' (incluido en PATCH de AppointmentPermission).
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            reason="Consulta inicial",
            notes="",
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant, role="doctor")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _cita_detail_url(appt.id),
                data={"reason": "Revisión de resultados", "notes": "Traer estudios."},
                format="json",
            )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["reason"] == "Revisión de resultados"
        assert data["notes"] == "Traer estudios."

    def test_patch_appointment_nonexistent_returns_404(self, db: None) -> None:
        """PATCH de UUID inexistente devuelve 404.

        Ajuste Paso 4: el user tiene rol 'reception' para pasar AppointmentPermission (PATCH).
        El 404 viene del selector (UUID no existe).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _cita_detail_url(uuid_module.uuid4()),
                data={"reason": "X"},
                format="json",
            )

        # Assert
        assert response.status_code == 404


# ===========================================================================
# DELETE /agenda/citas/<id>/ — cancelación (soft)
# ===========================================================================


class TestAppointmentDeleteApi:
    """DELETE /agenda/citas/<id>/ cancela la cita (no la borra físicamente)."""

    def test_delete_appointment_cancels_not_deletes(self, db: None) -> None:
        """DELETE → status=cancelled, registro físico permanece en BD.

        Ajuste Paso 4: el user tiene rol 'reception' (incluido en DELETE de
        AppointmentPermission = cancelar cita).
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
        )
        appt_id = appt.id
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.delete(_cita_detail_url(appt.id))

        # Assert — 204 No Content
        assert response.status_code == 204

        # El registro sigue en BD con status=cancelled (no borrado físico)
        appt.refresh_from_db()
        assert appt.status == Appointment.Status.CANCELLED
        assert Appointment.all_objects.filter(id=appt_id).exists()

    def test_delete_already_cancelled_returns_400(self, db: None) -> None:
        """DELETE de una cita ya cancelada devuelve 400 (transición inválida).

        Ajuste Paso 4: el user tiene rol 'reception' para pasar AppointmentPermission (DELETE).
        El 400 viene del servicio (máquina de estados), no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.CANCELLED,
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant, role="reception")

        # Act — intentar cancelar una cita ya cancelada
        with _tenant_context(tenant):
            response = client.delete(_cita_detail_url(appt.id))

        # Assert
        assert response.status_code == 400

    def test_delete_appointment_nonexistent_returns_404(self, db: None) -> None:
        """DELETE de UUID inexistente devuelve 404.

        Ajuste Paso 4: el user tiene rol 'owner' para pasar AppointmentPermission (DELETE).
        El 404 viene del selector (UUID no existe).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.delete(_cita_detail_url(uuid_module.uuid4()))

        # Assert
        assert response.status_code == 404

    def test_delete_appointment_cross_tenant_returns_404(self, db: None) -> None:
        """DELETE de una cita de otro tenant devuelve 404 (no 403, no revelar existencia).

        Ajuste Paso 4: el user tiene membresía en tenant_a (rol owner) para
        pasar AppointmentPermission (DELETE). El 404 viene del selector (ORM filtra).
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_b = PatientFactory(tenant=tenant_b)
        appt_b = AppointmentFactory(
            tenant=tenant_b,
            doctor=doctor_b,
            patient=patient_b,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT,
        )
        client = _make_member_client(tenant_a, role="owner")

        # Act — con contexto del tenant_a, intentar borrar cita del tenant_b
        with _tenant_context(tenant_a):
            response = client.delete(_cita_detail_url(appt_b.id))

        # Assert — 404, no 403 (no revelar existencia)
        assert response.status_code == 404

        # La cita del tenant_b sigue SCHEDULED (no fue modificada)
        appt_b.refresh_from_db()
        assert appt_b.status == Appointment.Status.SCHEDULED


# ===========================================================================
# JWT real — aislamiento cross-tenant (TestAppointmentJWTIsolation)
# ===========================================================================


class TestAppointmentJWTIsolation:
    """Verifica que el flujo JWT REAL aísla citas por tenant.

    Sin mock de tenant: obtiene token vía POST /api/v1/auth/login/ y lo usa
    en Authorization: Bearer. Si el test pasa, el tenant se resuelve
    correctamente desde el token JWT (TenantAPIView.initial()).
    """

    def test_jwt_auth_resolves_tenant_and_returns_own_citas(self, db: None) -> None:
        """Con JWT real, GET /agenda/citas/ devuelve solo citas del tenant del user.

        Flujo:
        1. Crea tenant A + user con membresía activa + 2 citas en A.
        2. Crea tenant B con 3 citas (otro tenant, no debe verse).
        3. Obtiene JWT real vía POST /api/v1/auth/login/.
        4. Llama GET /api/v1/agenda/citas/ con el Bearer token.
        5. Verifica: status 200, solo las 2 citas del tenant A.
        """
        # Arrange — tenant A: user con membresía activa
        tenant_a = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="admin", is_active=True)

        doctor_a = DoctorFactory(tenant=tenant_a)
        patient_a = PatientFactory(tenant=tenant_a)

        # 2 citas del tenant A (las que SÍ debe ver)
        AppointmentFactory(
            tenant=tenant_a,
            doctor=doctor_a,
            patient=patient_a,
            consultorio=None,
            starts_at=_BASE_DT,
        )
        AppointmentFactory(
            tenant=tenant_a,
            doctor=doctor_a,
            patient=patient_a,
            consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=2),
        )

        # Tenant B con 3 citas que NO debe ver
        tenant_b = TenantFactory()
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_b = PatientFactory(tenant=tenant_b)
        for i in range(3):
            AppointmentFactory(
                tenant=tenant_b,
                doctor=doctor_b,
                patient=patient_b,
                consultorio=None,
                starts_at=_BASE_DT + datetime.timedelta(days=1, hours=i * 2),
            )

        # Act — obtener JWT real y usar en el header
        access_token = _get_jwt_token(user)
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.get(CITAS_LIST_URL)

        # Assert — 200 y solo 2 citas del tenant A
        assert (
            response.status_code == 200
        ), f"Esperado 200, obtenido {response.status_code}: {response.json()}"
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 2, (
            f"Esperadas 2 citas del tenant A, obtenidas {len(results)}. "
            "Si son 5, hay fuga cross-tenant. "
            "Si son 0, TenantAPIView no resolvió el tenant desde el JWT."
        )

    def test_jwt_cross_tenant_cita_isolation(self, db: None) -> None:
        """Usuario del tenant A con JWT real NO puede ver citas del tenant B."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="admin", is_active=True)

        doctor_a = DoctorFactory(tenant=tenant_a)
        patient_a = PatientFactory(tenant=tenant_a)
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_b = PatientFactory(tenant=tenant_b)

        AppointmentFactory(
            tenant=tenant_a,
            doctor=doctor_a,
            patient=patient_a,
            consultorio=None,
            starts_at=_BASE_DT,
        )
        for i in range(5):
            AppointmentFactory(
                tenant=tenant_b,
                doctor=doctor_b,
                patient=patient_b,
                consultorio=None,
                starts_at=_BASE_DT + datetime.timedelta(days=1, hours=i * 2),
            )

        # Act
        access_token = _get_jwt_token(user)
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.get(CITAS_LIST_URL)

        # Assert — solo la 1 cita del tenant A
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 1, (
            f"Aislamiento cross-tenant fallido: se obtuvieron {len(results)} "
            f"citas en lugar de 1 del tenant A."
        )

    def test_jwt_auth_without_membership_returns_403(self, db: None) -> None:
        """Usuario con JWT pero SIN membresía activa recibe 403.

        CAMBIO POST-ENFORCEMENT: antes de activar los permisos por rol, este
        endpoint devolvía 200 con lista vacía. Ahora que HasClinicRole está activo,
        el usuario sin membresía tiene active_role=None → 403 Forbidden.
        Es el comportamiento correcto: los endpoints de clínica requieren rol activo.
        """
        # Arrange — user sin membresías
        user = UserFactory()
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            starts_at=_BASE_DT,
        )

        # Act — JWT real, sin membresía
        access_token = _get_jwt_token(user)
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.get(CITAS_LIST_URL)

        # Assert — 403: sin membresía activa, HasClinicRole deniega el acceso
        assert (
            response.status_code == 403
        ), f"Sin membresía activa esperamos 403, obtuvo {response.status_code}."


# ===========================================================================
# GET/PATCH /agenda/config/ — horario y granularidad de la rejilla
# ===========================================================================


class TestAgendaConfigApiGet:
    """GET /agenda/config/ — lectura de la configuración de agenda."""

    def test_get_returns_new_grid_fields_with_defaults(self, db: None) -> None:
        """GET devuelve agenda_start_hour/agenda_end_hour/slot_interval_minutes
        con sus defaults (9/18/30) para un tenant que nunca configuró nada."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.get(AGENDA_CONFIG_URL)

        # Assert
        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["agenda_start_hour"] == 9
        assert data["agenda_end_hour"] == 18
        assert data["slot_interval_minutes"] == 30

    def test_get_permitido_para_recepcion(self, db: None) -> None:
        """Recepción SÍ puede leer la config (2026-07-21).

        El horario y el intervalo definen cómo se dibuja la agenda, así que
        cualquier rol que la vea necesita leerlos. Editarla sigue siendo
        exclusivo de owner/admin (ver TestAgendaConfigApiPatch).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.get(AGENDA_CONFIG_URL)

        # Assert
        assert response.status_code == 200
        assert "agenda_start_hour" in response.json()


class TestAgendaConfigApiPatch:
    """PATCH /agenda/config/ — actualización del horario y la rejilla."""

    def test_patch_valid_updates_grid_fields(self, db: None) -> None:
        """PATCH con horario/rejilla válidos (8/20/15) persiste los 3 campos."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={
                    "agenda_start_hour": 8,
                    "agenda_end_hour": 20,
                    "slot_interval_minutes": 15,
                },
                format="json",
            )

        # Assert
        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["agenda_start_hour"] == 8
        assert data["agenda_end_hour"] == 20
        assert data["slot_interval_minutes"] == 15

        config = agenda_config_get(tenant=tenant)
        assert config.agenda_start_hour == 8
        assert config.agenda_end_hour == 20
        assert config.slot_interval_minutes == 15

    def test_patch_allowed_for_admin_role(self, db: None) -> None:
        """El rol admin también puede configurar el horario (200)."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="admin")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_start_hour": 7},
                format="json",
            )

        # Assert
        assert response.status_code == 200, response.json()

    def test_patch_end_hour_not_greater_than_start_hour_returns_400(self, db: None) -> None:
        """agenda_end_hour <= agenda_start_hour devuelve 400 con mensaje claro."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act — cierre igual a la apertura
        with _tenant_context(tenant):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_start_hour": 10, "agenda_end_hour": 10},
                format="json",
            )

        # Assert
        assert response.status_code == 400
        assert "posterior" in str(response.json()).lower()

    def test_patch_end_hour_less_than_start_hour_returns_400(self, db: None) -> None:
        """agenda_end_hour < agenda_start_hour también devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_start_hour": 15, "agenda_end_hour": 9},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_end_hour_conflicts_with_existing_start_hour_returns_400(self, db: None) -> None:
        """PATCH parcial que solo manda agenda_start_hour, pero vuelve inválida
        la combinación con el agenda_end_hour ya guardado, también da 400.

        Cubre la validación de estado final en el service (no solo en el
        serializer), que no conoce el valor ya persistido en un PATCH parcial.
        """
        # Arrange — config existente con horario default (9-18)
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")
        with _tenant_context(tenant):
            client.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_end_hour": 10},
                format="json",
            )

            # Act — solo sube el inicio a 12, que ya no es < 10 (el cierre guardado)
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_start_hour": 12},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_slot_interval_minutes_out_of_choices_returns_400(self, db: None) -> None:
        """slot_interval_minutes fuera de choices (ej. 45) devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"slot_interval_minutes": 45},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_agenda_start_hour_out_of_range_returns_400(self, db: None) -> None:
        """agenda_start_hour fuera de rango (ej. 25) devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_start_hour": 25},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_agenda_end_hour_out_of_range_returns_400(self, db: None) -> None:
        """agenda_end_hour fuera de rango (ej. 25) devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_end_hour": 25},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_forbidden_for_role_without_config_access(self, db: None) -> None:
        """Un rol sin derecho a configurar (ej. reception) recibe 403."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_start_hour": 8},
                format="json",
            )

        # Assert
        assert response.status_code == 403

    def test_patch_does_not_affect_other_tenants_config(self, db: None) -> None:
        """PATCH de un tenant no cambia la config de otro tenant (aislamiento)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        client_a = _make_member_client(tenant_a, role="owner")

        # Act
        with _tenant_context(tenant_a):
            client_a.patch(
                AGENDA_CONFIG_URL,
                data={"agenda_start_hour": 7, "agenda_end_hour": 22},
                format="json",
            )

        # Assert — tenant B conserva los defaults
        config_b = agenda_config_get(tenant=tenant_b)
        assert config_b.agenda_start_hour == 9
        assert config_b.agenda_end_hour == 18
