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

### Fase 3 — Suscripciones y planes reales

Objetivo: que SuscripcionesPage deje de ser maqueta y el trial se administre solo.

- Modelo mínimo en backend: `Plan` (nombre, precio, módulos incluidos) y
  `TenantSubscription` (tenant, plan, ciclo, vigencia, estado) — diseño alineado a lo
  que ya vende Maily (trial 60 días → anual con CFDI, ver `DECISIONES-CLAVE.md`).
- Endpoints plataforma: listar planes, asignar/cambiar plan de una clínica (super_admin, sales),
  listado de suscripciones con vencimientos.
- Tarea Celery beat: trials vencidos → aviso y/o suspensión automática (decisión de negocio:
  ¿suspender automático o solo alertar al equipo? — preguntar antes de implementar).
- Frontend: conectar SuscripcionesPage (planes reales, clínicas por plan, vencimientos).
- Auditoría: `SUBSCRIPTION_CHANGE` como nuevo ActionType.

### Fase 4 — Gestión del equipo de plataforma y cuentas

- Alta/edición/desactivación de staff de Maily desde el portal (solo super_admin),
  con contraseña temporal igual que las clínicas.
- Forzar cambio de contraseña temporal en primer login (dueños de clínica y staff).
- (Opcional, evaluar riesgos) Impersonación "entrar como la clínica" para soporte,
  SIEMPRE auditada y con banner visible — se decide con el dueño antes de construir.

### Fase 5 — Calidad continua del portal

- Tipos del frontend generados con drf-spectacular + openapi-typescript.
- E2E Playwright del portal (login staff → dashboard → alta clínica → auditoría).
- Pulido móvil pendiente del plan responsive (Fases 3-5 de `project responsive`).
- Carga: revisar pgbouncer/`SET LOCAL` si no se hizo en Fase 0, antes de sumar clínicas.

## 4. Orden y dependencias

```
Fase 0 (seguridad) ──┐
                     ├─→ Fase 2 (sistema) ─→ Fase 3 (suscripciones) ─→ Fase 4 (equipo) ─→ Fase 5 (calidad)
Fase 1 (auditoría) ──┘
```

Fase 0 y 1 van juntas ahora. Las fases 2-5 se arrancan una por una, cada una con su
ciclo completo de subagentes y su commit local.
