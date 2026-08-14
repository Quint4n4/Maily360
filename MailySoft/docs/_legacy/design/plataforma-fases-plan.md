# Portal de Plataforma (super-admin) — Plan por fases

> Fecha: 2026-07-02 · Estado: Fase 0 y Fase 1 en ejecución
> Documentos relacionados: `plataforma-portal.md`, `audit-modelo-datos.md`,
> `pgbouncer-rls-escalabilidad.md`, `adr/0003-aislamiento-multi-tenant-shared-rls.md`

## 1. Qué tenemos hoy (auditado 2026-07-02)

### Backend (`apps/plataforma`) — ✅ funcional con datos reales

| Endpoint | Método | Roles | Datos |
|---|---|---|---|
| `/api/v1/plataforma/metricas/` | GET | super_admin, sales, engineering | Reales (conteos globales) |
| `/api/v1/plataforma/clinicas/` | GET | super_admin, sales, engineering | Reales (lista + counts) |
| `/api/v1/plataforma/clinicas/` | POST | super_admin, sales | Real (alta atómica tenant+dueño+semilla) |
| `/api/v1/plataforma/clinicas/<id>/` | GET | super_admin, sales, engineering | Reales (ficha + miembros) |
| `/api/v1/plataforma/clinicas/<id>/estado/` | POST | super_admin, sales | Real (suspender/reactivar, auditado) |
| `/api/v1/plataforma/usuarios/` | GET | super_admin | Reales (staff de Maily) |

- 40 tests (23 alta de clínica + 17 seguridad). Sin TODOs.
- Cross-tenant vía `PlatformAPIView` (no setea GUC → RLS deja pasar) + `Model.all_objects`.
- Auditoría existente: registra `TENANT_CREATE` y `TENANT_STATUS_CHANGE` en `apps/audit`.

### Frontend (portal dentro de `web-soft`, rutas `/plataforma/*`)

| Pantalla | Estado |
|---|---|
| Dashboard | ✅ API real (`usePlatformMetrics`) |
| Clínicas (lista/alta/ficha/estado) | ✅ API real |
| Usuarios (equipo Maily) | ✅ API real |
| **Suscripciones** | ⚠️ MAQUETA (planes y clínicas hardcodeados en `data/clinicas.ts`) |
| **Sistema** | ⚠️ MAQUETA (uptime/servicios/incidentes inventados) |

- Base técnica buena: TypeScript estricto, TanStack Query, cliente HTTP tipado con
  refresh automático, tokens en memoria + cookie httpOnly + CSRF, responsivo con BottomNav.
- `web-platform/` está vacío: el portal vive en `web-soft` (decisión vigente).

### Lo que NO existe todavía

1. **Auditoría cross-tenant en el portal** — `apps/audit` es por-tenant; el portal no puede
   ver qué está pasando en las clínicas (el pedido principal: ver la actividad real del primer tenant).
2. **Suscripciones/planes reales** — no hay modelo `Plan`/`Subscription`; solo `Tenant.status` + `trial_ends_at`.
3. **Sistema con salud real** — no hay endpoint de healthcheck agregado (BD/Redis/Celery).
4. **Gestión del equipo de plataforma** — solo listado; no hay alta/edición/desactivación de staff.
5. **Brechas de seguridad conocidas** (de auditorías previas):
   - 4 tablas sin RLS: `notas_notes`, `agenda_item_notes`, `agenda_blocks`, `agenda_appointment_types`.
   - pgbouncer en modo transacción + GUC de sesión → migrar a `SET LOCAL` (doc P0).
   - Falta forzar cambio de contraseña temporal en el primer login del dueño.
6. **Tipos del frontend generados de OpenAPI** — hoy se mantienen a mano.

## 2. Metodología (aplica a TODAS las fases)

Cada fase se trabaja con los subagentes especialistas y no se da por terminada sin:

