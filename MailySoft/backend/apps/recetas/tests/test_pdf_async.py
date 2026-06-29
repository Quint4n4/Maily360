"""
Tests del PDF asíncrono de recetas (P0 — PDF en Celery).

Cubre:
  Servicio prescription_pdf_job_enqueue:
    - Crea un job PENDING para una receta.
    - Reusa el job DONE existente (caché — receta inmutable).
    - Re-encola (resetea a PENDING) un job FAILED.
    - Encola la tarea Celery con transaction.on_commit.
  Tarea generate_prescription_pdf (WeasyPrint mockeado):
    - Genera el PDF, lo guarda y marca DONE.
    - Si la generación falla → marca FAILED con el error.
    - Idempotente: si el job ya está DONE, no regenera.
  Selector prescription_pdf_job_get:
    - Aislamiento multi-tenant: job de otro tenant → DoesNotExist (404).
"""

from typing import Any
from unittest.mock import patch

import pytest

from apps.recetas.models import PrescriptionPdfJob
from apps.recetas.selectors import prescription_pdf_job_get
from apps.recetas.services import prescription_create, prescription_pdf_job_enqueue
from apps.recetas.tasks import generate_prescription_pdf
from apps.recetas.tests.conftest import tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
)

_ITEM = {
    "kind": "medicamento",
    "medication_name": "Paracetamol",
    "dose": "1 tableta",
    "frequency": "cada 8 horas",
    "route": "oral",
    "duration": "5 días",
    "indication": "Tomar con alimentos",
}


def _member_with_doctor(tenant: Any) -> tuple[Any, Any]:
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
    )
    doctor = DoctorFactory(tenant=tenant, membership=membership, is_active=True)
    return membership.user, doctor


def _make_prescription(tenant: Any) -> tuple[Any, Any]:
    """Crea (user, prescription) en el tenant dado."""
    user, _doctor = _member_with_doctor(tenant)
    patient = PatientFactory(tenant=tenant)
    with tenant_ctx(tenant):
        rx = prescription_create(
            tenant=tenant, user=user, patient_id=patient.id, items_data=[dict(_ITEM)]
        )
    return user, rx


class TestPrescriptionPdfJobEnqueue:
    def test_crea_job_pending(self, db: Any) -> None:
        tenant = TenantFactory()
        user, rx = _make_prescription(tenant)
        with tenant_ctx(tenant):
            job = prescription_pdf_job_enqueue(prescription=rx, user=user)
        assert job.status == PrescriptionPdfJob.Status.PENDING
        assert job.prescription_id == rx.id
        assert PrescriptionPdfJob.all_objects.filter(id=job.id).count() == 1

    def test_reusa_job_done_como_cache(self, db: Any) -> None:
        tenant = TenantFactory()
        user, rx = _make_prescription(tenant)
        with tenant_ctx(tenant):
            job1 = prescription_pdf_job_enqueue(prescription=rx, user=user)
            job1.status = PrescriptionPdfJob.Status.DONE
            job1.save(update_fields=["status"])
            job2 = prescription_pdf_job_enqueue(prescription=rx, user=user)
            total = PrescriptionPdfJob.objects.filter(prescription=rx).count()
        assert job2.id == job1.id
        assert job2.status == PrescriptionPdfJob.Status.DONE
        assert total == 1  # no se creó un segundo job

    def test_reencola_job_failed(self, db: Any) -> None:
        tenant = TenantFactory()
        user, rx = _make_prescription(tenant)
        with tenant_ctx(tenant):
            job1 = prescription_pdf_job_enqueue(prescription=rx, user=user)
            job1.status = PrescriptionPdfJob.Status.FAILED
            job1.error = "boom"
            job1.save(update_fields=["status", "error"])
            job2 = prescription_pdf_job_enqueue(prescription=rx, user=user)
        assert job2.id == job1.id
        assert job2.status == PrescriptionPdfJob.Status.PENDING
        assert job2.error == ""

    def test_encola_tarea_celery_on_commit(
        self, db: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        tenant = TenantFactory()
        user, rx = _make_prescription(tenant)
        with patch(
            "apps.recetas.tasks.generate_prescription_pdf.delay"
        ) as mock_delay:
            with django_capture_on_commit_callbacks(execute=True):
                with tenant_ctx(tenant):
                    job = prescription_pdf_job_enqueue(prescription=rx, user=user)
        mock_delay.assert_called_once_with(str(job.id))


class TestGeneratePrescriptionPdfTask:
    def test_genera_y_marca_done(self, db: Any) -> None:
        tenant = TenantFactory()
        user, rx = _make_prescription(tenant)
        with tenant_ctx(tenant):
            job = prescription_pdf_job_enqueue(prescription=rx, user=user)
        with patch(
            "apps.recetas.pdf.prescription_pdf_build", return_value=b"%PDF-fake-bytes"
        ):
            result = generate_prescription_pdf(str(job.id))
        assert result == "done"
        job.refresh_from_db()
        assert job.status == PrescriptionPdfJob.Status.DONE
        assert bool(job.file)  # el PDF quedó guardado

    def test_falla_marca_failed(self, db: Any) -> None:
        tenant = TenantFactory()
        user, rx = _make_prescription(tenant)
        with tenant_ctx(tenant):
            job = prescription_pdf_job_enqueue(prescription=rx, user=user)
        with patch(
            "apps.recetas.pdf.prescription_pdf_build",
            side_effect=RuntimeError("weasy boom"),
        ):
            result = generate_prescription_pdf(str(job.id))
        assert result == "failed"
        job.refresh_from_db()
        assert job.status == PrescriptionPdfJob.Status.FAILED
        assert "weasy boom" in job.error

    def test_idempotente_si_ya_done(self, db: Any) -> None:
        tenant = TenantFactory()
        user, rx = _make_prescription(tenant)
        with tenant_ctx(tenant):
            job = prescription_pdf_job_enqueue(prescription=rx, user=user)
            job.status = PrescriptionPdfJob.Status.DONE
            job.save(update_fields=["status"])
        with patch("apps.recetas.pdf.prescription_pdf_build") as mock_build:
            result = generate_prescription_pdf(str(job.id))
        assert result == "skipped:done"
        mock_build.assert_not_called()


class TestPdfJobSelectorIsolation:
    def test_get_de_otro_tenant_da_does_not_exist(self, db: Any) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user_a, rx_a = _make_prescription(tenant_a)
        with tenant_ctx(tenant_a):
            job_a = prescription_pdf_job_enqueue(prescription=rx_a, user=user_a)
        # En el contexto del tenant B, el job de A no debe ser visible (404).
        with tenant_ctx(tenant_b):
            with pytest.raises(PrescriptionPdfJob.DoesNotExist):
                prescription_pdf_job_get(job_id=job_a.id)
