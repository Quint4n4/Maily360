"""
Tests de selectors.py de la app pacientes.

Cubre:
- patient_list: filtro is_active, búsqueda por nombre/teléfono/expediente.
- patient_list: AISLAMIENTO cross-tenant (crítico) — con contexto activo solo
  se ven los pacientes del tenant en contexto.
- patient_get: retorna el paciente correcto; lanza DoesNotExist si no existe
  o pertenece a otro tenant.

Patrón: AAA. Todas tocan BD → fixture db.
Tenant context: para tests de aislamiento se activa explícitamente con
    set_current_tenant(tenant) + set_tenant_context_active(True).
El fixture autouse reset_tenant_context garantiza limpieza entre tests.
"""

import uuid

import pytest

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.pacientes.selectors import patient_get, patient_list
from tests.factories import PatientFactory, TenantFactory, UserFactory


# ===========================================================================
# patient_list — filtros básicos (sin contexto de tenant activo)
# ===========================================================================


class TestPatientListFilters:
    """patient_list filtra correctamente por is_active y búsqueda libre."""

    def test_patient_list_filters_by_active(self, db: None) -> None:
        """Solo deben aparecer pacientes con is_active=True."""
        # Arrange
        tenant = TenantFactory()
        active = PatientFactory(tenant=tenant, is_active=True)
        PatientFactory(tenant=tenant, is_active=False)  # inactivo: no debe aparecer

        # Act — sin contexto activo: manager no filtra por tenant
        qs = patient_list()

        # Assert — el activo está en el resultado y todos los resultados son activos
        ids = list(qs.values_list("id", flat=True))
        assert active.id in ids
        assert all(p.is_active for p in qs)

    def test_patient_list_returns_only_active_patients(self, db: None) -> None:
        """Versión más directa: cuenta activos vs total creados."""
        # Arrange
        tenant = TenantFactory()
        PatientFactory.create_batch(3, tenant=tenant, is_active=True)
        PatientFactory.create_batch(2, tenant=tenant, is_active=False)

        # Act
        qs = patient_list()

        # Assert — solo los 3 activos
        assert qs.count() == 3
        assert all(p.is_active for p in qs)

    def test_patient_list_search_by_first_name(self, db: None) -> None:
        """Buscar por primer nombre retorna solo coincidencias (case-insensitive)."""
        # Arrange
        tenant = TenantFactory()
        target = PatientFactory(tenant=tenant, first_name="Esperanza", is_active=True)
        PatientFactory(tenant=tenant, first_name="Roberto", is_active=True)

        # Act
        qs = patient_list(search="esperanza")

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert target.id in ids
        assert all("esperanza" in p.first_name.lower() for p in qs)

    def test_patient_list_search_by_paternal_surname(self, db: None) -> None:
        """Buscar por apellido paterno retorna solo coincidencias."""
        # Arrange
        tenant = TenantFactory()
        target = PatientFactory(tenant=tenant, paternal_surname="Zuñiga", is_active=True)
        PatientFactory(tenant=tenant, paternal_surname="Gómez", is_active=True)

        # Act
        qs = patient_list(search="zuñiga")

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert target.id in ids

    def test_patient_list_search_by_phone(self, db: None) -> None:
        """Buscar por teléfono retorna pacientes cuyo phone contiene el término."""
        # Arrange
        tenant = TenantFactory()
        target = PatientFactory(tenant=tenant, phone="5512349999", is_active=True)
        PatientFactory(tenant=tenant, phone="5500000001", is_active=True)

        # Act
        qs = patient_list(search="9999")

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert target.id in ids
        # El otro no debe aparecer
        other_ids = [p.id for p in qs]
        # Verificamos que el resultado solo contiene pacientes con "9999" en teléfono
        assert all("9999" in p.phone for p in qs)

    def test_patient_list_search_by_record_number(self, db: None) -> None:
        """Buscar por número de expediente retorna el paciente correcto."""
        # Arrange
        tenant = TenantFactory()
        target = PatientFactory(
            tenant=tenant, record_number="EXP-2026-00042", is_active=True
        )
        PatientFactory(tenant=tenant, record_number="EXP-2026-00001", is_active=True)

        # Act
        qs = patient_list(search="00042")

        # Assert
        ids = list(qs.values_list("id", flat=True))
        assert target.id in ids
        assert all("00042" in p.record_number for p in qs)

    def test_patient_list_empty_search_returns_all_active(self, db: None) -> None:
        """Sin término de búsqueda se retornan todos los pacientes activos."""
        # Arrange
        tenant = TenantFactory()
        PatientFactory.create_batch(5, tenant=tenant, is_active=True)

        # Act
        qs = patient_list(search="")

        # Assert
        assert qs.count() == 5

    def test_patient_list_search_no_matches_returns_empty(self, db: None) -> None:
        """Búsqueda sin coincidencias retorna QuerySet vacío."""
        # Arrange
        tenant = TenantFactory()
        PatientFactory(tenant=tenant, first_name="María", is_active=True)

        # Act
        qs = patient_list(search="xxxxxxxxxnoexiste")

        # Assert
        assert qs.count() == 0


