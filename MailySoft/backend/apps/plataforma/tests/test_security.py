"""
Tests de seguridad críticos para la app plataforma.

Validan los cuatro invariantes de seguridad que no se pueden omitir:
  (a) Usuario de clínica SIN is_platform_staff → 403 en /plataforma/*.
  (b) super_admin ve clínicas de MÁS DE UN tenant (cross-tenant funciona).
  (c) platform_role=engineering NO puede listar usuarios de plataforma.
  (d) Cambiar estado de clínica requiere super_admin o sales (engineering NO).

Estos tests son de integración de capa API: usan APIClient con force_authenticate.
No requieren BD de PostgreSQL real para correr (Django SQLite por defecto en tests).

NOTA: Los tests que ejercitan cross-tenant a nivel de RLS real (PostgreSQL) deben
correr en el entorno con Postgres. Aquí se valida la capa de permisos Python/DRF,
que es suficiente para la barrera de seguridad de primer nivel.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tests.factories import (
    PatientFactory,
    PlatformStaffFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# Fixtures específicas de plataforma
# ---------------------------------------------------------------------------


@pytest.fixture
def super_admin(db):
    """Usuario de plataforma con rol super_admin."""
    return UserFactory(
        is_platform_staff=True,
        is_staff=True,
        platform_role="super_admin",
    )


@pytest.fixture
def sales_user(db):
    """Usuario de plataforma con rol sales."""
    return UserFactory(
        is_platform_staff=True,
        platform_role="sales",
    )


@pytest.fixture
def engineering_user(db):
    """Usuario de plataforma con rol engineering (PlatformStaffFactory usa este rol por defecto)."""
    return PlatformStaffFactory()  # platform_role="engineering"


@pytest.fixture
def clinic_member(db):
    """Usuario miembro de una clínica SIN is_platform_staff."""
    return UserFactory(is_platform_staff=False)


@pytest.fixture
def two_tenants_with_patients(db):
    """Dos clínicas distintas, cada una con un paciente."""
    tenant_a = TenantFactory(name="Clínica Alpha", slug="alpha")
    tenant_b = TenantFactory(name="Clínica Beta", slug="beta")
    patient_a = PatientFactory(tenant=tenant_a)
    patient_b = PatientFactory(tenant=tenant_b)
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "patient_a": patient_a,
        "patient_b": patient_b,
    }


# ---------------------------------------------------------------------------
# (a) Usuario de clínica SIN is_platform_staff → 403 en /plataforma/*
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url_name",
    [
        "platform-metricas",
        "platform-clinicas-list",
        "platform-usuarios-list",
    ],
)
def test_clinic_member_is_rejected_from_platform_endpoints(db, clinic_member, url_name):
    """Un miembro de clínica (sin is_platform_staff) debe recibir 403 en todos
    los endpoints del panel de plataforma."""
    client = APIClient()
    client.force_authenticate(user=clinic_member)

    url = reverse(url_name)
    response = client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN, (
        f"Esperaba 403 en {url_name} para usuario sin is_platform_staff, "
        f"obtuvo {response.status_code}"
    )


def test_anonymous_user_is_rejected_from_platform_metrics(db):
    """Un usuario anónimo (sin JWT) debe recibir 401 en métricas."""
    client = APIClient()
    url = reverse("platform-metricas")
    response = client.get(url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_clinic_member_with_membership_cannot_access_platform(db):
    """Un usuario owner de una clínica (con membresía) tampoco puede acceder
    al panel de plataforma si no tiene is_platform_staff=True."""
    tenant = TenantFactory()
    owner = UserFactory(is_platform_staff=False)
    TenantMembershipFactory(user=owner, tenant=tenant, role="owner")

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("platform-metricas")
    response = client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# (b) super_admin ve clínicas de MÁS DE UN tenant (cross-tenant funciona)
# ---------------------------------------------------------------------------


def test_super_admin_sees_clinics_from_multiple_tenants(db, super_admin, two_tenants_with_patients):
    """Un super_admin debe poder ver todas las clínicas en el listado,
    sin importar a cuál (si alguna) pertenezca como miembro."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-clinicas-list")
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK, (
        f"super_admin debería poder listar clínicas, obtuvo {response.status_code}"
    )

    # Extraer los slugs de las clínicas devueltas.
    data = response.data
    results = data.get("results", data) if isinstance(data, dict) else data
    slugs = {item["slug"] for item in results}

    assert "alpha" in slugs, "Clínica Alpha debería estar en el listado cross-tenant"
    assert "beta" in slugs, "Clínica Beta debería estar en el listado cross-tenant"