1. **django-engineer / frontend** implementa siguiendo `django-clean-architecture` y
   `react-frontend-connect` (capas, tipado, sin secretos, backend = autoridad de permisos).
2. **django-tester** escribe/asegura pruebas pytest (≥80% del código de negocio nuevo,
   siempre incluyendo casos de permisos y aislamiento multi-tenant).
3. **django-reviewer** revisa el diff contra los estándares.
4. **django-security** audita: secretos, inyección, permisos, aislamiento cross-tenant,
   PII en logs, configuración de producción.
5. `pytest` completo verde + `tsc`/`vite build` verdes.
6. Documentación actualizada (este archivo + `ESTADO-DEL-PROYECTO.md`).
7. Commit local (push solo cuando el dueño lo pida).

## 3. Fases

### Fase 0 — Candados de seguridad multi-tenant (P0, corta) — ✅ HECHA (2026-07-02)

Objetivo: cerrar las brechas conocidas antes de construir encima.

- [x] Migraciones `enable_rls` para las 4 tablas sin RLS (`notas/0002`, `agenda/0012`),
      con `WITH CHECK` desde el origen.
- [x] Hallazgo ampliado por la auditoría de seguridad de este ciclo: **17 tablas
      preexistentes** tenían policy solo-USING (INSERT sin restricción a nivel BD,
      mismo defecto ALTO-2 que expediente corrigió en su 0005). Cerrado con
      migraciones `rls_with_check` en agenda (0013), finanzas (0003),
      notificaciones (0005), pacientes (0014) y personal (0007).
      Verificado en Postgres: 0 policies `ALL` sin `WITH CHECK`.
- [x] Test guardián `apps/core/tests/test_rls_coverage.py`: toda tabla tenant-aware
      debe tener RLS habilitado+forzado, al menos una policy, y cobertura de INSERT
      (`WITH CHECK`) — falla en CI si una app nueva olvida su migración.
- [x] Evaluación de `SET LOCAL` (pgbouncer): el cambio de código son 2 archivos
      (`core/middleware.py`, `core/views.py`), pero requiere garantizar transacción
      por request (`ATOMIC_REQUESTS` o equivalente) — sin eso, el fallback IS NULL
      ABRIRÍA acceso cross-tenant. Riesgo medio-alto → queda como tarea previa a
      escalar el piloto (Fase 5), NO se hace en caliente.

### Fase 1 — Auditoría cross-tenant en el portal (el panel "vivo") — ✅ HECHA (2026-07-02)

> Implementada completa (backend + frontend + 20 tests + revisión de código APROBADA
> + auditoría de seguridad). Pendientes de seguimiento anotados al final de la fase.

Objetivo: que el super-admin vea DESDE YA la actividad real de las clínicas
(el primer tenant en producción) desde el portal.

Backend:
- [ ] `GET /api/v1/plataforma/auditoria/` — bitácora cross-tenant paginada.
  - Filtros: `tenant_id`, `action`, `actor_id`, `date_from`, `date_to`, `search`.
  - Respuesta por evento: `id, created_at, action, action_display, actor_email,
    actor_role, tenant_id, tenant_name, resource_type, resource_id, description,
    ip_address, metadata` (la bitácora ya está diseñada SIN PII clínica).
  - Permisos: `PlatformAuditPermission` → **super_admin y engineering** (sales NO:
    la bitácora es operativa/técnica). Solo lectura; la tabla sigue append-only.
  - Selector con `AuditLog.all_objects` + `select_related` (actor, tenant), orden `-created_at`.
- [ ] Resumen para el dashboard: últimos N eventos globales (o el mismo endpoint con `page_size` chico).

Frontend:
- [ ] Nueva página `/plataforma/auditoria` (módulo `auditoria` en `platform/permisos.ts`:
      super_admin `view`, engineering `view`).
  - Tabla desktop + tarjetas móvil (mismo patrón que Usuarios), filtros por clínica,
    acción y rango de fechas, búsqueda, paginación.
  - Entrada en el topbar y en BottomNav móvil.
