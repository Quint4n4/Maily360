"""
Tests de regresión de seguridad — cierre del clúster F (apps.tenancy nunca
supo de sucursales). Ver docs/design/sucursales-hallazgos-seguridad.md.

Exploits reales verificados y cerrados (status 200 antes del fix):
    1. Auto-promoción: un admin acotado a una sede se PATCHeaba a sí mismo a
       owner (PATCH /miembros/<su_membership_id>/ {"role":"owner"}) y ganaba
       TODAS las sedes, anulando el modelo de sucursales.
    2. Toma de cuenta: ese mismo admin cambiaba la contraseña del DUEÑO
       (PATCH /miembros/<membership_del_owner>/ {"password":...}) y entraba
       como él.
    3. Fuga de lectura: GET /miembros/ (membership_list()) no filtraba por
       sede — un admin de sucursal veía a TODO el personal de la clínica.

Reglas de negocio del dueño cubiertas:
    D1. Lista de equipo filtrada por la sede ACTIVA del selector; los owner
        SIEMPRE aparecen (para un viewer OWNER); un miembro sin sede
        asignada aparece en la sede default.
    D2. Un admin de sucursal solo gestiona al personal de SUS sedes; nunca
        crea ni asciende a nadie a owner; nunca modifica a un owner; el
        personal que da de alta cae en SU sede, nunca en la default ajena.
    D3. El owner puede resetear la contraseña de cualquiera, incluido otro
        owner. El admin solo a personal de su sede que no sea owner.
    D4. Jerarquía de roles (decisión del dueño 2026-07-16 —
        `TenantMembership.operational_roles()`): la regla D2 se AMPLÍA de
        "nunca un owner" a "nunca un owner NI un admin". Un viewer/actor NO
        owner nunca VE (en la lista) ni puede TOCAR (detalle/PATCH/avatar) a
        otro owner ni a otro admin — solo a personal operacional, más a sí
        mismo en el listado. El detalle/PATCH/avatar de un owner o admin
        ajeno responde 404 (defensa en profundidad — `_member_get_or_404`
        corta antes de llegar al service), no 400: no se revela que el
        recurso existe. Esto CAMBIA el status code esperado de los exploits
        #2 y #3 (antes 400 por validación de negocio, ahora 404 por scope).

Patrón: AAA. Mismo helper `_api_tenant_ctx` que
apps/agenda/tests/test_sucursal_scoping.py y
apps/personal/tests/test_sucursal_filtering.py: NO se mockea
`resolve_membership_for_user` (corre real, vía BD) — solo se parchea
`get_current_tenant` donde el flujo lo necesita (thread-local del
TenantManager + `apps.clinica.sucursal_scope`).
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.clinica.models import MembershipSucursal
from apps.tenancy.models import TenantMembership
from apps.tenancy.services import member_create
from tests.factories import (
    MembershipSucursalFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

User = get_user_model()

LIST_URL = "/api/v1/miembros/"

_STRONG_PASSWORD = "Maily2026$Segura"


def _detail_url(membership_id: Any) -> str:
    return f"/api/v1/miembros/{membership_id}/"


@contextmanager
def _api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Inyecta el tenant en el middleware/TenantManager para tests HTTP.

    Parchea `get_current_tenant` en los módulos que lo necesitan: las vistas
    de tenancy, su selector, `apps.clinica.sucursal_scope` (scoping por
    sucursal) y el manager tenant-aware. `resolve_membership_for_user`
    (apps.core.views) corre SIN mockear — resuelve la membresía real del
    actor vía BD, igual que en producción.
    """
    with (
        patch("apps.tenancy.views.get_current_tenant", return_value=tenant),
        patch("apps.tenancy.selectors.get_current_tenant", return_value=tenant),
        patch("apps.clinica.sucursal_scope.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _member(tenant: Any, role: str) -> Any:
    """Crea un user con TenantMembership real activa en `tenant`."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _membership_of(user: Any, tenant: Any) -> TenantMembership:
    return TenantMembership.objects.get(user=user, tenant=tenant)


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _two_sucursales(tenant: Any) -> "tuple[Any, Any]":
    """Centro (sede default) + Norte."""
    centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
    norte = SucursalFactory(tenant=tenant, name="Norte", is_default=False)
    return centro, norte


# ===========================================================================
# Exploit #1 — auto-promoción a owner
# ===========================================================================


class TestAutoPromotionBlocked:
    def test_admin_de_norte_no_puede_auto_promoverse_a_owner(self, db: None) -> None:
        """PATCH a la propia membresía con role=owner debe rechazarse.

        D4 (jerarquía de roles, 2026-07-16): el rol propio del admin
        ("admin") ya NO es operacional, así que `_member_get_or_404` corta
        con 404 ANTES de llegar al service — defensa en profundidad, ya no
        un 400 de validación de negocio.
        """
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        _member(tenant, "owner")
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)
        client = _auth_client(admin_user)

        # Act
        with _api_tenant_ctx(tenant):
            response = client.patch(
                _detail_url(admin_membership.id), data={"role": "owner"}, format="json"
            )

        # Assert
        assert response.status_code == 404, (
            f"Auto-promoción a owner debió rechazarse (404, D4), obtuvo "
            f"{response.status_code}: {response.data}"
        )
        admin_membership.refresh_from_db()
        assert admin_membership.role == "admin", "El rol NO debió cambiar tras el intento."


# ===========================================================================
# Exploit #2 — toma de cuenta del dueño
# ===========================================================================


class TestOwnerAccountTakeoverBlocked:
    def test_admin_de_norte_no_puede_resetear_password_del_owner(self, db: None) -> None:
        """PATCH a la membresía del owner con password nuevo debe rechazarse.

        D4 (jerarquía de roles, 2026-07-16): el rol del target ("owner") no
        es operacional, así que `_member_get_or_404` corta con 404 ANTES de
        llegar al service — defensa en profundidad, ya no un 400.
        """
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        owner_user = _member(tenant, "owner")
        owner_user.set_password("PasswordOriginalDelDueno1$")
        owner_user.save()
        owner_membership = _membership_of(owner_user, tenant)

        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)
        client = _auth_client(admin_user)

        # Act
        with _api_tenant_ctx(tenant):
            response = client.patch(
                _detail_url(owner_membership.id),
                data={"password": "PasswordMaliciosaDelAdmin1$"},
                format="json",
            )

        # Assert
        assert response.status_code == 404, (
            f"Reset de contraseña del owner por un admin debió rechazarse (404, D4), obtuvo "
            f"{response.status_code}: {response.data}"
        )
        owner_user.refresh_from_db()
        assert owner_user.check_password(
            "PasswordOriginalDelDueno1$"
        ), "La contraseña del owner NO debió cambiar."
        assert not owner_user.check_password("PasswordMaliciosaDelAdmin1$")


# ===========================================================================
# Admin no puede modificar a un owner de NINGUNA forma (D2)
# ===========================================================================


class TestAdminCannotModifyOwner:
    @pytest.mark.parametrize(
        "payload",
        [
            {"role": "reception"},
            {"first_name": "Hackeado"},
            {"blocked": True},
        ],
        ids=["role", "first_name", "blocked"],
    )
    def test_admin_de_norte_no_puede_modificar_a_un_owner(
        self, db: None, payload: "dict[str, Any]"
    ) -> None:
        """D4 (jerarquía de roles, 2026-07-16): el target ("owner") no es
        operacional → `_member_get_or_404` corta con 404, ya no 400.
        """
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        owner_user = _member(tenant, "owner")
        owner_membership = _membership_of(owner_user, tenant)

        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)
        client = _auth_client(admin_user)

        # Act
        with _api_tenant_ctx(tenant):
            response = client.patch(_detail_url(owner_membership.id), data=payload, format="json")

        # Assert
        assert response.status_code == 404, (
            f"Modificar a un owner (payload={payload}) debió rechazarse (404, D4), obtuvo "
            f"{response.status_code}: {response.data}"
        )
        owner_membership.refresh_from_db()
        assert owner_membership.role == "owner"


# ===========================================================================
# Admin no puede crear un miembro owner (D2, anti-escalada)
# ===========================================================================


class TestAdminCannotCreateOwner:
    def test_admin_de_norte_no_puede_crear_miembro_con_rol_owner(self, db: None) -> None:
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)
        client = _auth_client(admin_user)

        payload = {
            "email": "intento-owner@clinic.test",
            "first_name": "Intento",
            "last_name": "De Escalada",
            "password": _STRONG_PASSWORD,
            "role": "owner",
        }

        # Act
        with _api_tenant_ctx(tenant):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400, (
            f"Crear un miembro owner debió rechazarse, obtuvo {response.status_code}: "
            f"{response.data}"
        )
        assert not User.objects.filter(email=payload["email"]).exists()


# ===========================================================================
# D4 — jerarquía de roles: admin no puede crear OTRO admin, sí personal
# operacional (decisión del dueño 2026-07-16)
# ===========================================================================


class TestAdminCannotCreateAdmin:
    def test_admin_de_norte_no_puede_crear_miembro_con_rol_admin(self, db: None) -> None:
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)
        client = _auth_client(admin_user)

        payload = {
            "email": "intento-admin@clinic.test",
            "first_name": "Intento",
            "last_name": "De Escalada",
            "password": _STRONG_PASSWORD,
            "role": "admin",
        }

        # Act
        with _api_tenant_ctx(tenant):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 400, (
            f"Crear un miembro admin debió rechazarse, obtuvo {response.status_code}: "
            f"{response.data}"
        )
        assert not User.objects.filter(email=payload["email"]).exists()


class TestAdminCanCreateOperationalRole:
    def test_admin_de_norte_puede_crear_miembro_con_rol_operacional_y_queda_en_norte(
        self, db: None
    ) -> None:
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)
        client = _auth_client(admin_user)

        payload = {
            "email": "nuevo-doctor@clinic.test",
            "first_name": "Nuevo",
            "last_name": "Doctor",
            "password": _STRONG_PASSWORD,
            "role": "doctor",
        }

        # Act
        with _api_tenant_ctx(tenant):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201, response.data
        assert response.json()["role"] == "doctor"
        new_membership_id = response.json()["id"]
        assigned_ids = set(
            MembershipSucursal.all_objects.filter(membership_id=new_membership_id).values_list(
                "sucursal_id", flat=True
            )
        )
        assert assigned_ids == {norte.id}, (
            "El nuevo miembro (rol operacional) debió quedar asignado a la sede del admin "
            f"que lo creó (Norte). Asignado: {assigned_ids}."
        )


# ===========================================================================
# Fuga de lectura — GET /miembros/ filtrado por sede (D1)
# ===========================================================================


class TestListFilteredBySucursal:
    def test_admin_de_norte_no_ve_owners_ni_otros_admins_pero_se_ve_a_si_mismo_y_a_operativos(
        self, db: None
    ) -> None:
        """D4 (jerarquía de roles, 2026-07-16): un admin de sucursal NUNCA ve
        a un owner ni a OTRO admin en el listado — ni siquiera de su propia
        sede. Sí ve a personal operacional de sus sedes y siempre se ve a
        sí mismo (aunque su propio rol "admin" no sea operacional).

        Reemplaza el comportamiento previo (D1 "el owner SIEMPRE aparece"),
        que aplicaba sin distinguir el rol del viewer — el dueño reportó
        que esto era un error: un admin de sucursal no debía ver a los
        dueños del negocio.
        """
        # Arrange
        tenant = TenantFactory()
        centro, norte = _two_sucursales(tenant)
        owner_user = _member(tenant, "owner")
        owner_membership = _membership_of(owner_user, tenant)

        admin_norte_user = _member(tenant, "admin")
        admin_norte_membership = _membership_of(admin_norte_user, tenant)
        MembershipSucursalFactory(membership=admin_norte_membership, sucursal=norte)

        otro_admin_norte_user = _member(tenant, "admin")
        otro_admin_norte_membership = _membership_of(otro_admin_norte_user, tenant)
        MembershipSucursalFactory(membership=otro_admin_norte_membership, sucursal=norte)

        doctor_norte_user = _member(tenant, "doctor")
        doctor_norte_membership = _membership_of(doctor_norte_user, tenant)
        MembershipSucursalFactory(membership=doctor_norte_membership, sucursal=norte)

        recep_centro_user = _member(tenant, "reception")
        recep_centro_membership = _membership_of(recep_centro_user, tenant)
        MembershipSucursalFactory(membership=recep_centro_membership, sucursal=centro)

        client = _auth_client(admin_norte_user)

        # Act — sin header: alcance parcial del admin (solo Norte)
        with _api_tenant_ctx(tenant):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200
        ids = {item["id"] for item in response.json()}
        assert str(admin_norte_membership.id) in ids, "El admin debe verse a sí mismo."
        assert (
            str(doctor_norte_membership.id) in ids
        ), "Debe ver a personal operacional (doctor/enfermería) de su sede."
        assert (
            str(owner_membership.id) not in ids
        ), "D4: un admin de sucursal NUNCA debe ver a un owner."
        assert str(otro_admin_norte_membership.id) not in ids, (
            "D4: un admin de sucursal NUNCA debe ver a OTRO admin, ni siquiera de su "
            "propia sede."
        )
        assert (
            str(recep_centro_membership.id) not in ids
        ), "BUG CRÍTICO: fuga de lectura — el admin de Norte vio personal de Centro."

    def test_miembro_sin_sede_aparece_en_default_no_en_otras(self, db: None) -> None:
        # Arrange
        tenant = TenantFactory()
        centro, norte = _two_sucursales(tenant)  # centro es la sede default
        owner_user = _member(tenant, "owner")
        sin_sede_user = _member(tenant, "reception")  # sin ninguna MembershipSucursal
        sin_sede_membership = _membership_of(sin_sede_user, tenant)
        client = _auth_client(owner_user)

        # Act — header Centro (default)
        with _api_tenant_ctx(tenant):
            resp_centro = client.get(LIST_URL, headers={"X-Sucursal-Id": str(centro.id)})
        # Act — header Norte
        with _api_tenant_ctx(tenant):
            resp_norte = client.get(LIST_URL, headers={"X-Sucursal-Id": str(norte.id)})

        # Assert
        ids_centro = {item["id"] for item in resp_centro.json()}
        ids_norte = {item["id"] for item in resp_norte.json()}
        assert (
            str(sin_sede_membership.id) in ids_centro
        ), "Un miembro sin sede asignada debe aparecer en la sede default."
        assert (
            str(sin_sede_membership.id) not in ids_norte
        ), "Un miembro sin sede asignada NO debe aparecer en una sede que no es la default."

    def test_owner_sin_header_ve_a_todos_y_con_header_ve_solo_esa_sede(self, db: None) -> None:
        # Arrange
        tenant = TenantFactory()
        centro, norte = _two_sucursales(tenant)
        owner_user = _member(tenant, "owner")
        owner_membership = _membership_of(owner_user, tenant)

        recep_centro_user = _member(tenant, "reception")
        recep_centro_membership = _membership_of(recep_centro_user, tenant)
        MembershipSucursalFactory(membership=recep_centro_membership, sucursal=centro)

        recep_norte_user = _member(tenant, "reception")
        recep_norte_membership = _membership_of(recep_norte_user, tenant)
        MembershipSucursalFactory(membership=recep_norte_membership, sucursal=norte)

        client = _auth_client(owner_user)

        # Act — "Todas" (sin header)
        with _api_tenant_ctx(tenant):
            resp_all = client.get(LIST_URL)
        # Act — header Centro
        with _api_tenant_ctx(tenant):
            resp_centro = client.get(LIST_URL, headers={"X-Sucursal-Id": str(centro.id)})

        # Assert — sin header: ve a todos
        ids_all = {item["id"] for item in resp_all.json()}
        assert {
            str(owner_membership.id),
            str(recep_centro_membership.id),
            str(recep_norte_membership.id),
        } <= ids_all

        # Assert — header Centro: solo Centro (+ owner)
        ids_centro = {item["id"] for item in resp_centro.json()}
        assert str(recep_centro_membership.id) in ids_centro
        assert str(recep_norte_membership.id) not in ids_centro
        assert str(owner_membership.id) in ids_centro, "El owner SIEMPRE debe aparecer (D1)."


# ===========================================================================
# Alta de personal cae en la sede del actor (D2)
# ===========================================================================


class TestMemberCreateAssignsActorSucursal:
    def test_miembro_creado_por_admin_de_norte_queda_asignado_a_norte(self, db: None) -> None:
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)
        client = _auth_client(admin_user)

        payload = {
            "email": "nueva-recepcion@clinic.test",
            "first_name": "Nueva",
            "last_name": "Recepcionista",
            "password": _STRONG_PASSWORD,
            "role": "reception",
        }

        # Act — SIN header de sede activa
        with _api_tenant_ctx(tenant):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201, response.data
        new_membership_id = response.json()["id"]
        assigned_ids = set(
            MembershipSucursal.all_objects.filter(membership_id=new_membership_id).values_list(
                "sucursal_id", flat=True
            )
        )
        assert assigned_ids == {norte.id}, (
            "El nuevo miembro debió quedar asignado a la sede del admin que lo creó "
            f"(Norte), no a la default ni a ninguna otra. Asignado: {assigned_ids}."
        )


# ===========================================================================
# Controles positivos — no romper la operación normal
# ===========================================================================


class TestPositiveOperationsStillWork:
    def test_admin_de_norte_puede_cambiar_rol_y_password_de_recepcionista_de_norte(
        self, db: None
    ) -> None:
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)

        recep_user = _member(tenant, "reception")
        recep_membership = _membership_of(recep_user, tenant)
        MembershipSucursalFactory(membership=recep_membership, sucursal=norte)
        client = _auth_client(admin_user)

        # Act
        with _api_tenant_ctx(tenant):
            response = client.patch(
                _detail_url(recep_membership.id),
                data={"role": "nurse", "password": "NuevaPasswordDeRecepcion1$"},
                format="json",
            )

        # Assert
        assert response.status_code == 200, response.data
        recep_membership.refresh_from_db()
        assert recep_membership.role == "nurse"
        recep_user.refresh_from_db()
        assert recep_user.check_password("NuevaPasswordDeRecepcion1$")

    def test_owner_puede_resetear_password_de_otro_owner(self, db: None) -> None:
        """D3: el owner puede resetear la contraseña de CUALQUIERA, incluido otro owner."""
        # Arrange
        tenant = TenantFactory()
        owner_a_user = _member(tenant, "owner")
        owner_b_user = _member(tenant, "owner")
        owner_b_user.set_password("PasswordOriginalDeOwnerB1$")
        owner_b_user.save()
        owner_b_membership = _membership_of(owner_b_user, tenant)
        client = _auth_client(owner_a_user)

        # Act
        with _api_tenant_ctx(tenant):
            response = client.patch(
                _detail_url(owner_b_membership.id),
                data={"password": "NuevaPasswordDeOwnerB1$"},
                format="json",
            )

        # Assert
        assert response.status_code == 200, response.data
        owner_b_user.refresh_from_db()
        assert owner_b_user.check_password("NuevaPasswordDeOwnerB1$")


# ===========================================================================
# D4 — jerarquía de roles: admin no puede tocar a OTRO admin (2026-07-16)
# ===========================================================================


class TestAdminCannotModifyOtherAdmin:
    """Un admin de sucursal recibe el MISMO trato que con un owner frente a
    otro admin: 404 (defensa en profundidad), ni siquiera de su propia sede.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            {"role": "reception"},
            {"first_name": "Hackeado"},
            {"blocked": True},
        ],
        ids=["role", "first_name", "blocked"],
    )
    def test_admin_de_norte_no_puede_modificar_a_otro_admin_de_su_sede(
        self, db: None, payload: "dict[str, Any]"
    ) -> None:
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        admin_a_user = _member(tenant, "admin")
        admin_a_membership = _membership_of(admin_a_user, tenant)
        MembershipSucursalFactory(membership=admin_a_membership, sucursal=norte)

        admin_b_user = _member(tenant, "admin")
        admin_b_membership = _membership_of(admin_b_user, tenant)
        MembershipSucursalFactory(membership=admin_b_membership, sucursal=norte)

        client = _auth_client(admin_a_user)

        # Act
        with _api_tenant_ctx(tenant):
            response = client.patch(_detail_url(admin_b_membership.id), data=payload, format="json")

        # Assert
        assert response.status_code == 404, (
            f"Modificar a OTRO admin de la misma sede (payload={payload}) debió "
            f"rechazarse (404, D4), obtuvo {response.status_code}: {response.data}"
        )
        admin_b_membership.refresh_from_db()
        assert admin_b_membership.role == "admin", "El rol NO debió cambiar."


