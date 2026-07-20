"""
Tests de la Calendarización de tratamientos (esquema de protocolos por
sesiones) — Fases 1 y 4.

Cubre (objetivo >= 80% en lógica de negocio):

1. treatment_plan_create (service):
   - genera sesiones 1..N cuando el item no trae `sessions`.
   - usa las sesiones enviadas tal cual cuando sí vienen (preserva fechas/estado).
   - snapshot de description/unit_price desde el ServiceConcept.
   - errores: sin items, doctor de otro tenant, rol no permitido.
   - audita TREATMENT_PLAN_SAVE.

2. treatment_plan_replace (service):
   - reemplaza items/sesiones completos, preservando lo que el cliente reenvíe.
   - Fase 4: reconciliación por `id` — preserva `appointment`/`applied_date` de lo
     que sobrevive; cancela la cita y borra lo que ya no viene (item o sesión).

3. treatment_plan_delete (service): baja lógica (excluido de listados/selector).

4. Selectors: aislamiento multi-tenant (404 DoesNotExist / lista vacía).

5. Endpoints HTTP:
   - listar (GET): 200 paginado, 403 por rol, 404 paciente inexistente.
   - crear (POST): 201, 400 sin items / campo desconocido, 403 por rol.
   - detalle (GET): 200, 404 IDOR, expone scheduled_time/duration_minutes/appointment.
   - reemplazar (PUT): 200, incluye marcar una sesión como aplicada.
   - eliminar (DELETE): 204, luego 404.
   - PDF (GET): 202 -> tarea -> 200 %PDF (kind "treatment_plan" registrado).

6. Fase 4 — agendar sesiones como citas reales (treatment_session_schedule /
   treatment_session_unschedule + TreatmentSessionScheduleApi):
   - agendar crea una cita real ligada.
   - agendar en un horario ocupado del mismo doctor -> 400 (empalme,
     reutilizando appointment_create).
   - reagendar con el MISMO doctor mueve la MISMA cita (appointment_reschedule).
   - reagendar con OTRO doctor cancela la cita vieja y crea una nueva.
   - quitar de agenda cancela la cita y limpia el FK; idempotente sin cita.
   - doctor_id obligatorio; permisos (recepción/finanzas 403).
   - 404 IDOR con sesión de otro tenant.

7. RLS: cubierto por el test guardián apps/core/tests/test_rls_coverage.py
   (descubre automáticamente las tablas nuevas vía TenantAwareModel).

Patrón: AAA. factory_boy para datos. Tenant context parcheado igual que el
resto de la app expediente (ver conftest.py).
"""

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.agenda.models import Appointment
from apps.audit.models import ActionType, AuditLog
from apps.expediente.models import (
    TreatmentPlan,
    TreatmentPlanItem,
    TreatmentPlanStatus,
    TreatmentSession,
    TreatmentSessionStatus,
)
from apps.expediente.selectors import treatment_plan_get, treatment_plan_list
from apps.expediente.services_calendarizacion import (
    treatment_plan_create,
    treatment_plan_delete,
    treatment_plan_replace,
    treatment_session_schedule,
    treatment_session_unschedule,
)
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    ConsultorioFactory,
    DoctorFactory,
    MembershipSucursalFactory,
    PatientFactory,
    ServiceConceptFactory,
    SucursalFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_LIST_CREATE_URL_TMPL = "/api/v1/expediente/{patient_id}/calendarizaciones/"
_DETAIL_URL_TMPL = "/api/v1/expediente/calendarizaciones/{plan_id}/"
_PDF_URL_TMPL = "/api/v1/expediente/calendarizaciones/{plan_id}/pdf/"
_SCHEDULE_URL_TMPL = "/api/v1/expediente/calendarizaciones/sesiones/{session_id}/agendar/"


