"""
Tests de gating por plan a nivel de API — la prueba de que el backend manda.

Ocultar módulos en el frontend es cosmético: cualquiera con la URL entra. Estos
tests pegan a los endpoints reales con una clínica que NO tiene el módulo y
verifican que el backend responde 404.

Por qué 404 y no 403: un 403 diría "esto existe pero no lo pagas" — delata el
catálogo. Un módulo no contratado simplemente no existe para esa clínica. (El
403 sigue siendo correcto para el ROL: ahí el recurso sí existe para la clínica.)

Patrón: AAA. factory_boy. Fixtures: db.
"""

from typing import Any

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.modules import Module
from tests.factories import (
    PatientFactory,
    PlanFactory,
    TenantFactory,
    TenantMembershipFactory,
)

#: Plan "dental" del caso real: clínico sin recetas y sin nada comercial.
_DENTAL = [Module.AGENDA, Module.RECORDATORIOS, Module.EXPEDIENTE, Module.NOTAS]


def _cliente(modules: list[str]) -> tuple[APIClient, Any]:
    """Cliente autenticado como dueño de una clínica con esos módulos."""
    tenant = TenantFactory(plan=PlanFactory(modules=modules))
    membership = TenantMembershipFactory(tenant=tenant, role="owner")
    client = APIClient()
    client.force_authenticate(user=membership.user)
    return client, tenant


@pytest.mark.django_db
class TestModuloApagadoDevuelve404:
    """El caso dental: agenda y expediente sí, recetas y finanzas no."""

    def test_recetas_apagadas(self) -> None:
        client, tenant = _cliente(_DENTAL)
        paciente = PatientFactory(tenant=tenant)

        url = reverse("prescription-list-create", kwargs={"patient_id": paciente.id})

        assert client.get(url).status_code == status.HTTP_404_NOT_FOUND

    def test_cotizaciones_apagadas(self) -> None:
        client, _ = _cliente(_DENTAL)

        assert client.get(reverse("finanzas-quote-list")).status_code == (
            status.HTTP_404_NOT_FOUND
        )

    def test_cobranza_apagada(self) -> None:
        client, _ = _cliente(_DENTAL)

        assert client.get(reverse("finanzas-charge-list")).status_code == (
            status.HTTP_404_NOT_FOUND
        )

    def test_servicios_apagados(self) -> None:
        client, _ = _cliente(_DENTAL)

        assert client.get(reverse("finanzas-concept-list")).status_code == (
            status.HTTP_404_NOT_FOUND
        )


@pytest.mark.django_db
class TestModuloEncendidoSiPasa:
    """Lo contratado funciona igual que siempre."""

    def test_agenda_responde(self) -> None:
        client, _ = _cliente(_DENTAL)

        assert client.get(reverse("appointment-list-create")).status_code == (
            status.HTTP_200_OK
        )

    def test_recetas_con_el_modulo_encendido(self) -> None:
        client, tenant = _cliente([*_DENTAL, Module.RECETAS])
        paciente = PatientFactory(tenant=tenant)

        url = reverse("prescription-list-create", kwargs={"patient_id": paciente.id})

        assert client.get(url).status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestGranularidadDeFinanzas:
    """La app `finanzas` son CINCO módulos: el guard es por capacidad, no por app.

    Si se hubiera gateado por app de Django, apagar la cobranza habría apagado
    también el catálogo de servicios y las cotizaciones.
    """

    def test_servicios_y_cotizaciones_sin_cobranza(self) -> None:
        client, _ = _cliente(
            [*_DENTAL, Module.SERVICIOS, Module.COTIZACIONES]
        )

        assert client.get(reverse("finanzas-concept-list")).status_code == status.HTTP_200_OK
        assert client.get(reverse("finanzas-quote-list")).status_code == status.HTTP_200_OK
        # Cobranza NO está contratada aunque viva en la misma app.
        assert client.get(reverse("finanzas-charge-list")).status_code == (
            status.HTTP_404_NOT_FOUND
        )

    def test_cfdi_aparte_de_cobranza(self) -> None:
        client, _ = _cliente([*_DENTAL, Module.COBRANZA])

        assert client.get(reverse("finanzas-charge-list")).status_code == status.HTTP_200_OK
        assert client.get(reverse("finanzas-cfdi-list")).status_code == (
            status.HTTP_404_NOT_FOUND
        )