# ===========================================================================
# D4 — controles positivos: la gestión de personal OPERACIONAL sigue
# funcionando, y la anti-escalada bloquea el ASCENSO a admin (2026-07-16)
# ===========================================================================


class TestAdminOperationalWriteStillWorks:
    def test_admin_de_norte_puede_editar_a_un_doctor_de_su_sede(self, db: None) -> None:
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)

        doctor_user = _member(tenant, "doctor")
        doctor_membership = _membership_of(doctor_user, tenant)
        MembershipSucursalFactory(membership=doctor_membership, sucursal=norte)
        client = _auth_client(admin_user)

        # Act — cambia nombre, rol operacional y contraseña en un solo PATCH
        with _api_tenant_ctx(tenant):
            response = client.patch(
                _detail_url(doctor_membership.id),
                data={
                    "first_name": "Actualizado",
                    "role": "nurse",
                    "password": "NuevaPasswordDeDoctor1$",
                },
                format="json",
            )

        # Assert
        assert response.status_code == 200, response.data
        doctor_membership.refresh_from_db()
        assert doctor_membership.role == "nurse"
        assert doctor_membership.user.first_name == "Actualizado"
        doctor_user.refresh_from_db()
        assert doctor_user.check_password("NuevaPasswordDeDoctor1$")

    def test_admin_de_norte_no_puede_ascender_a_un_doctor_de_su_sede_a_admin(
        self, db: None
    ) -> None:
        """La anti-escalada (`_ensure_role_grantable`) cubre el ASCENSO, no
        solo la creación: el target sigue siendo operacional (doctor, por
        eso no da 404), pero el ROL PEDIDO ("admin") no lo es.
        """
        # Arrange
        tenant = TenantFactory()
        _centro, norte = _two_sucursales(tenant)
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        MembershipSucursalFactory(membership=admin_membership, sucursal=norte)

        doctor_user = _member(tenant, "doctor")
        doctor_membership = _membership_of(doctor_user, tenant)
        MembershipSucursalFactory(membership=doctor_membership, sucursal=norte)
        client = _auth_client(admin_user)

        # Act
        with _api_tenant_ctx(tenant):
            response = client.patch(
                _detail_url(doctor_membership.id), data={"role": "admin"}, format="json"
            )

        # Assert
        assert response.status_code == 400, (
            f"Ascender a un doctor a admin debió rechazarse, obtuvo {response.status_code}: "
            f"{response.data}"
        )
        doctor_membership.refresh_from_db()
        assert doctor_membership.role == "doctor", "El rol NO debió cambiar."


