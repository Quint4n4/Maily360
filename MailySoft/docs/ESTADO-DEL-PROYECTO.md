# Estado del Proyecto — Maily Soft / Maily360

> Foto consolidada **full-stack** (backend + frontend). Actualizado: **2026-06-12**.
> Referencia rápida para entender **dónde está el proyecto hoy** — para el dueño y para cualquier dev nuevo.
> Decisiones técnicas detalladas en [`DECISIONES-CLAVE.md`](DECISIONES-CLAVE.md).

---

## 1. Resumen

**Maily Soft / Maily360** es una plataforma SaaS **multi-tenant** de gestión de clínicas (muchas clínicas, mismo software, datos aislados). Migra de un sistema PHP legacy (`app.maily.mx`). Hoy es un **MVP clínico funcional de punta a punta**: el backend está construido y probado, y el frontend está **conectado al backend real** panel por panel (auth, pacientes, agenda, personal).

| | |
|---|---|
<<<<<<< Updated upstream
=======
<<<<<<< HEAD
| **Stack** | Django 5 + DRF · PostgreSQL 16 · Redis · Celery · Docker |
| **Estado** | Backend MVP clínico funcional + cumplimiento base (NOM-024/LFPDPPP) + módulo Finanzas (cobros, cotizaciones, CFDI 4.0) |
| **Apps Django** | 8 (core, tenancy, authn, pacientes, personal, agenda, audit, finanzas) |
| **Tests** | 594 · cobertura ~96.7% (+ suite de finanzas: services/selectors/apis) |
| **Commits** | 18 · repo: github.com/Quint4n4/Maily360 |
| **Frontend** | En desarrollo aparte (web-soft, React+Vite); consume esta API. Módulo Finanzas con dashboard interactivo y estado de cuenta exportable |
=======
>>>>>>> Stashed changes
| **Stack backend** | Django 5 + DRF · PostgreSQL 16 · Redis · Celery · Docker |
| **Stack frontend** | React 18 + Vite + TypeScript + Tailwind + TanStack Query (carpeta `web-soft/`) |
| **Apps Django** | 8 (core, tenancy, authn, pacientes, personal, agenda, audit, **notas**) |
| **Tests backend** | **1013 pasando** (código commiteado, endurecido) |
| **Repo** | github.com/Quint4n4/Maily360 · rama `main` |
| **Cumplimiento** | NOM-024 / LFPDPPP (bitácora, minimización de PII, Argon2) |

---
<<<<<<< Updated upstream
=======
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes

## 2. Arquitectura en un vistazo

### Backend
- **Modular Monolith**: un backend dividido en apps por dominio.
- **Multi-tenant: Shared Database + Row Level Security** ([ADR-0003](adr/0003-aislamiento-multi-tenant-shared-rls.md)). Cada fila lleva `tenant_id`; **doble barrera**: (1) `TenantManager` filtra en Django, (2) RLS de PostgreSQL lo refuerza en la BD.
- **Arquitectura por capas**: `URLs → Views (delgadas) → Serializers → Services/Selectors → Models`. La lógica vive en services/selectors.
- **Identidad**: JWT (SimpleJWT) + contraseñas **Argon2**.

### Frontend (`web-soft/`)
- **Cliente HTTP central** (`src/lib/http.ts`): toda llamada pasa por aquí. Bearer en memoria + CSRF en mutaciones + **refresh automático ante 401** + soporte multipart (subida de archivos).
- **Auth híbrida**: access token en memoria (tokenStore), refresh en cookie `httpOnly` + CSRF double-submit. Bootstrap silencioso al recargar.
- **Estado de servidor**: TanStack Query (hooks por dominio en `src/hooks/`).
- **El backend es la AUTORIDAD de permisos**: el rol del front solo controla la UX (mostrar/ocultar). Quien decide es el backend (403).
- **Proxy de Vite**: `/api` y `/media` → `localhost:8000` (mismo origen en dev → cookies y CORS sin líos).
- **Cero secretos en el bundle**.

