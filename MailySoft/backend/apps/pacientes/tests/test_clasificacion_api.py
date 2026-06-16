"""
Tests de las APIs de clasificación y segmentos (Fase 1).

Cubre:
- POST /api/v1/pacientes/<uuid>/clasificacion/
  * 200 happy path (marcar favorito, VIP, ambos, body vacío).
  * 401 sin autenticación.
  * 403 rol readonly (no puede clasificar).
  * 404 paciente de otro tenant (aislamiento multi-tenant).
  * El response incluye is_favorite, is_vip actualizados.
- GET /api/v1/pacientes/?segment=date sin fechas → 400.
- GET /api/v1/pacientes/?segment=date con fechas válidas → 200, solo atendidos en rango.
- GET /api/v1/pacientes/?segment=favorites → solo favoritos del tenant.
- GET /api/v1/pacientes/?segment=vip → solo VIP del tenant.
- GET /api/v1/pacientes/?segment=recent → solo con cita atendida; includes last_seen_at y attended_count.
- GET /api/v1/pacientes/?segment=potential → solo potenciales del tenant.
- Campos is_favorite, is_vip, last_seen_at, attended_count presentes en el output.

Nota técnica sobre el contexto de tenant en tests de API:
  El TenantMiddleware no puede resolver el tenant cuando force_authenticate
  se usa (request.user es AnonymousUser a nivel de Django HttpRequest).
  Se usa el mismo helper _tenant_context() que los tests existentes de
  test_apis.py: mockea get_current_tenant y el TenantManager.

Patrón: AAA (Arrange-Act-Assert). Todas tocan BD → fixture db.
"""

import datetime
import uuid as uuid_module
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.agenda.models import Appointment
from tests.factories import (
    AppointmentFactory,
    DoctorFactory,
    PatientFactory,
    TenantFactory,
    TenantMembershipFactory,
    UserFactory,
)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

LIST_URL = "/api/v1/pacientes/"


def _classify_url(patient_id: Any) -> str:
    return f"/api/v1/pacientes/{patient_id}/clasificacion/"


# ---------------------------------------------------------------------------
# Helpers (mismo patrón que test_apis.py existente)
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_context(tenant: Any) -> Generator[None, None, None]:
    """Simula el efecto del TenantMiddleware + TenantManager para el tenant dado."""
    with (
        patch("apps.pacientes.views.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.get_current_tenant", return_value=tenant),
        patch("apps.core.managers.is_tenant_context_active", return_value=True),
    ):
        yield


