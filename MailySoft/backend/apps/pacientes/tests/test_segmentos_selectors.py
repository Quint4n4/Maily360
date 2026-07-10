"""
Tests de los segmentos del selector patient_list (Fase 1).

Cubre cada segmento nuevo con casos felices, casos borde y aislamiento
cross-tenant. Se llama al selector directamente con un tenant activo en el
thread-local para que TenantManager filtre correctamente.

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.

Convención de nombres: test_<segmento>_<condición>_<resultado>.

Nota sobre fechas:
  - Para week/month: se crean citas con starts_at relativo a timezone.now() para
    que el test no se rompa cuando cambie el día/semana/mes real.
  - Para date: se usa un rango fijo (2030-01-10..2030-01-20) completamente fuera
    del presente — determinista y sin dependencia de la hora del sistema.
  - Las citas se crean directamente con AppointmentFactory forzando el status
    (más rápido y aislado que pasar por el service de estados).

NOTA DE MIGRACIÓN (2026-06-23):
  is_favorite e is_vip ya NO son BooleanFields del modelo Patient.
  Son etiquetas del sistema (PatientCategory kind="favorite"/"vip") en la
  relación M2M `Patient.categories`. El selector filtra con:
    qs.filter(categories__kind="favorite")  /  qs.filter(categories__kind="vip")
  - PatientFactory ya NO acepta is_favorite= ni is_vip=.
  - Para crear un paciente "favorito/VIP", usar _assign_system_label().
  - Los tests de aislamiento cross-tenant verifican que la etiqueta de sistema
    del tenant B no es visible desde el contexto del tenant A.
"""

import datetime

import pytest
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.clinica.models import PatientCategory
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.pacientes.selectors import patient_list
from tests.factories import AppointmentFactory, DoctorFactory, PatientFactory, TenantFactory

# ---------------------------------------------------------------------------
# Helpers internos del módulo
# ---------------------------------------------------------------------------

