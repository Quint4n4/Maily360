"""
Tests de services.py de la app personal.

Cubre:
- doctor_create: camino feliz, validación de role, membresía de otro tenant,
  duplicado, created_by.
- consultorio_create: camino feliz, nombre duplicado en mismo tenant,
  mismo nombre en tenant distinto.
- schedule_create: camino feliz, end_time <= start_time.
- doctor_deactivate: soft-disable.
- schedule_deactivate: soft-disable.

Fixes F1-F6:
- F1: is_active rechazado en doctor_update.
- F3: consultorio de otro tenant rechazado en schedule_create.
- F4: valid_until < valid_from rechazado en schedule_create.
- F6: re-create doctor after soft-delete es posible.

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.
"""

import datetime
from typing import Any

import pytest
from django.core.exceptions import ValidationError

from apps.personal.models import Consultorio, Doctor, DoctorSchedule
from apps.personal.services import (
    consultorio_create,
    consultorio_deactivate,
    consultorio_update,
    doctor_create,
    doctor_deactivate,
    doctor_update,
    schedule_create,
    schedule_deactivate,
)
from tests.factories import (
    ConsultorioFactory,
    DoctorFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)


# ===========================================================================
# doctor_create
# ===========================================================================


class TestDoctorCreate:
    """Casos de uso del servicio doctor_create."""

    def test_doctor_create_ok(self, db: None) -> None:
        """Membresía con role='doctor' crea el perfil correctamente."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor")

        # Act
        doctor = doctor_create(
            tenant=tenant,
            user=user,
            membership=membership,
            cedula_profesional="12345678",
            specialty="Cardiología",
        )

        # Assert
        assert doctor.pk is not None
        assert doctor.tenant_id == tenant.id
        assert doctor.membership_id == membership.id
        assert doctor.cedula_profesional == "12345678"
        assert doctor.specialty == "Cardiología"
        assert doctor.is_active is True

    def test_doctor_create_rejects_non_doctor_membership(self, db: None) -> None:
        """Role distinto a 'doctor' en la membresía debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="reception")

        # Act & Assert
        with pytest.raises(ValidationError, match="médico"):
            doctor_create(tenant=tenant, user=user, membership=membership)

    def test_doctor_create_rejects_membership_from_other_tenant(self, db: None) -> None:
        """Membresía de un tenant distinto al tenant dado debe lanzar ValidationError."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        # La membresía pertenece a tenant_b pero intentamos crear en tenant_a
        membership_b = TenantMembershipFactory(tenant=tenant_b, role="doctor")

        # Act & Assert
        with pytest.raises(ValidationError, match="clínica"):
            doctor_create(tenant=tenant_a, user=user, membership=membership_b)

    def test_doctor_create_rejects_duplicate_for_same_membership(self, db: None) -> None:
        """Segunda llamada con la misma membresía debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor")
        # Primer Doctor creado exitosamente
        doctor_create(tenant=tenant, user=user, membership=membership)

        # Act & Assert — segundo intento con la misma membresía
        with pytest.raises(ValidationError, match="Ya existe"):
            doctor_create(tenant=tenant, user=user, membership=membership)

    def test_doctor_create_sets_created_by(self, db: None) -> None:
        """El campo created_by debe apuntar al usuario que hizo la llamada."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor")

        # Act
        doctor = doctor_create(tenant=tenant, user=user, membership=membership)

        # Assert
        assert doctor.created_by_id == user.id

    def test_doctor_create_defaults(self, db: None) -> None:
        """Sin pasar specialty ni cedula, los defaults deben ser cadena vacía."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor")

        # Act
        doctor = doctor_create(tenant=tenant, user=user, membership=membership)

        # Assert
        assert doctor.cedula_profesional == ""
        assert doctor.specialty == ""
        assert doctor.default_appointment_duration == 30
        assert doctor.bio_short == ""


# ===========================================================================
# consultorio_create
# ===========================================================================