<<<<<<< Updated upstream
---

## 3. Módulos backend (apps)

| App | Qué hace |
|---|---|
=======
<<<<<<< HEAD
| App | Qué hace | Tests | Estado |
|---|---|---:|---|
| `core` | Cimiento: TenantAwareModel, TenantManager, middleware, TenantAPIView, permisos por rol, request context | 80 | ✅ |
| `tenancy` | Clínicas (Tenant) y membresías (TenantMembership) con 7 roles | 16 | ✅ |
| `authn` | Usuario custom (email), login JWT con auditoría, endpoint `/me/` | 16 | ✅ |
| `pacientes` | Pacientes + numerador de expediente consecutivo por clínica | 61 | ✅ |
| `personal` | Doctores, consultorios, horarios de atención | 78 | ✅ |
| `agenda` | Citas (máquina de estados + anti-empalme doble), config por clínica, recordatorios WhatsApp (simulados) | 117 | ✅ |
| `audit` | Bitácora append-only NOM-024: quién accede/modifica qué | 59 | ✅ |
| `finanzas` | Conceptos, cotizaciones, cargos (CxC), pagos + aplicaciones, estado de cuenta, CFDI 4.0 (PAC vía adapter), dashboard de métricas | — | ✅ |
=======
---
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547

## 3. Módulos backend (apps)

<<<<<<< HEAD
Prefijo base: `/api/v1/`. Todos requieren JWT salvo login.

| Método | Ruta | Qué hace | Rol requerido |
|---|---|---|---|
| POST | `/auth/login/` | Login → tokens JWT (registra LOGIN en bitácora) | — (público) |
| POST | `/auth/refresh/` | Renueva el access token | — |
| POST | `/auth/verify/` | Verifica un token | — |
| GET | `/me/` | Perfil del usuario: rol, clínica activa, membresías | cualquiera autenticado |
| GET/POST | `/pacientes/` | Listar/buscar · crear paciente | ver: todos · crear: owner/admin/médico/enfermería/recepción |
| GET/PATCH/DELETE | `/pacientes/<id>/` | Ver ficha (auditada) · editar · dar de baja | baja: owner/admin |
| GET/POST | `/personal/doctores/` · `/consultorios/` · `.../horarios/` | Listar · gestionar personal | ver: todos · gestionar: owner/admin |
| GET/POST | `/agenda/citas/` | Calendario (filtros) · crear cita | ver: todos menos finanzas · crear: owner/admin/médico/recepción |
| GET/PATCH/DELETE | `/agenda/citas/<id>/` | Ver · editar · cancelar | cancelar: owner/admin/recepción |
| POST | `/agenda/citas/<id>/estado/` | Cambiar estado (llegó, en consulta…) | owner/admin/médico/enfermería/recepción |
| POST | `/agenda/citas/<id>/reagendar/` | Reagendar | owner/admin/médico/recepción |
| GET/PATCH | `/agenda/config/` | Config de agenda de la clínica | owner/admin |
| GET | `/audit/logs/` | Bitácora de la clínica (filtros) | owner/admin |
| GET/POST | `/finanzas/conceptos/` · `<id>/` | Catálogo de conceptos cobrables | ver: finanzas+ · gestionar: owner/admin |
| GET/PATCH | `/finanzas/config/` | Datos fiscales del emisor (sin secretos) | owner/admin |
| GET/POST | `/finanzas/cotizaciones/` · `<id>/` · `<id>/enviar/` · `<id>/aceptar/` | Cotizaciones (aceptar genera cargos) | owner/admin/finanzas/recepción |
| GET/POST | `/finanzas/cargos/` · `<id>/` | Cuentas por cobrar | ver: +recepción · crear: owner/admin/finanzas |
| GET/POST | `/finanzas/pagos/` · `<id>/` | Cobros + aplicación a cargos | owner/admin/finanzas/recepción |
| GET | `/finanzas/estado-cuenta/<patient_id>/` | Estado de cuenta (movimientos + saldo) | owner/admin/finanzas/recepción |
| GET/POST | `/finanzas/cfdi/` · `<id>/` · `<id>/cancelar/` | Emitir/cancelar CFDI 4.0 (PAC) | owner/admin/finanzas |
| GET | `/finanzas/dashboard/` | KPIs + series para gráficas | owner/admin/finanzas (readonly: ver) |
| GET | `/api/docs/` · `/api/schema/` | Documentación OpenAPI (solo en dev) | — |

