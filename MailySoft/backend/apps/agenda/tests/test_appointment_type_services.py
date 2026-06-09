"""
Tests de services para la Feature 1: AppointmentType (tipos de cita configurables).

Cubre:
- appointment_type_create: camino feliz, nombre+color_hex, sin color.
- appointment_type_create: constraint de nombre único por tenant (no borrados).
- appointment_type_update: cambio de nombre y color; ignora campos no editables.
- appointment_type_deactivate: soft-deactivate, is_active=False, persiste en BD.
- appointment_create con appointment_type_id válido: la cita queda con el tipo asignado.
- appointment_create con appointment_type_id de OTRO tenant: ValidationError.
- appointment_create SIN reason: permitido (reason="" por defecto).
- appointment_type_list: solo_active=True (default) y only_active=False.
- appointment_type_list: aislamiento multi-tenant (tipos de otro tenant invisibles).
- appointment_type_get: tenant activo filtra correctamente.

Patrón: AAA. Todas tocan BD → fixture db.
Contexto de tenant: set_current_tenant + set_tenant_context_active cuando
el service/selector llama internamente a TenantManager.
"""

import datetime
import uuid
from contextlib import contextmanager
from typing import Generator

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.agenda.models import Appointment, AppointmentType
from apps.agenda.selectors import appointment_type_get, appointment_type_list
from apps.agenda.services import (
    appointment_create,
    appointment_type_create,
    appointment_type_deactivate,
    appointment_type_update,
)
from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from tests.factories import (
    AppointmentFactory,
    ConsultorioFactory,
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_DT = datetime.datetime(2031, 3, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)


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


# ===========================================================================
# appointment_type_create
# ===========================================================================


class TestAppointmentTypeCreate:
    """appointment_type_create — camino feliz y validaciones."""

    def test_create_type_with_name_and_color_ok(self, db: None) -> None:
        """Crea un tipo con nombre y color; queda activo y persistido en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Primera vez", color_hex="#3B82F6"
        )

        # Assert
        assert atype.pk is not None
        assert atype.name == "Primera vez"
        assert atype.color_hex == "#3B82F6"
        assert atype.is_active is True
        assert atype.tenant_id == tenant.id

    def test_create_type_without_color_defaults_to_empty_string(self, db: None) -> None:
        """Crear un tipo sin color_hex deja el campo en cadena vacía."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        atype = appointment_type_create(tenant=tenant, user=user, name="Seguimiento")

        # Assert
        assert atype.color_hex == ""

    def test_create_type_sets_created_by(self, db: None) -> None:
        """created_by queda apuntando al usuario que invoca el service."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()

        # Act
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Urgente", color_hex="#EF4444"
        )

        # Assert
        assert atype.created_by_id == user.id

    def test_create_type_name_unique_per_tenant_raises_on_duplicate(
        self, db: None
    ) -> None:
        """Dos tipos con el mismo nombre en el mismo tenant lanzan IntegrityError
        (UniqueConstraint a nivel de BD — condition=deleted_at__isnull=True)."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        appointment_type_create(tenant=tenant, user=user, name="Seguimiento")

        # Act & Assert — segundo tipo con el mismo nombre en el mismo tenant
        with pytest.raises(IntegrityError):
            appointment_type_create(tenant=tenant, user=user, name="Seguimiento")

    def test_create_type_same_name_allowed_in_different_tenants(
        self, db: None
    ) -> None:
        """El mismo nombre sí puede existir en tenants distintos (constraint es por tenant)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()

        # Act — mismo nombre, tenants distintos: no debe fallar
        type_a = appointment_type_create(
            tenant=tenant_a, user=user, name="Consulta general"
        )
        type_b = appointment_type_create(
            tenant=tenant_b, user=user, name="Consulta general"
        )

        # Assert
        assert type_a.pk != type_b.pk


# ===========================================================================
# appointment_type_update
# ===========================================================================


class TestAppointmentTypeUpdate:
    """appointment_type_update — actualiza nombre y/o color; ignora otros campos."""

    def test_update_name_only(self, db: None) -> None:
        """Actualizar solo el nombre persiste el cambio en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Original", color_hex="#111111"
        )

        # Act
        updated = appointment_type_update(
            appointment_type=atype, user=user, name="Renombrado"
        )

        # Assert
        assert updated.name == "Renombrado"
        atype.refresh_from_db()
        assert atype.name == "Renombrado"

    def test_update_color_only(self, db: None) -> None:
        """Actualizar solo el color_hex persiste el cambio en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Urgente", color_hex="#000000"
        )

        # Act
        updated = appointment_type_update(
            appointment_type=atype, user=user, color_hex="#FF0000"
        )

        # Assert
        assert updated.color_hex == "#FF0000"
        atype.refresh_from_db()
        assert atype.color_hex == "#FF0000"

    def test_update_name_and_color_together(self, db: None) -> None:
        """Actualizar nombre y color en la misma llamada actualiza ambos campos."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Tipo viejo", color_hex="#AAAAAA"
        )

        # Act
        updated = appointment_type_update(
            appointment_type=atype, user=user, name="Tipo nuevo", color_hex="#BBBBBB"
        )

        # Assert
        assert updated.name == "Tipo nuevo"
        assert updated.color_hex == "#BBBBBB"

    def test_update_ignores_non_editable_fields(self, db: None) -> None:
        """Pasar campos fuera de _APPOINTMENT_TYPE_EDITABLE no los aplica ni lanza error."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Tipo test", color_hex="#123456"
        )
        original_id = atype.pk

        # Act — intentar cambiar campos que no son editables vía update
        # El service ignora silenciosamente los no editables
        updated = appointment_type_update(
            appointment_type=atype,
            user=user,
            name="Tipo editado",
            is_active=False,  # type: ignore[call-arg]
        )

        # Assert — nombre se actualizó; is_active fue ignorado (sigue True)
        assert updated.name == "Tipo editado"
        updated.refresh_from_db()
        assert updated.is_active is True  # no se cambió por update
        assert updated.pk == original_id


# ===========================================================================
# appointment_type_deactivate
# ===========================================================================


class TestAppointmentTypeDeactivate:
    """appointment_type_deactivate — soft deactivation."""

    def test_deactivate_sets_is_active_false(self, db: None) -> None:
        """Desactivar un tipo cambia is_active a False y persiste en BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        atype = appointment_type_create(
            tenant=tenant, user=user, name="A desactivar", color_hex="#CCCCCC"
        )
        assert atype.is_active is True

        # Act
        result = appointment_type_deactivate(appointment_type=atype, user=user)

        # Assert
        assert result.is_active is False
        atype.refresh_from_db()
        assert atype.is_active is False

    def test_deactivated_type_still_exists_in_db(self, db: None) -> None:
        """El tipo desactivado no se borra físicamente; permanece en la BD."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Persiste", color_hex="#DDDDDD"
        )
        type_id = atype.pk

        # Act
        appointment_type_deactivate(appointment_type=atype, user=user)

        # Assert — el registro sigue en BD con all_objects
        assert AppointmentType.all_objects.filter(id=type_id).exists()

    def test_deactivated_type_excluded_from_active_list(self, db: None) -> None:
        """Un tipo desactivado no aparece en appointment_type_list(only_active=True)."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        active_type = appointment_type_create(
            tenant=tenant, user=user, name="Activo", color_hex="#111111"
        )
        inactive_type = appointment_type_create(
            tenant=tenant, user=user, name="Inactivo", color_hex="#222222"
        )
        appointment_type_deactivate(appointment_type=inactive_type, user=user)

        # Act — lista solo activos (default)
        with _tenant_ctx(tenant):
            qs = appointment_type_list(only_active=True)
            ids = set(qs.values_list("id", flat=True))

        # Assert
        assert active_type.id in ids
        assert inactive_type.id not in ids

    def test_only_active_false_includes_inactive_types(self, db: None) -> None:
        """Con only_active=False, los tipos desactivados también aparecen en la lista."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        active_type = appointment_type_create(
            tenant=tenant, user=user, name="Activo", color_hex="#111111"
        )
        inactive_type = appointment_type_create(
            tenant=tenant, user=user, name="Inactivo", color_hex="#222222"
        )
        appointment_type_deactivate(appointment_type=inactive_type, user=user)

        # Act
        with _tenant_ctx(tenant):
            qs = appointment_type_list(only_active=False)
            ids = set(qs.values_list("id", flat=True))

        # Assert — ambos aparecen
        assert active_type.id in ids
        assert inactive_type.id in ids


# ===========================================================================
# appointment_type_list — aislamiento multi-tenant
# ===========================================================================


class TestAppointmentTypeListTenantIsolation:
    """appointment_type_list no filtra datos de otro tenant."""

    def test_types_of_other_tenant_not_visible(self, db: None) -> None:
        """Con contexto del tenant A, los tipos del tenant B son invisibles."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()

        type_a = appointment_type_create(
            tenant=tenant_a, user=user, name="Tipo A", color_hex="#AAAAAA"
        )
        appointment_type_create(
            tenant=tenant_b, user=user, name="Tipo B", color_hex="#BBBBBB"
        )

        # Act — contexto del tenant A
        with _tenant_ctx(tenant_a):
            qs = appointment_type_list(only_active=True)
            ids = set(qs.values_list("id", flat=True))

        # Assert — solo el tipo del tenant A
        assert type_a.id in ids
        assert len(ids) == 1, (
            f"Fuga cross-tenant: se obtuvieron {len(ids)} tipos en lugar de 1 del tenant A."
        )


