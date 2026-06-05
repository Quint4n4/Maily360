# Diseño: `apps/audit` — Bitácora de Auditoría Clínica (NOM-024)

> Estado: **borrador para aprobación** · Fecha: 2026-06-05 · Autor: Plan agent
> Pendiente: resolver "Preguntas abiertas" (§10) antes de implementar.

## 1. Resumen y alcance

`apps/audit` implementa una bitácora **append-only** de eventos clínicamente relevantes por clínica (tenant): quién hizo qué, sobre qué entidad, cuándo y desde dónde. Cumple NOM-024-SSA3-2012.

**v1 (este diseño):** modelo `AuditLog`, helper `audit_record(...)`, contexto de request (ip/request_id) vía thread-local, inmutabilidad (Python + PostgreSQL), endpoint de consulta para owner/admin, auditoría de lecturas de ficha de paciente, auditoría de login, índices.

**v2 (fuera de alcance):** particionado, exportación PDF/XLSX firmada, retención automática, integración SIEM, auditoría de listados.

## 2. Marco legal

NOM-024 (5.11, 8.1) obliga a registrar identificador de usuario, fecha/hora, tipo de operación y sistema de origen, con acceso restringido y conservación durante la vigencia del expediente. LFPDPPP (15, 19) exige demostrar la base de cada acceso a datos sensibles. La bitácora debe ser **íntegra e inalterable**. **Cada lectura de la ficha individual de un paciente** es acceso a expediente y debe registrarse.

## 3. Modelo `AuditLog` (hereda `TenantAwareModel`, tabla `audit_logs`)

**Decisión: tenant-aware** (cada clínica ve su propia bitácora vía RLS; platform staff ve todo vía `all_objects`). Excepción: `tenant` es **nullable** aquí (para eventos sin tenant, ej. login fallido).

| Campo | Tipo | Null | Descripción |
|---|---|---|---|
| `id` | UUID (pk) | No | heredado |
| `created_at` | DateTime (auto) | No | timestamp UTC, indexado. Inmutable |
| `tenant` | FK Tenant (PROTECT) | **Sí** | tenant del evento (null = global) |
| `actor` | FK User (SET_NULL) | Sí | quién realizó la acción (campo semántico) |
| `actor_role` | Char(20) | — | rol del actor en el momento (snapshot string) |
| `action` | Char(30) | No | tipo de acción (ActionType), indexado |
| `resource_type` | Char(50) | No | entidad: "Patient", "Appointment"... indexado |
| `resource_id` | UUID | Sí | id del objeto afectado, indexado |
| `resource_repr` | Char(200) | — | representación legible (snapshot, sin mutar) |
| `description` | Text | — | descripción en lenguaje natural |
| `ip_address` | GenericIPAddress | Sí | IP origen del request |
| `user_agent` | Char(512) | — | UA del request (opcional) |
| `request_id` | Char(64) | — | id de correlación del request |
| `metadata` | JSONB | — | contexto SIN PII (ver §3.4) |

Sin FK a modelos de negocio: `resource_type`+`resource_id` son referencias débiles (durables ante cambios/borrados del modelo).

### 3.3 ActionType (TextChoices)
PATIENT_CREATE/READ/UPDATE/DEACTIVATE · APPOINTMENT_CREATE/UPDATE/STATUS/RESCHEDULE · DOCTOR_CREATE/UPDATE/DEACTIVATE · CONSULTORIO_CREATE/UPDATE/DEACTIVATE · SCHEDULE_CREATE/DEACTIVATE · CONFIG_UPDATE · LOGIN · LOGIN_FAILED (futuro).

### 3.4 Política de `metadata` (estricta)
- **Permitido:** nombres de campos cambiados (`changed_fields`), estados no-clínicos (`old_status`/`new_status`), ids relacionados, conteos.
- **PROHIBIDO:** contenido clínico (diagnósticos, notas, medicamentos) y PII (nombre, CURP, teléfono, fecha nac). Esos datos viven en las tablas de negocio; no se duplican en la bitácora.

### 3.5 Índices
`(tenant_id, created_at)` · `(tenant_id, actor_id)` · `(tenant_id, resource_type, resource_id)` · `(tenant_id, action)`.

## 4. Inmutabilidad — doble barrera

**Python:** `save()` lanza `RuntimeError` si ya hay pk (prohíbe UPDATE); `delete()` lanza siempre.
**PostgreSQL:** RLS con política `FOR SELECT` (lectura por tenant) y `FOR INSERT WITH CHECK` (solo alta); además `REVOKE UPDATE, DELETE ON audit_logs FROM <rol_app>`. Defensa en profundidad: un bug Python no rompe la inmutabilidad porque la BD también la bloquea.

## 5. Mecanismo de registro

**Enfoque: helper explícito** `audit_record(...)` al final de cada service (NO signals — no tienen actor/HTTP; NO decoradores — mezclan capas). Consistente con la arquitectura services.

Firma:
```python
def audit_record(*, action, resource_type, actor, tenant,
                 resource_id=None, resource_repr="", description="",
                 metadata=None, actor_role="") -> AuditLog: ...
```
- **No lanza excepciones al caller.** Si falla, loguea el error pero NO tumba el service (una creación de cita no debe dar 500 porque falló la auditoría).
- **Contexto HTTP (ip/user_agent/request_id):** el helper lo lee de un thread-local nuevo en `tenant_context.py` (`set/get/clear_request_context`), poblado en `TenantAPIView.check_permissions()` y limpiado en el `finally` del middleware. El service NO recibe ip como argumento (no se acopla a HTTP).

