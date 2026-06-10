"""
Batería completa de tests para la matriz de permisos por rol clínico.

Fuente de verdad: apps/core/permissions.py
    - PatientPermission
    - PersonalPermission
    - AppointmentPermission
    - AppointmentStatusPermission
    - AgendaConfigPermission

Estrategia de autenticación en tests de matriz (force_authenticate + mock):
    Los tests de matriz usan force_authenticate + mock de resolve_membership_for_user
    (en apps.core.views) para inyectar el active_role directamente sin hacer una
    llamada JWT real en cada caso parametrizado. Esto evita el throttle del endpoint
    /auth/login/ (429 Too Many Requests) cuando se disparan ~100 tests a la vez.

    Flujo del mock:
        force_authenticate(user)           → request.user poblado
        mock resolve_membership_for_user   → devuelve un mock de TenantMembership
                                             con .role=<rol> y .tenant=<tenant>
        TenantAPIView.initial()            → llama resolve_membership_for_user (mockeado)
                                             → request.active_role = mock.role
        HasClinicRole.has_permission()     → evalúa request.active_role contra policy

    Para los casos borde que requieren el flujo JWT REAL (sin membership,
    tenant suspendido, etc.) sí se obtiene un token pero solo 1 por test.

Patrón: AAA. Todos tocan BD → fixture db.
"""

import datetime
import uuid as uuid_module
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

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
# Constantes de URLs
# ---------------------------------------------------------------------------

PACIENTES_LIST_URL = "/api/v1/pacientes/"
DOCTORES_LIST_URL = "/api/v1/personal/doctores/"
CONSULTORIOS_LIST_URL = "/api/v1/personal/consultorios/"
CITAS_LIST_URL = "/api/v1/agenda/citas/"
AGENDA_CONFIG_URL = "/api/v1/agenda/config/"

# Endpoints utilizados en tests de reagendamiento y OPTIONS
def _cita_reagendar_url(pk: Any) -> str:
    return f"/api/v1/agenda/citas/{pk}/reagendar/"

_BASE_DT = datetime.datetime(2031, 1, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)


def _paciente_detail_url(pk: Any) -> str:
    return f"/api/v1/pacientes/{pk}/"


def _doctor_detail_url(pk: Any) -> str:
    return f"/api/v1/personal/doctores/{pk}/"


def _consultorio_detail_url(pk: Any) -> str:
    return f"/api/v1/personal/consultorios/{pk}/"


def _cita_detail_url(pk: Any) -> str:
    return f"/api/v1/agenda/citas/{pk}/"


def _cita_estado_url(pk: Any) -> str:
    return f"/api/v1/agenda/citas/{pk}/estado/"


# ---------------------------------------------------------------------------
# Helper de autenticación JWT real (solo para tests de casos borde)
# ---------------------------------------------------------------------------


def _get_jwt_token(user: Any, password: str = "password-segura-123") -> str:
    """Obtiene un JWT real vía POST /api/v1/auth/login/."""
    login_client = APIClient()
    response = login_client.post(
        "/api/v1/auth/login/",
        data={"email": user.email, "password": password},
        format="json",
    )
    assert response.status_code == 200, (
        f"Login fallido para {user.email}: {response.json()}"
    )
    return response.json()["access"]


# ---------------------------------------------------------------------------
# Helpers para tests de matriz (force_authenticate + mock de membresía)
# ---------------------------------------------------------------------------


@contextmanager
def _role_context(tenant: Any, role: str, user: Any) -> Generator[None, None, None]:
    """Inyecta tenant + role en TenantAPIView.initial() sin llamar al login endpoint.

    Mockeamos resolve_membership_for_user (importada en apps.core.views) para que
    devuelva un membership mock con el rol deseado. También mockeamos get_current_tenant
    en cada módulo de vista y en el TenantManager para que las queries ORM filtren
    por el tenant correcto.

    Args:
        tenant: Tenant activo para este request simulado.
        role:   Rol clínico a inyectar en request.active_role.
        user:   Usuario ya autenticado via force_authenticate.
    """
    fake_membership = MagicMock()
    fake_membership.role = role
    fake_membership.tenant = tenant

    with (
        patch(
            "apps.core.views.resolve_membership_for_user",
            return_value=fake_membership,
        ),
        patch(
            "apps.pacientes.views.get_current_tenant",
            return_value=tenant,
        ),
        patch(
            "apps.personal.views.get_current_tenant",
            return_value=tenant,
        ),
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


def _make_member_client(tenant: Any, role: str) -> tuple[APIClient, Any]:
    """Crea user + membresía real en BD y devuelve (APIClient autenticado, user).

    La membresía se crea realmente en BD para que el flujo ORM sea correcto.
    El APIClient usa force_authenticate (no JWT real) para evitar el throttle.

    Returns:
        Tupla (APIClient, user) donde el cliente ya tiene force_authenticate aplicado.
    """
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


# ---------------------------------------------------------------------------
# Payloads para crear recursos
# ---------------------------------------------------------------------------

_PACIENTE_PAYLOAD: dict[str, Any] = {
    "first_name": "TestPerm",
    "paternal_surname": "Apellido",
    "maternal_surname": "Materno",
    "date_of_birth": "1990-01-01",
    "sex": "M",
    "phone": "5500000001",
    "curp": "",
    "email": "",
    "notes": "",
}


# ===========================================================================
# BLOQUE 1: PatientPermission
# ===========================================================================
#
# Matriz (de permissions.py):
#   GET    → ALL_ROLES  (7 roles)
#   POST   → owner, admin, doctor, nurse, reception (5 roles)
#   PATCH  → owner, admin, doctor, nurse, reception (5 roles)
#   DELETE → owner, admin (2 roles)
#
# Roles denegados en POST/PATCH: finance, readonly
# Roles denegados en DELETE: doctor, nurse, reception, finance, readonly
#
# ===========================================================================


class TestPatientPermissionGET:
    """GET /pacientes/ y GET /pacientes/<id>/ — todos los roles deben recibir 200."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_get_pacientes_list_allowed_for_all_roles(self, db: None, role: str) -> None:
        """Todos los 7 roles reciben 200 en GET /pacientes/ (lista)."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(PACIENTES_LIST_URL)

        # Assert
        assert response.status_code == 200, (
            f"GET /pacientes/ con rol '{role}' esperaba 200, obtuvo {response.status_code}. "
            f"Respuesta: {response.json()}"
        )

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_get_paciente_detail_allowed_for_all_roles(self, db: None, role: str) -> None:
        """Todos los 7 roles reciben 200 en GET /pacientes/<id>/ (detalle)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(_paciente_detail_url(patient.id))

        # Assert
        assert response.status_code == 200, (
            f"GET /pacientes/<id>/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )


class TestPatientPermissionPOST:
    """POST /pacientes/ — solo ciertos roles pueden crear pacientes."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception"],
    )
    def test_post_paciente_allowed_for_clinical_roles(self, db: None, role: str) -> None:
        """owner, admin, doctor, nurse, reception reciben 201 al crear un paciente."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)
        # phone distinto por rol para evitar colisiones en la misma BD de test
        role_phone = {
            "owner": "5511110001",
            "admin": "5511110002",
            "doctor": "5511110003",
            "nurse": "5511110004",
            "reception": "5511110005",
        }
        payload = {**_PACIENTE_PAYLOAD, "phone": role_phone[role]}

        # Act
        with _role_context(tenant, role, user):
            response = client.post(PACIENTES_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201, (
            f"POST /pacientes/ con rol '{role}' esperaba 201, obtuvo {response.status_code}. "
            f"Respuesta: {response.json()}"
        )

    @pytest.mark.parametrize(
        "role",
        ["finance", "readonly"],
    )
    def test_post_paciente_denied_for_restricted_roles(self, db: None, role: str) -> None:
        """finance y readonly reciben 403 al intentar crear un paciente."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.post(PACIENTES_LIST_URL, data=_PACIENTE_PAYLOAD, format="json")

        # Assert
        assert response.status_code == 403, (
            f"POST /pacientes/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: este rol NO deberia poder crear pacientes segun la matriz."
        )


