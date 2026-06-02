# ADR-0002 — Implementar multi-tenancy con shared schema, TenantManager y RLS como defensa en profundidad

| Campo | Valor |
|---|---|
| Estado | **Aceptada** |
| Fecha | 2026-06-02 |
| Autores | Equipo de arquitectura Maily |
| Revisado por | — |
| Implementado en | commit `8aa9ac9` (Paso 2) |

---

## Contexto

Maily Soft es una plataforma SaaS de gestión clínica. Cada cliente es una clínica independiente (un *tenant*). Los datos clínicos están sujetos a dos marcos normativos mexicanos con requisitos de aislamiento explícitos:

- **NOM-024-SSA3-2010**: obliga a mantener bitácora de auditoría e impide el acceso no autorizado al expediente clínico electrónico.
- **LFPDPPP**: exige que los datos personales sensibles (expediente médico, diagnósticos, medicamentos) no se compartan entre responsables distintos sin consentimiento.

Una fuga de datos entre clínicas — aunque sea por un bug de código — constituye una violación regulatoria con consecuencias legales para Maily y para el titular de la clínica.

Además, el modelo de negocio requiere que:
- Incorporar un nuevo tenant tenga costo operativo casi nulo.
- El mismo usuario (p. ej. un médico independiente) pueda pertenecer a varias clínicas.
- El equipo de plataforma (staff de Maily) pueda administrar tenants sin tener acceso a datos clínicos.

---

## Decisión

Se adopta la estrategia **shared database, shared schema** con las siguientes capas de aislamiento (defensa en profundidad):

### Capa 1 — Modelo de datos: `TenantAwareModel`

Todo modelo de negocio hereda de [`TenantAwareModel`](../../backend/apps/core/models.py), que añade:

- `tenant`: FK a `tenancy.Tenant`, protegida con `on_delete=PROTECT`.
- `created_by`: FK al usuario creador (nullable para seeds e importaciones).
- `objects`: `TenantManager` como manager por defecto.
- `all_objects`: manager estándar sin filtros, solo para management commands, migraciones y tests de bajo nivel.

Los modelos de plataforma (`Tenant`, `User`) heredan de `BaseModel` directamente porque *son* infraestructura de la plataforma, no datos de negocio de un tenant.

### Capa 2 — Manager: `TenantManager`

[`TenantManager`](../../backend/apps/core/managers.py) sobreescribe `get_queryset()` para:

1. Excluir registros con `deleted_at IS NOT NULL` (soft-delete).
2. Si hay un tenant en el thread-local, añadir `filter(tenant_id=tenant.id)`.
3. Si no hay tenant en el thread-local (Celery, management commands, migraciones), devolver todos los registros no eliminados sin filtrar por tenant.

El comportamiento 3 es intencional y seguro: los workers Celery y los comandos de gestión no tienen contexto de request y necesitan visibilidad global para tareas de mantenimiento.

### Capa 3 — Thread-local: `tenant_context`

[`tenant_context.py`](../../backend/apps/core/tenant_context.py) expone tres funciones sobre `threading.local()`:

- `set_current_tenant(tenant)` — llamada al inicio del request.
- `get_current_tenant()` — usada por `TenantManager` y los servicios.
- `clear_current_tenant()` — llamada en el bloque `finally` del middleware para que el thread de gunicorn/uvicorn no filtre datos en el siguiente request.

### Capa 4 — Middleware: `TenantMiddleware`

[`TenantMiddleware`](../../backend/apps/core/middleware.py) se posiciona en `MIDDLEWARE` **después** de `AuthenticationMiddleware` (requiere `request.user` resuelto). Su lógica en el Paso 2:

- Si el usuario está autenticado y tiene membresías activas, toma la primera.
- Si no hay usuario o no tiene membresías, el tenant queda en `None`.

**Evolución planeada en el Paso 3:** leer el header `X-Tenant-ID` y validarlo contra el claim `tenant_id` del JWT de SimpleJWT, para soportar usuarios con membresías en múltiples clínicas.

### Capa 5 — PostgreSQL RLS: función `current_tenant_id()`

La migración [`0002_enable_rls`](../../backend/apps/tenancy/migrations/0002_enable_rls.py) crea en PostgreSQL la función:

