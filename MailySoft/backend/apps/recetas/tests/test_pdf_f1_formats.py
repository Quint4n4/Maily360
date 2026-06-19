"""
Tests — F1: PDF multi-formato de receta médica.

Cubre:
  - Los tres formatos (standard, compact, digital) generan PDF válido (status 200,
    body empieza con %PDF) vía ?formato=.
  - Formato inválido cae en "standard" sin error (fallback silencioso).
  - Ítems con campos estructurados (dose, frequency, route, duration): PDF generado.
  - Sueros + terapias + diagnóstico: PDF generado con los tres formatos.
  - Receta activa y anulada con los tres formatos.
  - Sin sello + sin logo: PDF generado.
  - compact con 8+ ítems: generado sin error (prueba anti-encimado/página extra).
  - Accept: application/pdf con ?formato= → 200, no 406 (regresión).
  - prescription_pdf_build directo con los tres layouts.
  - _build_context incluye 'credentials', 'diagnosis', 'medicamentos', 'sueros', 'terapias'.
  - commercial_name prevalece sobre Tenant.name como clinic_name.
"""

from typing import Any
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.clinica.models import CredentialKind
from apps.recetas.models import ItemKind, Prescription, PrescriptionStatus
from apps.recetas.pdf import _build_context, prescription_pdf_build
from apps.recetas.tests.conftest import api_tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ClinicSettingsFactory,
    DoctorCredentialFactory,
    DoctorFactory,
    PatientFactory,
    PrescriptionFactory,
    PrescriptionItemFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URL helper
# ---------------------------------------------------------------------------

PDF_URL = "/api/v1/recetas/{prescription_id}/pdf/"


def _pdf_url(prescription_id: Any, formato: str = "standard") -> str:
    base = PDF_URL.format(prescription_id=str(prescription_id))
    return f"{base}?formato={formato}"


# ---------------------------------------------------------------------------
# Fixtures auxiliares
# ---------------------------------------------------------------------------


def _make_nurse(tenant: Any) -> Any:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantMembership.Role.NURSE)
    return user


def _make_doctor_user(tenant: Any) -> tuple[Any, Any]:
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR)
    doctor = DoctorFactory(tenant=tenant, membership=membership)
    return user, doctor


def _basic_rx(tenant: Any) -> Prescription:
    """Crea una receta con 1 ítem medicamento básico."""
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=1,
        medication_name="Paracetamol",
        medication_concentration="500 mg",
        medication_form="tableta",
        kind=ItemKind.MEDICAMENTO,
        dose="1 tableta",
        frequency="cada 8 horas",
        route="oral",
        duration="5 días",
    )
    return rx


def _get_full_rx(rx: Prescription, tenant: Any) -> Prescription:
    """Recarga la receta con relaciones precargadas para prescription_pdf_build."""
    from apps.recetas.selectors import prescription_get
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active

    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        return prescription_get(prescription_id=rx.id)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


# ---------------------------------------------------------------------------
# Tests de los tres formatos via API (?formato=)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("formato", ["standard", "compact", "digital"])
def test_pdf_all_formats_return_200_and_pdf_bytes(formato: str) -> None:
    """Los tres formatos generan PDF válido (200, %PDF)."""
    tenant = TenantFactory()
    rx = _basic_rx(tenant)
    user = _make_nurse(tenant)

    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id, formato=formato))

    assert resp.status_code == 200, f"formato={formato} → status {resp.status_code}"
    assert resp["Content-Type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF", f"formato={formato} no empieza con %PDF"


@pytest.mark.django_db
def test_pdf_invalid_formato_falls_back_to_standard() -> None:
    """Formato inválido en ?formato= → 200 con formato standard (fallback silencioso)."""
    tenant = TenantFactory()
    rx = _basic_rx(tenant)
    user = _make_nurse(tenant)

    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id, formato="inexistente"))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
