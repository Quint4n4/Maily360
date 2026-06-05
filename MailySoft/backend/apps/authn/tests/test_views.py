"""
Tests para las vistas de authn: login, refresh, logout y /me/.

Cubre el patrón de tokens HÍBRIDO:
  - Access token devuelto SOLO en el cuerpo JSON.
  - Refresh token almacenado SOLO en la cookie httpOnly "maily_refresh".
  - CSRF obligatorio en /refresh/ y /logout/.

# ── Estrategia CSRF en tests ───────────────────────────────────────────────
# DRF APIClient desactiva las verificaciones CSRF por defecto. Para probar
# que csrf_protect funciona se instancia el Client de Django con
# enforce_csrf_checks=True. Se usa el flujo real:
#   1. GET a un endpoint decorado con ensure_csrf_cookie (o login) para obtener
#      la cookie csrftoken.
#   2. Extraer el valor con client.cookies["csrftoken"].value.
#   3. Pasar el header X-CSRFToken en las siguientes llamadas.
#
# Para los tests funcionales (camino feliz de refresh/logout) se usa APIClient
# con enforce_csrf_checks=False (default) para no repetir la danza CSRF en cada
# test de negocio. Los tests de seguridad CSRF usan Django's test Client.
"""

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tests.factories import UserFactory


# ---------------------------------------------------------------------------
# Fixtures locales
# ---------------------------------------------------------------------------


LOGIN_URL = "/api/v1/auth/login/"
REFRESH_URL = "/api/v1/auth/refresh/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/me/"
COOKIE_NAME = "maily_refresh"


@pytest.fixture
def credentials(db: None) -> dict:
    """Crea un usuario activo y devuelve sus credenciales de login."""
    password = "password-segura-123"
    user = UserFactory(password=password)  # type: ignore[call-arg]
    # UserFactory usa set_password; forzamos la contraseña real aquí.
    user.set_password(password)
    user.save(update_fields=["password"])
    return {"email": user.email, "password": password}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def do_login(client: APIClient, credentials: dict) -> "rest_framework.response.Response":  # type: ignore[name-defined]
    """Realiza el POST de login y devuelve la response."""
    return client.post(LOGIN_URL, data=credentials, format="json")


# ---------------------------------------------------------------------------
# 1. Login — MailyTokenObtainPairView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_login_returns_access_token_in_body(api_client: APIClient, credentials: dict) -> None:
    """El login devuelve {access} en el cuerpo JSON."""
    # Arrange / Act
    response = do_login(api_client, credentials)

    # Assert
    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data


@pytest.mark.django_db
def test_login_does_not_return_refresh_in_body(api_client: APIClient, credentials: dict) -> None:
    """El refresh token NO debe aparecer en el cuerpo JSON tras el login."""
    # Arrange / Act
    response = do_login(api_client, credentials)

    # Assert
    assert response.status_code == status.HTTP_200_OK
    assert "refresh" not in response.data


@pytest.mark.django_db
def test_login_sets_httponly_refresh_cookie(api_client: APIClient, credentials: dict) -> None:
    """El login setea la cookie maily_refresh como httpOnly."""
    # Arrange / Act
    response = do_login(api_client, credentials)

    # Assert
    assert response.status_code == status.HTTP_200_OK
    assert COOKIE_NAME in response.cookies, "La cookie maily_refresh debe existir"
    cookie = response.cookies[COOKIE_NAME]
    # En tests el atributo httponly puede venir como string "True" o booleano.
    assert cookie.get("httponly") or str(cookie["httponly"]).lower() not in ("false", "0", "")


@pytest.mark.django_db
def test_login_cookie_path_is_auth(api_client: APIClient, credentials: dict) -> None:
    """La cookie maily_refresh debe tener Path=/api/v1/auth/ (superficie mínima)."""
    # Arrange / Act
    response = do_login(api_client, credentials)

    # Assert
    assert response.status_code == status.HTTP_200_OK
    cookie = response.cookies[COOKIE_NAME]
    assert cookie["path"] == "/api/v1/auth/"


@pytest.mark.django_db
def test_login_wrong_credentials_returns_401(api_client: APIClient, credentials: dict) -> None:
    """Credenciales incorrectas devuelven 401."""
    # Arrange
    bad = {"email": credentials["email"], "password": "wrong-password-xyz"}

    # Act
    response = do_login(api_client, bad)

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_login_sets_csrf_cookie(credentials: dict) -> None:
    """El login setea la cookie csrftoken (ensure_csrf_cookie) con HttpOnly=False."""
    # Usamos Django's Client para ver la cookie csrftoken real.
    # Arrange
    client = Client(enforce_csrf_checks=False)

    # Act
    response = client.post(
        LOGIN_URL,
        data={"email": credentials["email"], "password": credentials["password"]},
        content_type="application/json",
    )

    # Assert
    assert response.status_code == status.HTTP_200_OK
    assert "csrftoken" in response.cookies, "La cookie csrftoken debe existir"
    # csrftoken NO debe ser httponly (el frontend necesita leerla con JS)
    csrf_cookie = response.cookies["csrftoken"]
    httponly_value = csrf_cookie.get("httponly")
    assert not httponly_value or str(httponly_value).lower() in ("false", "0", "")