```sql
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_tenant_id', true), '')::uuid;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;
```

Esta función será referenciada por las políticas `USING (tenant_id = current_tenant_id())` que se añadirán tabla por tabla a partir del Paso 3. Centralizar la función en `tenancy` evita redefinirla en cada app de negocio.

### Identidad del paciente: arquitectura futura (MPI)

Los datos de identidad del paciente (nombre, CURP, fecha de nacimiento) vivirán en un módulo **Master Patient Index (MPI)** global, fuera del scope de tenant. Los expedientes clínicos, diagnósticos y evoluciones son tenant-scoped y heredan de `TenantAwareModel`. Esta separación se diseña ahora pero se implementa en pasos posteriores.

---

## Alternativas consideradas

| Alternativa | Pro | Contra | Decisión |
|---|---|---|---|
| **Schema-per-tenant** (`SET search_path`) | Aislamiento fuerte sin RLS | Migrar N schemas es operativamente costoso; no escala a cientos de clínicas pequeñas | Rechazada |
| **Database-per-tenant** | Aislamiento máximo | Imposible escalar comercialmente; costo de N instancias PostgreSQL inasumible | Rechazada |
| **Solo filtro en código sin RLS** | Más simple de implementar | Un bug en el ORM o una query manual fuga datos entre tenants sin ninguna red de seguridad | Rechazada |
| **Librería `django-tenants`** | Implementación lista | Usa schema-per-tenant; hereda todos sus costos operativos | Rechazada |

---

## Consecuencias

**Positivas:**
- Incorporar un tenant nuevo es un `INSERT` en `tenancy_tenants`; costo operativo nulo.
- `TenantManager` actúa automáticamente: los desarrolladores no necesitan recordar el filtro en cada query.
- RLS en PostgreSQL es una segunda línea de defensa independiente del código Python: un bug en el ORM no puede filtrar datos de otro tenant.
- La función `current_tenant_id()` ya está en la base de datos; las políticas se activan tabla por tabla sin necesidad de cambios de esquema.

**Negativas / costos:**
- El thread-local introduce un estado global implícito: difícil de rastrear en debugging y potencialmente peligroso si un worker reutiliza el thread sin que `clear_current_tenant()` se haya ejecutado. El bloque `finally` en el middleware mitiga esto pero requiere disciplina.
- En contextos sin request (Celery, scripts), `TenantManager` no filtra por tenant. El desarrollador debe ser consciente de esto y usar `all_objects` explícitamente cuando corresponda.
- Cada nuevo desarrollador debe interiorizar la regla: *todo modelo de negocio hereda de `TenantAwareModel`*. Un modelo que herede de `BaseModel` por error expone datos entre tenants sin protección.
- La integración completa de RLS (activar políticas por tabla) queda pendiente para el Paso 3; hasta entonces, el aislamiento depende exclusivamente de las capas de código.

**Impacto en módulos futuros:**
- Cualquier app de dominio (`agenda`, `expediente`, `facturacion`, `mensajeria`) **debe** heredar todos sus modelos de negocio de `TenantAwareModel`.
- Los tests de cada módulo deben incluir al menos un caso que verifique que un tenant no puede leer datos de otro tenant (test de fuga cross-tenant).
- La migración inicial de cada app de negocio debe añadir la política RLS `USING (tenant_id = current_tenant_id())` sobre su tabla principal.

---

## Referencias

- [BaseModel y TenantAwareModel](../../backend/apps/core/models.py)
- [TenantManager](../../backend/apps/core/managers.py)
- [tenant_context (thread-local)](../../backend/apps/core/tenant_context.py)
- [TenantMiddleware](../../backend/apps/core/middleware.py)
- [Migración RLS — current_tenant_id()](../../backend/apps/tenancy/migrations/0002_enable_rls.py)
- [ADR-0001 — Stack y arquitectura](0001-stack-y-arquitectura.md)
- [PostgreSQL Row Level Security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [NOM-024-SSA3-2010](http://www.dof.gob.mx/normasOficiales/4300/salud6a/salud6a.htm)
- [LFPDPPP — DOF](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf)