class TestPatientPermissionPATCH:
    """PATCH /pacientes/<id>/ — misma política que POST."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception"],
    )
    def test_patch_paciente_allowed_for_clinical_roles(self, db: None, role: str) -> None:
        """owner, admin, doctor, nurse, reception reciben 200 al editar un paciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                _paciente_detail_url(patient.id),
                data={"phone": "5511111111"},
                format="json",
            )

        # Assert
        assert response.status_code == 200, (
            f"PATCH /pacientes/<id>/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["finance", "readonly"],
    )
    def test_patch_paciente_denied_for_restricted_roles(self, db: None, role: str) -> None:
        """finance y readonly reciben 403 al intentar editar un paciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                _paciente_detail_url(patient.id),
                data={"phone": "5511111111"},
                format="json",
            )

        # Assert
        assert response.status_code == 403, (
            f"PATCH /pacientes/<id>/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: este rol NO deberia poder editar pacientes segun la matriz."
        )


class TestPatientPermissionDELETE:
    """DELETE /pacientes/<id>/ — solo owner y admin pueden desactivar pacientes."""

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_delete_paciente_allowed_for_manage_roles(self, db: None, role: str) -> None:
        """owner y admin reciben 204 al desactivar un paciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.delete(_paciente_detail_url(patient.id))

        # Assert
        assert response.status_code == 204, (
            f"DELETE /pacientes/<id>/ con rol '{role}' esperaba 204, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_delete_paciente_denied_for_non_manage_roles(self, db: None, role: str) -> None:
        """doctor, nurse, reception, finance, readonly reciben 403 al intentar DELETE."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.delete(_paciente_detail_url(patient.id))

        # Assert
        assert response.status_code == 403, (
            f"DELETE /pacientes/<id>/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: solo owner/admin pueden desactivar pacientes segun la matriz."
        )


# ===========================================================================
# BLOQUE 2: PersonalPermission (doctores, consultorios)
# ===========================================================================
#
# Matriz:
#   GET    → ALL_ROLES  (7 roles)
#   POST   → owner, admin (MANAGE_ROLES)
#   PATCH  → owner, admin (MANAGE_ROLES)
#   DELETE → owner, admin (MANAGE_ROLES)
#
# ===========================================================================


class TestPersonalPermissionGET:
    """GET en módulo personal — todos los roles deben recibir 200."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_get_doctores_allowed_for_all_roles(self, db: None, role: str) -> None:
        """Todos los 7 roles reciben 200 en GET /personal/doctores/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(DOCTORES_LIST_URL)

        # Assert
        assert response.status_code == 200, (
            f"GET /personal/doctores/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_get_consultorios_allowed_for_all_roles(self, db: None, role: str) -> None:
        """Todos los 7 roles reciben 200 en GET /personal/consultorios/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(CONSULTORIOS_LIST_URL)

        # Assert
        assert response.status_code == 200, (
            f"GET /personal/consultorios/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_get_doctor_detail_allowed_for_all_roles(self, db: None, role: str) -> None:
        """Todos los 7 roles reciben 200 en GET /personal/doctores/<id>/."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(_doctor_detail_url(doctor.id))

        # Assert
        assert response.status_code == 200, (
            f"GET /personal/doctores/<id>/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )


class TestPersonalPermissionPOST:
    """POST /personal/consultorios/ — solo owner y admin (MANAGE_ROLES)."""

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_post_consultorio_allowed_for_manage_roles(self, db: None, role: str) -> None:
        """owner y admin reciben 201 al crear un consultorio."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)
        payload = {"name": f"Consultorio-{role}", "location": "", "color_hex": ""}

        # Act
        with _role_context(tenant, role, user):
            response = client.post(CONSULTORIOS_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201, (
            f"POST /personal/consultorios/ con rol '{role}' esperaba 201, obtuvo {response.status_code}. "
            f"Respuesta: {response.json()}"
        )

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_post_consultorio_denied_for_non_manage_roles(self, db: None, role: str) -> None:
        """doctor, nurse, reception, finance, readonly reciben 403 al intentar crear consultorio."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)
        payload = {"name": "Intento no autorizado", "location": "", "color_hex": ""}

        # Act
        with _role_context(tenant, role, user):
            response = client.post(CONSULTORIOS_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 403, (
            f"POST /personal/consultorios/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: solo owner/admin pueden crear consultorios segun la matriz."
        )


class TestPersonalPermissionPATCH:
    """PATCH /personal/doctores/<id>/ y /personal/consultorios/<id>/ — solo MANAGE_ROLES."""

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_patch_consultorio_allowed_for_manage_roles(self, db: None, role: str) -> None:
        """owner y admin reciben 200 al editar un consultorio."""
        # Arrange
        tenant = TenantFactory()
        consultorio = ConsultorioFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                _consultorio_detail_url(consultorio.id),
                data={"location": "Piso 2"},
                format="json",
            )

        # Assert
        assert response.status_code == 200, (
            f"PATCH /personal/consultorios/<id>/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_patch_consultorio_denied_for_non_manage_roles(self, db: None, role: str) -> None:
        """doctor, nurse, reception, finance, readonly reciben 403 al intentar PATCH consultorio."""
        # Arrange
        tenant = TenantFactory()
        consultorio = ConsultorioFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                _consultorio_detail_url(consultorio.id),
                data={"location": "Piso 3"},
                format="json",
            )

        # Assert
        assert response.status_code == 403, (
            f"PATCH /personal/consultorios/<id>/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: solo owner/admin pueden editar consultorios segun la matriz."
        )

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_patch_doctor_allowed_for_manage_roles(self, db: None, role: str) -> None:
        """owner y admin reciben 200 al editar un doctor."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                _doctor_detail_url(doctor.id),
                data={"specialty": "Cardiologia"},
                format="json",
            )

        # Assert
        assert response.status_code == 200, (
            f"PATCH /personal/doctores/<id>/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_patch_doctor_denied_for_non_manage_roles(self, db: None, role: str) -> None:
        """doctor, nurse, reception, finance, readonly reciben 403 al intentar PATCH doctor."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                _doctor_detail_url(doctor.id),
                data={"specialty": "Intento no autorizado"},
                format="json",
            )

        # Assert
        assert response.status_code == 403, (
            f"PATCH /personal/doctores/<id>/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: solo owner/admin pueden editar doctores segun la matriz."
        )


class TestPersonalPermissionDELETE:
    """DELETE /personal/consultorios/<id>/ — solo MANAGE_ROLES."""

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_delete_consultorio_allowed_for_manage_roles(self, db: None, role: str) -> None:
        """owner y admin reciben 2xx al desactivar un consultorio."""
        # Arrange
        tenant = TenantFactory()
        consultorio = ConsultorioFactory(tenant=tenant, is_active=True)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.delete(_consultorio_detail_url(consultorio.id))

        # Assert — acepta 204 o 200 (depende de la implementación de la vista)
        assert response.status_code in (200, 204), (
            f"DELETE /personal/consultorios/<id>/ con rol '{role}' esperaba 2xx, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_delete_consultorio_denied_for_non_manage_roles(self, db: None, role: str) -> None:
        """doctor, nurse, reception, finance, readonly reciben 403 al intentar DELETE consultorio."""
        # Arrange
        tenant = TenantFactory()
        consultorio = ConsultorioFactory(tenant=tenant, is_active=True)
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.delete(_consultorio_detail_url(consultorio.id))

        # Assert
        assert response.status_code == 403, (
            f"DELETE /personal/consultorios/<id>/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: solo owner/admin pueden desactivar consultorios segun la matriz."
        )


# ===========================================================================
# BLOQUE 3: AppointmentPermission
# ===========================================================================
#
# Matriz:
#   GET    → owner, admin, doctor, nurse, reception, readonly  (finance denegado)
#   POST   → owner, admin, doctor, reception                   (nurse, finance, readonly denegados)
#   PATCH  → owner, admin, doctor, reception                   (idem)
#   DELETE → owner, admin, reception                           (doctor, nurse, finance, readonly denegados)
#
# ===========================================================================


class TestAppointmentPermissionGET:
    """GET /agenda/citas/ — finance es el único rol denegado."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception", "readonly"],
    )
    def test_get_citas_allowed_for_non_finance_roles(self, db: None, role: str) -> None:
        """Todos los roles excepto finance reciben 200 en GET /agenda/citas/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(CITAS_LIST_URL)

        # Assert
        assert response.status_code == 200, (
            f"GET /agenda/citas/ con rol '{role}' esperaba 200, obtuvo {response.status_code}. "
            f"Respuesta: {response.json()}"
        )

    def test_get_citas_denied_for_finance(self, db: None) -> None:
        """finance recibe 403 en GET /agenda/citas/ — no debe ver la agenda."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, "finance")

        # Act
        with _role_context(tenant, "finance", user):
            response = client.get(CITAS_LIST_URL)

        # Assert
        assert response.status_code == 403, (
            f"GET /agenda/citas/ con rol 'finance' esperaba 403, obtuvo {response.status_code}. "
            "BUG: finance NO debe tener acceso a la agenda segun la matriz."
        )

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception", "readonly"],
    )
    def test_get_cita_detail_allowed_for_non_finance_roles(self, db: None, role: str) -> None:
        """Todos los roles excepto finance reciben 200 en GET /agenda/citas/<id>/."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_BASE_DT,
        )
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(_cita_detail_url(appt.id))

        # Assert
        assert response.status_code == 200, (
            f"GET /agenda/citas/<id>/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )

    def test_get_cita_detail_denied_for_finance(self, db: None) -> None:
        """finance recibe 403 en GET /agenda/citas/<id>/."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_BASE_DT,
        )
        client, user = _make_member_client(tenant, "finance")

        # Act
        with _role_context(tenant, "finance", user):
            response = client.get(_cita_detail_url(appt.id))

        # Assert
        assert response.status_code == 403, (
            f"GET /agenda/citas/<id>/ con rol 'finance' esperaba 403, obtuvo {response.status_code}."
        )


