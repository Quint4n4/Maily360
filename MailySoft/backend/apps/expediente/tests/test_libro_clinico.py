"""
Tests del Libro Clínico del Paciente — Fase 1 (Backend).

Cubre (objetivo ≥ 80% en lógica de negocio):

1. book_build (selector):
   - Armado correcto: portada, HC viva, alergias, capítulos.
   - Orden más reciente primero (D-LIB-3).
   - Paginación: capitulos_count, total_pages, page clampeo.
   - Aislamiento multi-tenant: un paciente de otro tenant no aparece.
   - Sin N+1: cota de queries con django_assert_num_queries.

2. PatientBookApi (GET /expediente/<patient_id>/libro/):
   - 200 con estructura correcta (campos del contrato de API).
   - 401 sin autenticación.
   - 403/404 para paciente de otro tenant (anti-IDOR).
   - Permisos: recepción y finanzas → 403; clínicos → 200.
   - Paginación: ?page y ?page_size respetados.
   - Bitácora: PATIENT_BOOK_VIEW registrado en AuditLog.
   - Recetas por capítulo: resumen ligero (sin PDF).
   - Capítulo sin signos vitales: signos=null.
   - Capítulo sin recetas: recetas=[].

Patrón: AAA. factory_boy para datos.
Tenant context parcheado igual que el resto de la app expediente.
"""

from typing import Any
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.expediente.selectors import (
    BOOK_DEFAULT_PAGE_SIZE,
    BOOK_MAX_PAGE_SIZE,
    PatientBook,
    book_build,
)
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AddendumFactory,
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
# URL del endpoint
# ---------------------------------------------------------------------------

_LIBRO_URL_TMPL = "/api/v1/expediente/{patient_id}/libro/"


