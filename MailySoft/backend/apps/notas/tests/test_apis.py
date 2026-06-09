"""
Tests de las APIs de la app notas (views.py).

Cubre:
- GET  /api/v1/notas/          → 200, lista notas visibles; 401 sin token.
- POST /api/v1/notas/          → 201 creación personal; 400 body+title vacíos;
                                  400 scope=all por no-owner.
- PATCH /api/v1/notas/<id>/    → 200 actualización; 404 id ajeno; 400 bad fields.
- DELETE /api/v1/notas/<id>/   → 204 soft-delete; 404 id ajeno; 400 no-author.
- POST /api/v1/notas/<id>/done/ → 200 toggle done; 400 no-task; 404 id ajeno.
- GET  /api/v1/notas/recordatorios/?date_from&date_to → 200; 400 sin params.
- Permisos: finance puede GET y POST (NotePermission = ALL_ROLES); sin membresía → 403.
- Aislamiento multi-tenant: nota de otro tenant devuelve 404 en PATCH/DELETE/toggle.

Patrón: AAA. Fixture `db`. Mockeo de tenant igual que en agenda/tests/test_apis.py.
"""

import datetime
import uuid as uuid_module
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.notas.models import Note, NoteScope
from apps.tenancy.models import TenantMembership
from tests.factories import (
    NoteFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Constantes de URLs
# ---------------------------------------------------------------------------

NOTAS_LIST_URL = "/api/v1/notas/"
NOTAS_RECORDATORIOS_URL = "/api/v1/notas/recordatorios/"


def _nota_detail_url(note_id: Any) -> str:
    return f"/api/v1/notas/{note_id}/"


def _nota_done_url(note_id: Any) -> str:
    return f"/api/v1/notas/{note_id}/done/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el TenantMiddleware completo para tests con force_authenticate."""
    with (
        patch("apps.notas.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _make_auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_member_client(tenant: Any, role: str = "owner") -> tuple[Any, APIClient]:
    """Crea un user con TenantMembership y devuelve (user, client)."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user, _make_auth_client(user)


# ===========================================================================
# Autenticación requerida (401)
# ===========================================================================


class TestNotasEndpointsRequireAuth:
    """Todos los endpoints de notas requieren autenticación."""

    def test_list_requires_auth(self, db, api_client):
        """GET /notas/ sin token → 401."""
        response = api_client.get(NOTAS_LIST_URL)
        assert response.status_code == 401

    def test_create_requires_auth(self, db, api_client):
        """POST /notas/ sin token → 401."""
        response = api_client.post(NOTAS_LIST_URL, data={}, format="json")
        assert response.status_code == 401

    def test_patch_requires_auth(self, db, api_client):
        """PATCH /notas/<id>/ sin token → 401."""
        response = api_client.patch(_nota_detail_url(uuid_module.uuid4()), data={}, format="json")
        assert response.status_code == 401

    def test_delete_requires_auth(self, db, api_client):
        """DELETE /notas/<id>/ sin token → 401."""
        response = api_client.delete(_nota_detail_url(uuid_module.uuid4()))
        assert response.status_code == 401

    def test_toggle_done_requires_auth(self, db, api_client):
        """POST /notas/<id>/done/ sin token → 401."""
        response = api_client.post(_nota_done_url(uuid_module.uuid4()))
        assert response.status_code == 401

    def test_recordatorios_requires_auth(self, db, api_client):
        """GET /notas/recordatorios/ sin token → 401."""
        response = api_client.get(NOTAS_RECORDATORIOS_URL)
        assert response.status_code == 401


# ===========================================================================
# Permisos: sin membresía activa → 403
# ===========================================================================


class TestNotasPermissions:
    """Usuario autenticado sin membresía activa recibe 403."""

    def test_user_without_membership_gets_403_on_list(self, db):
        """Usuario sin membresía activa → 403 en GET /notas/."""
        tenant = TenantFactory()
        user = UserFactory()  # sin membresía
        client = _make_auth_client(user)

        with _tenant_context(tenant):
            response = client.get(NOTAS_LIST_URL)

        assert response.status_code == 403

    def test_finance_role_can_get_list(self, db):
        """Finance puede GET /notas/ (NotePermission = ALL_ROLES para GET)."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="finance")

        with _tenant_context(tenant):
            response = client.get(NOTAS_LIST_URL)

        assert response.status_code == 200

    def test_finance_role_can_post(self, db):
        """Finance puede POST /notas/ con scope personal (NotePermission = ALL_ROLES)."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="finance")

        with _tenant_context(tenant):
            response = client.post(
                NOTAS_LIST_URL,
                data={"title": "Nota de finanzas"},
                format="json",
            )

        assert response.status_code == 201

    def test_readonly_role_can_get_list(self, db):
        """readonly puede listar notas."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="readonly")

        with _tenant_context(tenant):
            response = client.get(NOTAS_LIST_URL)

        assert response.status_code == 200


# ===========================================================================
# GET /api/v1/notas/ — lista
# ===========================================================================


class TestNoteListApi:
    """GET /notas/ — lista notas visibles con paginación."""

    def test_list_returns_200_with_results(self, db):
        """GET retorna 200 y las notas visibles para el usuario."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        NoteFactory(tenant=tenant, author=user, title="Nota propia")

        with _tenant_context(tenant):
            response = client.get(NOTAS_LIST_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1
        titles = [n["title"] for n in data["results"]]
        assert "Nota propia" in titles

    def test_list_does_not_include_other_users_personal_notes(self, db):
        """GET no incluye notas personales de otros usuarios."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        other = UserFactory()
        TenantMembershipFactory(user=other, tenant=tenant, role="nurse")
        NoteFactory(tenant=tenant, author=other, scope=NoteScope.PERSONAL, title="Privada")

        with _tenant_context(tenant):
            response = client.get(NOTAS_LIST_URL)

        data = response.json()
        titles = [n["title"] for n in data["results"]]
        assert "Privada" not in titles

    def test_list_filter_is_task_true(self, db):
        """?is_task=true devuelve solo tareas."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        NoteFactory(tenant=tenant, author=user, is_task=True, title="Tarea")
        NoteFactory(tenant=tenant, author=user, is_task=False, title="Nota")

        with _tenant_context(tenant):
            response = client.get(NOTAS_LIST_URL, {"is_task": "true"})

        data = response.json()
        titles = [n["title"] for n in data["results"]]
        assert "Tarea" in titles
        assert "Nota" not in titles

    def test_list_filter_done_false(self, db):
        """?done=false&is_task=true devuelve solo tareas pendientes."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        NoteFactory(tenant=tenant, author=user, is_task=True, done=False, title="Pendiente")
        NoteFactory(tenant=tenant, author=user, is_task=True, done=True, title="Hecha")

        # Using is_task=true to restrict the set first, then done=false.
        # DRF BooleanField accepts "true"/"false" strings from query params.
        with _tenant_context(tenant):
            response = client.get(NOTAS_LIST_URL, {"is_task": "true", "done": "false"})

        assert response.status_code == 200
        data = response.json()
        titles = [n["title"] for n in data["results"]]
        assert "Pendiente" in titles
        assert "Hecha" not in titles


# ===========================================================================
# POST /api/v1/notas/ — creación
# ===========================================================================


class TestNoteCreateApi:
    """POST /notas/ — crear nota o tarea."""

    def test_create_personal_note_returns_201(self, db):
        """POST con title devuelve 201 y la nota creada."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.post(
                NOTAS_LIST_URL,
                data={"title": "Nueva nota"},
                format="json",
            )

        assert response.status_code == 201
        assert response.json()["title"] == "Nueva nota"
        assert response.json()["scope"] == NoteScope.PERSONAL

    def test_create_with_empty_title_and_body_returns_400(self, db):
        """POST con title y body vacíos → 400."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.post(
                NOTAS_LIST_URL,
                data={"title": "", "body": ""},
                format="json",
            )

        assert response.status_code == 400

    def test_non_owner_scope_all_returns_400(self, db):
        """POST con scope=all por un no-owner → 400 (el service rechaza)."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.post(
                NOTAS_LIST_URL,
                data={"title": "Para todos", "scope": "all"},
                format="json",
            )

        assert response.status_code == 400

    def test_owner_can_create_scope_all(self, db):
        """POST con scope=all por owner → 201."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="owner")

        with _tenant_context(tenant):
            response = client.post(
                NOTAS_LIST_URL,
                data={"title": "Aviso global", "scope": "all"},
                format="json",
            )

        assert response.status_code == 201
        assert response.json()["scope"] == "all"

    def test_create_task_note(self, db):
        """POST con is_task=True crea una tarea (done=False por defecto)."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.post(
                NOTAS_LIST_URL,
                data={"title": "Tarea nueva", "is_task": True},
                format="json",
            )

        assert response.status_code == 201
        data = response.json()
        assert data["is_task"] is True
        assert data["done"] is False


# ===========================================================================
# PATCH /api/v1/notas/<id>/ — actualización parcial
# ===========================================================================


class TestNoteDetailPatchApi:
    """PATCH /notas/<id>/ — edición parcial."""

    def test_patch_returns_200_with_updated_data(self, db):
        """PATCH de campos editables → 200 con datos actualizados."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=user, title="Original")

        with _tenant_context(tenant):
            response = client.patch(
                _nota_detail_url(note.id),
                data={"title": "Modificado"},
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["title"] == "Modificado"

    def test_patch_note_of_other_tenant_returns_404(self, db):
        """PATCH de nota de otro tenant → 404 (IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a = UserFactory()
        TenantMembershipFactory(user=user_a, tenant=tenant_a, role="doctor")
        note_a = NoteFactory(tenant=tenant_a, author=user_a, title="Nota A")

        _, client_b = _make_member_client(tenant_b, role="owner")

        with _tenant_context(tenant_b):
            response = client_b.patch(
                _nota_detail_url(note_a.id),
                data={"title": "Hack"},
                format="json",
            )

        assert response.status_code == 404

    def test_patch_by_non_author_returns_400(self, db):
        """PATCH de nota por quien no es author → 400 (el service rechaza)."""
        tenant = TenantFactory()
        author = UserFactory()
        TenantMembershipFactory(user=author, tenant=tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=author, title="Personal")
        _, client_other = _make_member_client(tenant, role="nurse")

        with _tenant_context(tenant):
            response = client_other.patch(
                _nota_detail_url(note.id),
                data={"title": "Intento fallido"},
                format="json",
            )

        assert response.status_code == 400

    def test_patch_with_no_fields_returns_400(self, db):
        """PATCH sin campos → 400."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=user, title="Sin cambios")

        with _tenant_context(tenant):
            response = client.patch(_nota_detail_url(note.id), data={}, format="json")

        assert response.status_code == 400

    def test_patch_nonexistent_note_returns_404(self, db):
        """PATCH de UUID inexistente → 404."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.patch(
                _nota_detail_url(uuid_module.uuid4()),
                data={"title": "Nada"},
                format="json",
            )

        assert response.status_code == 404


# ===========================================================================
# DELETE /api/v1/notas/<id>/ — soft-delete
# ===========================================================================


class TestNoteDetailDeleteApi:
    """DELETE /notas/<id>/ — soft-delete."""

    def test_delete_own_note_returns_204(self, db):
        """DELETE de nota propia → 204 y la nota queda soft-deleted."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=user, title="A borrar")

        with _tenant_context(tenant):
            response = client.delete(_nota_detail_url(note.id))

        assert response.status_code == 204
        note.refresh_from_db()
        assert note.deleted_at is not None

    def test_delete_note_of_other_tenant_returns_404(self, db):
        """DELETE de nota de otro tenant → 404 (IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a = UserFactory()
        TenantMembershipFactory(user=user_a, tenant=tenant_a, role="doctor")
        note_a = NoteFactory(tenant=tenant_a, author=user_a)
        _, client_b = _make_member_client(tenant_b, role="owner")

        with _tenant_context(tenant_b):
            response = client_b.delete(_nota_detail_url(note_a.id))

        assert response.status_code == 404

    def test_delete_by_non_author_returns_400(self, db):
        """DELETE de nota ajena (mismo tenant) → 400."""
        tenant = TenantFactory()
        author = UserFactory()
        TenantMembershipFactory(user=author, tenant=tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=author)
        _, client_other = _make_member_client(tenant, role="nurse")

        with _tenant_context(tenant):
            response = client_other.delete(_nota_detail_url(note.id))

        assert response.status_code == 400

    def test_delete_nonexistent_note_returns_404(self, db):
        """DELETE de UUID inexistente → 404."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.delete(_nota_detail_url(uuid_module.uuid4()))

        assert response.status_code == 404


# ===========================================================================
# POST /api/v1/notas/<id>/done/ — toggle done
# ===========================================================================


class TestNoteToggleDoneApi:
    """POST /notas/<id>/done/ — alternar estado done."""

    def test_toggle_done_on_task_returns_200(self, db):
        """POST /done/ en tarea → 200 con done=True."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=user, is_task=True, done=False)

        with _tenant_context(tenant):
            response = client.post(_nota_done_url(note.id))

        assert response.status_code == 200
        assert response.json()["done"] is True

    def test_toggle_done_on_task_twice_returns_false(self, db):
        """POST /done/ dos veces vuelve done a False."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=user, is_task=True, done=False)

        with _tenant_context(tenant):
            client.post(_nota_done_url(note.id))
            response = client.post(_nota_done_url(note.id))

        assert response.status_code == 200
        assert response.json()["done"] is False

    def test_toggle_done_on_non_task_returns_400(self, db):
        """POST /done/ en nota que no es tarea → 400."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=user, is_task=False)

        with _tenant_context(tenant):
            response = client.post(_nota_done_url(note.id))

        assert response.status_code == 400

    def test_toggle_done_by_non_author_returns_400(self, db):
        """POST /done/ por usuario que no es el author → 400."""
        tenant = TenantFactory()
        author = UserFactory()
        TenantMembershipFactory(user=author, tenant=tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=author, is_task=True)
        _, client_other = _make_member_client(tenant, role="nurse")

        with _tenant_context(tenant):
            response = client_other.post(_nota_done_url(note.id))

        assert response.status_code == 400

    def test_toggle_done_on_note_of_other_tenant_returns_404(self, db):
        """POST /done/ en nota de otro tenant → 404."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a = UserFactory()
        TenantMembershipFactory(user=user_a, tenant=tenant_a, role="doctor")
        note_a = NoteFactory(tenant=tenant_a, author=user_a, is_task=True)
        _, client_b = _make_member_client(tenant_b, role="owner")

        with _tenant_context(tenant_b):
            response = client_b.post(_nota_done_url(note_a.id))

        assert response.status_code == 404

    def test_toggle_done_on_nonexistent_note_returns_404(self, db):
        """POST /done/ en UUID inexistente → 404."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.post(_nota_done_url(uuid_module.uuid4()))

        assert response.status_code == 404


# ===========================================================================
# GET /api/v1/notas/recordatorios/ — recordatorios en rango
# ===========================================================================


class TestNoteRemindersApi:
    """GET /notas/recordatorios/?date_from&date_to."""

    def test_recordatorios_returns_200_with_note_in_range(self, db):
        """GET devuelve 200 y la nota con remind_at dentro del rango."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        remind_dt = datetime.datetime(2030, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
        NoteFactory(tenant=tenant, author=user, title="Recordar", remind_at=remind_dt)

        params = {
            "date_from": "2030-06-01T09:00:00Z",
            "date_to": "2030-06-01T11:00:00Z",
        }

        with _tenant_context(tenant):
            response = client.get(NOTAS_RECORDATORIOS_URL, params)

        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1

    def test_recordatorios_without_date_from_returns_400(self, db):
        """GET sin date_from → 400 (el serializer requiere ambos params)."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.get(NOTAS_RECORDATORIOS_URL, {"date_to": "2030-06-01T11:00:00Z"})

        assert response.status_code == 400

    def test_recordatorios_without_date_to_returns_400(self, db):
        """GET sin date_to → 400."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.get(NOTAS_RECORDATORIOS_URL, {"date_from": "2030-06-01T09:00:00Z"})

        assert response.status_code == 400

    def test_recordatorios_excludes_notes_outside_range(self, db):
        """Notas con remind_at fuera del rango no aparecen."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        remind_dt = datetime.datetime(2030, 6, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        NoteFactory(tenant=tenant, author=user, title="Mañana", remind_at=remind_dt)

        params = {
            "date_from": "2030-06-01T09:00:00Z",
            "date_to": "2030-06-01T11:00:00Z",
        }

        with _tenant_context(tenant):
            response = client.get(NOTAS_RECORDATORIOS_URL, params)

        assert response.status_code == 200
        assert response.json()["count"] == 0