class TestAppointmentPermissionPOST:
    """POST /agenda/citas/ — owner, admin, doctor, reception pueden crear citas."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "reception"],
    )
    def test_post_cita_allowed(self, db: None, role: str) -> None:
        """owner, admin, doctor, reception reciben 201 al crear una cita."""
        # Arrange
        from apps.tenancy.models import TenantMembership

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        # Regla de negocio: un médico solo puede agendar para SÍ MISMO. Para el caso
        # 'doctor', el perfil Doctor de la cita debe ser el del usuario que agenda.
        if role == "doctor":
            membership = TenantMembership.objects.get(user=user, tenant=tenant)
            doctor = DoctorFactory(tenant=tenant, membership=membership)
        else:
            doctor = DoctorFactory(tenant=tenant)

        role_offset = {"owner": 0, "admin": 1, "doctor": 2, "reception": 3}
        starts = _BASE_DT + datetime.timedelta(hours=role_offset[role])
        ends = starts + datetime.timedelta(minutes=30)

        payload = {
            "patient_id": str(patient.id),
            "doctor_id": str(doctor.id),
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "reason": f"Consulta {role}",
        }

        # Act
        with _role_context(tenant, role, user):
            response = client.post(CITAS_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201, (
            f"POST /agenda/citas/ con rol '{role}' esperaba 201, obtuvo {response.status_code}. "
            f"Respuesta: {response.json()}"
        )

    @pytest.mark.parametrize(
        "role",
        ["nurse", "finance", "readonly"],
    )
    def test_post_cita_denied(self, db: None, role: str) -> None:
        """nurse, finance, readonly reciben 403 al intentar crear una cita."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        client, user = _make_member_client(tenant, role)

        payload = {
            "patient_id": str(patient.id),
            "doctor_id": str(doctor.id),
            "starts_at": _BASE_DT.isoformat(),
            "reason": f"Intento no autorizado por {role}",
        }

        # Act
        with _role_context(tenant, role, user):
            response = client.post(CITAS_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 403, (
            f"POST /agenda/citas/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: este rol NO debe poder crear citas segun la matriz."
        )


class TestAppointmentPermissionPATCH:
    """PATCH /agenda/citas/<id>/ — misma política que POST."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "reception"],
    )
    def test_patch_cita_allowed(self, db: None, role: str) -> None:
        """owner, admin, doctor, reception reciben 200 al editar una cita."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        role_offset = {"owner": 10, "admin": 11, "doctor": 12, "reception": 13}
        starts = _BASE_DT + datetime.timedelta(hours=role_offset[role])
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=starts,
        )
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                _cita_detail_url(appt.id),
                data={"reason": f"Actualizado por {role}"},
                format="json",
            )

        # Assert
        assert response.status_code == 200, (
            f"PATCH /agenda/citas/<id>/ con rol '{role}' esperaba 200, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["nurse", "finance", "readonly"],
    )
    def test_patch_cita_denied(self, db: None, role: str) -> None:
        """nurse, finance, readonly reciben 403 al intentar PATCH de una cita."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=20),
        )
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                _cita_detail_url(appt.id),
                data={"reason": "Intento no autorizado"},
                format="json",
            )

        # Assert
        assert response.status_code == 403, (
            f"PATCH /agenda/citas/<id>/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: este rol NO debe poder editar citas segun la matriz."
        )


class TestAppointmentPermissionDELETE:
    """DELETE /agenda/citas/<id>/ — owner, admin, reception pueden cancelar."""

    @pytest.mark.parametrize("role", ["owner", "admin", "reception"])
    def test_delete_cita_allowed(self, db: None, role: str) -> None:
        """owner, admin, reception reciben 204 al cancelar una cita."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        role_offset = {"owner": 30, "admin": 31, "reception": 32}
        starts = _BASE_DT + datetime.timedelta(hours=role_offset[role])
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=starts,
        )
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.delete(_cita_detail_url(appt.id))

        # Assert
        assert response.status_code == 204, (
            f"DELETE /agenda/citas/<id>/ con rol '{role}' esperaba 204, obtuvo {response.status_code}."
        )

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "finance", "readonly"],
    )
    def test_delete_cita_denied(self, db: None, role: str) -> None:
        """doctor, nurse, finance, readonly reciben 403 al intentar cancelar una cita."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            starts_at=_BASE_DT + datetime.timedelta(hours=40),
        )
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.delete(_cita_detail_url(appt.id))

        # Assert
        assert response.status_code == 403, (
            f"DELETE /agenda/citas/<id>/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: este rol NO debe poder cancelar citas segun la matriz."
        )


# ===========================================================================
# BLOQUE 4: AppointmentStatusPermission
# ===========================================================================
#
# Endpoint: POST /agenda/citas/<id>/estado/
# Matriz:
#   POST → owner, admin, doctor, nurse, reception (finance y readonly denegados)
#
# ===========================================================================


class TestAppointmentStatusPermission:
    """POST /agenda/citas/<id>/estado/ — solo ciertos roles pueden cambiar el estado."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "nurse", "reception"],
    )
    def test_change_status_allowed(self, db: None, role: str) -> None:
        """owner, admin, doctor, nurse, reception reciben 200 al cambiar estado de cita."""
        # Arrange
        from apps.agenda.models import Appointment

        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        role_offset = {"owner": 50, "admin": 51, "doctor": 52, "nurse": 53, "reception": 54}
        starts = _BASE_DT + datetime.timedelta(hours=role_offset[role])
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=starts,
        )
        client, user = _make_member_client(tenant, role)

        # Act — transición SCHEDULED → CONFIRMED es siempre válida
        with _role_context(tenant, role, user):
            response = client.post(
                _cita_estado_url(appt.id),
                data={"status": Appointment.Status.CONFIRMED},
                format="json",
            )

        # Assert
        assert response.status_code == 200, (
            f"POST /estado/ con rol '{role}' esperaba 200, obtuvo {response.status_code}. "
            f"Respuesta: {response.json()}"
        )

    @pytest.mark.parametrize("role", ["finance", "readonly"])
    def test_change_status_denied_for_restricted_roles(self, db: None, role: str) -> None:
        """finance y readonly reciben 403 al intentar cambiar el estado de una cita."""
        # Arrange
        from apps.agenda.models import Appointment

        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, doctor=doctor, patient=patient, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT + datetime.timedelta(hours=60),
        )
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.post(
                _cita_estado_url(appt.id),
                data={"status": Appointment.Status.CONFIRMED},
                format="json",
            )

        # Assert
        assert response.status_code == 403, (
            f"POST /estado/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: finance y readonly NO deben poder cambiar estados segun la matriz."
        )


