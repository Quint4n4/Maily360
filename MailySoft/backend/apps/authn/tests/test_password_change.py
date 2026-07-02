"""
Tests de cambio de contraseña obligatorio (Fase 4):

  - Modelo: must_change_password default False; se activa al crear el dueño
    de una clínica nueva (tenant_and_owner_create) y al crear staff de
    plataforma (platform_staff_create); los seeds lo dejan explícitamente en
    False.
  - GET /api/v1/me/ expone must_change_password.
  - POST /api/v1/auth/change-password/: valida current_password, corre los
    validadores de Django sobre new_password, limpia el flag y audita
    PASSWORD_CHANGE sin contraseñas en metadata.
  - Enforcement centralizado (apps.core.views.enforce_password_change): un
    usuario con must_change_password=True recibe 403
    {"code": "password_change_required"} en endpoints de negocio de clínica
    (TenantAPIView) Y de plataforma (PlatformAPIView), pero SIGUE pudiendo
    llamar me/, refresh/, logout/ y change-password/. Tras cambiarla, el
    endpoint de negocio vuelve a funcionar.
"""

from typing import Any

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import ActionType, AuditLog
from apps.tenancy.models import TenantMembership
from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory

ME_URL = "/api/v1/me/"
CHANGE_PASSWORD_URL = "/api/v1/auth/change-password/"  # noqa: S105 — es una URL, no una contraseña
PLATFORM_METRICAS_URL = "/api/v1/plataforma/metricas/"


# ---------------------------------------------------------------------------
# Fixtures locales
# ---------------------------------------------------------------------------


