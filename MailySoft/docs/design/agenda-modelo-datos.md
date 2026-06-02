# Documento de Diseño: Módulo de Agenda — Maily Soft

> Estado: **borrador para aprobación** · Fase: Paso 3 · Autor: Plan agent · 2026-06-02
> Pendiente: resolver las "Preguntas abiertas" (sección 9) antes de codear.

## 1. Resumen y Alcance

### Qué entra en v1 (MVP)

| Entidad | App | Estado |
|---|---|---|
| `Patient` | `pacientes` | v1 |
| `PatientSequence` (helper anti-colisión) | `pacientes` | v1 |
| `Doctor` (perfil profesional) | `personal` | v1 |
| `Consultorio` | `personal` | v1 |
| `DoctorSchedule` | `personal` | v1 |
| `Appointment` | `agenda` | v1 |
| `AppointmentReminder` | `agenda` | v1 |

### Qué queda para v2
- `AppointmentSeries` (sesiones recurrentes / paquetes terapéuticos)
- `Specialty` como entidad de catálogo propia (hoy es un CharField libre)
- `WaitingList` (lista de espera)
- Módulo MPI (Master Patient Index) global para deduplicación cross-tenant por CURP
- `TenantAgendaConfig` de agenda: duración default, recordatorios automáticos, slots

---

## 2. Diagrama de Entidades

```
PLATAFORMA (BaseModel)
  Tenant (clínica) ──1:* ── TenantMembership (user, tenant, role)
                                      │ user FK
NEGOCIO (TenantAwareModel: id UUID, timestamps, soft-delete, tenant FK, created_by)
                                      ▼
                                    User (authn)
                                      │ user (OneToOne vía membership)
                                Doctor (membership FK, cedula, especialidad,
                                        duracion_default_cita, activo)
                                      │
        Consultorio (nombre, ubicacion, color, activo)
        DoctorSchedule (doctor FK, dia_semana, hora_inicio, hora_fin, consultorio FK?)
        Patient (nombre, apellidos, fecha_nac, sexo, CURP?, telefono, email, num_expediente)
                                      │
                                Appointment (patient FK, doctor FK, consultorio FK,
                                  starts_at UTC, ends_at UTC, estado, motivo, notas,
                                  especialidad CharField, cancelled_by?, cancellation_reason,
                                  series_id UUID? [gancho v2])
                                      │
                                AppointmentReminder (appointment FK, canal,
                                  scheduled_at, sent_at, estado, message_preview)
        PatientSequence (tenant FK unique, last_number int)
```

---

## 3. Entidades — campos clave

### 3.1 `pacientes_patients` (hereda TenantAwareModel)
`first_name`, `paternal_surname`, `maternal_surname` (blank), `date_of_birth`, `sex` (M/F/X NOM-024), `curp` (nullable, anti-duplicados futuro), `phone` (WhatsApp), `email` (opcional), `record_number` (consecutivo por clínica, único por tenant), `notes`, `is_active`.
Constraint: `UNIQUE (tenant_id, record_number)`.

### 3.2 `pacientes_patient_sequences` (hereda TenantAwareModel)
`last_number` (PositiveInteger). Un registro por tenant. Mecanismo de consecutivo seguro (ver 5.1).

### 3.3 `personal_doctors` (hereda TenantAwareModel)
`membership` (OneToOne a TenantMembership), `cedula_profesional` (blank), `specialty` (CharField, catálogo en v2), `default_appointment_duration` (min, default 30), `bio_short`, `is_active`.
`full_name` se deriva de `membership.user.full_name` (no se almacena).

### 3.4 `personal_consultorios` (hereda TenantAwareModel)
`name`, `location`, `color_hex` (calendario UI), `is_active`. Constraint: `UNIQUE (tenant_id, name)`.

### 3.5 `personal_doctor_schedules` (hereda TenantAwareModel)
`doctor` FK, `day_of_week` (0=Lun..6=Dom), `start_time`/`end_time` (TimeField, hora local), `consultorio` FK (nullable), `valid_from`/`valid_until` (nullable), `is_active`.
"L-V 9-14 y 16-19" = 10 filas (5 días × 2 bloques).

### 3.6 `agenda_appointments` (hereda TenantAwareModel) — modelo central
`patient` FK (PROTECT), `doctor` FK (PROTECT), `consultorio` FK (PROTECT), `starts_at` (UTC, index), `ends_at` (UTC), `status` (index), `reason` (requerido), `specialty` (CharField libre), `notes`, `cancelled_by` FK (SET_NULL), `cancellation_reason`, `no_show_registered_by` FK (SET_NULL), `series_id` (UUID nullable — gancho v2).

