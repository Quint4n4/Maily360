# Cierre de Fase 3 — Agenda de Maily Soft

| Campo | Valor |
|---|---|
| Fase | 3 — Agenda |
| Pasos cubiertos | Paso 3a (Pacientes) · Paso 3b (Personal) · Paso 3c-1 (Agenda nucleo) · Paso 3c-2 (Recordatorios) |
| Periodo | 2026-06-02 al 2026-06-03 |
| Commits | `3d24c07` · `c3317ed` · `13e79ca` · `f385dd8` · `751aa27` · `a9b93f1` · `13a01e1` |
| Tests al cierre | 350 passed |
| Cobertura al cierre | 95.51 % |
| Fecha de reporte | 2026-06-03 |

---

## Resumen ejecutivo

La Fase 3 entrega el MVP funcional de agenda medica de Maily Soft de punta a punta. Una clinica puede hoy registrar pacientes con numeracion consecutiva de expediente por clinica, dar de alta medicos y consultorios, definir horarios de atencion, agendar citas sin empalmes con una maquina de estados estricta, y programar recordatorios por WhatsApp (simulado, listo para conectar Meta cuando haya credenciales).

El trabajo se construyo en cuatro sub-pasos sobre los cimientos del Paso 2. Cada sub-paso siguio el ciclo completo engineer→tester→reviewer→security→docs. En total se corrigieron 2 hallazgos criticos de cimiento (GUC de RLS y resolucion de tenant con JWT), 6 hallazgos altos de seguridad, varios medios y nits. Todos quedaron resueltos antes de cerrar la fase.

Un resultado destacable: las tres reglas anti "puerta trasera de is_active" detectadas en los sub-pasos 3a y 3b se formalizaron en la skill `django-clean-architecture`. El sub-paso 3c-1 (Agenda nucleo) las cumplio desde el primer commit, sin que esos bugs reaparecieran. El equipo de agentes convirtio un hallazgo recurrente en conocimiento codificado y aplicable.

---

## Alcance entregado

### Paso 3a — Pacientes (`3d24c07`)

| Componente | Descripcion |
|---|---|
| `apps/pacientes` | Modelos `Patient` (TenantAwareModel) y `PatientSequence` (numerador atomico de expediente por clinica) |
| Numeracion de expediente | Select-for-update sobre `PatientSequence` garantiza consecutivos unicos por tenant sin colisiones concurrentes |
| API REST | CRUD completo de pacientes con filtros por nombre, CURP, expediente |
| Validaciones | Formato CURP (RENAPO), telefono, `is_active` inmutable en PATCH |
| RLS | Politicas sobre `pacientes_patients` y `pacientes_patient_sequences` |
| Admin | Restringido a `is_platform_staff`; evita exposicion de PII cross-tenant |
| Fix de cimiento A1 (CRITICO) | GUC de RLS configurado con `is_local=false`; antes se borraba entre queries con conexiones reutilizadas; el aislamiento en BD no persistia |
| Fix de cimiento A2 (ARQUITECTONICO) | `TenantAPIView` resuelve tenant a nivel DRF tras autenticacion JWT; el middleware no alcanzaba requests con Bearer token |
| Tests | 58 tests de pacientes; suites de services/selectors al 100 % de cobertura |

### Paso 3b — Personal (`c3317ed`, `13e79ca`)