def _make_auth_client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_member_client(tenant: Any, role: str = "owner") -> APIClient:
    """Crea user con TenantMembership y devuelve cliente autenticado."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role, is_active=True)
    return _make_auth_client(user)


def _attended_appointment(
    tenant: Any, patient: Any, starts_at: datetime.datetime
) -> Appointment:
    """Cita con status=attended para poblar anotaciones del selector."""
    doctor = DoctorFactory(tenant=tenant)
    return AppointmentFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        consultorio=None,
        status=Appointment.Status.ATTENDED,
        starts_at=starts_at,
        ends_at=starts_at + datetime.timedelta(hours=1),
    )


def _cancelled_appointment(
    tenant: Any, patient: Any, starts_at: datetime.datetime
) -> Appointment:
    doctor = DoctorFactory(tenant=tenant)
    return AppointmentFactory(
        tenant=tenant,
        patient=patient,
        doctor=doctor,
        consultorio=None,
        status=Appointment.Status.CANCELLED,
        starts_at=starts_at,
        ends_at=starts_at + datetime.timedelta(hours=1),
    )


_FIXED_DT_IN_RANGE = datetime.datetime(2030, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
_FIXED_DATE_FROM = datetime.date(2030, 1, 10)
_FIXED_DATE_TO = datetime.date(2030, 1, 20)


# ===========================================================================
# POST /api/v1/pacientes/<uuid>/clasificacion/
# ===========================================================================


class TestPatientClassifyApi:
    """POST /clasificacion/ — marcado de favorito y VIP vía API."""

    def test_classify_requires_authentication(
        self, db: None, api_client: APIClient
    ) -> None:
        """Sin autenticación devuelve 401."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)

        # Act
        response = api_client.post(
            _classify_url(patient.id), data={"is_favorite": True}, format="json"
        )

        # Assert
        assert response.status_code == 401

    def test_classify_sets_is_favorite_true_returns_200(self, db: None) -> None:
        """POST is_favorite=True devuelve 200 con el paciente actualizado."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=False)
        client = _make_member_client(tenant, role="doctor")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _classify_url(patient.id), data={"is_favorite": True}, format="json"
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["is_favorite"] is True

    def test_classify_sets_is_vip_true_returns_200(self, db: None) -> None:
        """POST is_vip=True devuelve 200 con el paciente actualizado."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_vip=False)
        client = _make_member_client(tenant, role="nurse")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _classify_url(patient.id), data={"is_vip": True}, format="json"
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["is_vip"] is True

    def test_classify_sets_both_flags_returns_200(self, db: None) -> None:
        """POST con is_favorite=True e is_vip=True actualiza ambos flags."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=False, is_vip=False)
        client = _make_member_client(tenant, role="reception")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _classify_url(patient.id),
                data={"is_favorite": True, "is_vip": True},
                format="json",
            )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["is_favorite"] is True
        assert data["is_vip"] is True

    def test_classify_unmark_favorite_returns_200(self, db: None) -> None:
        """POST is_favorite=False desmarca el favorito."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=True)
        client = _make_member_client(tenant, role="owner")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _classify_url(patient.id), data={"is_favorite": False}, format="json"
            )

        # Assert
        assert response.status_code == 200
        assert response.json()["is_favorite"] is False

    def test_classify_with_empty_body_returns_200_no_change(self, db: None) -> None:
        """POST sin campos devuelve 200 sin modificar al paciente."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_favorite=True, is_vip=False)
        client = _make_member_client(tenant, role="admin")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _classify_url(patient.id), data={}, format="json"
            )

        # Assert — 200 y los flags no cambiaron
        assert response.status_code == 200
        data = response.json()
        assert data["is_favorite"] is True
        assert data["is_vip"] is False

    def test_classify_response_includes_required_fields(self, db: None) -> None:
        """El response incluye is_favorite, is_vip, last_seen_at y attended_count."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="doctor")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _classify_url(patient.id), data={"is_favorite": True}, format="json"
            )

        # Assert — campos presentes en output
        data = response.json()
        assert "is_favorite" in data
        assert "is_vip" in data
        # last_seen_at y attended_count pueden ser null si no hay citas anotadas
        # (el endpoint de detalle usa patient_get, no patient_list; el serializer
        # es tolerante con getattr ... None)
        assert "last_seen_at" in data
        assert "attended_count" in data

    def test_classify_readonly_role_returns_403(self, db: None) -> None:
        """Rol 'readonly' no puede clasificar pacientes → 403."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _classify_url(patient.id), data={"is_favorite": True}, format="json"
            )

        # Assert
        assert response.status_code == 403

    def test_classify_other_tenant_patient_returns_404(self, db: None) -> None:
        """Paciente de otro tenant devuelve 404 (aislamiento multi-tenant)."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        patient_b = PatientFactory(tenant=tenant_b)
        client = _make_member_client(tenant_a, role="owner")

        # Act — contexto del tenant A, pero el paciente es del B
        with _tenant_context(tenant_a):
            response = client.post(
                _classify_url(patient_b.id), data={"is_favorite": True}, format="json"
            )

        # Assert — 404, no 403 (no se revela la existencia del recurso)
        assert response.status_code == 404

    def test_classify_unknown_uuid_returns_404(self, db: None) -> None:
        """UUID inexistente devuelve 404."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="doctor")

        # Act
        with _tenant_context(tenant):
            response = client.post(
                _classify_url(uuid_module.uuid4()), data={"is_favorite": True}, format="json"
            )

        # Assert
        assert response.status_code == 404


# ===========================================================================
# GET /api/v1/pacientes/?segment=date — validación y filtrado
# ===========================================================================


class TestSegmentDateApi:
    """GET /pacientes/?segment=date — validación de parámetros y resultados."""

    def test_segment_date_without_dates_returns_400(self, db: None) -> None:
        """segment=date sin date_from ni date_to devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "date"})

        # Assert
        assert response.status_code == 400

    def test_segment_date_without_date_to_returns_400(self, db: None) -> None:
        """segment=date con date_from pero sin date_to devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(
                LIST_URL, {"segment": "date", "date_from": "2030-01-10"}
            )

        # Assert
        assert response.status_code == 400

    def test_segment_date_without_date_from_returns_400(self, db: None) -> None:
        """segment=date con date_to pero sin date_from devuelve 400."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(
                LIST_URL, {"segment": "date", "date_to": "2030-01-20"}
            )

        # Assert
        assert response.status_code == 400

    def test_segment_date_with_both_dates_returns_200(self, db: None) -> None:
        """segment=date con ambas fechas devuelve 200."""
        # Arrange
        tenant = TenantFactory()
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(
                LIST_URL,
                {"segment": "date", "date_from": "2030-01-10", "date_to": "2030-01-20"},
            )

        # Assert
        assert response.status_code == 200

    def test_segment_date_returns_only_patients_attended_in_range(
        self, db: None
    ) -> None:
        """segment=date devuelve solo pacientes atendidos en el rango de fechas."""
        # Arrange
        tenant = TenantFactory()
        in_range = PatientFactory(tenant=tenant, is_active=True)
        out_range = PatientFactory(tenant=tenant, is_active=True)
        no_cita = PatientFactory(tenant=tenant, is_active=True)

        _attended_appointment(tenant, in_range, _FIXED_DT_IN_RANGE)
        _attended_appointment(
            tenant, out_range,
            datetime.datetime(2030, 1, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        )

        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(
                LIST_URL,
                {
                    "segment": "date",
                    "date_from": "2030-01-10",
                    "date_to": "2030-01-20",
                },
            )

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        ids = {r["id"] for r in results}
        assert str(in_range.id) in ids
        assert str(out_range.id) not in ids
        assert str(no_cita.id) not in ids


# ===========================================================================
# GET /api/v1/pacientes/?segment=favorites
# ===========================================================================


class TestSegmentFavoritesApi:
    """GET /pacientes/?segment=favorites — filtro por is_favorite."""

    def test_favorites_returns_only_favorite_patients(self, db: None) -> None:
        """segment=favorites devuelve solo los marcados como favoritos."""
        # Arrange
        tenant = TenantFactory()
        fav = PatientFactory(tenant=tenant, is_active=True, is_favorite=True)
        not_fav = PatientFactory(tenant=tenant, is_active=True, is_favorite=False)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "favorites"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        ids = {r["id"] for r in results}
        assert str(fav.id) in ids
        assert str(not_fav.id) not in ids

    def test_favorites_tenant_isolation_via_api(self, db: None) -> None:
        """segment=favorites no filtra favoritos de otro tenant vía API."""
        # Arrange
        tenant_a = TenantFactory()
        tenant_b = TenantFactory()
        PatientFactory(tenant=tenant_b, is_active=True, is_favorite=True)
        client = _make_member_client(tenant_a, role="readonly")

        # Act
        with _tenant_context(tenant_a):
            response = client.get(LIST_URL, {"segment": "favorites"})

        # Assert — tenant A no tiene favoritos
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) == 0


