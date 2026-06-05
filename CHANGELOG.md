# Changelog

Todos los cambios notables de Maily Platform se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

---

## [Unreleased]

### Added (Fase 4 — Bitácora de auditoría NOM-024) · commit `50d33dc`

- `apps/audit`: modelo `AuditLog` append-only tenant-aware (tenant nullable para eventos globales como login fallido); campos actor, rol snapshot, acción, recurso (referencia débil), ip, user_agent, request_id, metadata.
- Helper `audit_record(...)` que NUNCA propaga excepciones al caller (la auditoría no tumba la operación de negocio).
- Contexto de request (ip/user_agent/request_id) por thread-local, poblado en `TenantAPIView.check_permissions` y limpiado en el `finally` del middleware.
- 18 puntos de integración: services de pacientes/personal/agenda + `PATIENT_READ` en la view + `LOGIN` (`MailyTokenObtainPairView`) + `LOGIN_FAILED` (señal `user_login_failed`).
- Endpoint `GET /api/v1/audit/logs/` (paginado, filtros) solo para owner/admin (`AuditLogPermission`).
- Inmutabilidad doble barrera: override `save()`/`delete()` + `AuditLogQuerySet` que bloquea `update()`/`delete()` masivos + RLS append-only en Postgres (migraciones `0002`, `0003`).
- Decisiones del dueño: retención 10 años, auditar solo el detalle del expediente (no listas), login fallido registrado, ver bitácora solo owner/admin.

### Added (Fase 4 — Endpoint /me/) · commit `128e283`

- `GET /api/v1/me/`: devuelve identidad del usuario + `is_platform_staff` + `active_tenant` + `active_role` + lista de membresías activas. El frontend lo usa tras el login para decidir el panel según el rol. `MeApi` hereda de `APIView` (no `TenantAPIView`) para funcionar sin tenant activo.

### Added (Fase 4 — Permisos por rol clínico) · commit `ffd8c85`

- `apps/core/permissions.py`: `HasClinicRole` (base sensible al método HTTP) + 5 políticas declarativas (`PatientPermission`, `PersonalPermission`, `AppointmentPermission`, `AppointmentStatusPermission`, `AgendaConfigPermission`).
- Aplicado a los 14 endpoints de pacientes/personal/agenda según la matriz aprobada. Denegación por rol → 403; recurso de otro tenant → 404 (aislamiento).
- `TenantAPIView` resuelve el rol del servidor (`resolve_membership_for_user`) y lo expone en `request.active_role` antes de evaluar permisos.
- 159 tests de matriz (rol × endpoint × método).

### Changed (Fase 4)

- `TenantAPIView` sobreescribe `check_permissions()` en vez de reescribir `initial()` (preserva content-negotiation/versioning/renderers de DRF).
- `resolve_membership_for_user`: tenants en estado `trial` tienen acceso (modelo de prueba gratis); `suspended` queda bloqueado.
- Login (`/auth/login/`) usa view custom `MailyTokenObtainPairView` que registra el evento en la bitácora.

### Fixed (Fase 4)

- OPTIONS/HEAD no se bloquean por rol (el preflight CORS del frontend ya no da 403).
- Política RLS SELECT de la bitácora ya no expone eventos `tenant=NULL` (login fallido) a otros tenants — fuga cross-tenant/PII corregida.
- `resource_repr` de pacientes usa número de expediente, no el nombre (minimización LFPDPPP); email de login fallido se guarda hasheado (`email_hint`).
- Login sin doble `authenticate()` (evita `LOGIN_FAILED` espurio); señal limpia el request context en `finally`.
- Bitácora: `save()` usa `_state.adding` (sin SELECT extra); paginación con `max_page_size` (anti-DoS).

### Added (Paso 3c-2 — Recordatorios WhatsApp) · commits `a9b93f1`, `13a01e1`

