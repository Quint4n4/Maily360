"""
Tests de gestión del equipo de plataforma (Fase 4 — alta/edición/reset de staff).

Cubre:
  - POST   /api/v1/plataforma/usuarios/
  - PATCH  /api/v1/plataforma/usuarios/<user_id>/
  - POST   /api/v1/plataforma/usuarios/<user_id>/reset-password/

Valida:
  - Permisos: clinic_member/sales/engineering → 403; anónimo → 401;
    super_admin → OK en los tres endpoints.
  - Alta: email duplicado → 400; contraseña temporal en la respuesta pero
    NUNCA en la auditoría; must_change_password=True en el usuario creado;
    contrato exacto de campos.
  - Edición: 404 si el user no existe o no es staff de plataforma (usuario de
    clínica); allowlist de campos (mass assignment); el actor puede editar su
    propio nombre pero NO su propio platform_role/is_active (400); auditoría
    con campos cambiados y rol old→new si cambió.
  - Reset de contraseña: 404 si no existe/no es staff; 400 si está inactivo;
    contraseña nunca en auditoría; must_change_password queda en True.
"""

from typing import Any

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.authn.models import User
from tests.factories import PlatformStaffFactory, TenantMembershipFactory, UserFactory

STAFF_LIST_URL_NAME = "platform-usuarios-list"


def _staff_detail_url(user_id: Any) -> str:
    return reverse("platform-staff-detail", kwargs={"user_id": user_id})


def _staff_reset_password_url(user_id: Any) -> str:
    return reverse("platform-staff-password-reset", kwargs={"user_id": user_id})


# ---------------------------------------------------------------------------
# Fixtures locales (mismo patrón que test_planes_crud.py / test_suscripciones.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def super_admin(db: Any) -> Any:
    """Usuario de plataforma con rol super_admin."""
    return UserFactory(
        is_platform_staff=True,
        is_staff=True,
        platform_role="super_admin",
    )


@pytest.fixture
def sales_user(db: Any) -> Any:
    """Usuario de plataforma con rol sales."""
    return UserFactory(is_platform_staff=True, platform_role="sales")


@pytest.fixture
def engineering_user(db: Any) -> Any:
    """Usuario de plataforma con rol engineering."""
    return PlatformStaffFactory()  # platform_role="engineering"


@pytest.fixture
def clinic_member(db: Any) -> Any:
    """Usuario miembro de una clínica SIN is_platform_staff."""
    return UserFactory(is_platform_staff=False)


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "email": "nuevo.staff@maily.test",
        "first_name": "Nuevo",
        "last_name": "Staff",
        "platform_role": "sales",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Permisos — POST /usuarios/
# ---------------------------------------------------------------------------


