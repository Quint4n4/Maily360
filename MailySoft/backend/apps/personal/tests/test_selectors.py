"""
Tests de selectors.py de la app personal.

Cubre:
- doctor_list: filtro only_active, búsqueda por specialty y nombre de usuario.
- doctor_list: N+1 — select_related garantizado.
- doctor_list: AISLAMIENTO cross-tenant (crítico).
- consultorio_list: aislamiento cross-tenant.
- schedule_list_for_doctor: orden y filtro is_active.
- schedule_get: FIX-F2 — aislamiento cross-tenant (IDOR).

Patrón: AAA. Todas tocan BD → fixture db.
Tenant context: se activa explícitamente con set_current_tenant +
set_tenant_context_active. El fixture autouse reset_tenant_context (conftest.py)
limpia el thread-local entre tests.
"""

import datetime
from typing import Any

import pytest

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.personal.selectors import (
    consultorio_list,
    doctor_list,
    schedule_get,
    schedule_list_for_doctor,
)
from tests.factories import (
    ConsultorioFactory,
    DoctorFactory,
    DoctorScheduleFactory,
    TenantFactory,
    UserFactory,
)

# ===========================================================================
# doctor_list — filtros básicos (sin contexto de tenant activo)
# ===========================================================================


class TestDoctorListFilters:
    """doctor_list filtra correctamente por is_active y búsqueda libre."""

    def test_doctor_list_only_active_by_default(self, db: None) -> None:
        """Sin argumentos, solo se retornan doctores con is_active=True."""
        # Arrange
        tenant = TenantFactory()
        active = DoctorFactory(tenant=tenant, is_active=True)
        DoctorFactory(tenant=tenant, is_active=False)  # inactivo: no debe aparecer

        # Act — sin contexto de tenant activo, el manager no filtra por tenant
        qs = doctor_list()

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert active.id in ids
        assert all(d.is_active for d in qs)

    def test_doctor_list_includes_inactive_when_flag_false(self, db: None) -> None:
        """Con only_active=False, los doctores inactivos también aparecen."""
        # Arrange
        tenant = TenantFactory()
        inactive = DoctorFactory(tenant=tenant, is_active=False)

        # Act
        qs = doctor_list(only_active=False)

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert inactive.id in ids

    def test_doctor_list_search_by_specialty(self, db: None) -> None:
        """Buscar por especialidad retorna solo coincidencias (case-insensitive)."""
        # Arrange
        tenant = TenantFactory()
        target = DoctorFactory(tenant=tenant, specialty="Cardiología", is_active=True)
        DoctorFactory(tenant=tenant, specialty="Pediatría", is_active=True)

        # Act
        qs = doctor_list(search="cardio")

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert target.id in ids
        assert all("cardio" in d.specialty.lower() for d in qs)

    def test_doctor_list_search_by_user_name(self, db: None) -> None:
        """Buscar por nombre del usuario devuelve al médico correspondiente."""
        # Arrange — crear membership con usuario de nombre conocido
        from tests.factories import TenantMembershipFactory

        tenant = TenantFactory()
        user_target = UserFactory(first_name="Esperanza", last_name="Villanueva")
        membership = TenantMembershipFactory(tenant=tenant, user=user_target, role="doctor")
        target = DoctorFactory(tenant=tenant, membership=membership, is_active=True)
        DoctorFactory(tenant=tenant, is_active=True)  # otro doctor, no debe aparecer

        # Act
        qs = doctor_list(search="esperanza")

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert target.id in ids

    def test_doctor_list_search_no_match_returns_empty(self, db: None) -> None:
        """Búsqueda sin coincidencias devuelve QuerySet vacío."""
        # Arrange
        tenant = TenantFactory()
        DoctorFactory(tenant=tenant, specialty="Neurología", is_active=True)

        # Act
        qs = doctor_list(search="xxxxxxxxxnoexiste")

        # Assert
        assert qs.count() == 0

    def test_doctor_list_uses_select_related_no_n_plus_1(
        self, db: None, django_assert_num_queries: Any
    ) -> None:
        """Listar N doctores NO debe disparar N queries extra.

        doctor_list() usa select_related('membership__user') y
        prefetch_related('consultorios', 'sucursales'). Se esperan exactamente
        3 queries para N doctores (una JOIN para el queryset + una por cada
        prefetch M2M), independientemente de N. Esto sigue siendo O(1) en
        queries, no O(N). El prefetch de 'sucursales' se agregó en la Fase 1
        de multi-sede (docs/design/sucursales-plan-implementacion.md).
        """
        # Arrange — 5 doctores en el mismo tenant
        tenant = TenantFactory()
        DoctorFactory.create_batch(5, tenant=tenant, is_active=True)

        # Act & Assert — exactamente 3 queries para N doctores:
        #   1. SELECT personal_doctors JOIN tenancy_memberships JOIN authn_users
        #   2. SELECT personal_doctors_consultorios (prefetch M2M)
        #   3. SELECT personal_doctor_sucursales (prefetch M2M)
        with django_assert_num_queries(3):
            qs = doctor_list()
            # Forzar evaluación y acceso a la relación encadenada
            names = [d.full_name for d in qs]
            # Acceso a consultorios y sucursales (prefetchados, sin queries extra)
            _ = [list(d.consultorios.all()) for d in qs]
            _ = [list(d.sucursales.all()) for d in qs]

        assert len(names) == 5


