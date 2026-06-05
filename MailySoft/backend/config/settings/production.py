"""
Configuración de Django para entorno de PRODUCCIÓN.

Hereda de base.py. DEBUG=False obligatorio.
Activa HTTPS, HSTS, cookies seguras y headers de seguridad.
"""

from .base import *  # noqa: F401, F403
from .base import env

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
# Almacenamiento en S3
# ---------------------------------------------------------------------------

DEFAULT_FILE_STORAGE: str = env(
    "DJANGO_DEFAULT_FILE_STORAGE",
    default="storages.backends.s3boto3.S3Boto3Storage",
)

# ---------------------------------------------------------------------------
# Logging solo WARNING en prod (INFO para apps propias)
# ---------------------------------------------------------------------------

LOGGING["root"]["level"] = "WARNING"  # type: ignore[index]
LOGGING["loggers"]["apps"]["level"] = "INFO"  # type: ignore[index]
LOGGING["loggers"]["django"]["level"] = "WARNING"  # type: ignore[index]
