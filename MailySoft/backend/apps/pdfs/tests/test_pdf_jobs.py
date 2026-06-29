"""
Tests de la infraestructura genérica de PDFs asíncronos (apps.pdfs).

Cubre:
  Servicio pdf_job_enqueue:
    - Con cache_key: crea PENDING, reusa DONE (caché), re-encola FAILED/PENDING.
    - Sin cache_key: cada pedido crea un job nuevo (salida mutable).
    - Encola la tarea con transaction.on_commit.
  Tarea generate_pdf (despacha por kind):
    - Genera el PDF (builder registrado), lo guarda y marca DONE.
    - Si el builder falla → FAILED con el error.
    - Idempotente si ya está DONE; not_found si el job no existe.
  Selector pdf_job_get: aislamiento multi-tenant (job de otro tenant → 404).
  Endpoints compartidos (status / file): polling, descarga, 409 si no está listo,
    y 404 si el permiso del kind no concede acceso (defensa en profundidad).
"""

from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.test import APIClient

from apps.core.tenant_context import set_current_tenant, set_tenant_context_active
from apps.pdfs.models import PdfJob
from apps.pdfs.registry import register_pdf_kind
from apps.pdfs.selectors import pdf_job_get
from apps.pdfs.services import pdf_job_enqueue
from apps.pdfs.tasks import generate_pdf
from tests.factories import TenantFactory, UserFactory

# ── Kinds de prueba registrados a nivel módulo (namespace pdfs_test_*) ──────────


def _ok_builder(*, params: Any, tenant: Any) -> tuple[bytes, str]:
    return b"%PDF-ok-bytes", f"prueba-{params.get('n', 'x')}.pdf"


def _fail_builder(*, params: Any, tenant: Any) -> tuple[bytes, str]:
    raise RuntimeError("weasy boom")