# ===========================================================================
# AISLAMIENTO CROSS-TENANT (crítico)
# ===========================================================================


class TestDoctorListTenantIsolation:
    """El TenantManager debe garantizar que un tenant no vea datos de otro."""

    def test_doctor_list_only_current_tenant(self, db: None) -> None:
        """Con contexto del tenant A activo, solo se ven doctores del tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        doctors_a = DoctorFactory.create_batch(3, tenant=tenant_a, is_active=True)
        DoctorFactory.create_batch(2, tenant=tenant_b, is_active=True)

        # Activar contexto del tenant A
        set_current_tenant(tenant_a)
        set_tenant_context_active(True)

        # Act
        qs = doctor_list()

        # Assert — solo los 3 del tenant A
        assert qs.count() == 3
        result_ids = set(qs.values_list("id", flat=True))
        expected_ids = {d.id for d in doctors_a}
        assert result_ids == expected_ids

    def test_doctor_list_tenant_b_does_not_see_tenant_a(self, db: None) -> None:
        """Con contexto del tenant B activo, no se ven doctores del tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        DoctorFactory.create_batch(4, tenant=tenant_a, is_active=True)
        doctors_b = DoctorFactory.create_batch(2, tenant=tenant_b, is_active=True)

        # Activar contexto del tenant B
        set_current_tenant(tenant_b)
        set_tenant_context_active(True)

        # Act
        qs = doctor_list()

        # Assert — solo los 2 del tenant B
        assert qs.count() == 2
        result_ids = set(qs.values_list("id", flat=True))
        expected_ids = {d.id for d in doctors_b}
        assert result_ids == expected_ids

    def test_doctor_list_no_tenant_context_returns_empty(self, db: None) -> None:
        """Con context_active=True y tenant=None (falla segura), se devuelve vacío."""
        # Arrange
        tenant = TenantFactory()
        DoctorFactory.create_batch(3, tenant=tenant, is_active=True)

        # Activar contexto SIN tenant — falla segura
        set_current_tenant(None)
        set_tenant_context_active(True)

        # Act
        qs = doctor_list()

        # Assert — QuerySet vacío
        assert qs.count() == 0

    def test_doctor_list_cross_tenant_search_does_not_leak(self, db: None) -> None:
        """La búsqueda con contexto activo no fuga datos del otro tenant."""
        # Arrange — misma especialidad en dos tenants
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        target_a = DoctorFactory(tenant=tenant_a, specialty="Oncología", is_active=True)
        DoctorFactory(tenant=tenant_b, specialty="Oncología", is_active=True)

        # Activar contexto del tenant A
        set_current_tenant(tenant_a)
        set_tenant_context_active(True)

        # Act
        qs = doctor_list(search="Oncología")

        # Assert — solo el del tenant A
        assert qs.count() == 1
        assert qs.first().id == target_a.id  # type: ignore[union-attr]


# ===========================================================================
# consultorio_list — aislamiento cross-tenant
# ===========================================================================


