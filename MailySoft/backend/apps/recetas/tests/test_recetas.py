"""
Tests de la app recetas — sub-fase B1.2 (Recetas médicas).

Cubre (objetivo >= 80 % en lógica de negocio):

Modelos:
  - Prescription se crea con campos correctos.
  - PrescriptionItem se crea con snapshot correcto.
  - __str__ de ambos modelos es legible.

Folio consecutivo:
  - Dos recetas del mismo tenant tienen folios distintos (1, 2).
  - Tenants distintos tienen folios independientes (ambos empiezan en 1).

Inmutabilidad / anulación:
  - Receta nace con status=active.
  - prescription_cancel cambia status a cancelled + campos de anulación.
  - No se puede anular una receta ya anulada (400).

Snapshot de signos:
  - Si el paciente tiene tomas, vitals_snapshot se congela con los valores.
  - Si el paciente no tiene tomas, vitals_snapshot es null.

Permisos:
  - Solo un usuario con Doctor activo puede crear recetas.
  - Usuario sin Doctor activo → ValidationError.
  - Solo el médico emisor o owner/admin puede anular.
  - Otro médico no puede anular una receta ajena.

Paciente fallecido:
  - Crear receta para paciente fallecido lanza ValidationError.

Aislamiento multi-tenant / IDOR:
  - prescription_get de otro tenant → 404 (Prescription.DoesNotExist).
  - prescription_list no devuelve recetas de otro tenant.

Historial paginado (API):
  - GET historial 401 sin token.
  - GET historial 200 con token válido.
  - GET historial 403 para roles sin acceso (reception, finance).

Detalle (API):
  - GET detalle 401 sin token.
  - GET detalle 200 con token válido; contiene folio, items, vitals_snapshot.
  - GET detalle 404 para receta de otro tenant.

Crear receta (API):
  - POST 401 sin token.
  - POST 201 crea receta con doctor activo.
  - POST 400 si no hay ítems.
  - POST 400 si medication_name vacío en un ítem.
  - POST 400 si indication vacío en un ítem.
  - POST 400 si paciente es de otro tenant.
  - POST 403 para usuario sin perfil Doctor.

Anular receta (API):
  - POST /anular/ 401 sin token.
  - POST /anular/ 200 anula correctamente.
  - POST /anular/ 400 si razón vacía.
  - POST /anular/ 400 si receta ya anulada.
  - POST /anular/ 400 si médico distinto al emisor.
  - POST /anular/ 200 si owner/admin.

Bitácora:
  - PRESCRIPTION_CREATE se registra en AuditLog.
  - PRESCRIPTION_CANCEL se registra en AuditLog.
  - resource_repr = folio (sin PII).
"""

import uuid as uuid_module
from typing import Any

import pytest

from apps.audit.models import ActionType, AuditLog
from apps.recetas.models import Prescription, PrescriptionItem, PrescriptionStatus
from apps.recetas.selectors import prescription_get, prescription_list
from apps.recetas.services import prescription_cancel, prescription_create
from apps.recetas.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from rest_framework.test import APIClient
from tests.factories import (
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
    VitalSignsRecordFactory,
)


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def _url_list(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/recetas/"


def _url_detail(prescription_id: Any) -> str:
    return f"/api/v1/recetas/{prescription_id}/"


def _url_cancel(prescription_id: Any) -> str:
    return f"/api/v1/recetas/{prescription_id}/anular/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ITEM = {
    "medication_name": "Paracetamol",
    "indication": "1 tableta cada 8 h por 5 días",
    "medication_presentation": "Caja con 20 tabletas",
    "medication_form": "tableta",
    "medication_concentration": "500 mg",
    "quantity": "20 tabletas",
}


def _member_with_doctor(tenant: Any) -> tuple[Any, Any]:
    """Crea un usuario con membresía doctor Y perfil Doctor en el tenant.

    Retorna (user, doctor).
    """
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
    )
    doctor = DoctorFactory(tenant=tenant, membership=membership, is_active=True)
    doctor.created_by = membership.user
    doctor.save(update_fields=["created_by"])
    return membership.user, doctor


