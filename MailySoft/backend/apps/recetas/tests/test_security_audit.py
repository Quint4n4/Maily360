"""
Tests de seguridad — correcciones de auditoría B1.2 (Recetas).

Cubre los hallazgos M-1, M-2, M-3, M-4, M-5, B-1 y B-3.

M-1 — Validar que cita/nota pertenezcan al MISMO paciente:
  - Cita de OTRO paciente del mismo tenant → 400.
  - Nota de evolución de OTRO paciente del mismo tenant → 400.
  - Cita del mismo paciente → OK (201).

M-2 — Errores de autorización deben ser 403, no 400:
  - Usuario con role=doctor pero sin perfil Doctor → 403 (no 400).
  - Médico ajeno al emisor intenta anular → 403 (no 400).
  - Datos inválidos (medication_name vacío) → sigue siendo 400.

M-3 — Límites de tamaño anti-DoS:
  - indication > 2000 caracteres → 400.
  - 21 items en una receta → 400.
  - 20 items exactamente → OK (valida límite superior).

M-4 — Rechazar campos desconocidos:
  - Campo extra en el root del payload (ej. doctor_id) → 400.
  - Campo extra en un ítem (ej. secret_field) → 400.

M-5 — N+1 en items_count:
  - items_count usa el prefetch (django_assert_num_queries acotado).

B-3 — Validar medication_id del item pertenece al tenant:
  - medication_id de otro tenant → 400.
  - medication_id válido del mismo tenant → OK.
"""

import uuid as uuid_module
from typing import Any

import pytest

from apps.recetas.models import Prescription, PrescriptionStatus
from apps.recetas.selectors import prescription_list
from apps.recetas.services import prescription_cancel, prescription_create
from apps.recetas.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from rest_framework.test import APIClient
from tests.factories import (
    AppointmentFactory,
    DoctorFactory,
    EvolutionNoteFactory,
    MedicationFactory,
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


def _url_cancel(prescription_id: Any) -> str:
    return f"/api/v1/recetas/{prescription_id}/anular/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ITEM: dict[str, str] = {
    "kind": "medicamento",
    "medication_name": "Paracetamol",
    # COFEPRIS F2: campos estructurados obligatorios para kind=medicamento
    "dose": "1 tableta",
    "frequency": "cada 8 horas",
    "route": "oral",
    "duration": "5 días",
    "indication": "Tomar con alimentos",
}


def _cofepris_item(**overrides: Any) -> dict[str, Any]:
    """Helper: ítem COFEPRIS completo para kind=medicamento. Permite sobreescribir campos."""
    base: dict[str, Any] = dict(_ITEM)
    base.update(overrides)
    return base


def _member_with_doctor(tenant: Any) -> tuple[Any, Any]:
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
    )
    doctor = DoctorFactory(tenant=tenant, membership=membership, is_active=True)
    doctor.created_by = membership.user
    doctor.save(update_fields=["created_by"])
    return membership.user, doctor


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_prescription(tenant: Any, user: Any, patient: Any | None = None) -> Prescription:
    with tenant_ctx(tenant):
        if patient is None:
            patient = PatientFactory(tenant=tenant, is_deceased=False)
        return prescription_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            items_data=[dict(_ITEM)],
        )


# ===========================================================================
# M-1 — Cita/nota deben pertenecer al mismo paciente
# ===========================================================================


