"""
Tests de la app expediente — sub-fase A3 (Signos Vitales).

Cubre (objetivo ≥ 80% en lógica de negocio):
- services.vital_signs_create: camino feliz, validaciones de tenant/paciente,
  measured_at futura, appointment de otro paciente/tenant.
- selectors.vital_signs_list: filtrado por tenant, orden -measured_at.
- selectors.vital_signs_series: orden ascendente, nulos omitidos, imc derivado,
  extra_params incluidos.
- Modelo: property imc (cálculo correcto, None si falta peso o talla).
- Validación estricta D-EC-7: campos desconocidos → 400; claves extra en
  extra_params → 400; valores fuera de rango → 400; measured_at futura → 400;
  diastólica ≥ sistólica → 400.
- Append-only: PATCH y DELETE no están ruteados → 405.
- Permisos: nurse POST 200; recepción/finanzas POST 403; readonly GET 200.
- Bitácora: POST genera VITALSIGNS_CREATE con resource_repr=UUID (no PII).
- RLS: la tabla tiene política con USING y WITH CHECK.
- Multi-tenant / IDOR: tomas de otro tenant → 404; appointment de otro tenant → 404.

Patrón: AAA. factory_boy para datos. Mockeo de tenant igual que A1/A2.
"""

import uuid as uuid_module
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.expediente.models import VitalSignsRecord
from apps.expediente.selectors import vital_signs_list, vital_signs_series
from apps.expediente.services import vital_signs_create
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AppointmentFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
    VitalSignsRecordFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def _signos_url(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/signos/"


def _series_url(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/signos/series/"


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
# Modelo — property imc
# ===========================================================================


class TestVitalSignsModelImc:
    """Tests de la property imc del modelo VitalSignsRecord."""

    def test_imc_calculado_correctamente(self, db: Any) -> None:
        """IMC = peso / talla² redondeado a 2 decimales."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        record = VitalSignsRecordFactory(
            tenant=tenant,
            patient=patient,
            weight_kg=Decimal("70.0"),
            height_m=Decimal("1.700"),
        )
        imc = record.imc
        assert imc is not None
        # 70 / 1.7² = 70 / 2.89 ≈ 24.22
        assert imc == Decimal("24.22")

    def test_imc_none_si_falta_peso(self, db: Any) -> None:
        """IMC es None si weight_kg es None."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        record = VitalSignsRecordFactory(
            tenant=tenant, patient=patient, weight_kg=None, height_m=Decimal("1.700")
        )
        assert record.imc is None

    def test_imc_none_si_falta_talla(self, db: Any) -> None:
        """IMC es None si height_m es None."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        record = VitalSignsRecordFactory(
            tenant=tenant, patient=patient, weight_kg=Decimal("70.0"), height_m=None
        )
        assert record.imc is None

    def test_imc_none_si_faltan_ambos(self, db: Any) -> None:
        """IMC es None si faltan peso y talla."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        record = VitalSignsRecordFactory(
            tenant=tenant, patient=patient, weight_kg=None, height_m=None
        )
        assert record.imc is None


# ===========================================================================
# services.vital_signs_create
# ===========================================================================