# ===========================================================================
# D4 — regresión del OWNER: sin restricciones nuevas, sigue viendo/
# gestionando a cualquiera (incluidos admins y otros owners) y sigue
# pudiendo crear un admin (2026-07-16)
# ===========================================================================


class TestOwnerHierarchyRegression:
    def test_owner_ve_y_puede_editar_a_un_admin(self, db: None) -> None:
        # Arrange
        tenant = TenantFactory()
        owner_user = _member(tenant, "owner")
        admin_user = _member(tenant, "admin")
        admin_membership = _membership_of(admin_user, tenant)
        client = _auth_client(owner_user)

        # Act — lo ve en la lista
        with _api_tenant_ctx(tenant):
            list_response = client.get(LIST_URL)
        # Act — lo edita
        with _api_tenant_ctx(tenant):
            patch_response = client.patch(
                _detail_url(admin_membership.id),
                data={"first_name": "Editado"},
                format="json",
            )

        # Assert
        assert list_response.status_code == 200
        ids = {item["id"] for item in list_response.json()}
        assert str(admin_membership.id) in ids, "El owner debe seguir viendo a los admins."
        assert patch_response.status_code == 200, patch_response.data
        admin_membership.refresh_from_db()
        assert admin_membership.user.first_name == "Editado"

    def test_owner_puede_crear_un_admin(self, db: None) -> None:
        # Arrange
        tenant = TenantFactory()
        owner_user = _member(tenant, "owner")
        client = _auth_client(owner_user)

        payload = {
            "email": "nuevo-admin@clinic.test",
            "first_name": "Nuevo",
            "last_name": "Admin",
            "password": _STRONG_PASSWORD,
            "role": "admin",
        }

        # Act
        with _api_tenant_ctx(tenant):
            response = client.post(LIST_URL, data=payload, format="json")

        # Assert
        assert response.status_code == 201, response.data
        assert response.json()["role"] == "admin"