## 5. Roles y matriz de permisos

**7 roles de clínica** (`TenantMembership.Role`): Owner, Admin, Médico, Enfermería, Recepción, Finanzas, Solo lectura.
**3 roles de plataforma** (tu equipo SaaS): Súper Admin, Ventas, Ingeniería (`is_platform_staff`).

El backend **hace cumplir** la matriz (no solo la muestra): un usuario de recepción NO puede gestionar doctores (403); solo-lectura no crea nada; finanzas no ve la agenda; etc. Implementación declarativa en `apps/core/permissions.py`. Denegación por rol → **403**; recurso de otra clínica → **404** (no revela existencia).

## 6. Modelo de datos (entidades principales)

| App | Entidades |
|---|---|
| tenancy | `Tenant` (clínica), `TenantMembership` (user↔clínica + rol) |
| authn | `User` (email, is_platform_staff) |
| pacientes | `Patient`, `PatientSequence` (numerador) |
| personal | `Doctor` (→ membership), `Consultorio`, `DoctorSchedule` |
| agenda | `Appointment` (estados + anti-empalme), `TenantAgendaConfig`, `AppointmentReminder` |
| audit | `AuditLog` (append-only, inmutable) |
| finanzas | `ServiceConcept`, `ClinicFiscalConfig`, `Quote`+`QuoteItem`, `Charge`, `Payment`+`PaymentAllocation`, `CfdiDocument` |
=======
| App | Qué hace |
|---|---|
>>>>>>> Stashed changes
| **core** | Base multi-tenant (`TenantAwareModel`, `TenantManager`), permisos por rol (`HasClinicRole` y subclases), `TenantAPIView`, validación segura de imágenes (`files.py`). |
| **tenancy** | Tenants (clínicas) + `TenantMembership` (usuario↔clínica↔rol). **API de gestión de miembros** (alta, rol, bloqueo, restablecer contraseña, avatar). |
| **authn** | `User` custom (email login, Argon2), JWT híbrido (login/refresh/logout/verify), endpoint `/me/`, avatar de usuario. |
| **pacientes** | Expedientes (CRUD, búsqueda, baja lógica, número de expediente seguro). **Alta provisional** (al vuelo desde agenda). Avatar de paciente. |
| **personal** | Doctores (con **consultorios asignados** M2M y especialidad), consultorios, horarios (CRUD). |
| **agenda** | Citas (crear, estados con máquina de estados, reagendar, anti-empalme doble). **Tipos de cita** configurables con color. **Eventos** (reuniones/bloqueos) con bloqueo real. Recordatorios (Celery). Config de agenda. |
| **audit** | Bitácora NOM-024: registra create/update/delete/login/bloqueo/etc. por actor, rol y tenant. |
| **notas** | Notas y tareas: personales (privadas, con recordatorio), globales del Dueño (a un rol o a todos), y tareas (hecho/pendiente). Notas colaborativas (hilo con autor) viven en `agenda` (AgendaItemNote). |
<<<<<<< Updated upstream
=======
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes

---

## 4. Frontend — estado panel por panel