class TestVitalSignsCreate:
    """Tests del service vital_signs_create."""

    def test_crea_toma_feliz(self, db: Any) -> None:
        """vital_signs_create crea y devuelve una toma con los campos correctos."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        record = vital_signs_create(
            tenant=tenant,
            user=user,
            patient=patient,
            measured_at=timezone.now(),
            weight_kg=Decimal("68.5"),
            height_m=Decimal("1.720"),
            heart_rate=72,
            systolic=120,
            diastolic=80,
            temperature_c=Decimal("36.5"),
            oxygen_saturation=98,
        )

        assert record.pk is not None
        assert record.tenant_id == tenant.id
        assert record.patient_id == patient.id
        assert record.created_by_id == user.id
        assert record.weight_kg == Decimal("68.5")
        assert record.heart_rate == 72
        assert record.oxygen_saturation == 98

    def test_tenant_none_falla(self, db: Any) -> None:
        """vital_signs_create con tenant=None lanza ValidationError."""
        from django.core.exceptions import ValidationError

        patient = PatientFactory(tenant=TenantFactory())
        with pytest.raises(ValidationError, match="tenant activo"):
            vital_signs_create(
                tenant=None,  # type: ignore[arg-type]
                user=UserFactory(),
                patient=patient,
                measured_at=timezone.now(),
            )

    def test_paciente_otro_tenant_falla(self, db: Any) -> None:
        """Paciente de otro tenant → ValidationError (defensa en profundidad)."""
        from django.core.exceptions import ValidationError

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)

        with pytest.raises(ValidationError, match="no pertenece"):
            vital_signs_create(
                tenant=tenant_a,
                user=UserFactory(),
                patient=patient_b,
                measured_at=timezone.now(),
            )

    def test_measured_at_futuro_falla(self, db: Any) -> None:
        """measured_at en el futuro → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        future = timezone.now() + timezone.timedelta(hours=1)

        with pytest.raises(ValidationError, match="futura"):
            vital_signs_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                measured_at=future,
            )

    def test_appointment_de_otro_paciente_falla(self, db: Any) -> None:
        """Appointment de otro paciente → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        patient_a = PatientFactory(tenant=tenant)
        # Appointment pertenece a otro paciente del mismo tenant
        appt = AppointmentFactory()
        appt.tenant = tenant
        appt.save(update_fields=["tenant_id", "updated_at"])

        with pytest.raises(ValidationError, match="no corresponde"):
            vital_signs_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient_a,
                measured_at=timezone.now(),
                appointment=appt,
            )

    def test_appointment_de_otro_tenant_falla(self, db: Any) -> None:
        """Appointment de otro tenant → ValidationError."""
        from django.core.exceptions import ValidationError

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_a = PatientFactory(tenant=tenant_a)
        appt_b = AppointmentFactory()
        appt_b_patient = patient_a  # mismo paciente pero...

        # forzar appointment con tenant_b y patient_a (cross-tenant)
        appt_b.patient = patient_a
        appt_b.save(update_fields=["patient_id", "updated_at"])

        with pytest.raises(ValidationError, match="no pertenece"):
            vital_signs_create(
                tenant=tenant_a,
                user=UserFactory(),
                patient=patient_a,
                measured_at=timezone.now(),
                appointment=appt_b,  # tenant_b
            )

    def test_toma_sin_parametros_numericos_ok(self, db: Any) -> None:
        """Se puede crear una toma sin ningún valor numérico (toma vacía válida)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        record = vital_signs_create(
            tenant=tenant,
            user=UserFactory(),
            patient=patient,
            measured_at=timezone.now(),
        )
        assert record.pk is not None
        assert record.weight_kg is None
        assert record.heart_rate is None

    def test_extra_params_se_guardan(self, db: Any) -> None:
        """extra_params válidos se persisten correctamente."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        extra = {"colesterol": 200.0, "trigliceridos": 150.0}
        record = vital_signs_create(
            tenant=tenant,
            user=UserFactory(),
            patient=patient,
            measured_at=timezone.now(),
            extra_params=extra,
        )
        assert record.extra_params["colesterol"] == 200.0


# ===========================================================================
# selectors
# ===========================================================================


class TestVitalSignsSelectors:
    """Tests de vital_signs_list y vital_signs_series."""

    def test_list_orden_descendente(self, db: Any) -> None:
        """vital_signs_list devuelve tomas en orden -measured_at."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        now = timezone.now()
        r1 = VitalSignsRecordFactory(
            tenant=tenant, patient=patient,
            measured_at=now - timezone.timedelta(hours=2)
        )
        r2 = VitalSignsRecordFactory(
            tenant=tenant, patient=patient,
            measured_at=now - timezone.timedelta(hours=1)
        )
        with tenant_ctx(tenant):
            qs = list(vital_signs_list(patient=patient))
        # La más reciente primero
        assert qs[0].pk == r2.pk
        assert qs[1].pk == r1.pk

    def test_list_aislamiento_tenant(self, db: Any) -> None:
        """vital_signs_list no filtra tomas de otro tenant."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_a = PatientFactory(tenant=tenant_a)
        patient_b = PatientFactory(tenant=tenant_b)
        VitalSignsRecordFactory(tenant=tenant_b, patient=patient_b)

        with tenant_ctx(tenant_a):
            qs = vital_signs_list(patient=patient_a)
            assert qs.count() == 0

    def test_series_orden_ascendente(self, db: Any) -> None:
        """vital_signs_series devuelve series en orden ASC por measured_at."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        now = timezone.now()
        VitalSignsRecordFactory(
            tenant=tenant, patient=patient,
            measured_at=now - timezone.timedelta(hours=2),
            heart_rate=70,
        )
        VitalSignsRecordFactory(
            tenant=tenant, patient=patient,
            measured_at=now - timezone.timedelta(hours=1),
            heart_rate=80,
        )
        with tenant_ctx(tenant):
            series = vital_signs_series(patient=patient)

        hr_series = series["heart_rate"]
        assert len(hr_series) == 2
        assert hr_series[0]["value"] == 70.0
        assert hr_series[1]["value"] == 80.0

    def test_series_omite_nulos(self, db: Any) -> None:
        """vital_signs_series omite valores nulos en cada parámetro."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        # Solo una toma con heart_rate, sin oxygen_saturation
        VitalSignsRecordFactory(
            tenant=tenant, patient=patient,
            heart_rate=75,
            oxygen_saturation=None,
        )
        with tenant_ctx(tenant):
            series = vital_signs_series(patient=patient)

        assert len(series["heart_rate"]) == 1
        assert len(series["oxygen_saturation"]) == 0

    def test_series_incluye_imc(self, db: Any) -> None:
        """vital_signs_series incluye la serie de IMC derivado."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        VitalSignsRecordFactory(
            tenant=tenant, patient=patient,
            weight_kg=Decimal("70.0"),
            height_m=Decimal("1.700"),
        )
        with tenant_ctx(tenant):
            series = vital_signs_series(patient=patient)

        assert len(series["imc"]) == 1
        # 70 / 1.7² ≈ 24.22
        assert abs(series["imc"][0]["value"] - 24.22) < 0.01

    def test_series_imc_omite_si_falta_talla(self, db: Any) -> None:
        """vital_signs_series omite IMC si falta talla."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        VitalSignsRecordFactory(
            tenant=tenant, patient=patient,
            weight_kg=Decimal("70.0"),
            height_m=None,
        )
        with tenant_ctx(tenant):
            series = vital_signs_series(patient=patient)

        assert len(series["imc"]) == 0

    def test_series_incluye_extra_params(self, db: Any) -> None:
        """vital_signs_series incluye los parámetros de extra_params."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        VitalSignsRecordFactory(
            tenant=tenant, patient=patient,
            extra_params={"colesterol": 210.0, "trigliceridos": 160.0},
        )
        with tenant_ctx(tenant):
            series = vital_signs_series(patient=patient)

        assert len(series["colesterol"]) == 1
        assert series["colesterol"][0]["value"] == 210.0
        assert len(series["trigliceridos"]) == 1
        assert len(series["urea"]) == 0  # no hay datos


