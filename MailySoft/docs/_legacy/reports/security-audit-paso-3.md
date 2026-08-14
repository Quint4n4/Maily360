# Auditoria de seguridad — Paso 3: Fase de Agenda

| Campo | Valor |
|---|---|
| Auditor | django-security |
| Sub-pasos cubiertos | 3a (Pacientes) · 3b (Personal) · 3c-1 (Agenda nucleo) · 3c-2 (Recordatorios) |
| Commits auditados | `3d24c07` · `c3317ed` · `751aa27` · `a9b93f1` |
| Commits de remediation | `3d24c07` (incluye fixes 3a) · `c3317ed` + `13e79ca` (fixes 3b) · `751aa27` (incluye fixes 3c-1) · `13a01e1` (fixes 3c-2) |
| Fecha | 2026-06-03 |
| Marco normativo | NOM-024-SSA3-2010 · NOM-004-SSA3-2012 · LFPDPPP |
| Veredicto final | Seguro para dev/staging con adapter simulado; checklist antes de conectar WhatsApp real |

---

## Clasificacion del sistema

Maily Soft procesa **datos de salud** (expedientes clinicos, citas medicas, datos de contacto de pacientes). El marco normativo aplicable:

- **NOM-024-SSA3-2010**: obliga a mantener bitacoras de auditoria e impide el acceso no autorizado al expediente clinico electronico.
- **NOM-004-SSA3-2012**: regula la confidencialidad del expediente clinico.
- **LFPDPPP**: clasifica los datos de salud como datos sensibles, sujetos al nivel de proteccion mas alto. Cualquier fuga entre tenants distintos (clinicas distintas) es una violacion directa.

El modulo de Agenda introduce ademas **datos de contacto del paciente** (telefono en formato E.164 para recordatorios). Estos datos son PII bajo LFPDPPP y deben tratarse con cuidado especial en logs, trazas y almacenamiento temporal.

---

## Paso 3a — Pacientes: hallazgos

### CRITICO-3a-1 — GUC de RLS con `is_local=true` inactivo entre queries

**Descripcion:** El GUC `app.current_tenant_id` se alimentaba con `SET LOCAL`, que en PostgreSQL tiene alcance de transaccion. Django reutiliza conexiones entre requests; sin una transaccion activa que envuelva toda la peticion, el GUC se borraba entre queries dentro del mismo request. El resultado: las politicas RLS de Postgres — la segunda capa de aislamiento definida en el [ADR-0002](../adr/0002-arquitectura-multi-tenant.md) — estaban inactivas en la practica.

Para un sistema que procesa datos de salud bajo NOM-024 y LFPDPPP, operar con una sola capa de aislamiento (el ORM de Python) durante toda la Fase 2 y el inicio de la Fase 3 era una vulnerabilidad de nivel critico: un solo bug en el ORM suficiente para causar una fuga cross-tenant sin red de seguridad en la base de datos.

**Remediacion:** `SET LOCAL` reemplazado por `SET SESSION` (`is_local=false`). El GUC ahora persiste durante toda la vida de la conexion y se limpia explicitamente en el bloque `finally` de `TenantAPIView.initial()`.

**Estado:** Corregido en `3d24c07`.

---

### ALTO-3a-2 — TenantAPIView ausente; JWT requests no tenian contexto de tenant

**Descripcion:** El `TenantMiddleware` resuelve el tenant antes de que DRF ejecute la autenticacion JWT (que ocurre en `APIView.initial()`). Todo request con Bearer token llegaba a los views con `tenant=None`. El `TenantManager` retornaba queryset vacio para requests autenticados con JWT, ocultando el problema en lugar de evidenciarlo con una fuga.

Aunque el efecto observable era denegacion de acceso (queryset vacio), la causa era una falla arquitectonica: el aislamiento de tenant dependia de que el middleware hubiera resuelto el tenant, pero el middleware no tenia visibilidad del JWT.

**Remediacion:** `TenantAPIView` introducido como clase base de todos los views DRF. Resuelve tenant en `initial()` tras la autenticacion JWT. El middleware queda como fallback solo para sesiones Django (admin).

**Estado:** Corregido en `3d24c07`.

---

### Hallazgos medios — Paso 3a

| ID | Descripcion | Remediacion | Estado |
|---|---|---|---|
| MEDIO-3a-1 | Admin de pacientes accesible a cualquier staff (expone PII cross-tenant) | Restringido a `is_platform_staff` o `is_superuser` | Corregido en `3d24c07` (fix B5) |
| MEDIO-3a-2 | Sin validacion de formato CURP; cualquier string pasaba | Validacion contra patron RENAPO agregada | Corregido en `3d24c07` (fix B4) |
| MEDIO-3a-3 | `JWT_SIGNING_KEY` no obligatoria en produccion; fallback a `SECRET_KEY` | Variable marcada como obligatoria en `production.py` | Corregido en `3d24c07` (fix B6) |