| Componente | Descripcion |
|---|---|
| `apps/personal` | Modelos `Doctor` (OneToOne a `TenantMembership`), `Consultorio`, `DoctorSchedule` |
| Doctor | Apunta a una `TenantMembership` con `role=doctor` del mismo tenant; perfil clinico independiente por clinica |
| Consultorio | Recurso fisico con nombre unico por tenant y `color_hex` para UI |
| DoctorSchedule | Bloques de horario por dia de semana; `consultorio` opcional (telemedicina) |
| API REST | CRUD para los tres modelos; hereda `TenantAPIView` |
| RLS | Politicas sobre las tres tablas nuevas |
| Fixes de seguridad | `is_active` inmutable en Doctor PATCH (F1); IDOR en DELETE de horario tapado via selector con filtro de tenant (F2); FK de consultorio validada contra tenant del doctor (F3) |
| Indice unico parcial | `UniqueConstraint` sobre `Doctor.membership` con `condition=Q(deleted_at__isnull=True)` — permite dar de alta un nuevo perfil de doctor sobre una membresia cuyo perfil anterior fue soft-deleted (`13e79ca`) |
| Tests | 57 tests de personal; 201 tests totales al cierre del sub-paso; 95.16 % cobertura |

### Paso 3c-1 — Agenda nucleo (`751aa27`)

| Componente | Descripcion |
|---|---|
| `apps/agenda` (modelos base) | `TenantAgendaConfig` (config por clinica), `Appointment` (cita medica) |
| TenantAgendaConfig | Un registro por tenant; almacena duracion default, formato de expediente, offsets de recordatorio en minutos, flag de recordatorios on/off |
| Appointment | Modelo central: paciente + doctor + consultorio (opcional para telemedicina), rango UTC `starts_at`/`ends_at`, motivo, especialidad libre, `series_id` como gancho v2 |
| Maquina de estados | `scheduled → confirmed → arrived → in_progress → attended`; terminales: `cancelled`, `no_show`; transiciones invalidas rechazan con error |
| Anti-empalme doble candado | Validacion en service + `ExclusionConstraint` Postgres (`btree_gist`, `tstzrange`) por doctor y por consultorio; dos capas independientes |
| API REST | CRUD de citas; endpoint dedicado `POST /citas/<id>/estado/` para cambio de estado; `status` inmutable en PATCH |
| RLS | Politicas sobre `agenda_appointments` y `agenda_tenant_config` |
| Fixes de seguridad | `appointment_update` delegado al service (F1); constraints alineadas con `ACTIVE_STATUSES` excluyendo `attended` (F2); `APP_LOG_LEVEL` default a INFO (F5); excepts especificos (F6) |
| Reglas de skill aplicadas desde el inicio | `status` fuera del PATCH, detail via selector, FK validadas por tenant — los tres patrones de la skill se cumplieron sin que el reviewer los tuviera que senalar |
| Tests | 103 tests del nucleo de agenda; maquina de estados parametrizada (10 transiciones validas + 17 invalidas); 313 tests totales; 94.97 % cobertura |

### Paso 3c-2 — Recordatorios (`a9b93f1`, `13a01e1`)

| Componente | Descripcion |
|---|---|
| `AppointmentReminder` | Modelo de recordatorio con ciclo `PENDING → SENT / FAILED / SKIPPED / CANCELLED`; canal, `scheduled_at`, `sent_at`, `message_preview` |
| `adapters/whatsapp.py` | `WhatsAppAdapter` (ABC), `SimulatedWhatsAppAdapter` (dev: no envia, loguea enmascarado), `MetaWhatsAppAdapter` (placeholder para produccion), factory `get_whatsapp_adapter` |
| Tarea Celery | `send_appointment_reminder`: idempotente, verifica estado PENDING y cita activa antes de enviar, `max_retries=3`, formatea fecha en timezone del tenant |
| Integracion con agenda | `appointment_create` programa recordatorios (best-effort); `change_status` a `cancelled`/`no_show` los cancela; reprogramacion reprograma recordatorios |
| RLS | Politica sobre `agenda_appointment_reminders` (migracion `0005`) |
| Fixes de seguridad | N+1 corregido con `prefetch_related` (F1); PII no se loguea en adapter simulado, telefono enmascarado (F2/LFPDPPP); `CELERY_RESULT_EXPIRES=3600` (F3); validacion E.164 antes de enviar, `SKIPPED` si invalido (F4); `cancel_reminders` fuera de atomic en reprogramacion, evita race condition (F5) |
| Tests | Suite dedicada `test_reminders.py` con 1155 lineas; tests E.164 skip (2) y reschedule+rollback (2); 350 tests totales; 95.51 % cobertura |