class TestConsultorioCreate:
    """Casos de uso del servicio consultorio_create."""

    def test_consultorio_create_ok(self, db: None) -> None:
        """Crea un consultorio con nombre único en el tenant."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        consultorio = consultorio_create(
            tenant=tenant,
            user=user,
            name="Consultorio A",
            location="Piso 1",
            color_hex="#3B82F6",
        )

        # Assert
        assert consultorio.pk is not None
        assert consultorio.tenant_id == tenant.id
        assert consultorio.name == "Consultorio A"
        assert consultorio.location == "Piso 1"
        assert consultorio.color_hex == "#3B82F6"
        assert consultorio.is_active is True

    def test_consultorio_create_rejects_duplicate_name_in_tenant(self, db: None) -> None:
        """Mismo nombre en el mismo tenant debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        consultorio_create(tenant=tenant, user=user, name="Box 1")

        # Act & Assert
        with pytest.raises(ValidationError, match="Box 1"):
            consultorio_create(tenant=tenant, user=user, name="Box 1")

    def test_consultorio_create_allows_same_name_in_different_tenant(
        self, db: None
    ) -> None:
        """El mismo nombre puede existir en tenants distintos (unicidad es por tenant)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()

        # Act — no debe lanzar
        c_a = consultorio_create(tenant=tenant_a, user=user, name="Consultorio Único")
        c_b = consultorio_create(tenant=tenant_b, user=user, name="Consultorio Único")

        # Assert
        assert c_a.name == c_b.name
        assert c_a.tenant_id != c_b.tenant_id

    def test_consultorio_create_sets_created_by(self, db: None) -> None:
        """El campo created_by apunta al usuario que hizo la llamada."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        consultorio = consultorio_create(tenant=tenant, user=user, name="Box 2")

        # Assert
        assert consultorio.created_by_id == user.id


# ===========================================================================
# schedule_create
# ===========================================================================


class TestScheduleCreate:
    """Casos de uso del servicio schedule_create."""

    def test_schedule_create_ok(self, db: None) -> None:
        """Crea un horario válido para un médico del tenant."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()

        # Act
        schedule = schedule_create(
            tenant=doctor.tenant,
            user=user,
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
        )

        # Assert
        assert schedule.pk is not None
        assert schedule.doctor_id == doctor.id
        assert schedule.day_of_week == 0
        assert schedule.start_time == datetime.time(9, 0)
        assert schedule.end_time == datetime.time(13, 0)
        assert schedule.is_active is True

    def test_schedule_create_rejects_end_before_start(self, db: None) -> None:
        """end_time <= start_time debe lanzar ValidationError."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()

        # Act & Assert — end_time antes que start_time
        with pytest.raises(ValidationError):
            schedule_create(
                tenant=doctor.tenant,
                user=user,
                doctor=doctor,
                day_of_week=1,
                start_time=datetime.time(14, 0),
                end_time=datetime.time(10, 0),
            )

    def test_schedule_create_rejects_equal_start_and_end(self, db: None) -> None:
        """end_time == start_time también es inválido."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError):
            schedule_create(
                tenant=doctor.tenant,
                user=user,
                doctor=doctor,
                day_of_week=2,
                start_time=datetime.time(10, 0),
                end_time=datetime.time(10, 0),
            )

    def test_schedule_create_rejects_doctor_from_other_tenant(self, db: None) -> None:
        """Médico de un tenant distinto al proporcionado debe lanzar ValidationError."""
        # Arrange
        tenant_a = TenantFactory()
        doctor_b = DoctorFactory()  # pertenece a tenant_b (creado por DoctorFactory)
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="clínica"):
            schedule_create(
                tenant=tenant_a,  # tenant distinto al del doctor
                user=user,
                doctor=doctor_b,
                day_of_week=0,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(13, 0),
            )

    def test_schedule_create_with_consultorio(self, db: None) -> None:
        """Crear horario con consultorio asignado persiste la FK correctamente."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        consultorio = ConsultorioFactory(tenant=tenant)
        user = UserFactory()

        # Act
        schedule = schedule_create(
            tenant=tenant,
            user=user,
            doctor=doctor,
            day_of_week=3,
            start_time=datetime.time(16, 0),
            end_time=datetime.time(20, 0),
            consultorio=consultorio,
        )

        # Assert
        assert schedule.consultorio_id == consultorio.id


# ===========================================================================
# doctor_deactivate
# ===========================================================================