<<<<<<< Updated upstream
| Panel | Estado | Detalle |
=======
<<<<<<< HEAD
**Implementado:**
- ✅ Aislamiento multi-tenant: doble barrera (TenantManager + RLS forzada).
- ✅ Permisos por rol en todos los endpoints.
- ✅ Bitácora de auditoría inmutable (NOM-024): accesos y cambios a expedientes, login y login fallido. Retención 10 años.
- ✅ JWT + Argon2 + 2FA-ready. Sin secretos en código (django-environ).
- ✅ HTTPS/HSTS + cookies seguras en producción. CORS controlado.
- ✅ Minimización de datos: la bitácora guarda nº de expediente (no nombres), email hasheado en login fallido.
- ✅ Validación de entrada (CURP, teléfono, rangos). Anti-empalme en código + base de datos.

**Falta para producción real:**
- ⏳ Hosting en AWS región México (Querétaro) — residencia de datos.
- ⏳ Certificación formal NOM-024 (CENETEC) y aviso de privacidad LFPDPPP.
- ⏳ Exportación de bitácora (PDF/XLSX para COFEPRIS), retención automática a 10 años, particionado.
- ⏳ Confirmar rol de BD no-superuser en prod (para que el REVOKE de la bitácora aplique).
- ⏳ Rotación de secretos productivos + monitoreo (Sentry) en vivo.

## 8. Lo que FALTA / backlog

**Módulos clínicos aún no construidos:**
- Expediente clínico completo (historia, evolución SOAP, exploración, enfermería, archivos).
- Recetas, constancias, consentimientos.
- Inventario.

**Finanzas (construido) — pendientes para producción:**
- Integración real con PAC (Facturama): hoy el adapter usa un timbrado simulado; el `FacturamaCfdiAdapter` es un placeholder a completar con credenciales por `env`.
- Complemento de pagos (REP) y notas de crédito CFDI.
- Conciliación bancaria y reportes contables.
- Especialidades como plugins (núcleo + JSON Schema por especialidad).

**Plataforma y plataforma SaaS:**
- Panel de plataforma (tu vista de dueño: MRR, clínicas, billing, métricas).
- Registro self-service de clínica + invitación de equipo (hoy se crea por admin).
- Billing con Stripe (planes anuales + add-ons).
- `X-Tenant-ID` para usuarios que pertenecen a varias clínicas.

**Integraciones:**
- WhatsApp real (Meta Cloud API) — hoy adapter simulado.
- Maily te cuida (app del paciente, Flutter) — backend separado que consume esta API.
- IA de triage de síntomas.

## 9. Cómo correr el proyecto

```bash
cd ~/Desktop/Maily360/MailySoft
make up            # levanta Postgres + Redis + backend + celery (Docker)
make logs          # ver logs en vivo
make test          # correr la suite de tests
make down          # apagar
```
- API: http://localhost:8000/api/v1/
- Docs interactivas (Swagger): http://localhost:8000/api/docs/
- Admin Django: http://localhost:8000/admin/
- Usuarios de prueba: existen cuentas seed (admin de plataforma y recepción). Las credenciales NO se documentan aquí por seguridad — solicitarlas al equipo / regenerarlas con `manage.py`.
- Datos demo de finanzas: `python manage.py seed_finanzas --tenant <slug>` crea conceptos, cotizaciones, cargos de varias antigüedades (para el aging), pagos por distintos métodos y un CFDI timbrado con el PAC simulado, listos para ver el dashboard y el estado de cuenta.

## 10. Métricas

| | |
|---|---|
| Commits | 18 |
| Tests | 594 (~96.7% cobertura) |
| Apps Django | 7 |
| Endpoints REST | ~14 rutas de negocio + auth + docs |
| Migraciones | ~50 aplicadas |
| ADRs | 3 · Reportes de fase | 4 · Diseños | 2 |

## 11. Historial de fases

