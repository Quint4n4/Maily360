# Auditoria de seguridad — Paso 2: Cimientos multi-tenant

| Campo | Valor |
|---|---|
| Auditor | django-security |
| Commit auditado | `8aa9ac9` |
| Commit de remediation | `8bf747a` |
| Fecha | 2026-06-02 |
| Marco normativo | NOM-024-SSA3-2010 · NOM-004-SSA3-2012 · LFPDPPP |
| Veredicto final | Seguro para construir encima (post-fixes) |

---

## Clasificacion del sistema

Maily Soft procesa **datos de salud** (expedientes clinicos, diagnosticos, medicamentos, evolucion del paciente). Esta categoria de datos es de las mas sensibles bajo el marco normativo mexicano:

- **NOM-024-SSA3-2010** ("Para los sistemas de informacion de registro electronico para la salud"): obliga a mantener bitacoras de auditoria e impide el acceso no autorizado al expediente clinico electronico.
- **NOM-004-SSA3-2012** ("Del expediente clinico"): regula el contenido minimo y la confidencialidad del expediente.
- **LFPDPPP** (Ley Federal de Proteccion de Datos Personales en Posesion de los Particulares): clasifica los datos de salud como *datos sensibles*, sujetos al nivel de proteccion mas alto. Una fuga entre responsables distintos (tenants) es una violacion directa.

Cualquier fuga de datos entre tenants — aunque sea por un bug de codigo — tiene consecuencias legales para Maily y para el titular de cada clinica.

---

## Hallazgos de severidad ALTA

### ALTO-1 — Tenant suspendido seguia siendo activo en el middleware

**Descripcion:** El middleware `TenantMiddleware` consultaba la primera membresia activa del usuario (`is_active=True`) pero no verificaba el estado del `Tenant` asociado. Un tenant con `status=SUSPENDED` podia seguir sirviendo requests porque el filtro se aplicaba solo sobre la membresia, no sobre el tenant.

Un tenant puede ser suspendido por falta de pago, por una investigacion de uso indebido o por instruccion de la plataforma. Si el acceso continua tras la suspension, se pierde el control operativo del ciclo de vida del tenant y se expone la plataforma a responsabilidad en caso de uso indebido post-suspension.

**Archivo afectado:** [`apps/core/middleware.py`](../../backend/apps/core/middleware.py)

**Remediacion aplicada:** FIX-3 en commit `8bf747a`. El middleware ahora verifica `tenant.status != SUSPENDED` antes de establecer el contexto. Un tenant suspendido produce la misma respuesta que no tener membresia activa.

**Estado:** Corregido.

---

### ALTO-2 — Soft-delete de TenantMembership ignorado por el middleware

**Descripcion:** El middleware no excluia registros con `deleted_at IS NOT NULL` al consultar membresías activas. Un usuario cuya membresia fue marcada como eliminada (soft-delete) pero cuyo campo `is_active` no fue actualizado de forma atomica podia seguir obteniendo un contexto de tenant valido.

Esto afecta el control de acceso en el momento de baja de un empleado: si el proceso de baja hace soft-delete sin actualizar `is_active` primero, o si hay un fallo a mitad del proceso, el usuario conserva acceso.

**Archivo afectado:** [`apps/core/middleware.py`](../../backend/apps/core/middleware.py)

**Remediacion aplicada:** FIX-4 en commit `8bf747a`. El middleware filtra explicitamente `deleted_at__isnull=True` ademas de `is_active=True`.

**Estado:** Corregido.

---

## Hallazgos de severidad MEDIA

### MEDIO-1 — Funcion RLS `current_tenant_id()` nunca alimentada

**Descripcion:** La migracion `0002_enable_rls` creó la funcion `current_tenant_id()` en Postgres, pero el middleware no ejecutaba `SET LOCAL app.current_tenant_id = '<uuid>'` sobre la conexion de base de datos. La funcion siempre retornaba `NULL`, dejando todas las politicas RLS (presentes y futuras) sin efecto.

Desde el punto de vista de seguridad, el sistema operaba con una sola capa de aislamiento (el ORM) en lugar de las dos capas previstas por el [ADR-0002](../adr/0002-arquitectura-multi-tenant.md). Un bug en el codigo Python suficiente para causar una fuga de datos entre tenants sin ninguna red de seguridad en Postgres.

**Archivo afectado:** [`apps/core/middleware.py`](../../backend/apps/core/middleware.py)

**Remediacion aplicada:** FIX-1 en commit `8bf747a`. Coordinada con el django-reviewer (BLOQ-1).

**Estado:** Corregido.

---

### MEDIO-2 — Documentacion OpenAPI accesible publicamente en produccion

**Descripcion:** La configuracion inicial de `urls.py` exponia los endpoints de `drf-spectacular` (`/api/schema/`, `/api/docs/`) sin restriccion de entorno. En produccion, la documentacion OpenAPI publica facilita el reconocimiento de la superficie de ataque: un atacante puede enumerar todos los endpoints, parametros y esquemas de respuesta sin autenticacion.

**Archivo afectado:** [`config/urls.py`](../../backend/config/urls.py)

**Remediacion aplicada:** FIX-9 en commit `8bf747a`. Los endpoints de documentacion quedan activos solo cuando `DEBUG=True` (entornos de desarrollo/staging). En produccion se desactivan.

**Estado:** Corregido.

---

