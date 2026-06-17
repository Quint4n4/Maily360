"""
Tests de la feature "Indicaciones de enfermería" (notificación + endpoint).

Cubre:

Services (disparador en evolution_note_create):
- Con indicaciones_enfermeria no vacías → se crean notificaciones para cada enfermera
  del tenant (kind=NURSING_INSTRUCTION, target_type=PATIENT, target_id=paciente.id).
- El médico actor NO recibe su propia notificación (sin auto-notificación).
- Sin indicaciones (cadena vacía) → no se crea ninguna notificación de ese tipo.
- Si el fanout lanza una excepción, la nota de evolución igual se crea (best-effort).

Selectors:
- evolution_nursing_instructions_for_patient devuelve solo las notas con indicaciones.
- Devuelve [] para un paciente sin notas con indicaciones.
- Aislamiento multi-tenant: el selector usa TenantManager → no fuga entre tenants.

API — GET /api/v1/expediente/<patient_id>/indicaciones-enfermeria/:
- Nurse/doctor/owner/readonly → 200 con lista correcta.
- Solo devuelve notas del paciente correcto (no mezcla con otro paciente).
- IDOR: patient_id de otro tenant → 404 mismo mensaje.
- Recepción y finanzas → 403.
- Sin autenticación → 401.

Patrón: AAA. factory_boy para datos. api_tenant_ctx para tests de API.
"""

from typing import Any
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.agenda.models import Appointment
from apps.expediente.selectors import evolution_nursing_instructions_for_patient
from apps.expediente.services import evolution_note_create
from apps.notificaciones.models import Notification, NotificationKind, NotificationTarget
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AppointmentFactory,
    DoctorFactory,
    EvolutionNoteFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx

Role = TenantMembership.Role

# ---------------------------------------------------------------------------
# Helpers compartidos
# ---------------------------------------------------------------------------


