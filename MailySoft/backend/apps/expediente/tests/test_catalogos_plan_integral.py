"""
Tests de los catálogos que alimentan el Plan Integral de Longevidad.

DocumentTemplate (Fase 2) — plantillas de texto reutilizables.
LabAnalyte (Fase 3)       — analitos de laboratorio con rango de referencia.

Cubre:
1. Services: create/update/activate/deactivate/delete (soft-delete vía
   deleted_at), validaciones (section inválida, ref_low > ref_high,
   campos inmutables en update).
2. Selectors: filtros only_active/section, aislamiento multi-tenant.
3. Endpoints HTTP: permisos por rol (GET owner/admin/doctor; escritura
   owner/admin), 404 IDOR cross-tenant, 400 de validación, paginación.

RLS de expediente_document_templates y expediente_lab_analytes: cubierto por
el test guardián apps/core/tests/test_rls_coverage.py.

Patrón: AAA. factory_boy para datos. Mismo helper api_tenant_ctx que
test_plan_integral.py (parchea get_current_tenant en views_catalogos).
"""

from typing import Any

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.expediente.models import DocumentTemplate, LabAnalyte
from apps.expediente.selectors import (
    document_template_get,
    document_template_list,
    lab_analyte_get,
    lab_analyte_list,
)
from apps.expediente.services_catalogos import (
    document_template_activate,
    document_template_create,
    document_template_deactivate,
    document_template_delete,
    document_template_update,
    lab_analyte_activate,
    lab_analyte_create,
    lab_analyte_deactivate,
    lab_analyte_delete,
    lab_analyte_update,
)
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    DocumentTemplateFactory,
    LabAnalyteFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

_DOC_TEMPLATE_LIST_URL = "/api/v1/expediente/plantillas-documento/"
_LAB_ANALYTE_LIST_URL = "/api/v1/expediente/analitos/"


def _doc_template_detail_url(pk: Any) -> str:
    return f"/api/v1/expediente/plantillas-documento/{pk}/"


def _lab_analyte_detail_url(pk: Any) -> str:
    return f"/api/v1/expediente/analitos/{pk}/"


