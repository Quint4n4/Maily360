"""
Configuración base de Django para Maily Soft.

Todas las variables sensibles se leen desde entorno via django-environ.
NUNCA agregar secretos hardcodeados aquí.
"""

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# environ
# ---------------------------------------------------------------------------

env = environ.Env()

# Lee .env solo si existe (en dev se carga desde docker-compose o .env.dev)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

SECRET_KEY: str = env("DJANGO_SECRET_KEY")

DEBUG: bool = env.bool("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# ---------------------------------------------------------------------------
# Aplicaciones instaladas
# ---------------------------------------------------------------------------

DJANGO_APPS: list[str] = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS: list[str] = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "channels",
    "drf_spectacular",
    "corsheaders",
    # Almacenamiento de media en Cloudinary (opcional; activo si se configura
    # CLOUDINARY_URL + DJANGO_DEFAULT_FILE_STORAGE). Inofensivo si no se usa.
    "cloudinary_storage",
    "cloudinary",
]

LOCAL_APPS: list[str] = [
    "apps.core",
    # Infra genérica de PDFs asíncronos (Celery) — los módulos registran su builder
    "apps.pdfs",
    # authn ANTES que tenancy: tenancy.TenantMembership tiene FK a authn.User
    "apps.authn",
    "apps.tenancy",
    # Apps de negocio (Paso 3+)
    "apps.pacientes",
    "apps.personal",
    "apps.agenda",
    # Dominio finanzas (cotizaciones, cargos, pagos, CFDI 4.0)
    "apps.finanzas",
    # Bitácora de auditoría NOM-024 (Paso 4)
    "apps.audit",
    # Notas y Tareas (Fase 1)
    "apps.notas",
    # Notificaciones (campana de avisos)
    "apps.notificaciones",
    # Expediente Clínico (Fase A)
    "apps.expediente",
    # Mi Consultorio — configuración de la clínica (Fase B base)
    "apps.clinica",
    # Panel interno de plataforma (cross-tenant, equipo Maily)
    "apps.plataforma",
    # Recetas médicas (Fase B1)
    "apps.recetas",
]

INSTALLED_APPS: list[str] = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # TenantMiddleware DESPUÉS de AuthenticationMiddleware (necesita request.user resuelto)
    "apps.core.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF: str = "config.urls"

WSGI_APPLICATION: str = "config.wsgi.application"
ASGI_APPLICATION: str = "config.asgi.application"

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

DATABASES = {
    "default": env.db("DATABASE_URL"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["OPTIONS"] = {
    "connect_timeout": 10,
}

DEFAULT_AUTO_FIELD: str = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# GUC de tenant para RLS — modo sesión (default) vs. modo local (pgbouncer)
# ---------------------------------------------------------------------------
#
# DB_TENANT_GUC_MODE controla CÓMO se fija el GUC `app.current_tenant_id` que
# usan las políticas RLS de PostgreSQL (ver apps/core/tenant_context.py →
# apply_tenant_guc(), apps/core/middleware.py, apps/core/views.py).
#
#   "session" (DEFAULT — comportamiento actual, sin cambios):
#       set_config(..., false) → el GUC vive a nivel de SESIÓN/conexión.
#       Persiste durante todo CONN_MAX_AGE. Es seguro HOY porque cada
#       conexión real de Postgres pertenece a un solo worker/hilo de Django
#       (no hay pgbouncer en modo transacción reciclando conexiones entre
#       requests de distintos tenants).
#
#   "local" (para cuando se despliegue pgbouncer en modo transacción):
#       set_config(..., true) → SET LOCAL, el GUC vive SOLO dentro de la
#       transacción de base de datos actual y se borra solo al hacer
#       COMMIT/ROLLBACK. Requiere que el request completo corra DENTRO de una
#       transacción (ver TenantMiddleware, que envuelve get_response() en
#       transaction.atomic() cuando este modo está activo). Sin esa
#       transacción, SET LOCAL no tiene ningún efecto persistente y el GUC
#       quedaría vacío, activando el fallback `current_tenant_id() IS NULL`
#       de las políticas RLS — el escenario CONTRARIO al deseado (abriría
#       acceso cross-tenant en vez de cerrarlo). Ver
#       docs/design/pgbouncer-rls-escalabilidad.md antes de activar en prod.
#
# Ver el checklist de activación en docs/design/pgbouncer-rls-escalabilidad.md.
DB_TENANT_GUC_MODE: str = env("DB_TENANT_GUC_MODE", default="session")
if DB_TENANT_GUC_MODE not in ("session", "local"):
    raise ImproperlyConfigured(
        f"DB_TENANT_GUC_MODE debe ser 'session' o 'local', recibido: {DB_TENANT_GUC_MODE!r}"
    )

# ---------------------------------------------------------------------------
# Cache (Redis)
# ---------------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,
        },
    }
}

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK: dict = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": env.int("DRF_PAGE_SIZE", default=25),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("DRF_THROTTLE_ANON", default="60/minute"),
        "user": env("DRF_THROTTLE_USER", default="300/minute"),
        # Límite estricto para login: protege contra fuerza bruta de credenciales.
        "auth_login": env("DRF_THROTTLE_LOGIN", default="5/minute"),
        # Límite estricto para cambio/reset de contraseña (propio y de staff de
        # plataforma): protege contra fuerza bruta sobre current_password y
        # contra abuso del reset administrativo. Mismo criterio que auth_login.
        "auth_password_change": env("DRF_THROTTLE_PASSWORD_CHANGE", default="10/minute"),
        # Límite anti-enumeración para el endpoint público de verificación de receta (F5).
        # 30 consultas/min por IP es suficiente para una farmacia real; bloquea scrapers.
        "prescription_verify": env("DRF_THROTTLE_VERIFY", default="30/minute"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}