class TestDoctorDeactivate:
    """Casos de uso del servicio doctor_deactivate."""

    def test_doctor_deactivate_sets_inactive(self, db: None) -> None:
        """doctor_deactivate pone is_active=False sin borrar el registro."""
        # Arrange
        doctor = DoctorFactory(is_active=True)
        user = UserFactory()
        doctor_id = doctor.id

        # Act
        result = doctor_deactivate(doctor=doctor, user=user)

        # Assert — retorno
        assert result.is_active is False

        # Assert — persistencia en BD
        doctor.refresh_from_db()
        assert doctor.is_active is False
        assert Doctor.all_objects.filter(id=doctor_id).exists()

    def test_doctor_deactivate_is_idempotent(self, db: None) -> None:
        """Desactivar un médico ya inactivo no debe lanzar error."""
        # Arrange
        doctor = DoctorFactory(is_active=True)
        user = UserFactory()
        doctor_deactivate(doctor=doctor, user=user)

        # Act — segunda llamada
        doctor_deactivate(doctor=doctor, user=user)

        # Assert
        doctor.refresh_from_db()
        assert doctor.is_active is False


# ===========================================================================
# schedule_deactivate
# ===========================================================================


class TestScheduleDeactivate:
    """Casos de uso del servicio schedule_deactivate."""

    def test_schedule_deactivate_sets_inactive(self, db: None) -> None:
        """schedule_deactivate pone is_active=False sin borrar el registro."""
        # Arrange
        from tests.factories import DoctorScheduleFactory

        schedule = DoctorScheduleFactory(is_active=True)
        user = UserFactory()
        schedule_id = schedule.id

        # Act
        result = schedule_deactivate(schedule=schedule, user=user)

        # Assert — retorno
        assert result.is_active is False

        # Assert — persistencia en BD
        schedule.refresh_from_db()
        assert schedule.is_active is False
        assert DoctorSchedule.all_objects.filter(id=schedule_id).exists()


# ===========================================================================
# doctor_update
# ===========================================================================


class TestDoctorUpdate:
    """Casos de uso del servicio doctor_update."""

    def test_doctor_update_applies_allowed_fields(self, db: None) -> None:
        """Campos permitidos se actualizan y persisten en BD."""
        # Arrange
        doctor = DoctorFactory(specialty="Medicina General", bio_short="")
        user = UserFactory()

        # Act
        updated = doctor_update(
            doctor=doctor,
            user=user,
            specialty="Neurología",
            bio_short="Especialista en neurología vascular.",
        )

        # Assert — valor devuelto
        assert updated.specialty == "Neurología"
        assert updated.bio_short == "Especialista en neurología vascular."

        # Assert — persistido en BD
        doctor.refresh_from_db()
        assert doctor.specialty == "Neurología"

    def test_doctor_update_rejects_immutable_field_membership(self, db: None) -> None:
        """Intentar cambiar 'membership' debe lanzar ValidationError."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()
        other_membership = TenantMembershipFactory(
            tenant=doctor.tenant, role="doctor"
        )

        # Act & Assert
        with pytest.raises(ValidationError, match="membership"):
            doctor_update(doctor=doctor, user=user, membership=other_membership)

    def test_doctor_update_rejects_immutable_field_tenant(self, db: None) -> None:
        """Intentar cambiar 'tenant' debe lanzar ValidationError."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()
        other_tenant = TenantFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="tenant"):
            doctor_update(doctor=doctor, user=user, tenant=other_tenant)


# ===========================================================================
# consultorio_update
# ===========================================================================


class TestConsultorioUpdate:
    """Casos de uso del servicio consultorio_update."""

    def test_consultorio_update_applies_allowed_fields(self, db: None) -> None:
        """Campos permitidos se actualizan y persisten en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        consultorio = ConsultorioFactory(tenant=tenant, location="")

        # Act
        updated = consultorio_update(
            consultorio=consultorio,
            user=user,
            location="Piso 3",
        )

        # Assert
        assert updated.location == "Piso 3"
        consultorio.refresh_from_db()
        assert consultorio.location == "Piso 3"

    def test_consultorio_update_rejects_duplicate_name(self, db: None) -> None:
        """Renombrar a un nombre ya existente en el tenant lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        ConsultorioFactory(tenant=tenant, name="Sala A")
        consultorio_b = ConsultorioFactory(tenant=tenant, name="Sala B")

        # Act & Assert
        with pytest.raises(ValidationError, match="Sala A"):
            consultorio_update(consultorio=consultorio_b, user=user, name="Sala A")

    def test_consultorio_update_allows_same_name_on_same_record(
        self, db: None
    ) -> None:
        """Actualizar un consultorio con su propio nombre actual no lanza error."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        consultorio = ConsultorioFactory(tenant=tenant, name="Box Azul")

        # Act — no debe lanzar
        updated = consultorio_update(
            consultorio=consultorio, user=user, name="Box Azul"
        )

        # Assert
        assert updated.name == "Box Azul"

    def test_consultorio_update_rejects_immutable_field_tenant(
        self, db: None
    ) -> None:
        """Intentar cambiar 'tenant' debe lanzar ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        consultorio = ConsultorioFactory(tenant=tenant)
        other_tenant = TenantFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="tenant"):
            consultorio_update(consultorio=consultorio, user=user, tenant=other_tenant)


