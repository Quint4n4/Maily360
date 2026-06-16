# Plan de diseño — Módulo "Notificaciones"

> Plan acordado con el dueño durante el sprint de **2026-06-15**.
> Estado: **IMPLEMENTADO** (Fases 1–5 completas, 2026-06-15). 34 tests. Backend `apps/notificaciones` + disparadores en `apps/notas` y `apps/agenda`; frontend `web-soft` (campana en Topbar + luz en `App.tsx`).

---

## 1. Objetivo

Avisar a cada usuario de la clínica —en tiempo casi real— de los eventos que le incumben: reuniones que le apliquen, notas de equipo en sus citas, notas dirigidas a su rol, y avisos a toda la clínica. Sin WebSockets: polling cada 30 s es suficiente para el volumen y la UX esperada del MVP.

---

## 2. Decisiones tomadas (locked)

- **D-A · Polling, no WebSockets.** Polling a 30 s desde el frontend. Redis Channels añade complejidad operativa injustificada para clínicas pequeñas. Revisable cuando el volumen lo justifique.
- **D-B · Fan-out on write.** Cuando ocurre el evento, se crea una fila `Notification` por destinatario en ese momento. No hay fan-out on read. Ventaja: el `GET /conteo/` es barato (un `COUNT` indexado).
- **D-C · Best-effort, no transaccional.** Los disparadores van dentro de `try/except` en los services de origen. Un fallo al crear notificaciones nunca tumba la acción principal.
- **D-D · El actor no se notifica a sí mismo.** `notification_fanout` excluye al `actor` del reparto. Implementado y testeado (IDOR + cross-tenant + exclusión del actor).
- **D-E · RLS + filtro en selector = doble barrera.** La migración `0002_enable_rls` activa RLS sobre `notificaciones_notifications`. El selector además filtra por `tenant` y `recipient` (defensa en profundidad). El IDOR al marcar leída también está testeado (`notification_mark_read` verifica que `recipient == request.user`).
- **D-F · Cambio de permisos de notas globales (scope=role).** Antes solo el Dueño podía crear notas de rol. Ahora `ROLE_NOTE_SENDERS` = owner, admin, doctor, nurse, reception. `scope=all` (broadcast) sigue siendo exclusivo del Dueño. Ver [D-19 en DECISIONES-CLAVE.md](../DECISIONES-CLAVE.md).
- **D-G · PII en título de team_note.** El título incluye el nombre del paciente para facilitar la UX. Pendiente de decisión formal (ver pendientes en ESTADO-DEL-PROYECTO.md §9).

---

## 3. Modelo de datos

### App nueva: `apps/notificaciones`

#### `Notification(TenantAwareModel)`

| Campo | Tipo | Notas |
|---|---|---|
| `recipient` | FK User | Dueño de la notificación. Indexado. |
| `actor` | FK User, null | Quien disparó el evento. `SET_NULL` al borrar. |
| `kind` | choices | `meeting` / `team_note` / `role_note` / `broadcast`. |
| `title` | Char(160) | Texto ya armado para mostrar (denormalizado). |
| `body` | Text, opcional | Texto secundario. |
| `target_type` | choices | `appointment` / `agenda_block` / `note` / `""`. |
| `target_id` | UUID, null | UUID del objeto destino para el clic. |
| `read_at` | DateTime, null | Null = no leída. |
| timestamps + soft-delete | | Heredados de `TenantAwareModel`. |

Índices compuestos: `(recipient, read_at)` para el conteo y filtro de no leídas; `(recipient, -created_at)` para la lista ordenada.

---

## 4. API (endpoints)

Todos bajo el prefijo `api/v1/`. Requieren `NotificationPermission` (GET/POST = todos los roles autenticados con membresía activa; la privacidad real la garantiza el selector).

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `notificaciones/` | Lista de notificaciones del usuario (`?only_unread=true` opcional). |
| `GET` | `notificaciones/conteo/` | Entero: notificaciones no leídas del usuario. |
| `POST` | `notificaciones/leidas/` | Marca todas como leídas. |
| `POST` | `notificaciones/<uuid:id>/leida/` | Marca una como leída (idempotente). |

