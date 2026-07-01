#!/bin/bash
# =============================================================================
# Maily Soft — entrypoint.sh
# Espera a que Postgres esté disponible, corre migraciones y collectstatic,
# luego ejecuta el comando pasado como argumento (CMD del Dockerfile).
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colores para logs
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[entrypoint]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[entrypoint]${NC} $*"; }
log_error() { echo -e "${RED}[entrypoint]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Esperar a que Postgres esté listo
# ---------------------------------------------------------------------------
wait_for_postgres() {
    local retries=30
    local wait=2

    log_info "Esperando a PostgreSQL..."

    until python -c "
import sys, os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', '${DJANGO_SETTINGS_MODULE:-config.settings.production}')
django.setup()
from django.db import connection
connection.ensure_connection()
print('PostgreSQL listo')
" 2>/dev/null; do
        retries=$((retries - 1))
        if [ "$retries" -le 0 ]; then
            log_error "No se pudo conectar a PostgreSQL despues de varios intentos"
            exit 1
        fi
        log_warn "PostgreSQL no disponible, reintentando en ${wait}s... (intentos restantes: ${retries})"
        sleep "$wait"
    done

    log_info "PostgreSQL disponible"
}

# ---------------------------------------------------------------------------
# Migraciones
# ---------------------------------------------------------------------------
run_migrations() {
    log_info "Ejecutando migraciones..."
    python manage.py migrate --noinput
    log_info "Migraciones completadas"
}

# ---------------------------------------------------------------------------
# Archivos estáticos
# ---------------------------------------------------------------------------
collect_static() {
    log_info "Recolectando archivos estaticos..."
    python manage.py collectstatic --noinput --clear 2>/dev/null || \
        python manage.py collectstatic --noinput
    log_info "Archivos estaticos listos"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    wait_for_postgres

    # Solo el servicio web corre migraciones. En Railway el worker las omite con
    # RUN_MIGRATIONS=false para evitar carreras. Default true → web/local sin cambios.
    if [[ "${RUN_MIGRATIONS:-true}" == "true" ]]; then
        run_migrations
    else
        log_info "RUN_MIGRATIONS=false → se omiten migraciones (las corre el servicio web)."
    fi

    # Solo collectstatic si no es worker de Celery
    if [[ "${1:-}" != "celery"* ]]; then
        collect_static
    fi

    log_info "Iniciando: $*"
    exec "$@"
}

main "$@"