def _libro_url(patient_id: Any) -> str:
    return _LIBRO_URL_TMPL.format(patient_id=patient_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _member(tenant: Any, role: str = TenantMembership.Role.DOCTOR) -> Any:
    """Crea un user con membresía activa en el tenant dado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ===========================================================================
# 1. book_build — selector
# ===========================================================================


class TestBookBuildSelector:
    """Tests del selector book_build (capa de datos — sin HTTP)."""

    def test_devuelve_patient_book(self, db: Any) -> None:
        """book_build devuelve una instancia PatientBook con los datos del paciente."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build(patient=patient)

        assert isinstance(result, PatientBook)
        assert result.patient.id == patient.id

    def test_portada_incluye_clinic_settings(self, db: Any) -> None:
        """clinic_settings se incluye en la portada cuando existe."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        settings = ClinicSettingsFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build(patient=patient)

        assert result.clinic_settings is not None
        assert result.clinic_settings.id == settings.id

    def test_portada_clinic_settings_none_si_no_existe(self, db: Any) -> None:
        """clinic_settings es None cuando la clínica no tiene configuración."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build(patient=patient)

        assert result.clinic_settings is None

    def test_historia_clinica_viva(self, db: Any) -> None:
        """medical_history es la HC actual del paciente cuando existe."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        hc = MedicalHistoryFactory(tenant=tenant, patient=patient, created_by=user)

        with tenant_ctx(tenant):
            result = book_build(patient=patient)

        assert result.medical_history is not None
        assert result.medical_history.id == hc.id

    def test_historia_clinica_none_si_no_existe(self, db: Any) -> None:
        """medical_history es None cuando el paciente no tiene HC."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build(patient=patient)

        assert result.medical_history is None

    def test_alergias_vigentes_incluidas(self, db: Any) -> None:
        """Las alergias vigentes del paciente aparecen en el libro."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        AllergyFactory(tenant=tenant, patient=patient, created_by=user, is_active=True)
        AllergyFactory(tenant=tenant, patient=patient, created_by=user, is_active=True)

        with tenant_ctx(tenant):
            result = book_build(patient=patient)

        assert result.allergies.count() == 2

    def test_alergias_resueltas_no_incluidas(self, db: Any) -> None:
        """Las alergias resueltas (is_active=False) NO aparecen en el libro."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        AllergyFactory(tenant=tenant, patient=patient, created_by=user, is_active=True)
        AllergyFactory(tenant=tenant, patient=patient, created_by=user, is_active=False)

        with tenant_ctx(tenant):
            result = book_build(patient=patient)

        assert result.allergies.count() == 1

    def test_sin_evoluciones_capitulos_vacio(self, db: Any) -> None:
        """Un paciente sin evoluciones devuelve capitulos=[], count=0."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build(patient=patient)

        assert result.capitulos == []
        assert result.capitulos_count == 0
        assert result.total_pages == 1  # Paginator devuelve 1 aunque esté vacío

    def test_orden_mas_reciente_primero(self, db: Any) -> None:
        """Las evoluciones se ordenan más reciente primero (D-LIB-3)."""
        import datetime

        from django.utils import timezone

        tenant = TenantFactory()
        user = UserFactory()
        doctor_user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory

        doctor = DoctorFactory(tenant=tenant)
        # Crear evoluciones en orden cronológico (la primera es la más antigua).
        appt1 = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            status="attended", starts_at=timezone.now() - datetime.timedelta(days=10),
        )
        appt2 = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            status="attended", starts_at=timezone.now() - datetime.timedelta(days=5),
        )
        appt3 = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            status="attended", starts_at=timezone.now() - datetime.timedelta(days=1),
        )

        import datetime as dt
        now = timezone.now()
        evo_antigua = EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt1, created_by=user,
        )
        evo_media = EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt2, created_by=user,
        )
        evo_reciente = EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt3, created_by=user,
        )
        # Ajustar created_at para garantizar el orden.
        type(evo_antigua).objects  # noqa — solo para acceder
        from apps.expediente.models import EvolutionNote
        EvolutionNote.objects.filter(pk=evo_antigua.pk).update(
            created_at=now - datetime.timedelta(days=10)
        )
        EvolutionNote.objects.filter(pk=evo_media.pk).update(
            created_at=now - datetime.timedelta(days=5)
        )
        EvolutionNote.objects.filter(pk=evo_reciente.pk).update(
            created_at=now - datetime.timedelta(days=1)
        )

        with tenant_ctx(tenant):
            result = book_build(patient=patient, page=1, page_size=10)

        ids = [c.id for c in result.capitulos]
        # El más reciente debe ser el primero.
        assert ids[0] == evo_reciente.pk
        assert ids[-1] == evo_antigua.pk

    def test_paginacion_capitulos_count(self, db: Any) -> None:
        """capitulos_count refleja el total de evoluciones, no solo la página actual."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)

        # Crear 5 evoluciones.
        for i in range(5):
            appt = AppointmentFactory(
                tenant=tenant, patient=patient, doctor=doctor, status="attended",
            )
            EvolutionNoteFactory(
                tenant=tenant, patient=patient, doctor=doctor,
                appointment=appt, created_by=user,
            )

        with tenant_ctx(tenant):
            result = book_build(patient=patient, page=1, page_size=3)

        assert result.capitulos_count == 5
        assert result.total_pages == 2
        assert len(result.capitulos) == 3

    def test_paginacion_segunda_pagina(self, db: Any) -> None:
        """La segunda página devuelve las evoluciones restantes."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)

        for i in range(5):
            appt = AppointmentFactory(
                tenant=tenant, patient=patient, doctor=doctor, status="attended",
            )
            EvolutionNoteFactory(
                tenant=tenant, patient=patient, doctor=doctor,
                appointment=appt, created_by=user,
            )

        with tenant_ctx(tenant):
            result = book_build(patient=patient, page=2, page_size=3)

        assert result.page == 2
        assert len(result.capitulos) == 2  # 5 - 3 = 2 en la página 2

    def test_page_size_cota_maxima(self, db: Any) -> None:
        """page_size no puede superar BOOK_MAX_PAGE_SIZE (anti-DoS)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            result = book_build(patient=patient, page=1, page_size=9999)

        assert result.page_size == BOOK_MAX_PAGE_SIZE

    def test_page_clampeo_a_rango_valido(self, db: Any) -> None:
        """Una página fuera de rango se clampa al límite válido."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user,
        )

        with tenant_ctx(tenant):
            # Pedir página 999 cuando solo hay 1 página.
            result = book_build(patient=patient, page=999, page_size=10)

        assert result.page == 1
        assert len(result.capitulos) == 1

    def test_aislamiento_multi_tenant(self, db: Any) -> None:
        """Las evoluciones de otro tenant NO aparecen en el libro."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        patient_a = PatientFactory(tenant=tenant_a)
        patient_b = PatientFactory(tenant=tenant_b)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor_b = DoctorFactory(tenant=tenant_b)
        appt_b = AppointmentFactory(
            tenant=tenant_b, patient=patient_b, doctor=doctor_b, status="attended",
        )
        # Esta evolución pertenece a tenant_b.
        EvolutionNoteFactory(
            tenant=tenant_b, patient=patient_b, doctor=doctor_b,
            appointment=appt_b, created_by=user,
        )

        # Consultar el libro del paciente del tenant_a — no debe ver la evolución de B.
        with tenant_ctx(tenant_a):
            result = book_build(patient=patient_a)

        assert result.capitulos_count == 0
        assert result.capitulos == []


class TestBookBuildAntiN1:
    """Cota de queries (anti N+1) para book_build con datos reales."""

    def test_queries_acotadas_con_evoluciones(
        self, db: Any, django_assert_num_queries: Any
    ) -> None:
        """book_build debe usar un número fijo de queries sin importar la cantidad
        de evoluciones en la página (anti-N+1 por prefetch_related).

        Estructura de queries observada en la implementación actual (10 queries):
          1. clinic_settings                 (1 query)
          2. medical_history                 (1 query)
          3. COUNT evoluciones (paginación)  (1 query)
          4. evoluciones de la página        (1 query — select_related doctor/vitals)
          5. prefetch addenda                (1 query)
          6. prefetch addenda__author        (1 query — users de addenda)
          7. prefetch diagnoses              (1 query)
          8. prefetch images                 (1 query)
          9. prefetch prescriptions          (1 query)
         10. prefetch prescriptions__items   (1 query)

        TOTAL: 10 queries fijas sin importar cuántas evoluciones haya en la página.
        La allergies QuerySet es lazy y se evalúa después en serialización (fuera
        de esta ventana). La cota de 15 acepta variaciones de implementación (RLS,
        middleware, etc.) sin ser tan amplia que deje pasar un N+1 real.
        """
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicSettingsFactory(tenant=tenant)
        MedicalHistoryFactory(tenant=tenant, patient=patient, created_by=user)
        AllergyFactory(tenant=tenant, patient=patient, created_by=user, is_active=True)

        from tests.factories import AppointmentFactory, DoctorFactory, VitalSignsRecordFactory
        doctor = DoctorFactory(tenant=tenant)

        # Crear 3 evoluciones, cada una con signos, imagen, receta, addendum y diagnóstico.
        for i in range(3):
            appt = AppointmentFactory(
                tenant=tenant, patient=patient, doctor=doctor, status="attended",
            )
            signos = VitalSignsRecordFactory(
                tenant=tenant, patient=patient, created_by=user,
            )
            evo = EvolutionNoteFactory(
                tenant=tenant, patient=patient, doctor=doctor,
                appointment=appt, created_by=user, vital_signs=signos,
            )
            AddendumFactory(tenant=tenant, evolution=evo, author=user)
            DiagnosisFactory(tenant=tenant, patient=patient, evolution=evo, created_by=user)
            rx = PrescriptionFactory(
                tenant=tenant, patient=patient, doctor=doctor,
                evolution_note=evo, created_by=user,
            )
            PrescriptionItemFactory(prescription=rx, tenant=tenant, created_by=user)

        # La cota de queries debe ser fija (≤ 15), independientemente del número de
        # evoluciones en la página. El test verifica que NO hay N+1: si lo hubiera,
        # con 3 evoluciones ejecutaríamos 3×N queries adicionales.
        with tenant_ctx(tenant):
            with django_assert_num_queries(10):
                result = book_build(patient=patient, page=1, page_size=10)

        # Verificar que los datos estén disponibles (prefetch funcionó).
        assert len(result.capitulos) == 3
        for cap in result.capitulos:
            # Si hay N+1, estos accesos dispararían queries adicionales.
            # django_assert_num_queries ya habrá fallado antes de llegar aquí.
            _ = list(cap.addenda.all())
            _ = list(cap.diagnoses.all())
            _ = list(cap.images.all())
            _ = list(cap.prescriptions.all())


# ===========================================================================
# 2. PatientBookApi — endpoint HTTP
# ===========================================================================


class TestPatientBookApiAuth:
    """Tests de autenticación y permisos del endpoint GET /libro/."""

    def test_401_sin_token(self, db: Any) -> None:
        """Sin autenticación → 401."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = APIClient()

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 401

    def test_404_paciente_otro_tenant(self, db: Any) -> None:
        """Un patient_id de otro tenant → 404 (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        user = _member(tenant_a, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant_a):
            resp = client.get(_libro_url(patient_b.id))

        assert resp.status_code == 404

    def test_403_role_recepcion(self, db: Any) -> None:
        """Rol recepción → 403 (D-LIB-6)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.RECEPTION)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 403

    def test_403_role_finanzas(self, db: Any) -> None:
        """Rol finanzas → 403 (D-LIB-6)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.FINANCE)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 403

    def test_200_role_doctor(self, db: Any) -> None:
        """Rol doctor → 200."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 200

    def test_200_role_nurse(self, db: Any) -> None:
        """Rol enfermería → 200 (CLINICAL_READ)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.NURSE)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 200

    def test_200_role_owner(self, db: Any) -> None:
        """Rol owner → 200."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.OWNER)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 200

    def test_200_role_readonly(self, db: Any) -> None:
        """Rol readonly → 200 (CLINICAL_READ)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.READONLY)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 200


