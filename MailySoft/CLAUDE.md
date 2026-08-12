# Maily360 / MailySoft

**Qué es:** SaaS multitenant de gestión de clínicas privadas en México. Muchas clínicas, mismo
software, datos aislados. Migra de `app.maily.mx` (PHP heredado); es reemplazo, no coexistencia.
**Cliente:** producto propio de Emanuel, a vender por suscripción · **Etapa:** producción temprana
**Multitenant:** sí — lee `.claude/skills/multitenancy/` sin excepción.

**Fecha de adopción del modelo de trabajo: 2026-08-11.**
Todo commit posterior a esa fecha se revisa con el agente `reviewer` en **modo gate**. El código
anterior no bloquea nada: se audita una vez y se arregla por orden de riesgo (*clean as you code*).

## Cómo se trabaja aquí

El proceso completo está en `MI CONTEXTO/FLUJO-DE-TRABAJO.md` del usuario. Resumen operativo:

1. `docs/01-analisis.md` define **qué** se construye y para quién. No se toca al programar.
2. `docs/02-contrato.md` define **cómo**: modelo de datos, endpoints, permisos. **Es la fuente de
   verdad.** Backend y frontend construyen contra él, no contra suposiciones.
3. Si el código necesita contradecir el contrato, **se actualiza el contrato en el mismo PR.** Un
   contrato desactualizado hace que el siguiente agente construya sobre una mentira.
4. Cada módulo pasa por el agente `reviewer` antes de acercarse a `main`.

## Estado de la adopción

| Fase | Qué produce | Estado |
|---|---|---|
| A1 · Consolidar documentación | `docs/01-analisis.md` + `docs/_legacy/` | ✅ 2026-08-11 |
| A2 · Contrato inverso | `docs/02-contrato.md` + `docs/00-brechas.md` | ⏳ siguiente |
| A3 · Auditoría | `docs/00-deuda.md` | ⏳ |
| A4 · Triage | prioridades confirmadas | ⏳ |

## Agentes disponibles

| Agente | Cuándo |
|---|---|
| `architect` | Produce `02-contrato.md`. **En este repo se usa en MODO INVERSO**: extrae el contrato del código existente, no lo diseña. No escribe código ni migraciones. |
| `backend` | Implementa Django/DRF contra el contrato. |
| `frontend` | Implementa React/TS contra el contrato. |
| `reviewer` | Verifica con checklist falsable. **No edita código** (no tiene herramientas de escritura). |

Los cinco agentes anteriores (`django-engineer`, `django-reviewer`, `django-security`,
`django-tester`, `docs-reporter`) se retiraron el 2026-08-11 y están en
`docs/_legacy/agentes-anteriores/`. **No los uses:** dos definiciones de "cómo se revisa aquí"
producen revisiones que se contradicen.

## Documentación: dónde está la verdad

| Quieres saber | Lee |
|---|---|
| Qué es el producto y para quién | `docs/01-analisis.md` |
| Qué hace el sistema hoy, endpoint por endpoint | `docs/02-contrato.md` |
| Qué está mal y en qué orden se arregla | `docs/00-deuda.md` |
| Por qué se decidió algo | `docs/DECISIONES-CLAVE.md` y `docs/adr/` |
| Cómo se audita la seguridad | `docs/reports/PROTOCOLO-AUDITORIA-SEGURIDAD.md` |
| Qué falta de rendimiento | `docs/reports/metricas-refactor-huerfanos-escalabilidad.md` |
| Cómo se despliega | `docs/DEPLOY-RAILWAY.md`, `docs/deploy-rol-app-nosuperuser.md` |

**`docs/_legacy/` no es fuente de verdad.** Es documentación archivada que ya no describe el sistema.
Su `README.md` explica por qué se archivó cada documento y, además, lista las **correcciones
pendientes de los documentos que sí siguen vivos**. Si un documento vivo te contradice al código,
revisa esa lista antes de creerle.

## Stack real

- **Backend:** Django 5.2 + DRF · PostgreSQL con Row Level Security · Redis · Celery · Docker
- **Frontend:** Vite + React 18 + TypeScript + Tailwind + TanStack Query, en `web-soft/`
- **Infra:** Railway (API, Postgres, Redis, worker) · Cloudinary (archivos) · Sentry
- **PDFs:** WeasyPrint, generados de forma asíncrona con Celery (`apps/pdfs`)
- 15 apps Django por dominio · `web-platform/` está vacío: el portal interno vive en `web-soft/`

## Reglas duras de este proyecto

Además de las convenciones generales, aquí hay cinco que no se negocian porque son de seguridad o de
cumplimiento normativo:

1. **Todo modelo de negocio hereda de `TenantAwareModel` y necesita su migración de RLS.** El test
   `apps/core/tests/test_rls_coverage.py` falla en CI si falta. No lo silencies: agrega la migración.
   Aplica también a las tablas intermedias de un `ManyToManyField` sin `through`.
2. **El backend es la autoridad de permisos.** El rol del frontend solo decide qué se muestra. Un
   endpoint sin `permission_classes` es un bug de seguridad, no un descuido.
3. **Un módulo apagado responde 404, no 403.** La clínica no debe saber que existe algo que no
   compró.
4. **Lo clínico es inmutable.** Las notas de evolución y las recetas no se editan ni se borran: se
   corrigen con addendum o se anulan con motivo. No agregues un `update` "por comodidad".
5. **Las acciones sensibles se registran en la bitácora** (`audit_record`) con un identificador
   no-PII del recurso. Es requisito normativo, no adorno.

## Convenciones

- **Código, modelos, ramas y commits en inglés. Documentación y comentarios en español.**
- Apps Django por dominio de negocio, nunca por capa técnica.
- La lógica de negocio vive en `services.py`. Las vistas orquestan y responden; no deciden. Las
  lecturas complejas viven en `selectors.py`.
- Un serializer por caso de uso. No reutilizar un serializer de escritura para lectura.
- Commits: Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`).
- Ramas: `main` siempre desplegable. Una rama por feature: `feat/<modulo>`. Merge por PR.
- Nunca commitear `.env` ni secretos. Variables de entorno en Railway.
- Toda migración debe poder revertirse. Si no puede, se dice explícitamente en el PR.

## Comandos

```bash
# Backend (desde MailySoft/)
docker compose up
docker compose exec backend python manage.py migrate
docker compose exec backend pytest -q
docker compose exec backend python manage.py check_db_role   # diagnostica RLS vs rol superuser

# Siembra de datos (dev)
python manage.py seed_planes     # catálogo de planes: sin esto la clínica nace sin módulos
python manage.py seed_demo       # clínica de demostración (requiere DEMO_OWNER_PASSWORD)

# Frontend (desde web-soft/)
npm run dev
npm run build
npm run test:e2e
```

## Reglas para ti, Claude

- Si algo no está en `docs/02-contrato.md`, **no lo inventes: detente y pregunta.**
- No crees archivos, endpoints ni modelos que nadie pidió.
- No instales una dependencia nueva sin decir qué problema resuelve y qué se descartó.
- Emanuel es nivel intermedio en Django, y **principiante en frontend, base de datos y seguridad**.
  Explica el porqué de lo que haces en esas áreas, con un ejemplo concreto de este proyecto (una
  clínica con dos sedes, un médico que trabaja en dos clínicas, una receta ya emitida).
- Corrígelo en el momento en que detectes el error, no al final.
- Al terminar, di en dos líneas qué se puede romper después de este cambio.
