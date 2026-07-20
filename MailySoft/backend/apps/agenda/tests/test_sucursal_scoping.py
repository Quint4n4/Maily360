"""
Tests de Fase 2 — Agenda por sucursal (multi-sede).

Cubre:
1. Backfill (agenda/migrations/0015): citas y eventos de agenda heredan la
   sucursal de su consultorio, o caen a la "Sucursal Principal" del tenant.
2. REGLA CRÍTICA — la disponibilidad del MÉDICO es GLOBAL entre sedes: una
   cita en Sucursal A bloquea a ese médico en Sucursal B a la misma hora.
3. El anti-empalme de CONSULTORIO sigue funcionando (es implícitamente por
   sede, porque un consultorio pertenece a una única sucursal).
4. Bloqueos "de sucursal" (antes "de toda la clínica") NO cruzan de sede;
   un bloqueo de DOCTOR sí aplica en todas sus sedes (global).
5. Resolución/validación de sucursal en appointment_create: herencia desde
   el consultorio, incoherencia consultorio↔sucursal, médico que no atiende
   en la sede resuelta.
6. Aislamiento operativo en los endpoints HTTP: un rol acotado a una sede
   (vía MembershipSucursal) no ve ni crea citas de otra sede.
7. agenda_busy_intervals: bloqueos filtrados por sede, citas del médico
   siempre globales.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import datetime
import importlib
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from django.apps import apps as real_apps
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.agenda.models import AgendaBlock
from apps.agenda.selectors import agenda_block_list, agenda_busy_intervals
from apps.agenda.services import agenda_block_create, appointment_create
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AppointmentFactory,
    ConsultorioFactory,
    DoctorFactory,
    MembershipSucursalFactory,
    PatientFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

_BASE_DT = datetime.datetime(2032, 3, 1, 10, 0, 0, tzinfo=datetime.UTC)
_ONE_HOUR = datetime.timedelta(hours=1)

CITAS_URL = "/api/v1/agenda/citas/"


# ---------------------------------------------------------------------------
# Helpers
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
    """Inyecta el tenant en el middleware/TenantManager para tests HTTP.

    Parchea get_current_tenant en las vistas de agenda y en
    apps.clinica.sucursal_scope (de donde resolve_active_sucursal lo lee).
    """
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


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _load_agenda_backfill() -> Any:
    """Importa la función RunPython de la migración 0015 por su path completo."""
    module = importlib.import_module(
        "apps.agenda.migrations.0015_backfill_appointment_agendablock_sucursal"
    )
    return module.backfill_sucursal


# ---------------------------------------------------------------------------
# 1. Backfill — agenda/migrations/0015
# ---------------------------------------------------------------------------


class TestBackfillAppointmentAgendaBlockSucursal:
    def test_appointment_inherits_consultorio_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_default=True)
        consultorio = ConsultorioFactory(tenant=tenant, sucursal=centro)
        # Cita "legada": creada sin pasar por el service, sucursal aún NULL.
        appt = AppointmentFactory(tenant=tenant, consultorio=consultorio)
        assert appt.sucursal_id is None

        backfill = _load_agenda_backfill()
        backfill(real_apps, None)

        appt.refresh_from_db()
        assert appt.sucursal_id == centro.id

    def test_appointment_without_consultorio_falls_back_to_principal(self, db: Any) -> None:
        tenant = TenantFactory()
        principal = SucursalFactory(tenant=tenant, is_default=True)
        appt = AppointmentFactory(tenant=tenant, consultorio=None)
        assert appt.sucursal_id is None

        backfill = _load_agenda_backfill()
        backfill(real_apps, None)

        appt.refresh_from_db()
        assert appt.sucursal_id == principal.id

    def test_agendablock_backfill_same_rules(self, db: Any) -> None:
        tenant = TenantFactory()
        principal = SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)

        with _tenant_ctx(tenant):
            block_con_consultorio = AgendaBlock.objects.create(
                tenant=tenant,
                kind=AgendaBlock.Kind.BLOCK,
                consultorio=consultorio_norte,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
            )
            block_clinica = AgendaBlock.objects.create(
                tenant=tenant,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT + datetime.timedelta(hours=2),
                ends_at=_BASE_DT + datetime.timedelta(hours=3),
            )

        backfill = _load_agenda_backfill()
        backfill(real_apps, None)

        block_con_consultorio.refresh_from_db()
        block_clinica.refresh_from_db()
        assert block_con_consultorio.sucursal_id == norte.id
        assert block_clinica.sucursal_id == principal.id

    def test_idempotente_no_reasigna_sucursal_ya_asignada(self, db: Any) -> None:
        tenant = TenantFactory()
        SucursalFactory(tenant=tenant, is_default=True)
        otra_sede = SucursalFactory(tenant=tenant)
        appt = AppointmentFactory(tenant=tenant, consultorio=None, sucursal=otra_sede)

        backfill = _load_agenda_backfill()
        backfill(real_apps, None)
        backfill(real_apps, None)

        appt.refresh_from_db()
        assert appt.sucursal_id == otra_sede.id


# ---------------------------------------------------------------------------
# 2. REGLA CRÍTICA — disponibilidad del médico GLOBAL entre sedes
# ---------------------------------------------------------------------------


class TestDoctorGlobalAvailability:
    def test_doctor_cannot_be_double_booked_across_sucursales(self, db: Any) -> None:
        """Cita en Sucursal A de 10-11 impide agendar al MISMO doctor en
        Sucursal B a las 10-11 — el anti-empalme de doctor NUNCA se filtra
        por sede (_check_doctor_overlap mira TODAS las citas activas)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        paciente_a = PatientFactory(tenant=tenant)
        paciente_b = PatientFactory(tenant=tenant)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)

        with _tenant_ctx(tenant):
            appointment_create(
                tenant=tenant,
                user=user,
                patient_id=paciente_a.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_centro.id,
            )

            with pytest.raises(ValidationError, match="médico ya tiene una cita"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=paciente_b.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                    consultorio_id=consultorio_norte.id,
                )

    def test_doctor_can_work_different_sucursales_at_different_times(self, db: Any) -> None:
        """Mismo doctor, mismo día, horarios distintos en sedes distintas: OK."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        paciente_a = PatientFactory(tenant=tenant)
        paciente_b = PatientFactory(tenant=tenant)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)

        with _tenant_ctx(tenant):
            appt_centro = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=paciente_a.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_centro.id,
            )
            appt_norte = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=paciente_b.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT + datetime.timedelta(hours=2),
                ends_at=_BASE_DT + datetime.timedelta(hours=3),
                consultorio_id=consultorio_norte.id,
            )

        assert appt_centro.sucursal_id == centro.id
        assert appt_norte.sucursal_id == norte.id


# ---------------------------------------------------------------------------
# 3. Consultorio: el anti-empalme sigue funcionando dentro de su sede
# ---------------------------------------------------------------------------


class TestConsultorioOverlapStillWorks:
    def test_consultorio_overlap_blocks_different_doctors_same_room(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        consultorio = ConsultorioFactory(tenant=tenant, sucursal=centro)
        doctor_a = DoctorFactory(tenant=tenant)
        doctor_b = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        paciente_a = PatientFactory(tenant=tenant)
        paciente_b = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            appointment_create(
                tenant=tenant,
                user=user,
                patient_id=paciente_a.id,
                doctor_id=doctor_a.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio.id,
            )
            with pytest.raises(ValidationError, match="consultorio ya está ocupado"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=paciente_b.id,
                    doctor_id=doctor_b.id,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                    consultorio_id=consultorio.id,
                )


# ---------------------------------------------------------------------------
# 4. Bloqueos: "de sucursal" no cruza de sede; "de doctor" sí (global)
# ---------------------------------------------------------------------------


class TestBlockSucursalScope:
    def test_sucursal_wide_block_does_not_cross_to_other_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)

        with _tenant_ctx(tenant):
            agenda_block_create(
                tenant=tenant,
                user=user,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                sucursal_id=centro.id,
            )

            # Cita en Norte al mismo horario: el cierre de Centro NO aplica.
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_norte.id,
            )

        assert appt.sucursal_id == norte.id

    def test_sucursal_wide_block_does_block_same_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)

        with _tenant_ctx(tenant):
            agenda_block_create(
                tenant=tenant,
                user=user,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                sucursal_id=centro.id,
            )

            with pytest.raises(ValidationError, match="[Bb]loqueado"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                    consultorio_id=consultorio_centro.id,
                )

    def test_doctor_block_applies_across_all_sucursales(self, db: Any) -> None:
        """Un bloqueo de DOCTOR (sin importar en qué sede se creó) aplica en
        TODAS las sedes de ese médico — mismo principio que el anti-empalme
        global de citas."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)

        with _tenant_ctx(tenant):
            # Bloqueo del doctor, "creado" en el contexto de Centro.
            agenda_block_create(
                tenant=tenant,
                user=user,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                doctor_id=doctor.id,
                sucursal_id=centro.id,
            )

            # Aun así, bloquea al doctor en Norte.
            with pytest.raises(ValidationError, match="[Bb]loqueado"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                    consultorio_id=consultorio_norte.id,
                )