# ===========================================================================
# BLOQUE 5: AgendaConfigPermission
# ===========================================================================
#
# Endpoint: GET /agenda/config/ y PATCH /agenda/config/
# Matriz:
#   GET   → owner, admin (MANAGE_ROLES) — los otros 5 denegados
#   PATCH → owner, admin (MANAGE_ROLES) — los otros 5 denegados
#
# ===========================================================================


class TestAgendaConfigPermissionGET:
    """GET /agenda/config/ — solo owner y admin pueden ver la config."""

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_get_agenda_config_allowed_for_manage_roles(self, db: None, role: str) -> None:
        """owner y admin reciben 200 en GET /agenda/config/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(AGENDA_CONFIG_URL)

        # Assert
        assert response.status_code == 200, (
            f"GET /agenda/config/ con rol '{role}' esperaba 200, obtuvo {response.status_code}. "
            f"Respuesta: {response.json()}"
        )

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_get_agenda_config_denied_for_non_manage_roles(self, db: None, role: str) -> None:
        """doctor, nurse, reception, finance, readonly reciben 403 en GET /agenda/config/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.get(AGENDA_CONFIG_URL)

        # Assert
        assert response.status_code == 403, (
            f"GET /agenda/config/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: solo owner/admin pueden ver la config de agenda segun la matriz."
        )