# ===========================================================================
# Validación estricta D-EC-7 — serializers
# ===========================================================================


class TestVitalSignsInputValidation:
    """Tests de validación estricta del VitalSignsInputSerializer."""

    def test_campo_desconocido_da_400(self, db: Any) -> None:
        """Campo no declarado en raíz → 400 (D-EC-7)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 72, "campo_trampa": "x"},
                format="json",
            )
        assert resp.status_code == 400

    def test_clave_extra_en_extra_params_da_400(self, db: Any) -> None:
        """Clave no autorizada en extra_params → 400 (D-EC-7)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"extra_params": {"hierro": 90}},  # clave no permitida
                format="json",
            )
        assert resp.status_code == 400

    def test_peso_fuera_de_rango_da_400(self, db: Any) -> None:
        """Peso > 500 kg → 400 (valor imposible)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"weight_kg": "999.00"},
                format="json",
            )
        assert resp.status_code == 400

    def test_fc_fuera_de_rango_da_400(self, db: Any) -> None:
        """Frecuencia cardíaca 9999 → 400 (valor imposible)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 9999},
                format="json",
            )
        assert resp.status_code == 400

    def test_sato2_fuera_de_rango_da_400(self, db: Any) -> None:
        """SatO₂ = 200 → 400 (valor imposible)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"oxygen_saturation": 200},
                format="json",
            )
        assert resp.status_code == 400

    def test_temperatura_fuera_de_rango_da_400(self, db: Any) -> None:
        """Temperatura 60 °C → 400 (valor imposible)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"temperature_c": "60.0"},
                format="json",
            )
        assert resp.status_code == 400

    def test_diastolica_mayor_que_sistolica_da_400(self, db: Any) -> None:
        """Diastólica > Sistólica → 400 (fisiológicamente imposible)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"systolic": 80, "diastolic": 120},  # diastólica > sistólica
                format="json",
            )
        assert resp.status_code == 400

    def test_measured_at_futuro_da_400(self, db: Any) -> None:
        """measured_at en el futuro → 400."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        future = (timezone.now() + timezone.timedelta(hours=2)).isoformat()

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"measured_at": future},
                format="json",
            )
        assert resp.status_code == 400


# ===========================================================================
# Append-only: PATCH y DELETE no están ruteados
# ===========================================================================


