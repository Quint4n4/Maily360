"""
Tests para la feature "signos vitales capturados en la receta".

Cubre los 5 escenarios de verificación definidos en la especificación:

1. Receta con `vitals` (peso + talla) → vitals_snapshot tiene esos valores + IMC calculado.
2. Valor fuera de rango en `vitals` → 400 en la API (serializer rechaza).
3. Sin `vitals` y con última toma de enfermería → usa la última toma (comportamiento anterior).
4. Sin `vitals` y sin toma → vitals_snapshot es None.
5. Clave desconocida en `vitals` → 400 en la API (whitelist M-4).

Adicionalmente:
6. Solo peso (sin talla) en `vitals` → snapshot tiene weight_kg, imc=None.
7. Precedencia: vitals de la receta sobreescribe la última toma de enfermería.
8. `vitals` con todos los campos en None → se cae al fallback de enfermería.
9. Servicio: prescription_create con vitals → snapshot.source == "prescription".
10. Servicio: prescription_create sin vitals → snapshot.source == "nursing" cuando hay toma.
"""

from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.recetas.models import Prescription, PrescriptionStatus
from apps.recetas.serializers import PrescriptionCreateInputSerializer
from apps.recetas.services import prescription_create
from apps.recetas.tests.conftest import api_tenant_ctx, tenant_ctx
from tests.factories import (
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
    VitalSignsRecordFactory,
)
from apps.tenancy.models import TenantMembership


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ITEM: dict[str, Any] = {
    "kind": "medicamento",
    "medication_name": "Paracetamol",
    "dose": "1 tableta",
    "frequency": "cada 8 horas",
    "route": "oral",
    "duration": "5 días",
    "indication": "",
    "medication_presentation": "",
    "medication_form": "tableta",
    "medication_concentration": "500 mg",
    "quantity": "",
}


def _member_with_doctor(tenant: Any) -> tuple[Any, Any]:
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
    )
    doctor = DoctorFactory(tenant=tenant, membership=membership, is_active=True)
    doctor.created_by = membership.user
    doctor.save(update_fields=["created_by"])
    return membership.user, doctor


