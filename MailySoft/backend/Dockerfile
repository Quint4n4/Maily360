# =============================================================================
# Maily Soft Backend — Dockerfile multi-stage
# Stage 1: build (instala deps con Poetry)
# Stage 2: runtime (imagen slim, usuario no-root)
# =============================================================================

# ---- Stage 1: build ----
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
    && rm -rf /var/lib/apt/lists/*

# Instalar Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

# Copiar solo los archivos de dependencias primero (cache de Docker)
COPY pyproject.toml poetry.lock* ./

# Instalar dependencias de producción (sin dev deps)
RUN poetry install --only=main --no-root

# Copiar el código fuente
COPY . .

# Instalar el proyecto
RUN poetry install --only=main


# ---- Stage 2: runtime ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root por seguridad
RUN groupadd --gid 1001 mailysoft \
    && useradd --uid 1001 --gid mailysoft --shell /bin/bash --create-home mailysoft

WORKDIR /app

# Copiar virtualenv y código del builder
COPY --from=builder --chown=mailysoft:mailysoft /app/.venv /app/.venv
COPY --from=builder --chown=mailysoft:mailysoft /app /app

# Copiar y preparar entrypoint
COPY --chown=mailysoft:mailysoft entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER mailysoft

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/admin/login/ || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "gthread", \
     "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
