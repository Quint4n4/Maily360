"""
Tests de Fase 2 — DoctorSchedule.sucursal (multi-sede).

Cubre:
1. Backfill (personal/migrations/0011): horarios heredan la sucursal de su
   consultorio, o caen a la "Sucursal Principal" del tenant.
2. schedule_create: resolución de sucursal (explícita > consultorio > activa
   > predeterminada), coherencia implícita vía consultorio, regla del médico
   que no atiende en la sede resuelta, y compatibilidad retro (tenant sin
   sucursales configuradas).

Patrón: AAA. Todas tocan BD → fixture db.
"""

import datetime
import importlib
from typing import Any

import pytest
from django.apps import apps as real_apps
from django.core.exceptions import ValidationError

from apps.personal.services import schedule_create
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ConsultorioFactory,
    DoctorFactory,
    SucursalFactory,
    TenantMembershipFactory,
    UserFactory,
)


def _load_personal_backfill() -> Any:
    module = importlib.import_module(
        "apps.personal.migrations.0011_backfill_doctorschedule_sucursal"
    )
    return module.backfill_sucursal


def _owner(tenant: Any) -> Any:
    """Usuario OWNER del tenant: `allowed_sucursales` siempre le da acceso a
    todas las sedes, así estos tests pueden enfocarse en la RESOLUCIÓN de
    sucursal (precedencia) sin que la autorización de `resolve_write_sucursal`
    interfiera (ver apps/clinica/sucursal_scope.py)."""
    user = UserFactory()
    TenantMembershipFactory(
        user=user, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
    )
    return user


# ---------------------------------------------------------------------------
# Backfill — personal/migrations/0011
# ---------------------------------------------------------------------------


class TestBackfillDoctorScheduleSucursal:
    def test_schedule_inherits_consultorio_sucursal(self, db: Any) -> None:
        doctor = DoctorFactory()
        centro = SucursalFactory(tenant=doctor.tenant, is_default=True)
        consultorio = ConsultorioFactory(tenant=doctor.tenant, sucursal=centro)
        schedule = schedule_create(
            tenant=doctor.tenant,
            user=_owner(doctor.tenant),
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            consultorio=consultorio,
        )
        # schedule_create ya resuelve la sucursal correctamente en la creación;
        # forzamos el escenario "legado" (sucursal NULL) para probar el backfill.
        schedule.sucursal = None
        schedule.save(update_fields=["sucursal"])

        backfill = _load_personal_backfill()
        backfill(real_apps, None)

        schedule.refresh_from_db()
        assert schedule.sucursal_id == centro.id

    def test_schedule_without_consultorio_falls_back_to_principal(self, db: Any) -> None:
        doctor = DoctorFactory()
        principal = SucursalFactory(tenant=doctor.tenant, is_default=True)
        schedule = schedule_create(
            tenant=doctor.tenant,
            user=_owner(doctor.tenant),
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
        )
        schedule.sucursal = None
        schedule.save(update_fields=["sucursal"])

        backfill = _load_personal_backfill()
        backfill(real_apps, None)

        schedule.refresh_from_db()
        assert schedule.sucursal_id == principal.id


# ---------------------------------------------------------------------------
# schedule_create — resolución de sucursal
# ---------------------------------------------------------------------------


class TestScheduleCreateSucursalResolution:
    def test_inherits_sucursal_from_consultorio(self, db: Any) -> None:
        doctor = DoctorFactory()
        norte = SucursalFactory(tenant=doctor.tenant)
        consultorio = ConsultorioFactory(tenant=doctor.tenant, sucursal=norte)

        schedule = schedule_create(
            tenant=doctor.tenant,
            user=_owner(doctor.tenant),
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            consultorio=consultorio,
        )

        assert schedule.sucursal_id == norte.id

    def test_explicit_sucursal_id_takes_precedence_over_consultorio(self, db: Any) -> None:
        """schedule_create no exige coherencia consultorio↔sucursal (a
        diferencia de appointment_create); sucursal_id explícita gana."""
        doctor = DoctorFactory()
        centro = SucursalFactory(tenant=doctor.tenant)
        norte = SucursalFactory(tenant=doctor.tenant)
        consultorio_centro = ConsultorioFactory(tenant=doctor.tenant, sucursal=centro)

        schedule = schedule_create(
            tenant=doctor.tenant,
            user=_owner(doctor.tenant),
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            consultorio=consultorio_centro,
            sucursal_id=norte.id,
        )

        assert schedule.sucursal_id == norte.id

    def test_rejects_doctor_not_assigned_to_sucursal(self, db: Any) -> None:
        doctor = DoctorFactory()
        centro = SucursalFactory(tenant=doctor.tenant)
        norte = SucursalFactory(tenant=doctor.tenant)
        doctor.sucursales.add(centro)

        with pytest.raises(ValidationError, match="no atiende en esa sucursal"):
            schedule_create(
                tenant=doctor.tenant,
                user=_owner(doctor.tenant),
                doctor=doctor,
                day_of_week=0,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(13, 0),
                sucursal_id=norte.id,
            )

    def test_allows_doctor_assigned_to_sucursal(self, db: Any) -> None:
        doctor = DoctorFactory()
        centro = SucursalFactory(tenant=doctor.tenant)
        doctor.sucursales.add(centro)

        schedule = schedule_create(
            tenant=doctor.tenant,
            user=_owner(doctor.tenant),
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            sucursal_id=centro.id,
        )

        assert schedule.sucursal_id == centro.id

    def test_without_any_sucursal_falls_back_to_none(self, db: Any) -> None:
        """Compatibilidad retro: tenant sin ninguna sucursal configurada."""
        doctor = DoctorFactory()

        schedule = schedule_create(
            tenant=doctor.tenant,
            user=_owner(doctor.tenant),
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
        )

        assert schedule.sucursal_id is None
