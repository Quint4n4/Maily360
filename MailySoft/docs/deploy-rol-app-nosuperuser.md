# Rol de aplicación NOSUPERUSER en producción (activar RLS como 2ª barrera)

> Estado: guía lista, **NO aplicada en Railway todavía**. Probado y validado en
> local (Fase A). Ver también `design/pgbouncer-rls-escalabilidad.md`.

## Por qué

Hoy la app en Railway se conecta con el usuario `postgres`, que es **superuser**
(`rolsuper=t`, `rolbypassrls=t`). PostgreSQL exime a los superusers de Row Level
Security **incluso con FORCE**, así que las políticas RLS del proyecto están
**inertes en producción**: el aislamiento entre clínicas depende solo del
`TenantManager` (capa de aplicación). Queremos recuperar la 2ª barrera (RLS a
nivel BD) conectando la app con un rol sin privilegios.

Diseño: **dos roles según la tarea**.

| Tarea | Rol | Por qué |
|---|---|---|
| App día a día (web + worker) | `maily_app` (NOSUPERUSER NOBYPASSRLS) | RLS + FORCE le aplica → 2ª barrera activa |
| Migraciones (al desplegar) | `postgres` (el actual) | Solo él puede crear/alterar tablas y políticas |

El código ya soporta esto: `entrypoint.sh` usa `MIGRATION_DATABASE_URL` (rol
privilegiado) solo para `migrate`; el resto usa `DATABASE_URL` (rol de app).

## Validación en local (Fase A, ya hecha)

Con un `maily_app` NOSUPERUSER creado en el Postgres de Docker, fijando el GUC a
una clínica y consultando pacientes **saltándose el ORM**:

- `postgres`/superuser → vio **todos** los pacientes de todas las clínicas (RLS ignorado).
- `maily_app` → vio **solo** los de la clínica del GUC (RLS aplica). ✅
- `maily_app` puede `SELECT/INSERT/UPDATE/DELETE` pero **no** `CREATE TABLE`
  (`permission denied`) → confirma que las migraciones necesitan `postgres`.
- Django conecta con `maily_app` y `manage.py check_db_role` reporta `SUPERUSER: False`.

## Pasos en Railway (Fase B)

### Requisitos
- Saber el nombre de tu base (en Railway suele ser `railway`).
- Tener a mano la `DATABASE_URL` actual del plugin Postgres (la usarás como
  `MIGRATION_DATABASE_URL` sin cambios, y como plantilla para la de `maily_app`).
- Una contraseña fuerte nueva para `maily_app`. Genera una con, p. ej.:
  `openssl rand -base64 24`

### Paso 1 — Crear el rol en la consola de Postgres (pestaña Database → Query)

Reemplaza `PON_UNA_CONTRASEÑA_FUERTE` y, si tu base no se llama `railway`,
ajusta el nombre. Ejecuta todo el bloque:

```sql
-- 1. Rol de aplicación SIN poderes (RLS le aplicará)
CREATE ROLE maily_app WITH LOGIN PASSWORD 'PON_UNA_CONTRASEÑA_FUERTE'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

-- 2. Permiso de conexión y de usar el esquema
GRANT CONNECT ON DATABASE railway TO maily_app;   -- ajusta 'railway' si aplica
GRANT USAGE ON SCHEMA public TO maily_app;

-- 3. Permisos de datos sobre lo que YA existe
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO maily_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO maily_app;

-- 4. CRÍTICO: permisos automáticos sobre lo que se cree EN EL FUTURO
--    (cada deploy con tablas nuevas). Sin esto, la app se rompería tras la
--    próxima migración. Las tablas las crea 'postgres', por eso FOR ROLE postgres.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO maily_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO maily_app;
```

### Paso 2 — Verificar el rol ANTES de tocar la app (sin riesgo)

En la misma consola Query:

```sql
-- Debe decir rolsuper=false, rolbypassrls=false
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'maily_app';

-- Debe listar muchas tablas (que maily_app tiene permiso de leer)
SELECT count(*) FROM information_schema.role_table_grants WHERE grantee = 'maily_app';
```

### Paso 3 — Configurar las variables en el servicio backend (web) y worker

Construye la URL de `maily_app` a partir de tu `DATABASE_URL` actual: es la
misma cadena, cambiando **solo** el usuario y la contraseña.

```
# Actual (ejemplo):  postgresql://postgres:XXXX@HOST.railway.internal:5432/railway
# Nueva (maily_app): postgresql://maily_app:TU_CONTRASEÑA@HOST.railway.internal:5432/railway
```

En el **servicio web** (Variables):
- `DATABASE_URL` = la URL de **maily_app** (deja de usar `${{Postgres.DATABASE_URL}}`).
- `MIGRATION_DATABASE_URL` = la URL de **postgres** de siempre
  (`${{Postgres.DATABASE_URL}}` sigue sirviendo aquí).

En el **servicio worker** (Celery):
- `DATABASE_URL` = la URL de **maily_app**.
- No necesita `MIGRATION_DATABASE_URL` (el worker no migra: `RUN_MIGRATIONS=false`).

### Paso 4 — Redesplegar y verificar

Al guardar, Railway redespliega. Cuando termine, en el shell del servicio web
(o con la CLI) corre:

```
python manage.py check_db_role
```

Debe decir `Usuario: maily_app`, `SUPERUSER: False` y el ✅ verde. Haz un login
de prueba y navega el portal + una clínica para confirmar que todo responde.

## Plan para deshacer (rollback)

Si algo falla (la app no lee/escribe, errores 500):

1. En el servicio web y worker, vuelve a poner `DATABASE_URL = ${{Postgres.DATABASE_URL}}`
   (el usuario `postgres` de siempre) y borra `MIGRATION_DATABASE_URL`.
2. Redespliega. Vuelves al estado actual en 1-2 minutos.

El rol `maily_app` puede quedarse creado sin problema; no estorba hasta que la
app lo use.

## Advertencias importantes

- **Esto ACTIVA RLS por primera vez en producción.** Hoy, con `postgres`
  superuser, las políticas nunca se ejercen. Al cambiar a `maily_app`, cualquier
  consulta que dependiera de "RLS apagado" se comportará distinto. Los flujos
  normales están cubiertos (el middleware/`TenantAPIView` fijan el GUC; Celery y
  el portal cross-tenant usan el fallback `IS NULL`), pero **la suite de tests
  corre con un rol superuser**, así que no valida el sistema entero con RLS
  activo. Recomendación: aplicar en **horario de bajo tráfico**, con el rollback
  listo, y probar los flujos clave (login, agenda, pacientes, recetas, portal).
- Mantén `postgres` **solo** para migraciones/administración, nunca como usuario
  del tráfico normal.
- Este cambio es **independiente de pgbouncer**: es un prerequisito, pero no
  activa `DB_TENANT_GUC_MODE=local`. Son dos pasos separados.
- Opcional (mayor rigor, futuro): crear un rol NOSUPERUSER también en
  `docker-compose.yml` para que la suite de tests valide el enforcement real de
  RLS, no solo la expresión de la política.