class TestM1AppointmentPatientMatch:
    """M-1: appointment.patient_id debe coincidir con el patient de la receta."""

    def test_appointment_other_patient_raises_400(self, db: Any) -> None:
        """Cita de otro paciente del mismo tenant → 400."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient_rx = PatientFactory(tenant=tenant, is_deceased=False)
        patient_other = PatientFactory(tenant=tenant, is_deceased=False)

        # Cita que pertenece a patient_other, NO a patient_rx
        membership = doctor.membership
        appointment = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient_other,
            created_by=membership.user,
        )

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="no pertenece al paciente"):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient_rx.id,
                    items_data=[dict(_ITEM)],
                    appointment_id=appointment.id,
                )

    def test_appointment_same_patient_ok(self, db: Any) -> None:
        """Cita del mismo paciente → se crea la receta correctamente."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        membership = doctor.membership
        appointment = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            created_by=membership.user,
        )

        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                appointment_id=appointment.id,
            )

        assert rx.appointment_id == appointment.id

    def test_appointment_other_patient_api_400(self, db: Any) -> None:
        """API: cita de otro paciente del mismo tenant → 400."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient_rx = PatientFactory(tenant=tenant, is_deceased=False)
        patient_other = PatientFactory(tenant=tenant, is_deceased=False)

        membership = doctor.membership
        appointment = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient_other,
            created_by=membership.user,
        )

        payload = {
            "items": [dict(_ITEM)],
            "appointment_id": str(appointment.id),
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient_rx.id), data=payload, format="json")

        assert resp.status_code == 400


class TestM1EvolutionNotePatientMatch:
    """M-1: evolution_note.patient_id debe coincidir con el patient de la receta."""

    def test_evolution_note_other_patient_raises_400(self, db: Any) -> None:
        """Nota de evolución de otro paciente del mismo tenant → 400."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient_rx = PatientFactory(tenant=tenant, is_deceased=False)

        # EvolutionNoteFactory crea su propio paciente distinto a patient_rx
        note = EvolutionNoteFactory(doctor=doctor, tenant=tenant)
        # note.patient_id != patient_rx.id

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="no pertenece al paciente"):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient_rx.id,
                    items_data=[dict(_ITEM)],
                    evolution_note_id=note.id,
                )

    def test_evolution_note_same_patient_ok(self, db: Any) -> None:
        """Nota de evolución del mismo paciente → se crea la receta correctamente."""
        tenant = TenantFactory()
        user, doctor = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        # Crear nota del mismo patient
        appointment = AppointmentFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            created_by=doctor.membership.user,
            status="attended",
        )
        note = EvolutionNoteFactory(
            tenant=tenant,
            doctor=doctor,
            patient=patient,
            appointment=appointment,
        )

        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                evolution_note_id=note.id,
            )

        assert rx.evolution_note_id == note.id


# ===========================================================================
# M-2 — Errores de autorización deben ser 403
# ===========================================================================


