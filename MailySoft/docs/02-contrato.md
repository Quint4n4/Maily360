# Contrato técnico — Maily360 / MailySoft

> Define **cómo** funciona el sistema: modelo de datos, contrato de API, matriz de permisos y
> aislamiento de tenant. Es la **fuente de verdad** contra la que construyen `backend` y `frontend`.
>
> **Documento extraído, no diseñado.** Este contrato se produjo en la sesión A2 de adopción
> (`architect` en MODO INVERSO) leyendo el código de `MailySoft/backend/`. Describe **lo que el
> sistema hace hoy**, no lo que debería hacer. Donde la documentación previa contradecía al código,
> ganó el código y la diferencia quedó anotada en `docs/00-brechas.md`.

| | |
|---|---|
| Fecha de extracción | 2026-08-12 |
| Commit del código documentado | `ac4bc08` |
| Rama | `docs/adopcion-a1-analisis` |
| Alcance | `MailySoft/backend/` — 15 apps Django. El frontend no se documenta aquí |
| Entrada | `docs/01-analisis.md` (el *qué*), `docs/_legacy/` (archivo histórico) |
| Salida hermana | `docs/00-brechas.md` — donde el código contradice a la documentación |

## Cómo leer este documento

- **Cada afirmación lleva `archivo:línea`.** Si una afirmación no lo lleva, está marcada
  `**NO VERIFICADO**` con la razón. No hay una tercera categoría: lo que no se pudo verificar en el
  código no se afirmó.
- **La sección 1 es transversal y las demás la citan.** Antes de leer cualquier módulo, lee §1: el
  aislamiento de tenant, las clases de permiso y el sistema de módulos aplican a todo. Un módulo que
  dice "`EsMedicoOSuperior` (ver §1.3)" no está siendo perezoso: está evitando que existan dos
  descripciones del mismo permiso que en tres meses se contradigan.
- **Los números de línea envejecen.** Están anclados al commit `ac4bc08`. Si un número no cuadra,
  el nombre del símbolo sigue siendo válido: búscalo con `grep`.
- **Este documento no propone cambios.** Todo lo que está mal se documenta tal cual y se anota en
  `00-brechas.md`. Corregir mientras se documenta produce un contrato que no describe ni el sistema
  viejo ni el nuevo.

## Regla de mantenimiento

Si el código necesita contradecir este contrato, **se actualiza el contrato en el mismo PR**. Un
contrato desactualizado hace que el siguiente agente construya sobre una mentira.

## Índice

| § | Módulo | App(s) de Django |
|---|---|---|
| 1 | Capa transversal | `core`, `tenancy`, `clinica/sucursal_scope.py` |
| 2 | Pacientes | `pacientes` |
| 3 | Agenda | `agenda` |
| 4 | Expediente clínico | `expediente` |
| 5 | Recetas y generación de PDFs | `recetas`, `pdfs` |
| 6 | Finanzas | `finanzas` |
| 7 | Mi Consultorio (configuración de la clínica) | `clinica` |
| 8 | Personal, consultorios y tipos de cita | `personal` |
| 9 | Notas, tareas y avisos | `notas` |
| 10 | Notificaciones in-app | `notificaciones` |
| 11 | Autenticación y usuarios | `authn` |
| 12 | Bitácora de auditoría | `audit` |
| 13 | Portal interno de plataforma (cross-tenant) | `plataforma` |

---
## 1. Capa transversal

> Extraído del código el 2026-08-12 (modo inverso). Cada afirmación cita `archivo:línea` relativo a
> la raíz del repo. Lo que no se pudo verificar leyendo código está marcado con **NO VERIFICADO**.
> Las apps de dominio **citan** esta sección; no la repiten.

Alcance leído: `apps/core/` completo, `apps/tenancy/` completo, `apps/clinica/sucursal_scope.py`,
`config/settings/*` y `config/urls.py`, y `apps/core/tests/test_rls_coverage.py`. Se consultaron
como insumo `apps/authn/`, `apps/plataforma/views.py`, `apps/clinica/permissions.py`,
`apps/audit/permissions.py` y las migraciones de RLS.

---

### 1.1 Aislamiento de tenant

#### 1.1.1 Las dos barreras

| Barrera | Dónde vive | Qué pasa si no hay tenant resuelto |
|---|---|---|
| **Aplicación** — `TenantManager` | `MailySoft/backend/apps/core/managers.py:14` | **Fail-closed**: dentro de un request devuelve `qs.none()` (`managers.py:32`) |
| **Base de datos** — RLS de PostgreSQL | migraciones `*_enable_rls.py` de cada app + función `current_tenant_id()` en `MailySoft/backend/apps/tenancy/migrations/0002_enable_rls.py:22` | **Fail-open**: la policy incluye `OR current_tenant_id() IS NULL` (`MailySoft/backend/apps/pacientes/migrations/0002_enable_rls.py:31`), es decir sin GUC la fila es visible |

La combinación es cerrada, pero **por la barrera de Django, no por la de Postgres**. Consecuencia
operativa que hay que tener presente al escribir cualquier app: si un selector usa `all_objects` o
SQL crudo en un request sin GUC (todo endpoint que herede de `APIView` y no de `TenantAPIView`), no
queda ninguna barrera activa. Ver B-T-03 y B-T-12 en `docs/00-brechas.md`.

Forma canónica de la policy (todas las tablas siguen este patrón):

```sql
CREATE POLICY <nombre> ON <tabla>
    USING      (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
    WITH CHECK (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL);
```

`current_tenant_id()` lee el GUC `app.current_tenant_id` y devuelve `NULL` si está vacío o si el
setting no existe (`tenancy/migrations/0002_enable_rls.py:22-28`).

#### 1.1.2 Cómo se fija el contexto de tenant

Dos caminos, un solo helper:

1. **JWT (toda la API de clínica)** — `TenantAPIView.check_permissions()`
   (`MailySoft/backend/apps/core/views.py:121`). Se sobreescribe `check_permissions` y no `initial`
   para que DRF ya haya corrido `perform_authentication()` y `request.user` sea el usuario real
   (`core/views.py:12-42`). Una sola query resuelve membresía + tenant + rol
   (`core/views.py:152`), y de ahí salen:
   - `request.membership` y `request.active_role` (`core/views.py:156-159`),
   - `set_current_tenant(tenant)` + `set_tenant_context_active(True)` (`core/views.py:163-164`),
   - `apply_tenant_guc(tenant.id)` solo si hay tenant (`core/views.py:172-173`),
   - `set_request_context(ip, user_agent, request_id)` para la bitácora (`core/views.py:186`).
2. **Sesión de Django (/admin)** — `TenantMiddleware.__call__`
   (`MailySoft/backend/apps/core/middleware.py:67`), que corre después de
   `AuthenticationMiddleware` (`MailySoft/backend/config/settings/base.py:108-110`).

El middleware siempre marca el contexto activo al entrar (`middleware.py:70`) y **siempre** limpia
en el `finally`: `clear_current_tenant()`, `clear_request_context()`,
`set_tenant_context_active(False)` y `clear_tenant_guc()` (`middleware.py:104-113`). Esa limpieza
del GUC es la que impide que una conexión reciclada por `CONN_MAX_AGE=60`
(`config/settings/base.py:147`) herede el tenant de la petición anterior.

El único punto que ejecuta `set_config('app.current_tenant_id', ...)` es `apply_tenant_guc()`
(`MailySoft/backend/apps/core/tenant_context.py:224`).

#### 1.1.3 Modo del GUC (`DB_TENANT_GUC_MODE`)

`config/settings/base.py:182` — valores admitidos `"session"` (default) y `"local"`; cualquier otro
valor revienta al arrancar con `ImproperlyConfigured` (`base.py:183-186`).

| Modo | Qué ejecuta | Requisito | Estado hoy |
|---|---|---|---|
| `session` | `set_config(..., is_local=False)`: el GUC vive en la conexión | Limpieza en el `finally` del middleware | **Activo en producción** (default) |
| `local` | `set_config(..., is_local=True)` = `SET LOCAL`: vive dentro de la transacción | `TenantMiddleware` envuelve **todo** el request en `transaction.atomic()` (`middleware.py:93-102`) | Implementado, apagado |

Riesgo explícito documentado en el código: llamar `apply_tenant_guc()` en modo `local` **fuera** de
una transacción deja el GUC vacío y activa el fallback `current_tenant_id() IS NULL`, que **abre**
el acceso cross-tenant (`tenant_context.py:56-62`). No activar el modo sin el checklist de
`docs/design/pgbouncer-rls-escalabilidad.md`.

#### 1.1.4 El test guardián de cobertura RLS

`MailySoft/backend/apps/core/tests/test_rls_coverage.py`. Recorre por introspección:

- todo modelo concreto que hereda `TenantAwareModel` (`test_rls_coverage.py:53`), y
- toda tabla intermedia **auto-generada** de un `ManyToManyField` declarado en un modelo
  tenant-aware cuyo otro extremo también lo sea (`test_rls_coverage.py:68`).

Y exige contra `pg_class` / `pg_policies`:

| Test | Qué verifica | Línea |
|---|---|---|
| `..._rls_habilitado_y_forzado` | `relrowsecurity` **y** `relforcerowsecurity` | `:132` |
| `..._al_menos_una_policy` | ≥1 fila en `pg_policies` | `:180` |
| `..._restringen_insert_con_with_check` | policy `cmd IN ('ALL','INSERT')` con `with_check` no nulo | `:209` |
| `test_with_check_incluye_el_fallback_sin_tenant` | el `WITH CHECK` contiene `IS NULL` | `:245` |
| regresión brecha 2026-06-25 | 4 tablas concretas | `:287` |
| regresión Cluster E | 3 tablas through de M2M | `:323` |

**Límite real del guardián, dicho por el propio test** (`test_rls_coverage.py:255-258`): la suite
corre con un rol **superuser**, que PostgreSQL exime de RLS. El test verifica **metadatos del
catálogo**, no comportamiento. La verificación de comportamiento es manual con
`python manage.py check_db_role` (`MailySoft/backend/apps/core/management/commands/check_db_role.py`),
que sale con código 1 si el rol evade RLS (`check_db_role.py:57-70`) y **no está en CI**
(`.github/workflows/ci.yml`, no aparece).

#### 1.1.5 Dónde se puede saltar el filtro

`TenantAwareModel` expone dos managers (`MailySoft/backend/apps/core/models.py:72-73`):

- `objects` = `TenantManager` → filtra por tenant activo **y** excluye `deleted_at IS NOT NULL`.
- `all_objects` = `models.Manager()` → **sin filtro de tenant y sin filtro de soft-delete**.

`all_objects` aparece en 100 archivos (368 ocurrencias, incluyendo tests). Los usos legítimos y
sistemáticos son cuatro:

| Consumidor | Por qué | Referencia |
|---|---|---|
| Panel de plataforma (cross-tenant) | `PlatformAPIView` nunca resuelve tenant ni fija GUC | `MailySoft/backend/apps/plataforma/views.py:117-129` |
| `sucursal_scope` | se llama desde `MeApi`, que hereda `APIView` y no tiene thread-local de tenant | `MailySoft/backend/apps/clinica/sucursal_scope.py:155-159` |
| Services que corren desde Celery / comandos | fuera del ciclo request | `sucursal_scope.py:337-339` |
| Tests y migraciones | — | — |

Fuera de un request (`is_tenant_context_active()` es `False`), `TenantManager` **no filtra por
tenant** a propósito (`managers.py:35-36`): Celery, migraciones y management commands ven todos los
tenants. Es la decisión que hace posible el worker de PDFs y los seeds; también es la razón por la
que un bug en una tarea Celery no tiene ninguna red de seguridad.

#### 1.1.6 Qué tablas llevan `tenant_id` y cuáles no

| Tabla | `tenant_id` | RLS | Por qué |
|---|---|---|---|
| Todo modelo de negocio (hereda `TenantAwareModel`) | Sí, `PROTECT` | Sí, exigida por el guardián | Es el dato de la clínica |
| `tenancy_tenants` | No | No | **Es** el tenant |
| `tenancy_memberships` | Sí (`FK CASCADE`) pero hereda `BaseModel` | **No** | Decisión declarada en `apps/tenancy/models.py:6-14`; el aislamiento es un `filter(tenant=...)` explícito en cada selector (`apps/tenancy/selectors.py:4-5`) → ver B-T-03 |
| `tenancy_plans` | No | No | Catálogo global de la plataforma (`models.py:169-180`) |
| `tenancy_subscriptions` | Sí (`OneToOne`) pero `BaseModel` | No | Gestión exclusiva de plataforma (`models.py:325-337`) |
| `tenancy_entitlements` | Sí (`OneToOne`) pero `BaseModel` | No | Igual que arriba (`models.py:262-272`) |
| `authn_users` | No | No | Un usuario puede pertenecer a varias clínicas |
| `recetas.GlobalMedication` | No | No | Catálogo global compartido (`apps/recetas/models.py:129`) |

---

### 1.2 Autenticación y sesión

#### 1.2.1 Esquema híbrido de tokens

| Pieza | Dónde va | Vida | Referencia |
|---|---|---|---|
| **access** | cuerpo JSON del login; el front lo guarda en memoria y lo manda como `Authorization: Bearer` | 15 min (`JWT_ACCESS_MINUTES`) | `config/settings/base.py:257` |
| **refresh** | cookie `maily_refresh`, `httpOnly`, `Secure` en prod, `SameSite=Strict`, `Path=/api/v1/auth/` | 7 días (`JWT_REFRESH_DAYS`) | `base.py:258`, `base.py:504-507`, `apps/authn/views.py:100-108` |

- El refresh **no rota**: `ROTATE_REFRESH_TOKENS=False`, `BLACKLIST_AFTER_ROTATION=False`
  (`base.py:266-267`), con la razón escrita en el propio settings (sesiones que se caían al
  recargar). El logout sí lo invalida vía blacklist (`apps/authn/views.py:312-313`).
- Firma `HS256` con `SIGNING_KEY` propia; en producción es obligatoria y sin default
  (`config/settings/production.py:31`).
- Autenticación por defecto de DRF: solo `JWTAuthentication` (`base.py:208-210`). **No hay
  `SessionAuthentication`** en la API; la sesión de Django solo aplica a `/admin/`.

#### 1.2.2 CSRF

Como el refresh viaja en cookie, los dos endpoints que la leen están protegidos con
`@csrf_protect`: `CookieTokenRefreshView` (`apps/authn/views.py:238`) y `LogoutView`
(`apps/authn/views.py:286`). El login manda la cookie `csrftoken` con `@ensure_csrf_cookie`
(`views.py:136`) y `CSRF_COOKIE_HTTPONLY=False` para que el front pueda leerla y devolverla en
`X-CSRFToken` (`base.py:520`, reafirmado en `production.py:59`). `CSRF_TRUSTED_ORIGINS` sin default
en producción (`production.py:95`).

#### 1.2.3 Rutas de autenticación

| Método | Ruta | Vista | Notas |
|---|---|---|---|
| POST | `/api/v1/auth/login/` | `MailyTokenObtainPairView` | throttle `auth_login` 5/min; audita `LOGIN`; saca `refresh` del body a la cookie (`config/urls.py:31`, `authn/views.py:157-173`) |
| POST | `/api/v1/auth/refresh/` | `CookieTokenRefreshView` | lee la cookie, **no** el body; sin cookie → 401 (`authn/views.py:256-262`) |
| POST | `/api/v1/auth/logout/` | `LogoutView` | exige Bearer válido; 205 aunque el refresh ya estuviera muerto (`authn/views.py:304-326`) |
| POST | `/api/v1/auth/verify/` | `TokenVerifyView` (SimpleJWT sin modificar) | `config/urls.py:34` |
| GET | `/api/v1/me/` | `MeApi` | `apps/authn/urls.py:20` |
| POST | `/api/v1/auth/change-password/` | `PasswordChangeApi` | throttle `auth_password_change` 10/min (`authn/views.py:497-498`) |

#### 1.2.4 `must_change_password`

- Campo en `User` (`MailySoft/backend/apps/authn/models.py:77`), se enciende al recibir contraseña
  temporal (alta de clínica o alta de staff).
- El candado vive en **dos** puntos: `TenantAPIView.check_permissions()`
  (`core/views.py:149`) y `PlatformAPIView.initial()` (`plataforma/views.py:150-151`), vía
  `enforce_password_change()` (`core/views.py:97`).
- Respuesta: **403** con cuerpo `{"detail": "...", "code": "password_change_required"}`
  (`core/views.py:87-94`). El código es estable para que el front redirija sin parsear el mensaje.
- Los endpoints de `authn` quedan exentos **por herencia**, no por whitelist: heredan de `APIView`
  directo (`core/views.py:77-81`, `authn/views.py:469-476`). Un usuario bloqueado puede llegar a
  `/me/`, `/refresh/`, `/logout/` y `/change-password/` y a nada más.

#### 1.2.5 Clínica activa y usuarios con dos membresías

`resolve_membership_for_user()` (`apps/core/tenant_context.py:113`) es la **única** fuente de verdad
y devuelve:

```
memberships.filter(is_active=True, tenant__status__in=["active","trial"], deleted_at__isnull=True)
          .select_related("tenant").order_by("created_at").first()
```
(`tenant_context.py:156-165`)

De ahí:

- Un tenant `suspended` bloquea el acceso; `trial` y `active` lo permiten (`tenant_context.py:29-32`).
- Un usuario con **dos membresías activas siempre opera sobre la más antigua**. No hay forma de
  cambiar: **`X-Tenant-ID` no existe en el código** (solo se menciona en un docstring,
  `apps/tenancy/models.py:29`, y en un comentario de test). Verificado por búsqueda en todo
  `MailySoft/backend`. Ver B-T-02.
- Un usuario sin membresía tiene `request.active_role = None` → 403 en todo endpoint de clínica
  (`core/permissions.py:129-131`). Aplica también a un `is_platform_staff` sin membresía
  (`core/permissions.py:29-33`).
- `GET /me/` devuelve `active_tenant`, `active_role`, la lista completa de `memberships`,
  `doctor_id`, `sucursales` y `capabilities` (`apps/authn/serializers.py:71-100`); el front pinta la
  clínica activa a partir de ahí, pero no puede cambiarla.

---

### 1.3 Clases de permisos de `apps/core/permissions.py`

**Este inventario es la referencia que citan las apps de dominio.** 50 clases en el archivo.
Leyenda de roles: **O**=owner · **A**=admin · **D**=doctor · **N**=nurse · **R**=reception ·
**F**=finance · **L**=readonly. `TODOS` = los 7 (`ALL_ROLES`, `permissions.py:56`).
`CLINICAL_READ` = O A D N L (`permissions.py:670`).

#### 1.3.1 Comportamiento común (heredado de `HasClinicRole`, `permissions.py:81`)

- Lee `request.active_role`, que ya adjuntó `TenantAPIView` — **cero queries extra**
  (`permissions.py:129`).
- `OPTIONS` → **siempre `True`**, sin mirar rol (`permissions.py:123-124`). Es el preflight CORS.
  Consecuencia real en B-T-01.
- `HEAD` → se traduce a `GET` antes de consultar la policy (`permissions.py:127`).
- Método no declarado en `policy` y sin clave `"*"` → `frozenset()` → **denegado** (`permissions.py:133-135`).
- `active_role is None` → denegado (`permissions.py:130-131`).
- Denegar devuelve `False` → DRF responde **403** con `message` de la clase. **Nunca 404**: el 404
  está reservado al aislamiento por tenant y al gating por módulo (`permissions.py:15-18`).
- **Fail-closed** en todas las clases de esta sección, salvo la excepción de `OPTIONS`.

#### 1.3.2 Permisos de clínica (subclases de `HasClinicRole`)

| # | Clase (línea) | GET | POST | PATCH/PUT | DELETE | Notas |
|---|---|---|---|---|---|---|
| 1 | `HasClinicRole` `:81` | — | — | — | — | Base. `policy = {}` → deniega todo si se usa directa |
| 2 | `PatientPermission` `:144` | TODOS | O A D N R | O A D N R | O A | |
| 3 | `PersonalPermission` `:162` | TODOS | O A | O A | O A | |
| 4 | `AppointmentPermission` `:180` | O A D N R L | O A D R | O A D R | O A R | F excluido de toda la agenda (`:76`) |
| 5 | `AppointmentStatusPermission` `:199` | — | O A D N R | — | — | Solo POST |
| 6 | `MemberPermission` `:213` | O A | O A | O A | O A | DELETE = quitar avatar |
| 7 | `AppointmentTypePermission` `:232` | TODOS | O A | O A | O A | |
| 8 | `AgendaConfigPermission` `:250` | TODOS | — | O A (PATCH) | — | GET abierto para poder dibujar la rejilla |
| 9 | `FinanceDashboardPermission` `:304` | O A F L | — | — | — | R excluido |
| 10 | `FinanceConceptPermission` `:317` | O A F R L + D | **O** | **O** | **O** | Escritura solo dueño (decisión 2026-07-16) |
| 11 | `FinanceQuotePermission` `:340` | O A F R L | O A F R | O A F R | O A F R | **DEPRECADA y sin uso** → B-T-06 |
| 12 | `QuotePermission` `:368` | O A D R L | O A D R | O A D R | O A D R | F y N fuera por decisión del cliente |
| 13 | `TreatmentPackagePermission` `:393` | O A D R | **O** | **O** | **O** | |
| 14 | `FinanceChargePermission` `:417` | O A F R L | O A F | O A F | O A F | |
| 15 | `FinancePaymentPermission` `:435` | O A F R L | O A F R | — | — | |
| 16 | `FinanceStatementPermission` `:449` | O A F R L | — | — | — | **Sin uso** → B-T-06 |
| 17 | `CfdiPermission` `:590` | O A F L | O A F | — | — | R no factura |
| 18 | `FinanceConfigPermission` `:604` | O A | — | O A (PATCH) | — | |
| 19 | `AgendaItemNotePermission` `:616` | O A D N R L | O A D N R | — | O A D N R | El service valida autor/dueño |
| 20 | `NotePermission` `:638` | TODOS | TODOS | TODOS | TODOS | La granularidad la hace el service (`:641-652`) |
| 21 | `AllergyPermission` `:675` | TODOS | O A D N | O A D N | O A D N | GET abierto a propósito: bandera de seguridad |
| 22 | `MedicalHistoryPermission` `:697` | CLINICAL_READ | — | O A D (PUT) | — | |
| 23 | `VitalSignsPermission` `:721` | CLINICAL_READ | O A D N | — | — | Append-only |
| 24 | `EvolutionPermission` `:741` | CLINICAL_READ | O A D | — | O A D | Sin PATCH/PUT → 405 (inmutabilidad) |
| 25 | `ClinicalSummaryPermission` `:770` | O A D | O A D | — | — | |
| 26 | `TreatmentPlanPermission` `:796` | O A D | O A D | O A D (PUT) | O A D | |
| 27 | `LongevityPlanPermission` `:820` | O A D | O A D | — | — | |
| 28 | `DocumentTemplatePermission` `:844` | O A D | O A | O A | O A | |
| 29 | `LabAnalytePermission` `:862` | O A D | O A | O A | O A | |
| 30 | `AddendumPermission` `:880` | CLINICAL_READ | O A D | — | — | |
| 31 | `DiagnosisPermission` `:897` | CLINICAL_READ | O A D | — | — | |
| 32 | `NursingInstructionPermission` `:915` | CLINICAL_READ | — | — | — | Solo lectura |
| 33 | `PrescriptionPermission` `:935` | CLINICAL_READ | O A D | — | — | R y F fuera (DR-6). El service exige perfil Doctor activo |
| 34 | `MedicationPermission` `:983` | CLINICAL_READ | O A D | — | — | |
| 35 | `PrescriptionFormatPermission` `:1005` | TODOS | O A D | O A D | O A | Atributo `_DOCTOR_ROLES` `:1022` no se usa |
| 36 | `MedicalHistoryQuestionPermission` `:1032` | CLINICAL_READ | O A | O A | O A | |
| 37 | `NotificationPermission` `:1060` | TODOS | TODOS | — | — | El selector filtra por destinatario |
| 38 | `RetentionPermission` `:1119` | O A F L | — | — | — | R, D, N fuera |

#### 1.3.3 Permisos de clínica que **no** heredan de `HasClinicRole`

| # | Clase (línea) | Qué exige | Denegación | Fail |
|---|---|---|---|---|
| 39 | `PatientStatementPermission` `:502` | O A F R L siempre; **D solo si** `ClinicSettings.doctors_see_costs=True`; resto no | 403 | closed (`OPTIONS` → True, `:528`) |
| 40 | `ChargeListPermission` `:546` | GET igual que la anterior; POST/PATCH/DELETE → O A F | 403 | closed (`OPTIONS` → True, `:569`) |

Ambas leen el flag con `_tenant_doctors_see_costs()` (`permissions.py:461`), que cachea en
`request._doctors_see_costs` (1 query por request) y devuelve `False` ante cualquier fallo
(tenant nulo, sin `ClinicSettings`) → **fail-closed** (`permissions.py:489-497`).

#### 1.3.4 Permisos del panel interno (cross-tenant)

Todos exigen primero `is_platform_staff=True` y devuelven **403** (no 404): la existencia del panel
no es secreto (`permissions.py:1145-1149`). Todos dejan pasar `OPTIONS`.

| # | Clase (línea) | Roles de plataforma admitidos |
|---|---|---|
| 41 | `IsPlatformStaff` `:1139` | cualquiera con `is_platform_staff=True` |
| 42 | `PlatformMetricsPermission` `:1162` | super_admin, sales, engineering |
| 43 | `PlatformClinicReadPermission` `:1176` | los 3 — **solo GET/HEAD**; cualquier otro método → `False` (`:1193`) |
| 44 | `PlatformClinicWritePermission` `:1196` | super_admin, sales |
| 45 | `PlatformStaffListPermission` `:1215` | super_admin |
| 46 | `PlatformAuditPermission` `:1229` | super_admin, engineering |
| 47 | `PlatformSystemPermission` `:1249` | super_admin, engineering |
| 48 | `PlatformSubscriptionPermission` `:1268` | super_admin, sales (lectura **y** escritura) |
| 49 | `PlatformPlanWritePermission` `:1293` | super_admin |
| 50 | `PlatformStaffWritePermission` `:1317` | super_admin |

Constante única para "solo super_admin": `_PLATFORM_ROLES_SUPER_ADMIN_ONLY` (`permissions.py:1099`);
la nota de `:1109-1116` prohíbe declarar otro frozenset equivalente.

#### 1.3.5 Permisos definidos **fuera** de core (los documenta su app)

| Clase | Archivo:línea | Resumen |
|---|---|---|
| `ClinicSettingsPermission` | `MailySoft/backend/apps/clinica/permissions.py:29` | GET CLINICAL_READ · PUT O A |
| `ClinicTemplatePermission` | `clinica/permissions.py:43` | GET CLINICAL_READ · escritura O A D |
| `PatientCategoryPermission` | `clinica/permissions.py:61` | GET TODOS · POST/DELETE O A |
| `DoctorProfilePermission` | `clinica/permissions.py:77` | GET TODOS · escritura O A D |
| `ClinicTeamPermission` | `clinica/permissions.py:95` | GET O A D · escritura O A |
| `SucursalPermission` | `clinica/permissions.py:113` | GET TODOS · escritura **solo O** |
| `MembershipSucursalPermission` | `clinica/permissions.py:141` | GET/PUT O A (la granularidad la hace el service) |
| `AuditLogPermission` | `MailySoft/backend/apps/audit/permissions.py:25` | GET **solo O** |
| `FinanceDeskPermission` | `MailySoft/backend/apps/finanzas/views.py:92` | GET O A F R |

#### 1.3.6 Mixins, decoradores y checks por objeto

- **No existe** ningún mixin ni decorador de permiso por objeto. `has_object_permission` no está
  implementado en ninguna clase (verificado en todo `apps/`): el permiso HTTP gatea **solo por
  rol**; la autorización fina sobre el registro concreto vive en `services.py` / `selectors.py` de
  cada app (patrón declarado en `permissions.py:641-652`, `permissions.py:947-950` y
  `clinica/permissions.py:149-155`).
- Dos vistas hacen el check de rol **a mano**, fuera de toda clase de permiso:
  `DoctorCredentialTenantListApi` (`apps/clinica/views.py:772-777`) y
  `DoctorCredentialValidationApi` (`apps/clinica/views.py:798-803`) comparan
  `request.active_role not in ("owner","admin")` con strings literales → B-T-08.
- Tres vistas de plataforma resuelven el permiso por método con `get_permissions()` en vez de
  `permission_classes`: `PlatformClinicasListApi` (`plataforma/views.py:224`),
  `PlatformUsuariosListApi` (`:414`) y `PlatformPlanesListApi` (`:712`). Su
  `permission_classes = [IsAuthenticated]` a nivel de clase **no** es un hueco: `get_permissions()`
  lo sustituye por completo.
- `PdfJobStatusApi` / `PdfJobFileApi` declaran solo `IsAuthenticated`
  (`MailySoft/backend/apps/pdfs/views.py:52`, `:84`) pero revalidan dentro del handler el permiso
  registrado para el `kind` del job y responden **404** si falla (`pdfs/views.py:36-42`, `:63-68`).

**No hay ningún endpoint sin `permission_classes`.** Verificado sobre las 141 vistas de
`apps/**/views*.py`; el mínimo global además es `IsAuthenticated`
(`REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES`, `config/settings/base.py:211-213`). La única vista
`AllowAny` del sistema es la verificación pública de receta
(`MailySoft/backend/apps/recetas/views_public.py:81`).

---

### 1.4 Módulos y entitlements

#### 1.4.1 Catálogo (`MailySoft/backend/apps/core/modules.py:24`)

Los módulos viven en el **código**, no en la base: existen porque hay código que los implementa
(`modules.py:4-6`). Los planes solo referencian slugs. **Multi-sucursal no es módulo**: es el límite
`max_sucursales` (`modules.py:12-13`).

| # | Slug | Grupo | Depende de (`MODULE_REQUIRES`, `:50`) | Guard | ¿Se aplica? |
|---|---|---|---|---|---|
| 1 | `agenda` | Clínico | — | `RequiresAgenda` `entitlement_guards.py:92` | sí |
| 2 | `recordatorios` | Clínico | `agenda` | `RequiresRecordatorios` `:93` | **no, en ninguna vista** → B-T-07 |
| 3 | `expediente` | Clínico | — | `RequiresExpediente` `:94` | sí |
| 4 | `recetas` | Clínico | — | `RequiresRecetas` `:95` | sí |
| 5 | `notas` | Clínico | — | `RequiresNotas` `:96` | sí |
| 6 | `servicios` | Comercial | — | `RequiresServicios` `:97` | sí |
| 7 | `paquetes` | Comercial | `servicios` | `RequiresPaquetes` `:98` | sí |
| 8 | `cotizaciones` | Comercial | `servicios` | `RequiresCotizaciones` `:99` | sí |
| 9 | `cobranza` | Comercial | — | `RequiresCobranza` `:100` | sí |
| 10 | `cfdi` | Comercial | `cobranza` | `RequiresCfdi` `:101` | sí |
| 11 | `calendarizacion` | Especial | `expediente`, `servicios`, `cotizaciones` | `RequiresCalendarizacion` `:102` | sí |
| 12 | `personal` | Operación | — | `RequiresPersonal` `:103` | sí |

Helpers del catálogo: `modulos_desconocidos()` `:107`, `expandir_dependencias()` `:119`,
`dependencias_faltantes()` `:142`, `validar_modulos()` `:162` (**no** expande solo: un plan con
cotizaciones y sin servicios es error de captura, no algo que adivinar), `roles_disponibles()` `:192`.

#### 1.4.2 Cómo bloquea el guard

`RequiresModule.has_permission()` (`MailySoft/backend/apps/core/entitlement_guards.py:72`):

1. `OPTIONS` → `True` (`:75-76`).
2. Resuelve entitlements cacheados por request (`entitlements_del_request`, `:40`).
3. Si la clínica tiene el módulo → `True`.
4. Si no → **`raise NotFound("No encontrado.")`** = **404**, no 403 (`:84`).

La regla "módulo apagado = 404" está **verificada en código** y su razón escrita en el docstring del
módulo (`entitlement_guards.py:12-16`): un 403 delataría el catálogo. Sin tenant resuelto,
`entitlements_del_request` devuelve `None` y el guard también responde 404 → **fail-closed**.

Versión para services (Celery, comandos, reglas que dependen del body): `require_module()`
(`entitlement_guards.py:106`), misma semántica de `NotFound`.

Composición obligatoria: `permission_classes = [IsAuthenticated, <RolPermission>, <RequiresX>]` —
pasa **solo si el rol lo permite Y la clínica lo compró** (`entitlement_guards.py:59-68`).

#### 1.4.3 `Plan` vs `TenantEntitlements`: resolución de derechos

Fuente única: `entitlements_for_tenant()` (`MailySoft/backend/apps/tenancy/entitlements.py:71`).

```
módulos = (Plan.modules ∪ TenantEntitlements.modules_on) − TenantEntitlements.modules_off
límite  = override de la clínica si no es NULL, si no el del plan; NULL en ambos = ilimitado
```
(`entitlements.py:89-102`)

- Los slugs que ya no existen en el catálogo del código se descartan: `modulos &= set(Module.values)`
  (`entitlements.py:97`).
- Sin suscripción y sin ajustes → **cero módulos** (`entitlements.py:14-16`). Las clínicas que ya
  existían se migraron al plan `legacy-full` (`apps/tenancy/migrations/0007_entitlements_legacy_full.py:76`).
- El resultado es un dataclass congelado `Entitlements` (`entitlements.py:28`) con `tiene()`,
  `roles`, `sede_unica` (`max_sucursales == 1`, `:62`) y `limite()`.
- Se cachea **por request** en `request._entitlements_cache` (`entitlement_guards.py:46-56`).
- El mismo objeto alimenta el bloqueo del backend y el `capabilities` de `/me/`
  (`apps/authn/views.py:426-440`), así que front y backend no se pueden contradecir.

#### 1.4.4 Límites y dónde se hacen valer

`assert_within_limit()` (`entitlement_guards.py:123`) lanza `ValidationError` (→ 400) con mensaje
accionable. `None` = ilimitado (`:136-137`).

| Límite | Punto de aplicación | Cómo se cuenta |
|---|---|---|
| `max_sucursales` | `MailySoft/backend/apps/clinica/services.py:1116` | sucursales no borradas del tenant |
| `max_consultorios` | `MailySoft/backend/apps/personal/services.py:537` | consultorios no borrados |
| `max_usuarios` | `MailySoft/backend/apps/tenancy/services.py:254` | membresías activas no borradas |

No hay ningún otro punto que consulte límites (verificado por búsqueda de `assert_within_limit` en
`apps/`).

#### 1.4.5 Planes sembrados (`apps/tenancy/management/commands/seed_planes.py:60`)

| Plan | $/mes | Módulos | Roles ofrecidos | Suc. | Cons. | Usr. | Activo |
|---|---|---|---|---|---|---|---|
| `solo` | 900 | 5 clínicos | O | 1 | 1 | 1 | **no** (`:83`) |
| `basico` | 1500 | clínicos + `personal` | O D N R | 1 | 1 | 3 | sí |
| `pro` | 4500 | + 4 comerciales sin CFDI | los 7 | 1 | 5 | ∞ | sí (destacado) |
| `premium` | 8900 | + `cfdi` | los 7 | ∞ | ∞ | ∞ | sí |
| `enterprise` | 0 (a cotizar) | + `cfdi` | los 7 | ∞ | ∞ | ∞ | sí |

El comando es **conservador**: crea lo que falta, completa planes sin módulos, y solo reescribe uno
vivo con `--actualizar` (`seed_planes.py:201-220`). Antes de guardar expande dependencias y valida
(`:198-199`). `calendarizacion` no está en ningún plan: se enciende por override.

---

### 1.5 Alcance por sucursal

`MailySoft/backend/apps/clinica/sucursal_scope.py`. **No es una barrera de seguridad de base de
datos**: es un filtro operativo de segunda dimensión *dentro* del mismo tenant. Un bug aquí nunca
expone otro negocio (eso lo sostiene RLS); en el peor caso expone otra sede del mismo negocio —
aceptado por diseño y escrito así en el archivo (`sucursal_scope.py:4-12`).

Header de transporte: **`X-Sucursal-Id`** (`sucursal_scope.py:113`).

#### 1.5.1 Las cinco funciones

| Función | Línea | Devuelve | Para qué |
|---|---|---|---|
| `allowed_sucursales(user, tenant)` | `:135` | `QuerySet[Sucursal]` **activas** | selectores de UI y autorización de escritura |
| `actor_sucursal_ids(user, tenant)` | `:200` | `set[UUID]` incluyendo **inactivas**, o `None` = alcance total | autorización dura |
| `resolve_active_sucursal(request)` | `:270` | `Sucursal` o `None` si no vino el header | sede activa del request |
| `resolve_write_sucursal(...)` | `:313` | `Sucursal` o `None` | qué sede se graba en una escritura |
| `sucursal_scope_ids(request)` | `:429` | `list[UUID]` o `None` = sin filtro | alcance de un **listado** |

#### 1.5.2 Quién ve todas las sedes

| Rol | Alcance |
|---|---|
| `owner` | **Siempre todas** las sedes del tenant, sin necesitar `MembershipSucursal` (`:181-182`, `:238-239`) |
| Cualquier otro rol, **admin incluido** | Solo las asignadas vía `MembershipSucursal` (`:184-197`) |
| Cualquier rol **sin ninguna asignación** | Fallback anti-lockout: **solo** la sede `is_default=True`; si no hay default, **vacío** (`:191-195`) |
| Rol no owner con asignaciones que cubren **todas** las sedes (activas e inactivas) | "admin de negocio": alcance total (`:492-500`) |
| Usuario sin membresía activa en el tenant | Vacío (`:171-173`) |

El denominador de "cubre todas" se cuenta contra **todas** las sedes, no solo las activas: si se
contara solo activas, desactivar una sede ajena ampliaría por accidente el alcance de un admin
acotado (Clúster B, corregido, `:492-500`).

#### 1.5.3 Precedencia de escritura (`resolve_write_sucursal`, `:388-426`)

1. `sucursal_id` explícito del body → error inmediato si no existe en el tenant.
2. Sede del consultorio asignado.
3. `active_sucursal_id` (header).
4. Sede `is_default` del tenant.
5. Si el tenant no tiene ninguna sucursal → `None` (compatibilidad retro; los FK `sucursal` nacen
   nullables, `:362-369`).

**Después** de resolver por cualquiera de las 4 vías, valida contra `allowed_sucursales` y si no
está, `ValidationError` (`:421-424`). Eso cierra el body con sede ajena y el fallback silencioso a
la sede default que no es la del actor.

#### 1.5.4 Diferencia crítica entre las dos funciones de listado

- `resolve_active_sucursal`: **sin header = sin filtro**. Retro-compatible, pero por sí sola era el
  hueco de seguridad: un usuario de la sede A veía la B con solo omitir el header (`:436-438`).
- `sucursal_scope_ids`: **siempre acota** (header → esa sede; alcance parcial → sus sedes; alcance
  total → `None`).

Regla para las apps: **listados expuestos a roles acotados por sede usan `sucursal_scope_ids`**
(`sucursal_scope.py:92-94`). `resolve_active_sucursal` queda para conveniencia y para alimentar
escrituras.

#### 1.5.5 Dónde NO se aplica

| Caso | Evidencia | Consecuencia |
|---|---|---|
| Detalle de una nota de cita | `apps/agenda/views.py:1144` (`AgendaItemNoteDetailApi`), hallazgo abierto citado en `docs/01-analisis.md:346-348` | Un admin de Norte puede leer/borrar por id la nota de una cita de Centro |
| Bitácora de auditoría | `AuditLog` no tiene campo `sucursal`; se compensó restringiendo a `owner` (`apps/audit/permissions.py:10-14`) | Un admin de sede no ve bitácora de ninguna sede |
| Detalle/avatar de miembro | Usa `allowed_sucursales` (permiso), **no** `sucursal_scope_ids` (`apps/tenancy/views.py:70-110`) | Deliberado: el dueño parado en Centro sí puede editar a alguien de Norte |
| Tenant sin ninguna `Sucursal` | `sucursal_scope_ids` → `None` (`:487-490`); `_sucursal_scope_q` → `Q()` vacío (`apps/tenancy/selectors.py:64-68`) | Una clínica que nunca adoptó multi-sede opera sin filtro |

---

### 1.6 Roles

#### 1.6.1 Roles de clínica (7) — `MailySoft/backend/apps/tenancy/models.py:95`

| Valor | Etiqueta | Línea |
|---|---|---|
| `owner` | Dueño | `:96` |
| `admin` | Administrador | `:97` |
| `doctor` | Médico | `:98` |
| `nurse` | Enfermería | `:99` |
| `reception` | Recepción | `:100` |
| `finance` | Finanzas | `:101` |
| `readonly` | Solo lectura | `:102` |

Helper derivado: `TenantMembership.operational_roles()` (`models.py:104`) = todos **menos** `owner`
y `admin`. Se calcula desde `Role.choices` en cada llamada, para que agregar un rol nuevo no exija
tocar nada.

**Jerarquía (decisión del dueño 2026-07-16).** Un actor `owner` administra a cualquiera. Un actor
que **no** es owner (el "administrador de sucursal", típicamente `admin`):

- solo **ve** personal con rol operacional de sus sedes, más a sí mismo (`apps/tenancy/selectors.py:181-187`);
- solo **toca** (detalle, PATCH, avatar) personal operacional dentro de `allowed_sucursales`; contra
  un owner o admin recibe **404**, no 403 (`apps/tenancy/views.py:103-108`);
- nunca **otorga** los roles `owner` ni `admin` (anti-escalada, `apps/tenancy/services.py:114-133`);
- el service revalida lo mismo por si se invoca fuera de la vista (`services.py:76-111`).

Además: **un solo dueño por clínica** — crear un segundo `owner` fuera del bootstrap está bloqueado
(`services.py:223-230`).

#### 1.6.2 Staff interno de plataforma (3) — `MailySoft/backend/apps/authn/models.py:35`

| Valor | Etiqueta | Línea |
|---|---|---|
| `super_admin` | Súper Admin | `:38` |
| `sales` | Ventas / Éxito de Cliente | `:39` |
| `engineering` | Ingeniería | `:40` |

Se activa con `is_platform_staff=True` (`authn/models.py:65`); `platform_role` se ignora si el flag
es falso (`:75`). Un staff **sin** `TenantMembership` recibe 403 en toda la API de clínica
(`core/permissions.py:29-33`).

#### 1.6.3 Interacción rol × plan × módulo

Tres capas, en este orden:

1. **Módulo** — `ROLE_REQUIRES` (`apps/core/modules.py:66`): `doctor` y `nurse` exigen `expediente`;
   `reception` exige `agenda`; `finance` exige `cobranza`; `owner`, `admin` y `readonly` no exigen
   nada. `roles_disponibles(modules)` (`modules.py:192`) devuelve los que sobreviven.
2. **Plan** — `Plan.roles` es una allow-list; vacía = sin restricción extra
   (`apps/tenancy/models.py:234-243`).
3. **Resultado** — `Entitlements.roles` = capa 1 ∩ capa 2 (`apps/tenancy/entitlements.py:47-59`).

Se hace valer al dar de alta un miembro: si el rol no está en `ent.roles`, 400 con
"El plan de esta clínica no incluye el rol '<x>'" (`apps/tenancy/services.py:247-253`). Ejemplo
real: en plan **Básico** (`_ROLES_CLINICOS` = owner, doctor, nurse, reception, `seed_planes.py:52`)
**no se puede crear un `admin`**, aunque `admin` no dependa de ningún módulo. Y en cualquier plan sin
`cobranza`, `finance` desaparece aunque el plan lo liste.

El rol activo **no** se recalcula al cambiar el plan: una membresía `finance` existente sobrevive
aunque se apague `cobranza`; lo que la deja inútil es el 404 de los guards de módulo.

---

### 1.7 Convenciones de la API

Lo que aplica a **todos** los endpoints. Las apps de dominio no lo repiten.

| Tema | Regla | Referencia |
|---|---|---|
| **Prefijo** | `/api/v1/` para todo; cada app se incluye ahí | `config/urls.py:37-54` |
| **Versionado** | **No hay** versionado de DRF configurado. La versión es literal en la ruta | `config/settings/base.py:207-238` (sin `DEFAULT_VERSIONING_CLASS`) |
| **Autenticación** | `Authorization: Bearer <access>`; sin `SessionAuthentication` | `base.py:208-210` |
| **Permiso mínimo** | `IsAuthenticated` global | `base.py:211-213` |
| **Renderer** | Solo JSON (`JSONRenderer`). No hay Browsable API | `base.py:234-236` |
| **Header de sede** | `X-Sucursal-Id` opcional en cualquier endpoint que acote por sede | `apps/clinica/sucursal_scope.py:113` |
| **Fechas** | ISO-8601. `USE_TZ=True`, `TIME_ZONE=America/Mexico_City`; DRF serializa en el huso **activo**, y nada activa el huso del tenant → las respuestas salen con desplazamiento de Ciudad de México, no en UTC | `base.py:432-435`; verificado que no existe ninguna llamada a `timezone.activate` en `apps/` |
| **Idioma de los errores** | Mensajes de DRF localizados en español (`LANGUAGE_CODE=es-mx`, `USE_I18N=True`) | `base.py:432-434` |
| **Docs OpenAPI** | `/api/schema/`, `/api/docs/`, `/api/redoc/` **solo con `DEBUG=True`** | `config/urls.py:60-71` |
| **Salud** | `GET /healthz/` sin auth ni BD; exento del redirect a HTTPS | `config/urls.py:17-24`, `production.py:40` |
| **SPA** | Catch-all que sirve `index.html` para todo lo que no sea `api/`, `admin/`, `static/`, `media/` | `config/urls.py:89-99` |

#### 1.7.1 Paginación

**No es automática.** Todas las vistas heredan de `APIView`, así que `DEFAULT_PAGINATION_CLASS`
(`base.py:214`) **no se aplica sola**: cada vista que pagina instancia `PageNumberPagination()`
a mano.

| Paginador | Tamaño | `page_size` en query | Tope | Dónde |
|---|---|---|---|---|
| `PageNumberPagination` estándar | `PAGE_SIZE=25` (env `DRF_PAGE_SIZE`) | **no** admitido | — | pacientes, agenda, finanzas, notas, personal, notificaciones (p. ej. `apps/pacientes/views.py:181`) |
| `_AuditLogPagination` | 50 | sí | 200 | `apps/audit/views.py:27` |
| `_StandardPagination` (plataforma) | 20 | sí | 100 | `apps/plataforma/views.py:170` |

Respuesta paginada: `{count, next, previous, results}` (formato estándar de DRF). Los listados
**sin** paginador devuelven un array plano — p. ej. `GET /api/v1/miembros/`
(`apps/tenancy/views.py:150`), documentado como "son pocos" (`views.py:32`).

#### 1.7.2 Formato de error

Hay **tres formas** distintas de cuerpo de error conviviendo:

| Origen | Cuerpo | Ejemplo |
|---|---|---|
| Excepciones de DRF (401/403/404/405/429) | `{"detail": "<string>"}` | `{"detail": "No encontrado."}` (`entitlement_guards.py:84`) |
| Validación de serializer (400) | `{"<campo>": ["<error>", ...]}` | `is_valid(raise_exception=True)` |
| `ValidationError` de un service traducida en la vista (400) | `{"detail": ["<msg>", ...]}` — **lista**, no string | `apps/tenancy/views.py:180`, `:227`, `:257` |

Caso especial estable: **403 de contraseña temporal** →
`{"detail": "...", "code": "password_change_required"}` (`core/views.py:87-94`).

Códigos y su significado transversal:

| Código | Cuándo |
|---|---|
| 401 | Sin token o token inválido (`IsAuthenticated`) |
| 403 | Rol insuficiente; sin membresía activa; sede no permitida (`sucursal_scope.py:297`, `:307`); contraseña temporal pendiente |
| 404 | Recurso de otro tenant, fuera de la sede permitida, **o módulo no contratado** |
| 405 | Método no ruteado en la vista (así se sostiene la inmutabilidad clínica) |
| 429 | Throttle |

#### 1.7.3 Throttling (`config/settings/base.py:216-232`)

| Scope | Límite | Aplica a |
|---|---|---|
| `anon` | 60/min | todo endpoint sin usuario autenticado |
| `user` | 300/min | todo endpoint autenticado |
| `auth_login` | 5/min | `POST /auth/login/` (`authn/views.py:157-158`) |
| `auth_password_change` | 10/min | `POST /auth/change-password/` (`authn/views.py:497-498`) |
| `prescription_verify` | 30/min | verificación pública de receta |

Los tres scopes usan `ScopedRateThrottle`, que **reemplaza** los throttles por defecto en esa vista.
Todos configurables por variable de entorno.

#### 1.7.4 CORS / CSRF / cabeceras de seguridad

- CORS: orígenes explícitos (`CORS_ALLOWED_ORIGINS`), `CORS_ALLOW_CREDENTIALS=True`,
  `CORS_ALLOW_ALL_ORIGINS=False` (`base.py:488-489`, `production.py:90-91`). **No se declara
  `CORS_ALLOW_HEADERS`** → `X-Sucursal-Id` no está en la lista permitida por defecto (B-T-11).
  Hoy es inocuo: en desarrollo el front va por el proxy de Vite (`web-soft/vite.config.ts:24`) y en
  producción el SPA lo sirve el mismo Django (`config/urls.py:89`), así que no hay preflight.
- Producción: `SECURE_SSL_REDIRECT`, HSTS 1 año con preload, `X_FRAME_OPTIONS=DENY`, nosniff,
  `SECURE_PROXY_SSL_HEADER` (`production.py:37-71`).
- **CSP está comentada por completo** (`production.py:78-84`).
- Tamaño máximo de cuerpo en memoria: 5 MB (`base.py:337`).

---

### 1.8 Modelos base y campos comunes

#### 1.8.1 `BaseModel` (abstracto) — `MailySoft/backend/apps/core/models.py:19`

| Campo | Tipo | Null | Default | Índice |
|---|---|---|---|---|
| `id` | `UUIDField` PK, `editable=False` | no | `uuid.uuid4` | PK |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | ahora | **sí** (`db_index`) |
| `updated_at` | `DateTimeField(auto_now=True)` | no | ahora | no |
| `deleted_at` | `DateTimeField` | **sí** | `NULL` | **sí** |

`deleted_at IS NULL` = activo. **El borrado es lógico en todo el sistema**; `BaseModel` **no**
declara manager propio, así que un modelo que herede solo de `BaseModel` (Tenant, Membership, Plan,
Subscription, Entitlements, GlobalMedication) usa el manager por defecto de Django y **no** excluye
soft-deleted automáticamente. Es el origen de B-T-04 y B-T-05.

#### 1.8.2 `TenantAwareModel` (abstracto) — `core/models.py:42`

Agrega a lo anterior:

| Campo | Tipo | `on_delete` | Null | Consecuencia real |
|---|---|---|---|---|
| `tenant` | FK a `tenancy.Tenant`, `related_name="+"`, `db_index=True` | **PROTECT** | no | No se puede borrar en duro una clínica que tenga **un solo** registro de negocio. El "borrado" real de una clínica es `status=suspended` |
| `created_by` | FK a `AUTH_USER_MODEL`, `related_name="+"` | **SET_NULL** | sí | Borrar un usuario no bloquea ni arrastra sus registros: quedan con autor nulo (FIX-7, `models.py:63-64`) |

Managers: `objects = TenantManager()` y `all_objects = models.Manager()` (`models.py:72-73`).

#### 1.8.3 A qué obliga a cada app hija

1. Todo modelo de negocio hereda `TenantAwareModel` **y** trae su migración RLS (`ENABLE` + `FORCE`
   + policy con `USING` y `WITH CHECK`, ambos con el fallback `IS NULL`). Si falta, el test guardián
   rompe CI.
2. Un `ManyToManyField` **sin `through` explícito** entre dos modelos tenant-aware genera una tabla
   que **no** tiene `tenant_id`: necesita su propia migración RLS por subconsulta al padre
   (patrón: `apps/personal/migrations/0012_rls_doctor_m2m_through_tables.py`, citado en
   `test_rls_coverage.py:166-169`).
3. Nunca `all_objects` en vistas o services sin justificación escrita (`core/models.py:51`).
4. El borrado en API es lógico: se setea `deleted_at` o un `is_active`, nunca `DELETE` físico.

#### 1.8.4 Validadores y archivos compartidos

- `apps/core/validators.py`: `validar_cedula_profesional()` (`:35`) y `validar_cedulas_adicionales()`
  (`:55`). Patrón `^[0-9]{5,10}$` (`:30`); vacío es válido. Usa `[0-9]` y no `\d` a propósito, para
  rechazar dígitos Unicode y para que el espejo de `web-soft/src/lib/validacion.ts` valide lo mismo
  (`validators.py:26-29`).
- `apps/core/files.py`: `validate_image()` (`:51`) verifica con Pillow que el contenido **sea** una
  imagen (no la extensión ni el Content-Type), acepta solo JPEG/PNG/WEBP (`:38`), fuerza `.load()`
  para detectar bombas de descompresión con tope de 40 MP (`:48`, `:111-115`), y **falla cerrado** si
  no puede leer el tamaño (`:80-82`). Límites: 5 MB avatares (`:30`), 10 MB imágenes clínicas
  (`:35`). Los nombres se aleatorizan con UUID (`:157`) y las imágenes de evolución se guardan bajo
  `evoluciones/<tenant_id>/` (`:199-200`).
- `apps/core/pdf/branding.py`: `build_brand_context()` (`:86`) es el contexto de marca de **todos**
  los PDFs. Prioridad del color: `accent_color` del `PrescriptionFormat` default → 
  `ClinicSettings.brand_color` → `#9A7B1E` (`:103-108`). Si no hay `ClinicSettings` devuelve un
  contexto vacío pero completo (`:199`), para que ninguna plantilla reviente.

#### 1.8.5 Bitácora

`audit_record(action, resource_type, actor, tenant, resource_id, resource_repr, description,
metadata, actor_role)` (`MailySoft/backend/apps/audit/services.py:29`). **Absorbe toda excepción**:
si el INSERT falla, loguea y devuelve `None` — nunca tumba la operación de negocio (`:43-44`). El
contexto HTTP (ip, user_agent, request_id) lo lee del thread-local que pobló
`TenantAPIView.check_permissions()` (`core/views.py:186`), así que los services no se acoplan a HTTP.

---

### 1.9 Endpoints de tenancy

Prefijo: `/api/v1/` (`config/urls.py:38`). Rutas en `MailySoft/backend/apps/tenancy/urls.py:11-15`.
Todas heredan de `TenantAPIView` y usan `permission_classes = [IsAuthenticated, MemberPermission]`
→ **solo owner y admin**. **Ninguna lleva guard de módulo**: la gestión de miembros no es un módulo
vendible.

| Método | Ruta | Vista:línea | Permisos | Éxito | Errores |
|---|---|---|---|---|---|
| GET | `/api/v1/miembros/` | `views.py:127` | `IsAuthenticated`+`MemberPermission` (O A) | 200, **array plano sin paginar** | 401, 403 |
| POST | `/api/v1/miembros/` | `views.py:152` | ídem | 201 `MemberOutput` | 400, 401, 403 |
| PATCH | `/api/v1/miembros/<uuid:membership_id>/` | `views.py:202` | ídem | 200 `MemberOutput` | 400, 401, 403, 404 |
| POST | `/api/v1/miembros/<uuid:membership_id>/avatar/` | `views.py:242` | ídem, `multipart/form-data` | 200 `MemberOutput` | 400, 401, 403, 404 |
| DELETE | `/api/v1/miembros/<uuid:membership_id>/avatar/` | `views.py:262` | ídem | 200 `MemberOutput` | 401, 403, 404 |

**No existe `GET /api/v1/miembros/<id>/`**: `MemberDetailApi` solo implementa `patch` → cualquier GET
a esa ruta responde **405** (ver B-T-15).

#### `GET /api/v1/miembros/`

- **Query params:** ninguno. El único filtro es el header `X-Sucursal-Id`.
- **Alcance:** `sucursal_scope_ids(request)` — mismo criterio que agenda y finanzas
  (`views.py:145-149`). Un viewer `owner` ve a todos; un viewer no-owner ve solo personal
  operacional de sus sedes **más su propia membresía** (`selectors.py:181-187`).
- **Respuesta** (`MemberOutputSerializer`, `apps/tenancy/serializers.py:26`), por elemento:

```json
{
  "id": "uuid",
  "user": {"id":"uuid","email":"","first_name":"","last_name":"","full_name":"","avatar":null,"is_active":true},
  "role": "doctor",
  "role_display": "Médico",
  "is_active": true,
  "is_blocked": false,
  "sucursales": [{"id":"uuid","name":"Centro"}],
  "created_at": "2026-01-01T10:00:00-06:00"
}
```

`is_active` es de la **membresía**; `is_blocked` es la negación de `user.is_active` — la cuenta
bloqueada (`serializers.py:55-56`). Orden: rol, nombre, apellido (`selectors.py:177`).

#### `POST /api/v1/miembros/`

- **Entrada** (`views.py:120-125`): `email` (email, requerido), `first_name` (≤120, requerido),
  `last_name` (≤120, opcional, default `""`), `password` (≤128, write-only, requerido),
  `role` (uno de los 7).
- **Reglas del service `member_create`** (`apps/tenancy/services.py:136`), en orden:
  1. Rol válido (`:206`).
  2. Actor con membresía activa; si no la tiene, solo pasa el **bootstrap**: tenant sin ningún
     miembro y rol pedido = `owner` (`:231-240`).
  3. Anti-escalada: actor no owner solo crea roles operacionales (`:219`).
  4. Un solo dueño por clínica (`:223-230`).
  5. Rol incluido en el plan (`:247-253`) y `max_usuarios` con cupo (`:254-260`).
  6. Email no registrado (`:263-264`) y contraseña que pase los validadores de Django
     (mín. 10 caracteres, no común, no numérica, no similar al usuario — `base.py:413-421`).
  7. Sede asignada por precedencia: `X-Sucursal-Id` validado contra `allowed_sucursales` → si el
     actor no es owner, **todas** sus sedes → si es owner, ninguna (cae en la default por el
     fallback) (`:277-290`).
- **Éxito:** 201 con `MemberOutput`. Audita `MEMBER_CREATE` con el email y las sedes (`:314-325`).
- **Errores:** 400 `{"detail": ["<mensaje>"]}` para todo lo anterior; 400 con forma de serializer
  para campos mal formados; 403 sin tenant activo (`views.py:164-168`).

#### `PATCH /api/v1/miembros/<id>/`

- **Entrada** (`views.py:193-200`), todos opcionales: `first_name`, `last_name`, `role`,
  `password` (write-only, restablecer), `blocked` (bool: `true` bloquea la cuenta).
- Cuerpo vacío → **400** `{"detail": "No se proporcionaron campos para actualizar."}` (`views.py:210-214`).
- **Resolución del objetivo:** `_member_get_or_404` (`views.py:70`) acota a `allowed_sucursales`
  **del actor** (no al scope del listado) y, si el actor no es owner y el objetivo no tiene rol
  operacional, responde **404** — no revela que existe.
- **Reglas del service `member_update`** (`services.py:329`): mismas de jerarquía y anti-escalada;
  nadie puede **bloquearse a sí mismo** (`:439-440`).
- Audita `MEMBER_UPDATE` (campos cambiados), `MEMBER_PASSWORD` y `MEMBER_BLOCK` por separado
  (`:414-451`).
- **Éxito:** 200 `MemberOutput`. **Errores:** 400, 401, 403, 404 `{"detail": "Miembro no encontrado."}`.

#### `POST|DELETE /api/v1/miembros/<id>/avatar/`

- POST: `multipart/form-data`, campo **`avatar`**. Sin archivo → 400
  "No se envió ninguna imagen (campo 'avatar')" (`views.py:250-253`). La imagen pasa por
  `validate_avatar` (5 MB, JPEG/PNG/WEBP reales) antes de tocar disco (`views.py:255`).
- Ambos aplican `_authorize_write_on_member` en el service (`services.py:465`, `:494`): un admin de
  sede **no** puede cambiar ni borrar la foto de un dueño, de otro admin, ni de alguien fuera de sus
  sedes.
- Respuesta: 200 con `MemberOutput` (no 204).

---

### 1.10 Modelo de datos de tenancy

Cinco tablas, todas heredando `BaseModel` (id UUID, created_at, updated_at, deleted_at) —
**ninguna es `TenantAwareModel` y ninguna tiene política RLS**.

#### 1.10.1 `Tenant` → `tenancy_tenants` (`apps/tenancy/models.py:22`)

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `name` | `CharField(200)` | no | — | Nombre comercial |
| `slug` | `SlugField(100)` | no | — | **unique** |
| `status` | `CharField(20)` choices `trial`/`active`/`suspended` | no | `trial` | **db_index**. `suspended` bloquea todo acceso (`tenant_context.py:157-160`) |
| `trial_ends_at` | `DateTimeField` | sí | `NULL` | NULL = sin límite |
| `trial_expired_notified_at` | `DateTimeField` | sí | `NULL` | Idempotencia del aviso `TRIAL_EXPIRED` |
| `timezone` | `CharField(64)` | no | `America/Mexico_City` | **Se guarda pero no se usa para serializar fechas** (ver 1.7) |

`ordering = ["name"]`. Índices existentes: PK, unique de `slug`, `status`, `created_at`,
`deleted_at`. Migración: `0001_initial.py:18`.

#### 1.10.2 `TenantMembership` → `tenancy_memberships` (`models.py:78`)

| Campo | Tipo | `on_delete` | Null | Consecuencia |
|---|---|---|---|---|
| `user` | FK `authn.User`, `related_name="memberships"` | **CASCADE** | no | Borrar el usuario borra sus membresías (el historial de negocio queda por `created_by=SET_NULL`) |
| `tenant` | FK `Tenant`, `related_name="memberships"` | **CASCADE** | no | Borrar la clínica borra sus membresías — pero el `PROTECT` de los datos de negocio impide llegar a ese borrado |
| `role` | `CharField(20)` choices | — | no | Sin default: es obligatorio elegirlo |
| `is_active` | `BooleanField` | — | no (`True`) | **db_index**. `False` = acceso suspendido sin perder historial |

- **Unique:** `UniqueConstraint(user, tenant)` = `membership_user_tenant_uniq` (`models.py:157`,
  migración `0003:23`). Un usuario no puede tener dos roles en la misma clínica.
- **Índices:** `membership_tenant_role_idx (tenant, role)` — consulta que lo justifica: el listado de
  equipo agrupado por rol (`selectors.py:177`, `ORDER BY role`); `membership_user_active_idx
  (user, is_active)` — consulta que lo justifica: `resolve_membership_for_user`, que corre en **cada
  request autenticado** (`tenant_context.py:156-165`).

#### 1.10.3 `Plan` → `tenancy_plans` (`models.py:169`)

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `slug` | `SlugField(50)` | no | — | **unique**; identificador estable |
| `name` | `CharField(100)` | no | — | |
| `description` | `TextField` | no | `""` | |
| `price_monthly` | `DecimalField(10,2)` | no | — | MXN |
| `is_featured` | `BooleanField` | no | `False` | |
| `features` | `JSONField` | no | `[]` | **Marketing. No controla acceso** (`:202-208`) |
| `modules` | `JSONField` | no | `[]` | **Esto sí controla acceso** |
| `max_sucursales` | `PositiveIntegerField` | sí | `NULL` | NULL = ilimitado; `1` = modo sede única |
| `max_consultorios` | `PositiveIntegerField` | sí | `NULL` | |
| `max_usuarios` | `PositiveIntegerField` | sí | `NULL` | |
| `roles` | `JSONField` | no | `[]` | Allow-list; vacía = sin restricción extra |
| `is_active` | `BooleanField` | no | `True` | **db_index**. `False` = retirado del catálogo |
| `order` | `PositiveIntegerField` | no | `0` | Orden en la vitrina |

`ordering = ["order", "name"]`. Sin validación a nivel de modelo de que `modules` contenga slugs
reales: quien valida es `validar_modulos()` en el comando de siembra y en los services de plataforma.

#### 1.10.4 `TenantEntitlements` → `tenancy_entitlements` (`models.py:262`)

| Campo | Tipo | `on_delete` | Null | Notas |
|---|---|---|---|---|
| `tenant` | **OneToOne** `Tenant`, `related_name="entitlements"` | **CASCADE** | no | Una fila por clínica como mucho |
| `modules_on` | `JSONField` | — | no (`[]`) | Add-ons concedidos sobre el plan |
| `modules_off` | `JSONField` | — | no (`[]`) | Revocados aunque el plan los traiga |
| `max_sucursales` / `max_consultorios` / `max_usuarios` | `PositiveIntegerField` | — | sí | Override; `NULL` = usar el del plan |
| `notes` | `TextField` | — | no (`""`) | Por qué se concedió el trato especial |

Solo la plataforma la escribe: **ninguna clínica tiene endpoint para editar sus propios derechos**
(`models.py:265-269`).

#### 1.10.5 `TenantSubscription` → `tenancy_subscriptions` (`models.py:325`)

| Campo | Tipo | `on_delete` | Null | Notas |
|---|---|---|---|---|
| `tenant` | **OneToOne** `Tenant`, `related_name="subscription"` | **CASCADE** | no | Cambiar de plan actualiza la misma fila |
| `plan` | FK `Plan`, `related_name="subscriptions"` | **PROTECT** | no | No se puede borrar un plan con suscriptores |
| `billing_cycle` | `CharField(10)` choices `monthly`/`annual` | — | no | Sin default |
| `current_period_end` | `DateField` | — | no | Vencimiento del periodo |
| `period_expired_notified_at` | `DateTimeField` | — | sí | Idempotencia del aviso `SUBSCRIPTION_EXPIRED` |

`ordering = ["-created_at"]`.

#### 1.10.6 Índices que **no** existen y hoy no hacen falta

No hay índice sobre `tenancy_subscriptions.plan` más allá del que Django crea por la FK, ni sobre
`tenancy_plans.order`. Con 5 planes y una suscripción por clínica, cualquier índice adicional sería
peso muerto en cada escritura. No se propone ninguno.
## 2. Pacientes

> Extraído del código el 2026-08-12 (modo inverso). Alcance leído: `apps/pacientes/` completo
> (`models.py`, `views.py`, `services.py`, `selectors.py`, `serializers.py`, `urls.py`, `admin.py`,
> migraciones `0001`–`0015`). Se consultaron como insumo `apps/core/files.py`,
> `apps/core/permissions.py`, `apps/clinica/models.py` (`PatientCategory`),
> `apps/clinica/services.py` (siembra de etiquetas de sistema), `apps/agenda/services.py` y
> `MailySoft/web-soft/src/api/pacientes.ts` (solo lectura, para detectar endpoints sin consumidor).
> Rutas de archivo relativas a la raíz del repo; dentro de esta sección se abrevian a
> `apps/…` = `MailySoft/backend/apps/…`.

La capa transversal no se repite: aislamiento de tenant (§1.1), autenticación (§1.2), inventario de
clases de permiso (§1.3), módulos (§1.4), alcance por sucursal (§1.5), roles (§1.6), convenciones de
la API —paginación, formato de error, throttling— (§1.7) y modelos base (§1.8).

**Una advertencia de encuadre.** Este módulo es el directorio de pacientes: identidad, contacto y
datos NOM-004 de filiación. **No es el expediente clínico** (alergias, evoluciones, signos,
diagnósticos), que vive en `apps/expediente` y sí está detrás del módulo `expediente`. La distinción
importa porque los permisos de uno y otro son muy distintos y se confunden con facilidad.

---

### 2.1 Modelo de datos

Dos tablas, ambas `TenantAwareModel` (§1.8.2), más una tabla intermedia auto-generada por el M2M.

| Tabla | Modelo | `tenant_id` | RLS | Por qué |
|---|---|---|---|---|
| `pacientes_patients` | `Patient` (`apps/pacientes/models.py:66`) | sí, `PROTECT` | sí (`apps/pacientes/migrations/0002_enable_rls.py`, `WITH CHECK` reforzado en `0014_rls_with_check.py`) | Es el dato de la clínica |
| `pacientes_patient_sequences` | `PatientSequence` (`models.py:340`) | sí, `PROTECT` | sí (`0002_enable_rls.py`) | Consecutivo por clínica |
| `pacientes_patients_categories` | tabla `through` auto-generada del M2M `Patient.categories` | **no** (Django no lo genera) | sí, **por subconsulta al padre** (`apps/pacientes/migrations/0015_rls_patient_categories_through.py:35-53`) | Patrón obligatorio para M2M sin `through` explícito (§1.8.3 punto 2) |

#### 2.1.1 `Patient` → `pacientes_patients`

Hereda de `TenantAwareModel`: `id` (UUID), `created_at`, `updated_at`, `deleted_at`, `tenant`
(`PROTECT`), `created_by` (`SET_NULL`). Ver §1.8.

**Identidad y contacto**

| Campo | Tipo | Null | Default | Línea | Notas |
|---|---|---|---|---|---|
| `first_name` | `CharField(120)` | no | — | `models.py:77` | Obligatorio siempre |
| `paternal_surname` | `CharField(120)` | no | — | `:81` | Obligatorio siempre |
| `maternal_surname` | `CharField(120)` | no | `""` | `:85` | |
| `date_of_birth` | `DateField` | **sí** | `NULL` | `:91` | Nulo solo en provisionales |
| `sex` | `CharField(1)` choices `M`/`F`/`X` | no | `""` | `:96` | `Sex` (`:22`), NOM-024. Vacío en provisionales |
| `curp` | `CharField(18)` | no | `""` | `:103` | Único por clínica **cuando no está vacío** |
| `phone` | `CharField(20)` | no | `""` | `:109` | WhatsApp de contacto |
| `email` | `EmailField` | no | `""` | `:115` | |
| `record_number` | `CharField(30)` | no | — | `:120` | Lo genera el service; inmutable (`services.py:277`) |
| `notes` | `TextField` | no | `""` | `:124` | **Notas internas del expediente, texto libre** |
| `is_active` | `BooleanField` **db_index** | no | `True` | `:129` | `False` = desactivado. **No es** `deleted_at` |
| `is_provisional` | `BooleanField` **db_index** | no | `False` | `:134` | Alta al vuelo desde agenda |
| `avatar` | `ImageField(max_length=255)` | **sí** | `NULL` | `:144` | `upload_to=patient_avatar_path` |

**Campos NOM-004 (todos opcionales, `blank=True, default=""` salvo donde se indique)**

`address_street` (255, `:157`) · `address_neighborhood` (120, `:163`) · `city` (120, `:169`) ·
`state` (120, `:175`) · `postal_code` (10, `:181`) · `birthplace` (160, `:187`) ·
`marital_status` (choices `MaritalStatus`, `:193`) · `education` (choices `Education`, `:200`) ·
`occupation` (120, `:207`) · `religion` (80, `:213`) · `blood_type` (choices `BloodType`, `:219`) ·
`phone_secondary` (20, `:226`) · `phone_label` (40, `:232`).

| Campo | Tipo | Null | Default | Línea |
|---|---|---|---|---|
| `is_deceased` | `BooleanField` | no | `False` | `:238` |
| `deceased_at` | `DateField` | **sí** | `NULL` | `:242` |
| `custom_consultation_fee` | `DecimalField(10,2)` | **sí** | `NULL` | `:247` | `NULL` = tarifa estándar de la clínica |

**Clasificación**

| Campo | Tipo | Null | Default | Línea | Notas |
|---|---|---|---|---|---|
| `category` | `CharField(60)` | no | `""` | `:257` | **Legacy v1**, texto libre. Sigue siendo editable por PATCH |
| `categories` | `M2M` a `clinica.PatientCategory`, `related_name="patients"` | — | vacío | `:266` | Etiquetas del catálogo. **Sin `through` explícito** → obligó a la migración `0015` |

**Constraints** (`models.py:280-292`)

| Nombre | Definición | Consecuencia real |
|---|---|---|
| `patient_record_number_uniq` | `UNIQUE(tenant, record_number)` | Dos clínicas pueden tener `EXP-2026-00001`; una clínica no |
| `patient_curp_uniq` | `UNIQUE(tenant, curp)` **parcial**, `condition=~Q(curp="")` | Muchos pacientes sin CURP conviven; una CURP no se repite en la clínica. **No excluye borrados lógicos** → ver B-PAC-04 |

**Índices** (`models.py:293-329`)

| Índice | Consulta que lo justifica |
|---|---|
| `patient_apellidos_idx (tenant, paternal_surname, maternal_surname)` `:295` | Búsqueda por apellidos desde recepción |
| `patient_first_name_trgm` GIN `gin_trgm_ops` `:304` | `first_name__icontains` del OR de `patient_list` (`selectors.py:124`) |
| `patient_paternal_trgm` `:309` | `paternal_surname__icontains` (`selectors.py:125`) |
| `patient_maternal_trgm` `:314` | `maternal_surname__icontains` (`selectors.py:126`) |
| `patient_phone_trgm` `:319` | `phone__icontains` (`selectors.py:127`) |
| `patient_record_num_trgm` `:324` | `record_number__icontains` (`selectors.py:128`) |
| implícitos | `is_active` `:131`, `is_provisional` `:136`, `tenant` (FK), `created_at` y `deleted_at` (§1.8.1) |

Los cinco GIN existen porque Postgres solo puede indexar un `OR` completo si **cada** rama tiene su
índice; con uno solo faltando, el planificador cae en seq scan (razón escrita en `models.py:299-303`).
Requieren la extensión `pg_trgm`, que crea la propia migración `0012` antes de los índices. Límite
real, no documentado en el código: los trigramas **no sirven para patrones de 1 o 2 caracteres**
(ver B-PAC-11).

`ordering = ["-created_at"]` (`models.py:279`). Propiedad calculada `full_name` (`:334`).

**Índices que NO existen y hoy no hacen falta:** ninguno sobre `curp` solo (la constraint parcial ya
crea uno), ninguno sobre `email`, ninguno compuesto `(tenant, is_active)`. Con el volumen declarado
(§8 del análisis: 1–3 usuarios concurrentes) cualquier índice adicional es peso muerto en cada
escritura. No se propone ninguno.

#### 2.1.2 `PatientSequence` → `pacientes_patient_sequences`

| Campo | Tipo | Null | Default | Línea |
|---|---|---|---|---|
| `last_number` | `PositiveIntegerField` | no | `0` | `models.py:348` |

Constraint `patient_sequence_tenant_uniq` = `UNIQUE(tenant)` (`:359`). Existe para que la base
rechace la segunda fila en una carrera y el `get_or_create` falle con `IntegrityError` controlable en
vez de crear dos secuencias silenciosas (`models.py:355-357`).

#### 2.1.3 Historia del modelo que hay que conocer

`is_favorite` e `is_vip` **fueron campos booleanos** (migración `0007_patient_is_favorite_is_vip.py`),
se migraron a etiquetas de sistema (`0010_migrar_favorito_vip_a_etiquetas.py`) y las columnas se
eliminaron (`0011_remove_patient_is_favorite_remove_patient_is_vip.py`). Hoy son filas
`PatientCategory` con `kind=favorite|vip`, y la API los sigue exponiendo como booleanos derivados
(`serializers.py:87-93`). Cualquier consulta SQL heredada contra esas columnas está rota.

---

### 2.2 Endpoints

Prefijo `/api/v1/` (§1.7). Rutas en `apps/pacientes/urls.py:17-28`. **Las cinco vistas heredan de
`TenantAPIView` y llevan `permission_classes = [IsAuthenticated, PatientPermission]`
(§1.3.2 #2).**

**Ninguna lleva guard de módulo.** Verificado: `apps/pacientes/views.py` no importa
`entitlement_guards`. Es coherente con el catálogo — `pacientes` no es un módulo vendible
(`apps/core/modules.py:24`); el directorio de pacientes es base del producto. El módulo `expediente`
gatea `apps/expediente`, no esto.

| # | Método | Ruta | Vista:línea | Roles | Éxito | Errores |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/v1/pacientes/` | `views.py:165` | **TODOS** | 200 paginado | 400, 401, 403, 500 |
| 2 | POST | `/api/v1/pacientes/` | `views.py:195` | O A D N R | 201 `PatientOutput` | 400, 401, 403 |
| 3 | POST | `/api/v1/pacientes/rapido/` | `views.py:248` | O A D N R | 201 `PatientOutput` | 400, 401, 403 |
| 4 | GET | `/api/v1/pacientes/<uuid:patient_id>/` | `views.py:404` | **TODOS** | 200 `PatientOutput` | 401, 403, 404 |
| 5 | PATCH | `/api/v1/pacientes/<uuid:patient_id>/` | `views.py:425` | O A D N R | 200 `PatientOutput` | 400, 401, 403, 404 |
| 6 | DELETE | `/api/v1/pacientes/<uuid:patient_id>/` | `views.py:455` | **O A** | **204 sin cuerpo** | 401, 403, 404 |
| 7 | POST | `/api/v1/pacientes/<uuid:patient_id>/avatar/` | `views.py:476` | O A D N R | 200 `PatientOutput` | 400, 401, 403, 404 |
| 8 | DELETE | `/api/v1/pacientes/<uuid:patient_id>/avatar/` | `views.py:497` | **O A** | 200 `PatientOutput` (no 204) | 401, 403, 404 |
| 9 | POST | `/api/v1/pacientes/<uuid:patient_id>/clasificacion/` | `views.py:524` | O A D N R | 200 `PatientOutput` | 400, 401, 403, 404 |

**Endpoint sin consumidor conocido:** el **#8** (`DELETE .../avatar/`). `web-soft/src/api/pacientes.ts`
tiene cliente para los otros ocho y **ninguno** para quitar la foto (`pacientes.ts:93-106`). Es
código expuesto que nadie usa → B-PAC-08.

**Métodos no ruteados.** El código de respuesta depende del rol, no del método, porque
`check_permissions` corre antes del ruteo del handler: `PUT /pacientes/<id>/` da **403** para todos
(no hay clave `"PUT"` en `PatientPermission.policy`, §1.3.1); `DELETE /pacientes/` da **403** para
D/N/R/F/L y **405** para owner y admin (pasan el permiso y no hay handler). Ver B-PAC-12.

**Alcance por sucursal: ninguno.** `Patient` no tiene campo `sucursal` y ninguna vista llama a
`sucursal_scope_ids` ni a `resolve_active_sucursal` (verificado en todo `apps/pacientes/`). Un
paciente pertenece a la clínica, no a una sede. Consecuencia: en una clínica con dos sedes, la
recepcionista de Norte ve y edita el directorio completo, incluidos los pacientes que solo se
atienden en Centro → B-PAC-03.

---

#### 2.2.1 `GET /api/v1/pacientes/`

**Query params** (`FilterSerializer`, `views.py:114-144`):

| Param | Tipo | Default | Notas |
|---|---|---|---|
| `search` | string | `""` | `icontains` con OR sobre `first_name`, `paternal_surname`, `maternal_surname`, `phone`, `record_number` (`selectors.py:123-129`). **No busca por CURP ni por email** |
| `segment` | choice | `all` | `all` · `recent` · `week` · `month` · `date` · `potential` · `favorites` · `vip` |
| `date_from`, `date_to` | date | — | **Obligatorios y validados** solo si `segment=date` (`views.py:137-144`) |
| `category` | UUID | — | Filtra por etiqueta del catálogo; combinable con cualquier segmento (`selectors.py:230-231`) |
| `page` | int | 1 | `PageNumberPagination` estándar, 25 por página, **`page_size` no admitido** (§1.7.1) |

Semántica de los segmentos (`selectors.py:166-225`), toda calculada contra `agenda.Appointment`:

| Segmento | Filtro | Orden |
|---|---|---|
| `all` (y cualquier valor desconocido) | ninguno | `-created_at` |
| `recent` | tiene ≥1 cita `attended` | `-last_seen` |
| `week` | atendido en la semana calendario local (lunes 00:00, `_week_bounds` `:248`) | `-last_seen` |
| `month` | atendido en el mes calendario local (`_month_bounds` `:265`) | `-last_seen` |
| `date` | atendido en `[date_from, date_to]` inclusive (`_date_range_bounds` `:278`) | `-last_seen` |
| `potential` | `attended_count=0` **y** (canceladas>0 **o** reagendadas>0) | `-created_at` |
| `favorites` | tiene etiqueta `kind=favorite` | `-created_at` |
| `vip` | tiene etiqueta `kind=vip` | `-created_at` |

Base fija del listado: `Patient.objects.filter(is_active=True)` (`selectors.py:116`). **El listado
nunca muestra pacientes desactivados**, ni siquiera con un filtro; tampoco distingue provisionales.

Anotaciones que se calculan **siempre**, aunque el segmento no las use (`selectors.py:133-163`):
`last_seen`, `attended_count`, `cancelled_count`, `rescheduled_count`, `last_reason`. Son 4
agregados con `filter=` más un `Subquery` correlacionado por fila; a 25 filas por página es
irrelevante, y está escrito así para que el serializer pueda leerlas con `getattr` sin ramificar.

**Respuesta 200** — sobre `{count, next, previous, results}` (§1.7.1), cada elemento es
`PatientOutputSerializer` (`apps/pacientes/serializers.py:18`), **el mismo objeto completo que
devuelve el detalle**:

```json
{
  "id": "uuid",
  "full_name": "Ana López Pérez",
  "avatar": "https://…/avatars/pacientes/<uuid>.jpg",
  "first_name": "Ana", "paternal_surname": "López", "maternal_surname": "Pérez",
  "date_of_birth": "1980-05-02",
  "sex": "F", "sex_display": "Femenino",
  "curp": "LOPA800502MDFPRN04",
  "phone": "5512345678", "email": "ana@ejemplo.mx",
  "record_number": "EXP-2026-00042",
  "notes": "Prefiere cita por la tarde",
  "is_active": true, "is_provisional": false,
  "is_favorite": true, "is_vip": false,
  "address_street": "", "address_neighborhood": "", "city": "", "state": "",
  "postal_code": "", "birthplace": "",
  "marital_status": "casado", "marital_status_display": "Casado/a",
  "education": "licenciatura", "education_display": "Licenciatura",
  "occupation": "", "religion": "",
  "blood_type": "O+", "blood_type_display": "O+",
  "phone_secondary": "", "phone_label": "",
  "is_deceased": false, "deceased_at": null,
  "custom_consultation_fee": "800.00",
  "category": "",
  "categories": [{"id": "uuid", "name": "Asegurado IMSS"}],
  "created_at": "2026-01-15T10:00:00-06:00",
  "last_seen_at": "2026-08-01T17:30:00-06:00",
  "attended_count": 12,
  "last_reason": "Control de presión"
}
```

Detalles del serializer que el front debe conocer:

- `categories` expone **solo** las etiquetas `kind=custom`; Favorito y VIP salen como
  `is_favorite`/`is_vip` (`serializers.py:80-93`), derivados del prefetch — no hay query extra.
- `last_seen_at` y `attended_count` son `null` en el detalle individual (`patient_get` no anota,
  `serializers.py:48-54`).
- **`last_reason` se filtra por rol** (`serializers.py:56-78`): si `request.active_role` no está en
  `APPOINTMENT_VIEW_ROLES` (`apps/core/permissions.py:76`) devuelve `null`. El rol `finance` nunca lo
  recibe, porque `Appointment.reason` es información clínica y `AppointmentPermission.GET` lo excluye
  (§1.3.2 #4). Es el único control de PII por rol que existe en esta app y es **fail-closed**: sin
  request o sin rol resuelto, `null`.

**Errores:** 400 con forma de serializer si `segment=date` sin fechas; 401 sin token; 403 sin
membresía activa o con contraseña temporal pendiente (§1.2.4); **500** con
`{"detail": "Paginación no disponible…"}` si `PAGE_SIZE` no estuviera configurado
(`views.py:190-193`) — camino teóricamente inalcanzable, pero es el contrato escrito.

#### 2.2.2 `POST /api/v1/pacientes/`

**Entrada** (`InputSerializer`, `views.py:146-163`) — nótese que exige **más** que el modelo:

| Campo | Tipo | Requerido | Validación extra |
|---|---|---|---|
| `first_name` | ≤120 | **sí** | — |
| `paternal_surname` | ≤120 | **sí** | — |
| `maternal_surname` | ≤120 | no (`""`) | — |
| `date_of_birth` | date | **sí** | (el modelo la permite nula; aquí no) |
| `sex` | choice `M/F/X` | **sí** | revalidado en el service (`services.py:143-147`) |
| `phone` | ≤20 | **sí** | regex `^\+?[\d\s\-\(\)]{7,20}$` (`views.py:54`) |
| `curp` | ≤18 | no (`""`) | regex RENAPO `^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z\d]\d$`, case-insensitive, **normaliza a mayúsculas** (`views.py:51-79`) |
| `email` | email | no (`""`) | — |
| `notes` | ≤5000 | no (`""`) | — |

**No se aceptan** los campos NOM-004 en el alta: solo por PATCH posterior. Campos desconocidos se
**ignoran en silencio** (a diferencia del PATCH, que los rechaza).

**Reglas del service `patient_create`** (`apps/pacientes/services.py:96`), en orden:
1. `sex` dentro de los choices, si no `ValidationError` → 400 (`:143`).
2. Dentro de `transaction.atomic()`: si hay CURP, no debe existir otra igual **no borrada** en el
   tenant (`:155-162`).
3. `record_number` = `_next_record_number(tenant)` (`:32`): `SELECT FOR UPDATE` +
   `get_or_create` sobre `PatientSequence` con `all_objects` (justificado en `:74-78`), incremento,
   y formato **`EXP-<año>-<5 dígitos>`** (`:88`). El `TODO(3c)` de `:49-52` deja constancia de que el
   formato configurable por clínica **no está implementado**.
4. `IntegrityError` → 400 "Error de concurrencia al generar el número de expediente…" (`:180-187`).

**Éxito:** 201 con el `PatientOutput` completo. Audita `PATIENT_CREATE` con
`resource_repr=record_number` (identificador no-PII, `:189-196`).
**Errores:** 400 de serializer `{"campo": ["…"]}`; 400 de service `{"detail": ["…"]}` (lista, §1.7.2);
403 `{"detail": "No se encontró un tenant activo para este request."}` (`views.py:200-205`).

**No hay detección de duplicados.** Dos altas con el mismo nombre y fecha de nacimiento producen dos
expedientes con consecutivos distintos. Coincide con lo declarado como no construido en
`MailySoft/docs/01-analisis.md:268`.

#### 2.2.3 `POST /api/v1/pacientes/rapido/`

Alta **provisional** con datos mínimos. Entrada (`views.py:236-246`): `first_name` y
`paternal_surname` requeridos; `maternal_surname` y `phone` opcionales (el teléfono, si viene, pasa
la misma regex). El service `patient_create_quick` (`services.py:205`) fija
`date_of_birth=None`, `sex=""`, `is_provisional=True` y consume **el mismo consecutivo** que el alta
normal (`:239`). Audita `PATIENT_CREATE` con `metadata={"provisional": True}` (`:257-265`).

El mismo service se llama desde la agenda para crear paciente y cita en una sola transacción
(`apps/agenda/services.py:629` y `:733`). Esa ruta se gatea con `AppointmentPermission` +
`RequiresAgenda`, no con `PatientPermission`: **un alta de paciente puede entrar por dos puertas con
permisos distintos**. La de agenda es más estrecha (POST de cita = O A D R, sin `nurse`), así que no
abre nada, pero conviene saberlo.

#### 2.2.4 `GET /api/v1/pacientes/<id>/`

`patient_get` = `Patient.objects.get(id=...)` (`selectors.py:44`): el `TenantManager` filtra por
tenant y excluye soft-deleted; **no filtra `is_active`**, así que un paciente desactivado sigue
siendo legible y editable por id (B-PAC-05). `DoesNotExist` → 404
`{"detail": "Paciente no encontrado."}`.

Es el **único** endpoint de la app que audita la lectura: `PATIENT_READ` con
`resource_repr=record_number` y `actor_role`, registrado antes de serializar y sin poder tumbar la
respuesta (`views.py:413-421`; `audit_record` absorbe excepciones, §1.8.5). El listado del 2.2.1
**no audita nada** → B-PAC-06.

#### 2.2.5 `PATCH /api/v1/pacientes/<id>/`

**Entrada** (`views.py:283-389`): todos los campos opcionales. Además de los del alta acepta los 13
campos NOM-004, `custom_consultation_fee`, `category` (texto legacy) y `category_ids` (lista de UUID).

Validaciones propias del serializer:
- **Whitelist estricta**: cualquier campo no declarado → 400 `{"<campo>": ["Campo no permitido."]}`
  (`views.py:366-375`). Es el único serializer de esta app que lo hace.
- `postal_code`: regex `^\d{5}$` con mensaje propio (`views.py:314-321`).
- `phone_secondary`: misma regex que `phone` si no viene vacío (`:360-364`).
- Coherencia: `is_deceased=true` sin `deceased_at` → 400; `is_deceased=false` **limpia**
  `deceased_at` a `None` aunque el cliente no lo mande (`:377-387`).
- Cuerpo vacío tras validar → 400 `{"detail": "No se proporcionaron campos para actualizar."}`
  (`views.py:434-438`).

**Reglas del service `patient_update`** (`services.py:282`):
- Campos inmutables rechazados con 400: `record_number`, `tenant`, `tenant_id`, `id`, `created_at`,
  `deleted_at`, `is_active`, `is_provisional`, `updated_at` (`services.py:277-279`). El serializer ya
  no los expone; la defensa es doble a propósito.
- CURP: si cambia y no está vacía, revalida unicidad excluyéndose a sí mismo (`:329-336`).
- **Auto-completado de provisional**: si el paciente era provisional y tras el PATCH ya tiene
  `date_of_birth`, `sex` y `phone`, `is_provisional` pasa a `False` solo (`:346-348`). Es la única
  forma de quitar esa bandera.
- `category_ids` reemplaza **solo** las etiquetas `kind=custom` y **conserva** Favorito/VIP
  (`:360-377`). Los UUID que no correspondan a una etiqueta activa `custom` del tenant se
  **descartan en silencio**, sin error → B-PAC-10.
- Audita `PATIENT_UPDATE` con `metadata={"changed_fields": [...]}` (`:379-387`).

#### 2.2.6 `DELETE /api/v1/pacientes/<id>/`

Solo owner y admin. Llama `patient_deactivate` (`services.py:510`), que pone `is_active=False` y
**no toca `deleted_at`**. Responde **204 sin cuerpo**. Audita `PATIENT_DEACTIVATE`.

**No existe endpoint para reactivar.** Ni PATCH (el campo es inmutable) ni ningún otro: recuperar un
expediente desactivado exige el admin de Django o la consola → B-PAC-05.

#### 2.2.7 `POST|DELETE /api/v1/pacientes/<id>/avatar/`

- `parser_classes = [MultiPartParser, FormParser]` (`views.py:474`). Campo **`avatar`**.
- Sin archivo → 400 `{"detail": "No se envió ninguna imagen (campo 'avatar')."}` (`views.py:484-488`).
- `validate_avatar` (§1.8.4): ≤5 MB, JPEG/PNG/WEBP verificados con Pillow sobre el **contenido**, no
  la extensión; tope de 40 MP contra bombas de descompresión; falla cerrado. Error → 400
  `{"detail": ["…"]}`.
- `patient_set_avatar` borra el archivo anterior antes de asignar el nuevo, para no dejar huérfanos
  (`services.py:398-399`). `patient_clear_avatar` hace lo mismo y deja `avatar=None` (`:414-419`).
- Ambos responden **200 con el `PatientOutput` completo** (no 204).
- Ruta de almacenamiento: `avatars/pacientes/<uuid-hex>.<ext>` (`apps/core/files.py:165-167`) —
  nombre aleatorizado, **sin prefijo de tenant** (a diferencia de las imágenes clínicas, que sí van a
  `evoluciones/<tenant_id>/`). Ver B-PAC-02.

#### 2.2.8 `POST /api/v1/pacientes/<id>/clasificacion/`

**Entrada** (`views.py:520-522`): `is_favorite` y `is_vip`, ambos booleanos **opcionales**. Ausente =
sin cambio; ninguno de los dos = no escribe nada y responde 200 con el paciente intacto
(`services.py:490-491`).

`patient_set_classification` (`services.py:437`) agrega o quita la fila `PatientCategory` de sistema
correspondiente en el M2M. Si la etiqueta de sistema no existiera en la clínica, **la siembra al
vuelo** llamando `seed_system_patient_categories` (`services.py:466-471`) → un POST de clasificación
puede crear filas en el catálogo de la clínica (B-PAC-09). Audita `PATIENT_UPDATE` con
`metadata={"classification": [...]}` solo si hubo cambio.

El catálogo de etiquetas se administra en otra app: `GET|POST /api/v1/clinica/categorias/` y
`/api/v1/clinica/categorias/<id>/` (`apps/clinica/urls.py:66-74`), con
`PatientCategoryPermission` — GET todos, POST/DELETE owner y admin (§1.3.5).

---

### 2.3 Reglas de negocio verificadas en código

1. **El borrado es lógico, en dos niveles distintos y no equivalentes.** `is_active=False` es la baja
   de negocio y es lo único que expone la API (`services.py:530`). `deleted_at` es el soft-delete de
   `BaseModel` y **ningún endpoint de esta app lo escribe** (verificado en todo
   `apps/pacientes/services.py`). Un paciente "borrado" desde la app sigue con `deleted_at IS NULL` y
   por tanto sigue visible para el `TenantManager`, para el expediente, para la agenda y para
   finanzas; solo desaparece del listado de `/pacientes/`.
2. **El número de expediente es del sistema.** Formato fijo `EXP-<año>-<00000>`, generado con
   `SELECT FOR UPDATE` dentro de `transaction.atomic()`; el service revienta con `RuntimeError` si se
   le llama fuera de transacción (`services.py:69-72`). No se reinicia por año pese al `TODO(3c)`
   (`:49-52`): en enero de 2027 el siguiente será `EXP-2027-00043` si el último de 2026 fue el 42.
   Provisionales y altas normales comparten la misma secuencia.
3. **CURP única por clínica, opcional siempre.** Nunca única entre clínicas: el mismo paciente en dos
   clínicas son dos expedientes sin relación (coherente con el Master Patient Index descartado,
   `01-analisis.md:253`).
4. **Favorito y VIP no son campos: son etiquetas de sistema.** Se siembran al dar de alta la clínica
   (`apps/plataforma/services.py:306`), no se pueden borrar ni renombrar
   (`apps/clinica/models.py:353-360`), y hay constraint de una sola por tipo y clínica
   (`clinic_category_one_system_per_kind`, `clinica/models.py:396-400`).
5. **La bandera de provisional se apaga sola** cuando el expediente reúne fecha de nacimiento, sexo y
   teléfono (`services.py:346-348`). No hay forma de encenderla o apagarla a mano.
6. **`last_reason` es el único dato de la respuesta filtrado por rol** y su fuente de verdad de roles
   es compartida con la agenda para que no se desincronicen (`serializers.py:64-67`).
7. **La búsqueda es del servidor, no del cliente**: no hay endpoint de "buscar" separado; es el
   parámetro `search` del listado, sin longitud mínima y sin límite de longitud declarado.
8. **La API no expone `deleted_at` ni `created_by`** (`serializers.py:95-145`, `read_only_fields =
   fields`): el serializer entero es de solo lectura, toda escritura pasa por los `InputSerializer`
   de cada vista.

---

### 2.4 Matriz de permisos del módulo

Fuente única: `PatientPermission` (`apps/core/permissions.py:144-159`), §1.3.2 #2. No hay
`has_object_permission` en ninguna parte (§1.3.6): **el permiso es por rol, nunca por registro**. No
existe la noción de "mis pacientes": un médico ve y edita a todos los de la clínica.

Leyenda: **Sí** = permitido sobre cualquier registro de la clínica · **No** = 403 · **n/a** = no hay
tal acción.

| Acción | owner | admin | doctor | nurse | reception | finance | readonly |
|---|---|---|---|---|---|---|---|
| Listar pacientes (`GET /pacientes/`) | Sí | Sí | Sí | Sí | Sí | **Sí** | **Sí** |
| Ver detalle (`GET /pacientes/<id>/`) | Sí | Sí | Sí | Sí | Sí | **Sí** | **Sí** |
| Ver `last_reason` (motivo de cita) | Sí | Sí | Sí | Sí | Sí | **No** (null) | Sí |
| Crear paciente completo (`POST /pacientes/`) | Sí | Sí | Sí | Sí | Sí | No | No |
| Crear provisional (`POST /pacientes/rapido/`) | Sí | Sí | Sí | Sí | Sí | No | No |
| Editar paciente (`PATCH`) | Sí | Sí | Sí | Sí | Sí | No | No |
| Asignar etiquetas (`category_ids` en PATCH) | Sí | Sí | Sí | Sí | Sí | No | No |
| Marcar Favorito/VIP (`POST .../clasificacion/`) | Sí | Sí | Sí | Sí | Sí | No | No |
| Subir/reemplazar foto (`POST .../avatar/`) | Sí | Sí | Sí | Sí | Sí | No | No |
| Quitar foto (`DELETE .../avatar/`) | Sí | Sí | **No** | **No** | **No** | No | No |
| Desactivar paciente (`DELETE /pacientes/<id>/`) | Sí | Sí | No | No | No | No | No |
| Reactivar paciente | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Borrar físicamente | n/a (solo `/admin/`, superuser — `apps/pacientes/admin.py:140-142`) | n/a | n/a | n/a | n/a | n/a | n/a |
| Acotar por sucursal | n/a — el módulo no tiene alcance por sede | n/a | n/a | n/a | n/a | n/a | n/a |

Dos celdas que llaman la atención y son código, no descuido de esta tabla: `finance` y `readonly`
**leen todo el directorio de pacientes** (fila 1 y 2, `permissions.py:155` = `ALL_ROLES`), y quitar
la foto exige un rol más alto que ponerla (filas 9 y 10, `permissions.py:156` vs `:158`).

`OPTIONS` pasa siempre sin mirar rol (§1.3.1, B-T-01). `HEAD` se evalúa como `GET`.

---

### 2.5 Datos personales expuestos por endpoint

`PatientOutputSerializer` es **el mismo para los nueve endpoints**: el listado devuelve exactamente
el mismo objeto que el detalle. No hay serializer reducido para listas.

| Dato | Categoría | Endpoints que lo devuelven | Roles que lo reciben |
|---|---|---|---|
| Nombre completo, foto | PII identificativa | 1, 2, 3, 4, 5, 7, 8, 9 | **los 7** |
| Fecha de nacimiento, sexo | PII | ídem | **los 7** |
| **CURP** | PII de identificación oficial | ídem | **los 7** |
| Teléfono, teléfono secundario y su etiqueta, email | PII de contacto | ídem | **los 7** |
| Domicilio completo (calle, colonia, ciudad, estado, CP) | PII de localización | ídem | **los 7** |
| Lugar de nacimiento, estado civil, escolaridad, ocupación, **religión** | PII sensible (LFPDPPP art. 3 fr. VI: religión es dato sensible) | ídem | **los 7** |
| **Tipo de sangre** | **Dato de salud** | ídem | **los 7** |
| **`is_deceased` / `deceased_at`** | **Dato de salud** | ídem | **los 7** |
| `notes` (notas internas, texto libre) | Impredecible: lo que escriba el capturista | ídem | **los 7** |
| `custom_consultation_fee` | Dato económico del paciente | ídem | **los 7** |
| `record_number` | Identificador **no-PII** — es el que va a la bitácora | ídem | los 7 |
| Etiquetas (`categories`, `is_favorite`, `is_vip`) | Clasificación comercial | ídem | los 7 |
| `last_seen_at`, `attended_count` | Metadato clínico (frecuencia de atención) | 1 (listado) | los 7 |
| **`last_reason`** (motivo de la cita) | **Dato clínico** | 1 (listado) | los 6 de `APPOINTMENT_VIEW_ROLES`; `finance` recibe `null` |

**Lo que esto significa en la práctica.** `01-analisis.md:282-285` afirma: *"Recepción y Finanzas no
leen expediente ni recetas"*. Es cierto de `apps/expediente` y `apps/recetas`. **No es cierto del
directorio de pacientes**: un usuario `finance` —cuyo trabajo es cobrar— y un usuario `readonly`
reciben CURP, domicilio, religión, tipo de sangre y estado de defunción de cada paciente de la
clínica, paginados de 25 en 25, sin que quede rastro en la bitácora. La única PII que el código
protege por rol es `last_reason`. Ver B-PAC-01 y B-PAC-06.

**Minimización en la bitácora:** todas las llamadas a `audit_record` de esta app usan
`resource_repr=patient.record_number` con el comentario explícito "identificador no-PII (LFPDPPP)"
(`services.py:195`, `:263`, `:385`, `:408`, `:426`, `:539`; `views.py:419`). Esa parte sí está bien
hecha y es el contraste que hace visible el problema de la app `notas` (ver §9.5).

**El avatar es un caso aparte.** El campo se serializa como URL. Con
`DJANGO_DEFAULT_FILE_STORAGE=cloudinary_storage.storage.MediaCloudinaryStorage`
(`config/settings/base.py:348-354`, documentado como el piloto de producción en
`config/settings/production.py:100-102`) esa URL es de entrega pública del CDN: **no hay firma, no
hay expiración y no hay comprobación de token**. Quien tenga la URL ve la cara del paciente sin
sesión. Ver B-PAC-02.

---

### 2.6 Efectos secundarios

| Acción | Efecto colateral | Dónde |
|---|---|---|
| `POST /pacientes/` y `/pacientes/rapido/` | Incrementan `PatientSequence.last_number` del tenant **dentro** de la transacción; si la creación falla después, el número se devuelve con el rollback | `services.py:79-88` |
| `POST /pacientes/` | Bitácora `PATIENT_CREATE` | `services.py:189` |
| `POST /pacientes/rapido/` | Bitácora `PATIENT_CREATE` con `metadata.provisional=true` | `services.py:257` |
| `GET /pacientes/<id>/` | Bitácora `PATIENT_READ` (**una fila por apertura de ficha**) | `views.py:413` |
| `PATCH /pacientes/<id>/` | Bitácora `PATIENT_UPDATE` con la lista de campos; puede **apagar `is_provisional`** sin que el cliente lo pida; puede **reemplazar el set completo de etiquetas custom** | `services.py:346`, `:360-377`, `:379` |
| `POST .../avatar/` | **Borra físicamente el archivo anterior** del storage (irreversible) + bitácora `PATIENT_UPDATE` | `services.py:398-410` |
| `DELETE .../avatar/` | Ídem, borrado físico + bitácora | `services.py:416-428` |
| `POST .../clasificacion/` | Puede **crear filas `PatientCategory`** en el catálogo de la clínica si faltaban las de sistema + bitácora `PATIENT_UPDATE` | `services.py:466-471`, `:493` |
| `DELETE /pacientes/<id>/` | Bitácora `PATIENT_DEACTIVATE`. **No** cancela citas futuras, **no** cierra cargos abiertos, **no** toca el expediente clínico (verificado: `patient_deactivate` solo escribe `is_active`) | `services.py:510-541` |
| Alta de clínica (`apps/plataforma`) | Siembra las etiquetas de sistema Favorito y VIP de las que depende este módulo | `apps/plataforma/services.py:306` |
| Crear cita con paciente nuevo (`apps/agenda`) | Crea un `Patient` provisional en la misma transacción que la cita | `apps/agenda/services.py:629`, `:733` |

**Lo que NO ocurre y podría esperarse:** no hay señales (`post_save`), no hay tareas Celery, no hay
notificaciones de campana y no hay invalidación de caché en toda la app (verificado: `apps/pacientes/`
no importa `celery`, `signals` ni `cache`). El único acoplamiento hacia afuera son las escrituras en
la bitácora y en el catálogo de etiquetas.
## 3. Agenda

> Extraído del código el 2026-08-12 (modo inverso). App `MailySoft/backend/apps/agenda/`.
> Cada afirmación cita `archivo:línea`. Lo no verificable lleva el prefijo **NO VERIFICADO**.
> **Convención de rutas de esta sección:** dentro de tablas se abrevia `apps/agenda/views.py` =
> `MailySoft/backend/apps/agenda/views.py` (misma abreviatura que usa §1); fuera de tablas, cuando
> el archivo no es de `apps/agenda`, se escribe la ruta completa desde la raíz del repo.
>
> Alcance leído: `models.py`, `views.py`, `urls.py`, `services.py`, `selectors.py`, `serializers.py`,
> `notes.py`, `blocks.py`, `reminders.py`, `tasks.py`, `series.py`, `appointment_types.py`,
> `admin.py`, `apps.py`, las 16 migraciones, y `MailySoft/backend/adapters/whatsapp.py`. Los tests
> solo se consultaron para confirmar reglas (`tests/test_sucursal_idor_fixes.py`,
> `tests/test_reminders.py`).
>
> Este módulo depende de la capa transversal: aislamiento de tenant §1.1, permisos §1.3, gating de
> módulo §1.4, alcance por sucursal §1.5, convenciones de API §1.7, modelos base §1.8.
> **Ninguna clase de permiso nueva:** las cinco que usa la app ya están inventariadas en §1.3
> (`AppointmentPermission` #4, `AppointmentStatusPermission` #5, `AppointmentTypePermission` #7,
> `AgendaConfigPermission` #8, `AgendaItemNotePermission` #19).

---

### 3.1 Modelo de datos

Seis modelos, **los seis heredan `TenantAwareModel`** (§1.8.2): todos llevan `tenant_id` con
`on_delete=PROTECT`, `created_by` con `SET_NULL`, `id` UUID, `created_at`/`updated_at`/`deleted_at`,
y los dos managers `objects` (filtra tenant + soft-delete) y `all_objects` (sin filtro).
**Los seis tienen política RLS con `USING` y `WITH CHECK`** — ninguno depende del test guardián para
descubrirlo (`migrations/0002_enable_rls_and_constraints.py:33-57`,
`migrations/0012_rls_appointment_types_blocks_item_notes.py:33-76`,
`migrations/0013_rls_with_check.py:26-30`, `migrations/0005_appointment_reminder_rls.py`).
**No hay ningún `ManyToManyField` en esta app**, así que no hay tabla through que cubrir (§1.8.3.2).

| Tabla | Modelo | `tenant_id` | RLS | Por qué |
|---|---|---|---|---|
| `agenda_tenant_config` | `TenantAgendaConfig` | sí | sí | Ajustes de la clínica |
| `agenda_appointment_types` | `AppointmentType` | sí | sí | Catálogo por clínica, no global |
| `agenda_blocks` | `AgendaBlock` | sí | sí | Bloqueos/reuniones de la clínica |
| `agenda_appointments` | `Appointment` | sí | sí | El dato clínico-operativo central |
| `agenda_item_notes` | `AgendaItemNote` | sí | sí | Hilo interno del equipo |
| `agenda_appointment_reminders` | `AppointmentReminder` | sí | sí | Contiene PII del paciente en `message_preview` (`models.py:732-742`) |

#### 3.1.1 `TenantAgendaConfig` → `agenda_tenant_config` (`models.py:46`)

Un registro por clínica. Nace solo: `agenda_config_get` hace `get_or_create` con `all_objects`
(`selectors.py:254-265`), por eso **`GET /agenda/config/` nunca puede dar 404**.

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `record_number_format` | `CharField(50)` | no | `"EXP-{year}-{seq:05d}"` | **Se almacena y nadie lo lee**: la generación real vive en pacientes (`models.py:54-57`, TODO declarado) |
| `record_number_reset_yearly` | `BooleanField` | no | `False` | Ídem |
| `default_appointment_duration` | `PositiveSmallIntegerField` | no | `30` | Minutos. `Doctor.default_appointment_duration` tiene precedencia (`services.py:159-164`) |
| `reminder_offsets_minutes` | `JSONField` | no | `[1440]` | Lista de minutos antes de la cita (`models.py:36-38`) |
| `reminders_enabled` | `BooleanField` | no | `True` | Interruptor global; si es `False`, `schedule_reminders_for_appointment` devuelve `[]` (`reminders.py:47-48`) |
| `agenda_start_hour` | `PositiveSmallIntegerField` | no | `9` | Hora de apertura de la rejilla |
| `agenda_end_hour` | `PositiveSmallIntegerField` | no | `18` | Cierre, **exclusivo** |
| `slot_interval_minutes` | `PositiveSmallIntegerField` choices | no | `30` | 5/10/15/20/30/60 (`models.py:76-83`) |

**Constraints** (`models.py:136-160`, migración `0016_agenda_config_grid.py:48-75`):
`agenda_config_tenant_uniq` (unique en `tenant`) · `agenda_config_start_hour_range` (0–23) ·
`agenda_config_end_hour_range` (1–24) · `agenda_config_end_after_start` (`end > start`) ·
`agenda_config_slot_interval_choices`. Las cuatro `CheckConstraint` son **defensa en profundidad**
declarada: la validación de negocio vive en `agenda_config_update` (`models.py:141-143`,
`services.py:1282-1294`).

Índices: solo los de `BaseModel` (`created_at`, `deleted_at`) más el unique de `tenant`. Con una
fila por clínica no se propone ninguno más.

#### 3.1.2 `AppointmentType` → `agenda_appointment_types` (`models.py:173`)

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `name` | `CharField(80)` | no | — | |
| `color_hex` | `CharField(7)` | no (`blank`) | `""` | Formato `#RRGGBB` validado **solo en el serializer de la vista** (`views.py:793-800`), no en el modelo |
| `is_active` | `BooleanField` | no | `True` | `db_index=True` (`models.py:190-194`). `False` = no aparece al agendar |

`ordering = ["name"]`. **Constraint:** `appointment_type_name_uniq` = unique `(tenant, name)`
**condicionado a `deleted_at IS NULL`** (`models.py:201-205`) — un tipo borrado libera su nombre.
Ojo: la baja de la API es `is_active=False`, **no** `deleted_at` (`appointment_types.py:79-80`), así
que un tipo desactivado **sigue ocupando el nombre**.

Índices: PK, `is_active`, unique parcial, `created_at`, `deleted_at`. Consulta que los justifica:
`appointment_type_list(only_active=True)` → `WHERE is_active = true ORDER BY name`
(`selectors.py:113-118`). No se propone ninguno más: son decenas de filas por clínica.

#### 3.1.3 `AgendaBlock` → `agenda_blocks` (`models.py:212`)

Evento sin paciente: reunión (`meeting`) o bloqueo (`block`).

| Campo | Tipo | `on_delete` | Null | Default | Consecuencia real |
|---|---|---|---|---|---|
| `kind` | `CharField(10)` choices | — | no | `block` | `db_index=True` |
| `title` | `CharField(120)` | — | no (`blank`) | `""` | |
| `doctor` | FK `personal.Doctor` | **CASCADE** | sí | `NULL` | Borrar en duro un médico **borra sus bloqueos**. Incoherente con `Appointment.doctor` que es `PROTECT` → B-AGE-11 |
| `consultorio` | FK `personal.Consultorio` | **CASCADE** | sí | `NULL` | Ídem |
| `sucursal` | FK `clinica.Sucursal` | **SET_NULL** | sí | `NULL` | Borrar una sede deja el bloqueo "sin sede", y un bloqueo con `sucursal=NULL` solo aplica a citas con `sucursal=NULL` (`services.py:282-284`): en la práctica **deja de bloquear** |
| `starts_at` | `DateTimeField` | — | no | — | `db_index=True`, UTC |
| `ends_at` | `DateTimeField` | — | no | — | UTC |
| `all_day` | `BooleanField` | — | no | `False` | Es una **bandera de presentación**: no altera `starts_at`/`ends_at` ni el cálculo de empalmes |
| `notes` | `TextField` | — | no (`blank`) | `""` | |

`ordering = ["starts_at"]`. **Sin constraints propias y sin exclusion constraint**: dos bloqueos
pueden solaparse, y un bloqueo puede crearse encima de citas ya agendadas (`blocks.py:99-111`, no
hay verificación) → B-AGE-06.

Índices: PK, `kind`, `starts_at`, `tenant` (FK), `created_at`, `deleted_at`. La consulta del listado
es `starts_at < date_to AND ends_at > date_from` acotada por tenant (`selectors.py:75-88`); el índice
de `starts_at` la cubre. **No se propone índice compuesto `(tenant, starts_at)`**: con 1–3 usuarios
concurrentes y del orden de cientos de eventos por clínica al año, sería peso muerto en cada
escritura sin una consulta que lo exija.

#### 3.1.4 `Appointment` → `agenda_appointments` (`models.py:286`)

| Campo | Tipo | `on_delete` | Null | Default | Consecuencia real |
|---|---|---|---|---|---|
| `patient` | FK `pacientes.Patient` | **PROTECT** | no | — | No se puede borrar en duro un paciente con historial de citas. La baja real es lógica |
| `doctor` | FK `personal.Doctor` | **PROTECT** | no | — | Ídem: el médico que ya atendió no desaparece del historial |
| `consultorio` | FK `personal.Consultorio` | **PROTECT** | sí | `NULL` | `NULL` = telemedicina o domicilio; por eso el constraint de consultorio lleva `consultorio_id IS NOT NULL` |
| `sucursal` | FK `clinica.Sucursal` | **SET_NULL** | sí | `NULL` | `db_index=True`. Borrar la sede **no** borra la cita: queda sin sede y, para el alcance por sede, deja de ser visible para roles acotados (`selectors.py:234-235`, `sucursal_id__in`) |
| `modality` | `CharField(12)` choices | — | no | `office` | `db_index`. `office`/`phone`/`video`/`offsite` |
| `starts_at` | `DateTimeField` | — | no | — | `db_index`, UTC |
| `ends_at` | `DateTimeField` | — | no | — | UTC. Se calcula si no viene (`services.py:154-165`) |
| `status` | `CharField(20)` choices | — | no | `scheduled` | `db_index`. Solo lo mueve `appointment_change_status` |
| `reason` | `CharField(255)` | — | no (`blank`) | `""` | **Se considera dato clínico**: por eso `finance` está fuera de todo GET de agenda (`MailySoft/backend/apps/core/permissions.py:70-78`) |
| `appointment_type` | FK `agenda.AppointmentType` | **SET_NULL** | sí | `NULL` | Borrar el tipo deja la cita sin categoría, no la destruye |
| `specialty` | `CharField(100)` | — | no (`blank`) | `""` | Texto libre |
| `notes` | `TextField` | — | no (`blank`) | `""` | Notas internas |
| `cancelled_by` | FK `User` | **SET_NULL** | sí | `NULL` | Borrar al usuario no borra la cita cancelada; se pierde quién canceló |
| `cancellation_reason` | `TextField` | — | no (`blank`) | `""` | Se llena al cancelar; **no es obligatorio** → B-AGE-15 |
| `no_show_registered_by` | FK `User` | **SET_NULL** | sí | `NULL` | Ídem |
| `reschedule_count` | `PositiveSmallIntegerField` | — | no | `0` | Se incrementa en cada reagendamiento (`services.py:1028`) |
| `quote` | FK `finanzas.Quote` | **SET_NULL** | sí | `NULL` | Borrar la cotización no borra la cita |
| `series_id` | `UUIDField` | — | sí | `None` | `db_index`. Documentado como "gancho v2, siempre None en v1" (`models.py:475-485`) pero **el endpoint de serie ya lo puebla** (`services.py:726`) → B-AGE-12 |

`ordering = ["-starts_at"]` (`models.py:489`). `clean()` valida `ends_at > starts_at`
(`models.py:521-525`), pero **`clean()` no se invoca en ninguna ruta de la API**: quien valida es el
service (`services.py:519-520`).

**Índices declarados** (`models.py:490-516`), con la consulta que justifica cada uno:

| Índice | Campos | Consulta que lo justifica |
|---|---|---|
| `appt_doctor_range_idx` | `tenant, doctor, starts_at, ends_at` | Anti-empalme por médico (`services.py:190-198`) y agenda por médico (`selectors.py:216-217`) |
| `appt_consultorio_range_idx` | `tenant, consultorio, starts_at, ends_at` | Anti-empalme por consultorio (`services.py:230-236`) |
| `appt_patient_hist_idx` | `tenant, patient, -starts_at` | Historial del paciente (`selectors.py:219-220` + `ordering` DESC) |
| `appt_status_idx` | `tenant, status, starts_at` | Sala de espera / filtro por estado (`selectors.py:225-226`) |
| `appt_sucursal_range_idx` | `tenant, sucursal, starts_at` | Tablero por sede (`selectors.py:234-237`, migración `0014:45-50`) |

**Exclusion constraints anti-empalme (capa 2, PostgreSQL).** No se modelan en `Meta` porque el ORM
no soporta `EXCLUDE USING GIST` (`models.py:517-519`); viven en SQL crudo. Requieren
`CREATE EXTENSION btree_gist` (`migrations/0002:68`). Versión vigente en
`migrations/0003_fix_overlap_constraints.py:49-76`:

```sql
-- appointment_no_overlap_doctor
EXCLUDE USING gist (tenant_id WITH =, doctor_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
WHERE (deleted_at IS NULL AND status NOT IN ('cancelled','no_show','attended'));

-- appointment_no_overlap_consultorio  (idéntico + AND consultorio_id IS NOT NULL)
```

Dos consecuencias que hay que tener presentes: (1) el rango es `[)`, así que 10:00–11:00 y
11:00–12:00 **no** chocan; (2) el constraint del médico lleva `tenant_id` pero **no** `sucursal_id`:
un médico no puede tener dos citas solapadas ni aunque sean en sedes distintas — es deliberado
(`models.py:356-363`). Un médico que trabaja en **dos clínicas** sí puede: `tenant_id WITH =` lo
permite (`migrations/0002:78`).

#### 3.1.5 `AgendaItemNote` → `agenda_item_notes` (`models.py:574`)

| Campo | Tipo | `on_delete` | Null | Consecuencia real |
|---|---|---|---|---|
| `author` | FK `User`, `related_name="agenda_item_notes"` | **CASCADE** | no | Borrar en duro un usuario **borra todas sus notas del hilo**, contra la convención de borrado lógico de §1.8.1 y contra el `SET_NULL` de `created_by` → B-AGE-10 |
| `appointment` | FK `Appointment` | **CASCADE** | sí | Borrar en duro la cita borra su hilo |
| `agenda_block` | FK `AgendaBlock` | **CASCADE** | sí | Ídem para eventos |
| `body` | `TextField` | — | no | Requerido; la vista lo topa a 2 000 caracteres (`views.py:1035`) |

`ordering = ["created_at"]`. **Constraint** `agenda_item_note_exactly_one_target` (`models.py:624-630`):
XOR real entre `appointment` y `agenda_block` a nivel BD; el service repite la validación
(`notes.py:69-72`).

**Append-only por diseño**: no existe endpoint de edición (`models.py:584-585`); la corrección es
agregar otra nota. El borrado sí existe y es lógico (`notes.py:225-226`).

Índices: PK, los dos FK, `created_at`, `deleted_at`. La consulta del hilo es
`WHERE appointment_id = ? ORDER BY created_at` (`selectors.py:286-290`), cubierta por el índice de
la FK. No se propone ninguno más.

#### 3.1.6 `AppointmentReminder` → `agenda_appointment_reminders` (`models.py:660`)

| Campo | Tipo | `on_delete` | Null | Default | Notas |
|---|---|---|---|---|---|
| `appointment` | FK `Appointment`, `related_name="reminders"` | **CASCADE** | no | — | El recordatorio no sobrevive a su cita |
| `channel` | `CharField(20)` choices | — | no | `whatsapp` | `whatsapp`/`sms`/`email`. **Solo se crea `whatsapp`** (`reminders.py:77`) |
| `scheduled_at` | `DateTimeField` | — | no | — | `db_index`, UTC |
| `sent_at` | `DateTimeField` | — | sí | `NULL` | |
| `status` | `CharField(20)` choices | — | no | `pending` | `db_index`. `pending`/`sent`/`failed`/`skipped`/`cancelled` |
| `message_preview` | `TextField` | — | no (`blank`) | `""` | **Contiene PII del paciente** (nombre + fecha). Declarado LFPDPPP en el propio modelo (`models.py:736-741`). **No se expone en la API**: el serializer no lo incluye (`serializers.py:130-139`) |
| `error_detail` | `TextField` | — | no (`blank`) | `""` | Tampoco se expone |
| `external_message_id` | `CharField(200)` | — | no (`blank`) | `""` | Id del proveedor; hoy `sim-xxxxxxxxxxxx` |

`ordering = ["scheduled_at"]`. **Índices** (`models.py:761-772`):

| Índice | Campos | Consulta que lo justifica |
|---|---|---|
| `reminder_scheduled_status_idx` | `scheduled_at, status` | **Ninguna hoy.** El comentario dice "buscar los PENDING próximos a enviarse" (`models.py:762`), pero **no existe ninguna tarea que barra por `scheduled_at`**: el disparo es por `eta` de Celery (`reminders.py:82-85`) y `CELERY_BEAT_SCHEDULE` no tiene tarea de agenda (`MailySoft/backend/config/settings/base.py:303-310`). Es peso muerto en cada escritura hasta que exista la barredora → B-AGE-13 |
| `reminder_tenant_appt_idx` | `tenant, appointment` | `reminder_list_for_appointment` (`selectors.py:314`) y el `prefetch_related("reminders")` del listado (`selectors.py:214`) |

**Inmutabilidad declarada** (`models.py:682-686`): `scheduled_at`, `channel` y `appointment` no
cambian tras la creación; solo mutan `status`, `sent_at`, `error_detail` y `external_message_id`, y
solo desde la tarea Celery o desde `cancel_reminders_for_appointment`. **No hay endpoint de creación
manual** y el modelo prohíbe crearlo (`models.py:680`).

---

### 3.2 Endpoints

Prefijo `/api/v1/` (§1.7). Rutas en `apps/agenda/urls.py:37-123`. **Las 15 vistas heredan de
`TenantAPIView`** y **todas llevan el guard de módulo `RequiresAgenda`** (§1.4.2): si la clínica no
compró `agenda`, cualquiera de estos endpoints responde **404**, no 403.

Errores transversales que aplican a todos y no se repiten endpoint por endpoint (§1.7.2):
**401** sin token · **403** rol insuficiente / sin membresía / contraseña temporal pendiente ·
**404** módulo no contratado, otro tenant, o fuera del alcance de sede · **405** método no ruteado ·
**429** throttle `user` 300/min.

Dos formas de cuerpo de error conviven aquí:
`{"detail": ["<msg>", ...]}` — **lista** — cuando la vista traduce un `ValidationError` de service
(p. ej. `views.py:292-296`), y `{"<campo>": ["<msg>"]}` cuando falla el serializer.

| # | Método | Ruta | Vista:línea | Permiso de rol (§1.3) | Éxito |
|---|---|---|---|---|---|
| 1 | GET | `/api/v1/agenda/citas/` | `views.py:209` | `AppointmentPermission` | 200 paginado |
| 2 | POST | `/api/v1/agenda/citas/` | `views.py:255` | `AppointmentPermission` | 201 |
| 3 | POST | `/api/v1/agenda/citas/serie/` | `views.py:379` | `AppointmentPermission` | 201 |
| 4 | GET | `/api/v1/agenda/disponibilidad/` | `views.py:449` | `AppointmentPermission` | 200 |
| 5 | GET | `/api/v1/agenda/citas/<uuid>/` | `views.py:507` | `AppointmentPermission` | 200 |
| 6 | PATCH | `/api/v1/agenda/citas/<uuid>/` | `views.py:515` | `AppointmentPermission` | 200 |
| 7 | DELETE | `/api/v1/agenda/citas/<uuid>/` | `views.py:547` | `AppointmentPermission` | **204 sin cuerpo** |
| 8 | POST | `/api/v1/agenda/citas/<uuid>/estado/` | `views.py:589` | `AppointmentStatusPermission` | 200 |
| 9 | POST | `/api/v1/agenda/citas/<uuid>/reagendar/` | `views.py:644` | `AppointmentPermission` | 200 |
| 10 | POST | `/api/v1/agenda/citas/<uuid>/reactivar/` | `views.py:682` | `AppointmentPermission` | 200 |
| 11 | GET | `/api/v1/agenda/config/` | `views.py:734` | `AgendaConfigPermission` | 200 |
| 12 | PATCH | `/api/v1/agenda/config/` | `views.py:746` | `AgendaConfigPermission` | 200 |
| 13 | GET | `/api/v1/agenda/tipos-cita/` | `views.py:802` | `AppointmentTypePermission` | 200 **array plano** |
| 14 | POST | `/api/v1/agenda/tipos-cita/` | `views.py:808` | `AppointmentTypePermission` | 201 |
| 15 | PATCH | `/api/v1/agenda/tipos-cita/<uuid>/` | `views.py:861` | `AppointmentTypePermission` | 200 |
| 16 | DELETE | `/api/v1/agenda/tipos-cita/<uuid>/` | `views.py:881` | `AppointmentTypePermission` | 204 |
| 17 | GET | `/api/v1/agenda/eventos/` | `views.py:915` | `AppointmentPermission` | 200 **array plano** |
| 18 | POST | `/api/v1/agenda/eventos/` | `views.py:935` | `AppointmentPermission` | 201 |
| 19 | PATCH | `/api/v1/agenda/eventos/<uuid>/` | `views.py:986` | `AppointmentPermission` | 200 |
| 20 | DELETE | `/api/v1/agenda/eventos/<uuid>/` | `views.py:1010` | `AppointmentPermission` | 204 |
| 21 | GET | `/api/v1/agenda/citas/<uuid>/notas/` | `views.py:1043` | `AgendaItemNotePermission` | 200 **array plano** |
| 22 | POST | `/api/v1/agenda/citas/<uuid>/notas/` | `views.py:1052` | `AgendaItemNotePermission` | 201 |
| 23 | GET | `/api/v1/agenda/eventos/<uuid>/notas/` | `views.py:1103` | `AgendaItemNotePermission` | 200 **array plano** |
| 24 | POST | `/api/v1/agenda/eventos/<uuid>/notas/` | `views.py:1112` | `AgendaItemNotePermission` | 201 |
| 25 | DELETE | `/api/v1/agenda/notas/<uuid>/` | `views.py:1153` | `AgendaItemNotePermission` | 204 |

**Métodos que devuelven 405 por no estar ruteados** (así se sostiene la inmutabilidad, §1.7.2):
`POST`/`PUT` sobre `/agenda/citas/<id>/` · `GET` sobre `/agenda/tipos-cita/<id>/` · `GET` sobre
`/agenda/eventos/<id>/` · **`GET` sobre `/agenda/notas/<id>/`** (solo existe `delete`,
`views.py:1153`) · `PUT` sobre `/agenda/config/` · `DELETE` sobre `/agenda/citas/<id>/notas/`.

#### 3.2.1 `GET /api/v1/agenda/citas/`

- **Filtros** (`_FilterSerializer`, `views.py:228-234`), todos opcionales: `doctor_id` (UUID),
  `patient_id` (UUID), `consultorio_id` (UUID), `status` (uno de los 7 `Status.choices`),
  `date_from` (ISO datetime), `date_to` (ISO datetime). Un valor mal formado → **400** con forma de
  serializer. **No hay filtro por `sucursal_id` en query**: la sede se pasa por header
  `X-Sucursal-Id` (§1.5).
- **Semántica del rango:** `date_from` compara contra `starts_at >=` y `date_to` contra
  `starts_at <` (`selectors.py:228-232`). Es decir, **una cita que empezó antes de `date_from` y
  sigue corriendo NO aparece**. El listado de eventos usa el criterio contrario (solapamiento).
- **Alcance por sede:** siempre `sucursal_scope_ids(request)` (`views.py:239-241`). Ver §3.4.
- **Orden:** `starts_at` ASC (`selectors.py:239`), **no** el `-starts_at` del `Meta.ordering`.
- **Paginación:** `PageNumberPagination` estándar, `PAGE_SIZE=25`, **sin `page_size` en query**
  (§1.7.1). Query param `page`. Respuesta `{count, next, previous, results}`. El tablero del día no
  puede pedir más de 25 por página bajo ninguna combinación de parámetros → B-AGE-22.
- **500 posible por diseño:** si `PAGE_SIZE` fuera `None`, la vista devuelve
  `{"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."}` con **500**
  (`views.py:250-253`).
- **Elemento de `results`** (`AppointmentOutputSerializer`, `serializers.py:169`):

```json
{
  "id": "uuid",
  "patient": {"id": "uuid", "full_name": "Ana Pérez López"},
  "doctor":  {"id": "uuid", "full_name": "Dr. Juan Ruiz"},
  "consultorio": {"id": "uuid", "name": "Consultorio 1"},
  "sucursal":    {"id": "uuid", "name": "Centro"},
  "appointment_type": {"id": "uuid", "name": "Primera vez", "color_hex": "#3B82F6"},
  "modality": "office", "modality_display": "Consultorio u Oficina",
  "starts_at": "2026-08-13T10:00:00-06:00",
  "ends_at":   "2026-08-13T10:30:00-06:00",
  "status": "scheduled", "status_display": "Agendada",
  "reason": "Dolor lumbar", "specialty": "", "notes": "",
  "quote": {"id": "uuid", "total": "1500.00", "status": "accepted", "status_display": "Aceptada"},
  "reminders": [
    {"id": "uuid", "channel": "whatsapp", "channel_display": "WhatsApp",
     "scheduled_at": "2026-08-12T10:00:00-06:00", "sent_at": null,
     "status": "pending", "status_display": "Pendiente"}
  ],
  "created_at": "2026-08-01T09:12:33-06:00"
}
```

  `consultorio`, `sucursal`, `appointment_type` y `quote` pueden ser `null`. Fechas con
  desplazamiento de Ciudad de México, no UTC (§1.7). **No se exponen** `cancellation_reason`,
  `cancelled_by`, `no_show_registered_by`, `reschedule_count` ni `series_id`
  (`serializers.py:193-212`) — si el front necesita mostrar "reagendada 3 veces" o el motivo de
  cancelación, hoy **no lo tiene** → B-AGE-17.

#### 3.2.2 `POST /api/v1/agenda/citas/`

- **Entrada** (`InputSerializer`, `views.py:161-207`):

| Campo | Tipo | Req. | Default |
|---|---|---|---|
| `patient_id` | UUID | XOR con `new_patient` | `null` |
| `new_patient` | objeto `{first_name, paternal_surname, maternal_surname?, phone?}` (`views.py:143-151`) | XOR con `patient_id` | — |
| `doctor_id` | UUID | **sí** | — |
| `consultorio_id` | UUID | no | `null` |
| `appointment_type_id` | UUID | no | `null` |
| `modality` | choice | no | `office` |
| `starts_at` | datetime ISO | **sí** | — |
| `ends_at` | datetime ISO | no | `null` → se calcula |
| `reason` | string ≤255 | no | `""` |
| `specialty` | string ≤100 | no | `""` |
| `notes` | string | no | `""` |
| `quote_id` | UUID | no | `null` |
| `sucursal_id` | UUID | no | `null` → se resuelve |

- **`status` no se acepta**: el estado inicial es siempre `SCHEDULED` (`views.py:168-169`,
  `services.py:561`).
- **XOR paciente:** ninguno de los dos → 400 `"Indica un paciente existente (patient_id) o los datos
  de uno nuevo (new_patient)."`; ambos → 400 `"Elige un paciente existente O uno nuevo, no ambos."`
  (`views.py:196-207`). Forma: `{"non_field_errors": ["..."]}`.
- **Éxito:** **201** con `AppointmentOutputSerializer`.
- **403** `{"detail": "No se encontró un tenant activo para este request."}` si no hay tenant
  (`views.py:260-265`) — caso defensivo: `TenantAPIView` ya lo habría cortado antes.
- **400** `{"detail": ["<msg>"]}` con el catálogo completo de mensajes del service
  (`services.py:366-520`), en este orden de evaluación:

| Mensaje | Línea |
|---|---|
| `Paciente no encontrado en esta clínica.` | `services.py:369` |
| `Médico no encontrado en esta clínica.` | `:374` |
| `Consultorio no encontrado en esta clínica.` | `:381` |
| `El paciente / El médico / El consultorio no pertenece a esta clínica.` | `:385`, `:388`, `:391` |
| `El médico no está activo en esta clínica.` | `:395` |
| `El consultorio no está activo.` | `:397` |
| `No se encontró un perfil de médico activo para tu usuario en esta clínica.` | `:422` |
| `Como médico, solo puedes agendar citas para ti.` | `:425` |
| `Ese consultorio no está asignado al médico.` | `:437` |
| `El consultorio pertenece a otra sucursal distinta de la indicada.` | `:461` |
| `El médico no atiende en esa sucursal.` | `:471` |
| `Tipo de cita no encontrado en esta clínica.` / `no pertenece a esta clínica` | `:479`, `:481` |
| `Cotización no encontrada…` / `no pertenece…` / `no corresponde al paciente…` / `Solo se puede vincular una cotización aceptada…` | `:492`, `:496`, `:500`, `:504-507` |
| `La hora de fin debe ser posterior a la hora de inicio.` | `:520` |
| `El médico ya tiene una cita en ese horario. Por favor elija otro horario o médico.` | `:203-205` |
| `El consultorio ya está ocupado en ese horario…` | `:241-244` |
| `Ese horario está bloqueado por un evento de agenda. Elige otro horario.` | `:295-297` |
| `…(constraint BD)` — variantes cuando gana la capa 2 | `:573-582` |
| `Error de integridad al crear la cita. Por favor intente de nuevo.` | `:584-586` |
| Sede fuera de `allowed_sucursales` (mensaje de `resolve_write_sucursal`, §1.5.3) | `MailySoft/backend/apps/clinica/sucursal_scope.py:421-424` |

- **No se valida que la cita sea futura.** Se puede agendar en el pasado; el único efecto es que los
  recordatorios cuyo `scheduled_at` ya pasó no se crean (`reminders.py:60-62`).

#### 3.2.3 `POST /api/v1/agenda/citas/serie/`

- **Entrada** (`views.py:318-377`): todo lo de la cita base (**aquí `ends_at` es obligatorio**,
  `views.py:334`) más la recurrencia, en **dos modos excluyentes**:
  - **Modo regla:** `frequency` ∈ `weekly|biweekly|monthly` + **exactamente uno** de
    `count` (2–52) o `until` (fecha).
  - **Modo lista:** `explicit_starts` = lista de datetimes, no vacía, **máx. 52**.
- Validaciones del serializer: XOR de paciente obligatorio (`views.py:361-364`); sin
  `explicit_starts` y sin `frequency` → 400; `count` y `until` ambos o ninguno → 400
  (`views.py:366-376`).
- **`custom` no es alcanzable desde la API**: el service lo soporta con `interval_days`
  (`series.py:20`, `services.py:655`) pero el `ChoiceField` de la vista solo admite tres frecuencias
  (`views.py:342-344`) y `interval_days` no está en el serializer.
- **Éxito 201, best-effort** (`views.py:410-422`):

```json
{
  "series_id": "uuid",
  "created_count": 8,
  "created": [ /* AppointmentOutput[] */ ],
  "skipped_count": 2,
  "skipped": [{"starts_at": "2026-09-15T10:00:00+00:00", "error": "El médico ya tiene una cita en ese horario. …"}]
}
```

  Nótese que `skipped[].starts_at` sale de `datetime.isoformat()` crudo (`views.py:417`), es decir
  **en UTC**, mientras que las fechas de `created[]` salen del renderer de DRF en hora de Ciudad de
  México. Dos husos en la misma respuesta → B-AGE-18.
- **400** si: `"Indica un paciente existente o uno nuevo, no ambos ni ninguno."` (`services.py:699`);
  `"La hora de fin debe ser posterior a la de inicio."` (`:703`); `"Una serie debe tener al menos 2
  citas."` (`:710`, `series.py:76`); `"Una serie no puede tener más de 52 citas."` (`:712-714`);
  `"Frecuencia de repetición inválida: '<x>'."` (`series.py:66`); y — solo con paciente nuevo —
  `"Ninguna de las citas pudo agendarse (los horarios elegidos están ocupados)."` (`:763-765`), que
  **revierte también el expediente provisional**.

#### 3.2.4 `GET /api/v1/agenda/disponibilidad/`

- **Query params** (`views.py:452-456`): `doctor_id` **requerido**, `date_from` **requerido**,
  `date_to` **requerido**, `consultorio_id` opcional. Faltar cualquiera → 400 de serializer.
- **Respuesta 200:** `{"busy": [{"start": "…iso…", "end": "…iso…"}, …]}` — **sin ordenar** y con
  intervalos que se pueden solapar entre sí (`selectors.py:357`, `views.py:464-471`). Los ISO salen
  en UTC (`isoformat()` del datetime almacenado).
- **Qué cuenta como ocupado** (`selectors.py:359-386`): citas activas del médico **en todas las
  sedes** (nunca se filtran por sucursal, `selectors.py:361-368`) + eventos aplicables (del médico,
  del consultorio si se indicó, y bloqueos sin médico ni consultorio de las sedes del alcance).

#### 3.2.5 `GET|PATCH|DELETE /api/v1/agenda/citas/<uuid>/`

- Los tres resuelven la cita con `_appointment_get_or_404` (`views.py:97-118`) → **404**
  `{"detail": "Cita no encontrada."}` si no existe, es de otro tenant, o cae fuera del alcance de
  sede del actor.
- **PATCH** acepta **solo** `reason` (≤255), `specialty` (≤100, `allow_blank`) y `notes`
  (`allow_blank`) (`views.py:497-499`). Cuerpo vacío o sin campos conocidos → **400**
  `{"detail": "No se proporcionaron campos para actualizar."}` (`views.py:527-531`).
  **`reason` no lleva `allow_blank=True`**: mandar `"reason": ""` da 400 de serializer y no hay forma
  de vaciar el motivo → B-AGE-20.
  El service repite la lista negra por si se llama fuera de la vista
  (`_APPOINTMENT_IMMUTABLE_FIELDS`, `services.py:92-120`) y responde
  `"No se pueden modificar los campos: <a, b>."` (`services.py:1214-1216`).
- **DELETE = cancelar, no borrar** (`views.py:547-568`). Llama
  `appointment_change_status(new_status=CANCELLED)`. El motivo se lee de
  **`request.data.get("reason","")`, es decir del cuerpo de un DELETE** (`views.py:553`), y es
  opcional → B-AGE-15. Éxito **204 sin cuerpo**; 400 con la lista de mensajes si la transición no es
  válida (p. ej. cancelar una cita ya `attended`).

#### 3.2.6 `POST /api/v1/agenda/citas/<uuid>/estado/`

- **Entrada:** `{"status": "<uno de los 7>", "reason": "<opcional>"}` (`views.py:585-587`).
- **Regla propia de la vista, no del permiso:** enfermería no puede cancelar → **403**
  `{"detail": "Enfermería no puede cancelar citas."}` (`views.py:596-603`). Se evalúa **antes** de
  buscar la cita, así que un `nurse` que pida cancelar una cita inexistente recibe 403, no 404.
- **200** con la cita actualizada; **400** `{"detail": ["No se puede pasar de 'X' a 'Y'. Transición
  no permitida."]}` (`services.py:818-823`); **404** si la cita cae fuera de su alcance.

#### 3.2.7 `POST /api/v1/agenda/citas/<uuid>/reagendar/`

- **Entrada:** `starts_at` (requerido), `ends_at` (opcional → se recalcula), `consultorio_id`
  (opcional → conserva el actual) (`views.py:639-642`).
- **200** con la cita; **400** con: `"No se puede reagendar una cita en estado '<X>'."`
  (`services.py:914-916`), `"No tienes acceso a la sucursal actual de esta cita."` (`:933`),
  `"Consultorio no encontrado en esta clínica."` (`:941`), `"El consultorio no pertenece a esta
  clínica."` (`:944`), `"El médico no atiende en esa sucursal."` (`:979`), los tres mensajes de
  empalme, y los de constraint de BD (`:1046-1058`).
- **Efecto lateral no obvio:** reagendar una cita **CANCELADA la reactiva** (vuelve a `SCHEDULED`,
  limpia `cancelled_by` y `cancellation_reason`, `services.py:1038-1042`).

#### 3.2.8 `POST /api/v1/agenda/citas/<uuid>/reactivar/`

- **Sin cuerpo.** **200** con la cita en `SCHEDULED`.
- **400** si: no está cancelada (`"Solo se puede reactivar una cita cancelada. La cita está en estado
  '<X>'."`, `services.py:1112-1115`), el médico ya no atiende en esa sede (`:1122`), o el hueco se
  ocupó mientras estuvo cancelada (mensajes de empalme).

#### 3.2.9 `GET|PATCH /api/v1/agenda/config/`

- **GET:** 200 con `TenantAgendaConfigOutputSerializer` (`serializers.py:255-273`):
  `{id, record_number_format, record_number_reset_yearly, default_appointment_duration,
  reminder_offsets_minutes, reminders_enabled, agenda_start_hour, agenda_end_hour,
  slot_interval_minutes, created_at, updated_at}`. **Nunca 404** (get_or_create).
- **PATCH parcial** (`views.py:717-732`): `default_appointment_duration` 1–480;
  `reminder_offsets_minutes` lista de enteros ≥1, **puede ir vacía** (apaga los recordatorios sin
  tocar el interruptor); `agenda_start_hour` 0–23; `agenda_end_hour` 1–24; `slot_interval_minutes`
  choice.
- Cuerpo vacío → 400 `{"detail": "No se proporcionaron campos para actualizar."}` (`views.py:758-762`).
- **400** `{"detail": ["La hora de cierre debe ser posterior a la de apertura."]}` — se valida contra
  el **estado final combinado**, no solo contra lo enviado (`services.py:1292-1294`).
- **No hay tope al número de offsets ni a su valor**: `[1440, 1439, 1438, …]` crearía un recordatorio
  y una tarea Celery por cada uno en cada cita → B-AGE-19.

#### 3.2.10 Tipos de cita

- **GET `/agenda/tipos-cita/`** — query param `only_active` (default `"true"`; cualquier valor
  distinto de `"false"` cuenta como `true`, `views.py:804`). **Array plano sin paginar.** Elemento:
  `{id, name, color_hex, is_active, created_at}` (`serializers.py:76-82`).
- **POST** — `{name: ≤80 requerido, color_hex: "#RRGGBB" opcional}`. Color inválido → 400
  `{"color_hex": ["El color debe tener formato #RRGGBB (ej: #3B82F6)."]}` (`views.py:793-800`).
  201 con el objeto. **No se valida nombre duplicado en el service**: lo atrapa el constraint
  `appointment_type_name_uniq` como `IntegrityError` **no capturado** → 500 → B-AGE-21.
- **PATCH `<id>/`** — `name` y/o `color_hex`. Cuerpo vacío → 400. **204** no aplica: devuelve 200.
- **DELETE `<id>/`** — desactivación lógica (`is_active=False`), **204**. Las citas que ya usaban ese
  tipo lo conservan.
- **404** `{"detail": "Tipo de cita no encontrado."}` si no existe en el tenant (`views.py:855-859`).
  **No se acota por sede** — correcto: el catálogo es de la clínica, no de la sede.

#### 3.2.11 Eventos de agenda (reuniones y bloqueos)

- **GET `/agenda/eventos/`** — query params `date_from` y `date_to`, **ambos opcionales**
  (`views.py:923-925`). Criterio: **solapamiento** con el rango (`starts_at < date_to AND
  ends_at > date_from`, `selectors.py:76-79`) — distinto del criterio del listado de citas.
  **Array plano sin paginar y sin rango obligatorio**: omitir ambos devuelve todos los eventos
  históricos del tenant → B-AGE-07. Elemento (`serializers.py:85-109`):
  `{id, kind, kind_display, title, doctor, consultorio, sucursal, starts_at, ends_at, all_day, notes,
  created_at}`.
- **POST `/agenda/eventos/`** — `kind` (requerido, `meeting|block`), `title` ≤120, `doctor_id`,
  `consultorio_id`, `starts_at` y `ends_at` (requeridos), `all_day`, `notes`, `sucursal_id`
  (`views.py:901-913`). 201. **400**: `"Tipo de evento inválido '<x>'."` (`blocks.py:69`),
  `"La hora de fin debe ser posterior a la hora de inicio."` (`:71`), `"Médico/Consultorio no
  encontrado en esta clínica."` (`:78`, `:87`), `"…no pertenece a esta clínica."` (`:80`, `:89`), y
  el error de sede de `resolve_write_sucursal`.
- **PATCH `<id>/`** — solo `title`, `starts_at`, `ends_at`, `all_day`, `notes`
  (`views.py:973-978`). **El alcance (`doctor`, `consultorio`, `sucursal`) no se edita nunca**
  (`blocks.py:184-197`): para cambiarlo hay que borrar y recrear.
- **DELETE `<id>/`** — borrado lógico, **204**, **sin confirmación ni motivo** (`blocks.py:165-181`).
- **404** `{"detail": "Evento no encontrado."}` acotado por sede (`views.py:121-135`).

#### 3.2.12 Notas del hilo de agenda

- **GET/POST `/agenda/citas/<id>/notas/` y `/agenda/eventos/<id>/notas/`** — primero resuelven el
  padre con el helper acotado por sede; si el padre no está en su alcance → **404** del padre
  (`views.py:1045`, `:1105`). **Array plano sin paginar**, orden `created_at` ASC — decisión escrita:
  "el hilo de una cita es corto" (`views.py:1029`).
- Elemento (`serializers.py:236-247`):
  `{id, author: {id, full_name, avatar}, body, created_at}`. `full_name` cae al email si está vacío
  (`serializers.py:228-229`).
- **POST** — `{"body": "<≤2000 chars>"}`. 201. **400**
  `{"detail": ["El contenido de la nota no puede estar vacío."]}` si es solo espacios
  (`notes.py:65-66`).
- **DELETE `/agenda/notas/<id>/`** — **204**. **404** `{"detail": "Nota no encontrada."}` solo si es
  de otro tenant. **400** `{"detail": ["No puedes eliminar esta nota."]}` si el actor no es el autor
  ni owner/admin (`notes.py:222-223`) — 400 y no 403, con la razón escrita en el docstring
  (`notes.py:190-194`). **Este endpoint no acota por sede** → B-AGE-01.

---

### 3.3 Reglas de negocio verificadas en código

#### 3.3.1 Anti-empalme: las dos capas

**Capa 1 — servicio**, tres verificaciones dentro de `transaction.atomic()` justo antes del INSERT
(`services.py:523-547`):

| Verificación | Función:línea | Criterio |
|---|---|---|
| Médico ocupado | `_check_doctor_overlap` `services.py:168`, query `:190-198` | `tenant` + `doctor_id` + `status IN ACTIVE_STATUSES` + `starts_at < nuevo_fin AND ends_at > nuevo_inicio`. **No filtra por sede**: un médico no está en dos lados a la vez |
| Consultorio ocupado | `_check_consultorio_overlap` `:208`, query `:230-236` | Igual, por `consultorio_id`. Solo corre si hay consultorio (`:531`) |
| Bloqueo/reunión encima | `_check_block_overlap` `:247`, filtro `:282-292` | Aplica el evento si: es del mismo médico, **o** es del mismo consultorio, **o** no tiene ni médico ni consultorio y su `sucursal_id` **coincide exactamente** con la de la cita |

`ACTIVE_STATUSES` = `{scheduled, confirmed, arrived, in_progress}` (`models.py:645-652`): una cita
`attended`, `cancelled` o `no_show` **libera el hueco**.

**Capa 2 — base de datos**: los dos exclusion constraints `btree_gist` de
`migrations/0003_fix_overlap_constraints.py:49-76` (SQL en §3.1.4). Se capturan como `IntegrityError`
y se traducen a `ValidationError` de dominio buscando el nombre del constraint en el texto de la
excepción (`services.py:569-586`, `:1046-1058`) — acoplamiento frágil a la cadena de error de
PostgreSQL, pero explícito.

**Las dos capas están alineadas**: el `WHERE` del constraint excluye exactamente los tres estados que
`ACTIVE_STATUSES` deja fuera. Esa alineación **es un fix**: la migración 0002 no excluía `attended` y
la BD rechazaba citas que el service aceptaba (`migrations/0003:4-11`).

**Lo que ninguna de las dos capas cubre:** los `AgendaBlock` no tienen constraint ni verificación
propia. Se puede crear un bloqueo encima de citas existentes, y dos bloqueos pueden solaparse
(`blocks.py:99-111`) → B-AGE-06.

#### 3.3.2 Máquina de estados

Mapa único en `models.py:542-567`; el único punto de escritura es `appointment_change_status`
(`services.py:781`), que valida contra ese mapa (`:816-823`).

| Desde | Hacia | ¿Se puede saltar? |
|---|---|---|
| `scheduled` Agendada | `confirmed`, **`arrived`**, `cancelled`, `no_show` | **Sí**: se permite Agendada → En sala sin confirmar (walk-in), decisión escrita en `models.py:545-546` |
| `confirmed` Confirmada | `arrived`, `cancelled`, `no_show` | — |
| `arrived` En sala | `in_progress`, `cancelled`, `no_show` | — |
| `in_progress` En consulta | **solo** `attended` | Desde En consulta ya **no** se puede cancelar ni marcar no-show |
| `attended` / `cancelled` / `no_show` | **ninguno** (`set()`) | Terminales |

- **No se puede retroceder nunca**: ningún destino apunta hacia atrás. Marcar `arrived` por error
  obliga a cancelar la cita y crear otra.
- **`cancelled` es terminal aquí**, pero hay **dos puertas laterales que sí la revierten**:
  `appointment_reactivate` (`services.py:1149`) y `appointment_reschedule` sobre una cita cancelada
  (`services.py:1038-1042`). Ambas escriben `status` directamente, sin pasar por
  `appointment_change_status` ni por `VALID_TRANSITIONS` — y por tanto **sin registrar
  `APPOINTMENT_STATUS` en la bitácora**; registran su propia acción (`REACTIVATE` / `RESCHEDULE`).
- El estado **nunca cambia solo**: no hay tarea Celery ni señal que lo mueva (verificado: `tasks.py`
  solo lee `appointment.status`, `tasks.py:115`).
- Efectos por destino: `cancelled` escribe `cancelled_by` + `cancellation_reason`
  (`services.py:829-832`); `no_show` escribe `no_show_registered_by` (`:834-836`); ambos cancelan los
  recordatorios pendientes (`:841-848`).

#### 3.3.3 Paciente provisional creado al vuelo

`appointment_create_with_new_patient` (`services.py:615-636`): un único `transaction.atomic()`
(`:628`) envuelve `patient_create_quick` (`MailySoft/backend/apps/pacientes/services.py`) y
`appointment_create`. **Confirmado: es una sola transacción** — si la cita falla por empalme, por
regla de médico o por sede, el expediente provisional **no queda**. Coincide con
`docs/01-analisis.md:106-108`.

Matiz que el análisis no dice: dentro de esa transacción externa, `appointment_create` abre su propio
`atomic()` (`:523`), que en Django es un **savepoint**; el `IntegrityError` del constraint se atrapa
después de que el savepoint hizo rollback (`:569`), así que la transacción externa sobrevive y el
mensaje que llega al usuario es de dominio, no un 500.

En la **serie** con paciente nuevo el criterio es distinto y también deliberado: se crea el paciente
una vez y se intenta cada fecha; solo si **ninguna** se pudo agendar se revierte todo
(`services.py:730-765`).

#### 3.3.4 Disponibilidad y reglas del médico

- `ends_at` se deriva por precedencia `ends_at explícito → doctor.default_appointment_duration →
  config.default_appointment_duration → 30` (`services.py:154-165`). El `is not None and > 0` evita
  que una duración `0` caiga al siguiente nivel por *falsy*.
- **Regla A — un `doctor` solo agenda para sí mismo** (`services.py:399-425`): se resuelve el rol
  buscando el `TenantMembership` activo del usuario en **ese** tenant, no del thread-local, para que
  funcione desde Celery/commands. Sin membresía se asume staff de plataforma y **la restricción se
  salta** (`:414-416`). **Solo existe en la creación**: reagendar, reactivar y cambiar estado no la
  revalidan → B-AGE-04.
- **Regla B — el consultorio debe estar asignado al médico** (`services.py:433-437`), y solo si el
  médico tiene consultorios asignados. Sin consultorio (telemedicina) la regla no aplica — es la
  resolución que `docs/01-analisis.md:127-128` da por buena.
- **Regla C — el médico debe atender en la sede resuelta** (`services.py:469-471`), mismo patrón:
  sin sedes asignadas, sin restricción. Se revalida al reagendar si la sede cambia (`:974-979`) y al
  reactivar (`:1117-1122`).

#### 3.3.5 Series

- Máximo **52** ocurrencias, tope duro en dos puntos (`series.py:26` y `views.py:350`).
- Generación pura, sin BD (`series.py:52-87`). `monthly` recorta el día al último válido del mes
  (31 ene → 28 feb, `series.py:29-35`).
- **Best-effort**: cada fecha que choca se salta y se reporta en `skipped` (`services.py:738-759`).
  Todas comparten `series_id` y **la misma duración** que la primera (`services.py:701`, `:746`).
- `series_id` **no se expone en ninguna respuesta de cita** (`serializers.py:193-212`): recibido el
  201 de la serie, el front no puede volver a agrupar esas citas por ningún endpoint → B-AGE-12.

#### 3.3.6 Bloqueos y reuniones

- El **alcance** se fija al crear y es inmutable (`blocks.py:184-197`):
  con médico → aplica en **todas** las sedes de ese médico; con consultorio → solo ese cuarto;
  sin ninguno → **solo la sede del evento** (`models.py:264-271`).
- Compatibilidad retro explícita: en una clínica sin ninguna `Sucursal`, tanto el bloqueo como la
  cita resuelven `sucursal_id = None`, y `sucursal_id=None` en el filtro de Django se traduce a
  `IS NULL`, con lo que el bloqueo sigue aplicando a toda la clínica (`services.py:268-272`).
- **Solo las reuniones notifican**; los bloqueos no (`blocks.py:124`).

---

### 3.4 Alcance por sucursal en este módulo

Mecánica y funciones en §1.5. Header `X-Sucursal-Id`. En agenda **se usa `sucursal_scope_ids` en
todos los listados** (la función que *siempre* acota, §1.5.4) y **el mismo criterio en los detalles
por id**, con la regla escrita en el propio archivo: "si no lo veo en el listado, no lo puedo tocar
por id" (`views.py:86-93`).

#### 3.4.1 Dónde SÍ se aplica

| Endpoint | Cómo | `archivo:línea` |
|---|---|---|
| `GET /agenda/citas/` | `sucursal_scope_ids` → `appointment_list(sucursal_ids=…)` | `views.py:239-241`, `selectors.py:234-235` |
| `GET|PATCH|DELETE /agenda/citas/<id>/` | `_appointment_get_or_404` | `views.py:97-118`, `:505` |
| `POST /agenda/citas/<id>/estado/` | ídem | `views.py:605` |
| `POST /agenda/citas/<id>/reagendar/` | ídem **+ validación de sede ORIGEN y DESTINO en el service** | `views.py:649`, `services.py:928-933`, `:961-967` |
| `POST /agenda/citas/<id>/reactivar/` | ídem | `views.py:683` |
| `GET /agenda/disponibilidad/` | `sucursal_scope_ids` → acota los bloqueos "de sede" | `views.py:461-463`, `selectors.py:374` |
| `GET /agenda/eventos/` | `sucursal_scope_ids` → `_agenda_block_scope_q` | `views.py:930-932`, `selectors.py:31-52` |
| `PATCH|DELETE /agenda/eventos/<id>/` | `_agenda_block_get_or_404` | `views.py:121-135`, `:984` |
| `GET|POST /agenda/citas/<id>/notas/` | hereda el 404 del padre acotado | `views.py:1041`, `:1045`, `:1054` |
| `GET|POST /agenda/eventos/<id>/notas/` | ídem | `views.py:1101`, `:1105`, `:1114` |
| `POST /agenda/citas/` y `POST /agenda/eventos/` (escritura) | `resolve_write_sucursal`, que valida la sede resuelta contra `allowed_sucursales` | `services.py:445-451`, `blocks.py:91-97` |

#### 3.4.2 Dónde NO se aplica

| Caso | `archivo:línea` | Es correcto o es brecha |
|---|---|---|
| **`DELETE /agenda/notas/<id>/`** — `agenda_item_note_get(note_id=…)` **sin `sucursal_ids`** | `views.py:1156`, selector `selectors.py:295-301` | **Brecha B-AGE-01.** Es el hallazgo que `docs/01-analisis.md:346-348` y §1.5.5 daban por abierto: **confirmado**. Precisión sobre lo documentado: el endpoint **solo implementa `delete`**, así que el riesgo es **borrar**, no leer — la vista no tiene `get` (`views.py:1153`) |
| `agenda_item_note_create` resuelve el padre sin sede | `notes.py:81`, `notes.py:88` | Hoy lo cubre la vista, que ya validó el padre; el service por sí solo no. Defensa en profundidad faltante → B-AGE-09 |
| Disponibilidad del **médico**: sus citas nunca se filtran por sede | `selectors.py:361-368`, `services.py:190-198` | **Correcto y deliberado**: un médico no está en dos sedes a la vez. Documentado en `models.py:356-363` |
| Bloqueo **con médico**: aplica en todas las sedes de ese médico | `selectors.py:49`, `services.py:282` | Correcto, mismo principio |
| `GET|POST /agenda/tipos-cita/` y `<id>/` | `views.py:805`, `:854` | Correcto: el catálogo no tiene sede |
| `GET|PATCH /agenda/config/` | `views.py:743`, `:765` | Correcto: la config es del tenant. **Consecuencia real:** un admin acotado a Centro que edite el horario de la rejilla lo cambia **para las dos sedes** |
| Admin de Django | `admin.py:145`, `:197` | Usa `all_objects` a propósito, cross-tenant, restringido a `is_platform_staff` (`admin.py:128-141`) |

---

### 3.5 Matriz de permisos del módulo

Roles: **O** owner · **A** admin · **D** doctor · **N** nurse · **R** reception · **F** finance ·
**L** readonly. Leyenda: **✔** permitido · **✘** denegado (403) · **▲** permitido con condición.
**Encima de toda esta tabla manda el guard de módulo**: sin `agenda` contratada, **404 para los 7**
(§1.4.2). Y `OPTIONS` devuelve 200 para cualquier rol, incluso `finance` (§1.3.1) — el preflight no
consulta la política.

| Acción (endpoint) | O | A | D | N | R | F | L |
|---|---|---|---|---|---|---|---|
| Ver citas: listado, detalle, disponibilidad (1,4,5) | ✔ | ✔ | ✔ | ✔ | ✔ | ✘ | ✔ |
| Crear cita (2) | ✔ | ✔ | ▲ **solo para sí mismo** (`services.py:417-425`) | ✘ | ✔ | ✘ | ✘ |
| Crear serie (3) | ✔ | ✔ | ▲ ídem | ✘ | ✔ | ✘ | ✘ |
| Editar cita: `reason`/`specialty`/`notes` (6) | ✔ | ✔ | ▲ **cualquier cita de su alcance de sede, no solo las suyas** | ✘ | ✔ | ✘ | ✘ |
| Reagendar (9) | ✔ | ✔ | ▲ ídem — **la regla "solo para mí" no se revalida** (B-AGE-04) | ✘ | ✔ | ✘ | ✘ |
| Reactivar cita cancelada (10) | ✔ | ✔ | ▲ ídem | ✘ | ✔ | ✘ | ✘ |
| **Cancelar por `DELETE /citas/<id>/`** (7) | ✔ | ✔ | **✘** (`permissions.py:195`) | ✘ | ✔ | ✘ | ✘ |
| **Cancelar por `POST /estado/` `status=cancelled`** (8) | ✔ | ✔ | **✔ — hueco: contradice la fila anterior** (B-AGE-03) | ✘ 403 explícito (`views.py:596-603`) | ✔ | ✘ | ✘ |
| Otros cambios de estado: confirmar, en sala, en consulta, atendida, no asistió (8) | ✔ | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ |
| Ver config de agenda (11) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Editar config de agenda (12) | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ |
| Ver tipos de cita (13) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Crear / editar / desactivar tipo de cita (14,15,16) | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ |
| Ver eventos (17) | ✔ | ✔ | ✔ | ✔ | ✔ | ✘ | ✔ |
| Crear evento — reunión o bloqueo (18) | ✔ | ✔ | ✔ | ✘ | ✔ | ✘ | ✘ |
| Editar evento (19) | ✔ | ✔ | ✔ | ✘ | ✔ | ✘ | ✘ |
| Borrar evento (20) | ✔ | ✔ | **✘** | ✘ | ✔ | ✘ | ✘ |
| Ver hilo de notas (21,23) | ✔ | ✔ | ✔ | ✔ | ✔ | ✘ | ✔ |
| Agregar nota (22,24) | ✔ | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ |
| Borrar nota (25) | ✔ | ✔ | ▲ **solo las suyas** | ▲ solo las suyas | ▲ solo las suyas | ✘ | ✘ |

Notas de lectura:

- `finance` está fuera de **toda** la agenda por decisión explícita: el `reason` de una cita se
  considera dato clínico (`MailySoft/backend/apps/core/permissions.py:70-78`). Solo ve la config
  (que no tiene datos de paciente) y el catálogo de tipos.
- `readonly` **ve** la agenda y el hilo de notas, y **no escribe nada**.
- `nurse` **no crea ni edita citas ni eventos**, pero **sí mueve estados** — es la operación de
  piso (`permissions.py:209`).
- El **doctor** puede crear y borrar eventos pero **no puede borrar una cita** ni por `DELETE`
  (aunque sí por `/estado/`, ver B-AGE-03).
- El borrado de notas lo decide el service, no el permiso HTTP: autor, owner o admin
  (`notes.py:206-223`); cualquier otro recibe **400**, no 403.
- **Ninguna clase de permiso de esta app implementa `has_object_permission`** (§1.3.6): la
  granularidad por registro está toda en services y selectors.

---

### 3.6 Recordatorios y tareas asíncronas

#### 3.6.1 Qué se encola y cuándo

`schedule_reminders_for_appointment` (`reminders.py:20-88`) se llama en **tres** momentos, siempre
envuelto en `try/except` para que una falla no tumbe la cita:

| Momento | `archivo:línea` | ¿Dentro de transacción? |
|---|---|---|
| Al crear una cita | `services.py:589-597` | **No** — después del `atomic()` (`:523-567`), ya comprometido |
| Al reagendar | `services.py:1063-1074` | **No** — antes se cancelan los del horario viejo, deliberadamente fuera del `atomic()` para evitar una condición de carrera (`services.py:1060-1063`) |
| Al reactivar | `services.py:1156-1165` | **No** |

Pero por **anidamiento** sí quedan dentro de una transacción abierta en dos rutas:
`appointment_create_with_new_patient` (`services.py:628`) y `appointment_create_series`
(`services.py:730`), porque ambas envuelven a `appointment_create` en su propio `atomic()`.
Es el escenario donde muerde el `apply_async` sin `on_commit` → B-AGE-02.

Lógica de creación (`reminders.py:46-88`):

1. Si `config.reminders_enabled` es `False` → devuelve `[]` sin crear nada (`:47-48`).
2. Por cada `offset` de `config.reminder_offsets_minutes`: `scheduled_at = starts_at − offset`.
3. Si `scheduled_at <= now` → se **omite** (no se crea como `skipped`, simplemente no existe,
   `:60-62`).
4. Deduplicación por `(cita, scheduled_at, status=PENDING)` con `all_objects` (`:65-71`).
5. `AppointmentReminder.objects.create(... channel=WHATSAPP, status=PENDING)` (`:73-80`).
6. **`send_appointment_reminder.apply_async(args=[str(reminder.id)], eta=scheduled_at)`**
   (`:82-85`).

**Confirmado: `apply_async` no está envuelto en `transaction.on_commit`** (`reminders.py:82`), tal
como reporta `docs/01-analisis.md:352-354`. Precisión sobre la consecuencia que ahí se describe: si
la transacción externa revierte, **la fila del recordatorio revierte con ella**, así que la tarea no
"se dispara sobre una cita que terminó sin guardarse": se dispara, no encuentra el id y devuelve
`"not_found"` (`tasks.py:95-97`). El daño real es una tarea huérfana en la cola y ruido en el log,
no un mensaje enviado a un paciente cuya cita no existe.

Cancelación: `cancel_reminders_for_appointment` (`reminders.py:91-115`) hace un `UPDATE` masivo de
`PENDING → CANCELLED` con `all_objects`, y **no revoca la tarea en Celery**: la revocación por id es
cara y no garantizada, así que se confía en que la tarea revalide el estado (`reminders.py:99-104`).
Se invoca al cancelar, al marcar no-show (`services.py:841-848`) y al reagendar
(`services.py:1063`).

#### 3.6.2 La tarea `send_appointment_reminder`

`tasks.py:63-251`. `@shared_task(bind=True, max_retries=3, default_retry_delay=300)`.
Sin cola ni ruteo propio: usa la cola por defecto (`MailySoft/backend/config/settings/base.py:284`).

1. Carga con `all_objects` — **no hay tenant en el worker** (`tasks.py:6-13`, `:90-94`). El
   aislamiento lo da el UUID directo más RLS. Fuera de request `TenantManager` tampoco filtraría
   (§1.1.5).
2. Idempotencia: `status != PENDING` → `"skipped:<status>"` (`:102-108`).
3. Cita en `cancelled`/`no_show`/`attended` → marca `SKIPPED` (`:115-128`).
4. Formatea fecha en `Tenant.timezone` con fallback a `America/Mexico_City` y, si eso falla, a UTC
   (`:146-154`).
5. Valida E.164 con `^\+[1-9]\d{7,14}$` (`:60`). Sin teléfono o no E.164 → `SKIPPED`
   `"Teléfono ausente o no E.164."` (`:173-181`). En datos de desarrollo esto es lo normal
   (`tasks.py:25-29`).
6. Llama al adapter. Excepción → `self.retry()`; agotados los 3 reintentos → `FAILED` con el error en
   `error_detail`, **nunca en el valor de retorno** (`:193-211`).
7. `result.success` → `SENT` + `sent_at` + `external_message_id` (`:216-237`);
   `success=False` → `FAILED` **sin reintentar** (`:238-251`).

#### 3.6.3 Qué pasa hoy realmente al enviar

**Confirmado: no se envía nada.** `get_whatsapp_adapter()` **siempre** devuelve
`SimulatedWhatsAppAdapter` (`MailySoft/backend/adapters/whatsapp.py:106-121`; el `return` de la línea
121 es incondicional y hay un `TODO(whatsapp-real)` en `:119-120`). `MetaWhatsAppAdapter` **no
existe**: se menciona en el docstring del módulo (`:6-7`) pero no hay ninguna clase con ese nombre en
el archivo.

`SimulatedWhatsAppAdapter.send_template` (`:80-103`) escribe una línea INFO con el teléfono
enmascarado y sin params — cumplimiento LFPDPPP deliberado (`:87-91`) — y devuelve
`WhatsAppResult(success=True, external_message_id="sim-<12 hex>")`.

Consecuencia que hay que decir en voz alta: **el recordatorio queda en `SENT` con `sent_at` poblado
y ese estado se devuelve al front dentro de cada cita** (`serializers.py:188`,
`AppointmentOutputSerializer.reminders`). La clínica lee "Enviado" y el paciente nunca recibió nada
→ B-AGE-05. Coincide con `docs/01-analisis.md:255-256`, que ya lo declara fuera de alcance; lo que el
análisis no dice es que el estado mostrado **afirma** el envío.

#### 3.6.4 Lo que no existe

- **No hay barredora.** El único disparador es el `eta` guardado en el broker; `CELERY_BEAT_SCHEDULE`
  no tiene ninguna tarea de agenda (`MailySoft/backend/config/settings/base.py:303-310`). Si Redis se
  reinicia o purga la cola, esos recordatorios quedan `PENDING` para siempre y nadie se entera →
  B-AGE-13.
- **No hay endpoint de recordatorios.** Ni listado, ni creación, ni reintento manual. El selector
  `reminder_list_for_appointment` (`selectors.py:304-314`) **no lo usa ninguna vista** — solo los
  tests → B-AGE-14. La única exposición es el arreglo anidado `reminders` de cada cita.
- **No hay webhook de entrega** aunque el modelo reserve `external_message_id` para reconciliarlo
  (`models.py:748-756`).
- **El módulo `recordatorios` no gatea nada**: no hay `RequiresRecordatorios` ni `require_module`
  en toda la app (verificado por búsqueda en `apps/agenda/`). Una clínica con `agenda` y sin
  `recordatorios` **igual programa recordatorios y los ve en la respuesta de sus citas** → B-AGE-08.
  Es la manifestación concreta de B-T-07 (§1.4.1).

---

### 3.7 Efectos secundarios

#### 3.7.1 Bitácora

Toda escritura llama `audit_record` (§1.8.5, absorbe excepciones: nunca tumba la operación).

| Acción | `ActionType` | Dónde | `metadata` |
|---|---|---|---|
| Crear cita | `APPOINTMENT_CREATE` | `services.py:599-611` | `doctor_id`, `patient_id`, `sucursal_id` |
| Editar cita | `APPOINTMENT_UPDATE` | `services.py:1224-1232` | `changed_fields` |
| Cambiar estado | `APPOINTMENT_STATUS` | `services.py:850-861` | `old_status`, `new_status` |
| Reagendar | `APPOINTMENT_RESCHEDULE` | `services.py:1076-1088` | `new_starts_at`, `new_ends_at`, `sucursal_id` |
| Reactivar | `APPOINTMENT_REACTIVATE` | `services.py:1167-1174` | — |
| Config de agenda | `CONFIG_UPDATE` | `services.py:1299-1307` | `changed_fields` |
| Tipo de cita | `APPOINTMENT_TYPE_CREATE` / `_UPDATE` / `_DEACTIVATE` | `appointment_types.py:38`, `:61`, `:81` | `changed` en update |
| Evento | `AGENDA_EVENT_CREATE` / `_UPDATE` / `_DELETE` | `blocks.py:112`, `:208`, `:173` | `kind`, `changed` |
| Nota | `AGENDA_NOTE_ADD` / `_DELETE` | `notes.py:104-115`, `:228-236` | `appointment_id`/`block_id`, `deleted_by_role` |

Enumerados en `MailySoft/backend/apps/audit/models.py:48-58`, `:72`, `:102-103`.

**Dos observaciones sobre PII en la bitácora:** `resource_repr` de una cita es `str(appointment)`,
que incluye **el nombre completo del paciente** (`models.py:528-532`); y la creación de cita guarda
`patient_id` en `metadata`. La regla de §CLAUDE.md pide "un identificador no-PII del recurso" →
B-AGE-16.

**Lo que NO se audita:** la creación de recordatorios, su cancelación masiva
(`reminders.py:112-115`), y el envío o fallo del envío (`tasks.py` no llama `audit_record` en ningún
punto).

#### 3.7.2 Notificaciones in-app (campana)

Dos disparadores, ambos best-effort dentro de `try/except` que solo loguea:

| Disparo | Destinatarios | `archivo:línea` |
|---|---|---|
| Nota nueva en el hilo de una **cita** | médico de la cita **siempre** + recepción **filtrada a la sede de la cita** + todos los que ya comentaron el hilo, menos el autor | `notes.py:121-148` |
| Nota nueva en el hilo de un **evento** | médico del evento si lo hay + quienes ya comentaron | `notes.py:149-168` |
| **Reunión** creada (`kind=meeting`) | con médico → ese médico; con consultorio → los médicos activos de ese consultorio; sin ninguno → **staff de la sede del evento** | `blocks.py:124-153` |

Un **bloqueo** (`kind=block`) **no notifica a nadie** (`blocks.py:124`).

**PII en el aviso:** el título de la notificación de nota de cita es
`f"Nueva nota en la cita de {appointment.patient.full_name}"` y el cuerpo son los primeros 200
caracteres de la nota (`notes.py:143-144`). Es exactamente el riesgo 4 de
`docs/01-analisis.md:340-342`, confirmado aquí con línea.

#### 3.7.3 Consumidores de esta app fuera de agenda

Relevantes para no romper nada al tocar los services:

| Quién | Qué usa | `archivo:línea` |
|---|---|---|
| Calendarización de planes de tratamiento | `appointment_create`, `appointment_reschedule`, `appointment_change_status(CANCELLED)` | `MailySoft/backend/apps/expediente/services_calendarizacion.py:919`, `:952`, `:978`, `:209-214` |
| Nota de evolución | exige `appointment.status == ATTENDED` para poder escribirse | `MailySoft/backend/apps/expediente/services.py:682` |
| Signos vitales y evoluciones | leen `Appointment.objects.get(...)` | `MailySoft/backend/apps/expediente/views_signos.py:173`, `views_evoluciones.py:185` |
| Alta de clínica desde el portal interno | `appointment_type_create` para sembrar el catálogo | `MailySoft/backend/apps/plataforma/services.py:37` |
## 4. Expediente clínico

> Extraído del código el 2026-08-12 (modo inverso). Cada afirmación cita `archivo:línea` relativo a
> la raíz del repo. Lo que no se pudo verificar leyendo código está marcado con **NO VERIFICADO**.
> Esta sección **cita** la capa transversal (§1) y no la repite.

Alcance leído: `apps/expediente/` completo — `models.py`, `urls.py`, `views.py` (re-exportador),
`views_alergias.py`, `views_historia.py`, `views_signos.py`, `views_evoluciones.py`,
`views_imagenes.py`, `views_libro.py`, `views_preguntas.py`, `views_resumen.py`,
`views_plan_integral.py`, `views_calendarizacion.py`, `views_catalogos.py`, `services.py`,
`services_resumen.py`, `services_plan_integral.py`, `services_calendarizacion.py`,
`services_catalogos.py`, `selectors.py`, `serializers.py`, `validators.py`, `pdf_jobs.py`,
`apps.py` y el índice de `migrations/`. Se consultó como insumo `apps/core/permissions.py:660-1058`,
`apps/plataforma/services.py:602-652` y `apps/pacientes/selectors.py:28`.

**Resumen:** 15 modelos, 33 rutas, 52 operaciones HTTP, 33 clases de vista. Todas las vistas heredan
de `TenantAPIView` (§1.1.2) y todas declaran `permission_classes` con guard de módulo. Dos guards
distintos conviven: `RequiresExpediente` en 27 rutas y `RequiresCalendarizacion` en las 6 de
calendarización (§1.4.1).

---

### 4.1 Modelo de datos

**Los 15 modelos heredan de `TenantAwareModel`** (§1.8.2): id UUID, `created_at`/`updated_at`/
`deleted_at`, `tenant` FK `PROTECT`, `created_by` FK `SET_NULL`, managers `objects`/`all_objects`.
**Los 15 tienen migración de RLS** — `0002` alergias, `0004` HC, `0007` signos, `0010`
evolución/addendum/diagnóstico, `0013` imágenes, `0015` preguntas, `0018` resúmenes, `0020`
calendarización (3 tablas), `0024` plan integral, `0026` plantillas, `0028` analitos. **No hay ni un
`ManyToManyField` en la app** (verificado por búsqueda en `models.py`), así que no hay tablas
intermedias auto-generadas que cubrir.

**Ninguna tabla del expediente tiene columna `sucursal`** (verificado por búsqueda: `sucursal` solo
aparece en `views_calendarizacion.py`, `services_calendarizacion.py` y en el fanout a enfermería de
`services.py:783-787`). El expediente es **compartido entre sedes por diseño**; la consecuencia y su
falta de constancia escrita están en B-EXP-09.

#### 4.1.1 `Allergy` → `expediente_allergies` (`MailySoft/backend/apps/expediente/models.py:46`)

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `patient` | FK `pacientes.Patient`, `related_name="allergies"`, `db_index` | no | — | **PROTECT** (`:66`) |
| `substance` | `CharField(160)` | no | — | El service la exige no vacía (`services.py:132-134`) |
| `reaction` | `CharField(255)` | no | `""` | |
| `severity` | `CharField(10)` choices `leve`/`moderada`/`severa` | no | `""` | `Severity`, `models.py:38` |
| `is_active` | `BooleanField`, `db_index` | no | `True` | **Bandera clínica**, no borrado del sistema (`:88-96`) |

- `on_delete=PROTECT` en `patient`: **no se puede borrar en duro un paciente con alergias**. Es
  coherente con que el borrado de paciente sea lógico.
- `ordering = ["-created_at"]`; índice `allergy_patient_active_idx (patient, is_active)` (`:103-106`)
  — consulta que lo justifica: `allergy_list(patient, only_active=True)` (`selectors.py:111-113`),
  el listado por defecto de la ficha.
- Distinción explícita en el docstring del modelo (`:24-26`): `deleted_at` = borrado del sistema,
  **nunca se usa**; `is_active=False` = alergia resuelta.

#### 4.1.2 `MedicalHistory` → `expediente_medical_histories` (`models.py:119`)

| Campo | Tipo | Null | Default |
|---|---|---|---|
| `patient` | FK `Patient` **PROTECT**, `related_name="medical_histories"`, `db_index` | no | — |
| `heredo_familiares`, `personales_patologicos`, `no_patologicos`, `habitos_alimenticios`, `gineco_obstetricos`, `exploracion_fisica_basal` | `JSONField` | no | `{}` |
| `antecedentes_importancia`, `padecimiento_actual`, `tratamientos_actuales`, `prioridad_analisis` | `TextField` | no | `""` |
| `custom_answers` | `JSONField` `{"<question_uuid>": valor}` | no | `{}` |

- **Constraint único parcial** `medical_history_patient_active_uniq` sobre `patient` con
  `condition=Q(deleted_at__isnull=True)` (`:269-273`): una sola HC viva por paciente.
- Índice `medical_history_patient_idx (patient)` (`:276-279`) — consulta:
  `medical_history_get_for_patient` (`selectors.py:138`), que corre en el GET de HC, en el libro
  clínico, en el borrador del resumen y en el del plan integral.
- Los seis bloques JSON se validan por whitelist de claves y tipos en `validators.py` (§4.3.2).

#### 4.1.3 `VitalSignsRecord` → `expediente_vital_signs` (`models.py:296`)

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `patient` | FK `Patient` **PROTECT**, `related_name="vital_signs"` | no | — | |
| `appointment` | FK `agenda.Appointment` **SET_NULL**, `related_name="vital_signs"` | **sí** | `NULL` | Borrar la cita no borra la toma |
| `measured_at` | `DateTimeField`, `db_index` | no | `timezone.now` | No admite futuro (`services.py:541`) |
| `weight_kg` | `Decimal(5,2)` | sí | `NULL` | rango 0.2–500 (`serializers.py:354`) |
| `height_m` | `Decimal(4,3)` | sí | `NULL` | 0.2–2.6 |
| `heart_rate`, `resp_rate`, `systolic`, `diastolic`, `oxygen_saturation`, `glucose` | `PositiveSmallIntegerField` | sí | `NULL` | rangos en `serializers.py:353-363` |
| `temperature_c` | `Decimal(4,1)` | sí | `NULL` | 30–45 |
| `extra_params` | `JSONField` | no | `{}` | whitelist de 5 claves (`models.py:291`) |
| `notes` | `CharField(255)` | no | `""` | |

- `ordering = ["-measured_at"]`; índice `vitals_tenant_patient_time_idx (tenant, patient, measured_at)`
  (`:442-445`) — consulta: `vital_signs_list` (`selectors.py:158-162`) y `vital_signs_series`
  (`selectors.py:229-235`), ambas filtran por paciente y ordenan por tiempo.
- `imc` es **property calculada**, no columna (`:454-466`). El serializer la expone como campo
  virtual (`serializers.py:553-558`).
- El responsable de la toma se infiere de `created_by`; no hay campo aparte (`:325-327`).

#### 4.1.4 `EvolutionNote` → `expediente_evolution_notes` (`models.py:474`)

| Campo | Tipo | `on_delete` | Null | Consecuencia real |
|---|---|---|---|---|
| `patient` | FK `Patient` | **PROTECT** | no | Un paciente con notas no se puede borrar en duro |
| `appointment` | FK `agenda.Appointment` | **PROTECT** | no | **Una cita con nota de evolución queda blindada**: la agenda no puede borrarla ni en duro |
| `doctor` | FK `personal.Doctor` | **PROTECT** | no | Un médico con notas no se borra; su baja es lógica |
| `vital_signs` | FK `VitalSignsRecord` | **SET_NULL** | sí | Si la toma desapareciera, la nota sobrevive sin signos |

Campos clínicos, todos `TextField` `blank=True default=""`: `antecedentes`, `interrogatorio`,
`estudios`, `diagnosticos_texto`, `tratamiento`, `plan_recomendaciones`, `indicaciones_enfermeria`
(`:538-572`). `exploracion_fisica` es `JSONField` default `{}` (`:575`). `is_locked` es
`BooleanField default=True` (`:587`).

- **Constraint único parcial** `evolution_note_appointment_uniq` sobre `appointment` con
  `deleted_at IS NULL` (`:603-607`): **una sola nota por cita**.
- **CheckConstraint** `evolution_is_locked_always`: `Q(is_locked=True)` (`:611-614`). La
  inmutabilidad está sostenida **en la base**, no solo en la capa de servicio.
- Índice `evol_tenant_patient_time_idx (tenant, patient, created_at)` (`:617-620`) — consulta:
  `evolution_note_list` (`selectors.py:343-344`) y `book_build` (`selectors.py:673-712`).

#### 4.1.5 `Addendum` → `expediente_addenda` (`models.py:635`)

| Campo | Tipo | `on_delete` | Null | Consecuencia |
|---|---|---|---|---|
| `evolution` | FK `EvolutionNote`, `related_name="addenda"` | **CASCADE** | no | Si alguna vez se borrara en duro una nota, sus addenda se van con ella. Hoy es teórico: la nota no tiene endpoint de borrado |
| `author` | FK `authn.User`, `related_name="addenda"` | **PROTECT** | no | **Un usuario que firmó un addendum no se puede borrar** — es la firma clínica |
| `body` | `TextField` requerido | — | no | El service lo exige no vacío (`services.py:855-857`) |

`ordering = ["created_at"]` (cronológico ascendente); índice `addendum_evol_time_idx
(tenant, evolution, created_at)` (`:669-672`) — consulta: `addendum_list` (`selectors.py:366`) y el
prefetch `"addenda"` de `evolution_note_get`/`evolution_note_list`.

Además de `author`, el addendum guarda `created_by` (heredado, `SET_NULL`); ambos se llenan con el
mismo usuario (`services.py:859-865`).

#### 4.1.6 `Diagnosis` → `expediente_diagnoses` (`models.py:701`)

| Campo | Tipo | `on_delete` | Null | Default |
|---|---|---|---|---|
| `patient` | FK `Patient` | **PROTECT** | no | — |
| `evolution` | FK `EvolutionNote`, `related_name="diagnoses"` | **SET_NULL** | sí | `NULL` |
| `cie_code` | `CharField(10)` | — | no | `""` |
| `description` | `CharField(255)` | — | no | — |
| `kind` | `CharField(12)` `presuntivo`/`definitivo` | — | no | `presuntivo` |
| `status` | `CharField(10)` `activo`/`resuelto`, `db_index` | — | no | `activo` |

- Índice `diag_tenant_patient_status_idx (tenant, patient, status)` (`:763-766`) — consulta:
  `diagnosis_list(patient, only_active)` (`selectors.py:414-417`).
- Inmutabilidad parcial declarada en el docstring (`:706-711`): `description`, `cie_code` y `kind`
  no se pueden cambiar tras crear porque **no existe ningún endpoint ni service de update**; lo
  único que muta es `status` vía `diagnosis_resolve` (`services.py:1030-1032`). El docstring
  menciona un `_IMMUTABLE_FIELDS` que **no existe en el código** (búsqueda en `services.py`): la
  inmutabilidad es por ausencia de escritura, no por una lista de campos.

#### 4.1.7 `EvolutionImage` → `expediente_evolution_images` (`models.py:781`)

| Campo | Tipo | `on_delete` | Null | Consecuencia |
|---|---|---|---|---|
| `evolution` | FK `EvolutionNote`, `related_name="images"` | **CASCADE** | no | Igual que el addendum: solo aplicaría a un borrado físico que hoy no existe |
| `image` | `ImageField(upload_to=evolution_image_path, max_length=255)` | — | no | Nombre aleatorizado bajo `evoluciones/<tenant_id>/` (§1.8.4) |
| `caption` | `CharField(255)` | — | no (`""`) | |

`ordering = ["created_at"]`; índice `evol_image_evol_time_idx (evolution, created_at)` (`:841-844`)
— consulta: `evolution_images_list` (`selectors.py:522-526`). Tope de negocio: 20 imágenes activas
por nota (`services.py:1061`, `:1119-1125`).

#### 4.1.8 `MedicalHistoryQuestion` → `expediente_medical_history_questions` (`models.py:870`)

| Campo | Tipo | Null | Default |
|---|---|---|---|
| `label` | `CharField(255)` | no | — |
| `field_type` | `CharField(12)` `text`/`textarea`/`boolean`/`select`/`number`/`date` | no | — |
| `options` | `JSONField` | no | `[]` |
| `section` | `CharField(100)` | no | `""` |
| `order` | `PositiveIntegerField` | no | `0` |
| `is_required` | `BooleanField` | no | `False` |
| `is_active` | `BooleanField`, `db_index` | no | `True` |

`ordering = ["order", "id"]`; índice `mhq_tenant_active_idx (tenant, is_active)` (`:941-944`) —
consulta: `medical_history_questions_list(only_active=True)` (`selectors.py:782-784`), que además
corre **dentro de cada serialización de HC** (`serializers.py:335-344`).

Sin FK a `MedicalHistory`: la relación es por convención, la clave del dict `custom_answers` es el
UUID de la pregunta. Consecuencia: nada a nivel de base impide que queden respuestas huérfanas —
y el service las purga en silencio (B-EXP-02).

#### 4.1.9 `ClinicalSummary` → `expediente_clinical_summaries` (`models.py:957`)

| Campo | Tipo | `on_delete` | Null | Consecuencia real |
|---|---|---|---|---|
| `patient` | FK `Patient` | **PROTECT** | no | |
| `evolution` | FK `EvolutionNote`, `related_name="clinical_summaries"` | **PROTECT** | no | La consulta base queda blindada |
| `doctor` | FK `personal.Doctor` | **PROTECT** | sí | Snapshot para el membrete del PDF |
| `created_by` | FK `authn.User` | **PROTECT** ⚠ | sí | **Sobrescribe el `SET_NULL` de `TenantAwareModel`** (§1.8.2): borrar un usuario que generó un resumen queda bloqueado → B-EXP-06 |

Seis `TextField` `default=""`: `identificacion`, `antecedentes`, `padecimiento_actual`,
`exploracion_fisica`, `diagnostico_manejo`, `indicaciones` (`:1021-1050`).

`ordering = ["-created_at"]`; índice `clin_summ_tenant_pat_time_idx (tenant, patient, created_at)`
(`:1056-1059`) — consulta: `clinical_summary_list` (`selectors.py:957-963`).

El propio docstring dice que la inmutabilidad es **de negocio, no de base**: no hay PATCH/PUT
ruteado, pero el modelo no bloquea `save()` (`:966-970`).

#### 4.1.10 `TreatmentPlan` → `expediente_treatment_plans` (`models.py:1092`)

| Campo | Tipo | `on_delete` | Null | Consecuencia real |
|---|---|---|---|---|
| `patient` | FK `Patient` | **PROTECT** | no | |
| `doctor` | FK `personal.Doctor` | **PROTECT** | sí | Opcional: owner/admin arman esquemas sin médico fijo |
| `consultorio` | FK `personal.Consultorio`, `related_name="+"` | **SET_NULL** | sí | Borrar el consultorio no borra el esquema |
| `quote` | FK `finanzas.Quote`, `related_name="+"` | **SET_NULL** | sí | Cada regeneración crea cotización nueva y reapunta; la anterior queda viva (`services_calendarizacion.py:728-729`) |
| `created_by` | FK `authn.User` | **PROTECT** ⚠ | sí | Igual que `ClinicalSummary` → B-EXP-06 |
| `title` | `CharField(200)` | — | no | `DEFAULT_TREATMENT_PLAN_TITLE` (`:1074`) |
| `notes` | `TextField` | — | no (`""`) | |
| `status` | `CharField(10)` `borrador`/`activa`/`completada`, `db_index` | — | no (`activa`) | |

Índice `tx_plan_tenant_pat_time_idx (tenant, patient, created_at)` (`:1196-1199`) — consulta:
`treatment_plan_list` (`selectors.py:1063-1070`).

#### 4.1.11 `TreatmentPlanItem` → `expediente_treatment_plan_items` (`models.py:1209`)

| Campo | Tipo | `on_delete` | Null | Default |
|---|---|---|---|---|
| `plan` | FK `TreatmentPlan`, `related_name="items"` | **CASCADE** | no | — |
| `service_concept` | FK `finanzas.ServiceConcept`, `related_name="+"` | **PROTECT** | sí | `NULL` (permite captura manual) |
| `description` | `CharField(255)` | — | no | — (snapshot del concepto) |
| `unit_price` | `Decimal(12,2)` | — | no | `0` (snapshot) |
| `quantity` | `PositiveSmallIntegerField` | — | no | `1` (= nº de sesiones) |
| `order` | `PositiveSmallIntegerField` | — | no | `0` |

`ordering = ["order", "id"]`. **Sin índices propios** más allá de los de FK. Con esquemas de pocas
líneas por paciente, no se propone ninguno.

`CASCADE` desde `plan` significa que **borrar en duro un esquema arrastra sus líneas y sesiones** —
y eso ocurre de verdad en el PUT de reemplazo (B-EXP-03), no solo en teoría.

#### 4.1.12 `TreatmentSession` → `expediente_treatment_sessions` (`models.py:1261`)

| Campo | Tipo | `on_delete` | Null | Default |
|---|---|---|---|---|
| `item` | FK `TreatmentPlanItem`, `related_name="sessions"` | **CASCADE** | no | — |
| `number` | `PositiveSmallIntegerField` | — | no | — |
| `scheduled_date` | `DateField` | — | sí | `NULL` |
| `scheduled_time` | `TimeField` | — | sí | `NULL` |
| `applied_date` | `DateField` | — | sí | `NULL` |
| `status` | `CharField(10)` `programada`/`aplicada`, `db_index` | — | no | `programada` |
| `duration_minutes` | `PositiveSmallIntegerField` | — | sí | `NULL` |
| `appointment` | FK `agenda.Appointment`, `related_name="treatment_sessions"` | **SET_NULL** | sí | `NULL` — si la cita se borra, la sesión queda "sin agendar" |

`ordering = ["number", "id"]`. Las columnas de firma del PDF son **físicas**: nunca se persisten
(`:1263-1265`).

#### 4.1.13 `LongevityPlan` → `expediente_longevity_plans` (`models.py:1334`)

| Campo | Tipo | `on_delete` | Null | Consecuencia real |
|---|---|---|---|---|
| `patient` | FK `Patient` | **PROTECT** | no | |
| `doctor` | FK `Doctor` | **PROTECT** | sí | Solo se rellena si el actor es `doctor` (`services_plan_integral.py:440-443`) |
| `created_by` | FK `authn.User` | **PROTECT** ⚠ | sí | → B-EXP-06 |
| `treatment_plan` | FK `TreatmentPlan`, `related_name="longevity_plans"` | **SET_NULL** | sí | El snapshot `esquema` sobrevive aunque el esquema se borre |

Ocho `TextField default=""` (`alergias`, `antecedentes`, `tratamientos_actuales`,
`condiciones_mejorar`, `estudios`, `reporte_medico`, `interconsulta`, `seguimiento`) y cuatro
`JSONField default=list`: `esquema`, `lab_results`, `gabinete_studies`, `equipo` (`:1453-1488`).

Índice `long_plan_tenant_pat_time_idx (tenant, patient, created_at)` (`:1493-1496`) — consulta:
`longevity_plan_list` (`selectors.py:1123-1129`).

#### 4.1.14 `DocumentTemplate` → `expediente_document_templates` (`models.py:1526`)

| Campo | Tipo | Null | Default |
|---|---|---|---|
| `name` | `CharField(160)` | no | — |
| `section` | `CharField(30)` choices de `DocumentTemplateSection` (`:1509`), `db_index` | no | — |
| `body` | `TextField` | no | — |
| `is_active` | `BooleanField`, `db_index` | no | `True` |

`ordering = ["section", "name"]`; índice `doc_tmpl_tenant_section_idx (tenant, section)`
(`:1564-1567`) — consulta: `document_template_list(section=...)` (`selectors.py:1158-1163`).
Sin FK a paciente ni a plan: es catálogo por clínica.

#### 4.1.15 `LabAnalyte` → `expediente_lab_analytes` (`models.py:1579`)

| Campo | Tipo | Null | Default |
|---|---|---|---|
| `name` | `CharField(160)` | no | — |
| `unit` | `CharField(40)` | no | `""` |
| `ref_low` / `ref_high` | `Decimal(12,4)` | sí | `NULL` |
| `is_active` | `BooleanField`, `db_index` | no | `True` |

`ordering = ["name"]`; índice `lab_analyte_tenant_name_idx (tenant, name)` (`:1624`) — consulta:
`lab_analyte_list` (`selectors.py:1189-1192`). El rango se lee al crear la constancia y se
**snapshotea** dentro de `LongevityPlan.lab_results`; cambiar el catálogo después no altera
constancias emitidas (`services_plan_integral.py:245-274`).

#### 4.1.16 Índices que **no** existen y hoy no hacen falta

No hay índice sobre `expediente_treatment_plan_items.plan` ni sobre
`expediente_treatment_sessions.item` más allá del que Django crea por la FK, ni sobre
`expediente_addenda.author`. Con 1-3 usuarios concurrentes y esquemas de pocas líneas, cualquier
índice adicional sería peso muerto en cada escritura. No se propone ninguno.

---

### 4.2 Endpoints

Prefijo `/api/v1/` (`MailySoft/backend/config/urls.py:46`). Rutas en
`MailySoft/backend/apps/expediente/urls.py`. Convenciones generales (auth, formato de error,
códigos, throttling, fechas) en §1.7. Todos los `<uuid:...>` se resuelven por selector con
`TenantManager`: recurso de otro tenant → **404**, nunca 403 (§1.7.2).

**Guard de módulo por defecto:** `RequiresExpediente` (§1.4.1). Las 6 rutas de calendarización usan
`RequiresCalendarizacion`. Módulo apagado → **404**, no 403.

**Error común a casi todas las escrituras:** `400 {"detail": ["<mensaje>", ...]}` — es la traducción
de un `ValidationError` de service, **lista**, no string (§1.7.2). Los errores de serializer llegan
como `400 {"<campo>": ["..."]}`.

**Error común a las escrituras con `get_current_tenant()`:** `403 {"detail": "No se encontró un
tenant activo para este request."}` (p. ej. `views_alergias.py:74-78`). En la práctica
`TenantAPIView` ya lo garantiza; es defensa en profundidad.

#### 4.2.1 Alergias

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/alergias/` | `views_alergias.py:42` | `AllergyPermission` (§1.3.2 #21) + `RequiresExpediente` | 200 **array plano, sin paginar** |
| POST | `/api/v1/expediente/<patient_id>/alergias/` | `views_alergias.py:60` | ídem | 201 `AllergyOutput` |
| DELETE | `/api/v1/expediente/alergias/<allergy_id>/` | `views_alergias.py:108` | ídem | **204 sin cuerpo** |

- **GET** — query param `include_resolved` (`true|1|yes`, default `false`) (`views_alergias.py:53-55`).
  Lectura abierta a **los 7 roles** a propósito: bandera de seguridad (§1.3.2 #21). Errores: 401,
  403, 404 `{"detail": "Paciente no encontrado."}`.
- **POST** — body: `substance` (≤160, requerido, no vacío), `reaction` (≤255, opcional),
  `severity` (`leve|moderada|severa|""`) (`serializers.py:131-138`). Campos no declarados → 400
  `{"<campo>": ["Campo no permitido."]}` (`serializers.py:114-116`). Errores: 400, 401, 403, 404.
- **DELETE** — no borra: pone `is_active=False` (`services.py:209-211`). **Idempotente**: resolver
  una alergia ya resuelta devuelve 204 y no audita. **No existe endpoint para reactivarla.**
- Respuesta (`AllergyOutputSerializer`, `serializers.py:153`):
  `{id, patient_id, substance, reaction, severity, severity_display, is_active, created_at, updated_at}`.

#### 4.2.2 Historia clínica

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/historia/` | `views_historia.py:81` | `MedicalHistoryPermission` (§1.3.2 #22) + `RequiresExpediente` | 200 |
| PUT | `/api/v1/expediente/<patient_id>/historia/` | `views_historia.py:149` | ídem (PUT → O A D) | **200**, no 201 |

- **GET** — si el paciente aún no tiene HC devuelve **200 con un documento vacío**, no 404
  (`views_historia.py:138-142`): la HC es un "documento vivo" que siempre existe conceptualmente.
  ⚠ Ese documento vacío **no trae `custom_answers` ni `active_questions`**, que sí están en el
  serializer real (`views_historia.py:64-79` vs `serializers.py:315-332`) → B-EXP-10.
- **PUT** — upsert idempotente. Body: los 6 bloques JSON (opcionales, `null` = no tocar), 4 textos
  (`antecedentes_importancia`, `padecimiento_actual`, `tratamientos_actuales` ≤10 000;
  `prioridad_analisis` ≤5 000) y `custom_answers` (`serializers.py:214-238`).
  - Los bloques que llegan se validan contra whitelist de claves y tipos (`validators.py`, §4.3.2)
    → 400 `{"<bloque>": "Claves no permitidas: ..."}`.
  - `gineco_obstetricos` con contenido y paciente de sexo ≠ F → 400; sin paciente en el contexto →
    400 **fail-closed** (`serializers.py:263-289`).
  - Los textos **siempre se sobrescriben**, incluso si no llegan (el serializer les pone `""` por
    default y el service los asigna sin condición) — `services.py:352-356`. Un PUT parcial que solo
    manda un bloque JSON **borra los cuatro textos**.
- Respuesta: `MedicalHistoryOutputSerializer` — los 6 bloques, los 4 textos, `custom_answers` y
  `active_questions` (catálogo de preguntas activas para pintar el formulario, `serializers.py:335-344`).
- Errores: 400, 401, 403, 404 `{"detail": "Paciente no encontrado."}`.

#### 4.2.3 Signos vitales

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/signos/` | `views_signos.py:82` | `VitalSignsPermission` (§1.3.2 #23) + `RequiresExpediente` | 200 paginado |
| POST | `/api/v1/expediente/<patient_id>/signos/` | `views_signos.py:135` | ídem (POST → O A D N) | 201 |
| GET | `/api/v1/expediente/<patient_id>/signos/series/` | `views_signos.py:227` | ídem | 200 |

- **Append-only:** no hay PATCH/PUT/DELETE ruteados → **405**.
- **Paginación propia** `_VitalSignsPagination` (`views_signos.py:36`): `page_size=50`, param
  `page_size` **sí admitido**, tope 200 — se aparta del paginador estándar de §1.7.1.
- **POST** body (`serializers.py:370`): `measured_at` (ISO, default ahora, no futuro), los 9
  parámetros numéricos con rango fisiológico, `extra_params` (solo `colesterol`, `trigliceridos`,
  `urea`, `creatinina`, `hemoglobina`, cada uno número > 0 y ≤ 10 000), `notes` (≤255),
  `appointment_id` (opcional).
  - `systolic <= diastolic` → 400 (`serializers.py:498-502`).
  - `appointment_id` inexistente, de otro tenant o de otro paciente → **404 idéntico**
    `{"detail": "Cita no encontrada."}` (`views_signos.py:168-180`), para no filtrar existencia.
- **Series** (`views_signos.py:227`): query param `since=YYYY-MM-DD` (formato inválido → 400).
  Devuelve `{ "<parametro>": [{"measured_at": ISO, "value": float}, ...] }` con 14 claves: los 8
  campos planos, `imc` y las 5 de `extra_params` (`selectors.py:250-252`). Sin paginación; tope
  interno **silencioso** de 730 registros más recientes (`selectors.py:190`, `:235`).
- Respuesta de la toma (`VitalSignsOutputSerializer`, `serializers.py:511`): todos los parámetros +
  `imc` (float derivado) + `created_by_id` + `created_by_name` + `created_at`.

#### 4.2.4 Notas de evolución y addenda

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/evoluciones/` | `views_evoluciones.py:101` | `EvolutionPermission` (§1.3.2 #24) + `RequiresExpediente` | 200 paginado |
| POST | `/api/v1/expediente/<patient_id>/evoluciones/` | `views_evoluciones.py:148` | ídem (POST → O A D) | 201 |
| POST | `/api/v1/expediente/evoluciones/<evolution_id>/addendum/` | `views_evoluciones.py:270` | `AddendumPermission` (§1.3.2 #30) + `RequiresExpediente` | 201 |

- **PATCH, PUT y DELETE sobre una nota no existen** → **405**. Es el sostén HTTP de la inmutabilidad
  (`views.py:45-47`). `EvolutionPermission` sí declara `DELETE` pero solo lo consume el endpoint de
  imágenes (`permissions.py:753-760`).
- **Paginación** `_EvolutionPagination` (`views_evoluciones.py:56`): `page_size=20`, param
  `page_size` admitido, tope 100.
- **POST** body (`serializers.py:577`): `appointment_id` (requerido), `doctor_id` (requerido),
  `vital_signs_id` (opcional), 7 textos ≤10 000 y `exploracion_fisica` (JSON validado, §4.3.2).
  - **Nota vacía → 400**: hace falta al menos un texto con contenido o un aparato con estado
    distinto de `no_evaluado` (`serializers.py:672-677`).
  - Resolución anti-IDOR: cita → 404 `"Cita no encontrada."`; médico → 404
    `"Médico no encontrado."`; signos → 404 `"Signos vitales no encontrados."`
    (`views_evoluciones.py:173-220`).
  - Reglas de negocio del service en §4.3.1 (cita ATTENDED, doctor de la cita, una nota por cita,
    regla del médico).
- **Respuesta** (`EvolutionNoteOutputSerializer`, `serializers.py:699`): campos clínicos +
  `is_locked` + `addenda` anidados. Los diagnósticos **no** vienen aquí: van por su endpoint.
- **Addendum** body: `body` (≤5 000, no vacío) → 201
  `{id, evolution_id, author_id, body, created_at}`. **No hay GET, PATCH ni DELETE de addenda**: se
  leen anidados en la nota. `addendum_list` (`selectors.py:353`) existe pero **ninguna vista lo
  llama** (verificado por búsqueda) — selector muerto.

#### 4.2.5 Diagnósticos

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/diagnosticos/` | `views_evoluciones.py:337` | `DiagnosisPermission` (§1.3.2 #31) + `RequiresExpediente` | 200 paginado |
| POST | `/api/v1/expediente/<patient_id>/diagnosticos/` | `views_evoluciones.py:391` | ídem | 201 |
| POST | `/api/v1/expediente/diagnosticos/<diagnosis_id>/resolver/` | `views_evoluciones.py:464` | ídem | **200** con el diagnóstico |

- **GET** — query param `only_active` (`true|1|yes`, default `false` = trae activos y resueltos)
  (`views_evoluciones.py:376-377`). Paginado con `_EvolutionPagination`.
- **POST** body: `description` (≤255, requerida, no vacía), `cie_code` (≤10, opcional, **validado
  contra `^[A-Z]\d{2}(\.\d{1,2})?$` y normalizado a mayúsculas**, `serializers.py:86`, `:809-832`),
  `kind` (`presuntivo|definitivo`), `evolution_id` (opcional; de otro paciente o tenant → 404).
- **Resolver** — cambia `status` a `resuelto`. **Idempotente**: resolver uno ya resuelto devuelve
  200 y no audita (`services.py:1030`). **No hay endpoint para reabrirlo.**
- Respuesta: `{id, patient_id, evolution_id, cie_code, description, kind, kind_display, status, status_display, created_at, updated_at}`.

#### 4.2.6 Indicaciones de enfermería

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/indicaciones-enfermeria/` | `views_imagenes.py:64` | `NursingInstructionPermission` (§1.3.2 #32) + `RequiresExpediente` | 200 array plano |

Devuelve las **últimas 20** notas de evolución del paciente con `indicaciones_enfermeria` no vacía,
orden `-created_at` (`selectors.py:472-483`). **Sin paginación** ni query params: el límite es fijo
y no es configurable. Forma por elemento: `{id, fecha, doctor, indicaciones}`
(`serializers.py:873-894`) — `doctor` es el nombre completo del médico, `""` si no se puede
resolver. Único método ruteado: GET; cualquier otro → 405.

#### 4.2.7 Imágenes de evolución

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/evoluciones/<evolution_id>/imagenes/` | `views_imagenes.py:110` | `EvolutionPermission` + `RequiresExpediente` | 200 array plano |
| POST | `/api/v1/expediente/evoluciones/<evolution_id>/imagenes/` | `views_imagenes.py:128` | ídem (POST → O A D) | 201 |
| DELETE | `/api/v1/expediente/imagenes/<image_id>/` | `views_imagenes.py:187` | ídem (DELETE → O A D) | 204 |

- **POST** — `multipart/form-data`, campos `image` (requerido) y `caption` (≤255). La barrera real
  de seguridad es `validate_evolution_image` en el service (Pillow, JPEG/PNG/WEBP, 10 MB, tope de
  40 MP — §1.8.4), no el `ImageField` del serializer (`serializers.py:924-926`,
  `services.py:1131`). Tope de **20 imágenes activas por nota** → 400
  `{"detail": ["La nota ya tiene el máximo de imágenes (20)."]}` (`services.py:1122-1125`).
- **DELETE** — baja lógica (`deleted_at`), el archivo físico **no se borra**
  (`services.py:1445-1447`). Idempotente. 404 `{"detail": "Imagen no encontrada."}`.
- Respuesta: `{id, evolution_id, image_url, caption, created_at}` — `image_url` absoluta si hay
  `request` en el contexto (`serializers.py:967-979`).
- Sin paginación en el listado (acotado por el tope de 20).

#### 4.2.8 Libro clínico

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/libro/` | `views_libro.py:62` | `EvolutionPermission` (GET = CLINICAL_READ) + `RequiresExpediente` | 200 |
| GET | `/api/v1/expediente/<patient_id>/libro/pdf/` | `views_libro.py:146` | ídem | **202** `{job_id, status}` |

- **JSON** — query params `page` (default 1) y `page_size` (default 10, tope 50,
  `selectors.py:534-536`, `:656`). Valores no numéricos caen al default sin error
  (`views_libro.py:73-81`); `page` fuera de rango se **clampa**, no da 404 (`selectors.py:720`).
  Respuesta (`PatientBookSerializer`, `serializers.py:1254`):
  `{paciente, clinica, historia_clinica, alergias, capitulos_count, total_pages, page, page_size, capitulos[]}`.
  Cada capítulo (`serializers.py:1144`) trae `{id, fecha, doctor{full_name, cedulas_validadas},
  signos, subjetivo, objetivo, exploracion[], analisis{texto, diagnosticos[]}, plan{...},
  imagenes[], recetas[], addenda[]}` — estructura SOAP. Solo aparecen los diagnósticos **ligados a
  esa evolución**; los sueltos del paciente no se incluyen en ningún capítulo (decisión escrita en
  `selectors.py:614-625`).
- **PDF** — query params `modo` (`completo|hc|ultimo`, default `completo`; inválido → 400) e
  `imagenes` (`0|false|no` para omitirlas, default incluirlas) (`views_libro.py:160-171`).
  Encola con `cache_key=""` → **siempre genera un PDF nuevo** (`views_libro.py:202-213`). El
  seguimiento es por `/api/v1/pdfs/job/<job_id>/` (§1.3.6).

#### 4.2.9 Resumen clínico por consulta

Los 4 endpoints usan `ClinicalSummaryPermission` (§1.3.2 #25 → **solo O A D**, sin nurse ni
readonly) + `RequiresExpediente`.

| Método | Ruta | Vista:línea | Éxito |
|---|---|---|---|
| GET | `/api/v1/expediente/evoluciones/<evolution_id>/resumen/borrador/` | `views_resumen.py:93` | 200, **no persiste** |
| POST | `/api/v1/expediente/evoluciones/<evolution_id>/resumen/` | `views_resumen.py:118` | 201 |
| GET | `/api/v1/expediente/resumenes/<summary_id>/pdf/` | `views_resumen.py:165` | 202 `{job_id, status}` |
| GET | `/api/v1/expediente/<patient_id>/resumenes/` | `views_resumen.py:199` | 200 paginado |

- **Borrador** — compone HC + evolución + signos y devuelve
  `{"encabezado": {clinic_name, patient_name, edad, sexo, fecha, peso_kg, talla_m, ta, fc, fr, temp_c},
  "secciones": {identificacion, antecedentes, padecimiento_actual, exploracion_fisica,
  diagnostico_manejo, indicaciones}}` (`serializers.py:1330-1370`). Reglas de armado en
  `services_resumen.py:320-352`: los antecedentes "Negado"/vacíos se omiten (`:112`, `:118-123`), la
  exploración solo reporta sistemas `observacion`/`alterado` (`:115`, `:215-235`).
- **POST** — las 6 secciones, todas opcionales, ≤10 000 caracteres (`serializers.py:1373-1398`).
  Regla del médico en §4.3.1. Respuesta 201 `{id, created_at, doctor_name, evolution_id}` — **el
  texto no se devuelve** a propósito (`serializers.py:1409-1411`).
- **Listado** — paginación estándar de §1.7.1 (`PageNumberPagination()`, 25/pág, sin `page_size`).
- **No hay PATCH, PUT ni DELETE**: la constancia es append-only por ausencia de ruta.
- 404 posibles: `"Nota de evolución no encontrada."`, `"Resumen clínico no encontrado."`,
  `"Paciente no encontrado."`.

#### 4.2.10 Plan integral de longevidad

Los 3 endpoints usan `LongevityPlanPermission` (§1.3.2 #27 → **solo O A D**) + `RequiresExpediente`.

| Método | Ruta | Vista:línea | Éxito |
|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/plan-integral/borrador/` | `views_plan_integral.py:110` | 200, no persiste |
| GET | `/api/v1/expediente/<patient_id>/plan-integral/` | `views_plan_integral.py:144` | 200 paginado |
| POST | `/api/v1/expediente/<patient_id>/plan-integral/` | `views_plan_integral.py:156` | 201 |
| GET | `/api/v1/expediente/plan-integral/<plan_id>/pdf/` | `views_plan_integral.py:206` | 202 `{job_id, status}` |

- **Borrador** — query param `treatment_plan_id` (UUID; formato inválido → 400
  `{"detail": "treatment_plan_id no es un UUID válido."}`; inexistente → 404
  `"Esquema de calendarización no encontrado."`; de otro paciente → 400,
  `services_plan_integral.py:185-186`). Respuesta:
  `{encabezado{clinica_nombre, paciente_nombre, paciente_edad, fecha}, secciones{8 textos},
  esquema[], planes_disponibles[], lab_results: [], gabinete_studies: [], equipo[]}`
  (`serializers.py:1815-1834`). **Las claves del encabezado son distintas a las del resumen
  clínico** (`clinica_nombre` vs `clinic_name`): son dos contratos separados y así está escrito
  (`services_plan_integral.py:101-104`).
- **POST** body: `treatment_plan_id` (opcional), las 8 secciones ≤10 000, `lab_results[]`
  (`{analyte_id?, name, unit, ref_low, ref_high, result}`) y `gabinete_studies[]`
  (`{name, conclusion}`) (`serializers.py:1876-1917`). `out_of_range` **nunca se acepta del
  cliente**: se calcula en el service (`services_plan_integral.py:190-206`). `equipo` **tampoco** se
  acepta: se snapshotea siempre del catálogo vigente (`services_plan_integral.py:460-465`).
- Respuesta 201/listado: `{id, created_at, doctor_name}` — sin texto clínico.
- Listado con paginación estándar (25/pág).

#### 4.2.11 Calendarización de tratamientos

Los 6 endpoints usan `TreatmentPlanPermission` (§1.3.2 #26 → **O A D** en GET/POST/PUT/DELETE) +
**`RequiresCalendarizacion`** (no `RequiresExpediente`).

| Método | Ruta | Vista:línea | Éxito |
|---|---|---|---|
| GET | `/api/v1/expediente/<patient_id>/calendarizaciones/` | `views_calendarizacion.py:139` | 200 paginado |
| POST | `/api/v1/expediente/<patient_id>/calendarizaciones/` | `views_calendarizacion.py:153` | 201 detalle |
| POST | `/api/v1/expediente/<patient_id>/calendarizaciones/desde-paquete/` | `views_calendarizacion.py:205` | 201 detalle |
| GET | `/api/v1/expediente/calendarizaciones/<plan_id>/` | `views_calendarizacion.py:244` | 200 detalle |
| PUT | `/api/v1/expediente/calendarizaciones/<plan_id>/` | `views_calendarizacion.py:253` | 200 detalle |
| DELETE | `/api/v1/expediente/calendarizaciones/<plan_id>/` | `views_calendarizacion.py:292` | 204 |
| GET | `/api/v1/expediente/calendarizaciones/<plan_id>/pdf/` | `views_calendarizacion.py:323` | 202 `{job_id, status}` |
| POST | `/api/v1/expediente/calendarizaciones/<plan_id>/cotizacion/` | `views_calendarizacion.py:360` | 201 `{quote_id, status, total}` |
| POST | `/api/v1/expediente/calendarizaciones/sesiones/<session_id>/agendar/` | `views_calendarizacion.py:420` | **200** sesión |
| DELETE | `/api/v1/expediente/calendarizaciones/sesiones/<session_id>/agendar/` | `views_calendarizacion.py:487` | **200** sesión |

- **POST/PUT** body (`serializers.py:1518`): `title` (≤200), `notes`, `status`
  (`borrador|activa|completada`), `doctor_id`, `consultorio_id`, `items[]`. Cada item:
  `{id?, concept_id?, description?, unit_price?, quantity (≥1), order, sessions?[]}`; cada sesión:
  `{id?, number (≥1), scheduled_date?, scheduled_time?, duration_minutes?, applied_date?, status?}`.
  `items` **admite lista vacía y tiene default `[]`** (`serializers.py:1539-1541`) → ver B-EXP-04.
- **PUT reconcilia por `id`**, no borra y recrea: lo que trae `id` existente se actualiza en sitio y
  conserva su `appointment`/`applied_date`; lo que ya no viene **se borra físicamente** y su cita se
  cancela antes (`services_calendarizacion.py:255-331`, `:595-605`) → B-EXP-03.
- **DELETE del esquema** sí es lógico: `deleted_at` (`services_calendarizacion.py:640-641`).
- **Cotización** — genera una cotización nueva en `finanzas` y reapunta `plan.quote`; la anterior no
  se borra ni cancela (`services_calendarizacion.py:719-729`). Sede: `resolve_write_sucursal` a
  partir de `X-Sucursal-Id` (§1.5.3), `views_calendarizacion.py:372-378`. Sin items → 400
  `"El plan no tiene tratamientos para cotizar."`.
- **Desde paquete** — body `{package_id}`. Copia las líneas del paquete con **nombre y precio
  vigentes** del concepto (no el precio del paquete) (`services_calendarizacion.py:800-808`).
  Paquete inexistente → 404; de otro tenant o desactivado → 400.
- **Agendar** — body: `scheduled_date`, `scheduled_time`, `starts_at`, `ends_at` (UTC),
  `duration_minutes` (≥1), `doctor_id` (requerido), `consultorio_id` (opcional). Toda la validación
  de disponibilidad y anti-empalme la hace `apps.agenda.services`; este módulo nunca la
  reimplementa (`services_calendarizacion.py:919-988`). Errores 400 propagados de agenda.
- **Detalle** (`TreatmentPlanOutputSerializer`, `serializers.py:1650`):
  `{id, patient_id, title, notes, status, doctor_id, doctor_name, consultorio_id, consultorio_name,
  quote_id, created_at, total, items[]}` — `total` como **string decimal**.
  **Listado** (`TreatmentPlanListItemSerializer`, `:1704`):
  `{id, title, status, status_display, created_at, doctor_name, total, sessions_count, applied_count}`,
  paginación estándar (25/pág).
- 404 posibles: `"Paciente no encontrado."`, `"Esquema de tratamientos no encontrado."`,
  `"Sesión de tratamiento no encontrada."`, `"Médico no encontrado en esta clínica."`,
  `"Consultorio no encontrado en esta clínica."`, `"Paquete de tratamientos no encontrado."`.

#### 4.2.12 Preguntas extra de historia clínica

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/preguntas-hc/` | `views_preguntas.py:48` | `MedicalHistoryQuestionPermission` (§1.3.2 #36) + `RequiresExpediente` | 200 array plano |
| POST | `/api/v1/expediente/preguntas-hc/` | `views_preguntas.py:56` | ídem (POST → O A) | 201 |
| PATCH | `/api/v1/expediente/preguntas-hc/<question_id>/` | `views_preguntas.py:96` | ídem (PATCH → O A) | 200 |
| DELETE | `/api/v1/expediente/preguntas-hc/<question_id>/` | `views_preguntas.py:125` | ídem (DELETE → O A) | 204 |

- **GET** — query param `include_inactive` (`true|1|yes`). Sin paginación.
- **POST/PATCH** body: `label` (≤255), `field_type`, `options[]`, `section` (≤100), `order` (≥0),
  `is_required`. `is_active` **no es campo del serializer** → mandarlo da 400 "Campo no permitido".
  Coherencia: `select` exige `options` no vacía; cualquier otro tipo exige `options` vacía
  (`serializers.py:1022-1032`, revalidado en `services.py:1235-1240`).
- **No hay GET de detalle**: `MedicalHistoryQuestionDetailApi` solo implementa `patch` y `delete`
  (`views_preguntas.py:86`) → cualquier GET a esa ruta responde **405**.
- **DELETE** — baja lógica (`is_active=False`), idempotente (`services.py:1393-1395`).

#### 4.2.13 Catálogos del plan integral (plantillas y analitos)

| Método | Ruta | Vista:línea | Permiso | Éxito |
|---|---|---|---|---|
| GET | `/api/v1/expediente/plantillas-documento/` | `views_catalogos.py:79` | `DocumentTemplatePermission` (§1.3.2 #28) + `RequiresExpediente` | 200 paginado |
| POST | `/api/v1/expediente/plantillas-documento/` | `views_catalogos.py:94` | ídem (POST → O A) | 201 |
| GET | `/api/v1/expediente/plantillas-documento/<template_id>/` | `views_catalogos.py:130` | ídem | 200 |
| PATCH | `/api/v1/expediente/plantillas-documento/<template_id>/` | `views_catalogos.py:136` | ídem (O A) | 200 |
| DELETE | `/api/v1/expediente/plantillas-documento/<template_id>/` | `views_catalogos.py:164` | ídem (O A) | 204 |
| GET | `/api/v1/expediente/analitos/` | `views_catalogos.py:184` | `LabAnalytePermission` (§1.3.2 #29) + `RequiresExpediente` | 200 paginado |
| POST | `/api/v1/expediente/analitos/` | `views_catalogos.py:196` | ídem (O A) | 201 |
| GET | `/api/v1/expediente/analitos/<analyte_id>/` | `views_catalogos.py:226` | ídem | 200 |
| PATCH | `/api/v1/expediente/analitos/<analyte_id>/` | `views_catalogos.py:232` | ídem (O A) | 200 |
| DELETE | `/api/v1/expediente/analitos/<analyte_id>/` | `views_catalogos.py:260` | ídem (O A) | 204 |

- **Plantillas** — query params del listado: `section` y `only_active` (default `true`).
  Body POST: `name` (≤160), `section` (choice de 6, `models.py:1509`), `body`, `is_active`.
- **Analitos** — query param `only_active` (default `true`). Body POST: `name` (≤160), `unit`
  (≤40), `ref_low`, `ref_high` (`Decimal(12,4)`), `is_active`. `ref_low > ref_high` → 400
  (`services_catalogos.py:194-197`).
- **PATCH** — cuerpo vacío → 400 `{"detail": "No se proporcionaron campos para actualizar."}`.
  `is_active` **sí se acepta en el PATCH** y la vista lo enruta a `activate`/`deactivate`, nunca al
  update genérico (`views_catalogos.py:150-158`, `:246-254`). ⚠ Los docstrings de
  `DocumentTemplatePatchSerializer` (`serializers.py:1975-1977`) y `LabAnalytePatchSerializer`
  (`:2029-2031`) dicen que `is_active` "NO se expone aquí"; el código sí lo declara. Gana el código.
- **DELETE** — baja lógica vía `deleted_at` (`services_catalogos.py:161-162`, `:309-310`).
- Ambos listados usan paginación estándar (25/pág, sin `page_size`).

#### 4.2.14 Resumen de paginación y filtros del módulo

| Endpoint | Paginación | Filtros |
|---|---|---|
| Alergias | **ninguna** (array plano) | `include_resolved` |
| Historia clínica | n/a (documento único) | — |
| Signos vitales | `page_size=50`, param admitido, tope 200 | — |
| Series de signos | ninguna (tope interno 730) | `since` |
| Evoluciones | `page_size=20`, param admitido, tope 100 | — |
| Diagnósticos | `page_size=20`, param admitido, tope 100 | `only_active` |
| Indicaciones de enfermería | ninguna (límite fijo 20) | — |
| Imágenes | ninguna (tope 20/nota) | — |
| Libro clínico | `page`/`page_size` propios (default 10, tope 50) | `modo`, `imagenes` (solo PDF) |
| Resúmenes, planes integrales, calendarizaciones, plantillas, analitos | estándar 25/pág, **sin** `page_size` | `section`, `only_active` (catálogos) |
| Preguntas de HC | ninguna | `include_inactive` |

---

### 4.3 Reglas de negocio verificadas en código

#### 4.3.1 Inmutabilidad clínica y autoría

| # | Regla | Dónde | Cómo se sostiene |
|---|---|---|---|
| 1 | **La nota de evolución nace bloqueada** | `models.py:587` + `models.py:611-614` | `is_locked` default `True` y `CheckConstraint(is_locked=True)` — **la base rechaza cualquier fila con `is_locked=False`** |
| 2 | **No se edita ni se borra una nota** | `urls.py:123-127`, `views.py:45-47` | No hay `patch`/`put`/`delete` en `EvolutionNoteListCreateApi` → 405. `EvolutionPermission` ni siquiera declara PATCH/PUT (`permissions.py:763-767`) |
| 3 | **Una sola nota por cita** | `models.py:603-607` | Constraint parcial + chequeo previo en el service (`services.py:722-723`) + captura del `IntegrityError` como 400 (`services.py:743-747`) |
| 4 | **La nota solo nace de una cita ATTENDED** | `services.py:682-686` | 400 `"La nota de evolución solo puede crearse sobre una cita con estado ATTENDED (atendida)."` |
| 5 | **El médico de la nota debe ser el de la cita** | `services.py:689-690` | 400 |
| 6 | **Regla del médico**: con `actor_role == "doctor"`, solo sobre **sus** citas | `services.py:699-709` | Compara `appointment.doctor.membership.user_id` con `user.pk`. Owner/admin sin restricción. Si el médico de la cita no tiene membresía válida → 400, no 500 (`:702-705`) |
| 7 | **Corrección solo por addendum** | `services.py:815-888` | `addendum_create` es append-only; no hay update ni delete de addenda |
| 8 | **El addendum NO valida autoría sobre la nota** | `services.py:849-865` | Cualquier owner/admin/doctor puede firmar un addendum sobre la nota de otro médico → B-EXP-01 |
| 9 | **Las tomas de signos son append-only** | `urls.py:111-115` | Solo GET y POST ruteados; el resto → 405 |
| 10 | **El resumen clínico aplica la regla del médico** | `services_resumen.py:405-415` | 400 `"Un médico solo puede generar el resumen clínico de sus propias consultas."` |
| 11 | **En calendarización, un médico solo cancela/mueve sus propias citas** | `services_calendarizacion.py:201-206` | 400 `"Como médico, solo puedes cancelar o mover tus propias citas."` |
| 12 | **Los diagnósticos no se editan**: solo se resuelven | `services.py:1030-1032` | No existe service ni endpoint de update |
| 13 | **Las alergias no se borran**: se resuelven | `services.py:209-211` | `is_active=False`; sin endpoint de reactivación |
| 14 | **Las imágenes de la nota firmada siguen siendo mutables** | `views_imagenes.py:128`, `:187` | Se pueden agregar y quitar indefinidamente después de firmar → B-EXP-07 |

**Fail-open declarado:** las tres funciones que aplican reglas por rol (`_validate_actor_role` de
calendarización `services_calendarizacion.py:84`, la de plan integral
`services_plan_integral.py:76`, y la regla del médico de `evolution_note_create` `services.py:699`)
usan el patrón `if actor_role and actor_role not in ...`. **Un `actor_role` vacío pasa siempre.** Es
deliberado para llamadas fuera de HTTP, y está escrito en los docstrings — pero significa que una
vista futura que olvide pasar `actor_role` desactiva la regla en silencio → B-EXP-12.

#### 4.3.2 Validación de los bloques JSON (`validators.py`)

Whitelist estricta de claves y tipos, con 400 al primer desconocido:

| Bloque | Claves | Reglas especiales | Línea |
|---|---|---|---|
| `heredo_familiares` | 16 strings + `numero_hermanos` | entero ≥ 0, `bool` rechazado explícitamente | `validators.py:244` |
| `personales_patologicos` | 25 strings | **no incluye alergias**: la fuente de verdad es el modelo `Allergy` | `:322` |
| `no_patologicos` | 8 strings + `casa_habitacion` | choice `propia|rentada|prestada|otro` | `:344` |
| `habitos_alimenticios` | 4 strings + `numero_comidas_dia` | entero ≥ 0 | `:412` |
| `gineco_obstetricos` | 19 strings | la validación por sexo la hace el serializer | `:492` |
| `exploracion_fisica_basal` | 18 sistemas × `{estado, detalle}` | estado ∈ `sin_alteraciones|con_alteraciones` | `:517` |
| `exploracion_fisica` (evolución) | los mismos 18 sistemas | estado ∈ `no_evaluado|normal|observacion|alterado` (semáforo de 4) | `:630` |

Tope anti-DoS: 2 000 caracteres por valor de string en cualquier bloque (`validators.py:77`), y
2 000 por `detalle` de sistema (`:612`, `:726`).

#### 4.3.3 Otras reglas verificadas

- **`custom_answers` se filtra a preguntas activas en cada guardado** (`services.py:360-367`): las
  respuestas a preguntas desactivadas **se pierden** en el siguiente PUT, aunque el modelo promete lo
  contrario (`models.py:886-889`) → B-EXP-02.
- **El upsert de HC usa `select_for_update()`** y captura `IntegrityError` como fallback de carrera
  (`services.py:332-334`, `:381-410`): dos PUT simultáneos nunca producen 500 ni dos filas.
- **El snapshot del esquema en el plan integral es independiente** del `TreatmentPlan`: se copia
  `[{description, quantity, clinical_description}]` al crear (`services_plan_integral.py:149-167`).
- **`out_of_range` de laboratorio se calcula, nunca se acepta**: si el resultado no es numérico
  ("Negativo", "Pendiente") devuelve `False` (`services_plan_integral.py:190-206`).
- **Los rangos de referencia se normalizan** para la constancia: `"70.0000"` → `"70"`
  (`services_plan_integral.py:209-224`).
- **La cotización desde calendarización delega el cálculo en `finanzas.quote_create`** — el módulo
  nunca reimplementa totales (`services_calendarizacion.py:719-727`).
- **`treatment_session_schedule` decide entre crear, reagendar o cancelar+crear** según haya cita y
  si el médico cambia; las 3 ramas van dentro de un `transaction.atomic()` para que un empalme no
  deje la sesión sin cita (`services_calendarizacion.py:950-1002`).
- **Multi-sede en calendarización**: la vista valida la sede **destino** con `resolve_write_sucursal`
  (`views_calendarizacion.py:450-463`) y el service valida la sede **origen** de la cita ya agendada
  con `allowed_sucursales` (`services_calendarizacion.py:942-948`, `:1061-1067`). Es el único punto
  de todo el expediente donde se aplica alcance por sede.

---

### 4.4 Matriz de permisos del módulo

Roles: **O** owner · **A** admin · **D** doctor · **N** nurse · **R** reception · **F** finance ·
**L** readonly. `✔` permitido · `✘` denegado (403) · **propio** = permitido solo sobre sus propios
registros. Todas las celdas suponen que la clínica tiene el módulo; si no, la respuesta es **404**
para cualquier rol (§1.4.2).

| Acción | Guard de módulo | O | A | D | N | R | F | L |
|---|---|---|---|---|---|---|---|---|
| Listar alergias | expediente | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Crear alergia | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ |
| Resolver alergia | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ |
| Leer historia clínica | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Guardar historia clínica (PUT) | expediente | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Leer signos vitales / series | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Registrar toma de signos | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ |
| Leer notas de evolución | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Crear nota de evolución | expediente | ✔ | ✔ | **propio** | ✘ | ✘ | ✘ | ✘ |
| Editar / borrar nota de evolución | — | ✘ (405) | ✘ (405) | ✘ (405) | ✘ (405) | ✘ (405) | ✘ (405) | ✘ (405) |
| Crear addendum | expediente | ✔ | ✔ | ✔ *(no acotado, B-EXP-01)* | ✘ | ✘ | ✘ | ✘ |
| Leer diagnósticos | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Crear / resolver diagnóstico | expediente | ✔ | ✔ | ✔ *(no acotado)* | ✘ | ✘ | ✘ | ✘ |
| Leer indicaciones de enfermería | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Listar imágenes de evolución | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Subir / borrar imagen | expediente | ✔ | ✔ | ✔ *(no acotado)* | ✘ | ✘ | ✘ | ✘ |
| Ver libro clínico (JSON) | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Pedir PDF del libro | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Borrador de resumen clínico | expediente | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Guardar resumen clínico | expediente | ✔ | ✔ | **propio** | ✘ | ✘ | ✘ | ✘ |
| Listar resúmenes / pedir su PDF | expediente | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Borrador de plan integral | expediente | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Crear / listar plan integral, pedir PDF | expediente | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Listar / ver calendarización, pedir PDF | **calendarizacion** | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Crear / reemplazar / borrar calendarización | **calendarizacion** | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Crear calendarización desde paquete | **calendarizacion** | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Generar cotización desde calendarización | **calendarizacion** | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Agendar / desagendar sesión | **calendarizacion** | ✔ | ✔ | **propio** | ✘ | ✘ | ✘ | ✘ |
| Leer preguntas extra de HC | expediente | ✔ | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ |
| Crear / editar / desactivar pregunta | expediente | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ |
| Leer plantillas de documento / analitos | expediente | ✔ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| Crear / editar / borrar plantilla o analito | expediente | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ |

Fuente de cada fila: `apps/core/permissions.py:675` (alergias), `:697` (HC), `:721` (signos), `:741`
(evolución e imágenes), `:770` (resumen), `:796` (calendarización), `:820` (plan integral), `:844`
(plantillas), `:862` (analitos), `:880` (addendum), `:897` (diagnóstico), `:915` (enfermería),
`:1032` (preguntas de HC).

**Notas de la matriz:**

1. `OPTIONS` pasa **siempre**, sin mirar rol (§1.3.1). Aplica a todas las filas.
2. `AllergyPermission` declara `PATCH` (`permissions.py:692`) pero **ninguna ruta lo usa** → celda
   inexistente en la práctica, entrada muerta de la política.
3. Las tres celdas **propio** son las únicas restricciones por objeto de toda la app. Todo lo demás
   que un rol puede escribir, lo puede escribir sobre **cualquier** paciente de la clínica.
4. **Ningún endpoint del expediente acota por sucursal** salvo agendar/desagendar sesión
   (§4.3.3) → B-EXP-09.

---

### 4.5 Efectos secundarios

#### 4.5.1 Bitácora (`audit_record`, §1.8.5)

| Acción | Dónde se emite | `resource_repr` |
|---|---|---|
| `ALLERGY_CREATE` | `services.py:164` | UUID de la alergia |
| `ALLERGY_RESOLVE` | `services.py:221` | UUID |
| `MEDICAL_HISTORY_READ` | `views_historia.py:112` (**en la vista**, en el GET) | UUID de la HC, `""` si aún no existe |
| `MEDICAL_HISTORY_UPDATE` | `services.py:442` | UUID. El PUT **no** emite `READ` a propósito (`services.py:273-278`) |
| `VITALSIGNS_READ` | `views_signos.py:99` (lista) y `:257` (series) | UUID del **paciente** |
| `VITALSIGNS_CREATE` | `services.py:579` | UUID de la toma |
| `EVOLUTION_READ` | `views_evoluciones.py:116` | UUID del paciente |
| `EVOLUTION_CREATE` | `services.py:758` | UUID de la nota |
| `ADDENDUM_CREATE` | `services.py:875` | UUID del addendum |
| `DIAGNOSIS_READ` | `views_evoluciones.py:355` | UUID del paciente |
| `DIAGNOSIS_CREATE` / `DIAGNOSIS_RESOLVE` | `services.py:979` / `:1041` | UUID |
| `EVOLUTION_IMAGE_ADD` / `EVOLUTION_IMAGE_REMOVE` | `services.py:1152` / `:1458` | UUID (**nunca el nombre del archivo**) |
| `MEDICAL_HISTORY_QUESTION_CREATE/UPDATE/DEACTIVATE` | `services.py:1260`, `:1352`, `:1403` | UUID |
| `PATIENT_BOOK_VIEW` / `PATIENT_BOOK_PDF` | `views_libro.py:85` / `:176` | **`patient.record_number`** (número de expediente, no-PII) |
| `CLINICAL_SUMMARY_CREATE` | `services_resumen.py:438` | UUID |
| `LONGEVITY_PLAN_CREATE` | `services_plan_integral.py:494` | UUID |
| `TREATMENT_PLAN_SAVE` | `services_calendarizacion.py:490`, `:615`, `:649`, `:738`, `:819` | UUID. **Un solo tipo de acción para crear, reemplazar, borrar, cotizar y crear-desde-paquete**; lo que distingue es `metadata` |
| `TREATMENT_SESSION_SCHEDULE` | `services_calendarizacion.py:1011` y `:1084` | UUID. También un solo tipo para agendar y desagendar (`metadata.unscheduled=True`) |
| `DOCUMENT_TEMPLATE_CREATE/UPDATE/DELETE` | `services_catalogos.py:74`, `:118`, `:133`, `:148`, `:163` | ⚠ **`template.name`, no UUID** |
| `LAB_ANALYTE_CREATE/UPDATE/DELETE` | `services_catalogos.py:226`, `:266`, `:281`, `:296`, `:311` | ⚠ **`analyte.name`, no UUID** |

- **Trade-off explícito de disponibilidad:** si `audit_record` devuelve `None`, las 6 vistas que
  auditan lecturas emiten `logger.critical` y **dejan pasar el acceso**; nunca devuelven 503
  (`views_historia.py:123-136`, `views_signos.py:108-118`, `views_evoluciones.py:125-134`,
  `views_libro.py:100-110`). Está escrito y razonado en el código: *disponibilidad clínica >
  registro estricto*.
- **Lecturas de expediente que NO auditan:** listado de alergias, listado de imágenes, indicaciones
  de enfermería, borrador y listado de resúmenes clínicos, borrador y listado de planes integrales,
  detalle y listado de calendarizaciones → B-EXP-05.
- Los dos catálogos rompen la regla de privacidad escrita en el propio módulo ("`resource_repr`
  SIEMPRE es el UUID", `services.py:29-38`). No es PII de paciente, pero es una desviación real.

#### 4.5.2 Notificaciones

Un solo disparador en toda la app: al crear una nota de evolución **con
`indicaciones_enfermeria` no vacía** se hace fanout `NURSING_INSTRUCTION` a los usuarios con rol
`nurse`, **filtrados por la sede de la cita** (`services.py:777-797`).

- Título y cuerpo genéricos, **sin PII**: la navegación va por `target_type=PATIENT` +
  `target_id` (`services.py:791-796`).
- Envuelto en `try/except Exception` best-effort: un fallo del fanout **no tumba** la creación de la
  nota, solo emite `logger.warning` (`services.py:798-805`).
- Si la cita no tiene sede (`sucursal_id` nulo), notifica a enfermería de **todas** las sedes
  (`services.py:783-787`).

#### 4.5.3 Celery

Cuatro tipos de PDF registrados en `ExpedienteConfig.ready()` (`apps.py:30-45`), cada uno con su
clase de permiso, que `PdfJobStatusApi`/`PdfJobFileApi` revalidan al descargar (§1.3.6):

| `kind` | Builder | Permiso registrado | Encolado desde | `cache_key` |
|---|---|---|---|---|
| `book` | `build_book_pdf` (`pdf_jobs.py:18`) | `EvolutionPermission` | `views_libro.py:202` | `""` (siempre fresco) |
| `resumen_clinico` | `build_resumen_clinico_pdf` (`pdf_jobs.py:47`) | `ClinicalSummaryPermission` | `views_resumen.py:177` | `""` |
| `treatment_plan` | `build_treatment_plan_pdf` (`pdf_jobs.py:65`) | `TreatmentPlanPermission` | `views_calendarizacion.py:335` | `""` |
| `plan_integral` | `build_longevity_plan_pdf` (`pdf_jobs.py:83`) | `LongevityPlanPermission` | `views_plan_integral.py:218` | `""` |

**Ninguno cachea**: los 4 pasan `cache_key=""`, así que cada pedido genera un PDF nuevo
(`apps/pdfs/services.py:24-25`). Para el libro clínico es correcto (dato mutable); para el resumen y
el plan integral es una decisión de simplicidad explícita, aunque el documento sea inmutable
(`views_resumen.py:158-160`).

El renderizado es WeasyPrint con `_secure_fetcher`: solo data-URIs, cero acceso a archivos o HTTP
desde la plantilla (`pdf.py:6-9`). Las imágenes se redimensionan a 180×200 pt y se descartan las de
más de 8 MB (`pdf.py:59-63`, `:102-109`).

#### 4.5.4 Escrituras en otras apps

| Desde | Qué escribe | Dónde |
|---|---|---|
| `quote_create_from_treatment_plan` | Una `finanzas.Quote` en borrador con sus items | `services_calendarizacion.py:720-727` |
| `treatment_session_schedule` | Crea o reagenda un `agenda.Appointment` | `services_calendarizacion.py:952-988` |
| `_cancel_session_appointment_if_any` | Cancela un `agenda.Appointment` (vía `appointment_change_status`) | `services_calendarizacion.py:211-216` |
| `treatment_plan_replace` | **Cancela citas** de las sesiones que desaparecen del payload | `services_calendarizacion.py:322-331`, `:595-605` |

Las tres primeras delegan por completo en los services de la app dueña (anti-empalme, totales,
máquina de estados); ninguna toca esas tablas directamente. La cuarta es la que convierte un PUT de
edición en una cancelación de agenda (B-EXP-04).
## 5. Recetas y generación de PDFs

> Extraído del código el 2026-08-12 (modo inverso). Alcance leído completo: `apps/recetas/`
> (`models.py`, `serializers.py`, `services.py`, `views.py`, `views_public.py`, `selectors.py`,
> `urls.py`, `pdf.py`, `tasks.py`, `verification.py`, `apps.py`, migraciones y
> `management/commands/seed_medicamentos.py`) y `apps/pdfs/` completo. Se consultaron como insumo
> `apps/core/permissions.py`, `apps/personal/selectors.py`, `apps/audit/models.py`,
> `config/settings/base.py`, `config/settings/production.py` y los puntos de encolado de PDF en
> `apps/expediente/` y `apps/finanzas/`.
>
> La capa transversal **no se repite**: se cita como §1.x del documento
> `docs/_a2-partes/00-transversal.md`.

---

### 5.1 Modelo de datos (recetas)

Siete tablas: seis en `apps/recetas`, una en `apps/pdfs`. Todas heredan `TenantAwareModel` (§1.8.2)
**salvo `GlobalMedication`**, que hereda `BaseModel` (§1.8.1).

| Tabla | Modelo | `tenant_id` | RLS | Por qué |
|---|---|---|---|---|
| `recetas_global_medications` | `GlobalMedication` (`models.py:129`) | **No** | **No** | Catálogo global de la plataforma, compartido por todas las clínicas. La migración lo declara y lo omite a propósito (`migrations/0002_rls_medication.py:10-18`) |
| `recetas_medications` | `Medication` (`models.py:261`) | Sí | Sí (`0002_rls_medication.py:43-49`) | Catálogo propio de la clínica |
| `recetas_prescriptions` | `Prescription` (`models.py:383`) | Sí | Sí (`0004_rls_prescription.py:34-40`) | Documento médico-legal de la clínica |
| `recetas_prescription_items` | `PrescriptionItem` (`models.py:595`) | Sí | Sí (`0004_rls_prescription.py:51-57`) | Renglón de la receta |
| `recetas_prescription_formats` | `PrescriptionFormat` (`models.py:838`) | Sí | Sí (`0007_rls_prescription_format.py`) | Configuración de impresión de la clínica |
| `recetas_prescription_pdf_jobs` | `PrescriptionPdfJob` (`models.py:1072`) | Sí | Sí (`0015_rls_prescription_pdf_job.py:29-35`) | Trabajo de PDF de una receta |
| `pdfs_pdf_jobs` | `PdfJob` (`apps/pdfs/models.py:15`) | Sí | Sí (`apps/pdfs/migrations/0002_rls_pdf_job.py:29-35`) | Trabajo de PDF genérico de cualquier módulo |

**Ninguna tabla de este módulo tiene campo `sucursal`.** Verificado: cero ocurrencias de "sucursal"
en `apps/recetas/` y en `apps/pdfs/`. Consecuencia documentada en 5.6 y en B-REC-13.

#### 5.1.1 `GlobalMedication` → `recetas_global_medications` (`models.py:129`)

| Campo | Tipo | Null | Default | Índice |
|---|---|---|---|---|
| `generic_name` | `CharField(200)` | no | — | `db_index` (`:161`) |
| `commercial_name` | `CharField(200)` | no (`blank`) | `""` | `db_index` (`:172`) |
| `form` | `CharField(20)` choices `MedicationForm` (16 valores, `:108`) | no | — | `db_index` (`:182`) |
| `concentration` | `CharField(100)` | no (`blank`) | `""` | no |
| `presentation` | `CharField(200)` | no (`blank`) | `""` | no |
| `is_active` | `BooleanField` | no | `True` | `db_index` (`:209`) |
| `kind` | `CharField(15)` choices `ItemKind` (`:49`): `medicamento`/`suero`/`terapia` | no | `medicamento` | `db_index` (`:221`) |
| `controlled_group` | `CharField(5)` choices `ControlledGroup` (`:62`): `none`,`I`..`V` | no | `none` | `db_index` (`:231`) |

`ordering = ["generic_name","form","concentration"]` (`:241`). Índices declarados:
`global_med_name_form_idx (generic_name, form)` y `global_med_commercial_idx (commercial_name)`
(`:242-251`). **Consulta que los justifica:** el autocompletado hace dos `ILIKE` sobre
`generic_name` y `commercial_name` (`selectors.py:93`). *(Nota: un índice B-tree no acelera
`icontains`, que genera `LIKE '%x%'`; el índice sirve para el `ORDER BY generic_name` de
`selectors.py:97`. Con ~500 filas la diferencia es irrelevante.)*

**Sin `UniqueConstraint`** a propósito (`:152-156`): la idempotencia del seed la da un
`get_or_create` por `(generic_name, concentration, form)` (`seed_medicamentos.py:487-491`).

Sin `on_delete` que documentar: no tiene FK. Al heredar solo `BaseModel`, usa el manager por
defecto de Django y **no excluye soft-deleted** (§1.8.1, B-T-04).

#### 5.1.2 `Medication` → `recetas_medications` (`models.py:261`)

Mismos campos que `GlobalMedication` (`:281-342`), más `tenant` (`PROTECT`) y `created_by`
(`SET_NULL`) de `TenantAwareModel` (§1.8.2). `commercial_name` aquí **no** lleva `db_index`
(`:289`), a diferencia del global.

`ordering = ["generic_name","form","concentration"]` (`:346`). Índices:
`medication_tenant_name_idx (tenant, generic_name)` y `medication_tenant_active_idx
(tenant, is_active)` (`:347-356`). **Consulta que los justifica:** `medication_search` filtra
`is_active=True` + `ILIKE` y ordena por `generic_name`, siempre bajo el `WHERE tenant_id = …` que
inyecta el `TenantManager` (`selectors.py:115-121`).

Baja: `is_active=False` (baja clínica) además del `deleted_at` del sistema (`:313-320`). **Ningún
endpoint la borra ni la desactiva**: solo existe POST de alta (ver 5.2).

#### 5.1.3 `Prescription` → `recetas_prescriptions` (`models.py:383`)

| Campo | Tipo | `on_delete` | Null | Default | Consecuencia real de la regla de borrado |
|---|---|---|---|---|---|
| `patient` | FK `pacientes.Patient`, `related_name="prescriptions"` | **PROTECT** (`:415`) | no | — | Un paciente con una sola receta **no se puede borrar en duro**. Es lo correcto: la receta es prueba médico-legal y perdería a quién se emitió |
| `doctor` | FK `personal.Doctor`, `related_name="prescriptions"` | **PROTECT** (`:422`) | no | — | Un médico que ya emitió recetas no se borra. El "borrado" real de un médico es `is_active=False` |
| `appointment` | FK `agenda.Appointment` | **SET_NULL** (`:429`) | sí | `NULL` | Borrar la cita deja la receta viva y huérfana de contexto. Es deliberado: la receta vale sin la cita |
| `evolution_note` | FK `expediente.EvolutionNote` | **SET_NULL** (`:438`) | sí | `NULL` | Igual que arriba |
| `cancelled_by` | FK `AUTH_USER_MODEL`, `related_name="+"` | **SET_NULL** (`:533`) | sí | `NULL` | Si se borra el usuario que anuló, la anulación sobrevive sin autor. El **motivo** (`cancellation_reason`) no se pierde |
| `folio` | `PositiveIntegerField` | — | no | — (lo calcula el service) | `db_index` (`:448`) |
| `issued_at` | `DateTimeField` | — | no | `timezone.now` (`:457`) | `db_index` |
| `diagnosis` | `CharField(500)` | — | no (`blank`) | `""` | Texto libre. **No** hay FK a `expediente.Diagnosis` (`:470`) |
| `recommendations` | `TextField(max_length=5000)` | — | no (`blank`) | `""` | `max_length` en `TextField` **solo valida en formularios/serializer**, no en Postgres |
| `vitals_snapshot` | `JSONField` | — | **sí** | `NULL` | Congela los signos (DR-7). Estructura en 5.4.4 |
| `controlled_folio` | `CharField(60)` | — | no (`blank`) | `""` | Folio del recetario COFEPRIS, capturado a mano |
| `valid_until` | `DateTimeField` | — | **sí** | `NULL` | Vigencia; `NULL` = receta no controlada |
| `status` | `CharField(10)` choices `PrescriptionStatus` (`:371`): `active`/`cancelled` | — | no | `active` | `db_index` (`:523`) |
| `cancelled_at` | `DateTimeField` | — | sí | `NULL` | |
| `cancellation_reason` | `CharField(500)` | — | no (`blank`) | `""` | |

- **Constraint:** `UniqueConstraint(tenant, folio)` = `prescription_tenant_folio_uniq` (`:549-554`).
  Es la red de seguridad del consecutivo: dos folios iguales en la misma clínica revientan en la BD.
- **Índices** (`:555-568`), cada uno con su consulta:
  | Índice | Consulta que lo justifica |
  |---|---|
  | `rx_tenant_patient_issued_idx (tenant, patient, issued_at)` | `prescription_list` → `filter(patient=…).order_by("-issued_at")` (`selectors.py:403-404`), el historial que se abre en el expediente |
  | `rx_tenant_doctor_issued_idx (tenant, doctor, issued_at)` | **Ninguna consulta del código la usa hoy.** No hay listado por médico. Es peso muerto en cada INSERT hasta que exista ese reporte |
  | `rx_tenant_status_idx (tenant, status)` | **Ninguna consulta del código filtra por `status`**: el historial devuelve activas y anuladas juntas (`selectors.py:368`) |
- `ordering = ["-issued_at"]` (`:548`).
- **No hay `CheckConstraint` de inmutabilidad**, y el modelo lo dice (`:394`). La inmutabilidad es de
  aplicación (ver 5.4).
- `is_controlled` es una **property**, no una columna (`:570-581`): recorre `self.items.all()`. Sin
  `prefetch_related("items")` dispara una query extra por receta.

#### 5.1.4 `PrescriptionItem` → `recetas_prescription_items` (`models.py:595`)

| Campo | Tipo | `on_delete` | Null | Default |
|---|---|---|---|---|
| `prescription` | FK `Prescription`, `related_name="items"` | **CASCADE** (`:616`) | no | — |
| `order` | `PositiveSmallIntegerField` | — | no | `1` |
| `kind` | `CharField(15)` choices `ItemKind` | — | no | `medicamento`, `db_index` (`:631`) |
| `medication_name` | `CharField(200)` | — | no | — (**requerido**) |
| `medication_commercial_name` | `CharField(200)` | — | no (`blank`) | `""` |
| `medication_presentation` | `CharField(200)` | — | no (`blank`) | `""` |
| `medication_form` | `CharField(20)` **sin choices** (`:664`) | — | no (`blank`) | `""` |
| `medication_concentration` | `CharField(100)` | — | no (`blank`) | `""` |
| `global_medication` | FK `GlobalMedication` | **SET_NULL** (`:680`) | sí | `NULL` |
| `medication` | FK `Medication` | **SET_NULL** (`:691`) | sí | `NULL` |
| `dose` / `frequency` / `duration` | `CharField(120)` | — | no (`blank`) | `""` |
| `route` | `CharField(15)` choices `RouteOfAdministration` (14 valores, `:85`) | — | no (`blank`) | `""` |
| `indication` | `TextField` | — | no (`blank`) | `""` |
| `quantity` | `CharField(50)` | — | no (`blank`) | `""` |
| `controlled_group` | `CharField(5)` choices `ControlledGroup` | — | no | `none`, `db_index` (`:768`) |

**El `CASCADE` del ítem es seguro precisamente porque la receta nunca se borra** (DR-5, `:609-611`):
en la práctica los ítems son permanentes. El **`SET_NULL` de las dos FK de catálogo es la pieza
clave del diseño**: si la clínica da de baja un medicamento custom, la receta ya emitida conserva
`medication_name`, `medication_concentration`, etc. como texto congelado y solo pierde la
trazabilidad al catálogo (`:598-604`). El snapshot de texto es la fuente de verdad, no la FK.

Índice: `rx_item_prescription_order_idx (prescription, order)` (`:779-784`) — consulta que lo
justifica: `prescription.items.all().order_by("order")` al armar el PDF (`pdf.py:402`).
`ordering = ["prescription","order"]` (`:778`).

#### 5.1.5 `PrescriptionFormat` → `recetas_prescription_formats` (`models.py:838`)

| Campo | Tipo | `on_delete` | Null | Default |
|---|---|---|---|---|
| `name` | `CharField(120)` | — | no | — |
| `base_layout` | `CharField(10)` choices `compact`/`digital` (`:873`) | — | no | `digital`, `db_index` |
| `accent_color` | `CharField(7)` | — | no | `#9A7B1E` |
| `font` | `CharField(10)` choices `helvetica`/`times` (`:877`) | — | no | `helvetica` |
| `theme` | `CharField(12)` choices `ondas`/`minimal`/`barra`/`geometrico` (`:885`) | — | no | `ondas` |
| `sections` | `JSONField` | — | no (`blank`) | `{}` |
| `letterhead_mode` | `CharField(12)` choices `digital`/`preprinted` (`:881`) | — | no | `digital` |
| `is_default` | `BooleanField` | — | no | `False`, `db_index` |
| `doctor` | FK `personal.Doctor` | **SET_NULL** (`:958`) | sí | `NULL` |
| `is_authorized` | `BooleanField` | — | no | `False`, `db_index` |
| `is_active` | `BooleanField` | — | no | `True`, `db_index` |

`SET_NULL` en `doctor`: si se borra el médico, su formato personal sobrevive y pasa a comportarse
como un formato más del tenant (deja de aplicarse automáticamente porque la resolución busca por
`doctor_id`, `selectors.py:254-268`).

- Índices (`:988-997`): `pf_tenant_default_active_idx (tenant, is_default, is_active)` — consulta:
  la resolución del formato por defecto (`selectors.py:270-278`); `pf_tenant_doctor_auth_idx
  (tenant, doctor, is_authorized)` — consulta: la resolución del formato del médico
  (`selectors.py:256-266`). Los dos están justificados y se ejecutan **en cada generación de PDF**.
- **No hay constraint de "un solo default por tenant"**: lo sostiene el service, que desmarca el
  anterior dentro de la misma transacción (`services.py:932-938`, `services.py:1037-1042`). Dos
  defaults simultáneos son posibles si alguien escribe por fuera del service; la resolución toma el
  primero (`selectors.py:277`, `.first()` sin `order_by` determinista).
- `sections`: whitelist de 10 claves (`SECTIONS_KEYS`, `:801`); `edad_sexo` y `contacto_clinica` son
  **obligatorias por ley y no se pueden apagar** (`REQUIRED_SECTIONS`, `:835`). Defensa en tres
  capas: serializer (`serializers.py:788-794`), service (`services.py:1216-1222`) y modelo
  (`models.py:1021-1034`), más un cuarto refuerzo al renderizar (`get_sections_full()`, `:1045-1046`).

#### 5.1.6 `PrescriptionPdfJob` → `recetas_prescription_pdf_jobs` (`models.py:1072`)

| Campo | Tipo | `on_delete` | Null | Default |
|---|---|---|---|---|
| `prescription` | FK `Prescription`, `related_name="pdf_jobs"` | **CASCADE** (`:1095`) | no | — |
| `cache_key` | `CharField(200)` | — | no | — (`f"{prescription_id}|{format_id}|{layout}"`, `services.py:1238`) |
| `layout` | `CharField(40)` | — | no (`blank`) | `""` |
| `format_id` | `CharField(64)` | — | no (`blank`) | `""` |
| `status` | `CharField(12)` choices `pending`/`processing`/`done`/`failed` (`:1087`) | — | no | `pending`, `db_index` |
| `file` | `FileField(max_length=255)` → `tenants/<tenant_id>/recetas/pdf/<uuid>.pdf` (`:1067-1069`) | — | **sí** | `NULL` |
| `error` | `TextField` | — | no (`blank`) | `""` |

Constraint `UniqueConstraint(tenant, cache_key)` = `prescription_pdf_job_cache_uniq` (`:1125-1130`):
un solo job por salida. Índice `presc_pdf_job_presc_idx (tenant, prescription)` (`:1131-1136`) —
**ninguna consulta del código lista los jobs de una receta**; el acceso es siempre por `id`
(`selectors.py:415`) o por `(tenant, cache_key)` (`services.py:1265`). Índice sin uso hoy.

El nombre del archivo en el storage es un **UUID aleatorio distinto del `id` del job**
(`models.py:1069`) y va bajo `tenants/<tenant_id>/`, así que la ruta física no es derivable del
job_id.

#### 5.1.7 `PdfJob` → `pdfs_pdf_jobs` (`apps/pdfs/models.py:15`)

Igual que el anterior pero **genérico**: sin FK al recurso.

| Campo | Tipo | Null | Default |
|---|---|---|---|
| `kind` | `CharField(40)` | no | — (`db_index`, `:40`) |
| `cache_key` | `CharField(200)` | no (`blank`) | `""` |
| `params` | `JSONField` | no | `{}` |
| `filename` | `CharField(200)` | no (`blank`) | `""` |
| `status` | `CharField(12)` choices | no | `pending` (`db_index`) |
| `file` | `FileField(255)` → `tenants/<tenant_id>/pdfs/<kind>/<uuid>.pdf` (`:10-12`) | sí | `NULL` |
| `error` | `TextField` | no (`blank`) | `""` |

Constraint **parcial**: `UniqueConstraint(tenant, kind, cache_key)` con
`condition=~Q(cache_key="")` (`:65-73`). Es la diferencia de diseño con el job de recetas: aquí
`cache_key=""` significa "no cachear, cada pedido genera un PDF nuevo", y por eso los jobs sin
caché no chocan entre sí. Índice `pdf_job_kind_status_idx (tenant, kind, status)` (`:74-79`) —
**ninguna consulta lo usa**: el acceso es por `id` (`apps/pdfs/selectors.py:11`) o por la tupla de
caché (`services.py:30-33`). Peso muerto hoy.

---

### 5.2 Endpoints autenticados

Convenciones generales (prefijo `/api/v1/`, auth Bearer, formatos de error, throttling): §1.7.
Todas las vistas de `apps/recetas` heredan de `TenantAPIView` y llevan **el mismo trío**:
`[IsAuthenticated, <Permiso>, RequiresRecetas]`. El guard de módulo responde **404**, no 403
(§1.4.2). Las de `apps/pdfs` heredan `TenantAPIView` pero **no llevan guard de módulo** (ver 5.7.3).

Ninguna de estas rutas lee `X-Sucursal-Id`.

| # | Método | Ruta | Vista:línea | Permiso (§1.3) | Módulo | Éxito | Errores |
|---|---|---|---|---|---|---|---|
| 1 | GET | `/api/v1/recetas/medicamentos/buscar/` | `views.py:94` | `MedicationPermission` (§1.3.2 #34) | `RequiresRecetas` | 200 array | 401, 403, 404 (módulo) |
| 2 | POST | `/api/v1/recetas/medicamentos/` | `views.py:136` | `MedicationPermission` | `RequiresRecetas` | 201 | 400, 401, 403, 404 |
| 3 | GET | `/api/v1/expediente/<uuid:patient_id>/recetas/` | `views.py:201` | `PrescriptionPermission` (§1.3.2 #33) | `RequiresRecetas` | 200 paginado | 401, 403, 404 |
| 4 | POST | `/api/v1/expediente/<uuid:patient_id>/recetas/` | `views.py:247` | `PrescriptionPermission` | `RequiresRecetas` | 201 | 400, 401, 403, 404 |
| 5 | GET | `/api/v1/recetas/<uuid:prescription_id>/` | `views.py:315` | `PrescriptionPermission` | `RequiresRecetas` | 200 | 401, 403, 404 |
| 6 | POST | `/api/v1/recetas/<uuid:prescription_id>/anular/` | `views.py:489` | `PrescriptionPermission` | `RequiresRecetas` | 200 | 400, 401, 403, 404 |
| 7 | GET | `/api/v1/recetas/<uuid:prescription_id>/pdf/` | `views.py:376` | `PrescriptionPermission` | `RequiresRecetas` | **202** | 401, 403, 404 |
| 8 | GET | `/api/v1/recetas/pdf-job/<uuid:job_id>/` | `views.py:427` | `PrescriptionPermission` | `RequiresRecetas` | 200 | 401, 403, 404 |
| 9 | GET | `/api/v1/recetas/pdf-job/<uuid:job_id>/file/` | `views.py:456` | `PrescriptionPermission` | `RequiresRecetas` | 200 `application/pdf` | 404, **409**, 401, 403 |
| 10 | GET | `/api/v1/recetas/formatos/` | `views.py:556` | `PrescriptionFormatPermission` (§1.3.2 #35) | `RequiresRecetas` | 200 **array sin paginar** | 401, 403, 404 |
| 11 | POST | `/api/v1/recetas/formatos/` | `views.py:562` | `PrescriptionFormatPermission` | `RequiresRecetas` | 201 | 400, 401, 403, 404 |
| 12 | GET | `/api/v1/recetas/formatos/<uuid:format_id>/` | `views.py:619` | `PrescriptionFormatPermission` | `RequiresRecetas` | 200 | 401, 403, 404 |
| 13 | PATCH | `/api/v1/recetas/formatos/<uuid:format_id>/` | `views.py:635` | `PrescriptionFormatPermission` | `RequiresRecetas` | 200 | 400, 401, 403, 404 |
| 14 | DELETE | `/api/v1/recetas/formatos/<uuid:format_id>/` | `views.py:681` | `PrescriptionFormatPermission` | `RequiresRecetas` | **204** | 400, 401, 403, 404 |
| 15 | GET | `/api/v1/pdfs/job/<uuid:job_id>/` | `apps/pdfs/views.py:54` | `IsAuthenticated` + permiso del `kind` | **ninguno** | 200 | 401, 404 |
| 16 | GET | `/api/v1/pdfs/job/<uuid:job_id>/file/` | `apps/pdfs/views.py:87` | `IsAuthenticated` + permiso del `kind` | **ninguno** | 200 `application/pdf` | 404, 409, 401 |

Métodos no ruteados en cada vista → **405** (así se sostiene la inmutabilidad, §1.7.2). En
particular: **no existe PATCH ni PUT sobre `/api/v1/recetas/<id>/`**, ni DELETE, ni ninguna ruta
sobre `PrescriptionItem`.

#### 5.2.1 `GET /api/v1/recetas/medicamentos/buscar/`

- **Query params** (`views.py:118-131`):
  | Param | Tipo | Default | Regla |
  |---|---|---|---|
  | `q` | string | `""` | Se hace `strip()` y se **trunca a 200 caracteres** (`selectors.py:44`, `:84`). Vacío → `[]` sin tocar la BD (`selectors.py:85-86`) |
  | `limit` | int | `25` (`SEARCH_LIMIT`, `selectors.py:39`) | Se acota entre 1 y 50 (`views.py:124`); si no parsea, vuelve a 25 (`views.py:125-126`) |
  | `kind` | `medicamento`\|`suero`\|`terapia` | `None` (todos) | **Sin validar contra choices**: un `kind` inventado filtra a cero resultados, no da 400 (`views.py:129`, `selectors.py:95-96`) |
- **Sin paginación.** Devuelve array plano.
- **Respuesta 200** (`MedicationSearchOutputSerializer`, `serializers.py:80`), por elemento:

```json
{
  "id": "uuid-como-string",
  "generic_name": "Amoxicilina",
  "commercial_name": "Amoxil",
  "form": "capsula",
  "concentration": "500 mg",
  "presentation": "Caja con 12 cápsulas",
  "source": "global",
  "kind": "medicamento",
  "controlled_group": "none"
}
```

- `source` = `"global"` (catálogo Maily) o `"custom"` (de la clínica) (`selectors.py:107`, `:131`).
- **Unión en Python, no en SQL** (`selectors.py:139-143`), decisión escrita en `selectors.py:69-73`.
  Efecto colateral real: cada lado se corta a `limit` **antes** de unir y ordenar alfabéticamente, y
  el resultado se vuelve a cortar a `limit` → los medicamentos custom de la clínica pueden
  desaparecer del autocompletado (B-REC-14).
- **No se audita** a propósito (`views.py:107-113`): buscar en el catálogo no es acceso al
  expediente.

#### 5.2.2 `POST /api/v1/recetas/medicamentos/`

- **Entrada** (`MedicationCreateInputSerializer`, `serializers.py:100`): `generic_name` (≤200,
  requerido, no puede ser solo espacios `:150-157`), `form` (choices `MedicationForm`, requerido),
  `commercial_name` (≤200, opc.), `concentration` (≤100, opc.), `presentation` (≤200, opc.),
  `kind` (choices, default `medicamento`).
  **No acepta `controlled_group`** ni `is_active` (`:110-111`).
- **Reglas del service `medication_create`** (`services.py:147`): tenant no nulo (`:188`),
  `generic_name` no vacío tras `strip` (`:191-193`), `form` y `kind` contra choices (`:195-207`).
  **No hay control de duplicados**: dos medicamentos idénticos se pueden crear.
- **Éxito:** 201 con `{id, generic_name, commercial_name, form, concentration, presentation, kind,
  controlled_group, is_active, created_at}` (`serializers.py:160`).
- **Errores:** 400 forma de serializer para campos mal formados; 400 `{"detail": "<string>"}` desde
  el service (`views.py:166-170`).
- Bitácora: `MEDICATION_CREATE` con `resource_repr = str(med.id)` — nunca el nombre
  (`services.py:225-234`).

#### 5.2.3 `GET /api/v1/expediente/<patient_id>/recetas/`

- **Anti-IDOR:** `patient_get` usa `TenantManager`; paciente de otro tenant → **404**
  `{"detail": "Paciente no encontrado."}` (`views.py:204-209`).
- **Paginación propia**, distinta de la estándar de §1.7.1: `_PrescriptionPagination`
  (`views.py:82`) con `page_size=20`, **`page_size` sí admitido como query param**, tope 100
  (`:89-91`). Respuesta `{count, next, previous, results}`.
- **Filtros: ninguno.** No hay filtro por estado, por fecha ni por médico. El historial devuelve
  activas y anuladas juntas, orden `-issued_at` (`selectors.py:368`, `:404`).
- **Respuesta 200** (`PrescriptionListOutputSerializer`, `serializers.py:675`), por elemento:

```json
{
  "id": "uuid", "folio": 27, "issued_at": "2026-08-12T10:15:00-06:00",
  "status": "active", "diagnosis": "Faringitis aguda", "recommendations": "…",
  "doctor": {"id":"uuid","full_name":"María Pérez","cedula_profesional":"1234567",
             "specialty":"Medicina interna","cedulas_validadas":["1234567","7654321"]},
  "items_count": 3,
  "cancelled_at": null, "cancellation_reason": "",
  "controlled_folio": "", "valid_until": null
}
```

  `cedulas_validadas` solo trae credenciales con `validation_status="validada"` e `is_active=True`
  (`serializers.py:649-672`, precargadas en `selectors.py:383-387`). `items_count` usa `len()` sobre
  el prefetch para no disparar N+1 (`serializers.py:697-704`).
- **Bitácora:** `PRESCRIPTION_READ` con `resource_id=None` y `resource_repr="patient_uuid=<uuid>"`
  (`views.py:216-224`). Si el INSERT de bitácora falla, se escribe un `logger.critical` y **el
  acceso continúa** (`views.py:225-233`): disponibilidad clínica sobre registro estricto.
- 500 defensivo `{"detail": "Paginación no disponible."}` si el paginador devolviera `None`
  (`views.py:242-245`) — inalcanzable con `PageNumberPagination`.

#### 5.2.4 `POST /api/v1/expediente/<patient_id>/recetas/` — emitir receta

- **Entrada** (`PrescriptionCreateInputSerializer`, `serializers.py:483`):

```json
{
  "items": [ { "kind":"medicamento", "medication_name":"Amoxicilina",
               "medication_commercial_name":"", "dose":"1 cápsula",
               "frequency":"cada 8 horas", "route":"oral", "duration":"7 días",
               "indication":"", "medication_presentation":"", "medication_form":"",
               "medication_concentration":"500 mg", "quantity":"21 cápsulas",
               "global_medication_id":null, "medication_id":null } ],
  "diagnosis": "", "recommendations": "", "appointment_id": null,
  "evolution_note_id": null, "controlled_folio": "",
  "vitals": {"weight_kg":72.5,"height_m":1.70,"heart_rate":78,"resp_rate":16,
             "systolic":120,"diastolic":80,"temperature_c":36.5,
             "oxygen_saturation":98,"glucose":95}
}
```

  - `items`: **mínimo 1, máximo 20** (`serializers.py:496-501`, límite anti-DoS M-3).
  - `diagnosis` ≤500 opcional; `recommendations` ≤5000 opcional; `indication` de cada ítem ≤2000.
  - **No se acepta `doctor_id`** (sale del perfil activo) ni `patient_id` (viene de la URL)
    (`serializers.py:491-492`).
  - **Whitelist estricta en tres niveles**: raíz, cada ítem y `vitals` (`serializers.py:564-603`).
    Un campo no declarado devuelve 400 `{"campo": ["Campo no permitido."]}`. **`controlled_group`
    no está declarado en el ítem** → enviarlo es 400 (raíz de B-REC-01).
  - `vitals`: rangos fisiológicos duros (`serializers.py:339-349`), idénticos a los de expediente.
- **Validación condicional COFEPRIS** (`serializers.py:316-331` y otra vez en
  `services.py:267-283`): si `kind == "medicamento"`, son obligatorios `dose`, `frequency`, `route`
  y `duration`. Para `suero` y `terapia`, opcionales.
- **Reglas del service `prescription_create`** (`services.py:420`), en este orden:
  1. El actor **debe tener perfil `Doctor` activo en el tenant** → si no, `PermissionDenied` = **403**
     (`services.py:508-513`). Un `owner` sin perfil médico pasa el permiso HTTP y **falla aquí**.
  2. El médico debe tener `cedula_profesional` no vacía → 400 (`services.py:519-524`).
  3. Paciente del tenant → 400 "Paciente no encontrado en esta clínica." (`services.py:527-534`).
  4. Paciente no fallecido → 400 (`services.py:537-540`).
  5. Paciente con `date_of_birth` **y** `sex` → 400 con la lista de lo que falta
     (`services.py:545-556`). Es la NOM-004: un paciente provisional creado desde la agenda no
     puede recibir receta.
  6. Ítems válidos (`services.py:559`).
  7. `appointment_id`, si viene: del tenant **y del mismo paciente** → 400 (`services.py:562-575`).
  8. `evolution_note_id`, si viene: mismas dos reglas → 400 (`services.py:578-595`).
  9. Folio consecutivo (5.4.1).
  10. Snapshot de signos (5.4.4).
  11. Resolución de `controlled_group` por ítem y, si la receta resulta controlada,
      `controlled_folio` obligatorio → 400 (`services.py:629-634`).
- **Éxito:** **201** con `PrescriptionDetailOutputSerializer` completo — la vista vuelve a leer con
  `prescription_get` para traer relaciones (`views.py:292-297`).
- **Errores:** 400 forma de serializer; 400 `{"detail": "<string>"}` desde el service
  (`views.py:281-289`); **403** `{"detail": "Solo un médico puede emitir recetas…"}` cuando falta el
  perfil Doctor; 404 si el paciente no es del tenant.

#### 5.2.5 `GET /api/v1/recetas/<prescription_id>/` — detalle

- **Anti-IDOR:** `prescription_get` usa `TenantManager` → receta de otro tenant = 404
  `{"detail": "Receta no encontrada."}` (`views.py:319-325`, `selectors.py:192-204`).
- **Respuesta 200** (`PrescriptionDetailOutputSerializer`, `serializers.py:707`): todo lo del
  listado más `vitals_snapshot`, `patient_id`, `appointment_id`, `evolution_note_id`, `items[]`
  completos, `cancelled_by_id`, `created_at`, `is_controlled`.
  Cada ítem (`serializers.py:606`): `id, order, kind, medication_name,
  medication_commercial_name, medication_presentation, medication_form,
  medication_concentration, dose, frequency, route, duration, indication, quantity,
  global_medication_id, medication_id, controlled_group`.
- **Este es el endpoint del flujo "copiar de previa"** (`views.py:306-307`): el front lo lee y
  prellena el formulario de la receta nueva.
- Bitácora: `PRESCRIPTION_READ` con `resource_repr="folio=<n>"` (`views.py:328-336`). Aquí **no** se
  vigila el fallo de bitácora (a diferencia del listado).

#### 5.2.6 `POST /api/v1/recetas/<prescription_id>/anular/`

- **Entrada:** `{"reason": "<string ≤500, no vacío>"}` (`serializers.py:738`).
- **Reglas** (`prescription_cancel`, `services.py:747`): receta del tenant (`:783`); **no anulada ya**
  → 400 "La receta ya fue anulada." (`:787-788`); motivo no vacío → 400 (`:791-793`);
  **autorización**: `owner`/`admin` siempre; cualquier otro rol debe ser el **médico emisor**
  (`doctor.id == prescription.doctor_id`) o `PermissionDenied` = 403 (`:796-809`).
- **Éxito:** 200 con el detalle completo actualizado.
- **Errores:** 400 (`{"detail": "<string>"}`), 403, 404.
- Bitácora `PRESCRIPTION_CANCEL` con folio y `doctor_id` (`services.py:822-835`).

#### 5.2.7 `GET /api/v1/recetas/<prescription_id>/pdf/` — encolar

- **Query params** (`views.py:401-404`): `formato` = `compact`\|`digital` (cualquier otro valor se
  ignora silenciosamente, `:402-403`); `format_id` = UUID de un `PrescriptionFormat` (si no existe,
  fallback silencioso a la resolución normal, `selectors.py:327-334`).
- **Respuesta 202**: `{"job_id": "<uuid>", "status": "pending|processing|done"}` (`views.py:412-415`).
  Nunca devuelve el PDF directamente. **Si el PDF ya está en caché, llega `"done"` de una vez.**
- Bitácora `PRESCRIPTION_PDF` **al solicitar**, no al descargar (`views.py:390-398`).

#### 5.2.8 `GET /api/v1/recetas/pdf-job/<job_id>/` y `.../file/`

- Estado: `{"status": "pending|processing|done|failed"}`; si `failed` añade
  `{"detail": "No se pudo generar el PDF. Intenta de nuevo."}` — **el `error` interno del job nunca
  sale al cliente** (`views.py:439-442`).
- Descarga: 200 `application/pdf` con `Content-Disposition: inline;
  filename="receta-<folio>.pdf"`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`
  (`views.py:468-474`). Si el job no está `done` → **409** con cuerpo de **texto plano**
  `El PDF aun no esta listo.`; si no existe → 404 texto plano
  `Trabajo de PDF no encontrado.` (`views.py:463-466`). Son las dos únicas respuestas del módulo que
  no son JSON.
- El renderer `PdfRenderer` (`views.py:344`) existe solo para que `Accept: application/pdf` no dé
  406.
- **La descarga no se audita.**

#### 5.2.9 Formatos de receta (`/api/v1/recetas/formatos/`)

- **GET lista:** array plano sin paginar, solo `is_active=True`, orden `-is_default, name`
  (`selectors.py:243-245`). Visible para **todos los roles** (§1.3.2 #35).
- **POST crear** (`PrescriptionFormatCreateInputSerializer`, `serializers.py:798`): `name` (≤120, no
  vacío), `base_layout`, `theme`, `accent_color` (regex `#RRGGBB`, `:818-823`), `font`, `sections`
  (whitelist, `SectionsField:763`), `letterhead_mode`, `is_default`, `doctor_id`.
  **`is_authorized` no está declarado** → enviarlo da 400 "Campo no permitido" (`:826`), lo que hace
  inalcanzable el `data.pop("is_authorized")` de la vista (`views.py:576-577`). El service siempre
  crea con `is_authorized=False` (`services.py:952`).
  Si `is_default=True`, desmarca el default anterior en la misma transacción (`services.py:932-938`).
- **PATCH** (`PrescriptionFormatUpdateInputSerializer`, `serializers.py:830`): todos opcionales,
  incluye `is_authorized`. Cuerpo vacío → 400 "No se enviaron campos para actualizar."
  (`views.py:650-654`). El service rechaza campos inmutables (`id, tenant, tenant_id, created_at,
  updated_at, deleted_at, is_active`, `services.py:853-855`) y exige `is_admin` para tocar
  `is_authorized` (`services.py:1022-1025`). **No valida propiedad del formato** → B-REC-02.
- **DELETE:** baja lógica (`is_active=False`, `is_default=False`, `deleted_at=now`,
  `services.py:1132-1135`) → **204 sin cuerpo**. Si ya estaba inactivo → 400.
- Bitácora `FORMAT_CREATE` / `FORMAT_UPDATE` / `FORMAT_DELETE` (`services.py:957`, `:1079`, `:1138`).

---

### 5.3 Endpoint público de verificación

**Es el único endpoint sin sesión de todo el sistema** (§1.3.6). Vive aparte a propósito, en
`apps/recetas/views_public.py`, para no heredar nada de `TenantAPIView`.

```
GET /api/v1/verificar-receta/<uuid:prescription_id>/?sig=<token>
```

`urls.py:106-110` · vista `PrescriptionVerifyApi` (`views_public.py:54`).

#### 5.3.1 Postura de seguridad declarada en el código

| Control | Valor | Referencia |
|---|---|---|
| `permission_classes` | `[AllowAny]` | `views_public.py:81` |
| `authentication_classes` | **`[]`** — ni siquiera intenta leer el Bearer | `views_public.py:82` |
| `throttle_classes` | `[PrescriptionVerifyThrottle]`, `AnonRateThrottle` con scope `prescription_verify` | `views_public.py:44-51` |
| Cuota | **30 req/min**, configurable con `DRF_THROTTLE_VERIFY` | `config/settings/base.py:231` |
| Guard de módulo | **ninguno** | no aparece en `views_public.py` |
| Filtro de tenant | **ninguno**: `Prescription.all_objects` | `views_public.py:102` |
| Bitácora | `PRESCRIPTION_VERIFY` con `actor=None`, folio y estado; **no** registra IP ni el `sig` | `views_public.py:149-172` |

Es **cross-tenant por diseño** y está escrito así (`views_public.py:22-26`): cualquier farmacia
escanea el QR de cualquier clínica. La única autorización es la firma HMAC. Como la vista no es
`TenantAPIView`, **nunca se fija el GUC** `app.current_tenant_id`, así que la policy de RLS cae en
su rama `IS NULL` y no filtra nada (§1.1.1) — aquí eso es lo buscado, no un descuido.

#### 5.3.2 Cómo se firma y cómo se valida el QR

`apps/recetas/verification.py`:

```
token = HMAC-SHA256( key = PRESCRIPTION_VERIFY_SECRET,
                     msg = str(prescription.id) ).hexdigest()[:32]
url   = {PRESCRIPTION_VERIFY_BASE_URL}/verificar-receta/{id}?sig={token}
```
(`verification.py:66-68`, `:111-116`)

- **32 caracteres hex = 128 bits** (`_TOKEN_HEX_LEN`, `:45`). Adivinar uno es inviable.
- El mensaje firmado es **solo el UUID de la receta**: el token **no caduca, no se puede revocar y
  no está ligado al estado de la receta**. Quien fotografió el QR una vez lo puede consultar para
  siempre (B-REC-03).
- La clave sale de `settings.PRESCRIPTION_VERIFY_SECRET` y **cae a `SECRET_KEY` si está vacía**
  (`verification.py:50`, `config/settings/base.py:540`). `production.py` **no la exige** (verificado:
  no aparece en el archivo) → B-REC-03.
- Validación en tiempo constante con `hmac.compare_digest` (`verification.py:90`); cualquier
  excepción devuelve `False` (`:91-97`) — **fail-closed**.
- El QR se genera al construir el PDF (`pdf.py:535-537`) como PNG base64 con la librería `qrcode`;
  si falla, el PDF sale sin QR y solo se loguea (`verification.py:156-162`).
- La URL del QR apunta al **frontend** (`PRESCRIPTION_VERIFY_BASE_URL`, default
  `http://localhost:5173`), que a su vez llama a este endpoint.

#### 5.3.3 Orden de ejecución — anti-enumeración

1. Lee `sig` del query string (`views_public.py:89`).
2. **Valida la firma ANTES de tocar la base de datos** (`views_public.py:93-94`). Firma mala →
   **404 sin cuerpo**, sin una sola query. No se revela si el UUID existe.
3. Solo entonces busca la receta con `all_objects` (`views_public.py:102-110`). No existe → **404**,
   idéntico al anterior.

Firma inválida y receta inexistente son **indistinguibles** (`views_public.py:16-20`).

#### 5.3.4 Qué sale al público exactamente

`PrescriptionVerifyOutputSerializer` (`serializers.py:884`), respuesta **200**:

```json
{
  "folio": 27,
  "estado": "vigente",
  "fecha_emision": "2026-08-12",
  "medico": {"nombre": "María Pérez López", "cedula_profesional": "1234567"},
  "clinica": "Clínica Bienestar Centro",
  "controlado": false,
  "vigencia": null
}
```

| Campo | Origen | Nota |
|---|---|---|
| `folio` | `prescription.folio` | consecutivo por clínica: **revela el volumen de recetas** de esa clínica |
| `estado` | `"anulada"` si `status == cancelled`, si no `"vigente"` (`views_public.py:115-119`) | **no** contempla `valid_until` vencido: una receta expirada sigue diciendo "vigente" |
| `fecha_emision` | `issued_at.date()` (`views_public.py:187`) | solo fecha, sin hora |
| `medico.nombre` | `doctor.full_name`; si falla, el **UUID del doctor** (`views_public.py:123-127`) | dato personal del médico |
| `medico.cedula_profesional` | campo legacy del `Doctor`, **no** las credenciales validadas (`views_public.py:129`) | puede quedar vacío aunque el PDF sí imprima cédulas |
| `clinica` | `ClinicSettings.commercial_name`, si no `tenant.name` (`views_public.py:131-145`) | |
| `controlado` | `valid_until is not None or controlled_folio != ""` (`views_public.py:179-182`) | **inferido**, no consultado a los ítems |
| `vigencia` | `valid_until` ISO-8601 o `null` | |

**Datos del paciente que salen: ninguno.** Verificado campo por campo: no hay nombre, ni fecha de
nacimiento, ni sexo, ni diagnóstico, ni medicamentos, ni signos vitales, ni `controlled_folio`
(excluido a propósito, `views_public.py:178`). La política está escrita en `views_public.py:9-14`.

**Lo que sí es PII y sí sale:** el nombre completo del médico y su cédula profesional, más el nombre
comercial de la clínica. Es información profesional pública en México, pero permite a quien tenga un
QR confirmar que ese médico trabaja en esa clínica.

#### 5.3.5 Rate limiting: existe, y es evadible

El throttle de 30/min es un `AnonRateThrottle`, que identifica al cliente con `get_ident()`. Con
`NUM_PROXIES` **sin configurar** (verificado: no aparece en `config/settings/`), DRF usa el
contenido crudo de `X-Forwarded-For` como clave de cuota. Un cliente que rote esa cabecera se salta
el límite. No es explotable para enumerar (128 bits de firma lo impiden), pero **el control
anti-scraping declarado no funciona como está escrito** → B-REC-04. Es la misma raíz que el riesgo 3
de `docs/01-analisis.md:337-339`.

---

### 5.4 Reglas de inmutabilidad y folios

#### 5.4.1 Folio consecutivo por clínica

```python
max_folio_result = (
    Prescription.all_objects.select_for_update()
    .filter(tenant=tenant)
    .aggregate(max_folio=Max("folio"))
)
next_folio = (max_folio_result["max_folio"] or 0) + 1
```
(`services.py:601-606`)

- Corre dentro de `@transaction.atomic` (`services.py:419`). El `SELECT … FOR UPDATE` bloquea las
  filas de recetas del tenant, así que dos emisiones simultáneas se serializan; el lock se libera en
  el COMMIT (`services.py:597-600`).
- Arranca en **1** por clínica.
- Red de seguridad en la BD: `UniqueConstraint(tenant, folio)` (`models.py:549-554`).
- Usa `all_objects` a propósito: si usara `objects`, una receta soft-deleted (que no existe hoy)
  quedaría fuera del `MAX` y se reutilizaría su folio.
- **El folio nunca se reutiliza tras una anulación**: anular no toca `folio` (`services.py:816-818`).
  Un hueco en la numeración es imposible; una receta anulada conserva su número.

#### 5.4.2 Qué se puede cambiar después de crear

Solo cuatro campos, y solo por `prescription_cancel`:

```python
prescription.save(update_fields=["status","cancelled_at","cancelled_by",
                                 "cancellation_reason","updated_at"])
```
(`services.py:816-818`)

| Regla | Cómo se sostiene | Referencia |
|---|---|---|
| No hay PATCH/PUT de receta | La vista solo implementa `get` → cualquier otro método es **405** | `views.py:300-341` |
| No hay DELETE de receta | Idem | `views.py:300-341` |
| No hay endpoint de ítems | `urls.py` no rutea nada bajo `PrescriptionItem` | `urls.py:43-111` |
| No hay borrado físico | Ningún `.delete()` sobre `Prescription` o `PrescriptionItem` en toda la app | verificado en `services.py`, `views.py`, `selectors.py` |
| La corrección es anulación + receta nueva | Documentado en el modelo y aplicado por el service | `models.py:386-388`, `services.py:787-788` |
| **No hay `CheckConstraint`** que impida un UPDATE por SQL | Declarado explícitamente: "La BD no tiene CheckConstraint de inmutabilidad (es de aplicación)" | `models.py:394` |

La inmutabilidad es **de aplicación, no de base de datos**. Un `UPDATE` desde `psql`, desde el admin
de Django (no hay `admin.py` en esta app, verificado) o desde una tarea Celery mal escrita no
encuentra ninguna barrera.

#### 5.4.3 Anulación con motivo

- El motivo es obligatorio en dos capas: serializer (`serializers.py:744-755`) y service
  (`services.py:791-793`).
- Se guarda quién anuló (`cancelled_by`) y cuándo (`cancelled_at`).
- Anular dos veces → 400 (`services.py:787-788`).
- **El PDF ya cacheado no refleja la anulación** (B-REC-12): el contexto calcula
  `cancelled = status == CANCELLED` **al renderizar** (`pdf.py:446`), pero un job en estado `done`
  se reusa sin regenerar (`services.py:1281`).

#### 5.4.4 Snapshot de signos vitales (DR-7)

`_build_vitals_snapshot` (`services.py:286`), precedencia:

1. Si el body trae `vitals` con **al menos un valor no nulo** → se usa ese dict, se calcula el `imc`
   a partir de peso y talla, y `measured_at` = `issued_at` de la receta; `source = "prescription"`
   (`services.py:300-331`).
2. Si no → última toma de enfermería vía `vital_signs_latest` del expediente;
   `source = "nursing"` (`services.py:333-360`).
3. Si el paciente no tiene ninguna toma → `vitals_snapshot = NULL`.

Claves del JSON: `weight_kg, height_m, imc, heart_rate, resp_rate, systolic, diastolic,
temperature_c, oxygen_saturation, glucose, measured_at, source`.

Congela: cambios posteriores en el expediente **no** alteran la receta (`models.py:401-405`).

#### 5.4.5 Snapshot del medicamento

Cada `PrescriptionItem` copia `medication_name`, `medication_commercial_name`,
`medication_presentation`, `medication_form`, `medication_concentration` y `controlled_group` como
texto al crear (`services.py:672-697`). Las FK `global_medication` y `medication` son **solo
trazabilidad** y son `SET_NULL`. Ejemplo concreto: si la clínica corrige la concentración de un
medicamento custom de "500 mg" a "250 mg", las recetas ya emitidas siguen diciendo 500 mg — que es
lo que el paciente tiene en la mano.

---

### 5.5 Medicamentos y controlados

#### 5.5.1 Catálogo doble

| Origen | Modelo | Quién escribe | Quién lee |
|---|---|---|---|
| Global (Maily) | `GlobalMedication` | **Solo el management command** `seed_medicamentos` (`seed_medicamentos.py:487`). No hay endpoint de escritura, no hay `admin.py` | Todas las clínicas |
| Custom (clínica) | `Medication` | `POST /api/v1/recetas/medicamentos/` (owner/admin/doctor) | Solo su clínica (RLS + `TenantManager`) |
| Texto libre | — | El médico escribe `medication_name` sin tocar ningún catálogo | — |

`seed_medicamentos` es idempotente por `(generic_name, concentration, form)`, acepta `--dry-run` y
**no actualiza** entradas existentes (`seed_medicamentos.py:454-500`).

#### 5.5.2 Reglas extra de un medicamento controlado (F6)

Cuando **algún ítem resuelto** tiene `controlled_group != "none"`:

| Regla | Efecto | Referencia |
|---|---|---|
| `controlled_folio` obligatorio | 400 con mensaje explícito si falta. El folio del recetario especial lo emite COFEPRIS **fuera del sistema** y lo teclea el médico | `services.py:629-634` |
| Vigencia automática | `valid_until = issued_at + horas` según el **grupo más restrictivo** presente | `services.py:637-640`, `:123-141` |
| Tabla de vigencias | Grupo I → **24 h**; Grupos II–V → **720 h (30 días)**. Override por `settings.CONTROLLED_VALIDITY_HOURS` (no definido hoy en `config/settings/`) | `services.py:75-81`, `:94-104` |
| Orden de restrictividad | I > II > III > IV > V | `services.py:85-91`, `:107-120` |
| Bitácora reforzada | `PRESCRIPTION_CONTROLLED_CREATE` en vez de `PRESCRIPTION_CREATE`, con `controlled_group_top` en el metadata | `services.py:702-728` |
| Aviso en el PDF | `is_controlled`, `controlled_group_top`, `controlled_folio` y `valid_until` van al contexto del template | `pdf.py:542-568`, `:628-631` |
| QR público | `controlado: true` y `vigencia` con la fecha | `views_public.py:179-195` |

#### 5.5.3 De dónde sale `controlled_group` — y por qué hoy no sale de ningún lado

`_resolve_item_controlled_groups` (`services.py:363`) resuelve por ítem con esta prioridad:

1. `global_medication_id` → lee `GlobalMedication.controlled_group` (`services.py:386-391`).
2. `medication_id` → lee `Medication.controlled_group` del tenant; si no existe, **400**
   (`services.py:394-403`).
3. Valor explícito `controlled_group` en el ítem (`services.py:405-407`).
4. `none`.

El problema, verificado en los tres puntos de escritura:

- **Camino 1 muerto:** `seed_medicamentos` crea las 300+ entradas globales **sin** pasar
  `controlled_group` en `defaults` (`seed_medicamentos.py:491-495`) → todas quedan en `none`. El
  catálogo incluye Clonazepam, Alprazolam, Diazepam, Lorazepam y Zolpidem
  (`seed_medicamentos.py:296-316`).
- **Camino 2 muerto:** `MedicationCreateInputSerializer` no declara `controlled_group`
  (`serializers.py:100-148`) y `medication_create` no acepta el parámetro
  (`services.py:147-157`) → todo medicamento custom nace en `none`.
- **Camino 3 muerto:** `PrescriptionItemInputSerializer` tampoco declara `controlled_group`
  (`serializers.py:180-297`) y la whitelist de ítems rechaza claves no declaradas
  (`serializers.py:583-587`) → mandarlo desde la API es 400.

Resultado: **no existe ninguna ruta HTTP ni de siembra que produzca un `controlled_group` distinto
de `none`.** Todo el bloque F6 es código correcto y hoy inalcanzable. Los tests que lo cubren llaman
al **service** directo, saltándose el serializer (`tests/test_f6_controlled.py:92-102`). → B-REC-01.

---

### 5.6 Matriz de permisos del módulo

Roles: **O** owner · **A** admin · **D** doctor · **N** nurse · **R** reception · **F** finance ·
**L** readonly (§1.6.1). Leyenda: **Sí** = permitido · **No** = 403 · **Propios** = permitido solo
sobre sus propios registros. Toda celda "Sí"/"Propios" además exige que la clínica tenga el módulo
`recetas`; si no, **404** (§1.4.2).

| Acción | Endpoint | O | A | D | N | R | F | L |
|---|---|---|---|---|---|---|---|---|
| Buscar medicamentos | GET `/recetas/medicamentos/buscar/` | Sí | Sí | Sí | Sí | **No** | **No** | Sí |
| Crear medicamento custom | POST `/recetas/medicamentos/` | Sí | Sí | Sí | **No** | **No** | **No** | **No** |
| Ver historial de recetas | GET `/expediente/<id>/recetas/` | Sí | Sí | Sí | Sí | **No** | **No** | Sí |
| Emitir receta | POST `/expediente/<id>/recetas/` | **Solo con perfil Doctor activo** | **Solo con perfil Doctor activo** | Sí | **No** | **No** | **No** | **No** |
| Ver detalle de receta | GET `/recetas/<id>/` | Sí | Sí | Sí | Sí | **No** | **No** | Sí |
| Anular receta | POST `/recetas/<id>/anular/` | Sí (cualquiera) | Sí (cualquiera) | **Propios** (solo las que emitió) | **No** | **No** | **No** | **No** |
| Pedir PDF de receta | GET `/recetas/<id>/pdf/` | Sí | Sí | Sí | Sí | **No** | **No** | Sí |
| Consultar estado del job | GET `/recetas/pdf-job/<id>/` | Sí | Sí | Sí | Sí | **No** | **No** | Sí |
| Descargar PDF de receta | GET `/recetas/pdf-job/<id>/file/` | Sí | Sí | Sí | Sí | **No** | **No** | Sí |
| Listar formatos | GET `/recetas/formatos/` | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Ver formato | GET `/recetas/formatos/<id>/` | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Crear formato | POST `/recetas/formatos/` | Sí | Sí | Sí (**y a nombre de otro médico**) | **No** | **No** | **No** | **No** |
| Editar formato | PATCH `/recetas/formatos/<id>/` | Sí | Sí | Sí (**cualquiera del tenant, no solo el suyo**) | **No** | **No** | **No** | **No** |
| Autorizar formato (`is_authorized`) | PATCH `/recetas/formatos/<id>/` | Sí | Sí | **No** (400 del service) | **No** | **No** | **No** | **No** |
| Dar de baja formato | DELETE `/recetas/formatos/<id>/` | Sí | Sí | **No** | **No** | **No** | **No** | **No** |
| Estado de PDF genérico | GET `/pdfs/job/<id>/` | Según el permiso del `kind` | | | | | | |
| Descargar PDF genérico | GET `/pdfs/job/<id>/file/` | Según el permiso del `kind` | | | | | | |
| Verificar receta por QR | GET `/verificar-receta/<id>/` | **Público, sin sesión, sin rol, cross-tenant** | | | | | | |

Desglose de las dos últimas filas de PDF genérico, por `kind` registrado:

| `kind` | Permiso registrado | O | A | D | N | R | F | L |
|---|---|---|---|---|---|---|---|---|
| `book` (libro clínico) | `EvolutionPermission` (§1.3.2 #24) | Sí | Sí | Sí | Sí | No | No | Sí |
| `resumen_clinico` | `ClinicalSummaryPermission` (#25) | Sí | Sí | Sí | No | No | No | No |
| `treatment_plan` | `TreatmentPlanPermission` (#26) | Sí | Sí | Sí | No | No | No | No |
| `plan_integral` | `LongevityPlanPermission` (#27) | Sí | Sí | Sí | No | No | No | No |
| `quote` (cotización) | `QuotePermission` (#12) | Sí | Sí | Sí | No | Sí | No | Sí |
| `finance_report` | `FinanceDashboardPermission` (#9) | Sí | Sí | No | No | No | Sí | Sí |

**Dos ausencias que hay que leer como decisiones, no como olvidos:**

1. **Recepción y Finanzas no ven recetas en ninguna forma.** Es la decisión DR-6, escrita en
   `apps/core/permissions.py:965-970` y confirmada en `docs/01-analisis.md:283`.
2. **No hay ninguna celda "solo su sede".** El módulo no conoce sucursales (5.1). Un `admin` acotado
   a la sede Norte lee, imprime y **anula** recetas emitidas en Centro → B-REC-13.

Y una asimetría deliberada: `owner` y `admin` **pueden** anular cualquier receta pero **no pueden
emitir** ninguna si no tienen perfil de `Doctor` activo (`services.py:508-513`).

---

### 5.7 Generación asíncrona de PDFs (`apps/pdfs`)

#### 5.7.1 Dos mecanismos paralelos, no uno

| | Recetas | Todo lo demás |
|---|---|---|
| Modelo | `recetas.PrescriptionPdfJob` (`models.py:1072`) | `pdfs.PdfJob` (`apps/pdfs/models.py:15`) |
| Tarea | `apps.recetas.tasks.generate_prescription_pdf` (`tasks.py:38`) | `apps.pdfs.tasks.generate_pdf` (`apps/pdfs/tasks.py:37`) |
| Encolar | `prescription_pdf_job_enqueue` (`services.py:1241`) | `pdf_job_enqueue` (`apps/pdfs/services.py:11`) |
| Estado | `GET /api/v1/recetas/pdf-job/<id>/` | `GET /api/v1/pdfs/job/<id>/` |
| Descarga | `GET /api/v1/recetas/pdf-job/<id>/file/` | `GET /api/v1/pdfs/job/<id>/file/` |
| Guard de módulo | `RequiresRecetas` | **ninguno** (B-REC-07) |
| Registry | no participa | `register_pdf_kind` |

`apps/pdfs` se describe a sí misma como "un solo `PdfJob` + una tarea + endpoints de estado/descarga
sirven a TODOS los PDFs" (`apps/pdfs/__init__.py:3-5`), pero recetas nunca migró → B-REC-06.

#### 5.7.2 Los 7 tipos de documento — confirmados

`docs/01-analisis.md:245` dice "PDFs asíncronos con Celery (7 tipos de documento)". **Confirmado**,
con la salvedad de que solo 6 pasan por el registry:

| # | Documento | `kind` | Builder registrado en | Encolado en | `cache_key` |
|---|---|---|---|---|---|
| 1 | Libro clínico | `book` | `apps/expediente/apps.py:30` | `apps/expediente/views_libro.py:202` | `""` (mutable) |
| 2 | Resumen clínico | `resumen_clinico` | `apps/expediente/apps.py:31-35` | `apps/expediente/views_resumen.py:177` | `""` |
| 3 | Esquema de tratamientos | `treatment_plan` | `apps/expediente/apps.py:36-40` | `apps/expediente/views_calendarizacion.py:335` | `""` |
| 4 | Plan integral de longevidad | `plan_integral` | `apps/expediente/apps.py:41-45` | `apps/expediente/views_plan_integral.py:218` | `""` |
| 5 | Cotización | `quote` | `apps/finanzas/apps.py:28-30` | `apps/finanzas/views.py:733` | `""` |
| 6 | Reporte financiero | `finance_report` | `apps/finanzas/apps.py:31-35` | `apps/finanzas/views.py:1252` | `""` |
| 7 | **Receta** | — (fuera del registry) | — | `apps/recetas/views.py:406` | `"<rx_id>\|<format_id>\|<layout>"` |

**Ninguno de los 6 genéricos usa caché hoy** (`cache_key=""` en los seis puntos de encolado): cada
pedido regenera. La receta es el único caso cacheado, y es coherente con su inmutabilidad… salvo por
la anulación (B-REC-12).

#### 5.7.3 Ciclo de vida completo del job

```
pending ──(worker toma la tarea)──> processing ──(éxito)──> done
   │                                     │
   │                                     └──(excepción)──> failed
   └──(re-pedido del usuario)──> se re-encola, sigue pending
failed ──(re-pedido)──> se limpia (status=pending, error="", file=None) y se re-encola
done ──(re-pedido)──> se REUSA, no se regenera
```

1. **Encolar** (`apps/pdfs/services.py:11` / `recetas/services.py:1241`):
   - Con `cache_key`: `get_or_create` por `(tenant, kind, cache_key)`.
   - Sin `cache_key`: siempre crea fila nueva (`apps/pdfs/services.py:41-50`).
   - `needs_enqueue = job.status != DONE` (`:56`): **se re-encola siempre que no esté listo**, para
     recuperar mensajes perdidos por un worker caído (razón escrita en `:52-55`).
   - Un job `failed` se limpia antes de re-encolar (`:58-63`).
   - La tarea se dispara con `transaction.on_commit` (`:65-66`) para que el worker vea la fila ya
     comprometida.
2. **Worker** (`apps/pdfs/tasks.py:37`):
   - Carga el job con `all_objects` (sin contexto de tenant, `:46`).
   - Si ya está `done` → `"skipped:done"`, idempotencia ante at-least-once (`:51-52`).
   - **Fija el thread-local de tenant** con `set_current_tenant(job.tenant)` +
     `set_tenant_context_active(True)` (`:56-57`) para que los selectors del builder y RLS resuelvan
     el tenant correcto. **Nota:** fija el thread-local pero **no** llama `apply_tenant_guc`, así que
     la barrera activa es la de Django, no la de Postgres (§1.1.1).
   - `status = processing` (`:59-60`), despacha por `kind` al builder del registry (`:62-63`),
     guarda el archivo y pasa a `done` (`:65-74`).
   - Cualquier excepción → `failed` con `error = str(exc)[:1000]` y `logger.error` (`:76-87`).
     **No reintenta**: la decisión y su razón están en `apps/pdfs/tasks.py:16-18`.
   - `finally`: `clear_current_tenant()` + `set_tenant_context_active(False)` (`:88-90`).
   - La versión de recetas es idéntica (`recetas/tasks.py:50-110`) más la resolución del formato
     (`:78-82`).
3. **Polling:** el front consulta el estado "cada ~2 s" (`apps/pdfs/views.py:48-49`).
4. **Descarga:** solo si `status == done` **y** hay archivo; si no, **409**
   (`apps/pdfs/views.py:96-97`).

#### 5.7.4 Quién puede descargar un PDF ajeno

Tres capas, en este orden:

1. **Tenant:** `pdf_job_get` usa el `TenantManager` → un job de otra clínica es `DoesNotExist` →
   **404** (`apps/pdfs/selectors.py:8-11`).
2. **Rol:** `_kind_permission_ok` instancia el permiso registrado para el `kind` del job y le pide
   `has_permission(request, view)`; si falla → **404, no 403**, para no revelar que el job existe
   (`apps/pdfs/views.py:36-42`, `:63-68`, `:93-94`). Es el patrón que §1.3.6 documenta.
3. **Recurso concreto: no hay tercera capa.**

Consecuencia real, en términos del proyecto: cualquier usuario con rol `nurse` de la misma clínica
que consiga un `job_id` de tipo `book` puede descargar el **libro clínico completo** de un paciente
que nunca atendió; y una `admin` acotada a la sede Norte puede descargar el `finance_report` de la
sede Centro, porque el permiso del `kind` es por rol y no conoce sucursales → B-REC-09.

**La URL de descarga no es adivinable**: el path lleva el UUIDv4 del job (`urls.py:8-12`), 122 bits
de entropía, y solo se obtiene del endpoint de encolado, que sí verifica permiso, módulo y
propiedad del recurso. El archivo en el storage lleva **otro** UUID aleatorio bajo
`tenants/<tenant_id>/…` (`apps/pdfs/models.py:10-12`, `recetas/models.py:1067-1069`), así que
conocer el job_id no da la ruta física. **Pero** si el backend de storage sirve URLs públicas
—Cloudinary es el backend del piloto (`config/settings/base.py:348-354`, `production.py:100-102`)—
esos objetos quedan accesibles por enlace directo sin pasar por Django. La guardia
`AWS_S3_CUSTOM_DOMAIN` de `production.py:116-125` cubre S3/CloudFront, **no** Cloudinary. **NO
VERIFICADO**: no puedo confirmar desde el código con qué modo de entrega está configurado Cloudinary
en Railway; hay que revisarlo en la consola del proveedor.

#### 5.7.5 Qué pasa si el worker de Celery está caído

| Escenario | Qué ocurre hoy |
|---|---|
| **Worker caído, broker (Redis) vivo** | El `.delay()` encola sin error; la vista responde **202** con `status: "pending"`. El job se queda en `pending` **para siempre**. El front hace polling indefinido: no hay timeout, ni TTL, ni estado `expired` (verificado: no existe ninguna tarea de limpieza ni `CELERY_BEAT_SCHEDULE` que toque `PdfJob`). El usuario ve un spinner eterno |
| **Broker caído** | No hay `ATOMIC_REQUESTS` (verificado: no aparece en `config/settings/`) y ninguna vista de PDF envuelve la llamada en `transaction.atomic`, así que `transaction.on_commit` ejecuta el callback **de inmediato, dentro del request**. `.delay()` lanza la excepción de kombu sin capturar → **500 al usuario**, con la fila del job ya creada en estado `pending` (`apps/pdfs/services.py:65-66`, `recetas/services.py:1290-1291`) → B-REC-11 |
| **El usuario reintenta** | Cada nuevo pedido re-encola el mismo job si no está `done` (`apps/pdfs/services.py:56`), así que en cuanto el worker vuelve, el siguiente clic lo resuelve. Es la mitigación deliberada y funciona |
| **El worker muere a mitad del render** | El job queda en `processing`. Como `needs_enqueue` es `status != DONE`, un re-pedido lo vuelve a encolar y la tarea lo reprocesa (no está protegido contra dos workers procesando el mismo job a la vez; con 1–3 usuarios concurrentes es teórico) |
| **WeasyPrint falla** | `failed` + mensaje genérico al cliente; el `error` real solo va al log (`apps/pdfs/views.py:71-72`) |

#### 5.7.6 Seguridad del render

`prescription_pdf_build` (`pdf.py:635`) pasa a WeasyPrint un `url_fetcher` propio, `_secure_fetcher`
(`pdf.py:129`), que **solo admite `data:` URIs** y lanza `ValueError` ante `file://`, `http://`,
`https://` o rutas relativas (`pdf.py:150-163`). Es la defensa contra LFI y SSRF desde el HTML del
template: sin ella, una plantilla o un dato de la clínica con `<img src="file:///etc/passwd">`
filtraría archivos del contenedor al PDF. Todas las imágenes (logo, sello, credenciales, QR) se
incrustan en base64 **antes** del render (`pdf.py:169-204`, `:99-126`).

`base_url=None` en la llamada (`pdf.py:696`) elimina la resolución de rutas relativas.

---

### 5.8 Efectos secundarios

#### 5.8.1 Bitácora (`audit_record`, §1.8.5)

| Acción | Cuándo | `resource_repr` | Metadata | Referencia |
|---|---|---|---|---|
| `MEDICATION_CREATE` | Alta de medicamento custom | `str(med.id)` | — | `services.py:225-234` |
| `PRESCRIPTION_READ` | GET del historial | `patient_uuid=<uuid>` | `{patient_id}` | `views.py:216-224` |
| `PRESCRIPTION_READ` | GET del detalle | `folio=<n>` | `{folio}` | `views.py:328-336` |
| `PRESCRIPTION_CREATE` | Emisión no controlada | `folio=<n>` | `{folio, doctor_id, items_count, controlled:false}` | `services.py:712-728` |
| `PRESCRIPTION_CONTROLLED_CREATE` | Emisión controlada | `folio=<n>` | `+ {controlled_group_top}` | `services.py:702-728` |
| `PRESCRIPTION_CANCEL` | Anulación | `folio=<n>` | `{folio, doctor_id}` | `services.py:822-835` |
| `PRESCRIPTION_PDF` | **Solicitud** del PDF | `folio=<n>` | `{folio}` | `views.py:390-398` |
| `PRESCRIPTION_VERIFY` | Consulta pública por QR | `folio=<n>` | `{folio, estado}`, `actor=None` | `views_public.py:153-164` |
| `FORMAT_CREATE` / `FORMAT_UPDATE` / `FORMAT_DELETE` | CRUD de formatos | `format=<uuid>` | nombre/campos cambiados | `services.py:957`, `:1079`, `:1138` |

Los tipos están declarados en `apps/audit/models.py:122-197`.

- **Regla de privacidad respetada:** ningún `resource_repr` lleva nombre de paciente ni de
  medicamento; el folio es un número (`services.py:32-35`).
- **Lo que NO se audita:** la **descarga** del PDF (solo la solicitud) → B-REC-08; la búsqueda de
  medicamentos (exclusión deliberada, `views.py:107-113`); y la consulta de estado de un job.
- Solo el listado de recetas vigila el fallo de bitácora con `logger.critical` (`views.py:225-233`);
  el resto confía en el `absorbe-todo` de `audit_record`.

#### 5.8.2 Tareas Celery

| Tarea | Disparada por | Reintentos |
|---|---|---|
| `apps.recetas.tasks.generate_prescription_pdf` | `prescription_pdf_job_enqueue` vía `transaction.on_commit` (`services.py:1290-1291`) | **Ninguno** (`tasks.py:16-18`) |
| `apps.pdfs.tasks.generate_pdf` | `pdf_job_enqueue` vía `transaction.on_commit` (`apps/pdfs/services.py:65-66`) | **Ninguno** (`apps/pdfs/tasks.py:16-18`) |

Ninguna tarea periódica de `CELERY_BEAT_SCHEDULE` (`config/settings/base.py:303`) toca este módulo.

#### 5.8.3 Notificaciones

**Ninguna.** Verificado: ni `apps/recetas` ni `apps/pdfs` importan nada de
`apps.notificaciones`. Emitir o anular una receta no avisa a nadie; terminar un PDF tampoco. El
único canal es el polling del front.

#### 5.8.4 Escrituras colaterales

- `prescription_format_create` / `_update` con `is_default=True` hacen un `UPDATE` masivo que
  desmarca el default anterior del tenant, **usando `all_objects`** (`services.py:934-938`,
  `:1038-1042`). Está acotado por `filter(tenant=tenant)` explícito, así que no cruza clínicas.
- La tarea Celery escribe el `FileField` del job en el storage (`tasks.py:88-92`). **Los PDFs no se
  borran nunca**: no hay política de retención → B-REC-10.
- `PrescriptionItem` se crea en bucle dentro de la misma transacción de la receta
  (`services.py:662-697`): 1 + N inserts por emisión, con N ≤ 20.
## 6. Finanzas

> Extraído del código el 2026-08-12 (modo inverso). Cubre `apps/finanzas` completa y el adapter
> `adapters/cfdi.py`. Lo que no se pudo verificar leyendo código va marcado con **NO VERIFICADO**.
>
> **Abreviatura de rutas usada en esta sección:** `finanzas/<archivo>:<línea>` =
> `MailySoft/backend/apps/finanzas/<archivo>:<línea>`. Cualquier otra ruta se escribe completa
> desde la raíz del repo.
>
> Esta sección **cita** la capa transversal (`docs/_a2-partes/00-transversal.md`) y no la repite:
> aislamiento de tenant §1.1, auth §1.2, clases de permiso §1.3, módulos §1.4, alcance por sucursal
> §1.5, roles §1.6, convenciones de API §1.7, modelos base §1.8.

Archivos leídos: `models.py` (917), `views.py` (1375), `services.py` (1274), `selectors.py` (1134),
`retention.py` (589), `pdf.py` (402), `pdf_jobs.py`, `cache.py`, `serializers.py` (345), `urls.py`,
`admin.py`, `apps.py`, las 14 migraciones y `management/commands/seed_finanzas.py`. Como insumo:
`MailySoft/backend/adapters/cfdi.py`, `apps/core/permissions.py:280-614` y `:1119`,
`MailySoft/backend/apps/pdfs/views.py`.

**Cuatro módulos comerciales viven aquí** (`servicios`, `paquetes`, `cotizaciones`, `cobranza`) más
`cfdi`. Ninguna vista de esta app carece de `permission_classes`, y todas componen
`[IsAuthenticated, <RolPermission>, <RequiresX>]` como exige §1.4.2.

---

### 6.1 Modelo de datos

Nueve modelos concretos. **Los nueve heredan `TenantAwareModel`** (`finanzas/models.py:34, 114, 189,
305, 408, 461, 504, 621, 701, 745`), así que todos llevan `tenant_id` con `on_delete=PROTECT`,
`created_by` `SET_NULL`, soft-delete y los dos managers de §1.8.2. No hay ninguna tabla de esta app
sin `tenant_id` salvo las dos intermedias de M2M, cubiertas aparte (§6.1.10).

Precisión monetaria única en toda la app: `DecimalField(max_digits=12, decimal_places=2)`, declarada
en dos constantes (`finanzas/models.py:24-25`) y con la regla escrita en el docstring del módulo:
*"Montos: DecimalField(max_digits=12, decimal_places=2). NUNCA float para dinero"*
(`finanzas/models.py:14`). **Verificado: no hay ni un `FloatField` ni un `float()` sobre dinero en
ninguno de los nueve modelos ni en los services.** Los únicos `float` del dominio son ratios de
presentación: `conversion_rate` (`finanzas/selectors.py:669`), `retention_rate` /
`no_show_rate` / `pct_with_future_appt` (`finanzas/retention.py:520, 547, 578`), el ancho de barra
del SVG de aging (`finanzas/pdf.py:120`) y los porcentajes formateados del PDF
(`finanzas/pdf.py:219, 236, 243`). Hay **un matiz en el borde HTTP**, documentado en B-FIN-17.

#### 6.1.1 `ServiceConcept` — catálogo de servicios cobrables

Tabla `finanzas_service_concepts` (`finanzas/models.py:101`). Módulo: `servicios`.

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `name` | `CharField(160)` | no | — | `:46` |
| `description` | `TextField` | no | `""` | comercial `:50` |
| `clinical_description` | `TextField` | no | `""` | texto clínico para el Plan Integral de Longevidad `:55` |
| `base_price` | **`Decimal(12,2)`** | no | `0.00` | referencia; se copia como snapshot `:65` |
| `sat_product_key` | `CharField(10)` | no | `""` | ClaveProdServ; **opcional aquí**, requerida al timbrar `:71` |
| `sat_unit_key` | `CharField(10)` | no | `"E48"` | ClaveUnidad `:80` |
| `is_active` | `BooleanField` | no | `True` | `db_index=True` `:83` |
| `sucursales` | `M2M → clinica.Sucursal` | — | vacío | **vacío = disponible en TODAS las sedes** `:88-98` |

Constraint: `UniqueConstraint(tenant, name)` = `finanzas_concept_name_uniq` (`:104`), **sin condición
sobre `deleted_at`** → ver B-FIN-11. Orden por defecto: `name` (`:102`).

#### 6.1.2 `ClinicFiscalConfig` — datos del emisor

Tabla `finanzas_fiscal_configs` (`finanzas/models.py:159`). Uno por tenant. Módulo: `cfdi`.

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `rfc` | `CharField(13)` | no | `""` | `:124` |
| `legal_name` | `CharField(255)` | no | `""` | `:130` |
| `tax_regime` | `CharField(5)` | no | `""` | c_RegimenFiscal `:136` |
| `postal_code` | `CharField(5)` | no | `""` | LugarExpedicion `:142` |
| `series` | `CharField(10)` | no | `"A"` | `:148` |
| `next_folio` | `PositiveIntegerField` | no | `1` | consecutivo interno `:153` |

Constraint: `UniqueConstraint(tenant)` (`:161`). **No almacena secretos**: CSD y credenciales del PAC
se leen del entorno (`finanzas/models.py:117-120`, confirmado en
`MailySoft/backend/adapters/cfdi.py:16-19`). `next_folio` es inmutable por API
(`finanzas/services.py:352-354`).

#### 6.1.3 `Quote` / `QuoteItem` — cotizaciones

Tablas `finanzas_quotes` y `finanzas_quote_items` (`finanzas/models.py:292, 396`). Módulo:
`cotizaciones`.

**`Quote`** (`:189`):

| Campo | Tipo | Null | Default | `on_delete` y consecuencia real |
|---|---|---|---|---|
| `patient` | FK `pacientes.Patient` | no | — | **PROTECT** `:214` — no se puede borrar en duro un paciente con cotizaciones. El borrado real es lógico (§1.8.3) |
| `status` | `CharField(10)` choices | no | `draft` | `db_index=True` `:218` |
| `valid_until` | `DateField` | **sí** | `NULL` | vigencia; **solo se guarda y se imprime, nunca se hace valer** → B-FIN-06 `:225` |
| `notes` | `TextField` | no | `""` | `:230` |
| `subtotal` | **`Decimal(12,2)`** | no | `0.00` | snapshot, antes de descuentos `:235` |
| `discount_total` | **`Decimal(12,2)`** | no | `0.00` | descuento de renglón **+** general `:241` |
| `total` | **`Decimal(12,2)`** | no | `0.00` | snapshot `:247` |
| `global_discount_type` | `CharField(10)` choices | no | `amount` | `DiscountType` `:253` |
| `global_discount_value` | **`Decimal(12,2)`** | no | `0.00` | monto **o** porcentaje según el tipo `:264` |
| `sucursal` | FK `clinica.Sucursal` | **sí** | `NULL` | **SET_NULL** `:277` — borrar una sede no borra la cotización: queda "sin sede" y vuelve a comportarse como dato legado (pasa todos los filtros de alcance, `finanzas/views.py:161-162`) |

Índice: `finanzas_quote_patient_idx` sobre `(tenant, patient, status)` (`:295`). Consulta que lo
justifica: `quote_list(patient_id=..., status=...)` (`finanzas/selectors.py:161-164`), el historial de
cotizaciones del paciente en el drawer del expediente. Orden por defecto `-created_at` (`:293`).

**`QuoteItem`** (`:305`):

| Campo | Tipo | Null | Default | `on_delete` y consecuencia real |
|---|---|---|---|---|
| `quote` | FK `Quote` | no | — | **CASCADE** `:325` — borrar en duro la cotización se lleva sus líneas. Correcto: la línea no existe fuera del documento |
| `concept` | FK `ServiceConcept` | **sí** | `NULL` | **PROTECT** `:331` — no se puede borrar en duro un concepto usado en una cotización; el catálogo se desactiva, no se borra (`concept_deactivate`) |
| `description` | `CharField(200)` | no | — | snapshot del nombre `:337` |
| `quantity` | **`Decimal(10,2)`** | no | `1.00` | **sin validación de signo** → B-FIN-07 `:341` |
| `unit_price` | **`Decimal(12,2)`** | no | `0.00` | snapshot `:347` |
| `discount_type` | `CharField(10)` choices | no | `amount` | `:353` |
| `discount` | **`Decimal(12,2)`** | no | `0.00` | valor **capturado** (no es el descuento en $ si es porcentaje) `:363` |
| `discount_amount` | **`Decimal(12,2)`** | no | `0.00` | descuento **efectivo** en $, snapshot calculado `:374` |
| `line_total` | **`Decimal(12,2)`** | no | `0.00` | `(cant × precio) − discount_amount` `:385` |

Sin índices propios; se accede siempre por `quote` (índice implícito del FK). Orden `created_at`
(`:397`).

#### 6.1.4 `TreatmentPackage` / `TreatmentPackageItem` — paquetes de sesiones

Tablas `finanzas_treatment_packages` y `finanzas_treatment_package_items` (`:448, 492`). Módulo:
`paquetes`.

`TreatmentPackage` (`:408`): `name` `CharField(160)` (`:420`), `description` `TextField` default `""`
(`:424`), `is_active` `Boolean` default `True` con `db_index` (`:429`), `sucursales` M2M con la misma
convención "vacío = todas" (`:434`). Constraint `UniqueConstraint(tenant, name)` =
`finanzas_package_name_uniq` (`:451`), **sin condición sobre `deleted_at`** → B-FIN-11, y aquí el
riesgo es real porque `package_delete` **sí** hace soft-delete (`finanzas/services.py:841-844`).

`TreatmentPackageItem` (`:461`): `package` FK **CASCADE** (`:472` — la línea no existe sin el
paquete), `service_concept` FK **PROTECT** (`:478` — el paquete es plantilla viva, no snapshot; si
se pudiera borrar el concepto el paquete quedaría roto), `sessions`
`PositiveSmallIntegerField` default 1 (`:482`), `order` `PositiveSmallIntegerField` default 0
(`:486`). Orden `("order", "id")` (`:493`). Sin precio propio: el precio se lee **en vivo** del
catálogo (`finanzas/serializers.py:144-147`).

#### 6.1.5 `Charge` — cuentas por cobrar

Tabla `finanzas_charges` (`:594`). Módulo: `cobranza`.

| Campo | Tipo | Null | Default | `on_delete` y consecuencia real |
|---|---|---|---|---|
| `patient` | FK `Patient` | no | — | **PROTECT** `:524` — un paciente con cargos no se borra en duro. Es la garantía de que el dinero no queda huérfano |
| `concept` | FK `ServiceConcept` | **sí** | `NULL` | **PROTECT** `:530` |
| `description` | `CharField(200)` | no | — | snapshot `:536` |
| `appointment` | FK `agenda.Appointment` | **sí** | `NULL` | **SET_NULL** `:542` — borrar una cita no borra el adeudo, solo pierde su origen. **Ningún camino de producción lo puebla** → B-FIN-08 |
| `quote` | FK `Quote` | **sí** | `NULL` | **SET_NULL** `:550`, `related_name="charges"` — borrar la cotización deja el cargo vivo y sin origen |
| `amount` | **`Decimal(12,2)`** | **no** | **sin default** | `:556` |
| `amount_paid` | **`Decimal(12,2)`** | no | `0.00` | suma de sus `PaymentAllocation`, mantenida por el service `:561` |
| `status` | `CharField(10)` choices | no | `pending` | `db_index=True` `:567` |
| `issued_at` | `DateTimeField` | no | — | `db_index=True`, base del aging `:574` |
| `sucursal` | FK `Sucursal` | **sí** | `NULL` | **SET_NULL** `:580` |

Propiedad calculada `balance = amount − amount_paid` (`:610-613`); **no** está en la base, se serializa
como campo derivado (`finanzas/serializers.py:234`).

Índices (`:596-605`) y la consulta concreta que justifica cada uno:

| Índice | Campos | Consulta que lo necesita |
|---|---|---|
| `finanzas_charge_patient_idx` | `(tenant, patient, status)` | `charge_list(patient_id=..., status=...)` (`finanzas/selectors.py:254-257`) — estado de cuenta y pestaña de cargos del paciente |
| `finanzas_charge_aging_idx` | `(tenant, status, issued_at)` | `_aging_buckets` (`finanzas/selectors.py:632-637`), 4 consultas por dashboard/reporte: `status IN (pending, partial)` + rango de `issued_at` |

Orden por defecto `-issued_at` (`:595`).

#### 6.1.6 `Payment` / `PaymentAllocation` — cobros y su aplicación

Tablas `finanzas_payments` y `finanzas_payment_allocations` (`:684, 727`). Módulo: `cobranza`.

**`Payment`** (`:621`): `patient` FK **PROTECT** (`:637`), `amount` **`Decimal(12,2)` sin default**
(`:641`), `method` choices `cash|card|transfer|other` default `cash` con `db_index` (`:646`),
`reference` `CharField(120)` default `""` (`:653`), `received_at` `DateTimeField` con `db_index`
(`:659`), `notes` `TextField` default `""` (`:663`), `sucursal` FK **SET_NULL** (`:670`).

Índices (`:686-695`):

| Índice | Campos | Consulta que lo necesita |
|---|---|---|
| `finanzas_payment_patient_idx` | `(tenant, patient)` | `payment_list(patient_id=...)` (`selectors.py:301`) — estado de cuenta |
| `finanzas_payment_method_idx` | `(tenant, method, received_at)` | desglose `by_method` del dashboard/reporte/cierre (`selectors.py:587-593`, `:866-871`, `:1080-1085`) |

**`PaymentAllocation`** (`:701`): `payment` FK **CASCADE** (`:710` — borrar el pago se lleva sus
aplicaciones, **pero no recalcula `Charge.amount_paid`** → B-FIN-18), `charge` FK **PROTECT**
(`:716` — un cargo con dinero aplicado no se borra en duro), `amount` **`Decimal(12,2)` sin default**
(`:720`). Índice `finanzas_alloc_charge_idx` sobre `(tenant, charge)` (`:729`), justificado por el
`related_name="allocations"` que precarga `payment_get` (`selectors.py:278`) y por el recálculo de
`amount_paid`.

#### 6.1.7 `CfdiDocument` — comprobante fiscal

Tabla `finanzas_cfdi_documents` (`:902`). Módulo: `cfdi`.

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `payment` | FK `Payment` | **sí** | `NULL` | **SET_NULL** `:765`, `related_name="cfdi_documents"` (**plural: un pago admite varios CFDI** → B-FIN-01). Borrar el pago deja el comprobante fiscal huérfano pero vivo, que es lo correcto: ante el SAT sigue existiendo |
| `patient` | FK `Patient` | no | — | **PROTECT** `:773` |
| `status` | `CharField(10)` choices | no | `draft` | `db_index` `:779` |
| `series` / `folio` | `CharField(10)` / `PositiveInteger` | no / **sí** | `""` / `NULL` | folio interno `:787, :793` |
| `uuid_sat` | `CharField(36)` | no | `""` | `db_index` `:798` |
| `receptor_rfc` | `CharField(13)` | no | — | snapshot, **sin validación de formato** `:806` |
| `receptor_name` | `CharField(255)` | no | — | `:810` |
| `receptor_tax_regime` / `receptor_postal_code` | `CharField(5)` | no | `""` | `:814, :820` |
| `cfdi_use` | `CharField(5)` | no | `"G03"` | `:826` |
| `payment_form` | `CharField(2)` | no | `"01"` | `:831` |
| `payment_method` | `CharField(3)` | no | `"PUE"` | `:836` |
| `subtotal` / `total` | **`Decimal(12,2)`** | no | `0.00` | ambos se llenan con `payment.amount`; **cero impuestos** → B-FIN-16 `:841, :847` |
| `pac_id`, `xml_url`, `pdf_url` | `CharField(64)` / `URLField` ×2 | no | `""` | artefactos del PAC `:854, :860, :865` |
| `cancellation_reason` | `CharField(2)` | no | `""` | motivo SAT `:870` |
| `stamped_at` / `cancelled_at` | `DateTimeField` | **sí** | `NULL` | `:876, :881` |
| `sucursal` | FK `Sucursal` | **sí** | `NULL` | **SET_NULL** `:886`; se hereda de `payment.sucursal` al timbrar |

Índices (`:904-913`): `finanzas_cfdi_status_idx` `(tenant, status)` → `cfdi_list(status=...)`
(`selectors.py:346`); `finanzas_cfdi_patient_idx` `(tenant, patient)` → historial fiscal del paciente
(`selectors.py:344`). **No hay constraint único de folio** → B-FIN-13.

#### 6.1.8 Qué tablas llevan `tenant_id` y cuáles no

| Tabla | `tenant_id` | RLS | Por qué |
|---|---|---|---|
| Las 9 de negocio (`finanzas_service_concepts`, `_fiscal_configs`, `_quotes`, `_quote_items`, `_treatment_packages`, `_treatment_package_items`, `_charges`, `_payments`, `_payment_allocations`, `_cfdi_documents`) | Sí, `PROTECT` | Sí | Es el dato de la clínica (§1.8.2) |
| `finanzas_service_concepts_sucursales` | **No** (tabla through auto-generada) | Sí, por subconsulta al padre | Django no le pone `tenant_id`; la policy resuelve el tenant vía `finanzas_service_concepts` (`finanzas/migrations/0012_rls_finanzas_m2m_through_tables.py:44-57`) |
| `finanzas_treatment_packages_sucursales` | **No** | Sí, igual | Mismo patrón (`:51-56`) |

Cobertura RLS verificada en las migraciones: `0002_enable_rls` (8 tablas iniciales),
`0003_rls_with_check` (añade `WITH CHECK` a las mismas 8), `0005_rls_treatment_packages` (las 2 de
paquetes) y `0012` (las 2 through). Total: 12 tablas con policy, que es exactamente lo que exige el
test guardián de §1.1.4.

#### 6.1.9 Máquinas de estado declaradas

- `Quote.Status`: `draft | sent | accepted | rejected | expired` (`:205-210`).
- `Charge.Status`: `pending | partial | paid | cancelled` (`:516-520`).
- `Payment`: **no tiene estado** — un pago existe o no existe.
- `CfdiDocument.Status`: `draft | stamped | cancelled` (`:758-761`).

El comportamiento real (que no coincide del todo con lo declarado) está en §6.3.

---

### 6.2 Endpoints

19 rutas, 27 combinaciones método+ruta. Prefijo `/api/v1/` (§1.7). Todas heredan de `TenantAPIView`
(§1.1.2). Todas las respuestas de error siguen las tres formas de §1.7.2; en esta app la forma
dominante de error de negocio es `{"detail": ["<msg>", ...]}` (**lista**), porque las vistas
traducen `DjangoValidationError` con `exc.messages` (p. ej. `finanzas/views.py:245`).

Paginación: `PageNumberPagination()` instanciado a mano en cada listado, `PAGE_SIZE=25`, sin
`page_size` por query (§1.7.1). **Los endpoints analíticos no paginan**: dashboard, reporte, cierre
diario, estado de cuenta y retención devuelven el objeto completo.

Errores comunes a toda la app y su origen:

| Código | Cuerpo | Cuándo |
|---|---|---|
| 401 | `{"detail": ...}` | sin Bearer válido |
| 403 | `{"detail": ...}` | rol insuficiente; sede no permitida (`sucursal_scope_ids`); contraseña temporal (§1.2.4). También el `_NO_TENANT` de `finanzas/views.py:114-117` |
| 404 | `{"detail": "<recurso> no encontrado."}` | otro tenant, **fuera de la sede permitida**, o **módulo no contratado** (§1.4.2) |
| 405 | `{"detail": ...}` | método ruteado en la URL pero no implementado en la vista |
| 429 | `{"detail": ...}` | throttle `user` 300/min (§1.7.3). **No hay throttle específico de finanzas** |

Nota de orden: DRF corre `check_permissions` **antes** de resolver el handler, así que un método no
declarado en la `policy` del permiso devuelve **403, no 405** (p. ej. `DELETE /finanzas/pagos/<id>/`).

#### 6.2.1 Catálogo de servicios — guard `RequiresServicios`

| Método | Ruta | Permiso (§1.3) | Roles |
|---|---|---|---|
| GET | `/api/v1/finanzas/conceptos/` | `FinanceConceptPermission` (§1.3.2 #10) | O A F R L **+ D** |
| POST | `/api/v1/finanzas/conceptos/` | ídem | **solo O** |
| GET · PATCH · DELETE | `/api/v1/finanzas/conceptos/<uuid:concept_id>/` | ídem | GET: O A F R L D · escritura: **solo O** |

Vista: `ConceptListCreateApi` (`finanzas/views.py:196`), `ConceptDetailApi` (`:251`).

- **GET lista** — query: `only_active` (default `"true"`; cualquier valor distinto de `"false"`
  cuenta como true, `:227`). Se acota por sede con `sucursal_scope_ids` (`:229`) usando la convención
  "M2M vacío = todas las sedes" (`finanzas/selectors.py:69-89`, con `.distinct()` obligatorio).
  Respuesta **200** paginada: `{count, next, previous, results[]}` con
  `ServiceConceptOutputSerializer` (`finanzas/serializers.py:36`): `id, name, description,
  clinical_description, base_price, sat_product_key, sat_unit_key, is_active, sucursales[{id,name}],
  created_at`.
- **POST** — body: `name` (req, ≤160), `description`, `clinical_description`, `base_price`
  (`Decimal(12,2)`, default 0), `sat_product_key`, `sat_unit_key` (default `E48`), `sucursal_ids[]`
  (default `[]` = todas). **201** con el concepto. **400** `{"detail": ["Ya existe un concepto con ese
  nombre en esta clínica."]}` (`finanzas/services.py:211`) o `["Una o más sucursales indicadas no
  pertenecen a esta clínica."]` (`:147`). **403** si `tenant` es `None` (`views.py:239`).
- **GET detalle** — **404** `{"detail": "Concepto no encontrado."}` (`:278`). **No acota por sede**
  (a diferencia del listado) → B-FIN-15.
- **PATCH** — todos los campos opcionales, más `is_active` (que va por su propio service:
  `concept_reactivate` / `concept_deactivate`, `:304-308`) y `sucursal_ids` (si se envía **reemplaza**
  la disponibilidad; si se omite no se toca, `:271`). **400** si el body va vacío
  (`{"detail": "No se proporcionaron campos para actualizar."}`, `:295`).
- **DELETE** — **no borra**: llama `concept_deactivate` (`:321`). **204** sin cuerpo.

#### 6.2.2 Paquetes de tratamientos — guard `RequiresPaquetes`

| Método | Ruta | Permiso | Roles |
|---|---|---|---|
| GET · POST | `/api/v1/finanzas/paquetes/` | `TreatmentPackagePermission` (§1.3.2 #13) | GET: O A D R · POST: **solo O** |
| GET · PATCH · DELETE | `/api/v1/finanzas/paquetes/<uuid:package_id>/` | ídem | GET: O A D R · escritura: **solo O** |

Vista: `PackageListCreateApi` (`:374`), `PackageDetailApi` (`:428`).

- **GET lista** — query `only_active`; acotado por sede igual que conceptos (`:405`). **200** paginada
  con `TreatmentPackageListItemSerializer` (`serializers.py:197`): `id, name, description, is_active,
  items_count, sessions_total, price, sucursales[], created_at`. `price` se calcula **en vivo** como
  `Σ(concept.base_price × sessions)` (`serializers.py:144-147`).
- **POST** — body: `name`, `description`, `is_active` (default `True`), `items[]` (**obligatorio, no
  vacío**; cada item `{concept_id, sessions?, order?}` validado en el service), `sucursal_ids[]`.
  **201** con `TreatmentPackageOutputSerializer` (items anidados). **400**: nombre duplicado
  (`services.py:736`), paquete sin tratamientos (`:738`), item sin `concept_id` (`:678`), concepto
  inexistente (`:682`), concepto de otro tenant (`:683`), **concepto desactivado** (`:685`),
  `sessions` no entero (`:690`) o `< 1` (`:692`).
- **PATCH** — **es un reemplazo, no un patch parcial**: `name` es obligatorio y `description` /
  `is_active` se reescriben siempre con lo enviado (`views.py:443-451`). Si `items` se omite, la vista
  reenvía los actuales para no perderlos (`:477-487`), porque `package_replace` **borra y recrea**
  todas las líneas (`services.py:820`).
- **DELETE** — soft-delete (`services.py:843`). **204**.

#### 6.2.3 Configuración fiscal — guard `RequiresCfdi`

| Método | Ruta | Permiso | Roles |
|---|---|---|---|
| GET · PATCH | `/api/v1/finanzas/config/` | `FinanceConfigPermission` (§1.3.2 #18) | **O A** |

Vista `FiscalConfigApi` (`:330`). **GET** hace `get_or_create`: si la clínica nunca la configuró
devuelve un registro vacío recién creado (`services.py:343-349`). **PATCH** acepta `rfc`,
`legal_name`, `tax_regime`, `postal_code`, `series`; `next_folio` está en la lista de inmutables y su
envío da **400** (`services.py:352-372`). **Ninguno de los campos se valida en formato** → B-FIN-12.
Respuesta **200** con `ClinicFiscalConfigOutputSerializer`: `id, rfc, legal_name, tax_regime,
postal_code, series, next_folio, created_at` (`serializers.py:330`).

#### 6.2.4 Cotizaciones — guard `RequiresCotizaciones`

Permiso en las cinco rutas: `QuotePermission` (§1.3.2 #12) → **O A D R** para todo, **+ L** solo GET.
Finanzas y enfermería quedan fuera del módulo por decisión del cliente.

| Método | Ruta | Vista |
|---|---|---|
| GET · POST | `/api/v1/finanzas/cotizaciones/` | `QuoteListCreateApi` `:509` |
| GET · PATCH | `/api/v1/finanzas/cotizaciones/<uuid:quote_id>/` | `QuoteDetailApi` `:639` |
| POST | `.../<uuid:quote_id>/enviar/` | `QuoteSendApi` `:670` |
| POST | `.../<uuid:quote_id>/aceptar/` | `QuoteAcceptApi` `:686` |
| GET | `.../<uuid:quote_id>/pdf/` | `QuotePdfApi` `:702` |

- **GET lista** — filtros: `patient_id`, `status`. **Regla de sede**: con `patient_id` **no** se acota
  (historial del paciente, compartido entre sedes); sin él **sí** se acota con `sucursal_scope_ids`
  (`views.py:578-584`). **200** paginada con `QuoteOutputSerializer` (`serializers.py:90`): `id,
  patient, status, status_display, valid_until, notes, subtotal, discount_total,
  global_discount_type, global_discount_value, global_discount_amount, total, items[], sucursal,
  created_at`. `global_discount_amount` es derivado: `discount_total − Σ item.discount_amount`
  (`serializers.py:125-132`).
- **POST** — body: `patient_id` (req), `valid_until`, `notes`, `items[]` (**no vacío**, dicts libres),
  `global_discount_type` (`amount|percent`), `global_discount_value` (`≥ 0`, y `≤ 100` si es
  porcentaje — validado en el serializer `:549-568` **y** de nuevo en el service `:472-476`). Cada
  item: `{concept_id?, description?, quantity?, unit_price?, discount_type?, discount?}` —
  `ItemSerializer` está declarado (`views.py:521`) **pero no se usa**: `items` es
  `ListField(DictField())` y la validación real ocurre en `_create_quote_item`, hecho reconocido en
  el propio comentario (`views.py:516-520`). La sede de escritura se resuelve con
  `_resolve_write_sucursal` (§1.5.3). **201**. **404** `{"detail": "Paciente no encontrado."}`.
  **400**: sin líneas, descuento fuera de rango, línea sin descripción ni concepto (`services.py:543`),
  concepto inexistente (`:535`), sede ajena.
- **GET/PATCH detalle** — resuelto por `_quote_get_scoped` (`views.py:616`), que **sí** acota por sede
  y devuelve **404** con el mismo texto que "no existe" para no delatar la otra sede
  (`_scope_or_404`, `:130-166`). PATCH solo admite `status ∈ {rejected, expired}` (`:647`); ver la
  brecha de la máquina de estados en §6.3.
- **POST enviar** — `draft → sent`. **400** `["Solo se pueden enviar cotizaciones en borrador."]`
  (`services.py:576`).
- **POST aceptar** — `draft|sent → accepted` **y genera un `Charge` por línea**. **400** `["Solo se
  pueden aceptar cotizaciones en borrador o enviadas."]` (`:601`).
- **GET pdf** — **no devuelve el PDF**: encola un job de Celery y responde **202**
  `{"job_id": "<uuid>", "status": "<pending|...>"}` (`views.py:741-744`). El front hace polling contra
  `GET /api/v1/pdfs/job/<job_id>/` y descarga en `.../file/` (§6.7). `cache_key=""` → siempre se
  regenera. Acota por sede antes de encolar (`:727`).

#### 6.2.5 Cargos — guard `RequiresCobranza`

| Método | Ruta | Permiso | Roles |
|---|---|---|---|
| GET · POST | `/api/v1/finanzas/cargos/` | `ChargeListPermission` (§1.3.3 #40) | GET: O A F R L **+ D si `doctors_see_costs`** · POST: **O A F** |
| GET · DELETE | `/api/v1/finanzas/cargos/<uuid:charge_id>/` | `FinanceChargePermission` (§1.3.2 #14) | GET: O A F R L (**D nunca**) · DELETE: O A F |

Vista `ChargeListCreateApi` (`:752`), `ChargeDetailApi` (`:843`). La asimetría de permiso entre lista
y detalle es real → B-FIN-14.

- **GET lista** — filtros: `patient_id`, `status`, `appointment` (UUID; si no parsea → **400**
  `{"detail": "El parámetro 'appointment' debe ser un UUID válido."}`, `:793`). **Regla de sede**: con
  `patient_id` **o** `appointment` no se acota; sin ellos sí (`:796`). **200** paginada con
  `ChargeOutputSerializer` (`serializers.py:230`): `id, patient, concept, description, appointment,
  quote, amount, amount_paid, balance, status, status_display, issued_at, sucursal, created_at`.
  El filtro `?appointment=` **siempre devuelve vacío en producción** → B-FIN-08.
- **POST** — body: `patient_id`, `description` (≤200), `amount` (`Decimal(12,2)`), `concept_id?`,
  `appointment_id?` — **este último se acepta y se descarta silenciosamente** (`views.py:773` vs
  `:829-837`). **201**. **404** paciente/concepto no encontrado. **400** `["El monto del cargo debe ser
  mayor a cero."]` (`services.py:889`) o `["El cargo requiere una descripción."]` (`:891`).
- **GET detalle** — acotado por sede (`_scope_or_404`, `:866`). **404** `{"detail": "Cargo no
  encontrado."}`.
- **DELETE** — **no borra: cancela** (`status = cancelled`, `services.py:930`). **204**. **400**
  `["El cargo ya está cancelado."]` (`:925`) o `["No se puede cancelar un cargo con pagos aplicados.
  Cancela primero los pagos."]` (`:927`) — mensaje que promete una acción que **no existe en la API**
  → B-FIN-09.

#### 6.2.6 Pagos — guard `RequiresCobranza`

| Método | Ruta | Permiso | Roles |
|---|---|---|---|
| GET · POST | `/api/v1/finanzas/pagos/` | `FinancePaymentPermission` (§1.3.2 #15) | GET: O A F R L · POST: **O A F R** |
| GET | `/api/v1/finanzas/pagos/<uuid:payment_id>/` | ídem | O A F R L |

Vista `PaymentListCreateApi` (`:893`), `PaymentDetailApi` (`:959`).

- **GET lista** — filtros `patient_id`, `method`. Misma regla de sede que cargos (`:922`). **200**
  paginada con `PaymentOutputSerializer` (`serializers.py:267`): `id, patient, amount, method,
  method_display, reference, received_at, notes, allocations[{id, charge, amount}], sucursal,
  created_at`.
- **POST** — body: `patient_id`, `amount`, `method` (default `cash`), `reference`, `notes`,
  `allocations[]` (lista de `{charge_id, amount}`, opcional, default `[]`). **201**. **404** paciente.
  **400**: monto ≤ 0 (`services.py:991`); **`["El pago (X) excede el saldo pendiente del paciente (Y).
  No se permiten pagos a favor."]`** (`:1009`); aplicación ≤ 0 (`:1032`); cargo no encontrado
  (`:1037`); cargo de otro paciente (`:1039`); cargo cancelado (`:1041`); aplicación mayor que el
  saldo del cargo (`:1044`); suma de aplicaciones mayor que el pago (`:1060`).
- **GET detalle** — acotado por sede (`:973`). **404**.
- **No hay PATCH ni DELETE** en ninguna de las dos rutas, y el permiso tampoco los declara: cualquier
  intento devuelve **403** → B-FIN-09.

#### 6.2.7 Estado de cuenta — guard `RequiresCobranza`

| Método | Ruta | Permiso | Roles |
|---|---|---|---|
| GET | `/api/v1/finanzas/estado-cuenta/<uuid:patient_id>/` | `PatientStatementPermission` (§1.3.3 #39) | O A F R L **+ D si `doctors_see_costs`** |

Vista `AccountStatementApi` (`:1102`). Query: `date_from`, `date_to` (`YYYY-MM-DD`; un valor mal
formado se ignora en silencio y equivale a "sin filtro", `_parse_date` `:120-127`).

**Nunca filtra por sucursal, por diseño explícito** (`selectors.py:375-380`): un paciente cobrado en
Acapulco y en CDMX ve ambos movimientos; cada movimiento expone su sede como columna informativa.

Respuesta **200** (dict crudo, sin serializer):
```
{ patient: {id, full_name, record_number},
  movements: [{date, type: "charge"|"payment", description, charge, payment, balance,
               reference, id, sucursal: {id,name}|null}],
  total_charged, total_paid, balance, charges_count, payments_count }
```
Los cargos `cancelled` se excluyen (`selectors.py:394`). El saldo corriente se calcula en Python
sobre la lista ordenada (`:434-440`). **Sin paginación ni cota**: devuelve todo el historial del
paciente.

#### 6.2.8 CFDI — guard `RequiresCfdi`

Permiso en las tres rutas: `CfdiPermission` (§1.3.2 #17) → GET: **O A F L** · POST: **O A F**
(recepción no factura).

| Método | Ruta | Vista |
|---|---|---|
| GET · POST | `/api/v1/finanzas/cfdi/` | `CfdiListCreateApi` `:984` |
| GET | `/api/v1/finanzas/cfdi/<uuid:cfdi_id>/` | `CfdiDetailApi` `:1062` |
| POST | `/api/v1/finanzas/cfdi/<uuid:cfdi_id>/cancelar/` | `CfdiCancelApi` `:1074` |

- **GET lista** — filtros `patient_id`, `status`. Misma regla de sede (`:1012`). **200** paginada con
  `CfdiDocumentOutputSerializer` (24 campos, `serializers.py:292`).
- **POST emitir** — body: `payment_id` (req), `receptor_rfc` (req, ≤13), `receptor_name` (req, ≤255),
  `receptor_tax_regime`, `receptor_postal_code`, `cfdi_use` (default `G03`), `payment_form`
  (default `01`), `payment_method` (default `PUE`). **201**. **404** `{"detail": "Pago no
  encontrado."}`. **400**: `["Configura los datos fiscales del emisor (RFC) antes de timbrar."]`
  (`services.py:1150`), `["El receptor requiere RFC y razón social."]` (`:1152`), `["No tienes acceso
  a la sucursal de este comprobante."]` (`:171` — nótese que aquí el alcance por sede se manifiesta
  como **400**, no como 404), `["El PAC rechazó el timbrado: ..."]` (`:1207`).
- **POST cancelar** — body: `reason ∈ {01,02,03,04}` (default `02`). **200** con el CFDI. **400**
  `["Solo se pueden cancelar comprobantes timbrados."]` (`:1248`) o `["El PAC rechazó la cancelación:
  ..."]` (`:1258`). Acotado por sede con `_cfdi_get_scoped` → **404** (`views.py:1041`).

#### 6.2.9 Analítica: dashboard, reporte, cierre y retención — guard `RequiresCobranza`

| Método | Ruta | Permiso | Roles |
|---|---|---|---|
| GET | `/api/v1/finanzas/dashboard/` | `FinanceDashboardPermission` (§1.3.2 #9) | O A F L (**R fuera**) |
| GET | `/api/v1/finanzas/reporte/` | ídem | O A F L |
| GET | `/api/v1/finanzas/reporte/pdf/` | ídem | O A F L |
| GET | `/api/v1/finanzas/cierre-diario/` | `FinanceDeskPermission` (§1.3.5) | **O A F R** |
| GET | `/api/v1/finanzas/retencion/` | `RetentionPermission` (§1.3.2 #38) | O A F L |

`FinanceDeskPermission` está definido **dentro de la app** (`finanzas/views.py:92-101`), no en
`core/permissions.py`, y ya figura en §1.3.5.

- **Dashboard** (`views.py:1134`) — query `date_from`, `date_to` (default: últimos 30 días,
  `selectors.py:495-499`). Acotado por sede. **200** con `{range, kpis:{total_income, total_charged,
  outstanding, average_ticket, collection_rate, payments_count}, income_by_day[], income_by_concept[]
  (top 12), income_by_method[], aging[4 buckets], quotes_funnel{draft,sent,accepted,rejected,expired,
  conversion_rate}}` (`selectors.py:601-616`). **Cacheado en Redis** (§6.7).
- **Reporte de periodo** (`views.py:1161`) — query `date_from`, `date_to`, `group ∈ {day,week,month}`.
  **400** si `date_from > date_to` (`:1189`) o si `group` no es válido (`:1196`). **200** con 20 claves
  (`selectors.py:928-962`): KPIs actuales, `prev_*` del periodo anterior del mismo tamaño, `delta_*`,
  `aging`, `by_method`, `by_service` (top 15), `by_doctor`, `series`, y `adjustments_total: 0` con
  `adjustments_note` explicando que **el modelo `Adjustment` no existe** (`:955-961`). Cacheado.
- **Reporte PDF** (`views.py:1209`) — mismo rango; un `group` inválido aquí **no da 400, cae a `day`**
  (`:1241`), a diferencia del endpoint anterior. Responde **202** `{job_id, status}`. El alcance de
  sedes se resuelve en la vista y **se congela en los params del job**, porque Celery corre sin
  request (`:1245-1262`).
- **Cierre diario** (`views.py:1278`) — query `date` (default hoy). **400** si el formato es inválido
  (`:1305`). **200** con `{date, production, collection, adjustments_total: 0, collection_pct,
  by_method[], movements[], totals{}}` (`selectors.py:1120-1133`). Los movimientos incluyen cargos y
  pagos del día ordenados cronológicamente, cada uno con su sede.
- **Retención RFM** (`views.py:1323`) — sin parámetros. **403** si no hay tenant (`:1370`). **200** con
  `{segments{nuevo,vip,frecuente,en_riesgo,perdido,ocasional}, at_risk_list[], lost_list[],
  total_at_risk, total_lost, truncated, metrics{retention_rate, avg_ticket, no_show_rate,
  pct_with_future_appt, patients_seen_12m, patients_seen_prev_12m}}` (`retention.py:458-466`). Las
  listas accionables van **capadas a 500** (`retention.py:109, 410-411`) e incluyen teléfono y correo
  del paciente. **No hay caché** (§6.7).

#### 6.2.10 Lo que el frontend necesita y no está en ninguna respuesta

Recorriendo `FinanzasPage`, `CotizacionesPage` y `PaquetesPage` de `docs/01-analisis.md:166-168`
contra los serializers:

- El estado de cuenta y los listados devuelven `patient` como **UUID pelado**
  (`serializers.py:241, 279`), no `{id, nombre}`. La pantalla de cobros necesita el nombre y hoy lo
  obtiene con una llamada aparte a pacientes. Igual con `concept`, `appointment` y `quote` en
  `ChargeOutputSerializer`.
- `finance_daily_sheet` devuelve `patient_id` sin nombre (`selectors.py:1099, 1108`).
- No hay ningún endpoint que liste `PaymentAllocation` de forma independiente: solo vienen anidadas
  en el detalle/listado del pago.
- No hay endpoint para **editar las líneas** de una cotización, pese a que `QuotePdfApi` afirma en su
  docstring que "la cotización es MUTABLE (se edita)" (`views.py:709`). Solo se puede cambiar el
  estado.

---

### 6.3 Reglas de negocio verificadas en código

#### 6.3.1 Máquina de estados de `Quote` — lo declarado vs. lo implementado

Declarado (`models.py:192-193`): `DRAFT → SENT → (ACCEPTED | REJECTED | EXPIRED)`.

Implementado:

| Transición | Service | Guarda de origen | Verificado |
|---|---|---|---|
| `draft → sent` | `quote_send` `services.py:569` | **sí**: `status != DRAFT` → 400 (`:575`) | ✅ coincide |
| `draft|sent → accepted` | `quote_accept` `:591` | **sí**: `status not in (DRAFT, SENT)` → 400 (`:600`) | ✅ coincide |
| `* → rejected` / `* → expired` | `quote_set_status` `:637` | **NO valida el origen** (`:639-641` solo valida el destino) | ❌ **una cotización ACEPTADA puede pasar a RECHAZADA** y sus cargos siguen vivos → B-FIN-05 |

Además: **`valid_until` no interviene en ninguna transición**. No hay tarea de Celery ni comando que
marque `expired`, y `quote_accept` no compara contra la fecha. Verificado por búsqueda de
`valid_until` en todo `apps/`: en finanzas solo aparece en el modelo, el serializer, el service (como
parámetro que se guarda) y el PDF → B-FIN-06.

`quote_accept` **no es idempotente por bloqueo**, solo por estado leído antes de la transacción
(`:600-604`) → B-FIN-02.

#### 6.3.2 Cálculo de totales y descuentos

Dos niveles de descuento, ambos con tipo `amount` o `percent` (`DiscountType`, `models.py:176`).

Por renglón (`_create_quote_item`, `services.py:506-566`):
```
base            = _q2(quantity × unit_price)
discount_amount = _effective_discount(base, tipo, valor)      # services.py:95
line_total      = _q2(base − discount_amount)
```
`_effective_discount` (`:95-111`): si es porcentaje, `base × valor / 100`; luego **recorta a
`[0, base]`** con `max(ZERO, min(raw, base))` — un descuento que excede la línea **no se rechaza, se
recorta** (`:110`). `_validate_discount_value` (`:76-92`) rechaza tipo desconocido, valor negativo y
porcentaje > 100.

General (`_recalc_quote_totals`, `:396-427`):
```
subtotal        = Σ (quantity × unit_price)                       # SIN descuentos
net_lines_total = Σ line_total                                     # ya descontados por renglón
desc_general    = _effective_discount(net_lines_total, tipo_gral, valor_gral)
discount_total  = Σ discount_amount + desc_general
total           = net_lines_total − desc_general
```

Redondeo: **una sola función**, `_q2` = `value.quantize(Decimal("0.01"))` (`:68-70`), sin `rounding`
explícito → usa el default del contexto decimal de Python, `ROUND_HALF_EVEN`. Es consistente en toda
la app, pero no está declarado en ninguna parte.

**Lo que NO se valida**: `quantity` y `unit_price` no tienen cota inferior en el service, y el
serializer de entrada tampoco los mira (son dicts libres). Con `quantity` o `unit_price` negativo,
`base` es negativo, `_effective_discount` devuelve 0 (porque `max(ZERO, min(raw, base))` con
`base < 0` da `ZERO`) y `line_total` **queda negativo** → B-FIN-07.

#### 6.3.3 Cotización aceptada → cargos

`quote_accept` (`services.py:591-634`), dentro de `transaction.atomic()`:

1. `quote.status = ACCEPTED` y `save(update_fields=["status","updated_at"])` (`:605-606`).
2. Por cada `QuoteItem`, un `Charge` con `amount = item.line_total`, `amount_paid = 0`,
   `status = PENDING`, `issued_at = now`, `quote = quote`, `concept = item.concept`,
   `description = item.description` y **`sucursal = quote.sucursal`** — la sede donde se generó la
   cotización, no la del que acepta (`:608-623`, con la razón escrita en el comentario `:619-621`).
3. `appointment` queda `NULL`: el cargo nacido de una cotización nunca se liga a una cita.

**Este camino construye el `Charge` directamente con `objects.create()` y no pasa por
`charge_create`**, así que se salta las validaciones de monto positivo y descripción (`:888-891`).

#### 6.3.4 Máquina de estados de `Charge`

Derivada, no capturada. `_apply_charge_status` (`services.py:943-951`):
```
amount_paid <= 0            → PENDING
0 < amount_paid < amount    → PARTIAL
amount_paid >= amount       → PAID
```
`CANCELLED` es el único estado que se fija a mano, en `charge_cancel` (`:930`), con dos guardas:
ya cancelado (`:924`) y **con pagos aplicados** (`:926`). No existe transición de vuelta: un cargo
cancelado no se reactiva. No hay endpoint PATCH de cargo (la ruta no lo rutea), así que `amount` y
`description` son inmutables tras la creación.

#### 6.3.5 Asignación de pagos

`payment_register` (`services.py:959-1109`). Tres fases:

1. **Antes de la transacción** (`:996-1012`): calcula `deuda_pendiente` sumando en **Python** el
   `balance` de todos los cargos `PENDING|PARTIAL` del paciente, y rechaza el pago si lo excede →
   "No se permiten pagos a favor". Sin bloqueo y fuera del `atomic` → B-FIN-04.
2. **Aplicaciones explícitas** (`:1028-1057`), dentro de `atomic`: por cada `{charge_id, amount}`,
   `Charge.objects.select_for_update().filter(id=...).first()` (`:1035`), y valida: monto positivo,
   cargo existente, del mismo paciente, no cancelado, y que no exceda `charge.balance`. Crea la
   `PaymentAllocation`, suma a `amount_paid` y re-deriva el estado.
3. **Auto-asignación en cascada del remanente** (`:1062-1094`): lo que no se asignó a mano se aplica
   a los cargos `PENDING|PARTIAL` **más antiguos** (`order_by("issued_at","created_at")`, `:1076`),
   excluyendo los ya tocados, también con `select_for_update`. Lo que sobre "queda como saldo a favor
   del paciente" (comentario `:1065`) — es decir, **un `Payment` sin ninguna `PaymentAllocation`**,
   que es exactamente el estado que la validación de la fase 1 dice impedir.

`allocated_total > amount` se comprueba **después** de crear las asignaciones explícitas (`:1059`),
pero al estar dentro del `atomic` la excepción revierte todo. Es correcto, solo desperdicia trabajo.

#### 6.3.6 Emisión y cancelación de CFDI

`cfdi_issue` (`services.py:1117-1236`):

1. `_ensure_same_tenant(payment)` (`:1145`) y `_ensure_sucursal_allowed` (`:1146`, defensa en
   profundidad para llamadas fuera de la vista, `:151-171`).
2. Exige `ClinicFiscalConfig` con `rfc` no vacío (`:1148-1150`) y receptor con RFC y razón social
   (`:1151-1152`). **Nada más se valida.**
3. Dentro de `atomic` (`:1154`): `select_for_update` sobre la config, toma `folio = next_folio`,
   incrementa y guarda (`:1156-1159`). Crea el `CfdiDocument` en `DRAFT` con
   `subtotal = total = payment.amount` y `sucursal = payment.sucursal` (`:1161-1182`).
4. **Llama al PAC dentro de la misma transacción** (`:1184-1203`). Si `result.success` es falso,
   levanta `ValidationError` y **la transacción revierte, así que el folio no se consume** (comentario
   `:1206`). Si tiene éxito, persiste `uuid_sat`, `pac_id`, `xml_url`, `pdf_url`, `stamped_at` y pasa a
   `STAMPED` (`:1209-1225`).

**No hay ninguna comprobación de que el pago ya tenga un CFDI timbrado** → B-FIN-01. La red HTTP
dentro del `atomic` es B-FIN-03.

`cfdi_cancel` (`:1239-1274`): exige `status == STAMPED` (`:1247`), revalida la sede (`:1249`), llama
al PAC **fuera de transacción** (`:1251-1256`) y, si acepta, escribe `CANCELLED`,
`cancellation_reason` y `cancelled_at`. Un `CANCELLED` no se puede re-timbrar ni revertir. Si el PAC
acepta pero el `save` falla, la base queda diciendo `STAMPED` sobre un comprobante ya cancelado ante
el SAT.

#### 6.3.7 Alcance por sucursal — tabla completa

| Superficie | Acotada por sede | Mecanismo |
|---|---|---|
| Listado de conceptos / paquetes | **sí** | `sucursal_scope_ids` + convención M2M vacío (`views.py:229, 405`) |
| Detalle de concepto / paquete | **no** | B-FIN-15 |
| Listado de cotizaciones/cargos/pagos/CFDI **sin** `patient_id` | **sí** | `sucursal_scope_ids` (`views.py:579, 796, 922, 1012`) |
| Los mismos **con** `patient_id` (o `appointment`) | **no, a propósito** | historial del paciente compartido entre sedes |
| Detalle/acción por id: cotización, cargo, pago, CFDI | **sí** | `_scope_or_404` → **404**, mismo texto que "no existe" (`views.py:130-166`) |
| PDF de cotización | **sí** | `views.py:727` |
| Estado de cuenta | **nunca**, por diseño | `selectors.py:375-380` |
| Dashboard, reporte, reporte PDF, cierre diario, retención | **sí** | `sucursal_scope_ids` (`views.py:1149, 1204, 1249, 1313, 1374`) |
| Escritura de cotización/cargo/pago | **sí** | `_resolve_write_sucursal` (`views.py:169-188`, §1.5.3) |
| Cargo generado por `quote_accept` | hereda | `sucursal = quote.sucursal` (`services.py:622`) |
| CFDI | hereda | `sucursal = payment.sucursal` (`services.py:1181`) + `_ensure_sucursal_allowed` en timbrado y cancelación |

Un objeto con `sucursal_id = NULL` (legado o tenant sin sedes) **siempre pasa** todos los filtros
(`views.py:161-162`), decisión de compatibilidad retro escrita en el propio helper.

---

### 6.4 Integridad del dinero

#### 6.4.1 Dónde hay transacción y dónde no

| Operación | `transaction.atomic()` | Bloqueo |
|---|---|---|
| `quote_create` | sí `services.py:478` | — |
| `quote_accept` | sí `:604` | **ninguno sobre la cotización** |
| `quote_send`, `quote_set_status` | **no** | — (una sola escritura) |
| `package_create`, `package_replace` | sí `:743, :814` | — |
| `charge_create`, `charge_cancel` | **no** | — (una sola escritura) |
| `payment_register` | sí `:1014` | `select_for_update` sobre cada `Charge` (`:1035`, `:1070`) — pero **la validación de deuda queda fuera** (`:996-1012`) |
| `cfdi_issue` | sí `:1154` | `select_for_update` sobre `ClinicFiscalConfig` (`:1156`) |
| `cfdi_cancel` | **no** | — |

#### 6.4.2 Respuestas a las preguntas directas

**¿Se puede pagar dos veces el mismo cargo?** En una sola petición, no: cada asignación se valida
contra `charge.balance` con el cargo bloqueado (`services.py:1043`). En **dos peticiones concurrentes
del mismo importe sobre el mismo paciente**, sí se puede registrar el dinero dos veces: la validación
"no se permiten pagos a favor" corre antes de la transacción y sin bloqueo (`:996-1012`), así que
ambas la pasan; la segunda entra al `atomic`, no encuentra saldo que aplicar (el `select_for_update`
del bucle en cascada re-evalúa el filtro tras liberarse el lock y ya no ve el cargo como
`PENDING|PARTIAL`) y **termina creando un `Payment` con cero `PaymentAllocation`**. El cargo no se
paga dos veces, pero el ingreso sí se cuenta dos veces en el dashboard, en el cierre diario y en el
estado de cuenta, que pasa a saldo negativo. → **B-FIN-04**.

**¿Se puede editar un pago ya aplicado?** No. `PaymentDetailApi` solo implementa GET (`views.py:964`)
y `FinancePaymentPermission` no declara PATCH ni DELETE (`core/permissions.py:443-446`), así que
cualquier intento devuelve 403. No existe ningún service de edición ni de reversa de pago. Bueno para
la inmutabilidad, **pero deja sin salida el error de captura** → B-FIN-09.

**¿Un cargo ya cobrado se puede borrar?** No. El DELETE cancela, no borra (`services.py:930`), y
rechaza cualquier cargo con `amount_paid > 0` (`:926`). Como no hay forma de deshacer el pago, un
cargo cobrado por error **queda vivo para siempre**. Además `PaymentAllocation.charge` es `PROTECT`
(`models.py:716`), así que ni siquiera un borrado en duro pasa.

**¿Hay condiciones de carrera?** Tres verificadas:

1. `payment_register`: la comprobación de deuda fuera de la transacción (B-FIN-04).
2. `quote_accept`: sin `select_for_update` sobre la cotización; dos aceptaciones simultáneas generan
   **dos juegos completos de cargos** para la misma cotización (B-FIN-02).
3. `cfdi_issue`: sin verificación de unicidad ni bloqueo sobre el pago; dos emisiones simultáneas (o
   dos clics) producen **dos CFDI timbrados del mismo pago**, con dos folios y dos UUID del SAT
   (B-FIN-01).

El único punto donde el bloqueo está bien puesto es el folio consecutivo (`services.py:1156`).

#### 6.4.3 Idempotencia

**No existe ninguna clave de idempotencia** en toda la app: ni cabecera `Idempotency-Key`, ni
constraint único que impida el duplicado lógico (pago repetido, CFDI repetido, cargo repetido de la
misma cotización). Verificado por lectura completa de `views.py`, `services.py` y los `Meta` de
`models.py`. El único constraint de unicidad de negocio es el nombre del concepto y del paquete.

#### 6.4.4 Aritmética

`Decimal(12,2)` en los 16 campos monetarios, un solo cuantizador `_q2`, y las conversiones de entrada
se hacen con `Decimal(str(...))` para no pasar por `float` (`services.py:537-540`, `:1030`). Eso es
correcto. Dos matices:

- `Decimal(str(...))` sobre un valor no numérico levanta `decimal.InvalidOperation`, que **no** es
  `DjangoValidationError` y por tanto no la captura la vista → **500** (B-FIN-10).
- Los endpoints analíticos devuelven `Decimal` crudo dentro de un `dict` sin serializer
  (`selectors.py:601`, `:928`, `:1120`, `:445`), así que el redondeo del borde HTTP lo decide el
  encoder de DRF, no el código de la app (B-FIN-17). Además `collection_rate` y `collection_pct` son
  divisiones `Decimal/Decimal` sin cuantizar (`selectors.py:559`, `:820`): salen con la precisión
  completa del contexto decimal (28 dígitos).

---

### 6.5 CFDI: qué existe y qué no

#### 6.5.1 Qué existe

- El **modelo completo** `CfdiDocument` con 24 campos y su máquina de estados
  (`finanzas/models.py:745-917`).
- Los **tres endpoints** (listar/emitir, detalle, cancelar) con permiso y guard de módulo
  (`finanzas/urls.py:95-101`).
- Los **services** `cfdi_issue` y `cfdi_cancel` con folio consecutivo bloqueado, herencia de sede,
  bitácora y reversión del folio si el PAC rechaza (`finanzas/services.py:1117-1274`).
- La **configuración fiscal del emisor** con su endpoint (`finanzas/views.py:330`).
- Un **adapter con interfaz abstracta** (`MailySoft/backend/adapters/cfdi.py:66-97`), dos dataclasses
  de resultado (`:32-63`) y una factory (`:173-199`).
- Una **implementación simulada** que siempre tiene éxito: genera un `uuid4` como folio fiscal y URLs
  contra `https://sandbox.cfdi.local/...` (`adapters/cfdi.py:100-138`).

#### 6.5.2 Qué NO existe

- **No hay integración real con ningún PAC.** `FacturamaCfdiAdapter.stamp` y `.cancel` son
  `raise NotImplementedError` con el TODO a la vista
  (`MailySoft/backend/adapters/cfdi.py:160-170`). Los cuatro pasos de la integración están escritos
  como comentario, no como código (`:148-152`).
- **Lo que corre hoy en producción es el simulado.** La factory devuelve `FacturamaCfdiAdapter` solo
  si `FACTURAMA_API_USER`, `FACTURAMA_API_PASSWORD` y `FACTURAMA_BASE_URL` están **los tres** en
  settings; si no, `SimulatedCfdiAdapter` (`adapters/cfdi.py:193-199`). **NO VERIFICADO** si esas
  variables están definidas en el entorno de Railway — no se puede leer el entorno desde el
  repositorio; lo que sí es verificable es que si estuvieran definidas, **todo timbrado reventaría
  con `NotImplementedError` → 500**, porque la implementación no existe. Es decir: hoy o se simula, o
  se cae.
- **No se genera XML.** El payload que recibe `stamp()` es un `dict` plano de 14 claves
  (`services.py:1186-1202`); no hay serialización a XML del SAT, ni sellado con CSD, ni cadena
  original.
- **No hay conceptos en el comprobante.** El payload no incluye ninguna línea: solo `subtotal` y
  `total`, ambos iguales a `payment.amount` (`:1200-1201`). Las claves SAT del catálogo
  (`sat_product_key`, `sat_unit_key`) **nunca se leen** — verificado por búsqueda: solo aparecen en el
  modelo, el serializer de salida y los serializers de entrada del catálogo.
- **No hay impuestos.** `subtotal == total` siempre → B-FIN-16.
- **No hay validación fiscal de nada**: ni RFC (formato ni dígito verificador), ni régimen contra
  `c_RegimenFiscal`, ni `cfdi_use` contra `c_UsoCFDI`, ni `payment_form` contra `c_FormaPago`. El
  `CharField` con `max_length` es la única barrera.
- **No hay reintentos, ni timeout, ni circuit breaker** en la llamada al PAC.

Esto confirma lo que dice `docs/01-analisis.md:257`: *"Timbrado real de CFDI contra un PAC. El
modelo, los endpoints y el flujo existen; nunca se probó"*. El contrato lo precisa: no es que no se
haya probado, es que **la mitad del camino no está escrita**.

---

### 6.6 Matriz de permisos del módulo

Leyenda: **✅** permitido · **❌** denegado (403) · **🔒404** el módulo no contratado devuelve 404
antes de mirar el rol (§1.4.2) · **⚙️** condicionado por `doctors_see_costs`.
Roles: **O** owner · **A** admin · **D** doctor · **N** nurse · **R** reception · **F** finance ·
**L** readonly.

| Acción | Módulo | O | A | D | N | R | F | L |
|---|---|---|---|---|---|---|---|---|
| Ver catálogo de servicios | `servicios` | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| Crear / editar / desactivar servicio | `servicios` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Ver catálogo de paquetes | `paquetes` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| Crear / editar / borrar paquete | `paquetes` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Ver / editar configuración fiscal | `cfdi` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Ver cotizaciones | `cotizaciones` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| Crear cotización | `cotizaciones` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| Enviar / aceptar / rechazar cotización | `cotizaciones` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| Descargar PDF de cotización | `cotizaciones` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| **Listar cargos** | `cobranza` | ✅ | ✅ | **⚙️** | ❌ | ✅ | ✅ | ✅ |
| **Ver un cargo por id** | `cobranza` | ✅ | ✅ | **❌ siempre** | ❌ | ✅ | ✅ | ✅ |
| Crear cargo | `cobranza` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Cancelar cargo | `cobranza` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Ver pagos (lista y detalle) | `cobranza` | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Registrar pago | `cobranza` | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ |
| Editar / borrar / revertir un pago | `cobranza` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Ver estado de cuenta del paciente** | `cobranza` | ✅ | ✅ | **⚙️** | ❌ | ✅ | ✅ | ✅ |
| Ver CFDI (lista y detalle) | `cfdi` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Emitir CFDI | `cfdi` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Cancelar CFDI | `cfdi` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Dashboard financiero | `cobranza` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Reporte de periodo (JSON y PDF) | `cobranza` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Cierre diario de caja** | `cobranza` | ✅ | ✅ | ❌ | ❌ | **✅** | ✅ | ❌ |
| Panel de retención RFM | `cobranza` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |

Sin celdas vacías: 24 acciones × 7 roles = 168 celdas resueltas.

Tres asimetrías deliberadas que conviene tener presentes:

- **Recepción** entra al cierre diario pero **no** al dashboard ni al reporte: opera caja, no ve
  analítica (`views.py:1287-1289`, `core/permissions.py:308-309`).
- **Readonly** ve todo lo financiero **menos** el cierre diario (`FinanceDeskPermission` no lo
  incluye, `views.py:99-101`).
- **Finanzas** no entra a cotizaciones ni a paquetes: decisión del cliente escrita en
  `core/permissions.py:361-365` y `:374`.

#### 6.6.1 Efecto exacto de `doctors_see_costs`

Interruptor por clínica: `ClinicSettings.doctors_see_costs`, `BooleanField` default `False`
(`MailySoft/backend/apps/clinica/models.py:258`). Lo edita owner/admin por
`PUT /api/v1/clinica/configuracion/` (`apps/clinica/services.py:237-238`).

Se hace valer en **exactamente dos clases de permiso**, ambas en `core/permissions.py` y ambas
consumidas solo por finanzas:

| Clase | Endpoint | Línea del check |
|---|---|---|
| `PatientStatementPermission` | `GET /finanzas/estado-cuenta/<patient_id>/` | `core/permissions.py:540-541` |
| `ChargeListPermission` | `GET /finanzas/cargos/` | `core/permissions.py:582-583` |

Ambas leen el flag con `_tenant_doctors_see_costs` (`core/permissions.py:461`), que cachea el
resultado en `request._doctors_see_costs` (una query por request) y **devuelve `False` ante cualquier
fallo** — tenant nulo o sin `ClinicSettings` (`:488-497`): fail-closed.

**El flag nunca amplía escrituras**: `ChargeListPermission` lo aplica solo al GET; POST/PATCH/DELETE
siguen siendo `FINANCE_CORE_ROLES` (`core/permissions.py:586-587`). Y **no cubre el detalle del
cargo**: `ChargeDetailApi` usa `FinanceChargePermission`, que no conoce el flag → un médico con el
interruptor encendido ve la lista y recibe 403 al abrir un cargo concreto (B-FIN-14). Tampoco cubre
pagos, CFDI ni ningún reporte: ahí el médico está fuera con o sin flag.

---

### 6.7 Efectos secundarios

#### 6.7.1 Bitácora (`audit_record`, §1.8.5)

13 puntos de registro, todos con `resource_id` UUID y `resource_repr` sin PII del paciente:

| Acción (`apps/audit/models.py`) | Service | Metadata |
|---|---|---|
| `CONCEPT_CREATE` `:75` | `services.py:226` | — |
| `CONCEPT_UPDATE` `:76` | `:292` (update) y `:326` (reactivar) | `changed_fields`, `sucursales_changed` / `reactivated` |
| `CONCEPT_DEACTIVATE` `:77` | `:311` | — |
| `FISCAL_CONFIG_UPDATE` `:86` | `:379` | `changed_fields` |
| `QUOTE_CREATE` `:78` | `:494` | `items` (conteo) |
| `QUOTE_STATUS` `:80` | `:579` (enviar), `:625` (aceptar), `:644` (rechazar/vencer) | `new_status`, `charges_created` |
| `PACKAGE_CREATE` `:87` | `:755` | `items` |
| `PACKAGE_UPDATE` `:88` | `:829` | `items`, `sucursales_changed` |
| `PACKAGE_DELETE` `:89` | `:845` | — |
| `CHARGE_CREATE` `:81` | `:906` | `amount` (string) |
| `CHARGE_CANCEL` `:82` | `:932` | — |
| `PAYMENT_REGISTER` `:83` | `:1096` | `amount`, `method`, `allocations` (conteo) |
| `CFDI_ISSUE` `:84` | `:1227` | `total` |
| `CFDI_CANCEL` `:85` | `:1265` | `reason` |

Dos observaciones verificables: `QUOTE_UPDATE` existe en el catálogo de acciones
(`apps/audit/models.py:79`) pero **ningún service de finanzas la emite**; y `charge_cancel` registra
sin el monto, a diferencia de `charge_create`.

Todas las llamadas ocurren **fuera** del `transaction.atomic()` correspondiente (p. ej.
`services.py:494` tras el bloque abierto en `:478`), así que un fallo de la bitácora no revierte la
operación — coherente con el diseño de `audit_record`, que además absorbe toda excepción (§1.8.5).

#### 6.7.2 Notificaciones

**Ninguna.** Finanzas no crea `Notification` ni dispara correo ni WhatsApp: verificado por ausencia de
cualquier import de `apps.notificaciones` en toda la app. Una cotización "enviada" solo cambia de
estado; el envío al paciente es manual, fuera del sistema.

#### 6.7.3 PDFs y Celery

Dos generadores registrados en `FinanzasConfig.ready()` (`finanzas/apps.py:28-35`):

| `kind` | Builder | Permiso revalidado al descargar |
|---|---|---|
| `quote` | `build_quote_pdf` (`finanzas/pdf_jobs.py:15`) | `QuotePermission` |
| `finance_report` | `build_finance_report_pdf` (`:28`) | `FinanceDashboardPermission` |

Flujo: la vista encola con `pdf_job_enqueue` y responde **202** `{job_id, status}`; Celery genera; el
front consulta `GET /api/v1/pdfs/job/<id>/` y descarga en `.../file/`. Ambos endpoints declaran solo
`IsAuthenticated` y revalidan el permiso registrado para el `kind`, respondiendo **404** si falla
(`MailySoft/backend/apps/pdfs/views.py:36-42, 63-68, 93-94`), tal como describe §1.3.6.

**Límite conocido:** esa revalidación es **solo por rol**. No re-verifica el alcance por sucursal ni
que el job sea del usuario que lo pidió; el aislamiento entre clínicas lo sostiene `pdf_job_get`
(tenant). Consecuencia práctica: un admin acotado a la sede Norte, con el `job_id` de un PDF de
cotización encolado por alguien de Centro, pasaría el filtro de rol. Es un hueco de `apps/pdfs`, no de
finanzas; se anota aquí porque finanzas es el consumidor.

Ambos PDFs se generan con `cache_key=""` (siempre frescos) porque los datos son mutables
(`views.py:738`, `:1264`). WeasyPrint corre con `_secure_fetcher`, que solo admite data URIs y bloquea
`file://` y `http://` (`finanzas/pdf.py:51-73`).

**No hay ninguna tarea periódica de finanzas**: ni vencimiento de cotizaciones, ni recordatorios de
cobro, ni cierre automático. Verificado por ausencia de `tasks.py` en la app y de cualquier entrada
de finanzas en la configuración de Celery beat.

#### 6.7.4 Caché de Redis

`finanzas/cache.py`. Invalidación **por versión**, no por patrón: cada tenant tiene el contador
`finance:ver:<tenant_id>` (`:22`) y las claves lo incluyen (`:50`). Al guardar o borrar un `Payment`,
`Charge` o `Quote`, la señal `post_save`/`post_delete` incrementa la versión y todas las claves viejas
quedan inalcanzables (`:59-81`). TTL de 300 s como red de seguridad (`:18`).

| Endpoint | Cacheado | Clave |
|---|---|---|
| Dashboard | **sí** | `dash:<from>:<to>:<scope>` (`selectors.py:509-511`) |
| Reporte de periodo (JSON y el que recalcula el PDF) | **sí** | `report:<from>:<to>:<group>:<scope>` (`:759-762`) |
| Cierre diario | **no** | `finance_daily_sheet` no pasa por la caché (`:1024`) |
| Estado de cuenta | **no** | `:364` |
| Panel de retención | **no** | `retention_panel_build` no usa caché (`retention.py:315`) |

El **alcance de sucursal siempre forma parte de la clave** vía `_scope_suffix`
(`selectors.py:56-66`), con la razón de privacidad escrita en el docstring: sin ese sufijo un admin de
la sede A leería el valor cacheado del dueño. `PaymentAllocation` **no** dispara invalidación, pero
toda aplicación de pago escribe también el `Charge` (`services.py:951`), que sí la dispara.

#### 6.7.5 Consumidores externos de esta app

- `apps/expediente/services_calendarizacion.py:59` importa **`quote_create`** de finanzas: el módulo
  `calendarizacion` genera cotizaciones desde un plan de tratamiento. Toda la aritmética de descuentos
  de §6.3.2 aplica también por ese camino, y por eso el service revalida los rangos aunque el
  serializer de la vista de finanzas ya lo haya hecho (`views.py:552-556`).
- `apps/expediente/views_calendarizacion.py:73-74` y `services_catalogos.py:12` consumen
  `TreatmentPackage` y los services del catálogo.
- `apps/agenda/services.py:487-507` valida un `quote_id` al crear una cita: exige mismo tenant, mismo
  paciente y **estado `ACCEPTED`**.

#### 6.7.6 Escala del panel de retención

`retention_panel_build` (`retention.py:315`) calcula **todo en vivo, sin tabla intermedia ni caché**.
Consultas por petición:

1. `_rfm_rows` (`:151`): una agregación sobre **todas** las citas `ATTENDED` del tenant —
   `values("patient_id").annotate(Max, Min, Count, Subquery(pagos 12m))` (`:192-214`). **Sin cota
   temporal en la base**: `Max`/`Min` recorren el histórico completo.
2. Un bucle Python sobre el resultado, un registro por paciente con historial (`:219-235`).
3. `past_visits_qs` (`:360`): segunda agregación sobre el rango 12-24 meses.
4. `_compute_vip_threshold` (`:240`): ordena en memoria los gastos de todos los pacientes.
5. `_build_actionable_list` ×2 (`:413`): un `SELECT` con `id__in` de hasta 500 UUIDs cada uno.
6. `_compute_metrics` (`:469`): 6 consultas más, una de ellas materializa **el conjunto completo de
   pacientes activos en Python** y lo reinyecta como `patient_id__in=active_patient_ids`
   (`:555-573`) — un `IN` que crece linealmente con la clínica.

Con 1-3 usuarios concurrentes y clínicas de tamaño normal esto es aceptable, y el propio docstring
reconoce que "puede tardar >200 ms en clínicas grandes" y promete caché "en v2"
(`views.py:1357-1358`). Lo que hay que dejar escrito es que **el coste crece con el histórico
completo, no con el periodo consultado**, y que a diferencia del dashboard este endpoint no tiene ni
caché ni TTL. → B-FIN-20.
## 7. Mi Consultorio (configuración de la clínica)

> Extraído del código el 2026-08-12 (modo inverso). Alcance leído: `apps/clinica/models.py`,
> `urls.py`, `views.py`, `permissions.py`, `serializers.py`, `selectors.py`, `services.py` y sus
> migraciones. **`apps/clinica/sucursal_scope.py` no se re-documenta aquí**: vive en §1.5 y se cita.
> Lo transversal (aislamiento, auth, formato de error, paginación, throttling, modelos base) está en
> §1 y tampoco se repite.

Ocho modelos, 13 rutas, 32 operaciones HTTP. Todo bajo el prefijo `/api/v1/` (`config/urls.py:48`).

**Ningún endpoint de esta app lleva guard de módulo.** Verificado: la única importación de
`apps.core.entitlement_guards` en toda la app es `assert_within_limit`
(`MailySoft/backend/apps/clinica/services.py:40`). Mi Consultorio no es un módulo vendible del
catálogo (§1.4.1) — pero eso arrastra una consecuencia documentada en B-CLI-04.

**Ningún endpoint de esta app acota por sede salvo los dos de `Sucursal`.** Plantillas, categorías,
equipo, perfil médico y credenciales son catálogos de negocio compartidos por todas las sedes del
tenant; el aislamiento efectivo es solo el de tenant (§1.1).

---

### 7.1 Modelo de datos

Los ocho modelos heredan `TenantAwareModel` (§1.8.2): `id` UUID, `created_at`/`updated_at`/
`deleted_at`, `tenant` FK **PROTECT**, `created_by` FK **SET_NULL**, managers `objects`
(`TenantManager`) y `all_objects`. Todos tienen migración RLS con `ENABLE` + `FORCE` + policy con
`USING`/`WITH CHECK` y el fallback `IS NULL`.

| Modelo | Tabla | Migración RLS |
|---|---|---|
| `ClinicSettings` | `clinica_settings` | `clinica/migrations/0002_enable_rls.py:20-24` |
| `ClinicTemplate` | `clinica_templates` | ídem |
| `PatientCategory` | `clinica_patient_categories` | ídem |
| `DoctorUniversity` | `clinica_doctor_universities` | ídem |
| `DoctorCredential` | `clinica_doctor_credentials` | `clinica/migrations/0005_rls_doctor_credential.py` |
| `ClinicTeamMember` | `clinica_team_members` | `clinica/migrations/0015_rls_clinic_team_members.py` |
| `Sucursal` | `clinica_sucursales` | `clinica/migrations/0017_rls_sucursal.py` |
| `MembershipSucursal` | `tenancy_membership_sucursales` | `clinica/migrations/0018_rls_membership_sucursales.py:16-26` |

El `WITH CHECK` de `0002_enable_rls.py:42` nació **sin** el fallback `IS NULL` y se corrigió después
en `clinica/migrations/0013_rls_with_check_null_fallback.py`.

#### 7.1.1 `ClinicSettings` — `clinica_settings` (`models.py:121`)

Configuración única por clínica: identidad visual, contacto, membretes y el interruptor de costos.

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `logo` | `ImageField(max_length=255)` | sí | `NULL` | `upload_to=clinic_logo_path` → `clinica/<tenant_id>/logo/<uuid>.<ext>` (`models.py:53-60`). Validador `validate_clinic_image` = JPEG/PNG/WEBP ≤5 MB (`models.py:111-113`, §1.8.4) |
| `address` | `CharField(300)` | no | `""` | |
| `address_2` | `CharField(300)` | no | `""` | Colonia/referencias |
| `phone` | `CharField(30)` | no | `""` | |
| `mobile` | `CharField(30)` | no | `""` | WhatsApp |
| `email` | `CharField(254)` | no | `""` | `CharField`, **no** `EmailField`: la validación de formato solo la hace el serializer (`serializers.py:186`) |
| `website` | `CharField(200)` | no | `""` | |
| `facebook` / `instagram` / `youtube` | `CharField(200)` | no | `""` | URL o `@handle` |
| `letterhead_full` | `ImageField(255)` | sí | `NULL` | Membrete de hoja carta |
| `letterhead_half` | `ImageField(255)` | sí | `NULL` | Membrete de media hoja |
| `letterhead_full_spaces` | `PositiveIntegerField` | no | `0` | `MaxValueValidator(200)` declarado anti-DoS de altura de PDF (`models.py:215-222`); el serializer tope a **100** (`serializers.py:193`) → B-CLI-06 |
| `letterhead_half_spaces` | `PositiveIntegerField` | no | `0` | ídem |
| `commercial_name` | `CharField(200)` | no | `""` | COFEPRIS F2. Puede diferir de `Tenant.name` |
| `brand_color` | `CharField(7)` | no | `"#9A7B1E"` | `validate_hex_color` = `^#[0-9A-Fa-f]{6}$` (`models.py:28`, `:31`) |
| `doctors_see_costs` | `BooleanField` | no | `False` | **`db_index=True`** (`models.py:260`). Decisión D-2 |

- **Constraint:** `UniqueConstraint(tenant) WHERE deleted_at IS NULL` = `clinic_settings_tenant_active_uniq`
  (`models.py:272-276`). Una sola configuración viva por clínica; un registro soft-borrado no bloquea
  recrearla.
- **Índices existentes:** PK, el único parcial de arriba, `created_at`, `deleted_at`, `tenant`
  (FK) y `doctors_see_costs`.
- **Índice `doctors_see_costs`: peso muerto.** La consulta que lo usaría es
  `_tenant_doctors_see_costs()` (§1.3.3, `apps/core/permissions.py:461`), que busca por `tenant_id`,
  no por el booleano. Con **una fila por clínica**, cualquier índice sobre una columna que no sea
  `tenant` no puede reducir nada. No propongo índices nuevos aquí; propongo revisar este.
- `ordering = ["-created_at"]` (`models.py:269`).

#### 7.1.2 `ClinicTemplate` — `clinica_templates` (`models.py:296`)

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `kind` | `CharField(20)` choices `recipe`/`document`/`consent` (`models.py:288`) | no | — | `db_index=True` |
| `name` | `CharField(200)` | no | — | |
| `body` | `TextField` | no | — | Texto libre con `{placeholder}`; el serializer rechaza etiquetas HTML reales (`serializers.py:51`, `:305`) |
| `group` | `CharField(100)` | no | `""` | Agrupador temático ("PECAJEN", "ONCOLOGÍA") |
| `is_active` | `BooleanField` | no | `True` | `db_index=True`. DELETE = `is_active=False` |

- **Índice:** `clinic_tmpl_tenant_kind_idx (tenant, kind)` (`models.py:334-338`). Consulta que lo
  justifica: `clinic_template_list(kind=...)` (`selectors.py:87-92`) — el filtro por tipo del
  redactor de recetas, que es la única lectura del modelo.
- Sin unicidad de nombre: dos plantillas pueden llamarse igual.
- `ordering = ["kind", "name"]`.

#### 7.1.3 `PatientCategory` — `clinica_patient_categories` (`models.py:350`)

Etiquetas del catálogo de pacientes. Dos son "de sistema" y no se borran.

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `name` | `CharField(100)` | no | — | |
| `kind` | `CharField(10)` choices `custom`/`favorite`/`vip` (`models.py:362-367`) | no | `custom` | `db_index=True`. **No se puede fijar por API**: el serializer de entrada solo acepta `name` (`serializers.py:380`) |
| `is_active` | `BooleanField` | no | `True` | `db_index=True` |

- **Constraints** (`models.py:389-401`):
  - `clinic_category_tenant_name_active_uniq` = `UniqueConstraint(tenant, name) WHERE deleted_at IS NULL`.
  - `clinic_category_one_system_per_kind` = `UniqueConstraint(tenant, kind) WHERE deleted_at IS NULL AND kind <> 'custom'`.
- **Trampa real:** la unicidad se condiciona a `deleted_at`, pero la baja de la API es `is_active=False`
  (`services.py:469`). Una categoría desactivada sigue ocupando su nombre y no aparece en ningún
  listado → B-CLI-10.
- Propiedad `is_system` = `kind != custom` (`models.py:403-406`).
- Semilla idempotente `seed_system_patient_categories(tenant)` (`services.py:490`) crea "Favorito" y
  "VIP"; la invocan `apps/plataforma/services.py:306` (alta de clínica) y
  `apps/pacientes/services.py:468`.

#### 7.1.4 `DoctorUniversity` — `clinica_doctor_universities` (`models.py:417`)

| Campo | Tipo | `on_delete` | Null | Consecuencia real |
|---|---|---|---|---|
| `doctor` | FK `personal.Doctor`, `related_name="universities"` | **CASCADE** | no | Borrar en duro un `Doctor` arrastra sus logos. Como `Doctor` solo se desactiva (`is_active=False`, nunca `DELETE`), en la práctica no dispara nunca |
| `logo` | `ImageField` | — | no | **Obligatorio**: es la razón de ser del modelo |
| `name` | `CharField(200)` | — | no (`""`) | Opcional si el logo basta |

- Sin constraints ni índices propios más allá de los de `TenantAwareModel` y la FK. `ordering = ["name"]`.
- `clean()` (`models.py:453-461`) intenta validar que el doctor sea del mismo tenant leyendo un
  atributo `_doctor_cache_tenant_id` que **nadie escribe** (verificado por búsqueda en `apps/`): en
  la práctica es un no-op. La validación real la hace `doctor_university_create`
  (`services.py:599-600`).
- **Borrado físico** por decisión explícita (`services.py:627-631`), a diferencia del resto del sistema.

#### 7.1.5 `DoctorCredential` — `clinica_doctor_credentials` (`models.py:494`)

Credenciales académicas estructuradas para COFEPRIS 2026. Sustituye funcionalmente al texto libre
`Doctor.cedulas_adicionales`, que se conserva por compatibilidad.

| Campo | Tipo | `on_delete` | Null | Default | Notas |
|---|---|---|---|---|---|
| `doctor` | FK `personal.Doctor`, `related_name="credentials"`, `db_index=True` | **CASCADE** | no | — | Igual que arriba: no dispara porque `Doctor` no se borra en duro |
| `title` | `CharField(200)` | — | no | — | Sin abreviaturas |
| `institution` | `CharField(200)` | — | no | — | Obligatorio por COFEPRIS |
| `credential_number` | `CharField(60)` | — | no | `""` | El serializer exige solo dígitos si no está vacío (`serializers.py:523-534`) |
| `kind` | `CharField(20)` choices `profesional`/`especialidad`/`posgrado` (`models.py:469-478`) | — | no | — | `db_index=True` |
| `order` | `PositiveSmallIntegerField` | — | no | `0` | Posición en el membrete |
| `logo` | `ImageField(255)` | — | sí | `NULL` | Logo de la institución emisora |
| `is_active` | `BooleanField` | — | no | `True` | `db_index=True`. DELETE = baja lógica |
| `validation_status` | `CharField(12)` choices `pendiente`/`validada`/`rechazada` (`models.py:481-491`) | — | no | `pendiente` | `db_index=True` |
| `validation_note` | `CharField(300)` | — | no | `""` | Motivo del rechazo |

- **Sin `UniqueConstraint` a propósito**: un médico puede tener dos especialidades (`models.py:511-513`).
- **Índices:** `cred_tenant_doctor_idx (tenant, doctor)` y `cred_tenant_doctor_kind_idx (tenant, doctor, kind)`
  (`models.py:599-608`). El primero lo justifica `doctor_credential_list(doctor_id=...)`
  (`selectors.py:150-152`), que corre en cada apertura del perfil médico y en cada PDF de receta
  (`apps/recetas/pdf.py:301-306`). **El segundo no tiene consulta que lo justifique**: ningún
  selector ni service filtra por `kind` (verificado en `apps/clinica` y `apps/recetas`). Es peso
  muerto en cada alta de credencial.
- `ordering = ["doctor", "order", "id"]`.
- La migración `0008_doctorcredential_validation_note_and_more.py:14` dejó **validadas** todas las
  credenciales que ya existían, porque estaban en uso.

#### 7.1.6 `ClinicTeamMember` — `clinica_team_members` (`models.py:622`)

Catálogo del equipo por departamento. Lo consume `apps.expediente.services_plan_integral`, que
**snapshotea la lista completa** dentro de `LongevityPlan.equipo` al emitir la constancia
(`models.py:626-631`); el cliente nunca envía ese campo.

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `departamento` | `CharField(160)` | no | — | "Nutrición", "Enfermería" |
| `nombre` | `CharField(160)` | no | — | |
| `order` | `PositiveSmallIntegerField` | no | `0` | Orden en el listado y en el PDF |
| `is_active` | `BooleanField` | no | `True` | `db_index=True` |

- Sin constraints ni índices propios. `ordering = ["order", "departamento", "nombre"]`.
- Tiene **dos** bajas distintas: `is_active=False` (ocultar, `services.py:1029`) y `deleted_at`
  (`clinic_team_member_delete`, `services.py:1044-1047`, que es lo que hace el DELETE HTTP).

#### 7.1.7 `Sucursal` — `clinica_sucursales` (`models.py:676`)

La sede vive **dentro** del tenant; no es un tenant nuevo. El aislamiento duro sigue siendo por
`tenant_id` vía RLS y la sucursal es una segunda dimensión operativa (`models.py:665-673`, §1.5).

| Campo | Tipo | Null | Default | Notas |
|---|---|---|---|---|
| `name` | `CharField(160)` | no | — | Único por tenant |
| `address` | `CharField(255)` | no | `""` | |
| `phone` | `CharField(40)` | no | `""` | |
| `color_hex` | `CharField(7)` | no | `""` | `validate_hex_color`. Declarado "uso futuro Fase 2" (`models.py:711-714`) |
| `is_active` | `BooleanField` | no | `True` | `db_index=True`. DELETE = `is_active=False` |
| `is_default` | `BooleanField` | no | `False` | `db_index=True`. Solo por `sucursal_set_default` |

- **Constraints** (`models.py:733-743`, migración `0016_...:182-195`):
  - `sucursal_tenant_name_uniq` = `UniqueConstraint(tenant, name)` — **sin** condición sobre
    `deleted_at`, aunque el service sí la aplica (`services.py:1111`) → B-CLI-07.
  - `sucursal_tenant_one_default_uniq` = `UniqueConstraint(tenant) WHERE is_default=True`. Es la
    razón de que `sucursal_set_default` desmarque la anterior **antes** de marcar la nueva, dentro
    de una transacción (`services.py:1271-1277`).
- **Índices existentes:** PK, los dos únicos, `is_active`, `is_default`, `created_at`, `deleted_at`,
  `tenant`. No propongo ninguno: con un puñado de sedes por clínica, un índice más solo encarece
  cada escritura.
- La sede "Sucursal Principal" (`is_default=True`) de cada clínica existente la creó la migración de
  datos **`apps/personal/migrations/0009_backfill_sucursal_principal.py:54-63`**, no la "migración de
  backfill 0019" que menciona el docstring del modelo (`models.py:682`) → B-CLI-13.

#### 7.1.8 `MembershipSucursal` — `tenancy_membership_sucursales` (`models.py:749`)

Asigna una `TenantMembership` a una `Sucursal`. Es la tabla que define el alcance de sede de todo el
mundo **menos el owner**, cuyo acceso a todas las sedes es implícito por rol (§1.5.2).

| Campo | Tipo | `on_delete` | Null | Consecuencia real |
|---|---|---|---|---|
| `membership` | FK `tenancy.TenantMembership`, `related_name="sucursales_asignadas"` | **CASCADE** | no | Borrar en duro una membresía se lleva sus asignaciones; correcto, no hay nada que conservar |
| `sucursal` | FK `Sucursal`, `related_name="membresias"` | **CASCADE** | no | Borrar en duro una sede se lleva las asignaciones. No dispara nunca: la sede solo se desactiva |
| `tenant` | FK `Tenant` (heredado) | **PROTECT** | no | Es un `TenantAwareModel` explícito, a diferencia de las tablas intermedias auto-generadas de un M2M (§1.8.3) |

- **Constraint:** `membership_sucursal_uniq = UniqueConstraint(membership, sucursal)` (`models.py:782-785`).
- `ordering = ["-created_at"]`.
- **El service la borra en duro** (`services.py:1444-1446`, `.delete()`), aunque el modelo tiene
  `deleted_at` y el selector filtra por él (`selectors.py:308-311`) → B-CLI-08.

---

### 7.2 Endpoints

Todas las vistas heredan de `TenantAPIView` (§1.1.2) y por tanto resuelven tenant, rol, GUC y
contexto de bitácora antes de correr. Convenciones globales (auth, formato de error, throttling,
paginación) en §1.7. Errores comunes que **no** se repiten endpoint por endpoint:

- **401** sin `Authorization: Bearer` válido.
- **403** `{"detail": "..."}` por rol insuficiente (§1.3.1), o `{"detail": "...", "code": "password_change_required"}` con contraseña temporal pendiente (§1.2.4).
- **403** `{"detail": "No se encontró un tenant activo."}` cuando `get_current_tenant()` es `None` en un handler de escritura (p. ej. `views.py:134-137`, `:222-226`, `:344-347`).
- **405** si el método no está ruteado en la vista.
- **429** por throttle `user` 300/min.

#### 7.2.1 Configuración de la clínica

| Método | Ruta | Vista:línea | Permiso | Guard de módulo |
|---|---|---|---|---|
| GET | `/api/v1/clinica/configuracion/` | `views.py:130` | `IsAuthenticated` + `ClinicSettingsPermission` (§1.3.5) → O A D N L | ninguno |
| PUT | `/api/v1/clinica/configuracion/` | `views.py:145` | ídem → **PUT solo O A** | ninguno |

**GET** — sin query params. Respuesta **200** (`ClinicSettingsOutputSerializer`, `serializers.py:258`):

```json
{
  "id": "uuid", "commercial_name": "", "logo": null,
  "address": "", "address_2": "", "phone": "", "mobile": "", "email": "",
  "website": "", "facebook": "", "instagram": "", "youtube": "",
  "letterhead_full": null, "letterhead_half": null,
  "letterhead_full_spaces": 0, "letterhead_half_spaces": 0,
  "brand_color": "#9A7B1E", "doctors_see_costs": false,
  "created_at": "...", "updated_at": "..."
}
```

**Si la clínica todavía no tiene configuración responde `204 No Content` con cuerpo vacío**
(`views.py:139-141`), no un 404 ni un objeto con nulos. El front tiene que tratar el 204.

**PUT** — `multipart/form-data` (imágenes) o JSON. Es un **upsert parcial**: crea si no existe,
y solo toca los campos presentes (`views.py:171`, `services.py:241-242`). Campos aceptados
(`ClinicSettingsInputSerializer`, `serializers.py:162`), todos opcionales:
`logo`, `commercial_name`, `address`, `address_2`, `phone`, `mobile`, `email`, `website`,
`facebook`, `instagram`, `youtube`, `letterhead_full`, `letterhead_half`,
`letterhead_full_spaces` (0-100), `letterhead_half_spaces` (0-100), `doctors_see_costs`, `brand_color`.

- Campo no declarado → **400** `{"<campo>": ["Campo no permitido."]}` (`serializers.py:82-84`).
- `phone`/`mobile` contra `^\+?[\d\s\-\(\)]{7,20}$` (`serializers.py:47`).
- `facebook`/`instagram`/`youtube`: se rechazan etiquetas HTML reales y caracteres de control, se
  permiten `@handle` y URLs (`serializers.py:115-137`).
- Imágenes: `SecureImageField` corre `validate_image` — JPEG/PNG/WEBP reales, ≤5 MB (`serializers.py:140-154`, §1.8.4).
- Cuerpo vacío → **400** `{"detail": "No se proporcionaron campos para actualizar."}` (`views.py:154-158`).
- Éxito: **200** con el objeto completo (no 201 aunque lo haya creado).
- **Enviar `logo: null` no borra el logo**: el service solo asigna la imagen si no es `None`
  (`services.py:227-232`) → B-CLI-03.

#### 7.2.2 Plantillas clínicas

| Método | Ruta | Vista:línea | Permiso |
|---|---|---|---|
| GET | `/api/v1/clinica/plantillas/` | `views.py:195` | `ClinicTemplatePermission` → GET O A D N L |
| POST | `/api/v1/clinica/plantillas/` | `views.py:216` | → O A D |
| GET | `/api/v1/clinica/plantillas/<uuid:template_id>/` | `views.py:266` | → O A D N L |
| PATCH | `/api/v1/clinica/plantillas/<uuid:template_id>/` | `views.py:272` | → O A D |
| DELETE | `/api/v1/clinica/plantillas/<uuid:template_id>/` | `views.py:300` | → O A D |

- **GET lista**: paginada (`PageNumberPagination` estándar, 25/página, §1.7.1), solo `is_active=True`,
  ordenada por `kind, name` (`selectors.py:87-92`). Filtro: `?kind=recipe|document|consent`.
  **El valor de `kind` no se valida**: uno inválido devuelve una página vacía, no 400 (`views.py:200`).
- **POST**: `{kind, name, body, group?}`. `body` ≤50 000 caracteres y sin etiquetas HTML
  (`serializers.py:302`, `:311-316`). Éxito **201**. Errores: 400 de serializer,
  400 `{"detail": ["Tipo de plantilla inválido '<x>'. ..."]}` del service (`services.py:299-303`).
- **PATCH**: `{kind?, name?, body?, group?}`. `is_active` **no** es aceptable: está en
  `_TEMPLATE_IMMUTABLE` (`services.py:117-119`) y ni siquiera se declara en el serializer. Cuerpo
  vacío → 400. Éxito **200**.
- **DELETE**: baja lógica `is_active=False` (`services.py:385-386`). Éxito **204** sin cuerpo.
- Cualquier id de otro tenant o inexistente → **404** `{"detail": "Plantilla no encontrada."}`
  (`views.py:261-264`). **No hay forma de listar ni reactivar una plantilla desactivada.**

#### 7.2.3 Categorías (etiquetas) de paciente

| Método | Ruta | Vista:línea | Permiso |
|---|---|---|---|
| GET | `/api/v1/clinica/categorias/` | `views.py:321` | `PatientCategoryPermission` → GET todos los roles |
| POST | `/api/v1/clinica/categorias/` | `views.py:337` | → O A |
| DELETE | `/api/v1/clinica/categorias/<uuid:category_id>/` | `views.py:384` | → O A |

- **GET**: paginado, solo activas, orden por `name` (`selectors.py:118`). Sin filtros.
  Respuesta por elemento: `{id, name, kind, is_active, created_at}` (`serializers.py:393`).
- **POST**: `{name}` y nada más. `kind` siempre queda en `custom`. Duplicado → **400**
  `{"detail": ["Ya existe una categoría con el nombre '<x>' en esta clínica."]}` (`services.py:430`).
  Éxito **201**.
- **DELETE**: `is_active=False`. Sobre una etiqueta de sistema (Favorito/VIP) → **400**
  `{"detail": ["Las etiquetas del sistema (Favorito y VIP) no se pueden eliminar."]}`
  (`services.py:467-468`). Éxito **204**.
- **`PatientCategoryDetailApi` solo implementa `delete`** (`views.py:367`): `GET` y `PATCH` a
  `/clinica/categorias/<id>/` responden **405**. No existe renombrar ni reactivar → B-CLI-10.

#### 7.2.4 Perfil ampliado del médico

| Método | Ruta | Vista:línea | Permiso |
|---|---|---|---|
| PATCH | `/api/v1/clinica/doctores/<uuid:doctor_id>/perfil/` | `views.py:423` | `DoctorProfilePermission` → O A D |

- Entrada (`DoctorProfileImageInputSerializer`, `serializers.py:429`), todos opcionales:
  `sello` (imagen), `foto` (imagen), `cedulas_adicionales` (≤500, texto separado por comas validado
  con `validar_cedulas_adicionales`, §1.8.4).
- **Granularidad por objeto en la vista**: si `request.active_role == "doctor"` y
  `doctor.membership_id != request.membership.id` → **403**
  `{"detail": "Solo puedes modificar tu propio perfil médico."}` (`views.py:440-448`). Owner y admin
  no tienen esa restricción **ni ninguna de sede**.
- Doctor inexistente o de otro tenant → **404** `{"detail": "Médico no encontrado."}`.
- Cuerpo vacío → **400**. Éxito **200** con `DoctorOutputSerializer` de `apps/personal` (§8.2.1),
  releído con prefetch (`views.py:465-469`).
- `sello: null` / `foto: null` **no borran** la imagen (`services.py:542-547`) → B-CLI-03.

#### 7.2.5 Universidades del médico

| Método | Ruta | Vista:línea | Permiso |
|---|---|---|---|
| GET | `/api/v1/clinica/doctores/<uuid:doctor_id>/universidades/` | `views.py:494` | `DoctorProfilePermission` → GET todos los roles |
| POST | `/api/v1/clinica/doctores/<uuid:doctor_id>/universidades/` | `views.py:503` | → O A D |
| DELETE | `/api/v1/clinica/universidades/<uuid:university_id>/` | `views.py:566` | → O A D |

- **GET**: **array plano sin paginar** (`views.py:501`), orden por `name`. Elemento:
  `{id, logo, name, created_at}`.
- **POST**: `multipart/form-data` con `logo` (obligatorio) y `name` (opcional). Mismo guard M-1 del
  doctor sobre su propio perfil (`views.py:510-517`). Doctor de otro tenant → 400
  `{"detail": ["El médico no pertenece a esta clínica."]}` (`services.py:599-600`). Éxito **201**.
- **DELETE**: **borrado físico** del registro y del archivo asociado (`services.py:645`). Guard M-1
  igual (`views.py:572-580`). Éxito **204**.

#### 7.2.6 Credenciales del médico (COFEPRIS F2)

| Método | Ruta | Vista:línea | Permiso |
|---|---|---|---|
| GET | `/api/v1/clinica/doctores/<uuid:doctor_id>/credenciales/` | `views.py:616` | `DoctorProfilePermission` → GET todos los roles |
| POST | `/api/v1/clinica/doctores/<uuid:doctor_id>/credenciales/` | `views.py:625` | → O A D |
| PATCH | `/api/v1/clinica/credenciales/<uuid:credential_id>/` | `views.py:699` | → O A D |
| DELETE | `/api/v1/clinica/credenciales/<uuid:credential_id>/` | `views.py:738` | → O A D |
| GET | `/api/v1/clinica/credenciales/` | `views.py:771` | **`IsAuthenticated` solo**; el rol se compara a mano contra `("owner","admin")` |
| PATCH | `/api/v1/clinica/credenciales/<uuid:credential_id>/validar/` | `views.py:797` | ídem |

Las dos últimas comparan `request.active_role` con literales de cadena en vez de usar una clase de
permiso (`views.py:772-777`, `:798-803`) — es la brecha **B-T-08** ya registrada en §1.3.6.

- **POST/PATCH** aceptan `multipart/form-data`, `application/x-www-form-urlencoded` y JSON
  (`views.py:604`, `:685`). Entrada (`serializers.py:461`): `title` (req.), `institution` (req.),
  `kind` (req., whitelist), `credential_number` (opc., solo dígitos), `order` (0-999), `logo` (opc.).
- Respuesta (`DoctorCredentialOutputSerializer`, `serializers.py:542`):

```json
{
  "id":"uuid","title":"","institution":"","credential_number":"","kind":"especialidad",
  "kind_display":"Cédula de especialidad","order":0,"logo_url":null,"is_active":true,
  "validation_status":"pendiente","validation_status_display":"Pendiente de validación",
  "validation_note":"","doctor_id":"uuid","doctor_name":"Ana Ruiz","created_at":"..."
}
```

- **GET por médico**: array plano sin paginar, solo `is_active=True`, orden `order, id` (`selectors.py:150-152`).
- **PATCH detalle**: solo aplica los campos enviados. `logo` distingue "no enviado" de "enviado
  null" con `logo_provided` (`views.py:728`, `services.py:812-814`) — este endpoint **sí** permite
  quitar la imagen, a diferencia de 7.2.1 y 7.2.4.
- **DELETE detalle**: baja lógica `is_active=False`, no borrado (`services.py:915-916`), porque son
  documentos con implicación legal. Éxito **204**.
- **GET bandeja** (`/clinica/credenciales/`): array plano **sin paginar** de todas las credenciales
  activas del tenant, orden `validation_status, doctor, order, id` (`selectors.py:167-171`). Filtro
  `?status=pendiente|validada|rechazada`; valor fuera de esa lista → **400**
  `{"detail": "Estado de validación inválido."}` (`views.py:779-783`). Rol distinto de owner/admin →
  **403** `{"detail": "Solo un administrador puede ver la bandeja de validación."}`.
- **PATCH validar**: `{status: "validada"|"rechazada", note?: "≤300"}` (`serializers.py:579`).
  Enviar `"pendiente"` → 400 de serializer (no está en los choices). Éxito **200** con la credencial.

#### 7.2.7 Equipo de la clínica

| Método | Ruta | Vista:línea | Permiso |
|---|---|---|---|
| GET | `/api/v1/clinica/equipo/` | `views.py:841` | `ClinicTeamPermission` → GET O A D |
| POST | `/api/v1/clinica/equipo/` | `views.py:861` | → O A |
| GET | `/api/v1/clinica/equipo/<uuid:member_id>/` | `views.py:899` | → O A D |
| PATCH | `/api/v1/clinica/equipo/<uuid:member_id>/` | `views.py:905` | → O A |
| DELETE | `/api/v1/clinica/equipo/<uuid:member_id>/` | `views.py:933` | → O A |

- **GET lista**: paginada. Filtro `?only_active=false` para incluir los ocultos (`views.py:846`).
  Orden `order, departamento, nombre`. Elemento: `{id, departamento, nombre, order, is_active, created_at}`.
- **POST**: `{departamento, nombre, order?=0, is_active?=true}`. Éxito **201**. Sin validación de
  duplicados: dos filas idénticas son posibles.
- **PATCH**: `{departamento?, nombre?, order?, is_active?}`. La vista **separa** `is_active` y lo
  enruta a `clinic_team_member_activate` / `..._deactivate`; el resto va a `..._update`
  (`views.py:918-927`). Enviar ambos genera **dos** registros de bitácora.
- **DELETE**: pone `deleted_at` (`services.py:1046`), no `is_active`. Es la única baja irreversible
  del módulo. Éxito **204**.
- 404 → `{"detail": "Miembro del equipo no encontrado."}`.

#### 7.2.8 Sucursales

| Método | Ruta | Vista:línea | Permiso |
|---|---|---|---|
| GET | `/api/v1/clinica/sucursales/` | `views.py:961` | `SucursalPermission` → GET todos los roles |
| POST | `/api/v1/clinica/sucursales/` | `views.py:982` | → **solo owner** |
| GET | `/api/v1/clinica/sucursales/<uuid:sucursal_id>/` | `views.py:1053` | → todos los roles |
| PATCH | `/api/v1/clinica/sucursales/<uuid:sucursal_id>/` | `views.py:1059` | → **solo owner** |
| DELETE | `/api/v1/clinica/sucursales/<uuid:sucursal_id>/` | `views.py:1091` | → **solo owner** |

- **GET lista**: paginada. Devuelve `allowed_sucursales(user, tenant)` (§1.5.1), es decir **solo
  sedes activas**: owner las ve todas; cualquier otro rol solo las asignadas, o la `is_default` como
  fallback anti-lockout. Sin query params. Elemento:
  `{id, name, address, phone, color_hex, is_active, is_default, created_at, updated_at}`.
- **GET/PATCH/DELETE detalle**: `_get_or_404` acota el id contra `actor_sucursal_ids` (§1.5.1), que
  **sí incluye las inactivas**; fuera de alcance responde **404**, nunca 403 (`views.py:1042-1049`).
- **POST**: `{name, address?, phone?, color_hex?, is_default?=false}`. `color_hex` es un
  `RegexField` `^#[0-9A-Fa-f]{6}$` con mensaje propio (`serializers.py:663-670`). `is_active` no se
  expone: toda sede nace activa. Éxito **201**. Errores 400: nombre duplicado
  (`services.py:1112`) y **tope del plan** (7.3).
- **PATCH**: `{name?, address?, phone?, color_hex?, is_active?, is_default?}`. La vista enruta los
  dos booleanos a services dedicados y el resto a `sucursal_update` (`views.py:1072-1085`).
  `is_default: false` **se ignora en silencio** — solo se actúa si es `true` (`views.py:1082`), por
  diseño: siempre debe haber exactamente una sede predeterminada.
- **DELETE**: `is_active=False`. Sobre la sede predeterminada → **400**
  `{"detail": ["No se puede desactivar la sucursal predeterminada. Marca otra sucursal como predeterminada primero."]}`
  (`services.py:1237-1241`). Éxito **204**.
- `sucursal_set_default` sobre una sede inactiva → **400** (`services.py:1268-1269`).
- **Una sede desactivada desaparece de `GET /clinica/sucursales/` y no hay ningún parámetro para
  listarla** → B-CLI-02.

#### 7.2.9 Sedes asignadas a un miembro

| Método | Ruta | Vista:línea | Permiso |
|---|---|---|---|
| GET | `/api/v1/clinica/membresias/<uuid:membership_id>/sucursales/` | `views.py:1147` | `MembershipSucursalPermission` → O A |
| PUT | `/api/v1/clinica/membresias/<uuid:membership_id>/sucursales/` | `views.py:1154` | → O A |

Es el endpoint que crea el "administrador de sucursal": un `admin` con una sola fila queda acotado a
esa sede; con una fila por sede se vuelve "admin de negocio" (§1.5.2).

- Respuesta de ambos (**200**, sin paginar):
  `{"membership_id": "uuid", "sucursales": [{"id": "uuid", "name": "Centro", "is_default": true}]}`
  (`views.py:1140-1145`, `serializers.py:759`).
- **PUT**: `{"sucursal_ids": ["uuid", ...]}` — es el conjunto **completo**, reemplaza, no añade.
  Lista vacía es válida a nivel de formato (`serializers.py:748-751`).
- Reglas del service `membership_sucursales_set` (`services.py:1323`), en orden:
  1. Membresía del mismo tenant (`:1382`).
  2. Cada id existe, es del tenant y **está activo**; si no → 400 con los ids o los nombres
     (`:1396-1403`).
  3. El actor tiene membresía activa (`:1412-1413`).
  4. **Anti-escalada del admin**: la *diferencia simétrica* entre el conjunto actual y el nuevo debe
     estar contenida en su propio `allowed_sucursales` (`:1421-1431`). Las sedes que no cambian no
     se validan: un admin de Centro puede dejar intacta una asignación a Norte que ya existía.
  5. Anti-lockout del dueño: no se puede dejar al owner con la lista vacía (`:1433-1434`).
  6. Anti-lockout propio: un admin no puede vaciarse a sí mismo (`:1436-1441`).
- Membresía inexistente o de otro tenant → **404** `{"detail": "Miembro no encontrado."}`.
- **Lo que este endpoint NO valida**: la jerarquía de roles. `membership_get` solo aísla por tenant
  (`apps/tenancy/selectors.py:191-201`) y el service no comprueba el rol del objetivo → un admin
  puede leer y reescribir las sedes del dueño y de otro admin, cosa que `PATCH /miembros/<id>/` sí
  le prohíbe (`apps/tenancy/services.py:110-111`) → **B-CLI-01**.

---

### 7.3 Sucursales y límites del plan

**Multi-sucursal no es un módulo**: es el límite `max_sucursales` del plan (§1.4.1). No hay
`RequiresX` que apagar; lo único que existe es un tope numérico.

**Único punto de aplicación:** `sucursal_create` (`services.py:1116-1120`).

```
assert_within_limit(tenant, "max_sucursales",
                    actual=Sucursal.all_objects.filter(tenant=tenant, deleted_at__isnull=True).count())
```

- El conteo usa `all_objects` con filtro explícito de tenant (correcto: el service puede correr sin
  contexto de request) y **cuenta las sedes desactivadas**, porque filtra por `deleted_at`, no por
  `is_active`. Una clínica que desactiva Norte no libera cupo → B-CLI-12.
- `assert_within_limit` (`apps/core/entitlement_guards.py:123`) lanza `ValidationError` si
  `actual >= tope`; `None` = ilimitado (`:136-137`). La vista lo traduce a **400**
  `{"detail": ["El plan de esta clínica permite 1 sucursales y ya hay 1. Para ampliarlo, contacta a soporte de Maily."]}`.
- El límite se evalúa **antes** de abrir la transacción (`services.py:1116` vs `:1122`). Con 1 a 3
  usuarios concurrentes la carrera es teórica; no propongo bloqueo.
- Topes sembrados (`apps/tenancy/management/commands/seed_planes.py`): `solo` 1 (`:75`), `basico` 1
  (`:101`), `pro` **1** (`:122`), `premium` ilimitado (`:143`), `enterprise` ilimitado. **Multi-sede
  empieza en Premium**: una clínica Pro de $4 500 no puede abrir la segunda sede.
- `Entitlements.sede_unica` = `max_sucursales == 1` (§1.4.3) alimenta `capabilities` en `/me/`, así
  que el front puede ocultar el selector sin adivinar.

**Ningún otro punto del sistema consulta `max_sucursales`.** El resto de la app de sedes
(asignaciones, filtros, alcance) es independiente del plan: una clínica que baje de Premium a Pro
conserva sus sedes existentes y solo pierde la capacidad de crear otra.

---

### 7.4 Credenciales profesionales y su validación

Flujo híbrido en tres pasos, tal como está en el código:

1. **El médico captura.** `POST /clinica/doctores/<id>/credenciales/` con `DoctorProfilePermission`
   (O A D) y el guard M-1 de "solo tu propio perfil" si el actor es doctor (`views.py:631-639`). La
   credencial nace `validation_status="pendiente"` por default del campo (`models.py:581`).
2. **Se avisa a la administración.** `_notify_credential_pending` (`services.py:51`) hace fan-out a
   todos los usuarios con rol owner o admin del tenant
   (`users_with_roles(tenant, roles=["owner","admin"])`, `services.py:62`) con
   `NotificationKind.CREDENTIAL_REVIEW`. **Envuelto en `try/except Exception`**: si la notificación
   falla, el alta de la credencial no se interrumpe, solo se loguea (`services.py:74-75`).
3. **Owner o admin resuelve.** `PATCH /clinica/credenciales/<id>/validar/` con
   `status="validada"|"rechazada"` y `note` opcional. El rol se comprueba a mano contra
   `("owner","admin")` (`views.py:798-803`, B-T-08). El service `doctor_credential_set_validation`
   (`services.py:846`) revalida el estado, guarda, audita `CREDENTIAL_VALIDATE` y notifica al médico
   con `CREDENTIAL_RESULT` (`services.py:891`), también en `try/except`.

**Quién aprueba:** owner y admin, sin distinción entre ellos y **sin ninguna restricción de sede**.
Un admin acotado a Centro puede validar la cédula de un médico que solo trabaja en Norte:
`doctor_credential_get` únicamente aísla por tenant (`selectors.py:191`).

**Re-validación automática al editar.** Si un PATCH cambia `title`, `institution`,
`credential_number` o `kind` de una credencial ya resuelta, el service la devuelve a `pendiente`,
limpia `validation_note` y vuelve a notificar a la administración (`services.py:816-826`, `:841-842`).
Cambiar solo el `logo` o el `order` **no** invalida.

**Qué controla realmente el estado "validada":** solo lo que se imprime. Las credenciales validadas
son las que entran al PDF de receta (`apps/recetas/pdf.py:301-306`), al Libro Clínico y a los planes
del expediente (`apps/expediente/pdf.py:261-266`, `:616`, `:782`, `:931`).

**Qué NO controla:** el derecho a recetar. Lo que autoriza emitir una receta es el campo de texto
libre `Doctor.cedula_profesional`, que `apps/recetas/services.py:519` exige no vacío. Ese campo
**no tiene flujo de validación** y solo lo editan owner y admin por
`PATCH /api/v1/personal/doctores/<id>/` (§8.2.1). Es decir: la bandeja de validación es un control
de **presentación**, no de **habilitación**. Está bien que sea así, pero no es lo que sugiere el
nombre.

---

### 7.5 Reglas de negocio verificadas en código

1. **Una sola configuración viva por clínica.** Constraint parcial `clinic_settings_tenant_active_uniq`
   (`models.py:272-276`) + upsert en `clinic_settings_upsert` (`services.py:204-207`).
2. **El upsert de configuración es parcial de verdad.** La vista calcula
   `_partial_fields=frozenset(s.validated_data.keys())` y el service descarta todo lo demás
   (`views.py:171`, `services.py:241-242`). Un PUT con un solo campo no borra los otros nueve.
3. **`doctors_see_costs` es el único interruptor de negocio de esta app.** Se escribe por
   `PUT /clinica/configuracion/` (O A) y se lee desde `_tenant_doctors_see_costs()`
   (`apps/core/permissions.py:461`), que lo cachea por request y **falla cerrado** ante cualquier
   error. Gobierna `PatientStatementPermission` y `ChargeListPermission` (§1.3.3): con el flag
   apagado, un médico recibe 403 al pedir el estado de cuenta del paciente.
4. **Las etiquetas de sistema no se borran.** `patient_category_deactivate` rechaza `is_system`
   (`services.py:467-468`); la constraint garantiza una sola Favorito y una sola VIP por clínica.
5. **Las plantillas y las credenciales se dan de baja, no se borran.** `is_active=False`
   (`services.py:385`, `:915`). Las universidades sí se borran físicamente (`services.py:645`),
   decisión escrita en el docstring.
6. **Los campos sensibles no viajan por el PATCH genérico.** `_TEMPLATE_IMMUTABLE`
   (`services.py:117`), `_TEAM_MEMBER_IMMUTABLE` (`services.py:933`) y `_SUCURSAL_IMMUTABLE`
   (`services.py:1066`) rechazan `is_active`, `is_default`, `tenant` e ids; las vistas los enrutan a
   services dedicados.
7. **Solo el dueño administra sedes.** `SucursalPermission._OWNER_ONLY` (`permissions.py:131`),
   decisión del dueño del 2026-07-16 escrita en el docstring (`permissions.py:116-121`). Coincide con
   `docs/01-analisis.md:51`.
8. **El detalle de sede se acota por alcance del actor, no solo por tenant.** `actor_sucursal_ids`
   en `SucursalDetailApi._get_or_404` (`views.py:1042`), con 404 en vez de 403 para no revelar que
   la sede existe. Cierra el "Clúster C" citado en el docstring de la vista (`views.py:1014-1019`).
9. **No se puede desactivar la sede predeterminada** (`services.py:1237-1241`) ni marcar como
   predeterminada una inactiva (`services.py:1268-1269`). Entre las dos, una clínica siempre tiene al
   menos una sede activa.
10. **`sucursal_set_default` es atómico**: desmarca la anterior y marca la nueva dentro de
    `transaction.atomic()` para no violar el índice único parcial (`services.py:1271-1277`).
11. **Anti-escalada por diferencia simétrica.** Tanto `membership_sucursales_set`
    (`services.py:1425-1431`) como sus hermanos de `apps/personal` (§8.4) validan solo lo que
    *cambia*, no el conjunto entero. Es lo que permite que un admin de Centro edite a alguien que
    también tiene Norte sin poder tocar Norte.
12. **Un doctor solo edita su propio perfil.** Guard M-1 repetido en cuatro handlers
    (`views.py:440`, `:510`, `:572`, `:631`, `:705`, `:744`). Owner y admin no tienen esa limitación
    y tampoco tienen límite de sede.
13. **Todas las escrituras auditan** (7.7). Todas las lecturas de detalle traducen `DoesNotExist` a
    404, nunca a 403 (`views.py:8-12`).
14. **Rechazo de campos desconocidos en todos los serializers de entrada.**
    `_reject_unknown_fields` (`serializers.py:62`) → 400 `{"<campo>": ["Campo no permitido."]}`.
    Cierra el mass-assignment (decisión D-EC-7).

---

### 7.6 Matriz de permisos del módulo

**O**=owner · **A**=admin · **D**=doctor · **N**=nurse · **R**=reception · **F**=finance ·
**L**=readonly. `sí` = permitido · `no` = 403 · `propio` = solo sobre sus propios registros.
Ninguna celda queda vacía. **Ninguna fila lleva guard de módulo**, así que ninguna puede dar 404 por
entitlement.

| Acción | O | A | D | N | R | F | L |
|---|---|---|---|---|---|---|---|
| Ver configuración de la clínica (`GET /clinica/configuracion/`) | sí | sí | sí | sí | **no** | **no** | sí |
| Editar configuración, membrete, `brand_color`, `doctors_see_costs` (`PUT`) | sí | sí | no | no | no | no | no |
| Listar y ver plantillas | sí | sí | sí | sí | no | no | sí |
| Crear, editar y dar de baja plantillas | sí | sí | sí | no | no | no | no |
| Listar categorías de paciente | sí | sí | sí | sí | sí | sí | sí |
| Crear y desactivar categorías | sí | sí | no | no | no | no | no |
| Ver universidades y credenciales de un médico | sí | sí | sí | sí | sí | sí | sí |
| Editar sello, foto y cédulas adicionales | sí | sí | propio | no | no | no | no |
| Alta y baja de universidades | sí | sí | propio | no | no | no | no |
| Alta, edición y baja de credenciales | sí | sí | propio | no | no | no | no |
| Ver la bandeja de validación (`GET /clinica/credenciales/`) | sí | sí | no | no | no | no | no |
| Validar o rechazar una credencial | sí | sí | no | no | no | no | no |
| Ver el catálogo de equipo | sí | sí | sí | no | no | no | no |
| Crear, editar y borrar equipo | sí | sí | no | no | no | no | no |
| Listar sucursales (acotado por §1.5.2) | sí | sí | sí | sí | sí | sí | sí |
| Ver el detalle de una sucursal (acotado por `actor_sucursal_ids`) | sí | sí | sí | sí | sí | sí | sí |
| Crear, editar, marcar default y desactivar sucursales | sí | **no** | no | no | no | no | no |
| Ver las sedes asignadas a un miembro | sí | sí | no | no | no | no | no |
| Reasignar las sedes de un miembro | sí | sí (1) | no | no | no | no | no |

(1) El admin solo puede **agregar o quitar** sedes que él mismo tiene asignadas
(`services.py:1421-1431`), y no puede vaciarse a sí mismo. Lo que **sí** puede hoy, y probablemente
no debería, es tocar la asignación del dueño y la de otro admin → B-CLI-01.

**Notas de la matriz que conviene leer dos veces:**

- Recepción y finanzas **no pueden leer** `GET /clinica/configuracion/`: `ClinicSettingsPermission`
  usa `CLINICAL_READ` (§1.3.5), que los excluye. Cualquier pantalla que muestre el logo o el nombre
  comercial de la clínica a esos dos roles necesita otra fuente → B-CLI-11.
- El GET de universidades y credenciales está abierto a **los siete roles** (`ALL_ROLES` en
  `DoctorProfilePermission`, `permissions.py:88`), incluidos finanzas y solo-lectura. Son datos
  profesionales del médico, no clínicos del paciente.
- Ningún permiso de esta app implementa `has_object_permission` (§1.3.6): toda la granularidad fina
  vive en la vista (guard M-1) o en el service.

---

### 7.7 Efectos secundarios

Lo que ocurre **además** de escribir la fila. Todo lo que sigue está verificado en código.

| Disparador | Efecto | Referencia |
|---|---|---|
| `PUT /clinica/configuracion/` | `audit_record(CLINIC_SETTINGS_UPDATE)` con `{"created": bool, "changed_fields": [...]}` | `services.py:249-262` |
| ídem con imagen | Sube el archivo a `clinica/<tenant_id>/{logo,membretes/full,membretes/half}/<uuid>.<ext>`. **La imagen anterior queda huérfana en el storage**: nadie la borra | `models.py:53-72`, §1.8.4 |
| ídem | Cambia el color de acento de **todos** los PDFs del sistema vía `build_brand_context()`, salvo que el `PrescriptionFormat` default tenga su propio `accent_color` | §1.8.4 |
| ídem con `doctors_see_costs` | Cambia el resultado de `PatientStatementPermission` y `ChargeListPermission` para todos los médicos, en el siguiente request (la caché es por request) | §1.3.3 |
| Crear / editar / dar de baja plantilla | `TEMPLATE_CREATE` · `TEMPLATE_UPDATE` (con `changed_fields`) · `TEMPLATE_DELETE` | `services.py:315`, `:359`, `:388` |
| Crear / desactivar categoría | `PATIENT_CATEGORY_CREATE` · `PATIENT_CATEGORY_DELETE` | `services.py:439`, `:472` |
| Alta de clínica o alta de paciente sin categorías | `seed_system_patient_categories` crea Favorito y VIP con `created_by=None` | `services.py:490-509`, llamado desde `apps/plataforma/services.py:306` y `apps/pacientes/services.py:468` |
| Editar perfil médico | `DOCTOR_UPDATE` con `{"context": "profile_images"}` | `services.py:557-565` |
| Alta / baja de universidad | `DOCTOR_UPDATE` con `context` `university_create` / `university_delete`. El DELETE **borra el archivo del storage** junto con la fila | `services.py:610`, `:645-655` |
| Alta de credencial | `CREDENTIAL_CREATE` **y** notificación `CREDENTIAL_REVIEW` a todos los owner/admin del tenant | `services.py:734-743` |
| Edición académica de credencial | `CREDENTIAL_UPDATE`, regreso a `pendiente`, `validation_note` vaciada y **nueva** notificación a la administración | `services.py:816-842` |
| Validar / rechazar credencial | `CREDENTIAL_VALIDATE` + notificación `CREDENTIAL_RESULT` **al médico** (a `credential.doctor.membership.user`) | `services.py:882-891` |
| Validar credencial | Cambia lo que se imprime en las próximas recetas y en los PDFs del expediente. **No re-genera los PDFs ya emitidos** | `apps/recetas/pdf.py:301-306` |
| Baja de credencial | `CREDENTIAL_DELETE`; la credencial desaparece de los membretes futuros | `services.py:918-926` |
| Equipo: alta / edición / activar / desactivar / borrar | `CLINIC_TEAM_MEMBER_CREATE` · `..._UPDATE` (tres services distintos usan el mismo `ActionType`) · `..._DELETE` | `services.py:968`, `:1003`, `:1018`, `:1033`, `:1048` |
| Cambiar el catálogo de equipo | **No** altera los `LongevityPlan` ya emitidos: el equipo se snapshotea al crear la constancia | `models.py:626-631` |
| Crear sucursal | `SUCURSAL_CREATE`; si venía `is_default=true`, **además** `SUCURSAL_SET_DEFAULT` y la sede anterior pierde la marca | `services.py:1136-1146` |
| Editar / activar / desactivar / marcar default | `SUCURSAL_UPDATE` (con `changed_fields`) · `SUCURSAL_ACTIVATE` · `SUCURSAL_DEACTIVATE` · `SUCURSAL_SET_DEFAULT` | `services.py:1200`, `:1216`, `:1245`, `:1279` |
| Desactivar una sucursal | Desaparece de `allowed_sucursales` para todo el mundo (§1.5.1) → sus consultorios, doctores y horarios dejan de listarse para quien la tuviera como única sede. **Los `Consultorio.sucursal` y `DoctorSchedule.sucursal` siguen apuntando a ella**: no se limpia nada | `sucursal_scope.py:175-179` |
| `PUT /clinica/membresias/<id>/sucursales/` | `MEMBERSHIP_SUCURSALES_SET` con la lista de ids; **borrado físico** de las filas que sobran y `bulk_create` de las nuevas, en una transacción | `services.py:1443-1472` |
| ídem | Cambia inmediatamente el alcance operativo del miembro: qué pacientes, citas, doctores y consultorios ve (§1.5) | `sucursal_scope.py:184-197` |

Los `audit_record` **nunca tumban la operación**: absorben toda excepción (§1.8.5). Las dos
notificaciones de credenciales están además envueltas en su propio `try/except`
(`services.py:74-75`, `:105-106`).
## 8. Personal, consultorios y tipos de cita

> Extraído del código el 2026-08-12 (modo inverso). Alcance leído: `apps/personal/` completo
> (`models.py`, `urls.py`, `views.py`, `serializers.py`, `selectors.py`, `services.py`, `admin.py`,
> migraciones). Para §8.3 se leyeron además `apps/tenancy/services.py`, `apps/tenancy/views.py`,
> `apps/tenancy/selectors.py`, `apps/authn/services.py` y `apps/plataforma/services.py:1262-1289`.
> Lo transversal está en §1 y no se repite.

**Advertencia de alcance del título.** El código no está donde el nombre de esta sección sugiere:

| Lo que el usuario llama… | Vive en | Dónde se documenta |
|---|---|---|
| Doctores, consultorios, horarios | `apps/personal/` | **aquí** |
| Alta de personal, roles, bloqueo, contraseñas, avatar | `apps/tenancy/` (`/api/v1/miembros/`) | endpoints en §1.9; **reglas y autorización en §8.3** |
| Asignación de un miembro a sedes | `apps/clinica/` (`/api/v1/clinica/membresias/<id>/sucursales/`) | §7.2.9 |
| **Tipos de cita** (`AppointmentType`) | **`apps/agenda/`** (`apps/agenda/models.py:173`, `apps/agenda/views.py:784`, `apps/agenda/views.py:835`), permiso `AppointmentTypePermission` (§1.3.2 #7) y guard `RequiresAgenda` | sección de agenda del contrato, **no aquí** |
| Catálogo de equipo/departamentos | `apps/clinica/` | §7.1.6 y §7.2.7 |

`docs/01-analisis.md:164` los agrupa a todos en una sola pantalla (`PersonalPage`) y
`docs/01-analisis.md:194` mete "equipo" dentro del módulo `personal`. Esa agrupación es de interfaz,
no de código → B-PER-09.

Tres modelos propios, dos tablas intermedias auto-generadas, 6 rutas, 13 operaciones HTTP, todas bajo
`/api/v1/` (`config/urls.py:40`).

**Todas las vistas de `apps/personal` llevan guard de módulo**: `RequiresPersonal`
(`views.py:74`, `:189`, `:329`, `:420`, `:557`, `:672`). Una clínica sin el módulo `personal` recibe
**404** en las seis rutas (§1.4.2), no 403.

---

### 8.1 Modelo de datos

Los tres modelos heredan `TenantAwareModel` (§1.8.2). RLS: `personal/migrations/0002_enable_rls.py`
+ `0007_rls_with_check.py` para las tres tablas propias, y
`personal/migrations/0012_rls_doctor_m2m_through_tables.py` para las dos tablas intermedias.

#### 8.1.1 `Doctor` — `personal_doctors` (`models.py:45`)

Perfil profesional de una persona **dentro de una clínica**. Un médico que trabaja en dos clínicas
tiene dos filas `Doctor`, una por tenant, cada una con su propia cédula, sello y horarios.

| Campo | Tipo | `on_delete` | Null | Default | Consecuencia real |
|---|---|---|---|---|---|
| `membership` | FK `tenancy.TenantMembership`, `related_name="doctor_profile"` | **PROTECT** | no | — | No se puede borrar en duro una membresía que tenga perfil de médico. Es deliberado: el perfil es el ancla del historial clínico |
| `cedula_profesional` | `CharField(30)` | — | no | `""` | **Es lo único que autoriza emitir recetas** (`apps/recetas/services.py:519`). Formato `^[0-9]{5,10}$` validado solo en la vista (`views.py:101-103`, §1.8.4) |
| `specialty` | `CharField(100)` | — | no | `""` | Texto libre en v1 |
| `default_appointment_duration` | `PositiveSmallIntegerField` | — | no | `30` | Minutos. El serializer acota 5-480 (`views.py:90-94`) |
| `bio_short` | `CharField(255)` | — | no | `""` | |
| `is_active` | `BooleanField` | — | no | `True` | `db_index=True`. **Solo se puede poner en `False`**: es inmutable en `doctor_update` (`services.py:60-63`) y ningún endpoint lo reactiva → B-PER-04 |
| `consultorios` | `ManyToManyField(Consultorio)`, `related_name="doctores"`, `blank=True` | — | — | vacío | "Vacío = sin restricción" según el modelo (`models.py:103-107`) |
| `sucursales` | `ManyToManyField(clinica.Sucursal)`, `related_name="doctores"`, `blank=True` | — | — | vacío | "Vacío = sin restricción" según el modelo (`models.py:113-118`). **El filtro del listado lo trata como "ninguna sede"** → B-PER-02 |
| `sello` | `ImageField(255)` | — | sí | `NULL` | `clinica/<tenant_id>/doctores/sellos/<uuid>` |
| `foto` | `ImageField(255)` | — | sí | `NULL` | `clinica/<tenant_id>/doctores/fotos/<uuid>` |
| `cedulas_adicionales` | `CharField(500)` | — | no | `""` | Texto libre separado por comas. Conservado por compatibilidad; lo estructurado es `DoctorCredential` (§7.1.5) |

- **Constraint:** `doctor_membership_active_uniq = UniqueConstraint(membership) WHERE deleted_at IS NULL`
  (`models.py:154-158`). Índice único **parcial** en vez de `OneToOneField`, a propósito, para que un
  perfil soft-borrado no bloquee recrearlo (`models.py:52-54`). La FK declara `unique=False`
  explícitamente (`models.py:65`).
- **Índices existentes:** PK, el único parcial, `is_active`, `created_at`, `deleted_at`, `tenant`,
  `membership` (FK). `ordering = ["-created_at"]`.
- **Índice que sí falta y no propongo todavía.** `doctor_list` ordena por `-created_at` y filtra por
  `is_active` y por el M2M de sedes (`selectors.py:74-94`); con decenas de médicos por clínica
  cualquier índice compuesto sería peso muerto. Si una clínica pasa de ~500 médicos, el índice a
  crear es `(tenant, is_active, created_at DESC)`.
- **Quién puede tener perfil:** `ROLES_QUE_PUEDEN_EJERCER = {owner, admin, doctor}`
  (`services.py:38-44`). El perfil es una capacidad profesional, no un cargo: el dueño de un
  consultorio individual atiende pacientes, y `TenantMembership` solo admite un rol por clínica.
- `full_name` es una propiedad que atraviesa `membership.user.full_name` (`models.py:161-164`) — de
  ahí el `select_related("membership__user")` en todos los selectores.

#### 8.1.2 `Consultorio` — `personal_consultorios` (`models.py:171`)

| Campo | Tipo | `on_delete` | Null | Default | Consecuencia real |
|---|---|---|---|---|---|
| `name` | `CharField(100)` | — | no | — | Único por tenant |
| `location` | `CharField(200)` | — | no | `""` | Piso, ala, edificio |
| `color_hex` | `CharField(7)` | — | no | `""` | Sin validador a nivel de modelo; el `RegexField` del serializer es la única defensa (`views.py:339-345`) |
| `is_active` | `BooleanField` | — | no | `True` | `db_index=True`. **No se expone en ningún serializer de entrada** → no se puede reactivar → B-PER-04 |
| `sucursal` | FK `clinica.Sucursal`, `related_name="consultorios"` | **SET_NULL** | sí | `NULL` | Si la sede se borrara en duro, el consultorio sobrevive sin sede en vez de desaparecer. En la práctica no dispara: las sedes solo se desactivan (§7.2.8). `NULL` = "sin asignar" por compatibilidad retro |

- **Constraint:** `consultorio_tenant_name_uniq = UniqueConstraint(tenant, name)` (`models.py:216-219`)
  — **sin** condición sobre `deleted_at`, igual que `Sucursal` (B-CLI-07), mientras el service sí
  filtra por `deleted_at` (`services.py:528-532`).
- **Índices existentes:** PK, el único, `is_active`, `created_at`, `deleted_at`, `tenant`, `sucursal`
  (FK). `ordering = ["name"]`. La consulta que justifica el índice de la FK es
  `consultorio_list(sucursal_ids=...)` (`selectors.py:155-158`), que corre en cada carga del tablero
  de agenda.

#### 8.1.3 `DoctorSchedule` — `personal_doctor_schedules` (`models.py:242`)

Un bloque de disponibilidad. "L-V 9-14 y 16-19" son **10 filas** (`models.py:251`).

| Campo | Tipo | `on_delete` | Null | Default | Consecuencia real |
|---|---|---|---|---|---|
| `doctor` | FK `Doctor`, `related_name="schedules"` | **CASCADE** | no | — | Borrar en duro un médico se lleva sus horarios. No dispara: `Doctor` solo se desactiva |
| `day_of_week` | `PositiveSmallIntegerField` choices `Weekday` (0=Lunes … 6=Domingo, `models.py:226-239`) | — | no | — | |
| `start_time` / `end_time` | `TimeField` | — | no | — | **Hora local del tenant, NO UTC** (`models.py:245-250`). Quien compara con `Appointment.starts_at` (que sí es UTC) tiene que convertir |
| `consultorio` | FK `Consultorio`, `related_name="schedules"` | **SET_NULL** | sí | `NULL` | Desasignar un consultorio no borra el horario |
| `sucursal` | FK `clinica.Sucursal`, `related_name="doctor_schedules"` | **SET_NULL** | sí | `NULL` | Igual. `NULL` = horario legado sin sede |
| `valid_from` / `valid_until` | `DateField` | — | sí | `NULL` | `NULL` = sin límite de vigencia |
| `is_active` | `BooleanField` | — | no | `True` | `db_index=True`. DELETE = `is_active=False`; **no hay reactivación** → B-PER-06 |

- **Índice:** `schedule_doctor_day_idx (tenant, doctor, day_of_week)` (`models.py:310-315`). Consulta
  que lo justifica: la disponibilidad de un médico en un día, que consulta el motor de agenda en cada
  intento de agendar.
- `clean()` exige `end_time > start_time` (`models.py:317-322`) y `schedule_create` lo revalida antes
  (`services.py:725-728`) para dar un error legible. `full_clean(exclude=["tenant","created_by"])` se
  llama antes de guardar (`services.py:773`).
- **Sin constraint de solapamiento**, y el propio código lo dice: "En v1 no se valida solapamiento
  entre bloques de horario del mismo día. TODO(v2)" (`services.py:695-698`) → B-PER-06.
- `ordering = ["day_of_week", "start_time"]`.

#### 8.1.4 Las dos tablas intermedias sin `tenant_id`

`Doctor.consultorios` y `Doctor.sucursales` son `ManyToManyField` **sin `through` explícito**: Django
genera `personal_doctors_consultorios` y `personal_doctors_sucursales`, que **no tienen columna
`tenant_id`** ni pasan por `TenantManager`.

`personal/migrations/0012_rls_doctor_m2m_through_tables.py` les pone RLS con una **subconsulta al
padre** en vez de una comparación directa (`:70-76`):

```sql
EXISTS (SELECT 1 FROM personal_doctors d
        WHERE d.id = <tabla>.doctor_id
          AND (d.tenant_id = current_tenant_id() OR current_tenant_id() IS NULL))
```

La decisión de no convertirlas a `through` explícito está escrita: obligaría a una migración de datos
y a tocar todos los `.add()/.set()/.remove()` para un hallazgo sin exploit activo
(`0012_...:18-25`). Es el patrón que cita el test guardián (§1.1.4, `test_rls_coverage.py:166-169`).

---

### 8.2 Endpoints

Todas heredan de `TenantAPIView` y llevan `permission_classes = [IsAuthenticated, PersonalPermission, RequiresPersonal]`.

`PersonalPermission` (§1.3.2 #3): **GET todos los roles · POST/PATCH/DELETE solo owner y admin**.
`RequiresPersonal`: sin el módulo, **404** `{"detail": "No encontrado."}` en cualquier método salvo
`OPTIONS` (§1.4.2).

Errores comunes que no se repiten endpoint por endpoint: 401 · 403 por rol · 403
`{"detail": "...", "code": "password_change_required"}` · 403
`{"detail": "No se encontró un tenant activo para este request."}` en escrituras (`views.py:140-143`)
· 404 por módulo · 405 · 429.

Todos los listados usan `PageNumberPagination` estándar (25/página, sin `page_size` en la query,
§1.7.1) y, si el paginador devolviera `None`, responden **500**
`{"detail": "Paginación no disponible. Configura PAGE_SIZE en settings."}` (`views.py:128-131`) —
rama defensiva inalcanzable con la configuración actual.

#### 8.2.1 Médicos

| Método | Ruta | Vista:línea | Permiso | Acotado por sede |
|---|---|---|---|---|
| GET | `/api/v1/personal/doctores/` | `views.py:105` | GET: todos los roles | **sí** — `sucursal_scope_ids` |
| POST | `/api/v1/personal/doctores/` | `views.py:133` | O A | **no** |
| GET | `/api/v1/personal/doctores/<uuid:doctor_id>/` | `views.py:250` | todos los roles | **no** |
| PATCH | `/api/v1/personal/doctores/<uuid:doctor_id>/` | `views.py:256` | O A | **no** |
| DELETE | `/api/v1/personal/doctores/<uuid:doctor_id>/` | `views.py:310` | O A | **no** |

**GET lista** — query params:

| Param | Tipo | Default | Efecto |
|---|---|---|---|
| `search` | string | `""` | `icontains` sobre `specialty`, `first_name`, `last_name`, `email` del usuario (`selectors.py:86-92`) |
| `only_active` | `"false"` apaga el filtro | `"true"` | `is_active=True` |
| `page` | int | 1 | Paginación estándar |

Alcance: **siempre** `sucursal_scope_ids(request)` (§1.5.4), con o sin header `X-Sucursal-Id`
(`views.py:118`). Cuando el alcance no es total, el filtro es
`sucursales__id__in=[...]` + `.distinct()` (`selectors.py:81-82`).

Respuesta paginada; elemento (`DoctorOutputSerializer`, `serializers.py:46`):

```json
{
  "id":"uuid","full_name":"Ana Ruiz","user_email":"ana@x.mx","role":"doctor",
  "cedula_profesional":"1234567","specialty":"Dermatología",
  "default_appointment_duration":30,"bio_short":"",
  "sello":null,"foto":null,"cedulas_adicionales":"",
  "is_active":true,
  "consultorios":[{"id":"uuid","name":"Box 1"}],
  "sucursales":[{"id":"uuid","name":"Centro"}],
  "created_at":"..."
}
```

`membership_id` **no se expone** (decisión escrita en `serializers.py:52`), pero **sí se exige** en
el POST: el front tiene que obtenerlo de `GET /api/v1/miembros/` (§1.9).

**POST** — entrada (`views.py:76-103`): `membership_id` (UUID, req.), `cedula_profesional`
(≤30, default `""`, formato `^[0-9]{5,10}$` o vacío), `specialty` (≤100), `default_appointment_duration`
(5-480, default 30), `bio_short` (≤255).

Errores: **404** `{"detail": "Membresía no encontrada en este tenant."}` (`views.py:150-153`);
**400** `{"detail": [...]}` del service por rol que no puede ejercer (`services.py:120-123`),
membresía de otro tenant (`:125-129`) o perfil duplicado (`:134-135`). Éxito **201**.

**PATCH** — entrada (`views.py:191-238`), todos opcionales: `cedula_profesional`, `specialty`,
`default_appointment_duration`, `bio_short`, `consultorio_ids` (lista de UUID, vacía permitida),
`sucursal_ids` (ídem). `is_active` **no** se declara (`views.py:217-220`) y además está en
`_DOCTOR_IMMUTABLE_FIELDS` (`services.py:50-64`).

La vista separa los dos M2M y llama tres services distintos en orden: `doctor_update` →
`doctor_set_consultorios` → `doctor_set_sucursales` (`views.py:273-298`). **No hay transacción que
los envuelva**: si el tercero falla, los dos primeros ya se aplicaron. Cuerpo vacío → **400**.
Éxito **200** con el doctor releído con `prefetch` (`views.py:307`).

**DELETE** — `is_active=False` (`services.py:220-221`). Éxito **204**. **Irreversible por API.**

**Los tres endpoints de detalle resuelven el id con `doctor_get`, que solo aísla por tenant**
(`views.py:242`, `selectors.py:38-42`) — sin `sucursal_ids`, a diferencia de consultorios (§8.2.2) y
horarios (§8.2.3), que sí lo hacen → **B-PER-01**.

#### 8.2.2 Consultorios

| Método | Ruta | Vista:línea | Permiso | Acotado por sede |
|---|---|---|---|---|
| GET | `/api/v1/personal/consultorios/` | `views.py:349` | todos los roles | sí — `sucursal_scope_ids` |
| POST | `/api/v1/personal/consultorios/` | `views.py:374` | O A | sí — `resolve_write_sucursal` |
| GET | `/api/v1/personal/consultorios/<uuid:consultorio_id>/` | `views.py:464` | todos los roles | sí |
| PATCH | `/api/v1/personal/consultorios/<uuid:consultorio_id>/` | `views.py:470` | O A | sí |
| DELETE | `/api/v1/personal/consultorios/<uuid:consultorio_id>/` | `views.py:535` | O A | sí |

- **GET lista**: paginada, orden `name`. Param `only_active` (default `true`). Alcance
  `sucursal_scope_ids` siempre (`views.py:359`). Elemento:
  `{id, name, location, color_hex, is_active, sucursal: {id, name} | null, created_at}`.
- **Detalle/PATCH/DELETE**: `_get_consultorio_or_404` usa `consultorio_get(..., sucursal_ids=sucursal_scope_ids(request))`
  (`views.py:453-456`), **el mismo criterio que el listado**. Fuera de alcance → **404**
  `{"detail": "Consultorio no encontrado."}`. Cierra el hallazgo A5 citado en el docstring
  (`views.py:444-451`).
- **POST**: `{name, location?, color_hex?, sucursal_id?}`. `color_hex` es `RegexField` con mensaje
  propio. La sede se resuelve con `resolve_write_sucursal` (§1.5.3) dentro de `consultorio_create`
  (`services.py:543-548`), **no** con un selector tenant-scoped: un `sucursal_id` explícito de una
  sede ajena al actor da 400, no se acepta en silencio. Errores 400: nombre duplicado
  (`services.py:534`), **tope `max_consultorios` del plan** (`services.py:537-541`), sede no
  permitida. Éxito **201**.
- **PATCH**: `{name?, location?, color_hex?, sucursal_id?}`. `sucursal_id: null` **sí** desasigna
  (`views.py:496-501`); un id concreto pasa por `resolve_write_sucursal` (`views.py:509-513`).
  `is_active` no se expone. Cuerpo vacío → 400. Éxito **200**.
- **DELETE**: `is_active=False`. Éxito **204**. **Irreversible por API** → B-PER-04.

#### 8.2.3 Horarios del médico

| Método | Ruta | Vista:línea | Permiso | Acotado por sede |
|---|---|---|---|---|
| GET | `/api/v1/personal/doctores/<uuid:doctor_id>/horarios/` | `views.py:585` | todos los roles | sí |
| POST | `/api/v1/personal/doctores/<uuid:doctor_id>/horarios/` | `views.py:613` | O A | sí — `resolve_write_sucursal` |
| DELETE | `/api/v1/personal/horarios/<uuid:schedule_id>/` | `views.py:695` | O A | sí |

- **GET**: paginado, solo `is_active=True`, orden `day_of_week, start_time`, acotado por
  `sucursal_scope_ids` (`views.py:599`). Elemento
  (`DoctorScheduleOutputSerializer`, `serializers.py:129`):
  `{id, day_of_week, day_of_week_display, start_time, end_time, consultorio: {id,name}|null, sucursal: {id,name}|null, valid_from, valid_until, is_active}`.
  Doctor inexistente → **404** `{"detail": "Médico no encontrado."}`.
- **POST**: `{day_of_week (0-6), start_time, end_time, consultorio_id?, valid_from?, valid_until?, sucursal_id?}`
  (`views.py:559-573`). Consultorio inexistente → **404**
  `{"detail": "Consultorio no encontrado en este tenant."}` (`views.py:635-639`) — nótese que ese
  `consultorio_get` **no** pasa `sucursal_ids`, a diferencia del de `ConsultorioDetailApi`.
  Errores 400 del service: `end_time <= start_time` (`services.py:725-728`), doctor de otro tenant
  (`:730-731`), consultorio de otro tenant (`:735-736`), `valid_until < valid_from` (`:739-742`),
  y `{"detail": ["El médico no atiende en esa sucursal."]}` si el médico tiene sedes asignadas y la
  resuelta no está entre ellas (`:756-758`). Éxito **201**.
- **DELETE**: `schedule_get(..., sucursal_ids=sucursal_scope_ids(request))` (`views.py:684-687`) →
  fuera de alcance **404** `{"detail": "Horario no encontrado."}`. Baja lógica `is_active=False`.
  Éxito **204**.
- **`DoctorScheduleDetailApi` solo implementa `delete`** (`views.py:669`): GET y PATCH sobre
  `/personal/horarios/<id>/` responden **405**. No se puede corregir un horario mal capturado: hay
  que borrarlo y volverlo a crear → B-PER-06.

#### 8.2.4 Django Admin

`apps/personal/admin.py` registra los tres modelos con `all_objects` (**cross-tenant**,
`admin.py:118-120`, `:165-166`, `:217-220`) y restringe ver/agregar/cambiar a
`is_platform_staff or is_superuser` (`admin.py:23-28`), con el borrado reservado a `is_superuser`
(`admin.py:115-116`). No es API: entra por sesión de Django en `/admin/` (§1.2.1) y por el
`TenantMiddleware` (§1.1.2). El staff de una clínica nunca debe llegar ahí (`admin.py:4-12`).

---

### 8.3 Alta, bloqueo y restablecimiento de contraseña

**El código de estas tres acciones no está en `apps/personal`**, está en `apps/tenancy` bajo
`/api/v1/miembros/` (rutas y formas de respuesta en §1.9). Aquí se documenta **la autorización**,
que es lo que importa.

#### 8.3.1 Alta con contraseña inicial

`POST /api/v1/miembros/` → `member_create` (`apps/tenancy/services.py:136`). No hay invitación por
correo: quien da de alta **teclea la contraseña del empleado**, tal como describe
`docs/01-analisis.md:97`.

Orden real de las validaciones:

1. Rol dentro de los 7 válidos (`:206-207`).
2. Actor con membresía activa en el tenant; si no la tiene, solo pasa el **bootstrap**: tenant sin
   ninguna membresía y rol pedido exactamente `owner` (`:231-240`). Es la puerta que usa
   `apps/plataforma/services.py` al crear una clínica, y está acotada para no volverse alternativa.
3. **Anti-escalada**: un actor que no es owner solo puede crear roles operacionales — nunca `admin`
   ni `owner` (`_ensure_role_grantable`, `:114-133`).
4. **Un solo dueño por clínica**: crear un segundo `owner` fuera del bootstrap → 400 "Esta clínica ya
   tiene un dueño…" (`:223-230`).
5. **Plan**: el rol tiene que estar en `Entitlements.roles` (`:247-253`, §1.6.3).
6. **Límite `max_usuarios`** contra membresías activas no borradas (`:254-260`).
7. Email no registrado en **ninguna** clínica (`:263-264`) — el email es global.
8. Contraseña contra los validadores de Django, evaluada **contra el usuario en memoria** para poder
   detectar similitud con el nombre y el correo antes de persistir nada (`:266-275`).
9. Sede del nuevo miembro por precedencia (`:277-290`): `X-Sucursal-Id` validado contra
   `allowed_sucursales` del actor → si el actor no es owner, **todas** sus sedes → si es owner,
   ninguna asignación (cae en la default por el fallback anti-lockout de §1.5.2).

Todo dentro de `transaction.atomic()`: usuario, membresía y filas de `MembershipSucursal`
(`:292-312`).

**Lo que el alta NO hace:** encender `must_change_password`. El usuario nace con el default `False`
(`apps/authn/models.py:77-78`) y `member_create` no lo toca (`apps/tenancy/services.py:268-274`). La
contraseña que el dueño escribió vive indefinidamente y nada obliga a cambiarla → **B-PER-03**, que
es exactamente el riesgo que `docs/01-analisis.md:102` anticipa.

#### 8.3.2 Bloqueo de cuenta

`PATCH /api/v1/miembros/<id>/` con `{"blocked": true}` → `member_update`
(`apps/tenancy/services.py:438-451`). Pone `user.is_active = not blocked` y audita `MEMBER_BLOCK`.

- **Nadie puede bloquearse a sí mismo** (`:439-440`).
- **Es efectivo de inmediato**: `JWTAuthentication` de SimpleJWT rechaza el token de un usuario con
  `is_active=False`, así que el access token vigente deja de servir en el siguiente request.
- Bloquea **la cuenta**, no la membresía: un médico que trabaja en dos clínicas y al que una de ellas
  bloquea **pierde el acceso a las dos**. `TenantMembership.is_active` (que sí es por clínica) no se
  toca desde este endpoint.

#### 8.3.3 Restablecimiento de contraseña — quién puede sobre quién

Tres caminos distintos, con tres comportamientos distintos:

| Camino | Quién | Sobre quién | `must_change_password` | Invalida sesiones |
|---|---|---|---|---|
| `POST /api/v1/auth/change-password/` (propio) | cualquier usuario | sí mismo | lo **apaga** | **sí** — blacklistea todos los refresh vigentes (`apps/authn/services.py:70-84`) |
| Panel de plataforma → staff interno | `super_admin` | staff de Maily | lo **enciende** (`apps/plataforma/services.py:1274`) | **sí** (`:1277-1288`) |
| `PATCH /api/v1/miembros/<id>/` con `password` | owner / admin de la clínica | personal de la clínica | **no lo toca** | **no** |

La cadena de autorización del tercero, que es el que nos importa:

1. `MemberPermission` (§1.3.2 #6) deja pasar **solo owner y admin**; los otros cinco roles reciben 403
   sin llegar a la vista.
2. `_member_get_or_404` (`apps/tenancy/views.py:70`) resuelve la membresía con
   `membership_get_in_scope`, acotada a `allowed_sucursales` **del actor** (no al scope del listado),
   y **además** responde 404 si el actor no es owner y el objetivo tiene rol no operacional
   (`:103-108`). Un admin de Centro que pide la membresía del dueño recibe **404**, no 403: no se
   entera de que existe.
3. `member_update` revalida lo mismo en el service con `_authorize_write_on_member`
   (`apps/tenancy/services.py:76-111`), por si se invoca fuera de la vista.
4. `_ensure_role_grantable` impide de paso que un no-owner ascienda a nadie a `admin` u `owner`
   (`:114-133`).
5. La contraseña nueva pasa por `validate_password` contra el usuario objetivo (`:426`) y se audita
   `MEMBER_PASSWORD` sin registrar la contraseña (`:429-436`).

**Resultado del punto P0:** no hay escalamiento de privilegios. Un admin **no** puede restablecer la
contraseña del dueño ni la de otro admin, ni la de nadie fuera de sus sedes; el owner sí puede la de
cualquiera, incluido otro owner (decisión D3, documentada en `apps/tenancy/services.py:352-353`).
El bloqueo de cuenta hereda exactamente las mismas reglas, igual que el avatar
(`member_set_avatar` / `member_clear_avatar`, `:456`, `:485`).

**Lo que sí está mal:** este camino es el único de los tres que **no invalida las sesiones vivas**.
El propio código documenta el patrón correcto dos veces (`apps/authn/services.py:75-76` y
`apps/plataforma/services.py:1277-1280`) y aquí no se aplica → **B-PER-08**. Para echar de verdad a
alguien hoy hay que usar `blocked: true`, no restablecer la contraseña.

---

### 8.4 Reglas de negocio verificadas en código

1. **Un perfil de médico activo por membresía.** Índice único parcial + comprobación legible antes
   del `IntegrityError` (`models.py:154-158`, `services.py:134-135`).
2. **Ejercer no es un cargo.** `doctor_create` acepta owner, admin y doctor
   (`services.py:38-44`, `:120-123`). Lo que autoriza **recetar** es la cédula, no el rol
   (`apps/recetas/services.py:519`).
3. **Nada de reactivar por PATCH.** `is_active` está en `_DOCTOR_IMMUTABLE_FIELDS`
   (`services.py:50-64`) y no se declara en el serializer de consultorio: la única transición posible
   es activo → inactivo. Cierre del FIX-F1, con el efecto colateral B-PER-04.
4. **`membership` y `tenant` son inmutables en un `Doctor`.** No se puede mover un perfil de médico a
   otra persona ni a otra clínica (`services.py:50-56`).
5. **Nombre de consultorio único por clínica**, revalidado también al renombrar
   (`services.py:528-534`, `:598-612`).
6. **Límite `max_consultorios` del plan** en `consultorio_create` (`services.py:537-541`), contra
   consultorios **no borrados** — los desactivados siguen ocupando cupo → B-PER-07. Es uno de los
   tres únicos puntos del sistema que consultan un límite (§1.4.4).
7. **La sede de escritura siempre pasa por `resolve_write_sucursal`** (§1.5.3), nunca por un selector
   que solo mire el tenant: `consultorio_create` (`services.py:543-548`),
   `ConsultorioDetailApi.patch` (`views.py:509-513`) y `schedule_create` (`services.py:748-754`).
   Eso es lo que impide que un admin de Centro mande el `sucursal_id` de Norte en el cuerpo.
8. **Anti-escalada por diferencia simétrica en los dos M2M.** Si el actor no es owner, solo puede
   agregar o quitar sedes (`doctor_set_sucursales`, `services.py:448-458`) y consultorios cuya sede
   esté en su alcance (`doctor_set_consultorios`, `services.py:326-345`). Lo que no cambia no se
   valida: un admin de Centro puede editar a un médico que también atiende en Norte sin poder tocar
   Norte. Los consultorios con `sucursal=NULL` siempre pasan (`services.py:333-336`).
9. **`doctor_set_sucursales` no tiene regla anti-lockout** y está razonado: fija dónde **atiende** un
   médico, no el alcance operativo de una persona, así que vaciar la lista no puede autobloquear a
   nadie (`services.py:388-391`). El precio de esa decisión es B-PER-02.
10. **Un médico no puede tener horario en una sede donde no atiende**: si tiene sedes asignadas, la
    resuelta debe estar entre ellas (`services.py:756-758`). Si **no** tiene ninguna asignada, la
    comprobación se salta por completo.
11. **Los tiempos de horario son hora local del tenant, no UTC** (`models.py:245-250`). Quien compare
    con `Appointment.starts_at` tiene que convertir. Combinado con §1.7 (nada activa el huso del
    tenant), es una fuente de error latente para una clínica fuera de Ciudad de México.
12. **Sin validación de solapamiento de horarios**, declarado como TODO (`services.py:695-698`).
13. **Detalle y listado acotan igual** en consultorios (`views.py:444-456`) y horarios
    (`views.py:674-693`), por diseño explícito de los cierres A4/A5. **En médicos no**
    (`views.py:240-248`) → B-PER-01.
14. **Todo `DoesNotExist` se traduce a 404, nunca a 403** (`views.py:10-12`). Un id de otro tenant y
    un id de otra sede son indistinguibles desde fuera.
15. **Toda escritura audita** (8.6).

---

### 8.5 Matriz de permisos del módulo

**O**=owner · **A**=admin · **D**=doctor · **N**=nurse · **R**=reception · **F**=finance ·
**L**=readonly. `sí` = permitido · `no` = 403 · `propio` = solo sobre sus propios registros ·
`sede` = permitido pero acotado a sus sedes.

**Todas las filas de `apps/personal` responden 404 (no 403) si la clínica no tiene el módulo
`personal`** — antes de evaluar el rol, porque el guard corre en la misma lista de
`permission_classes` (§1.4.2).

| Acción | O | A | D | N | R | F | L |
|---|---|---|---|---|---|---|---|
| Listar médicos (`GET /personal/doctores/`) | sí | sede | sede | sede | sede | sede | sede |
| Ver el detalle de un médico | sí | sí (1) | sí (1) | sí (1) | sí (1) | sí (1) | sí (1) |
| Crear un perfil de médico | sí | sí (1) | no | no | no | no | no |
| Editar cédula, especialidad, duración, semblanza | sí | sí (1) | no | no | no | no | no |
| Reasignar consultorios y sedes de un médico | sí | sede | no | no | no | no | no |
| Desactivar un médico (`DELETE`) | sí | sí (1) | no | no | no | no | no |
| Listar consultorios | sí | sede | sede | sede | sede | sede | sede |
| Ver el detalle de un consultorio | sí | sede | sede | sede | sede | sede | sede |
| Crear un consultorio | sí | sede | no | no | no | no | no |
| Editar o reasignar de sede un consultorio | sí | sede | no | no | no | no | no |
| Desactivar un consultorio | sí | sede | no | no | no | no | no |
| Listar horarios de un médico | sí | sede | sede | sede | sede | sede | sede |
| Crear un horario | sí | sede | no | no | no | no | no |
| Desactivar un horario | sí | sede | no | no | no | no | no |
| Editar un horario | **no** — no existe el endpoint (405) | no | no | no | no | no | no |
| Reactivar un médico, consultorio u horario | **no** — no existe el endpoint | no | no | no | no | no | no |
| Editar sello, foto y cédulas adicionales (§7.2.4) | sí | sí | propio | no | no | no | no |

(1) **Sin acotar por sede**, a diferencia del listado: es exactamente el hueco B-PER-01.

Alta, bloqueo y contraseñas (`/api/v1/miembros/`, §1.9 y §8.3) — permiso `MemberPermission`, **sin**
guard de módulo:

| Acción | O | A | D | N | R | F | L |
|---|---|---|---|---|---|---|---|
| Listar el equipo | sí | sede + solo roles operacionales + sí mismo | no | no | no | no | no |
| Ver / editar / dar de alta a un miembro | sí | sede, solo roles operacionales | no | no | no | no | no |
| Otorgar el rol `owner` o `admin` | sí | **no** | no | no | no | no | no |
| Crear un segundo `owner` | **no** | no | no | no | no | no | no |
| Restablecer la contraseña de un miembro | sí (cualquiera) | sede, solo roles operacionales | no | no | no | no | no |
| Bloquear / desbloquear una cuenta | sí (salvo la propia) | sede, solo operacionales, salvo la propia | no | no | no | no | no |
| Subir o borrar el avatar de un miembro | sí | sede, solo operacionales | no | no | no | no | no |
| Cambiar la **propia** contraseña | sí | sí | sí | sí | sí | sí | sí |

Tipos de cita (`AppointmentType`, `apps/agenda`): `AppointmentTypePermission` = GET todos los roles ·
POST/PATCH/DELETE owner y admin (§1.3.2 #7), con guard `RequiresAgenda`. Se documenta en la sección
de agenda.

---

### 8.6 Efectos secundarios

| Disparador | Efecto | Referencia |
|---|---|---|
| `POST /personal/doctores/` | `audit_record(DOCTOR_CREATE)` | `services.py:147-154` |
| ídem | Habilita a esa persona para recibir citas y, **si la cédula no está vacía**, para emitir recetas | `apps/recetas/services.py:508-519` |
| ídem | Cambia la respuesta de `GET /api/v1/me/`: el usuario pasa a tener `doctor_id` | `apps/authn/views.py:407` |
| `PATCH /personal/doctores/<id>/` | `DOCTOR_UPDATE` con `changed_fields` | `services.py:192-200` |
| ídem con `cedula_profesional` vaciada | El médico deja de poder emitir recetas en el siguiente intento. **Las ya emitidas no se tocan** (son inmutables) | `apps/recetas/services.py:519` |
| ídem con `consultorio_ids` | `DOCTOR_CONSULTORIOS` con la lista. `doctor.consultorios.set()` **borra y reinserta** las filas de la tabla intermedia | `services.py:347-359` |
| ídem con `sucursal_ids` | `DOCTOR_SUCURSALES`. Cambia en qué sedes puede agendarse y en qué listados aparece; una lista **vacía lo saca de todo listado acotado** → B-PER-02 | `services.py:460-472` |
| ídem | **No hay transacción común**: `doctor_update`, `doctor_set_consultorios` y `doctor_set_sucursales` se aplican en secuencia y un fallo del tercero deja aplicados los dos primeros | `views.py:273-298` |
| `DELETE /personal/doctores/<id>/` | `DOCTOR_DEACTIVATE`. Desaparece de los listados con `only_active=true`; **sus citas, horarios y recetas quedan intactos** y no se valida que no tenga citas futuras | `services.py:220-230` |
| `PATCH /clinica/doctores/<id>/perfil/` | `DOCTOR_UPDATE` con `context: profile_images`; sube el archivo y **deja huérfano el anterior** en el storage | `apps/clinica/services.py:557-565` |
| `POST /personal/consultorios/` | `CONSULTORIO_CREATE`. Consume cupo de `max_consultorios` de forma permanente hasta que se borre en duro | `services.py:559-566` |
| `PATCH` de consultorio con `sucursal_id` | `CONSULTORIO_UPDATE`. **Mueve el consultorio de sede sin tocar los horarios ni las citas que ya lo referencian**: quedan con una sede distinta a la de su consultorio | `services.py:628-636` |
| `DELETE` de consultorio | `CONSULTORIO_DEACTIVATE`. Los `DoctorSchedule` y las citas que lo referencian **siguen apuntando a él**; `doctor_set_consultorios` sí rechaza asignar uno inactivo (`services.py:299-302`) | `services.py:657-664` |
| `POST /personal/doctores/<id>/horarios/` | `SCHEDULE_CREATE` con `day_of_week`. Amplía la disponibilidad que ve el motor de agenda **de inmediato**, sin comprobar solapamiento | `services.py:776-784` |
| `DELETE /personal/horarios/<id>/` | `SCHEDULE_DEACTIVATE`. Las citas ya agendadas dentro de ese bloque **no se cancelan ni se marcan** | `services.py:808-815` |
| `POST /api/v1/miembros/` | `MEMBER_CREATE` con el email y las sedes; crea `User` + `TenantMembership` + filas de `MembershipSucursal` en una transacción. **Sin `must_change_password`** | `apps/tenancy/services.py:292-325` |
| `PATCH /api/v1/miembros/<id>/` | Hasta **tres** registros separados: `MEMBER_UPDATE` (campos), `MEMBER_PASSWORD`, `MEMBER_BLOCK` | `apps/tenancy/services.py:414-451` |
| ídem con `password` | Cambia el hash. **No blacklistea nada**: el refresh de 7 días del objetivo sigue vivo → B-PER-08 | `apps/tenancy/services.py:425-436` |
| ídem con `blocked: true` | `user.is_active=False` → el usuario pierde el acceso **a todas sus clínicas**, no solo a esta | `apps/tenancy/services.py:441-442` |

Los `audit_record` nunca tumban la operación (§1.8.5).
## 9. Notas, tareas y avisos

> Extraído del código el 2026-08-12 (modo inverso). Alcance leído: `apps/notas/` completo
> (`models.py`, `views.py`, `services.py`, `selectors.py`, `serializers.py`, `urls.py`, `admin.py`,
> migraciones `0001`–`0004`). Se consultaron como insumo `apps/notificaciones/recipients.py`,
> `apps/notificaciones/services.py` (`notification_fanout`), `apps/clinica/sucursal_scope.py`,
> `apps/audit/models.py` y `MailySoft/web-soft/src/api/notas.ts` (solo lectura, para detectar
> endpoints sin consumidor). Rutas relativas a la raíz del repo; dentro de esta sección se abrevian a
> `apps/…` = `MailySoft/backend/apps/…`.

Se citan sin repetirse: aislamiento de tenant (§1.1), permisos (§1.3), módulos (§1.4), alcance por
sucursal (§1.5), roles (§1.6) y convenciones de la API (§1.7).

**Un solo modelo cubre tres cosas distintas** que el usuario percibe como productos separados: la
nota personal, la tarea con checkbox y el aviso dirigido a un rol o a toda la clínica. Lo que las
separa es el campo `scope`, no la tabla.

---

### 9.1 Modelo de datos

Una sola tabla. Hereda `TenantAwareModel` (§1.8.2): `id` UUID, `created_at`, `updated_at`,
`deleted_at`, `tenant` (`PROTECT`), `created_by` (`SET_NULL`).

| Tabla | Modelo | `tenant_id` | RLS | Por qué |
|---|---|---|---|---|
| `notas_notes` | `Note` (`apps/notas/models.py:44`) | sí, `PROTECT` | sí — `ENABLE` + `FORCE` + policy con `USING` y `WITH CHECK` (`apps/notas/migrations/0002_enable_rls.py:29-35`) | Es contenido de la clínica. La tabla nació sin RLS y la migración `0002` cerró esa brecha en la auditoría del 2026-06-25 (`0002_enable_rls.py:19-21`) |

No hay M2M, así que no hay tabla `through` que auditar (§1.8.3 punto 2).

#### 9.1.1 Campos

| Campo | Tipo | `on_delete` | Null | Default | Línea | Consecuencia real |
|---|---|---|---|---|---|---|
| `author` | FK `authn.User`, `related_name="notes"` | **CASCADE** | no | — | `models.py:68` | **Borrar el usuario borra físicamente todas sus notas**, incluidos los avisos que mandó a toda la clínica. Contrasta con `created_by=SET_NULL` de `TenantAwareModel`, que sí preserva el historial. En la práctica hoy no se alcanza: la API de miembros bloquea la cuenta, no la borra (§1.9) |
| `title` | `CharField(120)` | — | no | `""` | `:74` | |
| `body` | `TextField` | — | no | `""` | `:80` | Al menos uno de `title`/`body` debe tener contenido — regla del service, **no** del modelo (`services.py:144-147`) |
| `scope` | `CharField(10)` choices `personal`/`role`/`all` **db_index** | — | no | `personal` | `:85` | Define toda la visibilidad |
| `target_role` | `CharField(20)` | — | no | `""` | `:92` | Rol destinatario si `scope=role`. **Sin `choices` a nivel de modelo**: la lista válida vive en `services.py:68-78` |
| `sucursal` | FK `clinica.Sucursal`, `related_name="+"` **db_index** | **SET_NULL** | **sí** | `NULL` | `:102` | **`NULL` significa "todas las sedes", no "sin sede"**. Por lo tanto, si alguna vez se borrara físicamente una sucursal, sus avisos internos pasarían a ser visibles en toda la clínica. Hoy no se alcanza desde la API: la baja de sede es lógica (`apps/clinica/services.py:1227` `sucursal_deactivate`) |
| `is_important` | `BooleanField` | — | no | `False` | `:118` | Aviso destacado. **Solo el owner puede ponerlo en `True`** (`services.py:219-220`) |
| `is_task` | `BooleanField` | — | no | `False` | `:126` | Convierte la nota en tarea con checkbox |
| `done` | `BooleanField` | — | no | `False` | `:130` | Solo tiene sentido con `is_task=True`; solo cambia por el endpoint dedicado |
| `remind_at` | `DateTimeField` **db_index** | — | **sí** | `NULL` | `:134` | Recordatorio **pasivo**: ver 9.3 punto 8 |
| `pinned` | `BooleanField` | — | no | `False` | `:140` | Fija al tope del listado |

`Meta`: `db_table = "notas_notes"`, `ordering = ["-pinned", "-created_at"]` (`:145-147`).

#### 9.1.2 Constraints e índices

**No hay `constraints` ni `indexes` declarados en `Meta`.** Los únicos índices son los implícitos:
`scope`, `sucursal_id`, `remind_at` (por `db_index=True`), `author_id` y `tenant_id` (por FK),
`created_at` y `deleted_at` (heredados de `BaseModel`, §1.8.1).

Consultas reales del módulo y su índice:

| Consulta | Dónde | Índice que la sostiene |
|---|---|---|
| `WHERE tenant_id=? AND deleted_at IS NULL AND ((author_id=? AND scope='personal') OR (scope='role' AND target_role=?) OR scope='all') ORDER BY pinned DESC, created_at DESC` | `selectors.py:179-181` | Parcialmente: `tenant_id`, `scope`, `author_id`. **`target_role` no tiene índice** y el `ORDER BY` compuesto tampoco |
| `… AND remind_at >= ? AND remind_at < ? ORDER BY remind_at` | `selectors.py:217-221` | `remind_at` |
| `WHERE id=?` acotado por `sucursal_id IN (…)` | `selectors.py:71-86` | PK + `sucursal_id` |

**Índices que no se proponen y por qué.** Un índice compuesto `(tenant_id, scope, target_role)` haría
la primera consulta perfecta, pero con 1–3 usuarios concurrentes y notas del orden de decenas por
clínica (`01-analisis.md:312`) el planificador resuelve con el índice de `tenant_id` y un filtro en
memoria. Sería peso muerto en cada escritura. **Ninguna condición nueva se propone hasta que una
clínica pase de ~5.000 notas vivas**, número que hoy no existe.

Un detalle que sí conviene vigilar: `deleted_at` tiene índice pero la consulta real es
`deleted_at IS NULL`, que en Postgres se beneficiaría de un índice **parcial**. No se propone: el
mismo patrón está en todo el sistema y cambiarlo solo aquí crea una inconsistencia sin beneficio
medible.

#### 9.1.3 Qué decidió la migración de sedes

`0003_note_sucursal_is_important.py` agregó los dos campos; `0004_backfill_note_sucursal.py` es un
**no-op intencional** (`0004:33-35`): las notas y avisos anteriores al 2026-07-16 se quedaron con
`sucursal=NULL`, es decir, visibles en toda la clínica. La razón está escrita en la propia migración
(`0004:5-17`): asignarles la Sucursal Principal —como hicieron agenda, personal y finanzas— los
habría **ocultado** retroactivamente de las demás sedes, cambiando su significado. Es la única app
del proyecto donde `NULL` en `sucursal` significa "todas" y no "sin asignar".

---

### 9.2 Endpoints

Prefijo `/api/v1/` (§1.7). Rutas en `apps/notas/urls.py:25-50`. **Las cuatro vistas heredan de
`TenantAPIView` y llevan `permission_classes = [IsAuthenticated, NotePermission, RequiresNotas]`**
(`views.py:95`, `:213`, `:298`, `:331`).

- `NotePermission` (§1.3.2 #20) abre **los 4 métodos a los 7 roles**. La granularidad no está en el
  permiso HTTP: la hace el selector para leer y el service para escribir. La razón está escrita en
  `views.py:13-19` y en `apps/core/permissions.py:641-652`.
- `RequiresNotas` (§1.4.2): si la clínica no compró el módulo `notas`, **404**, no 403.
- Las cuatro vistas empiezan resolviendo el tenant y devuelven **403**
  `{"detail": "No se encontró un tenant activo para este request."}` si no hay
  (`views.py:57-65`).

| # | Método | Ruta | Vista:línea | Éxito | Errores |
|---|---|---|---|---|---|
| 1 | GET | `/api/v1/notas/` | `views.py:126` | 200 paginado | 400, 401, 403, 404 (módulo), 500 |
| 2 | POST | `/api/v1/notas/` | `views.py:169` | 201 `NoteOutput` | 400, 401, 403, 404 (módulo) |
| 3 | PATCH | `/api/v1/notas/<uuid:note_id>/` | `views.py:230` | 200 `NoteOutput` | 400, 401, 403, 404 |
| 4 | DELETE | `/api/v1/notas/<uuid:note_id>/` | `views.py:271` | **204 sin cuerpo** | 400, 401, 403, 404 |
| 5 | POST | `/api/v1/notas/<uuid:note_id>/done/` | `views.py:300` | 200 `NoteOutput` | 400, 401, 403, 404 |
| 6 | GET | `/api/v1/notas/recordatorios/` | `views.py:333` | 200 paginado | 400, 401, 403, 404 (módulo), 500 |

**No existe `GET /api/v1/notas/<id>/`**: `NoteDetailApi` solo implementa `patch` y `delete`, así que
un GET al detalle pasa el permiso (`NotePermission.GET` = todos) y muere en **405**. El front nunca
lo necesita porque el listado ya trae el objeto completo.

**Orden de rutas:** `notas/recordatorios/` va **antes** de `notas/<uuid:note_id>/`
(`urls.py:26-31`) — con el converter `uuid` no habría colisión real, pero el orden está fijado y
documentado a propósito (`urls.py:12-13`).

**Los seis endpoints tienen consumidor** en `web-soft/src/api/notas.ts:8-43`. No hay código muerto en
esta app.

**Respuesta común** (`NoteOutputSerializer`, `apps/notas/serializers.py:34`, todos los campos de solo
lectura):

```json
{
  "id": "uuid",
  "author": {"id": "uuid", "full_name": "Dra. Ana López"},
  "title": "Revisar consentimientos",
  "body": "Faltan las firmas de la semana pasada",
  "scope": "role", "scope_display": "Rol específico",
  "target_role": "reception",
  "sucursal": {"id": "uuid", "name": "Centro"},
  "is_important": false,
  "is_task": true, "done": false,
  "remind_at": "2026-08-13T09:00:00-06:00",
  "pinned": false,
  "created_at": "2026-08-12T18:04:00-06:00",
  "updated_at": "2026-08-12T18:04:00-06:00"
}
```

`author` es un objeto mínimo `{id, full_name}` (`serializers.py:17-24`); `sucursal` es
`{id, name}` o **`null` = todas las sedes** (`serializers.py:27-31`). El serializer **no** expone
`tenant`, `created_by` ni `deleted_at`.

---

#### 9.2.1 `GET /api/v1/notas/`

**Query params** (`_FilterSerializer`, `views.py:145-147`):

| Param | Tipo | Notas |
|---|---|---|
| `is_task` | bool | Opcional. `true` = solo tareas, `false` = solo notas |
| `done` | bool | Opcional. Filtra por estado de la tarea |
| `page` | int | `PageNumberPagination` estándar, 25 por página, sin `page_size` (§1.7.1) |

El docstring de la vista anuncia un tercer filtro `scope` (`views.py:132`) que **no existe** en el
serializer ni en el selector → B-NOT-05.

**Visibilidad — la regla central del módulo** (`note_list_visible`, `apps/notas/selectors.py:114`).
El `TenantManager` ya acotó al tenant y excluyó lo borrado; sobre eso se aplica un OR de tres ramas
(`selectors.py:160-181`):

| Rama | Condición | ¿Se acota por sede? |
|---|---|---|
| Personal | `author = yo AND scope = 'personal'` | **No.** Una nota personal no tiene noción de sede (`selectors.py:159`) |
| Por rol | `scope='role' AND target_role = mi rol en esta clínica` | Sí |
| Toda la clínica | `scope='all'` | Sí |

El rol se resuelve con una query propia a `TenantMembership` (`_get_user_role_in_tenant`,
`selectors.py:89`) filtrando `is_active=True, deleted_at IS NULL`. Si el usuario no tiene membresía,
la rama "por rol" se anula con `Q(pk__in=[])` (`selectors.py:166`) — **fail-closed**.

El acotamiento por sede se aplica a las ramas 2 y 3 con
`sucursal_id IS NULL OR sucursal_id IN (alcance del viewer)` (`selectors.py:172-177`), donde el
alcance lo calcula la vista con `sucursal_scope_ids(request)` (`views.py:155`), la función que
**siempre acota** (§1.5.4). Es el cierre del hueco del 2026-07-16: antes bastaba omitir el header
`X-Sucursal-Id` para ver los avisos de otra sede.

Consecuencia que hay que tener presente al leer el resto: en una clínica de **una sola sede** —y en
una que no tenga ninguna `Sucursal`— `sucursal_scope_ids` devuelve `None` para todo el mundo
(§1.5.5), así que ningún filtro de sede se aplica y todo este mecanismo es inerte. Solo se activa en
clínicas multi-sede con personal asignado a una parte de las sedes.

Los avisos `is_important` **sí** aparecen en el listado para todos los que estén en su alcance; solo
quedan fuera del alcance de **mutación** (ver 9.2.3).

**Errores:** 400 de serializer si `is_task`/`done` no son booleanos; 401; 403 sin tenant; 404 si la
clínica no compró `notas`; 500 con `{"detail": "Paginación no disponible…"}` si faltara `PAGE_SIZE`
(`views.py:164-167`).

#### 9.2.2 `POST /api/v1/notas/`

**Entrada** (`InputSerializer`, `views.py:97-124`) — **todos los campos son opcionales**, incluidos
los que solo el owner puede usar de verdad. La razón está escrita: no bifurcar el contrato del
endpoint por rol (`views.py:100-105`).

| Campo | Tipo | Default | Quién lo puede usar de verdad |
|---|---|---|---|
| `title` | ≤120, `allow_blank` | `""` | todos |
| `body` | ≤10.000, `allow_blank` | `""` | todos |
| `scope` | choice `personal`/`role`/`all` | `personal` | `all` → **solo owner y admin**; `role` → owner, admin, doctor, nurse, reception |
| `target_role` | ≤20, `allow_blank` | `""` | obligatorio si `scope=role` |
| `is_task` | bool | `false` | todos |
| `remind_at` | datetime nullable | `null` | todos |
| `pinned` | bool | `false` | todos |
| `sucursal_id` | UUID nullable | `null` | **solo el owner lo controla**; a cualquier otro se le re-resuelve |
| `is_important` | bool | `false` | **solo owner**; a cualquier otro se le **rechaza con 400** |

**Reglas del service `note_create`** (`apps/notas/services.py:242`), en orden:

1. `title` y `body` se hacen `strip()`; al menos uno debe quedar con contenido, si no 400 "La nota
   debe tener al menos un título o un cuerpo con contenido." (`:306-310`).
2. **Quién puede usar cada scope** (`:313-326`):
   - `scope=all` → el rol debe estar en `_SCOPE_ALL_SENDERS` = **owner o admin** (`services.py:106`).
     Si no: 400 "Solo el dueño o un administrador pueden enviar un aviso a toda la clínica".
   - `scope=role` → el rol debe estar en `ROLE_NOTE_SENDERS` = **owner, admin, doctor, nurse,
     reception** (`apps/notificaciones/recipients.py:32-34`). `finance` y `readonly` quedan fuera:
     400 "Tu rol no puede dirigir notas a un rol específico."
   - `scope=personal` → cualquiera de los 7.
3. `target_role` obligatorio y dentro de los 7 roles válidos si `scope=role`; **forzado a `""`** en
   cualquier otro scope (`:329-339`). Nótese que **se puede dirigir un aviso a `finance` o a
   `readonly`** aunque ellos no puedan enviarlos.
4. Sede y destacado (`_resolve_broadcast_sucursal`, `:167`):
   - `scope=personal` → siempre `sucursal=None`, `is_important=False` (`:343-345`).
   - Actor **owner** → `sucursal_id` tal cual (`None` = todas las sedes); si manda un UUID, debe ser
     una sucursal **activa** del tenant o 400 "Sucursal no encontrada en esta clínica o no está
     activa" (`:211-217`). `is_important` se respeta.
   - Actor **no owner (admin incluido)** → `is_important=True` se **rechaza** con 400 "Solo el dueño
     de la clínica puede marcar un aviso como importante" (`:219-220`), y la sede se resuelve con
     `resolve_write_sucursal` (§1.5.3), que valida contra `allowed_sucursales` y **hace imposible**
     colar una sede ajena, ni por `sucursal_id` explícito ni omitiendo el header (`:222-228`).
5. Se crea la nota con `author=user` y `created_by=user` (`:356-370`).

**Éxito:** 201 con `NoteOutput`.
**Errores:** 400 de serializer; 400 `{"detail": ["<mensaje>"]}` de todas las reglas anteriores
(§1.7.2); 401; 403 sin tenant; 404 si falta el módulo.

**Efectos:** bitácora + reparto de notificaciones. Ver 9.5.

#### 9.2.3 `PATCH /api/v1/notas/<id>/`

**Resolución del objetivo** — `_note_get_or_404` (`views.py:68`) → `note_get`
(`selectors.py:24`) con `sucursal_ids = sucursal_scope_ids(request)`. Con alcance **parcial** de sede,
la nota solo es alcanzable si (`selectors.py:72-85`):

- es una nota **personal del propio actor**, o
- es un aviso (`role`/`all`) **no importante** cuya `sucursal` es `NULL` o está en su alcance.

Todo lo demás → **404** `{"detail": "Nota no encontrada."}`, nunca 403: no se revela la existencia.
Los avisos importantes quedan deliberadamente fuera del alcance de mutación de un no-owner aunque
**sí** los vea en el listado (razón escrita en `selectors.py:41-48`).

Con alcance **total** (`sucursal_ids=None`: owner, "admin de negocio" que cubre todas las sedes, o
clínica de una sola sede) **no se aplica ningún filtro**: cualquier nota del tenant es alcanzable por
id, incluidas las notas personales de otros usuarios. La autorización queda entonces en manos del
service, que responde **400** en vez de 404 → B-NOT-04.

**Entrada** (`InputSerializer`, `views.py:215-228`): `title`, `body`, `scope`, `target_role`,
`is_task`, `remind_at`, `pinned`. **No** acepta `done` (hay endpoint propio), ni `sucursal_id`, ni
`is_important`. Campos desconocidos se **ignoran en silencio** (no hay whitelist como en pacientes).
Cuerpo vacío → 400 `{"detail": "No se proporcionaron campos para actualizar."}` (`views.py:250-254`).

**Reglas del service `note_update`** (`services.py:445`):
1. **Autorización** `_can_mutate` (`:150`): el autor siempre; además, **el owner del tenant** sobre
   cualquier nota `role`/`all` aunque no la haya escrito (supervisión). Si no: 400 "No tienes permiso
   para editar esta nota."
2. Campos inmutables (`_NOTE_IMMUTABLE_FIELDS`, `:81-101`): `id`, `tenant`, `created_at`,
   `updated_at`, `deleted_at`, `author`, `done`, **`sucursal`** e **`is_important`**. Si llegaran, 400.
3. Solo se procesan `title`, `body`, `is_task`, `remind_at`, `pinned`, `target_role`, `scope`
   (`:493`). Si tras filtrar no queda nada, devuelve la nota sin tocar **200**, sin auditar (`:496-497`).
4. Debe seguir habiendo `title` o `body` con contenido (`:514`).
5. Si cambia `scope`, se revalida quién puede: `all` → owner o admin; `role` → `ROLE_NOTE_SENDERS`
   (`:522-535`). Si el nuevo scope es `role`, `target_role` obligatorio y válido; si es otro, se
   fuerza a `""` (`:538-548`).

**El agujero de este service**: la sede y el destacado **no se re-resuelven** al cambiar el scope. Una
nota nacida `personal` tiene `sucursal=NULL`, y `NULL` significa "todas las sedes". Convertirla a
`all` o a `role` la publica en **toda la clínica**, saltándose el confinamiento de sede que
`note_create` impone a los no-owner. El comentario de `:518-521` afirma que el aviso "conserva la
sede con la que fue creado" — cierto solo si nació como aviso. Ver **B-NOT-01**.

#### 9.2.4 `DELETE /api/v1/notas/<id>/`

Mismo `_note_get_or_404` y misma autorización `_can_mutate`. `note_delete` (`services.py:618`) hace
**soft-delete**: `deleted_at = now()`, nunca `DELETE` físico (`:635-636`). Respuesta **204 sin
cuerpo**. Errores: 400 "No tienes permiso para eliminar esta nota.", 404, 401, 403.

No existe endpoint para restaurar una nota borrada.

#### 9.2.5 `POST /api/v1/notas/<id>/done/`

Sin cuerpo. Alterna `done` (`note_toggle_done`, `services.py:573`). Dos validaciones, ambas 400:

- `is_task=False` → "Solo se puede marcar como hecha una nota que sea una tarea (is_task=True)."
- `note.author_id != user.pk` → "Solo el autor puede marcar esta tarea como hecha o pendiente."
  **Ni siquiera el owner puede cerrar la tarea de otro** — es la única acción del módulo donde el
  owner no tiene la última palabra.

Respuesta 200 con `NoteOutput` ya alternado.

#### 9.2.6 `GET /api/v1/notas/recordatorios/`

**Query params obligatorios los dos** (`views.py:347-349`): `date_from` y `date_to`, datetimes ISO.
Si falta cualquiera → 400 con forma de serializer. El cliente los declara **opcionales**
(`web-soft/src/api/notas.ts:37`), así que una llamada sin rango revienta con 400 → B-NOT-06.

Devuelve las notas visibles del usuario (misma lógica de 9.2.1, incluido el acotamiento por sede) con
`remind_at` en `[date_from, date_to)`, ordenadas por `remind_at` ascendente
(`selectors.py:216-221`). Paginado estándar de 25.

---

### 9.3 Reglas de negocio verificadas en código

1. **Una nota personal es privada del autor y no tiene sede.** Ni el owner la ve en su listado
   (`selectors.py:160`: la rama personal exige `author=user`). Sí puede alcanzarla por id cuando
   tiene alcance total, pero no puede mutarla (`services.py:157-164`).
2. **Un aviso a toda la clínica lo mandan owner y admin.** Desde el 2026-07-16 ya no es exclusivo del
   owner (`services.py:106-108`, `:314-322`). El comentario del cliente de frontend sigue diciendo
   "global: solo Dueño" (`web-soft/src/api/notas.ts:16`) — desactualizado, no cambia el
   comportamiento del backend.
3. **Un aviso dirigido a un rol lo manda el staff clínico**: owner, admin, doctor, nurse, reception.
   `finance` y `readonly` no pueden dirigir avisos, pero **sí pueden recibirlos**
   (`recipients.py:32-34` vs `services.py:332`).
4. **Solo el owner destaca un aviso.** Cualquier otro que lo intente recibe 400 explícito en vez de
   un silencioso `False` (decisión escrita en `services.py:189-190`).
5. **Solo el owner elige "todas las sedes".** Para cualquier otro actor la sede se fuerza a la suya
   con la misma precedencia que agenda, personal y finanzas (§1.5.3). **Con la excepción del PATCH de
   scope**, que se salta esta regla (B-NOT-01).
6. **`NULL` en `sucursal` = todas las sedes.** Es la única app donde nulo significa "todas" y no "sin
   asignar" (`models.py:109-116`, `migrations/0004:5-17`).
7. **Borrado lógico siempre**, y el `done` de una tarea solo por su endpoint dedicado
   (`_NOTE_IMMUTABLE_FIELDS`, `services.py:92`).
8. **El recordatorio es pasivo.** `remind_at` **no dispara nada**: no hay tarea Celery, señal ni
   comando que lo lea. Verificado por búsqueda de `remind_at` en todo `MailySoft/backend/`: solo
   aparece en `apps/notas/` (modelo, serializer, selector, vista, tests), `tests/factories.py` y la
   migración `0001`. El "recordatorio" es un filtro que el widget de agenda consulta por sondeo
   (`01-analisis.md:150`). Nadie recibe nada si no abre la aplicación.
9. **El módulo `notas` sí se hace valer** en los cuatro endpoints, a diferencia de `recordatorios`,
   que no se aplica en ninguna vista del sistema (§1.4.1, B-T-07).
10. **La autorización fina vive en el service, no en el permiso HTTP**, y el service la revalida por
    completo para poder invocarse desde Celery o un comando sin request (razón escrita en
    `services.py:15-16`). En consecuencia, un rechazo de negocio sale como **400**, no como 403.

---

### 9.4 Matriz de permisos del módulo

`NotePermission` (§1.3.2 #20) deja pasar a los 7 roles en los 4 métodos, así que **esta tabla es la
del `service` y el `selector`, no la del permiso HTTP**. Un "No" aquí significa 400 con `detail`
(regla de negocio) salvo donde se indique 404 (fuera de alcance de sede) o 403 (rol/módulo).

Leyenda: **Sí** = permitido · **Propias** = solo sobre registros propios · **No** = denegado.

| Acción | owner | admin | doctor | nurse | reception | finance | readonly |
|---|---|---|---|---|---|---|---|
| Ver mis notas personales | Propias | Propias | Propias | Propias | Propias | Propias | Propias |
| Ver avisos dirigidos a mi rol (en mi sede o de toda la clínica) | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Ver avisos `scope=all` (en mi sede o de toda la clínica) | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Ver notas personales de otros | No | No | No | No | No | No | No |
| Ver avisos de una sede que no es la mía | Sí (alcance total) | Solo si sus `MembershipSucursal` la cubren | ídem | ídem | ídem | ídem | ídem |
| Crear nota personal | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Crear tarea (`is_task`) | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Poner recordatorio (`remind_at`) | Sí | Sí | Sí | Sí | Sí | Sí | Sí |
| Crear aviso a un rol (`scope=role`) | Sí | Sí | Sí | Sí | Sí | **No** | **No** |
| Crear aviso a toda la clínica (`scope=all`) | Sí | Sí | **No** | **No** | **No** | **No** | **No** |
| Elegir la sede del aviso | Sí (cualquiera, o todas) | **No** — forzado a la suya | **No** | **No** | **No** | n/a | n/a |
| Marcar un aviso como importante | Sí | **No** | **No** | **No** | **No** | **No** | **No** |
| Editar nota propia (`PATCH`) | Propias | Propias | Propias | Propias | Propias | Propias | Propias |
| Editar aviso ajeno (`role`/`all`) | **Sí** (supervisión) | No | No | No | No | No | No |
| Editar aviso importante ajeno | Sí | **404** | **404** | **404** | **404** | **404** | **404** |
| Cambiar `scope` de una nota propia a `role` | Sí | Sí | Sí | Sí | Sí | **No** | **No** |
| Cambiar `scope` de una nota propia a `all` | Sí | Sí | **No** | **No** | **No** | **No** | **No** |
| Cambiar `sucursal` o `is_important` por PATCH | **No** (400) | No | No | No | No | No | No |
| Borrar nota propia (`DELETE`, soft) | Propias | Propias | Propias | Propias | Propias | Propias | Propias |
| Borrar aviso ajeno (`role`/`all`) | **Sí** | No | No | No | No | No | No |
| Marcar tarea como hecha | Propias | Propias | Propias | Propias | Propias | Propias | Propias |
| Marcar hecha la tarea de otro | **No** | No | No | No | No | No | No |
| Restaurar una nota borrada | n/a — no existe endpoint | n/a | n/a | n/a | n/a | n/a | n/a |
| Cualquier acción sin el módulo `notas` | **404** | 404 | 404 | 404 | 404 | 404 | 404 |

La fila del "admin de negocio" (rol no-owner cuyas `MembershipSucursal` cubren **todas** las sedes,
§1.5.2) merece una nota: recibe `sucursal_ids=None` y por lo tanto **alcance total en `note_get`**,
igual que el owner. Sigue sin poder mutar lo ajeno porque `_can_mutate` compara contra el rol
`owner`, no contra el alcance — pero sí puede alcanzar por id cualquier nota del tenant y recibir un
400 en vez de un 404 (B-NOT-04).

---

### 9.5 Efectos secundarios

| Acción | Efecto colateral | Dónde |
|---|---|---|
| `POST /notas/` (`scope=personal`) | Bitácora `NOTE_CREATE` | `services.py:373-398` |
| `POST /notas/` (`scope=role`) | Bitácora `NOTE_GLOBAL_SEND` + **una fila `Notification` por cada usuario con ese rol**, filtrada por sede | `services.py:408-423` |
| `POST /notas/` (`scope=all`) | Bitácora `NOTE_GLOBAL_SEND` + **una fila `Notification` por cada usuario activo de la clínica**, filtrada por sede | `services.py:424-439` |
| `PATCH /notas/<id>/` | Bitácora `NOTE_UPDATE` con `changed_fields`. **No** vuelve a repartir notificaciones aunque la nota pase a ser un aviso | `services.py:557-567` |
| `POST /notas/<id>/done/` | Bitácora `NOTE_UPDATE` con `metadata={"done": …}` | `services.py:602-612` |
| `DELETE /notas/<id>/` | Bitácora `NOTE_DELETE`. **Las notificaciones ya repartidas no se borran**: la campana sigue apuntando a una nota que ya no existe | `services.py:639-649` |
| Toda escritura | Corre dentro de `@transaction.atomic` (`services.py:241`, `:444`, `:572`, `:617`), así que el fan-out de notificaciones y la nota se confirman juntos | — |

#### 9.5.1 Qué texto viaja a la notificación

`notification_fanout` (`apps/notificaciones/services.py:43`) crea **una fila `Notification` por
destinatario** (fan-out on write, `:85-98`), excluyendo al autor y deduplicando. Los campos que
recibe desde `notas`:

| Campo de `Notification` | Valor | Dónde |
|---|---|---|
| `title` | **el `title` de la nota tal cual**; si va vacío, `"Nueva nota para <Rol>"` o `"Aviso para toda la clínica"` / `"Aviso importante"` | `services.py:418`, `:433-434` |
| `body` | **los primeros 200 caracteres del cuerpo de la nota, sin filtrar** | `services.py:419`, `:435` |
| `kind` | `ROLE_NOTE` o `BROADCAST` | `:417`, `:432` |
| `target_type` / `target_id` | `NOTE` + UUID de la nota | `:421-422`, `:437-438` |
| `actor` | el autor | — |

Es decir: **el contenido de la nota se copia, literal, a tantas filas como destinatarios haya**. Si un
médico escribe "Llamar a Ana López, la biopsia salió positiva" en un aviso a recepción, ese texto
queda duplicado en la tabla de notificaciones de cada recepcionista. Es el riesgo 4 de
`01-analisis.md:340-342`, aquí confirmado con línea → B-NOT-02.

Destinatarios (`apps/notificaciones/recipients.py`):
- `scope=role` → `users_with_role` (`:57`): membresías activas con ese rol.
- `scope=all` → `all_tenant_users` (`:67`): **los 7 roles, `finance` y `readonly` incluidos**
  explícitamente (`:70-71`).
- Ambos pasan por `filter_recipients_by_sucursal` (`:87`): si el aviso quedó acotado a una sede, la
  campana solo suena a quien trabaja en ella, y **el dueño queda excluido a propósito** de las
  campanas de sede (razón escrita en `:96-103`) — las sigue viendo en `/notas/`, pero no le suenan.
  Con `sucursal_id=None` no filtra nada y el dueño sí recibe.

#### 9.5.2 Qué texto viaja a la bitácora

Las cinco llamadas a `audit_record` de esta app pasan **`resource_repr=str(note)`**
(`services.py:384`, `:563`, `:607`, `:645`). `Note.__str__` (`models.py:149-153`) devuelve:

```
[<scope>] <title, o los primeros 40 caracteres del body> — <email del autor>
```

O sea, la bitácora guarda **contenido de la nota y el correo del autor**. Contrasta de frente con la
app de pacientes, que en cada llamada pasa `record_number` con el comentario "identificador no-PII
(minimización LFPDPPP)", y con la regla dura 5 del `CLAUDE.md` del repo ("identificador no-PII del
recurso"). Ver **B-NOT-03**.

#### 9.5.3 Lo que no ocurre

No hay señales (`post_save`), ni tareas Celery, ni caché, ni envío por correo o WhatsApp en toda la
app (verificado: `apps/notas/` no importa `celery`, `signals`, `cache` ni ningún adaptador). El único
acoplamiento hacia afuera son `apps/audit` y `apps/notificaciones`. `remind_at` no dispara nada
(9.3 punto 8).
## 10. Notificaciones in-app

> Extraído del código el 2026-08-12 (modo inverso). Las rutas `apps/…` abrevian
> `MailySoft/backend/apps/…` desde la raíz del repo. Lo transversal (aislamiento, permisos, formato
> de error, paginación) **se cita** de `docs/_a2-partes/00-transversal.md`, no se repite.

La campana. Un solo modelo, cuatro endpoints, cero endpoints de escritura de contenido: las
notificaciones **no se crean por API**, las crean los services de otras apps por *fan-out on write*
(`apps/notificaciones/models.py:11-14`).

---

### 10.1 Modelo de datos

#### 10.1.1 `Notification` → `notificaciones_notifications` (`apps/notificaciones/models.py:57`)

**Hereda `TenantAwareModel`** (`models.py:57`), así que trae `id` UUID, `created_at`, `updated_at`,
`deleted_at`, `tenant` (FK `PROTECT`, no nulo) y `created_by` (FK `SET_NULL`) — ver §1.8.2.

| Campo | Tipo | `on_delete` | Null | Default | Consecuencia real de esa elección |
|---|---|---|---|---|---|
| `recipient` | FK `authn.User`, `related_name="notifications"`, `db_index=True` (`:76-82`) | **CASCADE** | no | — | Borrar en duro un usuario **borra todas sus notificaciones**. Es correcto: una notificación sin destinatario no significa nada. Contrasta con `created_by`, que es `SET_NULL` |
| `actor` | FK `authn.User`, `related_name="+"` (`:83-90`) | **SET_NULL** | **sí** | `NULL` | Borrar al que disparó el evento deja el aviso legible con "actor: null". El aviso sobrevive a la baja de quien lo generó |
| `kind` | `CharField(20)` choices `NotificationKind`, `db_index=True` (`:91-96`) | — | no | — | Sin default: siempre lo fija el service que reparte |
| `title` | `CharField(160)` (`:97-100`) | — | no | — | **Denormalizado**: texto ya armado. Aquí es donde entra la PII (ver 10.3) |
| `body` | `TextField` (`:101-105`) | — | no | `""` | Denormalizado. Los callers cortan a 200 caracteres |
| `target_type` | `CharField(20)` choices `NotificationTarget`, blank (`:106-112`) | — | no | `""` | `""` = la notificación no lleva a ningún lado |
| `target_id` | `UUIDField` (`:113-117`) | — | **sí** | `NULL` | **Referencia débil**: no hay FK. Si el objeto destino se borra, el clic lleva a un 404, no rompe la fila |
| `read_at` | `DateTimeField`, `db_index=True` (`:118-123`) | — | **sí** | `NULL` | `NULL` = no leída. Es el único estado |

`ordering = ["-created_at"]` (`:127`). `db_table = "notificaciones_notifications"` (`:126`).
Propiedad derivada `is_read` = `read_at is not None` (`:140-143`), expuesta en la respuesta.

#### 10.1.2 Catálogos

`NotificationKind` — 7 valores (`models.py:32-41`): `meeting`, `team_note`, `role_note`,
`broadcast`, `nursing_instruction`, `credential_review`, `credential_result`.

`NotificationTarget` — 5 valores (`models.py:44-54`): `appointment`, `agenda_block`, `note`,
`patient`, `credential`. Más el valor vacío `""` (sin destino).

#### 10.1.3 Índices existentes y la consulta que justifica cada uno

| Índice | Definición | Consulta que lo necesita |
|---|---|---|
| `notif_recip_read_idx` | `(recipient, read_at)` (`models.py:130`) | `GET /notificaciones/conteo/` → `filter(recipient, read_at__isnull=True).count()` (`selectors.py:84-88`). Es la consulta que el front dispara cada ~30 s |
| `notif_recip_created_idx` | `(recipient, -created_at)` (`models.py:132`) | `GET /notificaciones/` → `filter(recipient) ORDER BY -created_at` (`selectors.py:65-68` + `Meta.ordering`) |

No hay índice sobre `tenant` más allá del que crea la FK (`core/models.py:44-50`), y no hace falta:
las dos consultas del producto arrancan por `recipient`, que es mucho más selectivo.

#### 10.1.4 RLS

Sí, la tabla la tiene: `ENABLE` + `FORCE` + policy `notificaciones_notifications_tenant_isolation`
con `USING` (`apps/notificaciones/migrations/0002_enable_rls.py:23-28`) y el `WITH CHECK` agregado
después (`0005_rls_with_check.py:22`). Forma canónica de §1.1.1, con el fallback
`OR current_tenant_id() IS NULL`.

---

### 10.2 Endpoints

Prefijo `/api/v1/` (`MailySoft/backend/config/urls.py:45`). Rutas en
`apps/notificaciones/urls.py:25-46`. Las cuatro vistas heredan de `TenantAPIView`
(`apps/notificaciones/views.py:54`, `:94`, `:113`, `:128`) y declaran
`permission_classes = [IsAuthenticated, NotificationPermission]` (`views.py:61`, `:101`, `:116`,
`:131`).

`NotificationPermission` es la clase #37 del inventario §1.3.2 (`apps/core/permissions.py:1060`):
**GET y POST abiertos a los 7 roles**. La decisión está escrita en `views.py:11-15`: la notificación
es privada de su destinatario y quien acota es el **selector** (`recipient=request.user`), no el
permiso HTTP.

**Ninguno lleva guard de módulo.** La campana no es un módulo vendible: llega con cualquier plan.
Verificado: en `views.py` no se importa ningún `Requires*`.

| Método | Ruta | Vista:línea | Éxito | Errores |
|---|---|---|---|---|
| GET | `/api/v1/notificaciones/` | `views.py:54` | 200 paginado | 401, 403, 500 |
| GET | `/api/v1/notificaciones/conteo/` | `views.py:94` | 200 `{"unread": N}` | 401, 403 |
| POST | `/api/v1/notificaciones/leidas/` | `views.py:113` | 200 `{"updated": N}` | 401, 403 |
| POST | `/api/v1/notificaciones/<uuid:notification_id>/leida/` | `views.py:128` | 200 `Notification` | 401, 403, 404 |

Las rutas estáticas (`conteo/`, `leidas/`) se declaran **antes** que la dinámica para que no colisione
la resolución (`urls.py:12-13`).

#### `GET /api/v1/notificaciones/`

- **Query params:** `only_unread` (bool, opcional, default `false`) — validado con un serializer
  declarado dentro del handler (`views.py:69-73`); un valor no booleano da **400** con forma de
  serializer. `page` (paginación estándar). **`page_size` NO se admite**: la vista instancia
  `PageNumberPagination()` sin `page_size_query_param` (`views.py:81`), así que rige `PAGE_SIZE=25`
  de settings (§1.7.1).
- **Alcance:** `notification_list_for_user` filtra `tenant=` **y** `recipient=user` de forma
  explícita, además del filtro automático del `TenantManager` (`selectors.py:65-68`). Defensa en
  profundidad declarada.
- **Sin filtro por sucursal**, y es correcto: la notificación ya nació dirigida a una persona; el
  acotamiento por sede se hace **al repartir** (10.3), no al leer.
- **Respuesta** `{count, next, previous, results[]}`; cada elemento
  (`apps/notificaciones/serializers.py:24-58`):

```json
{
  "id": "uuid",
  "actor": {"id": "uuid", "full_name": "Ana Ruiz"},
  "kind": "team_note",
  "kind_display": "Nota de equipo",
  "title": "Nueva nota en la cita de Juan Pérez",
  "body": "Traer estudios de la semana pasada…",
  "target_type": "appointment",
  "target_id": "uuid",
  "read_at": null,
  "is_read": false,
  "created_at": "2026-08-12T10:00:00-06:00"
}
```

`actor` es `null` si el evento lo generó el sistema o el usuario se borró
(`serializers.py:39` + `models.py:83-90`). Todos los campos son `read_only`
(`serializers.py:58`).

- **500** si `PAGE_SIZE` no estuviera configurado (`views.py:88-91`). Es una rama defensiva: hoy
  `PAGE_SIZE=25` siempre está.

#### `GET /api/v1/notificaciones/conteo/`

- Sin parámetros. Devuelve `{"unread": <int>}` (`views.py:110`).
- Es un `COUNT` con el índice `notif_recip_read_idx`. Existe explícitamente para que el front
  sondee cada ~30 s sin traer la lista (`views.py:97-98`).

#### `POST /api/v1/notificaciones/leidas/`

- Sin cuerpo. Marca **todas** las no leídas del usuario en el tenant activo
  (`services.py:180-184`, un solo `UPDATE`). Devuelve `{"updated": <int>}` = filas afectadas
  (0 si ya estaban todas leídas).

#### `POST /api/v1/notificaciones/<id>/leida/`

- Sin cuerpo. **Idempotente**: si ya estaba leída no toca `read_at` (`services.py:162-164`).
- Doble verificación de propiedad: el selector filtra `recipient=user` en la query
  (`selectors.py:43`) y el service revalida `notification.recipient_id != user.pk`
  (`services.py:159-160`).
- Si la notificación es de otro usuario **o de otro tenant** → `Notification.DoesNotExist` →
  **404** `{"detail": "Notificación no encontrada."}` (`views.py:142-146`). Nunca 403: no se revela
  que exista.
- Éxito: **200** con el objeto completo (no 204), para que el front actualice la fila sin recargar.

---

### 10.3 Qué dispara cada notificación y qué contenido lleva

Las notificaciones se crean **solo** desde `notification_fanout` (`services.py:43`) o su atajo
`notification_create` (`services.py:109`). Ocho puntos de disparo en todo el backend (verificado por
búsqueda de ambos nombres en `apps/`, excluyendo tests):

| # | `kind` | Disparo (`archivo:línea`) | `title` | `body` | `target` | ¿PII? |
|---|---|---|---|---|---|---|
| 1 | `meeting` | Crear evento de agenda tipo reunión — `apps/agenda/blocks.py:144-153` | `f"Reunión: {title or 'Junta'}"` (`:148`) | `notes[:200]` — notas internas del evento (`:149`) | `agenda_block` + id | Texto libre del actor |
| 2 | `team_note` | Nota de equipo sobre una **cita** — `apps/agenda/notes.py:139-148` | `f"Nueva nota en la cita de {appointment.patient.full_name}"` (`:143`) | `body[:200]` — el texto de la nota (`:144`) | `appointment` + id | **Sí: nombre completo del paciente** |
| 3 | `team_note` | Nota de equipo sobre un **evento** — `apps/agenda/notes.py:159-168` | `f"Nueva nota en {agenda_block.title or 'un evento'}"` (`:163`) | `body[:200]` (`:164`) | `agenda_block` + id | Texto libre |
| 4 | `role_note` | Nota dirigida a un rol — `apps/notas/services.py:410-423` | `title or f"Nueva nota para {role_label}"` (`:418`) | `body[:200]` (`:419`) | `note` + id | Texto libre del actor |
| 5 | `broadcast` | Aviso a toda la clínica — `apps/notas/services.py:425-439` | `title` o `"Aviso importante"` / `"Aviso para toda la clínica"` (`:433-434`) | `body[:200]` (`:435`) | `note` + id | Texto libre del actor |
| 6 | `nursing_instruction` | Evolución con indicaciones de enfermería — `apps/expediente/services.py:788-797` | `"Indicaciones de enfermería pendientes"` — **fijo** (`:792`) | `"Hay nuevas indicaciones en el expediente del paciente."` — **fijo** (`:793`) | `patient` + id | **No.** Decisión explícita en `:775-776` |
| 7 | `credential_review` | Alta de credencial de médico — `apps/clinica/services.py:64-73` | `f"Credencial por validar — {doctor_name}"` (`:68`) | `f"{credential.title} ({credential.institution}). Revísala y valídala."` (`:69`) | `credential` + id | Nombre del **médico** (staff, no paciente) |
| 8 | `credential_result` | Validación/rechazo de credencial — `apps/clinica/services.py:95-104` | `"Tu credencial fue validada"` / `"…rechazada"` (`:89`, `:93`) | `f"{credential.title}: {motivo}."` — el motivo lo escribe el admin (`:94`) | `credential` + id | Texto libre del admin |

**El caso 2 es el que confirma el riesgo del análisis** (`docs/01-analisis.md:340-342`): el nombre
completo del paciente queda escrito, denormalizado y permanente, en `title`; y `body` lleva un
extracto de lo que un médico escribió sobre esa cita, entregado a recepción. Ver `B-NTF-01`.
El caso 6 lo hace bien y demuestra que el patrón sin PII es posible: navega con
`target_type=patient` + `target_id` y deja que el receptor abra el expediente si tiene permiso.

#### 10.3.1 Cómo se resuelven los destinatarios

Módulo `apps/notificaciones/recipients.py`. Solo conoce `TenantMembership` (roles); el mapeo de
dominio lo arma cada app (`recipients.py:8-10`).

| Helper | Línea | Devuelve |
|---|---|---|
| `users_with_roles(tenant, roles)` | `:37` | Usuarios con membresía **activa** y no borrada en esos roles |
| `users_with_role(tenant, role)` | `:57` | Atajo del anterior |
| `clinic_staff_users(tenant)` | `:62` | `STAFF_ROLES` = owner, admin, doctor, nurse, reception (`:22-28`) — **excluye finance y readonly** |
| `all_tenant_users(tenant)` | `:67` | Los 7 roles. Solo lo usa el broadcast |
| `filter_recipients_by_sucursal(tenant, recipients, sucursal_id)` | `:87` | Subconjunto que pertenece a esa sede |

**El filtro por sede** (`recipients.py:87-142`), decisión del 2026-07-16:

- `sucursal_id=None` → **no filtra nada** (`:121-122`). Un aviso "de toda la clínica" suena para
  todos, incluido el dueño.
- Con sede concreta: se queda quien tenga esa sede en `allowed_sucursales` (§1.5.1) **y**
  el **dueño queda excluido a propósito** (`:128-141`). El owner ve el aviso en la lista de Notas
  pero no recibe la campana de cada aviso interno de cada sede.

Quién acota por sede y quién no:

| Disparo | ¿Filtra por sede? |
|---|---|
| Reunión sin médico ni consultorio | Sí, por `block.sucursal_id` (`agenda/blocks.py:139-143`) |
| Reunión con médico / con consultorio | No: los destinatarios ya son los directamente implicados (`blocks.py:126-134`) |
| Nota de equipo en cita | Solo la **recepción** se filtra; el médico de la cita y quienes ya comentaron van siempre (`agenda/notes.py:128-138`) |
| Nota a un rol / broadcast | Sí (`notas/services.py:412-416`, `:427-431`) |
| Indicaciones de enfermería | Sí, por `appointment.sucursal_id` (`expediente/services.py:783-787`) |
| Credencial por validar | **No.** Se reparte a todos los owner+admin del tenant (`clinica/services.py:62`) → ver `B-NTF-05` |
| Resultado de credencial | No aplica: destinatario único |

---

### 10.4 Matriz de permisos

Las cuatro operaciones son **sobre los propios registros del usuario y solo sobre ellos**. No hay
ninguna celda "todos los registros": ni el dueño puede leer la campana de otro.

| Rol | `GET /notificaciones/` | `GET /conteo/` | `POST /leidas/` | `POST /<id>/leida/` | Recibir notificaciones |
|---|---|---|---|---|---|
| `owner` | Solo las suyas | Solo las suyas | Solo las suyas | Solo las suyas | Sí, **salvo** avisos acotados a una sede (`recipients.py:128-141`) |
| `admin` | Solo las suyas | Solo las suyas | Solo las suyas | Solo las suyas | Sí, si es miembro de la sede del evento |
| `doctor` | Solo las suyas | Solo las suyas | Solo las suyas | Solo las suyas | Sí |
| `nurse` | Solo las suyas | Solo las suyas | Solo las suyas | Solo las suyas | Sí (única receptora de `nursing_instruction`) |
| `reception` | Solo las suyas | Solo las suyas | Solo las suyas | Solo las suyas | Sí |
| `finance` | Solo las suyas | Solo las suyas | Solo las suyas | Solo las suyas | Solo `broadcast` (fuera de `STAFF_ROLES`, `recipients.py:22-28`) |
| `readonly` | Solo las suyas | Solo las suyas | Solo las suyas | Solo las suyas | Solo `broadcast` |
| Staff de plataforma **sin** membresía | 403 | 403 | 403 | 403 | No |
| Usuario con `must_change_password=True` | 403 `password_change_required` | 403 | 403 | 403 | Se acumulan, no las ve |

Fuente de las cuatro primeras columnas: `NotificationPermission` abre los 7 roles
(`core/permissions.py:1060`, §1.3.2 #37) y el selector acota a `recipient=user`
(`selectors.py:65-68`). Las dos últimas filas salen de §1.2.4 y `core/permissions.py:129-131`.

**No hay ninguna operación de creación ni de borrado por API.** `PUT`, `PATCH` y `DELETE` sobre
cualquiera de las cuatro rutas → **405** (los handlers no existen).

---

### 10.5 Efectos secundarios

| Efecto | Dónde | Detalle |
|---|---|---|
| **Nunca te notificas a ti mismo** | `services.py:78` | El `actor` se excluye del reparto por `pk` |
| **Deduplicación de destinatarios** | `services.py:75-80` | Un usuario que califica por dos vías (médico de la cita *y* comentó el hilo) recibe **un** aviso |
| **Reparto vacío = no-op** | `services.py:82-83` | Si tras filtrar no queda nadie, no se crea nada y devuelve `[]` |
| **Escritura en lote** | `services.py:99` | `bulk_create`: una sola sentencia para N destinatarios |
| **Log de reparto** | `services.py:100-105` | `INFO` con `kind` y `tenant.pk`. **Sin PII**: no loguea título ni cuerpo |
| **`created_by` = actor** | `services.py:88` | Coincide con `actor`; si el actor es `None`, ambos quedan nulos |
| **Marcar leída** | `services.py:164` | `save(update_fields=["read_at","updated_at"])`, dentro de `transaction.atomic` |
| **Marcar todas** | `services.py:180-184` | Un `UPDATE` masivo. No dispara `auto_now` de `updated_at` — las filas quedan con `updated_at` viejo |
| **Sin bitácora** | — | Ninguna operación de esta app llama a `audit_record`. Leer o marcar leída una notificación **no** deja rastro en la bitácora. Es coherente con §1.8.5 (solo acciones sensibles), pero conviene tenerlo presente |
| **Sin correo, sin push, sin WebSocket** | — | El único transporte es el sondeo del front. `channels` está instalado y sin usar (`docs/01-analisis.md:266`) |

#### 10.5.1 Manejo de fallos del reparto: asimétrico

Tres de los cuatro callers envuelven el fanout en `try/except` para que un fallo de la campana no
tumbe la operación de negocio:

- `apps/agenda/blocks.py:125-159` — `except Exception`, log `ERROR`, el evento se crea igual.
- `apps/agenda/notes.py:121-174` — igual.
- `apps/expediente/services.py:778-804` — igual, con la razón escrita: *"disponibilidad clínica >
  entrega garantizada de avisos"*.
- `apps/clinica/services.py:57-75` y `:83-106` — igual, log `WARNING`.

**`apps/notas/services.py:408-439` no lo hace.** El fanout de `role_note` y `broadcast` corre sin
protección: si falla, se propaga y la nota no se crea. Ver `B-NTF-03`.

#### 10.5.2 Costo del sondeo cada 30 s

Confirmado en el código: el endpoint de conteo existe explícitamente para eso
(`views.py:97-98`) y el análisis lo describe igual (`docs/01-analisis.md:149-151`).

- Por pestaña abierta: 2 `COUNT` por minuto, servidos por `notif_recip_read_idx`.
- El throttle que aplica es el global `user` = 300/min (§1.7.3). No hay throttle propio ni caché.
- Con 1–3 usuarios concurrentes es irrelevante. No se propone caché: sería complejidad sin número
  que la justifique.

El costo real no está en la lectura sino en el **reparto**: `filter_recipients_by_sucursal` ejecuta
una consulta `allowed_sucursales(...).exists()` **por destinatario** (`recipients.py:141`). Un
broadcast a 20 personas son 20 consultas más. Ver `B-NTF-04`.
## 11. Autenticación y usuarios

> Extraído del código el 2026-08-12 (modo inverso). Las rutas `apps/…` abrevian
> `MailySoft/backend/apps/…` desde la raíz del repo. El **esquema de tokens, la cookie de refresh,
> el CSRF, el candado `must_change_password` y la tabla de rutas `/api/v1/auth/…`** ya están en
> §1.2: aquí se documenta lo que §1.2 no cubre — el modelo `User`, el detalle de `/me/` y
> `/change-password/`, la política de contraseñas y los efectos de cada endpoint.

---

### 11.1 Modelo de datos (`User` y afines)

#### 11.1.1 `User` → `authn_users` (`apps/authn/models.py:23`)

Hereda de `AbstractBaseUser` + `PermissionsMixin` (`models.py:23`). **No hereda `BaseModel` ni
`TenantAwareModel`**, y es correcto: un usuario puede pertenecer a varias clínicas, así que no
"pertenece" a ninguna (§1.1.6). Consecuencias directas de esa decisión, que hay que tener presentes:

- **No tiene `updated_at` ni `deleted_at`.** No hay soft-delete: la baja es `is_active=False`
  (`models.py:57-60`). El propio service de plataforma lo asume (`plataforma/services.py:1194-1196`,
  que arma `update_fields` sin `updated_at`).
- **No tiene RLS** ni política de aislamiento. El aislamiento de "qué usuarios veo" lo hace cada
  selector: `apps/tenancy/selectors.py` para el equipo de una clínica, `platform_staff_list` para el
  equipo interno.

| Campo | Tipo | Null | Default | Índice / constraint | Notas |
|---|---|---|---|---|---|
| `id` | `UUIDField` PK, `editable=False` (`:42`) | no | `uuid.uuid4` | PK | |
| `password` | `CharField(128)` (heredado, `migrations/0001_initial.py:20`) | no | — | — | Hash Argon2 (11.3) |
| `last_login` | `DateTimeField` (heredado, `0001_initial.py:21`) | **sí** | `NULL` | — | Lo actualiza Django al autenticar |
| `is_superuser` | `BooleanField` (heredado, `0001_initial.py:22`) | no | `False` | — | Permisos de Django, **no** de plataforma |
| `email` | `EmailField(254)` (`:43-46`) | no | — | **unique** | Es el `USERNAME_FIELD` (`:90`) |
| `first_name` | `CharField(120)`, blank (`:47`) | no | `""` | — | |
| `last_name` | `CharField(120)`, blank (`:48`) | no | `""` | — | |
| `avatar` | `ImageField(max_length=255)`, `upload_to=user_avatar_path` (`:49-55`) | **sí** | `NULL` | — | Validado con `validate_image` de §1.8.4 al subirlo |
| `is_active` | `BooleanField` (`:57-60`) | no | `True` | — | `False` = cuenta bloqueada. Es lo que expone `is_blocked` en §1.9 |
| `is_staff` | `BooleanField` (`:61-64`) | no | `False` | — | **Acceso al Django admin.** El docstring avisa que no implica ser staff de plataforma… pero `platform_staff_create` lo pone en `True` a todo el equipo (`plataforma/services.py:1058`) → ver `B-AUT-02` |
| `is_platform_staff` | `BooleanField` (`:65-69`) | no | `False` | **db_index** | Puerta de entrada al panel interno (`core/permissions.py:1153-1159`) |
| `platform_role` | `CharField(20)` choices `PlatformRole`, blank (`:70-76`) | no | `""` | — | Se ignora si `is_platform_staff=False` (`:75`) |
| `must_change_password` | `BooleanField` (`:77-85`) | no | `False` | — | Candado de §1.2.4 |
| `date_joined` | `DateTimeField(auto_now_add=True)` (`:86`) | no | ahora | — | Única marca temporal del modelo |
| `groups` / `user_permissions` | M2M a `auth.Group` / `auth.Permission` (`0001_initial.py:32-33`) | — | vacío | — | Solo se usan en el Django admin. La API **no** los consulta |

`Meta`: `db_table = "authn_users"`, `ordering = ["email"]` (`:93-97`).
Propiedad derivada `full_name` = `"first last"` o el email si ambos están vacíos (`:102-105`).

**`PlatformRole`** (`models.py:35-40`): `super_admin`, `sales`, `engineering`. Es la misma lista de
§1.6.2.

#### 11.1.2 Índices que no existen y hoy no hacen falta

Solo hay dos índices más allá de la PK: el `unique` de `email` (que sirve tanto al login como a los
pre-checks de duplicado) y el `db_index` de `is_platform_staff` (que sirve a
`platform_staff_list`, `selectors.py:145`, y al conteo de métricas, `selectors.py:116`). No se
propone ninguno más: con decenas de usuarios por clínica cualquier índice adicional es peso muerto en
cada escritura.

#### 11.1.3 `UserManager` (`apps/authn/managers.py:16`)

- `create_user(email, password, **extra)` (`:24`): exige email no vacío (`:44-45`), lo normaliza con
  `normalize_email` — que **solo pasa a minúsculas el dominio**, no la parte local — y guarda
  (`:46-50`).
- `create_superuser(email, password, **extra)` (`:52`): fuerza `is_staff=True`, `is_superuser=True`
  **y `is_platform_staff=True`** (`:72-74`), pero **no fija `platform_role`**. Un superusuario creado
  con `createsuperuser` pasa `IsPlatformStaff` y falla **todos** los permisos que exigen un rol
  concreto (§1.3.4 #42–#50). Ver `B-AUT-03`.

#### 11.1.4 Modelos afines que esta app consume

| Modelo | Dónde vive | Qué aporta aquí |
|---|---|---|
| `tenancy.TenantMembership` | §1.10.2 | Liga usuario ↔ clínica ↔ rol. `FK user CASCADE`: borrar en duro un usuario borra sus membresías |
| `OutstandingToken` / `BlacklistedToken` | `rest_framework_simplejwt.token_blacklist` (app de terceros) | Refresh tokens emitidos y revocados. Los escribe `password_change` (`services.py:82-84`) y `platform_staff_password_reset` (`plataforma/services.py:1286-1288`) |
| `personal.Doctor` | app `personal` | `/me/` lo consulta para devolver `doctor_id` (`views.py:407`) |
| `clinica.Sucursal` | app `clinica` | `/me/` lo consulta vía `allowed_sucursales` (`views.py:418`) |

---

### 11.2 Endpoints

#### 11.2.1 Mapa completo

| Método | Ruta | Vista:línea | Registrada en | Permiso | Documentado en |
|---|---|---|---|---|---|
| POST | `/api/v1/auth/login/` | `apps/authn/views.py:137` | `config/urls.py:31` | ninguno (público) + throttle `auth_login` | §1.2.3 y 11.2.2 |
| POST | `/api/v1/auth/refresh/` | `apps/authn/views.py:239` | `config/urls.py` | ninguno (la cookie es la credencial) + `@csrf_protect` | §1.2.3 |
| POST | `/api/v1/auth/logout/` | `apps/authn/views.py:287` | `config/urls.py` | `IsAuthenticated` (`:304`) + `@csrf_protect` | §1.2.3 y 11.2.3 |
| POST | `/api/v1/auth/verify/` | `TokenVerifyView` de SimpleJWT sin modificar | `config/urls.py:34` | ninguno | §1.2.3 |
| GET | `/api/v1/me/` | `apps/authn/views.py:354` | `apps/authn/urls.py:20` | `IsAuthenticated` (`:365`) | 11.2.4 |
| POST | `/api/v1/auth/change-password/` | `apps/authn/views.py:462` | `apps/authn/urls.py:21` | `IsAuthenticated` (`:496`) + throttle `auth_password_change` | 11.2.5 |

Las cuatro vistas de esta app heredan de `APIView` directo, **no** de `TenantAPIView`
(`views.py:287`, `:354`, `:462`). Tres consecuencias que hay que saber:

1. **No resuelven tenant ni fijan el GUC de RLS.** Cualquier consulta que hagan corre sin barrera de
   base de datos (§1.1.1). Por eso `/me/` llama a `allowed_sucursales`, que usa `all_objects` a
   propósito (§1.1.5).
2. **No fijan `request.active_role`.** Ningún permiso de rol clínico puede usarse aquí.
3. **Quedan exentas del candado `must_change_password`** por herencia, no por whitelist (§1.2.4).
   Es lo que permite que un usuario bloqueado llegue a `/me/` y a `/change-password/` para
   desbloquearse solo.

**No hay endpoint de registro público, ni de "olvidé mi contraseña", ni de verificación de correo.**
Verificado sobre `apps/authn/urls.py:19-22` y `config/urls.py`. Un usuario solo nace desde el panel
de plataforma (§13) o desde el alta de miembro de una clínica (§1.9). Quien pierde su contraseña
depende de que el dueño se la restablezca (`PATCH /miembros/<id>/` con `password`) o, si es staff
interno, de un `super_admin` (§13.2).

#### 11.2.2 `POST /api/v1/auth/login/` — lo que §1.2.3 no dice

- **Entrada:** `{"email": "...", "password": "..."}` (`email` porque es el `USERNAME_FIELD`,
  `models.py:90`). El serializer es el de SimpleJWT sin modificar.
- **Éxito 200:** `{"access": "<jwt>"}` — el `refresh` se saca del cuerpo y se mueve a la cookie
  (`views.py:166-169`). Además viaja la cookie `csrftoken` por `@ensure_csrf_cookie`
  (`views.py:136`).
- **Error 401:** `{"detail": "<mensaje de SimpleJWT>"}`. **Ningún código de este repositorio
  diferencia "correo inexistente" de "contraseña incorrecta"**: `MailyTokenObtainPairView.post`
  delega íntegramente en `super().post()` y solo actúa cuando el status es 200 (`views.py:162-173`).
  **NO VERIFICADO**: el texto exacto que devuelve SimpleJWT en cada caso — no leí la librería. Lo
  verificable aquí es que este repositorio no introduce enumeración de usuarios en el login.
- **Error 429:** throttle `auth_login` 5/min (`views.py:157-158`). Ver 11.3.4 para su alcance real.
- **Efecto de bitácora:** `_audit_login_success` (`views.py:175-230`) puebla el contexto HTTP a mano
  (`views.py:183-194`, incluyendo la IP desde `X-Forwarded-For` — §12.4) y registra `LOGIN`. Para
  hacerlo **vuelve a buscar al usuario por email** (`views.py:200-209`); si esa búsqueda falla, el
  login responde 200 igual y solo queda un `logger.warning`. Ver `B-AUT-06`.
- El fallo de login lo audita la señal `user_login_failed`, no esta vista (§12.2, `audit/apps.py:35`).

#### 11.2.3 `POST /api/v1/auth/logout/` — lo que §1.2.3 no dice

- Lee el refresh de la cookie y lo blacklistea (`views.py:308-313`). **No comprueba que ese refresh
  pertenezca a `request.user`** — ver `B-AUT-05`.
- Si el token ya expiró o ya estaba en la blacklist, captura `TokenError`, loguea `INFO` y sigue
  (`views.py:314-321`).
- Audita `LOGOUT` con el tenant resuelto por `resolve_membership_for_user` (`views.py:328-346`).
- **205 Reset Content** siempre que haya Bearer válido, con el `Set-Cookie` de borrado que **repite
  los mismos atributos** (`secure`, `samesite`, `path`) — si no, el navegador ignora el borrado de
  una cookie `Secure` (`views.py:111-128`).

#### 11.2.4 `GET /api/v1/me/`

- **Permiso:** solo `IsAuthenticated` (`views.py:365`). Responde 200 aunque el usuario **no tenga
  ninguna clínica activa** (`views.py:360-362`): es el endpoint de identidad, no de negocio.
- **Query params:** ninguno. **No pagina.**
- **Qué hace, en orden** (`views.py:376-454`): resuelve tenant activo → lista membresías activas →
  localiza la membresía del tenant activo → resuelve `doctor_id` **si el rol activo puede ejercer**
  (incluye `owner` y `admin`, no solo `doctor` — `views.py:391-409`) → resuelve sucursales
  permitidas → resuelve entitlements.
- **Respuesta 200** (`apps/authn/serializers.py:57-155`):

```json
{
  "id": "uuid",
  "email": "ana@clinica.mx",
  "first_name": "Ana",
  "last_name": "Ruiz",
  "full_name": "Ana Ruiz",
  "avatar": "https://…/avatar.jpg",
  "is_platform_staff": false,
  "platform_role": "",
  "must_change_password": false,
  "active_tenant": {"id": "uuid", "name": "Clínica Norte", "slug": "clinica-norte", "status": "active"},
  "active_role": "owner",
  "active_role_display": "Dueño",
  "memberships": [
    {"tenant": {"id": "uuid", "name": "…", "slug": "…", "status": "active"},
     "role": "owner", "role_display": "Dueño", "is_active": true}
  ],
  "doctor_id": "uuid",
  "sucursales": [{"id": "uuid", "name": "Centro", "is_default": true}],
  "capabilities": {
    "plan_slug": "pro", "plan_name": "Pro",
    "modules": ["agenda", "expediente", "…"],
    "roles": ["owner", "doctor", "…"],
    "max_sucursales": 1, "max_consultorios": 5, "max_usuarios": null,
    "sede_unica": true
  }
}
```

- `active_tenant`, `active_role`, `active_role_display` y `capabilities` son **`null`** si el usuario
  no tiene clínica activa (`serializers.py:102-121`, `:149-155`; `views.py:428-440`).
- `doctor_id` es `null` si el rol activo no puede ejercer o el usuario no tiene perfil de médico
  (`views.py:401-409`).
- `sucursales` es `[]` sin tenant activo (`views.py:414-419`).
- `_TenantBriefSerializer` **no** expone `trial_ends_at` ni `timezone`, decisión escrita en
  `serializers.py:20-26`.
- **`capabilities` es la misma fuente que usan los guards del backend** (`entitlements_for_tenant`,
  `views.py:426-430`), así que front y backend no se pueden contradecir (§1.4.3).
- **No hay forma de cambiar de clínica** desde aquí ni desde ningún otro endpoint: `memberships` es
  informativa y `X-Tenant-ID` no existe (§1.2.5).
- **Errores:** 401 sin token o token inválido. Nada más: no hay 403 ni 404.

#### 11.2.5 `POST /api/v1/auth/change-password/`

- **Permiso:** `IsAuthenticated` (`views.py:496`). Throttle `auth_password_change` 10/min
  (`views.py:497-498`).
- **Entrada** (`serializers.py:158-177`), ambos obligatorios y `write_only`, con
  `trim_whitespace=False` (una contraseña que empieza con espacio es válida):

```json
{"current_password": "…", "new_password": "…"}
```

- **Éxito 200 con cuerpo vacío** (`views.py:515`) + `Set-Cookie: maily_refresh=<nuevo>`
  (`views.py:516-517`).
- **Errores:**
  - **400** `{"current_password": ["Este campo es requerido."]}` — forma de serializer, si falta un
    campo.
  - **400** `{"detail": ["La contraseña actual no es correcta."]}` — lista, no string
    (`views.py:512-513` traduce el `ValidationError` de Django con `exc.messages`). Misma forma para
    los fallos de los validadores de Django.
  - **401** sin Bearer válido. **429** al pasar el throttle.
- **Efecto que hay que conocer:** el service blacklistea **todos** los refresh tokens del usuario
  (`services.py:82-84`) y luego la vista emite uno nuevo para no desconectar a quien acaba de
  autenticarse (`views.py:516-517`). Cambiar la contraseña **cierra la sesión de cualquier otro
  dispositivo**, pero no la propia.

---

### 11.3 Política de contraseñas y sesión

#### 11.3.1 Validadores (`MailySoft/backend/config/settings/base.py:413-421`)

| Validador | Efecto |
|---|---|
| `UserAttributeSimilarityValidator` | Rechaza contraseñas parecidas al email o al nombre |
| `MinimumLengthValidator` con `min_length=10` | **10 caracteres mínimo** (`base.py:417`) |
| `CommonPasswordValidator` | Rechaza la lista de contraseñas comunes de Django |
| `NumericPasswordValidator` | Rechaza contraseñas solo numéricas |

**No hay** requisito de mayúsculas, dígitos o símbolos, ni caducidad, ni historial de contraseñas
anteriores. No se propone añadirlos: NIST SP 800-63B recomienda longitud + lista de comunes por
encima de las reglas de composición, y eso es exactamente lo que hay.

Hasheo: `Argon2PasswordHasher` primero, `PBKDF2PasswordHasher` de respaldo
(`base.py:423-426`). Argon2 es el que Django recomienda hoy.

Dónde se aplican: `password_change` (`apps/authn/services.py:68`), `member_create` (§1.9) y
`platform_staff_create` (`plataforma/services.py:1063`).

#### 11.3.2 Contraseñas temporales

Las genera `_generar_password_temporal` (`plataforma/services.py:76-111`), único generador del
sistema:

- 16 caracteres con `secrets.choice` y `secrets.SystemRandom().shuffle` (`:105-110`).
- Alfabeto sin caracteres ambiguos: sin `0/O`, sin `1/l/I` (`:69-72`).
- Garantiza 2 mayúsculas, 2 minúsculas, 2 dígitos y 2 símbolos antes de completar (`:94-105`).
- **Nunca se persiste ni se loguea**; solo viaja en el cuerpo de la respuesta de tres endpoints de
  plataforma (§13.6).
- Encienden `must_change_password=True` (`plataforma/services.py:283-284`, `:1061`, `:1274`).

**No caducan.** Un dueño dado de alta hace seis meses que nunca entró sigue teniendo su temporal
válida. Ver `B-PLA-06`.

#### 11.3.3 Sesión

Lo esencial está en §1.2.1. Lo que hay que añadir:

| Regla | Dónde | Nota |
|---|---|---|
| Access 15 min, refresh 7 días | `base.py:257-258` | |
| El refresh **no rota** | `base.py:266-267` | **Los docstrings del código dicen lo contrario** (`authn/views.py:30`, `:248`; `plataforma/services.py:1279`) → `B-AUT-04` |
| Cambio propio de contraseña → blacklist total + sesión propia renovada | `authn/services.py:82-84` + `views.py:516-517` | |
| Reset por un admin → blacklist total **sin** sesión nueva | `plataforma/services.py:1286-1288` | Correcto: el admin no es quien sigue operando esa cuenta (`:47-50`) |
| Logout → blacklist del refresh de la cookie | `authn/views.py:312-313` | |
| Bloquear a un miembro (`is_active=False`) | §1.9 | **No invalida sus tokens**: el access vigente sigue funcionando hasta 15 min. `resolve_membership_for_user` sí lo corta en el siguiente request de negocio si su membresía se desactiva (§1.2.5) |
| Suspender la clínica (`status=suspended`) | §13.6 | Bloquea en el siguiente request (`core/tenant_context.py:157-160`), no invalida tokens |

#### 11.3.4 Fuerza bruta: qué frena y qué no

| Control | Alcance real |
|---|---|
| `auth_login` 5/min (`views.py:157-158`) | `ScopedRateThrottle`. En el login el usuario es anónimo → la clave es **la IP**. Frena a un atacante desde una IP; **no frena** un ataque distribuido, y **sí molesta** a una clínica entera detrás de un NAT |
| `auth_password_change` 10/min (`views.py:497-498`) | Aquí el usuario **sí** está autenticado → la clave es el usuario. Protege `current_password` correctamente |
| `LOGIN_FAILED` en bitácora (`audit/signals.py:79-86`) | **Registra, no actúa.** No hay bloqueo de cuenta, no hay backoff creciente, no hay alerta |
| Hash Argon2 | Encarece el intento en el servidor, no lo impide |

**No existe bloqueo por cuenta.** Ver `B-AUT-01`.

---

### 11.4 Matriz de permisos

Columnas = las seis operaciones de autenticación. Celdas: **Sí** = permitido · **No** = denegado con
el código indicado · **Propio** = solo sobre su propio registro.

| Actor | `POST /auth/login/` | `POST /auth/refresh/` | `POST /auth/logout/` | `POST /auth/verify/` | `GET /me/` | `POST /auth/change-password/` |
|---|---|---|---|---|---|---|
| Anónimo (sin token) | Sí | Sí si trae la cookie; **No — 401** sin ella (`views.py:258-262`) | No — 401 | Sí | No — 401 | No — 401 |
| Usuario con `is_active=False` | No — 401 (lo rechaza el backend de auth de Django) | No — 401 al no poder resolver el usuario | No — 401 | Sí (el token sigue siendo válido hasta expirar) | No — 401 | No — 401 |
| Usuario **sin** membresía en ninguna clínica | Sí | Sí | Sí | Sí | **Sí** — 200 con `active_tenant: null` (`views.py:360-362`) | Sí (Propio) |
| Usuario con clínica `suspended` | Sí | Sí | Sí | Sí | **Sí** — 200, pero `active_tenant: null` (`tenant_context.py:157-160`) | Sí (Propio) |
| `owner` · `admin` · `doctor` · `nurse` · `reception` · `finance` · `readonly` | Sí | Sí | Sí | Sí | Sí (Propio) | Sí (Propio) |
| Staff de plataforma (`super_admin`, `sales`, `engineering`) | Sí | Sí | Sí | Sí | Sí (Propio) | Sí (Propio) |
| Cualquiera con `must_change_password=True` | Sí | Sí | Sí | Sí | **Sí** (exento por herencia, §1.2.4) | **Sí** — es su única salida |
| Cualquiera, sobre la contraseña **de otro** | — | — | — | — | — | **No.** No existe endpoint. El restablecimiento ajeno vive en §1.9 (miembros) y §13.2 (staff) |

Ninguna de las seis operaciones distingue por rol de clínica: **la identidad no depende del rol**.
La granularidad por rol empieza en `TenantAPIView` (§1.3.1).

---

### 11.5 Efectos secundarios

| Endpoint | Efectos |
|---|---|
| `POST /auth/login/` | 1) Cookie `maily_refresh` httpOnly (`views.py:169`, atributos en `:100-108`) · 2) Cookie `csrftoken` (`views.py:136`) · 3) Bitácora `LOGIN` con `resource_repr = email` y el tenant resuelto (`views.py:216-224`) · 4) Django actualiza `last_login` · 5) En fallo: la señal `user_login_failed` escribe `LOGIN_FAILED` con el **hash** del correo (§12.2) |
| `POST /auth/refresh/` | Solo emite un access nuevo. Como `ROTATE_REFRESH_TOKENS=False`, la rama que reescribe la cookie (`views.py:274-276`) **no se ejecuta hoy**. Sin bitácora |
| `POST /auth/logout/` | 1) Blacklist del refresh (`views.py:312-313`) · 2) Borrado efectivo de la cookie (`views.py:325`) · 3) Bitácora `LOGOUT` (`views.py:335-342`) |
| `POST /auth/verify/` | Ninguno. Sin bitácora |
| `GET /me/` | **Ninguna escritura.** 4–6 consultas: membresías (`selectors.py:51-61`), doctor (`views.py:407`), sucursales (`views.py:418`), entitlements (`views.py:430`). Sin bitácora: consultar el propio perfil no es acción sensible |
| `POST /auth/change-password/` | 1) `set_password` + `must_change_password=False` en una transacción (`services.py:70-73`) · 2) **Blacklist de todos** los `OutstandingToken` del usuario (`services.py:82-84`) · 3) Cookie de refresh nueva (`views.py:516-517`) · 4) Bitácora `PASSWORD_CHANGE` **sin contraseñas en metadata** (`services.py:87-97`) · 5) `logger.info` con el id del usuario, sin la contraseña (`services.py:99`) |

#### 11.5.1 Un detalle de la bitácora de `PASSWORD_CHANGE`

`actor_role` cae de vuelta a `platform_role` si el usuario no tiene membresía de clínica
(`services.py:94-96`). Es el único punto del sistema que mezcla los dos espacios de roles en el mismo
campo. Al leer la bitácora hay que saberlo: un `actor_role = "super_admin"` no es un rol de clínica.

#### 11.5.2 Lo que el Django admin puede hacer sobre `User`

`apps/authn/admin.py:10` registra `UserAdmin` heredando el de Django. El fieldset "Plataforma Maily"
expone **`is_platform_staff` y `platform_role` como campos editables** (`admin.py:29-31`), y el
fieldset "Permisos" expone `is_superuser`, `groups` y `user_permissions` (`admin.py:32-43`).
`readonly_fields` solo cubre `id`, `date_joined` y `last_login` (`admin.py:66`).

Quien tenga acceso a `/admin/` **y** el permiso `authn.change_user` puede promoverse a
`super_admin` de la plataforma sin pasar por ningún endpoint auditado — `platform_staff_update`
(§13.2), que sí tiene reglas anti-escalada, se salta por completo. Ver `B-AUT-02`.
## 12. Bitácora de auditoría

> Extraído del código el 2026-08-12 (modo inverso). Las rutas `apps/…` abrevian
> `MailySoft/backend/apps/…` desde la raíz del repo. El helper `audit_record` ya está descrito en
> §1.8.5; aquí se documenta el modelo, el catálogo completo, el endpoint de clínica, el origen de la
> IP y las barreras de inmutabilidad.

---

### 12.1 Modelo de datos

#### 12.1.1 `AuditLog` → `audit_logs` (`apps/audit/models.py:285`)

**Hereda `TenantAwareModel`** (`models.py:285`) — y **sobreescribe `tenant` para hacerlo nullable**
(`models.py:300-307`), porque hay eventos sin clínica: un login fallido no tiene tenant resuelto
todavía, y los eventos del panel de plataforma se graban con `tenant=None` a propósito (§13.6).

| Campo | Tipo | `on_delete` | Null | Default | Consecuencia real de esa elección |
|---|---|---|---|---|---|
| `tenant` | FK `tenancy.Tenant`, `related_name="+"` (`:300-307`) | **PROTECT** | **sí** | `NULL` | No se puede borrar en duro una clínica que tenga un solo renglón de bitácora. Es lo correcto: la bitácora es evidencia, no debe desaparecer con el cliente |
| `actor` | FK `authn.User`, `related_name="+"` (`:310-317`) | **SET_NULL** | sí | `NULL` | Dar de baja a un usuario **no borra ni bloquea** su rastro; el renglón queda con actor nulo. Por eso existe `actor_role`, que es un *snapshot* de texto |
| `actor_role` | `CharField(20)`, blank (`:318-323`) | — | no | `""` | Snapshot del rol **en el momento del evento**. Si mañana el usuario pasa de `doctor` a `admin`, el renglón viejo sigue diciendo `doctor` |
| `action` | `CharField(40)` choices `ActionType`, `db_index` (`:328-333`) | — | no | — | 40 caracteres por `MEDICAL_HISTORY_QUESTION_DEACTIVATE` (35), con margen (`:326-327`) |
| `resource_type` | `CharField(50)`, `db_index` (`:336-340`) | — | no | — | Nombre del modelo como texto: `"Patient"`, `"Appointment"` |
| `resource_id` | `UUIDField`, `db_index` (`:341-346`) | — | sí | `NULL` | **Referencia débil a propósito** (`:335`, `:295-296`): sin FK, así el renglón sobrevive al borrado del objeto referenciado |
| `resource_repr` | `CharField(200)`, blank (`:347-352`) | — | no | `""` | Snapshot legible. Es donde se cuela PII en varios callers (12.4) |
| `description` | `TextField`, blank (`:355-359`) | — | no | `""` | Texto libre. También lleva PII en los services de plataforma (12.4) |
| `ip_address` | `GenericIPAddressField(unpack_ipv4=True)` (`:362-367`) | — | sí | `NULL` | Acepta IPv4 e IPv6. Ver 12.4: **el valor es falsificable** |
| `user_agent` | `CharField(512)`, blank (`:368-373`) | — | no | `""` | Cortado a 512 por el caller (`core/views.py:183`) |
| `request_id` | `CharField(64)`, blank (`:374-379`) | — | no | `""` | `X-Request-ID` del cliente o un `uuid4().hex` generado (`core/views.py:184-185`) |
| `metadata` | `JSONField` (`:382-389`) | — | no | `{}` | Política declarada: **sin PII clínica**. Permitido `changed_fields`, `old/new_status`, ids. Prohibido diagnósticos, notas, CURP, teléfono, nombre |

Heredados de `BaseModel` (§1.8.1): `id` UUID, `created_at` (indexado, es el reloj del evento),
`updated_at`, `deleted_at`. Heredado de `TenantAwareModel`: `created_by` (`SET_NULL`).

> `created_by` y `updated_at` **no se usan nunca** en esta tabla: `audit_record` no los rellena
> (`services.py:71-84`) y no hay UPDATE posible. Son herencia inevitable de `TenantAwareModel`.
> `deleted_at` es más incómodo: existe un campo de borrado lógico en una tabla que se declara
> append-only. Ningún código lo escribe, y `AuditLogQuerySet.update()` lo bloquearía (`:31-32`).

`Meta`: `db_table = "audit_logs"`, `ordering = ["-created_at"]` (`:396-397`).

#### 12.1.2 Managers

```python
objects     = TenantManager.from_queryset(AuditLogQuerySet)()   # models.py:392
all_objects = models.Manager.from_queryset(AuditLogQuerySet)()  # models.py:393
```

Los dos llevan `AuditLogQuerySet`, que revienta en `update()` y `delete()` (`models.py:31-35`). Es
decir: **ni siquiera el manager de bypass permite modificar la bitácora**.

#### 12.1.3 Índices y la consulta que justifica cada uno

| Índice | Definición | Consulta que lo necesita |
|---|---|---|
| `audit_created_idx` | `(-created_at)` (`models.py:404-407`) | `GET /plataforma/auditoria/` — cross-tenant, `AuditLog.all_objects … ORDER BY -created_at` sin filtro de tenant (`plataforma/selectors.py:330`, `:350`). Los demás índices llevan `tenant` de prefijo y no sirven para este acceso; la razón está escrita en `models.py:399-403` |
| `audit_tenant_created_idx` | `(tenant, created_at)` (`:408-411`) | `GET /audit/logs/` — el listado por defecto del dueño (`audit/selectors.py:44-46` con el filtro implícito de tenant) y los filtros `date_from`/`date_to` (`:60-64`) |
| `audit_tenant_actor_idx` | `(tenant, actor)` (`:412-415`) | `GET /audit/logs/?actor_id=…` (`selectors.py:48-49`) |
| `audit_tenant_resource_idx` | `(tenant, resource_type, resource_id)` (`:416-419`) | `GET /audit/logs/?resource_type=Patient&resource_id=…` (`selectors.py:51-55`) — "todo lo que se hizo sobre este paciente" |
| `audit_tenant_action_idx` | `(tenant, action)` (`:420-423`) | `GET /audit/logs/?action=PRESCRIPTION_CREATE` (`selectors.py:57-58`) |

Cinco índices sobre una tabla de alto volumen y solo-inserción es mucho peso en cada escritura, pero
aquí sí está justificado: la bitácora se consulta por esas cinco vías exactas y una tabla de 10 años
sin índices es una búsqueda secuencial sobre millones de filas. Lo que **no** está cubierto es el
filtro `search` del panel de plataforma (`icontains` sobre `description` y `actor__email`,
`plataforma/selectors.py:348`): eso es un `Seq Scan` con `LIKE '%…%'`. Con el volumen actual da
igual; conviene recordarlo antes de vender el panel como buscador.

---

### 12.2 Catálogo de tipos de acción

**124 valores** en `ActionType` (`apps/audit/models.py:38-282`). El conteo está verificado dos veces:
por búsqueda de declaraciones en el archivo y por suma de los grupos de la tabla siguiente.
El análisis dice "más de 100" (`docs/01-analisis.md:243`): correcto, y ahora con número exacto.

| Grupo | Nº | Líneas | Valores |
|---|---|---|---|
| Pacientes | 4 | `:42-45` | `PATIENT_CREATE`, `PATIENT_READ`, `PATIENT_UPDATE`, `PATIENT_DEACTIVATE` |
| Citas y agenda | 11 | `:48-58` | `APPOINTMENT_CREATE/UPDATE/STATUS/RESCHEDULE/REACTIVATE`, `APPOINTMENT_TYPE_CREATE/UPDATE/DEACTIVATE`, `AGENDA_EVENT_CREATE/UPDATE/DELETE` |
| Personal | 9 | `:61-69` | `DOCTOR_CREATE/UPDATE/DEACTIVATE/CONSULTORIOS`, `CONSULTORIO_CREATE/UPDATE/DEACTIVATE`, `SCHEDULE_CREATE/DEACTIVATE` |
| Configuración de agenda | 1 | `:72` | `CONFIG_UPDATE` |
| Finanzas | 15 | `:75-89` | `CONCEPT_CREATE/UPDATE/DEACTIVATE`, `QUOTE_CREATE/UPDATE/STATUS`, `CHARGE_CREATE/CANCEL`, `PAYMENT_REGISTER`, `CFDI_ISSUE/CANCEL`, `FISCAL_CONFIG_UPDATE`, `PACKAGE_CREATE/UPDATE/DELETE` |
| Miembros de la clínica | 4 | `:92-95` | `MEMBER_CREATE/UPDATE/BLOCK/PASSWORD` |
| Notas y tareas | 6 | `:98-103` | `NOTE_CREATE/UPDATE/DELETE`, `NOTE_GLOBAL_SEND`, `AGENDA_NOTE_ADD/DELETE` |
| Expediente clínico | 14 | `:106-119` | `ALLERGY_CREATE/RESOLVE`, `MEDICAL_HISTORY_READ/UPDATE`, `VITALSIGNS_CREATE/READ`, `EVOLUTION_CREATE/READ`, `ADDENDUM_CREATE`, `DIAGNOSIS_CREATE/RESOLVE/READ`, `EVOLUTION_IMAGE_ADD/REMOVE` |
| Recetas — catálogo | 1 | `:122` | `MEDICATION_CREATE` |
| Recetas — receta | 3 | `:125-127` | `PRESCRIPTION_CREATE/READ/CANCEL` |
| Recetas — PDF | 1 | `:130` | `PRESCRIPTION_PDF` |
| Plataforma — clínicas | 2 | `:133-134` | `TENANT_CREATE`, `TENANT_STATUS_CHANGE` |
| Plataforma — suscripciones | 3 | `:137-139` | `SUBSCRIPTION_CHANGE`, `TRIAL_EXPIRED`, `SUBSCRIPTION_EXPIRED` |
| Plataforma — planes | 2 | `:142-143` | `PLAN_CREATE`, `PLAN_UPDATE` |
| Plataforma — entitlements | 1 | `:146` | `TENANT_ENTITLEMENTS_SET` |
| Plataforma — equipo | 3 | `:149-151` | `STAFF_CREATE`, `STAFF_UPDATE`, `STAFF_PASSWORD_RESET` |
| Autenticación | 4 | `:154-157` | `LOGIN`, `LOGOUT`, `LOGIN_FAILED`, `PASSWORD_CHANGE` |
| Mi Consultorio | 9 | `:160-177` | `CLINIC_SETTINGS_UPDATE`, `TEMPLATE_CREATE/UPDATE/DELETE`, `PATIENT_CATEGORY_CREATE/DELETE`, `CLINIC_TEAM_MEMBER_CREATE/UPDATE/DELETE` |
| Recetas — credenciales (COFEPRIS) | 4 | `:180-183` | `CREDENTIAL_CREATE/UPDATE/VALIDATE/DELETE` |
| Recetas — formatos | 3 | `:186-188` | `FORMAT_CREATE/UPDATE/DELETE` |
| Recetas — verificación pública | 1 | `:192` | `PRESCRIPTION_VERIFY` — sin PII: solo folio y resultado (`:191`) |
| Recetas — controlados | 1 | `:196` | `PRESCRIPTION_CONTROLLED_CREATE` |
| Libro clínico del paciente | 2 | `:206`, `:212` | `PATIENT_BOOK_VIEW`, `PATIENT_BOOK_PDF` — usan `record_number` como `resource_repr`, no el nombre (`:202`, `:211`) |
| Historia clínica configurable | 3 | `:215-226` | `MEDICAL_HISTORY_QUESTION_CREATE/UPDATE/DEACTIVATE` |
| Resumen clínico | 1 | `:231` | `CLINICAL_SUMMARY_CREATE` |
| Calendarización de tratamientos | 2 | `:240`, `:248` | `TREATMENT_PLAN_SAVE`, `TREATMENT_SESSION_SCHEDULE` |
| Plan de longevidad | 1 | `:257` | `LONGEVITY_PLAN_CREATE` |
| Catálogos de longevidad | 6 | `:265-270` | `DOCUMENT_TEMPLATE_CREATE/UPDATE/DELETE`, `LAB_ANALYTE_CREATE/UPDATE/DELETE` |
| Sucursales | 7 | `:273-282` | `SUCURSAL_CREATE/UPDATE/ACTIVATE/DEACTIVATE/SET_DEFAULT`, `DOCTOR_SUCURSALES`, `MEMBERSHIP_SUCURSALES_SET` |
| **Total** | **124** | | |

#### 12.2.1 Qué se audita de lectura y qué no

Ocho de los 124 son **lecturas**: `PATIENT_READ`, `MEDICAL_HISTORY_READ`, `VITALSIGNS_READ`,
`EVOLUTION_READ`, `DIAGNOSIS_READ`, `PRESCRIPTION_READ`, `PATIENT_BOOK_VIEW`, `PATIENT_BOOK_PDF`.
Es lo que exige NOM-024 §5.3 para el acceso al expediente. **No se auditan** las lecturas de agenda,
finanzas, notas ni notificaciones: el criterio es "lo clínico y lo sensible", no "todo".

#### 12.2.2 Cómo se añade un tipo nuevo

Cada valor nuevo exige su migración `AlterField` sobre `action`. Hay **36 migraciones** en
`apps/audit/migrations/`, la mayoría son exactamente eso (`0004_alter_auditlog_action.py` …
`0039_must_change_password_and_action_types.py`). Es ruido inevitable de usar `choices` en base de
datos, no un problema: el `CharField` no valida choices a nivel Postgres, así que la migración solo
actualiza el estado de Django.

---

### 12.3 Endpoints

Hay **un solo endpoint de bitácora en la API de clínica**. El cross-tenant vive en el panel de
plataforma y se documenta en §13.2.

| Método | Ruta | Vista:línea | Permiso | Guard de módulo | Éxito | Errores |
|---|---|---|---|---|---|---|
| GET | `/api/v1/audit/logs/` | `apps/audit/views.py:39` | `IsAuthenticated` + `AuditLogPermission` (`views.py:55`) | **ninguno** — la bitácora no es un módulo vendible | 200 paginado | 401, 403, 500 |

Ruta registrada en `apps/audit/urls.py:15` bajo el prefijo `api/v1/audit/`
(`MailySoft/backend/config/urls.py:43`). Hereda de `TenantAPIView` (`views.py:39`), así que resuelve
tenant y fija el GUC.

**`PUT`, `POST`, `PATCH` y `DELETE` → 405**: los handlers no existen (`views.py:42`). Es la misma
técnica con la que se sostiene la inmutabilidad clínica (§1.7.2).

#### `GET /api/v1/audit/logs/`

- **Permiso:** `AuditLogPermission` (`apps/audit/permissions.py:25`) = `{"GET": {owner}}`
  (`:22`, `:33-35`). **Solo el dueño.** El admin quedó fuera el 2026-07-16 y la razón está escrita en
  el módulo (`permissions.py:10-14`): `AuditLog` no tiene campo `sucursal`, así que no hay forma de
  acotar la bitácora por sede; antes que exponer la actividad de la sede A a un admin de la sede B,
  se restringió a quien supervisa toda la operación. Es la excepción de §1.5.5.
- **Paginación:** `_AuditLogPagination` (`views.py:27-36`) — `page_size=50`, parámetro `page_size`
  admitido, tope `max_page_size=200`. El tope tiene razón escrita: sin él, un dueño podría pedir
  `?page_size=1000000` y descargarse la bitácora entera (`views.py:29-32`).
- **Query params, todos opcionales:**

| Param | Tipo | Comportamiento con valor inválido |
|---|---|---|
| `actor_id` | UUID | **Se ignora en silencio** (`views.py:64-67`) |
| `resource_type` | string exacto | — |
| `resource_id` | UUID | **Se ignora en silencio** (`views.py:71-75`) |
| `action` | valor de `ActionType` | Un valor inexistente devuelve 0 resultados, no 400 |
| `date_from` | `YYYY-MM-DD` inclusive | **Se ignora en silencio**, y además **junto con `date_to`** porque comparten el mismo `try` (`views.py:82-91`) |
| `date_to` | `YYYY-MM-DD` inclusive | ídem |
| `page`, `page_size` | int | DRF responde 404 a una página inexistente |

Ese "se ignora en silencio" es un problema real: `?actor_id=pepe` devuelve **la bitácora completa**
en vez de un 400, y quien audita cree estar viendo lo de un actor concreto. El endpoint equivalente
de plataforma sí valida con serializer y responde 400 (`plataforma/views.py:640-641`). Ver
`B-AUD-04`.

- **Alcance:** `audit_log_list` usa `AuditLog.objects` = `TenantManager`
  (`apps/audit/selectors.py:44-46`), así que solo ve el tenant activo. Los eventos globales
  (`tenant IS NULL`: `LOGIN_FAILED`, y **todo el panel de plataforma**) **no aparecen nunca** aquí —
  ni por el manager ni por la policy RLS, que perdió el `OR tenant_id IS NULL` en
  `apps/audit/migrations/0003_fix_audit_select_policy.py:26-31`.
- **Respuesta 200:** `{count, next, previous, results[]}`; cada elemento
  (`apps/audit/serializers.py:30-59`):

```json
{
  "id": "uuid",
  "created_at": "2026-08-12T10:00:00-06:00",
  "actor": {"id": "uuid", "email": "ana@clinica.mx", "full_name": "Ana Ruiz"},
  "actor_role": "doctor",
  "action": "PRESCRIPTION_CREATE",
  "action_display": "Emitir receta médica",
  "resource_type": "Prescription",
  "resource_id": "uuid",
  "resource_repr": "REC-2026-000123",
  "description": "",
  "ip_address": "189.203.11.4",
  "user_agent": "Mozilla/5.0 …",
  "request_id": "9f2c…",
  "metadata": {"patient_id": "uuid", "controlled": false}
}
```

`actor` es `null` para eventos sin actor (`serializers.py:38`). `metadata` viaja **completo**: la
decisión está escrita (`serializers.py:5`) y se apoya en que el endpoint ya está restringido —
aunque el comentario dice "owner/admin" y el permiso real es solo owner (`B-AUD-05`).

- **Errores:** **401** sin token · **403** para los otros seis roles y para quien no tenga membresía
  activa (§1.3.1) · **500** `{"detail": "Paginación no disponible."}` como rama defensiva
  (`views.py:110-113`), con la razón escrita: nunca servir la bitácora sin paginar.

---

### 12.4 Origen de la IP y minimización de PII

#### 12.4.1 La IP: **confirmado, es falsificable**

El punto 3 del análisis (`docs/01-analisis.md:337-339`) **queda confirmado**. Hay **cuatro** sitios
que resuelven la IP y los cuatro hacen exactamente lo mismo:

| Sitio | Línea | Código efectivo |
|---|---|---|
| Toda la API de clínica | `apps/core/views.py:177-182` | `x_forwarded.split(",")[0].strip()` si hay `X-Forwarded-For`, si no `REMOTE_ADDR` |
| Login | `apps/authn/views.py:183-188` | idéntico |
| Login fallido (señal) | `apps/audit/signals.py:64-68` | idéntico |
| Panel de plataforma | `apps/plataforma/views.py:153-158` | idéntico |

**No existe ninguna lista de proxies confiables**: verificado por búsqueda de `ipware`,
`TRUSTED_PROXIES` y `USE_X_FORWARDED_*` en todo `MailySoft/backend/` — cero coincidencias fuera de
los cuatro sitios de arriba y de un test (`apps/audit/tests/test_integration.py:520`).

Por qué eso rompe la evidencia: un proxy inverso **añade** el cliente al final de `X-Forwarded-For`
y conserva lo que el cliente mandó. Tomar el **primer** elemento es tomar el valor que escribió el
cliente. Un `curl -H "X-Forwarded-For: 8.8.8.8"` deja `8.8.8.8` escrito en la bitácora. El sistema
tiene `SECURE_PROXY_SSL_HEADER` configurado (§1.7.4), es decir que **sí** se sabe que hay un proxy
delante; lo que falta es tratar `X-Forwarded-For` con el mismo criterio. Ver `B-AUD-01`.

El campo se documenta a sí mismo como "puede ser NAT; se registra igual (NOM-024)"
(`models.py:366`), lo cual describe una limitación distinta (varios clientes tras una misma IP) y no
la falsificación.

#### 12.4.2 Minimización de PII: la regla y sus tres grietas

**La regla declarada** vive en dos lugares: el docstring del modelo — *"Nunca contiene PII clínica en
metadata"* (`models.py:294`) — y el `help_text` del campo, que enumera lo permitido y lo prohibido
(`models.py:385-388`).

**Lo que se hace bien:**

- `LOGIN_FAILED` guarda `sha256(email)[:16]` en `metadata["email_hint"]`, **no el correo**
  (`apps/audit/signals.py:51-56`), y nunca la contraseña (`:31`, `:44`). Permite correlacionar un
  ataque de fuerza bruta sin almacenar el dato personal.
- El libro clínico usa `record_number` como `resource_repr`, no el nombre del paciente
  (`models.py:202`, `:211`).
- El resumen clínico, la calendarización y el plan de longevidad usan `str(obj.id)` como
  `resource_repr` y lo dicen explícitamente (`models.py:230`, `:238-239`, `:247`, `:256`).
- `PRESCRIPTION_VERIFY` registra folio y resultado, sin IP ni firma (`models.py:191`).
- `EVOLUTION_CREATE` guarda solo ids en metadata (`apps/expediente/services.py:765-769`).
- Las contraseñas temporales **nunca** entran ni en metadata ni en descripción
  (`plataforma/services.py:344`, `:1069`).

**Las tres grietas:**

1. **La regla solo cubre `metadata`.** `description` y `resource_repr` son texto libre y llevan
   datos personales de forma sistemática: `resource_repr = user.email` en `LOGIN`
   (`apps/authn/views.py:222`), en `PASSWORD_CHANGE` (`apps/authn/services.py:93`) y en
   `STAFF_CREATE`/`STAFF_UPDATE`/`STAFF_PASSWORD_RESET` (`plataforma/services.py:1076`, `:1210`,
   `:1296`); `description` incluye el correo del actor y el nombre de la clínica en **todos** los
   services de plataforma (`services.py:352-356`, `:439-443`, `:545-550`, `:646-648`, `:1077-1080`,
   `:1211-1214`, `:1297-1300`) y en la tarea de vencimientos (`tasks.py:105-109`, `:162-167`).
2. **`metadata` con correo en el alta de miembro.** Según §1.9 del contrato transversal,
   `member_create` audita "con el email y las sedes" (`apps/tenancy/services.py:314-325`).
   **NO VERIFICADO directamente**: `apps/tenancy/services.py` está fuera del alcance que leí; lo
   tomo de §1.9, que sí lo extrajo del código.
3. **`user_agent` completo, 512 caracteres.** Es una huella de dispositivo razonablemente
   identificadora, se guarda siempre y no hay política de retención que la caduque.

Ver `B-AUD-06`.

#### 12.4.3 Retención: no existe

El código afirma que "la bitácora retiene 10 años" (`apps/audit/views.py:31`), pero **no hay ningún
comando ni tarea que purgue nada**: verificado por búsqueda de `purge`, `retention` y `cleanup` en
`MailySoft/backend/apps/` — las únicas coincidencias son el panel de retención de pacientes de
finanzas, que no tiene relación. La bitácora crece sin cota y sin caducidad, con IPs, user-agents,
correos y nombres dentro. Ver `B-AUD-07`.

---

### 12.5 Quién puede leerla

| Actor | Bitácora de **su** clínica | Bitácora **cross-tenant** | Por dónde | Referencia |
|---|---|---|---|---|
| `owner` | **Sí**, completa (incluidos metadata, IP y user-agent) | No | `GET /api/v1/audit/logs/` | `apps/audit/permissions.py:22`, `:33-35` |
| `admin` | **No — 403** | No | — | `permissions.py:10-14` (decisión 2026-07-16) |
| `doctor` · `nurse` · `reception` · `finance` · `readonly` | **No — 403** | No | — | ídem |
| Plataforma `super_admin` | Sí, la de todas | **Sí** | `GET /api/v1/plataforma/auditoria/` | `core/permissions.py:1229`, `_PLATFORM_ROLES_AUDIT` `:1100-1102` |
| Plataforma `engineering` | Sí, la de todas | **Sí** | ídem | ídem |
| Plataforma `sales` | **No** por API — 403 | **No** por API — 403 | — | `_PLATFORM_ROLES_AUDIT` excluye `sales` |
| **Cualquier `is_platform_staff`, incluido `sales`** | **Sí** | **Sí** | **`/admin/audit/auditlog/`** | `apps/audit/admin.py:90-98` (`has_view_permission` y `has_module_perms` devuelven `True` con solo mirar `is_platform_staff`) + `get_queryset` con `all_objects` (`:72`) |
| Un usuario de clínica | — | — | Sin acceso al admin: `platform_staff_create` es lo único que pone `is_staff=True` (`plataforma/services.py:1058`) | |

**El último renglón es un agujero real en la matriz**: el API excluye a `sales` de la bitácora a
propósito y el Django admin se lo devuelve entero, cross-tenant, con búsqueda por email de actor,
IP y `resource_repr` (`admin.py:41-43`). Ver `B-AUD-02`.

Sobre los eventos globales (`tenant IS NULL`): desde
`apps/audit/migrations/0003_fix_audit_select_policy.py` **ninguna clínica los ve**. La razón está
escrita en la propia migración (`0003:3-6`): antes, la policy incluía `OR tenant_id IS NULL` y
cualquier tenant autenticado veía los `LOGIN_FAILED` de **toda la plataforma**, con el `email_hint`
dentro. Es una fuga cross-tenant ya corregida y vale la pena conservar la nota.

---

### 12.6 Inmutabilidad del registro

Cuatro barreras, dos en Python y dos en PostgreSQL.

| # | Barrera | Dónde | Qué bloquea | ¿Efectiva hoy? |
|---|---|---|---|---|
| 1 | `AuditLog.save()` lanza `RuntimeError` si `not self._state.adding` | `models.py:426-438` | UPDATE de instancia | **Sí**. Usa `_state.adding` para no pagar un `SELECT` extra por escritura (`:429-431`) |
| 2 | `AuditLog.delete()` lanza `RuntimeError` siempre | `models.py:440-446` | DELETE de instancia | **Sí** |
| 3 | `AuditLogQuerySet.update()` / `.delete()` lanzan `RuntimeError` | `models.py:31-35` | `filter(...).update()`, `filter(...).delete()` y `bulk_update()` (que internamente hace `update()`), **en los dos managers** | **Sí** |
| 4 | Postgres: `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy solo para `SELECT` e `INSERT`, **ninguna** para UPDATE/DELETE → denegación por defecto | `migrations/0002_enable_rls.py:45-48`, `:59-67`, `:78-86` | SQL crudo, `psql`, cualquier ORM | **Depende del rol de conexión** |
| 5 | `REVOKE UPDATE, DELETE ON audit_logs` | `0002_enable_rls.py:99-118` | ídem | **Condicionado**: el bloque `DO $$` solo ejecuta el `REVOKE` si `current_user` **no** es superuser (`:104-110`) |

El punto débil está en las barreras 4 y 5, y hay que decirlo claro: **PostgreSQL exime a los roles
superuser de RLS**, incluso con `FORCE`. §1.1.4 documenta que la suite corre con un rol superuser y
que la verificación de comportamiento (`python manage.py check_db_role`) **no está en CI**. Si el rol
con el que la aplicación se conecta en producción es superuser, las barreras 4 y 5 son inertes y la
inmutabilidad depende **solo** de las tres barreras de Python — que se saltan con un `cursor.execute`
o con `psql`. Ver `B-AUD-03`.

Lo que **sí** está bien resuelto y conviene no tocar:

- La política de INSERT sí existe y sí lleva `WITH CHECK` (`0002:78-86`), así que no se puede
  insertar un renglón con `tenant_id` ajeno estando en contexto de otra clínica.
- El `RunSQL` de `REVOKE` no tiene reverso real y lo dice (`0002:120-121`): revertir la migración no
  vuelve a conceder los permisos. Es lo correcto para producción.
- El Django admin es de solo lectura por triple negación: `has_add_permission`,
  `has_change_permission` y `has_delete_permission` devuelven `False`, y `actions = None` quita las
  acciones en lote (`apps/audit/admin.py:68`, `:74-88`).
- **`audit_record` nunca lanza**: absorbe toda excepción, loguea `ERROR` y devuelve `None`
  (`apps/audit/services.py:91-101`). Una cita no se cae porque la bitácora falle. El contrapeso es
  el que hay que aceptar a ojos abiertos: **una operación de negocio puede completarse sin dejar
  rastro** y lo único que queda es una línea de log. Es una decisión deliberada
  (`services.py:6-8`), no un descuido.
- La escritura es **síncrona**, con la razón escrita: NOM-024 no acepta la pérdida de eventos de un
  `fire-and-forget` de Celery (`services.py:10-12`).
## 13. Portal interno de plataforma (cross-tenant)

> Extraído del código el 2026-08-12 (modo inverso). Las rutas `apps/…` abrevian
> `MailySoft/backend/apps/…` desde la raíz del repo. Las clases de permiso están inventariadas en
> §1.3.4 y aquí se **citan**, no se redefinen.

Es el panel del equipo de Maily, no de las clínicas. Da de alta clínicas, asigna planes, ajusta
derechos a la medida, administra al equipo interno, lee la bitácora de todas las clínicas y mira la
salud de la infraestructura. **Es el único lugar del sistema donde el aislamiento por clínica se
apaga a propósito.**

---

### 13.1 Modelo de datos

**La app no define ningún modelo.** No existe `apps/plataforma/models.py` (verificado listando el
directorio completo: `__init__.py`, `apps.py`, `urls.py`, `views.py`, `serializers.py`,
`selectors.py`, `services.py`, `system_health.py`, `tasks.py` y `tests/`). Por lo tanto **no tiene
migraciones, no tiene tablas y no le aplica el guardián de cobertura RLS** (§1.1.4).

Eso es correcto y conviene dejarlo escrito: plataforma es una **capa de operación** sobre modelos que
pertenecen a otras apps. Si algún día necesita un modelo propio (por ejemplo, un registro de
incidencias comerciales), ese modelo **no** debería heredar `TenantAwareModel` — no pertenece a una
clínica — y por lo tanto tendría que documentar por qué no lleva `tenant_id`, igual que hacen
`Tenant`, `Plan` y `User` (§1.1.6).

Sobre qué modelos opera:

| Modelo | App dueña | Documentado en | Uso aquí |
|---|---|---|---|
| `Tenant` | tenancy | §1.10.1 | Alta, listado, detalle, cambio de estado |
| `TenantMembership` | tenancy | §1.10.2 | Conteo de miembros y lista de la ficha |
| `Plan` | tenancy | §1.10.3 | Catálogo: alta, edición, listado |
| `TenantEntitlements` | tenancy | §1.10.4 | Ajustes a la medida por clínica |
| `TenantSubscription` | tenancy | §1.10.5 | Asignación de plan y alertas de vencimiento |
| `User` | authn | §11.1 | Equipo interno: alta, edición, reset de contraseña |
| `AuditLog` | audit | §12.1 | Bitácora cross-tenant |
| `Patient`, `Appointment` | pacientes, agenda | (sus secciones) | **Solo conteos y `max(created_at)`.** El panel nunca lee una ficha ni una cita |
| `Sucursal`, `Consultorio` | clinica, personal | (sus secciones) | Solo conteos, para el consumo vs. límite |
| `PdfJob` | pdfs | (su sección) | Conteos de la cola en `/sistema/` |

Ningún endpoint de plataforma devuelve un dato clínico de un paciente. Lo más cerca que llega es el
número de pacientes y la fecha de la última cita de una clínica.

---

### 13.2 Endpoints

Prefijo `/api/v1/` (`MailySoft/backend/config/urls.py:50`); rutas en `apps/plataforma/urls.py:46-126`.
**15 rutas, 18 operaciones.** Todas heredan de `PlatformAPIView`
(`apps/plataforma/views.py:117`), que:

- **no** resuelve membresía, **no** fija el GUC de RLS (`views.py:120-125`);
- **sí** puebla el contexto HTTP de auditoría (`views.py:152-162`);
- **sí** aplica el candado `must_change_password` después de `super().initial()`, duplicado aquí
  porque hereda de `APIView` directo (`views.py:141-151`).

**Ninguna lleva guard de módulo**: los módulos son un concepto de clínica, no de plataforma.

| Método | Ruta | Vista:línea | Permiso (§1.3.4) | Roles | Éxito | Errores |
|---|---|---|---|---|---|---|
| GET | `/api/v1/plataforma/metricas/` | `views.py:181` | `PlatformMetricsPermission` (`:187`) | SA, sales, eng | 200 | 401, 403 |
| GET | `/api/v1/plataforma/clinicas/` | `views.py:205` | `PlatformClinicReadPermission` vía `get_permissions()` (`:224-229`) | SA, sales, eng | 200 paginado | 401, 403 |
| POST | `/api/v1/plataforma/clinicas/` | `views.py:262` | `PlatformClinicWritePermission` (`:226-227`) | SA, sales | **201** + `Cache-Control: no-store` | 400, 401, 403 |
| GET | `/api/v1/plataforma/clinicas/<uuid:tenant_id>/` | `views.py:325` | `PlatformClinicReadPermission` (`:331`) | SA, sales, eng | 200 | 401, 403, 404 |
| POST | `/api/v1/plataforma/clinicas/<tenant_id>/estado/` | `views.py:356` | `PlatformClinicWritePermission` (`:362`) | SA, sales | 200 | 400, 401, 403, 404 |
| POST | `/api/v1/plataforma/clinicas/<tenant_id>/suscripcion/` | `views.py:886` | `PlatformSubscriptionPermission` (`:892`) | SA, sales | 200 | 400, 401, 403, 404 |
| POST | `/api/v1/plataforma/clinicas/<tenant_id>/entitlements/` | `views.py:932` | `PlatformPlanWritePermission` (`:939`) | **SA** | 200 | 400, 401, 403, 404 |
| GET | `/api/v1/plataforma/usuarios/` | `views.py:400` | `PlatformStaffListPermission` (`:414-419`) | **SA** | 200 paginado | 401, 403 |
| POST | `/api/v1/plataforma/usuarios/` | `views.py:448` | `PlatformStaffWritePermission` (`:416-417`) | **SA** | **201** + `Cache-Control: no-store` | 400, 401, 403 |
| PATCH | `/api/v1/plataforma/usuarios/<uuid:user_id>/` | `views.py:517` | `PlatformStaffWritePermission` (`:523`) | **SA** | 200 | 400, 401, 403, 404 |
| POST | `/api/v1/plataforma/usuarios/<user_id>/reset-password/` | `views.py:561` | `PlatformStaffWritePermission` (`:571`) + throttle `auth_password_change` (`:572-573`) | **SA** | 200 + `Cache-Control: no-store` | 400, 401, 403, 404, 429 |
| GET | `/api/v1/plataforma/auditoria/` | `views.py:617` | `PlatformAuditPermission` (`:625`) | SA, eng | 200 paginado | 400, 401, 403 |
| GET | `/api/v1/plataforma/sistema/` | `views.py:668` | `PlatformSystemPermission` (`:678`) | SA, eng | 200 | 401, 403 |
| GET | `/api/v1/plataforma/planes/` | `views.py:696` | `PlatformSubscriptionPermission` (`:712-717`) | SA, sales | 200 **sin paginar** | 401, 403 |
| POST | `/api/v1/plataforma/planes/` | `views.py:735` | `PlatformPlanWritePermission` (`:714-715`) | **SA** | 201 | 400, 401, 403 |
| PATCH | `/api/v1/plataforma/planes/<uuid:plan_id>/` | `views.py:774` | `PlatformPlanWritePermission` (`:783`) | **SA** | 200 | 400, 401, 403, 404 |
| GET | `/api/v1/plataforma/suscripciones/` | `views.py:821` | `PlatformSubscriptionPermission` (`:827`) | SA, sales | 200 paginado | 400, 401, 403 |
| GET | `/api/v1/plataforma/suscripciones/resumen/` | `views.py:862` | `PlatformSubscriptionPermission` (`:868`) | SA, sales | 200 | 401, 403 |

SA = `super_admin` · eng = `engineering`.

**Verificado: no hay ningún endpoint de plataforma sin permiso de plataforma.** Las tres vistas que
resuelven el permiso por método (`get_permissions()`, `views.py:224`, `:414`, `:712`) sustituyen por
completo el `permission_classes = [IsAuthenticated]` de clase, tal como confirma §1.3.6.

Paginación: `_StandardPagination` (`views.py:170-173`) — `page_size=20`, parámetro `page_size`
admitido, tope 100. El catálogo de planes no pagina a propósito (`selectors.py:363-366`).

#### 13.2.1 `POST /plataforma/clinicas/` — el alta de una clínica

Es la operación más privilegiada del sistema. Entrada (`serializers.py:204-294`):

| Campo | Tipo | Req. | Default | Validación propia |
|---|---|---|---|---|
| `name` | str ≤200 | sí | — | `slugify(name)` debe dar ≥3 caracteres (`:268-275`) |
| `owner_email` | email | sí | — | — |
| `owner_first_name` / `owner_last_name` | str ≤150 | sí | — | `.strip()` |
| `timezone` | str ≤64 | no | `America/Mexico_City` | Debe ser IANA válida, verificada con `zoneinfo` (`:283-294`) |
| `trial_days` | int | no | `60` | 1–365 (`:228-234`) |
| `plan_id` | UUID | no | `null` | El plan debe existir y estar **activo** (`services.py:504-510`) |
| `billing_cycle` | `monthly`\|`annual` | no | `monthly` | — |
| `owner_cedula` | str ≤30 | no | `""` | `validar_cedula_profesional` de §1.8.4 (`:264-266`) |
| `owner_specialty` | str ≤100 | no | `""` | — |

Lo que hace `tenant_and_owner_create` (`services.py:168-387`), todo dentro de una transacción
(`:256`):

1. Revalida que el actor sea staff con rol `super_admin`/`sales` (`:239-245`) — defensa en
   profundidad, porque el service también se invoca desde comandos.
2. Genera slug único (`:250`, `_slug_unico` `:114`) y contraseña temporal de 16 caracteres (`:251`).
3. Crea el `Tenant` con `status=trial` y `trial_ends_at = now() + trial_days` (`:257-263`).
4. Activa el contexto de tenant para que los modelos `TenantAware` de semilla nazcan con el FK
   correcto, y **lo limpia en un `finally`** (`:267`, `:337-341`).
5. Crea al dueño con `member_create` (§1.9) y le pone `must_change_password=True` (`:270-284`).
6. **Siembra:** 1 consultorio "Consultorio 1" (`:290-296`), 3 tipos de cita — Consulta, Primera vez,
   Seguimiento (`:298-303`) — y las categorías de paciente de sistema (`:306`).
7. Si vino cédula, crea el perfil de médico del dueño (`:313-320`). Si no, la clínica **no puede
   agendar** porque `Appointment.doctor` es obligatorio; por eso la respuesta trae `needs_doctor`
   (`:384-386`).
8. Si vino plan, crea la suscripción con `current_period_end = fin del trial` (`:326-335`).
9. **Fuera** de la transacción, audita `TENANT_CREATE` con `tenant=None` y **sin PII ni contraseña**
   en metadata (`:345-369`, razón escrita en `:365-367`).

**Respuesta 201** (`serializers.py:302-319`):

```json
{
  "tenant": {"id":"uuid","name":"…","slug":"…","status":"trial","status_display":"Prueba",
             "trial_ends_at":"…","created_at":"…","member_count":1,"patient_count":0},
  "owner_email": "dueno@clinica.mx",
  "temporary_password": "K7m$Rq2…",
  "needs_doctor": false
}
```

Cabeceras `Cache-Control: no-store, no-cache, must-revalidate, private` y `Pragma: no-cache`
(`views.py:315-316`).

**Errores:** 400 `{"detail": [...]}` para los fallos del service (`views.py:286-287`) · 400 con
`"Conflicto al crear la clínica (identificador duplicado). Intenta de nuevo."` si dos altas
simultáneas produjeron el mismo slug (`views.py:288-293`) · 400 con forma de serializer para campos
mal formados · 401 · 403.

#### 13.2.2 `GET /plataforma/clinicas/<id>/` — la ficha

Devuelve, además de los conteos: `appointment_count`, `ultima_actividad` (max `created_at` de las
citas), **la lista completa de miembros con nombre, correo, rol y estado**
(`selectors.py:241-251`), y un bloque `entitlements` con módulos efectivos, todos los módulos del
catálogo, roles, **consumo vs. límite** de usuarios/consultorios/sucursales y los overrides vigentes
con sus `notes` (`selectors.py:269-288`). El serializer expone `entitlements` como `DictField` libre
para no duplicar la estructura (`serializers.py:352-355`).

404 `{"detail": "Clínica no encontrada."}` si el UUID no existe (`views.py:342-346`).

#### 13.2.3 `POST /plataforma/clinicas/<id>/entitlements/`

Entrada: `modules_on[]`, `modules_off[]` (ambos `ChoiceField` contra `Module.choices`, así que un
slug inventado da 400 de serializer), `max_sucursales`/`max_consultorios`/`max_usuarios`
(enteros ≥1 o `null`), `notes` (≤2000) — serializer anidado en la vista
(`views.py:941-953`).

El service `tenant_entitlements_set` (`services.py:575-652`) exige `super_admin` (`:613-616`),
revalida los slugs con `modulos_desconocidos` (`:620-624`) y hace `update_or_create` sobre la fila
única del tenant (`:626-636`). Audita `TENANT_ENTITLEMENTS_SET` con `tenant=None`.

Dos cosas que hay que notar:

- **El permiso se llama `PlatformPlanWritePermission`** (`views.py:939`). El rol resultante es el
  correcto (`super_admin`), pero el nombre miente sobre el recurso. Ver `B-PLA-07`.
- **No valida dependencias entre módulos**: `validar_modulos` sí se usa en planes
  (`services.py:720-724`) pero **no** aquí. Se puede encender `cotizaciones` sin `servicios` por
  override, algo que el propio catálogo declara incoherente (§1.4.1). Ver `B-PLA-05`.

#### 13.2.4 Equipo interno: `usuarios/`

- **POST** (`services.py:990-1093`): crea el `User` con `is_active=True`, **`is_staff=True`**,
  `is_platform_staff=True`, `platform_role` elegido y `must_change_password=True` (`:1053-1062`).
  Responde 201 con la temporal.
  El pre-check de duplicado mira **solo** cuentas de plataforma (`:1048-1049`); si el correo es de
  una clínica, deja pasar y falla en el `UniqueConstraint`, que la vista traduce a un 400 con
  mensaje genérico (`views.py:479-487`). La razón está escrita (`services.py:1031-1039`): evitar que
  un super_admin descubra por el mensaje de error que un correo arbitrario ya existe como usuario de
  otra clínica. **Es un buen patrón anti-enumeración y conviene no romperlo.**
- **PATCH** (`services.py:1096-1227`): allow-list de 4 campos —`first_name`, `last_name`,
  `platform_role`, `is_active` (`:962-964`). Dos reglas de seguridad:
  - **Anti-lockout personal**: nadie cambia su propio `platform_role` ni su propio `is_active`
    (`:1140-1146`). Sí puede cambiarse el nombre.
  - **Regla del último super_admin**: si el objetivo es un `super_admin` activo y el cambio lo
    degradaría o desactivaría, debe quedar **otro** `super_admin` activo (`:1160-1180`). Sin ella, un
    super_admin podría degradar a todos los demás uno por uno.
  404 si el id no existe **o no es staff de plataforma** (`selectors.py:158-176`): un usuario de
  clínica se ve como inexistente, nunca 403.
- **POST reset-password** (`services.py:1230-1312`): 400 si el objetivo está inactivo (`:1264-1265`);
  asigna temporal nueva, pone `must_change_password=True` y **blacklistea todos** los refresh tokens
  del objetivo (`:1272-1288`). No emite sesión nueva, y eso es correcto: el admin no es quien sigue
  operando esa cuenta (`:47-50` de `apps/authn/services.py`).

#### 13.2.5 `GET /plataforma/auditoria/`

Filtros validados con serializer (`serializers.py:364-378`): `tenant_id` (UUID), `action` (≤40),
`actor_id` (UUID), `date_from`/`date_to` (**datetime ISO completo**, no fecha suelta), `search`
(≤200, `icontains` sobre `description` **o** el correo del actor, `selectors.py:348`). Un valor mal
formado devuelve **400** (`views.py:640-641`) — al revés que el endpoint de clínica (§12.3).

Respuesta por elemento (`serializers.py:386-417`): `id`, `created_at`, `action`, `action_display`,
`actor_email`, `actor_role`, `tenant_id`, `tenant_name`, `resource_type`, `resource_id`,
`description`, `ip_address`, `metadata`. **No expone `user_agent`, `request_id` ni `resource_repr`**
—al contrario que el serializer de clínica (§12.3), que sí los expone.

#### 13.2.6 Planes y suscripciones

- `GET /planes/` devuelve **todos** los planes, activos e inactivos, sin paginar
  (`selectors.py:361-374`); el portal los pinta atenuados. La asignación sí rechaza planes inactivos
  (`services.py:509-510`).
- `PlanOutputSerializer` distingue `roles_ofrecidos` (lo que el super_admin marcó) de `roles`
  (efectivos = permitidos por los módulos ∩ ofrecidos, `serializers.py:495-503`). Es exactamente la
  intersección de §1.6.3.
- `PATCH /planes/<id>/`: allow-list explícita de 13 campos (`services.py:668-684`); `slug` es
  inmutable (`:661-663`) porque lo referencian `TenantSubscription` y el frontend. `is_active` **sí**
  se admite en el PATCH, como excepción documentada (`services.py:866-872`): `Plan` no tiene borrado
  físico —`TenantSubscription.plan` es `PROTECT`— y desactivar es la única baja posible.
- `POST /clinicas/<id>/suscripcion/`: los 3 campos son obligatorios, sin defaults
  (`serializers.py:754-768`). El service valida plan existente, plan activo, ciclo válido y
  `current_period_end` **futura** (`services.py:504-516`), y hace `update_or_create` reseteando
  `period_expired_notified_at` a `None` para que una renovación pueda volver a avisar
  (`:525-536`).
- `GET /suscripciones/`: una fila por clínica, tenga o no suscripción ("left join lógico",
  `selectors.py:517-522`). El campo `alerta` se calcula en Python (`_calcular_alerta`, `:398-461`)
  con prioridad `vencido > por_vencer` y `trial > periodo`; la ventana de "por vencer" es de 7 días
  (`:358`).
- `GET /suscripciones/resumen/`: `total_clinicas`, `sin_plan`, `por_plan[]`, los 4 conteos de alerta
  y `mrr_estimado` = suma de `price_monthly` de las suscripciones cuyo **tenant** está `active` —
  ni trial ni suspended cuentan (`selectors.py:586-588`).

---

### 13.3 Uso de `all_objects` y su protección

`all_objects` es el manager sin filtro de tenant **ni de soft-delete** (§1.1.5). En plataforma su uso
es sistemático y deliberado: `PlatformAPIView` nunca fija el GUC, así que `Model.objects`
(`TenantManager`) devolvería `qs.none()` dentro de un request — la razón está escrita en
`apps/plataforma/selectors.py:4-14`.

**Nueve usos productivos.** Una fila por cada uno:

| # | `archivo:línea` | Modelo | Qué lee | Endpoint que lo alcanza | Permiso que lo cubre | Roles |
|---|---|---|---|---|---|---|
| 1 | `apps/plataforma/selectors.py:68` | `Patient` | Subquery `COUNT` de pacientes por clínica (`patient_count` del listado) | `GET /plataforma/clinicas/` | `PlatformClinicReadPermission` (`views.py:229`) | SA, sales, eng |
| 2 | `apps/plataforma/selectors.py:119` | `Patient` | `COUNT` global de pacientes no borrados, todas las clínicas | `GET /plataforma/metricas/` | `PlatformMetricsPermission` (`views.py:187`) | SA, sales, eng |
| 3 | `apps/plataforma/selectors.py:215` | `Patient` | `COUNT` de pacientes de **una** clínica | `GET /plataforma/clinicas/<id>/` y `POST /clinicas/<id>/entitlements/` (que reusa el mismo selector, `views.py:983`) | `PlatformClinicReadPermission` (`views.py:331`) / `PlatformPlanWritePermission` (`views.py:939`) | SA, sales, eng / SA |
| 4 | `apps/plataforma/selectors.py:221` | `Appointment` | `COUNT` de citas de una clínica, incluidas canceladas | ídem #3 | ídem #3 | ídem #3 |
| 5 | `apps/plataforma/selectors.py:226` | `Appointment` | `MAX(created_at)` = última actividad de una clínica | ídem #3 | ídem #3 | ídem #3 |
| 6 | `apps/plataforma/selectors.py:262` | `Sucursal` | `COUNT` de sucursales no borradas (consumo vs. límite) | ídem #3 | ídem #3 | ídem #3 |
| 7 | `apps/plataforma/selectors.py:265` | `Consultorio` | `COUNT` de consultorios no borrados (consumo vs. límite) | ídem #3 | ídem #3 | ídem #3 |
| 8 | `apps/plataforma/selectors.py:330` | `AuditLog` | **Bitácora completa de todas las clínicas**, con `select_related("actor","tenant")` | `GET /plataforma/auditoria/` | `PlatformAuditPermission` (`views.py:625`) | SA, eng |
| 9 | `apps/plataforma/system_health.py:211` | `PdfJob` | `COUNT` agregado de la cola de PDFs (pending/processing/failed_24h), todas las clínicas | `GET /plataforma/sistema/` | `PlatformSystemPermission` (`views.py:678`) | SA, eng |

Lecturas cross-tenant que **no** usan `all_objects` porque no lo necesitan (los modelos no son
`TenantAware` y su manager por defecto ya ve todo): `Tenant.objects` (`selectors.py:79`, `:108`,
`:205`, `:540`, `:573`), `TenantMembership.objects` (`:55`, `:208`, `:230`), `User.objects`
(`:115`, `:145`, `:176`), `Plan.objects` (`:374`, `:395`), `TenantSubscription.objects` (`:577`,
`:586`), `TenantEntitlements.objects` (`:261`). La razón está escrita en `selectors.py:203-204`.

**Lo importante de esta tabla:** los 9 usos están cubiertos, y el único que devuelve datos —no
conteos— es el #8, la bitácora. Los ocho restantes son agregados. Un fallo de permiso en el #8
expondría la actividad completa de todas las clínicas; en los demás, un número.

**El riesgo estructural no está en estas 9 líneas sino en el patrón.** `PlatformAPIView` deja el GUC
vacío, con lo cual **las dos barreras de §1.1.1 quedan apagadas simultáneamente**: la de Django
porque se usa `all_objects`, y la de Postgres porque `current_tenant_id() IS NULL` hace verdadera la
condición `OR` de toda policy. Lo único que separa "el equipo de Maily" de "cualquier usuario
autenticado" es el `permission_class` que cada vista declara a mano. Su `permission_classes` de
clase es `[IsAuthenticated]` (`views.py:132`): una vista nueva que herede y olvide declarar el
permiso queda abierta a cualquier usuario de cualquier clínica. Hoy no ocurre —las 13 vistas lo
declaran—, pero es un fail-open por omisión. Ver `B-PLA-01`.

---

### 13.4 Salud del sistema y qué expone

`GET /api/v1/plataforma/sistema/` → `system_health_get()`
(`apps/plataforma/system_health.py:225-253`). Permiso `PlatformSystemPermission`: `super_admin` y
`engineering`; **`sales` queda fuera** (`views.py:671`, `_PLATFORM_ROLES_SYSTEM`
`core/permissions.py:1103-1105`).

**Respuesta 200** (`serializers.py:452-464`), contrato cerrado con el frontend (`:455-458`):

```json
{
  "generated_at": "2026-08-12T10:00:00-06:00",
  "overall_status": "operational",
  "services": [
    {"key":"database","label":"PostgreSQL","status":"operational","latency_ms":1.84,"detail":null},
    {"key":"redis","label":"Redis","status":"operational","latency_ms":0.92,"detail":null},
    {"key":"celery_worker","label":"Worker Celery","status":"operational","latency_ms":null,
     "detail":"2 worker(s) activo(s)"}
  ],
  "version": {"commit":"a1b2c3d4e5f6","django":"5.2.14","python":"3.12.4","environment":"production"},
  "pdf_queue": {"pending":0,"processing":1,"failed_24h":3}
}
```

Qué expone exactamente, y a quién:

| Dato | De dónde sale | Sensibilidad |
|---|---|---|
| Latencia de PostgreSQL | `SELECT 1` cronometrado (`system_health.py:61-69`) | Baja |
| Latencia de Redis | `ping()` sobre la conexión de `django_redis` (`:95-101`) | Baja |
| Nº de workers de Celery | `app.control.ping(timeout=2s)` (`:130-133`) — **broadcast por el broker** | Baja |
| SHA del commit | `RAILWAY_GIT_COMMIT_SHA`, cortado a 12 caracteres (`:185-187`) | **Media**: identifica la versión exacta desplegada |
| Versión de Django y de Python | `django.get_version()`, `platform.python_version()` (`:195-196`) | **Media**: dice qué CVEs aplican |
| Entorno | `SENTRY_ENVIRONMENT` o derivado de `DEBUG` (`:189-191`) | Baja |
| Cola de PDFs | `PdfJob.all_objects.aggregate(...)` (`:211-217`) | Baja: son conteos, no contenido |

Qué **no** expone, y está bien hecho:

- **Ninguna cadena de conexión, hostname ni credencial.** Cuando un check falla, el mensaje que sale
  por la API es genérico —`"Sin conexión. Revisa los logs del servidor para el detalle."`
  (`:52`)— y el texto real de la excepción va **solo** al log del servidor con `exc_info=True`
  (`:78`, `:110`, `:150`). La referencia está citada en el propio código: OWASP ASVS V7.4
  (`:49-52`). Es el patrón correcto y hay que conservarlo.
- **Nada de datos de clínicas.** Ni nombres, ni conteos por tenant.

Robustez:

- Cada check está aislado con `try/except`: la caída de un servicio nunca produce un 500
  (`:77`, `:109`, `:149`), y `_resolve_pdf_queue` también (`:241-245`).
- `overall_status` = `"down"` si la BD está caída, `"degraded"` si cualquier otro no está
  operacional, `"operational"` si todo lo está (`:160-173`).
- El `SELECT 1` va con `SET LOCAL statement_timeout = 3000` dentro de `transaction.atomic()`
  (`:65-67`), para que una conexión ya establecida pero colgada tenga cota superior sin alterar el
  `statement_timeout` de la conexión compartida por `CONN_MAX_AGE`. Buen detalle.

Costo: el panel refresca cada 30 s (`:210`) y **cada** refresco dispara un broadcast de Celery por
el broker. Sin caché y sin throttle propio. Con un equipo de dos personas es irrelevante; ver
`B-PLA-08`.

---

### 13.5 Matriz de permisos

**Y** = permitido · **No** = 403 · Ninguna celda vacía. El eje de "solo sobre sus propios registros"
solo aparece en el equipo interno, donde un actor tiene restricciones sobre **sí mismo**.

| Acción | `super_admin` | `sales` | `engineering` | Fuente |
|---|---|---|---|---|
| Ver métricas globales | Y | Y | Y | `PlatformMetricsPermission` (`core/permissions.py:1162`) |
| Listar clínicas | Y | Y | Y | `PlatformClinicReadPermission` (`:1176`) |
| Ver ficha de una clínica (incluye nombres y correos de su personal) | Y | Y | **Y** | ídem — ver `B-PLA-04` |
| Crear una clínica | Y | Y | **No** | `PlatformClinicWritePermission` (`:1196`) + revalidación en `services.py:241-245` |
| Suspender / reactivar una clínica | Y | Y | **No** | ídem + `services.py:416-420` |
| Asignar o cambiar el plan de una clínica | Y | Y | **No** | `PlatformSubscriptionPermission` (`:1268`) + `services.py:498-502` |
| Ajustar derechos a la medida (`entitlements`) | Y | **No** | **No** | `PlatformPlanWritePermission` (`:1293`) + `services.py:613-616` |
| Listar planes del catálogo | Y | Y | **No** | `PlatformSubscriptionPermission` (`views.py:717`) |
| Crear un plan | Y | **No** | **No** | `PlatformPlanWritePermission` + `_validar_actor_plan_write` (`services.py:727-750`) |
| Editar un plan (precio, módulos, límites, `is_active`) | Y | **No** | **No** | ídem |
| Ver listado y resumen de suscripciones | Y | Y | **No** | `PlatformSubscriptionPermission` (`views.py:827`, `:868`) |
| Listar el equipo interno | Y | **No** | **No** | `PlatformStaffListPermission` (`:1215`) |
| Crear un usuario del equipo | Y | **No** | **No** | `PlatformStaffWritePermission` (`:1317`) + `_validar_actor_staff_write` (`services.py:971-987`) |
| Editar nombre de otro usuario del equipo | Y | **No** | **No** | ídem |
| Editar **su propio** nombre | Y (solo el suyo) | **No** | **No** | `services.py:1140-1146` permite `first_name`/`last_name` sobre sí mismo |
| Cambiar **su propio** `platform_role` o `is_active` | **No** (anti-lockout) | **No** | **No** | `_STAFF_SELF_PROTECTED_FIELDS` (`services.py:968`, `:1140-1146`) |
| Degradar o desactivar al **último** `super_admin` activo | **No** | **No** | **No** | `services.py:1160-1180` |
| Restablecer la contraseña de otro miembro del equipo | Y | **No** | **No** | `PlatformStaffWritePermission` + `services.py:1260` |
| Leer la bitácora cross-tenant **por API** | Y | **No** | Y | `PlatformAuditPermission` (`:1229`) |
| Leer la bitácora cross-tenant **por Django admin** | Y | **Y (agujero)** | Y | `apps/audit/admin.py:90-98` — ver `B-AUD-02` |
| Ver salud del sistema | Y | **No** | Y | `PlatformSystemPermission` (`:1249`) |
| Leer o escribir cualquier dato clínico de una clínica | **No** | **No** | **No** | No existe endpoint. Un staff sin `TenantMembership` recibe 403 en toda la API de clínica (`core/permissions.py:29-33`) |
| Entrar al Django admin | Y | **Y** | **Y** | `platform_staff_create` pone `is_staff=True` a los tres (`services.py:1058`) |

Dos filas que hay que mirar con lupa: la del Django admin en la bitácora (`B-AUD-02`) y la última
(`B-AUT-02`). El panel de plataforma tiene una matriz de roles cuidada y **el Django admin es una
segunda puerta que no la respeta**.

---

### 13.6 Efectos secundarios

| Operación | Efectos |
|---|---|
| `POST /clinicas/` | Crea `Tenant` + `User` dueño + `TenantMembership` + 1 `Consultorio` + 3 `AppointmentType` + categorías de paciente de sistema + (opcional) `Doctor` + (opcional) `TenantSubscription`, **todo en una transacción** (`services.py:256-341`). Enciende `must_change_password` (`:283-284`). Devuelve la contraseña temporal en el cuerpo. Audita `TENANT_CREATE`, y por debajo `MEMBER_CREATE`, `CONSULTORIO_CREATE`, `DOCTOR_CREATE` (cada service el suyo) |
| `POST /clinicas/<id>/estado/` | `Tenant.status = active\|suspended` con `update_fields` (`services.py:429-430`). **`suspended` corta el acceso de todos los usuarios de esa clínica en su siguiente request** (`core/tenant_context.py:157-160`), sin invalidar tokens ni avisar a nadie. Audita `TENANT_STATUS_CHANGE`. **No se puede volver a `trial`** (`_ALLOWED_TARGET_STATUSES`, `services.py:62-64`) |
| `POST /clinicas/<id>/suscripcion/` | `update_or_create` sobre la fila única, y resetea `period_expired_notified_at=None` (`services.py:525-536`). Cambia los módulos y límites efectivos de la clínica **de inmediato** (§1.4.3): un módulo que sale del plan empieza a responder 404 en el siguiente request. **Los roles ya asignados no se recalculan** (§1.6.3). Audita `SUBSCRIPTION_CHANGE` con plan viejo → nuevo |
| `POST /clinicas/<id>/entitlements/` | `update_or_create` de `TenantEntitlements` (`services.py:626-636`). Mismo efecto inmediato. Audita `TENANT_ENTITLEMENTS_SET` |
| `POST /usuarios/` | Crea `User` con `is_staff=True` y `is_platform_staff=True` (`services.py:1053-1062`). Devuelve la temporal. Audita `STAFF_CREATE` con `metadata={"platform_role": …}` |
| `PATCH /usuarios/<id>/` | `save(update_fields=[…])` solo con los campos tocados (`services.py:1197`). Audita `STAFF_UPDATE` con `cambios` y, si cambió el rol, `platform_role_old/new` |
| `POST /usuarios/<id>/reset-password/` | Nueva temporal + `must_change_password=True` + **blacklist de todos** los `OutstandingToken` del objetivo (`services.py:1272-1288`). Audita `STAFF_PASSWORD_RESET` con `metadata={}` |
| `POST /planes/`, `PATCH /planes/<id>/` | Escriben el catálogo global. Un cambio de `modules` o de límites **afecta a todas las clínicas suscritas de golpe**, sin migración ni aviso. Auditan `PLAN_CREATE` / `PLAN_UPDATE`; el update guarda `price_old`/`price_new` si cambió el precio (`services.py:918-924`) |
| Todos los `GET` | Ninguna escritura y **ninguna entrada de bitácora**. Consultar la ficha de una clínica, sus miembros o la bitácora de todas **no deja rastro** |

#### 13.6.1 La bitácora de plataforma se escribe con `tenant=None`

**Todos** los `audit_record` de esta app pasan `tenant=None`: `services.py:349`, `:436`, `:542`,
`:642`, `:833`, `:930`, `:1074`, `:1208`, `:1294`, y la tarea `tasks.py:102`, `:159`.

La consecuencia es doble y hay que dejarla escrita:

- Esos eventos **no aparecen nunca** en `GET /api/v1/audit/logs/` — ni por el `TenantManager` ni por
  la policy RLS, que perdió el `OR tenant_id IS NULL` (§12.5). Es decir: **la clínica no tiene forma
  de ver que la plataforma la suspendió, le cambió el plan o le apagó un módulo.** Ver `B-PLA-02`.
- El `tenant_id` sí queda dentro de `metadata` (`services.py:359`, `:446`, `:553`, `:650`), así que
  el panel de plataforma puede correlacionar, aunque el filtro `?tenant_id=` de
  `/plataforma/auditoria/` consulta la **columna** (`selectors.py:332-333`) y por lo tanto tampoco
  encuentra estos eventos al filtrar por clínica.

#### 13.6.2 Tarea Celery: `avisar_vencimientos` (`apps/plataforma/tasks.py:50`)

- **Solo avisa. Nunca cambia `Tenant.status` ni ningún estado operativo** — decisión del dueño del
  2026-07-02, escrita en `tasks.py:6-10`. La suspensión de una clínica vencida es manual.
- Escribe `TRIAL_EXPIRED` por cada trial vencido (`:98-115`) y `SUBSCRIPTION_EXPIRED` por cada
  periodo vencido (`:155-174`).
- **Idempotente** por las columnas `trial_expired_notified_at` y `period_expired_notified_at`
  (`:92-96`, `:148-152`): correrla dos veces el mismo día no duplica eventos. Extender el trial o
  renovar con fecha futura resetea el marcador y permite volver a avisar.
- Escribe con un solo `bulk_update` por función (`:121`, `:180-182`), y como `bulk_update` no dispara
  `auto_now`, `updated_at` se fija a mano con el mismo `reference_now` (`:117`, `:176`).
- Corre sin request: `Tenant` y `TenantSubscription` no son `TenantAware`, así que no hay GUC que
  fijar (`:21-26`).
- **NO VERIFICADO**: la periodicidad real de la tarea en Celery beat — no leí `config/celery.py` ni
  la configuración de `beat_schedule`.

#### 13.6.3 Rendimiento: dos lugares que se van a notar antes que el resto

1. `platform_subscriptions_list` construye **todas** las filas en memoria y **después** se paginan
   (`selectors.py:548-557` alimentando `views.py:841-851`): pedir `?page=1` recorre igualmente las N
   clínicas. Y `platform_subscriptions_resumen` llama a la lista completa para contar alertas
   (`selectors.py:590`). Es una decisión consciente y escrita (`selectors.py:523-528`): el filtro de
   alerta no se puede empujar a SQL sin duplicar `_calcular_alerta`. Con decenas de clínicas es
   correcto; con miles, no.
2. `_slug_unico` hace una consulta por intento (`services.py:134-137`), documentado como evento raro
   (`:117-119`). La carrera se atrapa como `IntegrityError` en la vista (`views.py:288-293`) gracias
   al `unique` de `slug`. Está bien resuelto.

Ninguno de los dos justifica hoy caché ni cola: 1–3 usuarios concurrentes.