class TestPatientBookApiEstructura:
    """Tests de la estructura del JSON devuelto."""

    def test_estructura_raiz_del_libro(self, db: Any) -> None:
        """El JSON de respuesta contiene todos los campos del contrato de API."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 200
        data = resp.json()

        # Campos del contrato de API (plan §3).
        assert "paciente" in data
        assert "clinica" in data
        assert "historia_clinica" in data
        assert "alergias" in data
        assert "capitulos_count" in data
        assert "total_pages" in data
        assert "page" in data
        assert "page_size" in data
        assert "capitulos" in data

    def test_paciente_tiene_campos_portada(self, db: Any) -> None:
        """El campo paciente expone los campos de portada necesarios."""
        tenant = TenantFactory()
        patient = PatientFactory(
            tenant=tenant, first_name="Ana", paternal_surname="García",
        )
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        paciente = resp.json()["paciente"]
        assert paciente["id"] == str(patient.id)
        assert "full_name" in paciente
        assert "record_number" in paciente
        assert "date_of_birth" in paciente
        assert "sex" in paciente

    def test_clinica_none_si_no_hay_configuracion(self, db: Any) -> None:
        """clinica es null cuando el tenant no tiene ClinicSettings."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.json()["clinica"] is None

    def test_clinica_incluida_cuando_existe(self, db: Any) -> None:
        """clinica se serializa cuando el tenant tiene ClinicSettings."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        ClinicSettingsFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.json()["clinica"] is not None
        assert "commercial_name" in resp.json()["clinica"]

    def test_capitulos_vacios_sin_evoluciones(self, db: Any) -> None:
        """Un paciente sin evoluciones devuelve capitulos=[]."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        data = resp.json()
        assert data["capitulos"] == []
        assert data["capitulos_count"] == 0

    def test_capitulo_tiene_campos_soap(self, db: Any) -> None:
        """Cada capítulo expone los campos de la estructura SOAP del libro."""
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user_actor,
        )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 200
        capitulos = resp.json()["capitulos"]
        assert len(capitulos) == 1

        cap = capitulos[0]
        assert "id" in cap
        assert "fecha" in cap
        assert "doctor" in cap
        assert "signos" in cap
        assert "subjetivo" in cap
        assert "objetivo" in cap
        assert "exploracion" in cap
        assert "analisis" in cap
        assert "plan" in cap
        assert "imagenes" in cap
        assert "recetas" in cap
        assert "addenda" in cap

    def test_signos_none_cuando_no_hay_vitales(self, db: Any) -> None:
        """signos es null cuando la nota no tiene VitalSignsRecord asociado."""
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user_actor,
            vital_signs=None,
        )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        cap = resp.json()["capitulos"][0]
        assert cap["signos"] is None

    def test_signos_incluidos_cuando_existen(self, db: Any) -> None:
        """signos se serializa cuando la nota tiene VitalSignsRecord."""
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        signos = VitalSignsRecordFactory(
            tenant=tenant, patient=patient, created_by=user_actor,
        )
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user_actor,
            vital_signs=signos,
        )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        cap = resp.json()["capitulos"][0]
        assert cap["signos"] is not None
        assert "weight_kg" in cap["signos"]
        assert "measured_at" in cap["signos"]

    def test_recetas_vacias_sin_receta_vinculada(self, db: Any) -> None:
        """recetas=[] cuando la nota no tiene recetas vinculadas."""
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user_actor,
        )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        cap = resp.json()["capitulos"][0]
        assert cap["recetas"] == []

    def test_recetas_resumen_ligero(self, db: Any) -> None:
        """recetas incluye id, folio, status e items_resumen (sin PDF)."""
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        evo = EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user_actor,
        )
        rx = PrescriptionFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            evolution_note=evo, created_by=user_actor,
        )
        PrescriptionItemFactory(
            prescription=rx, tenant=tenant, created_by=user_actor,
            medication_name="Amoxicilina", dose="500 mg",
        )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        cap = resp.json()["capitulos"][0]
        assert len(cap["recetas"]) == 1
        receta = cap["recetas"][0]
        assert "id" in receta
        assert "folio" in receta
        assert "status" in receta
        assert "issued_at" in receta
        assert "items_resumen" in receta
        assert len(receta["items_resumen"]) == 1
        # El resumen incluye el nombre del medicamento.
        assert "Amoxicilina" in receta["items_resumen"][0]

    def test_diagnosticos_vinculados_a_evolucion(self, db: Any) -> None:
        """Los diagnósticos vinculados a la evolución aparecen en el capítulo."""
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        evo = EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user_actor,
        )
        DiagnosisFactory(
            tenant=tenant, patient=patient, evolution=evo,
            created_by=user_actor, description="Hipertensión esencial",
        )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        cap = resp.json()["capitulos"][0]
        assert len(cap["analisis"]["diagnosticos"]) == 1
        assert cap["analisis"]["diagnosticos"][0]["description"] == "Hipertensión esencial"

    def test_diagnosticos_sin_fk_evolucion_no_aparecen_en_capitulo(
        self, db: Any
    ) -> None:
        """Diagnósticos del paciente sin FK a evolución NO aparecen en ningún capítulo.

        (Decisión documentada: diagnósticos globales del paciente son para
        Fase 2/sección aparte del libro. Ver docstring de book_build.)
        """
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user_actor,
        )
        # Diagnóstico sin FK de evolución.
        DiagnosisFactory(
            tenant=tenant, patient=patient, evolution=None,
            created_by=user_actor, description="Diabetes tipo 2",
        )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        cap = resp.json()["capitulos"][0]
        # El diagnóstico global no debe aparecer en el capítulo.
        assert cap["analisis"]["diagnosticos"] == []

    def test_addenda_en_capitulo(self, db: Any) -> None:
        """Los addenda de la evolución se incluyen en el capítulo."""
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)
        appt = AppointmentFactory(
            tenant=tenant, patient=patient, doctor=doctor, status="attended",
        )
        evo = EvolutionNoteFactory(
            tenant=tenant, patient=patient, doctor=doctor,
            appointment=appt, created_by=user_actor,
        )
        AddendumFactory(
            tenant=tenant, evolution=evo, author=user_actor,
            body="Addendum de prueba.",
        )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        cap = resp.json()["capitulos"][0]
        assert len(cap["addenda"]) == 1
        assert cap["addenda"][0]["body"] == "Addendum de prueba."