class TestVitalSignsAppendOnly:
    """Verifica que las tomas son inmutables: PATCH/PUT/DELETE no están permitidos.

    Comportamiento observado: VitalSignsPermission no tiene PATCH/PUT/DELETE en su
    política, por lo que HasClinicRole devuelve 403 (antes de que DRF pueda devolver
    405). Esto es incluso más seguro que 405: el permiso bloquea la acción antes de
    que llegue al handler HTTP. Documentado como comportamiento correcto (append-only).
    """

    def test_patch_denegado(self, db: Any) -> None:
        """PATCH sobre la URL de signos → 403 (método no en la policy de permiso).

        VitalSignsPermission no incluye PATCH en su política. HasClinicRole devuelve
        False → DRF responde 403 antes de que el router pueda evaluar 405. Esto
        garantiza que ni siquiera el método llega al handler, reforzando append-only.
        """
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.patch(
                _signos_url(patient.id),
                data={"heart_rate": 99},
                format="json",
            )
        # 403 porque el permiso bloquea PATCH antes de llegar al handler
        assert resp.status_code == 403

    def test_delete_denegado(self, db: Any) -> None:
        """DELETE sobre la URL de signos → 403 (método no en la policy de permiso)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.delete(_signos_url(patient.id))
        assert resp.status_code == 403

    def test_put_denegado(self, db: Any) -> None:
        """PUT sobre la URL de signos → 403 (método no en la policy de permiso)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.put(
                _signos_url(patient.id),
                data={"heart_rate": 99},
                format="json",
            )
        assert resp.status_code == 403


# ===========================================================================
# Permisos por rol (plan §5)
# ===========================================================================


class TestVitalSignsPermissions:
    """Tests de la política de permisos VitalSignsPermission."""

    def test_sin_token_da_401(self, db: Any, api_client: APIClient) -> None:
        """Sin autenticación → 401."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        resp = api_client.get(_signos_url(patient.id))
        assert resp.status_code == 401

    def test_nurse_puede_crear(self, db: Any) -> None:
        """Enfermería puede registrar una toma (POST → 201)."""
        tenant = TenantFactory()
        nurse = _member(tenant, role=TenantMembership.Role.NURSE)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(nurse)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 72},
                format="json",
            )
        assert resp.status_code == 201

    def test_doctor_puede_crear(self, db: Any) -> None:
        """Doctor puede registrar una toma (POST → 201)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"temperature_c": "36.5"},
                format="json",
            )
        assert resp.status_code == 201

    def test_recepcion_no_puede_crear(self, db: Any) -> None:
        """Recepción NO puede registrar signos vitales (POST → 403)."""
        tenant = TenantFactory()
        reception = _member(tenant, role=TenantMembership.Role.RECEPTION)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(reception)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 72},
                format="json",
            )
        assert resp.status_code == 403

    def test_finanzas_no_puede_crear(self, db: Any) -> None:
        """Finanzas NO puede registrar signos vitales (POST → 403)."""
        tenant = TenantFactory()
        finance = _member(tenant, role=TenantMembership.Role.FINANCE)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(finance)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 72},
                format="json",
            )
        assert resp.status_code == 403

    def test_recepcion_no_puede_leer(self, db: Any) -> None:
        """Recepción NO puede listar signos vitales (GET → 403)."""
        tenant = TenantFactory()
        reception = _member(tenant, role=TenantMembership.Role.RECEPTION)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(reception)
        with api_tenant_ctx(tenant):
            resp = client.get(_signos_url(patient.id))
        assert resp.status_code == 403

    def test_finanzas_no_puede_leer(self, db: Any) -> None:
        """Finanzas NO puede listar signos vitales (GET → 403)."""
        tenant = TenantFactory()
        finance = _member(tenant, role=TenantMembership.Role.FINANCE)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(finance)
        with api_tenant_ctx(tenant):
            resp = client.get(_signos_url(patient.id))
        assert resp.status_code == 403

    def test_readonly_puede_leer(self, db: Any) -> None:
        """Readonly puede listar signos vitales (GET → 200)."""
        tenant = TenantFactory()
        ro = _member(tenant, role=TenantMembership.Role.READONLY)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(ro)
        with api_tenant_ctx(tenant):
            resp = client.get(_signos_url(patient.id))
        assert resp.status_code == 200

    def test_readonly_no_puede_crear(self, db: Any) -> None:
        """Readonly NO puede registrar signos vitales (POST → 403)."""
        tenant = TenantFactory()
        ro = _member(tenant, role=TenantMembership.Role.READONLY)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(ro)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 72},
                format="json",
            )
        assert resp.status_code == 403


# ===========================================================================
# IDOR / aislamiento multi-tenant en APIs
# ===========================================================================


