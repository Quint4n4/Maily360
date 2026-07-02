"""
Vistas de la app authn.

Endpoints registrados en config/urls.py:
    POST /api/v1/auth/login/    → MailyTokenObtainPairView
    POST /api/v1/auth/refresh/  → CookieTokenRefreshView
    POST /api/v1/auth/logout/   → LogoutView
    POST /api/v1/auth/verify/   → TokenVerifyView (SimpleJWT, sin cambios)

Registrados en apps/authn/urls.py:
    GET  /api/v1/me/            → MeApi

# ── Patrón de tokens HÍBRIDO ──────────────────────────────────────────────
# Access token : devuelto SOLO en el cuerpo JSON ({access: "..."}). El frontend
#                lo guarda en memoria (variable JS, NO localStorage) y lo adjunta
#                como header Authorization: Bearer <token> en cada petición.
# Refresh token: almacenado SOLO en la cookie httpOnly "maily_refresh".
#                El navegador la envía automáticamente a /api/v1/auth/*.
#                Nunca aparece en el cuerpo JSON.
#
# # ── CSRF ──────────────────────────────────────────────────────────────────
# DRF APIView es csrf_exempt por defecto (SessionAuthentication lo activa,
# pero usamos JWTAuthentication). Para proteger los endpoints que leen la
# cookie de refresh (refresh y logout), aplicamos @csrf_protect explícito,
# forzando la validación del header X-CSRFToken contra la cookie csrftoken.
#
# Flujo:
#   1. Login (no exige CSRF, aún no hay cookie): devuelve access en JSON,
#      setea cookie maily_refresh httpOnly + cookie csrftoken (ensure_csrf_cookie).
#   2. Refresh: lee maily_refresh de cookie; exige X-CSRFToken válido; rota
#      el refresh si ROTATE_REFRESH_TOKENS=True; devuelve {access} nuevo.
#   3. Logout: invalida el refresh con blacklist; borra la cookie; exige
#      X-CSRFToken.  No truena si el refresh ya expiró o fue borrado.
#
# ── Decisión: logout con IsAuthenticated ─────────────────────────────────
# LogoutView requiere un Bearer token válido (IsAuthenticated).  Razón: si
# el access token ya expiró pero la cookie de refresh sigue viva, el front
# debe llamar a /refresh/ primero para obtener un access nuevo y luego a
# /logout/.  Esto simplifica la lógica y evita endpoints completamente
# anónimos que manipulen la blacklist (superficie de DoS).  Si el token de
# refresh en la cookie es inválido o ya fue invalidado, LogoutView igualmente
# borra la cookie y responde 205 sin truene.

# ── Decisión: MeApi sin TenantAPIView ────────────────────────────────────
# /me/ es sobre identidad del usuario, debe funcionar incluso cuando
# el usuario no tiene tenant activo. El tenant se resuelve manualmente con
# resolve_tenant_for_user(), sin depender del contexto thread-local de tenant.
"""

import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.authn.models import User
from apps.authn.selectors import user_active_memberships
from apps.authn.serializers import MeSerializer, PasswordChangeInputSerializer
from apps.authn.services import password_change
from apps.core.tenant_context import resolve_membership_for_user, resolve_tenant_for_user
from apps.tenancy.models import Tenant, TenantMembership

# Import deferred to avoid circular imports at module load time.
# doctor_get_for_user is called in MeApi.get() at request time.
# This is the accepted pattern for cross-app selectors used in authn.

logger = logging.getLogger("apps.authn.views")


# ---------------------------------------------------------------------------
# Helper: set/delete cookie de refresh
# ---------------------------------------------------------------------------


def _set_refresh_cookie(response: Response, refresh_value: str) -> None:
    """Agrega la cookie httpOnly de refresh a la respuesta.

    Usa las constantes de settings para garantizar consistencia entre
    login y refresh (mismo nombre, mismos atributos, mismo path).
    Max-Age se toma de SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'] para que la
    cookie expire al mismo tiempo que el token (defensa en profundidad).
    """
    from datetime import timedelta

    refresh_lifetime: timedelta = settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
    max_age: int = int(refresh_lifetime.total_seconds())

    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE,
        value=refresh_value,
        max_age=max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
    )


