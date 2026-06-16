"""
Tests de la app expediente — sub-fase A1.

Cubre (objetivo ≥ 80% en lógica de negocio):
- services.allergy_create: camino feliz, sustancia vacía, severidad inválida,
  paciente de otro tenant.
- services.allergy_resolve: baja lógica (is_active=False), idempotente,
  sin borrado físico (D-EC-5).
- selectors.allergy_get / allergy_list: filtrado por tenant, only_active.
- Multi-tenant / IDOR: alergias de otro tenant devuelven 404, no datos cruzados.
- Permisos por rol: recepción y finanzas no pueden crear/resolver alergias;
  GET sí está permitido para todos (bandera de seguridad).
- Validación estricta (D-EC-7): campos desconocidos → 400; choices inválidos → 400.
- Patient NOM-004: acepta valores válidos de choices; rechaza choices inválidos.
- APIs: 401 sin token; 404 para paciente/alergia de otro tenant; 201 en creación;
  204 en resolve; listado correcto.

Patrón: AAA. factory_boy para datos. Mockeo de tenant igual que notificaciones.
"""

import uuid as uuid_module
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.expediente.models import Allergy, Severity
from apps.expediente.selectors import allergy_get, allergy_list
from apps.expediente.services import allergy_create, allergy_resolve
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.pacientes.models import BloodType, Education, MaritalStatus, Patient
from apps.tenancy.models import TenantMembership
from tests.factories import (
    AllergyFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def _allergy_list_url(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/alergias/"


def _allergy_resolve_url(allergy_id: Any) -> str:
    return f"/api/v1/expediente/alergias/{allergy_id}/"


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
# services.allergy_create
# ===========================================================================


class TestAllergyCreate:
    """Tests del service allergy_create."""

    def test_crea_alergia_feliz(self, db: Any) -> None:
        """allergy_create crea y devuelve una alergia vigente."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        allergy = allergy_create(
            tenant=tenant,
            user=user,
            patient=patient,
            substance="Penicilina",
            reaction="Urticaria generalizada",
            severity=Severity.MODERADA,
        )

        assert allergy.pk is not None
        assert allergy.substance == "Penicilina"
        assert allergy.severity == "moderada"
        assert allergy.is_active is True
        assert allergy.tenant_id == tenant.id
        assert allergy.patient_id == patient.id

    def test_sustancia_vacia_falla(self, db: Any) -> None:
        """Una sustancia vacía (solo espacios) lanza ValidationError."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError, match="vacía"):
            allergy_create(
                tenant=tenant,
                user=user,
                patient=patient,
                substance="   ",
            )

    def test_severity_invalida_falla(self, db: Any) -> None:
        """Una severidad fuera de los choices lanza ValidationError (D-EC-7)."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError, match="inválida"):
            allergy_create(
                tenant=tenant,
                user=user,
                patient=patient,
                substance="Aspirina",
                severity="extrema",  # no existe en Severity
            )

    def test_paciente_otro_tenant_falla(self, db: Any) -> None:
        """Un paciente de otro tenant lanza ValidationError (defensa en profundidad)."""
        from django.core.exceptions import ValidationError

        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        patient_b = PatientFactory(tenant=tenant_b)

        with pytest.raises(ValidationError, match="no pertenece"):
            allergy_create(
                tenant=tenant_a,
                user=user,
                patient=patient_b,
                substance="Látex",
            )

    def test_sin_severidad_ni_reaccion_ok(self, db: Any) -> None:
        """Se puede crear una alergia solo con substance (campos opcionales)."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        allergy = allergy_create(
            tenant=tenant,
            user=user,
            patient=patient,
            substance="Polen",
        )

        assert allergy.reaction == ""
        assert allergy.severity == ""


# ===========================================================================
# services.allergy_resolve  (D-EC-5: sin borrado físico)
# ===========================================================================


class TestAllergyResolve:
    """Tests del service allergy_resolve (baja lógica)."""

    def test_resolve_pone_inactive(self, db: Any) -> None:
        """allergy_resolve pone is_active=False sin borrar el registro."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient)

        assert allergy.is_active is True

        resolved = allergy_resolve(allergy=allergy, user=user)

        assert resolved.is_active is False
        # El registro sigue en la BD (D-EC-5).
        assert Allergy.all_objects.filter(pk=allergy.pk).exists()

    def test_resolve_es_idempotente(self, db: Any) -> None:
        """Resolver una alergia ya resuelta no cambia nada ni lanza error."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient, is_active=False)

        resolved = allergy_resolve(allergy=allergy, user=user)

        assert resolved.is_active is False

    def test_no_borrado_fisico(self, db: Any) -> None:
        """Después de resolver, el registro persiste en la BD (nunca DELETE real)."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient)
        allergy_id = allergy.pk

        allergy_resolve(allergy=allergy, user=user)

        # El registro existe, solo is_active=False.
        saved = Allergy.all_objects.get(pk=allergy_id)
        assert saved.is_active is False


# ===========================================================================
# selectors
# ===========================================================================


class TestAllergySelectors:
    """Tests de allergy_get y allergy_list."""

    def test_allergy_get_propio(self, db: Any) -> None:
        """allergy_get retorna la alergia del tenant activo."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient)

        with tenant_ctx(tenant):
            found = allergy_get(allergy_id=allergy.id)

        assert found.pk == allergy.pk

    def test_allergy_get_otro_tenant_raises(self, db: Any) -> None:
        """allergy_get de otro tenant lanza DoesNotExist → la view devuelve 404."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        allergy_b = AllergyFactory(tenant=tenant_b, patient=patient_b)

        with tenant_ctx(tenant_a):
            with pytest.raises(Allergy.DoesNotExist):
                allergy_get(allergy_id=allergy_b.id)

    def test_allergy_list_solo_activas(self, db: Any) -> None:
        """allergy_list con only_active=True retorna solo las vigentes."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        AllergyFactory(tenant=tenant, patient=patient, is_active=True)
        AllergyFactory(tenant=tenant, patient=patient, is_active=False)

        with tenant_ctx(tenant):
            qs = allergy_list(patient=patient, only_active=True)
            assert qs.count() == 1

    def test_allergy_list_todas(self, db: Any) -> None:
        """allergy_list con only_active=False retorna vigentes y resueltas."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        AllergyFactory(tenant=tenant, patient=patient, is_active=True)
        AllergyFactory(tenant=tenant, patient=patient, is_active=False)

        with tenant_ctx(tenant):
            qs = allergy_list(patient=patient, only_active=False)
            assert qs.count() == 2

    def test_allergy_list_aislamiento_tenant(self, db: Any) -> None:
        """Las alergias de otro tenant no aparecen en el listado."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_a = PatientFactory(tenant=tenant_a)
        patient_b = PatientFactory(tenant=tenant_b)
        AllergyFactory(tenant=tenant_b, patient=patient_b)

        with tenant_ctx(tenant_a):
            qs = allergy_list(patient=patient_a, only_active=True)
            assert qs.count() == 0


# ===========================================================================
# Validación estricta D-EC-7 — serializers
# ===========================================================================


class TestAllergyInputValidation:
    """Tests de validación estricta del AllergyInputSerializer."""

    def test_campo_desconocido_da_400(self, db: Any) -> None:
        """Un campo no declarado en el serializer → 400 (D-EC-7)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _allergy_list_url(patient.id),
                data={"substance": "Penicilina", "campo_extra": "valor_trampa"},
                format="json",
            )

        assert resp.status_code == 400

    def test_severity_invalida_da_400(self, db: Any) -> None:
        """Un valor fuera de Severity.choices → 400 (D-EC-7)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _allergy_list_url(patient.id),
                data={"substance": "Aspirina", "severity": "catastrofica"},
                format="json",
            )

        assert resp.status_code == 400

    def test_substance_vacia_da_400(self, db: Any) -> None:
        """Una sustancia vacía → 400."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _allergy_list_url(patient.id),
                data={"substance": ""},
                format="json",
            )

        assert resp.status_code == 400


# ===========================================================================
# Patient NOM-004 — validación de choices
# ===========================================================================


class TestPatientNom004Choices:
    """Verifica que los choices de los campos NOM-004 del Patient son correctos."""

    def test_marital_status_choices_validos(self) -> None:
        """Los valores de MaritalStatus son los documentados en el plan §3.1."""
        valores = [c[0] for c in MaritalStatus.choices]
        assert set(valores) == {
            "soltero", "casado", "union_libre", "divorciado", "viudo", "otro"
        }

    def test_education_choices_validos(self) -> None:
        """Los valores de Education son los documentados en el plan §3.1."""
        valores = [c[0] for c in Education.choices]
        assert set(valores) == {
            "ninguna", "primaria", "secundaria", "preparatoria", "licenciatura", "posgrado"
        }

    def test_blood_type_choices_validos(self) -> None:
        """Los 8 tipos ABO/Rh + desconocido están presentes."""
        valores = [c[0] for c in BloodType.choices]
        assert set(valores) == {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "desconocido"}

    def test_patient_acepta_blood_type_valido(self, db: Any) -> None:
        """Guardar un blood_type válido en un Patient no lanza error."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        patient.blood_type = "O+"
        patient.full_clean()  # Valida choices a nivel de modelo.
        patient.save(update_fields=["blood_type", "updated_at"])
        patient.refresh_from_db()
        assert patient.blood_type == "O+"

    def test_patient_acepta_marital_status_valido(self, db: Any) -> None:
        """Guardar un marital_status válido en un Patient no lanza error."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        patient.marital_status = "casado"
        patient.full_clean()
        patient.save(update_fields=["marital_status", "updated_at"])
        patient.refresh_from_db()
        assert patient.marital_status == "casado"

    def test_patient_rechaza_marital_status_invalido(self, db: Any) -> None:
        """Un marital_status fuera de choices falla al validar (D-EC-7)."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        patient.marital_status = "polígamo"  # no existe

        with pytest.raises(ValidationError):
            patient.full_clean()

    def test_patient_rechaza_blood_type_invalido(self, db: Any) -> None:
        """Un blood_type fuera de choices falla al validar (D-EC-7)."""
        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        patient.blood_type = "Z+"  # no existe

        with pytest.raises(ValidationError):
            patient.full_clean()


