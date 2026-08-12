# Revision de codigo — Paso 2: Cimientos multi-tenant

| Campo | Valor |
|---|---|
| Revisor | django-reviewer |
| Commit revisado | `8aa9ac9` |
| Commit de fixes | `8bf747a` |
| Fecha | 2026-06-02 |
| Veredicto final | Aprobado (tras correcciones) |

---

## Contexto de la revision

Este documento registra los hallazgos del django-reviewer sobre el commit `8aa9ac9` (Paso 2: cimientos multi-tenant). Los hallazgos se clasifican en tres niveles:

- **BLOQUEANTE**: el codigo no puede ir a produccion hasta que se corrija.
- **RECOMENDADO**: no bloquea, pero introduce deuda tecnica o riesgo real.
- **NIT**: estilo, convenciones menores, no afecta funcionalidad.

Los fixes se aplicaron en el commit `8bf747a`. El estado de cada hallazgo refleja la situacion post-fix.

---

## Hallazgos bloqueantes

### BLOQ-1 — Funcion RLS `current_tenant_id()` nunca alimentada

**Descripcion:** El middleware `TenantMiddleware` fijaba el tenant en el thread-local de Python pero nunca ejecutaba `SET LOCAL app.current_tenant_id = '<uuid>'` en la conexion de Postgres. La funcion RLS existia en la base de datos pero siempre devolvía `NULL`, lo que dejaba las politicas RLS sin efecto real. La segunda linea de defensa de la arquitectura de profundidad estaba inactiva.

**Archivo:** [`apps/core/middleware.py`](../../backend/apps/core/middleware.py)

**Correccion aplicada:** FIX-1 en commit `8bf747a`. El middleware ahora ejecuta `SET LOCAL` sobre la conexion activa al inicio del request y lo limpia en el bloque `finally`.

**Estado:** Corregido.

---

### BLOQ-2 — `TenantManager` con tenant=None devolvia datos de todos los tenants

**Descripcion:** Cuando `get_current_tenant()` retornaba `None` (usuario no autenticado, request sin tenant), `TenantManager.get_queryset()` omitia el filtro por `tenant_id` y devolvía todos los registros de la tabla. En contextos de Celery y management commands esto es correcto e intencional, pero en el contexto de un request HTTP autenticado con un usuario que no tiene membresia activa, el comportamiento era una fuga silenciosa: cualquier query devolvía datos de todos los tenants.

**Archivo:** [`apps/core/managers.py`](../../backend/apps/core/managers.py)

**Correccion aplicada:** FIX-2 en commit `8bf747a`. El manager distingue explicitamente entre el contexto de request (donde la ausencia de tenant resulta en queryset vacio, no en queryset global) y el contexto sin request.

**Estado:** Corregido.

---

### BLOQ-3 — Codigo de cimientos sin tests

**Descripcion:** El commit `8aa9ac9` entrego las tres apps (`core`, `tenancy`, `authn`) sin ningun test automatizado. El comportamiento critico del `TenantManager`, el middleware y el `tenant_context` no tenia cobertura.

**Correccion aplicada:** El django-tester escribio 62 tests cubriendo los tres modulos. Cobertura resultante: 98.62 %. Los tests se incluyen en el mismo commit `8bf747a`.

**Estado:** Resuelto.

---

## Hallazgos recomendados

### REC-1 — Indice compuesto (user, is_active) en TenantMembership

**Descripcion:** El middleware consulta la primera membresia activa del usuario en cada request. Sin un indice compuesto sobre `(user_id, is_active)`, esta consulta hace un sequential scan sobre la tabla de membresías a medida que crece.

**Correccion aplicada:** FIX-5 en commit `8bf747a`. Se agrego la migracion `0003` con el indice y se reemplazo `unique_together` deprecado por `UniqueConstraint`.

**Estado:** Corregido.

---

### REC-2 — `created_by` con `PROTECT` en vez de `SET_NULL`

**Descripcion:** `TenantAwareModel.created_by` usaba `on_delete=PROTECT`. Esto impide eliminar un usuario que haya creado cualquier registro, lo que en la practica bloquea la gestion de bajas de personal.

**Archivo:** [`apps/core/models.py`](../../backend/apps/core/models.py)

**Correccion aplicada:** FIX-6 en commit `8bf747a`. Cambiado a `SET_NULL` con `null=True`.

**Estado:** Corregido.

---

### REC-3 — Soft-delete de TenantMembership ignorado por el middleware

