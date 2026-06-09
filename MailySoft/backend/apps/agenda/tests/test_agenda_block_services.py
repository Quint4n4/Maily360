"""
Tests de services/selectors para la Feature 2: AgendaBlock (reuniones y bloqueos).

Cubre:
- agenda_block_create: camino feliz (clínica entera, doctor específico, consultorio,
  tipo meeting), validación ends_at<=starts_at, doctor/consultorio de otro tenant.
- agenda_block_delete: soft-delete; el evento desaparece de las queries normales.
- agenda_block_update: cambio de título/horario/all_day/notas; validación fin<=inicio.
- agenda_block_list: filtro por rango de fechas (overlap semántico).
- agenda_block_get: aislamiento multi-tenant.

LO MÁS IMPORTANTE — _check_block_overlap vía appointment_create:
  - Bloqueo de TODA la clínica (doctor=None, consultorio=None) impide citas que solapen.
  - Cita FUERA del rango del bloqueo se agenda sin error.
  - Bloqueo de doctor específico bloquea ESE doctor; NO bloquea otro doctor.
  - Bloqueo de consultorio específico bloquea ESE consultorio; NO bloquea otro consultorio.
  - Reunión (kind=meeting) bloquea igual que un bloqueo (kind=block).
  - Aislamiento multi-tenant: bloqueo de un tenant NO afecta citas de otro tenant.

Patrón: AAA. Todas tocan BD → fixture db.
"""

import datetime
from contextlib import contextmanager
from typing import Generator

import pytest
from django.core.exceptions import ValidationError

