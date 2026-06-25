"""
Tests de la app expediente — Fase 2: MedicalHistoryQuestion.

Cubre:

CRUD de preguntas (services):
  - medical_history_question_create: camino feliz (text, select, boolean).
  - Validación field_type: select requiere options; otros tipos prohíben options.
  - field_type inválido → ValidationError.
  - tenant None → ValidationError.
  - label vacío → ValidationError.
  - medical_history_question_update: actualiza campos mutables.
  - update intenta modificar campo inmutable (is_active) → ValidationError.
  - update normaliza label vacío → ValidationError.
  - medical_history_question_deactivate: baja lógica, idempotente.

Selectors:
  - medical_history_question_get: retorna pregunta del tenant activo.
  - medical_history_question_get: pregunta de otro tenant → DoesNotExist.
  - medical_history_questions_list: only_active filtra correctamente.

Serializer de entrada (MedicalHistoryQuestionInputSerializer):
  - select sin options → error de validación.
  - text con options → error de validación.
  - campo desconocido rechazado.
  - is_active no está en el serializer (no se puede enviar).

APIs (MedicalHistoryQuestionListCreateApi / MedicalHistoryQuestionDetailApi):
  - GET /preguntas-hc/ → 200 con lista de activas.
  - GET ?include_inactive=true → incluye inactivas.
  - POST /preguntas-hc/ → 201 (owner/admin).
  - POST con field_type select sin options → 400.
  - PATCH /preguntas-hc/<id>/ → 200.
  - DELETE /preguntas-hc/<id>/ → 204 (idempotente).

Permisos:
  - GET: doctor, nurse, readonly → 200.
  - POST, PATCH, DELETE: doctor/nurse/readonly → 403.
  - POST, PATCH, DELETE: owner/admin → 200/201/204.
  - Sin token → 401.

Multi-tenant (aislamiento):
  - Pregunta de otro tenant no aparece en GET → 404 con su UUID.
  - GET lista no devuelve preguntas de otro tenant.

custom_answers en MedicalHistory:
  - PUT con custom_answers guarda las respuestas a preguntas activas.
  - Claves de preguntas inactivas se ignoran silenciosamente.
  - Claves de preguntas de otro tenant se ignoran silenciosamente.
  - PUT sin custom_answers no toca el campo (None = no tocar).
  - Bloques NOM-004 (heredo_familiares, etc.) no se alteran al guardar custom_answers.

Output de HC:
  - GET HC incluye custom_answers y active_questions.
  - active_questions solo contiene preguntas activas del tenant activo.

Patrón: AAA. factory_boy para datos.
"""