def _member_no_doctor(tenant: Any, role: str = TenantMembership.Role.NURSE) -> Any:
    """Crea un usuario con membresía pero SIN perfil Doctor."""
    membership = TenantMembershipFactory(tenant=tenant, role=role, is_active=True)
    return membership.user


def _member_role(tenant: Any, role: str) -> Any:
    """Crea un usuario con membresía del rol dado, sin Doctor."""
    membership = TenantMembershipFactory(tenant=tenant, role=role, is_active=True)
    return membership.user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_prescription(
    tenant: Any,
    user: Any,
    patient: Any | None = None,
    items_data: list[dict[str, Any]] | None = None,
) -> Prescription:
    """Helper: crea una receta vía el servicio con contexto de tenant activo."""
    with tenant_ctx(tenant):
        if patient is None:
            patient = PatientFactory(tenant=tenant, is_deceased=False)
        return prescription_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            items_data=items_data or [dict(_ITEM)],
        )


# ===========================================================================
# Modelos
# ===========================================================================


class TestPrescriptionModel:
    """Tests básicos del modelo Prescription."""

    def test_create_prescription(self, db: Any) -> None:
        """Prescription se crea con campos correctos."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        rx = Prescription.objects.create(
            tenant=tenant,
            created_by=user,
            patient=patient,
            doctor=doctor,
            folio=1,
            status=PrescriptionStatus.ACTIVE,
            recommendations="Tomar con agua.",
        )
        assert rx.id is not None
        assert rx.folio == 1
        assert rx.status == PrescriptionStatus.ACTIVE
        assert rx.cancelled_at is None
        assert rx.cancellation_reason == ""

    def test_prescription_str(self, db: Any) -> None:
        """__str__ incluye folio y tenant."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant)
        rx = Prescription.objects.create(
            tenant=tenant,
            created_by=user,
            patient=patient,
            doctor=doctor,
            folio=42,
            status=PrescriptionStatus.ACTIVE,
        )
        s = str(rx)
        assert "42" in s
        assert "active" in s

    def test_prescription_item_str(self, db: Any) -> None:
        """PrescriptionItem.__str__ incluye order y medication_name."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant)
        rx = Prescription.objects.create(
            tenant=tenant,
            created_by=user,
            patient=patient,
            doctor=doctor,
            folio=1,
            status=PrescriptionStatus.ACTIVE,
        )
        item = PrescriptionItem.objects.create(
            tenant=tenant,
            created_by=user,
            prescription=rx,
            order=1,
            medication_name="Ibuprofeno",
            indication="1 tableta cada 8 h",
        )
        s = str(item)
        assert "1" in s
        assert "Ibuprofeno" in s


# ===========================================================================
# Servicio — prescription_create
# ===========================================================================


class TestPrescriptionCreate:
    """Tests del servicio prescription_create."""

    def test_create_happy_path(self, db: Any) -> None:
        """Crea receta con folio=1 e items correctos."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                recommendations="Reposo absoluto.",
            )

        assert rx.folio == 1
        assert rx.status == PrescriptionStatus.ACTIVE
        assert rx.doctor_id == doctor.id
        assert rx.recommendations == "Reposo absoluto."
        assert rx.items.count() == 1
        item = rx.items.first()
        assert item.medication_name == "Paracetamol"
        assert item.indication == "1 tableta cada 8 h por 5 días"
        assert item.order == 1

    def test_folio_consecutive_same_tenant(self, db: Any) -> None:
        """Dos recetas del mismo tenant tienen folios 1 y 2."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            rx1 = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
            )
            rx2 = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
            )

        assert rx1.folio == 1
        assert rx2.folio == 2

    def test_folio_independent_across_tenants(self, db: Any) -> None:
        """Tenants distintos tienen folios independientes."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, _ = _member_with_doctor(tenant_a)
        user_b, _ = _member_with_doctor(tenant_b)
        patient_a = PatientFactory(tenant=tenant_a, is_deceased=False)
        patient_b = PatientFactory(tenant=tenant_b, is_deceased=False)

        with tenant_ctx(tenant_a):
            rx_a = prescription_create(
                tenant=tenant_a,
                user=user_a,
                patient_id=patient_a.id,
                items_data=[dict(_ITEM)],
            )
        with tenant_ctx(tenant_b):
            rx_b = prescription_create(
                tenant=tenant_b,
                user=user_b,
                patient_id=patient_b.id,
                items_data=[dict(_ITEM)],
            )

        # Ambos empiezan en 1 (folios son por tenant)
        assert rx_a.folio == 1
        assert rx_b.folio == 1

    def test_no_doctor_raises(self, db: Any) -> None:
        """Usuario sin Doctor activo → PermissionDenied (M-2: error de autorización = 403)."""
        from rest_framework.exceptions import PermissionDenied

        tenant = TenantFactory()
        user = _member_no_doctor(tenant, role=TenantMembership.Role.NURSE)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            with pytest.raises(PermissionDenied, match="Solo un médico"):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    items_data=[dict(_ITEM)],
                )

    def test_deceased_patient_raises(self, db: Any) -> None:
        """Crear receta para paciente fallecido → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=True)

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="fallecido"):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    items_data=[dict(_ITEM)],
                )

    def test_no_items_raises(self, db: Any) -> None:
        """Lista de ítems vacía → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="al menos un medicamento"):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    items_data=[],
                )

    def test_item_missing_medication_name_raises(self, db: Any) -> None:
        """Ítem sin medication_name → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        bad_item = {"medication_name": "", "indication": "1 tableta c/8h"}
        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="nombre de medicamento"):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    items_data=[bad_item],
                )

    def test_item_missing_indication_raises(self, db: Any) -> None:
        """Ítem sin indication → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        bad_item = {"medication_name": "Amoxicilina", "indication": ""}
        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="indicación"):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    items_data=[bad_item],
                )

    def test_vitals_snapshot_with_toma(self, db: Any) -> None:
        """Si el paciente tiene tomas, vitals_snapshot se congela."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        # Crear una toma de signos
        with tenant_ctx(tenant):
            VitalSignsRecordFactory(
                tenant=tenant,
                patient=patient,
                weight_kg="70.00",
                height_m="1.750",
                heart_rate=72,
                systolic=120,
                diastolic=80,
            )
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
            )

        assert rx.vitals_snapshot is not None
        snap = rx.vitals_snapshot
        assert snap["weight_kg"] == pytest.approx(70.0)
        assert snap["heart_rate"] == 72
        assert snap["systolic"] == 120
        assert snap["diastolic"] == 80
        assert "measured_at" in snap

    def test_vitals_snapshot_null_without_toma(self, db: Any) -> None:
        """Sin tomas de signos, vitals_snapshot es None."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
            )

        assert rx.vitals_snapshot is None

    def test_patient_other_tenant_raises(self, db: Any) -> None:
        """Paciente de otro tenant → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, _ = _member_with_doctor(tenant_a)
        patient_b = PatientFactory(tenant=tenant_b)

        with tenant_ctx(tenant_a):
            with pytest.raises(ValidationError, match="no encontrado"):
                prescription_create(
                    tenant=tenant_a,
                    user=user_a,
                    patient_id=patient_b.id,
                    items_data=[dict(_ITEM)],
                )

    def test_audit_log_created(self, db: Any) -> None:
        """PRESCRIPTION_CREATE se registra en AuditLog."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
            )

        log = AuditLog.all_objects.filter(
            action=ActionType.PRESCRIPTION_CREATE,
            resource_id=rx.id,
        ).first()
        assert log is not None
        assert "folio" in log.resource_repr
        assert str(rx.folio) in log.resource_repr

    def test_multiple_items_created(self, db: Any) -> None:
        """Múltiples ítems se crean con orden correcto."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        items = [
            {"medication_name": "Paracetamol", "indication": "1 tab c/8h"},
            {"medication_name": "Ibuprofeno", "indication": "1 tab c/12h"},
        ]
        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=items,
            )

        assert rx.items.count() == 2
        orders = list(rx.items.order_by("order").values_list("order", flat=True))
        assert orders == [1, 2]


# ===========================================================================
# Servicio — prescription_cancel
# ===========================================================================


class TestPrescriptionCancel:
    """Tests del servicio prescription_cancel."""

    def test_cancel_happy_path(self, db: Any) -> None:
        """Anular receta con motivo cambia status a cancelled."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        user.active_role = TenantMembership.Role.DOCTOR

        rx = _make_prescription(tenant, user)

        with tenant_ctx(tenant):
            updated = prescription_cancel(
                prescription=rx,
                user=user,
                tenant=tenant,
                reason="Error en la dosis prescrita.",
            )

        assert updated.status == PrescriptionStatus.CANCELLED
        assert updated.cancelled_by_id == user.id
        assert updated.cancellation_reason == "Error en la dosis prescrita."
        assert updated.cancelled_at is not None

    def test_cancel_already_cancelled_raises(self, db: Any) -> None:
        """Anular una receta ya anulada → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        user.active_role = TenantMembership.Role.DOCTOR

        rx = _make_prescription(tenant, user)

        with tenant_ctx(tenant):
            prescription_cancel(
                prescription=rx,
                user=user,
                tenant=tenant,
                reason="Primera anulación.",
            )
            # Intentar anular de nuevo
            with pytest.raises(ValidationError, match="ya fue anulada"):
                prescription_cancel(
                    prescription=rx,
                    user=user,
                    tenant=tenant,
                    reason="Segunda anulación.",
                )

    def test_cancel_empty_reason_raises(self, db: Any) -> None:
        """Motivo vacío → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        user.active_role = TenantMembership.Role.DOCTOR

        rx = _make_prescription(tenant, user)

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="motivo"):
                prescription_cancel(
                    prescription=rx,
                    user=user,
                    tenant=tenant,
                    reason="",
                )

    def test_cancel_other_doctor_raises(self, db: Any) -> None:
        """Médico distinto al emisor no puede anular receta ajena → PermissionDenied (M-2)."""
        from rest_framework.exceptions import PermissionDenied

        tenant = TenantFactory()
        user_a, _ = _member_with_doctor(tenant)
        user_b, _ = _member_with_doctor(tenant)
        user_a.active_role = TenantMembership.Role.DOCTOR
        user_b.active_role = TenantMembership.Role.DOCTOR

        # user_a crea la receta
        rx = _make_prescription(tenant, user_a)

        # user_b intenta anularla
        with tenant_ctx(tenant):
            with pytest.raises(PermissionDenied, match="Solo el médico emisor"):
                prescription_cancel(
                    prescription=rx,
                    user=user_b,
                    tenant=tenant,
                    reason="Motivo cualquiera.",
                )

    def test_cancel_owner_can_cancel_any(self, db: Any) -> None:
        """Owner puede anular cualquier receta."""
        tenant = TenantFactory()
        user_doctor, _ = _member_with_doctor(tenant)
        user_owner = _member_role(tenant, TenantMembership.Role.OWNER)
        user_owner.active_role = TenantMembership.Role.OWNER

        rx = _make_prescription(tenant, user_doctor)

        with tenant_ctx(tenant):
            updated = prescription_cancel(
                prescription=rx,
                user=user_owner,
                tenant=tenant,
                reason="Anulada por el dueño.",
            )

        assert updated.status == PrescriptionStatus.CANCELLED

    def test_cancel_audit_log(self, db: Any) -> None:
        """PRESCRIPTION_CANCEL se registra en AuditLog."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        user.active_role = TenantMembership.Role.DOCTOR

        rx = _make_prescription(tenant, user)

        with tenant_ctx(tenant):
            prescription_cancel(
                prescription=rx,
                user=user,
                tenant=tenant,
                reason="Motivo de prueba.",
            )

        log = AuditLog.all_objects.filter(
            action=ActionType.PRESCRIPTION_CANCEL,
            resource_id=rx.id,
        ).first()
        assert log is not None
        assert str(rx.folio) in log.resource_repr


# ===========================================================================
# Selectores
# ===========================================================================


class TestPrescriptionSelectors:
    """Tests de prescription_get y prescription_list."""

    def test_prescription_get_ok(self, db: Any) -> None:
        """prescription_get retorna la receta correcta."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        rx = _make_prescription(tenant, user)

        with tenant_ctx(tenant):
            fetched = prescription_get(prescription_id=rx.id)

        assert fetched.id == rx.id
        assert fetched.folio == rx.folio

    def test_prescription_get_other_tenant_raises(self, db: Any) -> None:
        """prescription_get de otro tenant → DoesNotExist (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, _ = _member_with_doctor(tenant_a)
        rx = _make_prescription(tenant_a, user_a)

        with tenant_ctx(tenant_b):
            with pytest.raises(Prescription.DoesNotExist):
                prescription_get(prescription_id=rx.id)

    def test_prescription_list_filters_by_patient(self, db: Any) -> None:
        """prescription_list devuelve solo recetas del paciente dado."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient_a = PatientFactory(tenant=tenant, is_deceased=False)
        patient_b = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            rx_a = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient_a.id,
                items_data=[dict(_ITEM)],
            )
            prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient_b.id,
                items_data=[dict(_ITEM)],
            )

        with tenant_ctx(tenant):
            qs = prescription_list(patient=patient_a)
            ids = list(qs.values_list("id", flat=True))

        assert rx_a.id in ids
        assert len(ids) == 1

    def test_prescription_list_no_cross_tenant(self, db: Any) -> None:
        """prescription_list no devuelve recetas de otro tenant."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, _ = _member_with_doctor(tenant_a)
        patient_a = PatientFactory(tenant=tenant_a, is_deceased=False)

        with tenant_ctx(tenant_a):
            rx_a = prescription_create(
                tenant=tenant_a,
                user=user_a,
                patient_id=patient_a.id,
                items_data=[dict(_ITEM)],
            )

        # Desde tenant_b, patient_a no es visible (otro tenant) — pero probamos
        # que si accedemos al qs con tenant_b, la receta de tenant_a no aparece.
        with tenant_ctx(tenant_b):
            # Crear un patient propio del tenant_b
            patient_b = PatientFactory(tenant=tenant_b, is_deceased=False)
            qs = prescription_list(patient=patient_b)
            ids = list(qs.values_list("id", flat=True))

        assert rx_a.id not in ids


# ===========================================================================
# API — Historial (GET /expediente/<patient_id>/recetas/)
# ===========================================================================


class TestPrescriptionListApi:
    """Tests del endpoint GET /expediente/<patient_id>/recetas/."""

    def test_list_401_without_token(self, db: Any) -> None:
        """Sin token → 401."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = APIClient()
        resp = client.get(_url_list(patient.id))
        assert resp.status_code == 401

    def test_list_200_for_clinical_role(self, db: Any) -> None:
        """Usuario con rol doctor obtiene 200 con lista paginada."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
            )

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.get(_url_list(patient.id))

        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 1

    def test_list_403_for_reception(self, db: Any) -> None:
        """Recepción → 403 (no tiene CLINICAL_READ para recetas)."""
        tenant = TenantFactory()
        user = _member_role(tenant, TenantMembership.Role.RECEPTION)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.get(_url_list(patient.id))

        assert resp.status_code == 403

    def test_list_403_for_finance(self, db: Any) -> None:
        """Finanzas → 403 (no tiene CLINICAL_READ para recetas)."""
        tenant = TenantFactory()
        user = _member_role(tenant, TenantMembership.Role.FINANCE)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.get(_url_list(patient.id))

        assert resp.status_code == 403

    def test_list_404_for_patient_other_tenant(self, db: Any) -> None:
        """Paciente de otro tenant → 404."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_b, _ = _member_with_doctor(tenant_b)
        patient_a = PatientFactory(tenant=tenant_a)

        client = _auth_client(user_b)
        with api_tenant_ctx(tenant_b):
            resp = client.get(_url_list(patient_a.id))

        assert resp.status_code == 404


