"""Multi-sede en avisos (app notas) — cierre de hueco 2026-07-16.

Cubre:
1. note_create: el ADMIN queda forzado a SU sede; NO puede "todas las sedes"
   ni marcar importante. El OWNER elige la sede (o None=todas) y sí destaca.
2. note_list_visible: un aviso role/all se ve si su sede es None (toda la
   clínica) o está en el alcance del viewer; las notas PERSONALES no cambian.
3. La ruta HTTP real (POST/GET /notas/) respeta lo anterior.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.notas.models import NoteScope
from apps.notas.selectors import note_list_visible
from apps.notas.services import note_create
from apps.tenancy.models import TenantMembership
from tests.factories import (
    MembershipSucursalFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

NOTES_URL = "/api/v1/notas/"


@contextmanager
def _ctx(tenant: Any) -> Generator[None, None, None]:
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


def _owner(tenant: Any) -> Any:
    user = UserFactory()
    TenantMembershipFactory(
        user=user, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
    )
    return user


def _member_scoped(tenant: Any, role: str, sucursal: Any) -> Any:
    user = UserFactory()
    m = TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    MembershipSucursalFactory(tenant=tenant, membership=m, sucursal=sucursal)
    return user


def _escena(db: Any) -> Any:
    tenant = TenantFactory()
    centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
    norte = SucursalFactory(tenant=tenant, name="Norte")
    return tenant, centro, norte


# ---------------------------------------------------------------------------
# 1. note_create — autorización de sede / importante
# ---------------------------------------------------------------------------


class TestNoteCreateSucursal:
    def test_admin_aviso_queda_en_su_sede(self, db: Any) -> None:
        tenant, _, norte = _escena(db)
        admin = _member_scoped(tenant, TenantMembership.Role.ADMIN, norte)
        with _ctx(tenant):
            note = note_create(
                tenant=tenant,
                user=admin,
                title="Aviso Norte",
                scope=NoteScope.ALL,
                active_sucursal_id=norte.id,
            )
        assert note.sucursal_id == norte.id
        assert note.is_important is False

    def test_admin_no_puede_todas_las_sedes(self, db: Any) -> None:
        """Sin sede resuelta cae en su propia (default/allowed), nunca None global."""
        tenant, centro, norte = _escena(db)
        admin = _member_scoped(tenant, TenantMembership.Role.ADMIN, norte)
        with _ctx(tenant):
            note = note_create(
                tenant=tenant,
                user=admin,
                title="x",
                scope=NoteScope.ALL,
                sucursal_id=None,
                active_sucursal_id=norte.id,
            )
        assert note.sucursal_id == norte.id  # NO quedó en None (todas)

    def test_admin_no_puede_marcar_importante(self, db: Any) -> None:
        tenant, _, norte = _escena(db)
        admin = _member_scoped(tenant, TenantMembership.Role.ADMIN, norte)
        with _ctx(tenant):
            with pytest.raises(ValidationError, match="importante"):
                note_create(
                    tenant=tenant,
                    user=admin,
                    title="x",
                    scope=NoteScope.ALL,
                    active_sucursal_id=norte.id,
                    is_important=True,
                )

    def test_admin_no_puede_sede_ajena(self, db: Any) -> None:
        tenant, centro, norte = _escena(db)
        admin = _member_scoped(tenant, TenantMembership.Role.ADMIN, norte)
        with _ctx(tenant):
            with pytest.raises(ValidationError):
                note_create(
                    tenant=tenant,
                    user=admin,
                    title="x",
                    scope=NoteScope.ALL,
                    sucursal_id=centro.id,
                    active_sucursal_id=norte.id,
                )

    def test_owner_todas_las_sedes_e_importante(self, db: Any) -> None:
        tenant, _, _ = _escena(db)
        owner = _owner(tenant)
        with _ctx(tenant):
            note = note_create(
                tenant=tenant,
                user=owner,
                title="Junta general",
                scope=NoteScope.ALL,
                sucursal_id=None,
                is_important=True,
            )
        assert note.sucursal_id is None  # todas las sedes
        assert note.is_important is True

    def test_owner_puede_elegir_sede_especifica(self, db: Any) -> None:
        tenant, centro, _ = _escena(db)
        owner = _owner(tenant)
        with _ctx(tenant):
            note = note_create(
                tenant=tenant,
                user=owner,
                title="Solo Centro",
                scope=NoteScope.ALL,
                sucursal_id=centro.id,
            )
        assert note.sucursal_id == centro.id


# ---------------------------------------------------------------------------
# 2. note_list_visible — visibilidad por sede
# ---------------------------------------------------------------------------


class TestNoteVisibilidadSucursal:
    def _tres_avisos(self, tenant: Any, centro: Any, norte: Any, owner: Any) -> None:
        with _ctx(tenant):
            note_create(
                tenant=tenant,
                user=owner,
                title="de Norte",
                scope=NoteScope.ALL,
                sucursal_id=norte.id,
            )
            note_create(
                tenant=tenant,
                user=owner,
                title="de Centro",
                scope=NoteScope.ALL,
                sucursal_id=centro.id,
            )
            note_create(
                tenant=tenant, user=owner, title="de todas", scope=NoteScope.ALL, sucursal_id=None
            )

    def test_viewer_de_norte_ve_norte_y_todas_no_centro(self, db: Any) -> None:
        tenant, centro, norte = _escena(db)
        owner = _owner(tenant)
        self._tres_avisos(tenant, centro, norte, owner)
        viewer = _member_scoped(tenant, TenantMembership.Role.RECEPTION, norte)
        with _ctx(tenant):
            titulos = set(
                note_list_visible(user=viewer, tenant=tenant, sucursal_ids=[norte.id]).values_list(
                    "title", flat=True
                )
            )
        assert "de Norte" in titulos
        assert "de todas" in titulos
        assert "de Centro" not in titulos

    def test_owner_alcance_total_ve_todos(self, db: Any) -> None:
        tenant, centro, norte = _escena(db)
        owner = _owner(tenant)
        self._tres_avisos(tenant, centro, norte, owner)
        with _ctx(tenant):
            titulos = set(
                note_list_visible(user=owner, tenant=tenant, sucursal_ids=None).values_list(
                    "title", flat=True
                )
            )
        assert {"de Norte", "de Centro", "de todas"} <= titulos

    def test_notas_personales_no_se_acotan_por_sede(self, db: Any) -> None:
        tenant, _, norte = _escena(db)
        autor = _member_scoped(tenant, TenantMembership.Role.DOCTOR, norte)
        with _ctx(tenant):
            note_create(tenant=tenant, user=autor, title="mi personal", scope=NoteScope.PERSONAL)
            titulos = set(
                note_list_visible(user=autor, tenant=tenant, sucursal_ids=[norte.id]).values_list(
                    "title", flat=True
                )
            )
        assert "mi personal" in titulos


# ---------------------------------------------------------------------------
# 3. Ruta HTTP real
# ---------------------------------------------------------------------------


class TestNoteApiSucursal:
    def _auth(self, tenant: Any, user: Any, sucursal: Any) -> APIClient:
        c = APIClient()
        c.force_authenticate(user=user)
        c.credentials(HTTP_X_SUCURSAL_ID=str(sucursal.id))
        return c

    def test_admin_post_aviso_queda_en_su_sede(self, db: Any) -> None:
        tenant, _, norte = _escena(db)
        admin = _member_scoped(tenant, TenantMembership.Role.ADMIN, norte)
        from apps.notas.tests.conftest import api_tenant_ctx

        client = self._auth(tenant, admin, norte)
        with api_tenant_ctx(tenant):
            resp = client.post(NOTES_URL, {"title": "Aviso", "scope": "all"}, format="json")
        assert resp.status_code == 201, resp.content
        assert resp.json()["sucursal"]["name"] == "Norte"
        assert resp.json()["is_important"] is False

    def test_admin_post_importante_rechazado(self, db: Any) -> None:
        tenant, _, norte = _escena(db)
        admin = _member_scoped(tenant, TenantMembership.Role.ADMIN, norte)
        from apps.notas.tests.conftest import api_tenant_ctx

        client = self._auth(tenant, admin, norte)
        with api_tenant_ctx(tenant):
            resp = client.post(
                NOTES_URL, {"title": "x", "scope": "all", "is_important": True}, format="json"
            )
        assert resp.status_code == 400, resp.content