import uuid as uuid_module
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.expediente.models import MedicalHistoryQuestion, QuestionFieldType
from apps.expediente.selectors import (
    medical_history_question_get,
    medical_history_questions_list,
)
from apps.expediente.serializers import MedicalHistoryQuestionInputSerializer
from apps.expediente.services import (
    medical_history_question_create,
    medical_history_question_deactivate,
    medical_history_question_update,
    medical_history_upsert,
)
from apps.expediente.tests.conftest import api_tenant_ctx, tenant_ctx
from apps.tenancy.models import TenantMembership
from tests.factories import (
    MedicalHistoryFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_LIST_CREATE_URL = "/api/v1/expediente/preguntas-hc/"


def _detail_url(question_id: Any) -> str:
    return f"/api/v1/expediente/preguntas-hc/{question_id}/"


def _historia_url(patient_id: Any) -> str:
    return f"/api/v1/expediente/{patient_id}/historia/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _member(tenant: Any, role: str = TenantMembership.Role.OWNER) -> Any:
    """Crea un user con membresía activa en el tenant dado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return user


def _auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_question(tenant: Any, **kwargs: Any) -> MedicalHistoryQuestion:
    """Crea una pregunta de tipo text directamente en BD (sin pasar por el service)."""
    return MedicalHistoryQuestion.objects.create(
        tenant=tenant,
        created_by=UserFactory(),
        label=kwargs.get("label", "Pregunta de prueba"),
        field_type=kwargs.get("field_type", QuestionFieldType.TEXT),
        options=kwargs.get("options", []),
        section=kwargs.get("section", ""),
        order=kwargs.get("order", 0),
        is_required=kwargs.get("is_required", False),
        is_active=kwargs.get("is_active", True),
    )


# ===========================================================================
# Services — medical_history_question_create
# ===========================================================================


@pytest.mark.django_db
class TestMedicalHistoryQuestionCreate:
    """Tests del service de creación de preguntas extra."""

    def test_crear_pregunta_text_ok(self) -> None:
        """Crear pregunta tipo text: retorna instancia activa."""
        tenant = TenantFactory()
        user = UserFactory()

        with tenant_ctx(tenant):
            question = medical_history_question_create(
                tenant=tenant,
                user=user,
                label="¿Usa lentes?",
                field_type=QuestionFieldType.TEXT,
            )

        assert question.pk is not None
        assert question.label == "¿Usa lentes?"
        assert question.field_type == QuestionFieldType.TEXT
        assert question.is_active is True
        assert question.tenant_id == tenant.id
        assert question.options == []

    def test_crear_pregunta_select_con_options_ok(self) -> None:
        """Crear pregunta tipo select con opciones válidas."""
        tenant = TenantFactory()
        user = UserFactory()

        with tenant_ctx(tenant):
            question = medical_history_question_create(
                tenant=tenant,
                user=user,
                label="Nivel socioeconómico",
                field_type=QuestionFieldType.SELECT,
                options=["Bajo", "Medio", "Alto"],
            )

        assert question.options == ["Bajo", "Medio", "Alto"]
        assert question.field_type == QuestionFieldType.SELECT

    def test_crear_pregunta_boolean_ok(self) -> None:
        """Crear pregunta tipo boolean sin opciones."""
        tenant = TenantFactory()
        user = UserFactory()

        with tenant_ctx(tenant):
            question = medical_history_question_create(
                tenant=tenant,
                user=user,
                label="¿Tiene seguro médico?",
                field_type=QuestionFieldType.BOOLEAN,
            )

        assert question.field_type == QuestionFieldType.BOOLEAN
        assert question.options == []

    def test_tenant_none_falla(self) -> None:
        """tenant=None → ValidationError."""
        user = UserFactory()

        with pytest.raises(ValidationError, match="tenant"):
            medical_history_question_create(
                tenant=None,  # type: ignore[arg-type]
                user=user,
                label="Pregunta",
                field_type=QuestionFieldType.TEXT,
            )

    def test_label_vacio_falla(self) -> None:
        """label vacío → ValidationError."""
        tenant = TenantFactory()
        user = UserFactory()

        with pytest.raises(ValidationError, match="vacío"):
            medical_history_question_create(
                tenant=tenant,
                user=user,
                label="   ",
                field_type=QuestionFieldType.TEXT,
            )

    def test_field_type_invalido_falla(self) -> None:
        """field_type fuera de choices → ValidationError."""
        tenant = TenantFactory()
        user = UserFactory()

        with pytest.raises(ValidationError, match="inválido"):
            medical_history_question_create(
                tenant=tenant,
                user=user,
                label="Pregunta",
                field_type="radio",  # no existe en QuestionFieldType
            )

    def test_select_sin_options_falla(self) -> None:
        """field_type=select con options=[] → ValidationError."""
        tenant = TenantFactory()
        user = UserFactory()

        with pytest.raises(ValidationError, match="opciones"):
            medical_history_question_create(
                tenant=tenant,
                user=user,
                label="Pregunta select",
                field_type=QuestionFieldType.SELECT,
                options=[],
            )

    def test_text_con_options_falla(self) -> None:
        """field_type=text con options no vacíos → ValidationError."""
        tenant = TenantFactory()
        user = UserFactory()

        with pytest.raises(ValidationError, match="opciones"):
            medical_history_question_create(
                tenant=tenant,
                user=user,
                label="Pregunta text",
                field_type=QuestionFieldType.TEXT,
                options=["Opción A"],
            )

    def test_genera_audit_log(self) -> None:
        """Crear pregunta genera AuditLog MEDICAL_HISTORY_QUESTION_CREATE."""
        tenant = TenantFactory()
        user = UserFactory()

        with tenant_ctx(tenant):
            question = medical_history_question_create(
                tenant=tenant,
                user=user,
                label="Pregunta auditada",
                field_type=QuestionFieldType.TEXT,
            )

        assert AuditLog.all_objects.filter(
            action=ActionType.MEDICAL_HISTORY_QUESTION_CREATE,
            resource_id=question.id,
        ).exists()


# ===========================================================================
# Services — medical_history_question_update
# ===========================================================================


@pytest.mark.django_db
class TestMedicalHistoryQuestionUpdate:
    """Tests del service de actualización de preguntas extra."""

    def test_actualizar_label_ok(self) -> None:
        """Actualizar label: retorna pregunta con nuevo label."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant)

        with tenant_ctx(tenant):
            updated = medical_history_question_update(
                question=question,
                user=user,
                label="Nuevo label",
            )

        assert updated.label == "Nuevo label"

    def test_actualizar_order_ok(self) -> None:
        """Actualizar order: funciona sin tocar otros campos."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant)
        original_label = question.label

        with tenant_ctx(tenant):
            updated = medical_history_question_update(
                question=question,
                user=user,
                order=5,
            )

        assert updated.order == 5
        assert updated.label == original_label

    def test_intento_de_modificar_is_active_falla(self) -> None:
        """Modificar is_active via update → ValidationError (campo inmutable)."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant)

        with pytest.raises(ValidationError, match="is_active"):
            medical_history_question_update(
                question=question,
                user=user,
                is_active=False,
            )

    def test_intento_de_modificar_tenant_falla(self) -> None:
        """Modificar tenant via update → ValidationError."""
        tenant = TenantFactory()
        another_tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant)

        with pytest.raises(ValidationError):
            medical_history_question_update(
                question=question,
                user=user,
                tenant=another_tenant,
            )

    def test_label_vacio_falla(self) -> None:
        """Actualizar a label vacío → ValidationError."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant)

        with pytest.raises(ValidationError, match="vacío"):
            medical_history_question_update(
                question=question,
                user=user,
                label="   ",
            )

    def test_cambio_a_select_requiere_options(self) -> None:
        """Cambiar field_type a select sin options → ValidationError."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant, field_type=QuestionFieldType.TEXT)

        with pytest.raises(ValidationError, match="opciones"):
            medical_history_question_update(
                question=question,
                user=user,
                field_type=QuestionFieldType.SELECT,
            )

    def test_genera_audit_log(self) -> None:
        """Actualizar pregunta genera AuditLog MEDICAL_HISTORY_QUESTION_UPDATE."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant)

        with tenant_ctx(tenant):
            medical_history_question_update(
                question=question,
                user=user,
                label="Label actualizado",
            )

        assert AuditLog.all_objects.filter(
            action=ActionType.MEDICAL_HISTORY_QUESTION_UPDATE,
            resource_id=question.id,
        ).exists()


# ===========================================================================
# Services — medical_history_question_deactivate
# ===========================================================================


@pytest.mark.django_db
class TestMedicalHistoryQuestionDeactivate:
    """Tests del service de baja lógica de preguntas extra."""

    def test_desactivar_pregunta_ok(self) -> None:
        """Desactivar pregunta activa: pone is_active=False."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant, is_active=True)

        with tenant_ctx(tenant):
            result = medical_history_question_deactivate(question=question, user=user)

        assert result.is_active is False

    def test_desactivar_ya_inactiva_idempotente(self) -> None:
        """Desactivar pregunta ya inactiva: no error, sigue is_active=False."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant, is_active=False)

        with tenant_ctx(tenant):
            result = medical_history_question_deactivate(question=question, user=user)

        assert result.is_active is False

    def test_genera_audit_log(self) -> None:
        """Desactivar pregunta genera AuditLog MEDICAL_HISTORY_QUESTION_DEACTIVATE."""
        tenant = TenantFactory()
        user = UserFactory()
        question = _make_question(tenant, is_active=True)

        with tenant_ctx(tenant):
            medical_history_question_deactivate(question=question, user=user)

        assert AuditLog.all_objects.filter(
            action=ActionType.MEDICAL_HISTORY_QUESTION_DEACTIVATE,
            resource_id=question.id,
        ).exists()


# ===========================================================================
# Selectors
# ===========================================================================


@pytest.mark.django_db
class TestMedicalHistoryQuestionSelectors:
    """Tests de selectors de preguntas extra."""

    def test_get_retorna_pregunta_del_tenant(self) -> None:
        """medical_history_question_get retorna la pregunta correcta."""
        tenant = TenantFactory()
        question = _make_question(tenant)

        with tenant_ctx(tenant):
            result = medical_history_question_get(question_id=question.id)

        assert result.id == question.id

    def test_get_pregunta_otro_tenant_falla(self) -> None:
        """Pregunta de otro tenant → DoesNotExist (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        question = _make_question(tenant_a)

        with tenant_ctx(tenant_b):
            with pytest.raises(MedicalHistoryQuestion.DoesNotExist):
                medical_history_question_get(question_id=question.id)

    def test_list_solo_activas_por_defecto(self) -> None:
        """medical_history_questions_list(only_active=True) excluye inactivas."""
        tenant = TenantFactory()
        q_active = _make_question(tenant, is_active=True)
        q_inactive = _make_question(tenant, label="Inactiva", is_active=False)

        with tenant_ctx(tenant):
            qs = list(medical_history_questions_list(only_active=True))

        ids = [q.id for q in qs]
        assert q_active.id in ids
        assert q_inactive.id not in ids

    def test_list_include_inactive_falso(self) -> None:
        """medical_history_questions_list(only_active=False) retorna todas."""
        tenant = TenantFactory()
        q_active = _make_question(tenant, is_active=True)
        q_inactive = _make_question(tenant, label="Inactiva", is_active=False)

        with tenant_ctx(tenant):
            qs = list(medical_history_questions_list(only_active=False))

        ids = [q.id for q in qs]
        assert q_active.id in ids
        assert q_inactive.id in ids

    def test_list_no_filtra_otro_tenant(self) -> None:
        """medical_history_questions_list no devuelve preguntas de otro tenant."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        _make_question(tenant_a, label="Pregunta tenant A")
        _make_question(tenant_b, label="Pregunta tenant B")

        with tenant_ctx(tenant_a):
            qs = list(medical_history_questions_list())

        assert all(q.tenant_id == tenant_a.id for q in qs)


# ===========================================================================
# Serializer — MedicalHistoryQuestionInputSerializer
# ===========================================================================


@pytest.mark.django_db
class TestMedicalHistoryQuestionInputSerializer:
    """Tests del serializer de entrada de preguntas extra."""

    def test_valido_text(self) -> None:
        """Datos válidos para tipo text pasan."""
        s = MedicalHistoryQuestionInputSerializer(
            data={"label": "¿Pregunta?", "field_type": "text"}
        )
        assert s.is_valid(), s.errors

    def test_select_requiere_options(self) -> None:
        """select sin options → error de validación."""
        s = MedicalHistoryQuestionInputSerializer(
            data={"label": "¿Pregunta?", "field_type": "select", "options": []}
        )
        assert not s.is_valid()
        assert "options" in s.errors

    def test_text_con_options_falla(self) -> None:
        """text con options → error de validación."""
        s = MedicalHistoryQuestionInputSerializer(
            data={"label": "¿Pregunta?", "field_type": "text", "options": ["A", "B"]}
        )
        assert not s.is_valid()
        assert "options" in s.errors

    def test_campo_desconocido_rechazado(self) -> None:
        """Campo no declarado → error de validación (D-EC-7)."""
        s = MedicalHistoryQuestionInputSerializer(
            data={
                "label": "¿Pregunta?",
                "field_type": "text",
                "campo_extra": "valor",
            }
        )
        assert not s.is_valid()
        assert "campo_extra" in s.errors

    def test_is_active_no_esta_en_serializer(self) -> None:
        """is_active no está declarado en el serializer de entrada → se rechaza."""
        s = MedicalHistoryQuestionInputSerializer(
            data={
                "label": "¿Pregunta?",
                "field_type": "text",
                "is_active": False,
            }
        )
        assert not s.is_valid()
        assert "is_active" in s.errors

    def test_select_con_options_valido(self) -> None:
        """select con opciones válidas pasa."""
        s = MedicalHistoryQuestionInputSerializer(
            data={
                "label": "Selección",
                "field_type": "select",
                "options": ["Opción A", "Opción B"],
            }
        )
        assert s.is_valid(), s.errors
        assert s.validated_data["options"] == ["Opción A", "Opción B"]


# ===========================================================================
# APIs — MedicalHistoryQuestionListCreateApi (GET / POST)
# ===========================================================================


@pytest.mark.django_db
class TestMedicalHistoryQuestionListApi:
    """Tests del endpoint GET /api/v1/expediente/preguntas-hc/."""

    def test_get_lista_activas(self) -> None:
        """GET devuelve 200 con preguntas activas del tenant."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        _make_question(tenant, label="P1", is_active=True)
        _make_question(tenant, label="P2", is_active=False)

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.get(_LIST_CREATE_URL)

        assert resp.status_code == 200
        labels = [q["label"] for q in resp.data]
        assert "P1" in labels
        assert "P2" not in labels

    def test_get_include_inactive(self) -> None:
        """GET ?include_inactive=true devuelve activas e inactivas."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        _make_question(tenant, label="PA", is_active=True)
        _make_question(tenant, label="PI", is_active=False)

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.get(_LIST_CREATE_URL + "?include_inactive=true")

        assert resp.status_code == 200
        labels = [q["label"] for q in resp.data]
        assert "PA" in labels
        assert "PI" in labels

    def test_get_doctor_puede_listar(self) -> None:
        """Doctor (CLINICAL_READ) puede GET → 200."""
        tenant = TenantFactory()
        doctor = _member(tenant, TenantMembership.Role.DOCTOR)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.get(_LIST_CREATE_URL)

        assert resp.status_code == 200

    def test_get_readonly_puede_listar(self) -> None:
        """Readonly puede GET → 200."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.READONLY)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.get(_LIST_CREATE_URL)

        assert resp.status_code == 200

    def test_sin_token_retorna_401(self) -> None:
        """Sin token → 401."""
        client = APIClient()
        resp = client.get(_LIST_CREATE_URL)
        assert resp.status_code == 401

    def test_no_filtra_otro_tenant(self) -> None:
        """Preguntas de otro tenant NO aparecen en la lista."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner_a = _member(tenant_a, TenantMembership.Role.OWNER)
        _make_question(tenant_a, label="Q tenant A")
        _make_question(tenant_b, label="Q tenant B")

        client = _auth_client(owner_a)
        with api_tenant_ctx(tenant_a):
            resp = client.get(_LIST_CREATE_URL)

        labels = [q["label"] for q in resp.data]
        assert "Q tenant A" in labels
        assert "Q tenant B" not in labels


@pytest.mark.django_db
class TestMedicalHistoryQuestionCreateApi:
    """Tests del endpoint POST /api/v1/expediente/preguntas-hc/."""

    def test_owner_puede_crear(self) -> None:
        """Owner puede POST → 201."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL,
                {"label": "Nueva pregunta", "field_type": "text"},
                format="json",
            )

        assert resp.status_code == 201
        assert resp.data["label"] == "Nueva pregunta"
        assert resp.data["is_active"] is True

    def test_admin_puede_crear(self) -> None:
        """Admin puede POST → 201."""
        tenant = TenantFactory()
        admin = _member(tenant, TenantMembership.Role.ADMIN)

        client = _auth_client(admin)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL,
                {"label": "Pregunta admin", "field_type": "number"},
                format="json",
            )

        assert resp.status_code == 201

    def test_doctor_no_puede_crear(self) -> None:
        """Doctor no puede POST → 403."""
        tenant = TenantFactory()
        doctor = _member(tenant, TenantMembership.Role.DOCTOR)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL,
                {"label": "Pregunta doctor", "field_type": "text"},
                format="json",
            )

        assert resp.status_code == 403

    def test_nurse_no_puede_crear(self) -> None:
        """Nurse no puede POST → 403."""
        tenant = TenantFactory()
        nurse = _member(tenant, TenantMembership.Role.NURSE)

        client = _auth_client(nurse)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL,
                {"label": "Pregunta", "field_type": "text"},
                format="json",
            )

        assert resp.status_code == 403

    def test_select_sin_options_retorna_400(self) -> None:
        """POST select sin options → 400."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL,
                {"label": "Selección", "field_type": "select"},
                format="json",
            )

        assert resp.status_code == 400

    def test_crea_pregunta_select_con_options(self) -> None:
        """POST select con options válidas → 201."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.post(
                _LIST_CREATE_URL,
                {
                    "label": "Nivel",
                    "field_type": "select",
                    "options": ["Bajo", "Medio", "Alto"],
                },
                format="json",
            )

        assert resp.status_code == 201
        assert resp.data["options"] == ["Bajo", "Medio", "Alto"]