### 3.7 `agenda_appointment_reminders` (hereda TenantAwareModel)
`appointment` FK, `channel` (whatsapp/sms/email), `scheduled_at` (UTC), `sent_at` (UTC nullable), `status` (pending/sent/failed/skipped), `message_preview`, `error_detail`, `external_message_id`.

---

## 4. Máquina de Estados de Appointment

```
AGENDADA ──► CONFIRMADA ──► EN_SALA ──► EN_CONSULTA ──► ATENDIDA (terminal)
   │             │             │
   ├──► CANCELADA (terminal desde cualquier estado no-terminal)
   └──► NO_SHOW   (terminal)
```

Valores: `scheduled`, `confirmed`, `arrived`, `in_progress`, `attended`, `cancelled`, `no_show`.

| Origen | Destinos válidos | Quién |
|---|---|---|
| agendada | confirmada, cancelada, no_show | reception/admin/owner/doctor |
| confirmada | en_sala, cancelada, no_show | reception/admin/owner |
| en_sala | en_consulta, cancelada, no_show | reception/doctor/nurse |
| en_consulta | atendida | doctor/nurse |
| atendida / cancelada / no_show | — (terminal) | — |

Reagendar = crear una cita nueva (no se reabre la cancelada). Historial limpio.

---

## 5. Decisiones de diseño razonadas

### 5.1 Número de expediente consecutivo por clínica
Tabla `PatientSequence` (1 fila por tenant) + `SELECT ... FOR UPDATE` dentro de transacción. El bloqueo pesimista evita que dos inserciones simultáneas tomen el mismo número. Rechazado `MAX()+1` (race condition) y `django-sequences` (dependencia extra). Formato sugerido `EXP-{año}-{n:05d}` — a confirmar por el dueño.

### 5.2 Doctor: entidad separada que apunta a TenantMembership (OneToOne)
Recomendado sobre "solo membership" (no hay dónde guardar cédula/especialidad/duración) o "proxy de User" (problemático con multi-tenant). Ventaja: un médico en 2 clínicas tiene perfil distinto en cada una. Acceso al user: `doctor.membership.user`. El service valida que `membership.role == "doctor"`.

### 5.3 Zona horaria
Todo en **UTC** en BD (`USE_TZ=True`). `Tenant.timezone` (ya existe) para presentación. `DoctorSchedule` guarda hora local; el service la convierte a UTC al comparar disponibilidad (sobrevive cambios de horario de verano). Recordatorios Celery: `scheduled_at` en UTC.

### 5.6 Integración Maily te cuida (paciente)
El modelo lo soporta sin cambios: filtrar `Appointment` por `patient_id`. Falta (v2): auth del paciente (OTP), endpoint público, y posible flag `is_visible_to_patient`. No se cierra ninguna puerta.

---

## 6. Anti-empalme (double booking) — doble barrera

**Capa 1 (service):** antes de crear/mover cita, verificar solapamiento de doctor Y de consultorio con citas en estados activos (`starts_at__lt=ends_at, ends_at__gt=starts_at`). Devuelve `AppointmentConflictError` legible.

**Capa 2 (PostgreSQL exclusion constraint, defensa en profundidad):**
```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE agenda_appointments ADD CONSTRAINT appointment_no_overlap_doctor
EXCLUDE USING gist (
  doctor_id WITH =, tenant_id WITH =,
  tstzrange(starts_at, ends_at, '[)') WITH &&
) WHERE (deleted_at IS NULL AND status NOT IN ('cancelled','no_show'));
-- idéntico para consultorio_id
```
Incluye `tenant_id` para no bloquear médicos que trabajan en 2 clínicas. Rango `[)` permite citas consecutivas (10-11 y 11-12 no chocan). Solo aplica a citas vivas. En concurrencia, el 2º INSERT falla con IntegrityError → el service lo convierte en error de dominio.

---

## 7. Índices y RLS

### Índices calientes
- `appointments (tenant_id, doctor_id, starts_at, ends_at)` — calendario del médico
- `appointments (tenant_id, consultorio_id, starts_at, ends_at)` — calendario del consultorio
- `appointments (tenant_id, patient_id, starts_at DESC)` — historial del paciente
- `appointments (tenant_id, status, starts_at)` — sala de espera
- `patients (tenant_id, paternal_surname, maternal_surname)` — búsqueda recepción
- `patients (tenant_id, curp) UNIQUE WHERE curp != ''` — anti-duplicados
- `reminders (scheduled_at, status) WHERE status='pending'` — worker

