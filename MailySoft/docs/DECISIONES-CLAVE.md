# Decisiones clave — Maily Soft / Maily360

> Registro de las decisiones importantes tomadas durante el desarrollo, con su **porqué** y sus **implicaciones**.
> Las decisiones de arquitectura más formales tienen su propio ADR en `docs/adr/`. Este documento las consolida y agrega las decisiones de producto/UX y de frontend.
> Actualizado: **2026-06-15**.

---

## D-01 · Multi-tenant: Shared Database + Row Level Security
**Decisión:** una sola base de datos compartida; cada fila lleva `tenant_id`; aislamiento con **doble barrera** — `TenantManager` (Django) + **RLS de PostgreSQL**.
**Por qué:** simple de operar y barato (vs. una BD por clínica), pero seguro: aunque un bug salte el filtro de Django, RLS lo detiene en la base. Es el patrón correcto para SaaS de salud con muchos tenants pequeños.
**Implicación:** todo modelo de negocio hereda de `TenantAwareModel`; las lecturas por id pasan por selectors; las denegaciones por tenant ajeno son **404** (no revelar existencia), las de rol son **403**.
**Detalle:** [ADR-0003](adr/0003-aislamiento-multi-tenant-shared-rls.md).

## D-02 · Identidad: JWT + contraseñas Argon2
**Decisión:** SimpleJWT para tokens; **Argon2** para hashear contraseñas; validadores robustos (mín. 10 chars, no común, no numérica).
**Por qué:** Argon2 es el estándar moderno resistente a GPU; los validadores evitan contraseñas débiles en cuentas que tocan datos de salud.
**Implicación:** **las contraseñas NO se pueden "ver"** — están cifradas en un solo sentido. Lo que existe es **restablecer** (poner una nueva), nunca recuperar la actual.

## D-03 · Tokens HÍBRIDOS (access en memoria + refresh en cookie httpOnly)
**Decisión:** el **access token** vive solo en memoria del navegador (no localStorage); el **refresh token** vive en una cookie `httpOnly` `maily_refresh` + protección **CSRF double-submit** (`SameSite=Strict` + header `X-CSRFToken`).
**Por qué:** un XSS no puede robar el refresh (httpOnly) ni persistir el access (memoria, se pierde al recargar y se recupera con un refresh silencioso). Balance entre seguridad y UX.
**Implicación:** el frontend usa `credentials:'include'`; `/auth/refresh/` y `/auth/logout/` exigen CSRF; el cliente HTTP hace **refresh automático ante 401** y reintenta. En dev, el proxy de Vite hace que front y backend sean el mismo origen para que las cookies funcionen.

## D-04 · Permisos por rol: declarativos y *method-aware* (backend = autoridad)
**Decisión:** clase base `HasClinicRole` con una `policy` por método HTTP (GET/POST/PATCH/DELETE → conjunto de roles). El frontend solo usa el rol para **UX** (mostrar/ocultar); **el backend decide**.
**Por qué:** un solo lugar declarativo y testeable define quién puede qué; el front nunca es la última palabra (si oculta un botón pero alguien llama la API, el backend responde 403).
**Implicación:** ver la matriz en `ESTADO-DEL-PROYECTO.md §5`. OPTIONS (preflight CORS) nunca se bloquea por rol.

## D-05 · Arquitectura de conexión del frontend
**Decisión:** **cliente HTTP central** (`src/lib/http.ts`) por el que pasa TODA llamada; tipos de la API; **TanStack Query** para estado de servidor; cero secretos en el bundle.
**Por qué:** un solo punto para Bearer, CSRF, refresh, manejo de 401/403 y multipart → consistencia y seguridad. Evita lógica de red dispersa.
**Implicación:** los datos mock se eliminaron panel por panel conforme se conectó cada uno. Estándar en `.claude/skills/react-frontend-connect/SKILL.md`.

## D-06 · Expediente provisional (alta de paciente al vuelo)
**Decisión:** desde "Agendar cita" se puede crear un paciente **provisional** con datos mínimos (solo nombre). Se marca `is_provisional=True`; en Pacientes sale una alerta de "completar datos"; la bandera **se limpia sola** al completar fecha de nacimiento + sexo + teléfono.
**Por qué:** la recepción agenda rápido sin frenarse a capturar todo; pero el sistema recuerda que el expediente está incompleto (calidad de datos sin fricción).
**Implicación:** `Patient.date_of_birth/sex/phone` se volvieron opcionales; endpoint `POST /pacientes/rapido/`; el expediente nace incompleto pero rastreado.