# ===========================================================================
# GET /api/v1/pacientes/?segment=vip
# ===========================================================================


class TestSegmentVipApi:
    """GET /pacientes/?segment=vip — filtro por is_vip."""

    def test_vip_returns_only_vip_patients(self, db: None) -> None:
        """segment=vip devuelve solo los marcados como VIP."""
        # Arrange
        tenant = TenantFactory()
        vip = PatientFactory(tenant=tenant, is_active=True, is_vip=True)
        not_vip = PatientFactory(tenant=tenant, is_active=True, is_vip=False)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "vip"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        ids = {r["id"] for r in results}
        assert str(vip.id) in ids
        assert str(not_vip.id) not in ids


# ===========================================================================
# GET /api/v1/pacientes/?segment=recent
# ===========================================================================


class TestSegmentRecentApi:
    """GET /pacientes/?segment=recent — pacientes con al menos una cita atendida."""

    def test_recent_returns_patients_with_attended_appointments(
        self, db: None
    ) -> None:
        """segment=recent incluye al paciente con cita atendida."""
        # Arrange
        tenant = TenantFactory()
        attended = PatientFactory(tenant=tenant, is_active=True)
        no_cita = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, attended, _FIXED_DT_IN_RANGE)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "recent"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        ids = {r["id"] for r in results}
        assert str(attended.id) in ids
        assert str(no_cita.id) not in ids

    def test_recent_response_includes_last_seen_at_and_attended_count(
        self, db: None
    ) -> None:
        """El output de segment=recent incluye last_seen_at y attended_count."""
        # Arrange
        tenant = TenantFactory()
        patient = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, patient, _FIXED_DT_IN_RANGE)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "recent"})

        # Assert
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        # Hay al menos un resultado y el primero tiene los campos requeridos
        assert len(results) >= 1
        first = results[0]
        assert "last_seen_at" in first
        assert "attended_count" in first
        assert first["last_seen_at"] is not None
        assert first["attended_count"] >= 1


