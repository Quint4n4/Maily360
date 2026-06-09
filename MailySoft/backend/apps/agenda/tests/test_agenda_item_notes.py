"""
Tests para AgendaItemNote — notas colaborativas en citas y eventos de agenda.

Cubre:
SERVICES:
- agenda_item_note_create: body vacío → ValidationError; ambos ids (appointment+block)
  → ValidationError; ninguno → ValidationError; cita/evento de otro tenant →
  ValidationError; camino feliz con cita; camino feliz con evento.
- agenda_item_note_delete: author puede borrar la suya; owner y admin pueden borrar
  cualquiera; tercero sin privilegio → ValidationError; soft-delete.

MODELO:
- CheckConstraint "agenda_item_note_exactly_one_target": insertarambos o ninguno
  mediante ORM directo → IntegrityError.

SELECTORS:
- agenda_item_note_list: devuelve notas de la cita/evento, ordenadas por created_at ASC.
- agenda_item_note_get: IDOR → nota de otro tenant devuelve DoesNotExist.

APIs:
- GET  /api/v1/agenda/citas/<id>/notas/   → 200 lista; 404 cita inexistente.
- POST /api/v1/agenda/citas/<id>/notas/   → 201 crea nota; 400 body vacío; 404 cita
                                            inexistente o de otro tenant.
- GET  /api/v1/agenda/eventos/<id>/notas/ → 200 lista; 404 evento inexistente.
- POST /api/v1/agenda/eventos/<id>/notas/ → 201 crea nota; 404 evento inexistente.
- DELETE /api/v1/agenda/notas/<id>/        → 204 soft-delete; 404 nota otro tenant;
                                            400 tercero sin permiso.
- Permisos: finance → 403 en todos; readonly → 200 en GET, 201 en POST, 204 en DELETE.
- Aislamiento multi-tenant: GET citas de otro tenant → 404.

DOCUMENTACIÓN DE DISEÑO:
  readonly puede hacer POST (agregar nota al hilo) porque AgendaItemNotePermission
  incluye readonly en POST. Esto es un punto de revisión pendiente; el test lo
  documenta explícitamente para visibilizar la decisión.

Patrón: AAA. Fixture `db`. Mockeo de tenant igual que en test_apis.py.
"""

import datetime
import uuid as uuid_module
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.agenda.models import AgendaItemNote, Appointment
from apps.agenda.selectors import agenda_item_note_get, agenda_item_note_list
from apps.agenda.services import agenda_item_note_create, agenda_item_note_delete
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AgendaBlockFactory,
    AgendaItemNoteFactory,
    AppointmentFactory,
    DoctorFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Constantes de URLs
# ---------------------------------------------------------------------------