_FIXED_DATE_FROM = datetime.date(2030, 1, 10)
_FIXED_DATE_TO = datetime.date(2030, 1, 20)
_FIXED_DT_IN_RANGE = datetime.datetime(2030, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
_FIXED_DT_OUT_RANGE_BEFORE = datetime.datetime(2030, 1, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
_FIXED_DT_OUT_RANGE_AFTER = datetime.datetime(2030, 1, 25, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _activate_tenant(tenant: object) -> None:
    """Activa el contexto de tenant para que el TenantManager filtre correctamente."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)


def _deactivate_tenant() -> None:
    set_current_tenant(None)
    set_tenant_context_active(False)


def _assign_system_label(patient: object, tenant: object, kind: str) -> None:
    """Asigna una etiqueta de sistema (favorite/vip) al paciente.

    Crea la etiqueta del sistema si no existe para el tenant. Este helper
    reemplaza el antiguo PatientFactory(..., is_favorite=True/is_vip=True).
    """
    cat, _ = PatientCategory.objects.get_or_create(
        tenant=tenant,  # type: ignore[misc]
        kind=kind,
        deleted_at=None,
        defaults={"name": kind.title(), "created_by": None},
    )
    patient.categories.add(cat)  # type: ignore[union-attr]


def _attended_appointment(
    tenant: object, patient: object, starts_at: datetime.datetime
) -> Appointment:
    """Crea una cita con status=attended directamente (sin pasar por cambio de estado)."""
    doctor = DoctorFactory(tenant=tenant)  # type: ignore[arg-type]
    return AppointmentFactory(
        tenant=tenant,  # type: ignore[arg-type]
        patient=patient,
        doctor=doctor,
        consultorio=None,
        status=Appointment.Status.ATTENDED,
        starts_at=starts_at,
        ends_at=starts_at + datetime.timedelta(hours=1),
    )


def _cancelled_appointment(
    tenant: object, patient: object, starts_at: datetime.datetime
) -> Appointment:
    """Crea una cita con status=cancelled."""
    doctor = DoctorFactory(tenant=tenant)  # type: ignore[arg-type]
    return AppointmentFactory(
        tenant=tenant,  # type: ignore[arg-type]
        patient=patient,
        doctor=doctor,
        consultorio=None,
        status=Appointment.Status.CANCELLED,
        starts_at=starts_at,
        ends_at=starts_at + datetime.timedelta(hours=1),
    )


def _rescheduled_appointment(
    tenant: object, patient: object, starts_at: datetime.datetime
) -> Appointment:
    """Cita scheduled con reschedule_count=1 (simula cita que fue reagendada)."""
    doctor = DoctorFactory(tenant=tenant)  # type: ignore[arg-type]
    return AppointmentFactory(
        tenant=tenant,  # type: ignore[arg-type]
        patient=patient,
        doctor=doctor,
        consultorio=None,
        status=Appointment.Status.SCHEDULED,
        starts_at=starts_at,
        ends_at=starts_at + datetime.timedelta(hours=1),
        reschedule_count=1,
    )


# ===========================================================================
# Segmento "all"
# ===========================================================================


class TestSegmentAll:
    """Segmento 'all': todos los pacientes activos, orden -created_at."""

    def test_all_returns_all_active_patients(self, db: None) -> None:
        """'all' devuelve todos los activos del tenant, sin importar citas."""
        # Arrange
        tenant = TenantFactory()
        p1 = PatientFactory(tenant=tenant, is_active=True)
        p2 = PatientFactory(tenant=tenant, is_active=True)
        PatientFactory(tenant=tenant, is_active=False)  # inactivo: no debe aparecer

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="all")
            ids = set(qs.values_list("id", flat=True))

            # Assert — exactamente los 2 activos
            assert ids == {p1.id, p2.id}
        finally:
            _deactivate_tenant()

    def test_all_excludes_inactive_patients(self, db: None) -> None:
        """'all' nunca incluye pacientes con is_active=False."""
        # Arrange
        tenant = TenantFactory()
        PatientFactory.create_batch(3, tenant=tenant, is_active=False)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="all")

            # Assert
            assert qs.count() == 0
        finally:
            _deactivate_tenant()

    def test_all_tenant_isolation(self, db: None) -> None:
        """'all' solo devuelve pacientes del tenant activo, nunca del otro."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        a1 = PatientFactory(tenant=tenant_a, is_active=True)
        PatientFactory.create_batch(3, tenant=tenant_b, is_active=True)

        _activate_tenant(tenant_a)
        try:
            # Act
            qs = patient_list(segment="all")

            # Assert — solo el paciente de A
            ids = set(qs.values_list("id", flat=True))
            assert ids == {a1.id}
        finally:
            _deactivate_tenant()


# ===========================================================================
# Segmento "recent"
# ===========================================================================


class TestSegmentRecent:
    """Segmento 'recent': solo pacientes con al menos una cita atendida."""

    def test_recent_includes_patient_with_attended_appointment(self, db: None) -> None:
        """Paciente con cita atendida aparece en 'recent'."""
        # Arrange
        tenant = TenantFactory()
        attended_patient = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, attended_patient, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="recent")

            # Assert
            assert attended_patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_recent_excludes_patient_without_attended_appointment(self, db: None) -> None:
        """Paciente sin ninguna cita atendida NO aparece en 'recent'."""
        # Arrange
        tenant = TenantFactory()
        no_appointment_patient = PatientFactory(tenant=tenant, is_active=True)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="recent")

            # Assert
            assert no_appointment_patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_recent_excludes_patient_with_only_cancelled_appointments(
        self, db: None
    ) -> None:
        """Solo citas canceladas no cuenta como 'atendido'."""
        # Arrange
        tenant = TenantFactory()
        cancelled_only = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment(tenant, cancelled_only, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="recent")

            # Assert
            assert cancelled_only.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_recent_returns_exact_set(self, db: None) -> None:
        """'recent' devuelve exactamente los pacientes con cita atendida."""
        # Arrange
        tenant = TenantFactory()
        attended = PatientFactory(tenant=tenant, is_active=True)
        no_cita = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, attended, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="recent")
            ids = set(qs.values_list("id", flat=True))

            # Assert — exactamente uno
            assert ids == {attended.id}
            assert no_cita.id not in ids
        finally:
            _deactivate_tenant()


# ===========================================================================
# Segmento "week"
# ===========================================================================