| Fase | Qué se entregó | Reporte |
=======
| Panel | Estado | Detalle |
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes
|---|---|---|
| **Login / sesión** | ✅ Real | Login JWT híbrido, rol real desde `/me/`, logout, refresh automático, avatar en Topbar. |
| **Pacientes** (antes "Contactos") | ✅ Real | Lista, búsqueda server-side, alta, **edición**, **baja**, **avatar**. Expediente con **próxima cita + historial reales** (conectado a la agenda). Alerta de "expediente provisional". |
| **Agenda** | ✅ Real | Calendario navegable; citas por **tipo de cita** (color) y **modalidad** (presencial/teléfono/video/fuera, con columna fija **Telemedicina/Externo**); **agendar** (existente o **nuevo provisional atómico**); **cambiar estado** (máquina de estados); **reactivar/reagendar** (cancelada se ve con rayas rojas + "CANCELADA"); **bloqueos/reuniones** (card unificado, editable); **hilo de notas del equipo**; widget **"Mis recordatorios"**; **alerta de seguimiento** que guía el estado de las citas del día. El **médico** ve solo sus consultorios y citas; la **enfermería** cambia estado pero no agenda. |
| **Notas y Tareas** | ✅ Real | Tarjetas de colores: **Mis notas/tareas** (con recordatorio, fijar, marcar hecha) y **Avisos de la clínica** (globales del Dueño a un rol o a todos). |
| **Personal** | ✅ Real | Pestañas: **Equipo** (miembros por rol → ficha → editar/bloquear/contraseña/avatar/perfil médico), **Consultorios** (CRUD), **Tipos de cita** (CRUD con color). |
| **Finanzas** | 🔴 Mock | Sin backend conectado. |
| **Panel de plataforma** (dueño SaaS) | 🔴 Mock | Sin backend (Fase 4 — pendiente de construir). |

---

## 5. Matriz de roles y permisos (autoridad: backend)

7 roles: `owner` (Dueño), `admin` (Administrador), `doctor` (Médico), `nurse` (Enfermería), `reception` (Recepción), `finance` (Finanzas), `readonly` (Solo lectura).

| Recurso · acción | Roles permitidos |
|---|---|
| **Pacientes** — ver | Todos |
| **Pacientes** — crear/editar | Dueño, Admin, Médico, Enfermería, Recepción |
| **Pacientes** — dar de baja | Dueño, Admin |
| **Personal** (doctores/consultorios) — ver | Todos |
| **Personal** — crear/editar/desactivar | Dueño, Admin |
| **Tipos de cita** — ver | Todos · **crear/editar/borrar** | Dueño, Admin |
| **Citas** — ver | Todos menos Finanzas |
| **Citas** — **agendar** / reagendar / reactivar | Dueño, Admin, Médico, Recepción **(enfermería NO)** |
| **Citas** — **cambiar estado** (En sala/En consulta/Atendida/Cancelar/No asistió) | Dueño, Admin, Médico, **Enfermería**, Recepción |
| **Eventos** (reuniones/bloqueos) — crear/editar/borrar | Dueño, Admin, Médico, Recepción |
| El **médico** agenda solo para sí mismo y solo en sus consultorios asignados | — |
| **Miembros** (gestión de equipo) | Solo Dueño, Admin |
| **Config de agenda · Bitácora** | Solo Dueño, Admin |

> Regla base: sin membresía activa → **403** en todo. El staff de plataforma sin membresía también (opera vía Django admin).

---

## 6. Features clave construidas (resumen)

- **Conexión frontend↔backend** completa (auth híbrida, refresh automático, TanStack Query, tipos de API).
- **Pacientes**: CRUD real + **expediente provisional** (alta al vuelo desde la agenda con datos mínimos; se marca como "por completar" y la bandera se limpia sola al completar los datos).
- **Agenda**:
  - Calendario interactivo + citas reales por día.
  - **Tipos de cita configurables** (nombre + color) → la tarjeta de la cita se tiñe con el color del tipo.
  - **Máquina de estados** de citas (Agendada → Confirmada → En sala → En consulta → Atendida; + Cancelada / No asistió), validada en backend.
  - **Eventos: reuniones y bloqueos** — sin paciente, con alcance (toda la clínica / uno o varios consultorios / uno o varios doctores), todo el día o por horas. **Bloqueo REAL**: impide agendar citas encima.
  - **Card unificado**: al hacer clic en una casilla, eliges Cita / Bloqueo / Reunión en el mismo modal.
