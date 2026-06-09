"""
Tests de selectors.py de la app notas.

Cubre:
- note_get: retorna la nota por id; IDOR — nota de otro tenant devuelve
  DoesNotExist (no 403, no datos cruzados).
- note_list_visible: el usuario ve SUS personales + globales scope=all +
  globales scope=role cuyo target_role == su rol; NO ve personales de otros;
  NO ve role-notes de otro rol.
- note_list_visible: filtros is_task y done funcionan correctamente.
- note_list_visible: AISLAMIENTO multi-tenant — nota global de tenant A no
  aparece en el listado de un usuario de tenant B.
- note_reminders_for_user: devuelve solo las del usuario con remind_at en rango.

Patrón: AAA. Fixture `db`. El contexto de tenant se activa con set_current_tenant
para que el TenantManager filtre correctamente.
"""

import datetime
import uuid

import pytest

from apps.notas.models import Note, NoteScope
from apps.notas.selectors import note_get, note_list_visible, note_reminders_for_user
from apps.tenancy.models import TenantMembership
from tests.factories import (
    NoteFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)
from apps.notas.tests.conftest import tenant_ctx  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_DT = datetime.datetime(2030, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _make_member(tenant, role=TenantMembership.Role.DOCTOR):
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role)
    return user


def _make_owner(tenant):
    return _make_member(tenant, role=TenantMembership.Role.OWNER)


# ===========================================================================
# note_get — recuperación por id y aislamiento
# ===========================================================================


class TestNoteGet:
    """note_get: lookup seguro por id."""

    def test_note_get_returns_correct_note(self, db):
        """note_get retorna la instancia correcta cuando el id existe."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, title="Mi nota")

        with tenant_ctx(tenant):
            result = note_get(note_id=note.id)

        assert result.id == note.id
        assert result.title == "Mi nota"

    def test_note_get_raises_for_nonexistent_id(self, db):
        """note_get lanza DoesNotExist para un UUID aleatorio."""
        tenant = TenantFactory()

        with tenant_ctx(tenant):
            with pytest.raises(Note.DoesNotExist):
                note_get(note_id=uuid.uuid4())

    def test_note_get_raises_for_other_tenant_note(self, db):
        """IDOR: nota de otro tenant devuelve DoesNotExist, no sus datos."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a = _make_member(tenant_a)

        note_a = NoteFactory(tenant=tenant_a, author=user_a, title="Nota de A")

        # Activar el contexto del tenant B — no debe ver la nota de A
        with tenant_ctx(tenant_b):
            with pytest.raises(Note.DoesNotExist):
                note_get(note_id=note_a.id)

    def test_note_get_raises_for_deleted_note(self, db):
        """nota soft-deleted no es devuelta por note_get."""
        import django.utils.timezone as tz
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, deleted_at=tz.now())

        with tenant_ctx(tenant):
            with pytest.raises(Note.DoesNotExist):
                note_get(note_id=note.id)


# ===========================================================================
# note_list_visible — visibilidad correcta
# ===========================================================================


