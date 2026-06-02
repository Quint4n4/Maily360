"""
Tests de las APIs de la app pacientes (views.py).

Cubre:
- GET  /api/v1/pacientes/ — autenticación, paginación, búsqueda.
- POST /api/v1/pacientes/ — 201 creación, 400 validación, 403 sin tenant.
- GET  /api/v1/pacientes/<uuid>/ — 200 detalle, 404 no existe.
- PATCH /api/v1/pacientes/<uuid>/ — 200 update parcial, 400 campo inmutable.
- DELETE /api/v1/pacientes/<uuid>/ — 204 soft-disable.
- TestPatientJWTIsolation — verifica FIX-A2: con JWT real el tenant se resuelve
  correctamente y solo se ven los pacientes del tenant propio.

Nota sobre el contexto de tenant en tests de API con force_authenticate:
  El TenantMiddleware resuelve el tenant a partir de `request.user` del objeto
  HttpRequest de Django (resuelto por AuthenticationMiddleware antes de que el
  middleware de tenant se ejecute). El `force_authenticate` de DRF sólo afecta
  al wrapper DRF Request DENTRO del APIView, no al HttpRequest del middleware.
  Por eso, en esos tests mockeamos `get_current_tenant` a nivel de la vista
  para inyectar el tenant directamente, y mockeamos el TenantManager activando
  el contexto con set_current_tenant + set_tenant_context_active para que las
  queries se filtren correctamente dentro del handler.

  La clase TestPatientJWTIsolation (al final de este archivo) prueba el flujo
  REAL con JWT: obtiene un token vía POST /api/v1/auth/login/ y lo usa en el
  header Authorization: Bearer. Este test verifica que FIX-A2 funciona
  correctamente sin ningún mock de tenant.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import uuid as uuid_module
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.pacientes.models import Patient
from tests.factories import (
    PatientFactory,
    TenantFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_PAYLOAD: dict[str, Any] = {
    "first_name": "Ana",
    "paternal_surname": "Martínez",
    "maternal_surname": "Ríos",
    "date_of_birth": "1992-07-04",
    "sex": "F",
    "phone": "5512340010",
    "curp": "",
    "email": "",
    "notes": "",
}

LIST_URL = "/api/v1/pacientes/"


def _detail_url(patient_id: Any) -> str:
    return f"/api/v1/pacientes/{patient_id}/"


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Context manager que simula el efecto completo del TenantMiddleware
    para un tenant dado, durante un request de test.

    Problema: `force_authenticate` solo afecta el DRF Request wrapper (dentro
    del APIView). El TenantMiddleware recibe el HttpRequest de Django donde
    `request.user` aún es `AnonymousUser`, por lo que el middleware siempre
    resuelve `tenant=None` y sobrescribe el thread-local.

    Solución: mockeamos tanto (a) `get_current_tenant` en el módulo de la vista
    (para que la vista reciba el tenant correcto) como (b) `get_current_tenant`
    e `is_tenant_context_active` en el módulo del manager TenantManager (para
    que las queries ORM filtren por el tenant inyectado durante el request).
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


# ===========================================================================
# GET /api/v1/pacientes/
# ===========================================================================


class TestPatientListApi:
    """GET /api/v1/pacientes/ — lista de pacientes."""

    def test_list_patients_requires_auth(self, db: None, api_client: APIClient) -> None:
        """Sin token de autenticación debe devolver 401."""
        # Act
        response = api_client.get(LIST_URL)

        # Assert
        assert response.status_code == 401

    def test_list_patients_returns_200_for_authenticated_user(self, db: None) -> None:
        """Usuario autenticado con tenant inyectado recibe 200."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200

    def test_list_patients_returns_paginated_response(self, db: None) -> None:
        """La respuesta incluye la estructura de paginación DRF o lista directa."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        PatientFactory.create_batch(3, tenant=tenant, is_active=True)
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_list_patients_search_param_filters_results(self, db: None) -> None:
        """El parámetro ?search= filtra por nombre dentro del tenant del usuario."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        PatientFactory(tenant=tenant, first_name="Valentina", is_active=True)
        PatientFactory(tenant=tenant, first_name="Roberto", is_active=True)
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"search": "Valentina"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 1
        assert results[0]["first_name"] == "Valentina"

    def test_list_patients_only_shows_own_tenant_patients(self, db: None) -> None:
        """El listado solo muestra pacientes del tenant activo."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()

        PatientFactory.create_batch(2, tenant=tenant_a, is_active=True)
        PatientFactory.create_batch(3, tenant=tenant_b, is_active=True)
        client = _make_auth_client(user)

        # Act — contexto del tenant A
        with _tenant_context(tenant_a):
            response = client.get(LIST_URL)

        # Assert — solo los 2 del tenant A
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 2


# ===========================================================================
# POST /api/v1/pacientes/
# ===========================================================================


class TestPatientCreateApi:
    """POST /api/v1/pacientes/ — creación de paciente."""

    def test_create_patient_requires_auth(self, db: None, api_client: APIClient) -> None:
        """Sin autenticación debe devolver 401."""
        # Act
        response = api_client.post(LIST_URL, data=_VALID_PAYLOAD, format="json")

        # Assert
        assert response.status_code == 401

    def test_create_patient_returns_201(self, db: None) -> None:
        """POST válido con tenant activo devuelve 201 y record_number generado."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.post(LIST_URL, data=_VALID_PAYLOAD, format="json")

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["first_name"] == "Ana"
        assert "record_number" in data
        assert data["record_number"].startswith("EXP-")

    def test_create_patient_persists_to_database(self, db: None) -> None:
        """El paciente creado vía API debe existir en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.post(LIST_URL, data=_VALID_PAYLOAD, format="json")

        # Assert
        assert response.status_code == 201
        patient_id = response.json()["id"]
        assert Patient.all_objects.filter(id=patient_id).exists()

    def test_create_patient_validation_error_returns_400_missing_required(
        self, db: None
    ) -> None:
        """Faltar un campo requerido (first_name) debe devolver 400."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        client = _make_auth_client(user)
        incomplete_payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "first_name"}

        # Act
        with _tenant_context(tenant):
            response = client.post(LIST_URL, data=incomplete_payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_patient_validation_error_returns_400_invalid_sex(self, db: None) -> None:
        """Sexo inválido debe devolver 400 (rechazado por InputSerializer)."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        client = _make_auth_client(user)
        payload = {**_VALID_PAYLOAD, "sex": "Z"}

        # Act
        with _tenant_context(tenant):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_patient_duplicate_curp_returns_400(self, db: None) -> None:
        """CURP duplicada en el mismo tenant devuelve 400 con mensaje."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        curp = "MARL920704MDFNRS04"
        PatientFactory(tenant=tenant, curp=curp, is_active=True)
        client = _make_auth_client(user)
        payload = {**_VALID_PAYLOAD, "curp": curp}

        # Act
        with _tenant_context(tenant):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400
        # detail es una lista de mensajes (exc.messages) tras FIX-B7
        detail = response.json().get("detail", [])
        detail_str = " ".join(detail) if isinstance(detail, list) else detail
        assert "CURP" in detail_str

    def test_create_patient_without_tenant_returns_403(self, db: None) -> None:
        """Cuando get_current_tenant() devuelve None la vista retorna 403."""
        # Arrange — mockeamos explícitamente None para simular ausencia de tenant
        user = UserFactory()
        client = _make_auth_client(user)

        # Act — sin mock de tenant (el middleware real pone None porque es AnonymousUser)
        response = client.post(LIST_URL, data=_VALID_PAYLOAD, format="json")

        # Assert
        assert response.status_code == 403


# ===========================================================================
# GET /api/v1/pacientes/<uuid>/
# ===========================================================================


class TestPatientDetailApi:
    """GET /api/v1/pacientes/<uuid>/ — detalle de paciente."""

    def test_get_patient_detail_returns_200(self, db: None) -> None:
        """GET con UUID válido del propio tenant devuelve 200."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.get(_detail_url(patient.id))

        # Assert
        assert response.status_code == 200
        assert response.json()["id"] == str(patient.id)

    def test_get_patient_detail_returns_404_for_unknown_uuid(self, db: None) -> None:
        """UUID inexistente devuelve 404."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.get(_detail_url(uuid_module.uuid4()))

        # Assert
        assert response.status_code == 404

    def test_get_patient_detail_returns_404_for_other_tenant_patient(self, db: None) -> None:
        """Paciente de otro tenant retorna 404 (no 403; sin revelar existencia)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        client = _make_auth_client(user)

        # Act — contexto del tenant A, pero el paciente es del tenant B
        with _tenant_context(tenant_a):
            response = client.get(_detail_url(patient_b.id))

        # Assert
        assert response.status_code == 404

    def test_get_patient_detail_requires_auth(self, db: None) -> None:
        """Sin autenticación devuelve 401."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = APIClient()

        # Act
        response = client.get(_detail_url(patient.id))

        # Assert
        assert response.status_code == 401


# ===========================================================================
# PATCH /api/v1/pacientes/<uuid>/
# ===========================================================================


class TestPatientPatchApi:
    """PATCH /api/v1/pacientes/<uuid>/ — actualización parcial."""

    def test_patch_patient_returns_200_with_updated_fields(self, db: None) -> None:
        """PATCH válido devuelve 200 con los datos actualizados."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant, phone="5500000001")
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id), data={"phone": "5599999999"}, format="json"
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["phone"] == "5599999999"

    def test_patch_patient_record_number_returns_400(self, db: None) -> None:
        """Intentar cambiar record_number via PATCH devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id),
                data={"record_number": "MODIFICADO"},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_patient_empty_body_returns_400(self, db: None) -> None:
        """PATCH sin campos válidos devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.patch(_detail_url(patient.id), data={}, format="json")

        # Assert
        assert response.status_code == 400

    def test_patch_patient_returns_404_for_other_tenant(self, db: None) -> None:
        """PATCH a paciente de otro tenant devuelve 404."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant_a):
            response = client.patch(
                _detail_url(patient_b.id), data={"phone": "5599999999"}, format="json"
            )

        # Assert
        assert response.status_code == 404


