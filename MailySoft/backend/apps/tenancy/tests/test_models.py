"""
Tests para apps/tenancy/models.py — Tenant y TenantMembership.

Cubre: representación en cadena, estado por defecto, restricciones de unicidad,
choices de rol, y relaciones entre modelos.
"""

import uuid

import pytest
from django.db import IntegrityError

from apps.tenancy.models import Tenant, TenantMembership
from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tenant_str_returns_name() -> None:
    """__str__ devuelve el nombre comercial del tenant."""
    # Arrange
    tenant = TenantFactory(name="Clínica San José")

    # Act
    result = str(tenant)

    # Assert
    assert result == "Clínica San José"


@pytest.mark.django_db
def test_tenant_default_status_is_trial() -> None:
    """Un Tenant creado sin status explícito debe estar en estado 'trial'."""
    # Arrange / Act
    tenant = Tenant.objects.create(
        name="Nueva Clínica",
        slug="nueva-clinica",
    )

    # Assert
    assert tenant.status == Tenant.Status.TRIAL


@pytest.mark.django_db
def test_tenant_slug_is_unique() -> None:
    """No pueden existir dos Tenants con el mismo slug.

    Arrange: un tenant con slug 'duplicado'.
    Act: crear otro con el mismo slug.
    Assert: lanza IntegrityError.
    """
    # Arrange
    TenantFactory(slug="duplicado")

    # Act / Assert
    with pytest.raises(IntegrityError):
        TenantFactory(slug="duplicado")


@pytest.mark.django_db
def test_tenant_id_is_uuid() -> None:
    """El PK de Tenant es UUID (hereda de BaseModel)."""
    # Arrange / Act
    tenant = TenantFactory()

    # Assert
    assert isinstance(tenant.id, uuid.UUID)


@pytest.mark.django_db
def test_tenant_has_timestamps() -> None:
    """Tenant tiene created_at y updated_at rellenados automáticamente."""
    # Arrange / Act
    tenant = TenantFactory()

    # Assert
    assert tenant.created_at is not None
    assert tenant.updated_at is not None


@pytest.mark.django_db
def test_tenant_deleted_at_is_null_by_default() -> None:
    """Un tenant nuevo no debe estar soft-deleted."""
    # Arrange / Act
    tenant = TenantFactory()

    # Assert
    assert tenant.deleted_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        Tenant.Status.TRIAL,
        Tenant.Status.ACTIVE,
        Tenant.Status.SUSPENDED,
    ],
)
def test_tenant_accepts_valid_status_choices(status: str) -> None:
    """Cada estado del ciclo de vida de Tenant debe ser persistible."""
    # Arrange / Act
    tenant = TenantFactory(status=status)

    # Assert
    tenant.refresh_from_db()
    assert tenant.status == status


# ---------------------------------------------------------------------------
# TenantMembership
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_membership_str_contains_user_tenant_and_role() -> None:
    """__str__ de TenantMembership incluye email, nombre del tenant y rol."""
    # Arrange
    user = UserFactory(email="doc@clinica.mx")
    tenant = TenantFactory(name="Clínica ABC")
    membership = TenantMembershipFactory(user=user, tenant=tenant, role="doctor")

    # Act
    result = str(membership)

    # Assert
    assert "doc@clinica.mx" in result
    assert "Clínica ABC" in result
    assert "doctor" in result


@pytest.mark.django_db
def test_membership_unique_per_user_and_tenant() -> None:
    """Un usuario no puede tener dos membresías en la misma clínica.

    Arrange: membresía existente para user X en tenant Y.
    Act: crear otra membresía para el mismo par (user, tenant).
    Assert: lanza IntegrityError (unique_together).
    """
    # Arrange
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role="doctor")

    # Act / Assert
    with pytest.raises(IntegrityError):
        TenantMembershipFactory(user=user, tenant=tenant, role="admin")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [
        TenantMembership.Role.OWNER,
        TenantMembership.Role.ADMIN,
        TenantMembership.Role.DOCTOR,
        TenantMembership.Role.NURSE,
        TenantMembership.Role.RECEPTION,
        TenantMembership.Role.FINANCE,
        TenantMembership.Role.READONLY,
    ],
)
def test_membership_role_choices_are_all_persistable(role: str) -> None:
    """Cada rol definido en TenantMembership.Role debe poder guardarse en BD."""
    # Arrange / Act
    membership = TenantMembershipFactory(role=role)

    # Assert
    membership.refresh_from_db()
    assert membership.role == role


@pytest.mark.django_db
def test_user_can_have_memberships_in_multiple_tenants() -> None:
    """Un usuario puede pertenecer a más de una clínica con distintos roles.

    Esto modela el caso del médico que trabaja en varias clínicas.
    """
    # Arrange
    user = UserFactory()
    tenant_1 = TenantFactory()
    tenant_2 = TenantFactory()
    tenant_3 = TenantFactory()

    # Act
    m1 = TenantMembershipFactory(user=user, tenant=tenant_1, role="owner")
    m2 = TenantMembershipFactory(user=user, tenant=tenant_2, role="doctor")
    m3 = TenantMembershipFactory(user=user, tenant=tenant_3, role="readonly")

    # Assert
    memberships = user.memberships.all()
    assert memberships.count() == 3
    tenant_ids = set(memberships.values_list("tenant_id", flat=True))
    assert tenant_ids == {tenant_1.id, tenant_2.id, tenant_3.id}


@pytest.mark.django_db
def test_membership_is_active_by_default() -> None:
    """Una membresía recién creada debe estar activa."""
    # Arrange / Act
    membership = TenantMembershipFactory()

    # Assert
    assert membership.is_active is True


@pytest.mark.django_db
def test_membership_can_be_deactivated() -> None:
    """Una membresía puede desactivarse sin borrarla."""
    # Arrange
    membership = TenantMembershipFactory(is_active=True)

    # Act
    membership.is_active = False
    membership.save()

    # Assert
    membership.refresh_from_db()
    assert membership.is_active is False


@pytest.mark.django_db
def test_membership_does_not_appear_in_active_filter_when_inactive() -> None:
    """Membresías inactivas no deben aparecer al filtrar is_active=True."""
    # Arrange
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, is_active=False)

    # Act
    active_memberships = user.memberships.filter(is_active=True)

    # Assert
    assert active_memberships.count() == 0


@pytest.mark.django_db
def test_deleting_tenant_cascades_to_memberships() -> None:
    """Borrar un tenant debe eliminar en cascada sus membresías (on_delete=CASCADE)."""
    # Arrange
    user = UserFactory()
    tenant = TenantFactory()
    membership_id = TenantMembershipFactory(user=user, tenant=tenant).id

    # Act
    tenant.delete()

    # Assert
    assert not TenantMembership.objects.filter(id=membership_id).exists()


@pytest.mark.django_db
def test_deleting_user_cascades_to_memberships() -> None:
    """Borrar un usuario debe eliminar en cascada sus membresías (on_delete=CASCADE)."""
    # Arrange
    user = UserFactory()
    tenant = TenantFactory()
    membership_id = TenantMembershipFactory(user=user, tenant=tenant).id

    # Act
    user.delete()

    # Assert
    assert not TenantMembership.objects.filter(id=membership_id).exists()