- [ ] Bloque "Actividad reciente" en el Dashboard del portal (últimos eventos reales).

Tests: permisos (miembro de clínica 403, sales 403, engineering 200 lectura,
super_admin 200), visibilidad cross-tenant (eventos de 2 tenants), filtros y paginación,
inmutabilidad intacta. → `apps/plataforma/tests/test_auditoria.py` (20 tests).

Subagentes: django-engineer + frontend en paralelo (contrato fijado arriba) →
django-tester → django-reviewer → django-security. Ciclo completo ejecutado.

Seguimiento anotado por los revisores (no bloqueante, atender antes de escalar):
- Índice para queries cross-tenant en `AuditLog` (`-created_at` global; hoy todos
  los índices tienen `tenant` como prefijo → seq scan con volumen alto).
- La búsqueda cubre descripción y email del actor (el placeholder ya se ajustó).
- Deuda mypy preexistente en `apps/plataforma/serializers.py` (patrón repetido en
  las 9 clases previas; mypy es informativo, no bloqueante).

### Fase 2 — "Sistema" con salud real — ✅ HECHA (2026-07-02)

Objetivo: sustituir la maqueta de SistemaPage por datos reales.

- [x] `GET /api/v1/plataforma/sistema/` (`PlatformSystemPermission`: super_admin y
      engineering; sales 403): ping cronometrado a PostgreSQL (`SELECT 1` con
      `SET LOCAL statement_timeout=3s`) y Redis (timeout 2s, conexión de django-redis,
      cero URLs hardcodeadas), ping al worker Celery (`control.ping` timeout 2s),
      versión (commit de Railway/Django/Python/entorno) y cola de PDFs (conteos
      reales de PdfJob en una sola query agregada). Checks aislados: un servicio
      caído nunca tira el endpoint (responde 200 con down/degraded).
      Lógica en `apps/plataforma/system_health.py`; 25 tests en `tests/test_sistema.py`.
- [x] Seguridad (hallazgo ALTO de la auditoría de este ciclo, corregido): el
      `detail` de un servicio caído es un mensaje genérico — el texto crudo de la
      excepción (puede incluir hostname interno, puerto y usuario de BD) va SOLO
      a logs del servidor. Test que lo blinda.
- [x] Frontend: SistemaPage conectada (banner de estado global, cards por servicio
      con latencia, cola de PDFs con alerta de fallidos, versión, refresco cada 30s);
      eliminados el uptime inventado y los incidentes ficticios (ahora enlaza a Auditoría).
- Seguimiento no bloqueante: cachear el snapshot 5-10s si crecen los usuarios del
  panel; índice parcial para `PdfJob(status=failed, updated_at)` si crece la tabla;
  paralelizar los pings si se agregan más checks.

### Fase 3 — Suscripciones y planes reales — ✅ HECHA (2026-07-02)

Objetivo: que SuscripcionesPage deje de ser maqueta y los vencimientos se vigilen solos.

- [x] Modelos en `apps/tenancy`: `Plan` (sembrado con Básico $1500 / Pro $4500 /
      Premium $8900 de la maqueta) y `TenantSubscription` (OneToOne con tenant,
      plan, ciclo mensual/anual, fin de periodo). Deliberadamente NO TenantAware
      (catálogo/gestión exclusiva de plataforma; documentado en los docstrings).
- [x] Endpoints (`PlatformSubscriptionPermission`: solo super_admin y sales):
      `GET /plataforma/planes/`, `GET /plataforma/suscripciones/` (con `alerta`
      trial_vencido/trial_por_vencer/periodo_vencido/periodo_por_vencer),
      `GET /plataforma/suscripciones/resumen/` (conteos por plan, alertas, MRR)
      y `POST /plataforma/clinicas/<id>/suscripcion/` (asignar/cambiar plan,
      auditado con `SUBSCRIPTION_CHANGE`).