- `apps/agenda`: modelo `AppointmentReminder` con ciclo `PENDING → SENT / FAILED / SKIPPED / CANCELLED`; canal, `scheduled_at`, `sent_at`, `message_preview`, `external_message_id`.
- `adapters/whatsapp.py`: interfaz abstracta `WhatsAppAdapter` (ABC), `SimulatedWhatsAppAdapter` para desarrollo (no envia real, loguea con telefono enmascarado), `MetaWhatsAppAdapter` como placeholder para produccion, factory `get_whatsapp_adapter`.
- Tarea Celery `send_appointment_reminder`: idempotente, verifica estado `PENDING` y cita activa antes de enviar, `max_retries=3`, formatea fecha en timezone del tenant.
- Services `schedule_reminders_for_appointment` y `cancel_reminders_for_appointment`: leen `config.reminder_offsets_minutes`, omiten offsets en el pasado, evitan duplicados, encolan con `eta`.
- Integracion con agenda: `appointment_create` programa recordatorios (best-effort); `change_status` a `cancelled`/`no_show` los cancela; reprogramacion los reprograma.
- Selector `reminder_list_for_appointment`; `AppointmentReminderOutputSerializer` anidado en `AppointmentOutputSerializer`.
- Migracion `0005`: RLS sobre `agenda_appointment_reminders`.
- Variables de entorno nuevas: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `CELERY_RESULT_EXPIRES` (documentadas en `.env.example`).

---

### Added (Paso 3c-1 — Agenda nucleo) · commit `751aa27`

- `apps/agenda`: modelos `TenantAgendaConfig` (config de agenda por clinica: duracion default, formato expediente, offsets de recordatorio, flag on/off) y `Appointment` (modelo central de citas medicas).
- Maquina de estados en `Appointment`: `scheduled → confirmed → arrived → in_progress → attended`; terminales `cancelled` y `no_show`; transiciones invalidas rechazan con error.
- Anti-empalme de doble candado: validacion en service + `ExclusionConstraint` Postgres (`btree_gist`, `tstzrange`) por doctor y por consultorio.
- API REST completa: CRUD de citas; endpoint dedicado `POST /citas/<id>/estado/` para cambio de estado; `status` inmutable en PATCH.
- Admin restringido a `is_platform_staff`.
- Migraciones `0001` (tablas), `0002` (RLS + constraints), `0003` (correccion de constraints para excluir `attended` de `ACTIVE_STATUSES`).

---

### Added (Paso 3b — Personal) · commits `c3317ed`, `13e79ca`

- `apps/personal`: modelos `Doctor` (OneToOne a `TenantMembership` con `role=doctor`), `Consultorio` (recurso fisico con nombre unico por tenant), `DoctorSchedule` (bloques de horario por dia de semana).
- API REST completa para los tres modelos; hereda `TenantAPIView`.
- Migraciones `0001` (tablas), `0002` (RLS), `0003` (indice unico parcial en `Doctor.membership` con condicion `deleted_at__isnull=True`).
- Admin restringido a `is_platform_staff`.

---

### Added (Paso 3a — Pacientes) · commit `3d24c07`

- `apps/pacientes`: modelos `Patient` (TenantAwareModel) y `PatientSequence` (numerador atomico de expediente consecutivo por clinica con `select_for_update`).
- API REST CRUD de pacientes con filtros por nombre, CURP y numero de expediente.
- Validaciones: formato CURP (patron RENAPO), telefono, `is_active` inmutable en PATCH.
- Migraciones `0001`–`0004` (tablas, RLS, constraint unicidad, ajuste de `record_number`).
- Admin restringido a `is_platform_staff`; evita exposicion de PII cross-tenant.

---

### Changed (Paso 3a — Endurecer cimiento multi-tenant) · commit `3d24c07`

- `apps/core/middleware.py` + `TenantAPIView`: GUC de RLS configurado con `is_local=false` (`SET SESSION`); antes se borraba entre queries con conexiones reutilizadas. El RLS de Postgres ahora es efectivo durante toda la vida de la conexion.
- Introducido `TenantAPIView` como clase base de todos los views DRF: resuelve tenant en `initial()` despues de la autenticacion JWT; el middleware anterior no alcanzaba requests con Bearer token.
- `resolve_tenant_for_user()` centraliza la logica de resolucion de tenant (sin duplicar entre middleware y view).

---

### Changed (Skill endurecida — anti "puerta trasera") · commit `f385dd8`

- `django-clean-architecture/SKILL.md`: tres reglas anti-bug formalizadas tras los hallazgos de Pasos 3a y 3b: (1) `is_active` fuera del PATCH siempre; (2) detail de un recurso via selector con filtro de tenant (previene IDOR); (3) FK relacionadas validadas contra el tenant del request en el service. Resultado: las tres reglas se cumplieron desde el inicio en el Paso 3c-1.

---

### Fixed (Paso 3b — Seguridad personal) · commits `c3317ed`, `13e79ca`

