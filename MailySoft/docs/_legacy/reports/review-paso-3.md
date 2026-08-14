# Revision de codigo — Paso 3: Fase de Agenda

| Campo | Valor |
|---|---|
| Revisor | django-reviewer |
| Sub-pasos cubiertos | 3a (Pacientes) · 3b (Personal) · 3c-1 (Agenda nucleo) · 3c-2 (Recordatorios) |
| Commits revisados | `3d24c07` · `c3317ed` · `751aa27` · `a9b93f1` |
| Commits de fixes | `3d24c07` (incluye fixes 3a) · `c3317ed` + `13e79ca` (fixes 3b) · `751aa27` (incluye fixes 3c-1) · `13a01e1` (fixes 3c-2) |
| Fecha | 2026-06-03 |
| Veredicto final | Aprobado (todos los bloqueantes y recomendados corregidos) |

---

## Contexto

Este documento consolida los hallazgos del django-reviewer sobre los cuatro sub-pasos de la Fase 3. Los hallazgos se clasifican en tres niveles:

- **BLOQUEANTE**: el codigo no puede ir a produccion hasta que se corrija.
- **RECOMENDADO**: no bloquea, pero introduce deuda tecnica o riesgo real.
- **NIT**: estilo o convencion menor, no afecta funcionalidad.

Un patron importante atraviesa el Paso 3a y el Paso 3b: la "puerta trasera de is_active" (ver seccion al final). Se formalizó en la skill `django-clean-architecture` en el commit `f385dd8` y no reapareció en los sub-pasos siguientes.

---

## Paso 3a — Pacientes (`3d24c07`)

### Hallazgos bloqueantes

#### BLOQ-3a-1 — GUC de RLS con `is_local=true` se borraba entre queries

**Descripcion:** El middleware alimentaba el GUC `app.current_tenant_id` con `SET LOCAL`, que en PostgreSQL tiene alcance de transaccion. Con el connection pooling de Django, las conexiones se reutilizan entre requests. El valor del GUC quedaba vaciado entre queries dentro del mismo request cuando no habia una transaccion activa, dejando las politicas RLS sin efecto de forma intermitente.

**Correccion:** `SET LOCAL` reemplazado por `SET SESSION` (`is_local=false`) con limpieza explicita en `finally`. El GUC persiste durante toda la vida del request y se borra de forma segura al finalizar.

**Estado:** Corregido en `3d24c07`.

---

#### BLOQ-3a-2 — TenantAPIView ausente; resolucion de tenant no funcionaba con JWT

**Descripcion:** El `TenantMiddleware` resuelve el tenant durante el ciclo de request de Django, antes de que la autenticacion JWT termine. Los views DRF con `Bearer token` corren su autenticacion en `initial()`, que ocurre despues del middleware. En consecuencia, cualquier view con JWT Bearer recibia `tenant=None` y todos los querysets quedaban vacios o sin filtrar.

**Correccion:** Se introdujo `TenantAPIView` como clase base de todos los views DRF del proyecto. Llama a `resolve_tenant_for_user()` en `initial()`, despues de que DRF autentica el token. El middleware queda como fallback para sesiones Django (admin). La logica de resolucion esta centralizada en una sola funcion.

**Estado:** Corregido en `3d24c07`.

---

### Hallazgos recomendados

#### REC-3a-1 — `is_active` modificable via PATCH (puerta trasera)

**Descripcion:** El serializer de `Patient` incluia `is_active` en los campos editables del PATCH. Cualquier cliente podia activar o desactivar un paciente sin pasar por el endpoint de baja previsto.

**Correccion:** `is_active` excluido del serializer de update. Solo el servicio interno de baja puede modificarlo.

**Estado:** Corregido en `3d24c07` (fix B3).

---

#### REC-3a-2 — Transaccion atomica y assert de tenant en `_next_record_number`

**Descripcion:** La funcion que genera el numero de expediente consecutivo podia ejecutarse sin transaccion activa, creando una ventana de race condition entre el `select_for_update` y el `save()`. Ademas, no verificaba que `PatientSequence` perteneciera al tenant correcto antes de incrementar.

**Correccion:** `_next_record_number` envuelto en `transaction.atomic()` con `assert` de tenant.

**Estado:** Corregido en `3d24c07` (fix B2).

---

### Nits

| ID | Descripcion | Estado |
|---|---|---|
| NIT-3a-1 | `exc.messages` en lugar de `str(exc)` para errores de validacion Django | Corregido en `3d24c07` (fix B7) |
| NIT-3a-2 | `select_related` innecesario en selector de paciente (no usa el JOIN) | Corregido en `3d24c07` (fix B7) |
| NIT-3a-3 | `updated_at` inmutable (no debe enviarse en requests) | Corregido en `3d24c07` (fix B7) |
| NIT-3a-4 | `record_number` con `max_length` sin definir | Corregido en `3d24c07` (fix B7, `max_length=30`) |

---

## Paso 3b — Personal (`c3317ed`, `13e79ca`)

### Hallazgos bloqueantes

