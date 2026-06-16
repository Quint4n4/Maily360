# Multi-citas recurrentes + disponibilidad en vivo

> Implementado durante el sprint de **2026-06-16**.
> Estado: **IMPLEMENTADO** (backend + frontend, compila y pasa pruebas). 20 tests en `test_appointment_series.py`.
> Backend: `apps/agenda` (service `appointment_create_series`, selector `agenda_busy_intervals`, endpoints `/agenda/citas/serie/` y `/agenda/disponibilidad/`).
> Frontend: `web-soft` (modal `CrearEventoModal`, componente `MiniCalendario`, hook `useAgendaDisponibilidad`).

---

## 1. Objetivo

Permitir agendar **varias citas del mismo paciente de una sola vez** (una serie recurrente) y, al hacerlo, **mostrar en los mini-calendarios qué días/horarios ya están ocupados** para poder **mover cada cita a un hueco libre sin salir del modal ni reagendar todo después**.

Dos problemas que resuelve:

1. **Agendar en lote.** Antes había que crear cita por cita. Ahora se define una regla (Semanal / Quincenal / Mensual) o se eligen fechas a mano (Personalizado) y se crean todas juntas.
2. **Evitar choques a ciegas.** Antes no sabías si el médico ya tenía algo a esa hora hasta que el backend rechazaba la cita. Ahora los horarios ocupados se ven en **rojo** y puedes elegir uno libre ahí mismo.

---

## 2. Decisiones tomadas (locked)

- **D-A · Best-effort por cita, no "todo o nada".** Cada cita de la serie se crea en su propio savepoint atómico. Si una choca (médico/consultorio/bloqueo ocupado), se **omite** y las demás siguen. La respuesta devuelve `created` (creadas) y `skipped` (omitidas con su motivo). Excepción: si se crea un paciente nuevo junto con la serie y **ninguna** cita se pudo crear, se hace rollback para no dejar un paciente huérfano.
- **D-B · Dos modos de armar la serie.**
  - **Regla** (`frequency` + tope): `weekly` / `biweekly` / `monthly`, acotada por `count` (N citas) **XOR** `until` (fecha límite).
  - **Lista explícita** (`explicit_starts`): el frontend manda las fechas+horas exactas ya editadas por el usuario. Este es el modo que usa la UI hoy (incluso para las reglas: genera las fechas, deja editarlas y manda la lista final).
- **D-C · Tope duro de 52 citas por serie** (`_SERIES_MAX_OCCURRENCES`). Protege contra series infinitas.
- **D-D · Disponibilidad = solo lectura, sin reservar.** El endpoint `/agenda/disponibilidad/` devuelve intervalos ocupados; **no** bloquea ni aparta horarios. La verdad final la sigue imponiendo el anti-solape del `appointment_create` (constraint de exclusión en Postgres + chequeo en el service). La disponibilidad es una **ayuda visual**, no la autoridad.
- **D-E · `series_id` agrupa las citas.** Todas las citas de una serie comparten el mismo `Appointment.series_id` (UUID). Gancho para, en el futuro, editar/cancelar "toda la serie".
- **D-F · Disponibilidad por médico (+ consultorio si aplica).** Se consultan las citas activas del médico y los eventos (reuniones/bloqueos) de ese médico, de ese consultorio o de toda la clínica. En telemedicina/fuera de consultorio el `consultorio_id` va nulo.

---

## 3. Backend

### 3.1 Modelo

`Appointment.series_id = UUIDField(null=True, blank=True, db_index=True)` — nulo en citas sueltas; igual para todas las citas de una misma serie.

### 3.2 Service — crear la serie

`appointment_create_series(*, tenant, user, starts_at, ends_at, doctor_id, frequency=None, explicit_starts=None, patient_id=None, new_patient=None, count=None, until=None, consultorio_id=None, appointment_type_id=None, modality=OFFICE, reason="", specialty="", notes="") -> dict`

- Valida `patient_id` **XOR** `new_patient`.
- `duracion = ends_at - starts_at` (se respeta en cada cita).
- Si llega `explicit_starts` → usa esa lista (ordenada, sin duplicados, 2–52 citas).
- Si no, con `frequency` genera las fechas (`_generate_series_starts` + helpers `_series_step` / `_add_one_month`).
- Dentro de `transaction.atomic()`: resuelve el paciente (si es nuevo, `patient_create_quick`) y **recorre cada fecha** llamando a `appointment_create(..., series_id=series_id)` en `try/except ValidationError`, acumulando `created` / `skipped`.
- Devuelve `{"series_id", "created": [...], "skipped": [...]}`.

### 3.3 Selector — disponibilidad

`agenda_busy_intervals(*, doctor_id, consultorio_id, date_from, date_to) -> list[dict]`