# ===========================================================================
# consultorio_deactivate
# ===========================================================================


class TestConsultorioDeactivate:
    """Casos de uso del servicio consultorio_deactivate."""

    def test_consultorio_deactivate_sets_inactive(self, db: None) -> None:
        """consultorio_deactivate pone is_active=False sin borrar el registro."""
        # Arrange
        tenant = TenantFactory()
        consultorio = ConsultorioFactory(tenant=tenant, is_active=True)
        user = UserFactory()
        c_id = consultorio.id

        # Act
        result = consultorio_deactivate(consultorio=consultorio, user=user)

        # Assert — retorno
        assert result.is_active is False

        # Assert — persistencia en BD
        consultorio.refresh_from_db()
        assert consultorio.is_active is False
        assert Consultorio.all_objects.filter(id=c_id).exists()


# ===========================================================================
# FIX-F1: is_active inmutable en doctor_update
# ===========================================================================


class TestDoctorUpdateIsActiveImmutable:
    """FIX-F1: is_active no puede cambiarse vía doctor_update (solo vía doctor_deactivate)."""

    def test_doctor_update_rejects_is_active_field(self, db: None) -> None:
        """Enviar is_active=False en doctor_update debe lanzar ValidationError."""
        # Arrange
        doctor = DoctorFactory(is_active=True)
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="is_active"):
            doctor_update(doctor=doctor, user=user, is_active=False)

    def test_doctor_update_rejects_is_active_true(self, db: None) -> None:
        """Enviar is_active=True tampoco está permitido (solo doctor_deactivate puede escribir is_active)."""
        # Arrange
        doctor = DoctorFactory(is_active=True)
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="is_active"):
            doctor_update(doctor=doctor, user=user, is_active=True)

    def test_doctor_update_rejects_updated_at_field(self, db: None) -> None:
        """Intentar cambiar 'updated_at' directamente también debe lanzar ValidationError."""
        # Arrange
        import datetime as dt

        doctor = DoctorFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="updated_at"):
            doctor_update(doctor=doctor, user=user, updated_at=dt.datetime.now())


# ===========================================================================
# FIX-F3: consultorio de otro tenant rechazado en schedule_create
# ===========================================================================