from apps.agenda.models import AgendaBlock, Appointment
from apps.agenda.selectors import agenda_block_get, agenda_block_list
from apps.agenda.services import (
    agenda_block_create,
    agenda_block_delete,
    agenda_block_update,
    appointment_create,
)
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from tests.factories import (
    ConsultorioFactory,
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_DT = datetime.datetime(2031, 6, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
_ONE_HOUR = datetime.timedelta(hours=1)
_TWO_HOURS = datetime.timedelta(hours=2)


@contextmanager
def _tenant_ctx(tenant: object) -> Generator[None, None, None]:
    """Activa el contexto de tenant para que TenantManager filtre por él."""
    set_current_tenant(tenant)  # type: ignore[arg-type]
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


def _mk_block(
    *,
    tenant: object,
    user: object,
    starts_at: datetime.datetime = _BASE_DT,
    ends_at: datetime.datetime | None = None,
    kind: str = AgendaBlock.Kind.BLOCK,
    title: str = "",
    doctor_id: object = None,
    consultorio_id: object = None,
    all_day: bool = False,
    notes: str = "",
) -> AgendaBlock:
    """Helper: crea un AgendaBlock con contexto de tenant activo."""
    with _tenant_ctx(tenant):
        return agenda_block_create(
            tenant=tenant,  # type: ignore[arg-type]
            user=user,  # type: ignore[arg-type]
            kind=kind,
            title=title,
            doctor_id=doctor_id,  # type: ignore[arg-type]
            consultorio_id=consultorio_id,  # type: ignore[arg-type]
            starts_at=starts_at,
            ends_at=ends_at or (starts_at + _ONE_HOUR),
            all_day=all_day,
            notes=notes,
        )


def _mk_appointment(
    *,
    tenant: object,
    user: object,
    doctor: object,
    patient: object,
    starts_at: datetime.datetime = _BASE_DT,
    ends_at: datetime.datetime | None = None,
    consultorio_id: object = None,
) -> Appointment:
    """Helper: crea una cita vía service con contexto de tenant activo."""
    with _tenant_ctx(tenant):
        return appointment_create(
            tenant=tenant,  # type: ignore[arg-type]
            user=user,  # type: ignore[arg-type]
            patient_id=patient.id,  # type: ignore[union-attr]
            doctor_id=doctor.id,  # type: ignore[union-attr]
            starts_at=starts_at,
            ends_at=ends_at or (starts_at + _ONE_HOUR),
            consultorio_id=consultorio_id,  # type: ignore[arg-type]
        )


# ===========================================================================
# agenda_block_create — camino feliz
# ===========================================================================


class TestAgendaBlockCreateOk:
    """Creación de bloques en distintos alcances."""

    def test_create_clinic_wide_block_ok(self, db: None) -> None:
        """Bloqueo de toda la clínica (doctor=None, consultorio=None) se crea sin error."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        block = _mk_block(
            tenant=tenant, user=user, title="Día festivo", kind=AgendaBlock.Kind.BLOCK
        )

        # Assert
        assert block.pk is not None
        assert block.doctor is None
        assert block.consultorio is None
        assert block.kind == AgendaBlock.Kind.BLOCK
        assert block.tenant_id == tenant.id  # type: ignore[union-attr]

    def test_create_doctor_specific_block_ok(self, db: None) -> None:
        """Bloqueo de un médico específico se crea con la FK de doctor."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)

        # Act
        block = _mk_block(
            tenant=tenant,
            user=user,
            doctor_id=doctor.id,
            title="Vacaciones Dr.",
        )

        # Assert
        assert block.doctor_id == doctor.id
        assert block.consultorio is None

    def test_create_consultorio_specific_block_ok(self, db: None) -> None:
        """Bloqueo de un consultorio específico se crea con la FK de consultorio."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        consultorio = ConsultorioFactory(tenant=tenant)

        # Act
        block = _mk_block(
            tenant=tenant,
            user=user,
            consultorio_id=consultorio.id,
            title="Mantenimiento consultorio",
        )

        # Assert
        assert block.consultorio_id == consultorio.id
        assert block.doctor is None

    def test_create_meeting_block_ok(self, db: None) -> None:
        """Evento de tipo MEETING se crea correctamente con kind=meeting."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        block = _mk_block(
            tenant=tenant,
            user=user,
            kind=AgendaBlock.Kind.MEETING,
            title="Junta de equipo",
        )

        # Assert
        assert block.kind == AgendaBlock.Kind.MEETING


# ===========================================================================
# agenda_block_create — validaciones
# ===========================================================================


class TestAgendaBlockCreateValidation:
    """Validaciones al crear AgendaBlock."""

    def test_create_block_ends_before_starts_raises_validation_error(
        self, db: None
    ) -> None:
        """ends_at <= starts_at lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="posterior"):
            with _tenant_ctx(tenant):
                agenda_block_create(
                    tenant=tenant,  # type: ignore[arg-type]
                    user=user,  # type: ignore[arg-type]
                    kind=AgendaBlock.Kind.BLOCK,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT - datetime.timedelta(minutes=30),
                )

    def test_create_block_ends_equal_starts_raises_validation_error(
        self, db: None
    ) -> None:
        """ends_at == starts_at también debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError):
            with _tenant_ctx(tenant):
                agenda_block_create(
                    tenant=tenant,  # type: ignore[arg-type]
                    user=user,  # type: ignore[arg-type]
                    kind=AgendaBlock.Kind.BLOCK,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT,  # igual = inválido
                )

    def test_create_block_with_doctor_from_other_tenant_raises(
        self, db: None
    ) -> None:
        """Doctor de otro tenant lanza ValidationError."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        doctor_b = DoctorFactory(tenant=tenant_b)

        # Act & Assert
        with pytest.raises(ValidationError, match="[Mm]édico"):
            with _tenant_ctx(tenant_a):
                agenda_block_create(
                    tenant=tenant_a,  # type: ignore[arg-type]
                    user=user,  # type: ignore[arg-type]
                    kind=AgendaBlock.Kind.BLOCK,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                    doctor_id=doctor_b.id,
                )

    def test_create_block_with_consultorio_from_other_tenant_raises(
        self, db: None
    ) -> None:
        """Consultorio de otro tenant lanza ValidationError."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        consultorio_b = ConsultorioFactory(tenant=tenant_b)

        # Act & Assert
        with pytest.raises(ValidationError, match="[Cc]onsultorio"):
            with _tenant_ctx(tenant_a):
                agenda_block_create(
                    tenant=tenant_a,  # type: ignore[arg-type]
                    user=user,  # type: ignore[arg-type]
                    kind=AgendaBlock.Kind.BLOCK,
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                    consultorio_id=consultorio_b.id,
                )

    def test_create_block_invalid_kind_raises_validation_error(
        self, db: None
    ) -> None:
        """kind con valor fuera de los choices lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="[Tt]ipo"):
            with _tenant_ctx(tenant):
                agenda_block_create(
                    tenant=tenant,  # type: ignore[arg-type]
                    user=user,  # type: ignore[arg-type]
                    kind="vacaciones_especiales",  # inválido
                    starts_at=_BASE_DT,
                    ends_at=_BASE_DT + _ONE_HOUR,
                )


# ===========================================================================
# agenda_block_delete — soft delete
# ===========================================================================


class TestAgendaBlockDelete:
    """agenda_block_delete realiza soft-delete."""

    def test_delete_block_sets_deleted_at(self, db: None) -> None:
        """Después de delete, deleted_at queda seteado."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block = _mk_block(tenant=tenant, user=user, title="Para borrar")

        # Act
        deleted = agenda_block_delete(agenda_block=block, user=user)  # type: ignore[arg-type]

        # Assert
        assert deleted.deleted_at is not None
        block.refresh_from_db()
        assert block.deleted_at is not None

    def test_deleted_block_invisible_to_list(self, db: None) -> None:
        """Un bloque soft-eliminado no aparece en agenda_block_list."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block = _mk_block(tenant=tenant, user=user, title="Bloqueo a eliminar")
        block_id = block.pk

        # Verificar que antes de borrar sí aparece
        with _tenant_ctx(tenant):
            ids_before = set(agenda_block_list().values_list("id", flat=True))
        assert block_id in ids_before

        # Act
        agenda_block_delete(agenda_block=block, user=user)  # type: ignore[arg-type]

        # Assert — ya no aparece en la lista
        with _tenant_ctx(tenant):
            ids_after = set(agenda_block_list().values_list("id", flat=True))
        assert block_id not in ids_after

    def test_deleted_block_still_in_db_via_all_objects(self, db: None) -> None:
        """El bloque soft-eliminado sigue existiendo físicamente en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block = _mk_block(tenant=tenant, user=user, title="Persiste")
        block_id = block.pk

        # Act
        agenda_block_delete(agenda_block=block, user=user)  # type: ignore[arg-type]

        # Assert — accesible con all_objects (bypass del soft-delete filter)
        assert AgendaBlock.all_objects.filter(id=block_id).exists()