class TestAgendaConfigPermissionPATCH:
    """PATCH /agenda/config/ — solo owner y admin pueden editar la config."""

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_patch_agenda_config_allowed_for_manage_roles(self, db: None, role: str) -> None:
        """owner y admin reciben 200 en PATCH /agenda/config/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"default_appointment_duration": 45},
                format="json",
            )

        # Assert
        assert response.status_code == 200, (
            f"PATCH /agenda/config/ con rol '{role}' esperaba 200, obtuvo {response.status_code}. "
            f"Respuesta: {response.json()}"
        )

    @pytest.mark.parametrize(
        "role",
        ["doctor", "nurse", "reception", "finance", "readonly"],
    )
    def test_patch_agenda_config_denied_for_non_manage_roles(self, db: None, role: str) -> None:
        """doctor, nurse, reception, finance, readonly reciben 403 en PATCH /agenda/config/."""
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, role)

        # Act
        with _role_context(tenant, role, user):
            response = client.patch(
                AGENDA_CONFIG_URL,
                data={"default_appointment_duration": 15},
                format="json",
            )

        # Assert
        assert response.status_code == 403, (
            f"PATCH /agenda/config/ con rol '{role}' esperaba 403, obtuvo {response.status_code}. "
            "BUG: solo owner/admin pueden editar la config de agenda segun la matriz."
        )


# ===========================================================================
# BLOQUE 6: Casos borde de seguridad
# ===========================================================================
#
# 6.1  Sin token → 401 (no 403)
# 6.2  Autenticado con JWT real SIN membership activa → 403
# 6.3  Membership en tenant SUSPENDIDO → 403
# 6.4  Membership con is_active=False → 403
# 6.5  Membership soft-deleted (deleted_at IS NOT NULL) → 403
# 6.6  Platform staff (is_platform_staff=True) sin membership → 403
# 6.7  Aislamiento cross-tenant: owner de A accede a recurso de B → 404 (no 204/403)
#
# NOTA: Los casos 6.2–6.6 usan JWT REAL (no mock) para validar que
# resolve_membership_for_user realmente devuelve None en esos casos.
#
# ===========================================================================


class TestNoTokenReturns401:
    """Sin token de autenticación todos los endpoints devuelven 401."""

    @pytest.mark.parametrize(
        "url",
        [
            PACIENTES_LIST_URL,
            DOCTORES_LIST_URL,
            CONSULTORIOS_LIST_URL,
            CITAS_LIST_URL,
            AGENDA_CONFIG_URL,
        ],
    )
    def test_unauthenticated_request_returns_401(self, db: None, url: str) -> None:
        """GET sin token devuelve 401, no 403."""
        # Arrange
        client = APIClient()  # sin credentials

        # Act
        response = client.get(url)

        # Assert
        assert response.status_code == 401, (
            f"GET {url} sin token esperaba 401, obtuvo {response.status_code}. "
            "DRF deberia devolver 401 (no autenticado) antes de evaluar permisos."
        )


class TestAuthenticatedWithoutMembership:
    """Usuario autenticado con JWT pero SIN membresía activa → 403."""

    def test_no_membership_returns_403_on_patient_list(self, db: None) -> None:
        """Usuario válido sin ninguna membership obtiene 403 en GET /pacientes/."""
        # Arrange — user sin membresías
        user = UserFactory()
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(PACIENTES_LIST_URL)

        # Assert
        assert response.status_code == 403, (
            f"GET /pacientes/ sin membership esperaba 403, obtuvo {response.status_code}. "
            "HasClinicRole.has_permission debe devolver False cuando active_role=None."
        )

    def test_no_membership_returns_403_on_citas(self, db: None) -> None:
        """Usuario sin membership obtiene 403 en GET /agenda/citas/."""
        user = UserFactory()
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.get(CITAS_LIST_URL)

        assert response.status_code == 403, (
            f"GET /citas/ sin membership esperaba 403, obtuvo {response.status_code}."
        )

    def test_no_membership_returns_403_on_personal(self, db: None) -> None:
        """Usuario sin membership obtiene 403 en GET /personal/doctores/."""
        user = UserFactory()
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.get(DOCTORES_LIST_URL)

        assert response.status_code == 403, (
            f"GET /doctores/ sin membership esperaba 403, obtuvo {response.status_code}."
        )

    def test_no_membership_returns_403_on_agenda_config(self, db: None) -> None:
        """Usuario sin membership obtiene 403 en GET /agenda/config/."""
        user = UserFactory()
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.get(AGENDA_CONFIG_URL)

        assert response.status_code == 403, (
            f"GET /agenda/config/ sin membership esperaba 403, obtuvo {response.status_code}."
        )


class TestSuspendedTenantReturns403:
    """Membresía en tenant SUSPENDIDO → 403.

    FIX-C: trial y active tienen acceso; suspended queda bloqueado.
    Este test verifica que suspended sigue siendo bloqueado tras el fix.
    """

    def test_suspended_tenant_membership_returns_403(self, db: None) -> None:
        """Usuario con membresía en tenant suspendido recibe 403 en GET /pacientes/."""
        # Arrange — tenant suspendido
        from apps.tenancy.models import Tenant

        tenant = TenantFactory(status=Tenant.Status.SUSPENDED)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="owner", is_active=True)
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(PACIENTES_LIST_URL)

        # Assert — suspended no está en ["active", "trial"] → resolve devuelve None → 403
        assert response.status_code == 403, (
            f"GET /pacientes/ con tenant suspendido esperaba 403, obtuvo {response.status_code}. "
            "BUG CRITICO: resolve_membership_for_user no filtra tenant suspendido."
        )


class TestInactiveMembershipReturns403:
    """Membresía con is_active=False → 403."""

    def test_inactive_membership_returns_403(self, db: None) -> None:
        """Usuario con membresía desactivada (is_active=False) recibe 403."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="doctor", is_active=False)
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(PACIENTES_LIST_URL)

        # Assert — is_active=False → resolve devuelve None → active_role=None → 403
        assert response.status_code == 403, (
            f"GET /pacientes/ con membership inactiva esperaba 403, obtuvo {response.status_code}. "
            "BUG CRITICO: resolve_membership_for_user no filtra is_active=False."
        )


