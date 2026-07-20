"""
Tests de seguridad — cierre del Clúster A (detalle/acción por id sin
filtro de sede) documentado en docs/design/sucursales-hallazgos-seguridad.md.

Antes del fix: los selectors `appointment_get`/`agenda_block_get` (y por lo
tanto TODOS los endpoints de detalle/acción por id de agenda) solo filtraban
por tenant, nunca por sucursal. Como el id de cualquier cita/bloqueo se
obtiene del estado de cuenta COMPARTIDO del paciente (multi-sede, por
diseño), un admin acotado a una sede podía leer/editar/mover/cancelar
objetos de OTRA sede del mismo tenant con solo conocer su id.

Hallazgos cerrados aquí:
    A1 (CRÍTICO) — appointment_reschedule no validaba sede (ni origen ni
        destino). Ahora valida ambas: la sede ACTUAL de la cita contra
        allowed_sucursales del actor, y la sede DESTINO resuelta contra
        resolve_write_sucursal (que ya valida internamente).
    A2 (ALTO) — citas por id (detalle/patch/cancelar/estado/reagendar/
        reactivar/notas) no acotaban por sucursal. Ahora usan
        `appointment_get(sucursal_ids=sucursal_scope_ids(request))` — mismo
        criterio que el LISTADO — vía los helpers `_appointment_get_or_404`
        de apps.agenda.views.
    A3 (ALTO) — bloqueos/eventos por id (patch/delete/notas) no acotaban por
        sucursal. Mismo fix con `agenda_block_get(sucursal_ids=...)`.

Patrón: AAA. HTTP vía APIClient (helpers `_api_tenant_ctx`/`_auth_client`,
copiados de test_sucursal_scoping.py); el chequeo de sede ORIGEN de
`appointment_reschedule` también se prueba a nivel de SERVICIO directo
(bypassing el selector acotado de la vista) como defensa en profundidad,
siguiendo el mismo patrón ya usado en
TestAdminDeSucursalAgenda de test_sucursal_scoping.py.
"""

import datetime
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.agenda.models import AgendaBlock, Appointment
from apps.agenda.services import (
    agenda_block_create,
    appointment_change_status,
    appointment_create,
    appointment_reschedule,
)
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ConsultorioFactory,
    DoctorFactory,
    MembershipSucursalFactory,
    PatientFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

_BASE_DT = datetime.datetime(2033, 3, 1, 10, 0, 0, tzinfo=datetime.UTC)
_ONE_HOUR = datetime.timedelta(hours=1)


