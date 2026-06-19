"""
Tests F6 — Módulo de medicamentos controlados.

Cubre:
1. Snapshot de controlled_group en PrescriptionItem al crear receta.
2. Receta con medicamento controlado SIN controlled_folio → 400 claro.
3. Receta con controlado + folio → 201, valid_until correcto:
   - Grupo I  → 24 horas desde issued_at.
   - Grupo II → 30 días desde issued_at.
4. Receta normal (sin controlados) → valid_until = None.
5. is_controlled property → True/False correcto.
6. PDF de receta controlada → 200 con bytes PDF (inicia %PDF) y contiene aviso.
7. Endpoint verify expone `controlado` (bool) y `vigencia` (datetime) sin PII.

Patrón: AAA. factory_boy. Fixtures: db, django_db.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.recetas.models import ControlledGroup, GlobalMedication, Prescription, PrescriptionItem
from apps.recetas.services import (
    _calculate_valid_until,
    _most_restrictive_group,
    prescription_create,
)
from apps.recetas.verification import verification_token
from tests.factories import (
    DoctorFactory,
    GlobalMedicationFactory,
    MedicationFactory,
    PatientFactory,
    PrescriptionFactory,
    PrescriptionItemFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VERIFY_URL = "/api/v1/verificar-receta/{pid}/"


def _verify_url(pid: Any) -> str:
    return VERIFY_URL.format(pid=str(pid))


def _make_doctor_user(tenant: Any) -> tuple[Any, Any]:
    """Crea un User + Doctor activo en el tenant. Retorna (user, doctor)."""
    from apps.tenancy.models import TenantMembership

    user = UserFactory()
    membership = TenantMembershipFactory(
        user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
    )
    doctor = DoctorFactory(tenant=tenant, membership=membership)
    return user, doctor


def _ctx(tenant: Any):
    """Context managers que simulan TenantMiddleware + doctor_get_for_user."""
    return (
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    )


def _base_item(*, medication_name: str = "Fármaco Test", controlled_group: str = "none") -> dict:
    """Dict base de ítem (kind=medicamento con campos COFEPRIS completos)."""
    return {
        "kind": "medicamento",
        "medication_name": medication_name,
        "dose": "1 tableta",
        "frequency": "cada 8 horas",
        "route": "oral",
        "duration": "7 días",
        "controlled_group": controlled_group,
    }


def _create_prescription(tenant: Any, user: Any, items_data: list, **kwargs: Any) -> Prescription:
    """Helper: llama prescription_create con el contexto de tenant correcto."""
    patient = PatientFactory(tenant=tenant)
    with _ctx(tenant)[0], _ctx(tenant)[1]:
        return prescription_create(
            tenant=tenant,
            user=user,
            patient_id=patient.id,
            items_data=items_data,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# 1. Snapshot de controlled_group en PrescriptionItem
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_item_snapshot_controlled_group_from_global_medication() -> None:
    """Si el ítem viene con global_medication_id de un Grupo II, el snapshot es II."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    gm = GlobalMedicationFactory(controlled_group=ControlledGroup.II)

    item = _base_item(medication_name=gm.generic_name)
    item["global_medication_id"] = str(gm.id)
    item.pop("controlled_group", None)  # debe resolverse desde el catálogo

    rx = _create_prescription(
        tenant, user, [item], controlled_folio="COFEPRIS-2026-001"
    )

    pi = PrescriptionItem.objects.get(prescription=rx)
    assert pi.controlled_group == ControlledGroup.II


@pytest.mark.django_db
def test_item_snapshot_controlled_group_from_custom_medication() -> None:
    """Si el ítem viene con medication_id (custom) de Grupo IV, el snapshot es IV."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    cm = MedicationFactory(tenant=tenant, controlled_group=ControlledGroup.IV)

    item = _base_item(medication_name=cm.generic_name)
    item["medication_id"] = str(cm.id)
    item.pop("controlled_group", None)

    rx = _create_prescription(
        tenant, user, [item], controlled_folio="COFEPRIS-2026-002"
    )

    pi = PrescriptionItem.objects.get(prescription=rx)
    assert pi.controlled_group == ControlledGroup.IV


@pytest.mark.django_db
def test_item_snapshot_non_controlled_defaults_none() -> None:
    """Un ítem sin FK a catálogo controlado tiene controlled_group='none'."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    item = _base_item(medication_name="Paracetamol")

    rx = _create_prescription(tenant, user, [item])

    pi = PrescriptionItem.objects.get(prescription=rx)
    assert pi.controlled_group == ControlledGroup.NONE