# ===========================================================================
# Bootstrap del primer owner de un tenant nuevo (hallazgo durante la
# implementación — apps.plataforma.services.tenant_and_owner_create llama a
# member_create con un actor de PLATAFORMA que nunca tiene TenantMembership
# propia). Cierra la excepción exacta que debe permitirse sin abrir una
# puerta alterna para crear miembros sin membresía.
# ===========================================================================


class TestMemberCreateBootstrap:
    def test_actor_sin_membresia_puede_crear_al_primer_owner_de_un_tenant_vacio(
        self, db: None
    ) -> None:
        # Arrange — actor de plataforma, SIN ninguna TenantMembership
        tenant = TenantFactory()
        platform_actor = UserFactory(is_platform_staff=True)
        assert not TenantMembership.objects.filter(tenant=tenant).exists()

        # Act — no debe lanzar
        membership = member_create(
            tenant=tenant,
            actor=platform_actor,
            email="primer-owner@clinic.test",
            first_name="Primer",
            last_name="Dueño",
            password=_STRONG_PASSWORD,
            role="owner",
        )

        # Assert
        assert membership.role == "owner"
        assert membership.tenant_id == tenant.id

    def test_actor_sin_membresia_no_puede_crear_un_no_owner_en_tenant_vacio(self, db: None) -> None:
        """El bootstrap SOLO cubre el alta del primer OWNER, no cualquier rol."""
        # Arrange
        tenant = TenantFactory()
        platform_actor = UserFactory(is_platform_staff=True)

        # Act / Assert
        with pytest.raises(ValidationError):
            member_create(
                tenant=tenant,
                actor=platform_actor,
                email="no-deberia-crearse@clinic.test",
                first_name="Intento",
                last_name="Sin Membresía",
                password=_STRONG_PASSWORD,
                role="reception",
            )

    def test_actor_sin_membresia_no_puede_crear_miembros_si_el_tenant_ya_tiene_equipo(
        self, db: None
    ) -> None:
        """El bootstrap SOLO aplica cuando el tenant AÚN no tiene ningún miembro."""
        # Arrange — el tenant YA tiene un owner (ya no es un alta "en frío")
        tenant = TenantFactory()
        _member(tenant, "owner")
        platform_actor = UserFactory(is_platform_staff=True)

        # Act / Assert
        with pytest.raises(ValidationError):
            member_create(
                tenant=tenant,
                actor=platform_actor,
                email="intruso@clinic.test",
                first_name="Actor",
                last_name="Ajeno",
                password=_STRONG_PASSWORD,
                role="owner",
            )
