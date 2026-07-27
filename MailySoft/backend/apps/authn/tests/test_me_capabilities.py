"""
Tests de `capabilities` en GET /me/ — lo que el frontend usa para ocultar.

`/me/` es la única llamada que el frontend hace antes de pintar el menú, así que
los entitlements viajan aquí y no en un endpoint aparte: pedirlos por separado
haría parpadear módulos que la clínica no tiene.

Ambas capas leen de `apps/tenancy/entitlements.py`. Si divergieran, el usuario
vería un botón que al presionarlo da 404.

Patrón: AAA. factory_boy. Fixtures: db.
"""

from typing import Any

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.modules import Module
from apps.personal.services import doctor_create
from tests.factories import PlanFactory, TenantFactory, TenantMembershipFactory

_CLINICO = [Module.AGENDA, Module.EXPEDIENTE, Module.RECETAS, Module.NOTAS]


def _me(modules: list[str], *, role: str = "owner", **plan_kwargs: Any) -> dict:
    """GET /me/ como miembro de una clínica con esos módulos."""
    tenant = TenantFactory(plan=PlanFactory(modules=modules, **plan_kwargs))
    membership = TenantMembershipFactory(tenant=tenant, role=role)
    client = APIClient()
    client.force_authenticate(user=membership.user)
    response = client.get(reverse("me"))
    assert response.status_code == status.HTTP_200_OK
    return response.data


@pytest.mark.django_db
class TestCapabilities:
    def test_devuelve_los_modulos_contratados(self) -> None:
        data = _me(_CLINICO)

        assert set(data["capabilities"]["modules"]) == set(_CLINICO)

    def test_no_incluye_lo_que_el_plan_no_trae(self) -> None:
        data = _me(_CLINICO)

        assert Module.COBRANZA not in data["capabilities"]["modules"]
        assert Module.CFDI not in data["capabilities"]["modules"]

    def test_los_roles_vienen_derivados(self) -> None:
        """Sin cobranza no se ofrece el rol finanzas al invitar a alguien."""
        data = _me(_CLINICO)

        assert "finance" not in data["capabilities"]["roles"]
        assert "doctor" in data["capabilities"]["roles"]

    def test_expone_los_limites(self) -> None:
        data = _me(_CLINICO, max_sucursales=1, max_consultorios=3, max_usuarios=5)

        caps = data["capabilities"]
        assert caps["max_sucursales"] == 1
        assert caps["max_consultorios"] == 3
        assert caps["max_usuarios"] == 5

    def test_sede_unica_cuando_el_limite_es_uno(self) -> None:
        """Con esto el frontend esconde TODA la UI de sucursales."""
        data = _me(_CLINICO, max_sucursales=1)

        assert data["capabilities"]["sede_unica"] is True

    def test_limite_nulo_es_ilimitado(self) -> None:
        data = _me(_CLINICO, max_sucursales=None)

        assert data["capabilities"]["max_sucursales"] is None
        assert data["capabilities"]["sede_unica"] is False

    def test_incluye_el_nombre_del_plan(self) -> None:
        data = _me(_CLINICO)

        assert data["capabilities"]["plan_name"]


@pytest.mark.django_db
class TestDoctorIdDelDuenoMedico:
    """Regresión: el dueño que ejerce debe recibir su doctor_id.

    Antes `/me/` solo lo resolvía si el rol era exactamente 'doctor', así que el
    dueño de un consultorio individual —que ES el médico— no lo recibía y el
    frontend creía que no podía recetar.
    """

    def test_dueno_con_perfil_medico_recibe_doctor_id(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO))
        membership = TenantMembershipFactory(tenant=tenant, role="owner")
        doctor = doctor_create(
            tenant=tenant,
            user=membership.user,
            membership=membership,
            cedula_profesional="1234567",
        )
        client = APIClient()
        client.force_authenticate(user=membership.user)

        data = client.get(reverse("me")).data

        assert data["doctor_id"] == str(doctor.id)

    def test_admin_con_perfil_medico_recibe_doctor_id(self) -> None:
        tenant = TenantFactory(plan=PlanFactory(modules=_CLINICO))
        membership = TenantMembershipFactory(tenant=tenant, role="admin")
        doctor = doctor_create(
            tenant=tenant,
            user=membership.user,
            membership=membership,
            cedula_profesional="7654321",
        )
        client = APIClient()
        client.force_authenticate(user=membership.user)

        data = client.get(reverse("me")).data

        assert data["doctor_id"] == str(doctor.id)

    def test_recepcion_no_recibe_doctor_id(self) -> None:
        """Recepción no puede ejercer: no debe tener perfil de médico."""
        data = _me(_CLINICO, role="reception")

        assert data["doctor_id"] is None