## D-07 · Tipos de cita CONFIGURABLES con color
**Decisión:** los tipos de cita (Primera vez, Seguimiento, Urgente, …) NO son fijos: el dueño los **define** (nombre + color) en Personal → Tipos de cita. La cita guarda un FK opcional al tipo, y en el tablero **la tarjeta se tiñe con el color del tipo**.
**Por qué:** cada clínica categoriza distinto; configurable > hardcodeado. El color da lectura visual rápida en la agenda.
**Implicación:** modelo `AppointmentType` (tenant-scoped); el "motivo" de la cita se volvió opcional (el tipo es la categoría).

## D-08 · Eventos de agenda (reuniones / bloqueos) con bloqueo REAL
**Decisión:** modelo aparte `AgendaBlock` (no es una cita: no tiene paciente). Tipos: **reunión** y **bloqueo**. **Alcance flexible**: toda la clínica, uno o varios consultorios, o uno o varios doctores. El **bloqueo impide agendar** citas que le apliquen (anti-empalme real, no solo visual).
**Por qué:** las clínicas necesitan marcar días/horas no disponibles (festivos, vacaciones, juntas) y que el sistema lo respete. "Bloqueo real" fue elección explícita del dueño sobre "solo visual".
**Implicación:** `appointment_create` valida contra `AgendaBlock` (`_check_block_overlap`); un bloqueo de "toda la clínica" tiene `doctor` y `consultorio` en null; multi-selección de consultorios crea un bloqueo por cada uno. UI: card unificado **Cita / Bloqueo / Reunión** al hacer clic en una casilla.

## D-09 · Gestión de miembros (Equipo) — crear cuenta, no invitar
**Decisión:** el dueño da de alta miembros creando la **cuenta con una contraseña inicial** (no por invitación-email). Puede cambiar rol/nombre, **restablecer contraseña**, y **bloquear/reactivar** cuentas. No puede bloquearse a sí mismo. Solo Dueño/Admin gestionan miembros.
**Por qué:** funciona local/offline sin infraestructura de correo (MVP). El bloqueo da control de acceso inmediato. "Ver contraseñas" se rechazó por imposible/inseguro (ver D-02).
**Implicación:** API de miembros en la app `tenancy`; auditoría de alta/rol/bloqueo/contraseña; el "perfil médico" (cédula/especialidad) del doctor se edita desde su ficha.

## D-10 · Avatares — validación segura de imágenes
**Decisión:** subir foto de pacientes y personal con validación estricta: tamaño ≤ 5 MB, **se verifica que sea imagen real con Pillow** (no por extensión/Content-Type), whitelist JPG/PNG/WEBP (**se rechaza SVG** por riesgo XSS), nombre de archivo **aleatorizado**.
**Por qué:** es una app de salud; subir archivos es superficie de ataque clásica. No confiar en lo que dice el cliente.
**Implicación:** `apps/core/files.py`; endpoints `POST/DELETE .../avatar/`; media servido por Django en dev (proxy `/media` en Vite), S3 en prod. **Bug encontrado y corregido por los tests:** Pillow lanza `SyntaxError` con imágenes corruptas → se atrapa cualquier fallo como "imagen inválida" (400, no 500).

## D-11 · Bitácora de auditoría (NOM-024 / LFPDPPP)
**Decisión:** registrar acciones sensibles (create/update/delete, login/logout, bloqueo, restablecer contraseña, etc.) con actor, rol, tenant, y un identificador **no-PII** del recurso.
**Por qué:** cumplimiento regulatorio mexicano para datos de salud + trazabilidad de quién hizo qué.
**Implicación:** app `audit`; los services llaman `audit_record`; la bitácora la ve solo Dueño/Admin.

## D-12 · Especialidades como plugins (DECISIÓN DIFERIDA)
**Decisión:** las especialidades clínicas se modelarán como **plugins/extensiones por clínica**, pero **se construirán después del expediente clínico**.
**Por qué:** el expediente clínico es la base; las especialidades extienden sobre él. Orden correcto de construcción.
**Implicación:** pendiente; no bloquea el MVP actual. **Hoy** la especialidad es un campo de **texto libre** en el perfil del médico (ficha → Datos profesionales), copiado a la cita al agendar (snapshot). Un **catálogo configurable** de especialidades es ese paso futuro.

