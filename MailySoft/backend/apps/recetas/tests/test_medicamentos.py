"""
Tests de la app recetas — sub-fase B1.1 (Catálogo de medicamentos).

Cubre (objetivo ≥ 80% en lógica de negocio):
- models: GlobalMedication y Medication se crean correctamente.
- selectors.medication_search:
    - q vacío devuelve [].
    - encuentra por generic_name (icontains).
    - encuentra por commercial_name (icontains).
    - une resultados globales + custom del tenant.
    - filtra is_active=True (excluye inactivos).
    - marca source="global" / source="custom".
    - respeta el límite máximo de resultados.
    - custom de OTRO tenant no aparece (aislamiento multi-tenant).
- selectors.medication_get:
    - devuelve el Medication correcto en el tenant activo.
    - lanza DoesNotExist si el id no existe o es de otro tenant (anti-IDOR).
- services.medication_create:
    - camino feliz: crea Medication con los campos correctos.
    - falla si generic_name está vacío.
    - falla si generic_name es solo espacios.
    - falla si form es inválido.
    - falla si tenant es None.
    - registra entrada en AuditLog.
- APIs:
    - GET /recetas/medicamentos/buscar/ 401 sin token.
    - GET /recetas/medicamentos/buscar/?q= devuelve resultados para roles clínicos.
    - GET /recetas/medicamentos/buscar/ 403 para roles sin acceso (recepción, finanzas).
    - POST /recetas/medicamentos/ 401 sin token.
    - POST /recetas/medicamentos/ 201 crea Medication para doctor/admin/owner.
    - POST /recetas/medicamentos/ 403 para enfermería (solo puede buscar, no crear).
    - POST /recetas/medicamentos/ 400 con generic_name vacío.
    - POST /recetas/medicamentos/ 400 con form inválido.
- RLS: Medication de otro tenant no visible en el tenant activo.
- Seed (idempotencia): seed_medicamentos no duplica en segunda ejecución.

Patrón: AAA. factory_boy para datos. Mockeo de tenant igual que notificaciones.
"""

import uuid as uuid_module
from typing import Any

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.recetas.models import GlobalMedication, Medication, MedicationForm
from apps.recetas.selectors import MAX_Q_LENGTH, medication_get, medication_search
from apps.recetas.services import medication_create
from apps.recetas.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    GlobalMedicationFactory,
    MedicationFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