- IDOR en DELETE de `DoctorSchedule`: el endpoint recuperaba el horario por PK sin filtrar por tenant; ahora delega al selector `schedule_get` con filtro de tenant.
- FK de `Consultorio` en `DoctorSchedule` no validada contra tenant del doctor; el service ahora verifica `consultorio.tenant_id == tenant.id`.
- `UniqueConstraint` parcial en `Doctor.membership` con condicion `deleted_at__isnull=True`; permite recrear perfil de doctor tras soft-delete.

---

### Fixed (Paso 3c-2 — Seguridad recordatorios) · commit `13a01e1`

- N+1 en `appointment_get` y `appointment_list`: agregado `prefetch_related('reminders')`.
- PII en logs del adapter simulado: telefono enmascarado (solo ultimos 4 digitos visible); `message_preview` documentado como dato LFPDPPP protegido por RLS.
- `CELERY_RESULT_EXPIRES=3600`: evita acumulacion indefinida de resultados de tareas (minimizacion de datos, LFPDPPP).
- Validacion E.164 antes de intentar envio; tarea termina con `SKIPPED` si numero invalido o ausente (no consume reintentos).
- Race condition en reprogramacion: `cancel_reminders` movido fuera del bloque `atomic`; un rollback ya no cancela recordatorios de la cita original.

---

### Added (Paso 2 — Cimientos multi-tenant) · commit `8aa9ac9`

- `apps/core`: `BaseModel` (UUID pk, timestamps, soft-delete), `TenantAwareModel` (FK a tenant + `created_by`), `TenantManager` (filtra por tenant en thread-local + excluye soft-deleted), `tenant_context` (almacenamiento thread-local con `set/get/clear_current_tenant`) y `TenantMiddleware` (inyecta tenant desde la primera membresía activa del usuario autenticado).
- `apps/tenancy`: modelo `Tenant` con ciclo de vida `TRIAL → ACTIVE → SUSPENDED` y campo `slug` para futuro header `X-Tenant-ID`; modelo `TenantMembership` con 7 roles (`owner`, `admin`, `doctor`, `nurse`, `reception`, `finance`, `readonly`); admin de Django para ambos modelos.
- `apps/tenancy` migración `0002_enable_rls`: función PostgreSQL `current_tenant_id()` para políticas RLS de tablas tenant-aware (las políticas se activan tabla por tabla en el Paso 3).
- `apps/authn`: modelo `User` custom email-based (sin `username`), bandera `is_platform_staff` para separar staff de Maily de miembros de clínica, `PlatformRole` enum (`super_admin`, `sales`, `engineering`), `UserManager` con `create_user`/`create_superuser`; admin con fieldsets reorganizados.
- `config/settings/base.py`: `AUTH_USER_MODEL = 'authn.User'`, `LOCAL_APPS` con `apps.authn` y `apps.tenancy`, `TenantMiddleware` en posición correcta (después de `AuthenticationMiddleware`).
- Dependencia `argon2-cffi` añadida a `pyproject.toml`; `PASSWORD_HASHERS` usa Argon2 por defecto.
- `docs/adr/0002-arquitectura-multi-tenant.md`: ADR formal que documenta la decisión shared-schema + RLS.

---

### Added (Paso 1 — Scaffolding) · commits `36dbf5a`, `fc8458b`, `2e8059d`

- Monorepo `Maily360/` con backend Django 5 + DRF en `MailySoft/backend/`, placeholders de frontend en `web-soft/` y `web-platform/`.
- Docker Compose con servicios: Postgres 16, Redis 7, backend Django, worker Celery.
- Tooling: Poetry para gestión de dependencias, `black` + `ruff` para formateo/linting, `mypy` + `django-stubs` para tipos estáticos, `pytest` + `pytest-django` para tests, `pre-commit` con hooks configurados.
- CI con GitHub Actions: pipeline con jobs de lint (`black --check`, `ruff`), tipo (`mypy`), tests (`pytest`) y auditoría de dependencias (`pip-audit`).
- 5 agentes Claude especializados (`django-engineer`, `django-reviewer`, `django-tester`, `django-security`, `django-docs-reporter`) y skill `django-clean-architecture` versionados en `.claude/`.
- `docs/adr/0001-stack-y-arquitectura.md`: ADR del stack tecnológico (Django 5 + DRF + PostgreSQL + Celery + monolito modular).
- `Makefile` con comandos de desarrollo (`make up`, `make migrate`, `make test`, etc.).
