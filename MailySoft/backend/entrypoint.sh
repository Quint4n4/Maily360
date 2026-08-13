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
# Este bloque no solo prueba la base de datos: arranca Django entero. Falla por
# cualquier cosa que impida levantar (una variable de entorno faltante o mal
# escrita, un settings invalido, una dependencia rota), no solo porque Postgres
# no responda. Por eso el error REAL tiene que salir en el log.
#
# El 2026-08-13 un DSN de Sentry mal formado tuvo al worker 20 minutos en bucle
# de arranque mientras el log repetia "PostgreSQL no disponible". La base estaba
# perfecta. El 2>/dev/null que habia aqui se comio la unica pista que habia.
wait_for_postgres() {
    local retries=30
    local wait=2
    local err_file
    err_file="$(mktemp)"

    log_info "Esperando a PostgreSQL..."

    until python -c "
import sys, os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', '${DJANGO_SETTINGS_MODULE:-config.settings.production}')
django.setup()
from django.db import connection
connection.ensure_connection()
print('PostgreSQL listo')
" 2>"$err_file"; do
        retries=$((retries - 1))
        if [ "$retries" -le 0 ]; then
            log_error "No se pudo arrancar Django ni conectar a PostgreSQL despues de varios intentos."
            log_error "Error completo del ultimo intento:"
            cat "$err_file" >&2
            rm -f "$err_file"
            exit 1
        fi
        # En cada reintento, la ultima linea del traceback: es la que dice el tipo
        # de excepcion y el mensaje. El traceback completo se imprime al agotarse
        # los intentos, para no repetirlo 30 veces.
        log_warn "Fallo el arranque: $(tail -n 1 "$err_file")"
        log_warn "Reintentando en ${wait}s... (intentos restantes: ${retries})"
        sleep "$wait"
    done

    rm -f "$err_file"
    log_info "PostgreSQL disponible"
}

# ---------------------------------------------------------------------------
# Rol de base de datos: comprobar que RLS aplica de verdad
# ---------------------------------------------------------------------------
# El aislamiento entre clinicas tiene dos barreras: el TenantManager de Django
# (aplicacion) y las politicas RLS de PostgreSQL (base de datos). PostgreSQL
# EXIME de RLS a los roles superuser y bypassrls, incluso con FORCE. Si la app se
# conecta con uno de esos, la segunda barrera queda inerte y nada lo dice.
#
# check_db_role sale con codigo 1 cuando el rol evade RLS. Aqui eso ABORTA el
# arranque en produccion, y solo advierte fuera de ella: el Postgres de
# docker-compose y el de CI corren con un rol superuser a proposito, asi que
# bloquear ahi romperia `docker compose up` sin aportar nada.
#
# REQUIRE_DB_ROLE_RLS=false desactiva el candado. Existe para el rollback
# documentado en docs/deploy-rol-app-nosuperuser.md: si hay que volver
# temporalmente al rol 'postgres', sin este escape la app ya no arrancaria y el
# rollback quedaria bloqueado justo cuando hace falta.
verify_db_role() {
    local es_produccion="false"
    if [[ "${DJANGO_SETTINGS_MODULE:-}" == *production* ]]; then
        es_produccion="true"
    fi
    local obligatorio="${REQUIRE_DB_ROLE_RLS:-$es_produccion}"

    log_info "Verificando el rol de base de datos (RLS)..."

    if python manage.py check_db_role; then
        return 0
    fi

    if [[ "$obligatorio" == "true" ]]; then
        log_error "El rol de base de datos EVADE Row Level Security."
        log_error "La segunda barrera de aislamiento entre clinicas esta inerte:"
        log_error "el unico filtro por tenant seria el de la capa de aplicacion."
        log_error "Ver docs/deploy-rol-app-nosuperuser.md."
        log_error "Para arrancar de todos modos (rollback): REQUIRE_DB_ROLE_RLS=false"
        exit 1
    fi

    log_warn "El rol evade RLS. Se continua: no es un arranque de produccion."
}

# ---------------------------------------------------------------------------
# Migraciones
# ---------------------------------------------------------------------------
run_migrations() {
    log_info "Ejecutando migraciones..."
    # Las migraciones crean/alteran tablas y políticas RLS: requieren un rol con
    # privilegios de DDL (superuser/owner). Si la app del día a día se conecta con
    # un rol NOSUPERUSER (para que RLS aplique como segunda barrera), ese rol NO
    # puede migrar. MIGRATION_DATABASE_URL permite usar el rol privilegiado SOLO
    # aquí. Si no se define, se usa DATABASE_URL (comportamiento actual, local).
    if [[ -n "${MIGRATION_DATABASE_URL:-}" ]]; then
        log_info "Usando MIGRATION_DATABASE_URL (rol con privilegios de DDL)."
        DATABASE_URL="$MIGRATION_DATABASE_URL" python manage.py migrate --noinput
    else
        python manage.py migrate --noinput
    fi
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

    # Antes de migrar: si el rol de conexion evade RLS, mejor enterarse aqui que
    # despues de aplicar migraciones. Usa DATABASE_URL (el rol de la app), nunca
    # MIGRATION_DATABASE_URL — el rol privilegiado ES superuser por diseño.
    verify_db_role

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
