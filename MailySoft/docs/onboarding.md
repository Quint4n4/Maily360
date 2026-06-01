# Onboarding — Primer dia en Maily Soft

Bienvenido al equipo. Este documento te lleva del cero a tener el entorno local funcionando y hacer tu primer PR de prueba.

## Pre-requisitos

Instala estas herramientas antes de clonar el repo:

| Herramienta | Version minima | Instalacion |
|---|---|---|
| Docker Desktop | 4.x | https://www.docker.com/products/docker-desktop/ |
| Git | 2.x | `brew install git` |
| Poetry | 1.8+ | `curl -sSL https://install.python-poetry.org | python3 -` |
| Python | 3.12 | `brew install python@3.12` o `pyenv install 3.12` |
| make | (incluido en macOS) | — |

## Paso 1 — Clonar el repo

```bash
git clone <URL_DEL_REPO> ~/Desktop/Maily360/MailySoft
cd ~/Desktop/Maily360/MailySoft
```

## Paso 2 — Variables de entorno

```bash
cp backend/.env.example backend/.env.dev
```

Abre `backend/.env.dev` y verifica que `DATABASE_URL` y `REDIS_URL` coincidan con docker-compose (ya estan configurados por defecto para desarrollo local).

**No necesitas cambiar nada para levantar en local por primera vez.**

## Paso 3 — Levantar con Docker

```bash
make up
```

Docker descargara las imagenes (~500 MB la primera vez) y levantara:
- PostgreSQL en `localhost:5432`
- Redis en `localhost:6379`
- Django en `http://localhost:8000`
- Celery worker

Verifica que todo este verde:

```bash
docker compose ps
```

Todos los servicios deben estar en estado `running` o `healthy`.

## Paso 4 — Explorar la API

Abre en el browser:
- Swagger UI: http://localhost:8000/api/docs/
- ReDoc: http://localhost:8000/api/redoc/
- Admin Django: http://localhost:8000/admin/

Para crear un superusuario:

```bash
make superuser
```

## Paso 5 — Instalar herramientas de desarrollo

Si vas a hacer commits, instala pre-commit localmente para que los hooks corran antes de cada push:

```bash
cd backend
poetry install           # instala todas las dev deps
pre-commit install       # instala los hooks de git
```

## Paso 6 — Correr los tests

```bash
make test
# o localmente sin Docker:
make local-test
```

Debes ver cobertura >= 80% (el proyecto parte con poco codigo, la barra sube conforme se agrega logica).

## Flujo de trabajo

1. Crea una rama desde `main`: `git checkout -b feat/nombre-del-feature`
2. Escribe codigo siguiendo la skill `django-clean-architecture` (lee `.claude/skills/django-clean-architecture/SKILL.md`)
3. Corre `make lint`, `make fmt`, `make typecheck` antes de hacer push
4. Abre un PR contra `main`; el agente `django-reviewer` revisara automaticamente

## Leer antes de tu primer PR

- [README del proyecto](../README.md)
- [ADR-0001: Stack y arquitectura](adr/0001-stack-y-arquitectura.md)
- `.claude/skills/django-clean-architecture/SKILL.md` — las reglas de codigo que TODO PR debe cumplir

## Soporte

Si algo no funciona, revisa primero `docker compose logs backend`. La mayoria de los problemas en el arranque son de variables de entorno faltantes en `.env.dev`.
