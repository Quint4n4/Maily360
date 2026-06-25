# Estado del Proyecto — Maily Soft / Maily360

> Foto consolidada **full-stack** (backend + frontend). Actualizado: **2026-06-25**.
> Referencia rápida para entender **dónde está el proyecto hoy** — para el dueño y para cualquier dev nuevo.
> Decisiones técnicas detalladas en [`DECISIONES-CLAVE.md`](DECISIONES-CLAVE.md).

---

## 1. Resumen

**Maily Soft / Maily360** es una plataforma SaaS **multi-tenant** de gestión de clínicas (muchas clínicas, mismo software, datos aislados). Migra de un sistema PHP legacy (`app.maily.mx`). Hoy es un **MVP clínico funcional de punta a punta**: el backend está construido y probado, y el frontend está **conectado al backend real** panel por panel (auth, pacientes, agenda, personal, expediente, recetas, **finanzas**).

| | |
|---|---|
| **Stack backend** | Django 5 + DRF · PostgreSQL 16 · Redis · Celery · Docker |
| **Stack frontend** | React 18 + Vite + TypeScript + Tailwind + TanStack Query (carpeta `web-soft/`) |
| **Apps Django** | 12 (core, tenancy, authn, pacientes, personal, agenda, audit, notas, notificaciones, **clinica**, **recetas**, **finanzas**) |
| **Tests backend** | Suite en verde — ver `pytest -q` para cifra actualizada (las cifras de hitos anteriores son históricas) |
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
| **pacientes** | Expedientes (CRUD, búsqueda, baja lógica, número de expediente seguro). **Alta provisional** (al vuelo desde agenda). Avatar. **Etiquetas M2M** (`categories`) con catálogo por clínica; Favorito/VIP como etiquetas del sistema. Filtros por segmento (Recientes, Semana, Mes, Rango, Potenciales, Favoritos, VIP, etiqueta custom). |
| **personal** | Doctores (con **consultorios asignados** M2M y especialidad), consultorios, horarios (CRUD). |
| **agenda** | Citas (crear, estados con máquina de estados, reagendar, anti-empalme doble). **Tipos de cita** configurables con color. **Eventos** (reuniones/bloqueos) con bloqueo real. Recordatorios (Celery). Config de agenda. |
| **audit** | Bitácora NOM-024: registra create/update/delete/login/bloqueo/etc. por actor, rol y tenant. |
| **notas** | Notas y tareas: personales (privadas, con recordatorio), globales a un rol o a todos, y tareas (hecho/pendiente). Notas colaborativas (hilo con autor) viven en `agenda` (AgendaItemNote). |
| **notificaciones** | Avisos in-app por fan-out on write. Modelo `Notification` con RLS. Tipos: `meeting`, `team_note`, `role_note`, `broadcast`, **`credential_review`**, **`credential_result`** (2026-06-23). Services: `notification_fanout`, `notification_mark_read`, `notification_mark_all_read`. |
| **clinica** | Configuración de Mi Consultorio. `ClinicSettings` (logo, membrete, config de receta). `DoctorCredential` con **validación híbrida** (pendiente/validada/rechazada): el doctor captura, el admin valida, solo las validadas salen en la receta. `PatientCategory` con `kind` (custom/favorite/vip): catálogo de etiquetas de pacientes. Plantillas de texto (`ClinicTemplate`). |
| **recetas** | Recetas médicas inmutables (crear, anular con motivo, historial, PDF, copia de previa). Catálogo de medicamentos (global + custom por clínica). PDF con **WeasyPrint**: 2 formatos base (`compact` Farmacia / `digital` Paciente), 4 estilos de fondo (`ondas`/`minimal`/`barra`/`geometrico`), personalización de color, tipografía y secciones. Al emitir se generan **ambas versiones**. Módulo de medicamentos controlados (grupo COFEPRIS, folio, vigencia). |
| **finanzas** | Facturación y cobranza (integrado 2026-06-25). Catálogo de **conceptos** cobrables con claves SAT, **configuración fiscal** del emisor (RFC, razón social, régimen, serie/folio), **cotizaciones** (con enviar/aceptar), **cargos** (cuentas por cobrar), **pagos** con asignación a cargos (`PaymentAllocation`), **estado de cuenta** por paciente, **CFDI 4.0** (emitir/consultar/cancelar) y **dashboard** de métricas. Arquitectura por capas + RLS, como el resto. |

---

## 4. Frontend — estado panel por panel

