"""
Tests de los DISPARADORES de notificaciones (Fase 2).

Verifican que crear ciertos objetos de dominio genera las notificaciones correctas
para los destinatarios correctos (y nunca para el propio autor):

- notas.note_create:
    scope=role → notifica a los usuarios del rol destino (role_note).
    scope=all  → notifica a toda la clínica (broadcast).
- agenda.agenda_item_note_create (nota de equipo):
    en una cita → médico de la cita + recepción + quienes ya comentaron (team_note).
- agenda.agenda_block_create (reunión):
    reunión de clínica → staff clínico (owner/admin/doctor/nurse/reception).
    reunión de un médico → solo ese médico.
    un BLOQUEO (no reunión) → no notifica.

Patrón: AAA. Fixture `db`. Contexto de tenant activo (los services usan TenantManager).
Las aserciones leen Notification.all_objects para no depender del contexto.
"""

import datetime
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from apps.agenda.models import AgendaBlock
from apps.agenda.services import agenda_block_create, agenda_item_note_create
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.notas.models import NoteScope
from apps.notas.services import note_create
from apps.notificaciones.models import Notification, NotificationKind, NotificationTarget
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AgendaBlockFactory,
    AppointmentFactory,
    ConsultorioFactory,
    DoctorFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

_BASE_DT = datetime.datetime(2033, 1, 1, 10, 0, 0, tzinfo=datetime.UTC)
Role = TenantMembership.Role