_BASE_DT = datetime.datetime(2032, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _appt_notes_url(appt_id: Any) -> str:
    return f"/api/v1/agenda/citas/{appt_id}/notas/"


def _block_notes_url(block_id: Any) -> str:
    return f"/api/v1/agenda/eventos/{block_id}/notas/"


def _note_detail_url(note_id: Any) -> str:
    return f"/api/v1/agenda/notas/{note_id}/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el TenantMiddleware completo (mock) para tests con force_authenticate."""
    with (
        patch("apps.agenda.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


@contextmanager
def _raw_tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Activa el thread-local de tenant para services/selectors directos."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


def _make_member(tenant: Any, role: str = "doctor") -> Any:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role)
    return user


def _make_auth_client(user: Any) -> Any:
    from rest_framework.test import APIClient
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_member_client(tenant: Any, role: str = "owner") -> tuple[Any, Any]:
    user = _make_member(tenant, role=role)
    return user, _make_auth_client(user)


def _make_appointment(tenant: Any) -> Appointment:
    """Crea una cita del tenant con horario no solapado."""
    doctor = DoctorFactory(tenant=tenant)
    return AppointmentFactory(
        tenant=tenant,
        doctor=doctor,
        starts_at=_BASE_DT,
        ends_at=_BASE_DT + datetime.timedelta(minutes=30),
    )


# ===========================================================================
# agenda_item_note_create — services
# ===========================================================================


class TestAgendaItemNoteCreateService:
    """agenda_item_note_create: validaciones y camino feliz."""

    def test_create_note_on_appointment_happy_path(self, db):
        """Crear nota en una cita del mismo tenant → AgendaItemNote persiste."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        appt = _make_appointment(tenant)

        with _raw_tenant_context(tenant):
            note = agenda_item_note_create(
                tenant=tenant,
                user=user,
                body="Nota sobre la cita",
                appointment_id=appt.id,
            )

        assert note.pk is not None
        assert note.appointment_id == appt.id
        assert note.agenda_block_id is None
        assert note.author == user
        assert note.body == "Nota sobre la cita"
        assert note.deleted_at is None

    def test_create_note_on_agenda_block_happy_path(self, db):
        """Crear nota en un evento de agenda del mismo tenant → persiste."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        block = AgendaBlockFactory(tenant=tenant)

        with _raw_tenant_context(tenant):
            note = agenda_item_note_create(
                tenant=tenant,
                user=user,
                body="Nota sobre el evento",
                block_id=block.id,
            )

        assert note.pk is not None
        assert note.agenda_block_id == block.id
        assert note.appointment_id is None

    def test_empty_body_raises(self, db):
        """body vacío → ValidationError."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        appt = _make_appointment(tenant)

        with _raw_tenant_context(tenant):
            with pytest.raises(ValidationError, match="vacío"):
                agenda_item_note_create(
                    tenant=tenant, user=user, body="", appointment_id=appt.id
                )

    def test_whitespace_only_body_raises(self, db):
        """body de solo espacios → ValidationError."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        appt = _make_appointment(tenant)

        with _raw_tenant_context(tenant):
            with pytest.raises(ValidationError):
                agenda_item_note_create(
                    tenant=tenant, user=user, body="   ", appointment_id=appt.id
                )

    def test_both_ids_raises(self, db):
        """appointment_id + block_id simultáneos → ValidationError."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        appt = _make_appointment(tenant)
        block = AgendaBlockFactory(tenant=tenant)

        with _raw_tenant_context(tenant):
            with pytest.raises(ValidationError, match="exactamente uno"):
                agenda_item_note_create(
                    tenant=tenant,
                    user=user,
                    body="Ambos IDs",
                    appointment_id=appt.id,
                    block_id=block.id,
                )

    def test_no_id_raises(self, db):
        """Sin appointment_id ni block_id → ValidationError."""
        tenant = TenantFactory()
        user = _make_member(tenant)

        with _raw_tenant_context(tenant):
            with pytest.raises(ValidationError, match="exactamente uno"):
                agenda_item_note_create(
                    tenant=tenant,
                    user=user,
                    body="Sin destino",
                )

    def test_appointment_from_other_tenant_raises(self, db):
        """Cita de otro tenant → ValidationError (no cross-tenant)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_b = _make_member(tenant_b)
        appt_a = _make_appointment(tenant_a)

        with _raw_tenant_context(tenant_b):
            with pytest.raises(ValidationError):
                agenda_item_note_create(
                    tenant=tenant_b,
                    user=user_b,
                    body="Nota cross-tenant",
                    appointment_id=appt_a.id,
                )

    def test_block_from_other_tenant_raises(self, db):
        """Evento de otro tenant → ValidationError."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_b = _make_member(tenant_b)
        block_a = AgendaBlockFactory(tenant=tenant_a)

        with _raw_tenant_context(tenant_b):
            with pytest.raises(ValidationError):
                agenda_item_note_create(
                    tenant=tenant_b,
                    user=user_b,
                    body="Nota cross-tenant en evento",
                    block_id=block_a.id,
                )


# ===========================================================================
# agenda_item_note_delete — services
# ===========================================================================


class TestAgendaItemNoteDeleteService:
    """agenda_item_note_delete: control de acceso y soft-delete."""

    def test_author_can_delete_own_note(self, db):
        """El author puede borrar su propia nota."""
        tenant = TenantFactory()
        user = _make_member(tenant, role="doctor")
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=appt, agenda_block=None
        )

        agenda_item_note_delete(note=note, user=user)

        note.refresh_from_db()
        assert note.deleted_at is not None

    def test_owner_can_delete_any_note(self, db):
        """El owner del tenant puede borrar cualquier nota del hilo."""
        tenant = TenantFactory()
        author = _make_member(tenant, role="doctor")
        owner = _make_member(tenant, role=TenantMembership.Role.OWNER)
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=author, created_by=author, appointment=appt, agenda_block=None
        )

        agenda_item_note_delete(note=note, user=owner)

        note.refresh_from_db()
        assert note.deleted_at is not None

    def test_admin_can_delete_any_note(self, db):
        """El admin del tenant puede borrar cualquier nota del hilo."""
        tenant = TenantFactory()
        author = _make_member(tenant, role="doctor")
        admin = _make_member(tenant, role=TenantMembership.Role.ADMIN)
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=author, created_by=author, appointment=appt, agenda_block=None
        )

        agenda_item_note_delete(note=note, user=admin)

        note.refresh_from_db()
        assert note.deleted_at is not None

    def test_third_party_without_privilege_cannot_delete(self, db):
        """Un nurse que no es el author NO puede borrar la nota."""
        tenant = TenantFactory()
        author = _make_member(tenant, role="doctor")
        nurse = _make_member(tenant, role="nurse")
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=author, created_by=author, appointment=appt, agenda_block=None
        )

        with pytest.raises(ValidationError, match="No puedes eliminar"):
            agenda_item_note_delete(note=note, user=nurse)

    def test_delete_is_soft_not_hard(self, db):
        """El borrado es soft: la nota permanece en BD con deleted_at poblado."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=appt, agenda_block=None
        )
        note_id = note.id

        agenda_item_note_delete(note=note, user=user)

        assert AgendaItemNote.all_objects.filter(id=note_id, deleted_at__isnull=False).exists()


# ===========================================================================
# CheckConstraint a nivel BD — integridad XOR
# ===========================================================================


class TestAgendaItemNoteConstraint:
    """El constraint 'agenda_item_note_exactly_one_target' en la BD."""

    def test_constraint_fires_when_both_ids_set_directly(self, db):
        """ORM directo con ambos FKs → IntegrityError (violación del CheckConstraint)."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        appt = _make_appointment(tenant)
        block = AgendaBlockFactory(tenant=tenant)

        with pytest.raises(IntegrityError):
            AgendaItemNote.objects.create(
                tenant=tenant,
                created_by=user,
                author=user,
                appointment=appt,
                agenda_block=block,
                body="Violación de constraint",
            )

    def test_constraint_fires_when_no_id_set_directly(self, db):
        """ORM directo sin ninguna FK → IntegrityError."""
        tenant = TenantFactory()
        user = _make_member(tenant)

        with pytest.raises(IntegrityError):
            AgendaItemNote.objects.create(
                tenant=tenant,
                created_by=user,
                author=user,
                appointment=None,
                agenda_block=None,
                body="Sin destino",
            )


# ===========================================================================
# agenda_item_note_list y agenda_item_note_get — selectors
# ===========================================================================


class TestAgendaItemNoteSelectors:
    """Selectors de notas de agenda."""

    def test_note_list_filters_by_appointment(self, db):
        """agenda_item_note_list devuelve solo notas de la cita indicada."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        appt1 = _make_appointment(tenant)
        appt2 = _make_appointment(tenant)
        note1 = AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=appt1, agenda_block=None
        )
        note2 = AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=appt2, agenda_block=None
        )

        with _raw_tenant_context(tenant):
            qs = agenda_item_note_list(appointment_id=appt1.id)

        assert note1 in qs
        assert note2 not in qs

    def test_note_list_filters_by_block(self, db):
        """agenda_item_note_list devuelve solo notas del evento indicado."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        block = AgendaBlockFactory(tenant=tenant)
        note_block = AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=None, agenda_block=block
        )
        appt = _make_appointment(tenant)
        note_appt = AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=appt, agenda_block=None
        )

        with _raw_tenant_context(tenant):
            qs = agenda_item_note_list(block_id=block.id)

        assert note_block in qs
        assert note_appt not in qs

    def test_note_list_excludes_soft_deleted(self, db):
        """Notas soft-deleted no aparecen en el listado."""
        import django.utils.timezone as tz
        tenant = TenantFactory()
        user = _make_member(tenant)
        appt = _make_appointment(tenant)
        deleted_note = AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user,
            appointment=appt, agenda_block=None, deleted_at=tz.now()
        )

        with _raw_tenant_context(tenant):
            qs = agenda_item_note_list(appointment_id=appt.id)

        assert deleted_note not in qs

    def test_note_get_raises_for_other_tenant_note(self, db):
        """IDOR: nota de otro tenant → DoesNotExist, no 403."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a = _make_member(tenant_a)
        appt_a = _make_appointment(tenant_a)
        note_a = AgendaItemNoteFactory(
            tenant=tenant_a, author=user_a, created_by=user_a,
            appointment=appt_a, agenda_block=None
        )

        with _raw_tenant_context(tenant_b):
            with pytest.raises(AgendaItemNote.DoesNotExist):
                agenda_item_note_get(note_id=note_a.id)


