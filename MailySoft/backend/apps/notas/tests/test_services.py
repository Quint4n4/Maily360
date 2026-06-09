"""
Tests de services.py de la app notas.

Cubre:
- note_create: camino feliz (personal, global all, global role), body o title
  requerido, scope role/all rechazado si no es owner, target_role obligatorio
  para scope=role, target_role inválido, target_role forzado a "" en scope!=role.
- note_update: solo el author puede editar; owner puede editar nota global;
  tercero sin permiso es rechazado; campos inmutables rechazados; cambio de
  scope role→personal limpia target_role.
- note_toggle_done: alterna done; solo el author; solo si is_task=True.
- note_delete: soft-delete; solo author/owner; tercero rechazado.

Patrón: AAA (Arrange-Act-Assert). Fixture `db` en todos.
El contexto de tenant NO es necesario en los services porque reciben el
objeto `tenant` directamente. Los selectors internos que usan TenantManager
sí necesitarían el contexto — aquí no los llamamos.
"""

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.notas.models import Note, NoteScope
from apps.notas.services import note_create, note_delete, note_toggle_done, note_update
from apps.tenancy.models import TenantMembership
from tests.factories import (
    NoteFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_owner(tenant):
    """Crea un user con rol owner en el tenant."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantMembership.Role.OWNER)
    return user


def _make_member(tenant, role=TenantMembership.Role.DOCTOR):
    """Crea un user con el rol indicado en el tenant."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role)
    return user


# ===========================================================================
# note_create — camino feliz
# ===========================================================================


class TestNoteCreateHappyPath:
    """note_create: casos que deben devolver una instancia Note válida."""

    def test_create_personal_note_with_title(self, db):
        """Un usuario cualquiera puede crear una nota personal con title."""
        # Arrange
        tenant = TenantFactory()
        user = _make_member(tenant)

        # Act
        note = note_create(tenant=tenant, user=user, title="Mi nota")

        # Assert
        assert note.pk is not None
        assert note.title == "Mi nota"
        assert note.scope == NoteScope.PERSONAL
        assert note.author == user
        assert note.tenant == tenant
        assert note.done is False
        assert note.deleted_at is None

    def test_create_personal_note_with_body_only(self, db):
        """Nota personal con solo body (sin title) es válida."""
        tenant = TenantFactory()
        user = _make_member(tenant)

        note = note_create(tenant=tenant, user=user, body="Texto del cuerpo")

        assert note.body == "Texto del cuerpo"
        assert note.title == ""

    def test_create_global_all_note_as_owner(self, db):
        """El owner puede crear una nota scope=all."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)

        note = note_create(tenant=tenant, user=owner, title="Aviso para todos", scope=NoteScope.ALL)

        assert note.scope == NoteScope.ALL
        assert note.target_role == ""

    def test_create_role_note_as_owner(self, db):
        """El owner puede crear una nota scope=role con target_role válido."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)

        note = note_create(
            tenant=tenant,
            user=owner,
            title="Nota para doctores",
            scope=NoteScope.ROLE,
            target_role="doctor",
        )

        assert note.scope == NoteScope.ROLE
        assert note.target_role == "doctor"

    def test_create_task_note(self, db):
        """Una nota puede ser marcada como tarea (is_task=True)."""
        tenant = TenantFactory()
        user = _make_member(tenant)

        note = note_create(tenant=tenant, user=user, title="Tarea pendiente", is_task=True)

        assert note.is_task is True
        assert note.done is False

    def test_create_pinned_note(self, db):
        """El campo pinned se persiste correctamente."""
        tenant = TenantFactory()
        user = _make_member(tenant)

        note = note_create(tenant=tenant, user=user, title="Fijada", pinned=True)

        assert note.pinned is True

    def test_create_note_with_remind_at(self, db):
        """remind_at se guarda correctamente."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        future = timezone.now().replace(microsecond=0) + timezone.timedelta(hours=1)
        # Necesitamos un timestamp con tzinfo
        import datetime
        remind = datetime.datetime(2030, 1, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)

        note = note_create(tenant=tenant, user=user, title="Recordar algo", remind_at=remind)

        assert note.remind_at == remind


# ===========================================================================
# note_create — validaciones (debe lanzar ValidationError)
# ===========================================================================


class TestNoteCreateValidations:
    """note_create: todos los caminos que deben lanzar ValidationError."""

    def test_empty_title_and_body_raises(self, db):
        """Si title y body están ambos vacíos → ValidationError."""
        tenant = TenantFactory()
        user = _make_member(tenant)

        with pytest.raises(ValidationError, match="título o un cuerpo"):
            note_create(tenant=tenant, user=user, title="", body="")

    def test_whitespace_only_title_and_body_raises(self, db):
        """Strings de solo espacios también se consideran vacíos."""
        tenant = TenantFactory()
        user = _make_member(tenant)

        with pytest.raises(ValidationError):
            note_create(tenant=tenant, user=user, title="   ", body="   ")

    def test_scope_all_by_non_owner_raises(self, db):
        """Un no-owner NO puede crear nota scope=all."""
        tenant = TenantFactory()
        doctor = _make_member(tenant, role="doctor")

        with pytest.raises(ValidationError, match="dueño"):
            note_create(tenant=tenant, user=doctor, title="Aviso", scope=NoteScope.ALL)

    def test_scope_role_by_non_owner_raises(self, db):
        """Un no-owner NO puede crear nota scope=role."""
        tenant = TenantFactory()
        nurse = _make_member(tenant, role="nurse")

        with pytest.raises(ValidationError, match="dueño"):
            note_create(
                tenant=tenant,
                user=nurse,
                title="Aviso enfermería",
                scope=NoteScope.ROLE,
                target_role="nurse",
            )

    def test_scope_role_without_target_role_raises(self, db):
        """scope=role sin target_role → ValidationError."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)

        with pytest.raises(ValidationError, match="target_role"):
            note_create(tenant=tenant, user=owner, title="Para un rol", scope=NoteScope.ROLE, target_role="")

    def test_scope_role_with_invalid_target_role_raises(self, db):
        """scope=role con un rol que no existe en el sistema → ValidationError."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)

        with pytest.raises(ValidationError, match="no es válido"):
            note_create(
                tenant=tenant,
                user=owner,
                title="Para un rol",
                scope=NoteScope.ROLE,
                target_role="superadmin_inventado",
            )

    def test_scope_personal_clears_target_role(self, db):
        """Si se pasa target_role con scope=personal, se ignora y se fuerza a ''."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)

        note = note_create(
            tenant=tenant,
            user=owner,
            title="Personal con target_role por error",
            scope=NoteScope.PERSONAL,
            target_role="doctor",  # debe ser ignorado
        )

        assert note.target_role == ""

    def test_scope_all_clears_target_role(self, db):
        """scope=all fuerza target_role a '' aunque se haya pasado un valor."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)

        note = note_create(
            tenant=tenant,
            user=owner,
            title="Global all",
            scope=NoteScope.ALL,
            target_role="doctor",  # debe ser ignorado
        )

        assert note.target_role == ""

    @pytest.mark.parametrize("role", ["owner", "admin", "doctor", "nurse", "reception", "finance", "readonly"])
    def test_valid_target_roles_accepted(self, db, role):
        """Todos los roles válidos son aceptados cuando scope=role."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)

        note = note_create(
            tenant=tenant,
            user=owner,
            title=f"Para rol {role}",
            scope=NoteScope.ROLE,
            target_role=role,
        )

        assert note.target_role == role


# ===========================================================================
# note_update
# ===========================================================================


class TestNoteUpdate:
    """note_update: autorización, inmutabilidad de campos, reglas de scope."""

    def test_author_can_update_title(self, db):
        """El author puede cambiar el título de su nota."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, title="Original")

        updated = note_update(note=note, user=user, tenant=tenant, title="Nuevo título")

        assert updated.title == "Nuevo título"

    def test_owner_can_update_global_note(self, db):
        """El owner puede editar una nota global creada por otro owner."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)
        # Crea otra nota global como si la hubiera creado el mismo owner
        note = NoteFactory(
            tenant=tenant,
            author=owner,
            scope=NoteScope.ALL,
            title="Nota global",
        )
        # Crea un segundo owner del mismo tenant
        owner2 = _make_owner(tenant)

        updated = note_update(note=note, user=owner2, tenant=tenant, title="Editado por owner2")

        assert updated.title == "Editado por owner2"

    def test_non_author_non_owner_cannot_update(self, db):
        """Un usuario que no es author ni owner no puede editar la nota."""
        tenant = TenantFactory()
        author = _make_member(tenant, role="doctor")
        other = _make_member(tenant, role="nurse")
        note = NoteFactory(tenant=tenant, author=author, title="Privada")

        with pytest.raises(ValidationError, match="permiso"):
            note_update(note=note, user=other, tenant=tenant, title="Intento de edición")

    def test_immutable_field_done_is_rejected(self, db):
        """'done' es inmutable en note_update — solo cambia via note_toggle_done."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, is_task=True)

        with pytest.raises(ValidationError, match="done"):
            note_update(note=note, user=user, tenant=tenant, done=True)

    def test_immutable_field_author_id_is_rejected(self, db):
        """'author_id' es inmutable."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        other = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user)

        with pytest.raises(ValidationError, match="author_id"):
            note_update(note=note, user=user, tenant=tenant, author_id=other.pk)

    def test_change_scope_role_to_personal_clears_target_role(self, db):
        """Cambiar scope de role a personal debe forzar target_role a ''."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)
        note = NoteFactory(
            tenant=tenant,
            author=owner,
            scope=NoteScope.ROLE,
            target_role="doctor",
        )

        updated = note_update(note=note, user=owner, tenant=tenant, scope=NoteScope.PERSONAL)

        assert updated.scope == NoteScope.PERSONAL
        assert updated.target_role == ""

    def test_change_scope_to_global_by_non_owner_raises(self, db):
        """Solo el owner puede cambiar el scope a 'all' o 'role'."""
        tenant = TenantFactory()
        user = _make_member(tenant, role="doctor")
        note = NoteFactory(tenant=tenant, author=user, scope=NoteScope.PERSONAL)

        with pytest.raises(ValidationError, match="dueño"):
            note_update(note=note, user=user, tenant=tenant, scope=NoteScope.ALL)

    def test_update_clears_both_title_and_body_raises(self, db):
        """Vaciar tanto title como body en update → ValidationError."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, title="Algo", body="Otro")

        with pytest.raises(ValidationError):
            note_update(note=note, user=user, tenant=tenant, title="", body="")

    def test_no_fields_returns_unchanged_note(self, db):
        """Si no se pasa ningún campo, la nota no cambia."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, title="Sin cambios")

        returned = note_update(note=note, user=user, tenant=tenant)

        assert returned.title == "Sin cambios"

    def test_unknown_fields_are_silently_ignored(self, db):
        """Campos desconocidos no lanzan error; se ignoran silenciosamente."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, title="Original")

        updated = note_update(
            note=note, user=user, tenant=tenant,
            title="Actualizado",
            campo_inexistente="valor",  # debe ignorarse
        )

        assert updated.title == "Actualizado"


# ===========================================================================
# note_toggle_done
# ===========================================================================


class TestNoteToggleDone:
    """note_toggle_done: alternancia de estado done."""

    def test_toggle_done_pending_to_done(self, db):
        """Toggle en tarea pendiente la marca como hecha."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, is_task=True, done=False)

        updated = note_toggle_done(note=note, user=user, tenant=tenant)

        assert updated.done is True

    def test_toggle_done_done_to_pending(self, db):
        """Toggle en tarea hecha la vuelve a pendiente."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, is_task=True, done=True)

        updated = note_toggle_done(note=note, user=user, tenant=tenant)

        assert updated.done is False

    def test_toggle_done_not_task_raises(self, db):
        """Toggle en nota que NO es tarea → ValidationError."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user, is_task=False)

        with pytest.raises(ValidationError, match="is_task"):
            note_toggle_done(note=note, user=user, tenant=tenant)

    def test_toggle_done_by_non_author_raises(self, db):
        """Solo el author puede hacer toggle en la tarea."""
        tenant = TenantFactory()
        author = _make_member(tenant, role="doctor")
        other = _make_member(tenant, role="nurse")
        note = NoteFactory(tenant=tenant, author=author, is_task=True)

        with pytest.raises(ValidationError, match="autor"):
            note_toggle_done(note=note, user=other, tenant=tenant)


# ===========================================================================
# note_delete
# ===========================================================================


class TestNoteDelete:
    """note_delete: soft-delete con control de acceso."""

    def test_author_can_delete_own_note(self, db):
        """El author puede borrar su propia nota."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user)

        note_delete(note=note, user=user, tenant=tenant)

        note.refresh_from_db()
        assert note.deleted_at is not None

    def test_owner_can_delete_global_note_by_another_owner(self, db):
        """El owner puede borrar una nota global de otro owner."""
        tenant = TenantFactory()
        owner = _make_owner(tenant)
        owner2 = _make_owner(tenant)
        note = NoteFactory(tenant=tenant, author=owner, scope=NoteScope.ALL)

        note_delete(note=note, user=owner2, tenant=tenant)

        note.refresh_from_db()
        assert note.deleted_at is not None

    def test_non_author_cannot_delete_personal_note(self, db):
        """Un tercero no puede borrar una nota personal ajena."""
        tenant = TenantFactory()
        author = _make_member(tenant, role="doctor")
        other = _make_member(tenant, role="nurse")
        note = NoteFactory(tenant=tenant, author=author, scope=NoteScope.PERSONAL)

        with pytest.raises(ValidationError, match="permiso"):
            note_delete(note=note, user=other, tenant=tenant)

    def test_delete_is_soft_not_hard(self, db):
        """La nota no se borra físicamente de la BD."""
        tenant = TenantFactory()
        user = _make_member(tenant)
        note = NoteFactory(tenant=tenant, author=user)
        note_id = note.id

        note_delete(note=note, user=user, tenant=tenant)

        # La nota existe en la BD (raw)
        from apps.notas.models import Note as NoteModel
        assert NoteModel.all_objects.filter(id=note_id).exists()