@pytest.mark.parametrize("formato", ["standard", "compact", "digital"])
def test_pdf_accept_application_pdf_with_formato(formato: str) -> None:
    """Accept: application/pdf + ?formato= → 200, no 406 (regresión)."""
    tenant = TenantFactory()
    rx = _basic_rx(tenant)
    user = _make_nurse(tenant)

    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id, formato=formato), HTTP_ACCEPT="application/pdf")

    assert resp.status_code == 200
    assert "application/pdf" in resp["Content-Type"]
    assert resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Tests con campos estructurados F2
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("formato", ["standard", "compact", "digital"])
def test_pdf_with_structured_fields(formato: str) -> None:
    """Receta con dose/frequency/route/duration → PDF válido en todos los formatos."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant, patient=patient, doctor=doctor,
        diagnosis="Infección de vías respiratorias superiores",
    )
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=1,
        medication_name="Amoxicilina",
        medication_concentration="500 mg",
        medication_form="cápsula",
        medication_presentation="Caja con 21 cápsulas",
        kind=ItemKind.MEDICAMENTO,
        dose="500 miligramos",
        frequency="cada 8 horas",
        route="oral",
        duration="7 días",
        indication="Tomar con alimentos para evitar malestar estomacal",
    )

    user = _make_nurse(tenant)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id, formato=formato))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
@pytest.mark.parametrize("formato", ["standard", "compact", "digital"])
def test_pdf_with_sueros_terapias_diagnosis(formato: str) -> None:
    """Receta con medicamentos + sueros + terapias + diagnóstico → PDF válido."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant, patient=patient, doctor=doctor,
        diagnosis="Deshidratación leve",
    )
    # Medicamento
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=1,
        medication_name="Paracetamol",
        kind=ItemKind.MEDICAMENTO,
        dose="500 mg",
        frequency="cada 8 horas",
        route="oral",
        duration="3 días",
    )
    # Suero
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=2,
        medication_name="Solución Hartmann 1 L",
        medication_concentration="",
        medication_form="solucion_inyectable",
        kind=ItemKind.SUERO,
        dose="1 litro",
        frequency="una vez",
        route="intravenosa",
        duration="en 2 horas",
        indication="Pasar a 500 mL/h",
    )
    # Terapia
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=3,
        medication_name="Fisioterapia respiratoria",
        kind=ItemKind.TERAPIA,
        frequency="3 veces por semana",
        duration="2 semanas",
        indication="Ejercicios de expansión pulmonar",
    )

    user = _make_nurse(tenant)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id, formato=formato))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Tests receta anulada con los tres formatos
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("formato", ["standard", "compact", "digital"])
def test_pdf_cancelled_all_formats(formato: str) -> None:
    """Receta anulada genera PDF con marca de agua en los tres formatos."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant, patient=patient, doctor=doctor,
        status=PrescriptionStatus.CANCELLED,
        cancellation_reason="Error de indicación",
    )
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Ibuprofeno")

    user = _make_nurse(tenant)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id, formato=formato))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Test sin sello + sin logo
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("formato", ["standard", "compact", "digital"])
def test_pdf_no_logo_no_sello(formato: str) -> None:
    """Sin logo de clínica ni sello del médico → PDF generado igual."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    # Doctor sin sello (default de la factory)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Losartán")

    user = _make_nurse(tenant)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id, formato=formato))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Test compact con 8+ ítems (anti-encimado)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pdf_compact_many_items_no_error() -> None:
    """compact con 8+ ítems genera PDF sin error (no hay encimado)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant, patient=patient, doctor=doctor,
        diagnosis="Tratamiento integral complejo",
        vitals_snapshot={
            "weight_kg": 80, "height_m": 1.70, "imc": 27.7,
            "heart_rate": 80, "systolic": 130, "diastolic": 85,
            "temperature_c": 36.8, "oxygen_saturation": 97,
        },
    )
    # 5 medicamentos
    for i in range(1, 6):
        PrescriptionItemFactory(
            prescription=rx, tenant=tenant, order=i,
            medication_name=f"Medicamento {i}",
            kind=ItemKind.MEDICAMENTO,
            dose=f"{i * 10} miligramos",
            frequency="cada 12 horas",
            route="oral",
            duration="10 días",
        )
    # 2 sueros
    for i in range(1, 3):
        PrescriptionItemFactory(
            prescription=rx, tenant=tenant, order=5 + i,
            medication_name=f"Solución glucosada {i}",
            kind=ItemKind.SUERO,
            dose="500 mL",
            frequency="una vez al día",
            route="intravenosa",
            duration="3 días",
        )
    # 1 terapia
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=8,
        medication_name="Rehabilitación física",
        kind=ItemKind.TERAPIA,
        frequency="5 días a la semana",
        duration="1 mes",
    )

    user = _make_nurse(tenant)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id, formato="compact"))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Tests de prescription_pdf_build directo (unitarios F1)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("layout", ["standard", "compact", "digital"])
def test_prescription_pdf_build_all_layouts(layout: str) -> None:
    """prescription_pdf_build con los tres layouts retorna bytes %PDF."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=1,
        medication_name="Metformina", kind=ItemKind.MEDICAMENTO,
        dose="850 mg", frequency="con el almuerzo", route="oral", duration="indefinido",
    )

    full_rx = _get_full_rx(rx, tenant)
    pdf_bytes = prescription_pdf_build(prescription=full_rx, base_layout=layout)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert pdf_bytes[:4] == b"%PDF", f"layout={layout} no empieza con %PDF"


