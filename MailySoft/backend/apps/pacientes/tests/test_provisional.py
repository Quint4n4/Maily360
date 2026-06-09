"""
Tests para la feature de expediente PROVISIONAL (is_provisional).

Cubre:
- patient_create_quick (service): campos iniciales, record_number, tenant, auditoría.
- patient_update con provisional → complete: auto-clearance de is_provisional.
- patient_update con provisional → incompleto: sigue provisional.
- patient_update intentando setear is_provisional directamente: ValidationError (inmutable).
- API POST /api/v1/pacientes/rapido/ (PatientQuickCreateApi):
    - 201 con solo first_name + paternal_surname.
    - 201 con todos los campos opcionales.
    - 400 cuando falta first_name.
    - 400 cuando falta paternal_surname.
    - 400 cuando phone tiene formato inválido.
    - 401 sin autenticación.
    - 403 sin tenant activo.
    - is_provisional=True expuesto en la respuesta.
    - Aislamiento multi-tenant: tenant A no puede crear en tenant B (no ve datos de B).

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.
Se reutilizan TenantFactory, UserFactory, PatientFactory, TenantMembershipFactory
y el helper _tenant_context del módulo test_apis.py.
"""

import datetime
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.pacientes.models import Patient
from apps.pacientes.services import patient_create, patient_create_quick, patient_update
from tests.factories import (
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URL de la nueva vista
# ---------------------------------------------------------------------------

QUICK_URL = "/api/v1/pacientes/rapido/"


# ---------------------------------------------------------------------------
# Helpers compartidos (espejo del patrón en test_apis.py)
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Inyecta el tenant en la vista y en el TenantManager para el test.

    Replica el helper de test_apis.py para no importar desde otro módulo
    de test (evita acoplamiento de orden de importación en pytest).
    """
    with (
        patch(
            "apps.pacientes.views.get_current_tenant",
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


def _make_member_client(tenant: Any, role: str = "reception") -> APIClient:
    """Crea un user con TenantMembership del rol indicado y devuelve un cliente autenticado.

    Para PatientQuickCreateApi el rol mínimo es 'reception' (mismo que POST /pacientes/).
    """
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return _make_auth_client(user)


def _create_full_patient(tenant: Any, user: Any, **overrides: Any) -> Patient:
    """Crea un paciente COMPLETO (no provisional) vía patient_create.

    Usado en tests de transición de is_provisional.
    """
    defaults: dict[str, Any] = {
        "first_name": "Rosa",
        "paternal_surname": "López",
        "maternal_surname": "García",
        "date_of_birth": datetime.date(1990, 5, 15),
        "sex": "F",
        "phone": "5512340001",
        "curp": "",
        "email": "",
        "notes": "",
    }
    defaults.update(overrides)
    return patient_create(tenant=tenant, user=user, **defaults)


# ===========================================================================
# patient_create_quick — servicio
# ===========================================================================


class TestPatientCreateQuickService:
    """Casos de uso del service patient_create_quick."""

    def test_create_quick_minimal_fields_sets_is_provisional_true(self, db: None) -> None:
        """Con solo nombre y apellido paterno el paciente queda como provisional."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Carlos",
            paternal_surname="Mendoza",
        )

        # Assert
        assert patient.is_provisional is True

    def test_create_quick_date_of_birth_is_none(self, db: None) -> None:
        """El expediente provisional NO tiene fecha de nacimiento."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Carlos",
            paternal_surname="Mendoza",
        )

        # Assert
        assert patient.date_of_birth is None

    def test_create_quick_sex_is_empty_string(self, db: None) -> None:
        """El expediente provisional NO tiene sexo asignado (cadena vacía)."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Carlos",
            paternal_surname="Mendoza",
        )

        # Assert
        assert patient.sex == ""

    def test_create_quick_record_number_is_generated_and_not_empty(self, db: None) -> None:
        """El número de expediente se genera automáticamente (no vacío, formato EXP-)."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Carlos",
            paternal_surname="Mendoza",
        )

        # Assert
        assert patient.record_number != ""
        assert patient.record_number.startswith("EXP-")

    def test_create_quick_record_number_uses_same_sequence_as_patient_create(
        self, db: None
    ) -> None:
        """Los consecutivos de patient_create y patient_create_quick son compartidos por tenant."""
        # Arrange
        from django.utils import timezone

        tenant = TenantFactory()
        user = UserFactory()
        year = timezone.now().year

        # Act — primero un paciente completo, luego uno provisional
        first = _create_full_patient(tenant, user, phone="5500000001")
        second = patient_create_quick(
            tenant=tenant, user=user, first_name="Ana", paternal_surname="Torres"
        )

        # Assert — consecutivos sin saltos
        assert first.record_number == f"EXP-{year}-00001"
        assert second.record_number == f"EXP-{year}-00002"

    def test_create_quick_patient_belongs_to_correct_tenant(self, db: None) -> None:
        """El paciente provisional queda asignado al tenant indicado."""
        # Arrange
        tenant = TenantFactory()
        other_tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Carlos",
            paternal_surname="Mendoza",
        )

        # Assert
        assert patient.tenant_id == tenant.id
        assert patient.tenant_id != other_tenant.id

    def test_create_quick_sets_created_by(self, db: None) -> None:
        """El campo created_by debe quedar ligado al usuario que hace la llamada."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Carlos",
            paternal_surname="Mendoza",
        )

        # Assert
        assert patient.created_by_id == user.id

    def test_create_quick_with_optional_phone_persists_phone(self, db: None) -> None:
        """Cuando se pasa phone, queda guardado en el expediente provisional."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Carlos",
            paternal_surname="Mendoza",
            phone="5512345678",
        )

        # Assert
        patient.refresh_from_db()
        assert patient.phone == "5512345678"

    def test_create_quick_without_phone_defaults_to_empty(self, db: None) -> None:
        """Sin phone el campo queda vacío (no None)."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Carlos",
            paternal_surname="Mendoza",
        )

        # Assert
        assert patient.phone == ""

    def test_create_quick_with_maternal_surname_persists_it(self, db: None) -> None:
        """El apellido materno opcional se persiste correctamente."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant,
            user=user,
            first_name="Luis",
            paternal_surname="García",
            maternal_surname="Pérez",
        )

        # Assert
        patient.refresh_from_db()
        assert patient.maternal_surname == "Pérez"

    def test_create_quick_is_active_defaults_to_true(self, db: None) -> None:
        """El expediente provisional está activo por defecto."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Sofía", paternal_surname="Ramos"
        )

        # Assert
        assert patient.is_active is True