class TestSoftDeletedMembershipReturns403:
    """Membresía soft-deleted (deleted_at IS NOT NULL) → 403."""

    def test_soft_deleted_membership_returns_403(self, db: None) -> None:
        """Usuario con membresía soft-deleted no puede acceder a endpoints de clínica."""
        import django.utils.timezone as tz

        # Arrange — membership con deleted_at establecido
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role="owner", is_active=True
        )
        # Soft-delete de la membership
        membership.deleted_at = tz.now()
        membership.save(update_fields=["deleted_at"])

        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(PACIENTES_LIST_URL)

        # Assert — deleted_at IS NOT NULL → resolve filtra deleted_at__isnull=True → None → 403
        assert response.status_code == 403, (
            f"GET /pacientes/ con membership soft-deleted esperaba 403, obtuvo {response.status_code}. "
            "BUG CRITICO: resolve_membership_for_user no filtra deleted_at__isnull=True."
        )


class TestPlatformStaffWithoutMembershipReturns403:
    """Platform staff (is_platform_staff=True) sin membership → 403 en API de clínica."""

    def test_platform_staff_without_membership_denied_on_patient_list(
        self, db: None
    ) -> None:
        """El staff de plataforma sin membresía clínica recibe 403 en GET /pacientes/."""
        from tests.factories import PlatformStaffFactory

        # Arrange — staff de plataforma SIN membership
        staff = PlatformStaffFactory()
        token = _get_jwt_token(staff)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(PACIENTES_LIST_URL)

        # Assert — is_platform_staff no otorga rol clínico → active_role=None → 403
        assert response.status_code == 403, (
            f"Platform staff sin membership esperaba 403, obtuvo {response.status_code}. "
            "El staff de plataforma opera via admin de Django, no via la API de clinica (v1)."
        )

    def test_platform_staff_without_membership_denied_on_citas(self, db: None) -> None:
        """Staff de plataforma recibe 403 en GET /agenda/citas/."""
        from tests.factories import PlatformStaffFactory

        staff = PlatformStaffFactory()
        token = _get_jwt_token(staff)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.get(CITAS_LIST_URL)

        assert response.status_code == 403, (
            f"Platform staff sin membership esperaba 403 en /citas/, obtuvo {response.status_code}."
        )

    def test_platform_staff_without_membership_denied_on_agenda_config(
        self, db: None
    ) -> None:
        """Staff de plataforma recibe 403 en GET /agenda/config/."""
        from tests.factories import PlatformStaffFactory

        staff = PlatformStaffFactory()
        token = _get_jwt_token(staff)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.get(AGENDA_CONFIG_URL)

        assert response.status_code == 403, (
            f"Platform staff sin membership esperaba 403 en /config/, obtuvo {response.status_code}."
        )


# ===========================================================================
# BLOQUE 7: Aislamiento cross-tenant con enforcement de rol
# ===========================================================================
#
# Un usuario con rol permitido en tenant A que accede a un recurso del tenant B
# debe recibir 404 (no 204, no 403). El enforcement de rol NO debe romper
# el aislamiento multi-tenant.
#
# Verificamos 4 combinaciones críticas:
#   - owner de A → DELETE paciente de B → 404, paciente B intacto
#   - owner de A → DELETE cita de B → 404, cita B intacta
#   - admin de A → PATCH consultorio de B → 404
#   - owner de A → POST /estado/ en cita de B → 404, estado de cita B intacto
#
# IMPORTANTE: estos tests usan JWT REAL para verificar el aislamiento
# end-to-end (sin mock de tenant). Si el test pasa con JWT real pero falla
# con force_authenticate, indica que el mock de tenant está mal, no el código.
#
# ===========================================================================