def test_super_admin_dashboard_counts_all_tenants(db, super_admin, two_tenants_with_patients):
    """Las métricas del dashboard deben incluir los datos de todos los tenants."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-metricas")
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK
    data = response.data

    # Hay exactamente 2 clínicas creadas en two_tenants_with_patients.
    assert data["total_clinicas"] >= 2, (
        f"El dashboard debería contar al menos 2 clínicas, tiene {data['total_clinicas']}"
    )
    # Hay exactamente 2 pacientes cross-tenant.
    assert data["total_pacientes"] >= 2, (
        f"El dashboard debería contar al menos 2 pacientes cross-tenant, "
        f"tiene {data['total_pacientes']}"
    )


# ---------------------------------------------------------------------------
# (c) engineering NO puede listar usuarios de plataforma
# ---------------------------------------------------------------------------


def test_engineering_cannot_list_platform_users(db, engineering_user):
    """Un usuario con platform_role=engineering debe recibir 403 al intentar
    listar usuarios del equipo de plataforma (solo super_admin puede)."""
    client = APIClient()
    client.force_authenticate(user=engineering_user)

    url = reverse("platform-usuarios-list")
    response = client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN, (
        f"engineering debería recibir 403 en /plataforma/usuarios/, "
        f"obtuvo {response.status_code}"
    )


def test_sales_cannot_list_platform_users(db, sales_user):
    """Un usuario con platform_role=sales también debe recibir 403 al listar
    usuarios de plataforma."""
    client = APIClient()
    client.force_authenticate(user=sales_user)

    url = reverse("platform-usuarios-list")
    response = client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_super_admin_can_list_platform_users(db, super_admin, engineering_user):
    """El super_admin sí puede listar usuarios de plataforma y ver al
    engineering_user en la respuesta."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-usuarios-list")
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK, (
        f"super_admin debería poder listar usuarios de plataforma, "
        f"obtuvo {response.status_code}"
    )

    data = response.data
    results = data.get("results", data) if isinstance(data, dict) else data
    emails = {item["email"] for item in results}

    # Tanto el super_admin como el engineering_user deben aparecer.
    assert super_admin.email in emails
    assert engineering_user.email in emails


# ---------------------------------------------------------------------------
# (d) Cambiar estado de clínica: super_admin/sales SÍ, engineering NO
# ---------------------------------------------------------------------------


def test_engineering_cannot_change_clinic_status(db, engineering_user):
    """Un usuario con platform_role=engineering no puede suspender ni reactivar
    una clínica."""
    tenant = TenantFactory(status="active")

    client = APIClient()
    client.force_authenticate(user=engineering_user)

    url = reverse("platform-clinica-estado", kwargs={"tenant_id": tenant.id})
    response = client.post(url, {"status": "suspended"}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN, (
        f"engineering debería recibir 403 al cambiar estado de clínica, "
        f"obtuvo {response.status_code}"
    )

    # Verificar que el estado NO cambió en BD.
    tenant.refresh_from_db()
    assert tenant.status == "active", "El estado de la clínica no debería haber cambiado"


def test_super_admin_can_suspend_clinic(db, super_admin):
    """El super_admin puede suspender una clínica activa."""
    tenant = TenantFactory(status="active")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-clinica-estado", kwargs={"tenant_id": tenant.id})
    response = client.post(url, {"status": "suspended"}, format="json")

    assert response.status_code == status.HTTP_200_OK, (
        f"super_admin debería poder suspender una clínica, obtuvo {response.status_code}"
    )

    tenant.refresh_from_db()
    assert tenant.status == "suspended", "La clínica debería haber quedado suspendida"


def test_sales_can_reactivate_suspended_clinic(db, sales_user):
    """El usuario de sales puede reactivar una clínica suspendida."""
    tenant = TenantFactory(status="suspended")

    client = APIClient()
    client.force_authenticate(user=sales_user)

    url = reverse("platform-clinica-estado", kwargs={"tenant_id": tenant.id})
    response = client.post(url, {"status": "active"}, format="json")

    assert response.status_code == status.HTTP_200_OK, (
        f"sales debería poder reactivar una clínica, obtuvo {response.status_code}"
    )

    tenant.refresh_from_db()
    assert tenant.status == "active"


def test_clinic_member_cannot_change_clinic_status(db, clinic_member):
    """Un miembro de clínica sin is_platform_staff no puede cambiar el estado."""
    tenant = TenantFactory(status="active")

    client = APIClient()
    client.force_authenticate(user=clinic_member)

    url = reverse("platform-clinica-estado", kwargs={"tenant_id": tenant.id})
    response = client.post(url, {"status": "suspended"}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN

    tenant.refresh_from_db()
    assert tenant.status == "active"


def test_status_change_rejects_invalid_value(db, super_admin):
    """El endpoint rechaza valores de estado no válidos (como 'trial')."""
    tenant = TenantFactory(status="active")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-clinica-estado", kwargs={"tenant_id": tenant.id})
    response = client.post(url, {"status": "trial"}, format="json")

    # 400 — el serializer rechaza el valor.
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_change_status_404_for_nonexistent_clinic(db, super_admin):
    """El endpoint devuelve 404 si la clínica no existe."""
    import uuid

    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse(
        "platform-clinica-estado",
        kwargs={"tenant_id": uuid.uuid4()},
    )
    response = client.post(url, {"status": "suspended"}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Validaciones adicionales de permisos en métricas y listado
# ---------------------------------------------------------------------------


def test_engineering_can_read_metrics(db, engineering_user):
    """engineering sí puede ver las métricas del dashboard."""
    client = APIClient()
    client.force_authenticate(user=engineering_user)

    url = reverse("platform-metricas")
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK


def test_engineering_can_list_clinics(db, engineering_user):
    """engineering sí puede listar clínicas (solo lectura)."""
    TenantFactory()

    client = APIClient()
    client.force_authenticate(user=engineering_user)

    url = reverse("platform-clinicas-list")
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK


def test_sales_can_read_metrics(db, sales_user):
    """sales sí puede ver las métricas del dashboard."""
    client = APIClient()
    client.force_authenticate(user=sales_user)

    url = reverse("platform-metricas")
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK
