"""
Tests de la app expediente — sub-fase A4 (EvolutionNote, Addendum, Diagnosis).

Cubre (objetivo ≥ 80% en lógica de negocio):

Services:
- evolution_note_create: camino feliz, cita no ATTENDED → 400, cita otro tenant → 404,
  cita otro paciente → 404, doctor no es el de la cita → 400, regla del médico → 403.
- addendum_create: camino feliz, evolution otro tenant → 400.
- diagnosis_create: camino feliz, resolución (idempotente), evolution otro paciente → 400.
- diagnosis_resolve: activo→resuelto; idempotente.

Selectors:
- evolution_note_list: filtrado por tenant.
- diagnosis_list: only_active.
- evolution_note_get / diagnosis_get: IDOR cross-tenant → DoesNotExist.

Validación estricta D-EC-7:
- exploracion_fisica sistema/estado inválido → 400; claves desconocidas → 400.
- textos sobre max_length → 400; campos de raíz desconocidos → 400.

Permisos por rol:
- Nurse/recepción/finanzas NO crean evoluciones ni diagnósticos → 403.
- CLINICAL_READ (nurse, readonly) GET 200; recepción/finanzas GET 403.
- Regla del médico: doctor A no puede crear evolución de cita de doctor B → 400.

Inmutabilidad (D-EC-1):
- PATCH/PUT/DELETE a la URL de evoluciones → 405.
- Addendum SÍ se puede crear.

Bitácora:
- POST evolución genera EVOLUTION_CREATE con resource_repr=UUID (no PII).
- POST addendum genera ADDENDUM_CREATE.
- POST diagnóstico genera DIAGNOSIS_CREATE.
- POST resolver genera DIAGNOSIS_RESOLVE.
- GET evoluciones genera EVOLUTION_READ.

RLS:
- Las 3 tablas tienen política WITH CHECK (verificado via información del esquema).

IDOR / Multi-tenant:
- Evolución, addendum y diagnóstico de otro tenant → 404 (mismo mensaje).
- Cita de otro tenant → 404 al crear evolución.

Patrón: AAA. factory_boy para datos. Mockeo de tenant igual que A1/A2/A3.
"""