class _DenyPermission(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


register_pdf_kind("pdfs_test_ok", builder=_ok_builder, permission=AllowAny)
register_pdf_kind("pdfs_test_fail", builder=_fail_builder, permission=AllowAny)
register_pdf_kind("pdfs_test_denied", builder=_ok_builder, permission=_DenyPermission)


@contextmanager
def tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    set_current_tenant(tenant)
    set_tenant_context_active(True)
    try:
        yield
    finally:
        set_current_tenant(None)
        set_tenant_context_active(False)


@contextmanager
def api_tenant_ctx(tenant: Any) -> Generator[None, None, None]:
    """Simula el TenantMiddleware: el TenantManager filtra por este tenant."""
    with (
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


# ── Servicio ───────────────────────────────────────────────────────────────────


class TestPdfJobEnqueueConCache:
    def test_crea_job_pending(self, db: Any) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            job = pdf_job_enqueue(
                tenant=tenant, kind="pdfs_test_ok", params={"n": 1}, cache_key="k1"
            )
        assert job.status == PdfJob.Status.PENDING
        assert job.kind == "pdfs_test_ok"
        assert PdfJob.all_objects.filter(id=job.id).count() == 1

    def test_reusa_done_como_cache(self, db: Any) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            j1 = pdf_job_enqueue(
                tenant=tenant, kind="pdfs_test_ok", params={}, cache_key="k"
            )
            j1.status = PdfJob.Status.DONE
            j1.save(update_fields=["status"])
            j2 = pdf_job_enqueue(
                tenant=tenant, kind="pdfs_test_ok", params={}, cache_key="k"
            )
            total = PdfJob.objects.filter(kind="pdfs_test_ok").count()
        assert j2.id == j1.id
        assert j2.status == PdfJob.Status.DONE
        assert total == 1

    def test_reencola_failed(self, db: Any) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            j1 = pdf_job_enqueue(
                tenant=tenant, kind="pdfs_test_ok", params={}, cache_key="k"
            )
            j1.status = PdfJob.Status.FAILED
            j1.error = "boom"
            j1.save(update_fields=["status", "error"])
            j2 = pdf_job_enqueue(
                tenant=tenant, kind="pdfs_test_ok", params={}, cache_key="k"
            )
        assert j2.id == j1.id
        assert j2.status == PdfJob.Status.PENDING
        assert j2.error == ""

    def test_reencola_pending_atascado(
        self, db: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            j1 = pdf_job_enqueue(
                tenant=tenant, kind="pdfs_test_ok", params={}, cache_key="k"
            )
        with patch("apps.pdfs.tasks.generate_pdf.delay") as mock_delay:
            with django_capture_on_commit_callbacks(execute=True):
                with tenant_ctx(tenant):
                    j2 = pdf_job_enqueue(
                        tenant=tenant, kind="pdfs_test_ok", params={}, cache_key="k"
                    )
            total = PdfJob.objects.filter(kind="pdfs_test_ok").count()
        assert j2.id == j1.id
        assert total == 1
        mock_delay.assert_called_once_with(str(j1.id))


class TestPdfJobEnqueueSinCache:
    def test_sin_cache_siempre_crea_nuevo(self, db: Any) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            j1 = pdf_job_enqueue(tenant=tenant, kind="pdfs_test_ok", params={"n": 1})
            j2 = pdf_job_enqueue(tenant=tenant, kind="pdfs_test_ok", params={"n": 2})
            total = PdfJob.objects.filter(kind="pdfs_test_ok").count()
        assert j1.id != j2.id
        assert total == 2

    def test_on_commit_encola_tarea(
        self, db: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        tenant = TenantFactory()
        with patch("apps.pdfs.tasks.generate_pdf.delay") as mock_delay:
            with django_capture_on_commit_callbacks(execute=True):
                with tenant_ctx(tenant):
                    job = pdf_job_enqueue(
                        tenant=tenant, kind="pdfs_test_ok", params={}
                    )
        mock_delay.assert_called_once_with(str(job.id))


# ── Tarea ────────────────────────────────────────────────────────────────────


class TestGeneratePdfTask:
    def test_genera_y_marca_done(self, db: Any) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            job = pdf_job_enqueue(
                tenant=tenant, kind="pdfs_test_ok", params={"n": 7}
            )
        result = generate_pdf(str(job.id))
        assert result == "done"
        job.refresh_from_db()
        assert job.status == PdfJob.Status.DONE
        assert bool(job.file)
        assert job.filename == "prueba-7.pdf"

    def test_falla_marca_failed(self, db: Any) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            job = pdf_job_enqueue(tenant=tenant, kind="pdfs_test_fail", params={})
        result = generate_pdf(str(job.id))
        assert result == "failed"
        job.refresh_from_db()
        assert job.status == PdfJob.Status.FAILED
        assert "weasy boom" in job.error

    def test_idempotente_si_done(self, db: Any) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            job = pdf_job_enqueue(tenant=tenant, kind="pdfs_test_ok", params={})
            job.status = PdfJob.Status.DONE
            job.save(update_fields=["status"])
        with patch("apps.pdfs.registry.get_pdf_kind") as mock_get:
            result = generate_pdf(str(job.id))
        assert result == "skipped:done"
        mock_get.assert_not_called()

    def test_not_found(self, db: Any) -> None:
        import uuid

        assert generate_pdf(str(uuid.uuid4())) == "not_found"


# ── Selector ─────────────────────────────────────────────────────────────────


class TestSelectorIsolation:
    def test_get_de_otro_tenant_da_does_not_exist(self, db: Any) -> None:
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        with tenant_ctx(tenant_a):
            job_a = pdf_job_enqueue(tenant=tenant_a, kind="pdfs_test_ok", params={})
        with tenant_ctx(tenant_b):
            import pytest

            with pytest.raises(PdfJob.DoesNotExist):
                pdf_job_get(job_id=job_a.id)


# ── Endpoints compartidos ────────────────────────────────────────────────────


class TestSharedEndpoints:
    def _job_done(self, tenant: Any, kind: str = "pdfs_test_ok") -> PdfJob:
        with tenant_ctx(tenant):
            job = pdf_job_enqueue(tenant=tenant, kind=kind, params={})
        generate_pdf(str(job.id))
        job.refresh_from_db()
        return job

    def test_status_done(self, db: Any) -> None:
        tenant = TenantFactory()
        job = self._job_done(tenant)
        client = APIClient()
        client.force_authenticate(user=UserFactory())
        with api_tenant_ctx(tenant):
            resp = client.get(f"/api/v1/pdfs/job/{job.id}/")
        assert resp.status_code == 200, resp.content
        assert resp.json()["status"] == "done"

    def test_file_done(self, db: Any) -> None:
        tenant = TenantFactory()
        job = self._job_done(tenant)
        client = APIClient()
        client.force_authenticate(user=UserFactory())
        with api_tenant_ctx(tenant):
            resp = client.get(
                f"/api/v1/pdfs/job/{job.id}/file/", HTTP_ACCEPT="application/pdf"
            )
        assert resp.status_code == 200, resp.content
        assert resp["Content-Type"] == "application/pdf"
        assert resp["X-Frame-Options"] == "DENY"

    def test_file_not_ready_409(self, db: Any) -> None:
        tenant = TenantFactory()
        with tenant_ctx(tenant):
            job = pdf_job_enqueue(tenant=tenant, kind="pdfs_test_ok", params={})
        client = APIClient()
        client.force_authenticate(user=UserFactory())
        with api_tenant_ctx(tenant):
            resp = client.get(
                f"/api/v1/pdfs/job/{job.id}/file/", HTTP_ACCEPT="application/pdf"
            )
        assert resp.status_code == 409

    def test_permiso_del_kind_denegado_da_404(self, db: Any) -> None:
        tenant = TenantFactory()
        job = self._job_done(tenant, kind="pdfs_test_denied")
        client = APIClient()
        client.force_authenticate(user=UserFactory())
        with api_tenant_ctx(tenant):
            resp = client.get(f"/api/v1/pdfs/job/{job.id}/")
        assert resp.status_code == 404