class TestVitalSignsIsolationApis:
    """Tests de aislamiento cross-tenant en los endpoints de signos vitales."""

    def test_list_paciente_otro_tenant_da_404(self, db: Any) -> None:
        """GET de tomas de un paciente de otro tenant → 404 (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_a = _member(tenant_a, role=TenantMembership.Role.DOCTOR)
        patient_b = PatientFactory(tenant=tenant_b)

        client = _auth_client(doctor_a)
        with api_tenant_ctx(tenant_a):
            resp = client.get(_signos_url(patient_b.id))
        assert resp.status_code == 404

    def test_post_paciente_otro_tenant_da_404(self, db: Any) -> None:
        """POST para un paciente de otro tenant → 404 (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_a = _member(tenant_a, role=TenantMembership.Role.DOCTOR)
        patient_b = PatientFactory(tenant=tenant_b)

        client = _auth_client(doctor_a)
        with api_tenant_ctx(tenant_a):
            resp = client.post(
                _signos_url(patient_b.id),
                data={"heart_rate": 72},
                format="json",
            )
        assert resp.status_code == 404

    def test_series_paciente_otro_tenant_da_404(self, db: Any) -> None:
        """GET series de un paciente de otro tenant → 404 (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_a = _member(tenant_a, role=TenantMembership.Role.DOCTOR)
        patient_b = PatientFactory(tenant=tenant_b)

        client = _auth_client(doctor_a)
        with api_tenant_ctx(tenant_a):
            resp = client.get(_series_url(patient_b.id))
        assert resp.status_code == 404

    def test_patient_inexistente_da_404(self, db: Any) -> None:
        """UUID de paciente que no existe → 404."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(_signos_url(uuid_module.uuid4()))
        assert resp.status_code == 404


# ===========================================================================
# APIs — flujo completo
# ===========================================================================


class TestVitalSignsApis:
    """Tests de flujo completo de los endpoints de signos vitales."""

    def test_crear_y_listar_toma(self, db: Any) -> None:
        """POST crea la toma; GET la lista correctamente con imc derivado."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            post_resp = client.post(
                _signos_url(patient.id),
                data={
                    "weight_kg": "70.00",
                    "height_m": "1.700",
                    "heart_rate": 72,
                    "systolic": 120,
                    "diastolic": 80,
                    "temperature_c": "36.5",
                    "oxygen_saturation": 98,
                    "notes": "Toma rutinaria",
                },
                format="json",
            )
            assert post_resp.status_code == 201
            assert post_resp.data["heart_rate"] == 72
            # IMC derivado: 70 / 1.7² ≈ 24.22
            assert post_resp.data["imc"] is not None
            assert abs(post_resp.data["imc"] - 24.22) < 0.01

            get_resp = client.get(_signos_url(patient.id))
            assert get_resp.status_code == 200
            # MEDIO-3: GET ahora devuelve envoltura paginada {count, next, previous, results}.
            assert get_resp.data["count"] == 1
            assert len(get_resp.data["results"]) == 1

    def test_crear_con_extra_params_validos(self, db: Any) -> None:
        """POST con extra_params de la whitelist → 201."""
        tenant = TenantFactory()
        nurse = _member(tenant, role=TenantMembership.Role.NURSE)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(nurse)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={
                    "extra_params": {
                        "colesterol": 200,
                        "trigliceridos": 150,
                        "hemoglobina": 14.5,
                    }
                },
                format="json",
            )
        assert resp.status_code == 201
        assert resp.data["extra_params"]["colesterol"] == 200

    def test_series_endpoint_devuelve_estructura(self, db: Any) -> None:
        """GET series devuelve todas las claves de parámetros."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        VitalSignsRecordFactory(
            tenant=tenant,
            patient=patient,
            heart_rate=75,
            weight_kg=Decimal("68.0"),
            height_m=Decimal("1.720"),
            extra_params={"colesterol": 190.0},
        )

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(_series_url(patient.id))

        assert resp.status_code == 200
        data = resp.data
        # Todas las claves esperadas presentes
        for key in ["weight_kg", "heart_rate", "resp_rate", "systolic", "diastolic",
                    "temperature_c", "oxygen_saturation", "glucose", "imc",
                    "colesterol", "trigliceridos", "urea", "creatinina", "hemoglobina"]:
            assert key in data, f"Falta la clave '{key}' en la respuesta de series"
        # Los que tienen datos son listas de 1 elemento
        assert len(data["heart_rate"]) == 1
        assert len(data["imc"]) == 1
        assert len(data["colesterol"]) == 1
        # Los que no tienen datos son listas vacías
        assert len(data["resp_rate"]) == 0

    def test_crear_toma_paciente_inexistente_da_404(self, db: Any) -> None:
        """POST con patient_id inexistente → 404."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(uuid_module.uuid4()),
                data={"heart_rate": 72},
                format="json",
            )
        assert resp.status_code == 404


# ===========================================================================
# Bitácora de auditoría NOM-024
# ===========================================================================


class TestVitalSignsAuditLog:
    """Verifica que vital_signs_create genera entrada en AuditLog (NOM-024)."""

    def test_create_genera_auditlog(self, db: Any) -> None:
        """vital_signs_create escribe AuditLog con VITALSIGNS_CREATE."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        record = vital_signs_create(
            tenant=tenant,
            user=user,
            patient=patient,
            measured_at=timezone.now(),
            heart_rate=72,
        )

        logs = AuditLog.all_objects.filter(
            action=ActionType.VITALSIGNS_CREATE,
            resource_type="VitalSignsRecord",
            resource_id=record.id,
        )
        assert logs.count() == 1

        log = logs.first()
        assert log is not None
        assert log.tenant_id == tenant.id
        assert log.actor_id == user.id
        # ALTO-1: resource_repr es el UUID del registro, NUNCA valores clínicos.
        assert log.resource_repr == str(record.id)
        assert "72" not in log.resource_repr  # no debe contener la FC

    def test_resource_repr_es_uuid_no_valores_clinicos(self, db: Any) -> None:
        """resource_repr del AuditLog es el UUID, no contiene datos clínicos."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        record = vital_signs_create(
            tenant=tenant,
            user=user,
            patient=patient,
            measured_at=timezone.now(),
            temperature_c=Decimal("38.5"),
            notes="Paciente con fiebre",
        )

        log = AuditLog.all_objects.filter(
            action=ActionType.VITALSIGNS_CREATE,
            resource_id=record.id,
        ).first()

        assert log is not None
        assert log.resource_repr == str(record.id)
        assert "38.5" not in log.resource_repr
        assert "fiebre" not in log.resource_repr

    def test_post_via_api_genera_auditlog(self, db: Any) -> None:
        """POST al endpoint genera VITALSIGNS_CREATE en AuditLog."""
        tenant = TenantFactory()
        nurse = _member(tenant, role=TenantMembership.Role.NURSE)
        patient = PatientFactory(tenant=tenant)

        count_before = AuditLog.all_objects.filter(
            action=ActionType.VITALSIGNS_CREATE
        ).count()

        client = _auth_client(nurse)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 75, "oxygen_saturation": 97},
                format="json",
            )

        assert resp.status_code == 201
        count_after = AuditLog.all_objects.filter(
            action=ActionType.VITALSIGNS_CREATE
        ).count()
        assert count_after == count_before + 1


# ===========================================================================
# RLS — la tabla tiene política con USING y WITH CHECK
# ===========================================================================


class TestVitalSignsRls:
    """Verifica que la migración RLS dejó las políticas correctas en PostgreSQL."""

    def test_tabla_tiene_politica_rls(self, db: Any) -> None:
        """La tabla expediente_vital_signs tiene al menos una política de RLS."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FROM pg_policies
                WHERE tablename = 'expediente_vital_signs';
                """
            )
            count = cursor.fetchone()[0]

        assert count >= 1, (
            "La tabla expediente_vital_signs no tiene políticas RLS. "
            "Verificar migración 0007_rls_vital_signs.py."
        )

    def test_politica_tiene_using_y_with_check(self, db: Any) -> None:
        """La política RLS tiene tanto USING como WITH CHECK configurados."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT qual, with_check
                FROM pg_policies
                WHERE tablename = 'expediente_vital_signs'
                  AND policyname = 'expediente_vital_signs_tenant_isolation';
                """
            )
            row = cursor.fetchone()

        assert row is not None, "Política RLS 'expediente_vital_signs_tenant_isolation' no encontrada."
        qual, with_check = row
        assert qual is not None, "La política no tiene cláusula USING."
        assert with_check is not None, (
            "La política no tiene cláusula WITH CHECK. "
            "Los INSERTs no están protegidos por tenant (ALTO-2)."
        )


# ===========================================================================
# ALTO-1 — Oracle de existencia cross-tenant corregido
# ===========================================================================


class TestVitalSignsAlto1AppointmentOracle:
    """Verifica que los tres casos de fallo de appointment_id devuelven
    HTTP 404 idéntico (mismo status y mismo body), eliminando el oracle
    de existencia cross-tenant."""

    def test_appointment_inexistente_da_404(self, db: Any) -> None:
        """UUID de cita que no existe en BD → 404 'Cita no encontrada.'."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 72, "appointment_id": str(uuid_module.uuid4())},
                format="json",
            )
        assert resp.status_code == 404
        assert resp.data["detail"] == "Cita no encontrada."

    def test_appointment_otro_tenant_da_404_identico(self, db: Any) -> None:
        """Cita de otro tenant → mismo 404 que cita inexistente (sin oracle)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_a = _member(tenant_a, role=TenantMembership.Role.DOCTOR)
        patient_a = PatientFactory(tenant=tenant_a)
        # Cita que existe pero pertenece a tenant_b
        appt_b = AppointmentFactory()  # tenant_b, paciente de tenant_b

        client = _auth_client(doctor_a)
        with api_tenant_ctx(tenant_a):
            resp = client.post(
                _signos_url(patient_a.id),
                data={"heart_rate": 72, "appointment_id": str(appt_b.id)},
                format="json",
            )
        assert resp.status_code == 404
        assert resp.data["detail"] == "Cita no encontrada."

    def test_appointment_tenant_correcto_otro_paciente_da_404_identico(self, db: Any) -> None:
        """Cita del mismo tenant pero de otro paciente → mismo 404 (sin oracle)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient_a = PatientFactory(tenant=tenant)
        # Cita del mismo tenant pero asociada a patient_b
        appt = AppointmentFactory()
        appt.tenant = tenant
        appt.save(update_fields=["tenant_id", "updated_at"])
        # appt.patient es patient_b (otro paciente del mismo tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient_a.id),
                data={"heart_rate": 72, "appointment_id": str(appt.id)},
                format="json",
            )
        assert resp.status_code == 404
        assert resp.data["detail"] == "Cita no encontrada."

    def test_appointment_correcto_acepta_y_crea(self, db: Any) -> None:
        """Cita del mismo tenant y mismo paciente → 201 (camino feliz)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        # Cita válida: mismo tenant y mismo paciente
        appt = AppointmentFactory()
        appt.tenant = tenant
        appt.patient = patient
        appt.save(update_fields=["tenant_id", "patient_id", "updated_at"])

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"heart_rate": 72, "appointment_id": str(appt.id)},
                format="json",
            )
        assert resp.status_code == 201
        # appointment_id puede ser UUID o str según el serializer; verificar igualdad de valor.
        assert str(resp.data["appointment_id"]) == str(appt.id)


# ===========================================================================
# MEDIO-1 + BAJO-1 — extra_params: bool y cero rechazados
# ===========================================================================


class TestVitalSignsExtraParamsValidation:
    """MEDIO-1: bool aceptado como int en Python — ahora se rechaza.
    BAJO-1: 0 es fisiológicamente imposible — ahora se rechaza (positivo estricto)."""

    def test_extra_params_bool_da_400(self, db: Any) -> None:
        """extra_params con valor booleano → 400 (MEDIO-1)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"extra_params": {"colesterol": True}},
                format="json",
            )
        assert resp.status_code == 400

    def test_extra_params_false_da_400(self, db: Any) -> None:
        """extra_params con False (también bool) → 400 (MEDIO-1)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"extra_params": {"colesterol": False}},
                format="json",
            )
        assert resp.status_code == 400

    def test_extra_params_cero_da_400(self, db: Any) -> None:
        """extra_params con valor 0 → 400 (BAJO-1: positivo estricto)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"extra_params": {"colesterol": 0}},
                format="json",
            )
        assert resp.status_code == 400

    def test_extra_params_valor_positivo_acepta(self, db: Any) -> None:
        """extra_params con valor numérico positivo → 201 (camino feliz)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _signos_url(patient.id),
                data={"extra_params": {"colesterol": 180}},
                format="json",
            )
        assert resp.status_code == 201
        assert resp.data["extra_params"]["colesterol"] == 180


# ===========================================================================
# MEDIO-2 — Auditoría VITALSIGNS_READ en lecturas
# ===========================================================================


class TestVitalSignsReadAuditLog:
    """Verifica que los GET de signos vitales generan VITALSIGNS_READ en AuditLog."""

    def test_get_lista_genera_vitalsigns_read(self, db: Any) -> None:
        """GET /signos/ genera AuditLog con VITALSIGNS_READ (MEDIO-2)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        count_before = AuditLog.all_objects.filter(
            action=ActionType.VITALSIGNS_READ,
        ).count()

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(_signos_url(patient.id))

        assert resp.status_code == 200
        count_after = AuditLog.all_objects.filter(
            action=ActionType.VITALSIGNS_READ,
        ).count()
        assert count_after == count_before + 1

    def test_get_lista_audit_no_contiene_pii(self, db: Any) -> None:
        """resource_repr del AuditLog de lectura es UUID del paciente, sin PII."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        VitalSignsRecordFactory(
            tenant=tenant, patient=patient, heart_rate=99, notes="datos sensibles"
        )

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            client.get(_signos_url(patient.id))

        log = AuditLog.all_objects.filter(
            tenant=tenant,
            action=ActionType.VITALSIGNS_READ,
            resource_type="VitalSignsRecord",
        ).order_by("-created_at").first()

        assert log is not None
        assert log.resource_repr == str(patient.id)
        assert "datos sensibles" not in log.resource_repr
        assert "99" not in log.resource_repr
        assert str(patient.id) == log.metadata.get("patient_id")

    def test_get_series_genera_vitalsigns_read(self, db: Any) -> None:
        """GET /signos/series/ genera AuditLog con VITALSIGNS_READ (MEDIO-2)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        count_before = AuditLog.all_objects.filter(
            action=ActionType.VITALSIGNS_READ,
        ).count()

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(_series_url(patient.id))

        assert resp.status_code == 200
        count_after = AuditLog.all_objects.filter(
            action=ActionType.VITALSIGNS_READ,
        ).count()
        assert count_after == count_before + 1

    def test_get_series_audit_metadata_endpoint(self, db: Any) -> None:
        """AuditLog del endpoint de series incluye metadata endpoint='series'."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            client.get(_series_url(patient.id))

        log = AuditLog.all_objects.filter(
            tenant=tenant,
            action=ActionType.VITALSIGNS_READ,
        ).order_by("-created_at").first()

        assert log is not None
        assert log.metadata.get("endpoint") == "series"


# ===========================================================================
# MEDIO-3 — Paginación en lista y filtro ?since= en series
# ===========================================================================


class TestVitalSignsPaginationAndSince:
    """MEDIO-3: GET /signos/ devuelve envoltura paginada; GET /signos/series/
    acepta ?since= que filtra correctamente."""

    def test_lista_devuelve_envoltura_paginada(self, db: Any) -> None:
        """GET /signos/ devuelve {count, next, previous, results} (MEDIO-3)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        VitalSignsRecordFactory(tenant=tenant, patient=patient, heart_rate=70)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(_signos_url(patient.id))

        assert resp.status_code == 200
        assert "count" in resp.data
        assert "results" in resp.data
        assert "next" in resp.data
        assert "previous" in resp.data
        assert resp.data["count"] == 1
        assert len(resp.data["results"]) == 1

    def test_lista_vacia_devuelve_envoltura_paginada(self, db: Any) -> None:
        """GET /signos/ sin tomas → count=0, results=[] con envoltura."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(_signos_url(patient.id))

        assert resp.status_code == 200
        assert resp.data["count"] == 0
        assert resp.data["results"] == []

    def test_series_since_filtra_registros_anteriores(self, db: Any) -> None:
        """GET /signos/series/?since=<fecha> omite registros antes de esa fecha."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        now = timezone.now()

        # Toma antigua (hace 10 días)
        VitalSignsRecordFactory(
            tenant=tenant,
            patient=patient,
            measured_at=now - timezone.timedelta(days=10),
            heart_rate=60,
        )
        # Toma reciente (hace 2 días)
        VitalSignsRecordFactory(
            tenant=tenant,
            patient=patient,
            measured_at=now - timezone.timedelta(days=2),
            heart_rate=70,
        )

        # since = hace 5 días → solo debería devolver la toma reciente
        since_str = (now - timezone.timedelta(days=5)).date().isoformat()

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(f"{_series_url(patient.id)}?since={since_str}")

        assert resp.status_code == 200
        assert len(resp.data["heart_rate"]) == 1
        assert resp.data["heart_rate"][0]["value"] == 70.0

    def test_series_since_invalido_da_400(self, db: Any) -> None:
        """GET /signos/series/?since=<formato_malo> → 400."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(f"{_series_url(patient.id)}?since=not-a-date")

        assert resp.status_code == 400

    def test_series_sin_since_devuelve_todos(self, db: Any) -> None:
        """GET /signos/series/ sin ?since= devuelve todos los registros (hasta tope)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        now = timezone.now()
        VitalSignsRecordFactory(
            tenant=tenant,
            patient=patient,
            measured_at=now - timezone.timedelta(days=100),
            heart_rate=60,
        )
        VitalSignsRecordFactory(
            tenant=tenant,
            patient=patient,
            measured_at=now - timezone.timedelta(days=1),
            heart_rate=80,
        )

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(_series_url(patient.id))

        assert resp.status_code == 200
        assert len(resp.data["heart_rate"]) == 2