# ---------------------------------------------------------------------------
# drf-spectacular (OpenAPI)
# ---------------------------------------------------------------------------

SPECTACULAR_SETTINGS: dict = {
    "TITLE": "Maily Soft API",
    "DESCRIPTION": "API REST para la plataforma de gestión clínica Maily Soft",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ---------------------------------------------------------------------------
# SimpleJWT
# ---------------------------------------------------------------------------

SIMPLE_JWT: dict = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    # ROTATE=False: el refresh token NO cambia en cada renovación → la cookie es
    # estable y no puede quedar "desincronizada". Antes (ROTATE+BLACKLIST) cada
    # refresco anulaba el token anterior; si el usuario recargaba la página justo
    # cuando la cookie nueva aún no se guardaba, la siguiente petición usaba el
    # token ya anulado → 401 → sesión cerrada intermitentemente. La cookie sigue
    # segura (httpOnly + Secure + SameSite=Strict, vence a los 7 días) y el LOGOUT
    # sí invalida el token vía blacklist.
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    # FIX-10: clave de firma JWT propia para que rotar SECRET_KEY no invalide tokens.
    # En dev funciona con el default (SECRET_KEY). En prod configurar JWT_SIGNING_KEY
    # con un secreto independiente y de alta entropía (mínimo 50 caracteres aleatorios).
    # Si JWT_SIGNING_KEY está definida pero vacía en .env, usar SECRET_KEY (dev).
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default="") or SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL: str = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND: str = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT: list[str] = ["json"]
CELERY_TASK_SERIALIZER: str = "json"
CELERY_RESULT_SERIALIZER: str = "json"
CELERY_TIMEZONE: str = "America/Mexico_City"
CELERY_TASK_TRACK_STARTED: bool = True
CELERY_TASK_TIME_LIMIT: int = 30 * 60  # 30 minutos hard limit
CELERY_TASK_SOFT_TIME_LIMIT: int = 25 * 60  # 25 minutos soft limit
CELERY_RESULT_EXPIRES: int = env.int("CELERY_RESULT_EXPIRES", default=3600)  # 1h

# Tareas periódicas (Celery beat). El worker se arranca con
# `celery -A config.celery beat -l INFO` (ver docstring de config/celery.py).
# NOTA: django_celery_beat (DatabaseScheduler) todavía no está instalado en
# el proyecto; con el scheduler por defecto de Celery (PersistentScheduler)
# este dict ya es suficiente para correr la tarea. Si en el futuro se agrega
# django_celery_beat, su DatabaseScheduler sincroniza este mismo
# CELERY_BEAT_SCHEDULE a la base de datos al arrancar, así que no hace falta
# tocar este bloque.
CELERY_BEAT_SCHEDULE: dict = {
    "plataforma-avisar-vencimientos": {
        "task": "apps.plataforma.tasks.avisar_vencimientos",
        # Diaria a las 8:00 America/Mexico_City (CELERY_TIMEZONE ya está
        # configurado arriba con esa zona horaria).
        "schedule": crontab(hour=8, minute=0),
    },
}

# ---------------------------------------------------------------------------
# Channels (WebSockets)
# ---------------------------------------------------------------------------

