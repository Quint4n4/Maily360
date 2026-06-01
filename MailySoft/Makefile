# =============================================================================
# Maily Soft — Makefile
# Comandos de desarrollo. Todos los comandos de Django se ejecutan dentro
# del contenedor backend; para correrlos localmente usa el prefijo local-*.
# =============================================================================

.PHONY: help up down build migrate makemigrations test lint fmt typecheck \
        shell logs clean superuser audit beat

# ---------------------------------------------------------------------------
# Ayuda
# ---------------------------------------------------------------------------
help:
	@echo ""
	@echo "Maily Soft — comandos disponibles:"
	@echo ""
	@echo "  make up            Levanta todos los servicios (Docker)"
	@echo "  make down          Detiene y elimina contenedores"
	@echo "  make build         Reconstruye las imagenes Docker"
	@echo "  make migrate       Corre migraciones pendientes"
	@echo "  make makemigrations  Genera nuevas migraciones"
	@echo "  make test          Corre pytest con cobertura"
	@echo "  make lint          Ruff (linter)"
	@echo "  make fmt           Black (formateador)"
	@echo "  make typecheck     mypy (tipado estatico)"
	@echo "  make shell         Shell interactivo de Django"
	@echo "  make logs          Logs del backend en tiempo real"
	@echo "  make clean         Elimina contenedores, volumenes y cache"
	@echo "  make superuser     Crea superusuario admin"
	@echo "  make audit         Auditoria de dependencias (pip-audit)"
	@echo "  make beat          Levanta servicios + celery beat"
	@echo ""

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
up:
	docker compose up -d db redis backend celery_worker

down:
	docker compose down

build:
	docker compose build

beat:
	docker compose --profile beat up -d

# ---------------------------------------------------------------------------
# Django
# ---------------------------------------------------------------------------
migrate:
	docker compose exec backend python manage.py migrate

makemigrations:
	docker compose exec backend python manage.py makemigrations

shell:
	docker compose exec backend python manage.py shell

superuser:
	docker compose exec backend python manage.py createsuperuser

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test:
	docker compose exec backend poetry run pytest --cov --cov-fail-under=80 -v

# Para correr tests localmente (sin Docker), con venv activado:
local-test:
	cd backend && poetry run pytest --cov --cov-fail-under=80 -v

# ---------------------------------------------------------------------------
# Calidad de código
# ---------------------------------------------------------------------------
lint:
	docker compose exec backend poetry run ruff check .

fmt:
	docker compose exec backend poetry run black .

typecheck:
	docker compose exec backend poetry run mypy backend/

# Variantes locales (sin Docker)
local-lint:
	cd backend && poetry run ruff check .

local-fmt:
	cd backend && poetry run black .

local-typecheck:
	cd backend && poetry run mypy .

# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------
audit:
	cd backend && poetry run pip-audit --requirement <(poetry run pip freeze)

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
logs:
	docker compose logs -f backend

# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------
clean:
	docker compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
	find . -name "htmlcov" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name ".mypy_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name ".ruff_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "Limpieza completa"