# ===========================================================================
# APIs — AppointmentNotesApi
# ===========================================================================


class TestAppointmentNotesApi:
    """GET/POST /api/v1/agenda/citas/<id>/notas/."""

    def test_get_appointment_notes_returns_200(self, db):
        """GET lista notas de la cita → 200."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        appt = _make_appointment(tenant)
        AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=appt, agenda_block=None
        )

        with _tenant_context(tenant):
            response = client.get(_appt_notes_url(appt.id))

        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_get_appointment_notes_nonexistent_appt_returns_404(self, db):
        """GET para cita inexistente → 404."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.get(_appt_notes_url(uuid_module.uuid4()))

        assert response.status_code == 404

    def test_get_appointment_notes_other_tenant_returns_404(self, db):
        """GET para cita de otro tenant → 404 (aislamiento)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        appt_a = _make_appointment(tenant_a)
        _, client_b = _make_member_client(tenant_b, role="owner")

        with _tenant_context(tenant_b):
            response = client_b.get(_appt_notes_url(appt_a.id))

        assert response.status_code == 404

    def test_post_appointment_note_returns_201(self, db):
        """POST nota en cita → 201 con nota creada."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        appt = _make_appointment(tenant)

        with _tenant_context(tenant):
            response = client.post(
                _appt_notes_url(appt.id),
                data={"body": "Observación del médico"},
                format="json",
            )

        assert response.status_code == 201
        assert response.json()["body"] == "Observación del médico"

    def test_post_empty_body_returns_400(self, db):
        """POST con body vacío → 400."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")
        appt = _make_appointment(tenant)

        with _tenant_context(tenant):
            response = client.post(
                _appt_notes_url(appt.id),
                data={"body": ""},
                format="json",
            )

        assert response.status_code == 400

    def test_post_appointment_note_requires_auth(self, db):
        """POST sin autenticación → 401."""
        from rest_framework.test import APIClient
        appt_id = uuid_module.uuid4()
        response = APIClient().post(_appt_notes_url(appt_id), data={"body": "x"}, format="json")
        assert response.status_code == 401

    def test_finance_cannot_post_appointment_note(self, db):
        """Finance → 403 en POST (AgendaItemNotePermission excluye finance)."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="finance")
        appt = _make_appointment(tenant)

        with _tenant_context(tenant):
            response = client.post(
                _appt_notes_url(appt.id),
                data={"body": "Nota de finanzas"},
                format="json",
            )

        assert response.status_code == 403

    def test_finance_cannot_get_appointment_notes(self, db):
        """Finance → 403 en GET (AgendaItemNotePermission excluye finance)."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="finance")
        appt = _make_appointment(tenant)

        with _tenant_context(tenant):
            response = client.get(_appt_notes_url(appt.id))

        assert response.status_code == 403

    def test_readonly_cannot_post_appointment_note(self, db):
        """readonly es solo lectura: puede VER el hilo pero NO agregar notas (403).

        Decisión de seguridad (hardening Fase 6): se removió READONLY de POST/DELETE
        en AgendaItemNotePermission.
        """
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="readonly")
        appt = _make_appointment(tenant)

        with _tenant_context(tenant):
            response = client.post(
                _appt_notes_url(appt.id),
                data={"body": "Nota de solo lectura"},
                format="json",
            )

        assert response.status_code == 403


# ===========================================================================
# APIs — AgendaBlockNotesApi
# ===========================================================================


class TestAgendaBlockNotesApi:
    """GET/POST /api/v1/agenda/eventos/<id>/notas/."""

    def test_get_block_notes_returns_200(self, db):
        """GET lista notas del evento → 200."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        block = AgendaBlockFactory(tenant=tenant)
        AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=None, agenda_block=block
        )

        with _tenant_context(tenant):
            response = client.get(_block_notes_url(block.id))

        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_get_block_notes_nonexistent_block_returns_404(self, db):
        """GET para evento inexistente → 404."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")

        with _tenant_context(tenant):
            response = client.get(_block_notes_url(uuid_module.uuid4()))

        assert response.status_code == 404

    def test_get_block_notes_other_tenant_returns_404(self, db):
        """GET para evento de otro tenant → 404."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        block_a = AgendaBlockFactory(tenant=tenant_a)
        _, client_b = _make_member_client(tenant_b, role="owner")

        with _tenant_context(tenant_b):
            response = client_b.get(_block_notes_url(block_a.id))

        assert response.status_code == 404

    def test_post_block_note_returns_201(self, db):
        """POST nota en evento → 201."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="doctor")
        block = AgendaBlockFactory(tenant=tenant)

        with _tenant_context(tenant):
            response = client.post(
                _block_notes_url(block.id),
                data={"body": "Comentario sobre el evento"},
                format="json",
            )

        assert response.status_code == 201
        assert response.json()["body"] == "Comentario sobre el evento"

    def test_finance_cannot_get_block_notes(self, db):
        """Finance → 403 en GET para evento."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="finance")
        block = AgendaBlockFactory(tenant=tenant)

        with _tenant_context(tenant):
            response = client.get(_block_notes_url(block.id))

        assert response.status_code == 403