class TestSegmentWeek:
    """Segmento 'week': atendidos en la semana calendario actual."""

    def test_week_includes_patient_attended_this_week(self, db: None) -> None:
        """Paciente atendido dentro de la semana actual aparece en 'week'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        # Crear cita atendida hoy (dentro de la semana)
        now = timezone.now()
        _attended_appointment(tenant, patient, now)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="week")

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_week_excludes_patient_attended_last_week(self, db: None) -> None:
        """Paciente atendido la semana pasada NO aparece en 'week'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        # Cita atendida hace 8 días (semana pasada con margen)
        last_week = timezone.now() - datetime.timedelta(days=8)
        _attended_appointment(tenant, patient, last_week)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="week")

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_week_excludes_patient_with_no_appointment(self, db: None) -> None:
        """Paciente sin citas no aparece en 'week'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="week")

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_week_tenant_isolation(self, db: None) -> None:
        """'week' no filtra citas de otro tenant aunque sean de esta semana."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b, is_active=True)
        now = timezone.now()
        _attended_appointment(tenant_b, patient_b, now)

        # Activar contexto del tenant A (sin ninguna cita)
        _activate_tenant(tenant_a)
        try:
            # Act
            qs = patient_list(segment="week")

            # Assert — el paciente del tenant B no aparece
            assert patient_b.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()


# ===========================================================================
# Segmento "month"
# ===========================================================================