# ===========================================================================
# GET /api/v1/pacientes/?segment=potential
# ===========================================================================


class TestSegmentPotentialApi:
    """GET /pacientes/?segment=potential — potenciales vía API."""

    def test_potential_returns_patients_with_cancelled_no_attended(
        self, db: None
    ) -> None:
        """segment=potential incluye paciente con cita cancelada y sin atender."""
        # Arrange
        tenant = TenantFactory()
        cancelled_patient = PatientFactory(tenant=tenant, is_active=True)
        no_cita_patient = PatientFactory(tenant=tenant, is_active=True)
        _cancelled_appointment(tenant, cancelled_patient, _FIXED_DT_IN_RANGE)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "potential"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        ids = {r["id"] for r in results}
        assert str(cancelled_patient.id) in ids
        assert str(no_cita_patient.id) not in ids

    def test_potential_excludes_attended_patients_even_with_cancellations(
        self, db: None
    ) -> None:
        """Un paciente que fue atendido no es 'potential' aunque tenga canceladas."""
        # Arrange
        tenant = TenantFactory()
        attended_and_cancelled = PatientFactory(tenant=tenant, is_active=True)
        _attended_appointment(tenant, attended_and_cancelled, _FIXED_DT_IN_RANGE)
        _cancelled_appointment(
            tenant, attended_and_cancelled, _FIXED_DT_IN_RANGE + datetime.timedelta(days=5)
        )
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL, {"segment": "potential"})

        # Assert
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        ids = {r["id"] for r in results}
        assert str(attended_and_cancelled.id) not in ids


# ===========================================================================
# Output serializer: campos is_favorite, is_vip en la lista general
# ===========================================================================


class TestOutputSerializerFields:
    """Los campos is_favorite, is_vip aparecen en el output de la lista."""

    def test_list_response_includes_is_favorite_and_is_vip_fields(
        self, db: None
    ) -> None:
        """El output de GET /pacientes/ incluye is_favorite e is_vip."""
        # Arrange
        tenant = TenantFactory()
        PatientFactory(tenant=tenant, is_active=True, is_favorite=True, is_vip=False)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL)

        # Assert
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) >= 1
        first = results[0]
        assert "is_favorite" in first
        assert "is_vip" in first
        # El paciente creado tiene is_favorite=True
        assert first["is_favorite"] is True
        assert first["is_vip"] is False

    def test_list_response_null_last_seen_at_for_patient_without_appointments(
        self, db: None
    ) -> None:
        """last_seen_at es null para un paciente sin citas atendidas."""
        # Arrange
        tenant = TenantFactory()
        PatientFactory(tenant=tenant, is_active=True)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL)

        # Assert
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) >= 1
        first = results[0]
        assert "last_seen_at" in first
        assert first["last_seen_at"] is None

    def test_list_response_attended_count_zero_for_patient_without_attended_appointments(
        self, db: None
    ) -> None:
        """attended_count es 0 para un paciente sin citas atendidas."""
        # Arrange
        tenant = TenantFactory()
        PatientFactory(tenant=tenant, is_active=True)
        client = _make_member_client(tenant, role="readonly")

        # Act
        with _tenant_context(tenant):
            response = client.get(LIST_URL)

        # Assert
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        assert len(results) >= 1
        first = results[0]
        assert "attended_count" in first
        assert first["attended_count"] == 0