def _url_create(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/recetas/"


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Tests de servicio
# ---------------------------------------------------------------------------


class TestVitalsInPrescriptionService:
    """Tests del servicio prescription_create con el parámetro vitals."""

    def test_vitals_with_weight_and_height_builds_snapshot_and_imc(
        self, db: Any
    ) -> None:
        """Receta con vitals(peso+talla) → snapshot tiene esos valores + IMC calculado.

        Escenario 1 de verificación.
        IMC = peso / talla² = 70 / (1.75)² ≈ 22.86.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                vitals={
                    "weight_kg": Decimal("70.00"),
                    "height_m": Decimal("1.750"),
                },
            )

        assert rx.vitals_snapshot is not None
        snap = rx.vitals_snapshot
        assert snap["weight_kg"] == pytest.approx(70.0)
        assert snap["height_m"] == pytest.approx(1.75)
        # IMC = 70 / 1.75² = 70 / 3.0625 ≈ 22.86
        assert snap["imc"] is not None
        assert snap["imc"] == pytest.approx(22.86, abs=0.01)
        assert snap["source"] == "prescription"
        assert "measured_at" in snap

    def test_vitals_without_height_imc_is_none(self, db: Any) -> None:
        """Solo peso en vitals → snapshot tiene weight_kg, imc=None."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                vitals={"weight_kg": Decimal("65.00")},
            )

        snap = rx.vitals_snapshot
        assert snap is not None
        assert snap["weight_kg"] == pytest.approx(65.0)
        assert snap["imc"] is None
        assert snap["source"] == "prescription"

    def test_vitals_overrides_nursing_snapshot(self, db: Any) -> None:
        """Precedencia: vitals de la receta sobreescribe la última toma de enfermería.

        Escenario 7: el paciente tiene una toma con peso=80kg; el médico envía
        vitals con peso=70kg. El snapshot debe tener 70kg (vitals de la receta).
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            # Toma de enfermería con peso=80
            VitalSignsRecordFactory(
                tenant=tenant,
                patient=patient,
                weight_kg="80.00",
                height_m="1.750",
                heart_rate=75,
            )
            # El médico captura peso=70 en la receta
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                vitals={"weight_kg": Decimal("70.00"), "height_m": Decimal("1.750")},
            )

        snap = rx.vitals_snapshot
        assert snap is not None
        # Debe usar los vitals de la receta, NO la toma de enfermería
        assert snap["weight_kg"] == pytest.approx(70.0)
        assert snap["source"] == "prescription"

    def test_no_vitals_uses_nursing_snapshot(self, db: Any) -> None:
        """Sin vitals y con última toma → usa la última toma de enfermería.

        Escenario 3 de verificación.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            VitalSignsRecordFactory(
                tenant=tenant,
                patient=patient,
                weight_kg="72.00",
                height_m="1.720",
                heart_rate=68,
                systolic=118,
                diastolic=76,
            )
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                # SIN vitals → debe usar la última toma
            )

        snap = rx.vitals_snapshot
        assert snap is not None
        assert snap["weight_kg"] == pytest.approx(72.0)
        assert snap["heart_rate"] == 68
        assert snap["systolic"] == 118
        assert snap["source"] == "nursing"

    def test_no_vitals_no_nursing_snapshot_is_none(self, db: Any) -> None:
        """Sin vitals y sin toma → vitals_snapshot es None.

        Escenario 4 de verificación.
        """
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

    def test_vitals_all_none_values_falls_back_to_nursing(self, db: Any) -> None:
        """vitals dict con todos los valores en None → cae al fallback de enfermería.

        Escenario 8: si el médico envía vitals={} o todos en None, el servicio
        lo trata como "sin vitals" y usa la última toma.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            VitalSignsRecordFactory(
                tenant=tenant,
                patient=patient,
                weight_kg="68.00",
                heart_rate=70,
            )
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                vitals={"weight_kg": None, "height_m": None},
            )

        snap = rx.vitals_snapshot
        assert snap is not None
        assert snap["source"] == "nursing"
        assert snap["weight_kg"] == pytest.approx(68.0)

    def test_vitals_with_all_fields(self, db: Any) -> None:
        """vitals con todos los campos → snapshot los incluye todos."""
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)

        with tenant_ctx(tenant):
            rx = prescription_create(
                tenant=tenant,
                user=user,
                patient_id=patient.id,
                items_data=[dict(_ITEM)],
                vitals={
                    "weight_kg": Decimal("70.00"),
                    "height_m": Decimal("1.750"),
                    "heart_rate": 72,
                    "resp_rate": 16,
                    "systolic": 120,
                    "diastolic": 80,
                    "temperature_c": Decimal("36.5"),
                    "oxygen_saturation": 98,
                    "glucose": 95,
                },
            )

        snap = rx.vitals_snapshot
        assert snap is not None
        assert snap["heart_rate"] == 72
        assert snap["resp_rate"] == 16
        assert snap["systolic"] == 120
        assert snap["diastolic"] == 80
        assert snap["temperature_c"] == pytest.approx(36.5)
        assert snap["oxygen_saturation"] == 98
        assert snap["glucose"] == 95
        assert snap["source"] == "prescription"


# ---------------------------------------------------------------------------
# Tests del serializer — validación de rangos y whitelist
# ---------------------------------------------------------------------------


class TestVitalsInPrescriptionSerializer:
    """Tests del serializer VitalsInPrescriptionSerializer anidado en
    PrescriptionCreateInputSerializer.
    """

    def _base_payload(self, vitals: dict[str, Any] | None = None) -> dict[str, Any]:
        """Payload base válido para crear una receta."""
        payload: dict[str, Any] = {
            "items": [dict(_ITEM)],
            "diagnosis": "Fiebre",
        }
        if vitals is not None:
            payload["vitals"] = vitals
        return payload

    def test_valid_vitals_pass_serializer(self) -> None:
        """vitals con peso+talla válidos pasan la validación."""
        payload = self._base_payload(vitals={"weight_kg": 70.0, "height_m": 1.75})
        s = PrescriptionCreateInputSerializer(data=payload)
        assert s.is_valid(), s.errors
        vitals_out = s.validated_data.get("vitals")
        assert vitals_out is not None
        assert float(vitals_out["weight_kg"]) == pytest.approx(70.0)

    def test_no_vitals_field_is_none(self) -> None:
        """Si no se envía `vitals`, validated_data["vitals"] es None."""
        payload = self._base_payload()
        s = PrescriptionCreateInputSerializer(data=payload)
        assert s.is_valid(), s.errors
        assert s.validated_data.get("vitals") is None

    def test_weight_below_range_rejected(self) -> None:
        """weight_kg = 0.1 (< 0.2) → 400, rango fisiológico violado.

        Escenario 2 de verificación.
        """
        payload = self._base_payload(vitals={"weight_kg": 0.1})
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()
        # El error puede venir como error no_field o anidado en vitals
        errors_str = str(s.errors)
        assert "rango" in errors_str or "weight_kg" in errors_str

    def test_weight_above_range_rejected(self) -> None:
        """weight_kg = 600 (> 500) → rechazado."""
        payload = self._base_payload(vitals={"weight_kg": 600})
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()

    def test_height_below_range_rejected(self) -> None:
        """height_m = 0.1 (< 0.2) → rechazado."""
        payload = self._base_payload(vitals={"height_m": 0.1})
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()

    def test_heart_rate_above_range_rejected(self) -> None:
        """heart_rate = 350 (> 300) → rechazado."""
        payload = self._base_payload(vitals={"heart_rate": 350})
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()

    def test_oxygen_saturation_below_range_rejected(self) -> None:
        """oxygen_saturation = 30 (< 50) → rechazado."""
        payload = self._base_payload(vitals={"oxygen_saturation": 30})
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()

    def test_temperature_above_range_rejected(self) -> None:
        """temperature_c = 50 (> 45) → rechazado."""
        payload = self._base_payload(vitals={"temperature_c": 50})
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()

    def test_unknown_key_in_vitals_rejected(self) -> None:
        """Clave desconocida en vitals → rechazada (M-4 whitelist).

        Escenario 5 de verificación.
        """
        payload = self._base_payload(
            vitals={"weight_kg": 70.0, "bmi": 22.5}  # "bmi" no es una clave permitida
        )
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()
        errors_str = str(s.errors)
        assert "bmi" in errors_str or "no permitido" in errors_str

    def test_unknown_key_hemoglobin_in_vitals_rejected(self) -> None:
        """'hemoglobin' no es una clave permitida → rechazada."""
        payload = self._base_payload(vitals={"hemoglobin": 14.5})
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()

    def test_unknown_key_at_root_rejected(self) -> None:
        """Clave desconocida en el root del payload → rechazada (M-4)."""
        payload = self._base_payload()
        payload["extra_field"] = "valor"
        s = PrescriptionCreateInputSerializer(data=payload)
        assert not s.is_valid()
        assert "extra_field" in s.errors or "extra_field" in str(s.errors)


# ---------------------------------------------------------------------------
# Tests de API end-to-end
# ---------------------------------------------------------------------------


class TestVitalsInPrescriptionApi:
    """Tests de la API POST /api/v1/expediente/<patient_id>/recetas/ con vitals."""

    def test_post_with_vitals_returns_201_and_snapshot(self, db: Any) -> None:
        """POST con vitals válidos → 201 y vitals_snapshot tiene los valores.

        Escenario 1 de verificación vía API.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)
        client = _auth_client(user)

        payload = {
            "items": [dict(_ITEM)],
            "diagnosis": "Control de peso",
            "vitals": {
                "weight_kg": 70.0,
                "height_m": 1.75,
                "heart_rate": 72,
            },
        }

        with api_tenant_ctx(tenant):
            response = client.post(
                _url_create(patient.id), data=payload, format="json"
            )

        assert response.status_code == 201, response.data
        data = response.data
        snap = data.get("vitals_snapshot")
        assert snap is not None
        assert snap["weight_kg"] == pytest.approx(70.0)
        assert snap["heart_rate"] == 72
        assert snap["imc"] is not None
        assert snap["source"] == "prescription"

    def test_post_without_vitals_uses_nursing_snapshot(self, db: Any) -> None:
        """POST sin vitals y con toma previa → snapshot usa la toma de enfermería.

        Escenario 3 de verificación vía API.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)
        client = _auth_client(user)

        with tenant_ctx(tenant):
            VitalSignsRecordFactory(
                tenant=tenant,
                patient=patient,
                weight_kg="65.00",
                heart_rate=68,
            )

        payload = {"items": [dict(_ITEM)], "diagnosis": "Gripe"}

        with api_tenant_ctx(tenant):
            response = client.post(
                _url_create(patient.id), data=payload, format="json"
            )

        assert response.status_code == 201, response.data
        snap = response.data.get("vitals_snapshot")
        assert snap is not None
        assert snap["weight_kg"] == pytest.approx(65.0)
        assert snap["source"] == "nursing"

    def test_post_without_vitals_and_no_nursing_snapshot_is_null(
        self, db: Any
    ) -> None:
        """POST sin vitals y sin toma → vitals_snapshot es null.

        Escenario 4 de verificación vía API.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)
        client = _auth_client(user)

        payload = {"items": [dict(_ITEM)]}

        with api_tenant_ctx(tenant):
            response = client.post(
                _url_create(patient.id), data=payload, format="json"
            )

        assert response.status_code == 201, response.data
        assert response.data.get("vitals_snapshot") is None

    def test_post_with_out_of_range_vital_returns_400(self, db: Any) -> None:
        """POST con valor fuera de rango en vitals → 400.

        Escenario 2 de verificación vía API.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)
        client = _auth_client(user)

        payload = {
            "items": [dict(_ITEM)],
            "vitals": {"weight_kg": 600},  # > 500 kg → fuera de rango
        }

        with api_tenant_ctx(tenant):
            response = client.post(
                _url_create(patient.id), data=payload, format="json"
            )

        assert response.status_code == 400

    def test_post_with_unknown_key_in_vitals_returns_400(self, db: Any) -> None:
        """POST con clave desconocida en vitals → 400.

        Escenario 5 de verificación vía API.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)
        client = _auth_client(user)

        payload = {
            "items": [dict(_ITEM)],
            "vitals": {"weight_kg": 70, "colesterol": 200},  # "colesterol" no permitido
        }

        with api_tenant_ctx(tenant):
            response = client.post(
                _url_create(patient.id), data=payload, format="json"
            )

        assert response.status_code == 400
        errors_str = str(response.data)
        assert "colesterol" in errors_str or "no permitido" in errors_str

    def test_post_vitals_overrides_nursing_snapshot(self, db: Any) -> None:
        """POST con vitals sobreescribe la toma previa de enfermería.

        Escenario 7 vía API: la toma tiene peso=80, el médico envía peso=70.
        El snapshot debe reflejar el peso capturado en la receta.
        """
        tenant = TenantFactory()
        user, _ = _member_with_doctor(tenant)
        patient = PatientFactory(tenant=tenant, is_deceased=False)
        client = _auth_client(user)

        with tenant_ctx(tenant):
            VitalSignsRecordFactory(
                tenant=tenant,
                patient=patient,
                weight_kg="80.00",
            )

        payload = {
            "items": [dict(_ITEM)],
            "vitals": {"weight_kg": 70.0},
        }

        with api_tenant_ctx(tenant):
            response = client.post(
                _url_create(patient.id), data=payload, format="json"
            )

        assert response.status_code == 201, response.data
        snap = response.data.get("vitals_snapshot")
        assert snap is not None
        assert snap["weight_kg"] == pytest.approx(70.0)
        assert snap["source"] == "prescription"