No hubo hallazgos bloqueantes en el codigo de personal. Los tres altos de seguridad se detallan abajo; ninguno bloqueo por convencion del reviewer (quedaron en categoria ALTO del security audit).

### Hallazgos recomendados

#### REC-3b-1 — `is_active` modificable via PATCH en Doctor (puerta trasera — recurrente)

**Descripcion:** El mismo patron del Paso 3a reapareció: el serializer de `Doctor` incluia `is_active` como campo editable en PATCH. Un cliente podia reactivar un medico dado de baja sin pasar por el flujo de negocio.

**Nota:** Este fue el segundo caso del patron. Tras esta aparicion el equipo lo elevo a regla permanente en la skill (commit `f385dd8`).

**Correccion:** `is_active` excluido del serializer de update de Doctor. Corregido en `c3317ed` (fix F1).

**Estado:** Corregido.

---

#### REC-3b-2 — IDOR en DELETE de horario de doctor

**Descripcion:** El endpoint `DELETE /horarios/<id>/` recuperaba el `DoctorSchedule` por PK sin filtrar por tenant. Un usuario autenticado en el tenant A podia eliminar horarios del tenant B si conocia el UUID.

**Correccion:** El servicio de eliminacion delega la recuperacion al selector `schedule_get`, que filtra por tenant y lanza 404 si el horario no pertenece al tenant del request.

**Estado:** Corregido en `c3317ed` (fix F2).

---

#### REC-3b-3 — FK de consultorio no validada contra tenant del doctor

**Descripcion:** `schedule_create` aceptaba el `consultorio_id` sin verificar que el consultorio perteneciera al mismo tenant que el doctor. Una llamada maliciosa podia vincular un horario con un consultorio de otra clinica.

**Correccion:** El servicio verifica `consultorio.tenant_id == tenant.id` antes de crear el horario.

**Estado:** Corregido en `c3317ed` (fix F3).

---

#### REC-3b-4 — UniqueConstraint en `Doctor.membership` impedia recrear perfil tras soft-delete

**Descripcion:** El constraint `unique=True` (luego `UniqueConstraint`) sobre `Doctor.membership` no tenia condicion de soft-delete. Si un perfil de doctor era borrado logicamente, la misma membresia no podia asociarse a un nuevo perfil de doctor.

**Correccion:** Migracion `0003` agrega un `UniqueConstraint` parcial con `condition=Q(deleted_at__isnull=True)`. Los registros soft-deleted no participan en el constraint.

**Estado:** Corregido en `13e79ca`.

---

### Nits

| ID | Descripcion | Estado |
|---|---|---|
| NIT-3b-1 | Validacion de rango `valid_from <= valid_until` ausente en horarios | Corregido en `c3317ed` (fix F4) |
| NIT-3b-2 | `color_hex` sin validacion de formato `#RRGGBB` | Corregido en `c3317ed` (fix F5, `RegexField`) |
| NIT-3b-3 | Chequeo de doctor duplicado ignoraba soft-deleted | Corregido en `c3317ed` (fix F6) |

---

## Paso 3c-1 — Agenda nucleo (`751aa27`)

### Sobre la ausencia de bugs recurrentes

El commit `751aa27` documenta explicitamente: *"Las 3 reglas de la skill se cumplieron desde el inicio: status fuera del PATCH, detail via selector, FK validadas por tenant."* Los tres patrones que habian generado hallazgos en 3a y 3b (puerta trasera de is_active / IDOR / FK sin validar tenant) no aparecieron en el codigo de agenda porque el engineer los tenia incorporados como reglas de la skill antes de escribir la primera linea.

### Hallazgos bloqueantes

No hubo hallazgos bloqueantes.

### Hallazgos recomendados

#### REC-3c1-1 — `appointment_update` no delegaba al service; `_IMMUTABLE_FIELDS` inactivo

**Descripcion:** La view de update llamaba directamente a `serializer.save()` sin pasar por el service. El mecanismo de `_IMMUTABLE_FIELDS` (que impide modificar `patient`, `doctor`, `starts_at`, etc.) estaba definido en el service pero nunca se invocaba en el flujo real de PATCH.

**Correccion:** La view delega al service `appointment_update`. El service aplica `_IMMUTABLE_FIELDS` y valida el anti-empalme antes de guardar.

**Estado:** Corregido en `751aa27` (fix F1).

---

#### REC-3c1-2 — ExclusionConstraints incluian `attended` en `ACTIVE_STATUSES`

**Descripcion:** Las constraints de anti-empalme de Postgres excluian los estados terminales para no bloquear el slot ocupado por una cita pasada. Sin embargo, la lista `ACTIVE_STATUSES` usada en la migracion incluia `attended`, lo que significaba que dos citas "attended" en el mismo slot generaban un conflicto de constraint. La capa BD y la capa service no coincidian.

**Correccion:** Migracion `0003` redefine las constraints excluyendo `attended` de `ACTIVE_STATUSES`. Las citas atendidas liberan el slot.

**Estado:** Corregido en `751aa27` (fix F2, migracion `0003`).

---

### Nits