# ===========================================================================
# patient_update — transición automática de is_provisional
# ===========================================================================


class TestPatientUpdateProvisionalTransition:
    """patient_update gestiona is_provisional automáticamente al completar datos."""

    def test_update_provisional_with_all_missing_fields_clears_flag(self, db: None) -> None:
        """Completar date_of_birth + sex + phone en un provisional → is_provisional=False."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Lucía", paternal_surname="Vargas"
        )
        assert patient.is_provisional is True  # pre-condición

        # Act — completar los tres campos que faltaban
        updated = patient_update(
            patient=patient,
            user=user,
            date_of_birth=datetime.date(1995, 3, 10),
            sex="F",
            phone="5512349999",
        )

        # Assert
        assert updated.is_provisional is False

    def test_update_provisional_completing_only_sex_stays_provisional(self, db: None) -> None:
        """Completar SOLO el sexo en un provisional no limpia is_provisional."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Pedro", paternal_surname="Álvarez"
        )

        # Act — solo sex, faltan date_of_birth y phone
        updated = patient_update(patient=patient, user=user, sex="M")

        # Assert
        assert updated.is_provisional is True

    def test_update_provisional_completing_only_date_of_birth_stays_provisional(
        self, db: None
    ) -> None:
        """Completar SOLO la fecha de nacimiento no limpia is_provisional."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Laura", paternal_surname="Cruz"
        )

        # Act — solo date_of_birth, faltan sex y phone
        updated = patient_update(
            patient=patient,
            user=user,
            date_of_birth=datetime.date(1988, 7, 22),
        )

        # Assert
        assert updated.is_provisional is True

    def test_update_provisional_completing_only_phone_stays_provisional(self, db: None) -> None:
        """Completar SOLO el teléfono no limpia is_provisional."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Tomás", paternal_surname="Ríos"
        )

        # Act — solo phone, faltan date_of_birth y sex
        updated = patient_update(patient=patient, user=user, phone="5500001234")

        # Assert
        assert updated.is_provisional is True

    def test_update_provisional_with_two_of_three_fields_stays_provisional(
        self, db: None
    ) -> None:
        """Completar dos de tres campos (sex + phone, sin date_of_birth) → sigue provisional."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Elena", paternal_surname="Soto"
        )

        # Act — sex y phone, pero NO date_of_birth
        updated = patient_update(patient=patient, user=user, sex="F", phone="5512340099")

        # Assert
        assert updated.is_provisional is True

    def test_update_provisional_transition_persists_to_db(self, db: None) -> None:
        """La transición is_provisional=False se persiste en la base de datos."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Mario", paternal_surname="León"
        )

        # Act
        patient_update(
            patient=patient,
            user=user,
            date_of_birth=datetime.date(1980, 12, 1),
            sex="M",
            phone="5599887766",
        )

        # Assert — verificar desde BD, no desde la instancia en memoria
        patient.refresh_from_db()
        assert patient.is_provisional is False

    def test_update_non_provisional_patient_is_provisional_stays_false(self, db: None) -> None:
        """Actualizar un paciente NO provisional nunca activa is_provisional."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        # PatientFactory crea un paciente completo con is_provisional=False por defecto
        patient = PatientFactory(tenant=tenant, is_provisional=False, phone="5500000001")

        # Act — actualizar phone (sin cambiar is_provisional)
        updated = patient_update(patient=patient, user=user, phone="5599999999")

        # Assert — sigue False
        assert updated.is_provisional is False


# ===========================================================================
# patient_update — is_provisional es INMUTABLE para el cliente
# ===========================================================================


class TestPatientUpdateIsProvisionalImmutable:
    """is_provisional está en _IMMUTABLE_FIELDS: no puede setearse por el cliente."""

    def test_update_passing_is_provisional_raises_validation_error(self, db: None) -> None:
        """Intentar pasar is_provisional en patient_update lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Nadia", paternal_surname="Torres"
        )

        # Act & Assert
        with pytest.raises(ValidationError, match="is_provisional"):
            patient_update(patient=patient, user=user, is_provisional=False)

    def test_update_passing_is_provisional_true_also_raises(self, db: None) -> None:
        """No se puede forzar is_provisional=True tampoco."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant, is_provisional=False)

        # Act & Assert
        with pytest.raises(ValidationError, match="is_provisional"):
            patient_update(patient=patient, user=user, is_provisional=True)

    def test_update_is_provisional_not_changed_in_db_after_rejection(self, db: None) -> None:
        """Tras el rechazo, is_provisional no cambia en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = patient_create_quick(
            tenant=tenant, user=user, first_name="Ingrid", paternal_surname="Campos"
        )
        original_value = patient.is_provisional  # True

        # Act — intent to mutate; ignoramos el error intencionalmente
        with pytest.raises(ValidationError):
            patient_update(patient=patient, user=user, is_provisional=False)

        # Assert — BD no cambió
        patient.refresh_from_db()
        assert patient.is_provisional == original_value


