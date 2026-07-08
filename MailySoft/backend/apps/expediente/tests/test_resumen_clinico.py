"""
Tests del Resumen Clínico por consulta (documento entregable al paciente).

Cubre (objetivo >= 80% en lógica de negocio):

1. clinical_summary_draft (service, sin persistir):
   - identificación: sexo + edad calculada a la fecha de la consulta.
   - antecedentes: filtra 'Negado'/vacío, incluye numero_hermanos > 0.
   - antecedentes: sin HC o todo negado -> texto por defecto.
   - padecimiento_actual: interrogatorio de la evolución, o HC si está vacío.
   - exploración física: solo sistemas 'observacion'/'alterado'.
   - exploración física: sin alteraciones -> texto por defecto.
   - diagnóstico_manejo: diagnosticos_texto + Diagnosis + tratamiento.
   - indicaciones: plan_recomendaciones + indicaciones_enfermeria.

2. clinical_summary_create (service, persiste):
   - crea con doctor/created_by correctos y audita CLINICAL_SUMMARY_CREATE.
   - tenant None -> ValidationError.
   - evolution de otro tenant -> ValidationError.
   - regla del médico: actor_role='doctor' no autor de la evolución -> ValidationError.

3. Endpoints HTTP:
   - borrador (GET): 200, 404 IDOR, 401, 403 por rol.
   - crear (POST): 201, 400 secciones desconocidas, 403 por rol.
   - listar (GET): 200 paginado.
   - PDF (GET): 202 -> tarea -> 200 %PDF (kind "resumen_clinico" registrado).

4. RLS: cubierto por el test guardián apps/core/tests/test_rls_coverage.py
   (descubre automáticamente expediente_clinical_summaries).

Patrón: AAA. factory_boy para datos. Tenant context parcheado igual que el
resto de la app expediente (ver conftest.py).
"""

import datetime
from typing import Any

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.expediente.models import ClinicalSummary, EvolutionNote
from apps.expediente.selectors import (
    clinical_summary_get,
    clinical_summary_list,
    evolution_note_get,
)
from apps.expediente.services_resumen import clinical_summary_create, clinical_summary_draft
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    DiagnosisFactory,
    DoctorFactory,
    EvolutionNoteFactory,
    MedicalHistoryFactory,
    TenantMembershipFactory,
    UserFactory,
    VitalSignsRecordFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_DRAFT_URL_TMPL = "/api/v1/expediente/evoluciones/{evolution_id}/resumen/borrador/"
_CREATE_URL_TMPL = "/api/v1/expediente/evoluciones/{evolution_id}/resumen/"
_PDF_URL_TMPL = "/api/v1/expediente/resumenes/{summary_id}/pdf/"
_LIST_URL_TMPL = "/api/v1/expediente/{patient_id}/resumenes/"

_VALID_SECCIONES: dict[str, str] = {
    "identificacion": "Se trata de paciente femenino de 30 años.",
    "antecedentes": "Sin antecedentes de importancia referidos.",
    "padecimiento_actual": "Cefalea de 2 días de evolución.",
    "exploracion_fisica": "Exploración física sin alteraciones aparentes.",
    "diagnostico_manejo": "Cefalea tensional. Manejo: analgesia.",
    "indicaciones": "Reposo y abundantes líquidos.",
}


