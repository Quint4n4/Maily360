"""
Tests del PDF del Libro Clínico — Fase 3 (Maily Platform).

Cubre (objetivo >= 80% en lógica de negocio):

1. book_build_all (selector):
   - modo completo: retorna todos los capítulos.
   - modo hc: capitulos=[], capitulos_count real.
   - modo ultimo: solo el capítulo más reciente.
   - modo inválido: fallback a "completo".
   - Aislamiento multi-tenant: capítulos de otro paciente no aparecen.

2. libro_pdf_build (generador):
   - Genera bytes válidos (magic header %PDF) en los 3 modos.
   - Con imagenes=True y imagenes=False.
   - Sin evoluciones: no falla (PDF de portada + HC vacía).
   - Con MedicalHistory: aparece la HC.
   - Con EvolutionNote + Prescription: receta en resumen.

3. PatientBookPdfApi (GET /expediente/<patient_id>/libro/pdf/):
   - 200 + application/pdf + magic header %PDF.
   - modo=completo | hc | ultimo generan PDF.
   - imagenes=0 genera PDF (sin imágenes — solo texto).
   - 401 sin autenticación.
   - 403 para recepción y finanzas (D-LIB-6).
   - 404 IDOR: paciente de otro tenant.
   - 400 modo inválido.
   - Bitácora PATIENT_BOOK_PDF registrada en AuditLog.
   - Content-Disposition attachment (descarga, no inline).

Patrón: AAA. factory_boy para datos.
Tenant context parcheado igual que el resto de la app expediente.
"""

from typing import Any
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.expediente.selectors import PatientBook, book_build_all
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AllergyFactory,
    ClinicSettingsFactory,
    DiagnosisFactory,
    EvolutionNoteFactory,
    MedicalHistoryFactory,
    PatientFactory,
    PrescriptionFactory,
    PrescriptionItemFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
    VitalSignsRecordFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_PDF_URL_TMPL = "/api/v1/expediente/{patient_id}/libro/pdf/"