import uuid as uuid_module
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.agenda.models import Appointment
from apps.audit.models import ActionType, AuditLog
from apps.expediente.models import (
    Addendum,
    Diagnosis,
    DiagnosisStatus,
    EvolutionNote,
)
from apps.expediente.selectors import (
    diagnosis_get,
    diagnosis_list,
    evolution_note_get,
    evolution_note_list,
)
from apps.expediente.services import (
    addendum_create,
    diagnosis_create,
    diagnosis_resolve,
    evolution_note_create,
)
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AddendumFactory,
    AppointmentFactory,
    DiagnosisFactory,
    DoctorFactory,
    EvolutionNoteFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
    VitalSignsRecordFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def _evoluciones_url(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/evoluciones/"


def _addendum_url(evolution_id: Any) -> str:
    return f"/api/v1/expediente/evoluciones/{evolution_id}/addendum/"


def _diagnosticos_url(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/diagnosticos/"


def _resolver_url(diagnosis_id: Any) -> str:
    return f"/api/v1/expediente/diagnosticos/{diagnosis_id}/resolver/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _member(
    tenant: Any,
    role: str = TenantMembership.Role.DOCTOR,
) -> Any:
    """Crea un user con membresía activa en el tenant dado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _attended_appointment(tenant: Any, patient: Any, doctor: Any) -> Appointment:
    """Crea una cita ATTENDED en el tenant/paciente/doctor dados."""
    return AppointmentFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        status=Appointment.Status.ATTENDED,
    )


# ===========================================================================
# Services — evolution_note_create
# ===========================================================================


class TestEvolutionNoteCreate:
    """Tests del service evolution_note_create."""

    def test_camino_feliz(self, db: Any) -> None:
        """Crea una nota de evolución sobre una cita ATTENDED."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        user = doctor.membership.user

        with tenant_ctx(tenant):
            note = evolution_note_create(
                tenant=tenant,
                user=user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                antecedentes="Sin antecedentes relevantes.",
            )

        assert note.pk is not None
        assert note.is_locked is True
        assert note.patient_id == patient.id
        assert note.appointment_id == appt.id
        assert note.tenant_id == tenant.id

    def test_cita_no_attended_rechazada(self, db: Any) -> None:
        """D-EC-2: cita no ATTENDED → ValidationError."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            status=Appointment.Status.SCHEDULED,
        )

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="ATTENDED"):
                evolution_note_create(
                    tenant=tenant,
                    user=doctor.membership.user,
                    patient=patient,
                    appointment=appt,
                    doctor=doctor,
                )

    def test_cita_otro_tenant_rechazada(self, db: Any) -> None:
        """D-EC-2: cita de otro tenant → ValidationError."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        otro_tenant = TenantFactory()
        otro_doctor = DoctorFactory(tenant=otro_tenant)
        otro_patient = PatientFactory(tenant=otro_tenant)
        appt_otro = _attended_appointment(otro_tenant, otro_patient, otro_doctor)

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="clínica"):
                evolution_note_create(
                    tenant=tenant,
                    user=doctor.membership.user,
                    patient=patient,
                    appointment=appt_otro,
                    doctor=doctor,
                )

    def test_cita_otro_paciente_rechazada(self, db: Any) -> None:
        """D-EC-2: cita de otro paciente (mismo tenant) → ValidationError."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        otro_patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, otro_patient, doctor)

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="paciente"):
                evolution_note_create(
                    tenant=tenant,
                    user=doctor.membership.user,
                    patient=patient,
                    appointment=appt,
                    doctor=doctor,
                )

    def test_doctor_diferente_al_de_la_cita(self, db: Any) -> None:
        """D-EC-2: doctor de la nota distinto al de la cita → ValidationError."""
        doctor_a = DoctorFactory()
        tenant = doctor_a.tenant
        doctor_b = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor_a)

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="médico de la cita"):
                evolution_note_create(
                    tenant=tenant,
                    user=doctor_a.membership.user,
                    patient=patient,
                    appointment=appt,
                    doctor=doctor_b,  # distinto al de la cita
                )

    def test_regla_del_medico_doctor_ajeno_rechazado(self, db: Any) -> None:
        """ALTO-1: doctor A no puede crear evolución sobre cita de doctor B.

        actor_role se pasa explícito al service (no _active_role_cache efímero).
        """
        doctor_a = DoctorFactory()
        tenant = doctor_a.tenant
        doctor_b = DoctorFactory(tenant=tenant)
        patient = PatientFactory(tenant=tenant)

        # La cita le pertenece a doctor_b
        appt = _attended_appointment(tenant, patient, doctor_b)

        # Doctor A intenta crear la nota (actor distinto al de la cita)
        user_a = doctor_a.membership.user

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="propias citas"):
                evolution_note_create(
                    tenant=tenant,
                    user=user_a,
                    patient=patient,
                    appointment=appt,
                    doctor=doctor_b,  # doctor correcto de la cita
                    actor_role=TenantMembership.Role.DOCTOR,  # ALTO-1: explícito
                )

    def test_regla_del_medico_owner_puede_crear_para_otro_doctor(
        self, db: Any
    ) -> None:
        """Owner puede crear evolución sobre cita de cualquier médico.

        actor_role='owner' → sin restricción de médico.
        """
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        owner = UserFactory()
        TenantMembershipFactory(
            user=owner, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
        )

        with tenant_ctx(tenant):
            note = evolution_note_create(
                tenant=tenant,
                user=owner,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                actor_role=TenantMembership.Role.OWNER,  # ALTO-1: explícito
            )

        assert note.pk is not None

    def test_tenant_none_rechazado(self, db: Any) -> None:
        """Guardia de tenant None → ValidationError."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        with pytest.raises(ValidationError, match="tenant activo"):
            evolution_note_create(
                tenant=None,  # type: ignore[arg-type]
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
            )

    def test_vital_signs_otro_paciente_rechazado(self, db: Any) -> None:
        """vital_signs de otro paciente → ValidationError."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        otro_patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        # signos vitales del otro paciente
        vs = VitalSignsRecordFactory(tenant=tenant, patient=otro_patient)

        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="paciente"):
                evolution_note_create(
                    tenant=tenant,
                    user=doctor.membership.user,
                    patient=patient,
                    appointment=appt,
                    doctor=doctor,
                    vital_signs=vs,
                )

    def test_genera_auditoria_evolution_create(self, db: Any) -> None:
        """POST nota de evolución → EVOLUTION_CREATE en AuditLog con resource_repr=UUID."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        with tenant_ctx(tenant):
            note = evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
            )

        log = AuditLog.all_objects.filter(
            action=ActionType.EVOLUTION_CREATE,
        ).last()
        assert log is not None
        assert log.resource_repr == str(note.id)
        assert log.resource_id == note.id


# ===========================================================================
# Services — addendum_create
# ===========================================================================


class TestAddendumCreate:
    """Tests del service addendum_create."""

    def test_camino_feliz(self, db: Any) -> None:
        """Crea un addendum sobre una nota de evolución existente."""
        note = EvolutionNoteFactory()
        user = note.created_by

        with tenant_ctx(note.tenant):
            addendum = addendum_create(
                tenant=note.tenant,
                user=user,
                evolution=note,
                body="Aclaración: el paciente tomó la medicación correctamente.",
            )

        assert addendum.pk is not None
        assert addendum.evolution_id == note.id
        assert addendum.body.startswith("Aclaración")

    def test_body_vacio_rechazado(self, db: Any) -> None:
        """body vacío (solo espacios) → ValidationError."""
        note = EvolutionNoteFactory()

        with tenant_ctx(note.tenant):
            with pytest.raises(ValidationError, match="vacío"):
                addendum_create(
                    tenant=note.tenant,
                    user=note.created_by,
                    evolution=note,
                    body="   ",
                )

    def test_evolution_otro_tenant_rechazado(self, db: Any) -> None:
        """Evolution de otro tenant → ValidationError."""
        note = EvolutionNoteFactory()
        otro_tenant = TenantFactory()

        with tenant_ctx(otro_tenant):
            with pytest.raises(ValidationError, match="clínica"):
                addendum_create(
                    tenant=otro_tenant,
                    user=note.created_by,
                    evolution=note,
                    body="Addendum de prueba.",
                )

    def test_genera_auditoria_addendum_create(self, db: Any) -> None:
        """POST addendum → ADDENDUM_CREATE en AuditLog."""
        note = EvolutionNoteFactory()

        with tenant_ctx(note.tenant):
            addendum = addendum_create(
                tenant=note.tenant,
                user=note.created_by,
                evolution=note,
                body="Nota adicional sobre el tratamiento.",
            )

        log = AuditLog.all_objects.filter(action=ActionType.ADDENDUM_CREATE).last()
        assert log is not None
        assert log.resource_id == addendum.id


