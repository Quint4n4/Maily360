"""
Tests de API para las dos features nuevas de agenda:
  Feature 1: AppointmentType (tipos de cita configurables).
  Feature 2: AgendaBlock (reuniones y bloqueos).

Cubre:
- AppointmentType: GET lista (200), POST crea (201), color_hex inválido (400),
  PATCH edita (200), DELETE desactiva (204), ?only_active=false incluye inactivos,
  permisos: doctor/recepción/readonly puede GET pero NO POST/PATCH/DELETE (403),
  owner y admin sí pueden POST/PATCH/DELETE, aislamiento multi-tenant (404 cross-tenant).

- AgendaBlock: GET lista con date_from/date_to (200), POST crea (201), PATCH edita (200),
  DELETE elimina (204), 404 en id inexistente, 400 en ends_at<=starts_at, permisos,
  aislamiento multi-tenant (bloque de otro tenant retorna 404).

Patrón: AAA. Todas tocan BD → fixture db.
Mockeo de tenant igual que en test_apis.py existente.
"""

import datetime
import uuid as uuid_module
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.agenda.models import AgendaBlock, AppointmentType
from apps.agenda.services import appointment_type_create, appointment_type_deactivate
from tests.factories import (
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

TIPOS_CITA_LIST_URL = "/api/v1/agenda/tipos-cita/"
EVENTOS_LIST_URL = "/api/v1/agenda/eventos/"

_BASE_DT = datetime.datetime(2031, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
_ONE_HOUR = datetime.timedelta(hours=1)
_TWO_HOURS = datetime.timedelta(hours=2)


def _tipo_detail_url(type_id: Any) -> str:
    return f"/api/v1/agenda/tipos-cita/{type_id}/"


def _evento_detail_url(block_id: Any) -> str:
    return f"/api/v1/agenda/eventos/{block_id}/"


# ---------------------------------------------------------------------------
# Helpers (mismos patrones que test_apis.py existente)
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
    """Crea un user con TenantMembership del rol indicado y devuelve un cliente autenticado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return _make_auth_client(user)


# ===========================================================================
# AppointmentType — autenticación (401)
# ===========================================================================


class TestAppointmentTypeRequiresAuth:
    """Endpoints de tipos de cita requieren autenticación."""

    def test_list_tipos_cita_requires_auth(self, db: None, api_client: APIClient) -> None:
        """GET /tipos-cita/ sin token devuelve 401."""
        response = api_client.get(TIPOS_CITA_LIST_URL)
        assert response.status_code == 401

    def test_create_tipo_cita_requires_auth(self, db: None, api_client: APIClient) -> None:
        """POST /tipos-cita/ sin token devuelve 401."""
        response = api_client.post(TIPOS_CITA_LIST_URL, data={}, format="json")
        assert response.status_code == 401

    def test_patch_tipo_cita_requires_auth(self, db: None, api_client: APIClient) -> None:
        """PATCH /tipos-cita/<id>/ sin token devuelve 401."""
        response = api_client.patch(
            _tipo_detail_url(uuid_module.uuid4()), data={}, format="json"
        )
        assert response.status_code == 401

    def test_delete_tipo_cita_requires_auth(self, db: None, api_client: APIClient) -> None:
        """DELETE /tipos-cita/<id>/ sin token devuelve 401."""
        response = api_client.delete(_tipo_detail_url(uuid_module.uuid4()))
        assert response.status_code == 401


# ===========================================================================
# GET /agenda/tipos-cita/ — listado
# ===========================================================================


class TestAppointmentTypeListApi:
    """GET /agenda/tipos-cita/ — listado con filtros."""

    def test_list_tipos_returns_200(self, db: None) -> None:
        """Usuario autenticado con cualquier rol recibe 200."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(TIPOS_CITA_LIST_URL)

        # Assert
        assert response.status_code == 200

    def test_list_tipos_returns_only_active_by_default(self, db: None) -> None:
        """Sin ?only_active=false, la lista incluye solo tipos activos."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="readonly", is_active=True)
        client = _make_auth_client(user)
        active_type = appointment_type_create(
            tenant=tenant, user=user, name="Activo", color_hex="#111111"
        )
        inactive_type = appointment_type_create(
            tenant=tenant, user=user, name="Inactivo", color_hex="#222222"
        )
        appointment_type_deactivate(appointment_type=inactive_type, user=user)

        # Act
        with _tenant_context(tenant):
            response = client.get(TIPOS_CITA_LIST_URL)

        # Assert
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert str(active_type.id) in ids
        assert str(inactive_type.id) not in ids

    def test_list_tipos_only_active_false_includes_inactive(self, db: None) -> None:
        """?only_active=false incluye tipos inactivos en la respuesta."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="readonly", is_active=True)
        client = _make_auth_client(user)
        active_type = appointment_type_create(
            tenant=tenant, user=user, name="Activo", color_hex="#111111"
        )
        inactive_type = appointment_type_create(
            tenant=tenant, user=user, name="Inactivo", color_hex="#222222"
        )
        appointment_type_deactivate(appointment_type=inactive_type, user=user)

        # Act
        with _tenant_context(tenant):
            response = client.get(f"{TIPOS_CITA_LIST_URL}?only_active=false")

        # Assert
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert str(active_type.id) in ids
        assert str(inactive_type.id) in ids

    def test_list_tipos_tenant_isolation(self, db: None) -> None:
        """Tipos del tenant B no aparecen en la lista del tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="readonly", is_active=True)
        client = _make_auth_client(user)
        type_a = appointment_type_create(
            tenant=tenant_a, user=user, name="Tipo A", color_hex="#AAAAAA"
        )
        appointment_type_create(
            tenant=tenant_b, user=user, name="Tipo B", color_hex="#BBBBBB"
        )

        # Act — contexto del tenant A
        with _tenant_context(tenant_a):
            response = client.get(TIPOS_CITA_LIST_URL)

        # Assert — solo el tipo del tenant A
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert str(type_a.id) in ids
        assert len(ids) == 1, (
            f"Fuga cross-tenant: {len(ids)} tipos en lugar de 1 del tenant A."
        )


# ===========================================================================
# POST /agenda/tipos-cita/ — creación
# ===========================================================================


class TestAppointmentTypeCreateApi:
    """POST /agenda/tipos-cita/ — creación de tipos de cita."""

    def test_create_tipo_cita_201(self, db: None) -> None:
        """POST válido con nombre y color crea el tipo y devuelve 201."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                TIPOS_CITA_LIST_URL,
                data={"name": "Primera vez", "color_hex": "#3B82F6"},
                format="json",
            )

        # Assert
        assert response.status_code == 201, f"Esperado 201: {response.json()}"
        data = response.json()
        assert data["name"] == "Primera vez"
        assert data["color_hex"] == "#3B82F6"
        assert data["is_active"] is True
        assert "id" in data

    def test_create_tipo_cita_invalid_color_returns_400(self, db: None) -> None:
        """color_hex que no cumple #RRGGBB devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        invalid_colors = ["rojo", "#GGG", "3B82F6", "#3B82F", "#3B82F60000"]

        for bad_color in invalid_colors:
            # Act
            with _tenant_context(tenant):
                response = client.post(
                    TIPOS_CITA_LIST_URL,
                    data={"name": "Test", "color_hex": bad_color},
                    format="json",
                )
            # Assert
            assert response.status_code == 400, (
                f"Color '{bad_color}' debería devolver 400, obtuvo {response.status_code}"
            )

    def test_create_tipo_cita_without_color_creates_with_empty_color(
        self, db: None
    ) -> None:
        """POST sin color_hex crea el tipo con color en cadena vacía (201)."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="admin")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                TIPOS_CITA_LIST_URL,
                data={"name": "Sin color"},
                format="json",
            )

        # Assert
        assert response.status_code == 201
        assert response.json()["color_hex"] == ""

    def test_create_tipo_cita_missing_name_returns_400(self, db: None) -> None:
        """POST sin name devuelve 400 (campo requerido)."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                TIPOS_CITA_LIST_URL,
                data={"color_hex": "#123456"},
                format="json",
            )

        # Assert
        assert response.status_code == 400


# ===========================================================================
# AppointmentType — permisos
# ===========================================================================


class TestAppointmentTypePermissions:
    """Permisos de AppointmentTypePermission: GET=todos; POST/PATCH/DELETE=owner/admin."""

    @pytest.mark.parametrize("role", ["doctor", "nurse", "reception", "readonly", "finance"])
    def test_non_admin_can_get_list(self, db: None, role: str) -> None:
        """Roles que no son owner/admin pueden hacer GET a la lista."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role=role)

        # Act
        with _tenant_context(tenant):
            response = client.get(TIPOS_CITA_LIST_URL)

        # Assert
        assert response.status_code == 200

    @pytest.mark.parametrize("role", ["doctor", "nurse", "reception", "readonly", "finance"])
    def test_non_admin_cannot_post(self, db: None, role: str) -> None:
        """Roles sin privilegio de admin reciben 403 al intentar POST."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role=role)

        # Act
        with _tenant_context(tenant):
            response = client.post(
                TIPOS_CITA_LIST_URL,
                data={"name": "Tipo nuevo", "color_hex": "#AABBCC"},
                format="json",
            )

        # Assert
        assert response.status_code == 403

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_owner_and_admin_can_post(self, db: None, role: str) -> None:
        """owner y admin pueden crear tipos de cita (201)."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role=role)

        # Act
        with _tenant_context(tenant):
            response = client.post(
                TIPOS_CITA_LIST_URL,
                data={"name": f"Tipo {role}", "color_hex": "#001122"},
                format="json",
            )

        # Assert
        assert response.status_code == 201

    @pytest.mark.parametrize("role", ["doctor", "nurse", "reception", "readonly", "finance"])
    def test_non_admin_cannot_patch_tipo(self, db: None, role: str) -> None:
        """Roles sin privilegio de admin reciben 403 al intentar PATCH."""
        # Arrange
        tenant = TenantFactory()
        user_owner = UserFactory()
        TenantMembershipFactory(user=user_owner, tenant=tenant, role="owner", is_active=True)
        atype = appointment_type_create(
            tenant=tenant, user=user_owner, name="Tipo existente", color_hex="#AAAAAA"
        )
        client = _make_member_client(tenant, role=role)

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _tipo_detail_url(atype.id),
                data={"name": "Intento cambiar"},
                format="json",
            )

        # Assert
        assert response.status_code == 403

    @pytest.mark.parametrize("role", ["doctor", "nurse", "reception", "readonly", "finance"])
    def test_non_admin_cannot_delete_tipo(self, db: None, role: str) -> None:
        """Roles sin privilegio de admin reciben 403 al intentar DELETE."""
        # Arrange
        tenant = TenantFactory()
        user_owner = UserFactory()
        TenantMembershipFactory(user=user_owner, tenant=tenant, role="owner", is_active=True)
        atype = appointment_type_create(
            tenant=tenant, user=user_owner, name="Tipo a desactivar", color_hex="#BBBBBB"
        )
        client = _make_member_client(tenant, role=role)

        # Act
        with _tenant_context(tenant):
            response = client.delete(_tipo_detail_url(atype.id))

        # Assert
        assert response.status_code == 403

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_owner_and_admin_can_delete_tipo(self, db: None, role: str) -> None:
        """owner y admin pueden desactivar un tipo de cita (204)."""
        # Arrange
        tenant = TenantFactory()
        user_owner = UserFactory()
        TenantMembershipFactory(user=user_owner, tenant=tenant, role="owner", is_active=True)
        atype = appointment_type_create(
            tenant=tenant, user=user_owner, name=f"Tipo {role}", color_hex="#CCCCCC"
        )
        client = _make_member_client(tenant, role=role)

        # Act
        with _tenant_context(tenant):
            response = client.delete(_tipo_detail_url(atype.id))

        # Assert
        assert response.status_code == 204
        atype.refresh_from_db()
        assert atype.is_active is False


