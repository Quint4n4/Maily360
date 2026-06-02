# Changelog

Todos los cambios notables de Maily Platform se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

---

## [Unreleased]

### Added (Paso 2 — Cimientos multi-tenant) · commit `8aa9ac9`

- `apps/core`: `BaseModel` (UUID pk, timestamps, soft-delete), `TenantAwareModel` (FK a tenant + `created_by`), `TenantManager` (filtra por tenant en thread-local + excluye soft-deleted), `tenant_context` (almacenamiento thread-local con `set/get/clear_current_tenant`) y `TenantMiddleware` (inyecta tenant desde la primera membresía activa del usuario autenticado).
- `apps/tenancy`: modelo `Tenant` con ciclo de vida `TRIAL → ACTIVE → SUSPENDED` y campo `slug` para futuro header `X-Tenant-ID`; modelo `TenantMembership` con 7 roles (`owner`, `admin`, `doctor`, `nurse`, `reception`, `finance`, `readonly`); admin de Django para ambos modelos.
- `apps/tenancy` migración `0002_enable_rls`: función PostgreSQL `current_tenant_id()` para políticas RLS de tablas tenant-aware (las políticas se activan tabla por tabla en el Paso 3).
- `apps/authn`: modelo `User` custom email-based (sin `username`), bandera `is_platform_staff` para separar staff de Maily de miembros de clínica, `PlatformRole` enum (`super_admin`, `sales`, `engineering`), `UserManager` con `create_user`/`create_superuser`; admin con fieldsets reorganizados.
- `config/settings/base.py`: `AUTH_USER_MODEL = 'authn.User'`, `LOCAL_APPS` con `apps.authn` y `apps.tenancy`, `TenantMiddleware` en posición correcta (después de `AuthenticationMiddleware`).
- Dependencia `argon2-cffi` añadida a `pyproject.toml`; `PASSWORD_HASHERS` usa Argon2 por defecto.
- `docs/adr/0002-arquitectura-multi-tenant.md`: ADR formal que documenta la decisión shared-schema + RLS.

---

### Added (Paso 1 — Scaffolding) · commits `36dbf5a`, `fc8458b`, `2e8059d`

- Monorepo `Maily360/` con backend Django 5 + DRF en `MailySoft/backend/`, placeholders de frontend en `web-soft/` y `web-platform/`.
- Docker Compose con servicios: Postgres 16, Redis 7, backend Django, worker Celery.
- Tooling: Poetry para gestión de dependencias, `black` + `ruff` para formateo/linting, `mypy` + `django-stubs` para tipos estáticos, `pytest` + `pytest-django` para tests, `pre-commit` con hooks configurados.
- CI con GitHub Actions: pipeline con jobs de lint (`black --check`, `ruff`), tipo (`mypy`), tests (`pytest`) y auditoría de dependencias (`pip-audit`).
- 5 agentes Claude especializados (`django-engineer`, `django-reviewer`, `django-tester`, `django-security`, `django-docs-reporter`) y skill `django-clean-architecture` versionados en `.claude/`.
- `docs/adr/0001-stack-y-arquitectura.md`: ADR del stack tecnológico (Django 5 + DRF + PostgreSQL + Celery + monolito modular).
- `Makefile` con comandos de desarrollo (`make up`, `make migrate`, `make test`, etc.).