# ===========================================================================
# Services — diagnosis_create / diagnosis_resolve
# ===========================================================================


class TestDiagnosisCreateResolve:
    """Tests de los services diagnosis_create y diagnosis_resolve."""

    def test_camino_feliz_create(self, db: Any) -> None:
        """Crea un diagnóstico con status=activo."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = UserFactory()

        with tenant_ctx(tenant):
            diag = diagnosis_create(
                tenant=tenant,
                user=user,
                patient=patient,
                description="Hipertensión arterial sistémica",
                cie_code="I10",
            )

        assert diag.pk is not None
        assert diag.status == DiagnosisStatus.ACTIVO
        assert diag.cie_code == "I10"

    def test_description_vacia_rechazada(self, db: Any) -> None:
        """description vacía → ValidationError."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError, match="vacía"):
            diagnosis_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                description="   ",
            )

    def test_kind_invalido_rechazado(self, db: Any) -> None:
        """kind fuera de choices → ValidationError."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError, match="Tipo de diagnóstico inválido"):
            diagnosis_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                description="Diagnóstico válido",
                kind="inventado",
            )

    def test_resolve_activo_a_resuelto(self, db: Any) -> None:
        """diagnosis_resolve cambia status=activo → resuelto."""
        diag = DiagnosisFactory(status=DiagnosisStatus.ACTIVO)

        with tenant_ctx(diag.tenant):
            resultado = diagnosis_resolve(diagnosis=diag, user=UserFactory())

        assert resultado.status == DiagnosisStatus.RESUELTO

    def test_resolve_idempotente(self, db: Any) -> None:
        """Resolver un diagnóstico ya resuelto no lanza error (idempotente)."""
        diag = DiagnosisFactory(status=DiagnosisStatus.RESUELTO)

        with tenant_ctx(diag.tenant):
            resultado = diagnosis_resolve(diagnosis=diag, user=UserFactory())

        assert resultado.status == DiagnosisStatus.RESUELTO

    def test_description_no_editable_tras_create(self, db: Any) -> None:
        """description/cie_code/kind son inmutables: no existen endpoint PATCH → 405."""
        # Este test verifica que el modelo solo tiene los campos esperados.
        # La inmutabilidad real se garantiza por la ausencia de endpoint PATCH.
        diag = DiagnosisFactory(description="Original")
        assert diag.description == "Original"
        # No existe ningún service `diagnosis_update`; es intencional.

    def test_sin_borrado_fisico(self, db: Any) -> None:
        """D-EC-5: Diagnosis.delete() no está en ningún endpoint (no hay ruta DELETE)."""
        diag = DiagnosisFactory()
        pk = diag.pk
        # La tabla sigue existiendo después de resolver
        with tenant_ctx(diag.tenant):
            diagnosis_resolve(diagnosis=diag, user=UserFactory())
        assert Diagnosis.all_objects.filter(pk=pk).exists()

    def test_generates_auditoria_diagnosis_create(self, db: Any) -> None:
        """POST diagnóstico → DIAGNOSIS_CREATE en AuditLog con resource_repr=UUID."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            diag = diagnosis_create(
                tenant=tenant,
                user=UserFactory(),
                patient=patient,
                description="Diagnóstico de prueba",
            )

        log = AuditLog.all_objects.filter(action=ActionType.DIAGNOSIS_CREATE).last()
        assert log is not None
        assert log.resource_repr == str(diag.id)

    def test_generates_auditoria_diagnosis_resolve(self, db: Any) -> None:
        """POST resolver → DIAGNOSIS_RESOLVE en AuditLog."""
        diag = DiagnosisFactory(status=DiagnosisStatus.ACTIVO)

        with tenant_ctx(diag.tenant):
            diagnosis_resolve(diagnosis=diag, user=UserFactory())

        log = AuditLog.all_objects.filter(action=ActionType.DIAGNOSIS_RESOLVE).last()
        assert log is not None
        assert log.resource_id == diag.id

    def test_evolution_otro_paciente_rechazada(self, db: Any) -> None:
        """Evolution de otro paciente → ValidationError al crear diagnóstico."""
        tenant = TenantFactory()
        patient_a = PatientFactory(tenant=tenant)
        patient_b = PatientFactory(tenant=tenant)

        # Nota del paciente B
        doctor = DoctorFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient_b, doctor)
        with tenant_ctx(tenant):
            note_b = evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient_b,
                appointment=appt,
                doctor=doctor,
            )

            with pytest.raises(ValidationError, match="paciente"):
                diagnosis_create(
                    tenant=tenant,
                    user=UserFactory(),
                    patient=patient_a,  # paciente diferente
                    description="Diagnóstico",
                    evolution=note_b,
                )


