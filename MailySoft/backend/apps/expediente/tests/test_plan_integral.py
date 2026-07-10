"""
Tests del Plan Integral de Longevidad y Medicina Regenerativa (Fase 1).

Cubre (objetivo >= 80% en lógica de negocio):

1. longevity_plan_draft (service, sin persistir):
   - alergias: vigentes -> texto 'Sustancia (reacción) [severidad]'; sin
     alergias -> 'Negadas.'.
   - antecedentes / tratamientos_actuales: desde MedicalHistory.
   - condiciones_mejorar: solo sistemas 'con_alteraciones' de
     exploracion_fisica_basal.
   - esquema: [] sin treatment_plan_id; snapshot correcto con
     treatment_plan_id (incluye clinical_description del ServiceConcept).
   - planes_disponibles: lista los esquemas del paciente con items_count.
   - errores: treatment_plan_id de otro paciente -> ValidationError;
     inexistente/otro tenant -> TreatmentPlan.DoesNotExist.

2. longevity_plan_create (service, persiste):
   - crea con doctor resuelto del actor (actor_role='doctor') y snapshot
     del esquema; audita LONGEVITY_PLAN_CREATE.
   - owner/admin -> doctor None.
   - tenant None / paciente de otro tenant / rol no permitido -> ValidationError.
   - treatment_plan de otro paciente -> ValidationError.

3. Endpoints HTTP:
   - borrador (GET): 200, 400 uuid inválido, 404 IDOR paciente/esquema,
     403 por rol.
   - listar/crear (GET/POST mismo path): 201, 400 secciones desconocidas,
     403 por rol, 200 lista paginada, 404 IDOR paciente.
   - PDF (GET): 202 -> tarea -> 200 %PDF (kind "plan_integral" registrado).

4. Selectors: aislamiento multi-tenant.

5. RLS: cubierto por el test guardián apps/core/tests/test_rls_coverage.py
   (descubre automáticamente expediente_longevity_plans).

Patrón: AAA. factory_boy para datos. Tenant context parcheado igual que el
resto de la app expediente (ver conftest.py).
"""

import uuid
from typing import Any

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.expediente.models import LongevityPlan, TreatmentPlan
from apps.expediente.selectors import longevity_plan_get, longevity_plan_list
from apps.expediente.services_calendarizacion import treatment_plan_create
from apps.expediente.services_plan_integral import longevity_plan_create, longevity_plan_draft
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AllergyFactory,
    ClinicTeamMemberFactory,
    DoctorFactory,
    LabAnalyteFactory,
    MedicalHistoryFactory,
    PatientFactory,
    ServiceConceptFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_DRAFT_URL_TMPL = "/api/v1/expediente/{patient_id}/plan-integral/borrador/"
_LIST_CREATE_URL_TMPL = "/api/v1/expediente/{patient_id}/plan-integral/"
_PDF_URL_TMPL = "/api/v1/expediente/plan-integral/{plan_id}/pdf/"

_VALID_SECCIONES: dict[str, str] = {
    "alergias": "Negadas.",
    "antecedentes": "Sin antecedentes de importancia referidos.",
    "tratamientos_actuales": "Ninguno.",
    "condiciones_mejorar": "Fatiga crónica.",
    "estudios": "Perfil hormonal dentro de parámetros normales.",
    "reporte_medico": "Paciente en buen estado general.",
    "interconsulta": "Sin interconsulta requerida.",
    "seguimiento": "Cita de control en 3 meses.",
}


def _setup(tenant: Any = None) -> tuple[Any, Any, Any]:
    """Crea tenant/paciente/doctor consistentes (mismo tenant)."""
    tenant = tenant or TenantFactory()
    doctor = DoctorFactory(tenant=tenant)
    patient = PatientFactory(tenant=tenant)
    return tenant, patient, doctor