def _member(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> Any:
    """Crea user con membresía activa en el tenant."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _setup(tenant: Any = None) -> tuple[Any, Any, Any]:
    """Crea tenant/paciente/doctor consistentes (mismo tenant)."""
    tenant = tenant or TenantFactory()
    doctor = DoctorFactory(tenant=tenant)
    patient = PatientFactory(tenant=tenant)
    return tenant, patient, doctor


_SIMPLE_ITEM: dict[str, Any] = {
    "description": "Limpieza facial profunda",
    "unit_price": "500.00",
    "quantity": 3,
}


# ---------------------------------------------------------------------------
# 1. treatment_plan_create — service
# ---------------------------------------------------------------------------


class TestTreatmentPlanCreate:
    def test_genera_sesiones_1_a_n_cuando_no_vienen(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )

        assert plan.title == "Esquema y aplicación de protocolos de tratamientos"
        assert plan.items.count() == 1
        item = plan.items.first()
        assert item.quantity == 3
        sessions = list(item.sessions.order_by("number"))
        assert [s.number for s in sessions] == [1, 2, 3]
        assert all(s.status == TreatmentSessionStatus.PROGRAMADA for s in sessions)
        assert all(s.scheduled_date is None for s in sessions)

    def test_usa_sesiones_enviadas_preservando_fechas_y_estado(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        item_payload = {
            **_SIMPLE_ITEM,
            "quantity": 2,
            "sessions": [
                {
                    "number": 1,
                    "scheduled_date": "2026-08-01",
                    "applied_date": "2026-08-01",
                    "status": "aplicada",
                },
                {"number": 2, "scheduled_date": "2026-08-15"},
            ],
        }

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="Mi esquema",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[item_payload],
                actor_role="owner",
            )

        item = plan.items.first()
        sessions = list(item.sessions.order_by("number"))
        assert sessions[0].status == TreatmentSessionStatus.APLICADA
        assert sessions[0].scheduled_date == datetime.date(2026, 8, 1)
        assert sessions[0].applied_date == datetime.date(2026, 8, 1)
        assert sessions[1].status == TreatmentSessionStatus.PROGRAMADA
        assert sessions[1].scheduled_date == datetime.date(2026, 8, 15)
        assert sessions[1].applied_date is None

    def test_snapshot_de_concepto_cuando_no_hay_description_ni_precio(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user
        concept = ServiceConceptFactory(tenant=tenant, name="Bótox", base_price=Decimal("1200.00"))

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[{"concept_id": str(concept.id), "quantity": 1}],
                actor_role="doctor",
            )

        item = plan.items.first()
        assert item.description == "Bótox"
        assert item.unit_price == Decimal("1200.00")
        assert item.service_concept_id == concept.id

    def test_concepto_de_otro_tenant_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user
        other_tenant, _, _ = _setup()
        foreign_concept = ServiceConceptFactory(tenant=other_tenant)

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError):
                treatment_plan_create(
                    patient=patient,
                    actor=actor,
                    title="",
                    notes="",
                    status=TreatmentPlanStatus.ACTIVA,
                    items=[{"concept_id": str(foreign_concept.id), "quantity": 1}],
                    actor_role="doctor",
                )

    def test_concepto_desactivado_lanza_validation_error(self, db: Any) -> None:
        """FIX 3: un concepto desactivado no puede usarse en un tratamiento nuevo."""
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user
        inactive_concept = ServiceConceptFactory(tenant=tenant, is_active=False)

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError, match="está desactivado"):
                treatment_plan_create(
                    patient=patient,
                    actor=actor,
                    title="",
                    notes="",
                    status=TreatmentPlanStatus.ACTIVA,
                    items=[{"concept_id": str(inactive_concept.id), "quantity": 1}],
                    actor_role="doctor",
                )

    def test_sin_items_crea_borrador_vacio(self, db: Any) -> None:
        """Un esquema puede crearse vacío (contenedor/borrador)."""
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[],
                actor_role="doctor",
            )

        assert plan.items.count() == 0

    def test_doctor_de_otro_tenant_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, _ = _setup()
        other_tenant, _, other_doctor = _setup()

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError):
                treatment_plan_create(
                    patient=patient,
                    actor=UserFactory(),
                    title="",
                    notes="",
                    status=TreatmentPlanStatus.ACTIVA,
                    items=[dict(_SIMPLE_ITEM)],
                    doctor=other_doctor,
                    actor_role="owner",
                )

    def test_rol_no_permitido_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, _ = _setup()

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError):
                treatment_plan_create(
                    patient=patient,
                    actor=UserFactory(),
                    title="",
                    notes="",
                    status=TreatmentPlanStatus.ACTIVA,
                    items=[dict(_SIMPLE_ITEM)],
                    actor_role="reception",
                )

    def test_audita_treatment_plan_save(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )

        log = AuditLog.all_objects.filter(
            action=ActionType.TREATMENT_PLAN_SAVE, resource_id=plan.id
        ).first()
        assert log is not None
        assert log.resource_repr == str(plan.id)
        assert log.metadata.get("items") == 1


# ---------------------------------------------------------------------------
# 2. treatment_plan_replace — service
# ---------------------------------------------------------------------------


class TestTreatmentPlanReplace:
    def test_reemplaza_items_y_sesiones(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )
            old_item_id = plan.items.first().id

            plan = treatment_plan_replace(
                plan=plan,
                actor=actor,
                title="Actualizado",
                notes="notas nuevas",
                status=TreatmentPlanStatus.COMPLETADA,
                items=[{"description": "Otro tratamiento", "unit_price": "300.00", "quantity": 2}],
                actor_role="doctor",
            )

        assert plan.title == "Actualizado"
        assert plan.status == TreatmentPlanStatus.COMPLETADA
        assert plan.items.count() == 1
        assert plan.items.first().id != old_item_id
        assert not TreatmentSession.all_objects.filter(item_id=old_item_id).exists()

    def test_preserva_fechas_de_sesiones_reenviadas(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[{**_SIMPLE_ITEM, "quantity": 1}],
                actor_role="doctor",
            )

            plan = treatment_plan_replace(
                plan=plan,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[
                    {
                        **_SIMPLE_ITEM,
                        "quantity": 1,
                        "sessions": [
                            {
                                "number": 1,
                                "scheduled_date": "2026-09-01",
                                "applied_date": "2026-09-01",
                                "status": "aplicada",
                            }
                        ],
                    }
                ],
                actor_role="doctor",
            )

        session = plan.items.first().sessions.first()
        assert session.status == TreatmentSessionStatus.APLICADA
        assert session.applied_date == datetime.date(2026, 9, 1)

    def test_replace_con_items_vacios_deja_esquema_vacio(self, db: Any) -> None:
        """Reemplazar con items=[] vacía el esquema (borrador), sin error."""
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )
            plan = treatment_plan_replace(
                plan=plan,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[],
                actor_role="doctor",
            )

        assert plan.items.count() == 0


# ---------------------------------------------------------------------------
# 3. treatment_plan_delete — service
# ---------------------------------------------------------------------------


class TestTreatmentPlanDelete:
    def test_baja_logica_excluye_de_selectors(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )
            treatment_plan_delete(plan=plan, actor=actor, actor_role="doctor")

            with pytest.raises(TreatmentPlan.DoesNotExist):
                treatment_plan_get(plan_id=plan.id)
            assert list(treatment_plan_list(patient=patient)) == []

        assert TreatmentPlan.all_objects.get(id=plan.id).deleted_at is not None


# ---------------------------------------------------------------------------
# 4. Selectors — aislamiento multi-tenant
# ---------------------------------------------------------------------------


class TestTreatmentPlanSelectors:
    def test_treatment_plan_get_404_otro_tenant(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )

        other_tenant, _, _ = _setup()
        with tenant_ctx(other_tenant):
            with pytest.raises(TreatmentPlan.DoesNotExist):
                treatment_plan_get(plan_id=plan.id)

    def test_treatment_plan_list_aislamiento_multi_tenant(self, db: Any) -> None:
        tenant1, patient1, doctor1 = _setup()
        tenant2, patient2, doctor2 = _setup()

        with tenant_ctx(tenant1):
            treatment_plan_create(
                patient=patient1,
                actor=doctor1.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )
        with tenant_ctx(tenant2):
            treatment_plan_create(
                patient=patient2,
                actor=doctor2.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )

        with tenant_ctx(tenant1):
            results = list(treatment_plan_list(patient=patient1))

        assert len(results) == 1
        assert results[0].tenant_id == tenant1.id


# ---------------------------------------------------------------------------
# 5a. Endpoint: listar/crear
# ---------------------------------------------------------------------------


class TestTreatmentPlanListCreateApi:
    def test_201_crea_y_calcula_total(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        payload = {
            "title": "Esquema de tratamiento facial",
            "notes": "",
            "status": "activa",
            "items": [
                {"description": "Sesión láser", "unit_price": "800.00", "quantity": 2},
            ],
        }

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id), data=payload, format="json"
            )

        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["title"] == "Esquema de tratamiento facial"
        assert body["total"] == "1600.00"
        assert len(body["items"][0]["sessions"]) == 2

    def test_201_sin_items_crea_borrador_vacio(self, db: Any) -> None:
        """El esquema se puede crear vacío (contenedor/borrador): 201 con items []."""
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={"items": []},
                format="json",
            )

        assert resp.status_code == 201
        assert resp.json()["items"] == []

    def test_201_sin_body_crea_borrador_vacio(self, db: Any) -> None:
        """POST sin `items` en el body también crea un borrador vacío."""
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={},
                format="json",
            )

        assert resp.status_code == 201
        assert resp.json()["items"] == []

    def test_400_campo_no_declarado(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={"items": [dict(_SIMPLE_ITEM)], "campo_invalido": "x"},
                format="json",
            )

        assert resp.status_code == 400

    def test_403_recepcion_no_puede_crear(self, db: Any) -> None:
        tenant, patient, _ = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={"items": [dict(_SIMPLE_ITEM)]},
                format="json",
            )

        assert resp.status_code == 403

    def test_403_finanzas_no_puede_crear(self, db: Any) -> None:
        tenant, patient, _ = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.FINANCE))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={"items": [dict(_SIMPLE_ITEM)]},
                format="json",
            )

        assert resp.status_code == 403

    def test_403_enfermeria_no_puede_crear(self, db: Any) -> None:
        tenant, patient, _ = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.NURSE))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=patient.id),
                data={"items": [dict(_SIMPLE_ITEM)]},
                format="json",
            )

        assert resp.status_code == 403

    def test_404_paciente_inexistente(self, db: Any) -> None:
        tenant, _, doctor = _setup()
        client = _auth_client(doctor.membership.user)
        other_tenant, other_patient, _ = _setup()

        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL_TMPL.format(patient_id=other_patient.id),
                data={"items": [dict(_SIMPLE_ITEM)]},
                format="json",
            )

        assert resp.status_code == 404

    def test_200_lista_paginada(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )

        client = _auth_client(doctor.membership.user)
        with api_tenant_ctx(tenant):
            resp = client.get(_LIST_CREATE_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["count"] == 1
        item = body["results"][0]
        assert item["sessions_count"] == 3
        assert item["applied_count"] == 0
        assert item["total"] == "1500.00"

    def test_403_readonly_no_puede_listar(self, db: Any) -> None:
        tenant, patient, _ = _setup()
        client = _auth_client(_member(tenant, TenantMembership.Role.READONLY))

        with api_tenant_ctx(tenant):
            resp = client.get(_LIST_CREATE_URL_TMPL.format(patient_id=patient.id))

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 5b. Endpoint: detalle / reemplazar / eliminar
# ---------------------------------------------------------------------------


class TestTreatmentPlanDetailApi:
    def _create(self, tenant: Any, patient: Any, doctor: Any) -> Any:
        with tenant_ctx(tenant):
            return treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                actor_role="doctor",
            )

    def test_200_detalle(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create(tenant, patient, doctor)
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.get(_DETAIL_URL_TMPL.format(plan_id=plan.id))

        assert resp.status_code == 200, resp.content
        assert resp.json()["id"] == str(plan.id)

    def test_404_idor_otro_tenant(self, db: Any) -> None:
        tenant1, patient1, doctor1 = _setup()
        plan = self._create(tenant1, patient1, doctor1)
        tenant2, _, doctor2 = _setup()
        client = _auth_client(doctor2.membership.user)

        with api_tenant_ctx(tenant2):
            resp = client.get(_DETAIL_URL_TMPL.format(plan_id=plan.id))

        assert resp.status_code == 404

    def test_put_reemplaza_y_marca_sesion_aplicada(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create(tenant, patient, doctor)
        client = _auth_client(doctor.membership.user)

        payload = {
            "title": "Esquema revisado",
            "notes": "",
            "status": "activa",
            "items": [
                {
                    "description": _SIMPLE_ITEM["description"],
                    "unit_price": _SIMPLE_ITEM["unit_price"],
                    "quantity": 3,
                    "sessions": [
                        {
                            "number": 1,
                            "scheduled_date": "2026-08-01",
                            "applied_date": "2026-08-01",
                            "status": "aplicada",
                        },
                        {"number": 2, "scheduled_date": "2026-08-15", "status": "programada"},
                        {"number": 3, "scheduled_date": "2026-08-29", "status": "programada"},
                    ],
                }
            ],
        }

        with api_tenant_ctx(tenant):
            resp = client.put(_DETAIL_URL_TMPL.format(plan_id=plan.id), data=payload, format="json")

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["title"] == "Esquema revisado"
        sessions = body["items"][0]["sessions"]
        assert sessions[0]["status"] == "aplicada"
        assert sessions[0]["applied_date"] == "2026-08-01"

    def test_delete_204_y_luego_404(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create(tenant, patient, doctor)
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.delete(_DETAIL_URL_TMPL.format(plan_id=plan.id))
        assert resp.status_code == 204

        with api_tenant_ctx(tenant):
            resp = client.get(_DETAIL_URL_TMPL.format(plan_id=plan.id))
        assert resp.status_code == 404

    def test_403_finanzas_no_puede_ver_detalle(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create(tenant, patient, doctor)
        client = _auth_client(_member(tenant, TenantMembership.Role.FINANCE))

        with api_tenant_ctx(tenant):
            resp = client.get(_DETAIL_URL_TMPL.format(plan_id=plan.id))

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 5c. Endpoint: PDF
# ---------------------------------------------------------------------------


class TestTreatmentPlanPdfApi:
    def _create(self, tenant: Any, patient: Any, doctor: Any) -> Any:
        with tenant_ctx(tenant):
            return treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )

    def test_kind_treatment_plan_registrado(self) -> None:
        from apps.pdfs.registry import get_pdf_kind

        spec = get_pdf_kind("treatment_plan")
        assert spec.builder is not None
        assert spec.permission is not None

    def test_202_encola_y_luego_descarga_pdf(self, db: Any) -> None:
        from apps.pdfs.tasks import generate_pdf

        tenant, patient, doctor = _setup()
        plan = self._create(tenant, patient, doctor)
        client = _auth_client(doctor.membership.user)

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

    def test_403_enfermeria_no_puede_pedir_pdf(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create(tenant, patient, doctor)
        client = _auth_client(_member(tenant, TenantMembership.Role.NURSE))

        with api_tenant_ctx(tenant):
            resp = client.get(_PDF_URL_TMPL.format(plan_id=plan.id))

        assert resp.status_code == 403

    def test_404_idor_otro_tenant(self, db: Any) -> None:
        tenant1, patient1, doctor1 = _setup()
        plan = self._create(tenant1, patient1, doctor1)
        tenant2, _, doctor2 = _setup()
        client = _auth_client(doctor2.membership.user)

        with api_tenant_ctx(tenant2):
            resp = client.get(_PDF_URL_TMPL.format(plan_id=plan.id))

        assert resp.status_code == 404

    def test_202_con_sesion_agendada_incluye_hora(self, db: Any) -> None:
        """Una sesión con scheduled_time no rompe la generación del PDF (Fase 4)."""
        from apps.pdfs.tasks import generate_pdf

        tenant, patient, doctor = _setup()
        plan = self._create(tenant, patient, doctor)
        actor = doctor.membership.user
        client = _auth_client(actor)

        with tenant_ctx(tenant):
            session = plan.items.first().sessions.first()
            treatment_session_schedule(
                session=session,
                actor=actor,
                actor_role="doctor",
                doctor_id=doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )

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
        assert file_resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 6. Fase 4 — treatment_plan_replace: reconciliación por `id`
# ---------------------------------------------------------------------------


class TestTreatmentPlanReplaceReconciliationById:
    def _schedule(self, session: Any, actor: Any, doctor: Any) -> Any:
        return treatment_session_schedule(
            session=session,
            actor=actor,
            actor_role="doctor",
            doctor_id=doctor.id,
            consultorio_id=None,
            starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
            ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
            scheduled_date=datetime.date(2026, 8, 1),
            scheduled_time=datetime.time(10, 0),
            duration_minutes=30,
        )

    def test_preserva_appointment_y_id_de_sesion_que_sobrevive(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[{**_SIMPLE_ITEM, "quantity": 1}],
                doctor=doctor,
                actor_role="doctor",
            )
            item = plan.items.first()
            session = item.sessions.first()
            session = self._schedule(session, actor, doctor)
            appointment_id = session.appointment_id
            assert appointment_id is not None

            plan = treatment_plan_replace(
                plan=plan,
                actor=actor,
                title="Actualizado",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[
                    {
                        "id": str(item.id),
                        **_SIMPLE_ITEM,
                        "quantity": 1,
                        "sessions": [{"id": str(session.id), "number": 1}],
                    }
                ],
                doctor=doctor,
                actor_role="doctor",
            )

        assert plan.items.first().id == item.id
        updated_session = plan.items.first().sessions.first()
        assert updated_session.id == session.id
        assert updated_session.appointment_id == appointment_id
        # FIX 2: el payload solo trae {id, number} — scheduled_date/time/
        # duration_minutes NO vienen, así que deben sobrevivir intactos
        # (antes se pisaban con None por falta de guard "if key in raw_session").
        assert updated_session.scheduled_date == datetime.date(2026, 8, 1)
        assert updated_session.scheduled_time == datetime.time(10, 0)
        assert updated_session.duration_minutes == 30
        appt = Appointment.objects.get(id=appointment_id)
        assert appt.status == Appointment.Status.SCHEDULED

    def test_sesion_que_ya_no_viene_cancela_su_cita_y_se_borra(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[{**_SIMPLE_ITEM, "quantity": 2}],
                doctor=doctor,
                actor_role="doctor",
            )
            item = plan.items.first()
            sessions = list(item.sessions.order_by("number"))
            scheduled_session = self._schedule(sessions[0], actor, doctor)
            appointment_id = scheduled_session.appointment_id
            keep_session_id = sessions[1].id

            plan = treatment_plan_replace(
                plan=plan,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[
                    {
                        "id": str(item.id),
                        **_SIMPLE_ITEM,
                        "quantity": 2,
                        "sessions": [{"id": str(keep_session_id), "number": 1}],
                    }
                ],
                doctor=doctor,
                actor_role="doctor",
            )

        assert not TreatmentSession.all_objects.filter(id=scheduled_session.id).exists()
        assert plan.items.first().sessions.count() == 1
        appt = Appointment.objects.get(id=appointment_id)
        assert appt.status == Appointment.Status.CANCELLED

    def test_item_que_ya_no_viene_cancela_citas_de_sus_sesiones_y_agrega_uno_nuevo(
        self, db: Any
    ) -> None:
        tenant, patient, doctor = _setup()
        actor = doctor.membership.user

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[{**_SIMPLE_ITEM, "quantity": 1}],
                doctor=doctor,
                actor_role="doctor",
            )
            item = plan.items.first()
            session = item.sessions.first()
            session = self._schedule(session, actor, doctor)
            appointment_id = session.appointment_id

            plan = treatment_plan_replace(
                plan=plan,
                actor=actor,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[
                    {"description": "Otro tratamiento nuevo", "unit_price": "100.00", "quantity": 1}
                ],
                doctor=doctor,
                actor_role="doctor",
            )

        assert not TreatmentPlanItem.all_objects.filter(id=item.id).exists()
        appt = Appointment.objects.get(id=appointment_id)
        assert appt.status == Appointment.Status.CANCELLED
        assert plan.items.count() == 1
        assert plan.items.first().description == "Otro tratamiento nuevo"


# ---------------------------------------------------------------------------
# 7a. Fase 4 — treatment_session_schedule / treatment_session_unschedule (service)
# ---------------------------------------------------------------------------


class TestTreatmentSessionScheduleService:
    def _create_plan(self, tenant: Any, patient: Any, doctor: Any, quantity: int = 1) -> Any:
        with tenant_ctx(tenant):
            return treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[{**_SIMPLE_ITEM, "quantity": quantity}],
                doctor=doctor,
                actor_role="doctor",
            )

    def test_agenda_crea_cita_real_ligada(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)

        with tenant_ctx(tenant):
            session = plan.items.first().sessions.first()
            session = treatment_session_schedule(
                session=session,
                actor=doctor.membership.user,
                actor_role="doctor",
                doctor_id=doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )

        assert session.appointment_id is not None
        appt = Appointment.objects.get(id=session.appointment_id)
        assert appt.patient_id == patient.id
        assert appt.doctor_id == doctor.id
        assert appt.status == Appointment.Status.SCHEDULED
        assert appt.reason == _SIMPLE_ITEM["description"]

    def test_agendar_choque_de_horario_propaga_validation_error(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor, quantity=2)

        with tenant_ctx(tenant):
            sessions = list(plan.items.first().sessions.order_by("number"))
            treatment_session_schedule(
                session=sessions[0],
                actor=doctor.membership.user,
                actor_role="doctor",
                doctor_id=doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )

            with pytest.raises(DjangoValidationError):
                treatment_session_schedule(
                    session=sessions[1],
                    actor=doctor.membership.user,
                    actor_role="doctor",
                    doctor_id=doctor.id,
                    consultorio_id=None,
                    starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                    ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                    scheduled_date=datetime.date(2026, 8, 1),
                    scheduled_time=datetime.time(10, 0),
                    duration_minutes=30,
                )

    def test_reagendar_mismo_doctor_mueve_la_misma_cita(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)

        with tenant_ctx(tenant):
            session = plan.items.first().sessions.first()
            session = treatment_session_schedule(
                session=session,
                actor=doctor.membership.user,
                actor_role="doctor",
                doctor_id=doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )
            first_appointment_id = session.appointment_id

            session = treatment_session_schedule(
                session=session,
                actor=doctor.membership.user,
                actor_role="doctor",
                doctor_id=doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 2, 17, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 2, 17, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 2),
                scheduled_time=datetime.time(11, 0),
                duration_minutes=30,
            )

        assert session.appointment_id == first_appointment_id
        assert Appointment.objects.filter(tenant_id=tenant.id).count() == 1
        appt = Appointment.objects.get(id=first_appointment_id)
        assert appt.starts_at == datetime.datetime(2026, 8, 2, 17, 0, tzinfo=datetime.UTC)

    def test_reagendar_otro_doctor_cancela_la_vieja_y_crea_una_nueva(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        other_doctor = DoctorFactory(tenant=tenant)
        plan = self._create_plan(tenant, patient, doctor)
        # La regla "un doctor solo agenda para sí mismo" (apps.agenda.services)
        # bloquearía al propio doctor reasignando a otro médico: quien
        # reasigna aquí es un owner (sin esa restricción).
        owner_user = _member(tenant, TenantMembership.Role.OWNER)

        with tenant_ctx(tenant):
            session = plan.items.first().sessions.first()
            session = treatment_session_schedule(
                session=session,
                actor=doctor.membership.user,
                actor_role="doctor",
                doctor_id=doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )
            first_appointment_id = session.appointment_id

            session = treatment_session_schedule(
                session=session,
                actor=owner_user,
                actor_role="owner",
                doctor_id=other_doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 18, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 18, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(12, 0),
                duration_minutes=30,
            )

        assert session.appointment_id != first_appointment_id
        old_appt = Appointment.objects.get(id=first_appointment_id)
        assert old_appt.status == Appointment.Status.CANCELLED
        new_appt = Appointment.objects.get(id=session.appointment_id)
        assert new_appt.doctor_id == other_doctor.id
        assert new_appt.status == Appointment.Status.SCHEDULED

    def test_falta_doctor_id_lanza_validation_error(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)

        with tenant_ctx(tenant):
            session = plan.items.first().sessions.first()
            with pytest.raises(DjangoValidationError):
                treatment_session_schedule(
                    session=session,
                    actor=doctor.membership.user,
                    actor_role="doctor",
                    doctor_id=None,
                    consultorio_id=None,
                    starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                    ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                    scheduled_date=datetime.date(2026, 8, 1),
                    scheduled_time=datetime.time(10, 0),
                    duration_minutes=30,
                )

    def test_unschedule_cancela_cita_y_limpia_fk(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)

        with tenant_ctx(tenant):
            session = plan.items.first().sessions.first()
            session = treatment_session_schedule(
                session=session,
                actor=doctor.membership.user,
                actor_role="doctor",
                doctor_id=doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )
            appointment_id = session.appointment_id

            session = treatment_session_unschedule(
                session=session, actor=doctor.membership.user, actor_role="doctor"
            )

        assert session.appointment_id is None
        appt = Appointment.objects.get(id=appointment_id)
        assert appt.status == Appointment.Status.CANCELLED

    def test_unschedule_es_idempotente_sin_cita(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)

        with tenant_ctx(tenant):
            session = plan.items.first().sessions.first()
            session = treatment_session_unschedule(
                session=session, actor=doctor.membership.user, actor_role="doctor"
            )

        assert session.appointment_id is None


# ---------------------------------------------------------------------------
# 7a-bis. FIX 1 — atomicidad de treatment_session_schedule (rama cancelar+crear)
# ---------------------------------------------------------------------------


class TestTreatmentSessionScheduleAtomicity:
    """FIX 1 (bloqueante): si la rama 'otro doctor' cancela la cita vieja y la
    creación de la nueva falla (empalme), TODO debe revertirse — la sesión no
    puede quedar apuntando a una cita CANCELLED sin haber logrado agendar la
    nueva.
    """

    def _create_plan(self, tenant: Any, patient: Any, doctor: Any) -> Any:
        with tenant_ctx(tenant):
            return treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )

    def test_reasignar_a_otro_doctor_con_choque_no_deja_huerfana_la_sesion(self, db: Any) -> None:
        from apps.agenda.services import appointment_create as agenda_appointment_create

        tenant, patient, doctor_a = _setup()
        doctor_b = DoctorFactory(tenant=tenant)
        owner_user = _member(tenant, TenantMembership.Role.OWNER)
        plan = self._create_plan(tenant, patient, doctor_a)

        with tenant_ctx(tenant):
            session = plan.items.first().sessions.first()
            session = treatment_session_schedule(
                session=session,
                actor=doctor_a.membership.user,
                actor_role="doctor",
                doctor_id=doctor_a.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )
            original_appointment_id = session.appointment_id
            assert original_appointment_id is not None

            # doctor_b ya tiene una cita justo en el horario al que se
            # intentará reasignar la sesión -> appointment_create chocará.
            other_patient = PatientFactory(tenant=tenant)
            agenda_appointment_create(
                tenant=tenant,
                user=owner_user,
                patient_id=other_patient.id,
                doctor_id=doctor_b.id,
                starts_at=datetime.datetime(2026, 8, 1, 18, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 18, 30, tzinfo=datetime.UTC),
                reason="Cita que ocupa el horario",
            )

            with pytest.raises(DjangoValidationError):
                treatment_session_schedule(
                    session=session,
                    actor=owner_user,
                    actor_role="owner",
                    doctor_id=doctor_b.id,
                    consultorio_id=None,
                    starts_at=datetime.datetime(2026, 8, 1, 18, 0, tzinfo=datetime.UTC),
                    ends_at=datetime.datetime(2026, 8, 1, 18, 30, tzinfo=datetime.UTC),
                    scheduled_date=datetime.date(2026, 8, 1),
                    scheduled_time=datetime.time(12, 0),
                    duration_minutes=30,
                )

            session.refresh_from_db()
            assert session.appointment_id == original_appointment_id

            original_appointment = Appointment.objects.get(id=original_appointment_id)
            assert original_appointment.status == Appointment.Status.SCHEDULED


# ---------------------------------------------------------------------------
# 7a-ter. FIX 5 — un doctor solo cancela/mueve SUS propias citas
# ---------------------------------------------------------------------------


class TestTreatmentSessionOwnershipGuard:
    """FIX 5 (seguridad): con actor_role='doctor', _cancel_session_appointment_if_any
    exige que la cita a cancelar sea del PROPIO médico. owner/admin no tienen
    esta restricción.
    """

    def _schedule_for_doctor(
        self, tenant: Any, patient: Any, doctor: Any, scheduling_actor: Any, scheduling_role: str
    ) -> Any:
        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM)],
                doctor=doctor,
                actor_role="doctor",
            )
            session = plan.items.first().sessions.first()
            return treatment_session_schedule(
                session=session,
                actor=scheduling_actor,
                actor_role=scheduling_role,
                doctor_id=doctor.id,
                consultorio_id=None,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )

    def test_doctor_no_puede_desagendar_cita_de_otro_medico(self, db: Any) -> None:
        tenant, patient, doctor_a = _setup()
        doctor_b = DoctorFactory(tenant=tenant)
        session = self._schedule_for_doctor(
            tenant, patient, doctor_a, doctor_a.membership.user, "doctor"
        )

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError, match="solo puedes cancelar"):
                treatment_session_unschedule(
                    session=session, actor=doctor_b.membership.user, actor_role="doctor"
                )

            session.refresh_from_db()
            assert session.appointment_id is not None
            appt = Appointment.objects.get(id=session.appointment_id)
            assert appt.status == Appointment.Status.SCHEDULED

    def test_doctor_puede_desagendar_su_propia_cita(self, db: Any) -> None:
        tenant, patient, doctor_a = _setup()
        session = self._schedule_for_doctor(
            tenant, patient, doctor_a, doctor_a.membership.user, "doctor"
        )

        with tenant_ctx(tenant):
            session = treatment_session_unschedule(
                session=session, actor=doctor_a.membership.user, actor_role="doctor"
            )

        assert session.appointment_id is None

    def test_owner_puede_desagendar_cita_de_cualquier_medico(self, db: Any) -> None:
        tenant, patient, doctor_a = _setup()
        owner_user = _member(tenant, TenantMembership.Role.OWNER)
        session = self._schedule_for_doctor(
            tenant, patient, doctor_a, doctor_a.membership.user, "doctor"
        )

        with tenant_ctx(tenant):
            session = treatment_session_unschedule(
                session=session, actor=owner_user, actor_role="owner"
            )

        assert session.appointment_id is None

    def test_admin_puede_desagendar_cita_de_cualquier_medico(self, db: Any) -> None:
        tenant, patient, doctor_a = _setup()
        admin_user = _member(tenant, TenantMembership.Role.ADMIN)
        session = self._schedule_for_doctor(
            tenant, patient, doctor_a, doctor_a.membership.user, "doctor"
        )

        with tenant_ctx(tenant):
            session = treatment_session_unschedule(
                session=session, actor=admin_user, actor_role="admin"
            )

        assert session.appointment_id is None

    def test_doctor_no_puede_reasignar_a_si_mismo_la_cita_de_otro_medico(self, db: Any) -> None:
        """Cubre la cancelación implícita de la rama 'otro doctor' de schedule."""
        tenant, patient, doctor_a = _setup()
        doctor_b = DoctorFactory(tenant=tenant)
        session = self._schedule_for_doctor(
            tenant, patient, doctor_a, doctor_a.membership.user, "doctor"
        )
        original_appointment_id = session.appointment_id

        with tenant_ctx(tenant):
            with pytest.raises(DjangoValidationError, match="solo puedes cancelar"):
                treatment_session_schedule(
                    session=session,
                    actor=doctor_b.membership.user,
                    actor_role="doctor",
                    doctor_id=doctor_b.id,
                    consultorio_id=None,
                    starts_at=datetime.datetime(2026, 8, 5, 16, 0, tzinfo=datetime.UTC),
                    ends_at=datetime.datetime(2026, 8, 5, 16, 30, tzinfo=datetime.UTC),
                    scheduled_date=datetime.date(2026, 8, 5),
                    scheduled_time=datetime.time(10, 0),
                    duration_minutes=30,
                )

            session.refresh_from_db()
            assert session.appointment_id == original_appointment_id
            appt = Appointment.objects.get(id=original_appointment_id)
            assert appt.status == Appointment.Status.SCHEDULED


# ---------------------------------------------------------------------------
# 7b. Fase 4 — TreatmentSessionScheduleApi (endpoint)
# ---------------------------------------------------------------------------


def _schedule_payload(doctor_id: Any, **overrides: Any) -> dict[str, Any]:
    payload = {
        "scheduled_date": "2026-08-01",
        "scheduled_time": "10:00:00",
        "starts_at": "2026-08-01T16:00:00Z",
        "ends_at": "2026-08-01T16:30:00Z",
        "duration_minutes": 30,
        "doctor_id": str(doctor_id),
    }
    payload.update(overrides)
    return payload


class TestTreatmentSessionScheduleApi:
    def _create_plan(self, tenant: Any, patient: Any, doctor: Any, quantity: int = 1) -> Any:
        with tenant_ctx(tenant):
            return treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[{**_SIMPLE_ITEM, "quantity": quantity}],
                doctor=doctor,
                actor_role="doctor",
            )

    def test_200_agenda_crea_cita_ligada(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id),
                format="json",
            )

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["scheduled_time"] == "10:00:00"
        assert body["duration_minutes"] == 30
        assert body["appointment"] is not None
        assert body["appointment"]["doctor_id"] == str(doctor.id)
        assert body["appointment"]["status"] == "scheduled"

        appt = Appointment.objects.get(id=body["appointment"]["id"])
        assert appt.patient_id == patient.id

    def test_400_empalme_mismo_doctor(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor, quantity=2)
        sessions = list(plan.items.first().sessions.order_by("number"))
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp1 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=sessions[0].id),
                data=_schedule_payload(doctor.id),
                format="json",
            )
        assert resp1.status_code == 200, resp1.content

        with api_tenant_ctx(tenant):
            resp2 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=sessions[1].id),
                data=_schedule_payload(doctor.id),
                format="json",
            )
        assert resp2.status_code == 400, resp2.content
        assert "detail" in resp2.json()

    def test_200_reagendar_mismo_doctor_actualiza_la_misma_cita(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp1 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id),
                format="json",
            )
        first_appointment_id = resp1.json()["appointment"]["id"]

        with api_tenant_ctx(tenant):
            resp2 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(
                    doctor.id,
                    scheduled_date="2026-08-02",
                    scheduled_time="11:00:00",
                    starts_at="2026-08-02T17:00:00Z",
                    ends_at="2026-08-02T17:30:00Z",
                ),
                format="json",
            )

        assert resp2.status_code == 200, resp2.content
        assert resp2.json()["appointment"]["id"] == first_appointment_id
        assert Appointment.objects.filter(tenant_id=tenant.id).count() == 1

    def test_200_quitar_de_agenda_cancela_y_limpia_fk(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            resp1 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id),
                format="json",
            )
        appointment_id = resp1.json()["appointment"]["id"]

        with api_tenant_ctx(tenant):
            resp2 = client.delete(_SCHEDULE_URL_TMPL.format(session_id=session.id))

        assert resp2.status_code == 200, resp2.content
        assert resp2.json()["appointment"] is None
        appt = Appointment.objects.get(id=appointment_id)
        assert appt.status == Appointment.Status.CANCELLED

    def test_400_falta_doctor_id(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()
        client = _auth_client(doctor.membership.user)

        payload = _schedule_payload(doctor.id)
        del payload["doctor_id"]

        with api_tenant_ctx(tenant):
            resp = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id), data=payload, format="json"
            )

        assert resp.status_code == 400

    def test_403_recepcion_no_puede_agendar(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()
        client = _auth_client(_member(tenant, TenantMembership.Role.RECEPTION))

        with api_tenant_ctx(tenant):
            resp = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id),
                format="json",
            )

        assert resp.status_code == 403

    def test_403_finanzas_no_puede_quitar_de_agenda(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()
        client = _auth_client(_member(tenant, TenantMembership.Role.FINANCE))

        with api_tenant_ctx(tenant):
            resp = client.delete(_SCHEDULE_URL_TMPL.format(session_id=session.id))

        assert resp.status_code == 403

    def test_404_idor_sesion_de_otro_tenant(self, db: Any) -> None:
        tenant1, patient1, doctor1 = _setup()
        plan = self._create_plan(tenant1, patient1, doctor1)
        session = plan.items.first().sessions.first()

        tenant2, _, doctor2 = _setup()
        client = _auth_client(doctor2.membership.user)

        with api_tenant_ctx(tenant2):
            resp = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor2.id),
                format="json",
            )

        assert resp.status_code == 404

    def test_detalle_expone_scheduled_time_duration_minutes_y_appointment(self, db: Any) -> None:
        tenant, patient, doctor = _setup()
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()
        client = _auth_client(doctor.membership.user)

        with api_tenant_ctx(tenant):
            client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id),
                format="json",
            )
            resp = client.get(_DETAIL_URL_TMPL.format(plan_id=plan.id))

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["doctor_id"] == str(doctor.id)
        session_out = body["items"][0]["sessions"][0]
        assert session_out["scheduled_time"] == "10:00:00"
        assert session_out["duration_minutes"] == 30
        assert session_out["appointment"]["doctor_id"] == str(doctor.id)
        assert session_out["appointment"]["status"] == "scheduled"


# ---------------------------------------------------------------------------
# 8. Multi-sede — cierre de A8 (docs/design/sucursales-hallazgos-seguridad.md)
#
# TreatmentSessionScheduleApi (agendar/quitar) NO resolvía ni validaba sede,
# así que la rama "misma sesión + mismo médico" de treatment_session_schedule
# delegaba en appointment_reschedule (que tampoco valida sede) y la cita
# adoptaba la sede del consultorio elegido sin comprobar allowed_sucursales;
# el DELETE cancelaba la cita ligada sin filtro de sede. Un admin/doctor
# acotado a una sede podía así mover una cita de sesión a otra sede, o
# cancelar una cita que vive en otra sede.
# ---------------------------------------------------------------------------


def _admin_scoped_to(tenant: Any, sucursal: Any) -> Any:
    """Crea un admin con MembershipSucursal — acotado SOLO a `sucursal`."""
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.ADMIN, is_active=True
    )
    MembershipSucursalFactory(membership=membership, sucursal=sucursal)
    return membership.user


class TestTreatmentSessionScheduleApiSucursal:
    def _create_plan(self, tenant: Any, patient: Any, doctor: Any) -> Any:
        with tenant_ctx(tenant):
            return treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM, quantity=1)],
                doctor=doctor,
                actor_role="doctor",
            )

    def test_admin_acotado_a_centro_no_puede_mover_cita_a_consultorio_de_norte(
        self, db: Any
    ) -> None:
        """Sesión ya agendada (mismo doctor) — reagendar con consultorio_id de
        Norte debe rechazarse; la cita NO se mueve (sigue en Centro)."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()

        admin_centro = _admin_scoped_to(tenant, centro)
        client = _auth_client(admin_centro)

        with api_tenant_ctx(tenant):
            resp1 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id, consultorio_id=str(consultorio_centro.id)),
                format="json",
            )
        assert resp1.status_code == 200, resp1.content
        appointment_id = resp1.json()["appointment"]["id"]

        with api_tenant_ctx(tenant):
            resp2 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(
                    doctor.id,
                    consultorio_id=str(consultorio_norte.id),
                    scheduled_date="2026-08-02",
                    scheduled_time="11:00:00",
                    starts_at="2026-08-02T17:00:00Z",
                    ends_at="2026-08-02T17:30:00Z",
                ),
                format="json",
            )

        assert resp2.status_code == 400, resp2.content
        assert "detail" in resp2.json()

        appt = Appointment.objects.get(id=appointment_id)
        assert appt.sucursal_id == centro.id
        assert appt.consultorio_id == consultorio_centro.id
        assert appt.starts_at == datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC)

    def test_admin_acotado_a_centro_no_puede_quitar_de_agenda_cita_de_norte(self, db: Any) -> None:
        """DELETE sobre una sesión cuya cita vive en Norte debe rechazarse; la
        cita NO se cancela."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()

        owner = _member(tenant, TenantMembership.Role.OWNER)
        owner_client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp1 = owner_client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id, consultorio_id=str(consultorio_norte.id)),
                format="json",
            )
        assert resp1.status_code == 200, resp1.content
        appointment_id = resp1.json()["appointment"]["id"]

        admin_centro = _admin_scoped_to(tenant, centro)
        client = _auth_client(admin_centro)

        with api_tenant_ctx(tenant):
            resp2 = client.delete(_SCHEDULE_URL_TMPL.format(session_id=session.id))

        assert resp2.status_code == 400, resp2.content
        assert "detail" in resp2.json()

        appt = Appointment.objects.get(id=appointment_id)
        assert appt.status == Appointment.Status.SCHEDULED
        session.refresh_from_db()
        assert session.appointment_id == appt.id

    def test_admin_acotado_a_centro_puede_agendar_en_su_propia_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_default=True)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()

        admin_centro = _admin_scoped_to(tenant, centro)
        client = _auth_client(admin_centro)

        with api_tenant_ctx(tenant):
            resp = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id, consultorio_id=str(consultorio_centro.id)),
                format="json",
            )

        assert resp.status_code == 200, resp.content
        appt = Appointment.objects.get(id=resp.json()["appointment"]["id"])
        assert appt.sucursal_id == centro.id

    def test_owner_puede_mover_sesion_agendada_a_otra_sede(self, db: Any) -> None:
        """El owner (alcance total) SÍ puede mover la cita ligada a otra sede."""
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        consultorio_centro = ConsultorioFactory(tenant=tenant, sucursal=centro)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()

        owner = _member(tenant, TenantMembership.Role.OWNER)
        client = _auth_client(owner)

        with api_tenant_ctx(tenant):
            resp1 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id, consultorio_id=str(consultorio_centro.id)),
                format="json",
            )
        assert resp1.status_code == 200, resp1.content
        appointment_id = resp1.json()["appointment"]["id"]

        with api_tenant_ctx(tenant):
            resp2 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(
                    doctor.id,
                    consultorio_id=str(consultorio_norte.id),
                    scheduled_date="2026-08-02",
                    scheduled_time="11:00:00",
                    starts_at="2026-08-02T17:00:00Z",
                    ends_at="2026-08-02T17:30:00Z",
                ),
                format="json",
            )
        assert resp2.status_code == 200, resp2.content
        assert resp2.json()["appointment"]["id"] == appointment_id

        appt = Appointment.objects.get(id=appointment_id)
        assert appt.sucursal_id == norte.id
        assert appt.consultorio_id == consultorio_norte.id

    def test_owner_puede_quitar_de_agenda_cita_de_cualquier_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        norte = SucursalFactory(tenant=tenant)
        SucursalFactory(tenant=tenant, is_default=True)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        plan = self._create_plan(tenant, patient, doctor)
        session = plan.items.first().sessions.first()

        owner = _member(tenant, TenantMembership.Role.OWNER)
        client = _auth_client(owner)

        with api_tenant_ctx(tenant):
            resp1 = client.post(
                _SCHEDULE_URL_TMPL.format(session_id=session.id),
                data=_schedule_payload(doctor.id, consultorio_id=str(consultorio_norte.id)),
                format="json",
            )
        assert resp1.status_code == 200, resp1.content

        with api_tenant_ctx(tenant):
            resp2 = client.delete(_SCHEDULE_URL_TMPL.format(session_id=session.id))

        assert resp2.status_code == 200, resp2.content
        assert resp2.json()["appointment"] is None


class TestTreatmentSessionScheduleServiceSucursal:
    """Defensa en profundidad: los mismos candados directamente en el service,
    sin pasar por la vista (protege callers internos — commands, Celery, etc.)."""

    def test_service_rechaza_agendar_si_la_cita_existente_es_de_otra_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM, quantity=1)],
                doctor=doctor,
                actor_role="doctor",
            )
            # El actor que agenda la PRIMERA cita (en Norte) debe tener acceso
            # a esa sede — se usa un owner (alcance total) para no confundir
            # esta validación con la del propio `doctor` (que, sin fila de
            # MembershipSucursal, cae por el fallback anti-lockout SOLO en la
            # sede default = Centro).
            owner = TenantMembershipFactory(
                tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
            ).user
            session = plan.items.first().sessions.first()
            session = treatment_session_schedule(
                session=session,
                actor=owner,
                actor_role="owner",
                doctor_id=doctor.id,
                consultorio_id=consultorio_norte.id,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )
            assert session.appointment is not None
            assert session.appointment.sucursal_id == norte.id

            admin_centro = _admin_scoped_to(tenant, centro)

            with pytest.raises(DjangoValidationError, match="No tienes acceso a la sede"):
                treatment_session_schedule(
                    session=session,
                    actor=admin_centro,
                    actor_role="admin",
                    doctor_id=doctor.id,
                    consultorio_id=None,
                    starts_at=datetime.datetime(2026, 8, 2, 16, 0, tzinfo=datetime.UTC),
                    ends_at=datetime.datetime(2026, 8, 2, 16, 30, tzinfo=datetime.UTC),
                    scheduled_date=datetime.date(2026, 8, 2),
                    scheduled_time=datetime.time(10, 0),
                    duration_minutes=30,
                )

            session.appointment.refresh_from_db()
            assert session.appointment.sucursal_id == norte.id
            assert session.appointment.starts_at == datetime.datetime(
                2026, 8, 1, 16, 0, tzinfo=datetime.UTC
            )

    def test_service_rechaza_unschedule_si_la_cita_es_de_otra_sede(self, db: Any) -> None:
        tenant = TenantFactory()
        centro = SucursalFactory(tenant=tenant, is_default=True)
        norte = SucursalFactory(tenant=tenant)
        consultorio_norte = ConsultorioFactory(tenant=tenant, sucursal=norte)
        doctor = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            plan = treatment_plan_create(
                patient=patient,
                actor=doctor.membership.user,
                title="",
                notes="",
                status=TreatmentPlanStatus.ACTIVA,
                items=[dict(_SIMPLE_ITEM, quantity=1)],
                doctor=doctor,
                actor_role="doctor",
            )
            # El actor que agenda la PRIMERA cita (en Norte) debe tener acceso
            # a esa sede — se usa un owner (alcance total) para no confundir
            # esta validación con la del propio `doctor` (que, sin fila de
            # MembershipSucursal, cae por el fallback anti-lockout SOLO en la
            # sede default = Centro).
            owner = TenantMembershipFactory(
                tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
            ).user
            session = plan.items.first().sessions.first()
            session = treatment_session_schedule(
                session=session,
                actor=owner,
                actor_role="owner",
                doctor_id=doctor.id,
                consultorio_id=consultorio_norte.id,
                starts_at=datetime.datetime(2026, 8, 1, 16, 0, tzinfo=datetime.UTC),
                ends_at=datetime.datetime(2026, 8, 1, 16, 30, tzinfo=datetime.UTC),
                scheduled_date=datetime.date(2026, 8, 1),
                scheduled_time=datetime.time(10, 0),
                duration_minutes=30,
            )
            appointment_id = session.appointment_id

            admin_centro = _admin_scoped_to(tenant, centro)

            with pytest.raises(DjangoValidationError, match="No tienes acceso a la sede"):
                treatment_session_unschedule(
                    session=session, actor=admin_centro, actor_role="admin"
                )

            session.refresh_from_db()
            assert session.appointment_id == appointment_id
            appt = Appointment.objects.get(id=appointment_id)
            assert appt.status == Appointment.Status.SCHEDULED