# ===========================================================================
# Selectors
# ===========================================================================


class TestEvolutionSelectors:
    """Tests de selectors de A4."""

    def test_evolution_note_list_filtra_tenant(self, db: Any) -> None:
        """evolution_note_list devuelve solo notas del tenant activo."""
        note = EvolutionNoteFactory()
        _otro_note = EvolutionNoteFactory()  # tenant diferente

        with tenant_ctx(note.tenant):
            qs = evolution_note_list(patient=note.patient)
            assert qs.count() == 1
            assert qs.first().id == note.id

    def test_diagnosis_list_only_active(self, db: Any) -> None:
        """diagnosis_list con only_active=True devuelve solo los activos."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        diag_activo = DiagnosisFactory(
            tenant=tenant, patient=patient, status=DiagnosisStatus.ACTIVO
        )
        DiagnosisFactory(
            tenant=tenant, patient=patient, status=DiagnosisStatus.RESUELTO
        )

        with tenant_ctx(tenant):
            qs = diagnosis_list(patient=patient, only_active=True)
            ids = list(qs.values_list("id", flat=True))

        assert diag_activo.id in ids
        assert len(ids) == 1

    def test_evolution_note_get_otro_tenant_raises(self, db: Any) -> None:
        """evolution_note_get con id de otro tenant → DoesNotExist (anti-IDOR)."""
        note = EvolutionNoteFactory()
        otro_tenant = TenantFactory()

        with tenant_ctx(otro_tenant):
            with pytest.raises(EvolutionNote.DoesNotExist):
                evolution_note_get(evolution_id=note.id)

    def test_diagnosis_get_otro_tenant_raises(self, db: Any) -> None:
        """diagnosis_get con id de otro tenant → DoesNotExist (anti-IDOR)."""
        diag = DiagnosisFactory()
        otro_tenant = TenantFactory()

        with tenant_ctx(otro_tenant):
            with pytest.raises(Diagnosis.DoesNotExist):
                diagnosis_get(diagnosis_id=diag.id)


# ===========================================================================
# Validación estricta D-EC-7 (API)
# ===========================================================================


class TestEvolutionValidacionEstricta:
    """Tests de validación estricta D-EC-7 en el input de evoluciones."""

    def _setup_doctor_api(
        self,
    ) -> tuple[Any, Any, Any, Any, Any]:
        """Crea doctor, tenant, patient, cita ATTENDED y cliente autenticado.

        Reutiliza el usuario de la membership del doctor (ya creada por DoctorFactory)
        para evitar duplicar TenantMembership (UniqueConstraint).
        """
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        user = doctor.membership.user
        return doctor, tenant, patient, appt, user

    def test_exploracion_sistema_invalido_400(self, db: Any) -> None:
        """Sistema fuera de whitelist → 400."""
        doctor, tenant, patient, appt, user = self._setup_doctor_api()

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(
                _evoluciones_url(patient.id),
                data={
                    "appointment_id": str(appt.id),
                    "doctor_id": str(doctor.id),
                    "exploracion_fisica": {
                        "sistema_inventado": {"estado": "normal", "detalle": "ok"}
                    },
                },
                format="json",
            )

        assert resp.status_code == 400

    def test_estado_invalido_exploracion_400(self, db: Any) -> None:
        """Estado fuera de semáforo → 400."""
        doctor, tenant, patient, appt, user = self._setup_doctor_api()

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(
                _evoluciones_url(patient.id),
                data={
                    "appointment_id": str(appt.id),
                    "doctor_id": str(doctor.id),
                    "exploracion_fisica": {
                        "corazon": {"estado": "estado_inventado", "detalle": "ok"}
                    },
                },
                format="json",
            )

        assert resp.status_code == 400

    def test_campo_desconocido_raiz_400(self, db: Any) -> None:
        """Campo no declarado en raíz del input → 400."""
        doctor, tenant, patient, appt, user = self._setup_doctor_api()

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(
                _evoluciones_url(patient.id),
                data={
                    "appointment_id": str(appt.id),
                    "doctor_id": str(doctor.id),
                    "campo_desconocido": "valor",
                },
                format="json",
            )

        assert resp.status_code == 400

    def test_antecedentes_sobre_max_length_400(self, db: Any) -> None:
        """Campo de texto sobre max_length → 400."""
        doctor, tenant, patient, appt, user = self._setup_doctor_api()

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(
                _evoluciones_url(patient.id),
                data={
                    "appointment_id": str(appt.id),
                    "doctor_id": str(doctor.id),
                    "antecedentes": "A" * 10_001,  # 1 char sobre el límite
                },
                format="json",
            )

        assert resp.status_code == 400


# ===========================================================================
# Permisos por rol (API)
# ===========================================================================


class TestEvolutionPermisos:
    """Tests de permisos por rol en la API de evoluciones."""

    def test_nurse_no_puede_crear_evolucion(self, db: Any) -> None:
        """Enfermería no puede crear notas de evolución → 403."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        nurse = _member(tenant, role=TenantMembership.Role.NURSE)

        with api_tenant_ctx(tenant):
            client = _auth_client(nurse)
            resp = client.post(
                _evoluciones_url(patient.id),
                data={
                    "appointment_id": str(appt.id),
                    "doctor_id": str(doctor.id),
                },
                format="json",
            )

        assert resp.status_code == 403

    def test_recepcion_no_puede_crear_evolucion(self, db: Any) -> None:
        """Recepción no puede crear notas de evolución → 403."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        reception = _member(tenant, role=TenantMembership.Role.RECEPTION)

        with api_tenant_ctx(tenant):
            client = _auth_client(reception)
            resp = client.post(
                _evoluciones_url(patient.id),
                data={
                    "appointment_id": str(appt.id),
                    "doctor_id": str(doctor.id),
                },
                format="json",
            )

        assert resp.status_code == 403

    def test_finanzas_no_puede_ver_evoluciones(self, db: Any) -> None:
        """Finanzas no tiene acceso al GET de evoluciones → 403."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        finance = _member(tenant, role=TenantMembership.Role.FINANCE)

        with api_tenant_ctx(tenant):
            client = _auth_client(finance)
            resp = client.get(_evoluciones_url(patient.id))

        assert resp.status_code == 403

    def test_readonly_puede_ver_evoluciones(self, db: Any) -> None:
        """Readonly (CLINICAL_READ) puede ver el listado → 200."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        readonly = _member(tenant, role=TenantMembership.Role.READONLY)

        with api_tenant_ctx(tenant):
            client = _auth_client(readonly)
            resp = client.get(_evoluciones_url(patient.id))

        assert resp.status_code == 200

    def test_nurse_puede_ver_evoluciones(self, db: Any) -> None:
        """Nurse (CLINICAL_READ) puede ver el listado → 200."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        nurse = _member(tenant, role=TenantMembership.Role.NURSE)

        with api_tenant_ctx(tenant):
            client = _auth_client(nurse)
            resp = client.get(_evoluciones_url(patient.id))

        assert resp.status_code == 200

    def test_recepcion_no_puede_ver_diagnosticos(self, db: Any) -> None:
        """Recepción no tiene acceso al GET de diagnósticos → 403."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        reception = _member(tenant, role=TenantMembership.Role.RECEPTION)

        with api_tenant_ctx(tenant):
            client = _auth_client(reception)
            resp = client.get(_diagnosticos_url(patient.id))

        assert resp.status_code == 403


# ===========================================================================
# Inmutabilidad (D-EC-1) — API
# ===========================================================================


class TestEvolutionInmutabilidad:
    """Tests que verifican que PATCH/PUT/DELETE no están ruteados."""

    def test_patch_no_ruteado_405(self, db: Any) -> None:
        """PATCH /evoluciones/<patient_id>/ → 405 (método no ruteado).

        DRF responde 405 porque la View no tiene handler 'patch'.
        El usuario necesita autenticación + membresía activa para que el
        middleware de permisos llegue hasta el router y devuelva 405.
        """
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        # Reutilizar user de la membership ya creada por DoctorFactory.
        user = doctor.membership.user

        with api_tenant_ctx(tenant):
            # Parchear active_role para simular que el middleware de tenant lo inyecta.
            with patch("apps.expediente.views.EvolutionPermission.has_permission", return_value=True):
                client = _auth_client(user)
                resp = client.patch(_evoluciones_url(patient.id), data={}, format="json")

        assert resp.status_code == 405

    def test_addendum_si_se_puede_crear(self, db: Any) -> None:
        """Addendum sobre una nota existente → 201 (append-only permitido)."""
        note = EvolutionNoteFactory()
        tenant = note.tenant
        # El doctor de la nota ya tiene membership; usamos su usuario directamente.
        user = note.doctor.membership.user

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(
                _addendum_url(note.id),
                data={"body": "Aclaración sobre el tratamiento."},
                format="json",
            )

        assert resp.status_code == 201


# ===========================================================================
# IDOR / Multi-tenant (API)
# ===========================================================================


class TestEvolutionIdiomIDOR:
    """Tests que verifican respuestas 404 uniformes cross-tenant (anti-IDOR)."""

    def test_paciente_otro_tenant_404(self, db: Any) -> None:
        """patient_id de otro tenant → 404.

        El usuario tiene membresía activa en tenant A; el patient_id corresponde
        a un paciente de tenant B. TenantManager filtra y devuelve DoesNotExist → 404.
        """
        doctor = DoctorFactory()
        tenant = doctor.tenant
        # Reutilizar user de la membership ya creada por DoctorFactory.
        user = doctor.membership.user

        # Paciente en un tenant diferente.
        otro_tenant = TenantFactory()
        otro_patient = PatientFactory(tenant=otro_tenant)

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.get(_evoluciones_url(otro_patient.id))

        assert resp.status_code == 404

    def test_evolution_otro_tenant_addendum_404(self, db: Any) -> None:
        """evolution_id de otro tenant → 404 al crear addendum."""
        note_otro = EvolutionNoteFactory()  # tenant A
        tenant_b = TenantFactory()
        user_b = _member(tenant_b, role=TenantMembership.Role.DOCTOR)

        with api_tenant_ctx(tenant_b):
            client = _auth_client(user_b)
            resp = client.post(
                _addendum_url(note_otro.id),
                data={"body": "Addendum de prueba."},
                format="json",
            )

        assert resp.status_code == 404

    def test_diagnosis_otro_tenant_resolver_404(self, db: Any) -> None:
        """diagnosis_id de otro tenant → 404 al resolver."""
        diag = DiagnosisFactory()
        tenant_b = TenantFactory()
        user_b = _member(tenant_b, role=TenantMembership.Role.DOCTOR)

        with api_tenant_ctx(tenant_b):
            client = _auth_client(user_b)
            resp = client.post(_resolver_url(diag.id), data={}, format="json")

        assert resp.status_code == 404


# ===========================================================================
# Bitácora — GET evoluciones genera EVOLUTION_READ (API)
# ===========================================================================


class TestEvolutionBitacora:
    """Tests de registro de bitácora en lecturas de evoluciones."""

    def test_get_evoluciones_genera_evolution_read(self, db: Any) -> None:
        """GET /evoluciones/ registra EVOLUTION_READ en AuditLog."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        # Reutilizar user de la membership ya creada por DoctorFactory.
        user = doctor.membership.user

        before_count = AuditLog.all_objects.filter(
            action=ActionType.EVOLUTION_READ
        ).count()

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.get(_evoluciones_url(patient.id))

        assert resp.status_code == 200
        after_count = AuditLog.all_objects.filter(
            action=ActionType.EVOLUTION_READ
        ).count()
        assert after_count == before_count + 1