### MEDIO-3 — Orden no determinista en la consulta de membresia del middleware

**Descripcion:** El middleware recuperaba la primera membresia activa del usuario sin aplicar un `ORDER BY` explicito. Sin orden determinista, la base de datos puede retornar cualquier membresia activa dependiendo del plan de ejecucion de la query. Para un medico con membresías en dos clinicas, esto podia resultar en asignacion aleatoria de contexto de tenant entre requests, violando el principio de menor privilegio.

**Archivo afectado:** [`apps/core/middleware.py`](../../backend/apps/core/middleware.py)

**Remediacion aplicada:** FIX-10 en commit `8bf747a`. La consulta ahora incluye `order_by('created_at')` para comportamiento reproducible.

**Estado:** Corregido.

---

## Hallazgos informativos (INFO)

Estos hallazgos no representan vulnerabilidades inmediatas pero deben atenderse en proximas fases:

| ID | Descripcion | Impacto | Accion sugerida |
|---|---|---|---|
| INFO-1 | `normalize_email` solo normaliza el dominio (lowercase); el segmento local queda sensible a mayusculas | Riesgo de duplicados de cuenta (`User@clinic.com` vs `user@clinic.com`) | Normalizar todo el email a lowercase en `UserManager.create_user` en el Paso 3 |
| INFO-2 | `SIMPLE_JWT` sin `SIGNING_KEY` separada (post-fix queda como buena practica, pero la rotacion del secreto debe documentarse) | Invalida sesiones activas al rotar `SECRET_KEY` | Documentar el proceso de rotacion en el runbook operacional |
| INFO-3 | Configuracion de Celery con defaults de Django; sin limites de tasa ni timeout de tareas | Las tareas mal escritas pueden agotar recursos | Establecer `task_soft_time_limit` y `task_time_limit` antes del primer modulo async |
| INFO-4 | `.env.dev` contiene valores de secretos reales de desarrollo | Si el archivo llega al repo por error, los secretos se exponen | El archivo esta correctamente en `.gitignore`; verificar en cada PR que no se incluya |

---

## Controles positivos verificados

Los siguientes controles de seguridad estaban correctamente implementados en el commit `8aa9ac9` y se mantienen en `8bf747a`:

| Control | Descripcion | Ubicacion |
|---|---|---|
| try/finally en middleware | `clear_current_tenant()` se ejecuta siempre al finalizar el request, incluso si lanza excepcion | [`middleware.py`](../../backend/apps/core/middleware.py) |
| Argon2 como hasher por defecto | Mayor resistencia a ataques de fuerza bruta que bcrypt o PBKDF2 | `config/settings/base.py` + `pyproject.toml` |
| Sin referencias a `auth.User` | El codigo usa `settings.AUTH_USER_MODEL` y `get_user_model()` en todos lados; no hay acoplamiento duro al modelo de usuario de Django | `core/models.py`, `tenancy/models.py` |
| `IsAuthenticated` como permiso global | Todo endpoint requiere autenticacion por defecto; los publicos deben declararlo explicitamente | `config/settings/base.py` |
| UUIDs como primary key | Impide enumeracion de recursos por ID incremental | `core/models.py` (`BaseModel`) |
| `related_name="+"` en `created_by` | Evita relaciones inversas no intencionales que podrian exponer datos | `core/models.py` |
| HTTPS/HSTS en produccion | `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` configurados en `settings/production.py` | `config/settings/production.py` |
| Test de aislamiento de hilos | `test_zzz_tenant_isolation.py` verifica que el thread-local no fuga entre requests concurrentes | [`tests/test_zzz_tenant_isolation.py`](../../backend/apps/core/tests/test_zzz_tenant_isolation.py) |
| `all_objects` controlado | El manager sin filtros de tenant es accesible solo como atributo explicito `Model.all_objects`; no es el manager por defecto | `core/models.py` |
| `EXCEPTION WHEN OTHERS` en funcion RLS | La funcion `current_tenant_id()` captura errores de conversion y retorna `NULL` en lugar de lanzar excepcion; falla de forma segura | `tenancy/migrations/0002_enable_rls.py` |

---

## Veredicto

**Pre-fixes (`8aa9ac9`):** No apto para produccion. Dos hallazgos de severidad alta (control de acceso) y la RLS inactiva representan riesgos inaceptables para un sistema que procesa datos de salud bajo NOM-024 y LFPDPPP.

**Post-fixes (`8bf747a`):** Los 2 hallazgos altos y los 3 medios estan corregidos. Los hallazgos informativos no bloquean el avance pero deben agendarse. Los 10 controles positivos verificados muestran una postura de seguridad solida en los cimientos.

**El sistema es seguro para construir el Paso 3 encima de el.** La activacion de las politicas RLS tabla por tabla en el Paso 3 completara la arquitectura de defensa en profundidad descrita en el [ADR-0002](../adr/0002-arquitectura-multi-tenant.md).

---

## Referencias normativas

- [NOM-024-SSA3-2010](http://www.dof.gob.mx/normasOficiales/4300/salud6a/salud6a.htm)
- [NOM-004-SSA3-2012](https://www.dof.gob.mx/normasOficiales/4867/salud1_C/salud1_C.htm)
- [LFPDPPP — DOF](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf)
- [OWASP Django Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Django_Security_Cheat_Sheet.html)
- [ADR-0002 — Arquitectura multi-tenant](../adr/0002-arquitectura-multi-tenant.md)