# ===========================================================================
# API — Detalle (GET /recetas/<prescription_id>/)
# ===========================================================================


class TestPrescriptionDetailApi:
    """Tests del endpoint GET /recetas/<prescription_id>/."""

    def test_detail_401_without_token(self, db: Any) -> None:
        """Sin token → 401."""
        client = APIClient()
        resp = client.get(_url_detail(uuid_module.uuid4()))
        assert resp.status_code == 401

    def test_detail_200_with_items_and_snapshot(self, db: Any) -> None:
        """Detalle incluye ítems, folio y vitals_snapshot."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            VitalSignsRecordFactory(
                tenant=tenant,
                patient=patient,
                weight_kg="75.00",
                heart_rate=65,
            )
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                recommendations="No mezclar con alcohol.",
            )

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.get(_url_detail(rx.id))

        assert resp.status_code == 200
        data = resp.json()
        assert data["folio"] == rx.folio
        assert data["recommendations"] == "No mezclar con alcohol."
        assert data["vitals_snapshot"] is not None
        assert data["vitals_snapshot"]["weight_kg"] == pytest.approx(75.0)
        assert len(data["items"]) == 1
        assert data["items"][0]["medication_name"] == "Paracetamol"

    def test_detail_404_for_prescription_other_tenant(self, db: Any) -> None:
        """Receta de otro tenant → 404 (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, _ = _member_with_doctor(tenant_a)
        user_b, _ = _member_with_doctor(tenant_b)

        rx = _make_prescription(tenant_a, user_a)

        client = _auth_client(user_b)
        with api_tenant_ctx(tenant_b):
            resp = client.get(_url_detail(rx.id))

        assert resp.status_code == 404


# ===========================================================================
# API — Crear receta (POST /expediente/<patient_id>/recetas/)
# ===========================================================================


class TestPrescriptionCreateApi:
    """Tests del endpoint POST /expediente/<patient_id>/recetas/."""

    _PAYLOAD: dict[str, Any] = {
        "items": [
            {
                "medication_name": "Amoxicilina",
                "indication": "1 cápsula cada 8 horas por 7 días",
                "medication_form": "capsula",
                "medication_concentration": "500 mg",
            }
        ],
        "recommendations": "Completar el tratamiento completo.",
    }

    def test_create_401_without_token(self, db: Any) -> None:
        """Sin token → 401."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = APIClient()
        resp = client.post(_url_list(patient.id), data=self._PAYLOAD, format="json")
        assert resp.status_code == 401

    def test_create_201_with_doctor(self, db: Any) -> None:
        """Doctor activo crea receta → 201."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_list(patient.id), data=self._PAYLOAD, format="json"
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["folio"] == 1
        assert len(data["items"]) == 1
        assert data["status"] == "active"

    def test_create_400_no_items(self, db: Any) -> None:
        """Payload sin items → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_list(patient.id),
                data={"items": []},
                format="json",
            )

        assert resp.status_code == 400

    def test_create_400_empty_medication_name(self, db: Any) -> None:
        """Ítem con medication_name vacío → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        payload = {
            "items": [{"medication_name": "", "indication": "1 tab c/8h"}]
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 400

    def test_create_400_empty_indication(self, db: Any) -> None:
        """Ítem sin indication → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        payload = {
            "items": [{"medication_name": "Paracetamol", "indication": ""}]
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 400

    def test_create_400_patient_other_tenant(self, db: Any) -> None:
        """Paciente de otro tenant → 404."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_b, _ = _member_with_doctor(tenant_b)
        patient_a = PatientFactory(tenant=tenant_a)

        client = _auth_client(user_b)
        with api_tenant_ctx(tenant_b):
            resp = client.post(
                _url_list(patient_a.id), data=self._PAYLOAD, format="json"
            )

        # patient_get por TenantManager → 404
        assert resp.status_code == 404

    def test_create_403_nurse_role(self, db: Any) -> None:
        """Enfermería (nurse) → 403: PrescriptionPermission POST requiere doctor/admin/owner."""
        tenant = TenantFactory()
        user = _member_no_doctor(tenant, role=TenantMembership.Role.NURSE)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_list(patient.id), data=self._PAYLOAD, format="json"
            )

        # nurse no tiene POST en PrescriptionPermission → 403 de permiso HTTP
        assert resp.status_code == 403

    def test_create_403_doctor_role_but_no_doctor_profile(self, db: Any) -> None:
        """Usuario con role=doctor pero SIN perfil Doctor activo → 403 (M-2).

        El permiso HTTP (PrescriptionPermission) acepta el role=doctor.
        Pero el servicio (prescription_create) llama doctor_get_for_user
        y no encuentra un Doctor activo → PermissionDenied → 403.
        """
        tenant = TenantFactory()
        # Crear membresía con role=doctor pero SIN crear el perfil Doctor
        membership = TenantMembershipFactory(
            tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
        )
        user = membership.user
        # NO crear DoctorFactory → no hay Doctor activo para este usuario
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_list(patient.id), data=self._PAYLOAD, format="json"
            )

        # service lanza PermissionDenied("Solo un médico...") → 403 (M-2)
        assert resp.status_code == 403