| ID | Descripcion | Estado |
|---|---|---|
| NIT-3c1-1 | Precedencia de duracion fallaba si `duracion=0` (falsy) en lugar de `is not None` | Corregido en `751aa27` (fix F3) |
| NIT-3c1-2 | `APP_LOG_LEVEL` default era `DEBUG`, expone PII en produccion | Corregido en `751aa27` (fix F5, default `INFO`) |
| NIT-3c1-3 | `except Exception` generico en lugar de excepts especificos | Corregido en `751aa27` (fix F6) |

---

## Paso 3c-2 — Recordatorios (`a9b93f1`, `13a01e1`)

### Hallazgos bloqueantes

#### BLOQ-3c2-1 — N+1 en `appointment_get` y `appointment_list`

**Descripcion:** Tras agregar `AppointmentReminder` con serializacion anidada, cada cita en un listado disparaba una query adicional para obtener sus recordatorios. Con 50 citas en pantalla se disparaban 51 queries.

**Correccion:** `prefetch_related('reminders')` agregado en `appointment_get` y en el queryset base de `appointment_list`.

**Estado:** Corregido en `13a01e1` (fix F1).

---

### Hallazgos recomendados

#### REC-3c2-1 — `cancel_reminders` dentro del bloque atomico de reprogramacion

**Descripcion:** Al reprogramar una cita, `cancel_reminders_for_appointment` se ejecutaba dentro de la transaccion atomica. Si la transaccion hacia rollback (por ejemplo, por un conflict de anti-empalme en la nueva hora), los recordatorios quedaban cancelados aunque la cita no se hubiera movido. La cita seguia en su horario original pero sin recordatorios.

**Correccion:** `cancel_reminders` movido fuera del bloque `atomic`. Los recordatorios solo se cancelan si la reprogramacion de la cita termina con exito.

**Estado:** Corregido en `13a01e1` (fix F5).

---

#### REC-3c2-2 — Sin validacion E.164 antes de intentar envio

**Descripcion:** El adaptador intentaba enviar a numeros de telefono que no cumplen el formato E.164 (requerido por la API de Meta). Esto consumia un reintento del mecanismo `max_retries=3` con un error predecible y evitable.

**Correccion:** La tarea valida el numero antes de llamar al adaptador. Si el numero es invalido o esta ausente, la tarea termina con estado `SKIPPED` sin consumir reintentos.

**Estado:** Corregido en `13a01e1` (fix F4).

---

### Nits

| ID | Descripcion | Estado |
|---|---|---|
| NIT-3c2-1 | `WhatsAppAdapter` como clase base sin `ABC`; no forzaba implementar metodos | Corregido en `13a01e1` (fix F6, hereda `ABC`) |
| NIT-3c2-2 | `logger = logging.getLogger("apps.adapters.whatsapp")` hardcoded | Corregido en `13a01e1` (fix F6, `__name__`) |
| NIT-3c2-3 | Walrus operator (`:=`) en task; `order_by` redundante en queryset | Corregido en `13a01e1` (fix F6) |
| NIT-3c2-4 | `CELERY_RESULT_EXPIRES` sin configurar; resultados de tareas acumulados en Redis | Corregido en `13a01e1` (fix F3, `CELERY_RESULT_EXPIRES=3600`) |

---

## El patron "puerta trasera de is_active" — de bug recurrente a regla de skill

| Sub-paso | Aparicion | Resolucion |
|---|---|---|
| 3a — Pacientes | `is_active` editable en PATCH de Patient | Corregido en `3d24c07` (fix B3) |
| 3b — Personal | `is_active` editable en PATCH de Doctor | Corregido en `c3317ed` (fix F1) |
| `f385dd8` — Skill | Regla formalizada en `SKILL.md`: "is_active fuera del PATCH siempre" | Escrita en el skill; no requiere correccion |
| 3c-1 — Agenda | No aparecio | Engineer aplico la regla desde el inicio |
| 3c-2 — Recordatorios | No aparecio | `AppointmentReminder.status` solo modificable via service de transicion |

El mismo patron se registro dos veces seguidas, se elevo a conocimiento codificado, y se detuvo. Este es el mecanismo de mejora continua del flujo de agentes.

---

## Resumen de hallazgos por nivel

| Sub-paso | Bloqueantes | Recomendados | Nits | Pendientes tras cierre |
|---|---|---|---|---|
| 3a — Pacientes | 2 | 2 | 4 | 0 |
| 3b — Personal | 0 | 4 | 3 | 0 |
| 3c-1 — Agenda nucleo | 0 | 2 | 3 | 0 |
| 3c-2 — Recordatorios | 1 | 2 | 4 | 0 |
| **Total** | **3** | **10** | **14** | **0** |

---

## Veredicto

Todos los hallazgos bloqueantes y recomendados de los cuatro sub-pasos estan corregidos antes del cierre de la fase. Los nits de menor impacto quedaron resueltos en los mismos commits de fixes; ninguno quedo pendiente con impacto en correctitud o seguridad.

**El codigo del Paso 3 queda aprobado. La Fase de Agenda esta cerrada.**