# ===========================================================================
# API POST /api/v1/pacientes/rapido/
# ===========================================================================


class TestPatientQuickCreateApi:
    """POST /api/v1/pacientes/rapido/ — alta provisional."""

    def test_quick_create_returns_201_with_minimal_payload(self, db: None) -> None:
        """Solo first_name + paternal_surname produce 201."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {"first_name": "Silvia", "paternal_surname": "Morales"}

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201

    def test_quick_create_response_contains_is_provisional_true(self, db: None) -> None:
        """La respuesta incluye is_provisional=True."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {"first_name": "Silvia", "paternal_surname": "Morales"}

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["is_provisional"] is True

    def test_quick_create_response_contains_record_number(self, db: None) -> None:
        """La respuesta incluye un record_number generado (formato EXP-)."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {"first_name": "Silvia", "paternal_surname": "Morales"}

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert "record_number" in data
        assert data["record_number"].startswith("EXP-")

    def test_quick_create_returns_201_with_all_optional_fields(self, db: None) -> None:
        """Pasar también maternal_surname y phone produce 201."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {
            "first_name": "Jorge",
            "paternal_surname": "Núñez",
            "maternal_surname": "Díaz",
            "phone": "5512340001",
        }

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201

    def test_quick_create_missing_first_name_returns_400(self, db: None) -> None:
        """Sin first_name la validación del InputSerializer devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {"paternal_surname": "Morales"}  # sin first_name

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_quick_create_missing_paternal_surname_returns_400(self, db: None) -> None:
        """Sin paternal_surname la validación del InputSerializer devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {"first_name": "Silvia"}  # sin paternal_surname

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_quick_create_invalid_phone_returns_400(self, db: None) -> None:
        """Teléfono con formato inválido (demasiado corto) devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {
            "first_name": "Ana",
            "paternal_surname": "Ramos",
            "phone": "123",  # demasiado corto — no pasa _validate_phone
        }

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_quick_create_returns_401_without_auth(self, db: None) -> None:
        """Sin autenticación la vista devuelve 401."""
        # Arrange
        client = APIClient()
        payload = {"first_name": "Ana", "paternal_surname": "Ramos"}

        # Act
        response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 401

    def test_quick_create_without_tenant_returns_403(self, db: None) -> None:
        """Cuando get_current_tenant() devuelve None la vista retorna 403."""
        # Arrange — usuario autenticado pero sin tenant resuelto (sin mock)
        user = UserFactory()
        client = _make_auth_client(user)
        payload = {"first_name": "Ana", "paternal_surname": "Ramos"}

        # Act — sin _tenant_context: el middleware real pone tenant=None
        response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 403

    def test_quick_create_persists_patient_to_database(self, db: None) -> None:
        """El paciente provisional debe existir en BD tras el 201."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {"first_name": "Beatriz", "paternal_surname": "Espinosa"}

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        patient_id = response.json()["id"]
        assert Patient.all_objects.filter(id=patient_id, is_provisional=True).exists()

    def test_quick_create_patient_date_of_birth_is_null_in_response(self, db: None) -> None:
        """La respuesta tiene date_of_birth=null (campo vacío en provisional)."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {"first_name": "Héctor", "paternal_surname": "Fuentes"}

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        assert response.json()["date_of_birth"] is None

    def test_quick_create_patient_sex_is_empty_in_response(self, db: None) -> None:
        """La respuesta tiene sex='' (campo vacío en provisional)."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {"first_name": "Héctor", "paternal_surname": "Fuentes"}

        # Act
        with _tenant_context(tenant):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        assert response.json()["sex"] == ""


