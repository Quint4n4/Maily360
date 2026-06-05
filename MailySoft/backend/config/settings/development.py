"""
Configuración de Django para entorno de DESARROLLO.

Hereda de base.py. DEBUG=True. No usar en producción.
"""

from .base import *  # noqa: F401, F403
from .base import env

# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------

DEBUG: bool = env.bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

# ---------------------------------------------------------------------------
# Django Debug Toolbar (instalar como dev dep si se requiere)
# ---------------------------------------------------------------------------

# INSTALLED_APPS += ["debug_toolbar"]
# MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE
# INTERNAL_IPS = ["127.0.0.1"]

# ---------------------------------------------------------------------------
# Email en consola
# ---------------------------------------------------------------------------

EMAIL_BACKEND: str = "django.core.mail.backends.console.EmailBackend"

# ---------------------------------------------------------------------------
# CORS para desarrollo local
# ---------------------------------------------------------------------------
# NO usar CORS_ALLOW_ALL_ORIGINS=True: es INCOMPATIBLE con CORS_ALLOW_CREDENTIALS=True
# (el navegador rechaza credenciales/cookies cuando el server responde Allow-Origin: *).
# Con el patrón de cookies httpOnly el front DEBE usar credentials:'include', así que
# listamos los orígenes explícitamente (Vite 5173, CRA 3000/3001).
CORS_ALLOW_ALL_ORIGINS: bool = False
CORS_ALLOWED_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:5173",
]

# ---------------------------------------------------------------------------
# Auth cookie — desarrollo: Secure=False (HTTP local, no HTTPS)
# ---------------------------------------------------------------------------

AUTH_COOKIE_SECURE: bool = False

# ---------------------------------------------------------------------------
# CSRF — desarrollo: también Secure=False, HttpOnly=False (igual que base.py,
# se explicita aquí para mayor claridad)
# ---------------------------------------------------------------------------

CSRF_COOKIE_SECURE: bool = False
CSRF_TRUSTED_ORIGINS: list[str] = [  # type: ignore[assignment]
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8000",
]

# ---------------------------------------------------------------------------
# Logging más verboso en dev
# ---------------------------------------------------------------------------

LOGGING["root"]["level"] = "DEBUG"  # type: ignore[index]
LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # type: ignore[index]