# ===========================================================================
# DELETE /api/v1/pacientes/<uuid>/
# ===========================================================================


class TestPatientDeleteApi:
    """DELETE /api/v1/pacientes/<uuid>/ — desactivación soft."""

    def test_delete_patient_returns_204(self, db: None) -> None:
        """DELETE válido devuelve 204 No Content."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            response = client.delete(_detail_url(patient.id))

        # Assert
        assert response.status_code == 204

    def test_delete_patient_sets_inactive_in_db(self, db: None) -> None:
        """Tras DELETE el registro en BD tiene is_active=False (no fue borrado)."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        patient_id = patient.id
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant):
            client.delete(_detail_url(patient.id))

        # Assert
        patient_in_db = Patient.all_objects.get(id=patient_id)
        assert patient_in_db.is_active is False
        assert patient_in_db.deleted_at is None  # soft-disable, no soft-delete

    def test_delete_patient_returns_401_without_auth(self, db: None) -> None:
        """DELETE sin autenticación devuelve 401."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = APIClient()

        # Act
        response = client.delete(_detail_url(patient.id))

        # Assert
        assert response.status_code == 401

    def test_delete_patient_returns_404_for_other_tenant(self, db: None) -> None:
        """DELETE a paciente de otro tenant devuelve 404."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        client = _make_auth_client(user)

        # Act
        with _tenant_context(tenant_a):
            response = client.delete(_detail_url(patient_b.id))

        # Assert
        assert response.status_code == 404


