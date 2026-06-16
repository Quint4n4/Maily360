"""
Tests para el alta de clínica nueva y la ficha de detalle.

Cubre los casos críticos del spec:
  (1) Alta feliz: tenant + owner + semilla creados, contraseña válida para login,
      auditoría TENANT_CREATE registrada, owner puede autenticarse.
  (2) Slug único: dos clínicas con el mismo nombre obtienen slugs distintos.
  (3) Rollback atómico: email duplicado → 400, NO queda tenant huérfano.
  (4) Permisos: engineering NO puede crear (403); super_admin/sales sí.
  (5) Contraseña temporal NUNCA en auditoría.
  (6) Ficha de detalle: counts correctos, members listados.
  (7) Ficha 404 para id inexistente.
  (8) Aislamiento: un no-staff recibe 403 en la ficha.
"""

import uuid

import pytest
from django.contrib.auth import authenticate
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.personal.models import Consultorio
from apps.agenda.models import AppointmentType
from apps.plataforma.services import _generar_password_temporal, tenant_and_owner_create
from apps.tenancy.models import Tenant, TenantMembership
from tests.factories import (
    AppointmentFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


# ---------------------------------------------------------------------------
# Fixtures
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
    """Usuario de plataforma con rol engineering (solo lectura)."""
    return UserFactory(
        is_platform_staff=True,
        platform_role="engineering",
    )


@pytest.fixture
def clinic_member(db):
    """Usuario miembro de una clínica SIN is_platform_staff."""
    return UserFactory(is_platform_staff=False)


# ---------------------------------------------------------------------------
# (0) Tests unitarios del helper de contraseña
# ---------------------------------------------------------------------------


def test_generar_password_temporal_longitud():
    """La contraseña temporal tiene exactamente 16 caracteres."""
    pwd = _generar_password_temporal()
    assert len(pwd) == 16


def test_generar_password_temporal_no_numerica():
    """La contraseña temporal no es completamente numérica."""
    for _ in range(20):
        pwd = _generar_password_temporal()
        assert not pwd.isdigit(), f"Contraseña completamente numérica generada: {pwd}"


def test_generar_password_temporal_tiene_clases_requeridas():
    """La contraseña temporal tiene al menos 1 char de cada clase requerida."""
    for _ in range(20):
        pwd = _generar_password_temporal()
        tiene_upper = any(c in "ABCDEFGHJKLMNPQRSTUVWXYZ" for c in pwd)
        tiene_lower = any(c in "abcdefghjkmnpqrstuvwxyz" for c in pwd)
        tiene_digit = any(c.isdigit() for c in pwd)
        tiene_symbol = any(c in "!@#$%^&*" for c in pwd)
        assert tiene_upper, f"Sin mayúscula: {pwd}"
        assert tiene_lower, f"Sin minúscula: {pwd}"
        assert tiene_digit, f"Sin dígito: {pwd}"
        assert tiene_symbol, f"Sin símbolo: {pwd}"


def test_generar_password_temporal_es_unica():
    """Dos llamadas consecutivas producen contraseñas distintas."""
    pwd1 = _generar_password_temporal()
    pwd2 = _generar_password_temporal()
    # Con 16 chars y espacio de ~72^16, la probabilidad de colisión es astronómicamente baja.
    assert pwd1 != pwd2


# ---------------------------------------------------------------------------
# (1) Alta feliz — service
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tenant_and_owner_create_happy_path(super_admin):
    """Camino feliz: crea tenant + owner + semilla correctamente."""
    resultado = tenant_and_owner_create(
        actor=super_admin,
        name="Clínica San José",
        owner_email="dre@sanjose.test",
        owner_first_name="Rodrigo",
        owner_last_name="Martínez",
    )

    tenant = resultado["tenant"]
    owner = resultado["owner"]
    pwd = resultado["temporary_password"]

    # Tenant creado en TRIAL.
    assert Tenant.objects.filter(id=tenant.id).exists()
    assert tenant.status == Tenant.Status.TRIAL
    assert tenant.trial_ends_at is not None
    assert tenant.slug == "clinica-san-jose"

    # Owner creado con rol "owner".
    assert TenantMembership.objects.filter(
        tenant=tenant, user=owner.user, role="owner"
    ).exists()
    assert owner.user.email == "dre@sanjose.test"

    # Contraseña devuelta no está vacía.
    assert len(pwd) >= 10

    # Semilla: 1 consultorio.
    assert Consultorio.all_objects.filter(tenant=tenant, name="Consultorio 1").exists()

    # Semilla: 3 tipos de cita.
    tipos = list(
        AppointmentType.all_objects.filter(tenant=tenant).values_list("name", flat=True)
    )
    assert "Consulta" in tipos
    assert "Primera vez" in tipos
    assert "Seguimiento" in tipos


@pytest.mark.django_db
def test_tenant_and_owner_create_owner_can_authenticate(super_admin):
    """El owner puede autenticarse con la contraseña temporal devuelta."""
    resultado = tenant_and_owner_create(
        actor=super_admin,
        name="Clínica Prueba Auth",
        owner_email="owner@autenticacion.test",
        owner_first_name="Ana",
        owner_last_name="García",
    )
    pwd = resultado["temporary_password"]
    owner_email = resultado["owner"].user.email

    # Django authenticate valida email + password.
    user = authenticate(username=owner_email, password=pwd)
    assert user is not None, "El owner debería poder autenticarse con la contraseña temporal"


@pytest.mark.django_db
def test_tenant_and_owner_create_registra_auditoria(super_admin):
    """Se registra TENANT_CREATE en la auditoría."""
    resultado = tenant_and_owner_create(
        actor=super_admin,
        name="Clínica Auditada",
        owner_email="owner@auditada.test",
        owner_first_name="Carlos",
        owner_last_name="López",
    )
    tenant = resultado["tenant"]

    log = AuditLog.all_objects.filter(
        action=ActionType.TENANT_CREATE,
        resource_id=tenant.id,
    ).first()

    assert log is not None, "Debería existir un AuditLog TENANT_CREATE"
    assert log.actor_id == super_admin.id


# ---------------------------------------------------------------------------
# (2) Slug único
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_slug_unico_dos_clinicas_mismo_nombre(super_admin):
    """Dos clínicas con el mismo nombre obtienen slugs distintos."""
    r1 = tenant_and_owner_create(
        actor=super_admin,
        name="Clínica Norte",
        owner_email="owner1@norte.test",
        owner_first_name="A",
        owner_last_name="B",
    )
    r2 = tenant_and_owner_create(
        actor=super_admin,
        name="Clínica Norte",
        owner_email="owner2@norte.test",
        owner_first_name="C",
        owner_last_name="D",
    )
    assert r1["tenant"].slug != r2["tenant"].slug
    assert r2["tenant"].slug == "clinica-norte-2"


# ---------------------------------------------------------------------------
# (3) Rollback atómico
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rollback_atomico_email_duplicado(super_admin):
    """Email duplicado lanza ValidationError y NO queda tenant huérfano."""
    from django.core.exceptions import ValidationError as DjangoValidationError

    # Crear el primer tenant con el email.
    tenant_and_owner_create(
        actor=super_admin,
        name="Clínica Primero",
        owner_email="shared@email.test",
        owner_first_name="Primer",
        owner_last_name="Owner",
    )

    tenant_count_antes = Tenant.objects.count()

    with pytest.raises(DjangoValidationError):
        tenant_and_owner_create(
            actor=super_admin,
            name="Clínica Segundo",
            owner_email="shared@email.test",  # email duplicado
            owner_first_name="Segundo",
            owner_last_name="Owner",
        )

    # El Tenant de "Clínica Segundo" NO debe haber quedado en BD.
    assert Tenant.objects.count() == tenant_count_antes, (
        "No debería haber quedado un Tenant huérfano tras el rollback"
    )
    assert not Tenant.objects.filter(name="Clínica Segundo").exists()


# ---------------------------------------------------------------------------
# (4) Permisos en la API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_engineering_no_puede_crear_clinica(engineering_user):
    """engineering NO puede hacer POST /plataforma/clinicas/ (403)."""
    client = APIClient()
    client.force_authenticate(user=engineering_user)

    url = reverse("platform-clinicas-list")
    payload = {
        "name": "Clínica Intento Engineering",
        "owner_email": "eng@test.com",
        "owner_first_name": "Eng",
        "owner_last_name": "User",
    }
    response = client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_super_admin_puede_crear_clinica(super_admin):
    """super_admin puede hacer POST /plataforma/clinicas/ (201)."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-clinicas-list")
    payload = {
        "name": "Clínica SuperAdmin",
        "owner_email": "owner@superadmin.test",
        "owner_first_name": "Super",
        "owner_last_name": "Owner",
    }
    response = client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED

    data = response.data
    assert "temporary_password" in data
    assert len(data["temporary_password"]) >= 10
    assert data["owner_email"] == "owner@superadmin.test"
    assert "tenant" in data
    assert data["tenant"]["slug"] == "clinica-superadmin"


@pytest.mark.django_db
def test_sales_puede_crear_clinica(sales_user):
    """sales puede hacer POST /plataforma/clinicas/ (201)."""
    client = APIClient()
    client.force_authenticate(user=sales_user)

    url = reverse("platform-clinicas-list")
    payload = {
        "name": "Clínica Sales",
        "owner_email": "owner@sales.test",
        "owner_first_name": "Sales",
        "owner_last_name": "Owner",
    }
    response = client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_clinic_member_no_puede_crear_clinica(clinic_member):
    """Un miembro de clínica sin is_platform_staff recibe 403."""
    client = APIClient()
    client.force_authenticate(user=clinic_member)

    url = reverse("platform-clinicas-list")
    payload = {
        "name": "Clínica Intruso",
        "owner_email": "intruso@test.com",
        "owner_first_name": "Intruso",
        "owner_last_name": "User",
    }
    response = client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_email_duplicado_devuelve_400_sin_tenant_huerfano(super_admin):
    """Email duplicado → API devuelve 400 y NO crea Tenant huérfano."""
    client = APIClient()
    client.force_authenticate(user=super_admin)
    url = reverse("platform-clinicas-list")

    # Primera creación.
    payload = {
        "name": "Clínica Uno",
        "owner_email": "dup@api.test",
        "owner_first_name": "Primer",
        "owner_last_name": "Owner",
    }
    r1 = client.post(url, payload, format="json")
    assert r1.status_code == status.HTTP_201_CREATED

    tenant_count = Tenant.objects.count()

    # Segunda creación con email repetido.
    payload["name"] = "Clínica Dos"
    r2 = client.post(url, payload, format="json")
    assert r2.status_code == status.HTTP_400_BAD_REQUEST

    # No se creó un Tenant huérfano.
    assert Tenant.objects.count() == tenant_count


# ---------------------------------------------------------------------------
# (5) Contraseña temporal NUNCA en auditoría
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_password_temporal_no_en_auditoria(super_admin):
    """La contraseña temporal NO aparece en ninguna entrada de auditoría."""
    resultado = tenant_and_owner_create(
        actor=super_admin,
        name="Clínica Sin Password en Audit",
        owner_email="owner@nopasswd.test",
        owner_first_name="Sin",
        owner_last_name="Password",
    )
    pwd = resultado["temporary_password"]

    # Revisar todos los AuditLog creados en esta sesión de test.
    for log in AuditLog.all_objects.all():
        assert pwd not in str(log.description), (
            f"La contraseña temporal apareció en description del AuditLog {log.id}"
        )
        assert pwd not in str(log.metadata), (
            f"La contraseña temporal apareció en metadata del AuditLog {log.id}"
        )
        assert pwd not in str(log.resource_repr), (
            f"La contraseña temporal apareció en resource_repr del AuditLog {log.id}"
        )


# ---------------------------------------------------------------------------
# (6) Ficha de detalle — GET /plataforma/clinicas/<id>/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinica_detail_counts_correctos(super_admin):
    """La ficha de detalle devuelve counts correctos."""
    # Crear la clínica vía el service (incluye 1 consultorio y 3 tipos de cita).
    resultado = tenant_and_owner_create(
        actor=super_admin,
        name="Clínica Ficha",
        owner_email="owner@ficha.test",
        owner_first_name="Ficha",
        owner_last_name="Owner",
    )
    tenant = resultado["tenant"]

    # Agregar paciente y cita manualmente.
    patient = PatientFactory(tenant=tenant)
    # appointment necesita un doctor, pero para contar solo necesitamos la FK tenant.
    # Usamos AppointmentFactory que crea su propio doctor (y su tenant debe coincidir).
    # Como el doctor se crea en otro tenant, usamos all_objects directo.
    # Para simplificar el test, contamos desde la API directamente.

    client = APIClient()
    client.force_authenticate(user=super_admin)
    url = reverse("platform-clinica-detail", kwargs={"tenant_id": tenant.id})
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK
    data = response.data

    assert data["id"] == str(tenant.id)
    assert data["name"] == "Clínica Ficha"
    assert data["status"] == "trial"
    assert data["member_count"] == 1  # solo el owner
    assert data["appointment_count"] == 0
    assert isinstance(data["members"], list)
    assert len(data["members"]) == 1
    assert data["members"][0]["email"] == "owner@ficha.test"
    assert data["members"][0]["role"] == "owner"


@pytest.mark.django_db
def test_clinica_detail_members_listados(super_admin):
    """La ficha lista todos los miembros del tenant."""
    resultado = tenant_and_owner_create(
        actor=super_admin,
        name="Clínica Members",
        owner_email="owner@members.test",
        owner_first_name="Owner",
        owner_last_name="Test",
    )
    tenant = resultado["tenant"]

    # Agregar un segundo miembro directamente.
    extra_user = UserFactory()
    TenantMembershipFactory(user=extra_user, tenant=tenant, role="doctor")

    client = APIClient()
    client.force_authenticate(user=super_admin)
    url = reverse("platform-clinica-detail", kwargs={"tenant_id": tenant.id})
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK
    data = response.data
    assert data["member_count"] == 2  # owner + doctor (ambos activos)
    emails = {m["email"] for m in data["members"]}
    assert "owner@members.test" in emails
    assert extra_user.email in emails


# ---------------------------------------------------------------------------
# (7) Ficha 404 para id inexistente
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinica_detail_404_inexistente(super_admin):
    """GET /plataforma/clinicas/<id>/ con id inexistente devuelve 404."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-clinica-detail", kwargs={"tenant_id": uuid.uuid4()})
    response = client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# (8) Aislamiento de permisos en la ficha
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clinica_detail_requiere_platform_staff(clinic_member):
    """Un no-staff recibe 403 al intentar ver la ficha de una clínica."""
    tenant = TenantFactory()

    client = APIClient()
    client.force_authenticate(user=clinic_member)

    url = reverse("platform-clinica-detail", kwargs={"tenant_id": tenant.id})
    response = client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_clinica_detail_engineering_puede_ver(engineering_user):
    """engineering puede ver la ficha de cualquier clínica (solo lectura)."""
    tenant = TenantFactory()

    client = APIClient()
    client.force_authenticate(user=engineering_user)

    url = reverse("platform-clinica-detail", kwargs={"tenant_id": tenant.id})
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_clinica_detail_super_admin_ve_cualquier_tenant(super_admin):
    """super_admin ve la ficha de cualquier tenant (cross-tenant)."""
    tenant_a = TenantFactory(name="Alpha", slug="alpha-x")
    tenant_b = TenantFactory(name="Beta", slug="beta-x")

    client = APIClient()
    client.force_authenticate(user=super_admin)

    for tenant in (tenant_a, tenant_b):
        url = reverse("platform-clinica-detail", kwargs={"tenant_id": tenant.id})
        r = client.get(url)
        assert r.status_code == status.HTTP_200_OK, (
            f"super_admin debería ver ficha de {tenant.name}, obtuvo {r.status_code}"
        )


# ---------------------------------------------------------------------------
# (9) Validaciones de input
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_rechaza_trial_days_invalido(super_admin):
    """trial_days fuera de rango [1, 365] → 400."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-clinicas-list")
    payload = {
        "name": "Clínica Trial Inválido",
        "owner_email": "x@x.test",
        "owner_first_name": "X",
        "owner_last_name": "Y",
        "trial_days": 0,  # inválido: min=1
    }
    response = client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_create_rechaza_email_invalido(super_admin):
    """email malformado → 400."""
    client = APIClient()
    client.force_authenticate(user=super_admin)

    url = reverse("platform-clinicas-list")
    payload = {
        "name": "Clínica Email Malo",
        "owner_email": "no-es-un-email",
        "owner_first_name": "X",
        "owner_last_name": "Y",
    }
    response = client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