class TestNoteListVisible:
    """note_list_visible: visibilidad según scope y rol."""

    def test_user_sees_own_personal_notes(self, db):
        """El usuario ve sus propias notas personales."""
        tenant = TenantFactory()
        user = _make_member(tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=user, scope=NoteScope.PERSONAL)

        with tenant_ctx(tenant):
            qs = note_list_visible(user=user, tenant=tenant)

        assert note in qs

    def test_user_does_not_see_other_personal_notes(self, db):
        """El usuario NO ve notas personales de otros usuarios."""
        tenant = TenantFactory()
        user = _make_member(tenant, role="doctor")
        other = _make_member(tenant, role="nurse")
        other_note = NoteFactory(tenant=tenant, author=other, scope=NoteScope.PERSONAL)

        with tenant_ctx(tenant):
            qs = note_list_visible(user=user, tenant=tenant)

        assert other_note not in qs

    def test_user_sees_global_all_notes(self, db):
        """El usuario ve notas scope=all del tenant."""
        tenant = TenantFactory()
        user = _make_member(tenant, role="doctor")
        owner = _make_owner(tenant)
        global_note = NoteFactory(tenant=tenant, author=owner, scope=NoteScope.ALL)

        with tenant_ctx(tenant):
            qs = note_list_visible(user=user, tenant=tenant)

        assert global_note in qs

    def test_user_sees_role_note_matching_own_role(self, db):
        """El usuario ve notas scope=role cuyo target_role coincide con su rol."""
        tenant = TenantFactory()
        doctor = _make_member(tenant, role="doctor")
        owner = _make_owner(tenant)
        doctor_note = NoteFactory(
            tenant=tenant, author=owner, scope=NoteScope.ROLE, target_role="doctor"
        )

        with tenant_ctx(tenant):
            qs = note_list_visible(user=doctor, tenant=tenant)

        assert doctor_note in qs

    def test_user_does_not_see_role_note_of_different_role(self, db):
        """El usuario NO ve notas scope=role de un rol diferente al suyo."""
        tenant = TenantFactory()
        nurse = _make_member(tenant, role="nurse")
        owner = _make_owner(tenant)
        doctor_note = NoteFactory(
            tenant=tenant, author=owner, scope=NoteScope.ROLE, target_role="doctor"
        )

        with tenant_ctx(tenant):
            qs = note_list_visible(user=nurse, tenant=tenant)

        assert doctor_note not in qs

    def test_filter_is_task_true(self, db):
        """Filtro is_task=True devuelve solo tareas."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        task = NoteFactory(tenant=tenant, author=user, is_task=True)
        nota = NoteFactory(tenant=tenant, author=user, is_task=False)

        with tenant_ctx(tenant):
            qs = note_list_visible(user=user, tenant=tenant, is_task=True)

        assert task in qs
        assert nota not in qs

    def test_filter_is_task_false(self, db):
        """Filtro is_task=False devuelve solo notas (no tareas)."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        task = NoteFactory(tenant=tenant, author=user, is_task=True)
        nota = NoteFactory(tenant=tenant, author=user, is_task=False)

        with tenant_ctx(tenant):
            qs = note_list_visible(user=user, tenant=tenant, is_task=False)

        assert nota in qs
        assert task not in qs

    def test_filter_done_true(self, db):
        """Filtro done=True devuelve solo tareas completadas."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        done_task = NoteFactory(tenant=tenant, author=user, is_task=True, done=True)
        pending_task = NoteFactory(tenant=tenant, author=user, is_task=True, done=False)

        with tenant_ctx(tenant):
            qs = note_list_visible(user=user, tenant=tenant, done=True)

        assert done_task in qs
        assert pending_task not in qs

    def test_filter_done_false(self, db):
        """Filtro done=False devuelve solo tareas pendientes."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        done_task = NoteFactory(tenant=tenant, author=user, is_task=True, done=True)
        pending_task = NoteFactory(tenant=tenant, author=user, is_task=True, done=False)

        with tenant_ctx(tenant):
            qs = note_list_visible(user=user, tenant=tenant, done=False)

        assert pending_task in qs
        assert done_task not in qs

    def test_deleted_notes_are_excluded(self, db):
        """Las notas soft-deleted no aparecen en el listado visible."""
        import django.utils.timezone as tz
        tenant = TenantFactory()
        user = _make_member(tenant)
        deleted = NoteFactory(tenant=tenant, author=user, deleted_at=tz.now())

        with tenant_ctx(tenant):
            qs = note_list_visible(user=user, tenant=tenant)

        assert deleted not in qs


# ===========================================================================
# note_list_visible — AISLAMIENTO multi-tenant
# ===========================================================================