# ===========================================================================
# APIs — AgendaItemNoteDetailApi (DELETE)
# ===========================================================================


class TestAgendaItemNoteDetailApi:
    """DELETE /api/v1/agenda/notas/<id>/."""

    def test_delete_own_note_returns_204(self, db):
        """DELETE nota propia → 204 y soft-deleted."""
        tenant = TenantFactory()
        user, client = _make_member_client(tenant, role="doctor")
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=user, created_by=user, appointment=appt, agenda_block=None
        )

        with _tenant_context(tenant):
            response = client.delete(_note_detail_url(note.id))

        assert response.status_code == 204
        note.refresh_from_db()
        assert note.deleted_at is not None

    def test_delete_note_of_other_tenant_returns_404(self, db):
        """DELETE nota de otro tenant → 404 (IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a = _make_member(tenant_a, role="doctor")
        appt_a = _make_appointment(tenant_a)
        note_a = AgendaItemNoteFactory(
            tenant=tenant_a, author=user_a, created_by=user_a,
            appointment=appt_a, agenda_block=None
        )
        _, client_b = _make_member_client(tenant_b, role="owner")

        with _tenant_context(tenant_b):
            response = client_b.delete(_note_detail_url(note_a.id))

        assert response.status_code == 404

    def test_delete_by_third_party_returns_400(self, db):
        """DELETE por usuario sin privilegio (no author, no owner/admin) → 400."""
        tenant = TenantFactory()
        author = _make_member(tenant, role="doctor")
        nurse = _make_member(tenant, role="nurse")
        _, client_nurse = nurse, _make_auth_client(nurse)
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=author, created_by=author,
            appointment=appt, agenda_block=None
        )

        with _tenant_context(tenant):
            response = client_nurse.delete(_note_detail_url(note.id))

        assert response.status_code == 400

    def test_delete_nonexistent_note_returns_404(self, db):
        """DELETE UUID inexistente → 404."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="owner")

        with _tenant_context(tenant):
            response = client.delete(_note_detail_url(uuid_module.uuid4()))

        assert response.status_code == 404

    def test_delete_requires_auth(self, db):
        """DELETE sin autenticación → 401."""
        from rest_framework.test import APIClient
        response = APIClient().delete(_note_detail_url(uuid_module.uuid4()))
        assert response.status_code == 401

    def test_finance_cannot_delete(self, db):
        """Finance → 403 en DELETE."""
        tenant = TenantFactory()
        _, client = _make_member_client(tenant, role="finance")

        with _tenant_context(tenant):
            response = client.delete(_note_detail_url(uuid_module.uuid4()))

        assert response.status_code == 403

    def test_owner_can_delete_any_note_via_api(self, db):
        """El owner puede borrar la nota de otro usuario a través de la API."""
        tenant = TenantFactory()
        doctor = _make_member(tenant, role="doctor")
        owner, client_owner = _make_member_client(tenant, role="owner")
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=doctor, created_by=doctor,
            appointment=appt, agenda_block=None
        )

        with _tenant_context(tenant):
            response = client_owner.delete(_note_detail_url(note.id))

        assert response.status_code == 204

    def test_admin_can_delete_any_note_via_api(self, db):
        """El admin puede borrar la nota de otro usuario a través de la API."""
        tenant = TenantFactory()
        doctor = _make_member(tenant, role="doctor")
        admin, client_admin = _make_member_client(tenant, role="admin")
        appt = _make_appointment(tenant)
        note = AgendaItemNoteFactory(
            tenant=tenant, author=doctor, created_by=doctor,
            appointment=appt, agenda_block=None
        )

        with _tenant_context(tenant):
            response = client_admin.delete(_note_detail_url(note.id))

        assert response.status_code == 204