# ---------------------------------------------------------------------------
# Helpers (copiados de test_sucursal_scoping.py para no acoplar módulos de test)
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Activa el contexto de tenant para que TenantManager filtre por él."""
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


@contextmanager
def _api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Inyecta el tenant en el middleware/TenantManager para tests HTTP."""
    with (
        patch("apps.agenda.views.get_current_tenant", return_value=tenant),
        patch("apps.clinica.sucursal_scope.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _member(tenant: Any, role: str) -> Any:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _admin_scoped_to(tenant: Any, sucursal: Any) -> Any:
    """Crea un admin cuyo ÚNICO alcance de sede es `sucursal` (admin de sucursal)."""
    user = UserFactory()
    membership = TenantMembershipFactory(
        user=user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
    )
    MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=sucursal)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _detail_url(appointment_id: Any) -> str:
    return f"/api/v1/agenda/citas/{appointment_id}/"


def _estado_url(appointment_id: Any) -> str:
    return f"/api/v1/agenda/citas/{appointment_id}/estado/"


def _reagendar_url(appointment_id: Any) -> str:
    return f"/api/v1/agenda/citas/{appointment_id}/reagendar/"


def _reactivar_url(appointment_id: Any) -> str:
    return f"/api/v1/agenda/citas/{appointment_id}/reactivar/"


def _block_url(block_id: Any) -> str:
    return f"/api/v1/agenda/eventos/{block_id}/"


# ---------------------------------------------------------------------------
# Fixture compartida: tenant con dos sedes, un admin acotado a Centro
# ---------------------------------------------------------------------------


class _Escenario:
    """Agrupa el fixture común de los tests de este módulo (evita duplicar 15 líneas)."""

    def __init__(self) -> None:
        self.tenant = TenantFactory()
        self.centro = SucursalFactory(tenant=self.tenant, name="Centro")
        self.norte = SucursalFactory(tenant=self.tenant, name="Norte")
        self.consultorio_centro = ConsultorioFactory(tenant=self.tenant, sucursal=self.centro)
        self.consultorio_norte = ConsultorioFactory(tenant=self.tenant, sucursal=self.norte)
        self.doctor = DoctorFactory(tenant=self.tenant)
        self.owner = _member(self.tenant, TenantMembership.Role.OWNER)
        self.admin_centro = _admin_scoped_to(self.tenant, self.centro)

    def cita_en(self, sucursal_consultorio: Any) -> Appointment:
        with _tenant_ctx(self.tenant):
            return appointment_create(
                tenant=self.tenant,
                user=self.owner,
                patient_id=PatientFactory(tenant=self.tenant).id,
                doctor_id=self.doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=sucursal_consultorio.id,
            )


# ---------------------------------------------------------------------------
# A1 (CRÍTICO) — appointment_reschedule ahora valida sede origen y destino
# ---------------------------------------------------------------------------


class TestAppointmentRescheduleValidaSede:
    def test_service_rechaza_reagendar_cita_de_otra_sede_ATAQUE1(self, db: Any) -> None:
        """ATAQUE1: reagendar (a nivel servicio, bypassing el selector acotado
        de la vista, como defensa en profundidad) una cita cuya sede actual
        (Norte) no está entre las permitidas del actor (Centro)."""
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)

        with _tenant_ctx(esc.tenant), pytest.raises(ValidationError, match="No tienes acceso"):
            appointment_reschedule(
                appointment=cita_norte,
                user=esc.admin_centro,
                starts_at=_BASE_DT + datetime.timedelta(hours=5),
            )

    def test_service_rechaza_mover_cita_propia_a_consultorio_de_otra_sede_ATAQUE2(
        self, db: Any
    ) -> None:
        """ATAQUE2: el admin de Centro SÍ puede tocar su propia cita (sede
        origen permitida), pero no puede MOVERLA a un consultorio de Norte —
        la sede DESTINO resuelta debe validarse igual que en appointment_create."""
        esc = _Escenario()
        cita_centro = esc.cita_en(esc.consultorio_centro)

        with _tenant_ctx(esc.tenant), pytest.raises(ValidationError, match="No tienes acceso"):
            appointment_reschedule(
                appointment=cita_centro,
                user=esc.admin_centro,
                starts_at=_BASE_DT + datetime.timedelta(hours=5),
                consultorio_id=esc.consultorio_norte.id,
            )

    def test_owner_si_puede_mover_cita_entre_sedes(self, db: Any) -> None:
        """El owner tiene acceso a TODAS las sedes: mover una cita de Centro
        a un consultorio de Norte sigue funcionando (no es una regresión)."""
        esc = _Escenario()
        cita_centro = esc.cita_en(esc.consultorio_centro)

        with _tenant_ctx(esc.tenant):
            updated = appointment_reschedule(
                appointment=cita_centro,
                user=esc.owner,
                starts_at=_BASE_DT + datetime.timedelta(hours=5),
                consultorio_id=esc.consultorio_norte.id,
            )

        assert updated.sucursal_id == esc.norte.id

    def test_admin_puede_reagendar_dentro_de_su_propia_sede(self, db: Any) -> None:
        """Regresión: el flujo normal (reagendar sin cambiar de sede) sigue
        funcionando para un admin acotado a esa sede."""
        esc = _Escenario()
        cita_centro = esc.cita_en(esc.consultorio_centro)

        with _tenant_ctx(esc.tenant):
            updated = appointment_reschedule(
                appointment=cita_centro,
                user=esc.admin_centro,
                starts_at=_BASE_DT + datetime.timedelta(hours=5),
            )

        assert updated.sucursal_id == esc.centro.id
        assert updated.starts_at == _BASE_DT + datetime.timedelta(hours=5)


# ---------------------------------------------------------------------------
# A2 (ALTO) — endpoints HTTP de citas por id acotan por sucursal (404)
# ---------------------------------------------------------------------------