class TestPatientBookApiPaginacion:
    """Tests de paginación del endpoint."""

    def test_params_page_y_page_size(self, db: Any) -> None:
        """Los parámetros ?page y ?page_size se reflejan en la respuesta."""
        tenant = TenantFactory()
        user_actor = UserFactory()
        patient = PatientFactory(tenant=tenant)

        from tests.factories import AppointmentFactory, DoctorFactory
        doctor = DoctorFactory(tenant=tenant)

        for i in range(5):
            appt = AppointmentFactory(
                tenant=tenant, patient=patient, doctor=doctor, status="attended",
            )
            EvolutionNoteFactory(
                tenant=tenant, patient=patient, doctor=doctor,
                appointment=appt, created_by=user_actor,
            )

        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id) + "?page=2&page_size=3")

        data = resp.json()
        assert resp.status_code == 200
        assert data["page"] == 2
        assert data["page_size"] == 3
        assert data["capitulos_count"] == 5
        assert data["total_pages"] == 2
        assert len(data["capitulos"]) == 2  # 5 - 3*1 = 2

    def test_page_size_max_limitado(self, db: Any) -> None:
        """page_size no puede superar BOOK_MAX_PAGE_SIZE."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(
                _libro_url(patient.id) + f"?page_size={BOOK_MAX_PAGE_SIZE + 100}"
            )

        assert resp.status_code == 200
        assert resp.json()["page_size"] == BOOK_MAX_PAGE_SIZE

    def test_page_invalida_sin_error(self, db: Any) -> None:
        """Un ?page con valor no numérico no causa 500 — cae al default."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id) + "?page=abc")

        assert resp.status_code == 200
        assert resp.json()["page"] == 1


