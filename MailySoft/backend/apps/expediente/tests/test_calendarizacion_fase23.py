"""
Tests de las Fases 2 y 3 de la Calendarización de tratamientos.

Fase 2 — Generar cotización desde el plan:
    - quote_create_from_treatment_plan (service): copia items a la Quote,
      liga plan.quote, sin items -> ValidationError, regenerar crea una
      cotización NUEVA (no borra la anterior).
    - TreatmentPlanQuoteApi (endpoint): 201 {quote_id, status, total}, 400
      sin items, matriz de permisos (TreatmentPlanPermission), 404 IDOR.
    - TreatmentPlanOutputSerializer expone quote_id (null por defecto).

Fase 3 — Catálogo de paquetes + generar calendarización desde paquete:
    - treatment_plan_create_from_package (service): copia líneas del
      paquete a un esquema NUEVO (snapshot de nombre/precio vigente),
      paquete de otro tenant -> ValidationError, paquete sin items ->
      ValidationError.
    - TreatmentPlanFromPackageApi (endpoint): 201 detalle del plan nuevo,
      404 paquete inexistente, matriz de permisos.

Patrón: AAA. factory_boy para datos. Tenant context vía
apps.expediente.tests.conftest (tenant_ctx / api_tenant_ctx).
"""

from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.expediente.models import TreatmentPlan, TreatmentPlanStatus
from apps.expediente.selectors import treatment_plan_get
from apps.expediente.serializers import TreatmentPlanOutputSerializer
from apps.expediente.services_calendarizacion import (
    quote_create_from_treatment_plan,
    treatment_plan_create,
    treatment_plan_create_from_package,
)
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.finanzas.models import Quote
from apps.tenancy.models import TenantMembership
from tests.factories import (
    DoctorFactory,
    PatientFactory,
    ServiceConceptFactory,
    TenantFactory,
    TenantMembershipFactory,
    TreatmentPackageFactory,
    TreatmentPackageItemFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_QUOTE_URL_TMPL = "/api/v1/expediente/calendarizaciones/{plan_id}/cotizacion/"
_FROM_PACKAGE_URL_TMPL = "/api/v1/expediente/{patient_id}/calendarizaciones/desde-paquete/"


def _member(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> Any:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _setup(tenant: Any = None) -> tuple[Any, Any, Any]:
    tenant = tenant or TenantFactory()
    doctor = DoctorFactory(tenant=tenant)
    patient = PatientFactory(tenant=tenant)
    return tenant, patient, doctor


_SIMPLE_ITEM: dict[str, Any] = {
    "description": "Limpieza facial profunda",
    "unit_price": "500.00",
    "quantity": 3,
}


# ===========================================================================
# Fase 2 — quote_create_from_treatment_plan (service)
# ===========================================================================


class TestQuoteCreateFromTreatmentPlan:
    def test_creates_draft_quote_with_matching_items(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("500.00"))

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                items=[{"concept_id": str(concept.id), "quantity": 4}],
                doctor=doctor,
                actor_role="doctor",
            )
            quote = quote_create_from_treatment_plan(plan=plan, user=actor, actor_role="doctor")

        assert quote.status == Quote.Status.DRAFT
        assert quote.patient_id == patient.id
        assert quote.items.count() == 1
        item = quote.items.first()
        assert item.concept_id == concept.id
        assert item.description == concept.name
        assert item.quantity == Decimal("4.00")
        assert item.unit_price == Decimal("500.00")
        assert item.line_total == Decimal("2000.00")
        assert quote.total == Decimal("2000.00")

        plan.refresh_from_db()
        assert plan.quote_id == quote.id

    def test_plan_without_items_raises(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient, actor=actor, items=[], doctor=doctor, actor_role="doctor"
            )
            with pytest.raises(DjangoValidationError, match="no tiene tratamientos"):
                quote_create_from_treatment_plan(plan=plan, user=actor, actor_role="doctor")

    def test_disallowed_role_raises(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )
            with pytest.raises(DjangoValidationError):
                quote_create_from_treatment_plan(plan=plan, user=actor, actor_role="reception")

    def test_regenerating_creates_new_quote_and_relinks(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )
            first_quote = quote_create_from_treatment_plan(
                plan=plan, user=actor, actor_role="doctor"
            )
            plan = treatment_plan_get(plan_id=plan.id)
            second_quote = quote_create_from_treatment_plan(
                plan=plan, user=actor, actor_role="doctor"
            )

        assert first_quote.id != second_quote.id
        plan.refresh_from_db()
        assert plan.quote_id == second_quote.id
        # La cotización anterior sigue existiendo (no se borra ni cancela).
        assert Quote.objects.filter(id=first_quote.id).exists()


# ===========================================================================
# Fase 2 — TreatmentPlanQuoteApi (endpoint)
# ===========================================================================


class TestTreatmentPlanQuoteApi:
    def test_owner_generates_quote_201(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )

        user = _member(tenant, "owner")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_QUOTE_URL_TMPL.format(plan_id=plan.id))

        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert "quote_id" in data
        assert data["status"] == Quote.Status.DRAFT
        assert data["total"] == "1500.00"

    def test_plan_without_items_returns_400(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                items=[],
                doctor=doctor,
                actor_role="doctor",
            )

        user = _member(tenant, "owner")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_QUOTE_URL_TMPL.format(plan_id=plan.id))
        assert resp.status_code == 400

    def test_reception_forbidden(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )

        user = _member(tenant, "reception")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_QUOTE_URL_TMPL.format(plan_id=plan.id))
        assert resp.status_code == 403

    def test_unknown_plan_returns_404(self, db: Any) -> None:
        import uuid

        tenant = TenantFactory()
        user = _member(tenant, "owner")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_QUOTE_URL_TMPL.format(plan_id=uuid.uuid4()))
        assert resp.status_code == 404

    def test_plan_from_other_tenant_returns_404(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        other_tenant = TenantFactory()
        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )

        user = _member(other_tenant, "owner")
        client = _auth_client(user)
        with api_tenant_ctx(other_tenant):
            resp = client.post(_QUOTE_URL_TMPL.format(plan_id=plan.id))
        assert resp.status_code == 404