class TestAppointmentEndpointsHttpScoping:
    def test_get_detalle_cita_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp = client.get(_detail_url(cita_norte.id))

        assert resp.status_code == 404, resp.content

    def test_patch_cita_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp = client.patch(_detail_url(cita_norte.id), data={"reason": "hackeado"})

        assert resp.status_code == 404, resp.content
        cita_norte.refresh_from_db()
        assert cita_norte.reason != "hackeado"

    def test_cancelar_delete_cita_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp = client.delete(_detail_url(cita_norte.id))

        assert resp.status_code == 404, resp.content
        cita_norte.refresh_from_db()
        assert cita_norte.status != Appointment.Status.CANCELLED

    def test_cambiar_estado_cita_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp = client.post(
                _estado_url(cita_norte.id),
                data={"status": Appointment.Status.CONFIRMED},
                format="json",
            )

        assert resp.status_code == 404, resp.content

    def test_reagendar_cita_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp = client.post(
                _reagendar_url(cita_norte.id),
                data={"starts_at": (_BASE_DT + datetime.timedelta(hours=5)).isoformat()},
                format="json",
            )

        assert resp.status_code == 404, resp.content

    def test_reactivar_cita_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)
        with _tenant_ctx(esc.tenant):
            appointment_change_status(
                appointment=cita_norte,
                user=esc.owner,
                new_status=Appointment.Status.CANCELLED,
                reason="motivo de prueba",
            )
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp = client.post(_reactivar_url(cita_norte.id))

        assert resp.status_code == 404, resp.content

    def test_notas_de_cita_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp_get = client.get(f"/api/v1/agenda/citas/{cita_norte.id}/notas/")
            resp_post = client.post(
                f"/api/v1/agenda/citas/{cita_norte.id}/notas/",
                data={"body": "nota colada"},
                format="json",
            )

        assert resp_get.status_code == 404, resp_get.content
        assert resp_post.status_code == 404, resp_post.content

    # -- Regresión: el flujo normal en la propia sede sigue funcionando --

    def test_admin_opera_normalmente_citas_de_su_propia_sede(self, db: Any) -> None:
        esc = _Escenario()
        cita_centro = esc.cita_en(esc.consultorio_centro)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp_get = client.get(_detail_url(cita_centro.id))
            resp_patch = client.patch(_detail_url(cita_centro.id), data={"reason": "motivo ok"})
            resp_estado = client.post(
                _estado_url(cita_centro.id),
                data={"status": Appointment.Status.CONFIRMED},
                format="json",
            )
            resp_reagendar = client.post(
                _reagendar_url(cita_centro.id),
                data={"starts_at": (_BASE_DT + datetime.timedelta(hours=6)).isoformat()},
                format="json",
            )
            resp_cancelar = client.delete(_detail_url(cita_centro.id))
            resp_reactivar = client.post(_reactivar_url(cita_centro.id))

        assert resp_get.status_code == 200, resp_get.content
        assert resp_patch.status_code == 200, resp_patch.content
        assert resp_estado.status_code == 200, resp_estado.content
        assert resp_reagendar.status_code == 200, resp_reagendar.content
        assert resp_cancelar.status_code == 204, resp_cancelar.content
        assert resp_reactivar.status_code == 200, resp_reactivar.content

    def test_owner_opera_cita_de_cualquier_sede(self, db: Any) -> None:
        esc = _Escenario()
        cita_norte = esc.cita_en(esc.consultorio_norte)
        client = _auth_client(esc.owner)

        with _api_tenant_ctx(esc.tenant):
            resp = client.get(_detail_url(cita_norte.id))

        assert resp.status_code == 200, resp.content


# ---------------------------------------------------------------------------
# A3 (ALTO) — bloqueos/eventos por id acotan por sucursal (404)
# ---------------------------------------------------------------------------


class TestAgendaBlockEndpointsHttpScoping:
    def _bloqueo_en(self, esc: _Escenario, sucursal: Any) -> AgendaBlock:
        with _tenant_ctx(esc.tenant):
            return agenda_block_create(
                tenant=esc.tenant,
                user=esc.owner,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                sucursal_id=sucursal.id,
            )

    def test_patch_bloqueo_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        bloqueo_norte = self._bloqueo_en(esc, esc.norte)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp = client.patch(_block_url(bloqueo_norte.id), data={"title": "hackeado"})

        assert resp.status_code == 404, resp.content

    def test_delete_bloqueo_de_otra_sede_404(self, db: Any) -> None:
        esc = _Escenario()
        bloqueo_norte = self._bloqueo_en(esc, esc.norte)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp = client.delete(_block_url(bloqueo_norte.id))

        assert resp.status_code == 404, resp.content
        bloqueo_norte.refresh_from_db()
        assert bloqueo_norte.deleted_at is None

    def test_admin_opera_normalmente_bloqueos_de_su_propia_sede(self, db: Any) -> None:
        esc = _Escenario()
        bloqueo_centro = self._bloqueo_en(esc, esc.centro)
        client = _auth_client(esc.admin_centro)

        with _api_tenant_ctx(esc.tenant):
            resp_patch = client.patch(_block_url(bloqueo_centro.id), data={"title": "Cierre"})
            resp_delete = client.delete(_block_url(bloqueo_centro.id))

        assert resp_patch.status_code == 200, resp_patch.content
        assert resp_delete.status_code == 204, resp_delete.content

    def test_owner_opera_bloqueo_de_cualquier_sede(self, db: Any) -> None:
        esc = _Escenario()
        bloqueo_norte = self._bloqueo_en(esc, esc.norte)
        client = _auth_client(esc.owner)

        with _api_tenant_ctx(esc.tenant):
            resp = client.patch(_block_url(bloqueo_norte.id), data={"title": "Cierre autorizado"})

        assert resp.status_code == 200, resp.content
