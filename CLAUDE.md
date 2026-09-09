# Maily360 / MailySoft

**Qué es:** SaaS multitenant de gestión de clínicas privadas en México. Muchas clínicas, mismo
software, datos aislados. Migra de `app.maily.mx` (PHP heredado); es reemplazo, no coexistencia.
**Cliente:** producto propio de Emanuel, a vender por suscripción · **Etapa:** desarrollo
**Multitenant:** sí — lee la skill `aislamiento-de-datos` del plugin `biblioteca-de-skills`, sin
excepción. (La skill local `.claude/skills/multitenancy/` se archivó el 2026-08-18; ya no existe.)

> **Los hechos del repo viven en `.claude/PERFIL-DEL-REPO.md`, no aquí.** Si los dos difieren,
> gana el perfil. Este archivo se queda con la prosa: el porqué, las trampas heredadas y lo que
> no se toca.

**Fecha de adopción del modelo de trabajo: 2026-08-11.**
Todo commit posterior a esa fecha se revisa con el agente `reviewer` en **modo gate**. El código
anterior no bloquea nada: se audita una vez y se arregla por orden de riesgo (*clean as you code*).

## Estructura del repo: leer esto primero

El proyecto está **anidado un nivel**. Confundir los dos niveles ya costó una sesión de trabajo.

```
Maily360/            ← raíz del repo y raíz de la sesión. Aquí van .git, CLAUDE.md y .claude/
├── CLAUDE.md
├── .claude/agents/  ← architect · backend · frontend · reviewer
├── .claude/skills/
├── .github/workflows/ci.yml
├── CHANGELOG.md     ← congelado desde junio, hay que reescribirlo
├── documentacion/   ← maquetas y presentaciones comerciales en HTML. NO es doc técnica
└── MailySoft/       ← el proyecto: código y documentación técnica
    ├── backend/     ← Django, 15 apps en backend/apps/
    ├── web-soft/    ← React + Vite (app de clínica y portal interno)
    ├── web-platform/← vacío, ignorar
    └── docs/        ← 01-analisis.md, 02-contrato.md, adr/, design/, reports/, _legacy/
```

**Las sesiones se abren en `Maily360/`**, no en `MailySoft/`. Los comandos de Django y de npm sí se
corren desde dentro (`MailySoft/backend`, `MailySoft/web-soft`).

## Cómo se trabaja aquí

El proceso completo está en `MI CONTEXTO/FLUJO-DE-TRABAJO.md` del usuario. Resumen operativo:

1. `MailySoft/docs/01-analisis.md` define **qué** se construye y para quién. No se toca al programar.
2. `MailySoft/docs/02-contrato.md` define **cómo**: modelo de datos, endpoints, permisos. **Es la
   fuente de verdad.** Backend y frontend construyen contra él, no contra suposiciones.
3. Si el código necesita contradecir el contrato, **se actualiza el contrato en el mismo PR.** Un
   contrato desactualizado hace que el siguiente agente construya sobre una mentira.
4. Cada módulo pasa por el agente `reviewer` antes de acercarse a `main`.

## Estado de la adopción

| Fase | Qué produce | Estado |
|---|---|---|
| A1 · Consolidar documentación | `docs/01-analisis.md` + `docs/_legacy/` | ✅ 2026-08-11 |
| A2 · Contrato inverso | `docs/02-contrato.md` + `docs/00-brechas.md` | ✅ 2026-08-12 — 15 apps, 167 brechas |
| A3 · Auditoría | `docs/00-deuda.md` | ✅ 2026-08-13 — 27 causas raíz, 276 hallazgos |
| A4 · Triage | `docs/00-plan-de-ataque.md` + `docs/00-modulos.md` | ✅ 2026-08-13 — plan M0–M6 |

## Agentes

| Agente | Cuándo |
|---|---|
| `architect` | Produce `02-contrato.md`. **En este repo se usa en MODO INVERSO**: extrae el contrato del código existente, no lo diseña. No escribe código ni migraciones. |
| `backend` | Implementa Django/DRF contra el contrato. |
| `frontend` | Implementa React/TS contra el contrato. |
| `reviewer` | Verifica con checklist falsable. **No edita código** (no tiene herramientas de escritura). |

Los cinco agentes anteriores (`django-engineer`, `django-reviewer`, `django-security`,
`django-tester`, `docs-reporter`) se retiraron el 2026-08-11 y están en
`MailySoft/docs/_legacy/agentes-anteriores/`. **No los uses:** dos definiciones de "cómo se revisa
aquí" producen revisiones que se contradicen. Si aparecen como disponibles, están cargándose desde
`~/.claude/agents/` (globales del usuario) y hay que sacarlos de ahí — dilo en voz alta y detente.