URL_SEARCH = "/api/v1/recetas/medicamentos/buscar/"
URL_CREATE = "/api/v1/recetas/medicamentos/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _member(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> Any:
    """Crea un user con membresía activa en el tenant dado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ===========================================================================
# Modelos
# ===========================================================================


class TestGlobalMedicationModel:
    """Tests básicos del modelo GlobalMedication."""

    def test_create_global_medication(self, db: Any) -> None:
        """GlobalMedication se crea con los campos correctos."""
        med = GlobalMedicationFactory(
            generic_name="Paracetamol",
            concentration="500 mg",
            form=MedicationForm.TABLETA,
            commercial_name="Tempra",
            is_active=True,
        )
        assert med.id is not None
        assert med.generic_name == "Paracetamol"
        assert med.concentration == "500 mg"
        assert med.form == MedicationForm.TABLETA
        assert med.commercial_name == "Tempra"
        assert med.is_active is True

    def test_str_representation(self, db: Any) -> None:
        """__str__ incluye generic_name, concentration y form."""
        med = GlobalMedicationFactory(
            generic_name="Amoxicilina",
            concentration="500 mg",
            form=MedicationForm.CAPSULA,
        )
        s = str(med)
        assert "Amoxicilina" in s
        assert "500 mg" in s
        assert "capsula" in s


class TestMedicationModel:
    """Tests básicos del modelo Medication (custom por tenant)."""

    def test_create_medication_custom(self, db: Any) -> None:
        """Medication se crea correctamente con tenant."""
        tenant = TenantFactory()
        user = UserFactory()
        med = MedicationFactory(
            tenant=tenant,
            created_by=user,
            generic_name="Ibuprofeno especial",
            form=MedicationForm.TABLETA,
            is_active=True,
        )
        assert med.id is not None
        assert med.tenant_id == tenant.id
        assert med.created_by_id == user.id
        assert med.generic_name == "Ibuprofeno especial"
        assert med.is_active is True

    def test_str_includes_tenant(self, db: Any) -> None:
        """__str__ incluye [custom tenant=...]."""
        tenant = TenantFactory()
        med = MedicationFactory(tenant=tenant, generic_name="Losartán")
        s = str(med)
        assert "custom" in s


# ===========================================================================
# selectors.medication_search
# ===========================================================================


class TestMedicationSearch:
    """Tests del selector medication_search."""

    def test_empty_q_returns_empty(self, db: Any) -> None:
        """Si q está vacío o en blanco, devuelve lista vacía."""
        GlobalMedicationFactory(generic_name="Metformina")
        assert medication_search(q="") == []
        assert medication_search(q="   ") == []

    def test_long_q_is_truncated_to_max_length(self, db: Any) -> None:
        """Un q mayor a MAX_Q_LENGTH se trunca antes de ILIKE (B1.1 audit M1).

        Sin el tope, q="A"*50000 NO haría match (el término sería más largo que el
        campo, max_length=200). Con el tope a 200, q="A"*200 sí matchea el nombre,
        lo que prueba que el truncado ocurrió.
        """
        long_name = "A" * MAX_Q_LENGTH  # 200 chars = máximo del modelo
        GlobalMedicationFactory(
            generic_name=long_name, form=MedicationForm.TABLETA, is_active=True
        )
        results = medication_search(q="A" * 50_000)
        assert any(r["generic_name"] == long_name for r in results)

    def test_finds_by_generic_name(self, db: Any) -> None:
        """Busca por generic_name (icontains)."""
        GlobalMedicationFactory(
            generic_name="Amoxicilina",
            concentration="500 mg",
            form=MedicationForm.CAPSULA,
            is_active=True,
        )
        GlobalMedicationFactory(
            generic_name="Paracetamol",
            concentration="500 mg",
            form=MedicationForm.TABLETA,
        )
        results = medication_search(q="amox")
        names = [r["generic_name"] for r in results]
        assert "Amoxicilina" in names
        assert "Paracetamol" not in names

    def test_finds_by_commercial_name(self, db: Any) -> None:
        """Busca por commercial_name (icontains)."""
        GlobalMedicationFactory(
            generic_name="Ibuprofeno",
            commercial_name="Advil",
            form=MedicationForm.TABLETA,
            concentration="400 mg",
            is_active=True,
        )
        results = medication_search(q="advil")
        assert len(results) >= 1
        assert results[0]["commercial_name"] == "Advil"

    def test_excludes_inactive_global(self, db: Any) -> None:
        """Medicamentos inactivos (is_active=False) no aparecen en la búsqueda."""
        GlobalMedicationFactory(
            generic_name="MedicamentoRetiradog",
            form=MedicationForm.TABLETA,
            concentration="",
            is_active=False,
        )
        results = medication_search(q="MedicamentoRetiradog")
        assert results == []

    def test_source_global(self, db: Any) -> None:
        """Resultados del catálogo global tienen source='global'."""
        GlobalMedicationFactory(
            generic_name="Omeprazol",
            form=MedicationForm.CAPSULA,
            concentration="20 mg",
            is_active=True,
        )
        results = medication_search(q="Omeprazol")
        assert all(r["source"] == "global" for r in results)

    def test_source_custom(self, db: Any) -> None:
        """Resultados de medicamentos custom tienen source='custom'."""
        tenant = TenantFactory()
        MedicationFactory(
            tenant=tenant,
            generic_name="VitaminaCustom",
            form=MedicationForm.TABLETA,
            concentration="",
            is_active=True,
        )
        with tenant_ctx(tenant):
            results = medication_search(q="VitaminaCustom")
        custom = [r for r in results if r["source"] == "custom"]
        assert len(custom) == 1
        assert custom[0]["generic_name"] == "VitaminaCustom"

    def test_combines_global_and_custom(self, db: Any) -> None:
        """Une resultados globales y custom del tenant activo."""
        GlobalMedicationFactory(
            generic_name="Losartán",
            form=MedicationForm.TABLETA,
            concentration="50 mg",
            is_active=True,
        )
        tenant = TenantFactory()
        MedicationFactory(
            tenant=tenant,
            generic_name="LosartánCustom",
            form=MedicationForm.TABLETA,
            concentration="",
            is_active=True,
        )
        with tenant_ctx(tenant):
            results = medication_search(q="losart")
        sources = {r["source"] for r in results}
        assert "global" in sources
        assert "custom" in sources

    def test_custom_of_other_tenant_not_visible(self, db: Any) -> None:
        """Medicamentos custom de otro tenant NO aparecen."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        MedicationFactory(
            tenant=tenant_b,
            generic_name="MedicamentoDeB",
            form=MedicationForm.TABLETA,
            concentration="",
            is_active=True,
        )
        with tenant_ctx(tenant_a):
            results = medication_search(q="MedicamentoDeB")
        custom = [r for r in results if r["source"] == "custom"]
        assert custom == [], "Medicamentos de otro tenant no deben ser visibles."

    def test_respects_limit(self, db: Any) -> None:
        """El límite máximo de resultados se respeta."""
        for i in range(10):
            GlobalMedicationFactory(
                generic_name=f"Betabloqueador{i}",
                form=MedicationForm.TABLETA,
                concentration="",
                is_active=True,
            )
        results = medication_search(q="Betabloqueador", limit=3)
        assert len(results) <= 3