class TestConsultorioListIsolation:
    """consultorio_list respeta el aislamiento de tenant."""

    def test_consultorio_list_isolation(self, db: None) -> None:
        """Con contexto del tenant A, solo se ven consultorios del tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        ConsultorioFactory.create_batch(3, tenant=tenant_a, is_active=True)
        ConsultorioFactory.create_batch(2, tenant=tenant_b, is_active=True)

        # Activar contexto del tenant A
        set_current_tenant(tenant_a)
        set_tenant_context_active(True)

        # Act
        qs = consultorio_list()

        # Assert — solo los 3 del tenant A
        assert qs.count() == 3
        assert all(c.tenant_id == tenant_a.id for c in qs)

    def test_consultorio_list_only_active_by_default(self, db: None) -> None:
        """Solo se retornan consultorios con is_active=True por defecto."""
        # Arrange
        tenant = TenantFactory()
        active = ConsultorioFactory(tenant=tenant, is_active=True)
        ConsultorioFactory(tenant=tenant, is_active=False)  # no debe aparecer

        set_current_tenant(tenant)
        set_tenant_context_active(True)

        # Act
        qs = consultorio_list()

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert active.id in ids
        assert all(c.is_active for c in qs)


# ===========================================================================
# schedule_list_for_doctor
# ===========================================================================


class TestScheduleListForDoctor:
    """schedule_list_for_doctor retorna horarios activos ordenados."""

    def test_schedule_list_for_doctor_ordered(self, db: None) -> None:
        """Los horarios se retornan ordenados por day_of_week, luego start_time."""
        # Arrange
        doctor = DoctorFactory()

        # Crear horarios fuera de orden
        sched_miercoles = DoctorScheduleFactory(
            doctor=doctor,
            day_of_week=2,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            is_active=True,
        )
        sched_lunes_tarde = DoctorScheduleFactory(
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(16, 0),
            end_time=datetime.time(19, 0),
            is_active=True,
        )
        sched_lunes_manana = DoctorScheduleFactory(
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            is_active=True,
        )

        set_current_tenant(doctor.tenant)
        set_tenant_context_active(True)

        # Act
        qs = schedule_list_for_doctor(doctor=doctor)
        result = list(qs)

        # Assert — orden: Lunes mañana, Lunes tarde, Miércoles
        assert result[0].id == sched_lunes_manana.id
        assert result[1].id == sched_lunes_tarde.id
        assert result[2].id == sched_miercoles.id

    def test_schedule_list_for_doctor_excludes_inactive(self, db: None) -> None:
        """Horarios inactivos no aparecen en la lista."""
        # Arrange
        doctor = DoctorFactory()
        active_sched = DoctorScheduleFactory(doctor=doctor, is_active=True)
        DoctorScheduleFactory(doctor=doctor, is_active=False)  # no debe aparecer

        set_current_tenant(doctor.tenant)
        set_tenant_context_active(True)

        # Act
        qs = schedule_list_for_doctor(doctor=doctor)

        # Assert — solo el activo
        ids = list(qs.values_list("id", flat=True))
        assert active_sched.id in ids
        assert qs.count() == 1


# ===========================================================================
# FIX-F2: schedule_get — aislamiento cross-tenant (IDOR)
# ===========================================================================


class TestScheduleGetTenantIsolation:
    """FIX-F2: schedule_get usa TenantManager → no expone schedules de otro tenant.

    Verifica que:
    - schedule_get con contexto del tenant A devuelve el schedule correcto.
    - schedule_get con contexto del tenant A lanza DoesNotExist para schedule del tenant B
      (en lugar de devolvérselo, lo que sería un IDOR).
    """

    def test_schedule_get_returns_own_tenant_schedule(self, db: None) -> None:
        """schedule_get con tenant A activo devuelve el schedule del tenant A."""
        # Arrange
        doctor = DoctorFactory()
        schedule = DoctorScheduleFactory(doctor=doctor, is_active=True)

        set_current_tenant(doctor.tenant)
        set_tenant_context_active(True)

        # Act
        result = schedule_get(schedule_id=schedule.id)

        # Assert
        assert result.id == schedule.id

    def test_schedule_get_cross_tenant_raises_does_not_exist(self, db: None) -> None:
        """FIX-F2: Con contexto del tenant A, schedule del tenant B lanza DoesNotExist.

        Sin el fix, DoctorSchedule.objects.get(id=...) devolvería el schedule
        del tenant B (IDOR). Con el fix, el TenantManager filtra y lanza DoesNotExist.
        """
        # Arrange
        from apps.personal.models import DoctorSchedule

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        # Schedule en tenant B
        doctor_b = DoctorFactory(tenant=tenant_b)
        schedule_b = DoctorScheduleFactory(doctor=doctor_b, is_active=True)

        # Activar contexto del tenant A
        set_current_tenant(tenant_a)
        set_tenant_context_active(True)

        # Act & Assert — schedule del tenant B no debe ser accesible desde tenant A
        with pytest.raises(DoctorSchedule.DoesNotExist):
            schedule_get(schedule_id=schedule_b.id)