---

## Paso 3b — Personal: hallazgos

### Hallazgos altos — Paso 3b

| ID | Descripcion | Impacto | Remediacion | Estado |
|---|---|---|---|---|
| ALTO-3b-1 | `is_active` editable en PATCH de Doctor | Un cliente podia reactivar un medico dado de baja; bypass del flujo de negocio | `is_active` excluido del serializer de update | Corregido en `c3317ed` (fix F1) |
| ALTO-3b-2 | IDOR en DELETE de horario; sin filtro de tenant | Un tenant A podia eliminar horarios del tenant B con el UUID | Eliminacion delega a `schedule_get` con filtro de tenant | Corregido en `c3317ed` (fix F2) |
| ALTO-3b-3 | FK de consultorio en horario sin validar tenant | Un horario podia vincularse a un consultorio de otra clinica | `schedule_create` verifica `consultorio.tenant_id == tenant.id` | Corregido en `c3317ed` (fix F3) |

### Hallazgos medios — Paso 3b

| ID | Descripcion | Remediacion | Estado |
|---|---|---|---|
| MEDIO-3b-1 | Admin de Personal accesible a cualquier staff (igual que 3a) | Restringido a `is_platform_staff` | Corregido en `c3317ed` |
| MEDIO-3b-2 | UniqueConstraint en `Doctor.membership` sin condicion de soft-delete | Indice parcial con `condition=Q(deleted_at__isnull=True)` | Corregido en `13e79ca` |

---

## Paso 3c-1 — Agenda nucleo: hallazgos

### Hallazgos altos — Paso 3c-1

| ID | Descripcion | Impacto | Remediacion | Estado |
|---|---|---|---|---|
| ALTO-3c1-1 | `appointment_update` no usaba el service; `_IMMUTABLE_FIELDS` inactivo | Campos criticos como `patient`, `doctor`, `starts_at` eran mutables via PATCH directo | View delega al service `appointment_update` | Corregido en `751aa27` (fix F1) |
| ALTO-3c1-2 | ExclusionConstraints incluian `attended` en ACTIVE_STATUSES | Dos citas "attended" en el mismo slot generaban conflicto de constraint; imposible cerrar citas correctamente | Migracion `0003` redefine constraints excluyendo `attended` | Corregido en `751aa27` (fix F2) |

### Hallazgos medios — Paso 3c-1

| ID | Descripcion | Remediacion | Estado |
|---|---|---|---|
| MEDIO-3c1-1 | `APP_LOG_LEVEL` default `DEBUG`; posible exposicion de PII en produccion via logs de Django | Default cambiado a `INFO` | Corregido en `751aa27` (fix F5) |

---

## Paso 3c-2 — Recordatorios: hallazgos con foco LFPDPPP

### Hallazgos altos — Paso 3c-2

#### ALTO-3c2-1 — Telefono del paciente en logs del adapter (LFPDPPP)

**Descripcion:** El `SimulatedWhatsAppAdapter` registraba el numero de telefono del paciente en texto claro en los logs de la aplicacion. El numero de telefono es PII bajo LFPDPPP. Exponerlo en logs implica que cualquier servicio que acceda a los logs (agregadores, operadores de infraestructura, desarrolladores en staging) puede acceder a datos personales de pacientes sin autorizacion.

**Remediacion:** El adapter enmascara el telefono en los logs (muestra solo los ultimos 4 digitos). El numero completo nunca aparece en texto claro fuera de la base de datos. `message_preview` documentado como dato LFPDPPP, protegido por RLS.

**Estado:** Corregido en `13a01e1` (fix F2).

---

#### ALTO-3c2-2 — `CELERY_RESULT_EXPIRES` sin configurar; datos de tareas acumulados

**Descripcion:** Sin `CELERY_RESULT_EXPIRES`, el backend de resultados de Celery (Redis) acumula resultados de tareas indefinidamente. Cada resultado de `send_appointment_reminder` puede contener datos parciales de la cita (patient_id, appointment_id, canal). En un sistema de salud, acumular datos innecesariamente mas alla del tiempo necesario viola el principio de minimizacion de datos de la LFPDPPP.

**Remediacion:** `CELERY_RESULT_EXPIRES=3600` configurado. Los resultados se purgan tras una hora, suficiente para reintentos y diagnostico inmediato.

**Estado:** Corregido en `13a01e1` (fix F3).

---

### Hallazgos medios — Paso 3c-2

| ID | Descripcion | Remediacion | Estado |
|---|---|---|---|
| MEDIO-3c2-1 | Sin validacion E.164; envio a numeros invalidos consume reintentos y genera errores no controlados | Validacion E.164 antes de enviar; SKIPPED si invalido | Corregido en `13a01e1` (fix F4) |
| MEDIO-3c2-2 | `cancel_reminders` dentro del bloque atomico de reprogramacion; rollback cancelaba recordatorios de la cita original | `cancel_reminders` movido fuera del bloque `atomic` | Corregido en `13a01e1` (fix F5) |