# ===========================================================================
# agenda_block_update — edición de campos
# ===========================================================================


class TestAgendaBlockUpdate:
    """agenda_block_update modifica título, horario, all_day y notas."""

    def test_update_title_only(self, db: None) -> None:
        """Actualizar el título persiste el cambio en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block = _mk_block(tenant=tenant, user=user, title="Título original")

        # Act
        updated = agenda_block_update(
            agenda_block=block, user=user, title="Título actualizado"  # type: ignore[arg-type]
        )

        # Assert
        assert updated.title == "Título actualizado"
        block.refresh_from_db()
        assert block.title == "Título actualizado"

    def test_update_starts_at_and_ends_at(self, db: None) -> None:
        """Cambiar starts_at y ends_at a valores válidos persiste en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block = _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
        )
        new_starts = _BASE_DT + _TWO_HOURS
        new_ends = new_starts + _ONE_HOUR

        # Act
        updated = agenda_block_update(
            agenda_block=block,  # type: ignore[arg-type]
            user=user,
            starts_at=new_starts,
            ends_at=new_ends,
        )

        # Assert
        assert updated.starts_at == new_starts
        assert updated.ends_at == new_ends

    def test_update_ends_before_starts_raises_validation_error(
        self, db: None
    ) -> None:
        """ends_at <= starts_at después de update lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block = _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
        )

        # Act & Assert — intentar poner ends antes de starts
        with pytest.raises(ValidationError, match="posterior"):
            agenda_block_update(
                agenda_block=block,  # type: ignore[arg-type]
                user=user,
                starts_at=_BASE_DT + _TWO_HOURS,
                ends_at=_BASE_DT,  # end < start nuevo
            )

    def test_update_all_day_and_notes(self, db: None) -> None:
        """Actualizar all_day y notes funciona correctamente."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block = _mk_block(tenant=tenant, user=user, all_day=False, notes="")

        # Act
        updated = agenda_block_update(
            agenda_block=block,  # type: ignore[arg-type]
            user=user,
            all_day=True,
            notes="Todo el día bloqueado por mantenimiento.",
        )

        # Assert
        assert updated.all_day is True
        assert updated.notes == "Todo el día bloqueado por mantenimiento."