def _member(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> Any:
    """Crea user con membresía activa en el tenant."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


_SIMPLE_ITEM: dict[str, Any] = {
    "description": "Terapia de reemplazo hormonal",
    "unit_price": "1200.00",
    "quantity": 4,
}


# ---------------------------------------------------------------------------
# 1. longevity_plan_draft — service (sin persistir)
# ---------------------------------------------------------------------------


class TestLongevityPlanDraft:
    def test_alergias_vigentes_se_listan(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        AllergyFactory(
            tenant=tenant,
            patient=patient,
            substance="Penicilina",
            reaction="Urticaria",
            severity="severa",
        )

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert draft["secciones"]["alergias"] == "Penicilina (Urticaria) [severa]"

    def test_sin_alergias_usa_negadas(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert draft["secciones"]["alergias"] == "Negadas."

    def test_alergia_resuelta_no_aparece(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        AllergyFactory(tenant=tenant, patient=patient, substance="Sulfas", is_active=False)

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert draft["secciones"]["alergias"] == "Negadas."

    def test_antecedentes_y_tratamientos_desde_hc(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        MedicalHistoryFactory(
            tenant=tenant,
            patient=patient,
            antecedentes_importancia="Hipertensión controlada.",
            tratamientos_actuales="Losartán 50mg cada 24h.",
        )

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert draft["secciones"]["antecedentes"] == "Hipertensión controlada."
        assert draft["secciones"]["tratamientos_actuales"] == "Losartán 50mg cada 24h."

    def test_sin_hc_secciones_quedan_vacias(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert draft["secciones"]["antecedentes"] == ""
        assert draft["secciones"]["tratamientos_actuales"] == ""
        assert draft["secciones"]["condiciones_mejorar"] == ""

    def test_condiciones_mejorar_solo_con_alteraciones(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        MedicalHistoryFactory(
            tenant=tenant,
            patient=patient,
            exploracion_fisica_basal={
                "corazon": {"estado": "sin_alteraciones", "detalle": ""},
                "renal": {
                    "estado": "con_alteraciones",
                    "detalle": "Función renal disminuida",
                },
                "endocrino": {"estado": "con_alteraciones", "detalle": ""},
            },
        )

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        condiciones = draft["secciones"]["condiciones_mejorar"]
        assert "Renal: Función renal disminuida" in condiciones
        assert "Endocrino." in condiciones
        assert "Corazón" not in condiciones

    def test_esquema_vacio_sin_treatment_plan_id(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert draft["esquema"] == []

    def test_esquema_snapshot_con_treatment_plan_id(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        concept = ServiceConceptFactory(
            tenant=tenant,
            clinical_description="Protocolo de aplicación semanal por 4 semanas.",
        )
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                items=[{"concept_id": str(concept.id), "quantity": 4}],
                doctor=doctor,
                actor_role="doctor",
            )
            draft = longevity_plan_draft(patient=patient, treatment_plan_id=plan.id)

        assert len(draft["esquema"]) == 1
        item = draft["esquema"][0]
        assert item["description"] == concept.name
        assert item["quantity"] == 4
        assert item["clinical_description"] == concept.clinical_description

    def test_planes_disponibles_lista_esquemas_del_paciente(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            treatment_plan_create(
                patient=patient,
                actor=actor,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )
            draft = longevity_plan_draft(patient=patient)

        assert len(draft["planes_disponibles"]) == 1
        assert draft["planes_disponibles"][0]["items_count"] == 1

    def test_treatment_plan_de_otro_paciente_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        otro_paciente = PatientFactory(tenant=tenant)
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=otro_paciente,
                actor=actor,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )
            with pytest.raises(DjangoValidationError):
                longevity_plan_draft(patient=patient, treatment_plan_id=plan.id)

    def test_treatment_plan_de_otro_tenant_lanza_does_not_exist(self, db: Any) -> None:
        tenant1, patient1, doctor1 = _setup()
        tenant2, patient2, doctor2 = _setup()
        actor2 = doctor2.membership.user

        with tenant_ctx(tenant2):
            plan2 = treatment_plan_create(
                patient=patient2,
                actor=actor2,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor2,
                actor_role="doctor",
            )

        with tenant_ctx(tenant1):
            with pytest.raises(TreatmentPlan.DoesNotExist):
                longevity_plan_draft(patient=patient1, treatment_plan_id=plan2.id)


# ---------------------------------------------------------------------------
# 2. longevity_plan_create — service (persiste)
# ---------------------------------------------------------------------------


class TestLongevityPlanCreate:
    def test_crea_plan_con_doctor_resuelto_del_actor(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        assert plan.doctor_id == doctor.id
        assert plan.created_by_id == actor.id
        assert plan.patient_id == patient.id
        assert plan.alergias == _VALID_SECCIONES["alergias"]
        assert plan.treatment_plan_id is None
        assert plan.esquema == []

    def test_owner_crea_plan_sin_doctor_fijo(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        owner_user = UserFactory()

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=owner_user,
                actor_role="owner",
                **_VALID_SECCIONES,
            )

        assert plan.doctor_id is None
        assert plan.created_by_id == owner_user.id

    def test_snapshot_esquema_al_crear_con_treatment_plan_id(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        concept = ServiceConceptFactory(
            tenant=tenant, clinical_description="Aplicación intramuscular semanal."
        )
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            tx_plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                items=[{"concept_id": str(concept.id), "quantity": 6}],
                doctor=doctor,
                actor_role="doctor",
            )
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=actor,
                actor_role="doctor",
                treatment_plan_id=tx_plan.id,
                **_VALID_SECCIONES,
            )

        assert plan.treatment_plan_id == tx_plan.id
        assert len(plan.esquema) == 1
        assert plan.esquema[0]["description"] == concept.name
        assert plan.esquema[0]["quantity"] == 6
        assert plan.esquema[0]["clinical_description"] == concept.clinical_description

    def test_audita_longevity_plan_create(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        log = AuditLog.all_objects.filter(
            action=ActionType.LONGEVITY_PLAN_CREATE, resource_id=plan.id
        ).first()
        assert log is not None
        assert log.resource_repr == str(plan.id)
        assert log.metadata.get("patient_id") == str(patient.id)
        assert log.metadata.get("treatment_plan_id") is None

    def test_tenant_none_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with pytest.raises(DjangoValidationError):
            longevity_plan_create(
                tenant=None,
                patient=patient,
                actor=actor,
                **_VALID_SECCIONES,
            )

    def test_paciente_de_otro_tenant_lanza_validation_error(self, db: Any) -> None:
        tenant1, _patient1, doctor1 = _setup()
        tenant2, patient2, _doctor2 = _setup()
        actor = doctor1.membership.user

        with pytest.raises(DjangoValidationError):
            longevity_plan_create(
                tenant=tenant1,
                patient=patient2,
                actor=actor,
                **_VALID_SECCIONES,
            )

    def test_rol_no_permitido_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        actor = UserFactory()

        with pytest.raises(DjangoValidationError):
            longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=actor,
                actor_role="finance",
                **_VALID_SECCIONES,
            )

    def test_treatment_plan_de_otro_paciente_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        otro_paciente = PatientFactory(tenant=tenant)
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            tx_plan = treatment_plan_create(
                patient=otro_paciente,
                actor=actor,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )
            with pytest.raises(DjangoValidationError):
                longevity_plan_create(
                    tenant=tenant,
                    patient=patient,
                    actor=actor,
                    actor_role="doctor",
                    treatment_plan_id=tx_plan.id,
                    **_VALID_SECCIONES,
                )


# ---------------------------------------------------------------------------
# 3a. Endpoint: borrador (GET)
# ---------------------------------------------------------------------------


class TestLongevityPlanDraftApi:
    def test_200_devuelve_forma_esperada(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert "encabezado" in body
        assert "secciones" in body
        assert "esquema" in body
        assert "planes_disponibles" in body
        assert set(_VALID_SECCIONES.keys()) == set(body["secciones"].keys())

    def test_401_sin_autenticacion(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        client = APIClient()

        with api_tenant_ctx(tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 401

    def test_403_recepcion(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 403

    def test_403_finanzas(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.FINANCE))

        with api_tenant_ctx(tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 403

    def test_403_enfermeria(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.NURSE))

        with api_tenant_ctx(tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 403

    def test_200_owner_y_admin(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        for role in (TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN):
            client = _auth_client(_member(tenant, role))
            with api_tenant_ctx(tenant):
                resp = client.get(_DRAFT_URL_TMPL.format(patient_id=patient.id))
            assert resp.status_code == 200, (role, resp.content)

    def test_404_idor_paciente_otro_tenant(self, db: Any) -> None:
        tenant1, _patient1, doctor1 = _setup()
        _tenant2, patient2, _doctor2 = _setup()
        client = _auth_client(doctor1.membership.user)

        with api_tenant_ctx(tenant1):
            resp = client.get(_DRAFT_URL_TMPL.format(patient_id=patient2.id))

        assert resp.status_code == 404

    def test_400_treatment_plan_id_uuid_invalido(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.get(
                _DRAFT_URL_TMPL.format(patient_id=patient.id) + "?treatment_plan_id=no-es-un-uuid"
            )

        assert resp.status_code == 400

    def test_404_treatment_plan_id_inexistente(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.get(
                _DRAFT_URL_TMPL.format(patient_id=patient.id) + f"?treatment_plan_id={uuid.uuid4()}"
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3b. Endpoint: listar (GET) / crear (POST) — mismo path
# ---------------------------------------------------------------------------


class TestLongevityPlanListCreateApi:
    def test_201_crea_plan(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data=_VALID_SECCIONES,
                format="json",
            )

        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert LongevityPlan.all_objects.filter(id=body["id"]).exists()
        assert "doctor_name" in body

    def test_400_campo_no_declarado(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={**_VALID_SECCIONES, "campo_invalido": "x"},
                format="json",
            )

        assert resp.status_code == 400

    def test_403_recepcion_no_puede_crear(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data=_VALID_SECCIONES,
                format="json",
            )

        assert resp.status_code == 403

    def test_404_idor_paciente_otro_tenant_crear(self, db: Any) -> None:
        tenant1, _patient1, doctor1 = _setup()
        _tenant2, patient2, _doctor2 = _setup()
        client = _auth_client(doctor1.membership.user)

        with api_tenant_ctx(tenant1):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient2.id),
                data=_VALID_SECCIONES,
                format="json",
            )

        assert resp.status_code == 404

    def test_200_lista_paginada(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))
        with api_tenant_ctx(tenant):
            resp = client.get(_LIST_CREATE_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        assert "doctor_name" in body["results"][0]

    def test_403_enfermeria_no_puede_listar(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.NURSE))

        with api_tenant_ctx(tenant):
            resp = client.get(_LIST_CREATE_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 403

    def test_404_idor_paciente_otro_tenant_listar(self, db: Any) -> None:
        tenant1, _patient1, doctor1 = _setup()
        _tenant2, patient2, _doctor2 = _setup()
        client = _auth_client(doctor1.membership.user)

        with api_tenant_ctx(tenant1):
            resp = client.get(_LIST_CREATE_URL_TMPL.format(patient_id=patient2.id))

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3c. Endpoint: PDF (GET) — encola, corre la tarea, descarga
# ---------------------------------------------------------------------------


class TestLongevityPlanPdfApi:
    def _create_plan(self, tenant: Any, patient: Any, doctor: Any) -> Any:
        actor = doctor.membership.user
        with tenant_ctx(tenant):
            return longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=actor,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

    def test_kind_plan_integral_registrado(self) -> None:
        from apps.pdfs.registry import get_pdf_kind

        spec = get_pdf_kind("plan_integral")
        assert spec.builder is not None
        assert spec.permission is not None

    def test_202_encola_y_luego_descarga_pdf(self, db: Any) -> None:
        from apps.pdfs.tasks import generate_pdf

        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(tenant):
            resp = client.get(_PDF_URL_TMPL.format(plan_id=plan.id))
        assert resp.status_code == 202, resp.content
        job_id = resp.json()["job_id"]

        generate_pdf(job_id)

        with api_tenant_ctx(tenant):
            file_resp = client.get(
                f"/api/v1/pdfs/job/{job_id}/file/", HTTP_ACCEPT="application/pdf"
            )

        assert file_resp.status_code == 200
        assert file_resp["Content-Type"] == "application/pdf"
        assert file_resp.content[:4] == b"%PDF"

    def test_202_pdf_con_lab_results_gabinete_equipo_no_rompe(self, db: Any) -> None:
        """Smoke test: el PDF renderiza sin error con las 3 secciones nuevas pobladas."""
        from apps.pdfs.tasks import generate_pdf

        tenant, patient, doctor = _setup()
        ClinicTeamMemberFactory(tenant=tenant, departamento="Nutrición", nombre="Lic. Ruiz")
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=actor,
                actor_role="doctor",
                lab_results=[
                    {
                        "name": "Glucosa",
                        "unit": "mg/dL",
                        "ref_low": "70",
                        "ref_high": "100",
                        "result": "180",
                    }
                ],
                gabinete_studies=[{"name": "Rayos X de tórax", "conclusion": "Sin hallazgos."}],
                **_VALID_SECCIONES,
            )

        client = _auth_client(_member(tenant, TenantMembership.Role.DOCTOR))

        with api_tenant_ctx(tenant):
            resp = client.get(_PDF_URL_TMPL.format(plan_id=plan.id))
        assert resp.status_code == 202, resp.content
        job_id = resp.json()["job_id"]

        generate_pdf(job_id)

        with api_tenant_ctx(tenant):
            file_resp = client.get(
                f"/api/v1/pdfs/job/{job_id}/file/", HTTP_ACCEPT="application/pdf"
            )

        assert file_resp.status_code == 200
        assert file_resp["Content-Type"] == "application/pdf"
        assert file_resp.content[:4] == b"%PDF"

    def test_403_recepcion_no_puede_pedir_pdf(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(tenant):
            resp = client.get(_PDF_URL_TMPL.format(plan_id=plan.id))

        assert resp.status_code == 403

    def test_404_idor_plan_otro_tenant(self, db: Any) -> None:
        tenant1, patient1, doctor1 = _setup()
        tenant2, patient2, doctor2 = _setup()
        plan2 = self._create_plan(tenant2, patient2, doctor2)
        client = _auth_client(doctor1.membership.user)

        with api_tenant_ctx(tenant1):
            resp = client.get(_PDF_URL_TMPL.format(plan_id=plan2.id))

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Selectors — aislamiento multi-tenant
# ---------------------------------------------------------------------------


class TestLongevityPlanSelectors:
    def test_longevity_plan_list_aislamiento_multi_tenant(self, db: Any) -> None:
        tenant1, patient1, doctor1 = _setup()
        tenant2, patient2, doctor2 = _setup()

        with tenant_ctx(tenant1):
            longevity_plan_create(
                tenant=tenant1,
                patient=patient1,
                actor=doctor1.membership.user,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )
        with tenant_ctx(tenant2):
            longevity_plan_create(
                tenant=tenant2,
                patient=patient2,
                actor=doctor2.membership.user,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        with tenant_ctx(tenant1):
            results = list(longevity_plan_list(patient=patient1))

        assert len(results) == 1
        assert results[0].tenant_id == tenant1.id

    def test_longevity_plan_get_404_otro_tenant(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self.__class__._create(tenant, patient, doctor)

        other_tenant, _p, _d = _setup()
        with tenant_ctx(other_tenant):
            with pytest.raises(LongevityPlan.DoesNotExist):
                longevity_plan_get(plan_id=plan.id)

    @staticmethod
    def _create(tenant: Any, patient: Any, doctor: Any) -> Any:
        with tenant_ctx(tenant):
            return longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=doctor.membership.user,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )


# ---------------------------------------------------------------------------
# 5. Fase 3/4 — lab_results, gabinete_studies, equipo
# ---------------------------------------------------------------------------


class TestLongevityPlanDraftEquipo:
    def test_draft_incluye_equipo_del_catalogo_ordenado(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        ClinicTeamMemberFactory(
            tenant=tenant, departamento="Nutrición", nombre="Lic. Ruiz", order=1
        )
        ClinicTeamMemberFactory(
            tenant=tenant, departamento="Enfermería", nombre="Enf. Gómez", order=0
        )

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert draft["lab_results"] == []
        assert draft["gabinete_studies"] == []
        assert [m["departamento"] for m in draft["equipo"]] == ["Enfermería", "Nutrición"]

    def test_draft_equipo_excluye_inactivos(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()
        ClinicTeamMemberFactory(tenant=tenant, is_active=True)
        ClinicTeamMemberFactory(tenant=tenant, is_active=False)

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert len(draft["equipo"]) == 1

    def test_draft_equipo_vacio_sin_catalogo(self, db: Any) -> None:
        tenant, patient, _doctor = _setup()

        with tenant_ctx(tenant):
            draft = longevity_plan_draft(patient=patient)

        assert draft["equipo"] == []


class TestLongevityPlanCreateLabGabineteEquipo:
    def test_snapshotea_equipo_del_catalogo_vigente(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        ClinicTeamMemberFactory(tenant=tenant, departamento="Nutrición", nombre="Lic. Ruiz")

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=doctor.membership.user,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        assert plan.equipo == [{"departamento": "Nutrición", "nombre": "Lic. Ruiz"}]

    def test_cliente_no_puede_enviar_equipo(self, db: Any) -> None:
        """equipo NO es kwarg de longevity_plan_create — el cliente no puede inyectarlo."""
        import inspect

        sig = inspect.signature(longevity_plan_create)
        assert "equipo" not in sig.parameters

    def test_gabinete_studies_se_snapshotea(self, db: Any) -> None:
        tenant, patient, doctor = _setup()

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=doctor.membership.user,
                actor_role="doctor",
                gabinete_studies=[
                    {"name": "Ultrasonido abdominal", "conclusion": "Sin hallazgos."}
                ],
                **_VALID_SECCIONES,
            )

        assert plan.gabinete_studies == [
            {"name": "Ultrasonido abdominal", "conclusion": "Sin hallazgos."}
        ]

    def test_lab_result_out_of_range_true_cuando_fuera_de_rango(self, db: Any) -> None:
        tenant, patient, doctor = _setup()

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=doctor.membership.user,
                actor_role="doctor",
                lab_results=[
                    {
                        "name": "Glucosa",
                        "unit": "mg/dL",
                        "ref_low": "70",
                        "ref_high": "100",
                        "result": "180",
                    }
                ],
                **_VALID_SECCIONES,
            )

        assert len(plan.lab_results) == 1
        assert plan.lab_results[0]["out_of_range"] is True
        assert plan.lab_results[0]["result"] == "180"

    def test_lab_result_out_of_range_false_dentro_de_rango(self, db: Any) -> None:
        tenant, patient, doctor = _setup()

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=doctor.membership.user,
                actor_role="doctor",
                lab_results=[
                    {"name": "Glucosa", "ref_low": "70", "ref_high": "100", "result": "90"}
                ],
                **_VALID_SECCIONES,
            )

        assert plan.lab_results[0]["out_of_range"] is False

    def test_lab_result_no_numerico_out_of_range_false(self, db: Any) -> None:
        tenant, patient, doctor = _setup()

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=doctor.membership.user,
                actor_role="doctor",
                lab_results=[
                    {"name": "Cultivo", "ref_low": "1", "ref_high": "2", "result": "Negativo"}
                ],
                **_VALID_SECCIONES,
            )

        assert plan.lab_results[0]["out_of_range"] is False

    def test_lab_result_hereda_rango_del_analyte_id(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        analyte = LabAnalyteFactory(tenant=tenant, name="Colesterol", ref_low="0", ref_high="200")

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=doctor.membership.user,
                actor_role="doctor",
                lab_results=[
                    {"analyte_id": str(analyte.id), "name": "Colesterol", "result": "250"}
                ],
                **_VALID_SECCIONES,
            )

        assert plan.lab_results[0]["out_of_range"] is True
        assert plan.lab_results[0]["analyte_id"] == str(analyte.id)
        # ref_high heredado del catálogo y normalizado para el snapshot/PDF
        # (el catálogo lo guarda como Decimal("200.0000"); _fmt_ref -> "200").
        assert plan.lab_results[0]["ref_high"] == "200"

    def test_lab_result_analyte_id_otro_tenant_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        other_tenant = TenantFactory()
        other_analyte = LabAnalyteFactory(tenant=other_tenant)

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError):
                longevity_plan_create(
                    tenant=tenant,
                    patient=patient,
                    actor=doctor.membership.user,
                    actor_role="doctor",
                    lab_results=[{"analyte_id": str(other_analyte.id), "name": "X", "result": "1"}],
                    **_VALID_SECCIONES,
                )

    def test_lab_result_analyte_id_inexistente_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, doctor = _setup()

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError):
                longevity_plan_create(
                    tenant=tenant,
                    patient=patient,
                    actor=doctor.membership.user,
                    actor_role="doctor",
                    lab_results=[{"analyte_id": str(uuid.uuid4()), "name": "X", "result": "1"}],
                    **_VALID_SECCIONES,
                )

    def test_sin_lab_results_ni_gabinete_quedan_listas_vacias(self, db: Any) -> None:
        tenant, patient, doctor = _setup()

        with tenant_ctx(tenant):
            plan = longevity_plan_create(
                tenant=tenant,
                patient=patient,
                actor=doctor.membership.user,
                actor_role="doctor",
                **_VALID_SECCIONES,
            )

        assert plan.lab_results == []
        assert plan.gabinete_studies == []
        assert plan.equipo == []


class TestLongevityPlanCreateEndpointLabGabinete:
    def test_201_crea_con_lab_results_y_gabinete_studies(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={
                    **_VALID_SECCIONES,
                    "lab_results": [
                        {
                            "name": "Glucosa",
                            "unit": "mg/dL",
                            "ref_low": "70",
                            "ref_high": "100",
                            "result": "180",
                        }
                    ],
                    "gabinete_studies": [{"name": "Rayos X", "conclusion": "Normal."}],
                },
                format="json",
            )

        assert resp.status_code == 201, resp.content
        plan = LongevityPlan.all_objects.get(id=resp.json()["id"])
        assert plan.lab_results[0]["out_of_range"] is True
        assert plan.gabinete_studies == [{"name": "Rayos X", "conclusion": "Normal."}]

    def test_400_lab_result_con_campo_no_declarado(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={
                    **_VALID_SECCIONES,
                    "lab_results": [{"name": "X", "result": "1", "campo_invalido": True}],
                },
                format="json",
            )

        assert resp.status_code == 400

    def test_400_cliente_no_puede_enviar_equipo(self, db: Any) -> None:
        """equipo no es un campo declarado del InputSerializer -> 400 (D-EC-7)."""
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={**_VALID_SECCIONES, "equipo": [{"departamento": "X", "nombre": "Y"}]},
                format="json",
            )

        assert resp.status_code == 400


class TestLongevityPlanDraftApiLabGabineteEquipo:
    def test_200_draft_incluye_equipo_lab_gabinete_vacios(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        ClinicTeamMemberFactory(tenant=tenant, departamento="Nutrición", nombre="Lic. Ruiz")
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.get(_DRAFT_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["lab_results"] == []
        assert body["gabinete_studies"] == []
        assert body["equipo"] == [{"departamento": "Nutrición", "nombre": "Lic. Ruiz"}]