class TestCrossTenantIsolationWithRoleEnforcement:
    """El enforcement de rol no debe romper el aislamiento multi-tenant."""

    def test_owner_cannot_delete_patient_from_other_tenant(self, db: None) -> None:
        """Owner de tenant A intenta DELETE paciente de tenant B → 404, no 204.

        Combina: rol permitido (owner tiene DELETE en PatientPermission) +
                 aislamiento de tenant (paciente pertenece a otro tenant).
        El 404 garantiza que el ORM filtra por tenant antes de ejecutar la acción.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b, is_active=True)

        # Crear user con JWT real en tenant A (owner con permiso de DELETE)
        user_a = UserFactory()
        TenantMembershipFactory(user=user_a, tenant=tenant_a, role="owner", is_active=True)
        token_a = _get_jwt_token(user_a)
        client_a = APIClient()
        client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a}")

        # Act — owner de A intenta eliminar paciente de B
        response = client_a.delete(_paciente_detail_url(patient_b.id))

        # Assert — 404 (no 204; el recurso no existe en el tenant A)
        assert response.status_code == 404, (
            f"Owner de tenant A esperaba 404 al borrar paciente de tenant B, "
            f"obtuvo {response.status_code}. "
            "FUGA IDOR: si devolvio 204, un owner puede desactivar pacientes de otro tenant."
        )

        # El paciente del tenant B sigue activo (no fue afectado)
        patient_b.refresh_from_db()
        assert patient_b.is_active is True, (
            "FUGA IDOR CRITICA: el paciente del tenant B fue desactivado "
            "por un owner del tenant A."
        )

    def test_owner_cannot_delete_appointment_from_other_tenant(self, db: None) -> None:
        """Owner de tenant A intenta DELETE cita de tenant B → 404, no 204."""
        from apps.agenda.models import Appointment

        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_b = PatientFactory(tenant=tenant_b)
        appt_b = AppointmentFactory(
            tenant=tenant_b, doctor=doctor_b, patient=patient_b, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT + datetime.timedelta(hours=100),
        )

        user_a = UserFactory()
        TenantMembershipFactory(user=user_a, tenant=tenant_a, role="owner", is_active=True)
        token_a = _get_jwt_token(user_a)
        client_a = APIClient()
        client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a}")

        # Act
        response = client_a.delete(_cita_detail_url(appt_b.id))

        # Assert
        assert response.status_code == 404, (
            f"Owner de tenant A esperaba 404 al cancelar cita de tenant B, "
            f"obtuvo {response.status_code}. "
            "FUGA IDOR: si devolvio 204, un owner puede cancelar citas de otro tenant."
        )

        appt_b.refresh_from_db()
        assert appt_b.status == Appointment.Status.SCHEDULED, (
            "FUGA IDOR CRITICA: la cita del tenant B fue cancelada "
            "por un owner del tenant A."
        )

    def test_admin_cannot_patch_consultorio_from_other_tenant(self, db: None) -> None:
        """Admin de tenant A intenta PATCH consultorio de tenant B → 404, no 200."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        consultorio_b = ConsultorioFactory(tenant=tenant_b)

        user_a = UserFactory()
        TenantMembershipFactory(user=user_a, tenant=tenant_a, role="admin", is_active=True)
        token_a = _get_jwt_token(user_a)
        client_a = APIClient()
        client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a}")

        # Act
        response = client_a.patch(
            _consultorio_detail_url(consultorio_b.id),
            data={"location": "Intrusion desde tenant A"},
            format="json",
        )

        # Assert
        assert response.status_code == 404, (
            f"Admin de tenant A esperaba 404 al PATCH consultorio de tenant B, "
            f"obtuvo {response.status_code}. "
            "FUGA IDOR: si devolvio 200, un admin puede editar consultorios de otro tenant."
        )

    def test_owner_cannot_change_status_of_appointment_from_other_tenant(
        self, db: None
    ) -> None:
        """Owner de tenant A intenta POST /estado/ en cita de tenant B → 404, no 200."""
        from apps.agenda.models import Appointment

        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_b = DoctorFactory(tenant=tenant_b)
        patient_b = PatientFactory(tenant=tenant_b)
        appt_b = AppointmentFactory(
            tenant=tenant_b, doctor=doctor_b, patient=patient_b, consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=_BASE_DT + datetime.timedelta(hours=110),
        )

        user_a = UserFactory()
        TenantMembershipFactory(user=user_a, tenant=tenant_a, role="owner", is_active=True)
        token_a = _get_jwt_token(user_a)
        client_a = APIClient()
        client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a}")

        # Act
        response = client_a.post(
            _cita_estado_url(appt_b.id),
            data={"status": Appointment.Status.CONFIRMED},
            format="json",
        )

        # Assert
        assert response.status_code == 404, (
            f"Owner de tenant A esperaba 404 al cambiar estado de cita de tenant B, "
            f"obtuvo {response.status_code}. "
            "FUGA IDOR: si devolvio 200, un owner puede confirmar citas de otro tenant."
        )

        appt_b.refresh_from_db()
        assert appt_b.status == Appointment.Status.SCHEDULED, (
            "FUGA IDOR CRITICA: el estado de la cita del tenant B fue cambiado "
            "por owner del tenant A."
        )


# ===========================================================================
# BLOQUE 8: Tenant en TRIAL tiene acceso completo (FIX-C)
# ===========================================================================
#
# Modelo de negocio: las clínicas nuevas nacen con status=TRIAL y deben tener
# acceso completo durante los 2 meses de prueba gratuita. Antes del fix,
# resolve_membership_for_user filtraba solo tenant__status='active', dejando a
# los clientes de prueba bloqueados desde el primer día.
#
# Verificamos que un owner de un tenant TRIAL puede acceder a todos los módulos.
# El tenant SUSPENDIDO sigue bloqueado (test en BLOQUE 6.3).
#
# ===========================================================================