def _delete_refresh_cookie(response: Response) -> None:
    """Elimina la cookie de refresh.

    Usa set_cookie con Max-Age=0 (en vez de delete_cookie) para PROPAGAR el flag
    Secure: en producción (HTTPS) los navegadores pueden ignorar el borrado de una
    cookie Secure si el Set-Cookie de borrado no lleva Secure → la sesión persistiría
    tras el logout. set_cookie con los mismos atributos garantiza el borrado efectivo.
    """
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE,
        value="",
        max_age=0,
        expires="Thu, 01 Jan 1970 00:00:00 GMT",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
    )


# ---------------------------------------------------------------------------
# 1. Login
# ---------------------------------------------------------------------------


@method_decorator(ensure_csrf_cookie, name="dispatch")
class MailyTokenObtainPairView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — login JWT con auditoría de acceso.

    Diferencias respecto al TokenObtainPairView estándar de SimpleJWT:
    - El refresh token NO se incluye en el cuerpo JSON; se deposita en la
      cookie httpOnly "maily_refresh".
    - Se fuerza el envío de la cookie csrftoken (ensure_csrf_cookie) para que
      el frontend pueda leerla y adjuntarla en las llamadas a /refresh/ y /logout/.
    - El LOGIN exitoso se registra en la bitácora de auditoría.

    No exige CSRF en el login porque todavía no hay cookie que proteger.

    Throttle estricto (auth_login, 5/min) para frenar fuerza bruta de credenciales.

    Registra:
      - LOGIN exitoso: después de que SimpleJWT devuelve 200.
      - LOGIN_FAILED: delegado a la señal user_login_failed (handle_login_failed),
        que SimpleJWT dispara internamente al llamar authenticate().
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Delega a SimpleJWT; en éxito mueve el refresh a cookie y audita."""
        response: Response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            # Extraer refresh del cuerpo antes de mutarlo
            refresh_token: str = response.data.pop("refresh", "")  # type: ignore[union-attr]

            if refresh_token:
                _set_refresh_cookie(response, refresh_token)

            self._audit_login_success(request)

        return response

    def _audit_login_success(self, request: Request) -> None:
        """Registra el evento LOGIN exitoso en la bitácora."""
        try:
            from apps.audit.models import ActionType
            from apps.audit.services import audit_record
            from apps.core.tenant_context import set_request_context

            # Poblar contexto HTTP para que audit_record lea ip/user_agent.
            x_forwarded: str = request.META.get("HTTP_X_FORWARDED_FOR", "")
            ip: str = (
                x_forwarded.split(",")[0].strip()
                if x_forwarded
                else request.META.get("REMOTE_ADDR", "")
            )
            user_agent: str = request.META.get("HTTP_USER_AGENT", "")[:512]
            raw_request_id: str = request.META.get("HTTP_X_REQUEST_ID", "")
            import uuid as _uuid

            request_id: str = raw_request_id if raw_request_id else _uuid.uuid4().hex
            set_request_context(ip=ip, user_agent=user_agent, request_id=request_id)

            # Resolver el usuario por su email SIN re-autenticar.
            # SimpleJWT ya validó las credenciales (status=200).
            from apps.authn.models import User as _User

            username_field: str = _User.USERNAME_FIELD
            email_value: str = request.data.get(username_field, "")
            try:
                user: _User = _User.objects.get(**{username_field: email_value})
            except _User.DoesNotExist:
                logger.warning(
                    "MailyTokenObtainPairView: status=200 pero no se halló el usuario %s.",
                    email_value,
                )
                return

            # Resolver tenant para el usuario autenticado.
            membership: TenantMembership | None = resolve_membership_for_user(user)
            tenant: Tenant | None = membership.tenant if membership is not None else None
            actor_role: str = membership.role if membership is not None else ""

            audit_record(
                action=ActionType.LOGIN,
                resource_type="User",
                actor=user,
                tenant=tenant,
                resource_id=user.pk,
                resource_repr=str(getattr(user, "email", user.pk)),
                actor_role=actor_role,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "MailyTokenObtainPairView._audit_login_success: error al auditar LOGIN — %s",
                exc,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# 2. Refresh
# ---------------------------------------------------------------------------


@method_decorator(csrf_protect, name="dispatch")
class CookieTokenRefreshView(TokenRefreshView):
    """POST /api/v1/auth/refresh/ — rota el access token leyendo el refresh de cookie.

    Reemplaza a TokenRefreshView de SimpleJWT en config/urls.py.

    Comportamiento:
    - Lee el refresh token de la cookie httpOnly "maily_refresh" (no del body).
    - Si la cookie no existe → 401.
    - Valida el token vía el serializer de SimpleJWT.
    - Si ROTATE_REFRESH_TOKENS=True (activo en base.py), el nuevo refresh
      se deposita en la cookie (nunca en el cuerpo JSON).
    - Devuelve {access: "..."} únicamente.
    - Exige X-CSRFToken válido (csrf_protect) para prevenir CSRF.
    """

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Lee la cookie de refresh, rota si aplica, devuelve {access}."""
        refresh_token: str | None = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE)

        if not refresh_token:
            return Response(
                {"detail": "No hay sesión activa."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Inyectar el refresh en request.data para que el serializer base lo valide.
        # request.data es inmutable en DRF cuando la petición ya fue parseada,
        # así que creamos una copia mutable.
        request._full_data = {"refresh": refresh_token}  # type: ignore[attr-defined]

        response: Response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            # Si SimpleJWT rotó el refresh token, sacarlo del body y mandarlo
            # a la cookie. ROTATE_REFRESH_TOKENS=True en base.py.
            new_refresh: str | None = response.data.pop("refresh", None)  # type: ignore[union-attr]
            if new_refresh:
                _set_refresh_cookie(response, new_refresh)

        return response


# ---------------------------------------------------------------------------
# 3. Logout
# ---------------------------------------------------------------------------


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    """POST /api/v1/auth/logout/ — cierra sesión invalidando el refresh token.

    Requiere Bearer token válido (IsAuthenticated).  Razón: si el access token
    ya expiró, el front debe llamar a /refresh/ primero; de esa manera siempre
    hay un access token en memoria cuando se llama al logout.

    Comportamiento:
    - Lee el refresh de la cookie "maily_refresh".
    - Si existe, lo invalida con la blacklist de SimpleJWT.
    - Si el token ya expiró o fue invalidado, se ignora el error (no truena)
      y la cookie se borra igualmente — el objetivo es cerrar la sesión.
    - Borra la cookie "maily_refresh".
    - Devuelve 205 Reset Content (convención REST para "limpiaste el estado").
    - Exige X-CSRFToken válido (csrf_protect).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Invalida el refresh token y elimina la cookie de sesión."""
        refresh_token: str | None = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE)

        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except TokenError as exc:
                # Token ya expirado, inválido o previamente blacklisteado.
                # Continuamos: el objetivo es borrar la cookie de todas formas.
                logger.info(
                    "LogoutView: token de refresh inválido o ya blacklisteado para user=%s — %s",
                    request.user.pk,  # type: ignore[union-attr]
                    exc,
                )

        self._audit_logout(request)
        response = Response(status=status.HTTP_205_RESET_CONTENT)
        _delete_refresh_cookie(response)
        return response

    def _audit_logout(self, request: Request) -> None:
        """Registra el cierre de sesión en la bitácora (NOM-024)."""
        try:
            from apps.audit.models import ActionType
            from apps.audit.services import audit_record

            membership = resolve_membership_for_user(request.user)  # type: ignore[arg-type]
            audit_record(
                action=ActionType.LOGOUT,
                resource_type="User",
                actor=request.user,  # type: ignore[arg-type]
                tenant=membership.tenant if membership is not None else None,
                resource_id=request.user.pk,  # type: ignore[union-attr]
                actor_role=membership.role if membership is not None else "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "LogoutView._audit_logout: error al auditar LOGOUT — %s", exc, exc_info=True
            )


# ---------------------------------------------------------------------------
# 4. Me
# ---------------------------------------------------------------------------


class MeApi(APIView):
    """GET /api/v1/me/ — retorna el perfil completo del usuario autenticado.

    Incluye: datos personales, flags de plataforma, tenant activo, rol activo
    y lista de todas las membresías activas (para soportar multi-clínica).

    Responde 200 siempre que el token sea válido, incluso si el usuario no
    tiene tenant activo (active_tenant y active_role serán null en ese caso).
    Responde 401 si el token es inválido o está ausente.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Retorna el perfil del usuario autenticado."""
        from apps.personal.selectors import doctor_get_for_user

        user: User = request.user  # type: ignore[assignment]

        # 1. Resolver el tenant activo del usuario.
        active_tenant: Tenant | None = resolve_tenant_for_user(user)

        # 2. Obtener todas las membresías activas del usuario (con select_related).
        memberships_qs = user_active_memberships(user=user)
        memberships: list[TenantMembership] = list(memberships_qs)

        # 3. Localizar la membership que corresponde al tenant activo.
        active_membership: TenantMembership | None = None
        if active_tenant is not None:
            for m in memberships:
                if m.tenant_id == active_tenant.id:
                    active_membership = m
                    break

        # 4. Resolver el doctor_id si el rol activo es 'doctor'.
        #    Solo se incluye si el usuario tiene rol 'doctor' en el tenant activo.
        #    Para cualquier otro rol (owner, admin, reception, nurse…) será None.
        import uuid as _uuid_mod

        doctor_id: _uuid_mod.UUID | None = None
        if (
            active_tenant is not None
            and active_membership is not None
            and active_membership.role == TenantMembership.Role.DOCTOR
        ):
            doctor = doctor_get_for_user(user=user, tenant_id=active_tenant.id)
            if doctor is not None:
                doctor_id = doctor.id

        # 5. Serializar y devolver.
        serializer = MeSerializer(
            user,
            context={
                "active_tenant": active_tenant,
                "active_membership": active_membership,
                "memberships": memberships,
                "doctor_id": doctor_id,
            },
        )
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# 5. Cambio de contraseña (voluntario o forzado por must_change_password)
# ---------------------------------------------------------------------------


class PasswordChangeApi(APIView):
    """POST /api/v1/auth/change-password/ — cambia la contraseña del usuario autenticado.

    Aplica tanto al cambio voluntario como al flujo forzado por
    must_change_password=True (contraseña temporal de alta de clínica o de
    staff de plataforma — ver apps/plataforma/services.py).

    EXENTA del candado "cambio de contraseña obligatorio" (apps.core.views.
    enforce_password_change) por diseño: hereda de APIView directo, igual que
    MeApi/LogoutView/CookieTokenRefreshView, NO de TenantAPIView ni
    PlatformAPIView (los dos puntos donde vive el candado). Un usuario con
    must_change_password=True DEBE poder llegar a este endpoint para
    resolver su propio bloqueo.

    Requiere Bearer token válido (IsAuthenticated) — mismo criterio que
    LogoutView: si el access expiró, el frontend llama primero a /refresh/.

    Throttle dedicado (auth_password_change, 10/min) — mismo criterio que el
    login: frena fuerza bruta sobre current_password.

    Rotación de sesión propia: el servicio password_change() blacklistea
    TODOS los OutstandingToken del usuario (incluida la cookie de refresh
    actual), así que tras un cambio exitoso esta vista emite un refresh
    token NUEVO y lo deposita en la misma cookie httpOnly que usa el login
    — si no, la sesión propia moriría silenciosamente en cuanto el access
    token en memoria expirara (~15 min) y el frontend intentara refrescar
    con el refresh ya blacklisteado.
    IMPORTANTE: el reset por un admin (platform_staff_password_reset)
    invalida TODO sin emitir sesión nueva (correcto: el admin no es quien
    sigue operando esa cuenta); el cambio PROPIO, en cambio, rota la sesión
    para no desloguear al usuario que acaba de autenticarse con su
    contraseña actual.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_password_change"

    def post(self, request: Request) -> Response:
        """Valida la contraseña actual, aplica la nueva y rota la cookie de sesión."""
        s = PasswordChangeInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            user = password_change(
                user=request.user,  # type: ignore[arg-type]
                current_password=data["current_password"],
                new_password=data["new_password"],
            )
        except DjangoValidationError as exc:
            raise drf_serializers.ValidationError(exc.messages) from exc

        response = Response(status=status.HTTP_200_OK)
        new_refresh = RefreshToken.for_user(user)
        _set_refresh_cookie(response, str(new_refresh))
        return response