# ===========================================================================
# selectors.medication_get
# ===========================================================================


class TestMedicationGet:
    """Tests del selector medication_get."""

    def test_returns_medication_for_tenant(self, db: Any) -> None:
        """medication_get retorna el Medication correcto en el tenant activo."""
        tenant = TenantFactory()
        med = MedicationFactory(tenant=tenant)
        with tenant_ctx(tenant):
            result = medication_get(medication_id=med.id)
        assert result.id == med.id

    def test_raises_if_not_found(self, db: Any) -> None:
        """medication_get lanza DoesNotExist para un UUID inexistente."""
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            with pytest.raises(Medication.DoesNotExist):
                medication_get(medication_id=uuid_module.uuid4())

    def test_raises_for_other_tenant(self, db: Any) -> None:
        """medication_get lanza DoesNotExist para un Medication de otro tenant (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        med_b = MedicationFactory(tenant=tenant_b)
        with tenant_ctx(tenant_a):
            with pytest.raises(Medication.DoesNotExist):
                medication_get(medication_id=med_b.id)


# ===========================================================================
# services.medication_create
# ===========================================================================


class TestMedicationCreate:
    """Tests del service medication_create."""

    def test_creates_medication_happy_path(self, db: Any) -> None:
        """medication_create crea un Medication con los campos correctos."""
        tenant = TenantFactory()
        user = UserFactory()
        with tenant_ctx(tenant):
            med = medication_create(
                tenant=tenant,
                user=user,
                generic_name="Atorvastatina",
                form=MedicationForm.TABLETA,
                commercial_name="Lipitor",
                concentration="20 mg",
                presentation="Caja con 30 tabletas",
            )
        assert med.id is not None
        assert med.tenant_id == tenant.id
        assert med.generic_name == "Atorvastatina"
        assert med.form == MedicationForm.TABLETA
        assert med.commercial_name == "Lipitor"
        assert med.concentration == "20 mg"
        assert med.presentation == "Caja con 30 tabletas"
        assert med.is_active is True
        assert med.created_by_id == user.id

    def test_strips_whitespace_from_generic_name(self, db: Any) -> None:
        """medication_create limpia espacios del generic_name."""
        tenant = TenantFactory()
        user = UserFactory()
        with tenant_ctx(tenant):
            med = medication_create(
                tenant=tenant,
                user=user,
                generic_name="  Metformina  ",
                form=MedicationForm.TABLETA,
            )
        assert med.generic_name == "Metformina"

    def test_fails_if_generic_name_empty(self, db: Any) -> None:
        """Falla si generic_name está vacío."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user = UserFactory()
        with pytest.raises(ValidationError):
            medication_create(
                tenant=tenant,
                user=user,
                generic_name="",
                form=MedicationForm.TABLETA,
            )

    def test_fails_if_generic_name_only_spaces(self, db: Any) -> None:
        """Falla si generic_name es solo espacios."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user = UserFactory()
        with pytest.raises(ValidationError):
            medication_create(
                tenant=tenant,
                user=user,
                generic_name="   ",
                form=MedicationForm.TABLETA,
            )

    def test_fails_if_form_invalid(self, db: Any) -> None:
        """Falla si form no es un valor de MedicationForm."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user = UserFactory()
        with pytest.raises(ValidationError):
            medication_create(
                tenant=tenant,
                user=user,
                generic_name="Paracetamol",
                form="capsula_inventada",
            )

    def test_fails_if_tenant_none(self, db: Any) -> None:
        """Falla si tenant es None (defensa para contextos sin HTTP)."""
        from django.core.exceptions import ValidationError

        user = UserFactory()
        with pytest.raises(ValidationError):
            medication_create(
                tenant=None,  # type: ignore[arg-type]
                user=user,
                generic_name="Paracetamol",
                form=MedicationForm.TABLETA,
            )

    def test_records_audit_log(self, db: Any) -> None:
        """medication_create registra una entrada MEDICATION_CREATE en AuditLog."""
        tenant = TenantFactory()
        user = UserFactory()
        with tenant_ctx(tenant):
            med = medication_create(
                tenant=tenant,
                user=user,
                generic_name="Clopidogrel",
                form=MedicationForm.TABLETA,
            )
        # AuditLog usa all_objects para evitar filtrado por tenant
        log = AuditLog.all_objects.filter(
            action=ActionType.MEDICATION_CREATE,
            resource_id=med.id,
        ).first()
        assert log is not None, "Debe existir una entrada de auditoría MEDICATION_CREATE."
        assert log.resource_repr == str(med.id)  # nunca el nombre del medicamento

    def test_no_physical_delete(self, db: Any) -> None:
        """Los Medication custom no se borran físicamente (DR-5)."""
        tenant = TenantFactory()
        user = UserFactory()
        with tenant_ctx(tenant):
            med = medication_create(
                tenant=tenant,
                user=user,
                generic_name="Losartán custom",
                form=MedicationForm.TABLETA,
            )
        med_id = med.id
        # Baja lógica: is_active=False, deleted_at=None sigue siendo el soft-delete del sistema.
        # No hay delete físico expuesto; verificar que el registro existe en all_objects.
        assert Medication.all_objects.filter(id=med_id).exists()