### RLS (cada tabla tenant-aware nueva)
```sql
ALTER TABLE <tabla> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <tabla> FORCE ROW LEVEL SECURITY;
CREATE POLICY <tabla>_tenant_isolation ON <tabla>
USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
```
El `OR ... IS NULL` permite Celery/migraciones sin contexto. Aplica a: patients, patient_sequences, doctors, consultorios, doctor_schedules, appointments, appointment_reminders.

---

## 8. Ganchos para v2
- **Series:** `series_id` (UUID nullable) ya en Appointment; v1 todas NULL. v2 crea tabla `AppointmentSeries` sin migrar datos.
- **Especialidades:** hoy CharField; v2 → FK a tabla `Specialty`.
- **Casos multidisciplinarios:** futura tabla `AppointmentParticipant` o M2M `additional_doctors`.
- **Lista de espera:** futura `WaitingListEntry`.

---

## 9. Decisiones del dueño (RESUELTAS 2026-06-02)

| # | Pregunta | DECISIÓN |
|---|---|---|
| 1 | Formato del número de expediente | **Configurable por clínica** → en `TenantAgendaConfig.record_number_format` (default `EXP-{year}-{seq:05d}`) |
| 2 | ¿Consultorio obligatorio? | **Opcional** → `Appointment.consultorio` es `null=True`; el exclusion constraint de consultorio solo aplica cuando NO es null |
| 3 | ¿Cuántos recordatorios WhatsApp? | **Configurable por clínica** → en `TenantAgendaConfig.reminder_offsets` (default `[24h]`; permite p.ej. `[24h, 2h]`) |
| 4 | Duración de la cita | **Ambas** → `TenantAgendaConfig.default_appointment_duration` (clínica) + `Doctor.default_appointment_duration` (override por médico) |

### Implicación: nueva entidad `TenantAgendaConfig` (entra a v1)

**Tabla:** `agenda_tenant_config` · hereda de `TenantAwareModel` · **un registro por tenant**, creado con defaults al dar de alta la clínica.

| Campo | Tipo | Default | Descripción |
|---|---|---|---|
| `record_number_format` | `CharField(max_length=50)` | `"EXP-{year}-{seq:05d}"` | Plantilla del número de expediente. Placeholders: `{year}`, `{seq}` |
| `record_number_reset_yearly` | `BooleanField` | `False` | Si el consecutivo se reinicia cada año |
| `default_appointment_duration` | `PositiveSmallIntegerField` | `30` | Duración default de cita (min) a nivel clínica |
| `reminder_offsets_minutes` | `JSONField` (lista de int) | `[1440]` | Minutos antes de la cita para cada recordatorio. `[1440]`=24h; `[1440, 120]`=24h y 2h |
| `reminders_enabled` | `BooleanField` | `True` | Interruptor global de recordatorios de la clínica |

**Resolución de duración (orden de precedencia):** cita → `Doctor.default_appointment_duration` → `TenantAgendaConfig.default_appointment_duration` → 30.
**Resolución de recordatorios:** si `reminders_enabled`, se programa un `AppointmentReminder` por cada offset en `reminder_offsets_minutes`.

### Preguntas abiertas restantes (decidir más adelante, NO bloquean v1)
| # | Pregunta | Cuándo |
|---|---|---|
| 5 | ¿Paciente con múltiples teléfonos? (`PatientContact`) | v2 si se necesita |
| 6 | ¿`no_show` reversible? | default NO; revisitar con feedback de clínicas |
| 7 | ¿Bloqueos de agenda del doctor (vacaciones/junta)? | v2 (`DoctorBlock`) |
| 8 | ¿Citas de seguimiento heredan motivo? | v2 con series |

---

## Resumen de decisiones clave
1. `Doctor` apunta a `TenantMembership` (OneToOne) — perfil clínico por clínica.
2. `PatientSequence` + `SELECT FOR UPDATE` — consecutivos sin colisión.
3. Anti-empalme doble: service + exclusion constraint Postgres (incluye tenant_id).
4. UTC en BD; `DoctorSchedule` en hora local; conversión en service.
5. `series_id` nullable como único gancho v2 de series.
6. RLS `USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)`.