# ===========================================================================
# Fase 2 — TreatmentPlanOutputSerializer expone quote_id
# ===========================================================================


class TestTreatmentPlanSerializerQuoteId:
    def test_quote_id_null_by_default(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )
            data = TreatmentPlanOutputSerializer(plan).data

        assert data["quote_id"] is None

    def test_quote_id_set_after_generating_quote(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user
        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )
            quote = quote_create_from_treatment_plan(plan=plan, user=actor, actor_role="doctor")
            plan = treatment_plan_get(plan_id=plan.id)
            data = TreatmentPlanOutputSerializer(plan).data

        assert data["quote_id"] == str(quote.id)


# ===========================================================================
# Fase 3 — treatment_plan_create_from_package (service)
# ===========================================================================


class TestTreatmentPlanCreateFromPackage:
    def test_creates_new_plan_with_sessions_from_package(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user
        package = TreatmentPackageFactory(tenant=tenant, name="Paquete Facial")
        concept_1 = ServiceConceptFactory(
            tenant=tenant, name="Limpieza", base_price=Decimal("400.00")
        )
        concept_2 = ServiceConceptFactory(
            tenant=tenant, name="Peeling", base_price=Decimal("600.00")
        )
        TreatmentPackageItemFactory(package=package, service_concept=concept_1, sessions=3, order=0)
        TreatmentPackageItemFactory(package=package, service_concept=concept_2, sessions=2, order=1)

        with tenant_ctx(tenant):
            plan = treatment_plan_create_from_package(
                patient=patient, actor=actor, package=package, actor_role="doctor"
            )

        assert plan.title == "Paquete Facial"
        assert plan.status == TreatmentPlanStatus.ACTIVA
        items = list(plan.items.order_by("order"))
        assert len(items) == 2
        assert items[0].description == "Limpieza"
        assert items[0].unit_price == Decimal("400.00")
        assert items[0].quantity == 3
        assert items[0].sessions.count() == 3
        assert items[1].description == "Peeling"
        assert items[1].quantity == 2
        assert items[1].sessions.count() == 2

    def test_package_from_other_tenant_raises(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        other_tenant = TenantFactory()
        other_package = TreatmentPackageFactory(tenant=other_tenant)
        other_concept = ServiceConceptFactory(tenant=other_tenant)
        TreatmentPackageItemFactory(package=other_package, service_concept=other_concept)

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError, match="no pertenece a esta clínica"):
                treatment_plan_create_from_package(
                    patient=patient,
                    actor=doctor.membership.user,
                    package=other_package,
                    actor_role="doctor",
                )

    def test_inactive_package_raises(self, db: Any) -> None:
        """FIX 4: un paquete desactivado no puede usarse para un esquema nuevo."""
        tenant, patient, doctor = _setup()
        package = TreatmentPackageFactory(tenant=tenant, is_active=False)
        concept = ServiceConceptFactory(tenant=tenant)
        TreatmentPackageItemFactory(package=package, service_concept=concept)

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError, match="está desactivado"):
                treatment_plan_create_from_package(
                    patient=patient,
                    actor=doctor.membership.user,
                    package=package,
                    actor_role="doctor",
                )

    def test_package_without_items_raises(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        package = TreatmentPackageFactory(tenant=tenant)

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError, match="no tiene tratamientos"):
                treatment_plan_create_from_package(
                    patient=patient,
                    actor=doctor.membership.user,
                    package=package,
                    actor_role="doctor",
                )

    def test_disallowed_role_raises(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        package = TreatmentPackageFactory(tenant=tenant)
        concept = ServiceConceptFactory(tenant=tenant)
        TreatmentPackageItemFactory(package=package, service_concept=concept)

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError):
                treatment_plan_create_from_package(
                    patient=patient,
                    actor=doctor.membership.user,
                    package=package,
                    actor_role="finance",
                )