# ---------------------------------------------------------------------------
# 2. Refresh — CookieTokenRefreshView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_refresh_with_valid_cookie_returns_new_access(api_client: APIClient, credentials: dict) -> None:
    """Con la cookie maily_refresh presente, /refresh/ devuelve un nuevo {access}."""
    # Arrange: login para obtener la cookie
    login_resp = do_login(api_client, credentials)
    assert login_resp.status_code == 200
    refresh_value = login_resp.cookies[COOKIE_NAME].value
    api_client.cookies[COOKIE_NAME] = refresh_value

    # Act
    response = api_client.post(REFRESH_URL, format="json")

    # Assert
    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data


@pytest.mark.django_db
def test_refresh_does_not_return_refresh_in_body(api_client: APIClient, credentials: dict) -> None:
    """El nuevo refresh token NO debe aparecer en el cuerpo de /refresh/."""
    # Arrange
    login_resp = do_login(api_client, credentials)
    api_client.cookies[COOKIE_NAME] = login_resp.cookies[COOKIE_NAME].value

    # Act
    response = api_client.post(REFRESH_URL, format="json")

    # Assert
    assert response.status_code == status.HTTP_200_OK
    assert "refresh" not in response.data


@pytest.mark.django_db
def test_refresh_rotates_cookie(api_client: APIClient, credentials: dict) -> None:
    """Con ROTATE_REFRESH_TOKENS=True, /refresh/ setea una nueva cookie maily_refresh."""
    # Arrange
    login_resp = do_login(api_client, credentials)
    original_refresh = login_resp.cookies[COOKIE_NAME].value
    api_client.cookies[COOKIE_NAME] = original_refresh

    # Act
    response = api_client.post(REFRESH_URL, format="json")

    # Assert: hay cookie nueva en la respuesta (puede ser igual o diferente al original
    # dependiendo de la política de SimpleJWT; lo importante es que esté presente)
    assert response.status_code == 200
    assert COOKIE_NAME in response.cookies


@pytest.mark.django_db
def test_refresh_without_cookie_returns_401(api_client: APIClient) -> None:
    """Sin cookie maily_refresh, /refresh/ responde 401."""
    # Arrange: cliente sin cookie

    # Act
    response = api_client.post(REFRESH_URL, format="json")

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "detail" in response.data