# ===========================================================================
# API — GET /recetas/medicamentos/buscar/
# ===========================================================================


class TestMedicationSearchApi:
    """Tests de la API de búsqueda de medicamentos."""

    def test_search_requires_authentication(self, db: Any, api_client: APIClient) -> None:
        """401 sin token de autenticación."""
        response = api_client.get(URL_SEARCH, {"q": "para"})
        assert response.status_code == 401

    def test_search_returns_results_for_clinical_roles(self, db: Any) -> None:
        """200 con resultados para roles clínicos (doctor, nurse, readonly)."""
        GlobalMedicationFactory(
            generic_name="Naproxeno",
            form=MedicationForm.TABLETA,
            concentration="500 mg",
            is_active=True,
        )
        tenant = TenantFactory()
        for role in [
            TenantMembership.Role.DOCTOR,
            TenantMembership.Role.NURSE,
            TenantMembership.Role.READONLY,
            TenantMembership.Role.OWNER,
            TenantMembership.Role.ADMIN,
        ]:
            user = _member(tenant, role)
            client = _auth_client(user)
            with api_tenant_ctx(tenant):
                response = client.get(URL_SEARCH, {"q": "napr"})
            assert response.status_code == 200, f"Rol {role} debe poder buscar."

    def test_search_forbidden_for_reception_and_finance(self, db: Any) -> None:
        """403 para recepción y finanzas (no tienen acceso a recetas — DR-6)."""
        tenant = TenantFactory()
        for role in [TenantMembership.Role.RECEPTION, TenantMembership.Role.FINANCE]:
            user = _member(tenant, role)
            client = _auth_client(user)
            with api_tenant_ctx(tenant):
                response = client.get(URL_SEARCH, {"q": "para"})
            assert response.status_code == 403, f"Rol {role} debe recibir 403."

    def test_search_empty_q_returns_empty_list(self, db: Any) -> None:
        """q vacío devuelve lista vacía (200)."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            response = client.get(URL_SEARCH, {"q": ""})
        assert response.status_code == 200
        assert response.data == []

    def test_search_returns_global_and_custom(self, db: Any) -> None:
        """La API devuelve medicamentos globales y custom del tenant activo."""
        GlobalMedicationFactory(
            generic_name="Enalapril",
            form=MedicationForm.TABLETA,
            concentration="10 mg",
            is_active=True,
        )
        tenant = TenantFactory()
        MedicationFactory(
            tenant=tenant,
            generic_name="EnalaprilCustomTenant",
            form=MedicationForm.TABLETA,
            concentration="",
            is_active=True,
        )
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            response = client.get(URL_SEARCH, {"q": "enalapril"})
        assert response.status_code == 200
        names = [item["generic_name"] for item in response.data]
        sources = {item["source"] for item in response.data}
        assert "Enalapril" in names
        assert "EnalaprilCustomTenant" in names
        assert "global" in sources
        assert "custom" in sources

    def test_search_custom_of_other_tenant_not_visible_via_api(self, db: Any) -> None:
        """Medication de otro tenant no aparece en la búsqueda vía API."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        MedicationFactory(
            tenant=tenant_b,
            generic_name="SecretoDeB",
            form=MedicationForm.TABLETA,
            concentration="",
            is_active=True,
        )
        user = _member(tenant_a, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)
        with api_tenant_ctx(tenant_a):
            response = client.get(URL_SEARCH, {"q": "SecretoDeB"})
        assert response.status_code == 200
        custom = [r for r in response.data if r["source"] == "custom"]
        assert custom == [], "Medicamento de otro tenant no debe ser visible."


