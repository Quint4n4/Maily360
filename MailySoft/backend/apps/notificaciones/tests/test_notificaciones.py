"""
Tests de la app notificaciones (Fase 1 — cimiento).

Cubre:
- services.notification_fanout: una por destinatario, excluye al actor, deduplica,
  vacío cuando no hay destinatarios.
- services.notification_create: atajo de fanout; None si el destinatario es el actor.
- services.notification_mark_read: marca leída, idempotente, rechaza a quien no es
  el destinatario (DoesNotExist).
- services.notification_mark_all_read: marca todas y devuelve el conteo.
- selectors.notification_list_for_user / unread_count: solo lo del usuario, filtro
  only_unread, aislamiento multi-tenant.
- APIs: 401 sin token; listar; conteo; marcar una (200) y 404 de otro usuario/tenant;
  marcar todas.

Patrón: AAA. Fixture `db`. Mockeo de tenant igual que en notas/tests.
"""

import uuid as uuid_module
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.notificaciones.models import Notification, NotificationKind
from apps.notificaciones.selectors import (
    notification_list_for_user,
    notification_unread_count,
)
from apps.notificaciones.services import (
    notification_create,
    notification_fanout,
    notification_mark_all_read,
    notification_mark_read,
)
from apps.notificaciones.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

LIST_URL = "/api/v1/notificaciones/"
COUNT_URL = "/api/v1/notificaciones/conteo/"
MARK_ALL_URL = "/api/v1/notificaciones/leidas/"