## D-13 · Modalidad de la cita (presencial / teléfono / video / fuera)
**Decisión:** cada cita tiene una **modalidad** (`Appointment.modality`: office / phone / video / offsite). Solo la presencial usa consultorio; las demás no. En el tablero hay una **columna fija "Telemedicina / Externo"** (siempre visible, para todos) donde caen las citas no presenciales y sin sala; al hacer clic ahí, el formulario abre sin consultorio y con modalidad de video por defecto.
**Por qué:** las clínicas atienden por teléfono/video/domicilio; el sistema debe distinguirlo y darle un lugar visible. Resuelve además el hueco de "¿dónde agenda telemedicina un médico acotado a consultorios?".
**Implicación:** la regla de consultorio (D-15) NO aplica a citas sin consultorio, así que un médico siempre puede hacer telemedicina.

## D-14 · Reactivar y reagendar citas + estilo "Cancelada"
**Decisión:** "Cancelada" sigue siendo terminal en la máquina de estados, pero se agregaron acciones explícitas: **Reactivar** (cancelled → scheduled, mismo horario, revalida anti-empalme) y **Reagendar** (cambia día/hora; si la cita estaba cancelada, la reactiva y mueve en un paso). En el tablero, una cita cancelada se ve con **rayas rojas + "CANCELADA"** y el nombre tachado. Reagendar existe en citas activas (agendada/confirmada) y canceladas; pide **solo el nuevo día y hora** (no recaptura todo).
**Por qué:** cancelar por error pasaba (y era irreversible); el usuario necesita deshacerlo y mover citas con un cambio mínimo.
**Implicación:** endpoint `POST /agenda/citas/<id>/reactivar/`; `appointment_reschedule` acepta canceladas; auditoría `APPOINTMENT_REACTIVATE`. También se permitió **`Agendada → En sala`** directo (walk-in sin confirmación previa) para que la alerta de seguimiento funcione.

## D-15 · El médico se acota a sí mismo y a sus consultorios
**Decisión:** un usuario con rol **médico** solo puede agendar **para sí mismo** (no para otros médicos), y solo en los **consultorios que tiene asignados** (M2M `Doctor.consultorios`, que el dueño/admin gestiona en la ficha; vacío = cualquiera). En su agenda, el tablero **esconde los consultorios ajenos** y muestra **solo sus citas** y eventos de su alcance. `/me/` incluye `doctor_id` para que el frontend sepa qué médico es.
**Por qué:** privacidad y orden — cada médico administra lo suyo; el dueño/recepción ven todo.
**Implicación:** reglas A y B en `appointment_create` (rechazo 400 si viola); las reglas se aplican a CUALQUIER rol que agende para ese médico (es sobre sus consultorios).

## D-16 · Alerta de seguimiento de citas (mantener el estado al día)
**Decisión:** un vigilante in-app (global) detecta citas de **hoy** cuyo estado se quedó atrás del reloj y lanza un modal que **guía la transición** ("¿Ya llegó X?" → En sala → "¿Pasó a consulta?" → En consulta → "¿Se atendió?"). El texto cambia según la modalidad (en video pregunta "¿Iniciaste la videollamada?"). **Nunca cambia estados solo** — siempre lo confirma una persona. Solo le salta a **recepción** (todas las citas) o al **médico de esa cita** (las suyas). El "Aún no" (pospone 5 min) y la pausa tras confirmar persisten en **localStorage** (sobreviven al refresco).
**Por qué:** el estado es manual y se olvidaba; esto lo mantiene al día sin trabajo extra, y libera al doctor.
**Implicación:** in-app por ahora; el envío real (push/WhatsApp cuando nadie está en la app) se reusará del motor Celery de recordatorios, a futuro.

## D-17 · Permisos finos de agenda: agendar ≠ cambiar estado
**Decisión:** se separan dos capacidades:
- **Agendar/reagendar/reactivar/editar eventos** → Dueño, Admin, Médico, Recepción (la **enfermería NO**).
- **Cambiar el estado** de una cita (En sala, En consulta, Atendida, Cancelar, No asistió) → incluye **enfermería**.
Así la enfermera **ayuda al doctor moviendo al paciente** por el flujo, pero **no reserva citas** (eso es de recepción).
**Por qué:** agendar es tarea de front desk; la enfermería es soporte clínico.
**Implicación:** el backend ya lo distinguía (`AppointmentPermission` POST sin enfermería vs `AppointmentStatusPermission` con enfermería); se alineó el frontend con helpers `puedeAgendar` / `puedeCambiarEstadoCita`.