| Panel | Estado | Detalle |
|---|---|---|
| **Login / sesión** | ✅ Real | Login JWT híbrido, rol real desde `/me/`, logout, refresh automático, avatar en Topbar. |
| **Pacientes** (antes "Contactos") | ✅ Real | Lista, búsqueda server-side, alta, **edición**, **baja**, **avatar**. Expediente con **próxima cita + historial reales**. Alerta de "expediente provisional". **Filtros por segmento** (Recientes/Semana/Mes/Rango/Potenciales/Favoritos/VIP). **Etiquetas de paciente** (catálogo M2M; Favorito/VIP son etiquetas del sistema con estrella/corona; etiquetas custom; filtro por etiqueta). Asignación al editar paciente. |
| **Agenda** | ✅ Real | Calendario navegable; citas por **tipo de cita** (color) y **modalidad** (presencial/teléfono/video/fuera, con columna fija **Telemedicina/Externo**); **agendar** (existente o **nuevo provisional atómico**); **cambiar estado** (máquina de estados); **reactivar/reagendar** (cancelada se ve con rayas rojas + "CANCELADA"); **bloqueos/reuniones** (card unificado, editable); **hilo de notas del equipo**; widget **"Mis recordatorios"**; **alerta de seguimiento** que guía el estado de las citas del día. El **médico** ve solo sus consultorios y citas; la **enfermería** cambia estado pero no agenda. |
| **Notas y Tareas** | ✅ Real | Tarjetas de colores: **Mis notas/tareas** (con recordatorio, fijar, marcar hecha) y **Avisos de la clínica** (globales del Dueño a un rol o a todos). |
| **Personal** | ✅ Real | Pestañas: **Equipo** (miembros por rol → ficha → editar/bloquear/contraseña/avatar/perfil médico), **Consultorios** (CRUD), **Tipos de cita** (CRUD con color). |
| **Notificaciones — Campana** | ✅ Real | `CampanaNotificaciones.tsx` en Topbar: badge de no leídas, dropdown, marcar una/todas leídas, navega al objeto destino según `target_type`. Polling 30 s. Incluye notificaciones de credenciales (2026-06-23). |
| **Notificaciones — Luz recordatorios** | ✅ Real | `LuzRecordatorios.tsx` en `App.tsx`: luz amarilla parpadeante cuando hay recordatorios de hoy vencidos. Snooze de 4 h persiste en localStorage. |
| **Mi Consultorio — Recetas** | ✅ Real | Configuración del formato de receta: 2 bases (`compact`/`digital`), 4 estilos de fondo, color de acento, tipografía, secciones, modo membrete. Vista previa en vivo. |
| **Mi Consultorio — Credenciales** | ✅ Real | El médico captura credenciales académicas; el admin las valida/rechaza con motivo. Badge de estado. Solo las validadas salen en la receta impresa. |
| **Expediente — Recetas** | ✅ Real | Crear receta (buscador de medicamentos, renglones, recomendaciones, signos vitales, copia de previa). Historial. Botones **"Farmacia"** (media carta) y **"Paciente"** (carta completa). Anular con motivo. |
| **Finanzas** | ✅ Real | `FinanzasPage` con 5 pestañas conectadas al backend: **Dashboard** (métricas + gráficas con `recharts`, rango 7/30/90 días), **Cobros y pagos**, **Cotizaciones**, **CFDI** y **Estado de cuenta** (exportable a **PDF**/**Excel** con `jspdf`/`xlsx`). Las pestañas visibles se filtran por rol (UX; el backend es la autoridad). |
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
| **Recetas** — ver | Dueño, Admin, Médico, Enfermería **(Recepción/Finanzas NO — DR-6)** |
| **Recetas** — crear / anular | **Médico** (anular: el médico emisor o Dueño/Admin; validación fina en el servicio) |
| **Formatos de receta** — ver | Todos · **configurar (crear/editar/borrar)** | Dueño, Admin (el Médico puede crear su propio formato personal) |
| **Credenciales del médico** — capturar / solicitar revisión | El propio **Médico** (Dueño/Admin también pueden) |
| **Credenciales del médico** — **validar / rechazar** | Solo Dueño, Admin |
| **Catálogo de etiquetas de pacientes** — ver | Todos · **crear/borrar** | Dueño, Admin |
| **Etiquetas a un paciente · Favorito/VIP** | Dueño, Admin, Médico, Enfermería, Recepción (igual que editar paciente) |
| **Finanzas — dashboard** (métricas/reportes) | Dueño, Admin, Finanzas, Solo lectura **(Recepción NO)** |
| **Finanzas — conceptos/cotizaciones/cargos/pagos/estado de cuenta** — ver | Dueño, Admin, Finanzas, Recepción, Solo lectura |
| **Conceptos cobrables · Configuración fiscal** — crear/editar | Solo Dueño, Admin |
| **Cotizaciones · Pagos** — crear/registrar (caja) | Dueño, Admin, Finanzas, Recepción |
| **Cargos · CFDI** — crear/emitir/cancelar | Dueño, Admin, Finanzas **(Recepción NO factura)** |

> Regla base: sin membresía activa → **403** en todo. El staff de plataforma sin membresía también (opera vía Django admin).

---

## 6. Features clave construidas (resumen)

- **Conexión frontend↔backend** completa (auth híbrida, refresh automático, TanStack Query, tipos de API).
- **Pacientes**: CRUD real + **expediente provisional** + **etiquetas de paciente** (catálogo M2M por clínica; Favorito/VIP como etiquetas del sistema imborrables con marcado de 1 clic; etiquetas custom libres asignadas al editar; filtro por etiqueta en el panel de chips).
- **Agenda**:
  - Calendario interactivo + citas reales por día.
  - **Tipos de cita configurables** (nombre + color) → la tarjeta de la cita se tiñe con el color del tipo.
  - **Máquina de estados** de citas (Agendada → Confirmada → En sala → En consulta → Atendida; + Cancelada / No asistió), validada en backend.
  - **Eventos: reuniones y bloqueos** — sin paciente, con alcance (toda la clínica / uno o varios consultorios / uno o varios doctores), todo el día o por horas. **Bloqueo REAL**: impide agendar citas encima.
  - **Card unificado**: al hacer clic en una casilla, eliges Cita / Bloqueo / Reunión en el mismo modal.
- **Expediente ↔ Agenda**: el expediente del paciente muestra su **próxima cita** y su **historial** reales; al cambiar el estado en la agenda, se refleja en el expediente.
- **Gestión de miembros (Equipo)**: alta de miembro con **contraseña robusta**, cambiar nombre/rol, **bloquear/reactivar** cuenta, **restablecer contraseña**, **perfil médico** (cédula/especialidad). Navegación: roles → usuarios → ficha.
- **Avatares**: subir foto de pacientes y personal (validación segura de imágenes), mostradas en tarjetas, fichas y Topbar.
- **Notificaciones in-app** (fan-out on write, polling 30 s):
  - Campana en Topbar: badge de no leídas, dropdown con lista, marcar leídas, navegación al objeto destino.
  - Luz amarilla parpadeante (`LuzRecordatorios`): recordatorios personales vencidos del día, con snooze de 4 h.
  - Seis tipos de notificación: `meeting`, `team_note`, `role_note`, `broadcast`, `credential_review` (aviso al admin de credencial por validar), `credential_result` (resultado al doctor). Todos best-effort.
  - Cuatro endpoints bajo `api/v1/notificaciones/`:

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/api/v1/notificaciones/` | Lista de notificaciones del usuario. Acepta `?only_unread=true`. |
| `GET` | `/api/v1/notificaciones/conteo/` | Número de notificaciones no leídas (para el badge). |
| `POST` | `/api/v1/notificaciones/leidas/` | Marca **todas** las notificaciones del usuario como leídas. |
| `POST` | `/api/v1/notificaciones/<id>/leida/` | Marca **una** notificación como leída (idempotente). |

- **Recetas médicas** (Fase B1 — completa al 2026-06-23):
  - Crear receta inmutable (buscador de medicamentos global + custom, renglones de tratamiento, recomendaciones, snapshot de signos vitales, copia de previa), anular con motivo, historial por paciente.
  - PDF con WeasyPrint: **2 formatos base** (`compact` Farmacia / `digital` Paciente), **4 estilos de fondo** (`ondas`/`minimal`/`barra`/`geometrico`), personalización por clínica (color de acento, tipografía, secciones, modo membrete).
  - Al emitir: se generan **ambas versiones** (botones "Farmacia" y "Paciente" en el historial).
  - **Validación híbrida de credenciales del médico**: el doctor captura → admin valida o rechaza con motivo → solo las validadas (`validation_status="validada"`) salen en el PDF. Notificaciones en la campana.
  - Medicamentos controlados (grupo COFEPRIS, folio oficial, vigencia automática).
- **Mi Consultorio** — configuración de recetas con vista previa en vivo; sección de credenciales del médico con bandeja de validación para el administrador.
- **Finanzas** (facturación y cobranza — integrado 2026-06-25):
  - **Catálogo de conceptos** cobrables con claves SAT (producto/unidad).
  - **Configuración fiscal** del emisor (RFC, razón social, régimen, serie y folios) — solo Dueño/Admin.
  - **Cotizaciones** con renglones, descuento y total; acciones **enviar** y **aceptar**.
  - **Cargos** (cuentas por cobrar) y **pagos** con asignación a cargos (`PaymentAllocation`).
  - **Estado de cuenta** por paciente, exportable a **PDF**/**Excel** desde el frontend.
  - **CFDI 4.0** (emitir / consultar / cancelar) con datos SAT (UUID, serie, folio, RFC receptor).
  - **Dashboard** de métricas y series para gráficas (`recharts`), con rango configurable.
  - Endpoints bajo `api/v1/finanzas/`:

| Método | Endpoint | Descripción |
|---|---|---|
| `GET/POST` | `/finanzas/conceptos/` · `/<id>/` | Catálogo de conceptos cobrables. |
| `GET/PATCH` | `/finanzas/config/` | Configuración fiscal del emisor. |
| `GET/POST` | `/finanzas/cotizaciones/` · `/<id>/` · `/<id>/enviar/` · `/<id>/aceptar/` | Cotizaciones y acciones de estado. |
| `GET/POST` | `/finanzas/cargos/` · `/<id>/` | Cargos / cuentas por cobrar. |
| `GET/POST` | `/finanzas/pagos/` · `/<id>/` | Cobros / pagos. |
| `GET` | `/finanzas/estado-cuenta/<patient_id>/` | Estado de cuenta de un paciente. |
| `GET/POST` | `/finanzas/cfdi/` · `/<id>/` · `/<id>/cancelar/` | CFDI 4.0 (emitir/consultar/cancelar). |
| `GET` | `/finanzas/dashboard/` | Métricas y series para el panel. |

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

- **Detección/fusión de duplicados de persona** al agendar "paciente nuevo" (avisar si ya existe alguien con ese nombre/teléfono y ofrecer usar el existente).
- **Recordatorios reales**: hoy el envío de WhatsApp es `SimulatedWhatsAppAdapter` (solo loguea). Falta `MetaWhatsAppAdapter` con credenciales. Mismo motor serviría para los **avisos de cita offline** (push) de la alerta de seguimiento.
- **Especialidad/cédula al alta del médico** (quick win): hoy se capturan en la ficha, no en el form de "Nuevo miembro".
- **Catálogo configurable de especialidades** (D-12): después del expediente clínico.
- **Finanzas** (✅ integrado 2026-06-25): conectado al backend (conceptos, cotizaciones, cargos, pagos, estado de cuenta, CFDI 4.0, dashboard). Pendiente menor: la lib `xlsx` (export a Excel) tiene CVE sin parche oficial → evaluar reemplazo (p. ej. `exceljs`); validar el flujo de CFDI contra el PAC real.
- **Panel de plataforma** (dueño SaaS): construir backend + conectar.
- **Recetas — pendientes normativos (COFEPRIS)**: campo estructurado de dosis/frecuencia/vía/duración; diagnóstico obligatorio/recomendado en la receta; validación de formato de cédula. Ver `recetas-formatos-plan.md §13`.
- **Recetas — fuentes de marca**: hoy solo Helvetica/Times (fuentes seguras para WeasyPrint). Embeber TTF de marca requiere fase adicional.
- **Etiquetas de paciente — UX secundaria**: asignar/quitar etiquetas desde el Expediente (hoy solo desde el formulario de edición). Filtro combinado (segmento + etiqueta).
- **Endurecimiento prod**: IP real de auditoría vía proxy confiable (XFF), CSP, revisar `/verify/`.
- **Dependencias con CVE (seguridad — prioridad alta)**: actualizar **Django 5.2.14 → 5.2.15** y **Pillow 10.4.0 → 12.2.0**.
- **Limpieza de tooling backend**: ruff/black/mypy no forman parte del flujo de CI actual; alinear configuración y agregar a `Makefile`. En `web-soft/`: migrar ESLint a configuración flat v9.
- **PII en títulos de notificación**: el título de una `team_note` incluye el nombre del paciente. Decidir si se mantiene (UX) o se anonimiza (LFPDPPP) y documentarlo en un ADR.

---

## 10. Convenciones y dónde mirar

- **Estándares de código backend**: `.claude/skills/django-clean-architecture/SKILL.md`.
- **Estándares de conexión frontend**: `.claude/skills/react-frontend-connect/SKILL.md`.
- **Decisiones formales**: `docs/adr/` + [`DECISIONES-CLAVE.md`](DECISIONES-CLAVE.md).
- **Diseño/planes**: `docs/design/`.
- **Reportes por fase**: `docs/reports/`.