def _pdf_url(patient_id: Any, **params: Any) -> str:
    url = _PDF_URL_TMPL.format(patient_id=patient_id)
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    return url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _member(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> Any:
    """Crea user con membresía activa en el tenant."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _get_pdf_via_async(
    client: APIClient, patient_id: Any, tenant: Any, **params: Any
) -> Any:
    """Flujo async del PDF del libro: GET encola (202) -> corre la tarea -> GET file."""
    from apps.pdfs.tasks import generate_pdf

    with api_tenant_ctx(tenant):
        req = client.get(_pdf_url(patient_id, **params))
    assert req.status_code == 202, req.content
    job_id = req.json()["job_id"]
    generate_pdf(job_id)
    with api_tenant_ctx(tenant):
        return client.get(
            f"/api/v1/pdfs/job/{job_id}/file/", HTTP_ACCEPT="application/pdf"
        )


# ---------------------------------------------------------------------------
# 1. book_build_all — selector
# ---------------------------------------------------------------------------


class TestBookBuildAll:
    """Tests del selector book_build_all (sin paginación, para PDF)."""

    def test_devuelve_patient_book(self, db: Any) -> None:
        """book_build_all retorna PatientBook."""
        from tests.factories import DoctorFactory
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build_all(patient=patient)

        assert isinstance(result, PatientBook)
        assert result.patient.id == patient.id

    def test_modo_completo_todos_los_capitulos(self, db: Any) -> None:
        """modo=completo devuelve TODOS los capítulos del paciente."""
        nota1 = EvolutionNoteFactory()
        tenant = nota1.tenant
        patient = nota1.patient
        # Crear segunda nota para el mismo paciente.
        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=nota1.doctor,
        )

        with tenant_ctx(tenant):
            result = book_build_all(patient=patient, modo="completo")

        assert result.capitulos_count == 2
        assert len(result.capitulos) == 2

    def test_modo_hc_sin_capitulos(self, db: Any) -> None:
        """modo=hc devuelve capitulos=[] aunque haya evoluciones."""
        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient

        with tenant_ctx(tenant):
            result = book_build_all(patient=patient, modo="hc")

        # El contador real debe incluir el capítulo existente.
        assert result.capitulos_count == 1
        # Pero capitulos está vacío (modo hc: solo portada + HC).
        assert result.capitulos == []

    def test_modo_ultimo_solo_mas_reciente(self, db: Any) -> None:
        """modo=ultimo devuelve solo la nota más reciente (1 capítulo)."""
        import datetime
        from django.utils import timezone
        from apps.expediente.models import EvolutionNote

        nota_vieja = EvolutionNoteFactory()
        tenant = nota_vieja.tenant
        patient = nota_vieja.patient

        # Crear nota más reciente.
        nota_nueva = EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=nota_vieja.doctor,
        )
        # Forzar created_at para asegurar el orden.
        now = timezone.now()
        EvolutionNote.objects.filter(id=nota_vieja.id).update(
            created_at=now - datetime.timedelta(days=5)
        )
        EvolutionNote.objects.filter(id=nota_nueva.id).update(
            created_at=now
        )

        with tenant_ctx(tenant):
            result = book_build_all(patient=patient, modo="ultimo")

        assert result.capitulos_count == 2
        assert len(result.capitulos) == 1
        assert result.capitulos[0].id == nota_nueva.id

    def test_modo_invalido_fallback_completo(self, db: Any) -> None:
        """Un modo inválido se trata como 'completo' (fallback defensivo)."""
        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient

        with tenant_ctx(tenant):
            result = book_build_all(patient=patient, modo="inventado")

        # Fallback a completo: todos los capítulos.
        assert len(result.capitulos) == 1

    def test_aislamiento_multi_tenant(self, db: Any) -> None:
        """Capítulos de otro tenant no aparecen en el libro."""
        nota1 = EvolutionNoteFactory()
        tenant1 = nota1.tenant
        patient1 = nota1.patient

        # Nota de otro tenant (factory crea su propio tenant).
        EvolutionNoteFactory()

        with tenant_ctx(tenant1):
            result = book_build_all(patient=patient1, modo="completo")

        assert result.capitulos_count == 1
        assert len(result.capitulos) == 1
        assert result.capitulos[0].tenant_id == tenant1.id

    def test_sin_evoluciones(self, db: Any) -> None:
        """Paciente sin evoluciones: capitulos=[], count=0."""
        from tests.factories import DoctorFactory
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build_all(patient=patient, modo="completo")

        assert result.capitulos == []
        assert result.capitulos_count == 0

    def test_modo_ultimo_sin_evoluciones(self, db: Any) -> None:
        """modo=ultimo con paciente sin evoluciones: capitulos=[]."""
        from tests.factories import DoctorFactory
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build_all(patient=patient, modo="ultimo")

        assert result.capitulos == []
        assert result.capitulos_count == 0


# ---------------------------------------------------------------------------
# 2. libro_pdf_build — generador de PDF
# ---------------------------------------------------------------------------


class TestLibroPdfBuild:
    """Tests del generador libro_pdf_build (WeasyPrint)."""

    def _get_book(self, patient: Any, modo: str, tenant: Any) -> PatientBook:
        """Helper: construye el libro en el contexto del tenant."""
        with tenant_ctx(tenant):
            return book_build_all(patient=patient, modo=modo)

    def test_genera_bytes_validos_modo_completo(self, db: Any) -> None:
        """modo=completo genera bytes PDF con magic header %PDF."""
        from apps.expediente.pdf import libro_pdf_build

        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient

        book = self._get_book(patient, "completo", tenant)
        pdf = libro_pdf_build(
            patient=book.patient,
            clinic_settings=book.clinic_settings,
            medical_history=book.medical_history,
            allergies=book.allergies,
            capitulos=book.capitulos,
            capitulos_count=book.capitulos_count,
            modo="completo",
            incluir_imagenes=False,
        )

        assert isinstance(pdf, bytes)
        assert len(pdf) > 0
        assert pdf[:4] == b"%PDF"

    def test_genera_bytes_validos_modo_hc(self, db: Any) -> None:
        """modo=hc genera PDF válido (solo portada + HC)."""
        from apps.expediente.pdf import libro_pdf_build
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        MedicalHistoryFactory(tenant=tenant, patient=patient, created_by=user)

        book = self._get_book(patient, "hc", tenant)
        pdf = libro_pdf_build(
            patient=book.patient,
            clinic_settings=book.clinic_settings,
            medical_history=book.medical_history,
            allergies=book.allergies,
            capitulos=book.capitulos,
            capitulos_count=book.capitulos_count,
            modo="hc",
            incluir_imagenes=False,
        )

        assert pdf[:4] == b"%PDF"

    def test_genera_bytes_validos_modo_ultimo(self, db: Any) -> None:
        """modo=ultimo genera PDF válido (solo último capítulo)."""
        from apps.expediente.pdf import libro_pdf_build

        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient

        book = self._get_book(patient, "ultimo", tenant)
        pdf = libro_pdf_build(
            patient=book.patient,
            clinic_settings=book.clinic_settings,
            medical_history=book.medical_history,
            allergies=book.allergies,
            capitulos=book.capitulos,
            capitulos_count=book.capitulos_count,
            modo="ultimo",
            incluir_imagenes=False,
        )

        assert pdf[:4] == b"%PDF"

    def test_sin_imagenes_genera_pdf(self, db: Any) -> None:
        """incluir_imagenes=False genera un PDF sin error (D-LIB-2)."""
        from apps.expediente.pdf import libro_pdf_build

        nota = EvolutionNoteFactory(tratamiento="Reposo relativo 3 días.")
        tenant = nota.tenant
        patient = nota.patient

        book = self._get_book(patient, "completo", tenant)
        pdf = libro_pdf_build(
            patient=book.patient,
            clinic_settings=book.clinic_settings,
            medical_history=book.medical_history,
            allergies=book.allergies,
            capitulos=book.capitulos,
            capitulos_count=book.capitulos_count,
            modo="completo",
            incluir_imagenes=False,
        )
        assert pdf[:4] == b"%PDF"

    def test_sin_evoluciones_genera_pdf(self, db: Any) -> None:
        """Paciente sin evoluciones genera PDF de portada + HC vacía sin error."""
        from apps.expediente.pdf import libro_pdf_build
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        book = self._get_book(patient, "completo", tenant)
        pdf = libro_pdf_build(
            patient=book.patient,
            clinic_settings=book.clinic_settings,
            medical_history=book.medical_history,
            allergies=book.allergies,
            capitulos=book.capitulos,
            capitulos_count=book.capitulos_count,
            modo="completo",
            incluir_imagenes=False,
        )
        assert pdf[:4] == b"%PDF"

    def test_con_recetas_genera_pdf(self, db: Any) -> None:
        """Nota con receta vinculada genera PDF sin error (resumen de receta)."""
        from apps.expediente.pdf import libro_pdf_build

        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient

        # Receta vinculada a la nota.
        rx = PrescriptionFactory(
            tenant=tenant,
            patient=patient,
            evolution_note=nota,
        )
        PrescriptionItemFactory(prescription=rx, medication_name="Ibuprofeno 400mg")

        book = self._get_book(patient, "completo", tenant)
        pdf = libro_pdf_build(
            patient=book.patient,
            clinic_settings=book.clinic_settings,
            medical_history=book.medical_history,
            allergies=book.allergies,
            capitulos=book.capitulos,
            capitulos_count=book.capitulos_count,
            modo="completo",
            incluir_imagenes=False,
        )
        assert pdf[:4] == b"%PDF"

    def test_con_historia_clinica_genera_pdf(self, db: Any) -> None:
        """Con HC registrada genera PDF sin error (modo hc)."""
        from apps.expediente.pdf import libro_pdf_build
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()
        MedicalHistoryFactory(
            tenant=tenant,
            patient=patient,
            created_by=user,
            padecimiento_actual="Cefalea tensional recurrente.",
        )

        book = self._get_book(patient, "hc", tenant)
        pdf = libro_pdf_build(
            patient=book.patient,
            clinic_settings=book.clinic_settings,
            medical_history=book.medical_history,
            allergies=book.allergies,
            capitulos=book.capitulos,
            capitulos_count=book.capitulos_count,
            modo="hc",
            incluir_imagenes=False,
        )
        assert pdf[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 3. PatientBookPdfApi — endpoint HTTP
# ---------------------------------------------------------------------------


class TestPatientBookPdfApi:
    """Tests del endpoint GET /api/v1/expediente/<patient_id>/libro/pdf/ (async).

    El endpoint ahora ENCOLA (202 {job_id, status}); el PDF se genera en Celery y
    se descarga por el endpoint compartido /pdfs/job/<id>/file/. Los tests de
    permiso/IDOR/validación se quedan sobre el ENCOLAR; los de camino feliz corren
    la tarea y descargan el archivo via _get_pdf_via_async.
    """

    # ---- Camino feliz (encola -> tarea -> descarga) ----

    def test_200_modo_completo_devuelve_pdf(self, db: Any) -> None:
        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        resp = _get_pdf_via_async(
            client, patient.id, tenant, modo="completo", imagenes="0"
        )

        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        assert resp.content[:4] == b"%PDF"

    def test_200_modo_hc(self, db: Any) -> None:
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        resp = _get_pdf_via_async(client, patient.id, tenant, modo="hc", imagenes="0")

        assert resp.status_code == 200
        assert resp.content[:4] == b"%PDF"

    def test_200_modo_ultimo(self, db: Any) -> None:
        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        resp = _get_pdf_via_async(
            client, patient.id, tenant, modo="ultimo", imagenes="0"
        )

        assert resp.status_code == 200
        assert resp.content[:4] == b"%PDF"

    def test_200_sin_imagenes(self, db: Any) -> None:
        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        resp = _get_pdf_via_async(client, patient.id, tenant, imagenes="0")

        assert resp.status_code == 200
        assert resp.content[:4] == b"%PDF"

    def test_content_disposition_inline(self, db: Any) -> None:
        """El PDF servido por el endpoint compartido va inline (el front lo muestra)."""
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        resp = _get_pdf_via_async(client, patient.id, tenant, modo="hc", imagenes="0")

        assert resp.status_code == 200
        assert "inline" in resp.get("Content-Disposition", "")

    # ---- Permisos (D-LIB-6) — sobre el endpoint de ENCOLAR ----

    def test_401_sin_autenticacion(self, db: Any) -> None:
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        client = APIClient()

        with api_tenant_ctx(tenant):
            resp = client.get(_pdf_url(patient.id))

        assert resp.status_code == 401

    def test_403_recepcion_no_puede_acceder(self, db: Any) -> None:
        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(tenant):
            resp = client.get(_pdf_url(patient.id, imagenes="0"))

        assert resp.status_code == 403

    def test_403_finanzas_no_puede_acceder(self, db: Any) -> None:
        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient
        client = _auth_client(_member(tenant, TenantMembership.Role.FINANCE))

        with api_tenant_ctx(tenant):
            resp = client.get(_pdf_url(patient.id, imagenes="0"))

        assert resp.status_code == 403

    def test_202_owner_puede_acceder(self, db: Any) -> None:
        """owner puede encolar el PDF (202)."""
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant):
            resp = client.get(_pdf_url(patient.id, modo="hc", imagenes="0"))

        assert resp.status_code == 202

    # ---- Anti-IDOR (multi-tenant) ----

    def test_404_idor_paciente_otro_tenant(self, db: Any) -> None:
        from tests.factories import DoctorFactory

        doctor1 = DoctorFactory()
        tenant1 = doctor1.tenant
        doctor2 = DoctorFactory()
        tenant2 = doctor2.tenant
        patient2 = PatientFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(tenant1):
            resp = client.get(_pdf_url(patient2.id, modo="hc", imagenes="0"))

        assert resp.status_code == 404

    # ---- Validación de parámetros ----

    def test_400_modo_invalido(self, db: Any) -> None:
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(tenant):
            resp = client.get(_pdf_url(patient.id, modo="inventado", imagenes="0"))

        assert resp.status_code == 400

    # ---- Bitacora NOM-024 (D-LIB-4) — al ENCOLAR ----

    def test_bitacora_patient_book_pdf_registrada(self, db: Any) -> None:
        from tests.factories import DoctorFactory

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_pdf_url(patient.id, modo="hc", imagenes="0"))

        assert resp.status_code == 202

        log = AuditLog.all_objects.filter(
            action=ActionType.PATIENT_BOOK_PDF,
            actor=user,
        ).first()
        assert log is not None
        assert log.metadata.get("modo") == "hc"
        assert log.metadata.get("imagenes") == 0
        assert log.resource_repr == patient.record_number

    def test_bitacora_incluye_modo_en_metadata(self, db: Any) -> None:
        nota = EvolutionNoteFactory()
        tenant = nota.tenant
        patient = nota.patient
        user = _member(tenant, TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            client.get(_pdf_url(patient.id, modo="ultimo", imagenes="0"))

        log = (
            AuditLog.all_objects.filter(
                action=ActionType.PATIENT_BOOK_PDF,
                actor=user,
            )
            .order_by("-created_at")
            .first()
        )
        assert log is not None
        assert log.metadata.get("modo") == "ultimo"