# ===========================================================================
# API — POST /recetas/medicamentos/
# ===========================================================================


class TestMedicationCreateApi:
    """Tests de la API de creación de medicamento custom."""

    def test_create_requires_authentication(self, db: Any, api_client: APIClient) -> None:
        """401 sin token."""
        response = api_client.post(URL_CREATE, {})
        assert response.status_code == 401

    def test_create_success_for_doctor(self, db: Any) -> None:
        """201 al crear un medicamento custom con rol doctor."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)
        payload = {
            "generic_name": "Furosemida Custom",
            "form": MedicationForm.TABLETA,
            "concentration": "40 mg",
            "presentation": "Caja 20 tabletas",
        }
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, payload)
        assert response.status_code == 201, response.data
        assert response.data["generic_name"] == "Furosemida Custom"
        assert response.data["form"] == MedicationForm.TABLETA
        assert response.data["is_active"] is True
        assert "id" in response.data

    def test_create_success_for_admin(self, db: Any) -> None:
        """201 al crear con rol admin."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.ADMIN)
        client = _auth_client(user)
        payload = {"generic_name": "Atenolol Custom", "form": MedicationForm.TABLETA}
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, payload)
        assert response.status_code == 201

    def test_create_success_for_owner(self, db: Any) -> None:
        """201 al crear con rol owner."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.OWNER)
        client = _auth_client(user)
        payload = {"generic_name": "Valsartán Custom", "form": MedicationForm.CAPSULA}
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, payload)
        assert response.status_code == 201

    def test_create_forbidden_for_nurse(self, db: Any) -> None:
        """403 para enfermería: puede buscar pero no crear medicamentos custom."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.NURSE)
        client = _auth_client(user)
        payload = {"generic_name": "Algún medicamento", "form": MedicationForm.TABLETA}
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, payload)
        assert response.status_code == 403

    def test_create_forbidden_for_reception(self, db: Any) -> None:
        """403 para recepción."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.RECEPTION)
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, {"generic_name": "X", "form": MedicationForm.TABLETA})
        assert response.status_code == 403

    def test_create_forbidden_for_finance(self, db: Any) -> None:
        """403 para finanzas."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.FINANCE)
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, {"generic_name": "X", "form": MedicationForm.TABLETA})
        assert response.status_code == 403

    def test_create_fails_without_generic_name(self, db: Any) -> None:
        """400 si generic_name falta."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, {"form": MedicationForm.TABLETA})
        assert response.status_code == 400

    def test_create_fails_with_empty_generic_name(self, db: Any) -> None:
        """400 si generic_name está vacío."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, {"generic_name": "", "form": MedicationForm.TABLETA})
        assert response.status_code == 400

    def test_create_fails_with_invalid_form(self, db: Any) -> None:
        """400 si form no es un valor de MedicationForm."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, {"generic_name": "Algo", "form": "capsula_inventada"})
        assert response.status_code == 400

    def test_create_medication_is_stored_in_tenant(self, db: Any) -> None:
        """El Medication creado pertenece al tenant activo."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)
        payload = {"generic_name": "Metoprolol Custom", "form": MedicationForm.TABLETA}
        with api_tenant_ctx(tenant):
            response = client.post(URL_CREATE, payload)
        assert response.status_code == 201
        med_id = response.data["id"]
        med = Medication.all_objects.get(id=med_id)
        assert med.tenant_id == tenant.id