**Descripcion:** El middleware recuperaba membresías activas con un filtro `is_active=True` pero no excluia registros con `deleted_at IS NOT NULL`. Un usuario con membresia soft-deleted pero con `is_active=True` (por inconsistencia de datos) podia obtener acceso al tenant.

**Archivo:** [`apps/core/middleware.py`](../../backend/apps/core/middleware.py)

**Correccion aplicada:** FIX-4 en commit `8bf747a`. El middleware ahora filtra explicitamente `deleted_at__isnull=True`.

**Estado:** Corregido.

---

### REC-4 — Funcion RLS sin `SECURITY INVOKER`

**Descripcion:** La funcion `current_tenant_id()` se definio sin declarar explicitamente `SECURITY INVOKER`. Aunque es el comportamiento por defecto, la omision deja ambiguedad para revisores de seguridad y auditores.

**Archivo:** [`apps/tenancy/migrations/0002_enable_rls.py`](../../backend/apps/tenancy/migrations/0002_enable_rls.py)

**Correccion aplicada:** FIX-7 en commit `8bf747a`. La funcion ahora declara `SECURITY INVOKER` explicitamente.

**Estado:** Corregido.

---

### REC-5 — `SIMPLE_JWT` sin `SIGNING_KEY` explicita

**Descripcion:** La configuracion de SimpleJWT en `base.py` no definia `SIGNING_KEY`, lo que la dejaba usando `SECRET_KEY` de Django. Esto es funcional pero crea acoplamiento: rotar el `SECRET_KEY` (por ejemplo ante una filtracion) invalida todos los tokens JWT activos.

**Archivo:** [`config/settings/base.py`](../../backend/config/settings/base.py)

**Correccion aplicada:** FIX-8 en commit `8bf747a`. Se agrego `SIGNING_KEY` como variable de entorno separada con fallback a `SECRET_KEY` en desarrollo.

**Estado:** Corregido.

---

## Nits (menores, no bloqueantes)

| ID | Descripcion | Archivo | Estado |
|---|---|---|---|
| NIT-1 | `unique_together` deprecado desde Django 4.2; usar `UniqueConstraint` | `tenancy/models.py` | Corregido en FIX-5 (`8bf747a`) |
| NIT-2 | `default_auto_field` en `AppConfig` duplica la configuracion global de `base.py`; genera confusion sobre cual tiene precedencia | `core/apps.py` | Pendiente (baja prioridad) |
| NIT-3 | `prepopulated_fields` en el admin de `Tenant` funciona solo en el admin de Django; no aplica a la API REST | `tenancy/admin.py` | Pendiente (baja prioridad) |
| NIT-4 | Anotaciones de tipo usan `Optional[X]` en lugar de la sintaxis moderna `X \| None` (Python 3.10+) | `core/models.py`, `authn/models.py` | Pendiente (baja prioridad) |

---

## Mapa de fixes commit `8bf747a`

| Fix | Hallazgo que resuelve | Descripcion resumida |
|---|---|---|
| FIX-1 | BLOQ-1, REC-4 (parcial) | Middleware ejecuta `SET LOCAL` en Postgres |
| FIX-2 | BLOQ-2 | Manager distingue contexto request vs. sin-request |
| FIX-3 | (ver security audit) | Tenant suspendido bloqueado en middleware |
| FIX-4 | REC-3 | Middleware excluye membresías soft-deleted |
| FIX-5 | REC-1, NIT-1 | Indice compuesto + `UniqueConstraint` en migracion 0003 |
| FIX-6 | REC-2 | `created_by` cambiado a `SET_NULL` |
| FIX-7 | REC-4 | Funcion RLS declara `SECURITY INVOKER` |
| FIX-8 | REC-5 | `SIMPLE_JWT` con `SIGNING_KEY` separada |
| FIX-9 | (ver security audit) | OpenAPI deshabilitado en produccion |
| FIX-10 | (ver security audit) | Orden determinista en consulta de membresia |

---

## Veredicto

El commit `8aa9ac9` tenia hallazgos bloqueantes que impedian la entrega. Tras la correccion completa en `8bf747a`:

- Los 3 bloqueantes estan resueltos.
- Los 5 recomendados estan resueltos.
- Los 4 nits quedan registrados; 1 fue corregido (NIT-1), los 3 restantes son de baja prioridad y no afectan seguridad ni correctitud.

**El codigo del Paso 2 queda aprobado para servir de base al Paso 3.**
