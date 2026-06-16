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

ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

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
# Orígenes de desarrollo local
# ---------------------------------------------------------------------------
# Vite suele incrementar el puerto (5173 → 5174 → …) cuando hay varios proyectos
# corriendo a la vez. Generamos un rango para que CORS y CSRF no se rompan por el
# puerto. El proxy de Vite reenvía el header Origin (p. ej. http://localhost:5174),
# y Django valida CSRF contra CSRF_TRUSTED_ORIGINS → ambos DEBEN incluir ese origen.
_VITE_PORTS = range(5173, 5181)  # 5173..5180
_DEV_FRONT_ORIGINS: list[str] = [
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in _VITE_PORTS
] + [
    "http://localhost:3000",
    "http://localhost:3001",
]

# NO usar CORS_ALLOW_ALL_ORIGINS=True: es INCOMPATIBLE con CORS_ALLOW_CREDENTIALS=True
# (el navegador rechaza credenciales/cookies cuando el server responde Allow-Origin: *).
# Con el patrón de cookies httpOnly el front DEBE usar credentials:'include', así que
# listamos los orígenes explícitamente.
CORS_ALLOW_ALL_ORIGINS: bool = False
CORS_ALLOWED_ORIGINS: list[str] = list(_DEV_FRONT_ORIGINS)

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
    *_DEV_FRONT_ORIGINS,
    "http://localhost:8000",
]

# ---------------------------------------------------------------------------
# Logging más verboso en dev
# ---------------------------------------------------------------------------

LOGGING["root"]["level"] = "DEBUG"  # type: ignore[index]
LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # type: ignore[index]