def _mark_read_url(notification_id: Any) -> str:
    return f"/api/v1/notificaciones/{notification_id}/leida/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _member(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> Any:
    """Crea un user con membresía activa en el tenant."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_notification(
    *, tenant: Any, recipient: Any, actor: Any = None, read: bool = False
) -> Notification:
    """Crea una notificación directa (sin pasar por el fanout) para arrange."""
    note = notification_create(
        tenant=tenant,
        recipient=recipient,
        kind=NotificationKind.TEAM_NOTE,
        title="Aviso de prueba",
        actor=actor,
    )
    assert note is not None
    if read:
        note = notification_mark_read(notification=note, user=recipient)
    return note


# ===========================================================================
# services.notification_fanout
# ===========================================================================


class TestNotificationFanout:
    """Reparto de notificaciones a varios destinatarios."""

    def test_creates_one_per_recipient(self, db):
        """fanout crea exactamente una notificación por destinatario."""
        tenant = TenantFactory()
        r1, r2, r3 = UserFactory(), UserFactory(), UserFactory()

        created = notification_fanout(
            tenant=tenant,
            recipients=[r1, r2, r3],
            kind=NotificationKind.MEETING,
            title="Junta de equipo",
        )

        assert len(created) == 3
        assert {n.recipient_id for n in created} == {r1.pk, r2.pk, r3.pk}

    def test_excludes_actor(self, db):
        """El actor nunca se notifica a sí mismo."""
        tenant = TenantFactory()
        actor = UserFactory()
        other = UserFactory()

        created = notification_fanout(
            tenant=tenant,
            recipients=[actor, other],
            kind=NotificationKind.TEAM_NOTE,
            title="Nota nueva",
            actor=actor,
        )

        assert len(created) == 1
        assert created[0].recipient_id == other.pk

    def test_dedupes_recipients(self, db):
        """Un destinatario repetido recibe solo un aviso."""
        tenant = TenantFactory()
        r1 = UserFactory()

        created = notification_fanout(
            tenant=tenant,
            recipients=[r1, r1, r1],
            kind=NotificationKind.BROADCAST,
            title="Aviso",
        )

        assert len(created) == 1

    def test_empty_when_no_recipients_left(self, db):
        """Si solo estaba el actor, no se crea nada."""
        tenant = TenantFactory()
        actor = UserFactory()

        created = notification_fanout(
            tenant=tenant,
            recipients=[actor],
            kind=NotificationKind.TEAM_NOTE,
            title="x",
            actor=actor,
        )

        assert created == []


# ===========================================================================
# services.notification_create
# ===========================================================================


class TestNotificationCreate:
    def test_creates_single(self, db):
        """notification_create devuelve la notificación creada."""
        tenant = TenantFactory()
        recipient = UserFactory()

        note = notification_create(
            tenant=tenant,
            recipient=recipient,
            kind=NotificationKind.ROLE_NOTE,
            title="El doctor te dejó una nota",
        )

        assert note is not None
        assert note.recipient_id == recipient.pk
        assert note.is_read is False

    def test_returns_none_if_recipient_is_actor(self, db):
        """No hay auto-notificación: recipient == actor → None."""
        tenant = TenantFactory()
        user = UserFactory()

        note = notification_create(
            tenant=tenant,
            recipient=user,
            kind=NotificationKind.ROLE_NOTE,
            title="x",
            actor=user,
        )

        assert note is None


# ===========================================================================
# services.notification_mark_read / mark_all_read
# ===========================================================================


class TestNotificationMarkRead:
    def test_sets_read_at(self, db):
        """Marcar leída pobla read_at."""
        tenant = TenantFactory()
        recipient = UserFactory()
        note = _make_notification(tenant=tenant, recipient=recipient)

        updated = notification_mark_read(notification=note, user=recipient)

        assert updated.read_at is not None
        assert updated.is_read is True

    def test_is_idempotent(self, db):
        """Marcar leída dos veces no cambia el read_at original."""
        tenant = TenantFactory()
        recipient = UserFactory()
        note = _make_notification(tenant=tenant, recipient=recipient)

        first = notification_mark_read(notification=note, user=recipient)
        first_read_at = first.read_at
        second = notification_mark_read(notification=note, user=recipient)

        assert second.read_at == first_read_at

    def test_wrong_user_raises_doesnotexist(self, db):
        """Un usuario que no es el destinatario no puede marcarla (DoesNotExist)."""
        tenant = TenantFactory()
        recipient = UserFactory()
        intruder = UserFactory()
        note = _make_notification(tenant=tenant, recipient=recipient)

        with pytest.raises(Notification.DoesNotExist):
            notification_mark_read(notification=note, user=intruder)

    def test_mark_all_read_returns_count(self, db):
        """mark_all_read marca todas las no leídas y devuelve cuántas cambió."""
        tenant = TenantFactory()
        recipient = UserFactory()
        _make_notification(tenant=tenant, recipient=recipient)
        _make_notification(tenant=tenant, recipient=recipient)
        _make_notification(tenant=tenant, recipient=recipient, read=True)

        with tenant_ctx(tenant):
            changed = notification_mark_all_read(tenant=tenant, user=recipient)

        assert changed == 2


# ===========================================================================
# selectors
# ===========================================================================


class TestNotificationSelectors:
    def test_list_only_own(self, db):
        """Un usuario solo ve sus propias notificaciones."""
        tenant = TenantFactory()
        me = UserFactory()
        other = UserFactory()
        _make_notification(tenant=tenant, recipient=me)
        _make_notification(tenant=tenant, recipient=other)

        with tenant_ctx(tenant):
            qs = notification_list_for_user(user=me, tenant=tenant)
            ids = list(qs.values_list("recipient_id", flat=True))

        assert ids == [me.pk]

    def test_only_unread_filter(self, db):
        """only_unread devuelve solo las no leídas."""
        tenant = TenantFactory()
        me = UserFactory()
        _make_notification(tenant=tenant, recipient=me)
        _make_notification(tenant=tenant, recipient=me, read=True)

        with tenant_ctx(tenant):
            total = notification_list_for_user(user=me, tenant=tenant).count()
            unread = notification_list_for_user(user=me, tenant=tenant, only_unread=True).count()

        assert total == 2
        assert unread == 1

    def test_unread_count(self, db):
        """notification_unread_count cuenta solo las no leídas del usuario."""
        tenant = TenantFactory()
        me = UserFactory()
        _make_notification(tenant=tenant, recipient=me)
        _make_notification(tenant=tenant, recipient=me)
        _make_notification(tenant=tenant, recipient=me, read=True)

        with tenant_ctx(tenant):
            count = notification_unread_count(user=me, tenant=tenant)

        assert count == 2

    def test_tenant_isolation(self, db):
        """Una notificación de otro tenant no es visible (aislamiento)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        me = UserFactory()
        # Misma persona, notificación en el tenant B.
        _make_notification(tenant=tenant_b, recipient=me)

        with tenant_ctx(tenant_a):
            count = notification_unread_count(user=me, tenant=tenant_a)

        assert count == 0