class TestSegmentMonth:
    """Segmento 'month': atendidos en el mes calendario actual."""

    def test_month_includes_patient_attended_this_month(self, db: None) -> None:
        """Paciente atendido este mes aparece en 'month'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        now = timezone.now()
        _attended_appointment(tenant, patient, now)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="month")

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_month_excludes_patient_attended_previous_month(self, db: None) -> None:
        """Paciente atendido el mes pasado NO aparece en 'month'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        # Hace 35 días — siempre el mes anterior
        last_month = timezone.now() - datetime.timedelta(days=35)
        _attended_appointment(tenant, patient, last_month)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="month")

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_month_excludes_patient_with_no_appointment(self, db: None) -> None:
        """Paciente sin citas no aparece en 'month'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="month")

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()


# ===========================================================================
# Segmento "date"
# ===========================================================================


class TestSegmentDate:
    """Segmento 'date': atendidos entre date_from y date_to inclusive."""

    def test_date_includes_patient_attended_in_range(self, db: None) -> None:
        """Paciente atendido dentro del rango aparece en 'date'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, patient, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(
                segment="date",
                date_from=_FIXED_DATE_FROM,
                date_to=_FIXED_DATE_TO,
            )

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_date_includes_patient_attended_on_date_from(self, db: None) -> None:
        """Paciente atendido exactamente en date_from (límite inferior inclusive)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        # Cita al inicio del día de date_from
        dt_from_start = datetime.datetime(2030, 1, 10, 8, 0, 0, tzinfo=datetime.timezone.utc)
        _attended_appointment(tenant, patient, dt_from_start)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(
                segment="date",
                date_from=_FIXED_DATE_FROM,
                date_to=_FIXED_DATE_TO,
            )

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_date_includes_patient_attended_on_date_to(self, db: None) -> None:
        """Paciente atendido exactamente en date_to (límite superior inclusive)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        # Cita en date_to (20 ene 2030) al mediodía UTC
        dt_to_noon = datetime.datetime(2030, 1, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
        _attended_appointment(tenant, patient, dt_to_noon)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(
                segment="date",
                date_from=_FIXED_DATE_FROM,
                date_to=_FIXED_DATE_TO,
            )

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_date_excludes_patient_attended_before_range(self, db: None) -> None:
        """Paciente atendido antes del rango NO aparece en 'date'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, patient, _FIXED_DT_OUT_RANGE_BEFORE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(
                segment="date",
                date_from=_FIXED_DATE_FROM,
                date_to=_FIXED_DATE_TO,
            )

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_date_excludes_patient_attended_after_range(self, db: None) -> None:
        """Paciente atendido después del rango NO aparece en 'date'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, patient, _FIXED_DT_OUT_RANGE_AFTER)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(
                segment="date",
                date_from=_FIXED_DATE_FROM,
                date_to=_FIXED_DATE_TO,
            )

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_date_returns_exact_set_in_range(self, db: None) -> None:
        """'date' devuelve exactamente los pacientes atendidos en el rango dado."""
        # Arrange
        tenant = TenantFactory()
        in_range = PatientFactory(tenant=tenant, is_active=True)
        before_range = PatientFactory(tenant=tenant, is_active=True)
        no_cita = PatientFactory(tenant=tenant, is_active=True)

        _attended_appointment(tenant, in_range, _FIXED_DT_IN_RANGE)
        _attended_appointment(tenant, before_range, _FIXED_DT_OUT_RANGE_BEFORE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(
                segment="date",
                date_from=_FIXED_DATE_FROM,
                date_to=_FIXED_DATE_TO,
            )
            ids = set(qs.values_list("id", flat=True))

            # Assert — exactamente el de en rango
            assert ids == {in_range.id}
            assert before_range.id not in ids
            assert no_cita.id not in ids
        finally:
            _deactivate_tenant()

    def test_date_tenant_isolation(self, db: None) -> None:
        """'date' no filtra citas de otro tenant aunque caigan en el rango."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b, is_active=True)
        _attended_appointment(tenant_b, patient_b, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant_a)
        try:
            # Act
            qs = patient_list(
                segment="date",
                date_from=_FIXED_DATE_FROM,
                date_to=_FIXED_DATE_TO,
            )

            # Assert — el paciente del tenant B no aparece
            assert patient_b.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()


# ===========================================================================
# Segmento "potential"
# ===========================================================================


class TestSegmentPotential:
    """Segmento 'potential': nunca atendidos + tienen citas canceladas o reagendadas."""

    def test_potential_includes_patient_with_cancelled_and_no_attended(
        self, db: None
    ) -> None:
        """Paciente con cita cancelada y nunca atendido aparece en 'potential'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment(tenant, patient, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="potential")

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_potential_includes_patient_with_rescheduled_and_no_attended(
        self, db: None
    ) -> None:
        """Paciente con cita reagendada (reschedule_count>0) y nunca atendido
        aparece en 'potential'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _rescheduled_appointment(tenant, patient, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="potential")

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_potential_excludes_patient_with_attended_appointment(
        self, db: None
    ) -> None:
        """Paciente que ya tiene al menos una cita atendida NO es 'potential',
        aunque también tenga citas canceladas."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, patient, _FIXED_DT_IN_RANGE)
        _cancelled_appointment(
            tenant, patient, _FIXED_DT_IN_RANGE + datetime.timedelta(days=5)
        )

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="potential")

            # Assert — ya fue atendido, aunque también tenga cancelada
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_potential_excludes_patient_with_no_appointments_at_all(
        self, db: None
    ) -> None:
        """Paciente sin ninguna cita NO aparece en 'potential' (nunca tuvo interacción)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="potential")

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_potential_returns_exact_set(self, db: None) -> None:
        """'potential' devuelve exactamente los pacientes que cumplen la condición."""
        # Arrange
        tenant = TenantFactory()
        cancelled_never_attended = PatientFactory(tenant=tenant, is_active=True)
        rescheduled_never_attended = PatientFactory(tenant=tenant, is_active=True)
        attended_and_cancelled = PatientFactory(tenant=tenant, is_active=True)
        no_appointments = PatientFactory(tenant=tenant, is_active=True)

        _cancelled_appointment(tenant, cancelled_never_attended, _FIXED_DT_IN_RANGE)
        _rescheduled_appointment(
            tenant, rescheduled_never_attended, _FIXED_DT_IN_RANGE + datetime.timedelta(hours=2)
        )
        _attended_appointment(
            tenant, attended_and_cancelled, _FIXED_DT_IN_RANGE + datetime.timedelta(hours=4)
        )
        _cancelled_appointment(
            tenant, attended_and_cancelled, _FIXED_DT_IN_RANGE + datetime.timedelta(days=2)
        )

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="potential")
            ids = set(qs.values_list("id", flat=True))

            # Assert
            assert ids == {cancelled_never_attended.id, rescheduled_never_attended.id}
            assert attended_and_cancelled.id not in ids
            assert no_appointments.id not in ids
        finally:
            _deactivate_tenant()

    def test_potential_tenant_isolation(self, db: None) -> None:
        """'potential' no devuelve pacientes potenciales de otro tenant."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b, is_active=True)
        _cancelled_appointment(tenant_b, patient_b, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant_a)
        try:
            # Act
            qs = patient_list(segment="potential")

            # Assert
            assert patient_b.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()


# ===========================================================================
# Segmento "favorites"
# ===========================================================================


