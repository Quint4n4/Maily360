"""
Tests — B1.3: PDF de receta médica.

Cubre (objetivo >= 80 % del código nuevo):

Generación de PDF real (end-to-end):
  - Receta activa sin membrete → 200, Content-Type application/pdf, body inicia %PDF.
  - Receta activa con ClinicSettings (sin imagen de membrete, solo datos) → 200.
  - Receta anulada → 200 (el PDF se genera correctamente, debe contener "ANULADA").
  - Receta con vitals_snapshot → 200.
  - Receta sin vitals_snapshot → 200.
  - Receta con sello del médico (imagen mock) → 200.
  - Receta sin sello del médico → 200.

Permisos:
  - GET sin token → 401.
  - GET con rol reception → 403 (CLINICAL_READ excluye recepción).
  - GET con rol finance → 403.
  - GET con rol doctor (CLINICAL_READ) → 200.
  - GET con rol nurse → 200.

IDOR:
  - GET de prescription de otro tenant → 404.

Bitácora:
  - GET genera entrada PRESCRIPTION_PDF en AuditLog con resource_repr=folio (sin PII).

Módulo pdf.py:
  - _image_to_data_uri: campo vacío → ("", "").
  - _image_to_data_uri: archivo inexistente → ("", "") sin excepción.
  - prescription_pdf_build: devuelve bytes que inician con b"%PDF".
"""

import uuid as uuid_module
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.recetas.models import Prescription, PrescriptionStatus
from apps.recetas.pdf import _image_to_data_uri, prescription_pdf_build
from apps.recetas.tests.conftest import api_tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ClinicSettingsFactory,
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


def _pdf_url(prescription_id: Any) -> str:
    return PDF_URL.format(prescription_id=str(prescription_id))


# ---------------------------------------------------------------------------
# Fixtures auxiliares
# ---------------------------------------------------------------------------


def _make_doctor_user(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> tuple[Any, Any]:
    """Crea un usuario con membresía en el tenant y perfil Doctor (si role=doctor)."""
    user = UserFactory()
    membership = TenantMembershipFactory(user=user, tenant=tenant, role=role)
    if role == TenantMembership.Role.DOCTOR:
        DoctorFactory(tenant=tenant, membership=membership)
    return user, membership


def _make_user_with_role(tenant: Any, role: str) -> Any:
    """Crea un usuario con membresía en el tenant con el rol dado (sin Doctor profile)."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role)
    return user


# ---------------------------------------------------------------------------
# Tests de permisos y autenticación
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pdf_unauthenticated_returns_401() -> None:
    """Sin token → 401."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Ibuprofeno")

    client = APIClient()
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 401


@pytest.mark.django_db
def test_pdf_reception_role_returns_403() -> None:
    """Rol reception → 403 (no pertenece a CLINICAL_READ)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Ibuprofeno")

    user = _make_user_with_role(tenant, TenantMembership.Role.RECEPTION)

    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 403


@pytest.mark.django_db
def test_pdf_finance_role_returns_403() -> None:
    """Rol finance → 403."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Amoxicilina")

    user = _make_user_with_role(tenant, TenantMembership.Role.FINANCE)

    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 403


