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
# CORS abierto para desarrollo local
# ---------------------------------------------------------------------------

CORS_ALLOW_ALL_ORIGINS: bool = True

# ---------------------------------------------------------------------------
# Logging más verboso en dev
# ---------------------------------------------------------------------------

LOGGING["root"]["level"] = "DEBUG"  # type: ignore[index]
LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # type: ignore[index]