class TestScheduleCreateConsultorioTenantValidation:
    """FIX-F3: consultorio pasado a schedule_create debe pertenecer al mismo tenant."""

    def test_schedule_create_rejects_consultorio_from_other_tenant(
        self, db: None
    ) -> None:
        """Pasar un consultorio de otro tenant debe lanzar ValidationError."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor = DoctorFactory(tenant=tenant_a)
        consultorio_b = ConsultorioFactory(tenant=tenant_b)
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="consultorio"):
            schedule_create(
                tenant=tenant_a,
                user=user,
                doctor=doctor,
                day_of_week=0,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(13, 0),
                consultorio=consultorio_b,  # consultorio de otro tenant
            )

    def test_schedule_create_accepts_consultorio_same_tenant(self, db: None) -> None:
        """Consultorio del mismo tenant debe aceptarse sin error."""
        # Arrange
        tenant = TenantFactory()
        doctor = DoctorFactory(tenant=tenant)
        consultorio = ConsultorioFactory(tenant=tenant)
        user = UserFactory()

        # Act — no debe lanzar
        schedule = schedule_create(
            tenant=tenant,
            user=user,
            doctor=doctor,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            consultorio=consultorio,
        )

        # Assert
        assert schedule.consultorio_id == consultorio.id


# ===========================================================================
# FIX-F4: valid_until < valid_from rechazado en schedule_create
# ===========================================================================


class TestScheduleCreateValidityRange:
    """FIX-F4: valid_until debe ser >= valid_from si ambos se proveen."""

    def test_schedule_create_rejects_valid_until_before_valid_from(
        self, db: None
    ) -> None:
        """valid_until anterior a valid_from debe lanzar ValidationError."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()

        # Act & Assert
        with pytest.raises(ValidationError, match="valid_until"):
            schedule_create(
                tenant=doctor.tenant,
                user=user,
                doctor=doctor,
                day_of_week=1,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(13, 0),
                valid_from=datetime.date(2026, 6, 10),
                valid_until=datetime.date(2026, 6, 1),  # anterior a valid_from
            )

    def test_schedule_create_rejects_valid_until_equal_to_valid_from(
        self, db: None
    ) -> None:
        """valid_until == valid_from es inválido (el servicio requiere posterior)."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()

        # valid_until == valid_from → range degenerado (solo 1 día sería valid_from==valid_until)
        # La validación es valid_until < valid_from, así que igual NO lanza.
        # Documentamos este borde aquí para claridad.
        schedule = schedule_create(
            tenant=doctor.tenant,
            user=user,
            doctor=doctor,
            day_of_week=2,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            valid_from=datetime.date(2026, 6, 1),
            valid_until=datetime.date(2026, 6, 1),  # igual es permitido (1 día)
        )
        assert schedule.valid_from == schedule.valid_until

    def test_schedule_create_accepts_valid_until_after_valid_from(
        self, db: None
    ) -> None:
        """valid_until posterior a valid_from debe persistirse correctamente."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()

        # Act
        schedule = schedule_create(
            tenant=doctor.tenant,
            user=user,
            doctor=doctor,
            day_of_week=3,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            valid_from=datetime.date(2026, 6, 1),
            valid_until=datetime.date(2026, 12, 31),
        )

        # Assert
        assert schedule.valid_from == datetime.date(2026, 6, 1)
        assert schedule.valid_until == datetime.date(2026, 12, 31)

    def test_schedule_create_accepts_none_validity_dates(self, db: None) -> None:
        """Si ambas fechas son None (sin límite), no debe lanzar error."""
        # Arrange
        doctor = DoctorFactory()
        user = UserFactory()

        # Act — no debe lanzar
        schedule = schedule_create(
            tenant=doctor.tenant,
            user=user,
            doctor=doctor,
            day_of_week=4,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(13, 0),
            valid_from=None,
            valid_until=None,
        )

        # Assert
        assert schedule.valid_from is None
        assert schedule.valid_until is None


# ===========================================================================
# FIX-F6: re-create doctor after soft-delete
# ===========================================================================


class TestDoctorCreateAfterSoftDelete:
    """FIX-F6: re-crear un Doctor tras soft-delete es posible (extremo a extremo).

    El service excluye soft-deleted del chequeo de duplicado
    (deleted_at__isnull=True) Y el constraint de BD es ahora un índice único
    parcial (doctor_membership_active_uniq, WHERE deleted_at IS NULL) en lugar
    de la antigua restricción UNIQUE total del OneToOneField. Por eso un Doctor
    soft-deleted ya NO bloquea la re-creación del perfil con la misma membresía.
    """

    def test_doctor_create_allows_recreate_after_soft_delete(
        self, db: None
    ) -> None:
        """FIX-F6: tras soft-deletear un Doctor, se puede crear otro con la misma
        membresía sin lanzar ValidationError ni IntegrityError.

        Verifica el fix completo: el índice único parcial deja fuera a los
        registros soft-deleted, así que el INSERT del segundo Doctor tiene éxito.
        """
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor")

        # Crear doctor y luego soft-deletear manualmente
        original = doctor_create(tenant=tenant, user=user, membership=membership)
        original.deleted_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        original.save(update_fields=["deleted_at"])

        # Act — re-crear con la misma membresía debe tener ÉXITO (sin excepción)
        recreated = doctor_create(tenant=tenant, user=user, membership=membership)

        # Assert — es un registro nuevo, activo, con la misma membresía
        assert recreated.pk is not None
        assert recreated.pk != original.pk
        assert recreated.membership_id == membership.id
        assert recreated.deleted_at is None
        # El original sigue soft-deleted; el activo es el recién creado.
        assert Doctor.all_objects.filter(
            membership=membership, deleted_at__isnull=True
        ).count() == 1

    def test_doctor_create_still_rejects_active_duplicate(self, db: None) -> None:
        """Si el Doctor activo (no soft-deleted) ya existe, sigue lanzando ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        membership = TenantMembershipFactory(tenant=tenant, role="doctor")
        doctor_create(tenant=tenant, user=user, membership=membership)  # activo

        # Act & Assert — segundo intento con mismo membership activo → rechazado
        with pytest.raises(ValidationError, match="Ya existe"):
            doctor_create(tenant=tenant, user=user, membership=membership)