---

## Resumen de hallazgos de la fase

| Sub-paso | Criticos | Altos | Medios | Total | Todos corregidos |
|---|---|---|---|---|---|
| 3a — Pacientes (+ cimiento) | 1 | 1 | 3 | 5 | Si |
| 3b — Personal | 0 | 3 | 2 | 5 | Si |
| 3c-1 — Agenda nucleo | 0 | 2 | 1 | 3 | Si |
| 3c-2 — Recordatorios | 0 | 2 | 2 | 4 | Si |
| **Total** | **1** | **8** | **8** | **17** | **Si** |

---

## Controles positivos verificados en la fase

| Control | Descripcion | Donde |
|---|---|---|
| RLS activo en todas las tablas nuevas | Cada app activa RLS y crea la politica `USING (tenant_id = current_tenant_id())` en su migracion `enable_rls` | `pacientes`, `personal`, `agenda` (migraciones `0002`) |
| TenantAPIView como base de todos los views DRF | Garantiza que ningun view procese datos sin contexto de tenant valido | `apps/pacientes/views.py`, `apps/personal/views.py`, `apps/agenda/views.py` |
| Anti-empalme en dos capas | Service + ExclusionConstraint Postgres; ninguna capa sola es suficiente | `apps/agenda/services.py` + migracion `0002`/`0003` |
| `is_active` inmutable en todos los modelos de dominio | Baja de paciente, medico o consultorio solo por endpoint dedicado | Pacientes (B3), Doctor (F1 de 3b), Appointment status (diseno inicial) |
| Transiciones de estado estrictas | `VALID_TRANSITIONS` en `Appointment`; estados terminales no admiten transicion | `apps/agenda/models.py` |
| PII no en logs | Telefono enmascarado en adapter simulado; `message_preview` protegido por RLS | `adapters/whatsapp.py` |
| Admin restringido a `is_platform_staff` | El admin de Django no expone datos cross-tenant al staff de clinica | `pacientes/admin.py`, `personal/admin.py`, `agenda/admin.py` |
| Celery idempotente | La tarea verifica estado PENDING antes de enviar; reintento no duplica envio | `apps/agenda/tasks.py` |
| UUIDs en todas las claves primarias | Impide enumeracion de recursos por ID incremental | Herencia de `BaseModel` |

---

## Pendientes de seguridad para produccion

Los siguientes items no bloquean dev/staging pero deben resolverse antes de activar el adapter de WhatsApp real o de salir a produccion:

| Pendiente | Riesgo | Accion requerida |
|---|---|---|
| `MetaWhatsAppAdapter` debe replicar enmascarado de logs | PII (telefono) en logs de produccion si se implementa sin cuidado | Al implementar `MetaWhatsAppAdapter`: aplicar el mismo patron de enmascarado que `SimulatedWhatsAppAdapter` |
| Validacion E.164 en `MetaWhatsAppAdapter` | Envio a numeros invalidos con la API real genera errores facturables y posibles fugas de datos a Meta | Usar el mismo validador que la tarea usa antes de llamar al adapter |
| `message_preview` es PII protegida por RLS | Si se expone en un endpoint sin RLS activo, filtra datos del paciente | Verificar que el serializador de recordatorios no exponga `message_preview` en contextos sin RLS (tests de cross-tenant sobre recordatorios) |
| `apps/audit` ausente | NOM-024 requiere bitacora de modificaciones en expediente; sin ella el sistema no es conforme | Implementar como proximo modulo (ver [cierre de fase](fase-3-agenda.md)) |
| Permisos por rol clinico | Hoy cualquier miembro autenticado del tenant puede crear citas o dar de baja pacientes | Implementar control por rol (`doctor`, `reception`, etc.) en v2 |

---

## Veredicto

**El sistema con adapter simulado es seguro para desarrollo y staging.**

El unico hallazgo critico de la fase (GUC de RLS) esta corregido. Los 8 altos y 8 medios estan corregidos. La segunda capa de aislamiento (RLS en Postgres) esta activa en todas las tablas de dominio introducidas en la fase.

**Antes de conectar WhatsApp real (MetaWhatsAppAdapter) y antes de un deploy a produccion**, el equipo debe resolver los cinco pendientes de la tabla anterior, con prioridad en el enmascarado de logs del adapter real y en la implementacion de `apps/audit`.

---

## Referencias normativas

- [NOM-024-SSA3-2010](http://www.dof.gob.mx/normasOficiales/4300/salud6a/salud6a.htm)
- [NOM-004-SSA3-2012](https://www.dof.gob.mx/normasOficiales/4867/salud1_C/salud1_C.htm)
- [LFPDPPP — DOF](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf)
- [OWASP Django Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Django_Security_Cheat_Sheet.html)
- [ADR-0002 — Arquitectura multi-tenant](../adr/0002-arquitectura-multi-tenant.md)