---

## 5. Disparadores y tabla de envío

| Evento de dominio | Service que dispara | `kind` | Destinatarios |
|---|---|---|---|
| `note_create` con `scope=role` | `apps/notas/services.py` | `role_note` | Todos los usuarios del tenant con `target_role`. |
| `note_create` con `scope=all` | `apps/notas/services.py` | `broadcast` | Todos los usuarios del tenant. |
| `agenda_item_note_create` | `apps/agenda/services.py` | `team_note` | Médico de la cita + recepción + autores previos del hilo. |
| `agenda_block_create` con `kind=meeting` | `apps/agenda/services.py` | `meeting` | Depende del alcance: `medico` → ese médico; `consultorio` → sus médicos; `clinica` → staff clínico. Los bloqueos simples no notifican. |

Helpers en `apps/notificaciones/recipients.py`: `users_with_role`, `users_with_roles`, `clinic_staff_users`, `all_tenant_users`, `ROLE_NOTE_SENDERS`, `STAFF_ROLES`.

---

## 6. Frontend

- **`CampanaNotificaciones.tsx`** (Topbar): badge con conteo de no leídas, dropdown con lista, marcar una/todas leídas, navega a `/agenda` o `/notas` según `target_type`. Polling a 30 s.
- **`LuzRecordatorios.tsx`** (`App.tsx`): luz amarilla parpadeante cuando hay recordatorios personales vencidos del día. Snooze de 4 h persistido en `localStorage`.
- Carpetas de soporte: `api/notificaciones.ts`, `hooks/useNotificaciones.ts`, `types/notificaciones.ts`.

---

## 7. Plan por fases

| Fase | Qué incluye | Estado |
|---|---|---|
| **1 · Cimiento backend** | App `apps/notificaciones`, modelo `Notification`, migraciones (datos + RLS), `NotificationPermission`, services, selectors, `recipients.py`, views, urls. | IMPLEMENTADO |
| **2 · Enganches y permisos** | Disparadores en `note_create` / `note_update` (notas); `agenda_item_note_create` (team_note); `agenda_block_create` (meeting). Cambio de permisos: `scope=role` habilitado a `ROLE_NOTE_SENDERS`. | IMPLEMENTADO |
| **3 · Campana** | `CampanaNotificaciones.tsx` + `api/` + `hooks/` (polling 30 s) + `types/`. Badge, dropdown, marcar leídas, navegación. | IMPLEMENTADO |
| **4 · Luz de recordatorios** | `LuzRecordatorios.tsx` montado en `App.tsx`. Luz parpadeante + snooze 4 h en `localStorage`. | IMPLEMENTADO |
| **5 · Revision y docs** | 34 tests (fanout, exclusión actor, IDOR, aislamiento multi-tenant, cross-tenant, los 3 disparadores). Auditoría de seguridad (0 hallazgos CRÍTICO/ALTO). Arreglo de tooling (mypy + `@types/node`). Documentación (D-19, ESTADO-DEL-PROYECTO, este archivo). | IMPLEMENTADO |
| **Futuro** | WebSockets / SSE si el polling deja de ser suficiente. Acuses de recibo de notificaciones. Notificaciones push/email reales (reusando el motor Celery de recordatorios). Decisión formal sobre PII en `team_note`. |  |

---

## 8. Tests

34 pruebas en `apps/notificaciones/tests/`:

- `test_notificaciones.py`: `notification_fanout` (fan-out correcto, exclusión del actor, deduplicación), `notification_mark_read` (idempotente, IDOR cross-user, cross-tenant), `notification_list_for_user` (solo las propias, aislamiento multi-tenant), `notification_unread_count`.
- `test_hooks.py`: disparador `role_note`, disparador `broadcast`, disparador `team_note` (médico + recepción + comentaristas previos), disparador `meeting` (alcance médico, consultorio, clínica). Error en el disparador no tumba la acción principal.

Ejecutar:
```bash
docker compose exec -T backend python -m pytest apps/notificaciones/ -q -o addopts=""
```