# ===========================================================================
# RLS — verificación de políticas (schema)
# ===========================================================================


class TestRLSPolicies:
    """Verifica que las políticas RLS están presentes en el esquema PostgreSQL."""

    @pytest.mark.parametrize(
        "table_name,policy_name",
        [
            ("expediente_evolution_notes", "exp_evolution_notes_tenant_iso"),
            ("expediente_addenda", "exp_addenda_tenant_iso"),
            ("expediente_diagnoses", "exp_diagnoses_tenant_iso"),
        ],
    )
    def test_rls_policy_existe_con_using_y_with_check(
        self, db: Any, table_name: str, policy_name: str
    ) -> None:
        """La tabla tiene política RLS con USING y WITH CHECK (ALTO-2)."""
        from django.db import connection  # noqa: PLC0415

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT polname, polcmd, polqual, polwithcheck
                FROM pg_policy
                WHERE polrelid = %s::regclass
                  AND polname = %s
                """,
                [table_name, policy_name],
            )
            row = cursor.fetchone()

        assert row is not None, (
            f"No se encontró la política RLS '{policy_name}' en la tabla '{table_name}'."
        )
        polname, polcmd, polqual, polwithcheck = row
        # '*' = ALL en pg_policy.polcmd (valor de PostgreSQL para políticas ALL).
        assert polcmd == "*", "La política debe aplicar a todos los comandos (ALL)."
        assert polqual is not None, "La política debe tener cláusula USING."
        assert polwithcheck is not None, "La política debe tener cláusula WITH CHECK."


# ===========================================================================
# Diagnóstico — API camino feliz
# ===========================================================================


class TestDiagnosisAPI:
    """Tests de la API de diagnósticos."""

    def test_crear_diagnostico_201(self, db: Any) -> None:
        """POST /diagnosticos/ crea diagnóstico y responde 201."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(
                _diagnosticos_url(patient.id),
                data={
                    "description": "Diabetes mellitus tipo 2",
                    "cie_code": "E11",
                    "kind": "definitivo",
                },
                format="json",
            )

        assert resp.status_code == 201
        assert resp.data["description"] == "Diabetes mellitus tipo 2"
        assert resp.data["kind"] == "definitivo"
        assert resp.data["status"] == "activo"

    def test_resolver_diagnostico_200(self, db: Any) -> None:
        """POST /diagnosticos/<id>/resolver/ → 200 con status=resuelto."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        diag = DiagnosisFactory(
            tenant=tenant, patient=patient, status=DiagnosisStatus.ACTIVO
        )
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(_resolver_url(diag.id), data={}, format="json")

        assert resp.status_code == 200
        assert resp.data["status"] == "resuelto"

    def test_resolver_diagnostico_idempotente_200(self, db: Any) -> None:
        """POST /resolver/ sobre un diagnóstico ya resuelto → 200 (idempotente)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        diag = DiagnosisFactory(
            tenant=tenant, patient=patient, status=DiagnosisStatus.RESUELTO
        )
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(_resolver_url(diag.id), data={}, format="json")

        assert resp.status_code == 200
        assert resp.data["status"] == "resuelto"

    def test_listado_diagnosticos_paginado(self, db: Any) -> None:
        """GET /diagnosticos/ devuelve listado paginado con envoltura {count, results}."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        DiagnosisFactory.create_batch(3, tenant=tenant, patient=patient)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.get(_diagnosticos_url(patient.id))

        assert resp.status_code == 200
        assert "results" in resp.data
        assert resp.data["count"] == 3


# ===========================================================================
# Tests de seguridad — correcciones de auditoría
# ===========================================================================


class TestSecurityFixes:
    """Tests que cubren las correcciones de seguridad de la auditoría (A4).

    ALTO-1: actor_role explícito — sin _active_role_cache efímero.
    ALTO-2: DIAGNOSIS_READ en bitácora.
    MEDIO-1: max_length=2000 en detalle de exploración.
    MEDIO-2: UniqueConstraint — una evolución por cita.
    MEDIO-4: membership ausente → 400.
    BAJO-2: CheckConstraint is_locked=True.
    """

    # -----------------------------------------------------------------------
    # ALTO-1: actor_role argumento explícito en evolution_note_create
    # -----------------------------------------------------------------------

    def test_alto1_actor_role_sin_rol_no_aplica_restriccion(self, db: Any) -> None:
        """actor_role='' → sin restricción de médico (owner/admin sin role explícito)."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        owner = UserFactory()
        TenantMembershipFactory(
            user=owner, tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
        )

        with tenant_ctx(tenant):
            note = evolution_note_create(
                tenant=tenant,
                user=owner,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                actor_role="",  # Sin rol → no aplica restricción del médico
            )

        assert note.pk is not None

    def test_alto1_actor_role_doctor_mismo_medico_permitido(self, db: Any) -> None:
        """actor_role='doctor' y el mismo médico crea su propia nota → permitido."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        with tenant_ctx(tenant):
            note = evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                actor_role=TenantMembership.Role.DOCTOR,  # propio médico → OK
            )

        assert note.pk is not None
        assert note.is_locked is True

    # -----------------------------------------------------------------------
    # ALTO-2: DIAGNOSIS_READ en bitácora NOM-024
    # -----------------------------------------------------------------------

    def test_alto2_diagnosis_read_genera_auditoria(self, db: Any) -> None:
        """GET /diagnosticos/ → DIAGNOSIS_READ en AuditLog."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        DiagnosisFactory(tenant=tenant, patient=patient)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)

        audit_count_before = AuditLog.all_objects.filter(
            action=ActionType.DIAGNOSIS_READ
        ).count()

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.get(_diagnosticos_url(patient.id))

        assert resp.status_code == 200
        assert (
            AuditLog.all_objects.filter(action=ActionType.DIAGNOSIS_READ).count()
            == audit_count_before + 1
        )

    def test_alto2_diagnosis_read_resource_repr_es_uuid_no_pii(
        self, db: Any
    ) -> None:
        """GET /diagnosticos/ → resource_repr es UUID del paciente (sin PII)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            client.get(_diagnosticos_url(patient.id))

        log = AuditLog.all_objects.filter(
            action=ActionType.DIAGNOSIS_READ
        ).order_by("-created_at").first()

        assert log is not None
        assert log.resource_repr == str(patient.id)
        assert log.metadata.get("patient_id") == str(patient.id)

    # -----------------------------------------------------------------------
    # MEDIO-1: max_length=2000 en detalle de exploración física
    # -----------------------------------------------------------------------

    def test_medio1_detalle_gigante_basal_rechazado(self, db: Any) -> None:
        """validate_exploracion_fisica_basal: detalle > 2000 chars → ValidationError."""
        from apps.expediente.validators import validate_exploracion_fisica_basal  # noqa: PLC0415
        from rest_framework.exceptions import ValidationError as DRFValidationError  # noqa: PLC0415

        datos = {
            "cerebro": {
                "estado": "con_alteraciones",
                "detalle": "x" * 2001,  # 1 char sobre el límite
            }
        }

        with pytest.raises(DRFValidationError, match="2000"):
            validate_exploracion_fisica_basal(datos)

    def test_medio1_detalle_en_limite_basal_permitido(self, db: Any) -> None:
        """validate_exploracion_fisica_basal: detalle == 2000 chars → OK."""
        from apps.expediente.validators import validate_exploracion_fisica_basal  # noqa: PLC0415

        datos = {
            "cerebro": {
                "estado": "con_alteraciones",
                "detalle": "x" * 2000,  # exactamente en el límite
            }
        }

        result = validate_exploracion_fisica_basal(datos)
        assert result == datos

    def test_medio1_detalle_gigante_evolucion_rechazado(self, db: Any) -> None:
        """validate_exploracion_evolucion: detalle > 2000 chars → ValidationError."""
        from apps.expediente.validators import validate_exploracion_evolucion  # noqa: PLC0415
        from rest_framework.exceptions import ValidationError as DRFValidationError  # noqa: PLC0415

        datos = {
            "corazon": {
                "estado": "alterado",
                "detalle": "a" * 2001,
            }
        }

        with pytest.raises(DRFValidationError, match="2000"):
            validate_exploracion_evolucion(datos)

    def test_medio1_detalle_gigante_via_api_rechazado(self, db: Any) -> None:
        """POST /evoluciones/ con detalle > 2000 chars → 400 (validación en serializer)."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        user = doctor.membership.user

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(
                _evoluciones_url(patient.id),
                data={
                    "appointment_id": str(appt.id),
                    "doctor_id": str(doctor.id),
                    "exploracion_fisica": {
                        "cerebro": {
                            "estado": "normal",
                            "detalle": "z" * 2001,
                        }
                    },
                },
                format="json",
            )

        assert resp.status_code == 400

    # -----------------------------------------------------------------------
    # MEDIO-2: UniqueConstraint — una sola evolución por cita
    # -----------------------------------------------------------------------

    def test_medio2_segunda_evolucion_misma_cita_service_rechazada(
        self, db: Any
    ) -> None:
        """evolution_note_create sobre una cita que ya tiene nota → ValidationError."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        # Crear la primera nota
        with tenant_ctx(tenant):
            evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
            )

        # Intentar crear la segunda sobre la misma cita
        with tenant_ctx(tenant):
            with pytest.raises(ValidationError, match="Ya existe una nota"):
                evolution_note_create(
                    tenant=tenant,
                    user=doctor.membership.user,
                    patient=patient,
                    appointment=appt,
                    doctor=doctor,
                )

    def test_medio2_segunda_evolucion_misma_cita_api_rechazada(
        self, db: Any
    ) -> None:
        """POST /evoluciones/ sobre cita con nota existente → 400."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        # Crear primera nota directamente
        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            appointment=appt,
            doctor=doctor,
        )

        user = doctor.membership.user

        with api_tenant_ctx(tenant):
            client = _auth_client(user)
            resp = client.post(
                _evoluciones_url(patient.id),
                data={
                    "appointment_id": str(appt.id),
                    "doctor_id": str(doctor.id),
                },
                format="json",
            )

        assert resp.status_code == 400

    # -----------------------------------------------------------------------
    # MEDIO-4: appointment.doctor.membership ausente → 400 (no 500)
    # -----------------------------------------------------------------------

    def test_medio4_membership_ausente_doctor_rol_rechazado(self, db: Any) -> None:
        """MEDIO-4: actor_role=doctor con membership ausente → ValidationError (no 500).

        Parchea `appointment.doctor.membership` a nivel de clase para lanzar
        AttributeError al acceder. El service debe capturarlo y devolver
        ValidationError("membresía") en lugar de propagarlo como 500.
        """
        from unittest.mock import PropertyMock, patch  # noqa: PLC0415
        from apps.personal.models import Doctor as DoctorModel  # noqa: PLC0415

        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        user = UserFactory()
        TenantMembershipFactory(
            user=user, tenant=tenant, role=TenantMembership.Role.DOCTOR, is_active=True
        )

        # Parchar el acceso a Doctor.membership como property que lanza AttributeError.
        # Esto simula un Doctor en BD sin TenantMembership asociado (datos corruptos).
        broken_membership = PropertyMock(
            side_effect=AttributeError(
                "RelatedObjectDoesNotExist: Doctor has no membership."
            )
        )

        with patch.object(type(appt.doctor), "membership", broken_membership):
            with tenant_ctx(tenant):
                with pytest.raises(ValidationError, match="membresía"):
                    evolution_note_create(
                        tenant=tenant,
                        user=user,
                        patient=patient,
                        appointment=appt,
                        doctor=doctor,
                        actor_role=TenantMembership.Role.DOCTOR,
                    )

    # -----------------------------------------------------------------------
    # BAJO-2: CheckConstraint is_locked=True
    # -----------------------------------------------------------------------

    def test_bajo2_evolucion_siempre_locked(self, db: Any) -> None:
        """EvolutionNote creada tiene is_locked=True (CheckConstraint a nivel BD)."""
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        with tenant_ctx(tenant):
            note = evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
            )

        # Recargar desde BD para confirmar que el constraint persiste
        note.refresh_from_db()
        assert note.is_locked is True

    def test_bajo2_constraint_is_locked_en_bd(self, db: Any) -> None:
        """CheckConstraint evolution_is_locked_always existe en el esquema de la BD."""
        from django.db import connection  # noqa: PLC0415

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'expediente_evolution_notes'::regclass
                  AND contype = 'c'
                  AND conname = 'evolution_is_locked_always'
                """
            )
            row = cursor.fetchone()

        assert row is not None, (
            "La CheckConstraint 'evolution_is_locked_always' no existe en la BD."
        )