## Documentación: dónde está la verdad

Todo bajo `MailySoft/docs/`.

| Quieres saber | Lee |
|---|---|
| Qué es el producto y para quién | `01-analisis.md` |
| Qué hace el sistema hoy, endpoint por endpoint | `02-contrato.md` |
| Qué está mal y en qué orden se arregla | `00-deuda.md` |
| Por qué se decidió algo | `DECISIONES-CLAVE.md` y `adr/` |
| Cómo se audita la seguridad | `reports/PROTOCOLO-AUDITORIA-SEGURIDAD.md` |
| Qué falta de rendimiento | `reports/metricas-refactor-huerfanos-escalabilidad.md` |
| Cómo se despliega | `DEPLOY-RAILWAY.md`, `deploy-rol-app-nosuperuser.md` |

**`docs/_legacy/` no es fuente de verdad.** Es documentación archivada que ya no describe el sistema.
Su `README.md` explica por qué se archivó cada documento y, además, lista las **correcciones
pendientes de los documentos que sí siguen vivos**. Si un documento vivo contradice al código,
revisa esa lista antes de creerle.

## Stack real

- **Backend:** Django 5.2 + DRF · PostgreSQL con Row Level Security · Redis · Celery · Docker
- **Frontend:** Vite + React 18 + TypeScript + Tailwind + TanStack Query, en `MailySoft/web-soft/`
- **Infra:** Railway (API, Postgres, Redis, worker) · Cloudinary (archivos) · Sentry
- **PDFs:** WeasyPrint, generados de forma asíncrona con Celery (`apps/pdfs`)

## Reglas duras de este proyecto

Cinco que no se negocian porque son de seguridad o de cumplimiento normativo:

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

# Frontend (desde MailySoft/web-soft/)
npm run dev
npm run build
npm run test:e2e
```

## Notas del entorno

- **Dos cuentas de GitHub en esta máquina.** El repo es de `Quint4n4`; el keychain suele autenticar
  como `EmanuelRealGamboa`. Si un push falla por credenciales:
  `gh auth switch --user Quint4n4`.
  **Son dos credenciales distintas y hay que entenderlo o se pierde media hora:**
  - `git push` usa el **llavero de macOS** (`credential.helper = osxkeychain`).
  - `gh pr create` usa el **keyring propio de `gh`**, con su cuenta activa.

  `gh auth switch` cambia la de `gh` **y reescribe la del llavero** (verificado). El problema es que
  **la cuenta activa vuelve sola a `EmanuelRealGamboa` entre invocaciones de shell**: un comando
  puede terminar con `Quint4n4` activa y el siguiente arrancar con la otra.

  Por eso el switch y el comando que lo necesita van en la **misma invocación de shell**. Y si aun
  así falla, **verifica el usuario en vez de repetir el switch a ciegas** — cuando `gh` ya se cree en
  la cuenta destino, el switch no reescribe nada:

  ```bash
  printf 'protocol=https\nhost=github.com\n\n' | git credential fill | grep '^username'
  ```

  Un fallo aquí se disfraza: `git` dice `Permission denied` y `gh` dice `must be a collaborator`,
  que suena a permiso faltante del repo y no lo es.

  Arreglo de fondo, pendiente: limpiar del llavero la credencial de `github.com` y correr
  `gh auth setup-git` con `Quint4n4` activa.
- **Locks colgados de git.** Si un comando falla con `index.lock` o `HEAD.lock`, revisa que no haya
  otro proceso git corriendo y bórralos (`.git/index.lock`, `.git/HEAD.lock`, ambos de 0 bytes).
- **Nunca dos sesiones a la vez sobre este repo.** Se pisan los archivos. Paralelismo solo con
  `git worktree` en carpetas distintas.

## Reglas para ti, Claude

- Si algo no está en `MailySoft/docs/02-contrato.md`, **no lo inventes: detente y pregunta.**
- No crees archivos, endpoints ni modelos que nadie pidió.
- No instales una dependencia nueva sin decir qué problema resuelve y qué se descartó.
- Emanuel es nivel intermedio en Django, y **principiante en frontend, base de datos y seguridad**.
  Explica el porqué de lo que haces en esas áreas, con un ejemplo concreto de este proyecto (una
  clínica con dos sedes, un médico que trabaja en dos clínicas, una receta ya emitida).
- Corrígelo en el momento en que detectes el error, no al final.
- **Respuestas al grano.** Le cuesta leer respuestas largas: poco texto, bien estructurado, sin
  repetir lo ya dicho.
- Al terminar, di en dos líneas qué se puede romper después de este cambio.