class TestTrialTenantAllowed:
    """Tenant en TRIAL tiene acceso completo — igual que ACTIVE (FIX-C)."""

    def test_trial_tenant_owner_can_list_patients(self, db: None) -> None:
        """Owner de un tenant TRIAL recibe 200 en GET /pacientes/."""
        from apps.tenancy.models import Tenant

        # Arrange — tenant en periodo de prueba (estado inicial al registrarse)
        tenant = TenantFactory(status=Tenant.Status.TRIAL)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="owner", is_active=True)
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(PACIENTES_LIST_URL)

        # Assert — TRIAL está en ["active", "trial"] → membership resuelta → 200
        assert response.status_code == 200, (
            f"GET /pacientes/ con tenant TRIAL esperaba 200, obtuvo {response.status_code}. "
            "BUG: las clinicas en periodo de prueba quedan bloqueadas desde el primer dia."
        )

    def test_trial_tenant_owner_can_list_citas(self, db: None) -> None:
        """Owner de un tenant TRIAL recibe 200 en GET /agenda/citas/."""
        from apps.tenancy.models import Tenant

        # Arrange
        tenant = TenantFactory(status=Tenant.Status.TRIAL)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="owner", is_active=True)
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(CITAS_LIST_URL)

        # Assert
        assert response.status_code == 200, (
            f"GET /agenda/citas/ con tenant TRIAL esperaba 200, obtuvo {response.status_code}."
        )

    def test_trial_tenant_admin_can_access_agenda_config(self, db: None) -> None:
        """Admin de un tenant TRIAL recibe 200 en GET /agenda/config/."""
        from apps.tenancy.models import Tenant

        # Arrange
        tenant = TenantFactory(status=Tenant.Status.TRIAL)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="admin", is_active=True)
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(AGENDA_CONFIG_URL)

        # Assert
        assert response.status_code == 200, (
            f"GET /agenda/config/ con tenant TRIAL esperaba 200, obtuvo {response.status_code}."
        )

    def test_suspended_tenant_still_blocked_after_fix(self, db: None) -> None:
        """Regresión: SUSPENDED sigue bloqueado aunque TRIAL ahora esté permitido."""
        from apps.tenancy.models import Tenant

        # Arrange
        tenant = TenantFactory(status=Tenant.Status.SUSPENDED)
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="owner", is_active=True)
        token = _get_jwt_token(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Act
        response = client.get(PACIENTES_LIST_URL)

        # Assert — SUSPENDED no está en ["active", "trial"] → None → 403
        assert response.status_code == 403, (
            f"GET /pacientes/ con tenant SUSPENDIDO esperaba 403, obtuvo {response.status_code}. "
            "REGRESION: FIX-C no debe haber desbloqueado a tenants suspendidos."
        )


# ===========================================================================
# BLOQUE 9: OPTIONS preflight nunca bloqueado por HasClinicRole (FIX-B)
# ===========================================================================
#
# OPTIONS es el preflight CORS que el navegador envía antes de cualquier
# petición cross-origin con credenciales. Si OPTIONS devuelve 403, el
# navegador cancela la petición real y el frontend queda completamente roto.
#
# HasClinicRole.has_permission devuelve True para OPTIONS sin importar el rol.
# IsAuthenticated (primera en permission_classes) ya exige token válido.
#
# ===========================================================================


class TestOptionsPreflightNeverBlocked:
    """OPTIONS nunca debe devolver 403 por la política de roles (FIX-B)."""

    @pytest.mark.parametrize(
        "url",
        [
            PACIENTES_LIST_URL,
            DOCTORES_LIST_URL,
            CONSULTORIOS_LIST_URL,
            CITAS_LIST_URL,
            AGENDA_CONFIG_URL,
        ],
    )
    def test_options_not_blocked_by_role_policy(self, db: None, url: str) -> None:
        """OPTIONS en cualquier endpoint no devuelve 403 para usuario con membresía.

        Nota: DRF puede devolver 200 o 204 para OPTIONS dependiendo del renderer.
        Lo importante es que NO sea 403 (que rompería el preflight CORS).
        """
        # Arrange — cualquier rol; usamos 'readonly' que es el más restrictivo en escritura
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, "readonly")

        # Act
        with _role_context(tenant, "readonly", user):
            response = client.options(url)

        # Assert — no debe ser 403 (preflight roto) ni 401 (autenticado)
        assert response.status_code not in (401, 403), (
            f"OPTIONS {url} con rol 'readonly' devolvio {response.status_code}. "
            "BUG: OPTIONS debe pasar la policy de roles para no romper el preflight CORS."
        )

    @pytest.mark.parametrize(
        "url",
        [
            PACIENTES_LIST_URL,
            CITAS_LIST_URL,
            AGENDA_CONFIG_URL,
        ],
    )
    def test_options_not_blocked_for_finance_role(self, db: None, url: str) -> None:
        """OPTIONS no se bloquea aunque el rol finance tenga acceso limitado al recurso.

        finance no puede hacer GET /agenda/citas/ ni GET /agenda/config/,
        pero OPTIONS nunca debe dar 403.
        """
        # Arrange
        tenant = TenantFactory()
        client, user = _make_member_client(tenant, "finance")

        # Act
        with _role_context(tenant, "finance", user):
            response = client.options(url)

        # Assert
        assert response.status_code not in (401, 403), (
            f"OPTIONS {url} con rol 'finance' devolvio {response.status_code}. "
            "BUG: OPTIONS nunca debe ser bloqueado por la policy de roles (preflight CORS)."
        )


# ===========================================================================
# BLOQUE 10: AppointmentReschedulePermission (FIX-D)
# ===========================================================================
#
# Endpoint: POST /api/v1/agenda/citas/<id>/reagendar/
# Usa AppointmentPermission (la misma que POST /citas/).
#
# Matriz heredada de AppointmentPermission:
#   POST → owner, admin, doctor, reception   (permitidos)
#   POST → nurse, finance, readonly          (denegados → 403)
#
# ===========================================================================


class TestAppointmentReschedulePermission:
    """POST /agenda/citas/<id>/reagendar/ — permisos por rol (FIX-D)."""

    @pytest.mark.parametrize(
        "role",
        ["owner", "admin", "doctor", "reception"],
    )
    def test_reagendar_allowed_for_permitted_roles(self, db: None, role: str) -> None:
        """owner, admin, doctor, reception reciben 200 o 400 (nunca 403) al reagendar.

        200 = reagendamiento exitoso.
        400 = ValidationError de negocio (conflicto de horario, etc.).
        403 sería un bug de permisos.
        """
        # Arrange
        from apps.agenda.models import Appointment

        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        role_offset = {"owner": 200, "admin": 201, "doctor": 202, "reception": 203}
        starts = _BASE_DT + datetime.timedelta(hours=role_offset[role])
        ends = starts + datetime.timedelta(minutes=30)
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=starts,
        )
        client, user = _make_member_client(tenant, role)

        # Nuevo horario: 1 hora después del original (sin conflicto)
        new_starts = starts + datetime.timedelta(hours=10)
        new_ends = new_starts + datetime.timedelta(minutes=30)

        # Act
        with _role_context(tenant, role, user):
            response = client.post(
                _cita_reagendar_url(appt.id),
                data={
                    "starts_at": new_starts.isoformat(),
                    "ends_at": new_ends.isoformat(),
                },
                format="json",
            )

        # Assert — 200 (ok) o 400 (validación de negocio), NUNCA 403 (permiso)
        assert response.status_code in (200, 400), (
            f"POST /reagendar/ con rol '{role}' esperaba 200/400, "
            f"obtuvo {response.status_code}. "
            "BUG: este rol deberia tener permiso para reagendar segun la matriz."
        )

    @pytest.mark.parametrize(
        "role",
        ["nurse", "finance", "readonly"],
    )
    def test_reagendar_denied_for_restricted_roles(self, db: None, role: str) -> None:
        """nurse, finance, readonly reciben 403 al intentar reagendar una cita."""
        # Arrange
        from apps.agenda.models import Appointment

        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        role_offset = {"nurse": 210, "finance": 211, "readonly": 212}
        starts = _BASE_DT + datetime.timedelta(hours=role_offset[role])
        appt = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            starts_at=starts,
        )
        client, user = _make_member_client(tenant, role)

        new_starts = starts + datetime.timedelta(hours=10)
        new_ends = new_starts + datetime.timedelta(minutes=30)

        # Act
        with _role_context(tenant, role, user):
            response = client.post(
                _cita_reagendar_url(appt.id),
                data={
                    "starts_at": new_starts.isoformat(),
                    "ends_at": new_ends.isoformat(),
                },
                format="json",
            )

        # Assert
        assert response.status_code == 403, (
            f"POST /reagendar/ con rol '{role}' esperaba 403, "
            f"obtuvo {response.status_code}. "
            "BUG: este rol NO debe poder reagendar citas segun la matriz."
        )
