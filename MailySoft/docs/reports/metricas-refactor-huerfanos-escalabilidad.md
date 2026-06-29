# Reporte de Métricas — Refactor, Código Huérfano y Escalabilidad

> Maily Soft / Maily360 · Generado **2026-06-25** · Análisis estático (no se modificó código).
> Alcance: backend (`backend/`) + frontend (`web-soft/`). Foto de la rama `main` local.

---

## 0. Resumen ejecutivo (TL;DR)

- **Salud general: muy buena.** Arquitectura por capas respetada, tipado disciplinado (0 `any` en frontend, 0 `print()` en backend), multi-tenant con doble barrera (TenantManager + RLS forzado), tests abundantes.
- **Código muerto: poco.** 2 funciones backend confirmadas muertas + 2-3 componentes frontend huérfanos (restos de la migración "doctores → miembros"). Limpieza total ≈ **460 líneas** sin riesgo.
- **Refactor: concentrado en pocos archivos gigantes.** 6 archivos backend > 1.000 líneas y 6 componentes frontend > 700 líneas. Un solo "god-component" real (`CrearEventoModal`, 34 `useState`) y una función de 425 líneas (`prescription_create`).
- **Escalar: la arquitectura aguanta, pero hay 3 cuellos P0 operativos** — PDF síncrono que bloquea workers, búsqueda de pacientes sin índice de texto, y falta de pgbouncer + caché de aplicación (Redis está configurado pero no se usa para cachear).

---

## 1. ¿Cuánto pesa la aplicación?

| Concepto | Peso | Nota |
|---|---|---|
| **Repo completo en disco** | **286 MB** | El 80 % es `node_modules` (no se versiona). |
| `web-soft/node_modules` | 228 MB | Dependencias de desarrollo del frontend. |
| **Código real (lo que importa)** | **~25 MB** | Backend `apps/` 4,1 MB + frontend `src/` 1,3 MB + docs + assets. |
| Historial Git (`.git`) | 12 MB | Sano para 95 commits. |
| **Bundle de producción (frontend)** | **785 KB JS + 45 KB CSS** | Un único chunk. **~203 KB en gzip** (lo que realmente baja el navegador). |
| `media/` y `staticfiles/` backend | 0 B | Vacíos en local (en prod van a S3). |

### Tamaño del código fuente

| | Archivos | Líneas (LOC) |
|---|---|---|
| **Backend — producción** (sin tests ni migraciones) | ~230 `.py` | **~37.600** |
| **Backend — tests** | 102 `.py` | **~47.900** |
| **Frontend** (`src/`, TS + TSX) | 141 (90 `.tsx`) | **~26.050** |
| **Total código fuente** | | **~111.500 LOC** |

> La suite de tests (47.9k LOC) es **más grande que el código de producción** (37.6k): señal de una base bien probada.

### Desglose backend por app (14 apps Django)

| App | LOC prod | Migraciones | Comentario |
|---|---|---|---|
| expediente | ~7.800 | 15 | La más pesada (libro clínico, evoluciones, signos). |
| recetas | ~5.000 | 13 | PDF WeasyPrint, COFEPRIS. |
| agenda | ~4.500 | 10 | Citas, series, bloqueos. |
| pacientes | ~3.000 | 12 | CRUD, etiquetas, filtros. |
| clinica | ~2.900 | 9 | Mi Consultorio, credenciales. |
| finanzas | ~2.500 | 2 | CFDI, cobranza. |
| core | ~2.100 | 0 | Base multi-tenant (modelos abstractos → sin migración, correcto). |
| personal, notas, audit, tenancy, authn, notificaciones, plataforma | resto | — | `plataforma` y `core` sin migraciones (correcto: 1 es lógica pura, 1 es abstracto). |

> **Dato de churn:** `audit` tiene **37 migraciones** — muchísimas para su tamaño. Conviene revisar si hubo idas y vueltas en el esquema; no es un bug, pero es ruido en el historial.

---

## 2. Código huérfano / muerto

### 2.1 Backend — confirmado muerto (0 referencias en todo el repo)

| Archivo:línea | Símbolo | Acción |
|---|---|---|
| `apps/finanzas/selectors.py:139` | `charges_outstanding` | Eliminar o integrar al flujo de pago por antigüedad. |
| `apps/finanzas/selectors.py:214` | `fiscal_config_get_or_none` | Eliminar (la vista usa `fiscal_config_get_or_create`). |