@contextmanager
def _ctx(tenant: Any) -> Generator[None, None, None]:
    """Activa el thread-local de tenant para services/selectors directos."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


def _member(tenant: Any, role: str) -> Any:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _recipients_of(tenant: Any, kind: str) -> set[Any]:
    """Conjunto de recipient_id de las notificaciones de ese tipo en el tenant."""
    return set(
        Notification.all_objects.filter(tenant=tenant, kind=kind).values_list(
            "recipient_id", flat=True
        )
    )


# ===========================================================================
# notas.note_create → role_note / broadcast
# ===========================================================================


class TestNoteCreateNotifies:
    def test_role_note_notifies_target_role(self, db):
        """scope=role notifica a los usuarios del rol destino (y no a otros)."""
        tenant = TenantFactory()
        owner = _member(tenant, Role.OWNER)
        rec1 = _member(tenant, Role.RECEPTION)
        rec2 = _member(tenant, Role.RECEPTION)
        nurse = _member(tenant, Role.NURSE)

        with _ctx(tenant):
            note = note_create(
                tenant=tenant,
                user=owner,
                title="Avisar a recepción",
                scope=NoteScope.ROLE,
                target_role=Role.RECEPTION,
            )

        recipients = _recipients_of(tenant, NotificationKind.ROLE_NOTE)
        assert recipients == {rec1.pk, rec2.pk}
        assert nurse.pk not in recipients
        # apunta a la nota
        notif = Notification.all_objects.filter(
            tenant=tenant, kind=NotificationKind.ROLE_NOTE
        ).first()
        assert notif.target_type == NotificationTarget.NOTE
        assert notif.target_id == note.id

    def test_broadcast_notifies_everyone_except_author(self, db):
        """scope=all notifica a toda la clínica menos al autor."""
        tenant = TenantFactory()
        owner = _member(tenant, Role.OWNER)
        doctor = _member(tenant, Role.DOCTOR)
        finance = _member(tenant, Role.FINANCE)

        with _ctx(tenant):
            note_create(
                tenant=tenant,
                user=owner,
                title="Aviso general",
                scope=NoteScope.ALL,
            )

        recipients = _recipients_of(tenant, NotificationKind.BROADCAST)
        assert doctor.pk in recipients
        assert finance.pk in recipients
        assert owner.pk not in recipients

    def test_role_note_excludes_author_in_same_role(self, db):
        """Si el autor tiene el rol destino, no se notifica a sí mismo."""
        tenant = TenantFactory()
        doctor_a = _member(tenant, Role.DOCTOR)
        doctor_b = _member(tenant, Role.DOCTOR)

        with _ctx(tenant):
            note_create(
                tenant=tenant,
                user=doctor_a,
                title="Para médicos",
                scope=NoteScope.ROLE,
                target_role=Role.DOCTOR,
            )

        recipients = _recipients_of(tenant, NotificationKind.ROLE_NOTE)
        assert recipients == {doctor_b.pk}


# ===========================================================================
# agenda.agenda_item_note_create → team_note
# ===========================================================================


class TestTeamNoteNotifies:
    def _appointment(self, tenant: Any) -> Any:
        doctor = DoctorFactory(tenant=tenant)
        return AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + datetime.timedelta(minutes=30),
        )

    def test_notifies_doctor_and_reception(self, db):
        """Una nota de equipo en la cita notifica al médico y a recepción."""
        tenant = TenantFactory()
        appt = self._appointment(tenant)
        doc_user = appt.doctor.membership.user
        rec_user = _member(tenant, Role.RECEPTION)
        author = _member(tenant, Role.NURSE)

        with _ctx(tenant):
            agenda_item_note_create(
                tenant=tenant, user=author, body="Pedir ayuno", appointment_id=appt.id
            )

        recipients = _recipients_of(tenant, NotificationKind.TEAM_NOTE)
        assert doc_user.pk in recipients
        assert rec_user.pk in recipients
        assert author.pk not in recipients

    def test_excludes_author_when_doctor_writes(self, db):
        """Si el propio médico de la cita escribe, no se autonotifica; recepción sí."""
        tenant = TenantFactory()
        appt = self._appointment(tenant)
        doc_user = appt.doctor.membership.user
        rec_user = _member(tenant, Role.RECEPTION)

        with _ctx(tenant):
            agenda_item_note_create(
                tenant=tenant, user=doc_user, body="Indicaciones", appointment_id=appt.id
            )

        recipients = _recipients_of(tenant, NotificationKind.TEAM_NOTE)
        assert doc_user.pk not in recipients
        assert rec_user.pk in recipients

    def test_notifies_prior_commenters(self, db):
        """Quien ya comentó el hilo recibe aviso de los comentarios siguientes."""
        tenant = TenantFactory()
        appt = self._appointment(tenant)
        nurse = _member(tenant, Role.NURSE)

        with _ctx(tenant):
            # 1) la enfermera comenta primero
            agenda_item_note_create(
                tenant=tenant, user=nurse, body="Primera nota", appointment_id=appt.id
            )
            # 2) el médico comenta después → la enfermera (comentó antes) debe recibir aviso
            agenda_item_note_create(
                tenant=tenant,
                user=appt.doctor.membership.user,
                body="Respuesta del médico",
                appointment_id=appt.id,
            )

        nurse_notifs = Notification.all_objects.filter(
            tenant=tenant, kind=NotificationKind.TEAM_NOTE, recipient=nurse
        )
        assert nurse_notifs.exists()

    def test_team_note_on_event_notifies_prior_commenters(self, db):
        """Nota de equipo en un EVENTO de agenda avisa a quienes ya comentaron."""
        tenant = TenantFactory()
        block = AgendaBlockFactory(tenant=tenant)
        nurse = _member(tenant, Role.NURSE)
        reception = _member(tenant, Role.RECEPTION)

        with _ctx(tenant):
            agenda_item_note_create(tenant=tenant, user=nurse, body="primera", block_id=block.id)
            agenda_item_note_create(
                tenant=tenant, user=reception, body="segunda", block_id=block.id
            )

        nurse_notifs = Notification.all_objects.filter(
            tenant=tenant, kind=NotificationKind.TEAM_NOTE, recipient=nurse
        )
        assert nurse_notifs.exists()


# ===========================================================================
# agenda.agenda_block_create → meeting
# ===========================================================================


class TestMeetingNotifies:
    def _meeting_args(self, **over: Any) -> dict[str, Any]:
        base = {
            "kind": AgendaBlock.Kind.MEETING,
            "starts_at": _BASE_DT,
            "ends_at": _BASE_DT + datetime.timedelta(hours=1),
            "title": "Junta de equipo",
        }
        base.update(over)
        return base

    def test_clinic_wide_meeting_notifies_staff_only(self, db):
        """Reunión de toda la clínica → staff clínico (no finance/readonly), sin el autor."""
        tenant = TenantFactory()
        owner = _member(tenant, Role.OWNER)
        doctor = _member(tenant, Role.DOCTOR)
        nurse = _member(tenant, Role.NURSE)
        reception = _member(tenant, Role.RECEPTION)
        finance = _member(tenant, Role.FINANCE)
        readonly = _member(tenant, Role.READONLY)

        with _ctx(tenant):
            agenda_block_create(tenant=tenant, user=owner, **self._meeting_args())

        recipients = _recipients_of(tenant, NotificationKind.MEETING)
        assert recipients == {doctor.pk, nurse.pk, reception.pk}
        assert owner.pk not in recipients
        assert finance.pk not in recipients
        assert readonly.pk not in recipients

    def test_doctor_meeting_notifies_only_that_doctor(self, db):
        """Reunión atada a un médico → solo ese médico."""
        tenant = TenantFactory()
        owner = _member(tenant, Role.OWNER)
        _member(tenant, Role.NURSE)  # ruido: no debe recibir
        doctor = DoctorFactory(tenant=tenant)
        doc_user = doctor.membership.user

        with _ctx(tenant):
            agenda_block_create(
                tenant=tenant, user=owner, **self._meeting_args(doctor_id=doctor.id)
            )

        recipients = _recipients_of(tenant, NotificationKind.MEETING)
        assert recipients == {doc_user.pk}

    def test_consultorio_meeting_notifies_its_doctors(self, db):
        """Reunión atada a un consultorio → los médicos de ese consultorio."""
        tenant = TenantFactory()
        owner = _member(tenant, Role.OWNER)
        consultorio = ConsultorioFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        doctor.consultorios.add(consultorio)
        DoctorFactory(tenant=tenant)  # otro médico sin ese consultorio: no recibe

        with _ctx(tenant):
            agenda_block_create(
                tenant=tenant,
                user=owner,
                **self._meeting_args(consultorio_id=consultorio.id),
            )

        recipients = _recipients_of(tenant, NotificationKind.MEETING)
        assert recipients == {doctor.membership.user.pk}

    def test_block_does_not_notify(self, db):
        """Un BLOQUEO (no reunión) no genera notificaciones."""
        tenant = TenantFactory()
        owner = _member(tenant, Role.OWNER)
        _member(tenant, Role.DOCTOR)

        with _ctx(tenant):
            agenda_block_create(
                tenant=tenant,
                user=owner,
                **self._meeting_args(kind=AgendaBlock.Kind.BLOCK, title="Festivo"),
            )

        assert Notification.all_objects.filter(tenant=tenant).count() == 0