# ===========================================================================
# Permisos por rol (plan §5)
# ===========================================================================


class TestAllergyPermissions:
    """Tests de la política de permisos por rol para Allergy."""

    def test_sin_token_da_401(self, db: Any, api_client: APIClient) -> None:
        """Sin autenticación → 401."""
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        resp = api_client.get(_allergy_list_url(patient.id))
        assert resp.status_code == 401

    def test_doctor_puede_crear(self, db: Any) -> None:
        """Un doctor puede crear alergias (POST)."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _allergy_list_url(patient.id),
                data={"substance": "Penicilina"},
                format="json",
            )

        assert resp.status_code == 201

    def test_nurse_puede_crear(self, db: Any) -> None:
        """Una enfermera puede crear alergias (POST)."""
        tenant = TenantFactory()
        nurse = _member(tenant, role=TenantMembership.Role.NURSE)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(nurse)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _allergy_list_url(patient.id),
                data={"substance": "Ibuprofeno"},
                format="json",
            )

        assert resp.status_code == 201

    def test_recepcion_no_puede_crear(self, db: Any) -> None:
        """Recepción no puede registrar alergias (POST → 403)."""
        tenant = TenantFactory()
        reception = _member(tenant, role=TenantMembership.Role.RECEPTION)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(reception)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _allergy_list_url(patient.id),
                data={"substance": "Penicilina"},
                format="json",
            )

        assert resp.status_code == 403

    def test_finanzas_no_puede_crear(self, db: Any) -> None:
        """Finanzas no puede registrar alergias (POST → 403)."""
        tenant = TenantFactory()
        finance = _member(tenant, role=TenantMembership.Role.FINANCE)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(finance)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _allergy_list_url(patient.id),
                data={"substance": "Penicilina"},
                format="json",
            )

        assert resp.status_code == 403

    def test_recepcion_puede_ver_alergias(self, db: Any) -> None:
        """Recepción SÍ puede listar alergias (GET → 200, bandera de seguridad)."""
        tenant = TenantFactory()
        reception = _member(tenant, role=TenantMembership.Role.RECEPTION)
        patient = PatientFactory(tenant=tenant)
        AllergyFactory(tenant=tenant, patient=patient)

        client = _auth_client(reception)
        with api_tenant_ctx(tenant):
            resp = client.get(_allergy_list_url(patient.id))

        assert resp.status_code == 200

    def test_finanzas_puede_ver_alergias(self, db: Any) -> None:
        """Finanzas SÍ puede listar alergias (GET → 200, bandera de seguridad)."""
        tenant = TenantFactory()
        finance = _member(tenant, role=TenantMembership.Role.FINANCE)
        patient = PatientFactory(tenant=tenant)
        AllergyFactory(tenant=tenant, patient=patient)

        client = _auth_client(finance)
        with api_tenant_ctx(tenant):
            resp = client.get(_allergy_list_url(patient.id))

        assert resp.status_code == 200

    def test_readonly_puede_ver_alergias(self, db: Any) -> None:
        """Solo lectura SÍ puede listar alergias (GET → 200)."""
        tenant = TenantFactory()
        ro = _member(tenant, role=TenantMembership.Role.READONLY)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(ro)
        with api_tenant_ctx(tenant):
            resp = client.get(_allergy_list_url(patient.id))

        assert resp.status_code == 200

    def test_recepcion_no_puede_resolver(self, db: Any) -> None:
        """Recepción no puede dar de baja una alergia (DELETE → 403)."""
        tenant = TenantFactory()
        reception = _member(tenant, role=TenantMembership.Role.RECEPTION)
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient)

        client = _auth_client(reception)
        with api_tenant_ctx(tenant):
            resp = client.delete(_allergy_resolve_url(allergy.id))

        assert resp.status_code == 403


# ===========================================================================
# IDOR / aislamiento multi-tenant en APIs
# ===========================================================================


class TestAllergyIsolationApis:
    """Tests de aislamiento cross-tenant en las APIs de alergias."""

    def test_list_paciente_otro_tenant_da_404(self, db: Any) -> None:
        """Listar alergias de un paciente de otro tenant → 404."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_a = _member(tenant_a, role=TenantMembership.Role.DOCTOR)
        patient_b = PatientFactory(tenant=tenant_b)

        client = _auth_client(doctor_a)
        with api_tenant_ctx(tenant_a):
            resp = client.get(_allergy_list_url(patient_b.id))

        assert resp.status_code == 404

    def test_resolve_alergia_otro_tenant_da_404(self, db: Any) -> None:
        """Resolver una alergia de otro tenant → 404 (no 403, no revelar existencia)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        doctor_a = _member(tenant_a, role=TenantMembership.Role.DOCTOR)
        patient_b = PatientFactory(tenant=tenant_b)
        allergy_b = AllergyFactory(tenant=tenant_b, patient=patient_b)

        client = _auth_client(doctor_a)
        with api_tenant_ctx(tenant_a):
            resp = client.delete(_allergy_resolve_url(allergy_b.id))

        assert resp.status_code == 404

    def test_resolve_id_inexistente_da_404(self, db: Any) -> None:
        """Un UUID que no existe → 404."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.delete(_allergy_resolve_url(uuid_module.uuid4()))

        assert resp.status_code == 404