- **Expediente ↔ Agenda**: el expediente del paciente muestra su **próxima cita** y su **historial** reales; al cambiar el estado en la agenda, se refleja en el expediente.
- **Gestión de miembros (Equipo)**: alta de miembro con **contraseña robusta**, cambiar nombre/rol, **bloquear/reactivar** cuenta, **restablecer contraseña**, **perfil médico** (cédula/especialidad). Navegación: roles → usuarios → ficha.
- **Avatares**: subir foto de pacientes y personal (validación segura de imágenes), mostradas en tarjetas, fichas y Topbar.

---

## 7. Usuarios de prueba (solo DEV · clínica "Demo Vitalis")

| Correo | Rol | Contraseña |
|---|---|---|
| `admin@maily.local` | Dueño (superusuario Django admin) | `admin12345` |
| `owner@demo.local` | Dueño | `demo12345` |
| `admin@demo.local` | Administrador | `demo12345` |
| `doctor@demo.local` | Médico | `demo12345` |
| `nurse@demo.local` | Enfermería | `demo12345` |
| `reception@demo.local` | Recepción | `demo12345` |
| `finance@demo.local` | Finanzas | `demo12345` |
| `readonly@demo.local` | Solo lectura | `demo12345` |

> Estas credenciales son **solo de desarrollo local**. NUNCA usar en producción.

---

## 8. Cómo correr (dev local)

**Backend** (Docker, desde `MailySoft/`):
```bash
docker compose up           # levanta backend (:8000), db, redis, celery
docker compose exec backend python manage.py migrate
```

**Frontend** (desde `MailySoft/web-soft/`):
```bash
npm install
npm run dev                 # :5173 (o el siguiente puerto libre)
```
El proxy de Vite reenvía `/api` y `/media` al backend. Entra con un usuario de la tabla de arriba.

> Ojo: si cambias `vite.config.ts`, **reinicia** `npm run dev` (la config no recarga en caliente).

---

## 9. Pendientes / próximos pasos

- **django-tester del último bloque**: reactivar/reagendar, modalidad, reglas del médico (self + consultorios M2M), creación atómica paciente+cita, alerta de seguimiento — aún sin suite formal (el resto del backend: 1013 tests).
- **Detección/fusión de duplicados de persona** al agendar "paciente nuevo" (avisar si ya existe alguien con ese nombre/teléfono y ofrecer usar el existente).
- **Recordatorios reales**: hoy el envío de WhatsApp es `SimulatedWhatsAppAdapter` (solo loguea). Falta `MetaWhatsAppAdapter` con credenciales. Mismo motor serviría para los **avisos de cita offline** (push) de la alerta de seguimiento.
- **Especialidad/cédula al alta del médico** (quick win): hoy se capturan en la ficha, no en el form de "Nuevo miembro".
- **Catálogo configurable de especialidades** (D-12): después del expediente clínico.
- **Horarios del doctor** (UI). **Reagendar cita** ya tiene UI.
- **Finanzas**: conectar al backend (módulo por construir).
- **Panel de plataforma** (dueño SaaS): construir backend + conectar.
- **Expediente clínico** (notas médicas, padecimientos): módulo médico por construir.
- **Endurecimiento prod**: IP real de auditoría vía proxy confiable (XFF), CSP, revisar `/verify/`.

---

## 10. Convenciones y dónde mirar

- **Estándares de código backend**: `.claude/skills/django-clean-architecture/SKILL.md`.
- **Estándares de conexión frontend**: `.claude/skills/react-frontend-connect/SKILL.md`.
- **Decisiones formales**: `docs/adr/` + [`DECISIONES-CLAVE.md`](DECISIONES-CLAVE.md).
- **Diseño/planes**: `docs/design/`.
- **Reportes por fase**: `docs/reports/`.
