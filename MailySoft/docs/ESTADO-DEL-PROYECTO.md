# Estado del Proyecto — Maily Soft (backend)

> Foto consolidada del proyecto. Actualizado: 2026-06-05 · Para dueño + cualquier dev nuevo.
> Esta es la referencia rápida para entender **dónde está el proyecto hoy**.

## 1. Resumen

**Maily Soft** es el backend de una plataforma SaaS de gestión clínica **multi-tenant**: muchas clínicas usan el mismo software, con sus datos totalmente aislados. Está en fase de **MVP clínico (backend)**: ya permite el flujo de operación diaria de una clínica — registrar pacientes, dar de alta médicos/consultorios/horarios, agendar citas con estados y anti-empalme, recordatorios, y todo auditado por rol.

| | |
|---|---|
| **Stack** | Django 5 + DRF · PostgreSQL 16 · Redis · Celery · Docker |
| **Estado** | Backend MVP clínico funcional + cumplimiento base (NOM-024/LFPDPPP) |
| **Apps Django** | 7 (core, tenancy, authn, pacientes, personal, agenda, audit) |
| **Tests** | 594 · cobertura ~96.7% |
| **Commits** | 18 · repo: github.com/Quint4n4/Maily360 |
| **Frontend** | En desarrollo aparte (web-soft, React+Vite); consume esta API |

## 2. Arquitectura en un vistazo

- **Modular Monolith**: un solo backend dividido en apps por dominio.
- **Multi-tenant: Shared Database + Row Level Security** (ver [ADR-0003](adr/0003-aislamiento-multi-tenant-shared-rls.md)). Cada fila lleva `tenant_id`; **doble barrera** de aislamiento: (1) `TenantManager` filtra en Django, (2) RLS de PostgreSQL lo refuerza en la base de datos.
- **Arquitectura por capas**: `URLs → Views (delgadas) → Serializers → Services/Selectors → Models`. La lógica vive en services/selectors.
- **Identidad**: JWT (SimpleJWT) + contraseñas Argon2.
- **Decisiones formales**: [ADR-0001 stack](adr/0001-stack-y-arquitectura.md) · [ADR-0002 multi-tenant](adr/0002-arquitectura-multi-tenant.md) · [ADR-0003 shared+RLS](adr/0003-aislamiento-multi-tenant-shared-rls.md).
- **Estándares de código**: ver `.claude/skills/django-clean-architecture/SKILL.md` (tipado, sin secretos, CRUD seguro).

## 3. Módulos (apps) construidos

| App | Qué hace | Tests | Estado |
|---|---|---:|---|
| `core` | Cimiento: TenantAwareModel, TenantManager, middleware, TenantAPIView, permisos por rol, request context | 80 | ✅ |
| `tenancy` | Clínicas (Tenant) y membresías (TenantMembership) con 7 roles | 16 | ✅ |
| `authn` | Usuario custom (email), login JWT con auditoría, endpoint `/me/` | 16 | ✅ |
| `pacientes` | Pacientes + numerador de expediente consecutivo por clínica | 61 | ✅ |
| `personal` | Doctores, consultorios, horarios de atención | 78 | ✅ |
| `agenda` | Citas (máquina de estados + anti-empalme doble), config por clínica, recordatorios WhatsApp (simulados) | 117 | ✅ |
| `audit` | Bitácora append-only NOM-024: quién accede/modifica qué | 59 | ✅ |

## 4. Mapa de endpoints REST (hoy)

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

Toda entidad de negocio hereda de `TenantAwareModel` (UUID, timestamps, soft delete, `tenant_id`) y tiene política RLS en PostgreSQL.

## 7. Seguridad y cumplimiento

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
- Finanzas / estado de cuenta / CFDI 4.0.
- Inventario.
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
|---|---|---|
| 1 — Cimientos | Scaffolding + multi-tenant (core/tenancy/authn) | [fase-1-cimientos.md](reports/fase-1-cimientos.md) |
| 3 — Agenda | Pacientes + personal + agenda (citas/estados/anti-empalme) + recordatorios | [fase-3-agenda.md](reports/fase-3-agenda.md) |
| 4 — Permisos + Auditoría | `/me/` + permisos por rol + bitácora NOM-024 | [fase-4-permisos-y-auditoria.md](reports/fase-4-permisos-y-auditoria.md) |