# ===========================================================================
# APIs — MedicalHistoryQuestionDetailApi (PATCH / DELETE)
# ===========================================================================


@pytest.mark.django_db
class TestMedicalHistoryQuestionPatchApi:
    """Tests del endpoint PATCH /api/v1/expediente/preguntas-hc/<id>/."""

    def test_owner_puede_patch(self) -> None:
        """Owner puede PATCH → 200."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        question = _make_question(tenant, label="Original")

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.patch(
                _detail_url(question.id),
                {"label": "Actualizado"},
                format="json",
            )

        assert resp.status_code == 200
        assert resp.data["label"] == "Actualizado"

    def test_doctor_no_puede_patch(self) -> None:
        """Doctor no puede PATCH → 403."""
        tenant = TenantFactory()
        doctor = _member(tenant, TenantMembership.Role.DOCTOR)
        question = _make_question(tenant)

        client = _auth_client(doctor)
        with api_tenant_ctx(tenant):
            resp = client.patch(
                _detail_url(question.id),
                {"label": "Intento"},
                format="json",
            )

        assert resp.status_code == 403

    def test_pregunta_otro_tenant_retorna_404(self) -> None:
        """Pregunta de otro tenant → 404 (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner_a = _member(tenant_a, TenantMembership.Role.OWNER)
        question_b = _make_question(tenant_b, label="Ajena")

        client = _auth_client(owner_a)
        with api_tenant_ctx(tenant_a):
            resp = client.patch(
                _detail_url(question_b.id),
                {"label": "Intento"},
                format="json",
            )

        assert resp.status_code == 404


@pytest.mark.django_db
class TestMedicalHistoryQuestionDeleteApi:
    """Tests del endpoint DELETE /api/v1/expediente/preguntas-hc/<id>/."""

    def test_owner_puede_desactivar(self) -> None:
        """Owner puede DELETE → 204 y pregunta queda is_active=False."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        question = _make_question(tenant, is_active=True)

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(question.id))

        assert resp.status_code == 204
        question.refresh_from_db()
        assert question.is_active is False

    def test_delete_idempotente(self) -> None:
        """DELETE sobre pregunta ya inactiva → 204 sin error."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        question = _make_question(tenant, is_active=False)

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(question.id))

        assert resp.status_code == 204

    def test_readonly_no_puede_delete(self) -> None:
        """Readonly no puede DELETE → 403."""
        tenant = TenantFactory()
        user = _member(tenant, TenantMembership.Role.READONLY)
        question = _make_question(tenant)

        client = _auth_client(user)
        with api_tenant_ctx(tenant):
            resp = client.delete(_detail_url(question.id))

        assert resp.status_code == 403

    def test_pregunta_otro_tenant_retorna_404(self) -> None:
        """Pregunta de otro tenant → 404 (anti-IDOR)."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner_a = _member(tenant_a, TenantMembership.Role.OWNER)
        question_b = _make_question(tenant_b)

        client = _auth_client(owner_a)
        with api_tenant_ctx(tenant_a):
            resp = client.delete(_detail_url(question_b.id))

        assert resp.status_code == 404


# ===========================================================================
# custom_answers en MedicalHistory (upsert + output)
# ===========================================================================


@pytest.mark.django_db
class TestCustomAnswersInMedicalHistory:
    """Tests de custom_answers en el service medical_history_upsert y la API."""

    def test_upsert_guarda_custom_answers_activas(self) -> None:
        """Upsert con custom_answers guarda solo claves de preguntas activas."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        q_active = _make_question(tenant, is_active=True)
        q_inactive = _make_question(tenant, label="Inactiva", is_active=False)

        with tenant_ctx(tenant):
            hc = medical_history_upsert(
                tenant=tenant,
                user=user,
                patient=patient,
                custom_answers={
                    str(q_active.id): "respuesta activa",
                    str(q_inactive.id): "respuesta inactiva",
                },
            )

        # Solo la clave de la pregunta activa debe persistir.
        assert str(q_active.id) in hc.custom_answers
        assert hc.custom_answers[str(q_active.id)] == "respuesta activa"
        assert str(q_inactive.id) not in hc.custom_answers

    def test_upsert_ignora_claves_de_otro_tenant(self) -> None:
        """Claves de preguntas de otro tenant se ignoran silenciosamente."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant_a)
        q_b = _make_question(tenant_b, label="Pregunta B", is_active=True)

        with tenant_ctx(tenant_a):
            hc = medical_history_upsert(
                tenant=tenant_a,
                user=user,
                patient=patient,
                custom_answers={str(q_b.id): "respuesta ajena"},
            )

        # La clave del otro tenant se ignora.
        assert str(q_b.id) not in hc.custom_answers

    def test_upsert_none_no_toca_custom_answers(self) -> None:
        """custom_answers=None no modifica el campo existente."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        q = _make_question(tenant, is_active=True)

        with tenant_ctx(tenant):
            # Primera llamada: guarda respuesta.
            hc = medical_history_upsert(
                tenant=tenant,
                user=user,
                patient=patient,
                custom_answers={str(q.id): "primera respuesta"},
            )

        with tenant_ctx(tenant):
            # Segunda llamada: custom_answers=None (no debe tocar).
            hc2 = medical_history_upsert(
                tenant=tenant,
                user=user,
                patient=patient,
                custom_answers=None,
            )

        # La respuesta anterior debe permanecer intacta.
        assert hc2.custom_answers.get(str(q.id)) == "primera respuesta"

    def test_upsert_nom004_no_se_altera(self) -> None:
        """Guardar custom_answers no altera los bloques NOM-004 existentes."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)
        q = _make_question(tenant, is_active=True)

        with tenant_ctx(tenant):
            # Primero guarda HC con datos NOM-004.
            hc = medical_history_upsert(
                tenant=tenant,
                user=user,
                patient=patient,
                heredo_familiares={"diabetes": "Padre"},
            )

        with tenant_ctx(tenant):
            # Segundo PUT: solo custom_answers, no toca NOM-004.
            hc2 = medical_history_upsert(
                tenant=tenant,
                user=user,
                patient=patient,
                custom_answers={str(q.id): "valor"},
            )

        # Los bloques NOM-004 deben mantenerse.
        assert hc2.heredo_familiares == {"diabetes": "Padre"}

    def test_upsert_claves_uuid_invalidas_ignoradas(self) -> None:
        """Claves que no son UUID de preguntas activas se ignoran silenciosamente."""
        tenant = TenantFactory()
        user = UserFactory()
        patient = PatientFactory(tenant=tenant)

        with tenant_ctx(tenant):
            hc = medical_history_upsert(
                tenant=tenant,
                user=user,
                patient=patient,
                custom_answers={"clave_falsa": "valor"},
            )

        # La clave falsa no debe persistir.
        assert "clave_falsa" not in hc.custom_answers


# ===========================================================================
# Output del GET de HC incluye custom_answers y active_questions
# ===========================================================================


@pytest.mark.django_db
class TestMedicalHistoryOutputConPreguntas:
    """Tests del serializer de salida: custom_answers y active_questions."""

    def test_get_hc_incluye_custom_answers(self) -> None:
        """GET de HC incluye campo custom_answers en la respuesta."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)
        q = _make_question(tenant, is_active=True)

        # Crear HC con respuesta.
        MedicalHistoryFactory(
            tenant=tenant,
            patient=patient,
            created_by=owner,
            custom_answers={str(q.id): "respuesta de prueba"},
        )

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.get(_historia_url(patient.id))

        assert resp.status_code == 200
        assert "custom_answers" in resp.data
        assert str(q.id) in resp.data["custom_answers"]

    def test_get_hc_incluye_active_questions(self) -> None:
        """GET de HC incluye active_questions con las preguntas activas del tenant."""
        tenant = TenantFactory()
        owner = _member(tenant, TenantMembership.Role.OWNER)
        patient = PatientFactory(tenant=tenant)
        q_active = _make_question(tenant, label="Activa", is_active=True)
        q_inactive = _make_question(tenant, label="Inactiva", is_active=False)

        MedicalHistoryFactory(tenant=tenant, patient=patient, created_by=owner)

        client = _auth_client(owner)
        with api_tenant_ctx(tenant):
            resp = client.get(_historia_url(patient.id))

        assert resp.status_code == 200
        assert "active_questions" in resp.data

        question_ids = [str(q["id"]) for q in resp.data["active_questions"]]
        assert str(q_active.id) in question_ids
        assert str(q_inactive.id) not in question_ids

    def test_get_hc_active_questions_solo_del_tenant(self) -> None:
        """active_questions no incluye preguntas de otro tenant."""
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        owner_a = _member(tenant_a, TenantMembership.Role.OWNER)
        patient_a = PatientFactory(tenant=tenant_a)
        q_a = _make_question(tenant_a, label="Pregunta A")
        q_b = _make_question(tenant_b, label="Pregunta B")

        MedicalHistoryFactory(tenant=tenant_a, patient=patient_a, created_by=owner_a)

        client = _auth_client(owner_a)
        with api_tenant_ctx(tenant_a):
            resp = client.get(_historia_url(patient_a.id))

        assert resp.status_code == 200
        question_ids = [str(q["id"]) for q in resp.data["active_questions"]]
        assert str(q_a.id) in question_ids
        assert str(q_b.id) not in question_ids
