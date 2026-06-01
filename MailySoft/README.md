# Maily Soft

Maily Soft es una plataforma SaaS multi-tenant de gestión clínica. Permite a clínicas y consultorios administrar su agenda, expedientes electrónicos, facturación y comunicación con pacientes desde una interfaz unificada. Esta es la base del monorepo que contiene el backend Django, los frontends React y el portal de administracion del SaaS.

## Stack tecnologico

| Capa | Tecnologia |
|---|---|
| Backend API | Django 5.1 + DRF 3.15 |
| Autenticacion | SimpleJWT (access 15min / refresh 7d) |
| Base de datos | PostgreSQL 16 |
| Cache / broker | Redis 7 |
| Tareas asincronas | Celery 5 |
| WebSockets | Django Channels 4 |
| Schema API | drf-spectacular (OpenAPI 3) |
| Frontend clinica | React (web-soft/) — pendiente |
| Frontend SaaS | React (web-platform/) — pendiente |
| Contenedores | Docker + docker-compose |
| CI | GitHub Actions |
| Tipado | mypy + django-stubs |
| Linting | Ruff + Black |

## Estructura del repositorio

```
MailySoft/
├── backend/                  # API Django
│   ├── config/               # Settings, URLs, ASGI/WSGI, Celery
│   ├── apps/                 # Modulos de dominio (core + futuros)
│   ├── adapters/             # Integraciones externas (Stripe, WhatsApp...)
│   ├── workers/              # Tareas Celery compartidas
│   └── tests/                # Fixtures globales de pytest
├── web-soft/                 # Frontend React para la clinica (placeholder)
├── web-platform/             # Frontend React para el panel SaaS (placeholder)
├── docs/
│   ├── onboarding.md         # Guia de primer dia
│   └── adr/                  # Architecture Decision Records
├── infra/                    # Terraform / configs de infra (placeholder)
├── .github/workflows/ci.yml  # Pipeline de CI
├── docker-compose.yml
├── Makefile
└── .pre-commit-config.yaml
```

## Quick start con Docker

```bash
# 1. Crear archivo de variables de entorno
cp backend/.env.example backend/.env.dev
# Editar backend/.env.dev con tus valores locales

# 2. Levantar todos los servicios
make up

# 3. Abrir el browser
open http://localhost:8000/api/docs/
```

> La primera vez Docker construye las imagenes (~2-3 min).

## Comandos comunes

Todos los comandos frecuentes estan en el `Makefile`. Ejecuta `make help` para ver la lista completa.

```bash
make up           # Levanta servicios
make down         # Detiene servicios
make migrate      # Corre migraciones
make test         # Tests con cobertura
make lint         # Ruff linter
make fmt          # Black formateador
make typecheck    # mypy
make shell        # Shell Django
make logs         # Logs del backend
make clean        # Limpieza total
```

## Agentes disponibles

Este proyecto incluye agentes Claude especializados en `.claude/agents/`:

| Agente | Rol |
|---|---|
| `django-engineer` | Escribe features siguiendo la arquitectura limpia |
| `django-reviewer` | Revisa PRs contra los estandares del proyecto |
| `django-tester` | Escribe tests pytest/factory-boy |
| `django-security` | Audita seguridad (OWASP, secrets, permisos) |
| `docs-reporter` | Genera documentacion tecnica |

Para invocar un agente en Claude Code: abre el chat y menciona el agente por nombre.

## Documentacion

- [Guia de onboarding](docs/onboarding.md) — primer dia como dev
- [ADR-0001: Stack y arquitectura](docs/adr/0001-stack-y-arquitectura.md) — por que este stack
