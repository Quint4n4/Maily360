"""Tests de los selectors de authn."""

from typing import Any

import pytest

from apps.authn.selectors import user_active_memberships
from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory


@pytest.mark.django_db
def test_user_active_memberships_incluye_clinicas_en_trial() -> None:
    """El dueño de una clínica en TRIAL debe aparecer en sus membresías activas.

    Regresión del bug 2026-07-03: `user_active_memberships` filtraba solo
    `tenant__status="active"`, excluyendo "trial". Como
    `resolve_membership_for_user` SÍ incluye trial, el `/me/` resolvía el
    active_tenant pero NO encontraba la membership correspondiente →
    active_role=None → el frontend degradaba al dueño a "Solo lectura"
    (fallback de mínimo privilegio). Todas las clínicas nacen en trial, así que
    afectaba a TODO dueño de clínica nueva.
    """
    user: Any = UserFactory()
    tenant_trial = TenantFactory(status="trial")
    TenantMembershipFactory(user=user, tenant=tenant_trial, role="owner", is_active=True)

    memberships = list(user_active_memberships(user=user))

    assert len(memberships) == 1
    assert memberships[0].tenant_id == tenant_trial.id
    assert memberships[0].role == "owner"


@pytest.mark.django_db
def test_user_active_memberships_incluye_clinicas_active() -> None:
    """Las clínicas 'active' siguen incluyéndose (no se rompió el caso previo)."""
    user: Any = UserFactory()
    tenant_active = TenantFactory(status="active")
    TenantMembershipFactory(user=user, tenant=tenant_active, role="admin", is_active=True)

    memberships = list(user_active_memberships(user=user))

    assert len(memberships) == 1
    assert memberships[0].tenant_id == tenant_active.id


@pytest.mark.django_db
def test_user_active_memberships_excluye_suspended() -> None:
    """Las clínicas 'suspended' NO aparecen: solo active/trial tienen acceso."""
    user: Any = UserFactory()
    tenant_susp = TenantFactory(status="suspended")
    TenantMembershipFactory(user=user, tenant=tenant_susp, role="owner", is_active=True)

    assert list(user_active_memberships(user=user)) == []