# ===========================================================================
# appointment_type_get — aislamiento multi-tenant
# ===========================================================================


class TestAppointmentTypeGetIsolation:
    """appointment_type_get usa TenantManager: tipo de otro tenant → DoesNotExist."""

    def test_get_type_of_other_tenant_raises_does_not_exist(self, db: None) -> None:
        """appointment_type_get con UUID de otro tenant lanza DoesNotExist (→ 404)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        type_b = appointment_type_create(
            tenant=tenant_b, user=user, name="Tipo B", color_hex="#BBBBBB"
        )

        # Act — con contexto del tenant A, intentar leer el tipo del tenant B
        with _tenant_ctx(tenant_a):
            with pytest.raises(AppointmentType.DoesNotExist):
                appointment_type_get(type_id=type_b.id)

    def test_get_type_of_own_tenant_ok(self, db: None) -> None:
        """appointment_type_get retorna el tipo cuando pertenece al tenant activo."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Tipo propio", color_hex="#123456"
        )

        # Act
        with _tenant_ctx(tenant):
            result = appointment_type_get(type_id=atype.id)

        # Assert
        assert result.id == atype.id


# ===========================================================================
# appointment_create con appointment_type_id
# ===========================================================================


class TestAppointmentCreateWithAppointmentType:
    """appointment_create acepta appointment_type_id y lo valida correctamente."""

    def test_create_appointment_with_valid_type_sets_appointment_type(
        self, db: None
    ) -> None:
        """Cita creada con appointment_type_id válido tiene el tipo asignado."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        atype = appointment_type_create(
            tenant=tenant, user=user, name="Primera vez", color_hex="#3B82F6"
        )

        # Act
        with _tenant_ctx(tenant):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                appointment_type_id=atype.id,
            )

        # Assert
        assert appt.appointment_type_id == atype.id

    def test_create_appointment_with_type_from_other_tenant_raises_validation_error(
        self, db: None
    ) -> None:
        """Tipo de cita de otro tenant lanza ValidationError.

        El TenantManager filtra por contexto activo: appointment_type_get con un
        UUID del tenant B dentro del contexto del tenant A lanza DoesNotExist,
        que el service convierte en ValidationError("Tipo de cita no encontrado…").
        En el caso de que el id llegase sin filtrar (e.g. en un command), la segunda
        comprobación (tenant_id != tenant.id) también lanzaría ValidationError.
        Ambos caminos son defensa en profundidad.
        """
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant_a)
        patient = PatientFactory(tenant=tenant_a)
        type_b = appointment_type_create(
            tenant=tenant_b, user=user, name="Tipo B", color_hex="#FF0000"
        )

        # Act & Assert — tipo del tenant B: el TenantManager lo hace invisible,
        # el service lanza ValidationError("Tipo de cita no encontrado en esta clínica.")
        with pytest.raises(ValidationError, match="[Tt]ipo de cita"):
            with _tenant_ctx(tenant_a):
                appointment_create(
                    tenant=tenant_a,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    appointment_type_id=type_b.id,
                )

    def test_create_appointment_without_reason_is_allowed(self, db: None) -> None:
        """Crear cita sin reason (campo opcional desde v2) está permitido: reason=""."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Act — sin reason (no se pasa el argumento)
        with _tenant_ctx(tenant):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
                # reason no se pasa → default ""
            )

        # Assert — cita creada sin error, reason es cadena vacía
        assert appt.pk is not None
        assert appt.reason == ""

    def test_create_appointment_without_appointment_type_leaves_type_null(
        self, db: None
    ) -> None:
        """Sin appointment_type_id la cita se crea con appointment_type=None."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # Act
        with _tenant_ctx(tenant):
            appt = appointment_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                doctor_id=doctor.id,
                starts_at=_BASE_DT,
            )

        # Assert
        assert appt.appointment_type is None

    def test_create_appointment_with_nonexistent_type_raises_validation_error(
        self, db: None
    ) -> None:
        """appointment_type_id que no existe lanza ValidationError."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        fake_type_id = uuid.uuid4()

        # Act & Assert — UUID inexistente: DoesNotExist → "Tipo de cita no encontrado"
        with pytest.raises(ValidationError, match="[Tt]ipo de cita"):
            with _tenant_ctx(tenant):
                appointment_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    starts_at=_BASE_DT,
                    appointment_type_id=fake_type_id,
                )