class TestSegmentFavorites:
    """Segmento 'favorites': solo pacientes con la etiqueta kind=favorite."""

    def test_favorites_includes_patient_with_favorite_label(self, db: None) -> None:
        """Paciente con etiqueta kind=favorite aparece en 'favorites'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _assign_system_label(patient, tenant, PatientCategory.Kind.FAVORITE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="favorites")

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_favorites_excludes_patient_without_favorite_label(self, db: None) -> None:
        """Paciente sin etiqueta favorite NO aparece en 'favorites'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        # No se asigna ninguna etiqueta de sistema

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="favorites")

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_favorites_returns_exact_set(self, db: None) -> None:
        """'favorites' devuelve exactamente los que tienen la etiqueta favorite."""
        # Arrange
        tenant = TenantFactory()
        fav = PatientFactory(tenant=tenant, is_active=True)
        not_fav = PatientFactory(tenant=tenant, is_active=True)
        _assign_system_label(fav, tenant, PatientCategory.Kind.FAVORITE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="favorites")
            ids = set(qs.values_list("id", flat=True))

            # Assert
            assert ids == {fav.id}
            assert not_fav.id not in ids
        finally:
            _deactivate_tenant()

    def test_favorites_tenant_isolation(self, db: None) -> None:
        """'favorites' no devuelve favoritos de otro tenant.

        Cada tenant tiene SU PROPIA etiqueta de sistema kind=favorite.
        La etiqueta del tenant B no es visible en el contexto del tenant A.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        fav_b = PatientFactory(tenant=tenant_b, is_active=True)
        _assign_system_label(fav_b, tenant_b, PatientCategory.Kind.FAVORITE)

        _activate_tenant(tenant_a)
        try:
            # Act
            qs = patient_list(segment="favorites")

            # Assert — tenant A no tiene favoritos
            assert fav_b.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()


# ===========================================================================
# Segmento "vip"
# ===========================================================================


class TestSegmentVip:
    """Segmento 'vip': solo pacientes con la etiqueta kind=vip."""

    def test_vip_includes_patient_with_vip_label(self, db: None) -> None:
        """Paciente con etiqueta kind=vip aparece en 'vip'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _assign_system_label(patient, tenant, PatientCategory.Kind.VIP)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="vip")

            # Assert
            assert patient.id in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_vip_excludes_patient_without_vip_label(self, db: None) -> None:
        """Paciente sin etiqueta vip NO aparece en 'vip'."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        # No se asigna etiqueta VIP

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="vip")

            # Assert
            assert patient.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()

    def test_vip_returns_exact_set(self, db: None) -> None:
        """'vip' devuelve exactamente los que tienen la etiqueta vip."""
        # Arrange
        tenant = TenantFactory()
        vip = PatientFactory(tenant=tenant, is_active=True)
        not_vip = PatientFactory(tenant=tenant, is_active=True)
        _assign_system_label(vip, tenant, PatientCategory.Kind.VIP)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="vip")
            ids = set(qs.values_list("id", flat=True))

            # Assert
            assert ids == {vip.id}
            assert not_vip.id not in ids
        finally:
            _deactivate_tenant()

    def test_vip_tenant_isolation(self, db: None) -> None:
        """'vip' no devuelve VIPs de otro tenant.

        Cada tenant tiene SU PROPIA etiqueta de sistema kind=vip.
        La etiqueta del tenant B no es visible en el contexto del tenant A.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        vip_b = PatientFactory(tenant=tenant_b, is_active=True)
        _assign_system_label(vip_b, tenant_b, PatientCategory.Kind.VIP)

        _activate_tenant(tenant_a)
        try:
            # Act
            qs = patient_list(segment="vip")

            # Assert — tenant A no tiene VIPs
            assert vip_b.id not in set(qs.values_list("id", flat=True))
        finally:
            _deactivate_tenant()


# ===========================================================================
# Anotaciones: last_seen / attended_count / cancelled_count / rescheduled_count
# ===========================================================================


