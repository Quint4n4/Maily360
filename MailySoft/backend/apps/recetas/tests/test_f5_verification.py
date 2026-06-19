"""
Tests — F5: verificación pública de autenticidad de receta (QR).

Endpoint público (sin auth): GET /api/v1/verificar-receta/<id>/?sig=<token>

Cubre lo crítico de un endpoint público de salud:
  - Token válido → 200 con datos NO sensibles (folio, estado, fecha, médico, clínica).
  - **Privacidad:** la respuesta NUNCA contiene PII del paciente, medicamentos ni diagnóstico.
  - Token inválido / ausente / receta inexistente → 404 uniforme (anti-enumeración).
  - Receta anulada → estado "anulada".
  - Token HMAC: round-trip correcto y rechazo de firmas inválidas (tiempo constante).
"""

import uuid as uuid_module
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.recetas.models import PrescriptionStatus
from apps.recetas.verification import verification_token, verify_token
from apps.tenancy.models import TenantMembership
from tests.factories import (
    DoctorFactory,
    PatientFactory,
    PrescriptionFactory,
    PrescriptionItemFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

VERIFY_URL = "/api/v1/verificar-receta/{pid}/"


def _verify_url(pid: Any) -> str:
    return VERIFY_URL.format(pid=str(pid))


def _make_doctor(tenant: Any) -> Any:
    user = UserFactory()
    membership = TenantMembershipFactory(
        user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR
    )
    return DoctorFactory(tenant=tenant, membership=membership)


def _make_prescription(tenant: Any, **kwargs: Any) -> Any:
    patient = PatientFactory(tenant=tenant)
    doctor = _make_doctor(tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor, **kwargs)
    return rx, patient


class _Fake:
    def __init__(self, pid: Any) -> None:
        self.id = pid


# ---------------------------------------------------------------------------
# Token HMAC (unit)
# ---------------------------------------------------------------------------


def test_token_roundtrip_and_rejection() -> None:
    fake = _Fake(uuid_module.uuid4())
    token = verification_token(prescription=fake)
    assert len(token) == 32
    assert verify_token(prescription_id=fake.id, sig=token) is True
    assert verify_token(prescription_id=fake.id, sig="x" * 32) is False
    assert verify_token(prescription_id=fake.id, sig="") is False
    # Token de otra receta no valida para esta.
    other = verification_token(prescription=_Fake(uuid_module.uuid4()))
    assert verify_token(prescription_id=fake.id, sig=other) is False


# ---------------------------------------------------------------------------
# Endpoint público
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_verify_valid_token_returns_200_without_pii() -> None:
    tenant = TenantFactory()
    rx, patient = _make_prescription(tenant, diagnosis="DiagnosticoSecretoXYZ")
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=1, medication_name="MedicamentoSecretoXYZ"
    )
    token = verification_token(prescription=rx)

    resp = APIClient().get(_verify_url(rx.id), {"sig": token})

    assert resp.status_code == 200
    data = resp.json()
    assert data["folio"] == rx.folio
    assert data["estado"] == "vigente"
    assert "medico" in data and "clinica" in data

    # PRIVACIDAD: ningún dato sensible del paciente/clínico en la respuesta.
    body = resp.content.decode("utf-8")
    assert patient.full_name not in body
    assert "MedicamentoSecretoXYZ" not in body
    assert "DiagnosticoSecretoXYZ" not in body


@pytest.mark.django_db
def test_verify_invalid_token_returns_404() -> None:
    tenant = TenantFactory()
    rx, _ = _make_prescription(tenant)
    resp = APIClient().get(_verify_url(rx.id), {"sig": "deadbeef" * 4})
    assert resp.status_code == 404


@pytest.mark.django_db
def test_verify_missing_sig_returns_404() -> None:
    tenant = TenantFactory()
    rx, _ = _make_prescription(tenant)
    resp = APIClient().get(_verify_url(rx.id))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_verify_nonexistent_prescription_returns_404() -> None:
    # Token correcto en formato para un id que no existe → 404 (no distingue de firma mala).
    random_id = uuid_module.uuid4()
    token = verification_token(prescription=_Fake(random_id))
    resp = APIClient().get(_verify_url(random_id), {"sig": token})
    assert resp.status_code == 404


@pytest.mark.django_db
def test_verify_cancelled_shows_anulada() -> None:
    tenant = TenantFactory()
    rx, _ = _make_prescription(tenant, status=PrescriptionStatus.CANCELLED)
    token = verification_token(prescription=rx)
    resp = APIClient().get(_verify_url(rx.id), {"sig": token})
    assert resp.status_code == 200
    assert resp.json()["estado"] == "anulada"