---

## Flujo de trabajo de agentes y la "leccion que se aplico sola"

La Fase 3 uso el mismo ciclo de cinco agentes establecido en la Fase 1:

1. **django-engineer** implementa el codigo de produccion (modelos, services, selectors, vistas, migraciones).
2. **django-tester** escribe los tests antes de que el reviewer vea el codigo.
3. **django-reviewer** audita contra el Django Styleguide y las convenciones del proyecto. Clasifica hallazgos en bloqueante / recomendado / nit.
4. **django-security** audita con foco en NOM-024 y LFPDPPP. Prioriza fugas entre tenants, PII en logs y control de acceso.
5. **django-docs-reporter** (este agente) documenta lo construido, genera reportes y actualiza el CHANGELOG.

Ningun sub-paso avanza al siguiente hasta que los bloqueantes y altos esten corregidos.

### El patron que se convirtio en conocimiento codificado

En el Paso 3a (Pacientes) el reviewer identifico que `is_active` era modificable via PATCH — una "puerta trasera" que permite activar o desactivar un recurso sin pasar por el flujo de negocio previsto. El mismo patron aparecio en el Paso 3b (Personal) en el modelo Doctor.

En lugar de solo corregir los dos bugs, el commit `f385dd8` agrego tres reglas al archivo `SKILL.md` de `django-clean-architecture`:

1. `is_active` fuera del PATCH (la "puerta trasera de is_active").
2. Detail de un recurso siempre via selector con filtro de tenant (previene IDOR).
3. FK relacionadas validadas contra el tenant del request en el service.

Cuando el engineer implemento el Paso 3c-1 (Agenda nucleo), las tres reglas ya estaban en la skill. El commit `751aa27` registra explicitamente: *"Las 3 reglas de la skill se cumplieron desde el inicio: status fuera del PATCH, detail via selector, FK validadas por tenant."* El reviewer no tuvo que senalar esos bugs porque no aparecieron.

---

## Metricas reales

| Metrica | Valor |
|---|---|
| Commits en la fase | 7 (`3d24c07`, `c3317ed`, `13e79ca`, `f385dd8`, `751aa27`, `a9b93f1`, `13a01e1`) |
| Apps Django nuevas en la fase | 3 (`pacientes`, `personal`, `agenda`) |
| Apps Django totales en el sistema | 6 (`core`, `tenancy`, `authn`, `pacientes`, `personal`, `agenda`) |
| Tests al cierre de la fase | 350 passed |
| Cobertura al cierre de la fase | 95.51 % |
| Archivos insertados en 3a | 28 archivos · 3150 inserciones (con 52 eliminaciones de cimiento) |
| Archivos insertados en 3b | 20 archivos · 4045 inserciones |
| Archivos insertados en 3c-1 | 21 archivos · 5059 inserciones (con 1 eliminacion) |
| Archivos insertados en 3c-2 | 8 archivos · 852 inserciones (con 5 eliminaciones) |
| Archivos del fix de recordatorios | 10 archivos · 1263 inserciones (con 31 eliminaciones) |
| Politicas RLS activadas en la fase | 7 (pacientes x2, personal x3, agenda x2 nucleo + x1 recordatorios) |
| Archivo de skill actualizado | 1 (`django-clean-architecture/SKILL.md`, commit `f385dd8`) |

---

## Hallazgos de seguridad de la fase

El detalle completo por sub-paso esta en [`security-audit-paso-3.md`](security-audit-paso-3.md). El resumen:

| Sub-paso | Criticos | Altos | Medios | Todos corregidos |
|---|---|---|---|---|
| 3a — Pacientes (cimiento) | 1 (GUC RLS) | 1 (TenantAPIView) | 3 | Si, en `3d24c07` |
| 3b — Personal | 0 | 3 | 2 | Si, en `c3317ed` + `13e79ca` |
| 3c-1 — Agenda nucleo | 0 | 2 | 1 | Si, en `751aa27` |
| 3c-2 — Recordatorios | 0 | 2 (LFPDPPP PII) | 2 | Si, en `13a01e1` |

El hallazgo mas significativo fue el **CRITICO del GUC de RLS** en el Paso 3a: el `SET LOCAL` del GUC de Postgres se borraba entre queries en conexiones reutilizadas (`is_local=false` faltaba), lo que dejaba el aislamiento de BD inactivo en la practica aunque el middleware lo alimentara al inicio del request.

---

## Estado del sistema al cierre de la fase

Una clinica conectada a Maily Soft puede hoy realizar el flujo completo de agenda:

1. **Registrar un paciente** con numero de expediente consecutivo unico por clinica, validacion de CURP y telefono.
2. **Dar de alta un medico** vinculado a una membresia del tenant con rol `doctor`, con perfil clinico propio.
3. **Crear consultorios** como recursos fisicos del tenant.
4. **Definir horarios de atencion** por dia de semana para cada medico.
5. **Agendar una cita** con validacion de empalme en dos capas (service + constraints Postgres), doctor y consultorio activos, duracion configurable por clinica y por medico.
6. **Mover la cita por su ciclo de vida**: `scheduled → confirmed → arrived → in_progress → attended`; cancelar o marcar inasistencia en cualquier punto valido.
7. **Recibir recordatorios automaticos** programados via Celery segun la config de la clinica; el adapter de WhatsApp esta listo para conectar Meta cuando haya credenciales.

El sistema corre en Docker Compose local (`make up && make migrate`). Los 350 tests pasan en verde con 95.51 % de cobertura.

---

## Pendientes anotados para fases siguientes

Estos items quedaron identificados pero fuera del alcance de la Fase 3. Se registran para que el equipo los agende:

| Pendiente | Origen | Prioridad sugerida |
|---|---|---|
| `apps/audit` — bitacora de cambios NOM-024 | Mencionado en 3b y 3c-1 como "pendiente" | Alta (requerimiento normativo) |
| Permisos por rol clinico (v2) | Mencionado en 3c-1 | Media |
| Indice `pg_trgm` para busqueda de pacientes por nombre | Diseno pendiente | Media |
| `MetaWhatsAppAdapter` real | Requiere credenciales Meta; interfaz lista | Alta (cuando haya credenciales) |
| Header `X-Tenant-ID` para users multi-clinica | Mencionado en 3b; middleware hoy usa primera membresia | Media |
| Normalizar email a lowercase completo en `UserManager` | INFO-1 del audit de Fase 1 | Baja |
| `AppointmentSeries` (citas recurrentes/paquetes) | Diseno v2 en [`agenda-modelo-datos.md`](../design/agenda-modelo-datos.md) | Baja |
| `message_preview` como dato LFPDPPP | Documentado en `13a01e1`; protegido por RLS, sin accion inmediata | Informativo |

---

## Proximo paso recomendado

**`apps/audit`** — Bitacora de auditoria de cambios en expedientes clinicos.

La NOM-024-SSA3-2010 obliga a registrar quien modifico que en el expediente electronico y cuando. Sin bitacora de auditoria el sistema no puede considerarse conforme a la norma, aunque el resto de la funcionalidad este correcta. Este es el gap normativo de mayor prioridad que quedo fuera de la Fase 3.

El alcance minimo del modulo seria: capturar `CREATE`, `UPDATE` y `DELETE` (incluyendo soft-delete) sobre `Patient`, `Appointment` y en el futuro sobre registros clinicos; almacenar actor, timestamp, tenant, objeto afectado y delta de cambio; garantizar inmutabilidad de la bitacora (sin soft-delete ni update sobre los registros de audit).