class TestAnnotations:
    """Las anotaciones del selector reflejan correctamente los conteos reales."""

    def test_attended_count_reflects_number_of_attended_appointments(
        self, db: None
    ) -> None:
        """attended_count cuenta exactamente las citas con status=attended."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, patient, _FIXED_DT_IN_RANGE)
        _attended_appointment(
            tenant, patient, _FIXED_DT_IN_RANGE + datetime.timedelta(hours=3)
        )

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="all")
            result = qs.get(id=patient.id)

            # Assert
            assert result.attended_count == 2
        finally:
            _deactivate_tenant()

    def test_attended_count_is_zero_for_patient_with_no_attended_appointments(
        self, db: None
    ) -> None:
        """Paciente sin citas atendidas tiene attended_count=0."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment(tenant, patient, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="all")
            result = qs.get(id=patient.id)

            # Assert
            assert result.attended_count == 0
        finally:
            _deactivate_tenant()

    def test_last_seen_is_null_for_patient_never_attended(self, db: None) -> None:
        """last_seen es None para paciente sin ninguna cita atendida."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="all")
            result = qs.get(id=patient.id)

            # Assert
            assert result.last_seen is None
        finally:
            _deactivate_tenant()

    def test_last_seen_reflects_most_recent_attended_appointment(
        self, db: None
    ) -> None:
        """last_seen apunta a la cita atendida más reciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        dt_old = _FIXED_DT_IN_RANGE
        dt_new = _FIXED_DT_IN_RANGE + datetime.timedelta(hours=6)
        _attended_appointment(tenant, patient, dt_old)
        _attended_appointment(tenant, patient, dt_new)

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="all")
            result = qs.get(id=patient.id)

            # Assert — la más reciente
            assert result.last_seen == dt_new
        finally:
            _deactivate_tenant()

    def test_cancelled_count_reflects_number_of_cancelled_appointments(
        self, db: None
    ) -> None:
        """cancelled_count cuenta exactamente las citas con status=cancelled."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment(tenant, patient, _FIXED_DT_IN_RANGE)
        _cancelled_appointment(
            tenant, patient, _FIXED_DT_IN_RANGE + datetime.timedelta(hours=3)
        )

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="all")
            result = qs.get(id=patient.id)

            # Assert
            assert result.cancelled_count == 2
        finally:
            _deactivate_tenant()

    def test_rescheduled_count_reflects_appointments_with_reschedule_count_gt_0(
        self, db: None
    ) -> None:
        """rescheduled_count cuenta citas con reschedule_count>0 (las que fueron reagendadas)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _rescheduled_appointment(tenant, patient, _FIXED_DT_IN_RANGE)
        # Una cita normal (sin reagendar)
        doctor = DoctorFactory(tenant=tenant)
        AppointmentFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            consultorio=None,
            status=Appointment.Status.SCHEDULED,
            reschedule_count=0,
            starts_at=_FIXED_DT_IN_RANGE + datetime.timedelta(hours=2),
            ends_at=_FIXED_DT_IN_RANGE + datetime.timedelta(hours=3),
        )

        _activate_tenant(tenant)
        try:
            # Act
            qs = patient_list(segment="all")
            result = qs.get(id=patient.id)

            # Assert — solo la reagendada cuenta
            assert result.rescheduled_count == 1
        finally:
            _deactivate_tenant()


# ===========================================================================
# Anotación "last_reason" (motivo de la última cita cancelada/reagendada)
# ===========================================================================


class TestLastReasonAnnotation:
    """La anotación last_reason expone el motivo ('¿a qué viene?') de la cita
    cancelada/reagendada más reciente, para precargar el motivo al reagendar."""

    def test_last_reason_is_most_recent_cancelled_or_rescheduled(self, db: None) -> None:
        """Devuelve el reason de la cita cancelada/reagendada más reciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        doctor = DoctorFactory(tenant=tenant)
        # Cancelada antigua con un motivo.
        AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, consultorio=None,
            status=Appointment.Status.CANCELLED, reason="Dolor de muela",
            starts_at=_FIXED_DT_IN_RANGE,
            ends_at=_FIXED_DT_IN_RANGE + datetime.timedelta(hours=1),
        )
        # Reagendada más reciente con otro motivo → debe ganar.
        AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, consultorio=None,
            status=Appointment.Status.SCHEDULED, reschedule_count=1, reason="Revisión anual",
            starts_at=_FIXED_DT_IN_RANGE + datetime.timedelta(days=5),
            ends_at=_FIXED_DT_IN_RANGE + datetime.timedelta(days=5, hours=1),
        )

        _activate_tenant(tenant)
        try:
            # Act
            result = patient_list(segment="all").get(id=patient.id)

            # Assert
            assert result.last_reason == "Revisión anual"
        finally:
            _deactivate_tenant()

    def test_last_reason_none_without_cancelled_or_rescheduled(self, db: None) -> None:
        """Sin citas canceladas/reagendadas (solo atendida), last_reason es None."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, patient, _FIXED_DT_IN_RANGE)

        _activate_tenant(tenant)
        try:
            # Act
            result = patient_list(segment="all").get(id=patient.id)

            # Assert
            assert result.last_reason is None
        finally:
            _deactivate_tenant()
