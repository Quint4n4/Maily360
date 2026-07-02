"""
Configuración de Django para entorno de PRODUCCIÓN.

Hereda de base.py. DEBUG=False obligatorio.
Activa HTTPS, HSTS, cookies seguras y headers de seguridad.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403
from .base import AWS_S3_CUSTOM_DOMAIN, env

# ---------------------------------------------------------------------------
# Seguridad obligatoria en producción
# ---------------------------------------------------------------------------

DEBUG: bool = False

ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS")

SECRET_KEY: str = env("DJANGO_SECRET_KEY")

# ---------------------------------------------------------------------------
# JWT — clave de firma obligatoria en producción (FIX-B10)
# ---------------------------------------------------------------------------

# En producción la clave JWT DEBE ser distinta de SECRET_KEY y de alta entropía.
# Sin JWT_SIGNING_KEY configurada, el proceso falla al arrancar con un ImproperlyConfigured
# claro. En base.py queda el fallback a SECRET_KEY para entornos de desarrollo.
# El dict base se importó vía `from .base import *`; solo sobreescribimos la clave de firma.
SIMPLE_JWT["SIGNING_KEY"] = env("JWT_SIGNING_KEY")  # type: ignore[index]  # Sin default — falla ruidoso si falta.

# ---------------------------------------------------------------------------
# HTTPS y HSTS
# ---------------------------------------------------------------------------

SECURE_SSL_REDIRECT: bool = True
# El healthcheck interno de Railway llega por HTTP sin X-Forwarded-Proto; se exenta
# /healthz/ del redirect a HTTPS para que responda 200 (no 301).
SECURE_REDIRECT_EXEMPT: list[str] = [r"^healthz/?$"]
SECURE_HSTS_SECONDS: int = 31536000  # 1 año
SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = True
SECURE_HSTS_PRELOAD: bool = True
SECURE_PROXY_SSL_HEADER: tuple[str, str] = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY: str = "strict-origin-when-cross-origin"

# ---------------------------------------------------------------------------
# Cookies seguras
# ---------------------------------------------------------------------------

SESSION_COOKIE_SECURE: bool = True
SESSION_COOKIE_HTTPONLY: bool = True
SESSION_COOKIE_SAMESITE: str = "Lax"
SESSION_COOKIE_AGE: int = 60 * 60 * 24 * 7  # 7 días

CSRF_COOKIE_SECURE: bool = True
# CSRF_COOKIE_HTTPONLY DEBE ser False: el frontend necesita leer csrftoken con JS
# para enviarlo como X-CSRFToken en refresh y logout. Sobreescribimos el True de base.
CSRF_COOKIE_HTTPONLY: bool = False
CSRF_COOKIE_SAMESITE: str = "Strict"

# AUTH cookie de refresh: Secure=True obligatorio en producción (HTTPS).
AUTH_COOKIE_SECURE: bool = True

# ---------------------------------------------------------------------------
# Headers de seguridad adicionales
# ---------------------------------------------------------------------------

SECURE_CONTENT_TYPE_NOSNIFF: bool = True
SECURE_BROWSER_XSS_FILTER: bool = True
X_FRAME_OPTIONS: str = "DENY"

# ---------------------------------------------------------------------------
# CSP (Content Security Policy)
# Descomenta y ajusta cuando el frontend esté configurado
# ---------------------------------------------------------------------------

# MIDDLEWARE = ["csp.middleware.CSPMiddleware"] + MIDDLEWARE
# CSP_DEFAULT_SRC = ("'self'",)
# CSP_SCRIPT_SRC = ("'self'",)
# CSP_STYLE_SRC = ("'self'", "https://fonts.googleapis.com")
# CSP_FONT_SRC = ("'self'", "https://fonts.gstatic.com")
# CSP_IMG_SRC = ("'self'", "data:", "https:")
# CSP_CONNECT_SRC = ("'self'",)

# ---------------------------------------------------------------------------
# CORS en producción: solo orígenes explícitos
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_ALL_ORIGINS: bool = False

# CSRF: orígenes confiables explícitos en prod (sin default → falla ruidoso si falta).
# El front (cookie httpOnly + double-submit) requiere que su origen esté aquí.
CSRF_TRUSTED_ORIGINS: list[str] = env.list("CSRF_TRUSTED_ORIGINS")

# ---------------------------------------------------------------------------
# Almacenamiento de media
# ---------------------------------------------------------------------------
# El backend se define en base.py vía STORAGES["default"], que lee
# DJANGO_DEFAULT_FILE_STORAGE del entorno (Cloudinary en este piloto; S3 o
# FileSystemStorage según se configure). Django 5.1+ ya NO usa DEFAULT_FILE_STORAGE.

# ---------------------------------------------------------------------------
# BAJO-3 — Guardia S3: imágenes clínicas nunca deben quedar en URLs públicas.
#
# Si AWS_S3_CUSTOM_DOMAIN está configurado (indica un CDN/CloudFront custom
# domain) pero AWS_CLOUDFRONT_SIGNED no está activo, los objetos del bucket
# serán accesibles vía URL directa sin firma — exponiendo imágenes de salud
# protegidas por la LFPDPPP y NOM-024 a cualquiera que tenga el enlace.
#
# Esta guardia falla ruidosamente al arrancar en lugar de silenciosamente
# en producción con datos de salud expuestos.
# ---------------------------------------------------------------------------

_cloudfront_signed: bool = env.bool("AWS_CLOUDFRONT_SIGNED", default=False)
if AWS_S3_CUSTOM_DOMAIN and not _cloudfront_signed:
    raise ImproperlyConfigured(
        "BAJO-3 (seguridad clínica): AWS_S3_CUSTOM_DOMAIN está configurado pero "
        "AWS_CLOUDFRONT_SIGNED no está activo (o es False). Las imágenes clínicas "
        "quedarían accesibles públicamente vía URL directa sin firma de CloudFront, "
        "violando LFPDPPP y NOM-024. "
        "Activa las URLs firmadas (AWS_CLOUDFRONT_SIGNED=True) o elimina "
        "AWS_S3_CUSTOM_DOMAIN si no usas CloudFront."
    )

# ---------------------------------------------------------------------------
# Logging solo WARNING en prod (INFO para apps propias)
# ---------------------------------------------------------------------------

LOGGING["root"]["level"] = "WARNING"  # type: ignore[index]
LOGGING["loggers"]["apps"]["level"] = "INFO"  # type: ignore[index]
LOGGING["loggers"]["django"]["level"] = "WARNING"  # type: ignore[index]