# ===========================================================================
# agenda_block_list — filtro por rango
# ===========================================================================


class TestAgendaBlockList:
    """agenda_block_list filtra eventos que solapan el rango dado."""

    def test_list_returns_overlapping_events(self, db: None) -> None:
        """Evento que solapa el rango [date_from, date_to] aparece en la lista."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        # Bloqueo 10:00-11:00
        block = _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
            title="Dentro del rango",
        )
        # date_from=09:30, date_to=10:30 → solapa con 10:00-11:00
        date_from = _BASE_DT - datetime.timedelta(minutes=30)
        date_to = _BASE_DT + datetime.timedelta(minutes=30)

        # Act
        with _tenant_ctx(tenant):
            ids = set(
                agenda_block_list(date_from=date_from, date_to=date_to).values_list(
                    "id", flat=True
                )
            )

        # Assert
        assert block.id in ids

    def test_list_excludes_non_overlapping_events(self, db: None) -> None:
        """Evento fuera del rango no aparece en la lista."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        # Bloqueo 10:00-11:00
        block = _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
            title="Fuera del rango",
        )
        # Rango 11:00-12:00 → NO solapa (fin exacto = no overlap con [))
        date_from = _BASE_DT + _ONE_HOUR
        date_to = _BASE_DT + _TWO_HOURS

        # Act
        with _tenant_ctx(tenant):
            ids = set(
                agenda_block_list(date_from=date_from, date_to=date_to).values_list(
                    "id", flat=True
                )
            )

        # Assert
        assert block.id not in ids

    def test_list_without_range_returns_all_events(self, db: None) -> None:
        """Sin date_from ni date_to, retorna todos los eventos del tenant."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block1 = _mk_block(
            tenant=tenant, user=user, starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR
        )
        block2 = _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT + _TWO_HOURS,
            ends_at=_BASE_DT + _TWO_HOURS + _ONE_HOUR,
        )

        # Act
        with _tenant_ctx(tenant):
            ids = set(agenda_block_list().values_list("id", flat=True))

        # Assert
        assert block1.id in ids
        assert block2.id in ids

    def test_list_isolation_other_tenant_blocks_not_visible(self, db: None) -> None:
        """Eventos del tenant B no aparecen en la lista del tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        block_a = _mk_block(
            tenant=tenant_a, user=user,
            starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
        )
        _mk_block(
            tenant=tenant_b, user=user,
            starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
        )

        # Act — con contexto del tenant A
        with _tenant_ctx(tenant_a):
            ids = set(agenda_block_list().values_list("id", flat=True))

        # Assert — solo el bloque del tenant A
        assert block_a.id in ids
        assert len(ids) == 1, (
            f"Fuga cross-tenant en agenda_block_list: {len(ids)} en lugar de 1."
        )


# ===========================================================================
# agenda_block_get — aislamiento multi-tenant
# ===========================================================================


class TestAgendaBlockGetIsolation:
    """agenda_block_get usa TenantManager: bloque de otro tenant → DoesNotExist."""

    def test_get_block_of_other_tenant_raises_does_not_exist(self, db: None) -> None:
        """agenda_block_get con UUID de otro tenant lanza DoesNotExist (→ 404)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        block_b = _mk_block(
            tenant=tenant_b, user=user,
            starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
        )

        # Act — con contexto del tenant A
        with _tenant_ctx(tenant_a):
            with pytest.raises(AgendaBlock.DoesNotExist):
                agenda_block_get(block_id=block_b.id)

    def test_get_block_of_own_tenant_ok(self, db: None) -> None:
        """agenda_block_get retorna el bloque cuando pertenece al tenant activo."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        block = _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
        )

        # Act
        with _tenant_ctx(tenant):
            result = agenda_block_get(block_id=block.id)

        # Assert
        assert result.id == block.id