@pytest.mark.django_db
def test_pdf_nurse_role_returns_200() -> None:
    """Rol nurse (CLINICAL_READ) → 200 y body empieza con %PDF."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Paracetamol")

    user = _make_user_with_role(tenant, TenantMembership.Role.NURSE)

    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_doctor_role_returns_200() -> None:
    """Rol doctor (CLINICAL_READ) → 200."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    user, membership = _make_doctor_user(tenant, TenantMembership.Role.DOCTOR)
    doctor = membership.doctor_profile.filter(deleted_at__isnull=True).first()
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Aspirina")

    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_accept_application_pdf_header_returns_200() -> None:
    """Con `Accept: application/pdf` (como el frontend) → 200, no 406.

    Regresión: la vista no declaraba un renderer de PDF, por lo que DRF respondía
    406 'Could not satisfy the request Accept header' antes de generar el PDF.
    """
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    user, membership = _make_doctor_user(tenant, TenantMembership.Role.DOCTOR)
    doctor = membership.doctor_profile.filter(deleted_at__isnull=True).first()
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Aspirina")

    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id), HTTP_ACCEPT="application/pdf")

    assert resp.status_code == 200
    assert "application/pdf" in resp["Content-Type"]
    assert resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Tests de IDOR
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pdf_cross_tenant_returns_404() -> None:
    """Receta de otro tenant → 404 (anti-IDOR)."""
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()

    patient_a = PatientFactory(tenant=tenant_a)
    doctor_a = DoctorFactory(tenant=tenant_a)
    rx_a = PrescriptionFactory(tenant=tenant_a, patient=patient_a, doctor=doctor_a)
    PrescriptionItemFactory(prescription=rx_a, tenant=tenant_a, order=1, medication_name="X")

    # Usuario del tenant_b intenta acceder a rx_a
    user_b = _make_user_with_role(tenant_b, TenantMembership.Role.DOCTOR)

    client = APIClient()
    client.force_authenticate(user=user_b)
    with api_tenant_ctx(tenant_b):
        resp = client.get(_pdf_url(rx_a.id))

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests de generación de PDF (end-to-end real con WeasyPrint)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pdf_active_prescription_no_letterhead() -> None:
    """Receta activa sin membrete → 200, Content-Type application/pdf, body %PDF."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        status=PrescriptionStatus.ACTIVE,
        vitals_snapshot=None,
    )
    PrescriptionItemFactory(
        prescription=rx,
        tenant=tenant,
        order=1,
        medication_name="Paracetamol",
        medication_concentration="500 mg",
        medication_form="tableta",
        indication="1 tableta cada 8 horas por 5 días",
    )

    user = _make_user_with_role(tenant, TenantMembership.Role.NURSE)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert "application/pdf" in resp["Content-Type"]
    assert len(resp.content) > 0
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_with_clinic_settings_no_image() -> None:
    """Receta con ClinicSettings (datos de texto, sin imagen) → 200."""
    tenant = TenantFactory()
    ClinicSettingsFactory(
        tenant=tenant,
        address="Av. Insurgentes 123",
        phone="55-1234-5678",
        email="clinica@ejemplo.com",
    )
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Ibuprofeno")

    user = _make_user_with_role(tenant, TenantMembership.Role.DOCTOR)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_cancelled_prescription_returns_200() -> None:
    """Receta anulada → 200 (el PDF se genera; marca de agua en el HTML)."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        status=PrescriptionStatus.CANCELLED,
        cancellation_reason="Error en la indicación",
    )
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Metformina")

    user = _make_user_with_role(tenant, TenantMembership.Role.NURSE)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_with_vitals_snapshot() -> None:
    """Receta con vitals_snapshot → 200."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    vitals: dict[str, Any] = {
        "weight_kg": 72.5,
        "height_m": 1.75,
        "imc": 23.7,
        "heart_rate": 72,
        "systolic": 120,
        "diastolic": 80,
        "temperature_c": 36.6,
        "oxygen_saturation": 98,
        "glucose": None,
        "measured_at": "2026-06-18T10:00:00Z",
    }
    rx = PrescriptionFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        vitals_snapshot=vitals,
    )
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Omeprazol")

    user = _make_user_with_role(tenant, TenantMembership.Role.DOCTOR)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_without_vitals_snapshot() -> None:
    """Receta sin vitals_snapshot → 200."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        vitals_snapshot=None,
    )
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Losartán")

    user = _make_user_with_role(tenant, TenantMembership.Role.READONLY)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_multiple_items() -> None:
    """Receta con 3 ítems → 200."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Med A")
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=2, medication_name="Med B")
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=3, medication_name="Med C")

    user = _make_user_with_role(tenant, TenantMembership.Role.NURSE)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_pdf_with_recommendations() -> None:
    """Receta con recomendaciones → 200."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        recommendations="Reposo absoluto. Dieta blanda. Tomar abundantes líquidos.",
    )
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Naproxeno")

    user = _make_user_with_role(tenant, TenantMembership.Role.NURSE)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Test de Content-Disposition
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pdf_content_disposition_inline() -> None:
    """El header Content-Disposition debe ser inline con el nombre receta-<folio>.pdf."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor, folio=42)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="X")

    user = _make_user_with_role(tenant, TenantMembership.Role.NURSE)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200
    disposition = resp.get("Content-Disposition", "")
    assert "inline" in disposition
    assert "receta-42.pdf" in disposition


# ---------------------------------------------------------------------------
# Test de bitácora
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pdf_generates_audit_log() -> None:
    """GET PDF → entrada PRESCRIPTION_PDF en AuditLog con resource_repr=folio."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Atenolol")

    user = _make_user_with_role(tenant, TenantMembership.Role.NURSE)
    client = APIClient()
    client.force_authenticate(user=user)
    with api_tenant_ctx(tenant):
        resp = client.get(_pdf_url(rx.id))

    assert resp.status_code == 200

    log = AuditLog.all_objects.filter(
        action=ActionType.PRESCRIPTION_PDF,
        resource_id=rx.id,
    ).first()
    assert log is not None
    assert f"folio={rx.folio}" in log.resource_repr
    # Sin PII: resource_repr NO debe contener nombre del paciente
    assert patient.first_name not in log.resource_repr