- [x] Tarea Celery beat diaria `plataforma.avisar_vencimientos` (8:00 CDMX):
      **SOLO AVISA** — registra `TRIAL_EXPIRED`/`SUBSCRIPTION_EXPIRED` en la
      bitácora, idempotente, respeta extensiones/renovaciones y NUNCA toca
      `Tenant.status`. **Decisión del dueño (2026-07-02): la suspensión/
      cancelación es MANUAL; el sistema únicamente avisa cuando la fecha ya pasó.**
      Nota: django_celery_beat no está instalado; beat usa CELERY_BEAT_SCHEDULE
      estándar (compose ya tiene el perfil `beat`).
- [x] Frontend: SuscripcionesPage real (banner de vencidas con leyenda "la
      suspensión es manual", KPIs con MRR, cards de planes con conteos, tabla con
      alertas, filtros, modal Asignar/Cambiar plan) + aviso en el Dashboard.
- [x] 55 tests nuevos (`test_suscripciones.py`); revisión APROBADA y auditoría de
      seguridad SEGURO PARA DESPLEGAR.
- Seguimiento no bloqueante: unificar los frozensets de roles duplicados entre
  `services.py` y `permissions.py` (una sola fuente de verdad); `bulk_update` en
  la tarea de avisos si el número de clínicas crece a cientos.

#### Fase 3.1 — Gestión del catálogo de planes — ✅ HECHA (2026-07-02)

Pedido del dueño: poder agregar y editar los planes desde el portal.

- [x] `POST /plataforma/planes/` y `PATCH /plataforma/planes/<id>/` — escritura
      SOLO super_admin (`PlatformPlanWritePermission`, fuente única de roles
      `_PLATFORM_ROLES_SUPER_ADMIN_ONLY`); sales sigue leyendo/asignando.
      Slug generado del nombre (único con sufijos, respaldo unique en BD e
      IntegrityError→400) e INMUTABLE al renombrar. Sin DELETE: solo desactivar
      (`is_active=false`; PROTECT desde TenantSubscription). Los inactivos se
      listan en el GET (para reactivarlos) pero la asignación los rechaza.
      Auditado con `PLAN_CREATE`/`PLAN_UPDATE` (precio old→new en metadata).
- [x] Frontend: botón "Nuevo plan" + lápiz por card (solo super_admin, módulo
      `planes` en permisos.ts), PlanFormModal (nombre, precio, descripción,
      características editables, Popular, activo, orden); inactivos atenuados
      con badge y excluidos del dropdown de asignación.
- [x] 45 tests nuevos (`test_planes_crud.py`); revisión APROBADA y seguridad
      SEGURO PARA DESPLEGAR; correcciones menores de ambos aplicadas (tope de
      2000 chars en descripción, máx. 50 características, excepción específica
      en test, test renombrado).

### Fase 4 — Gestión del equipo de plataforma y cuentas — ✅ HECHA (2026-07-02)

- [x] Alta/edición/desactivación de staff (SOLO super_admin, `PlatformStaffWritePermission`):
      contraseña temporal criptográfica mostrada una vez, anti-lockout (nadie se
      auto-desactiva/degrada; protegido el ÚLTIMO super_admin activo), reset de
      contraseña con invalidación real de refresh tokens (token_blacklist, test
      de regresión e2e), 404 uniforme para usuarios de clínica y pre-check de
      email acotado al namespace de plataforma (sin enumeración). Auditoría
      STAFF_CREATE/UPDATE/PASSWORD_RESET sin contraseñas.