# ---------------------------------------------------------------------------
# 5. Resolución/validación de sucursal en appointment_create
# ---------------------------------------------------------------------------


class TestAppointmentSucursalResolution:
    def test_appointment_inherits_sucursal_from_consultorio(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_norte.id,
            )

        assert appt.sucursal_id == norte.id

    def test_appointment_create_rejects_incoherent_sucursal_and_consultorio(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="otra sucursal"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                    consultorio_id=consultorio_centro.id,
                    sucursal_id=norte.id,
                )

    def test_appointment_create_rejects_doctor_not_assigned_to_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        doctor.sucursales.add(centro)  # solo atiende en Centro
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="no atiende en esa sucursal"):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                    sucursal_id=norte.id,
                )

    def test_appointment_create_allows_doctor_assigned_to_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        doctor.sucursales.add(centro)
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                sucursal_id=centro.id,
            )

        assert appt.sucursal_id == centro.id

    def test_appointment_create_without_any_sucursal_falls_back_to_none(self, db: Any) -> None:
        """Compatibilidad retro: tenant sin NINGUNA sucursal configurada
        (nunca adoptó multi-sede) sigue creando citas sin sucursal, sin error."""
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)

        with _tenant_ctx(tenant):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
            )

        assert appt.sucursal_id is None


