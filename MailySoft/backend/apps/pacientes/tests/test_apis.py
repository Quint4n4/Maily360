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

import datetime
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
    TenantMembershipFactory,
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


def _make_member_client(tenant: Any, role: str = "owner") -> APIClient:
    """Crea un user con TenantMembership del rol indicado y devuelve un cliente autenticado.

    Necesario desde que se activó el enforcement de permisos por rol (PatientPermission).
    Sin membership activa en el tenant, TenantAPIView adjunta active_role=None y
    HasClinicRole deniega la solicitud con 403.

    Args:
        tenant: el Tenant al que pertenece la membresía.
        role:   rol clínico requerido para la operación que se va a testear.

    Returns:
        APIClient autenticado como el user creado.
    """
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return _make_auth_client(user)


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
        """Usuario autenticado con tenant inyectado recibe 200.

        Ajuste Paso 4: el user ahora tiene rol 'readonly' (mínimo para GET pacientes).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200

    def test_list_patients_returns_paginated_response(self, db: None) -> None:
        """La respuesta incluye la estructura de paginación DRF o lista directa.

        Ajuste Paso 4: el user tiene rol 'readonly' para pasar PatientPermission en GET.
        """
        # Arrange
        tenant = TenantFactory()
        PatientFactory.create_batch(3, tenant=tenant, is_active=True)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_list_patients_search_param_filters_results(self, db: None) -> None:
        """El parámetro ?search= filtra por nombre dentro del tenant del usuario.

        Ajuste Paso 4: el user tiene rol 'readonly' para pasar PatientPermission en GET.
        """
        # Arrange
        tenant = TenantFactory()
        PatientFactory(tenant=tenant, first_name="Valentina", is_active=True)
        PatientFactory(tenant=tenant, first_name="Roberto", is_active=True)
        client = _make_member_client(tenant, role="readonly")

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
        """El listado solo muestra pacientes del tenant activo.

        Ajuste Paso 4: el user tiene membresía en tenant_a (rol readonly) para
        pasar PatientPermission en GET. El aislamiento sigue siendo verificado
        por el TenantManager + contexto mockeado.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        PatientFactory.create_batch(2, tenant=tenant_a, is_active=True)
        PatientFactory.create_batch(3, tenant=tenant_b, is_active=True)
        client = _make_member_client(tenant_a, role="readonly")

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
        """POST válido con tenant activo devuelve 201 y record_number generado.

        Ajuste Paso 4: el user tiene rol 'reception' (incluido en POST de PatientPermission).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

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
        """El paciente creado vía API debe existir en BD.

        Ajuste Paso 4: el user tiene rol 'reception' para pasar PatientPermission en POST.
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

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
        """Faltar un campo requerido (first_name) debe devolver 400.

        Ajuste Paso 4: el user tiene rol 'reception' para pasar PatientPermission.
        El 400 viene del InputSerializer, no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        incomplete_payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "first_name"}

        # Act
        with _tenant_context(tenant):
            response = client.post(LIST_URL, data=incomplete_payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_patient_validation_error_returns_400_invalid_sex(self, db: None) -> None:
        """Sexo inválido debe devolver 400 (rechazado por InputSerializer).

        Ajuste Paso 4: el user tiene rol 'reception' para pasar PatientPermission.
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")
        payload = {**_VALID_PAYLOAD, "sex": "Z"}

        # Act
        with _tenant_context(tenant):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_patient_duplicate_curp_returns_400(self, db: None) -> None:
        """CURP duplicada en el mismo tenant devuelve 400 con mensaje.

        Ajuste Paso 4: el user tiene rol 'reception' para pasar PatientPermission en POST.
        """
        # Arrange
        tenant = TenantFactory()
        curp = "MARL920704MDFNRS04"
        PatientFactory(tenant=tenant, curp=curp, is_active=True)
        client = _make_member_client(tenant, role="reception")
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
        """GET con UUID válido del propio tenant devuelve 200.

        Ajuste Paso 4: el user tiene rol 'readonly' (mínimo para GET pacientes).
        """
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(_detail_url(patient.id))

        # Assert
        assert response.status_code == 200
        assert response.json()["id"] == str(patient.id)

    def test_get_patient_detail_returns_404_for_unknown_uuid(self, db: None) -> None:
        """UUID inexistente devuelve 404.

        Ajuste Paso 4: el user tiene rol 'readonly' para pasar PatientPermission en GET.
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(_detail_url(uuid_module.uuid4()))

        # Assert
        assert response.status_code == 404

    def test_get_patient_detail_returns_404_for_other_tenant_patient(self, db: None) -> None:
        """Paciente de otro tenant retorna 404 (no 403; sin revelar existencia).

        Ajuste Paso 4: el user tiene membresía en tenant_a (rol readonly) para
        pasar PatientPermission en GET. El 404 viene del selector (ORM filtra por tenant).
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        client = _make_member_client(tenant_a, role="readonly")

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
        """PATCH válido devuelve 200 con los datos actualizados.

        Ajuste Paso 4: el user tiene rol 'reception' (incluido en PATCH de PatientPermission).
        """
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, phone="5500000001")
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id), data={"phone": "5599999999"}, format="json"
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["phone"] == "5599999999"

    def test_patch_patient_record_number_returns_400(self, db: None) -> None:
        """Intentar cambiar record_number via PATCH devuelve 400.

        Ajuste Paso 4: el user tiene rol 'reception' para pasar PatientPermission (PATCH).
        El 400 viene del servicio (campo inmutable), no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

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
        """PATCH sin campos válidos devuelve 400.

        Ajuste Paso 4: el user tiene rol 'reception' para pasar PatientPermission (PATCH).
        """
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.patch(_detail_url(patient.id), data={}, format="json")

        # Assert
        assert response.status_code == 400

    def test_patch_patient_returns_404_for_other_tenant(self, db: None) -> None:
        """PATCH a paciente de otro tenant devuelve 404.

        Ajuste Paso 4: el user tiene membresía en tenant_a (rol reception) para
        pasar PatientPermission (PATCH). El 404 viene del selector.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        client = _make_member_client(tenant_a, role="reception")

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
        """DELETE válido devuelve 204 No Content.

        Ajuste Paso 4: el user tiene rol 'owner' (único junto a 'admin' con DELETE
        en PatientPermission según la matriz de roles).
        """
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.delete(_detail_url(patient.id))

        # Assert
        assert response.status_code == 204

    def test_delete_patient_sets_inactive_in_db(self, db: None) -> None:
        """Tras DELETE el registro en BD tiene is_active=False (no fue borrado).

        Ajuste Paso 4: el user tiene rol 'owner' para pasar PatientPermission (DELETE).
        """
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        patient_id = patient.id
        client = _make_member_client(tenant, role="owner")

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
        """DELETE a paciente de otro tenant devuelve 404.

        Ajuste Paso 4: el user tiene membresía en tenant_a (rol owner) para
        pasar PatientPermission (DELETE). El 404 viene del selector.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        client = _make_member_client(tenant_a, role="owner")

        # Act
        with _tenant_context(tenant_a):
            response = client.delete(_detail_url(patient_b.id))

        # Assert
        assert response.status_code == 404


# ===========================================================================
# Verificación de FIX-A2: JWT real + aislamiento de tenant
# ===========================================================================


# ===========================================================================
# ALTO-2 — Validación estricta del PATCH de Patient (D-EC-7)
# ===========================================================================


class TestPatientPatchStrictValidation:
    """ALTO-2: verifica la validación estricta agregada al InputSerializer del PATCH.

    Cubre:
    - Campo desconocido → 400.
    - is_deceased=True sin deceased_at → 400.
    - is_deceased=False limpia deceased_at.
    - MEDIO-2: phone_secondary inválido → 400; vacío → permitido.
    """

    def test_campo_desconocido_da_400(self, db: None) -> None:
        """PATCH con campo no declarado en el InputSerializer → 400 (D-EC-7)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id),
                data={"first_name": "Maria", "campo_trampa": "inyeccion"},
                format="json",
            )

        assert response.status_code == 400
        # El error debe señalar el campo desconocido.
        detail = response.json()
        assert "campo_trampa" in str(detail)

    def test_is_deceased_true_sin_deceased_at_da_400(self, db: None) -> None:
        """PATCH con is_deceased=True y sin deceased_at → 400."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id),
                data={"is_deceased": True},
                format="json",
            )

        assert response.status_code == 400
        detail_str = str(response.json())
        assert "deceased_at" in detail_str

    def test_is_deceased_true_con_deceased_at_da_200(self, db: None) -> None:
        """PATCH con is_deceased=True y deceased_at provisto → 200."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id),
                data={"is_deceased": True, "deceased_at": "2024-01-15"},
                format="json",
            )

        assert response.status_code == 200

    def test_is_deceased_false_limpia_deceased_at(self, db: None) -> None:
        """PATCH con is_deceased=False limpia deceased_at aunque se envíe una fecha."""
        tenant = TenantFactory()
        # Paciente previamente marcado como fallecido.
        patient = PatientFactory(
            tenant=tenant, is_deceased=True, deceased_at=datetime.date(2024, 1, 15)
        )
        client = _make_member_client(tenant, role="reception")

        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id),
                data={"is_deceased": False, "deceased_at": "2024-01-15"},
                format="json",
            )

        assert response.status_code == 200
        patient.refresh_from_db()
        assert patient.is_deceased is False
        assert patient.deceased_at is None

    # MEDIO-2 — phone_secondary

    def test_phone_secondary_invalido_da_400(self, db: None) -> None:
        """MEDIO-2: phone_secondary con formato inválido → 400."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id),
                data={"phone_secondary": "NO-ES-UN-TELEFONO!!!@@##"},
                format="json",
            )

        assert response.status_code == 400

    def test_phone_secondary_vacio_permitido(self, db: None) -> None:
        """MEDIO-2: phone_secondary vacío → 200 (campo opcional)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id),
                data={"phone_secondary": ""},
                format="json",
            )

        assert response.status_code == 200

    def test_phone_secondary_valido_da_200(self, db: None) -> None:
        """MEDIO-2: phone_secondary con formato válido → 200."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="reception")

        with _tenant_context(tenant):
            response = client.patch(
                _detail_url(patient.id),
                data={"phone_secondary": "+52 55 1234 5678"},
                format="json",
            )

        assert response.status_code == 200


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

    def test_jwt_auth_without_membership_returns_403(self, db: None) -> None:
        """Usuario con JWT pero SIN membresía activa en ningún tenant recibe 403.

        CAMBIO POST-ENFORCEMENT: antes de activar los permisos por rol, este
        endpoint devolvía 200 con lista vacía (falla segura: tenant=None → ORM
        devuelve qs.none()). Ahora que HasClinicRole está activo, el usuario sin
        membresía tiene active_role=None → 403 Forbidden. Este es el comportamiento
        correcto: el endpoint de clínica requiere un rol activo para acceder.
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

        # Assert — 403: sin membresía activa, HasClinicRole deniega el acceso
        assert response.status_code == 403, (
            f"Sin membresía activa esperamos 403, obtuvo {response.status_code}. "
            "HasClinicRole debe denegar si active_role=None."
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


# ---------------------------------------------------------------------------
# M1 — notes de paciente sin límite (max_length=5000)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patient_create_notes_over_limit_returns_400() -> None:
    """POST con notes > 5000 caracteres → 400 (M1)."""
    tenant = TenantFactory()
    client = _make_member_client(tenant, role="owner")
    payload = {**_VALID_PAYLOAD, "notes": "x" * 5001}

    with _tenant_context(tenant):
        response = client.post(LIST_URL, payload, format="json")

    assert response.status_code == 400
    assert "notes" in response.data or "notes" in str(response.data)


@pytest.mark.django_db
def test_patient_create_notes_at_limit_succeeds() -> None:
    """POST con notes exactamente en 5000 caracteres → 201 (M1 límite exacto OK)."""
    tenant = TenantFactory()
    client = _make_member_client(tenant, role="owner")
    payload = {**_VALID_PAYLOAD, "notes": "a" * 5000}

    with _tenant_context(tenant):
        response = client.post(LIST_URL, payload, format="json")

    assert response.status_code == 201


@pytest.mark.django_db
def test_patient_patch_notes_over_limit_returns_400(db: Any) -> None:
    """PATCH con notes > 5000 caracteres → 400 (M1 en PatientDetailApi.InputSerializer)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant, is_active=True)
    client = _make_member_client(tenant, role="owner")

    with _tenant_context(tenant):
        response = client.patch(
            _detail_url(patient.id),
            {"notes": "z" * 5001},
            format="json",
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# B7 — postal_code sin formato (debe ser exactamente 5 dígitos)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patient_patch_postal_code_valid_succeeds(db: Any) -> None:
    """PATCH con postal_code de 5 dígitos → 200 (B7)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant, is_active=True)
    client = _make_member_client(tenant, role="owner")

    with _tenant_context(tenant):
        response = client.patch(
            _detail_url(patient.id),
            {"postal_code": "39355"},
            format="json",
        )

    assert response.status_code == 200


@pytest.mark.django_db
def test_patient_patch_postal_code_alpha_returns_400(db: Any) -> None:
    """PATCH con postal_code alfabético → 400 (B7)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant, is_active=True)
    client = _make_member_client(tenant, role="owner")

    with _tenant_context(tenant):
        response = client.patch(
            _detail_url(patient.id),
            {"postal_code": "abc"},
            format="json",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_patient_patch_postal_code_4digits_returns_400(db: Any) -> None:
    """PATCH con postal_code de 4 dígitos (< 5) → 400 (B7)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant, is_active=True)
    client = _make_member_client(tenant, role="owner")

    with _tenant_context(tenant):
        response = client.patch(
            _detail_url(patient.id),
            {"postal_code": "1234"},
            format="json",
        )

    assert response.status_code == 400


@pytest.mark.django_db
def test_patient_patch_postal_code_empty_succeeds(db: Any) -> None:
    """PATCH con postal_code vacío → 200 (B7: campo opcional, vacío permitido)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant, is_active=True)
    client = _make_member_client(tenant, role="owner")

    with _tenant_context(tenant):
        response = client.patch(
            _detail_url(patient.id),
            {"postal_code": ""},
            format="json",
        )

    assert response.status_code == 200