> **Importante:** la búsqueda de "0 referencias" arroja muchos falsos positivos con helpers privados (`_sum`, `_aging_buckets`, `_resolve_ends_at`, etc.) que **sí se usan dentro de su propio archivo**. Esas NO son código muerto. Solo las 2 de arriba están confirmadas.

### 2.2 Frontend — componentes huérfanos (restos de migración "doctores → miembros")

| Componente | Ruta | Reemplazado por |
|---|---|---|
| `NuevoDoctorDrawer` | `src/components/personal/NuevoDoctorDrawer.tsx` | `NuevoMiembroDrawer.tsx` |
| `DoctorDetalleDrawer` | `src/components/personal/DoctorDetalleDrawer.tsx` | `MiembroDetalleDrawer.tsx` |
| `ConfiguracionAgendaModal` | `src/components/personal/ConfiguracionAgendaModal.tsx` | Queda huérfano **en cascada** al borrar `DoctorDetalleDrawer`. |
| `src/data/personal.ts` (mocks) | `DOCTORES`, `CONSULTORIOS_DATA`, `HORARIOS`… | Queda muerto al borrar los drawers de arriba. |

**Limpieza segura ≈ 457 LOC.** Verificar con `npx tsc --noEmit` (hoy compila en verde) después de borrar.

> ⚠️ **No tocar** `src/data/clinicas.ts`: sigue VIVO porque el **panel de plataforma sigue siendo mock** (por diseño, Fase 4 pendiente).

### 2.3 Lo que NO está muerto (verificado)

- **Vistas no enrutadas:** 0. Todas las `views.py` están en sus `urls.py`.
- **Exports muertos** en `api/`, `hooks/`, `lib/`, `types/`: **0**. La capa de datos del frontend está impecable.
- **Imports sin usar (F401):** ninguno evidente (el frontend tiene `noUnusedLocals` activo y compila limpio).

---

## 3. Refactorización (deuda de mantenibilidad)

### 3.1 Backend — archivos y funciones gigantes

| Archivo | LOC | Problema principal |
|---|---|---|
| `apps/agenda/services.py` | ~~1.728~~ → **1.157** | ✅ **HECHO (2026-06-25).** Dividido en `appointment_types.py`, `notes.py`, `series.py`, `reminders.py`, `blocks.py` (re-export desde services; importadores intactos). |
| `apps/expediente/views.py` | ~~1.616~~ → **84** | ✅ **HECHO (2026-06-25).** Dividido por recurso en 7 módulos `views_*` (facade de re-exports; urls.py y tests intactos). Pendiente menor: mover la validación cita↔paciente de la view al service. |
| `apps/expediente/services.py` | 1.537 | `medical_history_upsert` (230 líneas), `evolution_note_create` (222). |
| `apps/recetas/services.py` | 1.141 | **`prescription_create` = 425 líneas** (la función más grande del proyecto). |
| `apps/agenda/views.py` | 1.067 | |
| `apps/core/permissions.py` | 879 | Grande pero **sano** (matriz de roles declarativa, sin duplicación). |

**Funciones > 80 líneas (top):** `prescription_create` (425), `appointment_create` (240), `medical_history_upsert` (230), `evolution_note_create` (222), `appointment_reschedule` (170).

**Duplicación / violaciones de capa:**
- `apps/personal/views.py:125` hace `TenantMembership.objects.get(...)` directo en la view en vez de usar el selector existente `membership_get`. Viola "thin views".
- `prescription_create` repite la validación COFEPRIS que ya hace el serializer (defensa en profundidad intencional, pero infla la función).
- Wrappers superfluos `_validate_doctor_image` / `validate_clinic_image` (1 línea cada uno sobre `core.files.validate_image`).

### 3.2 Frontend — componentes grandes

| Archivo | LOC | `useState` | Diagnóstico |
|---|---|---|---|
| `agenda/CrearEventoModal.tsx` | 736 | **34** | **God-component real.** Wizard + paciente + horarios + recurrencia en una función. → `useReducer`/hook + dividir pasos. |
| `expediente/RecetasTab.tsx` | 1.241 | 20 | Archivo god (bien decompuesto adentro, pero todo en 1 archivo). Mover subcomponentes a archivos propios. |
| `consultorio/SeccionFormatos.tsx` | 812 | 6 | OK estructuralmente; extraer editor + previews. |
| `expediente/EvolucionTab.tsx` | 762 | 13 | Extraer módulo de galería. |
| `expediente/LibroClinico.tsx` | 894 | 6 | Dividir por secciones. |
| `expediente/EvolucionSoapStepper.tsx` | 658 | 9 | Bien decompuesto, bajo riesgo. |

