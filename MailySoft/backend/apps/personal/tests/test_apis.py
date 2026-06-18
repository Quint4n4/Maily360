"""
Tests de las APIs de la app personal (views.py).

Cubre:
- GET  /api/v1/personal/doctores/    — autenticación requerida (401).
- TestDoctorJWTIsolation             — JWT real, solo se ven doctores del tenant propio.
- POST /api/v1/personal/consultorios/ — 201 creación, 400 validación.
- POST /api/v1/personal/doctores/    — 400 membresía inválida.
- FIX-F1: PATCH doctor con is_active → 400 (campo inmutable).
- FIX-F5: POST/PATCH consultorio con color_hex inválido → 400.

Nota sobre el contexto de tenant en tests con force_authenticate:
  Mismo patrón que pacientes: mockeamos get_current_tenant en el módulo de la vista
  y en el TenantManager para inyectar el tenant directamente cuando usamos
  force_authenticate. Para el flujo JWT REAL usamos el token obtenido vía
  POST /api/v1/auth/login/ sin ningún mock.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import uuid as uuid_module
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from tests.factories import (
    DoctorFactory,
    DoctorScheduleFactory,
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

DOCTORES_LIST_URL = "/api/v1/personal/doctores/"
CONSULTORIOS_LIST_URL = "/api/v1/personal/consultorios/"


def _doctor_detail_url(doctor_id: Any) -> str:
    return f"/api/v1/personal/doctores/{doctor_id}/"


def _consultorio_detail_url(consultorio_id: Any) -> str:
    return f"/api/v1/personal/consultorios/{consultorio_id}/"


def _schedule_detail_url(schedule_id: Any) -> str:
    return f"/api/v1/personal/horarios/{schedule_id}/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el efecto completo del TenantMiddleware para tests con force_authenticate.

    Mockea tanto (a) get_current_tenant en la vista de personal como
    (b) el TenantManager en core.managers para que las queries ORM filtren
    por el tenant inyectado.
    """
    with (
        patch(
            "apps.personal.views.get_current_tenant",
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

    Necesario desde que se activó el enforcement de permisos por rol (PersonalPermission).
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


# ===========================================================================
# GET /api/v1/personal/doctores/ — autenticación
# ===========================================================================


class TestDoctorListAuth:
    """Seguridad básica: el endpoint requiere autenticación."""

    def test_list_doctores_requires_auth(self, db: None, api_client: APIClient) -> None:
        """Sin token de autenticación debe devolver 401."""
        # Act
        response = api_client.get(DOCTORES_LIST_URL)

        # Assert
        assert response.status_code == 401

    def test_list_doctores_returns_200_for_authenticated_user(self, db: None) -> None:
        """Usuario autenticado con tenant inyectado recibe 200.

        Ajuste Paso 4: el user tiene rol 'readonly' (mínimo para GET personal).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(DOCTORES_LIST_URL)

        # Assert
        assert response.status_code == 200

    def test_list_doctores_only_shows_active_doctors(self, db: None) -> None:
        """Por defecto solo se retornan doctores activos.

        Ajuste Paso 4: el user tiene rol 'readonly' para pasar PersonalPermission en GET.
        """
        # Arrange
        tenant = TenantFactory()
        DoctorFactory.create_batch(2, tenant=tenant, is_active=True)
        DoctorFactory(tenant=tenant, is_active=False)  # no debe aparecer
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(DOCTORES_LIST_URL)

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 2


# ===========================================================================
# POST /api/v1/personal/doctores/ — validación de entrada
# ===========================================================================


class TestDoctorCreateApi:
    """POST /api/v1/personal/doctores/ — creación y validación."""

    def test_create_doctor_validation_error_400_invalid_membership(
        self, db: None
    ) -> None:
        """Enviar un membership_id que no existe en el tenant devuelve 404.

        Ajuste Paso 4: el user tiene rol 'admin' (MANAGE_ROLES = POST en PersonalPermission).
        El 404 viene de la lógica de la vista (membership no encontrada), no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="admin")
        payload = {
            "membership_id": str(uuid_module.uuid4()),  # UUID inexistente
            "specialty": "Cardiología",
        }

        # Act
        with _tenant_context(tenant):
            response = client.post(DOCTORES_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 404

    def test_create_doctor_validation_error_400_non_doctor_role(
        self, db: None
    ) -> None:
        """Membresía existente pero con role != 'doctor' devuelve 400.

        Ajuste Paso 4: el user tiene rol 'admin' para pasar PersonalPermission (POST).
        El 400 viene del servicio (validación de rol del doctor), no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="reception")
        client = _make_member_client(tenant, role="admin")
        payload = {
            "membership_id": str(membership.id),
        }

        # Act
        with _tenant_context(tenant):
            response = client.post(DOCTORES_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_doctor_requires_auth(self, db: None, api_client: APIClient) -> None:
        """Sin autenticación POST devuelve 401."""
        # Act
        response = api_client.post(DOCTORES_LIST_URL, data={}, format="json")

        # Assert
        assert response.status_code == 401

    def test_create_doctor_returns_201(self, db: None) -> None:
        """POST con membresía válida crea el doctor y devuelve 201.

        Ajuste Paso 4: el user tiene rol 'admin' (MANAGE_ROLES = POST en PersonalPermission).
        La membership de role='doctor' es la que se le asigna al nuevo perfil de médico,
        no la del actor del request.
        """
        # Arrange
        tenant = TenantFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor")
        client = _make_member_client(tenant, role="admin")
        payload = {
            "membership_id": str(membership.id),
            "specialty": "Pediatría",
            "cedula_profesional": "987654",
        }

        # Act
        with _tenant_context(tenant):
            response = client.post(DOCTORES_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["specialty"] == "Pediatría"
        assert data["is_active"] is True

    def test_create_doctor_without_tenant_returns_403(self, db: None) -> None:
        """Sin tenant resuelto (get_current_tenant=None) la vista retorna 403."""
        # Arrange
        user = UserFactory()
        client = _make_auth_client(user)

        # Act — sin mock de tenant (el middleware real pone None)
        response = client.post(
            DOCTORES_LIST_URL,
            data={"membership_id": str(uuid_module.uuid4())},
            format="json",
        )

        # Assert
        assert response.status_code == 403


# ===========================================================================
# POST /api/v1/personal/consultorios/ — creación y validación
# ===========================================================================


class TestConsultorioCreateApi:
    """POST /api/v1/personal/consultorios/ — creación de consultorio."""

    def test_create_consultorio_via_api_201(self, db: None) -> None:
        """POST válido con nombre nuevo devuelve 201 y los datos persistidos.

        Ajuste Paso 4: el user tiene rol 'admin' (MANAGE_ROLES = POST en PersonalPermission).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="admin")
        payload = {
            "name": "Consultorio Azul",
            "location": "Piso 2, Ala Norte",
            "color_hex": "#3B82F6",
        }

        # Act
        with _tenant_context(tenant):
            response = client.post(CONSULTORIOS_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Consultorio Azul"
        assert data["location"] == "Piso 2, Ala Norte"
        assert data["color_hex"] == "#3B82F6"
        assert "id" in data

    def test_create_consultorio_duplicate_name_returns_400(self, db: None) -> None:
        """Nombre duplicado en el mismo tenant devuelve 400.

        Ajuste Paso 4: el user tiene rol 'admin' para pasar PersonalPermission (POST).
        El 400 viene del servicio (nombre duplicado), no del permiso.
        """
        # Arrange
        from tests.factories import ConsultorioFactory

        tenant = TenantFactory()
        ConsultorioFactory(tenant=tenant, name="Box 1")
        client = _make_member_client(tenant, role="admin")
        payload = {"name": "Box 1"}

        # Act
        with _tenant_context(tenant):
            response = client.post(CONSULTORIOS_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_consultorio_requires_auth(
        self, db: None, api_client: APIClient
    ) -> None:
        """Sin autenticación devuelve 401."""
        # Act
        response = api_client.post(
            CONSULTORIOS_LIST_URL, data={"name": "Test"}, format="json"
        )

        # Assert
        assert response.status_code == 401

    def test_create_consultorio_missing_name_returns_400(self, db: None) -> None:
        """Omitir el campo name requerido devuelve 400.

        Ajuste Paso 4: el user tiene rol 'admin' para pasar PersonalPermission (POST).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="admin")

        # Act
        with _tenant_context(tenant):
            response = client.post(CONSULTORIOS_LIST_URL, data={}, format="json")

        # Assert
        assert response.status_code == 400

    def test_create_consultorio_without_tenant_returns_403(self, db: None) -> None:
        """Sin tenant resuelto la vista retorna 403."""
        # Arrange
        user = UserFactory()
        client = _make_auth_client(user)

        # Act
        response = client.post(
            CONSULTORIOS_LIST_URL, data={"name": "Box X"}, format="json"
        )

        # Assert
        assert response.status_code == 403


# ===========================================================================
# GET /api/v1/personal/consultorios/ — seguridad básica
# ===========================================================================


class TestConsultorioListAuth:
    """GET /api/v1/personal/consultorios/ requiere autenticación."""

    def test_list_consultorios_requires_auth(
        self, db: None, api_client: APIClient
    ) -> None:
        """Sin token devuelve 401."""
        # Act
        response = api_client.get(CONSULTORIOS_LIST_URL)

        # Assert
        assert response.status_code == 401


# ===========================================================================
# Verificación JWT real + aislamiento cross-tenant
# ===========================================================================


class TestDoctorJWTIsolation:
    """Verifica que FIX-A2 (TenantAPIView) funciona con JWT REAL para doctores.

    Sin mock de tenant: obtiene token vía POST /api/v1/auth/login/ y lo usa
    en Authorization: Bearer. Si el test pasa, el tenant se resuelve
    correctamente en el flujo JWT.
    """

    def test_jwt_auth_resolves_tenant_and_returns_own_doctors(self, db: None) -> None:
        """Con JWT real, GET /personal/doctores/ devuelve solo doctores del tenant del user.

        Flujo:
        1. Crea tenant A + user con membresía activa + 2 doctores en A.
        2. Crea tenant B con 3 doctores (otro tenant, no debe verse).
        3. Obtiene JWT real vía POST /api/v1/auth/login/.
        4. Llama GET /api/v1/personal/doctores/ con el Bearer token.
        5. Verifica: status 200, solo los 2 doctores del tenant A.
        """
        # Arrange — tenant A: user con membresía activa
        tenant_a = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="admin", is_active=True)

        # Doctores del tenant A (los que SÍ debe ver)
        DoctorFactory.create_batch(2, tenant=tenant_a, is_active=True)

        # Tenant B con doctores que NO debe ver
        tenant_b = TenantFactory()
        DoctorFactory.create_batch(3, tenant=tenant_b, is_active=True)

        # Act — obtener JWT real
        access_token = _get_jwt_token(user)

        # Usar el JWT en el header Authorization
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.get(DOCTORES_LIST_URL)

        # Assert — 200 y solo los 2 doctores del tenant A
        assert response.status_code == 200, (
            f"Esperado 200, obtenido {response.status_code}: {response.json()}"
        )
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 2, (
            f"Esperados 2 doctores del tenant A, obtenidos {len(results)}. "
            "Si obtuvo 0, FIX-A2 (TenantAPIView) no está funcionando. "
            "Si obtuvo 5, hay fuga cross-tenant."
        )

    def test_jwt_cross_tenant_doctor_isolation(self, db: None) -> None:
        """Usuario del tenant A con JWT real NO puede ver doctores del tenant B."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="admin", is_active=True)

        DoctorFactory.create_batch(2, tenant=tenant_a, is_active=True)
        DoctorFactory.create_batch(5, tenant=tenant_b, is_active=True)

        # Obtener JWT real
        access_token = _get_jwt_token(user)

        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Pedir lista — debe ver solo los 2 del tenant A, nunca los 5 del B
        response = api_client.get(DOCTORES_LIST_URL)
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 2, (
            f"Aislamiento cross-tenant fallido: se obtuvieron {len(results)} "
            f"doctores en lugar de 2 del tenant A."
        )

    def test_jwt_auth_without_membership_returns_403(
        self, db: None
    ) -> None:
        """Usuario con JWT pero SIN membresía activa recibe 403.

        CAMBIO POST-ENFORCEMENT: antes de activar los permisos por rol, este
        endpoint devolvía 200 con lista vacía. Ahora que HasClinicRole está activo,
        el usuario sin membresía tiene active_role=None → 403 Forbidden.
        Es el comportamiento correcto: los endpoints de clínica requieren rol activo.
        """
        # Arrange — user sin membresías
        user = UserFactory()
        tenant = TenantFactory()
        DoctorFactory.create_batch(3, tenant=tenant, is_active=True)

        # Act — JWT real, sin membresía
        access_token = _get_jwt_token(user)

        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.get(DOCTORES_LIST_URL)

        # Assert — 403: sin membresía activa, HasClinicRole deniega el acceso
        assert response.status_code == 403, (
            f"Sin membresía activa esperamos 403, obtuvo {response.status_code}."
        )


# ===========================================================================
# FIX-F1: PATCH doctor con is_active debe devolver 400
# ===========================================================================


class TestDoctorPatchIsActiveRejected:
    """FIX-F1: PATCH /doctores/<id>/ con is_active no puede cambiar el estado del médico.

    El campo is_active fue eliminado del InputSerializer de DoctorDetailApi.
    La vista lo ignorará (partial=True → campo ausente → no se pasa al service).
    El service lo rechaza si llega (campo inmutable en _DOCTOR_IMMUTABLE_FIELDS).
    """

    def test_patch_doctor_ignores_is_active_field(self, db: None) -> None:
        """PATCH con is_active=False es ignorado: el doctor permanece activo.

        Ajuste Paso 4: el user tiene rol 'admin' (MANAGE_ROLES = PATCH en PersonalPermission).
        El 400 viene de que is_active no está en el InputSerializer → validated_data vacío.
        """
        # Arrange
        from tests.factories import DoctorFactory

        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant, is_active=True)
        client = _make_member_client(tenant, role="admin")

        # Act — enviar is_active=False en PATCH
        with _tenant_context(tenant):
            response = client.patch(
                _doctor_detail_url(doctor.id),
                data={"is_active": False},
                format="json",
            )

        # Assert — el campo is_active fue ignorado (no está en el InputSerializer).
        # La vista devuelve 400 porque s.validated_data queda vacío (ningún campo válido).
        assert response.status_code == 400

    def test_patch_doctor_allowed_field_still_works(self, db: None) -> None:
        """PATCH con un campo permitido (specialty) actualiza correctamente.

        Ajuste Paso 4: el user tiene rol 'admin' (MANAGE_ROLES = PATCH en PersonalPermission).
        """
        # Arrange
        from tests.factories import DoctorFactory

        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant, specialty="General")
        client = _make_member_client(tenant, role="admin")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _doctor_detail_url(doctor.id),
                data={"specialty": "Neurología"},
                format="json",
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["specialty"] == "Neurología"


# ===========================================================================
# FIX-F5: POST/PATCH consultorio con color_hex inválido → 400
# ===========================================================================


class TestConsultorioColorHexValidation:
    """FIX-F5: color_hex debe tener formato #RRGGBB; valores inválidos devuelven 400."""

    def test_create_consultorio_invalid_color_hex_returns_400(self, db: None) -> None:
        """POST con color_hex inválido (no #RRGGBB) devuelve 400.

        Ajuste Paso 4: el user tiene rol 'admin' para pasar PersonalPermission (POST).
        El 400 viene del serializer (RegexField), no del permiso.
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="admin")

        invalid_colors = [
            "FF0000",     # sin #
            "#GG0000",    # hex inválido
            "#FF000",     # demasiado corto
            "#FF00000",   # demasiado largo
            "rojo",       # texto libre
            "#ff00ff00",  # RGBA no permitido
        ]

        for bad_color in invalid_colors:
            payload = {"name": f"Consultorio {bad_color}", "color_hex": bad_color}
            with _tenant_context(tenant):
                response = client.post(CONSULTORIOS_LIST_URL, data=payload, format="json")
            assert response.status_code == 400, (
                f"color_hex='{bad_color}' debió devolver 400 pero devolvió {response.status_code}"
            )

    def test_create_consultorio_valid_color_hex_accepted(self, db: None) -> None:
        """POST con color_hex válido (#RRGGBB) devuelve 201.

        Ajuste Paso 4: el user tiene rol 'admin' para pasar PersonalPermission (POST).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="admin")
        payload = {"name": "Sala Color", "color_hex": "#3B82F6"}

        # Act
        with _tenant_context(tenant):
            response = client.post(CONSULTORIOS_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        assert response.json()["color_hex"] == "#3B82F6"

    def test_create_consultorio_empty_color_hex_accepted(self, db: None) -> None:
        """POST con color_hex='' (vacío) es aceptado (campo opcional).

        Ajuste Paso 4: el user tiene rol 'admin' para pasar PersonalPermission (POST).
        """
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="admin")
        payload = {"name": "Sala Sin Color", "color_hex": ""}

        # Act
        with _tenant_context(tenant):
            response = client.post(CONSULTORIOS_LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201
        assert response.json()["color_hex"] == ""

    def test_patch_consultorio_invalid_color_hex_returns_400(self, db: None) -> None:
        """PATCH con color_hex inválido devuelve 400.

        Ajuste Paso 4: el user tiene rol 'admin' (MANAGE_ROLES = PATCH en PersonalPermission).
        El 400 viene del serializer (RegexField), no del permiso.
        """
        # Arrange
        from tests.factories import ConsultorioFactory

        tenant = TenantFactory()
        consultorio = ConsultorioFactory(tenant=tenant)
        client = _make_member_client(tenant, role="admin")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _consultorio_detail_url(consultorio.id),
                data={"color_hex": "not-a-color"},
                format="json",
            )

        # Assert
        assert response.status_code == 400


# ===========================================================================
# FIX-F2: DELETE /personal/horarios/<id>/ — aislamiento cross-tenant (IDOR)
# ===========================================================================


class TestScheduleDeleteTenantIsolation:
    """FIX-F2 verificado de extremo a extremo en el endpoint DELETE.

    El selector schedule_get ya filtra por tenant vía TenantManager (cubierto en
    test_selectors.py). Estos tests prueban el flujo HTTP COMPLETO con JWT real
    (sin mocks): TenantAPIView.initial() resuelve el tenant del token y el handler
    DELETE solo puede desactivar horarios del tenant del usuario.

    Si un usuario del tenant A pudiera borrar un horario del tenant B, sería un
    IDOR. El contrato esperado: 404 (no 403) y el horario del tenant B intacto.
    """

    def test_jwt_delete_own_schedule_returns_204(self, db: None) -> None:
        """Camino feliz: el usuario desactiva un horario de su propio tenant → 204."""
        # Arrange — usuario con membresía activa en el tenant A
        tenant_a = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="admin", is_active=True)

        doctor_a = DoctorFactory(tenant=tenant_a, is_active=True)
        schedule_a = DoctorScheduleFactory(doctor=doctor_a, is_active=True)

        access_token = _get_jwt_token(user)
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Act
        response = api_client.delete(_schedule_detail_url(schedule_a.id))

        # Assert — 204 y el horario quedó desactivado (soft) en su tenant
        assert response.status_code == 204, (
            f"Esperado 204, obtenido {response.status_code}: {response.content!r}"
        )
        schedule_a.refresh_from_db()
        assert schedule_a.is_active is False

    def test_jwt_cross_tenant_schedule_delete_returns_404(self, db: None) -> None:
        """IDOR: usuario del tenant A NO puede desactivar un horario del tenant B.

        Adivinar el UUID de un horario ajeno debe devolver 404 (el recurso "no
        existe" para este tenant) y el horario del tenant B debe seguir activo.
        """
        from apps.personal.models import DoctorSchedule

        # Arrange — usuario autenticado en el tenant A
        tenant_a = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="admin", is_active=True)

        # Horario que pertenece a OTRO tenant (B)
        tenant_b = TenantFactory()
        doctor_b = DoctorFactory(tenant=tenant_b, is_active=True)
        schedule_b = DoctorScheduleFactory(doctor=doctor_b, is_active=True)

        access_token = _get_jwt_token(user)
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Act — intentar borrar el horario del tenant B desde el contexto del A
        response = api_client.delete(_schedule_detail_url(schedule_b.id))

        # Assert — 404 (no 403; no se revela que existe en otro tenant)
        assert response.status_code == 404, (
            f"IDOR cross-tenant: esperado 404, obtenido {response.status_code}. "
            "Un usuario del tenant A pudo alcanzar un horario del tenant B."
        )

        # El horario del tenant B sigue ACTIVO: nunca fue desactivado.
        # all_objects evita cualquier filtro de tenant en la aserción.
        schedule_b_fresh = DoctorSchedule.all_objects.get(id=schedule_b.id)
        assert schedule_b_fresh.is_active is True, (
            "El horario del tenant B fue desactivado por un usuario del tenant A "
            "(fuga cross-tenant en el DELETE)."
        )