# ===========================================================================
# APIs — flujo completo
# ===========================================================================


class TestAllergyApis:
    """Tests de flujo completo de los endpoints de alergias."""

    def test_crear_y_listar_alergia(self, db: Any) -> None:
        """POST crea la alergia; GET la lista correctamente."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            post_resp = client.post(
                _allergy_list_url(patient.id),
                data={
                    "substance": "Penicilina",
                    "reaction": "Urticaria",
                    "severity": "leve",
                },
                format="json",
            )
            assert post_resp.status_code == 201
            assert post_resp.data["substance"] == "Penicilina"
            assert post_resp.data["is_active"] is True

            get_resp = client.get(_allergy_list_url(patient.id))
            assert get_resp.status_code == 200
            assert len(get_resp.data) == 1

    def test_resolve_da_204_y_marca_inactiva(self, db: Any) -> None:
        """DELETE /alergias/<id>/ devuelve 204 y la alergia queda is_active=False."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient, is_active=True)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.delete(_allergy_resolve_url(allergy.id))

        assert resp.status_code == 204
        # Verificar que sigue en BD (D-EC-5).
        allergy.refresh_from_db()
        assert allergy.is_active is False

    def test_incluir_resueltas_en_listado(self, db: Any) -> None:
        """GET con include_resolved=true incluye alergias resueltas."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)
        patient = PatientFactory(tenant=tenant)
        AllergyFactory(tenant=tenant, patient=patient, is_active=True)
        AllergyFactory(tenant=tenant, patient=patient, is_active=False)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp_default = client.get(_allergy_list_url(patient.id))
            resp_todas = client.get(
                _allergy_list_url(patient.id), {"include_resolved": "true"}
            )

        assert len(resp_default.data) == 1
        assert len(resp_todas.data) == 2

    def test_create_alergia_paciente_inexistente_da_404(self, db: Any) -> None:
        """POST con patient_id inexistente → 404."""
        tenant = TenantFactory()
        doctor = _member(tenant, role=TenantMembership.Role.DOCTOR)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _allergy_list_url(uuid_module.uuid4()),
                data={"substance": "Penicilina"},
                format="json",
            )

        assert resp.status_code == 404


# ===========================================================================
# Bitácora de auditoría NOM-024 — allergy_create y allergy_resolve
# ===========================================================================


class TestAllergyAuditLog:
    """Verifica que allergy_create y allergy_resolve generan entradas en AuditLog (NOM-024).

    Patrón: AAA. Usa AuditLog.all_objects para leer registros (bypasa TenantManager).
    """

    def test_allergy_create_genera_auditlog(self, db: Any) -> None:
        """allergy_create escribe un AuditLog con action=ALLERGY_CREATE, actor y tenant correctos."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        # Act
        allergy = allergy_create(
            tenant=tenant,
            user=user,
            patient=patient,
            substance="Penicilina",
            reaction="Urticaria",
            severity=Severity.LEVE,
        )

        # Assert — debe existir exactamente un AuditLog para este evento.
        logs = AuditLog.all_objects.filter(
            action=ActionType.ALLERGY_CREATE,
            resource_type="Allergy",
            resource_id=allergy.id,
        )
        assert logs.count() == 1, "Se esperaba exactamente 1 AuditLog para ALLERGY_CREATE"

        log = logs.first()
        assert log is not None
        assert log.tenant_id == tenant.id
        assert log.actor_id == user.id
        # ALTO-1: resource_repr debe ser el UUID del registro, NUNCA la sustancia
        # (PII clínica). La bitácora es append-only e inmutable (NOM-024).
        assert log.resource_repr == str(allergy.id)
        assert "Penicilina" not in log.resource_repr, (
            "resource_repr NO debe contener PII clínica (sustancia)."
        )
        # metadata incluye patient_id y severity — no PII clínica (solo referencias).
        assert str(patient.id) in log.metadata.get("patient_id", "")
        assert log.metadata.get("severity") == "leve"

    def test_allergy_create_sustancia_vacia_no_genera_auditlog(self, db: Any) -> None:
        """Si allergy_create lanza ValidationError, no se genera AuditLog."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        count_before = AuditLog.all_objects.filter(action=ActionType.ALLERGY_CREATE).count()

        with pytest.raises(Exception):
            allergy_create(
                tenant=tenant,
                user=user,
                patient=patient,
                substance="",
            )

        count_after = AuditLog.all_objects.filter(action=ActionType.ALLERGY_CREATE).count()
        assert count_after == count_before, "No debe generarse AuditLog si la creación falla"

    def test_allergy_resolve_genera_auditlog(self, db: Any) -> None:
        """allergy_resolve escribe un AuditLog con action=ALLERGY_RESOLVE, actor y tenant correctos."""
        # Arrange
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient, is_active=True)

        # Act
        allergy_resolve(allergy=allergy, user=user)

        # Assert
        logs = AuditLog.all_objects.filter(
            action=ActionType.ALLERGY_RESOLVE,
            resource_type="Allergy",
            resource_id=allergy.id,
        )
        assert logs.count() == 1, "Se esperaba exactamente 1 AuditLog para ALLERGY_RESOLVE"

        log = logs.first()
        assert log is not None
        assert log.tenant_id == tenant.id
        assert log.actor_id == user.id
        assert str(patient.id) in log.metadata.get("patient_id", "")

    def test_allergy_resolve_idempotente_genera_un_solo_auditlog(self, db: Any) -> None:
        """Resolver una alergia ya resuelta (idempotente) no genera AuditLog adicional."""
        # Arrange — alergia ya inactiva desde el inicio.
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient, is_active=False)

        # Act — resolve sobre alergia ya resuelta.
        allergy_resolve(allergy=allergy, user=user)

        # Assert — no debe haberse generado ningún log (is_active ya era False).
        count = AuditLog.all_objects.filter(
            action=ActionType.ALLERGY_RESOLVE,
            resource_id=allergy.id,
        ).count()
        assert count == 0, "allergy_resolve idempotente no debe generar AuditLog"

    def test_allergy_create_auditlog_best_effort_no_tumba_operacion(self, db: Any) -> None:
        """Si el INSERT de AuditLog falla internamente, allergy_create no lanza excepción.

        La auditoría es best-effort (absorbe excepciones). La alergia debe crearse igual.
        """
        from unittest.mock import patch

        from apps.audit.models import AuditLog as AuditLogModel

        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with patch.object(AuditLogModel, "save", side_effect=Exception("Fallo simulado de BD")):
            # La operación de negocio NO debe lanzar aunque el log falle.
            allergy = allergy_create(
                tenant=tenant,
                user=user,
                patient=patient,
                substance="Amoxicilina",
            )

        # La alergia sí se creó (la transacción principal va aparte del log).
        assert allergy.pk is not None
        assert Allergy.all_objects.filter(pk=allergy.pk).exists()


# ===========================================================================
# ALTO-1 — resource_repr es UUID, nunca PII clínica
# ===========================================================================


class TestAuditLogResourceReprNoContienePii:
    """ALTO-1: Verifica que resource_repr del AuditLog nunca contiene PII clínica.

    La bitácora es append-only e inmutable (NOM-024); no se puede purgar.
    Por eso, ni la sustancia ni ningún dato del expediente puede quedar en
    resource_repr.
    """

    def test_allergy_create_resource_repr_es_uuid_no_sustancia(self, db: Any) -> None:
        """allergy_create: resource_repr del AuditLog es el UUID de la alergia."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        allergy = allergy_create(
            tenant=tenant,
            user=user,
            patient=patient,
            substance="Sulfamidas",
            severity=Severity.SEVERA,
        )

        log = AuditLog.all_objects.filter(
            action=ActionType.ALLERGY_CREATE,
            resource_id=allergy.id,
        ).first()

        assert log is not None
        assert log.resource_repr == str(allergy.id)
        assert "Sulfamidas" not in log.resource_repr

    def test_allergy_resolve_resource_repr_es_uuid_no_sustancia(self, db: Any) -> None:
        """allergy_resolve: resource_repr del AuditLog es el UUID de la alergia."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(
            tenant=tenant, patient=patient, substance="Látex peligroso", is_active=True
        )

        allergy_resolve(allergy=allergy, user=user)

        log = AuditLog.all_objects.filter(
            action=ActionType.ALLERGY_RESOLVE,
            resource_id=allergy.id,
        ).first()

        assert log is not None
        assert log.resource_repr == str(allergy.id)
        assert "Látex peligroso" not in log.resource_repr


# ===========================================================================
# BAJO-2 / MEDIO-3 — Guardia de tenant en services
# ===========================================================================


class TestAllergyServicesTenantGuardia:
    """Verifica las guardias de tenant en allergy_create y allergy_resolve.

    Defiende contra llamadas desde Celery/management commands sin contexto HTTP,
    donde tenant puede llegar como None.
    """

    def test_allergy_create_tenant_none_lanza_validation_error(self, db: Any) -> None:
        """allergy_create con tenant=None lanza ValidationError inmediatamente."""
        from django.core.exceptions import ValidationError

        user = UserFactory()
        # Necesitamos un patient; creamos con un tenant para el modelo.
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        with pytest.raises(ValidationError, match="tenant activo"):
            allergy_create(
                tenant=None,  # type: ignore[arg-type]
                user=user,
                patient=patient,
                substance="Aspirina",
            )

    def test_allergy_resolve_tenant_none_en_alergia_lanza_error(self, db: Any) -> None:
        """allergy_resolve con allergy.tenant=None lanza ValidationError."""
        from unittest.mock import PropertyMock, patch

        from django.core.exceptions import ValidationError

        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        allergy = AllergyFactory(tenant=tenant, patient=patient, is_active=True)

        # Simulamos que allergy.tenant es None (no puede ocurrir en BD normal,
        # pero es posible si se llama desde código que construye el objeto a mano).
        with patch.object(type(allergy), "tenant", new_callable=PropertyMock, return_value=None):
            with pytest.raises(ValidationError, match="tenant asociado"):
                allergy_resolve(allergy=allergy, user=user)


# ===========================================================================
# MEDIO-4 — No quedan imports rotos por el código muerto eliminado
# ===========================================================================


class TestMedio4SinImportsRotos:
    """Verifica que eliminar PatientNom004*Serializer no deja imports colgados."""

    def test_expediente_serializers_module_importa_sin_error(self) -> None:
        """El módulo expediente.serializers se importa sin AttributeError."""
        import importlib

        import apps.expediente.serializers as smod

        importlib.reload(smod)
        # Solo deben existir AllergyInputSerializer y AllergyOutputSerializer.
        assert hasattr(smod, "AllergyInputSerializer")
        assert hasattr(smod, "AllergyOutputSerializer")
        assert not hasattr(smod, "PatientNom004InputSerializer"), (
            "PatientNom004InputSerializer fue eliminado (MEDIO-4) y no debe existir."
        )
        assert not hasattr(smod, "PatientNom004OutputSerializer"), (
            "PatientNom004OutputSerializer fue eliminado (MEDIO-4) y no debe existir."
        )