**Duplicación de ALTO impacto (lo más accionable):**
- **Función `erroresDe()` copiada en 9 componentes** (~110 LOC) pese a existir la canónica en `lib/apiErrors.ts`. Consolidar.
- **Constantes de estilo `INPUT`/`LABEL`** (string Tailwind glass) repetidas en ≥4 archivos. → componente `<Field>` o constante compartida.
- Helper `addMin` reimplementa lógica de `lib/fecha.ts` (`combineToISO`).

### 3.3 Salud del código (señales)

| Señal | Backend | Frontend |
|---|---|---|
| `print()` / `console.*` dejados | **0** ✅ | **0** ✅ |
| `any` explícito | n/a | **0** ✅ |
| `# type: ignore` / `@ts-ignore` | **191** ⚠️ | **0** ✅ |
| `except Exception` desnudo | 47 (mayoría con `# noqa` justificado; ~8 sin justificar en expediente) | n/a |
| TODO/FIXME reales | 5 | 1 (en archivo que se borra) |

> Los **191 `# type: ignore`** del backend son la señal más llamativa: indican que la config de mypy con DRF no está bien resuelta (faltaría aprovechar `djangorestframework-stubs` y `from __future__ import annotations`). No son bugs, pero esconden la utilidad del tipado.

---

## 4. Escalabilidad y rendimiento

### 4.1 Lo que está BIEN (no tocar)

- **Aislamiento multi-tenant sólido y falla-segura.** `TenantManager` devuelve `qs.none()` si no hay tenant resuelto; RLS de Postgres con `FORCE ROW LEVEL SECURITY` en todas las apps. `tenant_id` indexado en todos los modelos.
- **Dashboard de finanzas: agregaciones 100 % en SQL** (`Sum`, `Count`, `TruncDate`), cero loops en Python. Ejemplar.
- **Índices compuestos** liderados por `tenant` en agenda y finanzas, calzados a las queries reales.
- **TanStack Query** bien configurado (staleTime 30s, retries inteligentes). Paginación server-side en casi todos los listados.

### 4.2 Riesgos al escalar — priorizados

#### 🔴 P0 — Críticos

| # | Riesgo | Dónde | Recomendación |
|---|---|---|---|
| 1 | ✅ **RESUELTO (2026-06-29).** PDF síncrono que bloqueaba workers. | recetas + libro + cotización + reporte | Movido a **Celery** vía infra genérica `apps.pdfs` (encolar 202 → polling → descarga). Cola default (la dedicada `pdf` queda como optimización). |
| 2 | **Búsqueda de pacientes sin índice de texto.** `icontains` sobre 5 campos → table scan O(n). Con 50k+ pacientes/clínica, cada tecla del buscador escanea la tabla. | `apps/pacientes/selectors.py:99-108` (el propio código tiene un `TODO(perf)` en la línea 100) | Índice **GIN `pg_trgm`** sobre nombre/apellidos/teléfono (con `tenant_id`). |
| 3 | **Sin pgbouncer + workers fijos.** `CONN_MAX_AGE=60` reusa conexiones pero al escalar replicas se puede agotar `max_connections` de Postgres. | `Dockerfile:102`, `base.py:139` | pgbouncer. **Ojo:** el modo *transaction* puede chocar con el GUC `app.current_tenant_id` (nivel sesión) → habría que migrar a `SET LOCAL` o usar *session-mode*. Decisión estructural que toca el núcleo de RLS. |

#### 🟠 P1 — Importantes