# ---------------------------------------------------------------------------
# 2. Receta controlada sin controlled_folio → 400
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_controlled_prescription_without_folio_raises_validation_error() -> None:
    """Receta con medicamento Grupo I sin controlled_folio → ValidationError 400."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    gm = GlobalMedicationFactory(controlled_group=ControlledGroup.I)
    item = _base_item(medication_name=gm.generic_name)
    item["global_medication_id"] = str(gm.id)

    with pytest.raises(ValidationError) as exc_info:
        _create_prescription(tenant, user, [item])  # sin controlled_folio

    msg = str(exc_info.value)
    assert "folio" in msg.lower() or "controlado" in msg.lower()


@pytest.mark.django_db
def test_controlled_prescription_with_empty_folio_raises_validation_error() -> None:
    """controlled_folio vacío ('') también debe fallar."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    gm = GlobalMedicationFactory(controlled_group=ControlledGroup.II)
    item = _base_item(medication_name=gm.generic_name)
    item["global_medication_id"] = str(gm.id)

    with pytest.raises(ValidationError):
        _create_prescription(tenant, user, [item], controlled_folio="   ")


# ---------------------------------------------------------------------------
# 3. Receta controlada con folio → 201 + valid_until correcto
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_controlled_group_I_valid_until_24h() -> None:
    """Grupo I → valid_until = issued_at + 24 horas (±30 segundos de tolerancia)."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    gm = GlobalMedicationFactory(controlled_group=ControlledGroup.I)
    item = _base_item(medication_name=gm.generic_name)
    item["global_medication_id"] = str(gm.id)

    before = timezone.now()
    rx = _create_prescription(
        tenant, user, [item], controlled_folio="FOLIO-GRUPO-I"
    )
    after = timezone.now()

    assert rx.valid_until is not None
    expected_min = before + timedelta(hours=24)
    expected_max = after + timedelta(hours=24)
    assert expected_min <= rx.valid_until <= expected_max

    # Folio guardado correctamente
    assert rx.controlled_folio == "FOLIO-GRUPO-I"


@pytest.mark.django_db
def test_controlled_group_II_valid_until_30_days() -> None:
    """Grupo II → valid_until = issued_at + 30 días (720 horas ±30 segundos)."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    gm = GlobalMedicationFactory(controlled_group=ControlledGroup.II)
    item = _base_item(medication_name=gm.generic_name)
    item["global_medication_id"] = str(gm.id)

    before = timezone.now()
    rx = _create_prescription(
        tenant, user, [item], controlled_folio="FOLIO-GRUPO-II"
    )
    after = timezone.now()

    assert rx.valid_until is not None
    expected_min = before + timedelta(days=30)
    expected_max = after + timedelta(days=30)
    assert expected_min <= rx.valid_until <= expected_max


@pytest.mark.django_db
def test_mixed_groups_most_restrictive_wins() -> None:
    """Si hay Grupo I y Grupo III, valid_until es 24h (el más restrictivo)."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    gm_I = GlobalMedicationFactory(controlled_group=ControlledGroup.I)
    gm_III = GlobalMedicationFactory(controlled_group=ControlledGroup.III)

    item_I = _base_item(medication_name=gm_I.generic_name)
    item_I["global_medication_id"] = str(gm_I.id)

    item_III = _base_item(medication_name=gm_III.generic_name)
    item_III["global_medication_id"] = str(gm_III.id)

    before = timezone.now()
    rx = _create_prescription(
        tenant, user, [item_I, item_III], controlled_folio="FOLIO-MIXTO"
    )
    after = timezone.now()

    assert rx.valid_until is not None
    # Debe ser ~24 horas, no 30 días
    expected_min = before + timedelta(hours=24)
    expected_max = after + timedelta(hours=24)
    assert expected_min <= rx.valid_until <= expected_max


# ---------------------------------------------------------------------------
# 4. Receta normal → valid_until = None
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_non_controlled_prescription_valid_until_none() -> None:
    """Receta sin medicamentos controlados → valid_until=None, controlled_folio=''."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    item = _base_item(medication_name="Amoxicilina")

    rx = _create_prescription(tenant, user, [item])

    assert rx.valid_until is None
    assert rx.controlled_folio == ""


# ---------------------------------------------------------------------------
# 5. is_controlled property
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_is_controlled_true_when_item_has_controlled_group() -> None:
    """is_controlled=True si algún ítem tiene controlled_group != 'none'."""
    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)

    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, controlled_group=ControlledGroup.II
    )
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, controlled_group=ControlledGroup.NONE
    )

    # Refrescar desde BD para limpiar caché de manager
    rx_fresh = Prescription.objects.prefetch_related("items").get(id=rx.id)
    assert rx_fresh.is_controlled is True