# ===========================================================================
# Verificación de FIX-A2: JWT real + aislamiento de tenant
# ===========================================================================


class TestPatientJWTIsolation:
    """Prueba que FIX-A2 funciona con JWT REAL (sin mock de tenant).

    Este es el test obligatorio del FIX-A2. Obtiene un token JWT real usando
    POST /api/v1/auth/login/ y lo usa para llamar a GET /api/v1/pacientes/.
    Sin FIX-A2 (TenantAPIView), el request con JWT devolvería 0 pacientes o error
    porque TenantMiddleware no puede resolver el tenant (request.user es AnonymousUser
    cuando el middleware corre).

    Si este test PASA sin ningún mock de get_current_tenant, FIX-A2 está correcto.
    """

    def test_jwt_auth_resolves_tenant_and_returns_own_patients(self, db: None) -> None:
        """Con JWT real, GET /pacientes/ devuelve solo los pacientes del tenant del user.

        Flujo:
        1. Crea tenant A + user con membresía activa + 2 pacientes en A.
        2. Crea tenant B con 3 pacientes (otro tenant, no debe verse).
        3. Obtiene JWT real vía POST /api/v1/auth/login/.
        4. Llama GET /api/v1/pacientes/ con el Bearer token.
        5. Verifica: status 200, solo los 2 pacientes del tenant A.
        """
        from tests.factories import TenantMembershipFactory

        # Arrange — tenant A: user con membresía activa
        tenant_a = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="doctor", is_active=True)

        # Pacientes del tenant A (los que SÍ debe ver)
        PatientFactory.create_batch(2, tenant=tenant_a, is_active=True)

        # Tenant B con pacientes que NO debe ver
        tenant_b = TenantFactory()
        PatientFactory.create_batch(3, tenant=tenant_b, is_active=True)

        # Act — obtener JWT real
        login_client = APIClient()
        login_response = login_client.post(
            "/api/v1/auth/login/",
            data={"email": user.email, "password": "password-segura-123"},
            format="json",
        )
        assert login_response.status_code == 200, (
            f"Login fallido: {login_response.json()}"
        )
        access_token: str = login_response.json()["access"]

        # Act — usar el JWT en el header Authorization
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.get(LIST_URL)

        # Assert — 200 y solo los 2 pacientes del tenant A
        assert response.status_code == 200, f"Esperado 200, obtenido {response.status_code}: {response.json()}"
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 2, (
            f"Esperados 2 pacientes del tenant A, obtenidos {len(results)}. "
            "Si obtuvo 0, FIX-A2 (TenantAPIView) no está funcionando. "
            "Si obtuvo 5, hay fuga cross-tenant."
        )

    def test_jwt_auth_without_membership_returns_empty_list(self, db: None) -> None:
        """Usuario con JWT pero SIN membresía activa en ningún tenant recibe lista vacía.

        TenantAPIView debe resolver tenant=None → TenantManager devuelve qs.none().
        """
        # Arrange — user sin membresías
        user = UserFactory()
        tenant = TenantFactory()
        PatientFactory.create_batch(3, tenant=tenant, is_active=True)

        # Act — obtener JWT real
        login_client = APIClient()
        login_response = login_client.post(
            "/api/v1/auth/login/",
            data={"email": user.email, "password": "password-segura-123"},
            format="json",
        )
        assert login_response.status_code == 200
        access_token = login_response.json()["access"]

        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.get(LIST_URL)

        # Assert — 200 pero sin resultados (falla segura)
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 0, (
            f"Sin membresía debería devolver 0 pacientes, obtuvo {len(results)}."
        )

    def test_jwt_cross_tenant_isolation(self, db: None) -> None:
        """Usuario del tenant A con JWT real NO puede ver pacientes del tenant B.

        Verifica el aislamiento multi-tenant end-to-end con JWT.
        """
        from tests.factories import TenantMembershipFactory

        # Arrange — user solo en tenant A
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="doctor", is_active=True)

        PatientFactory.create_batch(2, tenant=tenant_a, is_active=True)
        PatientFactory.create_batch(5, tenant=tenant_b, is_active=True)

        # Obtener JWT
        login_client = APIClient()
        login_response = login_client.post(
            "/api/v1/auth/login/",
            data={"email": user.email, "password": "password-segura-123"},
            format="json",
        )
        access_token = login_response.json()["access"]

        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Pedir lista — debe ver solo los 2 del tenant A, nunca los 5 del B
        response = api_client.get(LIST_URL)
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 2, (
            f"Aislamiento cross-tenant fallido: se obtuvieron {len(results)} pacientes "
            f"en lugar de 2 del tenant A."
        )