- [x] Cambio de contraseña forzado en primer login (staff y dueños de clínica):
      `User.must_change_password` + `POST /auth/change-password/` (rota la cookie
      de refresh propia para no matar la sesión) + enforcement central en
      TenantAPIView/PlatformAPIView (403 `password_change_required` en TODO
      endpoint de negocio; authn exento por diseño; seeds demo/E2E en False).
      Throttle dedicado 10/min en change-password y reset-password (hallazgo
      ALTO de la auditoría de este ciclo, corregido).
- [x] Frontend: StaffFormModal, acciones por fila en UsuariosPage (fila propia
      protegida), pantalla /cambiar-contrasena con redirección forzada central
      (clínica y portal) + listener del 403 en el cliente http.
- [x] 72 tests nuevos; revisión APROBADA; auditoría de seguridad con ALTO/MEDIO
      corregidos en el mismo commit.
- [ ] (Sigue opcional) Impersonación "entrar como la clínica" para soporte,
      SIEMPRE auditada y con banner visible — pendiente de decisión del dueño.

### Fase 5 — Calidad continua del portal — ✅ HECHA (2026-07-03)

Hecha en tres olas, cada una con su verificación:

- [x] **Seguimientos técnicos** acumulados de fases previas: índice global
      `-created_at` en AuditLog (consultas cross-tenant del panel), roles de
      plataforma unificados en una sola fuente (sin frozensets duplicados),
      tarea de avisos con `bulk_update` en vez de `save()` por fila.
- [x] **E2E Playwright del portal** (`web-soft/e2e/plataforma.spec.ts`, 9 pruebas
      verdes): login staff → dashboard → alta de clínica (captura de contraseña
      temporal) → auditoría → asignación de plan → permisos por rol → flujo de oro
      del cambio de contraseña forzado. Seed `seed_e2e_user --platform`.
- [x] **Tipos generados desde OpenAPI**: pipeline drf-spectacular →
      openapi-typescript (schema en `web-soft/openapi/schema.yml`, script
      `npm run types:api`, `src/types/openapi.d.ts`); 13 vistas de plataforma
      anotadas con `@extend_schema`; los tipos de salida del portal derivan del
      schema. Los inputs de formularios quedan a mano (documentado).
- [x] **Preparación pgbouncer (`SET LOCAL`)** — el P0 de escalabilidad, hecho con
      MÍNIMO RIESGO: feature flag `DB_TENANT_GUC_MODE` (`session` default = 100%
      el comportamiento actual / `local` = SET LOCAL en transacción por request
      para pool de pgbouncer). Un único punto de fijado del GUC (`apply_tenant_guc`),
      atomic condicional en el middleware, 16 tests incluyendo el de no-fuga
      (SET LOCAL no sobrevive al commit). Suite completa verde en modo default.
      **NO activado** — el código queda listo; ver checklist en
      `pgbouncer-rls-escalabilidad.md` para activarlo (rol NOSUPERUSER, flag a
      `local`, carga con pgbouncer real, despliegue).

Hallazgos abiertos que dejó esta fase (fuera de alcance, anotados para seguimiento):
- **Rol de conexión SUPERUSER en dev/test**: Postgres exime a superusers de RLS
  aun con FORCE. Verificar que el rol de PRODUCCIÓN (Railway) sea NOSUPERUSER para
  que RLS funcione como segunda barrera real. **Importante antes de escalar.**
- `apps/agenda/reminders.py` encola con `apply_async` sin `transaction.on_commit`
  (a diferencia de pdfs/recetas); alinear antes de activar el modo `local`.
- Pulido móvil pendiente del plan responsive (Fases 3-5 de `project responsive`).

## 4. Orden y dependencias

```
Fase 0 (seguridad) ──┐
                     ├─→ Fase 2 (sistema) ─→ Fase 3 (suscripciones) ─→ Fase 4 (equipo) ─→ Fase 5 (calidad)
Fase 1 (auditoría) ──┘
```

Fase 0 y 1 van juntas ahora. Las fases 2-5 se arrancan una por una, cada una con su
ciclo completo de subagentes y su commit local.