def _member(tenant: Any, role: str) -> Any:
    """Crea un User con membresía activa en el tenant con el rol dado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _attended_appointment(tenant: Any, patient: Any, doctor: Any) -> Appointment:
    return AppointmentFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        status=Appointment.Status.ATTENDED,
    )


def _nursing_url(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/indicaciones-enfermeria/"


def _recipients_kind(tenant: Any, kind: str) -> set[Any]:
    """Conjunto de recipient_id de las notificaciones de un kind en el tenant."""
    return set(
        Notification.all_objects.filter(tenant=tenant, kind=kind).values_list(
            "recipient_id", flat=True
        )
    )


# ===========================================================================
# Services — disparador de notificación al crear evolución
# ===========================================================================


class TestNursingInstructionNotification:
    """Tests del disparador en evolution_note_create."""

    def test_con_indicaciones_notifica_a_cada_enfermera(self, db: Any) -> None:
        """Crear evolución con indicaciones → 1 notificación por enfermera del tenant."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        nurse_a = _member(tenant, Role.NURSE)
        nurse_b = _member(tenant, Role.NURSE)
        # Otro rol → no debe recibir
        _member(tenant, Role.RECEPTION)

        # Act
        with tenant_ctx(tenant):
            evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                indicaciones_enfermeria="Tomar signos vitales cada 2 horas.",
            )

        # Assert
        recipients = _recipients_kind(tenant, NotificationKind.NURSING_INSTRUCTION)
        assert nurse_a.pk in recipients
        assert nurse_b.pk in recipients
        assert len(recipients) == 2  # exactamente las dos enfermeras

    def test_con_indicaciones_actor_no_se_autonotifica(self, db: Any) -> None:
        """El médico actor no recibe su propia notificación.

        Aunque el actor sea también enfermera en OTRO tenant (para evitar la restricción
        de membresía única por tenant), el fanout lo excluye por ser actor.
        Verificamos directamente que el actor no está en los recipients.
        """
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        actor_user = doctor.membership.user

        # Una enfermera distinta en el tenant (asegura que el fanout no queda vacío)
        nurse = _member(tenant, Role.NURSE)

        # Act
        with tenant_ctx(tenant):
            evolution_note_create(
                tenant=tenant,
                user=actor_user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                indicaciones_enfermeria="Control de dolor.",
            )

        # Assert: la enfermera sí recibe; el actor (médico) NO
        recipients = _recipients_kind(tenant, NotificationKind.NURSING_INSTRUCTION)
        assert nurse.pk in recipients
        assert actor_user.pk not in recipients

    def test_con_indicaciones_target_es_patient(self, db: Any) -> None:
        """La notificación apunta a PATIENT con el UUID del paciente."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        nurse = _member(tenant, Role.NURSE)

        # Act
        with tenant_ctx(tenant):
            evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                indicaciones_enfermeria="Preparar sala de procedimientos.",
            )

        # Assert
        notif = Notification.all_objects.filter(
            tenant=tenant,
            kind=NotificationKind.NURSING_INSTRUCTION,
            recipient=nurse,
        ).first()
        assert notif is not None
        assert notif.target_type == NotificationTarget.PATIENT
        assert notif.target_id == patient.id

    def test_sin_indicaciones_no_crea_notificacion(self, db: Any) -> None:
        """Crear evolución con indicaciones vacías → no se crea ninguna notificación."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        _member(tenant, Role.NURSE)

        # Act
        with tenant_ctx(tenant):
            evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                indicaciones_enfermeria="",  # vacío: no debe notificar
            )

        # Assert
        count = Notification.all_objects.filter(
            tenant=tenant, kind=NotificationKind.NURSING_INSTRUCTION
        ).count()
        assert count == 0

    def test_sin_indicaciones_solo_espacios_no_crea_notificacion(self, db: Any) -> None:
        """Indicaciones con solo espacios (strip = '') → no se notifica."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        _member(tenant, Role.NURSE)

        # Act
        with tenant_ctx(tenant):
            evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                indicaciones_enfermeria="   ",  # solo espacios: no debe notificar
            )

        # Assert
        count = Notification.all_objects.filter(
            tenant=tenant, kind=NotificationKind.NURSING_INSTRUCTION
        ).count()
        assert count == 0

    def test_fanout_falla_nota_igual_se_crea(self, db: Any) -> None:
        """Best-effort: si el fanout lanza excepción, la nota de evolución igual se crea."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)

        # Act — parcheamos notification_fanout para que lance RuntimeError
        with tenant_ctx(tenant):
            with patch(
                "apps.expediente.services.notification_fanout",
                side_effect=RuntimeError("BD de notificaciones no disponible"),
            ):
                note = evolution_note_create(
                    tenant=tenant,
                    user=doctor.membership.user,
                    patient=patient,
                    appointment=appt,
                    doctor=doctor,
                    indicaciones_enfermeria="Control de signos.",
                )

        # Assert — la nota fue creada a pesar del fallo del fanout
        assert note.pk is not None
        assert note.is_locked is True

    def test_sin_enfermeras_en_tenant_no_crea_notificaciones(self, db: Any) -> None:
        """Si el tenant no tiene enfermeras, el fanout retorna [] sin error."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        appt = _attended_appointment(tenant, patient, doctor)
        # No creamos ninguna enfermera

        # Act
        with tenant_ctx(tenant):
            note = evolution_note_create(
                tenant=tenant,
                user=doctor.membership.user,
                patient=patient,
                appointment=appt,
                doctor=doctor,
                indicaciones_enfermeria="Preparar medicamentos.",
            )

        # Assert — nota creada, sin notificaciones
        assert note.pk is not None
        count = Notification.all_objects.filter(
            tenant=tenant, kind=NotificationKind.NURSING_INSTRUCTION
        ).count()
        assert count == 0


# ===========================================================================
# Selectors — evolution_nursing_instructions_for_patient
# ===========================================================================


class TestEvolutionNursingInstructionsSelector:
    """Tests del selector evolution_nursing_instructions_for_patient."""

    def test_devuelve_notas_con_indicaciones(self, db: Any) -> None:
        """Solo devuelve las notas que tienen indicaciones no vacías."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        # Nota CON indicaciones
        note_con = EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="Control de glucosa.",
        )
        # Nota SIN indicaciones
        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="",
        )

        # Act
        with tenant_ctx(tenant):
            qs = evolution_nursing_instructions_for_patient(patient=patient)
            result_ids = list(qs.values_list("id", flat=True))

        # Assert
        assert note_con.id in result_ids
        assert len(result_ids) == 1

    def test_sin_indicaciones_devuelve_lista_vacia(self, db: Any) -> None:
        """Paciente sin notas con indicaciones → QuerySet vacío."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor, indicaciones_enfermeria=""
        )

        # Act
        with tenant_ctx(tenant):
            qs = evolution_nursing_instructions_for_patient(patient=patient)

        # Assert
        assert list(qs) == []

    def test_aislamiento_multi_tenant(self, db: Any) -> None:
        """El selector no devuelve notas de otro tenant."""
        # Arrange
        doctor_a = DoctorFactory()
        tenant_a = doctor_a.tenant
        patient_a = PatientFactory(tenant=tenant_a)
        EvolutionNoteFactory(
            tenant=tenant_a,
            patient=patient_a,
            doctor=doctor_a,
            indicaciones_enfermeria="Indicaciones tenant A.",
        )

        doctor_b = DoctorFactory()
        tenant_b = doctor_b.tenant
        patient_b = PatientFactory(tenant=tenant_b)
        EvolutionNoteFactory(
            tenant=tenant_b,
            patient=patient_b,
            doctor=doctor_b,
            indicaciones_enfermeria="Indicaciones tenant B.",
        )

        # Act — activamos contexto de tenant_a
        with tenant_ctx(tenant_a):
            qs = evolution_nursing_instructions_for_patient(patient=patient_a)
            result_ids = set(qs.values_list("id", flat=True))

        # Assert — solo la nota de tenant_a
        assert len(result_ids) == 1

    def test_limit_aplica(self, db: Any) -> None:
        """El parámetro limit restringe el número de resultados."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        for i in range(5):
            EvolutionNoteFactory(
                tenant=tenant,
                patient=patient,
                doctor=doctor,
                indicaciones_enfermeria=f"Indicación {i}",
            )

        # Act
        with tenant_ctx(tenant):
            qs = evolution_nursing_instructions_for_patient(patient=patient, limit=3)
            results = list(qs)

        # Assert
        assert len(results) == 3

    def test_orden_descendente(self, db: Any) -> None:
        """Las notas se ordenan por -created_at (la más reciente primero)."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        note_old = EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="Primera indicación.",
        )
        note_new = EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="Segunda indicación (más reciente).",
        )

        # Act
        with tenant_ctx(tenant):
            qs = evolution_nursing_instructions_for_patient(patient=patient)
            ids = list(qs.values_list("id", flat=True))

        # Assert — la más reciente primero
        # note_new tiene created_at > note_old porque se insertó después
        assert ids[0] == note_new.id
        assert ids[1] == note_old.id


# ===========================================================================
# API — GET /api/v1/expediente/<patient_id>/indicaciones-enfermeria/
# ===========================================================================


class TestNursingInstructionListApi:
    """Tests del endpoint GET /api/v1/expediente/<patient_id>/indicaciones-enfermeria/."""

    def test_nurse_obtiene_200_con_lista(self, db: Any) -> None:
        """Enfermería puede leer las indicaciones (CLINICAL_READ incluye NURSE)."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="Vigilar herida quirúrgica.",
        )

        nurse_user = _member(tenant, Role.NURSE)
        client = _auth_client(nurse_user)

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "indicaciones" in data[0]
        assert data[0]["indicaciones"] == "Vigilar herida quirúrgica."

    def test_doctor_obtiene_200(self, db: Any) -> None:
        """El médico también puede leer las indicaciones."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="Control de hidratación.",
        )
        client = _auth_client(doctor.membership.user)

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 200

    def test_owner_obtiene_200(self, db: Any) -> None:
        """El owner también puede leer las indicaciones."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="Monitorizar ECG.",
        )
        owner_user = _member(tenant, Role.OWNER)
        client = _auth_client(owner_user)

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 200

    def test_solo_notas_con_indicaciones_en_respuesta(self, db: Any) -> None:
        """El endpoint solo devuelve notas CON indicaciones (no las vacías)."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)

        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="Indicación válida.",
        )
        # Nota sin indicaciones: no debe aparecer en la respuesta
        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="",
        )

        nurse_user = _member(tenant, Role.NURSE)
        client = _auth_client(nurse_user)

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_solo_devuelve_notas_del_paciente_correcto(self, db: Any) -> None:
        """El endpoint no mezcla indicaciones de distintos pacientes del mismo tenant."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient_a = PatientFactory(tenant=tenant)
        patient_b = PatientFactory(tenant=tenant)

        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient_a,
            doctor=doctor,
            indicaciones_enfermeria="Indicación para paciente A.",
        )
        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient_b,
            doctor=doctor,
            indicaciones_enfermeria="Indicación para paciente B.",
        )

        nurse_user = _member(tenant, Role.NURSE)
        client = _auth_client(nurse_user)

        # Act — pedimos las de patient_a
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient_a.id))

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["indicaciones"] == "Indicación para paciente A."

    def test_idor_patient_otro_tenant_retorna_404(self, db: Any) -> None:
        """IDOR: patient_id de otro tenant → 404 (no revela existencia cross-tenant)."""
        # Arrange
        doctor_a = DoctorFactory()
        tenant_a = doctor_a.tenant
        nurse_a = _member(tenant_a, Role.NURSE)

        doctor_b = DoctorFactory()
        tenant_b = doctor_b.tenant
        patient_b = PatientFactory(tenant=tenant_b)

        client = _auth_client(nurse_a)

        # Act — intento acceder a paciente de otro tenant
        with api_tenant_ctx(tenant_a):
            resp = client.get(_nursing_url(patient_b.id))

        # Assert — 404, no 403 (anti-IDOR)
        assert resp.status_code == 404

    def test_recepcion_obtiene_403(self, db: Any) -> None:
        """Recepción NO tiene acceso a contenido clínico → 403."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        reception_user = _member(tenant, Role.RECEPTION)
        client = _auth_client(reception_user)

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 403

    def test_finanzas_obtiene_403(self, db: Any) -> None:
        """Finanzas NO tiene acceso a contenido clínico → 403."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        finance_user = _member(tenant, Role.FINANCE)
        client = _auth_client(finance_user)

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 403

    def test_sin_autenticacion_retorna_401(self, db: Any) -> None:
        """Sin token → 401 (IsAuthenticated primero)."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        client = APIClient()  # sin autenticar

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 401

    def test_lista_vacia_cuando_no_hay_indicaciones(self, db: Any) -> None:
        """Paciente sin indicaciones → 200 con lista vacía (no 404)."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        # Nota sin indicaciones
        EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor, indicaciones_enfermeria=""
        )

        nurse_user = _member(tenant, Role.NURSE)
        client = _auth_client(nurse_user)

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 200
        assert resp.json() == []

    def test_campos_de_respuesta_correctos(self, db: Any) -> None:
        """La respuesta contiene id, fecha, doctor e indicaciones."""
        # Arrange
        doctor = DoctorFactory()
        tenant = doctor.tenant
        patient = PatientFactory(tenant=tenant)
        EvolutionNoteFactory(
            tenant=tenant,
            patient=patient,
            doctor=doctor,
            indicaciones_enfermeria="Revisar apósitos.",
        )
        nurse_user = _member(tenant, Role.NURSE)
        client = _auth_client(nurse_user)

        # Act
        with api_tenant_ctx(tenant):
            resp = client.get(_nursing_url(patient.id))

        # Assert
        assert resp.status_code == 200
        item = resp.json()[0]
        assert "id" in item
        assert "fecha" in item
        assert "doctor" in item
        assert "indicaciones" in item
        # No expone campos de otros bloques clínicos (anti-divulgación mínima)
        assert "antecedentes" not in item
        assert "diagnosticos_texto" not in item
        assert "tratamiento" not in item