| # | Riesgo | Dónde | Recomendación |
|---|---|---|---|
| 4 | **N+1 en el libro clínico:** `obj.credentials.filter()` por médico. | `apps/expediente/serializers.py:1089` | `prefetch_related("doctor__credentials")` en `book_build`. Quick-win. |
| 5 | **Cero caché de aplicación** pese a tener Redis listo. El dashboard de finanzas y catálogos se recalculan en cada request. | `base.py:150` (configurado, nunca usado) | Cachear dashboard + catálogos con invalidación por tenant. |
| 6 | ✅ **HECHO.** Code-splitting aplicado: `React.lazy()` por ruta (13 rutas) + `manualChunks` en Vite. | `web-soft/src/App.tsx`, `vite.config.ts` | — |
| 7 | **Recordatorios con `eta` lejana retenidos en Redis con `allkeys-lru`** → pueden ser **descartados** silenciosamente bajo presión de memoria (recordatorios perdidos). | `apps/agenda/services.py:1251`, `docker-compose.yml:35` | Redis del broker en `noeviction` (separado del cache), o patrón **beat** que escanee recordatorios PENDING por ventana. |

#### 🟡 P2 — A vigilar

- **Sin particionamiento de tablas.** Viable por ahora; planear partición por fecha para `audit` y `agenda_appointments` antes de decenas de millones de filas.
- **Celery con una sola cola**, sin `task_routes`/`rate_limit` (proteger cuota de WhatsApp al crecer).
- **List endpoints sin paginación** (`agenda/views.py:816`, `:707`) y **listas frontend sin virtualización** — sin techo, riesgo bajo hoy.
- **2 round-trips SQL extra por request** (set/clear del GUC de tenant). Costo fijo aceptable.
- **WebSockets scaffolded sin uso** (`config/asgi.py` con `URLRouter([])` vacío). Sin impacto hasta que se implemente.

> **Pendientes de seguridad ya anotados en `ESTADO-DEL-PROYECTO.md`:** actualizar Django 5.2.14→5.2.15 y Pillow 10.4.0→12.2.0; reemplazar `xlsx` (CVE sin parche) por `exceljs`.

---

## 5. Plan de acción sugerido (de menor a mayor esfuerzo)

**Quick wins (1-2 horas, bajo riesgo):**
1. ✅ **HECHO (2026-06-25).** Borrar código muerto frontend: `NuevoDoctorDrawer`, `DoctorDetalleDrawer`, `ConfiguracionAgendaModal`, `data/personal.ts` (−478 LOC). `tsc --noEmit` en verde.
2. ✅ **HECHO (2026-06-25).** Borrar `charges_outstanding` y `fiscal_config_get_or_none` del backend (+ import `ClinicFiscalConfig`).
3. ✅ **HECHO (2026-06-25).** N+1 del libro clínico cerrado: `Prefetch("doctor__credentials", to_attr=...)` en `book_build`/`book_build_all` + serializer lee del cache. 471 tests de expediente en verde (test de cota de queries actualizado 10→11).
4. ✅ **HECHO (2026-06-25).** Índice `pg_trgm` para búsqueda de pacientes: migración `0012` (extensión + 5 índices GIN trgm). EXPLAIN confirma `BitmapOr` sobre los 5 índices. 219 tests de pacientes en verde.

**Esfuerzo medio (medio día c/u):**
5. ✅ **erroresDe HECHO (2026-06-25).** Consolidadas **10** copias de `erroresDe()` en `lib/apiErrors.ts`. −118 LOC. ⏳ **Pendiente:** extraer `<Field>`/`INPUT`/`LABEL` compartido.
6. ✅ **HECHO (2026-06-29).** PDF a Celery para **TODOS** los PDFs vía infra genérica `apps.pdfs`. Ver `docs/design/pdf-async-celery-plan.md`.
7. ⏳ **PENDIENTE.** Activar caché de Redis para dashboard de finanzas y catálogos.
8. ✅ **HECHO.** `React.lazy()` por ruta + `manualChunks` en Vite.

**Estructural (planear como tarea propia):**
9. ✅ **HECHO (2026-06-25).** Dividido `agenda/services.py` (1761→1157, 5 módulos), `expediente/views.py` (1616→84, 7 módulos `views_*`) y `recetas/services.py` (`prescription_create` 425→290, 3 helpers extraídos).
10. 🟡 **PARCIAL (2026-06-25).** `CrearEventoModal`: sacados `Chip`/`ModoPill` del render (anti-patrón). **Pendiente:** los 34 `useState` → `useReducer` — requiere pruebas en navegador (sin tests del modal).
11. Decidir pgbouncer + compatibilidad con el GUC de RLS.
12. Resolver la config de mypy/DRF para reducir los 191 `# type: ignore`.

---

*Fin del reporte. Generado por análisis estático de la rama `main` local el 2026-06-25.*