# ---------------------------------------------------------------------------
# 6. Aislamiento operativo HTTP por sucursal
# ---------------------------------------------------------------------------


class TestAppointmentApiSucursalIsolation:
    def test_header_de_sede_no_permitida_403(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CITAS_URL, headers={"X-Sucursal-Id": str(norte.id)})

        assert resp.status_code == 403

    def test_listado_filtrado_no_trae_citas_de_otra_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        owner = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            appointment_create(
                tenant=tenant,
                user=owner,
                patient_id=PatientFactory(tenant=tenant).id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_centro.id,
            )
            appointment_create(
                tenant=tenant,
                user=owner,
                patient_id=PatientFactory(tenant=tenant).id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT + datetime.timedelta(hours=3),
                ends_at=_BASE_DT + datetime.timedelta(hours=4),
                consultorio_id=consultorio_norte.id,
            )

        recepcion_user = UserFactory()
        membership = TenantMembershipFactory(
            user=recepcion_user,
            tenant=tenant,
            role=TenantMembership.Role.RECEPTION,
            is_active=True,
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(recepcion_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CITAS_URL, headers={"X-Sucursal-Id": str(centro.id)})

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["sucursal"]["id"] == str(centro.id)

    def test_crear_cita_con_header_activo_hereda_esa_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        user = UserFactory()
        membership = TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(user)

        payload = {
            "patient_id": str(patient.id),
            "doctor_id": str(doctor.id),
            "starts_at": _BASE_DT.isoformat(),
            "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
        }

        with _api_tenant_ctx(tenant):
            resp = client.post(
                CITAS_URL, data=payload, format="json", headers={"X-Sucursal-Id": str(centro.id)}
            )

        assert resp.status_code == 201, resp.content
        assert resp.json()["sucursal"]["id"] == str(centro.id)


# ---------------------------------------------------------------------------
# 6b. Objetivo A (Fase 3) — sin header YA NO fuga otra sede
# ---------------------------------------------------------------------------


class TestSinHeaderYaNoFugaOtraSede:
    """Antes del fix: un rol acotado a Centro veía citas/bloqueos de Norte con
    solo OMITIR el header X-Sucursal-Id. `sucursal_scope_ids` acota SIEMPRE."""

    def test_recepcion_acotada_a_centro_no_ve_citas_de_norte_sin_header(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        owner = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            appointment_create(
                tenant=tenant,
                user=owner,
                patient_id=PatientFactory(tenant=tenant).id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_centro.id,
            )
            appointment_create(
                tenant=tenant,
                user=owner,
                patient_id=PatientFactory(tenant=tenant).id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT + datetime.timedelta(hours=3),
                ends_at=_BASE_DT + datetime.timedelta(hours=4),
                consultorio_id=consultorio_norte.id,
            )

        reception_user = UserFactory()
        membership = TenantMembershipFactory(
            user=reception_user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(reception_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CITAS_URL)  # SIN X-Sucursal-Id

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["sucursal"]["id"] == str(centro.id)

    def test_owner_sin_header_sigue_viendo_todo_consolidado(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        owner = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            appointment_create(
                tenant=tenant,
                user=owner,
                patient_id=PatientFactory(tenant=tenant).id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_centro.id,
            )
            appointment_create(
                tenant=tenant,
                user=owner,
                patient_id=PatientFactory(tenant=tenant).id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT + datetime.timedelta(hours=3),
                ends_at=_BASE_DT + datetime.timedelta(hours=4),
                consultorio_id=consultorio_norte.id,
            )

        client = _auth_client(owner)

        with _api_tenant_ctx(tenant):
            resp = client.get(CITAS_URL)

        assert resp.status_code == 200, resp.content
        assert resp.json()["count"] == 2

    def test_recepcion_acotada_a_centro_no_ve_bloqueos_de_norte_sin_header(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        owner = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            agenda_block_create(
                tenant=tenant,
                user=owner,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                sucursal_id=centro.id,
            )
            agenda_block_create(
                tenant=tenant,
                user=owner,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT + datetime.timedelta(hours=3),
                ends_at=_BASE_DT + datetime.timedelta(hours=4),
                sucursal_id=norte.id,
            )

        reception_user = UserFactory()
        membership = TenantMembershipFactory(
            user=reception_user, tenant=tenant, role=TenantMembership.Role.RECEPTION, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(reception_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(
                "/api/v1/agenda/eventos/",
                {
                    "date_from": _BASE_DT.isoformat(),
                    "date_to": (_BASE_DT + datetime.timedelta(hours=6)).isoformat(),
                },
            )

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert len(body) == 1
        assert body[0]["sucursal"]["id"] == str(centro.id)


# ---------------------------------------------------------------------------
# 6c. "Admin de sucursal" — mismo aislamiento que un rol operativo acotado
# (bug corregido: antes cualquier admin veía/creaba citas en TODAS las sedes
# sin importar su MembershipSucursal; ver
# docs/design/sucursales-arquitectura-analisis.md §12)
# ---------------------------------------------------------------------------


class TestAdminDeSucursalAgenda:
    def test_admin_acotado_a_centro_no_ve_citas_de_norte_sin_header(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        owner = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            appointment_create(
                tenant=tenant,
                user=owner,
                patient_id=PatientFactory(tenant=tenant).id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_centro.id,
            )
            appointment_create(
                tenant=tenant,
                user=owner,
                patient_id=PatientFactory(tenant=tenant).id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT + datetime.timedelta(hours=3),
                ends_at=_BASE_DT + datetime.timedelta(hours=4),
                consultorio_id=consultorio_norte.id,
            )

        admin_user = UserFactory()
        membership = TenantMembershipFactory(
            user=admin_user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CITAS_URL)  # SIN X-Sucursal-Id

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["sucursal"]["id"] == str(centro.id)

    def test_admin_acotado_a_centro_pide_header_de_norte_403(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")

        admin_user = UserFactory()
        membership = TenantMembershipFactory(
            user=admin_user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(admin_user)

        with _api_tenant_ctx(tenant):
            resp = client.get(CITAS_URL, headers={"X-Sucursal-Id": str(norte.id)})

        assert resp.status_code == 403

    def test_admin_acotado_a_centro_no_puede_crear_cita_en_sede_default_ajena(
        self, db: Any
    ) -> None:
        """CIERRE DEL HUECO (resolve_write_sucursal): la sede PREDETERMINADA
        del tenant es Norte, el admin solo está asignado a Centro. Sin
        header ni consultorio, `resolve_write_sucursal` NO debe caer
        silenciosamente en la default ajena — debe rechazar la escritura."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        SucursalFactory(tenant=tenant, name="Norte", is_default=True)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        admin_user = UserFactory()
        membership = TenantMembershipFactory(
            user=admin_user, tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
        )
        MembershipSucursalFactory(tenant=tenant, membership=membership, sucursal=centro)
        client = _auth_client(admin_user)

        payload = {
            "patient_id": str(patient.id),
            "doctor_id": str(doctor.id),
            "starts_at": _BASE_DT.isoformat(),
            "ends_at": (_BASE_DT + _ONE_HOUR).isoformat(),
        }

        with _api_tenant_ctx(tenant):
            resp = client.post(CITAS_URL, data=payload, format="json")  # SIN header

        assert resp.status_code == 400, resp.content

    def test_admin_acotado_a_centro_no_puede_crear_cita_con_sucursal_id_explicita_de_norte(
        self, db: Any
    ) -> None:
        """Cierra la ruta de fuga por BODY: mandar `sucursal_id` explícito de
        Norte tampoco debe funcionar aunque el header no se use para ese
        campo — `resolve_write_sucursal` valida la sede RESUELTA contra
        `allowed_sucursales`, sin importar por qué vía llegó."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, name="Centro")
        norte = SucursalFactory(tenant=tenant, name="Norte")
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        admin_user = _member(tenant, TenantMembership.Role.ADMIN)
        MembershipSucursalFactory(
            tenant=tenant,
            membership=TenantMembership.objects.get(user=admin_user, tenant=tenant),
            sucursal=centro,
        )

        with _tenant_ctx(tenant), pytest.raises(ValidationError, match="No tienes acceso"):
            appointment_create(
                tenant=tenant,
                user=admin_user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                sucursal_id=norte.id,
            )


# ---------------------------------------------------------------------------
# 7. agenda_busy_intervals — bloqueos por sede, citas del doctor globales
# ---------------------------------------------------------------------------


class TestAgendaBusyIntervalsSucursal:
    def test_doctor_appointments_are_global_block_scoped_by_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)

        with _tenant_ctx(tenant):
            appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_centro.id,
            )
            agenda_block_create(
                tenant=tenant,
                user=user,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT + datetime.timedelta(hours=3),
                ends_at=_BASE_DT + datetime.timedelta(hours=4),
                sucursal_id=centro.id,
            )

            intervalos = agenda_busy_intervals(
                doctor_id=doctor.id,
                consultorio_id=None,
                date_from=_BASE_DT,
                date_to=_BASE_DT + datetime.timedelta(hours=6),
                sucursal_id=norte.id,
            )

        starts = {i["start"] for i in intervalos}
        # La cita del doctor SÍ aparece consultando Norte (global).
        assert _BASE_DT in starts
        # El bloqueo "de sede" de Centro NO aparece al consultar Norte.
        assert (_BASE_DT + datetime.timedelta(hours=3)) not in starts

    def test_block_appears_when_querying_its_own_sucursal(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            agenda_block_create(
                tenant=tenant,
                user=user,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT + datetime.timedelta(hours=3),
                ends_at=_BASE_DT + datetime.timedelta(hours=4),
                sucursal_id=centro.id,
            )

            intervalos = agenda_busy_intervals(
                doctor_id=doctor.id,
                consultorio_id=None,
                date_from=_BASE_DT,
                date_to=_BASE_DT + datetime.timedelta(hours=6),
                sucursal_id=centro.id,
            )

        starts = {i["start"] for i in intervalos}
        assert (_BASE_DT + datetime.timedelta(hours=3)) in starts


# ---------------------------------------------------------------------------
# 8. agenda_block_list — filtro por sede
# ---------------------------------------------------------------------------


class TestAgendaBlockListSucursalFilter:
    def test_sucursal_wide_block_filtered_by_its_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            agenda_block_create(
                tenant=tenant,
                user=user,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                sucursal_id=centro.id,
            )

            qs_centro = agenda_block_list(sucursal_id=centro.id)
            qs_norte = agenda_block_list(sucursal_id=norte.id)

        assert qs_centro.count() == 1
        assert qs_norte.count() == 0

    def test_doctor_block_always_visible_regardless_of_sucursal_filter(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant)
        norte = SucursalFactory(tenant=tenant)
        doctor = DoctorFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.OWNER)

        with _tenant_ctx(tenant):
            agenda_block_create(
                tenant=tenant,
                user=user,
                kind=AgendaBlock.Kind.BLOCK,
                starts_at=_BASE_DT,
                ends_at=_BASE_DT + _ONE_HOUR,
                doctor_id=doctor.id,
                sucursal_id=centro.id,
            )

            qs_norte = agenda_block_list(sucursal_id=norte.id)

        assert qs_norte.count() == 1