# ===========================================================================
# API — Anular receta (POST /recetas/<id>/anular/)
# ===========================================================================


class TestPrescriptionCancelApi:
    """Tests del endpoint POST /recetas/<prescription_id>/anular/."""

    def test_cancel_401_without_token(self, db: Any) -> None:
        """Sin token → 401."""
        client = APIClient()
        resp = client.post(
            _url_cancel(uuid_module.uuid4()),
            data={"reason": "Motivo"},
            format="json",
        )
        assert resp.status_code == 401

    def test_cancel_200_by_emitting_doctor(self, db: Any) -> None:
        """El médico emisor puede anular su propia receta → 200."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        rx = _make_prescription(tenant, user)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_cancel(rx.id),
                data={"reason": "Error en la prescripción."},
                format="json",
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancellation_reason"] == "Error en la prescripción."

    def test_cancel_400_empty_reason(self, db: Any) -> None:
        """Motivo vacío → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        rx = _make_prescription(tenant, user)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_cancel(rx.id),
                data={"reason": ""},
                format="json",
            )

        assert resp.status_code == 400

    def test_cancel_400_already_cancelled(self, db: Any) -> None:
        """Receta ya anulada → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        rx = _make_prescription(tenant, user)

        user.active_role = TenantMembership.Role.DOCTOR
        with tenant_ctx(tenant):
            prescription_cancel(
                prescription=rx, user=user, tenant=tenant, reason="Primera."
            )

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_cancel(rx.id),
                data={"reason": "Segunda."},
                format="json",
            )

        assert resp.status_code == 400

    def test_cancel_403_other_doctor(self, db: Any) -> None:
        """Médico ajeno → 403 (M-2: error de autorización, no de datos)."""
        tenant = TenantFactory()
        user_a, _ = _member_with_doctor(tenant)
        user_b, _ = _member_with_doctor(tenant)

        rx = _make_prescription(tenant, user_a)

        client = _auth_client(user_b)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_cancel(rx.id),
                data={"reason": "Motivo del ajeno."},
                format="json",
            )

        assert resp.status_code == 403

    def test_cancel_200_by_owner(self, db: Any) -> None:
        """Owner puede anular cualquier receta → 200."""
        tenant = TenantFactory()
        user_doctor, _ = _member_with_doctor(tenant)
        user_owner = _member_role(tenant, TenantMembership.Role.OWNER)
        rx = _make_prescription(tenant, user_doctor)

        client = _auth_client(user_owner)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_cancel(rx.id),
                data={"reason": "Anulada por el dueño."},
                format="json",
            )

        assert resp.status_code == 200

    def test_cancel_404_other_tenant(self, db: Any) -> None:
        """Receta de otro tenant → 404."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, _ = _member_with_doctor(tenant_a)
        user_b, _ = _member_with_doctor(tenant_b)

        rx = _make_prescription(tenant_a, user_a)

        client = _auth_client(user_b)
        with api_tenant_ctx(tenant_b):
            resp = client.post(
                _url_cancel(rx.id),
                data={"reason": "Motivo."},
                format="json",
            )

        assert resp.status_code == 404