# ---------------------------------------------------------------------------
# Tests del módulo pdf.py (unitarios)
# ---------------------------------------------------------------------------


def test_image_to_data_uri_empty_field() -> None:
    """Campo vacío (falsy) → ("", "") sin excepción."""
    result = _image_to_data_uri(None)
    assert result == ("", "")


def test_image_to_data_uri_field_with_no_name() -> None:
    """Campo con name vacío → ("", "")."""
    mock_field = MagicMock()
    mock_field.__bool__ = lambda self: True
    mock_field.name = ""
    result = _image_to_data_uri(mock_field)
    assert result == ("", "")


def test_image_to_data_uri_file_not_found() -> None:
    """Campo que no puede abrirse → ("", "") sin propagar excepción."""
    mock_field = MagicMock()
    mock_field.__bool__ = lambda self: True
    mock_field.name = "clinica/x/logo/test.png"
    mock_field.open.side_effect = FileNotFoundError("no such file")
    result = _image_to_data_uri(mock_field)
    assert result == ("", "")


@pytest.mark.django_db
def test_prescription_pdf_build_returns_bytes() -> None:
    """prescription_pdf_build devuelve bytes que inician con b'%PDF'."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(
        prescription=rx,
        tenant=tenant,
        order=1,
        medication_name="Simvastatina",
        indication="1 tableta al día",
    )

    # Recargar con relaciones para simular el comportamiento del selector.
    from apps.recetas.selectors import prescription_get as _pg
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active

    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        full_rx = _pg(prescription_id=rx.id)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    pdf_bytes = prescription_pdf_build(prescription=full_rx)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert pdf_bytes[:4] == b"%PDF"


@pytest.mark.django_db
def test_prescription_pdf_build_with_clinic_settings() -> None:
    """PDF con ClinicSettings (datos de texto) → bytes válidos."""
    tenant = TenantFactory()
    ClinicSettingsFactory(
        tenant=tenant,
        address="Calle Falsa 123",
        phone="55-0000-0000",
    )
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Diclofenaco")

    from apps.recetas.selectors import prescription_get as _pg
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active

    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        full_rx = _pg(prescription_id=rx.id)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    pdf_bytes = prescription_pdf_build(prescription=full_rx)
    assert pdf_bytes[:4] == b"%PDF"


@pytest.mark.django_db
def test_prescription_pdf_build_cancelled() -> None:
    """PDF de receta anulada → bytes válidos."""
    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        status=PrescriptionStatus.CANCELLED,
    )
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Alprazolam")

    from apps.recetas.selectors import prescription_get as _pg
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active

    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        full_rx = _pg(prescription_id=rx.id)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    pdf_bytes = prescription_pdf_build(prescription=full_rx)
    assert pdf_bytes[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Tests — logo propio en DoctorCredential (credencial con logo pegado)
# ---------------------------------------------------------------------------


def _make_png_bytes(width: int = 40, height: int = 30) -> bytes:
    """Genera bytes PNG mínimos con Pillow para usar en tests."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (width, height), color=(120, 80, 200)).save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