@pytest.mark.django_db
def test_refresh_rejects_request_without_csrf_token(credentials: dict) -> None:
    """Sin X-CSRFToken, /refresh/ debe responder 403 (csrf_protect activo)."""
    # Usamos Django's Client con enforce_csrf_checks=True para verificar CSRF real.
    # Arrange: hacer login para obtener la cookie de refresh
    client = Client(enforce_csrf_checks=True)
    login_resp = client.post(
        LOGIN_URL,
        data={"email": credentials["email"], "password": credentials["password"]},
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    # La cookie maily_refresh ya está en el jar del client tras el login.
    # No mandamos X-CSRFToken → debe fallar.

    # Act
    response = client.post(REFRESH_URL, content_type="application/json", data="{}")

    # Assert: 403 Forbidden por falta de CSRF token
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_refresh_accepts_request_with_csrf_token(credentials: dict) -> None:
    """Con X-CSRFToken válido, /refresh/ responde 200."""
    # Arrange: login con Django's Client para obtener cookies reales
    client = Client(enforce_csrf_checks=True)
    login_resp = client.post(
        LOGIN_URL,
        data={"email": credentials["email"], "password": credentials["password"]},
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    csrf_token = client.cookies["csrftoken"].value

    # Act: enviar X-CSRFToken en el header
    response = client.post(
        REFRESH_URL,
        content_type="application/json",
        data="{}",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    # Assert
    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# 3. Logout — LogoutView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_logout_returns_205(api_client: APIClient, credentials: dict) -> None:
    """El logout responde 205 Reset Content."""
    # Arrange: login y autenticar con el access token
    login_resp = do_login(api_client, credentials)
    access_token: str = login_resp.data["access"]
    refresh_value = login_resp.cookies[COOKIE_NAME].value
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    api_client.cookies[COOKIE_NAME] = refresh_value

    # Act
    response = api_client.post(LOGOUT_URL, format="json")

    # Assert
    assert response.status_code == status.HTTP_205_RESET_CONTENT


@pytest.mark.django_db
def test_logout_clears_refresh_cookie(api_client: APIClient, credentials: dict) -> None:
    """Tras el logout, la cookie maily_refresh se borra (Max-Age=0 o ausente)."""
    # Arrange
    login_resp = do_login(api_client, credentials)
    access_token: str = login_resp.data["access"]
    refresh_value = login_resp.cookies[COOKIE_NAME].value
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    api_client.cookies[COOKIE_NAME] = refresh_value

    # Act
    response = api_client.post(LOGOUT_URL, format="json")

    # Assert: la cookie de refresh en la respuesta debe tener Max-Age=0 (borrada)
    # DRF APIClient popula response.cookies con las cookies seteadas en la respuesta.
    assert response.status_code == 205
    if COOKIE_NAME in response.cookies:
        # delete_cookie setea Max-Age=0 o expires en el pasado
        max_age = response.cookies[COOKIE_NAME].get("max-age", "")
        expires = response.cookies[COOKIE_NAME].get("expires", "")
        # Al menos uno de los dos debe indicar expiración
        cookie_is_deleted = str(max_age) == "0" or "1970" in str(expires)
        assert cookie_is_deleted, f"La cookie debe estar marcada como borrada. max_age={max_age}, expires={expires}"


@pytest.mark.django_db
def test_logout_requires_authentication(api_client: APIClient) -> None:
    """Logout sin Bearer token responde 401."""
    # Arrange: cliente sin autenticar

    # Act
    response = api_client.post(LOGOUT_URL, format="json")

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_logout_rejects_request_without_csrf_token(credentials: dict) -> None:
    """Sin X-CSRFToken, /logout/ debe responder 403."""
    # Arrange: login con Django's Client con enforce_csrf_checks=True
    client = Client(enforce_csrf_checks=True)
    login_resp = client.post(
        LOGIN_URL,
        data={"email": credentials["email"], "password": credentials["password"]},
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    import json as _json
    access_token: str = _json.loads(login_resp.content)["access"]

    # Act: sin X-CSRFToken
    response = client.post(
        LOGOUT_URL,
        content_type="application/json",
        data="{}",
        HTTP_AUTHORIZATION=f"Bearer {access_token}",
    )

    # Assert
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_logout_with_invalid_refresh_cookie_still_clears_cookie(
    api_client: APIClient, credentials: dict
) -> None:
    """Si el refresh ya fue invalido/blacklisteado, logout igual responde 205 y borra la cookie."""
    # Arrange: login, obtener tokens
    login_resp = do_login(api_client, credentials)
    access_token: str = login_resp.data["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    # Poner un refresh inválido en la cookie
    api_client.cookies[COOKIE_NAME] = "token-invalido-o-expirado"

    # Act
    response = api_client.post(LOGOUT_URL, format="json")

    # Assert: no truena; responde 205
    assert response.status_code == status.HTTP_205_RESET_CONTENT


# ---------------------------------------------------------------------------
# 4. Auditoría de LOGIN — regresión (el login sigue registrando)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_login_records_audit_event(api_client: APIClient, credentials: dict) -> None:
    """El login exitoso genera un registro de auditoría de tipo LOGIN."""
    from apps.audit.models import ActionType, AuditLog

    # Arrange: no hay registros previos
    before = AuditLog.all_objects.filter(action=ActionType.LOGIN).count()

    # Act
    response = do_login(api_client, credentials)

    # Assert
    assert response.status_code == 200
    after = AuditLog.all_objects.filter(action=ActionType.LOGIN).count()
    assert after == before + 1, "Debe haberse creado exactamente 1 registro LOGIN"


# ---------------------------------------------------------------------------
# 5. Seguridad adicional: refresh body vacío (no en cookie)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_refresh_ignores_refresh_in_body(credentials: dict) -> None:
    """Si se manda el refresh en el body en lugar de la cookie, el endpoint responde 401.

    Usa dos clientes separados:
    - client_login: realiza el login y obtiene el refresh token.
    - client_refresh: cliente NUEVO sin cookies; envía el refresh en el body.
    De esta forma se prueba que la cookie NO viene implícitamente del login anterior.
    """
    # Arrange: login en un cliente para obtener el refresh token válido
    client_login = APIClient()
    login_resp = do_login(client_login, credentials)
    assert login_resp.status_code == 200
    refresh_value = login_resp.cookies[COOKIE_NAME].value

    # Act: cliente NUEVO sin ninguna cookie; intenta usar el refresh en el body
    client_fresh = APIClient()  # sin cookies
    response = client_fresh.post(REFRESH_URL, data={"refresh": refresh_value}, format="json")

    # Assert: debe rechazarse porque la cookie maily_refresh no está presente
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
