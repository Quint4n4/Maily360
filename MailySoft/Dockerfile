# =============================================================================
# Maily Soft — Dockerfile para RAILWAY (imagen única: frontend + backend)
#
# El backend Django sirve el build de React en el MISMO origen (sin CORS), que
# es lo que exige el login con cookies httpOnly seguras.
#
# Contexto de build: la carpeta MailySoft/ (contiene backend/ y web-soft/).
# En Railway → Root Directory = "MailySoft".
#
# IMPORTANTE: el desarrollo local NO usa este archivo. Local usa
# backend/Dockerfile vía docker-compose (target: builder + runserver). Este
# Dockerfile es EXCLUSIVO del despliegue en Railway.
# =============================================================================

# ---- Stage 1: build del frontend (Vite / React) ----
FROM node:20-alpine AS frontend

WORKDIR /web

# La API vive en el mismo origen que el backend → ruta relativa (igual que local).
ENV VITE_API_URL=/api/v1

# Cache de dependencias: primero el lockfile.
COPY web-soft/package.json web-soft/package-lock.json ./
RUN npm ci

COPY web-soft/ ./
RUN npm run build          # genera /web/dist


# ---- Stage 2: dependencias del backend (Poetry) ----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        libpq-dev \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        libffi-dev \
        shared-mime-info \
        libfontconfig1 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

COPY backend/pyproject.toml backend/poetry.lock ./
RUN poetry install --only=main --no-root

COPY backend/ ./
RUN poetry install --only=main

ENV PATH="/app/.venv/bin:$PATH"


# ---- Stage 3: runtime ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        libffi8 \
        shared-mime-info \
        libfontconfig1 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root por seguridad
RUN groupadd --gid 1001 mailysoft \
    && useradd --uid 1001 --gid mailysoft --shell /bin/bash --create-home mailysoft

WORKDIR /app

# venv + código del backend
COPY --from=builder --chown=mailysoft:mailysoft /app/.venv /app/.venv
COPY --from=builder --chown=mailysoft:mailysoft /app /app

# Build de React → carpeta que Django/WhiteNoise sirven (settings.FRONTEND_DIST_DIR).
COPY --from=frontend --chown=mailysoft:mailysoft /web/dist /app/frontend_dist

# Entrypoint (espera Postgres, migra [solo si RUN_MIGRATIONS], collectstatic)
COPY --chown=mailysoft:mailysoft backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Carpetas de escritura para collectstatic/media. El COPY deja /app como root;
# el usuario no-root necesita poder escribir aquí (si no, collectstatic falla con
# PermissionError). Se crean y se asigna el dueño correcto.
RUN mkdir -p /app/staticfiles /app/media \
    && chown mailysoft:mailysoft /app /app/staticfiles /app/media

USER mailysoft

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

# Railway inyecta $PORT en runtime → bind dinámico (sh -c para expandir la var).
# Servicio WEB: usa este CMD. Servicio WORKER: se sobreescribe el start command
# en Railway con "celery -A config.celery worker -l INFO -c 2".
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --worker-class gthread --threads 2 --timeout 120 --access-logfile - --error-logfile -"]