# ---------------------------------------------------------------------------
# Pendiente frontend: DoctorOutputSerializer expone sello, foto, cedulas_adicionales
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_doctor_output_serializer_includes_profile_fields() -> None:
    """DoctorOutputSerializer incluye sello, foto y cedulas_adicionales (pendiente frontend).

    Verifica que los tres campos añadidos para el frontend estén presentes en el output,
    incluso cuando son None/vacío (el frontend necesita conocer su existencia).
    """
    from apps.personal.serializers import DoctorOutputSerializer

    doctor = DoctorFactory()
    # Agregar prefetch para evitar N+1 en serializer
    from apps.personal.models import Doctor

    doctor_refreshed = (
        Doctor.objects.prefetch_related("consultorios").select_related("membership__user").get(pk=doctor.pk)
    )

    data = DoctorOutputSerializer(doctor_refreshed).data

    assert "sello" in data, "DoctorOutputSerializer no incluye el campo 'sello'"
    assert "foto" in data, "DoctorOutputSerializer no incluye el campo 'foto'"
    assert "cedulas_adicionales" in data, (
        "DoctorOutputSerializer no incluye el campo 'cedulas_adicionales'"
    )


@pytest.mark.django_db
def test_doctor_output_serializer_cedulas_content() -> None:
    """cedulas_adicionales en output refleja el valor guardado."""
    from apps.personal.serializers import DoctorOutputSerializer
    from apps.personal.models import Doctor

    doctor = DoctorFactory()
    doctor.cedulas_adicionales = "11111111,22222222"
    doctor.save(update_fields=["cedulas_adicionales", "updated_at"])

    doctor_refreshed = (
        Doctor.objects.prefetch_related("consultorios").select_related("membership__user").get(pk=doctor.pk)
    )
    data = DoctorOutputSerializer(doctor_refreshed).data

    assert data["cedulas_adicionales"] == "11111111,22222222"