@pytest.mark.django_db
def test_prescription_pdf_build_invalid_layout_falls_back() -> None:
    """Layout inválido → fallback silencioso a 'standard'."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Omeprazol")

    full_rx = _get_full_rx(rx, tenant)
    # No debe lanzar excepción; usa standard silenciosamente.
    pdf_bytes = prescription_pdf_build(prescription=full_rx, base_layout="tipo_inexistente")

    assert pdf_bytes[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Tests de _build_context (campos F2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_context_includes_f2_fields() -> None:
    """_build_context expone credentials, diagnosis, medicamentos, sueros, terapias."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant, patient=patient, doctor=doctor,
        diagnosis="Hipertensión arterial leve",
    )
    # Medicamento
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=1,
        medication_name="Losartán",
        kind=ItemKind.MEDICAMENTO,
        dose="50 mg", frequency="cada 24 horas", route="oral", duration="continuo",
    )
    # Suero
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=2,
        medication_name="Solución fisiológica",
        kind=ItemKind.SUERO,
    )
    # Terapia
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=3,
        medication_name="Dieta DASH",
        kind=ItemKind.TERAPIA,
    )
    # Credencial estructurada
    DoctorCredentialFactory(
        tenant=tenant,
        doctor=doctor,
        title="Médico Cirujano",
        institution="UNAM",
        credential_number="12345678",
        kind=CredentialKind.PROFESIONAL,
        order=0,
    )

    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        from apps.recetas.selectors import prescription_get
        full_rx = prescription_get(prescription_id=rx.id)
        ctx = _build_context(full_rx)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    # Campos F2 presentes
    assert "credentials" in ctx
    assert "diagnosis" in ctx
    assert "medicamentos" in ctx
    assert "sueros" in ctx
    assert "terapias" in ctx

    # Valores correctos
    assert ctx["diagnosis"] == "Hipertensión arterial leve"
    assert len(ctx["medicamentos"]) == 1
    assert len(ctx["sueros"]) == 1
    assert len(ctx["terapias"]) == 1
    assert len(ctx["credentials"]) == 1
    assert ctx["credentials"][0]["credential_number"] == "12345678"

    # Campos estructurados del ítem medicamento
    med = ctx["medicamentos"][0]
    assert med["dose"] == "50 mg"
    assert med["frequency"] == "cada 24 horas"
    assert med["route"] == "oral"
    assert med["route_label"] == "Oral"
    assert med["duration"] == "continuo"


@pytest.mark.django_db
def test_build_context_commercial_name_takes_priority() -> None:
    """commercial_name de ClinicSettings prevalece como clinic_name."""
    tenant = TenantFactory()
    ClinicSettingsFactory(tenant=tenant, commercial_name="Clínica Camsa")
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="X")

    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        from apps.recetas.selectors import prescription_get
        full_rx = prescription_get(prescription_id=rx.id)
        ctx = _build_context(full_rx)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    assert ctx["commercial_name"] == "Clínica Camsa"
    assert ctx["clinic_name"] == "Clínica Camsa"


@pytest.mark.django_db
def test_build_context_tenant_name_fallback_when_no_commercial_name() -> None:
    """Sin commercial_name, clinic_name cae a Tenant.name."""
    tenant = TenantFactory()
    # ClinicSettings sin commercial_name
    ClinicSettingsFactory(tenant=tenant, commercial_name="")
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Y")

    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        from apps.recetas.selectors import prescription_get
        full_rx = prescription_get(prescription_id=rx.id)
        ctx = _build_context(full_rx)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    # Debe caer al nombre del tenant
    assert ctx["clinic_name"] == tenant.name


@pytest.mark.django_db
def test_build_context_route_label_mapping() -> None:
    """La vía de administración se convierte a etiqueta legible (route_label)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(
        prescription=rx, tenant=tenant, order=1,
        medication_name="Insulina",
        kind=ItemKind.MEDICAMENTO,
        route="subcutanea",
    )

    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        from apps.recetas.selectors import prescription_get
        full_rx = prescription_get(prescription_id=rx.id)
        ctx = _build_context(full_rx)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    med = ctx["medicamentos"][0]
    assert med["route"] == "subcutanea"
    assert med["route_label"] == "Subcutánea"
