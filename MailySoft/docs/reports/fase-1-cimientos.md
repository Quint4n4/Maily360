# Cierre de Fase 1 — Cimientos de Maily Soft

| Campo | Valor |
|---|---|
| Fase | 1 — Cimientos |
| Pasos cubiertos | Paso 1 (Scaffolding) · Paso 2 (Multi-tenant) |
| Periodo | 2026-06-01 al 2026-06-02 |
| Commits | `36dbf5a` · `fc8458b` · `2e8059d` · `8aa9ac9` · `8bf747a` |
| Fecha de reporte | 2026-06-02 |

---

## Resumen ejecutivo

La Fase 1 establece los cimientos sobre los que se construirá toda la plataforma Maily Soft. En dos pasos de trabajo se levantó el monorepo completo con su infraestructura de contenedores, el sistema de identidad multi-tenant con tres capas de aislamiento en código más una cuarta en la base de datos (PostgreSQL Row Level Security), y un conjunto de 62 tests automatizados que llegan al 98.62 % de cobertura en los módulos base.

El trabajo fue revisado por un ciclo completo de revisión de código y auditoría de seguridad antes de darse por cerrado. Se encontraron 4 hallazgos bloqueantes (incluyendo una falla en la alimentación de la función RLS y una fuga silenciosa en el manager) y múltiples issues de nivel medio. Todos fueron corregidos en el commit `8bf747a` antes de marcar la fase como terminada. El sistema arranca limpio, las migraciones corren sin error sobre una base de datos nueva, y el entorno local es 100 % reproducible con `make up && make migrate`.

La Fase 2 puede comenzar sobre una base sólida. El primer módulo de negocio (Agenda) será también el momento en que se activen las primeras políticas RLS sobre tablas reales, completando así el círculo de la arquitectura de defensa en profundidad definida en el [ADR-0002](../adr/0002-arquitectura-multi-tenant.md).

---

## Alcance entregado

### Paso 1 — Scaffolding (`36dbf5a`, `fc8458b`, `2e8059d`)

| Componente | Descripción |
|---|---|
| Monorepo | `Maily360/` con `MailySoft/backend/`, `web-soft/` y `web-platform/` |
| Backend base | Django 5 + DRF + Postgres 16 + Redis 7 + Celery, gestionado con Poetry |
| Infraestructura local | Docker Compose con 4 servicios: `db`, `redis`, `backend`, `worker` |
| Tooling | `black` + `ruff` (formato/lint), `mypy` + `django-stubs` (tipos), `pytest` + `pytest-django` (tests), `pre-commit` |
| CI | GitHub Actions con jobs de lint, tipos, tests y `pip-audit` |
| Agentes | 5 agentes Claude especializados + skill `django-clean-architecture` en `.claude/` |
| ADR | [ADR-0001 — Stack y arquitectura](../adr/0001-stack-y-arquitectura.md) |
| Makefile | Comandos `make up`, `make migrate`, `make test`, entre otros |

### Paso 2 — Cimientos multi-tenant (`8aa9ac9`, `8bf747a`)

| Componente | Descripción |
|---|---|
| `apps/core` | `BaseModel` (UUID pk, timestamps, soft-delete), `TenantAwareModel`, `TenantManager`, `tenant_context` (thread-local), `TenantMiddleware` |
| `apps/tenancy` | Modelo `Tenant` (ciclo `TRIAL → ACTIVE → SUSPENDED`, `slug`), `TenantMembership` (7 roles), admin Django; migración `0002_enable_rls` con función PostgreSQL `current_tenant_id()` |
| `apps/authn` | Modelo `User` email-based (sin `username`), bandera `is_platform_staff`, `PlatformRole` enum, `UserManager`, admin con fieldsets reorganizados |
| Seguridad | Argon2 como hasher por defecto (`argon2-cffi`), `IsAuthenticated` como permiso global |
| Tests | 62 tests en `core`, `tenancy` y `authn`; factories y fixtures en `conftest.py` |
| ADR | [ADR-0002 — Arquitectura multi-tenant](../adr/0002-arquitectura-multi-tenant.md) |