Devuelve `[{"start": datetime, "end": datetime}, ...]` con:
- Citas **activas** del médico (`status__in=ACTIVE_STATUSES`) que solapan el rango — las canceladas/no-show **no** cuentan.
- Eventos de agenda aplicables: del médico, del consultorio (si se da), o de toda la clínica (`doctor` y `consultorio` nulos).

Solo lectura; el `TenantManager` filtra por el tenant activo.

### 3.4 Endpoints (`api/v1/`)

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/agenda/citas/serie/` | Crea la serie. Responde `{series_id, created_count, created[], skipped_count, skipped[]}`. |
| `GET`  | `/agenda/disponibilidad/` | Query: `doctor_id` (req), `consultorio_id` (opc), `date_from`, `date_to`. Responde `{busy: [{start, end}]}`. |

Permiso: `AppointmentPermission` (mismos roles que pueden agendar).

### 3.5 Tests

`apps/agenda/tests/test_appointment_series.py` — **20 tests**. Cubren la generación de fechas por frecuencia, tope `count`/`until`, modo explícito, paciente nuevo + rollback, omisión de citas que chocan, y la disponibilidad:
- `test_incluye_cita_activa`, `test_excluye_cancelada`, `test_incluye_bloqueo_de_clinica`, `test_api_disponibilidad`.

---

## 4. Frontend (`web-soft`)

### 4.1 Tipos (`types/agenda.ts`)
- `SeriesFrequency = 'weekly' | 'biweekly' | 'monthly' | 'custom'`.
- `CreateAppointmentSeriesInput` (extiende la cita con `frequency` / `count` / `until` / `explicit_starts`).
- `AppointmentSeriesResult` (`created` / `skipped`).
- `BusyInterval { start, end }` y `AgendaDisponibilidad { busy: BusyInterval[] }`.

### 4.2 API + hooks
- `api/agenda.ts`: `createAppointmentSeries()`, `getAgendaDisponibilidad()`.
- `hooks/agenda.ts`: `useCreateAppointmentSeries()`, `useAgendaDisponibilidad({doctorId, consultorioId, from, to, enabled})` (TanStack Query, `staleTime: 30s`, sólo corre con médico + rango).

### 4.3 `MiniCalendario.tsx`
Mini-calendario mensual reutilizable. Props: `value`, `onPick`, `onRemove` (× para quitar), `min` (día mínimo), `accent: 'gold' | 'green' | 'red'`, `footer`. El acento `red` (`#C0392B`) marca el día ocupado.

### 4.4 `CrearEventoModal.tsx` — la experiencia final
Asistente de 2 pasos. Al activar **"Repetir esta cita"** aparece **una sola lista unificada de tarjetas** (estado `ocurrencias: {date, time}[]`):

1. **Cada cuánto**: pastillas Semanal / Quincenal / Mensual / **Personalizado**.
2. Si es regla, **¿Hasta cuándo?**: `N veces` o `Hasta una fecha`. Un `useEffect` regenera las ocurrencias con `seriesDates()` (espejo del backend, máx. 52, mensual vía `addOneMonth`).
3. **Cada tarjeta** es un `MiniCalendario` con:
   - El **día** (se mueve tocando otro día del calendario).
   - Un **selector de horarios** (9:00–17:30, cada 30 min) en el footer:
     - 🔴 **Ocupado** → fondo `#FDE8E8`, texto `#C0392B`, tachado y deshabilitado.
     - 🟡 **Seleccionado** → dorado `#C9A227`.
     - ⚪ **Libre** → blanco, clicable → mueve la cita a ese hueco.
   - Si el día choca completo a la hora elegida, el calendario entero usa `accent="red"`.
   - **×** para quitar la cita (si quedan más de 2).
   - En **Personalizado**, botón punteado **"+ Agregar cita"**.
4. Al guardar: arma `explicit_starts` con todas las ocurrencias y llama a `createAppointmentSeries`. El resultado muestra cuántas se crearon y cuántas se omitieron.

La disponibilidad se consulta en vivo (`useAgendaDisponibilidad`) sobre el rango de las ocurrencias; `ocupadoEn(date, time)` cruza cada slot contra los `busy` para decidir el color.

---

## 5. Pendientes / ideas a futuro

- **Editar/cancelar "toda la serie"** aprovechando `series_id` (hoy se edita cita por cita).
- **Slots configurables**: el rango 9:00–17:30 está fijo en el front; podría venir del horario del médico/clínica.
- **Disponibilidad por consultorio en telemedicina**: hoy se omite el consultorio cuando la modalidad no es presencial (correcto), pero podría considerarse el recurso "sala virtual" si se modela.
- **Mostrar el motivo de cada omisión** en el resumen final de forma más visual (hoy llega en `skipped[].error`).