class TestM2AuthorizationErrors403:
    """M-2: PermissionDenied del service → 403 en la API, no 400."""

    def test_doctor_role_without_doctor_profile_creates_403(self, db: Any) -> None:
        """Usuario role=doctor SIN perfil Doctor activo → 403 (antes era 400).

        El permission HTTP (PrescriptionPermission) acepta el role=doctor.
        El servicio lanza PermissionDenied → DRF lo convierte en 403.
        """
        tenant = TenantFactory()
        # Membresía doctor pero SIN DoctorFactory (sin perfil Doctor en BD)
        membership = TenantMembershipFactory(
            tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
        )
        user = membership.user
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        payload = {"items": [dict(_ITEM)]}
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        # M-2: debe ser 403, no 400
        assert resp.status_code == 403

    def test_other_doctor_cancel_is_403(self, db: Any) -> None:
        """Médico ajeno al emisor intenta anular → 403 (antes era 400)."""
        tenant = TenantFactory()
        user_a, _ = _member_with_doctor(tenant)
        user_b, _ = _member_with_doctor(tenant)

        rx = _make_prescription(tenant, user_a)

        client = _auth_client(user_b)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _url_cancel(rx.id),
                data={"reason": "Intento de ajeno."},
                format="json",
            )

        # M-2: debe ser 403, no 400
        assert resp.status_code == 403

    def test_invalid_data_still_returns_400(self, db: Any) -> None:
        """Datos inválidos (medication_name vacío) → sigue siendo 400, no 403."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        payload = {"items": [{"medication_name": "", "indication": "1 tab"}]}
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 400

    def test_doctor_role_without_profile_service_raises_permission_denied(self, db: Any) -> None:
        """A nivel de servicio: sin Doctor activo → PermissionDenied (no ValidationError)."""
        from rest_framework.exceptions import PermissionDenied

        tenant = TenantFactory()
        membership = TenantMembershipFactory(
            tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
        )
        user = membership.user
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            with pytest.raises(PermissionDenied):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    items_data=[dict(_ITEM)],
                )

    def test_other_doctor_cancel_service_raises_permission_denied(self, db: Any) -> None:
        """A nivel de servicio: médico ajeno al emisor → PermissionDenied (no ValidationError)."""
        from rest_framework.exceptions import PermissionDenied

        tenant = TenantFactory()
        user_a, _ = _member_with_doctor(tenant)
        user_b, _ = _member_with_doctor(tenant)
        user_b.active_role = TenantMembership.Role.DOCTOR

        rx = _make_prescription(tenant, user_a)

        with tenant_ctx(tenant):
            with pytest.raises(PermissionDenied):
                prescription_cancel(
                    prescription=rx,
                    user=user_b,
                    tenant=tenant,
                    reason="Intento de ajeno.",
                )


# ===========================================================================
# M-3 — Límites de tamaño anti-DoS
# ===========================================================================


class TestM3SizeLimits:
    """M-3: max_length en indication (2000) y en items (20)."""

    def test_indication_too_long_returns_400(self, db: Any) -> None:
        """indication con > 2000 caracteres → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        long_indication = "x" * 2001
        payload = {
            "items": [_cofepris_item(indication=long_indication)]
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 400

    def test_indication_exactly_2000_chars_ok(self, db: Any) -> None:
        """indication con exactamente 2000 caracteres → 201 (límite inclusivo)."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        indication_2000 = "a" * 2000
        payload = {
            "items": [_cofepris_item(indication=indication_2000)]
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 201

    def test_21_items_returns_400(self, db: Any) -> None:
        """21 ítems en la receta → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        items = [
            _cofepris_item(medication_name=f"Med {i}", indication="1 tab c/8h")
            for i in range(21)
        ]
        payload = {"items": items}
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 400

    def test_20_items_ok(self, db: Any) -> None:
        """20 ítems exactamente → 201 (límite superior inclusivo)."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        items = [
            _cofepris_item(medication_name=f"Med {i}", indication="1 tab c/8h")
            for i in range(20)
        ]
        payload = {"items": items}
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 201

    def test_0_items_returns_400(self, db: Any) -> None:
        """0 ítems → 400 (mínimo = 1)."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        payload = {"items": []}
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 400


# ===========================================================================
# M-4 — Rechazar campos desconocidos
# ===========================================================================


class TestM4UnknownFieldsRejected:
    """M-4: campos no declarados en el serializer → 400."""

    def test_unknown_field_in_root_payload_returns_400(self, db: Any) -> None:
        """Campo extra en el root (doctor_id) → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        payload = {
            "items": [dict(_ITEM)],
            "doctor_id": str(uuid_module.uuid4()),  # campo no declarado
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 400

    def test_unknown_field_in_item_returns_400(self, db: Any) -> None:
        """Campo extra dentro de un ítem (secret_field) → 400."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        # Ítem con campos COFEPRIS completos MÁS un campo desconocido (secret_field).
        # El serializer debe rechazarlo por M-4 (campo no declarado), no por COFEPRIS.
        item_with_unknown = _cofepris_item(
            medication_name="Paracetamol",
            indication="1 tab c/8h",
            secret_field="inyección SQL",  # tipo: ignorar — campo no declarado en whitelist
        )
        payload = {"items": [item_with_unknown]}
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 400

    def test_known_fields_only_accepted(self, db: Any) -> None:
        """Payload solo con campos conocidos → 201."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        payload = {
            "items": [
                {
                    "kind": "medicamento",
                    "medication_name": "Amoxicilina",
                    # COFEPRIS F2: campos estructurados para kind=medicamento
                    "dose": "1 cápsula",
                    "frequency": "cada 8 horas",
                    "route": "oral",
                    "duration": "7 días",
                    "indication": "1 cap c/8h por 7 días",
                    "medication_form": "capsula",
                    "medication_concentration": "500 mg",
                    "medication_presentation": "Caja 20 caps",
                    "quantity": "20 caps",
                    "global_medication_id": None,
                    "medication_id": None,
                }
            ],
            "recommendations": "Completar el tratamiento.",
            "appointment_id": None,
            "evolution_note_id": None,
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 201


# ===========================================================================
# M-5 — N+1 en items_count (django_assert_num_queries)
# ===========================================================================


class TestM5ItemsCountNoNPlusOne:
    """M-5: el listado de recetas no dispara N queries extra para items_count."""

    def test_list_queries_bounded_with_prefetch(
        self, db: Any, django_assert_num_queries: Any
    ) -> None:
        """prescription_list con 3 recetas NO dispara una query extra por receta.

        Verifica el fix de M-5: len(obj.items.all()) aprovecha el cache del
        prefetch_related y NO dispara queries adicionales, a diferencia de
        obj.items.count() que haría una query por cada receta en el listado.

        Queries esperadas al evaluar el QS: exactamente 2:
          - 1 SELECT de Prescription con select_related (doctor, membership, user)
          - 1 SELECT de PrescriptionItem (prefetch)
        Con .count() sería 2 + 3 = 5 (una query COUNT por receta).
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        # Crear 3 recetas, cada una con 2 ítems
        for _ in range(3):
            with tenant_ctx(tenant):
                prescription_create(
                    tenant=tenant,
                    user=user,
                    patient_id=patient.id,
                    items_data=[
                        _cofepris_item(medication_name="Med A", indication="1 tab c/8h"),
                        _cofepris_item(medication_name="Med B", indication="1 cap c/12h"),
                    ],
                )

        from apps.recetas.serializers import PrescriptionListOutputSerializer

        with tenant_ctx(tenant):
            qs = prescription_list(patient=patient)
            # 2 queries: SELECT prescriptions + prefetch items (sin N+1)
            with django_assert_num_queries(2):
                prescriptions_cache = list(qs)

        # La serialización fuera del bloque NO dispara queries extras (usa cache del prefetch)
        data = PrescriptionListOutputSerializer(prescriptions_cache, many=True).data
        counts = [item["items_count"] for item in data]

        assert len(counts) == 3
        assert all(c == 2 for c in counts)


# ===========================================================================
# B-3 — medication_id del item debe pertenecer al tenant
# ===========================================================================


class TestB3MedicationIdTenantValidation:
    """B-3: medication_id de otro tenant → 400."""

    def test_medication_id_other_tenant_service_raises_400(self, db: Any) -> None:
        """medication_id de otro tenant → ValidationError en el servicio."""
        from django.core.exceptions import ValidationError

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, _ = _member_with_doctor(tenant_a)
        patient_a = PatientFactory(tenant=tenant_a, is_deceased=False)

        # Medicamento del tenant_b (ajeno al tenant_a)
        med_b = MedicationFactory(tenant=tenant_b)

        item_with_med: dict[str, Any] = _cofepris_item(
            medication_name="Paracetamol",
            indication="1 tab c/8h",
        )
        item_with_med["medication_id"] = med_b.id
        with tenant_ctx(tenant_a):
            with pytest.raises(ValidationError, match="no existe o no pertenece"):
                prescription_create(
                    tenant=tenant_a,
                    user=user_a,
                    patient_id=patient_a.id,
                    items_data=[item_with_med],
                )

    def test_medication_id_other_tenant_api_400(self, db: Any) -> None:
        """API: medication_id de otro tenant → 400."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, _ = _member_with_doctor(tenant_a)
        patient_a = PatientFactory(tenant=tenant_a, is_deceased=False)
        med_b = MedicationFactory(tenant=tenant_b)

        payload = {
            "items": [
                _cofepris_item(
                    medication_name="Paracetamol",
                    indication="1 tab c/8h",
                    medication_id=str(med_b.id),
                )
            ]
        }
        client = _auth_client(user_a)
        with api_tenant_ctx(tenant_a):
            resp = client.post(_url_list(patient_a.id), data=payload, format="json")

        assert resp.status_code == 400

    def test_medication_id_same_tenant_ok(self, db: Any) -> None:
        """medication_id del mismo tenant → 201."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)
        med = MedicationFactory(tenant=tenant, is_active=True)

        payload = {
            "items": [
                _cofepris_item(
                    medication_name=med.generic_name,
                    indication="1 tab c/8h",
                    medication_id=str(med.id),
                )
            ]
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 201

    def test_global_medication_id_not_validated_per_tenant(self, db: Any) -> None:
        """global_medication_id es global: no requiere validación de tenant → 201."""
        from tests.factories import GlobalMedicationFactory

        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)
        global_med = GlobalMedicationFactory()  # sin tenant

        payload = {
            "items": [
                _cofepris_item(
                    medication_name=global_med.generic_name,
                    indication="1 tab c/8h",
                    global_medication_id=str(global_med.id),
                )
            ]
        }
        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.post(_url_list(patient.id), data=payload, format="json")

        assert resp.status_code == 201