# ===========================================================================
# PATCH /agenda/tipos-cita/<id>/ — edición
# ===========================================================================


class TestAppointmentTypePatchApi:
    """PATCH /agenda/tipos-cita/<id>/ — actualización parcial."""

    def test_patch_tipo_cita_name_returns_200(self, db: None) -> None:
        """PATCH con nombre válido actualiza y devuelve 200."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="owner", is_active=True)
        client = _make_auth_client(user)
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Original", color_hex="#111111"
        )

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _tipo_detail_url(atype.id),
                data={"name": "Actualizado"},
                format="json",
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["name"] == "Actualizado"

    def test_patch_tipo_cita_invalid_color_returns_400(self, db: None) -> None:
        """PATCH con color_hex inválido devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="owner", is_active=True)
        client = _make_auth_client(user)
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Tipo test", color_hex="#111111"
        )

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _tipo_detail_url(atype.id),
                data={"color_hex": "rojo_vivo"},
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_tipo_nonexistent_returns_404(self, db: None) -> None:
        """PATCH con UUID inexistente devuelve 404."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")
        fake_id = uuid_module.uuid4()

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _tipo_detail_url(fake_id),
                data={"name": "Inexistente"},
                format="json",
            )

        # Assert
        assert response.status_code == 404

    def test_patch_tipo_of_other_tenant_returns_404(self, db: None) -> None:
        """PATCH de tipo de otro tenant devuelve 404 (aislamiento, no 403)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_b = UserFactory()
        atype_b = appointment_type_create(
            tenant=tenant_b, user=user_b, name="Tipo B", color_hex="#BBBBBB"
        )
        client = _make_member_client(tenant_a, role="owner")

        # Act — con contexto del tenant A, intentar patchear tipo del tenant B
        with _tenant_context(tenant_a):
            response = client.patch(
                _tipo_detail_url(atype_b.id),
                data={"name": "Cross-tenant hack"},
                format="json",
            )

        # Assert — 404, no 403 (no revelar existencia)
        assert response.status_code == 404