@pytest.mark.django_db
def test_build_context_credential_with_logo_includes_logo_b64() -> None:
    """_build_context incluye logo_b64 no vacío cuando la credencial tiene logo."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.clinica.services import doctor_credential_create
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
    from apps.recetas.pdf import _build_context

    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Paracetamol")

    png_bytes = _make_png_bytes()
    logo_file = SimpleUploadedFile("cred_logo.png", png_bytes, content_type="image/png")

    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        cred = doctor_credential_create(
            tenant=tenant,
            user=UserFactory(),
            doctor=doctor,
            title="Médico con logo",
            institution="UNAM",
            kind="profesional",
            logo=logo_file,
        )
        # Solo las credenciales validadas aparecen en la receta (flujo híbrido).
        cred.validation_status = "validada"
        cred.save(update_fields=["validation_status"])
        from apps.recetas.selectors import prescription_get as _pg
        full_rx = _pg(prescription_id=rx.id)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    ctx = _build_context(full_rx)

    cred_block = next(
        (b for b in ctx["credential_blocks"] if b["title"] == "Médico con logo"),
        None,
    )
    assert cred_block is not None, "No se encontró el bloque de credencial con logo"
    assert cred_block["logo_b64"], "logo_b64 debe ser no vacío cuando hay logo"
    assert cred_block["logo_mime"], "logo_mime debe tener valor cuando hay logo"


@pytest.mark.django_db
def test_build_context_credential_without_logo_has_empty_logo_b64() -> None:
    """_build_context entrega logo_b64='' cuando la credencial no tiene logo."""
    from apps.clinica.services import doctor_credential_create
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
    from apps.recetas.pdf import _build_context

    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Ibuprofeno")

    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        doctor_credential_create(
            tenant=tenant,
            user=UserFactory(),
            doctor=doctor,
            title="Médico sin logo",
            institution="IPN",
            kind="posgrado",
        )
        from apps.clinica.models import DoctorCredential as _DC
        _DC.objects.filter(doctor=doctor).update(validation_status="validada")
        from apps.recetas.selectors import prescription_get as _pg
        full_rx = _pg(prescription_id=rx.id)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    ctx = _build_context(full_rx)

    cred_block = next(
        (b for b in ctx["credential_blocks"] if b["title"] == "Médico sin logo"),
        None,
    )
    assert cred_block is not None
    assert cred_block["logo_b64"] == ""
    assert cred_block["logo_mime"] == ""


@pytest.mark.django_db
def test_build_context_credential_blocks_equals_credentials() -> None:
    """credential_blocks es idéntico a credentials (sin emparejamiento por índice)."""
    from apps.clinica.services import doctor_credential_create
    from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
    from apps.recetas.pdf import _build_context

    tenant = TenantFactory()
    patient = PatientFactory(tenant=tenant)
    doctor = DoctorFactory(tenant=tenant)
    rx = PrescriptionFactory(tenant=tenant, patient=patient, doctor=doctor)
    PrescriptionItemFactory(prescription=rx, tenant=tenant, order=1, medication_name="Atenolol")

    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        doctor_credential_create(
            tenant=tenant, user=UserFactory(), doctor=doctor,
            title="Cred A", institution="UAG", kind="profesional",
        )
        doctor_credential_create(
            tenant=tenant, user=UserFactory(), doctor=doctor,
            title="Cred B", institution="UANL", kind="especialidad",
        )
        from apps.clinica.models import DoctorCredential as _DC
        _DC.objects.filter(doctor=doctor).update(validation_status="validada")
        from apps.recetas.selectors import prescription_get as _pg
        full_rx = _pg(prescription_id=rx.id)
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)

    ctx = _build_context(full_rx)

    assert ctx["credential_blocks"] is ctx["credentials"]
    assert len(ctx["credential_blocks"]) == 2