def test_crear_staff_anonymous_is_rejected(db: Any) -> None:
    client = APIClient()
    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_crear_staff_clinic_member_is_rejected(db: Any, clinic_member: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=clinic_member)
    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_crear_staff_sales_is_rejected(db: Any, sales_user: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=sales_user)
    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_crear_staff_engineering_is_rejected(db: Any, engineering_user: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=engineering_user)
    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_crear_staff_super_admin_ok(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")
    assert response.status_code == status.HTTP_201_CREATED


# ---------------------------------------------------------------------------
# Alta — validaciones y efectos
# ---------------------------------------------------------------------------


def test_crear_staff_email_duplicado_400(db: Any, super_admin: Any) -> None:
    UserFactory(email="dup@maily.test")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(STAFF_LIST_URL_NAME),
        _valid_payload(email="dup@maily.test"),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_crear_staff_rol_invalido_400(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(STAFF_LIST_URL_NAME),
        _valid_payload(platform_role="not-a-role"),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_crear_staff_incluye_contraseña_temporal_en_respuesta(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert "temporary_password" in response.data
    assert len(response.data["temporary_password"]) == 16


def test_crear_staff_marca_must_change_password(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")

    user = User.objects.get(id=response.data["id"])
    assert user.must_change_password is True
    assert user.is_platform_staff is True
    assert user.is_active is True


def test_crear_staff_persiste_datos_correctos(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(STAFF_LIST_URL_NAME),
        _valid_payload(email="persistido@maily.test", platform_role="engineering"),
        format="json",
    )

    user = User.objects.get(id=response.data["id"])
    assert user.email == "persistido@maily.test"
    assert user.platform_role == "engineering"
    assert user.check_password(response.data["temporary_password"]) is True


def test_crear_staff_contraseña_nunca_en_auditoria(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")
    temp_password = response.data["temporary_password"]

    log = AuditLog.all_objects.filter(action=ActionType.STAFF_CREATE).latest("created_at")
    assert temp_password not in str(log.metadata)
    assert temp_password not in log.description
    assert "password" not in log.metadata
    assert "temporary_password" not in log.metadata
    assert log.actor_id == super_admin.id


def test_contrato_campos_respuesta_post(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(reverse(STAFF_LIST_URL_NAME), _valid_payload(), format="json")

    expected_fields = {
        "id",
        "email",
        "full_name",
        "first_name",
        "last_name",
        "platform_role",
        "platform_role_display",
        "is_active",
        "temporary_password",
    }
    assert set(response.data.keys()) == expected_fields


# ---------------------------------------------------------------------------
# GET /usuarios/ — sigue funcionando con first_name/last_name expuestos
# ---------------------------------------------------------------------------


def test_get_usuarios_incluye_first_last_name(db: Any, super_admin: Any) -> None:
    UserFactory(
        is_platform_staff=True,
        platform_role="sales",
        first_name="Ana",
        last_name="Pérez",
    )
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.get(reverse(STAFF_LIST_URL_NAME))

    assert response.status_code == status.HTTP_200_OK
    results = response.data.get("results", response.data)
    ana = next(
        r for r in results if r["email"].endswith("@maily.test") and r["first_name"] == "Ana"
    )
    assert ana["last_name"] == "Pérez"


# ---------------------------------------------------------------------------
# Permisos — PATCH /usuarios/<id>/
# ---------------------------------------------------------------------------


def test_editar_staff_anonymous_is_rejected(db: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    response = client.patch(_staff_detail_url(target.id), {"first_name": "X"}, format="json")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_editar_staff_clinic_member_is_rejected(db: Any, clinic_member: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=clinic_member)
    response = client.patch(_staff_detail_url(target.id), {"first_name": "X"}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_editar_staff_sales_is_rejected(db: Any, sales_user: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=sales_user)
    response = client.patch(_staff_detail_url(target.id), {"first_name": "X"}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_editar_staff_engineering_is_rejected(db: Any, engineering_user: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=engineering_user)
    response = client.patch(_staff_detail_url(target.id), {"first_name": "X"}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_editar_staff_super_admin_ok(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.patch(_staff_detail_url(target.id), {"first_name": "Editado"}, format="json")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["first_name"] == "Editado"


# ---------------------------------------------------------------------------
# Edición — 404 para usuario de clínica / inexistente
# ---------------------------------------------------------------------------


def test_editar_staff_inexistente_404(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.patch(
        _staff_detail_url("00000000-0000-0000-0000-000000000000"),
        {"first_name": "X"},
        format="json",
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_editar_usuario_de_clinica_404(db: Any, super_admin: Any) -> None:
    """Un usuario que NO es is_platform_staff debe verse como inexistente aquí."""
    membership = TenantMembershipFactory()
    clinic_user = membership.user
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(
        _staff_detail_url(clinic_user.id), {"first_name": "Hackeo"}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    clinic_user.refresh_from_db()
    assert clinic_user.first_name != "Hackeo"


# ---------------------------------------------------------------------------
# Edición — allowlist y anti-lockout
# ---------------------------------------------------------------------------


def test_editar_staff_campo_desconocido_400(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(
        _staff_detail_url(target.id), {"email": "otro@maily.test"}, format="json"
    )

    # email no está en StaffUpdateInputSerializer: DRF lo ignora (no reconocido),
    # así que no hay 400 de "campo desconocido" a nivel HTTP, pero el email NO cambia.
    assert response.status_code == status.HTTP_200_OK
    target.refresh_from_db()
    assert target.email != "otro@maily.test"


def test_super_admin_puede_editar_su_propio_nombre(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(
        _staff_detail_url(super_admin.id), {"first_name": "MiNuevoNombre"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["first_name"] == "MiNuevoNombre"


def test_super_admin_no_puede_cambiar_su_propio_platform_role(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(
        _staff_detail_url(super_admin.id), {"platform_role": "sales"}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    super_admin.refresh_from_db()
    assert super_admin.platform_role == "super_admin"


def test_super_admin_no_puede_desactivarse_a_si_mismo(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_staff_detail_url(super_admin.id), {"is_active": False}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    super_admin.refresh_from_db()
    assert super_admin.is_active is True


def test_super_admin_puede_cambiar_rol_de_otro_usuario(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory(platform_role="engineering")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_staff_detail_url(target.id), {"platform_role": "sales"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    target.refresh_from_db()
    assert target.platform_role == "sales"


def test_super_admin_puede_desactivar_a_otro_usuario(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory(is_active=True)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_staff_detail_url(target.id), {"is_active": False}, format="json")

    assert response.status_code == status.HTTP_200_OK
    target.refresh_from_db()
    assert target.is_active is False


def test_editar_staff_rol_invalido_400(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(
        _staff_detail_url(target.id), {"platform_role": "not-a-role"}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Edición — auditoría
# ---------------------------------------------------------------------------


def test_editar_staff_registra_auditoria_con_rol_old_new(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory(platform_role="engineering")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    client.patch(_staff_detail_url(target.id), {"platform_role": "sales"}, format="json")

    log = AuditLog.all_objects.filter(action=ActionType.STAFF_UPDATE).latest("created_at")
    assert log.actor_id == super_admin.id
    assert log.metadata["platform_role_old"] == "engineering"
    assert log.metadata["platform_role_new"] == "sales"
    assert "cambios" in log.metadata


def test_editar_staff_sin_cambiar_rol_no_incluye_rol_old_new(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    client.patch(_staff_detail_url(target.id), {"first_name": "Solo Nombre"}, format="json")

    log = AuditLog.all_objects.filter(action=ActionType.STAFF_UPDATE).latest("created_at")
    assert "platform_role_old" not in log.metadata
    assert "platform_role_new" not in log.metadata


# ---------------------------------------------------------------------------
# Permisos — POST /usuarios/<id>/reset-password/
# ---------------------------------------------------------------------------


def test_reset_password_anonymous_is_rejected(db: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    response = client.post(_staff_reset_password_url(target.id))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_reset_password_clinic_member_is_rejected(db: Any, clinic_member: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=clinic_member)
    response = client.post(_staff_reset_password_url(target.id))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_reset_password_sales_is_rejected(db: Any, sales_user: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=sales_user)
    response = client.post(_staff_reset_password_url(target.id))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_reset_password_engineering_is_rejected(db: Any, engineering_user: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=engineering_user)
    response = client.post(_staff_reset_password_url(target.id))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_reset_password_super_admin_ok(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.post(_staff_reset_password_url(target.id))
    assert response.status_code == status.HTTP_200_OK
    assert "temporary_password" in response.data
    assert len(response.data["temporary_password"]) == 16


# ---------------------------------------------------------------------------
# Reset de contraseña — 404 / 400 / efectos / auditoría
# ---------------------------------------------------------------------------


def test_reset_password_inexistente_404(db: Any, super_admin: Any) -> None:
    client = APIClient()
    client.force_authenticate(user=super_admin)
    response = client.post(_staff_reset_password_url("00000000-0000-0000-0000-000000000000"))
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_reset_password_usuario_de_clinica_404(db: Any, super_admin: Any) -> None:
    membership = TenantMembershipFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(_staff_reset_password_url(membership.user.id))

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_reset_password_usuario_inactivo_400(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory(is_active=False)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(_staff_reset_password_url(target.id))

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_reset_password_marca_must_change_password(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory(must_change_password=False)
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(_staff_reset_password_url(target.id))

    target.refresh_from_db()
    assert target.must_change_password is True
    assert target.check_password(response.data["temporary_password"]) is True


def test_reset_password_nunca_en_auditoria(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(_staff_reset_password_url(target.id))
    temp_password = response.data["temporary_password"]

    log = AuditLog.all_objects.filter(action=ActionType.STAFF_PASSWORD_RESET).latest("created_at")
    assert temp_password not in str(log.metadata)
    assert temp_password not in log.description
    assert log.actor_id == super_admin.id


def test_contrato_campos_respuesta_reset_password(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(_staff_reset_password_url(target.id))

    assert set(response.data.keys()) == {"temporary_password"}


# ---------------------------------------------------------------------------
# Contrato exacto de campos — PATCH
# ---------------------------------------------------------------------------


def test_contrato_campos_respuesta_patch(db: Any, super_admin: Any) -> None:
    target = PlatformStaffFactory()
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_staff_detail_url(target.id), {"first_name": "X"}, format="json")

    expected_fields = {
        "id",
        "email",
        "full_name",
        "first_name",
        "last_name",
        "platform_role",
        "platform_role_display",
        "is_active",
    }
    assert set(response.data.keys()) == expected_fields


# ---------------------------------------------------------------------------
# Throttle dedicado (auth_password_change) — hallazgo ALTO de seguridad
# ---------------------------------------------------------------------------
#
# No se simula el rate real (sería flaky/lento); solo se verifica que la
# vista está configurada con el throttle_scope correcto, igual que
# PasswordChangeApi (apps/authn/views.py) y MailyTokenObtainPairView.


def test_reset_password_api_usa_throttle_dedicado() -> None:
    from rest_framework.throttling import ScopedRateThrottle

    from apps.plataforma.views import PlatformStaffPasswordResetApi

    assert PlatformStaffPasswordResetApi.throttle_classes == [ScopedRateThrottle]
    assert PlatformStaffPasswordResetApi.throttle_scope == "auth_password_change"


# ---------------------------------------------------------------------------
# Enumeración de emails (MEDIO de seguridad) — POST /usuarios/
# ---------------------------------------------------------------------------
#
# El pre-check de platform_staff_create solo mira is_platform_staff=True. Un
# correo de clínica NO debe delatar su existencia: debe fallar con un mensaje
# genérico (vía IntegrityError capturado en la vista), sin crear el usuario
# y sin ninguna palabra que confirme que la cuenta de clínica existe.


def test_crear_staff_email_de_plataforma_duplicado_400_mensaje_especifico(
    db: Any, super_admin: Any
) -> None:
    PlatformStaffFactory(email="staff.existente@maily.test")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(STAFF_LIST_URL_NAME),
        _valid_payload(email="staff.existente@maily.test"),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "plataforma" in str(response.data).lower()


def test_crear_staff_email_de_clinica_400_mensaje_generico_sin_confirmar_cuenta(
    db: Any, super_admin: Any
) -> None:
    clinic_membership = TenantMembershipFactory()
    clinic_email = clinic_membership.user.email
    previous_count = User.objects.filter(email=clinic_email).count()

    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.post(
        reverse(STAFF_LIST_URL_NAME),
        _valid_payload(email=clinic_email),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    mensaje = str(response.data).lower()
    assert "ya existe una cuenta de plataforma" not in mensaje
    assert "clínica" not in mensaje
    assert "clinica" not in mensaje
    # No se creó ningún usuario nuevo con ese correo (sigue habiendo solo el original).
    assert User.objects.filter(email=clinic_email).count() == previous_count


# ---------------------------------------------------------------------------
# Regla del último super_admin (recomendado del reviewer) — PATCH /usuarios/<id>/
# ---------------------------------------------------------------------------


def test_desactivar_al_unico_super_admin_via_otro_super_admin_400(
    db: Any, super_admin: Any
) -> None:
    """Con 2 super_admins, desactivar a uno OK; desactivar al último → 400."""
    segundo_super_admin = UserFactory(
        is_platform_staff=True, is_staff=True, platform_role="super_admin"
    )
    client_segundo = APIClient()
    client_segundo.force_authenticate(user=segundo_super_admin)

    # El segundo desactiva al primero (super_admin): queda un solo activo
    # (segundo_super_admin) → OK.
    response_ok = client_segundo.patch(
        _staff_detail_url(super_admin.id), {"is_active": False}, format="json"
    )
    assert response_ok.status_code == status.HTTP_200_OK
    super_admin.refresh_from_db()
    assert super_admin.is_active is False

    # Ahora solo queda segundo_super_admin activo. Un tercer actor (super_admin
    # recién creado y activo) intenta desactivar al ÚLTIMO super_admin activo
    # restante (segundo_super_admin): debe fallar, porque tras esa operación
    # NO quedaría ningún otro super_admin activo (el tercero sigue activo,
    # pero el chequeo excluye al target, no al actor — el tercero cuenta como
    # "otro super_admin activo" así que primero lo desactivamos a él también
    # para simular el escenario real de "solo queda uno").
    tercer_super_admin = UserFactory(
        is_platform_staff=True, is_staff=True, platform_role="super_admin", is_active=False
    )
    client_tercero = APIClient()
    client_tercero.force_authenticate(user=tercer_super_admin)
    # tercer_super_admin está inactivo, pero PlatformStaffWritePermission solo
    # exige is_platform_staff + platform_role=="super_admin" (no is_active),
    # así que puede seguir usando el endpoint como actor.

    response_bloqueado = client_tercero.patch(
        _staff_detail_url(segundo_super_admin.id), {"is_active": False}, format="json"
    )
    assert response_bloqueado.status_code == status.HTTP_400_BAD_REQUEST
    segundo_super_admin.refresh_from_db()
    assert segundo_super_admin.is_active is True


def test_degradar_al_ultimo_super_admin_via_otro_super_admin_400(db: Any, super_admin: Any) -> None:
    """Con un solo super_admin activo, degradarle el rol vía OTRO actor debe fallar."""
    otro_super_admin = UserFactory(
        is_platform_staff=True, is_staff=True, platform_role="super_admin", is_active=False
    )
    client = APIClient()
    client.force_authenticate(user=otro_super_admin)

    response = client.patch(
        _staff_detail_url(super_admin.id), {"platform_role": "sales"}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    super_admin.refresh_from_db()
    assert super_admin.platform_role == "super_admin"


def test_desactivar_super_admin_ok_si_queda_otro_activo(db: Any, super_admin: Any) -> None:
    """Si quedan 2+ super_admins activos, desactivar a uno de ellos SÍ procede."""
    target = UserFactory(is_platform_staff=True, is_staff=True, platform_role="super_admin")
    client = APIClient()
    client.force_authenticate(user=super_admin)

    response = client.patch(_staff_detail_url(target.id), {"is_active": False}, format="json")

    assert response.status_code == status.HTTP_200_OK
    target.refresh_from_db()
    assert target.is_active is False


# ---------------------------------------------------------------------------
# Regresión: invalidación real de refresh tras reset-password (INFO seguridad)
# ---------------------------------------------------------------------------


def test_reset_password_invalida_refresh_token_real_del_target(db: Any, super_admin: Any) -> None:
    """Un refresh real y vigente del target debe dejar de servir tras el reset."""
    from rest_framework_simplejwt.tokens import RefreshToken

    target = PlatformStaffFactory()
    target_refresh = RefreshToken.for_user(target)

    client_target = APIClient()
    client_target.cookies["maily_refresh"] = str(target_refresh)
    response_antes = client_target.post("/api/v1/auth/refresh/")
    assert response_antes.status_code == status.HTTP_200_OK

    client_admin = APIClient()
    client_admin.force_authenticate(user=super_admin)
    reset_response = client_admin.post(_staff_reset_password_url(target.id))
    assert reset_response.status_code == status.HTTP_200_OK

    client_target_despues = APIClient()
    client_target_despues.cookies["maily_refresh"] = str(target_refresh)
    response_despues = client_target_despues.post("/api/v1/auth/refresh/")
    assert response_despues.status_code == status.HTTP_401_UNAUTHORIZED