## D-18 · Crear paciente provisional + cita de forma ATÓMICA
**Decisión:** al agendar "paciente nuevo", el expediente provisional y la cita se crean en **una sola transacción** (`appointment_create_with_new_patient`; el POST de cita acepta `new_patient` además de `patient_id`). Si la cita falla, el paciente **no se crea** (rollback).
**Por qué:** antes se creaban en dos llamadas; si la cita fallaba (empalme, reglas de médico), el expediente quedaba **huérfano** y cada reintento lo **duplicaba**. Las reglas nuevas (D-15) hicieron que fallara más seguido → más duplicados.
**Implicación:** se eliminó la causa raíz de los expedientes duplicados; quedan como pendiente la **detección/fusión de duplicados de persona** (mismo nombre/teléfono) al agendar.

## D-19 · Sistema de notificaciones in-app (campana + luz amarilla)

**Decisión:** un sistema de notificaciones en tiempo casi real basado en **polling cada 30 s** (sin WebSockets), con una app Django nueva `apps/notificaciones/` y dos componentes visuales en el frontend: campana en el Topbar y luz amarilla para recordatorios.

**Por qué:** los WebSockets añaden complejidad operativa (Redis Channels, cambio en ASGI) que no justifica el MVP. El polling a 30 s es suficiente para los tres casos de uso (notas de equipo, reuniones, notas a un rol) y aprovecha la infraestructura HTTP existente. El sistema es **best-effort**: los disparadores van dentro de `try/except` para que un fallo en las notificaciones nunca tumbe la acción principal (agendar una reunión, escribir una nota).

**Diseño: quién envía y quién recibe por tipo de notificación:**

| `kind` | Evento disparador | Destinatarios |
|---|---|---|
| `meeting` | Se crea un `AgendaBlock` con `kind=meeting` | Depende del alcance: `medico` → ese médico; `consultorio` → sus médicos; `clinica` → todo el staff (owner/admin/doctor/nurse/reception). Los bloqueos simples **no** notifican. |
| `team_note` | Se agrega una `AgendaItemNote` a una cita | El médico de la cita + recepción + quienes ya comentaron el hilo. |
| `role_note` | Se crea una `Note` con `scope=role` | Todos los usuarios del tenant con ese rol. |
| `broadcast` | Se crea una `Note` con `scope=all` | Todos los usuarios del tenant. |

Regla transversal: el **actor** (quien dispara) siempre se excluye del reparto.

**Cambio de permisos en notas (parte de esta feature):** antes, `scope=role` y `scope=all` eran exclusivos del Dueño. Ahora:
- `scope=role` → lo pueden crear owner, admin, doctor, nurse, reception (`ROLE_NOTE_SENDERS`).
- `scope=all` → sigue siendo exclusivo del Dueño.
La decisión fue del dueño del producto: el staff clínico necesita avisarle a un rol específico sin requerir al dueño.

**Aislamiento multi-tenant:** `Notification` hereda de `TenantAwareModel`; tiene RLS (migración `0002_enable_rls`, mismo patrón que pacientes). El selector filtra por `tenant` **y** `recipient` (doble barrera; el IDOR está testeado).

**Frontend:** `CampanaNotificaciones.tsx` (badge de no leídas, dropdown, marcar una/todas, navega al objeto destino) montado en el Topbar; `LuzRecordatorios.tsx` (luz parpadeante de recordatorios de hoy vencidos, snooze 4 h) montado en `App.tsx`. Ambos usan hooks de polling a 30 s.

**Implicación:** todo el código de negocio que crea eventos (notas, reuniones) llama a `notification_fanout` al final de su service, dentro de `try/except` (no bloquea). Nuevos endpoints: `GET /api/v1/notificaciones/`, `GET /api/v1/notificaciones/conteo/`, `POST /api/v1/notificaciones/leidas/`, `POST /api/v1/notificaciones/<id>/leida/`.

**PII pendiente a revisar:** el título de la notificación de `team_note` incluye el nombre del paciente (facilita la UX pero es PII). El equipo debe decidir si anonimizarlo o aceptarlo documentado.

---

## Decisiones de proceso / colaboración

- **Flujo de construcción backend:** ingeniero → tester → revisor → seguridad → docs (la "trifecta" de subagentes), con el dueño aprobando cada paso. Los subagentes actúan con modelo **sonnet**.
- **Tests primero en lo sensible:** lo que toca cuentas, contraseñas o archivos se cubre con tests automatizados (los tests cazaron bugs reales, p. ej. el permiso `DELETE` faltante en miembros y el 500 de imágenes corruptas).
- **`web-soft/` es el frontend del dueño** (originado en una sesión paralela): se commitea cuando el dueño lo aprueba.
- **Commits frecuentes y push a GitHub** como respaldo; mensajes descriptivos en español.