CHANNEL_LAYERS: dict = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("REDIS_URL", default="redis://localhost:6379/2")],
        },
    },
}

# ---------------------------------------------------------------------------
# Archivos estáticos y media
# ---------------------------------------------------------------------------

STATIC_URL: str = "/static/"
STATIC_ROOT: Path = BASE_DIR / "staticfiles"

MEDIA_URL: str = "/media/"
MEDIA_ROOT: Path = BASE_DIR / "media"

# Limita el tamaño máximo de payload en memoria a 5 MB (protección contra
# cuerpos de plantilla o multipart gigantes que saturen RAM del worker).
DATA_UPLOAD_MAX_MEMORY_SIZE: int = 5 * 1024 * 1024  # 5 MB

# ---------------------------------------------------------------------------
# Almacenamiento (S3/MinIO en prod, local en dev)
# ---------------------------------------------------------------------------

# Django 5.1+ ELIMINÓ los settings DEFAULT_FILE_STORAGE / STATICFILES_STORAGE:
# ahora la configuración de almacenamiento vive en STORAGES. Si se usan los viejos,
# Django los IGNORA silenciosamente (media caía a FileSystemStorage → imágenes 404
# en prod). El backend de media se elige por entorno (Cloudinary en prod;
# FileSystemStorage en dev); los estáticos SIEMPRE con WhiteNoise.
STORAGES = {
    "default": {
        "BACKEND": env(
            "DJANGO_DEFAULT_FILE_STORAGE",
            default="django.core.files.storage.FileSystemStorage",
        ),
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

AWS_ACCESS_KEY_ID: str = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY: str = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME: str = env("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME: str = env("AWS_S3_REGION_NAME", default="us-east-1")
AWS_S3_CUSTOM_DOMAIN: str = env("AWS_S3_CUSTOM_DOMAIN", default="")
AWS_DEFAULT_ACL: str = "private"
AWS_S3_FILE_OVERWRITE: bool = False

# ---------------------------------------------------------------------------
# Media en Cloudinary (piloto)
# ---------------------------------------------------------------------------
# La librería `cloudinary` lee CLOUDINARY_URL del entorno automáticamente
# (formato cloudinary://<api_key>:<api_secret>@<cloud_name>). Para activarlo en
# producción basta con setear esa variable y
# DJANGO_DEFAULT_FILE_STORAGE=cloudinary_storage.storage.MediaCloudinaryStorage.
# NUNCA hardcodear el CLOUDINARY_URL aquí (es un secreto).

# ---------------------------------------------------------------------------
# Frontend (SPA React) servido por el MISMO backend en producción
# ---------------------------------------------------------------------------
# En el despliegue de Railway el Dockerfile compila web-soft (Vite) y copia el
# build a esta carpeta. Cuando existe:
#   - WhiteNoise sirve los assets (/assets/*, favicon, etc.) tal cual.
#   - urls.py agrega una ruta catch-all que devuelve index.html (React Router).
#   - las plantillas encuentran index.html.
# En desarrollo la carpeta NO existe → cero efecto (el frontend corre en Vite).
FRONTEND_DIST_DIR: Path = BASE_DIR / "frontend_dist"
if FRONTEND_DIST_DIR.is_dir():
    WHITENOISE_ROOT: str = str(FRONTEND_DIST_DIR)
    TEMPLATES[0]["DIRS"].append(str(FRONTEND_DIST_DIR))  # type: ignore[index]

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_BACKEND: str = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST: str = env("EMAIL_HOST", default="localhost")
EMAIL_PORT: int = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS: bool = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_HOST_USER: str = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD: str = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL: str = env("DEFAULT_FROM_EMAIL", default="noreply@mailysoft.mx")

# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------

# Modelo de usuario custom: email-based, con is_platform_staff y multi-tenant
AUTH_USER_MODEL: str = "authn.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# ---------------------------------------------------------------------------
# Internacionalización
# ---------------------------------------------------------------------------

LANGUAGE_CODE: str = "es-mx"
TIME_ZONE: str = "America/Mexico_City"
USE_I18N: bool = True
USE_TZ: bool = True

# ---------------------------------------------------------------------------
# Logging (formato JSON-friendly para agregadores como Datadog/Loki)
# ---------------------------------------------------------------------------

LOGGING: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "logging.Formatter",
            "fmt": '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
        "verbose": {
            "format": "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("DJANGO_LOG_LEVEL", default="INFO"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": env("DB_LOG_LEVEL", default="WARNING"),
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": env("APP_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# CORS (ajustar orígenes según frontend)
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS: bool = True

# ---------------------------------------------------------------------------
# Auth — cookie de refresh (patrón híbrido: access en memoria, refresh en cookie)
#
# AUTH_REFRESH_COOKIE: nombre de la cookie httpOnly que transporta el refresh token.
# AUTH_COOKIE_SECURE: True en producción (HTTPS), False en desarrollo. Se sobreescribe
#   en settings/production.py.  Lee de env para permitir ajuste sin tocar el código.
# AUTH_COOKIE_SAMESITE: "Strict" — la cookie NO se envía en requests cross-site,
#   lo que bloquea CSRF incluso sin el header X-CSRFToken en escenarios same-origin.
# AUTH_COOKIE_PATH: limita la cookie al prefijo de los endpoints de auth únicamente,
#   reduciendo la superficie de ataque (la cookie no viaja en requests a /api/v1/pacientes/,
#   /api/v1/personal/, etc.).
# ---------------------------------------------------------------------------

AUTH_REFRESH_COOKIE: str = "maily_refresh"
AUTH_COOKIE_SECURE: bool = env.bool("AUTH_COOKIE_SECURE", default=False)
AUTH_COOKIE_SAMESITE: str = "Strict"
AUTH_COOKIE_PATH: str = "/api/v1/auth/"

# ---------------------------------------------------------------------------
# CSRF
#
# CSRF_COOKIE_HTTPONLY=False: el front necesita leer la cookie csrftoken con JS
#   (document.cookie) y mandarlo como header X-CSRFToken en refresh y logout.
# CSRF_COOKIE_SAMESITE="Strict": mismo razonamiento que AUTH_COOKIE_SAMESITE.
# CSRF_TRUSTED_ORIGINS: debe incluir el origen del frontend. En dev se incluye
#   localhost:5173 (Vite) y localhost:3000. En prod, el dominio real del frontend.
# CsrfViewMiddleware ya está en MIDDLEWARE (ver arriba).
# ---------------------------------------------------------------------------

CSRF_COOKIE_HTTPONLY: bool = False  # El frontend DEBE poder leerla con JS
CSRF_COOKIE_SAMESITE: str = "Strict"
CSRF_TRUSTED_ORIGINS: list[str] = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:5173", "http://localhost:3000"],
)

# ---------------------------------------------------------------------------
# Recetas — QR de verificación pública (F5)
#
# PRESCRIPTION_VERIFY_SECRET: secreto HMAC-SHA256 para generar/validar el token
#   del QR de cada receta.  Debe ser distinto de DJANGO_SECRET_KEY (rotación
#   independiente). Si no está en el entorno, usa SECRET_KEY como fallback
#   seguro (ambas son sensibles y se rotan del mismo modo en dev).
#   En producción OBLIGATORIO configurar como secreto independiente.
# PRESCRIPTION_VERIFY_BASE_URL: URL del frontend donde vive la pantalla pública
#   de verificación. El QR apunta a {BASE_URL}/verificar-receta/{id}?sig={token}.
#   Default: http://localhost:5173 para desarrollo local.
# ---------------------------------------------------------------------------

PRESCRIPTION_VERIFY_SECRET: str = env("PRESCRIPTION_VERIFY_SECRET", default=SECRET_KEY)
PRESCRIPTION_VERIFY_BASE_URL: str = env(
    "PRESCRIPTION_VERIFY_BASE_URL", default="http://localhost:5173"
)

# ---------------------------------------------------------------------------
# Sentry (observabilidad de errores) — opcional, se activa con SENTRY_DSN
# ---------------------------------------------------------------------------
#
# Sin SENTRY_DSN (caso local), Sentry queda DORMIDO: no se inicializa ni envía
# nada. Se activa en producción/Railway poniendo la variable SENTRY_DSN. Como este
# settings lo importan tanto gunicorn (web) como el worker de Celery, captura errores
# de ambos (incluidas las fallas de tareas en segundo plano, p. ej. los PDF).

SENTRY_DSN: str = env("SENTRY_DSN", default="")

if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        # PRIVACIDAD (app de salud — NOM-024 / LFPDPPP): NUNCA enviar datos de
        # pacientes a Sentry. Se desactivan PII, cuerpos de request y variables
        # locales de los tracebacks (que podrían contener nombre, CURP, etc.).
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        # Performance tracing desactivado por defecto (0.0); subir en prod si se quiere.
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
    )