@pytest.mark.django_db
def test_is_controlled_false_when_all_items_none() -> None:
    """is_controlled=False si todos los ítems tienen controlled_group='none'."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)

    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, controlled_group=ControlledGroup.NONE
    )

    rx_fresh = Prescription.objects.prefetch_related("items").get(id=rx.id)
    assert rx_fresh.is_controlled is False


# ---------------------------------------------------------------------------
# 6. PDF de receta controlada → 200 con bytes %PDF y aviso visible
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_controlled_prescription_pdf_contains_warning_text() -> None:
    """PDF de receta controlada genera bytes válidos (%PDF) y contiene aviso F6."""
    from apps.recetas.pdf import prescription_pdf_build

    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    gm = GlobalMedicationFactory(controlled_group=ControlledGroup.II)
    item = _base_item(medication_name=gm.generic_name)
    item["global_medication_id"] = str(gm.id)

    rx = _create_prescription(
        tenant, user, [item], controlled_folio="FOLIO-PDF-TEST"
    )

    # Refrescar con prefetch_related para que is_controlled / _build_context funcionen
    from apps.recetas.selectors import prescription_get
    rx_full = prescription_get(prescription_id=rx.id)

    pdf_bytes = prescription_pdf_build(prescription=rx_full, base_layout="standard")

    # Debe ser un PDF válido
    assert pdf_bytes[:4] == b"%PDF"

    # El aviso de controlado debe aparecer en el HTML de contexto.
    # Verificamos indirectamente: el template renderiza el folio y el grupo.
    from apps.recetas.pdf import _build_context
    ctx = _build_context(rx_full)
    assert ctx["is_controlled"] is True
    assert ctx["controlled_folio"] == "FOLIO-PDF-TEST"
    assert ctx["controlled_group_top"] == ControlledGroup.II
    assert ctx["valid_until"] != ""  # fecha formateada, no vacía


@pytest.mark.django_db
def test_non_controlled_prescription_pdf_no_warning() -> None:
    """PDF de receta no controlada: is_controlled=False en contexto."""
    from apps.recetas.pdf import _build_context
    from apps.recetas.selectors import prescription_get

    tenant = TenantFactory()
    user, _ = _make_doctor_user(tenant)

    item = _base_item(medication_name="Ibuprofeno")
    rx = _create_prescription(tenant, user, [item])
    rx_full = prescription_get(prescription_id=rx.id)

    ctx = _build_context(rx_full)
    assert ctx["is_controlled"] is False
    assert ctx["controlled_folio"] == ""
    assert ctx["valid_until"] == ""


# ---------------------------------------------------------------------------
# 7. Endpoint verify expone controlado / vigencia sin PII
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_verify_controlled_prescription_exposes_controlado_and_vigencia() -> None:
    """GET verify de receta controlada → controlado=True, vigencia=datetime."""
    from rest_framework.test import APIClient

    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)

    rx = PrescriptionFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        controlled_folio="FOLIO-VERIFY",
        valid_until=timezone.now() + timedelta(hours=24),
    )
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, controlled_group=ControlledGroup.I
    )

    token = verification_token(prescription=rx)
    resp = APIClient().get(_verify_url(rx.id), {"sig": token})

    assert resp.status_code == 200
    data = resp.json()

    # F6: campos obligatorios en respuesta pública
    assert "controlado" in data
    assert "vigencia" in data
    assert data["controlado"] is True
    assert data["vigencia"] is not None

    # Privacidad: no expone PII
    body = resp.content.decode("utf-8")
    assert patient.full_name not in body
    assert "FOLIO-VERIFY" not in body  # el folio especial NO se expone en verify


@pytest.mark.django_db
def test_verify_non_controlled_prescription_controlado_false() -> None:
    """GET verify de receta normal → controlado=False, vigencia=null."""
    from rest_framework.test import APIClient

    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)

    rx = PrescriptionFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        valid_until=None,
    )
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, controlled_group=ControlledGroup.NONE
    )

    token = verification_token(prescription=rx)
    resp = APIClient().get(_verify_url(rx.id), {"sig": token})

    assert resp.status_code == 200
    data = resp.json()
    assert data["controlado"] is False
    assert data["vigencia"] is None


# ---------------------------------------------------------------------------
# Unit tests de helpers internos de vigencia
# ---------------------------------------------------------------------------


def test_most_restrictive_group_I_wins_over_II() -> None:
    """Grupo I es más restrictivo que II."""
    result = _most_restrictive_group(
        {ControlledGroup.II, ControlledGroup.I, ControlledGroup.V}
    )
    assert result == ControlledGroup.I


def test_most_restrictive_group_empty_returns_none() -> None:
    """Sin grupos → None."""
    assert _most_restrictive_group(set()) is None


def test_calculate_valid_until_group_I() -> None:
    """Grupo I → +24h."""
    now = timezone.now()
    result = _calculate_valid_until(issued_at=now, groups={ControlledGroup.I})
    assert result is not None
    delta = result - now
    assert abs(delta.total_seconds() - 24 * 3600) < 1


def test_calculate_valid_until_group_II() -> None:
    """Grupo II → +720h (30 días)."""
    now = timezone.now()
    result = _calculate_valid_until(issued_at=now, groups={ControlledGroup.II})
    assert result is not None
    delta = result - now
    assert abs(delta.total_seconds() - 720 * 3600) < 1


def test_calculate_valid_until_empty_groups_returns_none() -> None:
    """Sin grupos controlados → None."""
    now = timezone.now()
    assert _calculate_valid_until(issued_at=now, groups=set()) is None