# ===========================================================================
# APIs
# ===========================================================================


class TestNotificationApisRequireAuth:
    def test_list_requires_auth(self, db, api_client):
        """GET /notificaciones/ sin token → 401."""
        resp = api_client.get(LIST_URL)
        assert resp.status_code == 401

    def test_count_requires_auth(self, db, api_client):
        """GET /notificaciones/conteo/ sin token → 401."""
        resp = api_client.get(COUNT_URL)
        assert resp.status_code == 401


class TestNotificationApis:
    def test_list_returns_my_notifications(self, db):
        """GET /notificaciones/ devuelve solo las del usuario autenticado."""
        tenant = TenantFactory()
        me = _member(tenant)
        other = _member(tenant)
        _make_notification(tenant=tenant, recipient=me)
        _make_notification(tenant=tenant, recipient=other)

        client = _auth_client(me)
        with api_tenant_ctx(tenant):
            resp = client.get(LIST_URL)

        assert resp.status_code == 200
        assert resp.data["count"] == 1

    def test_unread_count_endpoint(self, db):
        """GET /notificaciones/conteo/ devuelve {'unread': N}."""
        tenant = TenantFactory()
        me = _member(tenant)
        _make_notification(tenant=tenant, recipient=me)
        _make_notification(tenant=tenant, recipient=me, read=True)

        client = _auth_client(me)
        with api_tenant_ctx(tenant):
            resp = client.get(COUNT_URL)

        assert resp.status_code == 200
        assert resp.data["unread"] == 1

    def test_mark_read_endpoint(self, db):
        """POST /notificaciones/<id>/leida/ marca leída y devuelve la notificación."""
        tenant = TenantFactory()
        me = _member(tenant)
        note = _make_notification(tenant=tenant, recipient=me)

        client = _auth_client(me)
        with api_tenant_ctx(tenant):
            resp = client.post(_mark_read_url(note.id))

        assert resp.status_code == 200
        assert resp.data["is_read"] is True

    def test_mark_read_other_user_404(self, db):
        """No puedo marcar la notificación de otro usuario → 404."""
        tenant = TenantFactory()
        me = _member(tenant)
        other = _member(tenant)
        note = _make_notification(tenant=tenant, recipient=other)

        client = _auth_client(me)
        with api_tenant_ctx(tenant):
            resp = client.post(_mark_read_url(note.id))

        assert resp.status_code == 404

    def test_mark_read_unknown_id_404(self, db):
        """Un id inexistente → 404."""
        tenant = TenantFactory()
        me = _member(tenant)

        client = _auth_client(me)
        with api_tenant_ctx(tenant):
            resp = client.post(_mark_read_url(uuid_module.uuid4()))

        assert resp.status_code == 404

    def test_mark_read_cross_tenant_404(self, db):
        """No se puede marcar una notificación de OTRO tenant → 404 (aislamiento)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        me = _member(tenant_a)
        victim = _member(tenant_b)
        note = _make_notification(tenant=tenant_b, recipient=victim)

        client = _auth_client(me)
        with api_tenant_ctx(tenant_a):
            resp = client.post(_mark_read_url(note.id))

        assert resp.status_code == 404

    def test_mark_all_read_endpoint(self, db):
        """POST /notificaciones/leidas/ marca todas y devuelve {'updated': N}."""
        tenant = TenantFactory()
        me = _member(tenant)
        _make_notification(tenant=tenant, recipient=me)
        _make_notification(tenant=tenant, recipient=me)

        client = _auth_client(me)
        with api_tenant_ctx(tenant):
            resp = client.post(MARK_ALL_URL)

        assert resp.status_code == 200
        assert resp.data["updated"] == 2