@pytest.fixture
def clinic_owner_with_password(db: Any) -> tuple[Any, str]:
    """Miembro owner de una clínica con contraseña conocida y must_change_password=False."""
    password = "password-segura-123"  # noqa: S105 — credencial de prueba local, no es secreto
    tenant = TenantFactory(status="active")
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
    )
    user = membership.user
    user.set_password(password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    return user, password


@pytest.fixture
def super_admin_with_password(db: Any) -> tuple[Any, str]:
    """Usuario de plataforma super_admin con contraseña conocida."""
    password = "password-segura-123"  # noqa: S105 — credencial de prueba local, no es secreto
    user = UserFactory(
        is_platform_staff=True,
        is_staff=True,
        platform_role="super_admin",
    )
    user.set_password(password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    return user, password


# ---------------------------------------------------------------------------
# must_change_password — defaults y altas
# ---------------------------------------------------------------------------


def test_must_change_password_default_false(db: Any) -> None:
    user = UserFactory()
    assert user.must_change_password is False


def test_alta_de_clinica_marca_owner_must_change_password(db: Any) -> None:
    from apps.plataforma.services import tenant_and_owner_create

    actor = UserFactory(is_platform_staff=True, platform_role="super_admin")
    resultado = tenant_and_owner_create(
        actor=actor,
        name="Clínica Nueva Fase 4",
        owner_email="duenio.fase4@maily.test",
        owner_first_name="Dueño",
        owner_last_name="Nuevo",
    )
    owner_user = resultado["owner"].user
    owner_user.refresh_from_db()
    assert owner_user.must_change_password is True


def test_alta_de_staff_marca_must_change_password(db: Any) -> None:
    from apps.plataforma.services import platform_staff_create

    actor = UserFactory(is_platform_staff=True, platform_role="super_admin")
    resultado = platform_staff_create(
        actor=actor,
        email="staff.nuevo@maily.test",
        first_name="Staff",
        last_name="Nuevo",
        platform_role="engineering",
    )
    assert resultado["user"].must_change_password is True


# ---------------------------------------------------------------------------
# /me/ expone must_change_password
# ---------------------------------------------------------------------------


def test_me_expone_must_change_password_false(
    db: Any, clinic_owner_with_password: tuple[Any, str]
) -> None:
    user, _password = clinic_owner_with_password
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(ME_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["must_change_password"] is False


def test_me_expone_must_change_password_true(db: Any) -> None:
    user = UserFactory(must_change_password=True)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(ME_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["must_change_password"] is True


# ---------------------------------------------------------------------------
# POST /auth/change-password/ — camino feliz y validaciones
# ---------------------------------------------------------------------------


def test_change_password_requires_authentication(db: Any) -> None:
    client = APIClient()
    response = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": "x", "new_password": "y"},
        format="json",
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_change_password_current_incorrecta_400(
    db: Any, clinic_owner_with_password: tuple[Any, str]
) -> None:
    user, _password = clinic_owner_with_password
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": "contraseña-incorrecta", "new_password": "NuevaClaveSegura123!"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_change_password_nueva_debil_400(
    db: Any, clinic_owner_with_password: tuple[Any, str]
) -> None:
    user, password = clinic_owner_with_password
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": password, "new_password": "12345678"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_change_password_feliz_limpia_flag_y_audita(db: Any) -> None:
    password = "password-segura-123"  # noqa: S105 — credencial de prueba local, no es secreto
    user = UserFactory(must_change_password=True)
    user.set_password(password)
    user.save(update_fields=["password"])

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": password, "new_password": "NuevaClaveSegura123!"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.check_password("NuevaClaveSegura123!") is True

    log = AuditLog.all_objects.filter(action=ActionType.PASSWORD_CHANGE).latest("created_at")
    assert log.actor_id == user.id
    assert "NuevaClaveSegura123!" not in str(log.metadata)
    assert password not in str(log.metadata)


# ---------------------------------------------------------------------------
# Enforcement — 403 password_change_required en endpoints de negocio
# ---------------------------------------------------------------------------


def test_enforcement_bloquea_endpoint_de_clinica(db: Any) -> None:
    tenant = TenantFactory(status="active")
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
    )
    membership.user.must_change_password = True
    membership.user.save(update_fields=["must_change_password"])

    client = APIClient()
    client.force_authenticate(user=membership.user)

    response = client.get(reverse("patient-list-create"))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["code"] == "password_change_required"


def test_enforcement_bloquea_endpoint_de_plataforma(db: Any) -> None:
    user = UserFactory(
        is_platform_staff=True,
        platform_role="super_admin",
        must_change_password=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(PLATFORM_METRICAS_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["code"] == "password_change_required"


def test_enforcement_no_bloquea_usuario_normal_de_clinica(db: Any) -> None:
    tenant = TenantFactory(status="active")
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
    )
    assert membership.user.must_change_password is False

    client = APIClient()
    client.force_authenticate(user=membership.user)

    response = client.get(reverse("patient-list-create"))

    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Enforcement — endpoints exentos (whitelist implícita por herencia)
# ---------------------------------------------------------------------------


def test_enforcement_no_bloquea_me(db: Any) -> None:
    user = UserFactory(must_change_password=True)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(ME_URL)

    assert response.status_code == status.HTTP_200_OK


def test_enforcement_no_bloquea_change_password(db: Any) -> None:
    password = "password-segura-123"  # noqa: S105 — credencial de prueba local, no es secreto
    user = UserFactory(must_change_password=True)
    user.set_password(password)
    user.save(update_fields=["password"])

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": password, "new_password": "OtraClaveSegura456!"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK


def test_enforcement_no_bloquea_refresh(db: Any) -> None:
    """El refresh no depende de TenantAPIView/PlatformAPIView: siempre exento.

    CookieTokenRefreshView hereda de APIView directo (no de TenantAPIView ni
    PlatformAPIView), así que el candado enforce_password_change nunca se
    ejecuta para este endpoint sin importar must_change_password. Sin cookie
    de refresh válida da 401 por falta de sesión, NUNCA 403 por el candado.
    """
    client = APIClient()
    response = client.post("/api/v1/auth/refresh/")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_enforcement_no_bloquea_logout(db: Any) -> None:
    user = UserFactory(must_change_password=True)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post("/api/v1/auth/logout/")

    assert response.status_code == status.HTTP_205_RESET_CONTENT


# ---------------------------------------------------------------------------
# Enforcement — tras cambiar la contraseña, el endpoint de negocio funciona
# ---------------------------------------------------------------------------


def test_endpoint_de_negocio_funciona_tras_cambiar_password(db: Any) -> None:
    password = "password-segura-123"  # noqa: S105 — credencial de prueba local, no es secreto
    tenant = TenantFactory(status="active")
    membership = TenantMembershipFactory(
        tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True
    )
    membership.user.set_password(password)
    membership.user.must_change_password = True
    membership.user.save(update_fields=["password", "must_change_password"])

    client = APIClient()
    client.force_authenticate(user=membership.user)

    blocked = client.get(reverse("patient-list-create"))
    assert blocked.status_code == status.HTTP_403_FORBIDDEN

    changed = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": password, "new_password": "NuevaClaveSegura789!"},
        format="json",
    )
    assert changed.status_code == status.HTTP_200_OK

    unblocked = client.get(reverse("patient-list-create"))
    assert unblocked.status_code == status.HTTP_200_OK


def test_endpoint_de_plataforma_funciona_tras_cambiar_password(
    db: Any, super_admin_with_password: tuple[Any, str]
) -> None:
    user, password = super_admin_with_password
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])

    client = APIClient()
    client.force_authenticate(user=user)

    blocked = client.get(PLATFORM_METRICAS_URL)
    assert blocked.status_code == status.HTTP_403_FORBIDDEN

    changed = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": password, "new_password": "NuevaClaveSegura999!"},
        format="json",
    )
    assert changed.status_code == status.HTTP_200_OK

    unblocked = client.get(PLATFORM_METRICAS_URL)
    assert unblocked.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Throttle dedicado (auth_password_change) — hallazgo ALTO de seguridad