# ===========================================================================
# DELETE /agenda/tipos-cita/<id>/ — desactivación soft
# ===========================================================================


class TestAppointmentTypeDeleteApi:
    """DELETE /agenda/tipos-cita/<id>/ desactiva el tipo (soft)."""

    def test_delete_tipo_cita_204_sets_inactive(self, db: None) -> None:
        """DELETE devuelve 204 y el tipo queda is_active=False."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="owner", is_active=True)
        client = _make_auth_client(user)
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Para desactivar", color_hex="#DDDDDD"
        )

        # Act
        with _tenant_context(tenant):
            response = client.delete(_tipo_detail_url(atype.id))

        # Assert
        assert response.status_code == 204
        atype.refresh_from_db()
        assert atype.is_active is False

    def test_delete_tipo_nonexistent_returns_404(self, db: None) -> None:
        """DELETE con UUID inexistente devuelve 404."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.delete(_tipo_detail_url(uuid_module.uuid4()))

        # Assert
        assert response.status_code == 404


# ===========================================================================
# AgendaBlock API — autenticación (401)
# ===========================================================================


class TestAgendaBlockRequiresAuth:
    """Endpoints de eventos requieren autenticación."""

    def test_list_eventos_requires_auth(self, db: None, api_client: APIClient) -> None:
        """GET /eventos/ sin token devuelve 401."""
        response = api_client.get(EVENTOS_LIST_URL)
        assert response.status_code == 401

    def test_create_evento_requires_auth(self, db: None, api_client: APIClient) -> None:
        """POST /eventos/ sin token devuelve 401."""
        response = api_client.post(EVENTOS_LIST_URL, data={}, format="json")
        assert response.status_code == 401

    def test_patch_evento_requires_auth(self, db: None, api_client: APIClient) -> None:
        """PATCH /eventos/<id>/ sin token devuelve 401."""
        response = api_client.patch(
            _evento_detail_url(uuid_module.uuid4()), data={}, format="json"
        )
        assert response.status_code == 401

    def test_delete_evento_requires_auth(self, db: None, api_client: APIClient) -> None:
        """DELETE /eventos/<id>/ sin token devuelve 401."""
        response = api_client.delete(_evento_detail_url(uuid_module.uuid4()))
        assert response.status_code == 401