class TestNoteListVisibleTenantIsolation:
    """note_list_visible: NUNCA mezcla datos entre tenants."""

    def test_global_note_from_tenant_a_not_visible_in_tenant_b(self, db):
        """Una nota global de tenant A NO aparece para un usuario de tenant B."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        owner_a = _make_owner(tenant_a)
        user_b = _make_member(tenant_b, role="doctor")

        # Nota global en tenant A
        global_note_a = NoteFactory(
            tenant=tenant_a, author=owner_a, scope=NoteScope.ALL, title="Global A"
        )

        # Listar notas como usuario de tenant B
        with tenant_ctx(tenant_b):
            qs = note_list_visible(user=user_b, tenant=tenant_b)

        assert global_note_a not in qs

    def test_personal_note_from_user_in_tenant_a_not_visible_in_tenant_b(self, db):
        """Nota personal de tenant A no aparece para el mismo user en tenant B."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        # Mismo usuario tiene membresía en ambos tenants
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=tenant_a, role="doctor")
        TenantMembershipFactory(user=user, tenant=tenant_b, role="doctor")

        personal_a = NoteFactory(tenant=tenant_a, author=user, scope=NoteScope.PERSONAL)

        # En el contexto de tenant_b no debe ver la nota de tenant_a
        with tenant_ctx(tenant_b):
            qs = note_list_visible(user=user, tenant=tenant_b)

        assert personal_a not in qs

    def test_role_note_from_tenant_a_not_visible_in_tenant_b(self, db):
        """Nota scope=role de tenant A no contamina tenant B aunque el rol coincida."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner_a = _make_owner(tenant_a)
        doctor_b = _make_member(tenant_b, role="doctor")

        role_note_a = NoteFactory(
            tenant=tenant_a,
            author=owner_a,
            scope=NoteScope.ROLE,
            target_role="doctor",
        )

        with tenant_ctx(tenant_b):
            qs = note_list_visible(user=doctor_b, tenant=tenant_b)

        assert role_note_a not in qs


# ===========================================================================
# note_reminders_for_user
# ===========================================================================


class TestNoteRemindersForUser:
    """note_reminders_for_user: recordatorios en un rango de fechas."""

    def test_returns_note_with_remind_at_in_range(self, db):
        """Devuelve notas con remind_at dentro del rango [from, to)."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        remind_dt = datetime.datetime(2030, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
        note = NoteFactory(tenant=tenant, author=user, title="Recordar", remind_at=remind_dt)

        date_from = datetime.datetime(2030, 6, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        date_to = datetime.datetime(2030, 6, 1, 11, 0, 0, tzinfo=datetime.timezone.utc)

        with tenant_ctx(tenant):
            qs = note_reminders_for_user(user=user, tenant=tenant, date_from=date_from, date_to=date_to)

        assert note in qs

    def test_excludes_note_outside_range(self, db):
        """No devuelve notas cuyo remind_at queda fuera del rango."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        remind_dt = datetime.datetime(2030, 6, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        note = NoteFactory(tenant=tenant, author=user, title="Mañana", remind_at=remind_dt)

        date_from = datetime.datetime(2030, 6, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        date_to = datetime.datetime(2030, 6, 1, 11, 0, 0, tzinfo=datetime.timezone.utc)

        with tenant_ctx(tenant):
            qs = note_reminders_for_user(user=user, tenant=tenant, date_from=date_from, date_to=date_to)

        assert note not in qs

    def test_excludes_note_without_remind_at(self, db):
        """Nota sin remind_at no aparece en los recordatorios."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, remind_at=None)

        date_from = datetime.datetime(2030, 6, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        date_to = datetime.datetime(2030, 6, 1, 11, 0, 0, tzinfo=datetime.timezone.utc)

        with tenant_ctx(tenant):
            qs = note_reminders_for_user(user=user, tenant=tenant, date_from=date_from, date_to=date_to)

        assert note not in qs

    def test_excludes_reminders_of_other_users_personal_notes(self, db):
        """Recordatorio de nota personal de otro usuario NO aparece."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        other = _make_member(tenant, role="nurse")
        remind_dt = datetime.datetime(2030, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
        other_note = NoteFactory(
            tenant=tenant, author=other, scope=NoteScope.PERSONAL, remind_at=remind_dt
        )

        date_from = datetime.datetime(2030, 6, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        date_to = datetime.datetime(2030, 6, 1, 11, 0, 0, tzinfo=datetime.timezone.utc)

        with tenant_ctx(tenant):
            qs = note_reminders_for_user(user=user, tenant=tenant, date_from=date_from, date_to=date_to)

        assert other_note not in qs

    def test_results_ordered_by_remind_at_asc(self, db):
        """Los recordatorios se devuelven ordenados por remind_at ASC."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        dt1 = datetime.datetime(2030, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
        dt2 = datetime.datetime(2030, 6, 1, 10, 30, 0, tzinfo=datetime.timezone.utc)
        note_later = NoteFactory(tenant=tenant, author=user, title="Segundo", remind_at=dt2)
        note_earlier = NoteFactory(tenant=tenant, author=user, title="Primero", remind_at=dt1)

        date_from = datetime.datetime(2030, 6, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        date_to = datetime.datetime(2030, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        with tenant_ctx(tenant):
            result_ids = list(
                note_reminders_for_user(
                    user=user, tenant=tenant, date_from=date_from, date_to=date_to
                ).values_list("id", flat=True)
            )

        assert result_ids.index(note_earlier.id) < result_ids.index(note_later.id)