# ===========================================================================
# RLS — aislamiento de datos entre tenants
# ===========================================================================


class TestMedicationRLS:
    """Tests de aislamiento multi-tenant (RLS) para Medication."""

    def test_medication_of_other_tenant_not_in_queryset(self, db: Any) -> None:
        """El TenantManager filtra Medication de otro tenant."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        med_b = MedicationFactory(tenant=tenant_b)
        with tenant_ctx(tenant_a):
            exists = Medication.objects.filter(id=med_b.id).exists()
        assert not exists, "Medication de tenant_b no debe ser visible desde tenant_a."

    def test_medication_of_own_tenant_is_visible(self, db: Any) -> None:
        """El TenantManager permite ver Medication del propio tenant."""
        tenant = TenantFactory()
        med = MedicationFactory(tenant=tenant)
        with tenant_ctx(tenant):
            exists = Medication.objects.filter(id=med.id).exists()
        assert exists


# ===========================================================================
# Seed — idempotencia
# ===========================================================================


class TestSeedMedicamentos:
    """Tests del management command seed_medicamentos."""

    def test_seed_creates_medications(self, db: Any) -> None:
        """seed_medicamentos carga medicamentos en GlobalMedication."""
        assert GlobalMedication.objects.count() == 0
        call_command("seed_medicamentos", verbosity=0)
        count = GlobalMedication.objects.count()
        assert count > 100, f"Se esperan >100 medicamentos, se cargaron {count}."

    def test_seed_is_idempotent(self, db: Any) -> None:
        """Ejecutar seed_medicamentos dos veces no duplica registros."""
        call_command("seed_medicamentos", verbosity=0)
        count_first = GlobalMedication.objects.count()
        call_command("seed_medicamentos", verbosity=0)
        count_second = GlobalMedication.objects.count()
        assert count_first == count_second, (
            f"El seed no es idempotente: primera vez {count_first}, "
            f"segunda vez {count_second}."
        )

    def test_seed_dry_run_does_not_insert(self, db: Any) -> None:
        """--dry-run no inserta ningún medicamento en la BD."""
        call_command("seed_medicamentos", "--dry-run", verbosity=0)
        assert GlobalMedication.objects.count() == 0

    def test_seed_medications_are_active(self, db: Any) -> None:
        """Todos los medicamentos cargados por el seed son activos."""
        call_command("seed_medicamentos", verbosity=0)
        inactive = GlobalMedication.objects.filter(is_active=False).count()
        assert inactive == 0, f"{inactive} medicamentos inactivos tras el seed."