# ===========================================================================
# GET /agenda/eventos/ — listado con rango
# ===========================================================================


class TestAgendaBlockListApi:
    """GET /agenda/eventos/ con filtros de rango."""

    def test_list_eventos_returns_200(self, db: None) -> None:
        """Usuario autenticado recibe 200."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(EVENTOS_LIST_URL)

        # Assert
        assert response.status_code == 200

    def test_list_eventos_with_date_range_returns_overlapping_events(
        self, db: None
    ) -> None:
        """GET con date_from/date_to retorna solo eventos que solapan el rango."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="reception", is_active=True)
        client = _make_auth_client(user)

        # Crear bloque dentro del rango
        with (
            patch("apps.agenda.views.get_current_tenant", return_value=tenant),
            patch("apps.core.managers.get_current_tenant", return_value=tenant),
            patch("apps.core.managers.is_tenant_context_active", return_value=True),
        ):
            resp_create = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "title": "Dentro del rango",
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )
        assert resp_create.status_code == 201
        block_id = resp_create.json()["id"]

        # Bloque fuera del rango (mucho después)
        far_start = _BASE_DT + datetime.timedelta(days=7)
        with (
            patch("apps.agenda.views.get_current_tenant", return_value=tenant),
            patch("apps.core.managers.get_current_tenant", return_value=tenant),
            patch("apps.core.managers.is_tenant_context_active", return_value=True),
        ):
            client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "title": "Fuera del rango",
                    "starts_at": far_start.isoformat(),
                    "ends_at": (far_start + _ONE_HOUR).isoformat(),
                },
                format="json",
            )

        # Act — filtrar rango que incluye el primer bloque.
        # Se usa strftime con Z (en lugar de isoformat que produce "+00:00") para
        # evitar que el símbolo "+" sea interpretado como espacio al decodificar
        # el query string del URL.
        range_from = (_BASE_DT - datetime.timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        range_to = (_BASE_DT + _TWO_HOURS).strftime("%Y-%m-%dT%H:%M:%SZ")

        with _tenant_context(tenant):
            response = client.get(
                f"{EVENTOS_LIST_URL}?date_from={range_from}&date_to={range_to}"
            )

        # Assert
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert block_id in ids
        assert len(ids) == 1

    def test_list_eventos_tenant_isolation(self, db: None) -> None:
        """Eventos del tenant B no aparecen en la lista del tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a = UserFactory()
        user_b = UserFactory()
        TenantMembershipFactory(user=user_a, tenant=tenant_a, role="reception", is_active=True)
        TenantMembershipFactory(user=user_b, tenant=tenant_b, role="reception", is_active=True)
        client_a = _make_auth_client(user_a)
        client_b = _make_auth_client(user_b)

        # Crear un bloque en el tenant A
        with _tenant_context(tenant_a):
            resp_a = client_a.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "title": "Bloque A",
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )
        assert resp_a.status_code == 201

        # Crear un bloque en el tenant B
        with _tenant_context(tenant_b):
            resp_b = client_b.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "title": "Bloque B",
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )
        assert resp_b.status_code == 201

        # Act — listar con contexto del tenant A
        with _tenant_context(tenant_a):
            response = client_a.get(EVENTOS_LIST_URL)

        # Assert — solo el bloque del tenant A
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert resp_a.json()["id"] in ids
        assert resp_b.json()["id"] not in ids
        assert len(ids) == 1, (
            f"Fuga cross-tenant: {len(ids)} eventos en lugar de 1 del tenant A."
        )


# ===========================================================================
# POST /agenda/eventos/ — creación
# ===========================================================================


class TestAgendaBlockCreateApi:
    """POST /agenda/eventos/ — creación de eventos de agenda."""

    def test_create_block_event_returns_201(self, db: None) -> None:
        """POST válido crea un bloqueo de toda la clínica y devuelve 201."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "title": "Día festivo",
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )

        # Assert
        assert response.status_code == 201, f"Esperado 201: {response.json()}"
        data = response.json()
        assert data["kind"] == AgendaBlock.Kind.BLOCK
        assert data["title"] == "Día festivo"

    def test_create_meeting_event_returns_201(self, db: None) -> None:
        """POST con kind=meeting crea una reunión y devuelve 201."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.MEETING,
                    "title": "Junta de equipo",
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )

        # Assert
        assert response.status_code == 201
        assert response.json()["kind"] == AgendaBlock.Kind.MEETING

    def test_create_block_ends_before_starts_returns_400(self, db: None) -> None:
        """POST con ends_at < starts_at devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT - datetime.timedelta(hours=1)).isoformat(),
                },
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_create_block_with_doctor_id_returns_201(self, db: None) -> None:
        """POST con doctor_id válido crea bloqueo para ese médico."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "title": "Vacaciones",
                    "doctor_id": str(doctor.id),
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )

        # Assert
        assert response.status_code == 201
        assert response.json()["doctor"] is not None

    def test_create_block_missing_required_fields_returns_400(
        self, db: None
    ) -> None:
        """POST sin starts_at o ends_at devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act — falta ends_at
        with _tenant_context(tenant):
            response = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "starts_at": _BASE_DT.isoformat(),
                    # ends_at ausente
                },
                format="json",
            )

        # Assert
        assert response.status_code == 400