# ===========================================================================
# Aislamiento multi-tenant — API quick-create
# ===========================================================================


class TestPatientQuickCreateApiTenantIsolation:
    """Un usuario del tenant A no puede crear ni ver pacientes del tenant B."""

    def test_quick_create_patient_belongs_only_to_requesting_tenant(self, db: None) -> None:
        """El paciente creado queda en el tenant del request, no en otro tenant."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        client = _make_member_client(tenant_a, role="reception")
        payload = {"first_name": "Rosa", "paternal_surname": "Ibáñez"}

        # Act — request con contexto del tenant A
        with _tenant_context(tenant_a):
            response = client.post(QUICK_URL, data=payload, format="json")

        # Assert — 201, el paciente es del tenant A
        assert response.status_code == 201
        patient_id = response.json()["id"]
        patient_in_db = Patient.all_objects.get(id=patient_id)
        assert patient_in_db.tenant_id == tenant_a.id

        # El tenant B no tiene ningún paciente creado por esta operación
        assert Patient.all_objects.filter(tenant=tenant_b).count() == 0

    def test_quick_create_via_context_tenant_b_does_not_see_tenant_a_patient(
        self, db: None
    ) -> None:
        """El paciente creado en tenant A no es visible desde el contexto del tenant B."""
        # Arrange — crear un provisional en tenant A
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        provisional = patient_create_quick(
            tenant=tenant_a, user=user, first_name="Valeria", paternal_surname="Reyes"
        )

        # Act — activar contexto del tenant B y pedir lista
        from apps.core.tenant_context import set_current_tenant, set_tenant_context_active

        set_current_tenant(tenant_b)
        set_tenant_context_active(True)

        from apps.pacientes.selectors import patient_list

        qs = patient_list()

        # Assert — el provisional del tenant A no debe aparecer
        ids = list(qs.values_list("id", flat=True))
        assert provisional.id not in ids