# ===========================================================================
# _check_block_overlap — bloqueo real de citas (lo más importante)
# ===========================================================================


class TestCheckBlockOverlapClinicWide:
    """Bloqueo de TODA la clínica (doctor=None, consultorio=None) impide citas."""

    def test_clinic_wide_block_prevents_overlapping_appointment(
        self, db: None
    ) -> None:
        """Una cita que solapa un bloqueo de toda la clínica lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Bloqueo de toda la clínica 10:00-12:00
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _TWO_HOURS,
            kind=AgendaBlock.Kind.BLOCK,
        )

        # Act & Assert — cita 10:30-11:30 cae dentro del bloqueo
        with pytest.raises(ValidationError, match="[Bb]loqueado"):
            _mk_appointment(
                tenant=tenant, user=user, doctor=doctor, patient=patient,
                starts_at=_BASE_DT + datetime.timedelta(minutes=30),
                ends_at=_BASE_DT + datetime.timedelta(minutes=90),
            )

    def test_appointment_outside_block_range_is_allowed(self, db: None) -> None:
        """Cita fuera del rango del bloqueo se agenda sin error."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Bloqueo 10:00-11:00
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
        )

        # Act — cita 11:00-12:00 (empieza exactamente cuando termina el bloqueo → OK)
        appt = _mk_appointment(
            tenant=tenant, user=user, doctor=doctor, patient=patient,
            starts_at=_BASE_DT + _ONE_HOUR,
            ends_at=_BASE_DT + _TWO_HOURS,
        )

        # Assert — cita creada sin error
        assert appt.pk is not None

    def test_clinic_wide_block_prevents_appointment_with_any_doctor(
        self, db: None
    ) -> None:
        """El bloqueo de toda la clínica impide citas de CUALQUIER médico."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor_1 = DoctorFactory(tenant=tenant)
        doctor_2 = DoctorFactory(tenant=tenant)
        patient_1 = PatientFactory(tenant=tenant)
        patient_2 = PatientFactory(tenant=tenant)

        # Bloqueo de toda la clínica
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _TWO_HOURS,
        )

        # Act & Assert — ambos médicos quedan bloqueados
        with pytest.raises(ValidationError, match="[Bb]loqueado"):
            _mk_appointment(
                tenant=tenant, user=user, doctor=doctor_1, patient=patient_1,
                starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
            )

        with pytest.raises(ValidationError, match="[Bb]loqueado"):
            _mk_appointment(
                tenant=tenant, user=user, doctor=doctor_2, patient=patient_2,
                starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
            )


class TestCheckBlockOverlapDoctorSpecific:
    """Bloqueo de doctor específico solo afecta a ese médico."""

    def test_doctor_block_prevents_appointment_for_that_doctor(
        self, db: None
    ) -> None:
        """Bloqueo del doctor A impide citas de ese doctor en el horario bloqueado."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor_a = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Bloqueo solo del doctor_a
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
            doctor_id=doctor_a.id,
        )

        # Act & Assert — cita del doctor_a en ese horario falla
        with pytest.raises(ValidationError, match="[Bb]loqueado"):
            _mk_appointment(
                tenant=tenant, user=user, doctor=doctor_a, patient=patient,
                starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
            )

    def test_doctor_block_does_not_prevent_appointment_for_other_doctor(
        self, db: None
    ) -> None:
        """Bloqueo del doctor A NO impide citas del doctor B en el mismo horario."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor_a = DoctorFactory(tenant=tenant)
        doctor_b = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Bloqueo solo del doctor_a
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
            doctor_id=doctor_a.id,
        )

        # Act — cita del doctor_b en el mismo horario: NO debe bloquearse
        appt = _mk_appointment(
            tenant=tenant, user=user, doctor=doctor_b, patient=patient,
            starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
        )

        # Assert
        assert appt.pk is not None
        assert appt.doctor_id == doctor_b.id


class TestCheckBlockOverlapConsultorioSpecific:
    """Bloqueo de consultorio específico solo afecta a ese consultorio."""

    def test_consultorio_block_prevents_appointment_in_that_consultorio(
        self, db: None
    ) -> None:
        """Bloqueo del consultorio A impide citas en ese consultorio en el horario."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        consultorio_a = ConsultorioFactory(tenant=tenant)

        # Bloqueo del consultorio_a
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
            consultorio_id=consultorio_a.id,
        )

        # Act & Assert — cita en consultorio_a falla
        with pytest.raises(ValidationError, match="[Bb]loqueado"):
            _mk_appointment(
                tenant=tenant, user=user, doctor=doctor, patient=patient,
                starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
                consultorio_id=consultorio_a.id,
            )

    def test_consultorio_block_does_not_prevent_appointment_in_other_consultorio(
        self, db: None
    ) -> None:
        """Bloqueo del consultorio A NO impide citas en el consultorio B."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        consultorio_a = ConsultorioFactory(tenant=tenant)
        consultorio_b = ConsultorioFactory(tenant=tenant)

        # Bloqueo solo del consultorio_a
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
            consultorio_id=consultorio_a.id,
        )

        # Act — cita en consultorio_b en el mismo horario: NO debe bloquearse
        appt = _mk_appointment(
            tenant=tenant, user=user, doctor=doctor, patient=patient,
            starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
            consultorio_id=consultorio_b.id,
        )

        # Assert
        assert appt.pk is not None
        assert appt.consultorio_id == consultorio_b.id


class TestCheckBlockOverlapMeeting:
    """Reunión (kind=meeting) también bloquea citas igual que un bloqueo."""

    def test_meeting_kind_also_blocks_appointment(self, db: None) -> None:
        """Un evento de tipo MEETING impide citas que solapen igual que BLOCK."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Reunión de toda la clínica 10:00-11:00
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
            kind=AgendaBlock.Kind.MEETING,
            title="Junta de equipo",
        )

        # Act & Assert — cita en el mismo horario falla
        with pytest.raises(ValidationError, match="[Bb]loqueado"):
            _mk_appointment(
                tenant=tenant, user=user, doctor=doctor, patient=patient,
                starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
            )

    def test_meeting_for_doctor_blocks_that_doctors_appointment(
        self, db: None
    ) -> None:
        """Reunión asignada al doctor A bloquea citas del doctor A."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor_a = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Reunión del doctor_a
        _mk_block(
            tenant=tenant, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
            kind=AgendaBlock.Kind.MEETING,
            doctor_id=doctor_a.id,
        )

        # Act & Assert
        with pytest.raises(ValidationError, match="[Bb]loqueado"):
            _mk_appointment(
                tenant=tenant, user=user, doctor=doctor_a, patient=patient,
                starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
            )


class TestCheckBlockOverlapTenantIsolation:
    """Bloqueo de un tenant NO afecta las citas de otro tenant."""

    def test_block_in_tenant_b_does_not_prevent_appointment_in_tenant_a(
        self, db: None
    ) -> None:
        """El bloqueo del tenant B no impide citas en el mismo horario en el tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        doctor_a = DoctorFactory(tenant=tenant_a)
        patient_a = PatientFactory(tenant=tenant_a)

        # Bloqueo de toda la clínica en el tenant B (mismo horario)
        _mk_block(
            tenant=tenant_b, user=user,
            starts_at=_BASE_DT,
            ends_at=_BASE_DT + _ONE_HOUR,
        )

        # Act — cita en tenant A en el mismo horario: NO debe bloquearse
        appt = _mk_appointment(
            tenant=tenant_a, user=user, doctor=doctor_a, patient=patient_a,
            starts_at=_BASE_DT, ends_at=_BASE_DT + _ONE_HOUR,
        )

        # Assert
        assert appt.pk is not None
        assert appt.status == Appointment.Status.SCHEDULED