def _member(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> Any:
    """Crea user con membresía activa en el tenant."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _doctor_note(**overrides: Any) -> Any:
    """Crea una EvolutionNote con su doctor/paciente/tenant, lista para usar."""
    return EvolutionNoteFactory(**overrides)


# ---------------------------------------------------------------------------
# 1. clinical_summary_draft — service (sin persistir)
# ---------------------------------------------------------------------------


class TestClinicalSummaryDraft:
    def test_identificacion_sexo_femenino_y_edad(self, db: Any) -> None:
        note = _doctor_note()
        patient = note.patient
        patient.date_of_birth = datetime.date(1990, 1, 1)
        patient.sex = "F"
        patient.save(update_fields=["date_of_birth", "sex"])

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        assert "femenino" in draft["secciones"]["identificacion"]
        assert "años" in draft["secciones"]["identificacion"]
        assert draft["encabezado"]["sexo"] == "F"
        assert draft["encabezado"]["edad"] is not None

    def test_identificacion_sexo_masculino(self, db: Any) -> None:
        note = _doctor_note()
        patient = note.patient
        patient.sex = "M"
        patient.save(update_fields=["sex"])

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        assert "masculino" in draft["secciones"]["identificacion"]

    def test_antecedentes_filtra_negado_e_incluye_relevantes(self, db: Any) -> None:
        note = _doctor_note()
        MedicalHistoryFactory(
            tenant=note.tenant,
            patient=note.patient,
            heredo_familiares={
                "diabetes": "Madre",
                "cancer": "Negado",
                "numero_hermanos": 2,
            },
            personales_patologicos={
                "quirurgicos": "Apendicectomía 2010",
                "diabetes": "Negado",
                "otros": "",
            },
        )

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        antecedentes = draft["secciones"]["antecedentes"]
        assert "ANTECEDENTES HEREDOFAMILIARES" in antecedentes
        assert "Diabetes: Madre" in antecedentes
        assert "Número de hermanos: 2" in antecedentes
        assert "Cáncer" not in antecedentes  # 'Negado' se excluye
        assert "ANTECEDENTES PERSONALES PATOLÓGICOS" in antecedentes
        assert "Apendicectomía 2010" in antecedentes

    def test_antecedentes_sin_hc_usa_texto_default(self, db: Any) -> None:
        note = _doctor_note()

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        assert draft["secciones"]["antecedentes"] == "Sin antecedentes de importancia referidos."

    def test_antecedentes_todo_negado_usa_texto_default(self, db: Any) -> None:
        note = _doctor_note()
        MedicalHistoryFactory(
            tenant=note.tenant,
            patient=note.patient,
            heredo_familiares={"diabetes": "Negado"},
            personales_patologicos={"diabetes": "Negado"},
        )

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        assert draft["secciones"]["antecedentes"] == "Sin antecedentes de importancia referidos."

    def test_padecimiento_actual_usa_interrogatorio_de_la_evolucion(self, db: Any) -> None:
        note = _doctor_note(interrogatorio="Dolor torácico opresivo.")
        MedicalHistoryFactory(
            tenant=note.tenant, patient=note.patient, padecimiento_actual="HC: otro texto."
        )

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        assert draft["secciones"]["padecimiento_actual"] == "Dolor torácico opresivo."

    def test_padecimiento_actual_fallback_a_hc(self, db: Any) -> None:
        note = _doctor_note(interrogatorio="")
        MedicalHistoryFactory(
            tenant=note.tenant, patient=note.patient, padecimiento_actual="Cefalea recurrente."
        )

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        assert draft["secciones"]["padecimiento_actual"] == "Cefalea recurrente."

    def test_exploracion_solo_sistemas_alterados_u_observacion(self, db: Any) -> None:
        note = _doctor_note(
            exploracion_fisica={
                "corazon": {"estado": "normal", "detalle": "Sin soplos"},
                "gastrointestinal": {
                    "estado": "alterado",
                    "detalle": "Dolor a la palpación en FID",
                },
                "renal": {"estado": "observacion", "detalle": ""},
            }
        )

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        exploracion = draft["secciones"]["exploracion_fisica"]
        assert "Gastrointestinal" in exploracion
        assert "Dolor a la palpación en FID" in exploracion
        assert "Renal" in exploracion
        assert "Corazón" not in exploracion  # normal se excluye

    def test_exploracion_sin_alteraciones_usa_texto_default(self, db: Any) -> None:
        note = _doctor_note(exploracion_fisica={})

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        assert (
            draft["secciones"]["exploracion_fisica"]
            == "Exploración física sin alteraciones aparentes."
        )

    def test_diagnostico_manejo_incluye_texto_diagnoses_y_tratamiento(self, db: Any) -> None:
        note = _doctor_note(
            diagnosticos_texto="Sospecha de apendicitis",
            tratamiento="Referencia a urgencias",
        )
        DiagnosisFactory(
            tenant=note.tenant,
            patient=note.patient,
            evolution=note,
            description="Apendicitis aguda",
            cie_code="K35",
        )

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        diagnostico = draft["secciones"]["diagnostico_manejo"]
        assert "Sospecha de apendicitis" in diagnostico
        assert "Apendicitis aguda [K35]" in diagnostico
        assert "Manejo: Referencia a urgencias" in diagnostico

    def test_indicaciones_junta_plan_e_indicaciones_enfermeria(self, db: Any) -> None:
        note = _doctor_note(
            plan_recomendaciones="Acudir a urgencias.",
            indicaciones_enfermeria="Ayuno.",
        )

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        indicaciones = draft["secciones"]["indicaciones"]
        assert "Acudir a urgencias." in indicaciones
        assert "Ayuno." in indicaciones

    def test_encabezado_incluye_signos_vitales_de_la_consulta(self, db: Any) -> None:
        note = _doctor_note()
        vs = VitalSignsRecordFactory(
            tenant=note.tenant,
            patient=note.patient,
            weight_kg=70,
            height_m="1.75",
            systolic=118,
            diastolic=76,
            heart_rate=68,
        )
        note.vital_signs = vs
        note.save(update_fields=["vital_signs"])

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            draft = clinical_summary_draft(evolution=evolution)

        encabezado = draft["encabezado"]
        assert encabezado["ta"] == "118/76"
        assert encabezado["fc"] == 68


# ---------------------------------------------------------------------------
# 2. clinical_summary_create — service (persiste)
# ---------------------------------------------------------------------------


class TestClinicalSummaryCreate:
    def test_crea_resumen_con_doctor_y_created_by_correctos(self, db: Any) -> None:
        note = _doctor_note()
        actor = note.doctor.membership.user

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            summary = clinical_summary_create(
                tenant=note.tenant,
                evolution=evolution,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        assert summary.doctor_id == note.doctor_id
        assert summary.created_by_id == actor.id
        assert summary.patient_id == note.patient_id
        assert summary.evolution_id == note.id
        assert summary.identificacion == _VALID_SECCIONES["identificacion"]

    def test_audita_clinical_summary_create(self, db: Any) -> None:
        note = _doctor_note()
        actor = note.doctor.membership.user

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            summary = clinical_summary_create(
                tenant=note.tenant,
                evolution=evolution,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        log = AuditLog.all_objects.filter(
            action=ActionType.CLINICAL_SUMMARY_CREATE, resource_id=summary.id
        ).first()
        assert log is not None
        assert log.resource_repr == str(summary.id)
        assert log.metadata.get("evolution_id") == str(note.id)
        assert log.metadata.get("patient_id") == str(note.patient_id)

    def test_tenant_none_lanza_validation_error(self, db: Any) -> None:
        note = _doctor_note()
        actor = note.doctor.membership.user

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)

        with pytest.raises(DjangoValidationError):
            clinical_summary_create(
                tenant=None,
                evolution=evolution,
                actor=actor,
                **_VALID_SECCIONES,
            )

    def test_evolution_de_otro_tenant_lanza_validation_error(self, db: Any) -> None:
        note1 = _doctor_note()
        note2 = _doctor_note()  # otro tenant
        actor = note1.doctor.membership.user

        with tenant_ctx(note1.tenant):
            evolution2 = EvolutionNote.all_objects.get(id=note2.id)
            with pytest.raises(DjangoValidationError):
                clinical_summary_create(
                    tenant=note1.tenant,
                    evolution=evolution2,
                    actor=actor,
                    **_VALID_SECCIONES,
                )

    def test_regla_del_medico_actor_no_autor_lanza_error(self, db: Any) -> None:
        note = _doctor_note()
        otro_doctor_user = UserFactory()

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            with pytest.raises(DjangoValidationError):
                clinical_summary_create(
                    tenant=note.tenant,
                    evolution=evolution,
                    actor=otro_doctor_user,
                    actor_role="doctor",
                    **_VALID_SECCIONES,
                )

    def test_owner_puede_crear_resumen_para_cualquier_medico(self, db: Any) -> None:
        note = _doctor_note()
        owner_user = UserFactory()

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            summary = clinical_summary_create(
                tenant=note.tenant,
                evolution=evolution,
                actor=owner_user,
                actor_role="owner",
                **_VALID_SECCIONES,
            )

        assert summary.doctor_id == note.doctor_id
        assert summary.created_by_id == owner_user.id


# ---------------------------------------------------------------------------
# 3a. Endpoint: borrador (GET)
# ---------------------------------------------------------------------------


class TestClinicalSummaryDraftApi:
    def test_200_devuelve_encabezado_y_secciones(self, db: Any) -> None:
        note = _doctor_note()
        client = _auth_client(_member(note.tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(note.tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(evolution_id=note.id))

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert "encabezado" in body
        assert "secciones" in body
        assert set(_VALID_SECCIONES.keys()) == set(body["secciones"].keys())

    def test_401_sin_autenticacion(self, db: Any) -> None:
        note = _doctor_note()
        client = APIClient()

        with api_tenant_ctx(note.tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(evolution_id=note.id))

        assert resp.status_code == 401

    def test_403_recepcion(self, db: Any) -> None:
        note = _doctor_note()
        client = _auth_client(_member(note.tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(note.tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(evolution_id=note.id))

        assert resp.status_code == 403

    def test_403_finanzas(self, db: Any) -> None:
        note = _doctor_note()
        client = _auth_client(_member(note.tenant, TenantMembership.Role.FINANCE))

        with api_tenant_ctx(note.tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(evolution_id=note.id))

        assert resp.status_code == 403

    def test_403_enfermeria(self, db: Any) -> None:
        note = _doctor_note()
        client = _auth_client(_member(note.tenant, TenantMembership.Role.NURSE))

        with api_tenant_ctx(note.tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(evolution_id=note.id))

        assert resp.status_code == 403

    def test_403_readonly(self, db: Any) -> None:
        note = _doctor_note()
        client = _auth_client(_member(note.tenant, TenantMembership.Role.READONLY))

        with api_tenant_ctx(note.tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(evolution_id=note.id))

        assert resp.status_code == 403

    def test_200_owner_y_admin(self, db: Any) -> None:
        note = _doctor_note()
        for role in (TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN):
            client = _auth_client(_member(note.tenant, role))
            with api_tenant_ctx(note.tenant):
                resp = client.get(_DRAFT_URL_TMPL.format(evolution_id=note.id))
            assert resp.status_code == 200, (role, resp.content)

    def test_404_idor_evolucion_otro_tenant(self, db: Any) -> None:
        note1 = _doctor_note()
        note2 = _doctor_note()
        client = _auth_client(_member(note1.tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(note1.tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(evolution_id=note2.id))

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3b. Endpoint: crear (POST)
# ---------------------------------------------------------------------------


class TestClinicalSummaryCreateApi:
    def test_201_crea_resumen(self, db: Any) -> None:
        note = _doctor_note()
        user = note.doctor.membership.user
        # El usuario ya tiene membresía de doctor (creada por DoctorFactory);
        # forzamos autenticación con ese mismo user.
        client = _auth_client(user)

        with api_tenant_ctx(note.tenant):
            resp = client.post(
                _CREATE_URL_TMPL.format(evolution_id=note.id),
                data=_VALID_SECCIONES,
                format="json",
            )

        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["evolution_id"] == str(note.id)
        assert ClinicalSummary.all_objects.filter(id=body["id"]).exists()

    def test_400_campo_no_declarado(self, db: Any) -> None:
        note = _doctor_note()
        client = _auth_client(note.doctor.membership.user)

        with api_tenant_ctx(note.tenant):
            resp = client.post(
                _CREATE_URL_TMPL.format(evolution_id=note.id),
                data={**_VALID_SECCIONES, "campo_invalido": "x"},
                format="json",
            )

        assert resp.status_code == 400

    def test_403_recepcion_no_puede_crear(self, db: Any) -> None:
        note = _doctor_note()
        client = _auth_client(_member(note.tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(note.tenant):
            resp = client.post(
                _CREATE_URL_TMPL.format(evolution_id=note.id),
                data=_VALID_SECCIONES,
                format="json",
            )

        assert resp.status_code == 403

    def test_404_idor_evolucion_otro_tenant(self, db: Any) -> None:
        note1 = _doctor_note()
        note2 = _doctor_note()
        client = _auth_client(_member(note1.tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(note1.tenant):
            resp = client.post(
                _CREATE_URL_TMPL.format(evolution_id=note2.id),
                data=_VALID_SECCIONES,
                format="json",
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3c. Endpoint: listar (GET)
# ---------------------------------------------------------------------------


class TestPatientClinicalSummaryListApi:
    def test_200_lista_paginada(self, db: Any) -> None:
        note = _doctor_note()
        actor = note.doctor.membership.user

        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            clinical_summary_create(
                tenant=note.tenant,
                evolution=evolution,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        client = _auth_client(_member(note.tenant, TenantMembership.Role.DOCTOR))
        with api_tenant_ctx(note.tenant):
            resp = client.get(_LIST_URL_TMPL.format(patient_id=note.patient_id))

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["evolution_id"] == str(note.id)
        assert "doctor_name" in body["results"][0]

    def test_403_enfermeria_no_puede_listar(self, db: Any) -> None:
        note = _doctor_note()
        client = _auth_client(_member(note.tenant, TenantMembership.Role.NURSE))

        with api_tenant_ctx(note.tenant):
            resp = client.get(_LIST_URL_TMPL.format(patient_id=note.patient_id))

        assert resp.status_code == 403

    def test_404_idor_paciente_otro_tenant(self, db: Any) -> None:
        note1 = _doctor_note()
        note2 = _doctor_note()
        client = _auth_client(_member(note1.tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(note1.tenant):
            resp = client.get(_LIST_URL_TMPL.format(patient_id=note2.patient_id))

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3d. Endpoint: PDF (GET) — encola, corre la tarea, descarga
# ---------------------------------------------------------------------------


class TestClinicalSummaryPdfApi:
    def _create_summary(self, note: Any) -> Any:
        actor = note.doctor.membership.user
        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            return clinical_summary_create(
                tenant=note.tenant,
                evolution=evolution,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

    def test_kind_resumen_clinico_registrado(self) -> None:
        from apps.pdfs.registry import get_pdf_kind

        spec = get_pdf_kind("resumen_clinico")
        assert spec.builder is not None
        assert spec.permission is not None

    def test_202_encola_y_luego_descarga_pdf(self, db: Any) -> None:
        from apps.pdfs.tasks import generate_pdf

        note = _doctor_note()
        summary = self._create_summary(note)
        client = _auth_client(_member(note.tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(note.tenant):
            resp = client.get(_PDF_URL_TMPL.format(summary_id=summary.id))
        assert resp.status_code == 202, resp.content
        job_id = resp.json()["job_id"]

        generate_pdf(job_id)

        with api_tenant_ctx(note.tenant):
            file_resp = client.get(
                f"/api/v1/pdfs/job/{job_id}/file/", HTTP_ACCEPT="application/pdf"
            )

        assert file_resp.status_code == 200
        assert file_resp["Content-Type"] == "application/pdf"
        assert file_resp.content[:4] == b"%PDF"

    def test_403_recepcion_no_puede_pedir_pdf(self, db: Any) -> None:
        note = _doctor_note()
        summary = self._create_summary(note)
        client = _auth_client(_member(note.tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(note.tenant):
            resp = client.get(_PDF_URL_TMPL.format(summary_id=summary.id))

        assert resp.status_code == 403

    def test_404_idor_resumen_otro_tenant(self, db: Any) -> None:
        note1 = _doctor_note()
        note2 = _doctor_note()
        summary2 = self._create_summary(note2)
        client = _auth_client(_member(note1.tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(note1.tenant):
            resp = client.get(_PDF_URL_TMPL.format(summary_id=summary2.id))

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Selectors — aislamiento multi-tenant
# ---------------------------------------------------------------------------


class TestClinicalSummarySelectors:
    def test_clinical_summary_list_aislamiento_multi_tenant(self, db: Any) -> None:
        note1 = _doctor_note()
        note2 = _doctor_note()
        actor1 = note1.doctor.membership.user
        actor2 = note2.doctor.membership.user

        with tenant_ctx(note1.tenant):
            evolution1 = evolution_note_get(evolution_id=note1.id)
            clinical_summary_create(
                tenant=note1.tenant,
                evolution=evolution1,
                actor=actor1,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )
        with tenant_ctx(note2.tenant):
            evolution2 = evolution_note_get(evolution_id=note2.id)
            clinical_summary_create(
                tenant=note2.tenant,
                evolution=evolution2,
                actor=actor2,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        with tenant_ctx(note1.tenant):
            results = list(clinical_summary_list(patient=note1.patient))

        assert len(results) == 1
        assert results[0].tenant_id == note1.tenant_id

    def test_clinical_summary_get_404_otro_tenant(self, db: Any) -> None:
        note = _doctor_note()
        summary = self.__class__._create(note)

        other_tenant = DoctorFactory().tenant
        with tenant_ctx(other_tenant):
            with pytest.raises(ClinicalSummary.DoesNotExist):
                clinical_summary_get(summary_id=summary.id)

    @staticmethod
    def _create(note: Any) -> Any:
        actor = note.doctor.membership.user
        with tenant_ctx(note.tenant):
            evolution = evolution_note_get(evolution_id=note.id)
            return clinical_summary_create(
                tenant=note.tenant,
                evolution=evolution,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )
