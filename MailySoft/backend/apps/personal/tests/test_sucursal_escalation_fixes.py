"""
Tests de cierre de hueco de seguridad — multi-sede, apps/personal.

Reproduce y verifica el arreglo de los hallazgos de
docs/design/sucursales-hallazgos-seguridad.md que le tocan a esta app:

- A5: consultorios — crear con `sucursal_id` de otra sede (ATAQUE3), y
  PATCH/DELETE de un consultorio de otra sede por id.
- A4: horarios (DoctorSchedule) — DELETE de un horario de otra sede por id.
- Clúster C: `doctor_set_sucursales` — un admin acotado a una sede ya no
  puede otorgar NI quitar el acceso de un médico a una sede fuera de su
  propio alcance (ATAQUE4).

Patrón: AAA. Mismo helper `_api_tenant_ctx` que
apps/personal/tests/test_sucursal_filtering.py (cada archivo de test define
su propia copia por convención del proyecto).
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.personal.services import doctor_set_consultorios, doctor_set_sucursales
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ConsultorioFactory,
    DoctorFactory,
    DoctorScheduleFactory,
    MembershipSucursalFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

CONSULTORIOS_URL = "/api/v1/personal/consultorios/"


def _consultorio_detail_url(consultorio_id: Any) -> str:
    return f"/api/v1/personal/consultorios/{consultorio_id}/"


def _schedule_detail_url(schedule_id: Any) -> str:
    return f"/api/v1/personal/horarios/{schedule_id}/"


def _doctor_detail_url(doctor_id: Any) -> str:
    return f"/api/v1/personal/doctores/{doctor_id}/"


@contextmanager
def _api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Inyecta tenant en el middleware/TenantManager para tests HTTP.

    Parchea get_current_tenant en TODOS los módulos que lo llaman
    directamente para este flujo (mismo patrón que test_sucursal_filtering.py
    y test_apis.py).
    """
    with (
        patch("apps.personal.views.get_current_tenant", return_value=tenant),
        patch("apps.clinica.sucursal_scope.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _admin_de_centro(tenant: Any, centro: Any) -> Any:
    """Crea un admin acotado ÚNICAMENTE a la sucursal `centro` (vía MembershipSucursal)."""
    user = UserFactory()
    membership = TenantMembershipFactory(
        user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
    )
    MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ===========================================================================
# A5 — Consultorios: crear con sucursal_id de otra sede (ATAQUE3)
# ===========================================================================


class TestConsultorioCreateCrossSucursalRejected:
    def test_admin_centro_no_puede_crear_consultorio_en_norte(self, db: Any) -> None:
        """Antes del fix: sucursal_get solo validaba tenant, no el alcance del
        actor, así que un admin de Centro podía crear un consultorio en Norte
        mandando el sucursal_id explícito de Norte (ATAQUE3)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.post(
                CONSULTORIOS_URL,
                {"name": "Intruso", "sucursal_id": str(norte.id)},
                format="json",
            )

        assert resp.status_code == 400, resp.content
        from apps.personal.models import Consultorio

        assert not Consultorio.all_objects.filter(tenant=tenant, name="Intruso").exists()

    def test_admin_centro_puede_crear_consultorio_en_su_propia_sede(self, db: Any) -> None:
        """Camino feliz: crear con el sucursal_id de la sede propia SÍ funciona."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        SucursalFactory(tenant=tenant, name="Norte")
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.post(
                CONSULTORIOS_URL,
                {"name": "Sala Centro Nueva", "sucursal_id": str(centro.id)},
                format="json",
            )

        assert resp.status_code == 201, resp.content
        assert resp.json()["sucursal"]["id"] == str(centro.id)


# ===========================================================================
# A5 — Consultorios: PATCH/DELETE de un consultorio de otra sede por id
# ===========================================================================


class TestConsultorioDetailCrossSucursal404:
    def test_admin_centro_patch_consultorio_de_norte_404(self, db: Any) -> None:
        """Antes del fix: _get_consultorio_or_404 no acotaba por sede (solo por
        tenant vía consultorio_get) y el PATCH de un consultorio de Norte
        pasaba con 200, incluso reasignándolo (ATAQUE3)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte, name="Sala Norte")
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.patch(
                _consultorio_detail_url(consultorio_norte.id),
                {"location": "Reasignado por intruso"},
                format="json",
            )

        assert resp.status_code == 404, resp.content
        consultorio_norte.refresh_from_db()
        assert consultorio_norte.location == ""

    def test_admin_centro_delete_consultorio_de_norte_404(self, db: Any) -> None:
        """Antes del fix: DELETE de un consultorio de Norte desactivaba el
        registro (204) aunque el actor estuviera acotado a Centro."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte, is_active=True)
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.delete(_consultorio_detail_url(consultorio_norte.id))

        assert resp.status_code == 404, resp.content
        consultorio_norte.refresh_from_db()
        assert consultorio_norte.is_active is True

    def test_admin_centro_puede_patch_consultorio_de_su_propia_sede(self, db: Any) -> None:
        """Camino feliz: PATCH de un consultorio de Centro SÍ funciona."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.patch(
                _consultorio_detail_url(consultorio_centro.id),
                {"location": "Piso 2"},
                format="json",
            )

        assert resp.status_code == 200, resp.content
        assert resp.json()["location"] == "Piso 2"


# ===========================================================================
# A4 — Horarios: DELETE de un horario de otra sede por id
# ===========================================================================


class TestDoctorScheduleDeleteCrossSucursal404:
    def test_admin_centro_delete_horario_de_norte_404(self, db: Any) -> None:
        """Antes del fix: schedule_get (usado por DELETE) solo filtraba por
        tenant, no por sede, así que un admin de Centro podía borrar el
        horario de un médico en Norte con solo conocer el id."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)
        horario_norte = DoctorScheduleFactory(doctor=doctor, sucursal=norte, is_active=True)
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.delete(_schedule_detail_url(horario_norte.id))

        assert resp.status_code == 404, resp.content
        horario_norte.refresh_from_db()
        assert horario_norte.is_active is True

    def test_admin_centro_puede_borrar_horario_de_su_propia_sede(self, db: Any) -> None:
        """Camino feliz: DELETE de un horario de Centro SÍ funciona."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        doctor = DoctorFactory(tenant=tenant)
        horario_centro = DoctorScheduleFactory(doctor=doctor, sucursal=centro, is_active=True)
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.delete(_schedule_detail_url(horario_centro.id))

        assert resp.status_code == 204, resp.content
        horario_centro.refresh_from_db()
        assert horario_centro.is_active is False


# ===========================================================================
# Clúster C — doctor_set_sucursales: escalada de un admin acotado a una sede
# ===========================================================================


class TestDoctorSetSucursalesEscalation:
    """Antes del fix, doctor_set_sucursales no validaba allowed_sucursales del
    actor (a diferencia de membership_sucursales_set) — un admin de Centro
    reasignaba en qué sedes atiende CUALQUIER médico del tenant (ATAQUE4)."""

    def test_admin_centro_no_puede_otorgar_norte_a_un_medico(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)  # sin sucursales asignadas todavía
        admin = _admin_de_centro(tenant, centro)

        with pytest.raises(ValidationError, match="sedes"):
            doctor_set_sucursales(doctor=doctor, user=admin, sucursal_ids=[norte.id])

        assert not doctor.sucursales.filter(id=norte.id).exists()

    def test_admin_centro_no_puede_quitar_norte_de_un_medico(self, db: Any) -> None:
        """Reasignar (vaciar) las sedes de un médico que YA atiende en Norte
        también es escalada si el actor no tiene Norte."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)
        doctor.sucursales.add(norte)
        admin = _admin_de_centro(tenant, centro)

        with pytest.raises(ValidationError, match="sedes"):
            doctor_set_sucursales(doctor=doctor, user=admin, sucursal_ids=[])

        assert doctor.sucursales.filter(id=norte.id).exists()

    def test_admin_centro_puede_gestionar_centro(self, db: Any) -> None:
        """Camino feliz: un admin de Centro SÍ puede asignar un médico a Centro."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)
        admin = _admin_de_centro(tenant, centro)

        result = doctor_set_sucursales(doctor=doctor, user=admin, sucursal_ids=[centro.id])

        assert list(result.sucursales.values_list("id", flat=True)) == [centro.id]

    def test_owner_puede_otorgar_cualquier_sede(self, db: Any) -> None:
        """El owner no está sujeto a la restricción de allowed_sucursales."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)
        owner = UserFactory()
        TenantMembershipFactory(
            user=owner, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
        )

        result = doctor_set_sucursales(
            doctor=doctor, user=owner, sucursal_ids=[centro.id, norte.id]
        )

        assert set(result.sucursales.values_list("id", flat=True)) == {centro.id, norte.id}

    def test_admin_centro_no_puede_otorgar_norte_via_patch_doctor_api(self, db: Any) -> None:
        """Reproduce ATAQUE4 de punta a punta vía PATCH /doctores/<id>/, la
        ruta HTTP real que dispara doctor_set_sucursales."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.patch(
                _doctor_detail_url(doctor.id),
                {"sucursal_ids": [str(norte.id)]},
                format="json",
            )

        assert resp.status_code == 400, resp.content
        assert not doctor.sucursales.filter(id=norte.id).exists()


# ===========================================================================
# Clúster C (hermano) — doctor_set_consultorios: la MISMA escalada por sede,
# pero vía consultorio_ids (los consultorios son privados por sede — A5).
# ===========================================================================


class TestDoctorSetConsultoriosEscalation:
    """Antes del fix, doctor_set_consultorios validaba tenant + activo pero NO
    `allowed_sucursales` del actor — un admin de Centro podía asignar (o
    quitar) un consultorio de Norte a cualquier médico sin tener acceso a Norte."""

    def test_admin_centro_no_puede_asignar_consultorio_de_norte(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte, is_active=True)
        doctor = DoctorFactory(tenant=tenant)
        admin = _admin_de_centro(tenant, centro)

        with pytest.raises(ValidationError, match="consultorios"):
            doctor_set_consultorios(
                doctor=doctor, user=admin, consultorio_ids=[consultorio_norte.id]
            )

        assert not doctor.consultorios.filter(id=consultorio_norte.id).exists()

    def test_admin_centro_no_puede_quitar_consultorio_de_norte(self, db: Any) -> None:
        """Vaciar/reemplazar los consultorios de un médico que YA usa uno de
        Norte también es escalada si el actor no tiene Norte."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte, is_active=True)
        doctor = DoctorFactory(tenant=tenant)
        doctor.consultorios.add(consultorio_norte)
        admin = _admin_de_centro(tenant, centro)

        with pytest.raises(ValidationError, match="consultorios"):
            doctor_set_consultorios(doctor=doctor, user=admin, consultorio_ids=[])

        assert doctor.consultorios.filter(id=consultorio_norte.id).exists()

    def test_admin_centro_puede_asignar_consultorio_de_su_sede(self, db: Any) -> None:
        """Camino feliz: un admin de Centro SÍ puede asignar un consultorio de Centro."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        SucursalFactory(tenant=tenant, name="Norte")
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro, is_active=True)
        doctor = DoctorFactory(tenant=tenant)
        admin = _admin_de_centro(tenant, centro)

        result = doctor_set_consultorios(
            doctor=doctor, user=admin, consultorio_ids=[consultorio_centro.id]
        )

        assert list(result.consultorios.values_list("id", flat=True)) == [consultorio_centro.id]

    def test_owner_puede_asignar_consultorio_de_cualquier_sede(self, db: Any) -> None:
        """El owner no está sujeto a la restricción de allowed_sucursales."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte, is_active=True)
        doctor = DoctorFactory(tenant=tenant)
        owner = UserFactory()
        TenantMembershipFactory(
            user=owner, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
        )

        result = doctor_set_consultorios(
            doctor=doctor, user=owner, consultorio_ids=[consultorio_norte.id]
        )

        assert list(result.consultorios.values_list("id", flat=True)) == [consultorio_norte.id]

    def test_admin_centro_no_puede_asignar_norte_via_patch_doctor_api(self, db: Any) -> None:
        """De punta a punta vía PATCH /doctores/<id>/ con consultorio_ids."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro", is_default=True)
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte, is_active=True)
        doctor = DoctorFactory(tenant=tenant)
        admin = _admin_de_centro(tenant, centro)
        client = _auth_client(admin)

        with _api_tenant_ctx(tenant):
            resp = client.patch(
                _doctor_detail_url(doctor.id),
                {"consultorio_ids": [str(consultorio_norte.id)]},
                format="json",
            )

        assert resp.status_code == 400, resp.content
        assert not doctor.consultorios.filter(id=consultorio_norte.id).exists()