# ===========================================================================
# PATCH /agenda/eventos/<id>/ — edición
# ===========================================================================


class TestAgendaBlockPatchApi:
    """PATCH /agenda/eventos/<id>/ — edición de eventos."""

    def test_patch_block_title_returns_200(self, db: None) -> None:
        """PATCH con título válido devuelve 200 con el título actualizado."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="reception", is_active=True)
        client = _make_auth_client(user)

        # Crear el bloque primero
        with _tenant_context(tenant):
            resp = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "title": "Título original",
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )
        block_id = resp.json()["id"]

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _evento_detail_url(block_id),
                data={"title": "Título actualizado"},
                format="json",
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["title"] == "Título actualizado"

    def test_patch_block_invalid_time_range_returns_400(self, db: None) -> None:
        """PATCH con ends_at <= starts_at devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="reception", is_active=True)
        client = _make_auth_client(user)

        # Crear bloque
        with _tenant_context(tenant):
            resp = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )
        block_id = resp.json()["id"]

        # Act — intentar poner ends < starts
        with _tenant_context(tenant):
            response = client.patch(
                _evento_detail_url(block_id),
                data={
                    "starts_at": (_BASE_DT + _TWO_HOURS).isoformat(),
                    "ends_at": _BASE_DT.isoformat(),  # ends antes del nuevo starts
                },
                format="json",
            )

        # Assert
        assert response.status_code == 400

    def test_patch_block_nonexistent_returns_404(self, db: None) -> None:
        """PATCH de UUID inexistente devuelve 404."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.patch(
                _evento_detail_url(uuid_module.uuid4()),
                data={"title": "No existe"},
                format="json",
            )

        # Assert
        assert response.status_code == 404

    def test_patch_block_of_other_tenant_returns_404(self, db: None) -> None:
        """PATCH de evento de otro tenant devuelve 404 (aislamiento, no 403)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_b = UserFactory()
        TenantMembershipFactory(user=user_b, tenant=tenant_b, role="reception", is_active=True)
        client_b = _make_auth_client(user_b)

        # Crear bloque en el tenant B
        with _tenant_context(tenant_b):
            resp = client_b.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )
        block_b_id = resp.json()["id"]

        # Intentar patchear el bloque del tenant B desde el tenant A
        client_a = _make_member_client(tenant_a, role="owner")
        with _tenant_context(tenant_a):
            response = client_a.patch(
                _evento_detail_url(block_b_id),
                data={"title": "Cross-tenant hack"},
                format="json",
            )

        # Assert — 404, no 403
        assert response.status_code == 404