class TestPatientBookApiBitacora:
    """Tests de auditoría NOM-024 del endpoint."""

    def test_registra_patient_book_view(self, db: Any) -> None:
        """Cada GET al libro registra PATIENT_BOOK_VIEW en AuditLog."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        logs_antes = AuditLog.all_objects.filter(
            action=ActionType.PATIENT_BOOK_VIEW
        ).count()

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 200
        logs_despues = AuditLog.all_objects.filter(
            action=ActionType.PATIENT_BOOK_VIEW
        ).count()
        assert logs_despues == logs_antes + 1

    def test_resource_repr_es_record_number(self, db: Any) -> None:
        """resource_repr del AuditLog es el record_number del paciente (no-PII)."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.DOCTOR)
        client = _auth_client(user)

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 200
        log = (
            AuditLog.all_objects.filter(
                action=ActionType.PATIENT_BOOK_VIEW,
                resource_id=patient.id,
            )
            .order_by("-created_at")
            .first()
        )
        assert log is not None
        assert log.resource_repr == patient.record_number

    def test_no_registra_para_403(self, db: Any) -> None:
        """Un acceso rechazado (403) NO genera entrada en AuditLog."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        user = _member(tenant, role=TenantMembership.Role.RECEPTION)
        client = _auth_client(user)

        logs_antes = AuditLog.all_objects.filter(
            action=ActionType.PATIENT_BOOK_VIEW
        ).count()

        with api_tenant_ctx(tenant):
            resp = client.get(_libro_url(patient.id))

        assert resp.status_code == 403
        logs_despues = AuditLog.all_objects.filter(
            action=ActionType.PATIENT_BOOK_VIEW
        ).count()
        assert logs_despues == logs_antes  # Sin cambio.