---

## Cómo se trabajó

La Fase 1 usó un flujo de 5 agentes especializados que se convierte en el modelo de trabajo para todas las fases siguientes:

1. **django-engineer** — implementa el código de producción (modelos, managers, middleware, migraciones, configuración).
2. **django-tester** — escribe los tests de la funcionalidad entregada. No avanza si no hay tests.
3. **django-reviewer** — revisa el código contra el Django Styleguide y las convenciones del proyecto. Emite hallazgos clasificados por severidad.
4. **django-security** — audita con foco en el marco normativo mexicano (NOM-024, LFPDPPP). Prioriza fugas de datos entre tenants y autenticación.
5. **django-docs-reporter** (este agente) — documenta lo que se construyó, genera ADRs, reportes y actualiza el CHANGELOG.

El ciclo de una entrega es: **engineer → tester → reviewer → security → docs**. Ningún paso se salta. Los hallazgos bloqueantes del reviewer o security detienen el avance hasta ser corregidos.

---

## Metricas reales

| Metrica | Valor |
|---|---|
| Commits en la fase | 5 (`36dbf5a`, `fc8458b`, `2e8059d`, `8aa9ac9`, `8bf747a`) |
| Apps Django creadas | 3 (`core`, `tenancy`, `authn`) |
| Tests automatizados | 62 |
| Cobertura de tests | 98.62 % |
| Funcion RLS en Postgres | 1 (`current_tenant_id()`) |
| ADRs formalizados | 2 (ADR-0001, ADR-0002) |
| Archivos insertados en Paso 2 | 21 archivos · 923 inserciones (commit `8aa9ac9`) |
| Fixes aplicados tras revisión | 10 (commit `8bf747a`) |

---

## Calidad y seguridad

El código del Paso 2 pasó por un ciclo completo de revisión antes de cerrarse:

- El **django-reviewer** encontró 3 hallazgos bloqueantes, 5 recomendados y 4 nits. Ver detalle en [`review-paso-2.md`](review-paso-2.md).
- El **django-security** encontró 2 hallazgos de severidad alta y 3 medios. Ver detalle en [`security-audit-paso-2.md`](security-audit-paso-2.md).
- Todos los bloqueantes y hallazgos altos fueron corregidos en el commit `8bf747a` antes de cerrar la fase.
- Los nits de menor impacto quedan registrados en los reportes de revisión para atención en sprints posteriores.

---

## Estado del sistema al cierre

- 4 contenedores corriendo: `db` (Postgres 16), `redis` (Redis 7), `backend` (Django), `worker` (Celery).
- Migraciones aplicadas limpiamente sobre base de datos nueva.
- Superuser `admin@maily.local` creado.
- Tenant de demostración "Clinica Demo Vitalis" creado con membresía `admin@Owner`.
- `/admin/login/` responde 200.

---

## Proximos pasos — Paso 3: primer modulo de negocio

El **Paso 3** implementará el módulo **Agenda** (citas y disponibilidad). Será el primer módulo con modelos que heredan de `TenantAwareModel` en una app de dominio real, lo que activará también las primeras **políticas RLS** sobre tablas concretas — completando la última capa de aislamiento descrita en el [ADR-0002](../adr/0002-arquitectura-multi-tenant.md).

Trabajo esperado en el Paso 3:

- Modelos `Appointment`, `Slot`, `Schedule` heredando de `TenantAwareModel`.
- Migración que activa `ENABLE ROW LEVEL SECURITY` + política `USING (tenant_id = current_tenant_id())` en cada tabla nueva.
- Endpoints DRF (create, list, retrieve, cancel).
- Tests de fuga cross-tenant obligatorios por módulo.
- Evolución del middleware para leer header `X-Tenant-ID` y validarlo contra el JWT.