# ===========================================================================
# DELETE /agenda/eventos/<id>/ — eliminación soft
# ===========================================================================


class TestAgendaBlockDeleteApi:
    """DELETE /agenda/eventos/<id>/ elimina (soft) un evento."""

    def test_delete_block_returns_204(self, db: None) -> None:
        """DELETE devuelve 204 y el bloque desaparece de las queries normales."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant, role="reception", is_active=True)
        client = _make_auth_client(user)

        # Crear el bloque
        with _tenant_context(tenant):
            resp = client.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )
        block_id = resp.json()["id"]

        # Act
        with _tenant_context(tenant):
            response = client.delete(_evento_detail_url(block_id))

        # Assert
        assert response.status_code == 204

        # El bloque ya no aparece en el listado
        with _tenant_context(tenant):
            list_response = client.get(EVENTOS_LIST_URL)
        ids = [item["id"] for item in list_response.json()]
        assert block_id not in ids

    def test_delete_block_nonexistent_returns_404(self, db: None) -> None:
        """DELETE de UUID inexistente devuelve 404."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.delete(_evento_detail_url(uuid_module.uuid4()))

        # Assert
        assert response.status_code == 404

    def test_delete_block_of_other_tenant_returns_404(self, db: None) -> None:
        """DELETE de evento de otro tenant devuelve 404 (aislamiento)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_b = UserFactory()
        TenantMembershipFactory(user=user_b, tenant=tenant_b, role="reception", is_active=True)
        client_b = _make_auth_client(user_b)

        # Crear bloque en tenant B
        with _tenant_context(tenant_b):
            resp = client_b.post(
                EVENTOS_LIST_URL,
                data={
                    "kind": AgendaBlock.Kind.BLOCK,
                    "starts_at": _BASE_DT.isoformat(),
                    "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
                },
                format="json",
            )
        block_b_id = resp.json()["id"]

        # Intentar eliminar el bloque del tenant B desde el tenant A
        client_a = _make_member_client(tenant_a, role="owner")
        with _tenant_context(tenant_a):
            response = client_a.delete(_evento_detail_url(block_b_id))

        # Assert — 404, no 403
        assert response.status_code == 404
