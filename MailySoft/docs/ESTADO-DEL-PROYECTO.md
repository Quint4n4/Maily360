# Estado del Proyecto — Maily Soft / Maily360

> Foto consolidada **full-stack** (backend + frontend). Actualizado: **2026-06-09**.
> Referencia rápida para entender **dónde está el proyecto hoy** — para el dueño y para cualquier dev nuevo.
> Decisiones técnicas detalladas en [`DECISIONES-CLAVE.md`](DECISIONES-CLAVE.md).

---

## 1. Resumen

**Maily Soft / Maily360** es una plataforma SaaS **multi-tenant** de gestión de clínicas (muchas clínicas, mismo software, datos aislados). Migra de un sistema PHP legacy (`app.maily.mx`). Hoy es un **MVP clínico funcional de punta a punta**: el backend está construido y probado, y el frontend está **conectado al backend real** panel por panel (auth, pacientes, agenda, personal).

| | |
|---|---|
| **Stack backend** | Django 5 + DRF · PostgreSQL 16 · Redis · Celery · Docker |
| **Stack frontend** | React 18 + Vite + TypeScript + Tailwind + TanStack Query (carpeta `web-soft/`) |
| **Apps Django** | 8 (core, tenancy, authn, pacientes, personal, agenda, audit, **notas**) |
| **Tests backend** | **1009 pasando** (código commiteado, endurecido) |
| **Repo** | github.com/Quint4n4/Maily360 · rama `main` |
| **Cumplimiento** | NOM-024 / LFPDPPP (bitácora, minimización de PII, Argon2) |

---

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

---

## 3. Módulos backend (apps)

| App | Qué hace |
|---|---|
| **core** | Base multi-tenant (`TenantAwareModel`, `TenantManager`), permisos por rol (`HasClinicRole` y subclases), `TenantAPIView`, validación segura de imágenes (`files.py`). |
| **tenancy** | Tenants (clínicas) + `TenantMembership` (usuario↔clínica↔rol). **API de gestión de miembros** (alta, rol, bloqueo, restablecer contraseña, avatar). |
| **authn** | `User` custom (email login, Argon2), JWT híbrido (login/refresh/logout/verify), endpoint `/me/`, avatar de usuario. |
| **pacientes** | Expedientes (CRUD, búsqueda, baja lógica, número de expediente seguro). **Alta provisional** (al vuelo desde agenda). Avatar de paciente. |
| **personal** | Doctores, consultorios, horarios (CRUD). |
| **agenda** | Citas (crear, estados con máquina de estados, reagendar, anti-empalme doble). **Tipos de cita** configurables con color. **Eventos** (reuniones/bloqueos) con bloqueo real. Recordatorios (Celery). Config de agenda. |
| **audit** | Bitácora NOM-024: registra create/update/delete/login/bloqueo/etc. por actor, rol y tenant. |
| **notas** | Notas y tareas: personales (privadas, con recordatorio), globales del Dueño (a un rol o a todos), y tareas (hecho/pendiente). Notas colaborativas (hilo con autor) viven en `agenda` (AgendaItemNote). |

---

## 4. Frontend — estado panel por panel

| Panel | Estado | Detalle |
|---|---|---|
| **Login / sesión** | ✅ Real | Login JWT híbrido, rol real desde `/me/`, logout, refresh automático, avatar en Topbar. |
| **Pacientes** (antes "Contactos") | ✅ Real | Lista, búsqueda server-side, alta, **edición**, **baja**, **avatar**. Expediente con **próxima cita + historial reales** (conectado a la agenda). Alerta de "expediente provisional". |
| **Agenda** | ✅ Real | Calendario navegable, citas coloreadas por **tipo de cita**, **agendar** (paciente existente o **nuevo provisional**), **cambiar estado** (máquina de estados), **bloqueos/reuniones** (card unificado Cita/Bloqueo/Reunión, editable), **hilo de notas del equipo** en cada cita/evento, y widget **"Mis recordatorios"** (personal). |
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
| **Citas** — crear/editar | Dueño, Admin, Médico, Recepción |
| **Citas** — cancelar | Dueño, Admin, Recepción |
| **Citas** — cambiar estado | Dueño, Admin, Médico, Enfermería, Recepción |
| **Eventos** (reuniones/bloqueos) — crear/borrar | Dueño, Admin, Médico, Recepción |
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

- **Tests automatizados** de las features recientes (tipos de cita, eventos/bloqueos, expediente↔agenda). El resto del backend tiene 754 tests.
- **Commit + push** del bloque acumulado (tipos de cita, expediente↔agenda, eventos, card unificado).
- **Editar perfil médico** ya existe; falta **horarios del doctor** (UI).
- **Reagendar cita** (endpoint backend existe; falta UI).
- **Finanzas**: conectar al backend (módulo por construir).
- **Panel de plataforma** (dueño SaaS): construir backend + conectar.
- **Expediente clínico** (notas médicas, padecimientos): módulo médico por construir.
- **Especialidades como plugins**: pendiente (después del expediente clínico).
- **Endurecimiento prod**: IP real de auditoría vía proxy confiable (XFF), CSP, revisar `/verify/`.

---

## 10. Convenciones y dónde mirar

- **Estándares de código backend**: `.claude/skills/django-clean-architecture/SKILL.md`.
- **Estándares de conexión frontend**: `.claude/skills/react-frontend-connect/SKILL.md`.
- **Decisiones formales**: `docs/adr/` + [`DECISIONES-CLAVE.md`](DECISIONES-CLAVE.md).
- **Diseño/planes**: `docs/design/`.
- **Reportes por fase**: `docs/reports/`.