def _member(tenant: Any, role: str) -> Any:
    """Crea user con membresía activa en el tenant."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# DocumentTemplate — services
# ---------------------------------------------------------------------------


class TestDocumentTemplateServices:
    def test_create_ok(self, db: Any) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with tenant_ctx(tenant):
            template = document_template_create(
                tenant=tenant,
                user=user,
                name="Reporte estándar",
                section="reporte_medico",
                body="Texto sugerido...",
            )

        assert template.id is not None
        assert template.section == "reporte_medico"
        assert template.is_active is True

    def test_create_seccion_invalida_lanza_validation_error(self, db: Any) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            document_template_create(
                tenant=tenant,
                user=user,
                name="X",
                section="seccion-inventada",
                body="...",
            )

    def test_update_rechaza_is_active(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant)

        with tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            document_template_update(template=template, user=UserFactory(), is_active=False)

    def test_update_seccion_invalida_lanza_validation_error(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant)

        with tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            document_template_update(template=template, user=UserFactory(), section="inventada")

    def test_update_cambia_campos_permitidos(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant, name="Original")

        with tenant_ctx(tenant):
            updated = document_template_update(
                template=template, user=UserFactory(), name="Actualizado"
            )

        assert updated.name == "Actualizado"

    def test_activate_deactivate_toggle_is_active(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant, is_active=True)

        with tenant_ctx(tenant):
            document_template_deactivate(template=template, user=UserFactory())
            template.refresh_from_db()
            assert template.is_active is False

            document_template_activate(template=template, user=UserFactory())
            template.refresh_from_db()
            assert template.is_active is True

    def test_delete_soft_deletes_y_desaparece_del_listado(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant)

        with tenant_ctx(tenant):
            document_template_delete(template=template, user=UserFactory())
            assert not document_template_list(only_active=False).filter(id=template.id).exists()
            assert DocumentTemplate.all_objects.get(id=template.id).deleted_at is not None


# ---------------------------------------------------------------------------
# DocumentTemplate — selectors
# ---------------------------------------------------------------------------


class TestDocumentTemplateSelectors:
    def test_list_filtra_por_section(self, db: Any) -> None:
        tenant = TenantFactory()
        DocumentTemplateFactory(tenant=tenant, section="reporte_medico")
        DocumentTemplateFactory(tenant=tenant, section="seguimiento")

        with tenant_ctx(tenant):
            qs = document_template_list(section="seguimiento")

        assert qs.count() == 1
        assert qs.first().section == "seguimiento"

    def test_list_only_active_excluye_inactivas(self, db: Any) -> None:
        tenant = TenantFactory()
        DocumentTemplateFactory(tenant=tenant, is_active=True)
        DocumentTemplateFactory(tenant=tenant, is_active=False)

        with tenant_ctx(tenant):
            assert document_template_list(only_active=True).count() == 1
            assert document_template_list(only_active=False).count() == 2

    def test_get_aislamiento_multi_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = DocumentTemplateFactory(tenant=tenant2)

        with tenant_ctx(tenant1), pytest.raises(DocumentTemplate.DoesNotExist):
            document_template_get(template_id=other.id)


# ---------------------------------------------------------------------------
# DocumentTemplate — endpoints HTTP
# ---------------------------------------------------------------------------


class TestDocumentTemplateApi:
    def test_401_sin_autenticacion(self, db: Any) -> None:
        tenant = TenantFactory()
        client = APIClient()

        with api_tenant_ctx(tenant):
            resp = client.get(_DOC_TEMPLATE_LIST_URL)

        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "role",
        [TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN, TenantMembership.Role.DOCTOR],
    )
    def test_get_200_roles_permitidos(self, db: Any, role: str) -> None:
        tenant = TenantFactory()
        DocumentTemplateFactory(tenant=tenant)
        client = _auth_client(_member(tenant, role))

        with api_tenant_ctx(tenant):
            resp = client.get(_DOC_TEMPLATE_LIST_URL)

        assert resp.status_code == 200, (role, resp.content)
        assert resp.json()["count"] == 1

    @pytest.mark.parametrize(
        "role",
        [
            TenantMembership.Role.RECEPTION,
            TenantMembership.Role.FINANCE,
            TenantMembership.Role.NURSE,
            TenantMembership.Role.READONLY,
        ],
    )
    def test_get_403_roles_no_permitidos(self, db: Any, role: str) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, role))

        with api_tenant_ctx(tenant):
            resp = client.get(_DOC_TEMPLATE_LIST_URL)

        assert resp.status_code == 403

    def test_post_201_owner(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _DOC_TEMPLATE_LIST_URL,
                data={"name": "Nueva", "section": "estudios", "body": "Texto"},
                format="json",
            )

        assert resp.status_code == 201, resp.content
        assert DocumentTemplate.all_objects.filter(id=resp.json()["id"]).exists()

    def test_post_403_doctor_no_puede_crear(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _DOC_TEMPLATE_LIST_URL,
                data={"name": "X", "section": "general", "body": "Y"},
                format="json",
            )

        assert resp.status_code == 403

    def test_post_400_section_invalida(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.ADMIN))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _DOC_TEMPLATE_LIST_URL,
                data={"name": "X", "section": "no-existe", "body": "Y"},
                format="json",
            )

        assert resp.status_code == 400

    def test_post_400_campo_no_declarado(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _DOC_TEMPLATE_LIST_URL,
                data={"name": "X", "section": "general", "body": "Y", "campo_invalido": 1},
                format="json",
            )

        assert resp.status_code == 400

    def test_patch_200_admin_actualiza_texto(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant, name="Original")
        client = _auth_client(_member(tenant, TenantMembership.Role.ADMIN))

        with api_tenant_ctx(tenant):
            resp = client.patch(
                _doc_template_detail_url(template.id), data={"name": "Editada"}, format="json"
            )

        assert resp.status_code == 200, resp.content
        assert resp.json()["name"] == "Editada"

    def test_patch_toggle_is_active(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant, is_active=True)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant):
            resp = client.patch(
                _doc_template_detail_url(template.id), data={"is_active": False}, format="json"
            )

        assert resp.status_code == 200, resp.content
        assert resp.json()["is_active"] is False

    def test_patch_403_doctor_no_puede_editar(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(tenant):
            resp = client.patch(
                _doc_template_detail_url(template.id), data={"name": "X"}, format="json"
            )

        assert resp.status_code == 403

    def test_delete_204_y_no_reaparece_en_listado(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant):
            resp = client.delete(_doc_template_detail_url(template.id))
            assert resp.status_code == 204

            list_resp = client.get(_DOC_TEMPLATE_LIST_URL)

        assert list_resp.json()["count"] == 0

    def test_delete_403_reception(self, db: Any) -> None:
        tenant = TenantFactory()
        template = DocumentTemplateFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(tenant):
            resp = client.delete(_doc_template_detail_url(template.id))

        assert resp.status_code == 403

    def test_404_idor_get_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other_template = DocumentTemplateFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant1):
            resp = client.get(_doc_template_detail_url(other_template.id))

        assert resp.status_code == 404

    def test_404_idor_patch_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other_template = DocumentTemplateFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant1):
            resp = client.patch(
                _doc_template_detail_url(other_template.id), data={"name": "hack"}, format="json"
            )

        assert resp.status_code == 404

    def test_404_idor_delete_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other_template = DocumentTemplateFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant1):
            resp = client.delete(_doc_template_detail_url(other_template.id))

        assert resp.status_code == 404
        assert DocumentTemplate.all_objects.get(id=other_template.id).deleted_at is None


# ---------------------------------------------------------------------------
# LabAnalyte — selectors
# ---------------------------------------------------------------------------


class TestLabAnalyteSelectors:
    def test_list_only_active_excluye_inactivos(self, db: Any) -> None:
        tenant = TenantFactory()
        LabAnalyteFactory(tenant=tenant, is_active=True)
        LabAnalyteFactory(tenant=tenant, is_active=False)

        with tenant_ctx(tenant):
            assert lab_analyte_list(only_active=True).count() == 1
            assert lab_analyte_list(only_active=False).count() == 2

    def test_get_aislamiento_multi_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = LabAnalyteFactory(tenant=tenant2)

        with tenant_ctx(tenant1), pytest.raises(LabAnalyte.DoesNotExist):
            lab_analyte_get(analyte_id=other.id)


# ---------------------------------------------------------------------------
# LabAnalyte — services
# ---------------------------------------------------------------------------


class TestLabAnalyteServices:
    def test_create_ok(self, db: Any) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with tenant_ctx(tenant):
            analyte = lab_analyte_create(
                tenant=tenant,
                user=user,
                name="Glucosa en ayuno",
                unit="mg/dL",
                ref_low="70",
                ref_high="100",
            )

        assert analyte.name == "Glucosa en ayuno"
        assert analyte.is_active is True

    def test_create_rango_invertido_lanza_validation_error(self, db: Any) -> None:
        tenant = TenantFactory()
        user = UserFactory()

        with tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            lab_analyte_create(tenant=tenant, user=user, name="X", ref_low="100", ref_high="50")

    def test_update_rechaza_is_active(self, db: Any) -> None:
        tenant = TenantFactory()
        analyte = LabAnalyteFactory(tenant=tenant)

        with tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            lab_analyte_update(analyte=analyte, user=UserFactory(), is_active=False)

    def test_update_rango_invertido_lanza_validation_error(self, db: Any) -> None:
        tenant = TenantFactory()
        analyte = LabAnalyteFactory(tenant=tenant, ref_low="10", ref_high="20")

        with tenant_ctx(tenant), pytest.raises(DjangoValidationError):
            lab_analyte_update(analyte=analyte, user=UserFactory(), ref_low="30")

    def test_activate_deactivate_toggle(self, db: Any) -> None:
        tenant = TenantFactory()
        analyte = LabAnalyteFactory(tenant=tenant, is_active=True)

        with tenant_ctx(tenant):
            lab_analyte_deactivate(analyte=analyte, user=UserFactory())
            analyte.refresh_from_db()
            assert analyte.is_active is False

            lab_analyte_activate(analyte=analyte, user=UserFactory())
            analyte.refresh_from_db()
            assert analyte.is_active is True

    def test_delete_soft_deletes(self, db: Any) -> None:
        tenant = TenantFactory()
        analyte = LabAnalyteFactory(tenant=tenant)

        with tenant_ctx(tenant):
            lab_analyte_delete(analyte=analyte, user=UserFactory())
            assert not lab_analyte_list(only_active=False).filter(id=analyte.id).exists()
            assert LabAnalyte.all_objects.get(id=analyte.id).deleted_at is not None


# ---------------------------------------------------------------------------
# LabAnalyte — endpoints HTTP
# ---------------------------------------------------------------------------


class TestLabAnalyteApi:
    def test_get_200_doctor(self, db: Any) -> None:
        tenant = TenantFactory()
        LabAnalyteFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(tenant):
            resp = client.get(_LAB_ANALYTE_LIST_URL)

        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_get_403_finance(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.FINANCE))

        with api_tenant_ctx(tenant):
            resp = client.get(_LAB_ANALYTE_LIST_URL)

        assert resp.status_code == 403

    def test_post_201_admin(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.ADMIN))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LAB_ANALYTE_LIST_URL,
                data={"name": "Colesterol total", "unit": "mg/dL", "ref_high": "200"},
                format="json",
            )

        assert resp.status_code == 201, resp.content
        assert LabAnalyte.all_objects.filter(id=resp.json()["id"]).exists()

    def test_post_403_doctor(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(tenant):
            resp = client.post(_LAB_ANALYTE_LIST_URL, data={"name": "X"}, format="json")

        assert resp.status_code == 403

    def test_post_400_rango_invertido(self, db: Any) -> None:
        tenant = TenantFactory()
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LAB_ANALYTE_LIST_URL,
                data={"name": "X", "ref_low": "100", "ref_high": "10"},
                format="json",
            )

        assert resp.status_code == 400

    def test_patch_200_owner(self, db: Any) -> None:
        tenant = TenantFactory()
        analyte = LabAnalyteFactory(tenant=tenant, name="Original")
        client = _auth_client(_member(tenant, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant):
            resp = client.patch(
                _lab_analyte_detail_url(analyte.id), data={"name": "Editado"}, format="json"
            )

        assert resp.status_code == 200, resp.content
        assert resp.json()["name"] == "Editado"

    def test_delete_204_admin(self, db: Any) -> None:
        tenant = TenantFactory()
        analyte = LabAnalyteFactory(tenant=tenant)
        client = _auth_client(_member(tenant, TenantMembership.Role.ADMIN))

        with api_tenant_ctx(tenant):
            resp = client.delete(_lab_analyte_detail_url(analyte.id))

        assert resp.status_code == 204

    def test_404_idor_get_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = LabAnalyteFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant1):
            resp = client.get(_lab_analyte_detail_url(other.id))

        assert resp.status_code == 404

    def test_404_idor_delete_otro_tenant(self, db: Any) -> None:
        tenant1 = TenantFactory()
        tenant2 = TenantFactory()
        other = LabAnalyteFactory(tenant=tenant2)
        client = _auth_client(_member(tenant1, TenantMembership.Role.OWNER))

        with api_tenant_ctx(tenant1):
            resp = client.delete(_lab_analyte_detail_url(other.id))

        assert resp.status_code == 404
        assert LabAnalyte.all_objects.get(id=other.id).deleted_at is None