# ===========================================================================
# Fase 3 — TreatmentPlanFromPackageApi (endpoint)
# ===========================================================================


class TestTreatmentPlanFromPackageApi:
    def test_doctor_creates_plan_from_package_201(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        package = TreatmentPackageFactory(tenant=tenant, name="Paquete API")
        concept = ServiceConceptFactory(tenant=tenant, base_price=Decimal("300.00"))
        TreatmentPackageItemFactory(package=package, service_concept=concept, sessions=5)

        user = _member(tenant, "doctor")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _FROM_PACKAGE_URL_TMPL.format(patient_id=patient.id),
                data={"package_id": str(package.id)},
                format="json",
            )

        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert data["title"] == "Paquete API"
        assert len(data["items"]) == 1
        assert data["items"][0]["quantity"] == 5

        # Se creó un esquema NUEVO (persistido, tenant-aislado).
        with tenant_ctx(tenant):
            assert TreatmentPlan.objects.filter(patient=patient, title="Paquete API").count() == 1

    def test_unknown_package_returns_404(self, db: Any) -> None:
        import uuid

        tenant, patient, doctor = _setup()
        user = _member(tenant, "owner")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _FROM_PACKAGE_URL_TMPL.format(patient_id=patient.id),
                data={"package_id": str(uuid.uuid4())},
                format="json",
            )
        assert resp.status_code == 404

    def test_package_from_other_tenant_returns_404(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        other_tenant = TenantFactory()
        other_package = TreatmentPackageFactory(tenant=other_tenant)
        other_concept = ServiceConceptFactory(tenant=other_tenant)
        TreatmentPackageItemFactory(package=other_package, service_concept=other_concept)

        user = _member(tenant, "owner")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _FROM_PACKAGE_URL_TMPL.format(patient_id=patient.id),
                data={"package_id": str(other_package.id)},
                format="json",
            )
        assert resp.status_code == 404

    def test_reception_forbidden(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        package = TreatmentPackageFactory(tenant=tenant)
        concept = ServiceConceptFactory(tenant=tenant)
        TreatmentPackageItemFactory(package=package, service_concept=concept)

        user = _member(tenant, "reception")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _FROM_PACKAGE_URL_TMPL.format(patient_id=patient.id),
                data={"package_id": str(package.id)},
                format="json",
            )
        assert resp.status_code == 403

    def test_unknown_patient_returns_404(self, db: Any) -> None:
        import uuid

        tenant = TenantFactory()
        package = TreatmentPackageFactory(tenant=tenant)
        concept = ServiceConceptFactory(tenant=tenant)
        TreatmentPackageItemFactory(package=package, service_concept=concept)

        user = _member(tenant, "owner")
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _FROM_PACKAGE_URL_TMPL.format(patient_id=uuid.uuid4()),
                data={"package_id": str(package.id)},
                format="json",
            )
        assert resp.status_code == 404
