# Plan de diseño — Módulo "Notas y Tareas"

> Plan acordado con el dueño el **2026-06-09**. Guía de implementación por fases.
> Estado: **diseñado, pendiente de implementar** (no se ha escrito código aún).

---

## 1. Objetivo

Un módulo nuevo, **"Notas y Tareas"**, que maneja **tres tipos de notas** dentro de cada clínica (tenant):

| Tipo | Quién la crea | Quién la ve | Notas |
|---|---|---|---|
| **1. Personal** | Cualquier rol | Solo el autor | Privada. Puede ser **tarea** (hecho/pendiente) y tener **recordatorio** opcional. |
| **2. Global (del dueño)** | Solo el Dueño | Un rol específico **o** todos los roles | Aviso/difusión interna. |
| **3. En evento de agenda** | Cualquier rol | Todos | Nota colaborativa pegada a una cita/reunión/bloqueo (la agenda es compartida). |

---

## 2. Decisiones tomadas (locked)

- **D-A · Recordatorios personales → vista personal + widget.** NO se mezclan en el tablero compartido (privacidad + el tablero está organizado por consultorios + el modelo "agenda compartida = lo que ven todos"). En su lugar: una vista personal en el módulo Notas, y un widget **"Mis recordatorios de hoy"** en la barra lateral de la Agenda, **visible solo para el usuario logueado**.
- **D-B · Notas en cita/evento → hilo con autor.** Varias notas por evento de agenda, cada una con autor + fecha (tipo comentarios). NO un solo campo editable (evita que uno borre lo de otro y da historial).
- **D-C · Recordatorios MVP = in-app.** El recordatorio aparece en el panel del usuario (widget + lista). El envío *real* (WhatsApp/email/push) se difiere a una fase futura, reusando el motor de Celery que ya existe para recordatorios de citas.
- **D-D · Notas globales = solo el Dueño** (se puede extender a Admin después si se desea). Destino: **un rol** o **todos**. (Targeting por usuario individual: futuro.)

---

## 3. Modelo de datos

### App nueva: `apps/notas`

#### `Note(TenantAwareModel)` — notas personales y globales
| Campo | Tipo | Notas |
|---|---|---|
| `author` | FK User | Quién la creó. |
| `title` | Char(120), opcional | |
| `body` | Text | Contenido. |
| `scope` | choices: `personal` / `role` / `all` | Audiencia. |
| `target_role` | Char (rol), null | Solo si `scope=role`. |
| `is_task` | bool | Si es tarea (muestra checkbox). |
| `done` | bool | Estado de la tarea. |
| `remind_at` | DateTime, null | Recordatorio opcional → widget de agenda. |
| `pinned` | bool | Fijar arriba (opcional). |
| timestamps | | created_at / updated_at / deleted_at (soft). |

**Visibilidad (la resuelve un selector):**
- `personal` → solo `author`.
- `role` → usuarios del tenant cuyo rol == `target_role` (+ el autor/dueño).
- `all` → todos los usuarios del tenant.

> (Futuro) `NoteRead(note, user, read_at)` para acuses de lectura de notas globales.

#### `AgendaItemNote(TenantAwareModel)` — notas colaborativas de la agenda
| Campo | Tipo | Notas |
|---|---|---|
| `author` | FK User | |
| `appointment` | FK Appointment, null | Una de las dos FKs va seteada… |
| `agenda_block` | FK AgendaBlock, null | …según si es cita o evento. |
| `body` | Text | |
| timestamps | | |

- Visible para **todos** los roles con acceso a la agenda.
- Constraint: exactamente una de (`appointment`, `agenda_block`) no nula.

---

## 4. API (endpoints)

**Notas (personales + globales):**
- `GET /notas/` — mis notas personales + las globales dirigidas a mí. Filtros: `?is_task=`, `?done=`, `?scope=`.
- `POST /notas/` — crear (personal: cualquiera; `role`/`all`: solo Dueño).
- `PATCH /notas/<id>/` — editar (autor; Dueño para las suyas).
- `DELETE /notas/<id>/` — borrar (autor/Dueño).
- `POST /notas/<id>/done/` — alternar hecho/pendiente (tareas personales).
- `GET /notas/recordatorios/?date_from&date_to` — mis recordatorios en un rango (para el widget de agenda).

**Notas de agenda (hilo):**
- `GET /agenda/citas/<id>/notas/` · `POST` — notas de una cita.
- `GET /agenda/eventos/<id>/notas/` · `POST` — notas de un evento.
- `DELETE /agenda/notas/<id>/` — borrar una nota del hilo (autor / Dueño / Admin).

---

## 5. Permisos

- **Note personal:** CRUD solo el autor.
- **Note global (`role`/`all`):** crear/editar/borrar solo el **Dueño**; destinatarios solo lectura.
- **`NotePermission`:** GET autenticado (el selector filtra lo visible); POST permitido a todos para `personal`, restringido a Dueño para `role`/`all` (validado en el service); PATCH/DELETE con check a nivel de objeto (autor/Dueño).
- **AgendaItemNote:** agregar = cualquier rol que pueda ver la agenda (todos menos Finanzas); ver = igual; borrar = autor / Dueño / Admin.

---

## 6. Frontend

- **Navegación:** nuevo ítem **"Notas y Tareas"** en el Topbar.
- **`NotasPage`** con secciones:
  - **Mis notas/tareas** — lista, crear/editar/borrar, marcar hecha, filtro Notas/Tareas, poner recordatorio.
  - **Recibidas** — bandeja de notas globales dirigidas a mí.
  - **Enviar nota global** *(solo Dueño)* — redactar y elegir alcance: un rol o todos.
- **Agenda:** widget **"Mis recordatorios de hoy"** en la barra lateral (privado, solo el usuario).
- **Detalle de cita y de evento:** sección **"Notas del equipo"** — lista (autor + hora + texto) + caja para agregar nota.
- types / api / hooks por dominio (igual que el resto).

---

## 7. Plan por fases

| Fase | Qué incluye |
|---|---|
| **1 · Backend núcleo** | App `apps/notas` + modelo `Note` + capas (selectors/services/serializers/views/urls) + `NotePermission` + migración + **notas/tareas personales** + tests. |
| **2 · Backend globales** | `note_create` acepta `role`/`all` (solo Dueño) + selector entrega las dirigidas a cada quien + auditoría del envío + tests (no-dueño bloqueado, destinatarios correctos, aislamiento). |
| **3 · Frontend panel** | Ítem de nav + `NotasPage` (Mis notas/tareas, Recibidas, Enviar global) + types/api/hooks. |
| **4 · Recordatorios en agenda** | Endpoint de "mis recordatorios" por rango + widget **"Mis recordatorios de hoy"** en la barra lateral + (opcional) badge de pendientes. |
| **5 · Notas colaborativas de agenda** | Modelo `AgendaItemNote` + endpoints + permisos + sección **"Notas del equipo"** en detalle de cita y de evento + tests. |
| **6 · Endurecimiento + entrega** | Trifecta (tester/reviewer/security) + docs (ADR + estado) + commit/push. |
| **Futuro (opcional)** | Recordatorios reales por Celery (WhatsApp/email/push) + acuses de lectura de notas globales + targeting por usuario. |

---

## 8. Auditoría

Nuevos `ActionType`: `NOTE_CREATE`, `NOTE_UPDATE`, `NOTE_DELETE`, `NOTE_GLOBAL_SEND`, `AGENDA_NOTE_ADD`. Se audita especialmente el **envío global** (el Dueño difundiendo) por trazabilidad.
