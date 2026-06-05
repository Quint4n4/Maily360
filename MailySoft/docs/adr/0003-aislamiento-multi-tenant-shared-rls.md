# ADR-0003 — Aislamiento multi-tenant con Shared Database + Row Level Security

- **Estado:** aceptada
- **Fecha:** 2026-06-05
- **Decisión relacionada:** [ADR-0002 — Arquitectura multi-tenant](0002-arquitectura-multi-tenant.md)

## Contexto

Maily Soft es un SaaS donde muchas clínicas (tenants) usan el mismo software. La
pregunta de fondo: **¿cómo se separan los datos de cada clínica?** Existen tres
estrategias estándar, de menos a más aislamiento físico:

1. **Shared Database, Shared Schema** — una sola base de datos y un solo juego de
   tablas; cada fila lleva una columna `tenant_id` que indica de qué clínica es.
2. **Shared Database, Schema-per-Tenant** — una base de datos, pero un *schema*
   (juego de tablas propio) por clínica; al dar de alta un cliente se crea su schema.
3. **Database-per-Tenant** — una base de datos completa y separada por clínica.

La preocupación legítima del modelo 1 es: *¿un bug podría mostrar datos de una
clínica a otra?* Los modelos 2 y 3 reducen ese riesgo a costa de complejidad
operativa y costo.

## Decisión

Usamos el **modelo 1: Shared Database + Shared Schema**, con `tenant_id` en toda
tabla de negocio, reforzado por **dos barreras de aislamiento independientes**:

1. **Capa de aplicación (Django):** `TenantManager` filtra automáticamente toda
   consulta por el tenant del request. El desarrollador no puede olvidarlo: es el
   manager por defecto de `TenantAwareModel`.
2. **Capa de base de datos (PostgreSQL Row Level Security):** cada tabla tiene una
   política RLS (`FORCE ROW LEVEL SECURITY`) sobre `tenant_id`. Aunque el código
   tuviera un bug y olvidara filtrar, **PostgreSQL rechaza devolver filas de otro
   tenant**. El tenant activo se propaga a la sesión de PostgreSQL en cada request
   (GUC `app.current_tenant_id`).

Una fuga de datos requeriría romper **las dos barreras a la vez**.

## Alternativas consideradas

| Modelo | Pro | Contra | Por qué se descartó como default |
|---|---|---|---|
| **Schema-per-tenant** | Aislamiento fuerte | Migraciones N veces (una por schema); ~500+ schemas degradan el catálogo de Postgres | Inviable operativamente con miles de clínicas pequeñas |
| **Database-per-tenant** | Aislamiento total; backup/restore por cliente trivial | Costo alto por cliente; cada prueba gratis cuesta una BD; provisión y operación complejas | Incompatible con el modelo "prueba gratis + muchas clínicas chicas" |

## Consecuencias

### Positivas
- **Costo marginal por cliente ≈ $0** → encaja con el modelo de prueba gratis +
  suscripción anual y permite escalar a miles de tenants.
- **Una sola migración** aplica a todas las clínicas a la vez.
- **Doble barrera** (manager + RLS) mitiga el riesgo de fuga que motiva los modelos
  2/3. Verificado con 159+ tests de aislamiento (incluido cross-tenant con JWT real).
- Es el patrón estándar de los SaaS con muchos tenants pequeños.

### Negativas / costos
- El aislamiento es **lógico**, no físico: depende de que el manager y la RLS
  funcionen (por eso se auditan y testean de forma estricta).
- Backup/restore de **una sola** clínica es más laborioso que en DB-per-tenant.
- Requiere disciplina: toda tabla de negocio DEBE heredar de `TenantAwareModel` y
  toda migración de tabla tenant-aware DEBE crear su política RLS.

### Puerta abierta (Enterprise)
Para un hospital o cadena que **exija** aislamiento físico total (por contrato o
regulación), se ofrecerá un plan **Enterprise con base de datos dedicada**
(modelo 3) a precio premium. El modelo 1 es el default para el ~95% de los tenants;
el modelo 3 es a la carta. No quedamos atrapados en una sola opción.

## Notas de cumplimiento (NOM-024 / LFPDPPP)
- El aislamiento por tenant + RLS contribuye al control de acceso a datos de salud.
- Pendiente complementario: **bitácora de auditoría** (`apps/audit`) que registre
  accesos y cambios a expedientes — requisito explícito de NOM-024, en construcción.