# ---------------------------------------------------------------------------
#
# No se simula el rate real (haría el test flaky/lento); solo se verifica que
# la vista está configurada con el throttle_scope correcto, igual que
# MailyTokenObtainPairView (auth_login).


def test_password_change_api_usa_throttle_dedicado() -> None:
    from rest_framework.throttling import ScopedRateThrottle

    from apps.authn.views import PasswordChangeApi

    assert PasswordChangeApi.throttle_classes == [ScopedRateThrottle]
    assert PasswordChangeApi.throttle_scope == "auth_password_change"


# ---------------------------------------------------------------------------
# Rotación de la sesión propia tras cambiar contraseña (recomendado reviewer)
# ---------------------------------------------------------------------------
#
# password_change() blacklistea TODOS los OutstandingToken del usuario,
# incluida la cookie de refresh vigente. Sin rotación, la sesión propia
# moriría silenciosamente en cuanto expirara el access token en memoria.
# PasswordChangeApi debe emitir un refresh NUEVO y setearlo en la misma
# cookie httpOnly que usa el login.


COOKIE_NAME = "maily_refresh"
REFRESH_URL = "/api/v1/auth/refresh/"


def test_change_password_feliz_rota_cookie_de_refresh(db: Any) -> None:
    password = "password-segura-123"  # noqa: S105 — credencial de prueba local, no es secreto
    user = UserFactory(must_change_password=False)
    user.set_password(password)
    user.save(update_fields=["password"])

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": password, "new_password": "NuevaClaveSegura123!"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert COOKIE_NAME in response.cookies
    nueva_cookie = response.cookies[COOKIE_NAME]
    assert nueva_cookie.value != ""
    assert nueva_cookie["httponly"] is True
    assert nueva_cookie["samesite"] == "Strict"
    assert nueva_cookie["path"] == "/api/v1/auth/"


def test_change_password_refresh_viejo_queda_invalidado(db: Any) -> None:
    """El refresh que estaba vigente ANTES del cambio queda blacklisteado (401)."""
    from rest_framework_simplejwt.tokens import RefreshToken

    password = "password-segura-123"  # noqa: S105 — credencial de prueba local, no es secreto
    user = UserFactory(must_change_password=False)
    user.set_password(password)
    user.save(update_fields=["password"])

    old_refresh = RefreshToken.for_user(user)

    client = APIClient()
    client.force_authenticate(user=user)
    client.cookies[COOKIE_NAME] = str(old_refresh)

    changed = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": password, "new_password": "NuevaClaveSegura123!"},
        format="json",
    )
    assert changed.status_code == status.HTTP_200_OK

    client_viejo = APIClient()
    client_viejo.cookies[COOKIE_NAME] = str(old_refresh)
    response_viejo = client_viejo.post(REFRESH_URL)
    assert response_viejo.status_code == status.HTTP_401_UNAUTHORIZED


def test_change_password_refresh_nuevo_funciona(db: Any) -> None:
    """El refresh nuevo emitido tras el cambio SÍ sirve para pedir un access nuevo."""
    password = "password-segura-123"  # noqa: S105 — credencial de prueba local, no es secreto
    user = UserFactory(must_change_password=False)
    user.set_password(password)
    user.save(update_fields=["password"])

    client = APIClient()
    client.force_authenticate(user=user)

    changed = client.post(
        CHANGE_PASSWORD_URL,
        {"current_password": password, "new_password": "NuevaClaveSegura123!"},
        format="json",
    )
    assert changed.status_code == status.HTTP_200_OK
    nuevo_refresh_value = changed.cookies[COOKIE_NAME].value

    client_nuevo = APIClient()
    client_nuevo.cookies[COOKIE_NAME] = nuevo_refresh_value
    response_nuevo = client_nuevo.post(REFRESH_URL)
    assert response_nuevo.status_code == status.HTTP_200_OK
    assert "access" in response_nuevo.data