# ===========================================================================
# AISLAMIENTO CROSS-TENANT (crítico)
# ===========================================================================


class TestPatientListTenantIsolation:
    """El TenantManager debe garantizar que un tenant no vea datos de otro."""

    def test_patient_list_only_returns_current_tenant_patients(self, db: None) -> None:
        """Con contexto del tenant A activo, solo se ven pacientes del tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        patients_a = PatientFactory.create_batch(3, tenant=tenant_a, is_active=True)
        PatientFactory.create_batch(2, tenant=tenant_b, is_active=True)

        # Activar contexto del tenant A
        set_current_tenant(tenant_a)
        set_tenant_context_active(True)

        # Act
        qs = patient_list()

        # Assert — solo los 3 del tenant A
        assert qs.count() == 3
        result_ids = set(qs.values_list("id", flat=True))
        expected_ids = {p.id for p in patients_a}
        assert result_ids == expected_ids

    def test_patient_list_tenant_b_context_does_not_see_tenant_a_data(
        self, db: None
    ) -> None:
        """Con contexto del tenant B activo, no se ven datos del tenant A."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        PatientFactory.create_batch(4, tenant=tenant_a, is_active=True)
        patients_b = PatientFactory.create_batch(2, tenant=tenant_b, is_active=True)

        # Activar contexto del tenant B
        set_current_tenant(tenant_b)
        set_tenant_context_active(True)

        # Act
        qs = patient_list()

        # Assert — solo los 2 del tenant B
        assert qs.count() == 2
        result_ids = set(qs.values_list("id", flat=True))
        expected_ids = {p.id for p in patients_b}
        assert result_ids == expected_ids

    def test_patient_list_with_no_tenant_context_returns_empty(self, db: None) -> None:
        """Dentro de un request sin tenant resuelto (context_active=True, tenant=None),
        el manager debe devolver QuerySet vacío (falla segura)."""
        # Arrange
        tenant = TenantFactory()
        PatientFactory.create_batch(3, tenant=tenant, is_active=True)

        # Activar contexto SIN tenant — falla segura
        set_current_tenant(None)
        set_tenant_context_active(True)

        # Act
        qs = patient_list()

        # Assert — QuerySet vacío (no expone datos de ningún tenant)
        assert qs.count() == 0

    def test_patient_list_cross_tenant_search_does_not_leak(self, db: None) -> None:
        """La búsqueda con contexto activo no debe filtrar datos de otro tenant,
        incluso si ambos tenants tienen pacientes con el mismo nombre."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()

        # Mismo nombre en ambos tenants
        PatientFactory(
            tenant=tenant_a, first_name="Duplicado", paternal_surname="Test", is_active=True
        )
        PatientFactory(
            tenant=tenant_b, first_name="Duplicado", paternal_surname="Test", is_active=True
        )

        # Activar contexto del tenant A
        set_current_tenant(tenant_a)
        set_tenant_context_active(True)

        # Act
        qs = patient_list(search="Duplicado")

        # Assert — solo el del tenant A
        assert qs.count() == 1
        assert qs.first().tenant_id == tenant_a.id  # type: ignore[union-attr]


# ===========================================================================
# patient_get
# ===========================================================================


class TestPatientGet:
    """patient_get retorna el paciente correcto y respeta el contexto de tenant."""

    def test_patient_get_returns_patient(self, db: None) -> None:
        """patient_get retorna la instancia correcta por UUID (sin contexto activo)."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        # Act
        result = patient_get(patient_id=patient.id)

        # Assert
        assert result.id == patient.id
        assert result.first_name == patient.first_name

    def test_patient_get_raises_does_not_exist_for_unknown_uuid(self, db: None) -> None:
        """UUID inexistente debe lanzar Patient.DoesNotExist."""
        # Arrange
        from apps.pacientes.models import Patient

        unknown_id = uuid.uuid4()

        # Act & Assert
        with pytest.raises(Patient.DoesNotExist):
            patient_get(patient_id=unknown_id)

    def test_patient_get_with_tenant_context_raises_for_other_tenant_patient(
        self, db: None
    ) -> None:
        """Con contexto del tenant A activo, pedir un paciente del tenant B lanza DoesNotExist."""
        # Arrange
        from apps.pacientes.models import Patient

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)

        # Activar contexto del tenant A
        set_current_tenant(tenant_a)
        set_tenant_context_active(True)

        # Act & Assert — el paciente de B no existe para A
        with pytest.raises(Patient.DoesNotExist):
            patient_get(patient_id=patient_b.id)

    def test_patient_get_with_matching_tenant_context_succeeds(self, db: None) -> None:
        """Con contexto del tenant A activo, recuperar un paciente del tenant A funciona."""
        # Arrange
        tenant_a = TenantFactory()
        patient_a = PatientFactory(tenant=tenant_a)

        # Activar contexto del tenant A
        set_current_tenant(tenant_a)
        set_tenant_context_active(True)

        # Act
        result = patient_get(patient_id=patient_a.id)

        # Assert
        assert result.id == patient_a.id