## 6. Puntos de integración (mapea los TODO(audit))

| Service / punto | action | resource_type | metadata |
|---|---|---|---|
| `patient_create` | PATIENT_CREATE | Patient | {} |
| `patient_update` | PATIENT_UPDATE | Patient | changed_fields |
| `patient_deactivate` | PATIENT_DEACTIVATE | Patient | {} |
| `PatientDetailApi.get()` (view) | PATIENT_READ | Patient | {} |
| `doctor_create/update/deactivate` | DOCTOR_* | Doctor | changed_fields |
| `consultorio_create/update/deactivate` | CONSULTORIO_* | Consultorio | changed_fields |
| `schedule_create/deactivate` | SCHEDULE_* | DoctorSchedule | day_of_week |
| `appointment_create` | APPOINTMENT_CREATE | Appointment | doctor_id, patient_id |
| `appointment_update` | APPOINTMENT_UPDATE | Appointment | changed_fields |
| `appointment_change_status` | APPOINTMENT_STATUS | Appointment | old/new_status |
| `appointment_reschedule` | APPOINTMENT_RESCHEDULE | Appointment | old/new_starts_at |
| `agenda_config_update` | CONFIG_UPDATE | TenantAgendaConfig | changed_fields |
| señal `user_logged_in` | LOGIN | User | {} |

`PATIENT_READ` se registra en la **view** (el selector no recibe actor). Solo se audita el **detalle** del paciente, no el listado.

## 7. Consulta de la bitácora

`GET /api/v1/audit/logs/` — `AuditLogListApi(TenantAPIView)`, paginado, solo lectura. Filtros: `actor_id`, `resource_type`, `resource_id`, `action`, `date_from`, `date_to`.

**Permisos:** `AuditLogPermission(HasClinicRole)` con `policy = {"GET": MANAGE_ROLES}` → solo owner/admin ven la bitácora de su clínica. Platform staff ve todo vía Django Admin (`all_objects`). RLS garantiza aislamiento por tenant.

## 8. Performance, retención, volumen

- **Volumen:** clínica media ~250 eventos/día; 1,000 clínicas ~7.5M filas/mes (~3.75 GB/mes). Significativo a 12 meses.
- **v1: escritura SÍNCRONA** (INSERT simple <2ms; NOM-024 no quiere pérdida de eventos que tendría Celery fire-and-forget). El helper absorbe excepciones.
- **v2:** si el volumen lo exige, Celery best-effort; particionado por rango de fecha (`PARTITION BY RANGE (created_at)`); retención automática.
- **Retención:** NOM-024 ≥5 años; recomendación legal 10. v1 sin borrado automático.

## 9. Decisiones razonadas

| Decisión | Elegido | Por qué |
|---|---|---|
| tenant-aware vs global | tenant-aware (tenant nullable) | cada clínica ve su bitácora; RLS automático |
| sync vs async | síncrono v1 | INSERT rápido; sin riesgo de pérdida (NOM-024) |
| signals vs helper | helper explícito | signals no tienen actor/HTTP context |
| flujo ip/request_id | thread-local extendido | patrón ya usado para tenant; no acopla services a HTTP |
| FK a negocio | referencias débiles (type+id) | durabilidad ante cambios/borrados del modelo |
| inmutabilidad | Python + REVOKE en BD | defensa en profundidad |
| auditar listas | solo detalle de paciente | NOM-024 = acceso al expediente individual; ~10x menos filas |
| diff de datos | solo changed_fields (sin valores) | evita duplicar PII clínica |

## 10. Decisiones del dueño (RESUELTAS 2026-06-05)
1. **Retención:** **10 años** (sin borrado automático en v1; política documentada).
2. **Auditar lecturas:** **solo el detalle** de la ficha de paciente (PATIENT_READ en la view), NO los listados.
3. **LOGIN_FAILED:** **SÍ en v1** — conectar señal de login fallido (Django `user_login_failed` / SimpleJWT). Filas con tenant=None (usuario no resuelto).
4. **`metadata` en la API:** se expone solo a owner/admin (mismos que ven la bitácora).
5. **Exportación PDF/XLSX:** v2 (no v1).
6. **IP bajo NAT:** registrar IP igual (útil para geolocalización gruesa y detección de anomalías) + User-Agent.

### Permisos confirmados
- Ver la bitácora: **solo owner y admin** (`AuditLogPermission` con `policy={"GET": MANAGE_ROLES}`). Médico/enfermería/recepción/finanzas/lectura → 403.
- Platform staff: ve todas las clínicas vía Django Admin (`all_objects`).

## Estructura del módulo
```
apps/audit/{__init__,apps,models,services,selectors,serializers,views,urls,admin}.py
apps/audit/migrations/{0001_initial, 0002_enable_rls}.py
```
Cambios en core: `tenant_context.py` (+request context), `views.py` (set_request_context en check_permissions), `middleware.py` (clear en finally). `LOCAL_APPS += apps.audit`. `urls += api/v1/audit/`.

## Resumen de decisiones clave
1. `AuditLog` tenant-aware con tenant nullable (cubre login sin tenant).
2. Inmutabilidad doble barrera (save/delete override + REVOKE en BD).
3. Helper explícito `audit_record(...)`, no signals.
4. Contexto HTTP por thread-local extendido (sin acoplar services).
5. `PATIENT_READ` se audita en la view; solo detalle, no listas.
6. Escritura síncrona en v1 (sin pérdida de eventos).
