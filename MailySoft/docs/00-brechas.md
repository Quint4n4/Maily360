# Brechas — lo que el código hace y la documentación no dice

> Producido en la sesión A2 de adopción (`architect` en MODO INVERSO), junto con
> `docs/02-contrato.md`. Una **brecha** es una diferencia entre lo que se creyó construir y lo que
> efectivamente se construyó. Es donde vive la mayoría de los bugs.

| | |
|---|---|
| Fecha | 2026-08-12 |
| Commit auditado | `ac4bc08` |
| Contra qué se comparó | `docs/01-analisis.md`, `docs/_legacy/README.md` y el propio código |
| Documento hermano | `docs/02-contrato.md` — lo que el sistema hace hoy |

## Qué NO es este documento

**No es `docs/00-deuda.md`.** Las severidades de aquí son **propuestas**, no veredictos. La deuda
priorizada de verdad sale de la sesión A3, donde el `reviewer` audita el código por su cuenta con su
propio checklist. Si A3 no confirma una brecha de aquí con `archivo:línea`, gana A3.

**No se corrigió nada.** Un endpoint sin `permission_classes` está documentado, no arreglado. Es
deliberado: documentar y arreglar a la vez produce un contrato que no describe ni el sistema viejo
ni el nuevo.

## Cómo se leen las severidades propuestas

| | Criterio |
|---|---|
| **P0** | Fuga de datos entre clínicas, endpoint sin control de acceso, escalamiento de privilegios, pérdida o corrupción de datos clínicos o de dinero. Se atiende antes de vender la siguiente licencia |
| **P1** | Incumplimiento normativo, evidencia de auditoría falsificable, PII expuesta de más, promesa comercial sin implementación, rendimiento que ya duele |
| **P2** | Código muerto, inconsistencias de documentación, deuda de tests, cosas que se arreglan cuando se toque ese archivo |

## Prefijos de identificador

`B-T` transversal · `B-PAC` pacientes · `B-AGE` agenda · `B-EXP` expediente · `B-REC` recetas y PDFs
· `B-FIN` finanzas · `B-CLI` Mi Consultorio · `B-PER` personal · `B-NOT` notas · `B-NTF`
notificaciones · `B-AUT` autenticación · `B-AUD` bitácora · `B-PLA` portal interno.

## Resumen

**167 brechas: 4 P0 · 48 P1 · 115 P2.**

| Bloque | Total | P0 | P1 | P2 |
|---|---:|---:|---:|---:|
| Transversal (`core`, `tenancy`, `sucursal_scope`) | 20 | 0 | 7 | 13 |
| Pacientes, notas y avisos | 22 | 0 | 6 | 16 |
| Agenda | 22 | 0 | 4 | 18 |
| Expediente | 12 | 0 | 2 | 10 |
| Recetas y PDFs | 16 | **1** | 4 | 11 |
| Finanzas | 22 | **3** | 9 | 10 |
| Mi Consultorio y Personal | 26 | 0 | 8 | 18 |
| Notificaciones, autenticación, bitácora y portal interno | 27 | 0 | 8 | 19 |
| **Total** | **167** | **4** | **48** | **115** |

### Las cuatro P0

| ID | Qué pasa |
|---|---|
| `B-REC-01` | No existe ninguna ruta para marcar un medicamento como controlado: el módulo F6 completo es inalcanzable. Una receta de Clonazepam sale como receta común |
| `B-FIN-01` | Se puede timbrar dos veces el mismo pago: dos folios y dos UUID del SAT sobre un solo cobro |
| `B-FIN-02` | `quote_accept` sin bloqueo: dos aceptaciones concurrentes duplican los cargos |
| `B-FIN-03` | La llamada al PAC ocurre dentro de la transacción: un CFDI puede quedar timbrado ante el SAT sin fila en la base |

**Que no haya ninguna P0 de fuga entre clínicas es el resultado más importante de esta sesión.** Las
cuatro P0 son de integridad de datos dentro de una misma clínica, no de aislamiento. Ningún
subagente encontró un camino por el que una clínica lea datos de otra. Las 48 P1 sí incluyen huecos
de alcance por sucursal, de permisos por objeto y de evidencia de auditoría.

---
## Transversal (core, tenancy, sucursal_scope)

> Hallazgos de la extracción del contrato inverso de la capa transversal (A2, 2026-08-12).
> **No se corrigió nada de código.** Severidades son *propuestas*: las confirma o las mueve A3.
> Alcance: `apps/core/`, `apps/tenancy/`, `apps/clinica/sucursal_scope.py`, `config/settings/*`,
> `config/urls.py` y `apps/core/tests/test_rls_coverage.py`.

### B-T-01 · Un usuario con dos membresías no puede elegir clínica: `X-Tenant-ID` no existe
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/core/tenant_context.py:156` (resolución) · `MailySoft/backend/apps/tenancy/models.py:29` (única mención del header)
- **Qué dice la documentación:** `docs/01-analisis.md:333-336` lo declara riesgo abierto; `docs/_legacy/README.md:125` dice que ADR-0002 prometió `X-Tenant-ID` validado contra el JWT y que "sigue sin implementarse"; `docs/01-analisis.md:261` lo lista en "NO incluye".
- **Qué hace el código:** `resolve_membership_for_user()` devuelve `.order_by("created_at").first()` sobre las membresías activas con tenant en `active`/`trial`. La clínica activa es siempre la **más antigua**. Búsqueda en todo `MailySoft/backend`: no hay ningún lector de `X-Tenant-ID` / `HTTP_X_TENANT`; solo aparece en un docstring y en un comentario de test. `GET /me/` devuelve la lista completa de `memberships` (`apps/authn/serializers.py:87`) pero no hay endpoint ni header para cambiar la activa.
- **Consecuencia concreta:** un médico que trabaja en dos clínicas escribe la nota de evolución y emite la receta **siempre en la clínica donde lo dieron de alta primero**. Como la nota clínica y la receta son inmutables por diseño (`apps/core/permissions.py:747-751`), el error no se corrige: se anula y se rehace, dejando rastro en el expediente equivocado.

### B-T-02 · La barrera de RLS es *fail-open* sin GUC: la protección efectiva fuera de `TenantAPIView` es solo el manager de Django
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/pacientes/migrations/0002_enable_rls.py:31` (patrón de policy, replicado en todas las apps) · `MailySoft/backend/apps/core/managers.py:32` · `MailySoft/backend/apps/plataforma/views.py:122-128`
- **Qué dice la documentación:** `docs/01-analisis.md:228-233` presenta la doble barrera como "la pieza de seguridad mejor resuelta del proyecto" y `:76` explica el cross-tenant del staff interno diciendo que opera "con `all_objects` (bypass explícito del filtro por clínica)".
- **Qué hace el código:** la policy es `USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)`. Cuando el GUC está vacío, RLS **deja ver todo**, no bloquea. El cross-tenant de plataforma no lo habilita `all_objects` (eso solo salta el manager de Django): lo habilita **la propia política de la base**, porque `PlatformAPIView` nunca fija el GUC. Es decir: en cualquier request que no pase por `TenantAPIView` (los de `authn`, los de `plataforma`), en cualquier tarea Celery y en cualquier management command, **la segunda barrera está inerte**; lo único que aísla es el `TenantManager`, y solo si el código usa `objects` y no `all_objects`.
- **Consecuencia concreta:** una consulta con `all_objects` o SQL crudo dentro de una tarea Celery —por ejemplo el worker que arma el PDF del libro clínico— puede leer expedientes de otra clínica sin que nada la detenga: no hay excepción, no hay 404, no hay registro. La doble barrera solo es doble dentro de los endpoints que heredan de `TenantAPIView`.

### B-T-03 · El test guardián de RLS corre con rol superuser: verifica el catálogo, no el comportamiento
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/core/tests/test_rls_coverage.py:255-258` · `MailySoft/backend/apps/core/management/commands/check_db_role.py:57-70` · `.github/workflows/ci.yml:86-97`
- **Qué dice la documentación:** `docs/01-analisis.md:228-233` afirma que hay "un test guardián que recorre todos los modelos contra el catálogo de PostgreSQL y falla en CI si alguien agrega una tabla sin política". `docs/_legacy/README.md:126` pide añadir al ADR-0003 "el rol de aplicación NOSUPERUSER, sin el cual `FORCE RLS` no aplica al dueño de las tablas".
- **Qué hace el código:** el propio test lo dice: *"no se puede validar funcionalmente aquí porque la suite corre con un rol superuser (exento de RLS); por eso se inspecciona la expresión de la policy"*. CI arranca Postgres con `POSTGRES_USER: mailysoft`, que es el dueño/superusuario de la base, y **no ejecuta `check_db_role`** en ningún paso. Resultado: CI garantiza que la policy *existe y está bien escrita*, nunca que *bloquea*.
- **Consecuencia concreta:** si producción se conecta con un rol superuser (que es el default de un Postgres de Railway recién creado), el aislamiento de dos clínicas depende exclusivamente del filtro de Django, y **ningún test lo delata**. La verificación existe (`check_db_role`) pero hay que acordarse de correrla a mano contra el entorno real.

### B-T-04 · `tenancy_memberships` —la tabla que decide quién pertenece a qué clínica— no tiene RLS
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/tenancy/models.py:78` (hereda `BaseModel`, no `TenantAwareModel`) · `MailySoft/backend/apps/tenancy/selectors.py:4-5` · `MailySoft/backend/apps/core/tests/test_rls_coverage.py:62` (el guardián solo recorre subclases de `TenantAwareModel`)
- **Qué dice la documentación:** `docs/01-analisis.md:229-231` afirma que "**ninguna tabla con datos de clínica quedó sin política RLS**, incluidas las tablas intermedias de las relaciones muchos-a-muchos".
- **Qué hace el código:** `TenantMembership` **sí tiene** columna `tenant_id`, pero hereda de `BaseModel`, así que ni pasa por `TenantManager` ni el guardián la mira ni existe política RLS para ella. Lo mismo aplica a `tenancy_subscriptions` y `tenancy_entitlements` (con FK a `Tenant`). El aislamiento es un `filter(tenant=...)` escrito a mano en cada selector, y el propio archivo lo declara: *"Las membresías NO heredan de TenantAwareModel, así que el aislamiento por tenant se aplica EXPLÍCITAMENTE"*.
- **Consecuencia concreta:** hoy todos los selectores filtran bien, pero es una regla que se recuerda, no un mecanismo que se aplica. El día que alguien escriba `TenantMembership.objects.filter(role="owner")` para un reporte, obtendrá los dueños de **todas** las clínicas de la plataforma —correos incluidos— y ni el manager ni la base dirán nada. La afirmación del análisis es falsa en el sentido estricto: hay tablas con datos de clínica sin política.

### B-T-05 · El detalle de una nota de cita no se acota por sucursal
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:1144` (`AgendaItemNoteDetailApi`)
- **Qué dice la documentación:** `docs/01-analisis.md:346-348` lo lista como riesgo 7, "hallazgo de alcance por sucursal abierto… lo predijo la propia auditoría de sucursales y sigue ahí". `docs/_legacy/README.md:46` confirma que es el único hallazgo que la auditoría de sucursales dejó abierto.
- **Qué hace el código:** el resto de la app aplica `sucursal_scope_ids(request)` en los listados y `allowed_sucursales` en las escrituras (`apps/clinica/sucursal_scope.py:429`, `:135`); esta vista resuelve la nota por id sin pasar por ninguno de los dos. El permiso `AgendaItemNotePermission` (`apps/core/permissions.py:616`) solo gatea por rol.
- **Consecuencia concreta:** en una clínica con dos sedes, el administrador de Norte —que no puede ver la agenda de Centro— sí puede leer y borrar por id la nota que el equipo de Centro escribió sobre una cita de Centro, que suele traer nombre del paciente y motivo.

### B-T-06 · El límite `max_usuarios` cuenta membresías, no cuentas habilitadas, y no hay forma de dar de baja a un miembro
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/tenancy/services.py:254-260` (conteo) · `MailySoft/backend/apps/tenancy/models.py:230-233` (`help_text` del campo) · `MailySoft/backend/apps/tenancy/urls.py:11-15` (rutas existentes)
- **Qué dice la documentación:** `Plan.max_usuarios` se describe en el propio modelo como "Máximo de **miembros activos** de la clínica". `docs/01-analisis.md:100-102` anticipa como riesgo "que el dueño exceda el límite de usuarios del plan a media captura del equipo".
- **Qué hace el código:** el conteo es `TenantMembership.objects.filter(tenant=tenant, is_active=True, deleted_at__isnull=True).count()`, es decir cuenta **membresías**. Bloquear a alguien (`PATCH …/miembros/<id>/` con `blocked=true`) apaga `user.is_active` (`services.py:441`), **no** `membership.is_active`, así que sigue contando. Y no existe ningún endpoint `DELETE /api/v1/miembros/<id>/`: la app solo expone GET/POST de lista, PATCH de detalle y POST/DELETE de avatar.
- **Consecuencia concreta:** una clínica en plan Básico (tope 3 usuarios) despide a su recepcionista, la bloquea como indica la UI, e intenta dar de alta al reemplazo: recibe 400 *"El plan de esta clínica permite 3 usuarios y ya hay 3"*. **No hay salida desde el producto** —ni borrar, ni liberar el cupo— más que subir de plan o pedir intervención manual en el admin de Django.

### B-T-07 · `OPTIONS` pasa por encima del rol y del gating por módulo
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/core/permissions.py:123-124` · `MailySoft/backend/apps/core/entitlement_guards.py:75-76`
- **Qué dice la documentación:** `CLAUDE.md` regla dura 3: "un módulo apagado responde 404, no 403. La clínica no debe saber que existe algo que no compró". `docs/01-analisis.md:217-218` repite la regla.
- **Qué hace el código:** tanto `HasClinicRole` como `RequiresModule` devuelven `True` incondicionalmente para `OPTIONS`, con una razón legítima (si el preflight CORS devuelve 403 el frontend queda inutilizable). Pero DRF responde a `OPTIONS` con `SimpleMetadata`: 200 y el nombre y descripción de la vista. `IsAuthenticated` sigue aplicando, así que hace falta una sesión válida — cualquier sesión.
- **Consecuencia concreta:** una recepcionista de una clínica en plan Básico manda `OPTIONS /api/v1/cotizaciones/` y recibe 200 con el nombre de la vista, en vez del 404 que el contrato promete. Lo mismo un usuario `finance` contra un endpoint de expediente. No se filtran datos de pacientes, pero sí el catálogo de lo que la clínica no compró y de lo que su rol no puede tocar.

### B-T-08 · El módulo `recordatorios` es vendible pero no se hace valer en ningún punto
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/core/entitlement_guards.py:93` (`RequiresRecordatorios`, declarado) · `MailySoft/backend/apps/agenda/reminders.py:46-48` (donde debería aplicarse)
- **Qué dice la documentación:** `docs/01-analisis.md:190` lista `recordatorios` como módulo 2, con dependencia de `agenda`; `docs/01-analisis.md:236` afirma "planes, módulos y límites por clínica, con el backend como autoridad (91 vistas con guard de módulo)".
- **Qué hace el código:** `RequiresRecordatorios` no aparece en ninguna vista (búsqueda en todo `apps/`: solo su propia línea de declaración). `schedule_reminders_for_appointment()` decide únicamente con `config.reminders_enabled`, que es un interruptor de la clínica, no del plan; nunca consulta `Entitlements.tiene("recordatorios")` ni llama a `require_module()`.
- **Consecuencia concreta:** una clínica cuyo plan no incluye recordatorios los sigue programando y encolando en Celery. Hoy es inocuo porque el adaptador de WhatsApp solo escribe en el log (`docs/01-analisis.md:255-257`); el día que se conecte la API de WhatsApp Business, esa clínica genera **costo real de mensajes por una función que no pagó**.

### B-T-09 · Código muerto en la capa de permisos y de rutas
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/core/permissions.py:340` (`FinanceQuotePermission`) · `:449` (`FinanceStatementPermission`) · `:1022` (`PrescriptionFormatPermission._DOCTOR_ROLES`) · `MailySoft/backend/config/urls.py:36` (`# path("api/v1/", include("apps.core.urls"))`)
- **Qué dice la documentación:** nada. Hallazgo nuevo.
- **Qué hace el código:** `FinanceQuotePermission` está marcada *"DEPRECADO: usar QuotePermission en su lugar… Se mantiene para no romper endpoints que todavía no se migraron"*, pero **ninguna vista la usa**: la migración ya terminó. `FinanceStatementPermission` tampoco se usa en ninguna vista (la sustituyó `PatientStatementPermission`, según su propio docstring en `:513`). `_DOCTOR_ROLES` es un atributo de clase declarado y jamás leído (la policy usa un `frozenset` literal). La línea comentada de `config/urls.py` apunta a `apps/core/urls.py`, archivo que no existe.
- **Consecuencia concreta:** quien documente o modifique finanzas encuentra **dos** clases de permiso plausibles para cotizaciones y **dos** para el estado de cuenta, con matrices de roles distintas (`FinanceQuotePermission` incluye `finance`; `QuotePermission` no). Cablear la equivocada por error da acceso a finanzas a un módulo del que el cliente lo excluyó a propósito.

### B-T-10 · El rol `readonly` puede crear, editar y borrar notas
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/core/permissions.py:655-660` (`NotePermission.policy`, los cuatro métodos con `ALL_ROLES`)
- **Qué dice la documentación:** `docs/01-analisis.md:56` describe `readonly` como "Contador externo, auditor, socio. Lee finanzas y panel de retención. **No escribe nada**".
- **Qué hace el código:** `NotePermission` abre `GET/POST/PATCH/DELETE` a los 7 roles, incluido `readonly`, y delega la granularidad al service (`note_create` solo restringe el *scope* `role|all` a owner). El módulo hermano sí excluye a `readonly` de la escritura: `AgendaItemNotePermission` (`permissions.py:628-635`) le da GET pero no POST ni DELETE, con el comentario explícito *"READONLY puede ver el hilo pero NO escribir"*.
- **Consecuencia concreta:** el contador externo al que se le dio acceso `readonly` puede crear notas y tareas dentro de la clínica y borrarlas. Dos módulos de notas con criterios opuestos para el mismo rol es exactamente el tipo de inconsistencia que nadie descubre hasta una auditoría.

### B-T-11 · Dos vistas chequean el rol con strings literales, fuera del sistema de permisos
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/views.py:772-777` (`DoctorCredentialTenantListApi`) · `:798-803` (`DoctorCredentialValidationApi`)
- **Qué dice la documentación:** nada explícito; `docs/01-analisis.md:169` sí describe la bandeja de validación de credenciales como "de Owner/Admin".
- **Qué hace el código:** ambas declaran `permission_classes = [IsAuthenticated]` y luego, dentro del handler, comparan `request.active_role not in ("owner", "admin")` devolviendo 403 a mano. El comportamiento hoy es correcto, pero queda **invisible** para cualquiera que lea `apps/core/permissions.py` o `apps/clinica/permissions.py` buscando la matriz de roles, y los literales no se derivan de `TenantMembership.Role`.
- **Consecuencia concreta:** si mañana se renombra un rol o se añade "administrador de sucursal" como rol propio, la matriz declarativa se actualiza en un solo archivo y estas dos vistas se quedan con la regla vieja sin que ningún test de permisos lo note. La bandeja de credenciales del médico es justo lo que decide qué cédula se imprime en una receta.

### B-T-12 · Los selectores de membresía ignoran el borrado lógico
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/tenancy/selectors.py:162` (`membership_list`) y `:198` (`membership_get`) · contraste con `MailySoft/backend/apps/core/tenant_context.py:160` (`deleted_at__isnull=True`)
- **Qué dice la documentación:** `docs/01-analisis.md:299` afirma que el sistema usa "borrado lógico en lugar de físico" como práctica general.
- **Qué hace el código:** `TenantMembership` hereda de `BaseModel`, que **no** declara manager propio, así que `objects` es el manager estándar de Django y no excluye `deleted_at IS NOT NULL`. `membership_list`/`membership_get` filtran por tenant pero no por `deleted_at`; en cambio `resolve_membership_for_user` (la que da acceso) sí lo hace.
- **Consecuencia concreta:** el día que alguien implemente la baja de un miembro con `deleted_at` (que es la forma correcta según la convención del proyecto), esa persona **seguirá apareciendo en la lista de equipo de la clínica** —con su correo y su rol— aunque ya no pueda entrar. Lo mismo vale para el conteo del límite de usuarios (B-T-06).

### B-T-13 · `entitlements_for_tenant` no excluye suscripción ni ajustes borrados lógicamente
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/tenancy/entitlements.py:80-85`
- **Qué dice la documentación:** nada. Hallazgo nuevo.
- **Qué hace el código:** `TenantSubscription.objects.select_related("plan").filter(tenant=tenant).first()` y `TenantEntitlements.objects.filter(tenant=tenant).first()`. Ambos modelos heredan `BaseModel` (manager estándar) y ninguno de los dos filtros incluye `deleted_at__isnull=True`.
- **Consecuencia concreta:** si se da de baja lógica la suscripción de una clínica morosa —el gesto natural, dado que el resto del sistema borra en lógico— la clínica **conserva todos sus módulos**: `entitlements_for_tenant` sigue leyendo esa fila. La suspensión real hoy solo funciona por `Tenant.status = suspended`, y eso no está escrito en ninguna parte del código de entitlements.

### B-T-14 · `all_objects` se usa masivamente fuera del panel interno
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/core/models.py:51` (la regla) · usos verificados en `MailySoft/backend/apps/clinica/sucursal_scope.py:175`, `:184`, `:241`, `:260`, `:391`, `:417`, `:482` · `MailySoft/backend/apps/tenancy/selectors.py:64`, `:70`, `:78` · `MailySoft/backend/apps/tenancy/services.py:302` · `MailySoft/backend/apps/core/pdf/branding.py:61`
- **Qué dice la documentación:** `apps/core/models.py:51` es tajante: *"NUNCA usar `all_objects` en vistas o servicios sin justificación explícita"*. `docs/01-analisis.md:76` presenta `all_objects` como el mecanismo del **staff de plataforma**, dando a entender que es la excepción.
- **Qué hace el código:** una búsqueda en `apps/` devuelve 368 ocurrencias en 100 archivos (tests incluidos; conteo por búsqueda, no leí cada archivo). Fuera de `plataforma/` aparece en `clinica/services.py`, `clinica/selectors.py`, `personal/services.py`, `personal/selectors.py`, `recetas/services.py`, `recetas/selectors.py`, `recetas/views_public.py`, `expediente/services.py`, `notas/services.py`, `notas/selectors.py`, `audit/*` y `core/pdf/branding.py`. En los casos que leí la justificación es real y está escrita (funciones llamadas desde `MeApi`, que no resuelve thread-local de tenant, o desde Celery), y **todos** compensan con un `filter(tenant_id=…)` explícito.
- **Consecuencia concreta:** la excepción se volvió norma, y con ella la única barrera que queda es la disciplina de recordar el `filter(tenant_id=…)` en cada llamada — sin RLS detrás cuando no hay GUC (B-T-02). Un `all_objects.filter(id=…)` sin tenant, copiado de la línea de al lado, devuelve el registro de otra clínica: por ejemplo, `PrescriptionFormat.all_objects` en `core/pdf/branding.py:61` decide el color de marca de **todos** los PDFs; sin su `tenant=tenant` imprimiría la identidad visual de otra clínica en una receta.

### B-T-15 · CORS sin `CORS_ALLOW_HEADERS`: `X-Sucursal-Id` no está permitido en el preflight
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/config/settings/base.py:488-489` y `MailySoft/backend/config/settings/production.py:90-91` (no se declara `CORS_ALLOW_HEADERS` en ninguno) · `MailySoft/backend/apps/clinica/sucursal_scope.py:113` (el header) · `MailySoft/web-soft/vite.config.ts:24` (proxy de dev) · `MailySoft/backend/config/urls.py:89` (SPA same-origin en prod)
- **Qué dice la documentación:** nada. Hallazgo nuevo.
- **Qué hace el código:** `django-cors-headers` sin `CORS_ALLOW_HEADERS` explícito usa su lista por defecto, que **no incluye** `x-sucursal-id`. Hoy no rompe nada porque no hay peticiones cross-origin reales: en desarrollo el frontend va por el proxy de Vite (`/api` → `localhost:8000`, mismo origen para el navegador) y en producción el propio Django sirve el SPA. Pero `CORS_ALLOWED_ORIGINS` + `CORS_ALLOW_CREDENTIALS=True` están configurados como si sí las hubiera.
- **Consecuencia concreta:** el día que el frontend se despliegue en un origen propio (Vercel, Netlify, un subdominio distinto), **toda** petición que lleve sucursal activa —agenda, finanzas, equipo, notas— fallará en el preflight, y el síntoma será "la clínica con dos sedes no carga nada al seleccionar una sede", con un error de CORS que no menciona sucursales.

### B-T-16 · `GET /api/v1/miembros/<id>/` no existe, pero la política y los docstrings lo dan por hecho
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/tenancy/views.py:188-202` (`MemberDetailApi`, solo implementa `patch`) · `MailySoft/backend/apps/core/permissions.py:224` (`MemberPermission.policy["GET"]`) · `MailySoft/backend/apps/tenancy/views.py:70-90` (docstring de `_member_get_or_404`)
- **Qué dice la documentación:** nada externo. El propio código habla repetidamente de "el detalle/avatar de un miembro" (`views.py:14-17`, `:73-76`) como si fuera un endpoint existente.
- **Qué hace el código:** la ruta `miembros/<uuid:membership_id>/` (`apps/tenancy/urls.py:13`) está mapeada a una vista que solo define `patch`, así que un GET devuelve **405 Method Not Allowed**. La entrada `GET` de `MemberPermission` solo sirve para el listado.
- **Consecuencia concreta:** el frontend que intente abrir la ficha de un miembro por su id recibe 405 y no 200 ni 404, y quien lea la matriz de permisos concluye —razonablemente— que el detalle existe y está permitido para owner y admin. Es una promesa de contrato que el código no cumple.

### B-T-17 · El docstring de `CookieTokenRefreshView` contradice la configuración real de rotación de tokens
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/authn/views.py:248-250` y `:272-276` · contra `MailySoft/backend/config/settings/base.py:266-267`
- **Qué dice la documentación:** el propio código: *"Si `ROTATE_REFRESH_TOKENS=True` (activo en base.py), el nuevo refresh se deposita en la cookie"* y *"ROTATE_REFRESH_TOKENS=True en base.py"*.
- **Qué hace el código:** `base.py` tiene `ROTATE_REFRESH_TOKENS: False` y `BLACKLIST_AFTER_ROTATION: False`, con una explicación larga de por qué se apagó (sesiones que se cerraban solas al recargar). El `response.data.pop("refresh", None)` de la vista simplemente nunca encuentra nada. No hay bug funcional; hay dos afirmaciones opuestas en el mismo repo.
- **Consecuencia concreta:** quien audite la seguridad de la sesión leerá en la vista que el refresh rota en cada renovación —una propiedad de seguridad que **no existe**— y dará por cubierto el robo de cookie de refresh. La cookie vive 7 días sin rotar y solo el logout la invalida.

### B-T-18 · El docstring de `/me/` dice que el administrador ve todas las sucursales
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/authn/serializers.py:92-93` · contra `MailySoft/backend/apps/clinica/sucursal_scope.py:181-197`
- **Qué dice la documentación:** el contrato interno de `/me/` afirma: *"Owner/admin ven TODAS las sucursales activas del tenant; cualquier otro rol solo las suyas (MembershipSucursal)"*. `docs/01-analisis.md:66` dice lo contrario y coincide con el código: "El `owner` ve todas las sedes; todos los demás, **incluido `admin`**, solo las que tienen asignadas".
- **Qué hace el código:** `allowed_sucursales` devuelve todas las sedes **solo** si `membership.role == OWNER`; para cualquier otro rol —admin incluido— devuelve las asignadas vía `MembershipSucursal`, o la sede `is_default` como fallback anti-lockout, o vacío. Es la corrección deliberada que habilitó el rol "administrador de sucursal".
- **Consecuencia concreta:** un desarrollador de frontend que construya el selector de sedes leyendo ese docstring asumirá que un admin siempre trae la lista completa y tratará una lista de un solo elemento como un error o como "aún no cargó". En una clínica con dos sedes, el administrador de Norte vería el selector roto en vez de ver correctamente su única sede.

### B-T-19 · Mensaje de límite de plan con un condicional que no hace nada
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/core/entitlement_guards.py:141-143`
- **Qué dice la documentación:** nada. Hallazgo nuevo.
- **Qué hace el código:** `f"…y ya {'hay' if actual == 1 else 'hay'} {actual}."` — las dos ramas del condicional son idénticas. Se pretendía singular/plural y quedó a medias; el mensaje además dice "ya hay 3 sucursales" en lugar de "sucursales" correctamente flexionado en el caso 1.
- **Consecuencia concreta:** ninguna de seguridad. Vale como señal: es el mensaje que ve un dueño al chocar con el tope de su plan —el momento exacto en el que se le está pidiendo que pague más— y nadie lo leyó nunca en producción.

### B-T-20 · `Tenant.timezone` se guarda pero no se usa para fechar documentos ni respuestas
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/tenancy/models.py:64-68` (el campo) · `MailySoft/backend/config/settings/base.py:433` (`TIME_ZONE = "America/Mexico_City"`) · `MailySoft/backend/apps/recetas/pdf.py:384-385` · `MailySoft/backend/apps/expediente/pdf.py:230` · `MailySoft/backend/apps/pacientes/selectors.py:245` · uso correcto aislado en `MailySoft/backend/apps/agenda/tasks.py:150`
- **Qué dice la documentación:** el `help_text` del campo dice "Zona horaria del tenant para localizar fechas". `docs/01-analisis.md` no menciona el tema.
- **Qué hace el código:** no existe ninguna llamada a `timezone.activate()` en todo `apps/`, así que el huso activo es siempre el global (`America/Mexico_City`) y `timezone.localtime()` convierte a **CDMX**, no al huso de la clínica. `apps/pacientes/selectors.py:245` usa explícitamente `settings.TIME_ZONE` para cortar fechas. El único lugar que respeta `Tenant.timezone` es la tarea de recordatorios (`agenda/tasks.py:150`). Lo mismo aplica a la serialización de DRF: las respuestas salen con desplazamiento de CDMX.
- **Consecuencia concreta:** una clínica en Tijuana (UTC-8, dos horas menos que CDMX) emite una receta a las 9:00 de su mañana y el PDF —documento clínico con valor legal— **imprime "11:00"**. El corte del cierre diario de caja y los cortes de "hoy" en los reportes tienen el mismo desfase de dos horas. El campo existe y da la falsa impresión de que el problema está resuelto.
## Pacientes, notas y avisos

> Brechas encontradas al extraer el contrato de `apps/pacientes` y `apps/notas` el 2026-08-12.
> **No se corrigió ni una línea de código**: esto es el inventario, no el arreglo. Cada entrada cita
> `archivo:línea` relativo a la raíz del repo. `MailySoft/docs/01-analisis.md` es la documentación de
> referencia; cuando dice "nada", es que el análisis no habla del tema.
>
> Severidades: **P0** fuga entre clínicas o salto de autenticación · **P1** exposición de datos,
> pérdida de datos o regla de negocio evadible dentro de la clínica · **P2** deuda, inconsistencia de
> contrato o código muerto.
>
> Resumen: 22 brechas — **0 P0, 5 P1, 17 P2**. Ninguna rompe el aislamiento entre clínicas: las dos
> barreras de §1.1 se sostienen en las dos apps.

---

### B-PAC-01 · El directorio de pacientes entrega datos sensibles y de salud a finanzas y solo-lectura
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/core/permissions.py:155` (`"GET": ALL_ROLES`) +
  `MailySoft/backend/apps/pacientes/serializers.py:97-144` (lista de campos) +
  `MailySoft/backend/apps/pacientes/views.py:184` (el listado usa el mismo serializer que el detalle)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:162` dice que `ContactosPage` la ven
  "Todos". Pero `MailySoft/docs/01-analisis.md:282-285` afirma: *"Recepción y Finanzas no leen
  expediente ni recetas — es una decisión explícita"*, y `:276-280` lista como dato sensible
  "nombre, fecha de nacimiento, sexo, teléfono y correo del paciente".
- **Qué hace el código:** `PatientPermission.GET = ALL_ROLES`, y el único serializer de salida
  devuelve **el objeto completo** en el listado: CURP, domicilio completo, lugar de nacimiento,
  estado civil, escolaridad, ocupación, **religión**, **tipo de sangre**, **`is_deceased` /
  `deceased_at`**, `notes` (texto libre interno) y `custom_consultation_fee`. El único campo filtrado
  por rol es `last_reason` (`serializers.py:56-78`). No existe un serializer reducido para listas.
- **Consecuencia concreta:** en una clínica con dos sedes, la persona de finanzas de Centro —cuyo
  trabajo es cobrar— pagina el directorio completo de las dos sedes y se lleva CURP, domicilio,
  religión y tipo de sangre de cada paciente, incluidos los que nunca pisaron su sede. Con un usuario
  `readonly` (pensado para auditoría o para un socio) pasa lo mismo. Religión y tipo de sangre son
  datos sensibles bajo LFPDPPP; el proyecto se declara alineado a esa ley
  (`01-analisis.md:291-295`).

### B-PAC-02 · La foto del paciente se sirve desde una URL pública, sin firma y sin prefijo de tenant
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/core/files.py:165-167` (`patient_avatar_path` →
  `avatars/pacientes/<uuid>.<ext>`) + `MailySoft/backend/config/settings/base.py:348-354`
  (`STORAGES["default"]` por variable de entorno) +
  `MailySoft/backend/config/settings/production.py:100-102` (Cloudinary como backend del piloto) +
  `MailySoft/backend/apps/pacientes/serializers.py:40` (el campo se serializa como URL)
- **Qué dice la documentación:** `01-analisis.md:297-299` presume "validación real de imágenes
  subidas" —cierto— pero no dice nada de cómo se **entregan**. `01-analisis.md:306` solo menciona
  "Cloudinary para archivos".
- **Qué hace el código:** el nombre del archivo se aleatoriza, pero la ruta **no lleva `tenant_id`**,
  a diferencia de las imágenes clínicas, que sí van a `evoluciones/<tenant_id>/`
  (`core/files.py:175-200`). Con `MediaCloudinaryStorage` la URL resultante es de entrega pública del
  CDN: nada la firma, nada la caduca y nada comprueba el JWT. `AWS_DEFAULT_ACL="private"`
  (`base.py:365`) solo aplicaría al backend S3, que no está en uso.
  **NO VERIFICADO**: el valor real de `DJANGO_DEFAULT_FILE_STORAGE` en Railway — no tengo acceso al
  entorno. Si en producción fuera `FileSystemStorage`, el problema cambia de forma (Django no sirve
  `/media/` fuera de `DEBUG`, `config/urls.py:60-77`) pero no desaparece.
- **Consecuencia concreta:** la cara de un paciente queda accesible para cualquiera que tenga el
  enlace —un historial de navegador, un enlace copiado a WhatsApp, un backup de caché—, sin sesión,
  sin rol y sin quedar registrada en la bitácora. Y como las fotos de todas las clínicas comparten el
  prefijo `avatars/pacientes/`, no se puede escribir una política de bucket ni de IAM por clínica: no
  hay forma de conceder "solo los archivos de esta clínica" a nadie.

### B-PAC-03 · Ningún endpoint de pacientes se acota por sucursal, y no está decidido si debería
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pacientes/models.py:66-329` (el modelo `Patient` **no** tiene
  campo `sucursal`) + `MailySoft/backend/apps/pacientes/views.py` completo (no importa
  `sucursal_scope`, verificado por búsqueda en toda la app)
- **Qué dice la documentación:** nada. `01-analisis.md:162` describe la pantalla de contactos sin
  mencionar sedes. La regla general de la capa transversal sí existe: *"listados expuestos a roles
  acotados por sede usan `sucursal_scope_ids`"*
  (`MailySoft/backend/apps/clinica/sucursal_scope.py:92-94`, §1.5.4).
- **Qué hace el código:** el listado es `Patient.objects.filter(is_active=True)`
  (`apps/pacientes/selectors.py:116`) sin ninguna dimensión de sede, y el detalle es
  `Patient.objects.get(id=...)` (`selectors.py:44`). Agenda, personal, finanzas y notas sí acotan.
- **Consecuencia concreta:** en una clínica con sede Centro y sede Norte, la recepcionista de Norte
  —asignada solo a Norte por `MembershipSucursal`— ve, edita y desactiva el expediente de cualquier
  paciente de Centro. Puede ser lo correcto (el paciente es de la clínica, no de la sede) o no serlo;
  lo que no puede ser es que no esté decidido. Mientras no se decida, el módulo es la excepción no
  escrita a una regla escrita, y el siguiente que agregue un campo a `Patient` no sabrá qué hacer.

### B-PAC-04 · La unicidad de CURP ignora los borrados lógicos y el error resultante miente
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pacientes/services.py:155-162` (chequeo en app, con
  `deleted_at__isnull=True`) + `MailySoft/backend/apps/pacientes/models.py:287-291` (constraint en BD,
  **sin** condición sobre `deleted_at`) + `MailySoft/backend/apps/pacientes/services.py:180-187`
  (traducción del `IntegrityError`)
- **Qué dice la documentación:** nada. `01-analisis.md:268` solo declara que la detección de
  duplicados no está construida.
- **Qué hace el código:** el service comprueba en Python que no exista otro paciente **no borrado**
  con esa CURP; la constraint `patient_curp_uniq` de Postgres no distingue borrados. Si existiera un
  paciente soft-deleted con esa CURP, el chequeo de aplicación pasa y la base rechaza el `INSERT`; el
  `except IntegrityError` traduce **cualquier** violación a *"Error de concurrencia al generar el
  número de expediente. Por favor, intente de nuevo."*. El mismo desfase está en el update
  (`services.py:329-336`).
- **Consecuencia concreta:** hoy es latente, porque ningún endpoint escribe `deleted_at` en
  `Patient`. Pero el día que soporte borre lógicamente un expediente duplicado desde `/admin/` y
  recepción intente volver a capturar a ese paciente con su CURP, recibirá un mensaje que dice
  "intente de nuevo" ante un error que **nunca** se resolverá reintentando. Se perderán minutos
  buscando un problema de concurrencia inexistente.

### B-PAC-05 · Un paciente desactivado no se puede reactivar, y sigue siendo editable y "escribible" por id
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/pacientes/services.py:530` (`is_active=False`) +
  `MailySoft/backend/apps/pacientes/services.py:277-279` (`is_active` es campo inmutable en el PATCH)
  + `MailySoft/backend/apps/pacientes/selectors.py:44` (`patient_get` **no** filtra `is_active`) +
  `MailySoft/backend/apps/pacientes/urls.py:17-28` (no hay ruta de reactivación)
- **Qué dice la documentación:** `01-analisis.md:162` dice que en Contactos se puede dar de "baja".
  No dice que la baja sea irreversible. `01-analisis.md:299` presume "borrado lógico en lugar de
  físico", que es cierto pero incompleto.
- **Qué hace el código:** `DELETE /pacientes/<id>/` pone `is_active=False` y responde 204. El campo es
  inmutable en el PATCH por diseño (FIX-B3) y no existe ningún otro endpoint que lo toque. A la vez,
  `patient_get` —que importan **también** una docena de vistas de `apps/expediente`, `apps/recetas`,
  `apps/agenda` y `apps/finanzas`— no filtra por `is_active`: el paciente desactivado desaparece del
  listado y de ningún otro lado.
- **Consecuencia concreta:** dos daños distintos. (1) Recepción da de baja por error a un paciente
  duplicado y elige el expediente equivocado: no hay forma de deshacerlo desde la aplicación, hay que
  entrar al admin de Django con una cuenta de plataforma. (2) Un paciente "dado de baja" sigue
  aceptando notas de evolución y recetas si alguien conserva el enlace del expediente — y las notas
  clínicas son inmutables por regla dura del proyecto, así que ese registro ya no se puede corregir.

### B-PAC-06 · Leer el directorio completo de pacientes no deja ningún rastro en la bitácora
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/pacientes/views.py:413-421` (el detalle **sí** audita
  `PATIENT_READ`) vs `MailySoft/backend/apps/pacientes/views.py:165-193` (el listado **no** audita
  nada)
- **Qué dice la documentación:** `01-analisis.md:287-289`: *"¿Requiere bitácora de auditoría? Sí, y
  existe: quién, qué acción, sobre qué recurso…"*. `CLAUDE.md` regla dura 5: *"Las acciones sensibles
  se registran en la bitácora"*. El propio código declara la intención en `views.py:410-412`:
  *"NOM-024: registrar acceso al expediente individual del paciente"*.
- **Qué hace el código:** se audita la apertura de **una** ficha. No se audita el listado, que
  devuelve el objeto completo de 25 pacientes por página, ni la búsqueda, que permite localizar a una
  persona concreta por teléfono o apellido.
- **Consecuencia concreta:** un usuario que quiera llevarse el padrón de pacientes de la clínica solo
  tiene que paginar `/api/v1/pacientes/` y no aparece **nada** en la bitácora; el que abre una ficha
  para atender a su paciente sí queda registrado. La evidencia que se guardaría ante una queja de la
  autoridad registra al que trabaja y no al que exfiltra. Con el throttle de 300 req/min (§1.7.3) se
  descarga un padrón de 7.500 pacientes por minuto.

### B-PAC-07 · `_VALID_SEGMENTS` es código muerto
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pacientes/views.py:102-104`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** define un `frozenset` con los ocho segmentos válidos que **nadie lee**: la
  validación real la hace el `ChoiceField` del `FilterSerializer` (`views.py:118-131`), y el selector
  trata cualquier valor desconocido como `"all"` (`selectors.py:223-225`).
- **Consecuencia concreta:** hay dos listas de segmentos válidos en el mismo archivo. Quien agregue el
  segmento "cumpleaños del mes" y actualice la que no toca creerá que lo agregó y el filtro se
  comportará como `all`, devolviendo todos los pacientes en vez de ninguno — un fallo silencioso, que
  es el peor tipo.

### B-PAC-08 · `DELETE /pacientes/<id>/avatar/` no tiene consumidor y exige un rol más alto que subirla
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pacientes/views.py:497-505` (el endpoint) +
  `MailySoft/backend/apps/core/permissions.py:156` (POST = O A D N R) vs `:158` (DELETE = O A) +
  `MailySoft/web-soft/src/api/pacientes.ts:93-106` (solo hay cliente para el POST)
- **Qué dice la documentación:** `01-analisis.md:162` menciona "avatar" entre lo que se puede hacer en
  Contactos, sin distinguir subir de quitar.
- **Qué hace el código:** `PatientAvatarApi` usa la misma clase de permiso para los dos métodos, y
  `PatientPermission` mapea `DELETE` a owner+admin. Resultado: un médico puede **reemplazar** la foto
  de un paciente cuantas veces quiera, pero no puede **quitarla**. Y el endpoint que la quita no lo
  llama nadie desde el frontend.
- **Consecuencia concreta:** si un paciente ejerce su derecho de cancelación sobre su fotografía, el
  médico que lo atiende no puede borrarla: tiene que pedírselo al dueño, que tampoco tiene botón —
  hay que llamar a la API a mano. Mientras tanto el endpoint sigue expuesto, es superficie de ataque
  sin uso, y nadie lo prueba porque nadie lo ve.

### B-PAC-09 · Un POST de clasificación puede escribir en el catálogo de etiquetas de la clínica
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pacientes/services.py:462-472`
  (`_system_category` → `seed_system_patient_categories`)
- **Qué dice la documentación:** `01-analisis.md:93` dice que las etiquetas de sistema se siembran al
  dar de alta la clínica. No menciona ninguna segunda siembra.
- **Qué hace el código:** si al marcar un paciente como Favorito no encuentra la etiqueta de sistema,
  la **crea al vuelo** llamando a un service de otra app (`apps/clinica/services.py:490`). Es una
  defensa razonable, pero convierte una acción de clasificación en una escritura sobre el catálogo, y
  lo hace **fuera** de cualquier transacción explícita y **sin auditar** esa creación: el
  `audit_record` posterior (`services.py:493`) registra `PATIENT_UPDATE`, no la creación de la
  etiqueta.
- **Consecuencia concreta:** si la siembra del alta de clínica fallara —o si alguien borrara la
  etiqueta desde el admin—, el catálogo se repara solo la primera vez que alguien pulse la estrella,
  sin que nadie se entere de que estuvo roto. El día que haya que explicar por qué apareció una
  categoría nueva en una clínica, la bitácora no tendrá la respuesta.

### B-PAC-10 · Dos sistemas de categorización conviven, y los ids inválidos se descartan en silencio
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pacientes/models.py:257-265` (`category`, texto libre legacy) +
  `:266-275` (`categories`, M2M) + `MailySoft/backend/apps/pacientes/views.py:348-352` (el PATCH
  acepta **los dos**) + `MailySoft/backend/apps/pacientes/services.py:363-370` (filtro silencioso)
- **Qué dice la documentación:** nada sobre el campo legacy. `01-analisis.md:162` habla solo de
  "etiquetas".
- **Qué hace el código:** el PATCH acepta `category` (string de 60, sin validar contra ningún
  catálogo) y `category_ids` (lista de UUID). Al aplicar `category_ids`, filtra por
  `kind=CUSTOM, is_active=True, deleted_at IS NULL` y **asigna lo que sobrevive**: un UUID inexistente,
  inactivo o de una etiqueta de sistema simplemente desaparece sin error. El serializer de salida
  expone ambos campos.
- **Consecuencia concreta:** el frontend manda tres etiquetas, el backend responde 200 y guarda dos.
  Nadie se entera hasta que alguien nota que el filtro por etiqueta no encuentra al paciente. Y el
  campo `category` sigue viajando en cada respuesta, así que hay dos lugares donde buscar "cómo está
  clasificado este paciente" y ninguno es autoritativo.

### B-PAC-11 · El comentario del selector niega índices que sí existen, y los trigramas no cubren las dos primeras teclas
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pacientes/selectors.py:120-122`
  (`TODO(perf): … considerar índice pg_trgm (GIN) … Ver: CREATE EXTENSION IF NOT EXISTS pg_trgm`) vs
  `MailySoft/backend/apps/pacientes/models.py:304-328` (los cinco índices GIN **ya existen** desde la
  migración `MailySoft/backend/apps/pacientes/migrations/0012_patient_patient_first_name_trgm_and_more.py`)
- **Qué dice la documentación:** nada. La contradicción es interna al código.
- **Qué hace el código:** el `TODO` dice que el índice haría falta "cuando el volumen supere ~50k";
  el modelo ya lo creó. Además, el comentario de `models.py:299-303` afirma que los índices evitan
  "caer en seq scan O(n) por cada tecleo" — **`pg_trgm` no puede usar el índice con patrones de menos
  de 3 caracteres**, así que las dos primeras teclas de cada búsqueda siguen haciendo un recorrido
  secuencial con cinco `ILIKE` unidos por `OR`. El endpoint no impone longitud mínima al parámetro
  `search` (`views.py:117`).
- **Consecuencia concreta:** hoy nada, con clínicas pequeñas. Pero quien lea el `TODO` creerá que
  falta crear un índice que ya existe y lo creará otra vez con otro nombre, pagando el doble en cada
  escritura; y quien lea el comentario del modelo creerá que la búsqueda incremental está resuelta
  cuando el caso más frecuente —teclear "an" para buscar a Ana— es justo el que no usa índice.

### B-PAC-12 · El código de error de un método no ruteado depende del rol del que pregunta
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/core/permissions.py:133-135` (método sin clave en `policy` →
  denegado) + `MailySoft/backend/apps/core/permissions.py:154-159` (`PatientPermission` no declara
  `PUT`) + `MailySoft/backend/apps/pacientes/views.py:275-462` (`PatientDetailApi` no implementa
  `put`)
- **Qué dice la documentación:** §1.7.2 del contrato transversal fija que **405** es "método no
  ruteado en la vista" y **403** es "rol insuficiente".
- **Qué hace el código:** DRF corre `check_permissions` antes de resolver el handler. `PUT
  /pacientes/<id>/` devuelve **403 para los siete roles** (no hay clave `"PUT"`), y `DELETE
  /pacientes/` devuelve **403** para doctor, enfermería, recepción, finanzas y solo-lectura pero
  **405** para owner y admin, que sí pasan el permiso y se topan con la ausencia de handler.
- **Consecuencia concreta:** el mismo request devuelve dos códigos distintos según quién lo mande, y
  ninguno de los dos significa lo que el contrato dice que significa. Un cliente que reintente ante
  403 ("cambio de rol y funciona") perseguirá un fantasma, y las pruebas de contrato que se escriban
  contra estos endpoints tendrán que aceptar dos respuestas para el mismo caso.

---

### B-NOT-01 · Un PATCH de `scope` convierte una nota personal en un aviso a TODAS las sedes
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/notas/services.py:343-345` (una nota personal nace con
  `sucursal=None`) + `MailySoft/backend/apps/notas/services.py:493` (`scope` es campo editable) +
  `MailySoft/backend/apps/notas/services.py:81-101` (`sucursal` e `is_important` son inmutables, así
  que **no se recalculan**) + `MailySoft/backend/apps/notas/views.py:224` (el serializer del PATCH
  acepta `scope`)
- **Qué dice la documentación:** el propio código promete lo contrario. `apps/notas/models.py:20-23`:
  *"scope=all lo pueden crear el owner (cualquier sede, o todas) o un admin (forzado a SU sede)"*. Y
  `apps/notas/services.py:518-521`: *"un admin que convierte su propio aviso a scope=all conserva la
  sede con la que fue creado (forzada a la suya en note_create)"*. `01-analisis.md:165` solo dice que
  en Notas se puede "dirigir un aviso a un rol".
- **Qué hace el código:** el comentario es cierto **solo** si la nota nació como aviso. Una nota
  creada con `scope=personal` tiene `sucursal=NULL`, y en este modelo `NULL` significa **"todas las
  sedes"** (`models.py:109-116`). Al hacer `PATCH {"scope": "all"}`, `note_update` valida únicamente
  el rol (`services.py:522-530`) y guarda; la sede sigue en `NULL` porque es campo inmutable. Lo
  mismo con `scope=role` para doctor, enfermería y recepción (`services.py:531-535`).
- **Consecuencia concreta:** el administrador de la sede Norte —al que `note_create` obliga siempre a
  publicar en Norte— crea una nota personal ("Cerramos a las 3 el viernes"), le hace PATCH a
  `scope=all` y el aviso aparece en el tablero de Centro y de cualquier otra sede, incluida la del
  dueño. Dos peticiones, ninguna prohibida, y el confinamiento por sede que se construyó el
  2026-07-16 queda anulado. Con `scope=role` lo puede hacer también un médico o una recepcionista.

### B-NOT-02 · El cuerpo de la nota se copia literal a la fila de notificación de cada destinatario
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/notas/services.py:418-419` (`title=title …, body=body[:200]`) y
  `:433-435` (ídem para `scope=all`) + `MailySoft/backend/apps/notificaciones/services.py:85-98`
  (una fila `Notification` por destinatario) +
  `MailySoft/backend/apps/notificaciones/recipients.py:67-84` (`all_tenant_users` incluye `finance` y
  `readonly`)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:340-342`, riesgo 4: *"PII y texto
  clínico en el título y cuerpo de las notificaciones. El aviso de una nota de equipo incluye el
  nombre del paciente y un extracto de la nota. Hay que decidirlo y documentarlo, no dejarlo sin
  decidir."* Aquí queda confirmado con línea, y sigue sin decidirse.
- **Qué hace el código:** el título íntegro y los primeros 200 caracteres del cuerpo se duplican en
  una fila por destinatario, con `target_type=NOTE` y el UUID de la nota. Nada filtra ni redacta el
  texto. El borrado de la nota (`services.py:635-636`) **no** borra esas copias.
- **Consecuencia concreta:** un médico escribe un aviso a enfermería que dice "Preparar a la señora
  López para curación de la herida quirúrgica"; ese texto queda copiado en la tabla de notificaciones
  de cada enfermera. Si además el aviso es `scope=all`, la copia llega también a finanzas y a
  solo-lectura, que por decisión explícita no leen expediente. Y si el autor borra la nota
  arrepentido, las copias siguen ahí.

### B-NOT-03 · La bitácora guarda el contenido de la nota y el correo del autor
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/notas/services.py:384`, `:563`, `:607`, `:645`
  (`resource_repr=str(note)`) + `MailySoft/backend/apps/notas/models.py:149-153` (`__str__` =
  `[scope] título-o-40-caracteres-del-cuerpo — email del autor`)
- **Qué dice la documentación:** `CLAUDE.md` del repo, regla dura 5: *"Las acciones sensibles se
  registran en la bitácora (`audit_record`) con **un identificador no-PII del recurso**"*.
  `01-analisis.md:299` presume "minimización de PII en la bitácora".
- **Qué hace el código:** las cuatro llamadas a `audit_record` de la app pasan la representación
  textual del objeto, que incluye contenido y correo. La app de pacientes hace exactamente lo
  contrario y lo deja escrito en cada llamada: `resource_repr=patient.record_number` con el comentario
  *"identificador no-PII (minimización LFPDPPP)"* (`apps/pacientes/services.py:195`, `:263`, `:385`,
  `:408`, `:426`, `:539`).
- **Consecuencia concreta:** la bitácora —la tabla que se entregaría como evidencia ante una
  auditoría y que se exporta desde el portal interno de Maily (`AuditoriaPage`, cross-tenant)—
  acumula fragmentos del contenido de las notas de todas las clínicas. Si una nota menciona a un
  paciente por su nombre, ese nombre queda en la bitácora, que es precisamente el sitio donde el
  proyecto se comprometió a no ponerlo. Y `AuditLog` no tiene campo `sucursal` (§1.5.5), así que la
  compensación por sede tampoco aplica.

### B-NOT-04 · Con alcance total, cualquier nota es alcanzable por id y el rechazo es 400, no 404
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/notas/selectors.py:71-86` (`note_get` no filtra nada si
  `sucursal_ids is None`) + `MailySoft/backend/apps/clinica/sucursal_scope.py:487-500` (alcance total
  = owner, "admin de negocio", o tenant sin sucursales) +
  `MailySoft/backend/apps/notas/services.py:482-483` (rechazo con `ValidationError` → **400**)
- **Qué dice la documentación:** `apps/notas/views.py:26-29` promete el criterio contrario: *"si no la
  veo, no la puedo tocar (404, no revela existencia en otra sede)"*. §1.7.2 del contrato transversal
  fija 404 para "recurso de otro tenant **o fuera de la sede permitida**".
- **Qué hace el código:** el filtro de alcance solo se aplica cuando `sucursal_ids` **no** es `None`.
  Con alcance total —que en una clínica de una sola sede es **todo el mundo**, porque las
  asignaciones cubren todas las sedes— `note_get` devuelve cualquier nota del tenant por id,
  incluidas las notas personales de otros usuarios; después `_can_mutate` (`services.py:150`)
  rechaza con 400 "No tienes permiso para editar esta nota."
- **Consecuencia concreta:** en la clínica típica de una sola sede (planes Básico y Pro tienen
  `max_sucursales=1`), la diferencia entre "esa nota no existe" y "esa nota existe y no es tuya" es
  observable por cualquier recepcionista que pruebe UUIDs. El impacto práctico es bajo —los UUID v4
  no se adivinan—, pero el contrato promete 404 y entrega 400, y esa promesa es la que otros módulos
  copian.

### B-NOT-05 · La vista documenta un filtro `scope` que no existe
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/notas/views.py:132` (docstring: *"scope: str — filtrar por scope
  (aún no en selector; se aplica en query param)"*) vs `views.py:145-147` (el `_FilterSerializer` solo
  declara `is_task` y `done`) y `apps/notas/selectors.py:183-187` (el selector solo aplica esos dos)
- **Qué dice la documentación:** nada en `01-analisis.md`. La contradicción es interna al código.
- **Qué hace el código:** un `?scope=all` en la query se **ignora en silencio**: DRF no rechaza
  parámetros desconocidos y el listado devuelve todo lo visible.
- **Consecuencia concreta:** el frontend que quiera una pestaña "solo avisos" creerá que el parámetro
  existe porque el docstring lo anuncia, lo mandará, verá notas personales mezcladas y buscará el bug
  en su código. Cuesta media hora la primera vez y se repite con cada persona nueva.

### B-NOT-06 · `/notas/recordatorios/` exige dos parámetros que el cliente declara opcionales
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/notas/views.py:347-352` (`date_from` y `date_to` sin
  `required=False` → obligatorios) vs `MailySoft/web-soft/src/api/notas.ts:37-42`
  (`params: { date_from?: string; date_to?: string } = {}`)
- **Qué dice la documentación:** nada. `01-analisis.md:150` solo menciona "una luz de recordatorios
  vencidos".
- **Qué hace el código:** una llamada sin rango devuelve **400** con forma de serializer
  (`{"date_from": ["Este campo es requerido."], …}`), no una lista vacía ni un rango por defecto.
- **Consecuencia concreta:** el widget de recordatorios de la barra lateral de agenda falla con 400 en
  cuanto alguien lo invoque sin rango —por ejemplo, al montar el componente antes de que el
  calendario resuelva sus fechas—. **NO VERIFICADO**: si hoy ocurre en producción; no revisé los
  componentes de `web-soft/src/`, solo el cliente HTTP.

### B-NOT-07 · Dos helpers dicen usar `all_objects` y usan `objects`
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/notas/selectors.py:92` (*"Usa all_objects para ser seguro fuera
  de contexto HTTP"*) vs `:103` (`TenantMembership.objects.get(...)`) — y el mismo par en
  `MailySoft/backend/apps/notas/services.py:119` vs `:122`
- **Qué dice la documentación:** §1.1.6 del contrato transversal deja claro que
  `tenancy_memberships` hereda `BaseModel`, **no** `TenantAwareModel`, y que su aislamiento es un
  `filter(tenant=...)` explícito.
- **Qué hace el código:** funcionalmente es correcto —para `TenantMembership`, `objects` **es** el
  manager plano de Django, y ambos helpers filtran `tenant=tenant` explícitamente—, pero el
  comentario describe un mecanismo que no está ahí.
- **Consecuencia concreta:** el siguiente que copie este patrón para un modelo que **sí** sea
  `TenantAwareModel` copiará también el comentario y creerá que `objects` no filtra por tenant, o al
  revés: que `all_objects` filtra. En una app tenant-aware ese malentendido produce una fuga o un
  listado vacío que nadie entiende. Es el tipo de comentario que envejece mal precisamente porque
  suena autoritativo.

### B-NOT-08 · Borrar un usuario borra físicamente todos sus avisos, incluidos los de la clínica
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/notas/models.py:68-73` (`author` FK con
  `on_delete=models.CASCADE`), frente a `MailySoft/backend/apps/core/models.py:63-64`
  (`created_by` con `SET_NULL` y la razón escrita: FIX-7)
- **Qué dice la documentación:** `01-analisis.md:299` presume "borrado lógico en lugar de físico".
  `apps/notas/models.py:27` lo repite: *"Borrado: soft-delete (deleted_at = now), nunca DELETE real"*
  — cierto para el endpoint, falso para la cascada.
- **Qué hace el código:** `Note` tiene los dos FK a usuario: `created_by` (`SET_NULL`, heredado) y
  `author` (`CASCADE`, propio). El segundo gana: al borrar la fila del usuario, Postgres borra sus
  notas, incluidos los avisos `scope=all` que el resto de la clínica todavía está leyendo. Hoy no se
  alcanza desde la API —la gestión de miembros bloquea la cuenta, no la borra (§1.9)—, solo desde
  `/admin/` con una cuenta superuser o desde la consola.
- **Consecuencia concreta:** un médico que trabaja en dos clínicas se va y alguien decide "limpiar" su
  usuario desde el admin: desaparecen los avisos que dejó en **las dos** clínicas, sin registro de
  borrado y sin posibilidad de recuperarlos, mientras que el resto de su historial (pacientes,
  recetas) sobrevive con autor nulo. El sistema queda contando dos historias distintas sobre la misma
  persona.

### B-NOT-09 · `NoteAdmin` no restringe audiencia y permite buscar dentro del cuerpo de las notas
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/notas/admin.py:8-13` (registro sin ningún
  `has_view_permission`, con `search_fields = ["title", "body"]`), frente a
  `MailySoft/backend/apps/pacientes/admin.py:116-142` (cuatro overrides que exigen
  `is_platform_staff` o superuser, y borrado solo para superuser)
- **Qué dice la documentación:** nada. `apps/pacientes/admin.py:4-14` sí deja escrita la política:
  *"herramienta EXCLUSIVA del equipo interno… No debe ser accesible a staff de clínica"*.
- **Qué hace el código:** `NoteAdmin` hereda el comportamiento por defecto: cualquier usuario con
  `is_staff=True` y el permiso de modelo correspondiente puede listar y **buscar por contenido** las
  notas. El aislamiento no se pierde —el `TenantManager` filtra por el tenant que resuelve
  `TenantMiddleware`, y devuelve vacío si no hay tenant (§1.1.1)—, pero la política de audiencia que
  pacientes declara explícitamente aquí no existe.
- **Consecuencia concreta:** dos admins del mismo proyecto aplican dos criterios distintos sobre datos
  de sensibilidad comparable. El día que se conceda `is_staff` a alguien para una tarea puntual, esa
  persona podrá buscar por texto libre dentro de las notas de la clínica; con pacientes no podría.

### B-NOT-10 · Las notificaciones sobreviven al borrado de la nota a la que apuntan
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/notas/services.py:635-636` (soft-delete de la nota) +
  `MailySoft/backend/apps/notas/services.py:408-439` (el fan-out guarda `target_type=NOTE` y
  `target_id`) — no hay ninguna limpieza (verificado: `note_delete` no importa nada de
  `apps/notificaciones`)
- **Qué dice la documentación:** nada.
- **Qué hace el código:** la nota queda con `deleted_at` y desaparece de `/notas/`, pero cada fila
  `Notification` sigue viva con su copia del título y del cuerpo y un enlace a un recurso que ya no
  se puede abrir.
- **Consecuencia concreta:** la campana de una recepcionista muestra "Aviso: cerramos a las 3 el
  viernes" y al pulsarla no pasa nada, o lleva a una pantalla vacía. Peor: el texto borrado sigue
  siendo legible en la notificación, así que "borrar la nota" no borra el contenido —lo que importa
  si alguien escribió ahí algo que no debía y lo borró para corregirlo.
## Agenda

> Brechas encontradas al extraer el contrato de `MailySoft/backend/apps/agenda/` el 2026-08-12.
> Severidad **propuesta**, no confirmada: el triage es de A4. Criterio usado:
> **P0** = fuga entre clínicas o pérdida de datos · **P1** = un rol hace algo que la documentación le
> niega, o el sistema afirma algo falso al usuario · **P2** = deuda, incoherencia interna o riesgo
> latente sin explotación hoy.
>
> **Ninguna brecha de este módulo alcanza P0**: no hay ningún camino que cruce el límite de tenant.
> Todo lo que sigue ocurre **dentro** de una misma clínica.

---

### B-AGE-01 · El borrado de una nota de agenda no se acota por sede
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:1153-1161` (`AgendaItemNoteDetailApi.delete`), selector sin filtro en `MailySoft/backend/apps/agenda/selectors.py:295-301`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:346-348` lo declara hallazgo abierto: "el detalle de una nota de cita no se acota por sede (`backend/apps/agenda/views.py:1144`)". La sección transversal lo repite en §1.5.5 diciendo "un admin de Norte puede **leer/borrar** por id la nota de una cita de Centro".
- **Qué hace el código:** `agenda_item_note_get(note_id=note_id)` se llama **sin** `sucursal_ids`, mientras que los otros 13 endpoints de la app pasan `sucursal_scope_ids(request)` a través de `_appointment_get_or_404` / `_agenda_block_get_or_404` (`views.py:97-135`). El permiso `AgendaItemNotePermission` deja pasar el `DELETE` a owner, admin, doctor, nurse y reception (§1.3 #19), y el service solo verifica autoría o rol privilegiado (`notes.py:206-223`), nunca sede. **Corrección a lo documentado:** la vista **solo implementa `delete`**; un `GET` a `/api/v1/agenda/notas/<id>/` responde **405**. El riesgo es borrar, no leer.
- **Consecuencia concreta:** en una clínica con sede Centro y sede Norte, un `admin` asignado solo a Centro que obtenga el id de una nota de Norte —los ids de agenda circulan en el estado de cuenta compartido del paciente, que es multi-sede por diseño— **borra la nota del hilo de la otra sede**. Como el hilo es append-only, esa nota no se recupera y el equipo de Norte no sabe que existió: la bitácora la registra, pero solo el dueño puede leer la bitácora (§1.3.5, `AuditLogPermission`).

---

### B-AGE-02 · El recordatorio se encola antes de que confirme la transacción
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/reminders.py:82-85`; rutas afectadas `MailySoft/backend/apps/agenda/services.py:628` y `MailySoft/backend/apps/agenda/services.py:730`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:352-354`: "Un recordatorio se encola antes de que la transacción confirme (`apply_async` sin `transaction.on_commit`): **puede dispararse sobre una cita que terminó sin guardarse**".
- **Qué hace el código:** **confirmado el hecho, matizada la consecuencia.** `send_appointment_reminder.apply_async(args=[str(reminder.id)], eta=scheduled_at)` no está dentro de `transaction.on_commit`. Ahora bien, en la ruta normal (`appointment_create`) la llamada ocurre **después** de cerrar el `atomic()` (`services.py:589`), y no hay `ATOMIC_REQUESTS` activo (no aparece en `MailySoft/backend/config/settings/`), así que ahí ya está comprometido. El problema real vive en las **dos rutas con transacción externa**: `appointment_create_with_new_patient` (`services.py:628`) y `appointment_create_series` (`services.py:730`), que envuelven a `appointment_create`. Si esa transacción externa revierte, la fila del `AppointmentReminder` revierte con ella, así que la tarea **no manda un mensaje sobre una cita fantasma**: encuentra un id inexistente y devuelve `"not_found"` (`tasks.py:95-97`).
- **Consecuencia concreta:** al agendar una serie de 12 sesiones para un paciente nuevo y fallar la última validación, quedan hasta 12 tareas huérfanas en Redis con un `eta` de días o semanas y 12 líneas `WARNING reminder ... not found` en el log del worker. Ruido operativo y ocupación de la cola, no un aviso indebido a un paciente. **Cambia de severidad el día que el envío sea real y alguien mueva el `apply_async` antes del `save()`**, o si la tarea llegara a ejecutarse antes del commit — hoy imposible en la práctica porque el `eta` mínimo es de 1 minuto (`views.py:722-726`, `min_value=1`).

---

### B-AGE-03 · Un médico cancela citas por `/estado/` lo que el permiso le niega por `DELETE`
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/core/permissions.py:195` frente a `MailySoft/backend/apps/agenda/views.py:596-603`
- **Qué dice la documentación:** el propio docstring del permiso: "DELETE → owner, admin, reception (cancela cita — **sin doctor; el doctor solo confirma/atiende, no cancela en nombre de la clínica**)" (`permissions.py:187-188`). `MailySoft/docs/01-analisis.md:52` describe al médico como quien maneja "su agenda"; no menciona la cancelación.
- **Qué hace el código:** `AppointmentPermission.policy["DELETE"] = {owner, admin, reception}`, así que `DELETE /api/v1/agenda/citas/<id>/` le da 403 a un `doctor`. Pero `AppointmentStatusPermission.policy["POST"]` incluye `doctor` (`permissions.py:209`) y la única exclusión codificada en `AppointmentChangeStatusApi` es la de enfermería: `if status == CANCELLED and active_role == "nurse"` (`views.py:596-603`). Un `POST /api/v1/agenda/citas/<id>/estado/` con `{"status": "cancelled"}` desde un médico pasa y ejecuta la misma cancelación.
- **Consecuencia concreta:** la regla que se quiso escribir ("el médico no cancela en nombre de la clínica") no existe: cualquier médico cancela cualquier cita dentro de su alcance de sede, incluidas las de **otro** médico (ver B-AGE-04). Recepción pierde el control del calendario y la bitácora registra `APPOINTMENT_STATUS`, no una cancelación identificable como tal. Además revela un patrón peligroso: **la política de un recurso está partida en dos clases de permiso que no se hablan**.

---

### B-AGE-04 · "Un médico solo agenda para sí mismo" existe únicamente al crear
- **Severidad propuesta:** P1
- **Dónde:** regla presente en `MailySoft/backend/apps/agenda/services.py:399-425`; ausente en `appointment_reschedule` (`services.py:870-1089`), `appointment_reactivate` (`services.py:1092-1175`), `appointment_change_status` (`services.py:781-862`) y `appointment_update` (`services.py:1183-1233`)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:52` es explícito: el médico ve "su agenda … Solo agenda **para sí mismo** y en **sus** consultorios". `MailySoft/docs/01-analisis.md:284`: "Un médico solo puede escribir sobre las citas que son suyas".
- **Qué hace el código:** `appointment_create` resuelve el `TenantMembership` del actor y, si su rol es `doctor`, exige `caller_doctor.id == doctor.id` (`services.py:417-425`). Ningún otro service repite el chequeo, y `AppointmentPermission` concede `PATCH` y `POST` a `doctor` sin distinguir de quién es la cita. Resultado: un médico puede **reagendar**, **reactivar**, **cambiar de estado** y **editar el motivo/notas** de la cita de un colega, siempre que caiga en su alcance de sede.
- **Consecuencia concreta:** en una clínica con dos médicos en la misma sede, el Dr. A mueve la cita de las 10:00 del Dr. B a las 16:00. El anti-empalme no lo impide —la cita sigue siendo del Dr. B y su horario nuevo está libre—, el Dr. B se entera cuando el paciente no llega, y la bitácora dice `APPOINTMENT_RESCHEDULE` con el Dr. A como actor. La restricción que el análisis vende como propiedad del producto solo cubre uno de los cinco caminos que tocan una cita.

---

### B-AGE-05 · El recordatorio se marca "Enviado" sin que exista envío
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/adapters/whatsapp.py:106-121` y `MailySoft/backend/apps/agenda/tasks.py:216-237`; se muestra al usuario en `MailySoft/backend/apps/agenda/serializers.py:188`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:255-256` lo lista en "NO incluye": "Recordatorios reales por WhatsApp. El adaptador es un placeholder que solo escribe en el log. El motor de Celery existe; el envío no."
- **Qué hace el código:** **confirmado.** `get_whatsapp_adapter()` termina con un `return SimulatedWhatsAppAdapter()` incondicional (`whatsapp.py:121`) y un `TODO(whatsapp-real)` justo encima; `MetaWhatsAppAdapter` se nombra en el docstring del módulo (`:6-7`) pero **no existe como clase**. El simulado escribe una línea INFO con el teléfono enmascarado y devuelve `success=True` con `external_message_id="sim-<12 hex>"` (`:92-103`). La tarea interpreta ese `success` como envío real: pone `status=SENT`, `sent_at=now()` y guarda el `sim-…` (`tasks.py:216-231`). Lo que el análisis no dice: **ese estado viaja al frontend** dentro de cada cita, en el arreglo `reminders` con `status_display: "Enviado"` (`serializers.py:117-139`, `:188`).
- **Consecuencia concreta:** recepción abre la cita del día siguiente, ve "Recordatorio · WhatsApp · Enviado" y decide **no** llamar al paciente. El paciente nunca recibió nada. La consecuencia no es técnica sino de negocio: el sistema afirma algo falso en una pantalla operativa, y el módulo `recordatorios` se vende como parte de todos los planes clínicos (§1.4.5). Mientras no haya adaptador real, el estado honesto sería `skipped` o una etiqueta explícita de simulación.

---

### B-AGE-06 · Crear o mover un bloqueo no verifica las citas que ya existen debajo
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/blocks.py:99-111` (create) y `MailySoft/backend/apps/agenda/blocks.py:189-217` (update). Sin exclusion constraint: `MailySoft/backend/apps/agenda/models.py:278-280` (`Meta` de `AgendaBlock` sin `constraints`)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:110-111`: "El sistema **impide el empalme** por médico, por consultorio y contra bloqueos, en el servicio y con restricciones de la base de datos".
- **Qué hace el código:** el anti-empalme contra bloqueos es **unidireccional**. `_check_block_overlap` (`services.py:247-297`) solo corre al crear o reagendar una **cita**. `agenda_block_create` no consulta `Appointment` en ningún punto, y `agenda_block_update` solo valida `ends_at > starts_at` (`blocks.py:203-204`). Tampoco hay constraint de base de datos para `agenda_blocks`, ni entre bloqueos entre sí.
- **Consecuencia concreta:** el administrador marca "Día festivo 15 de septiembre" sobre la sede Centro. Las 14 citas ya agendadas ese día siguen vivas, visibles en el tablero y con sus recordatorios programados; nadie recibe aviso. Cuando alguien intente **reagendar** una de esas citas a otra hora del mismo día, ahí sí fallará con "Ese horario está bloqueado por un evento de agenda", sin explicar que el bloqueo se puso encima. Además, un bloqueo con `sucursal` que se borra deja `sucursal=NULL` (`SET_NULL`, `models.py:258-272`) y **deja de bloquear cualquier cita con sede**, porque el filtro compara `sucursal_id` exacto (`services.py:282-284`).

---

### B-AGE-07 · El listado de eventos no exige rango de fechas y no pagina
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:915-933`; selector `MailySoft/backend/apps/agenda/selectors.py:55-88`
- **Qué dice la documentación:** nada. `MailySoft/docs/01-analisis.md:161` describe la pantalla como "Tablero por día", lo que sugiere un rango siempre presente, pero el contrato de la API no lo obliga.
- **Qué hace el código:** `date_from` y `date_to` son `required=False` (`views.py:924-925`) y la respuesta es un **array plano** sin paginador (`views.py:933`). Omitir ambos devuelve **todos** los eventos históricos del tenant dentro del alcance de sede, con `select_related` de tres tablas.
- **Consecuencia concreta:** hoy es inocuo —una clínica genera decenas de bloqueos al año y hay 1 a 3 usuarios concurrentes (`MailySoft/docs/01-analisis.md:312`)—, pero es un crecimiento sin techo: a los cinco años de operación de una clínica con dos sedes son miles de filas serializadas en una sola respuesta cada vez que el front no manda el rango. Es la única lectura de la app sin cota alguna: el listado de citas sí pagina y el hilo de notas sí está acotado a un padre.

---

### B-AGE-08 · El módulo `recordatorios` no gatea nada dentro de agenda
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/reminders.py:20-88` (sin `require_module`); verificado por búsqueda: no hay ninguna ocurrencia de `RequiresRecordatorios` ni de `require_module` en `MailySoft/backend/apps/agenda/`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:190` lista `recordatorios` como módulo vendible número 2, dependiente de `agenda`. §1.4.1 de la capa transversal ya lo marca como "no se aplica en ninguna vista" (B-T-07).
- **Qué hace el código:** la única condición para programar recordatorios es `config.reminders_enabled` (`reminders.py:47-48`), que es un ajuste de la clínica con default `True` (`models.py:112-115`) — no un derecho de plan. El guard `RequiresRecordatorios` existe (`MailySoft/backend/apps/core/entitlement_guards.py:93`) y nadie lo usa. Además, el arreglo `reminders` viaja anidado en **toda** respuesta de cita (`serializers.py:188`), sin consultar entitlements.
- **Consecuencia concreta:** una clínica en plan Básico que no contrató recordatorios los recibe igual: se crean filas `AppointmentReminder`, se encolan tareas Celery a costa de la infraestructura de Maily, y la interfaz muestra el estado del recordatorio en cada cita. Se está regalando un módulo de pago y, peor, se está estableciendo la expectativa de que funciona. En sentido inverso, el día que se apague el módulo a una clínica, **nada cambiará** — y el cliente lo notará.

---

### B-AGE-09 · El service de notas resuelve su cita/evento sin alcance de sede
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/notes.py:81` y `MailySoft/backend/apps/agenda/notes.py:88`
- **Qué dice la documentación:** nada específico. La regla de consistencia está escrita en el propio código: "el detalle/acción por id debe acotar EXACTAMENTE igual que su listado" (`views.py:86-93`).
- **Qué hace el código:** `agenda_item_note_create` llama `appointment_get(appointment_id=…)` y `agenda_block_get(block_id=…)` **sin** `sucursal_ids`, y valida solo `tenant_id`. Hoy no es explotable por HTTP porque las dos vistas que lo invocan ya resolvieron el padre con el helper acotado (`views.py:1054`, `:1114`), pero el service es una frontera reutilizable y ya hay precedente de llamarlos desde otra app (`MailySoft/backend/apps/expediente/services_calendarizacion.py:919`).
- **Consecuencia concreta:** el día que alguien agregue una nota automática de agenda desde otra app o desde un comando —"la calendarización movió esta sesión"—, esa ruta escribirá sobre citas de cualquier sede sin darse cuenta. Es defensa en profundidad ausente en el mismo módulo donde ya hubo un clúster completo de hallazgos de este tipo (`views.py:85-93`).

---

### B-AGE-10 · `AgendaItemNote.author` es `CASCADE`: borrar un usuario borra el hilo del equipo
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/models.py:592-597`
- **Qué dice la documentación:** §1.8.2 de la capa transversal fija el criterio del sistema: `created_by` es `SET_NULL` "para que borrar un usuario no bloquee ni arrastre sus registros"; §1.8.3.4 dice que el borrado en la API es lógico. `MailySoft/docs/01-analisis.md:299` presume "borrado lógico en lugar de físico".
- **Qué hace el código:** el hilo de notas tiene **dos** FK al usuario con reglas opuestas: `created_by` (heredado, `SET_NULL`) y `author` (`CASCADE`). Un `DELETE` físico del `User` arrastra todas sus notas de agenda. El mismo modelo declara `appointment` y `agenda_block` también en `CASCADE` (`models.py:598-613`), lo cual sí es coherente (la nota no sobrevive a su padre).
- **Consecuencia concreta:** no hay endpoint que borre usuarios en duro —la baja es bloquear la cuenta (§1.9)—, así que hoy no ocurre. Pero cuando llegue la petición de "borrar los datos de este empleado" por LFPDPPP, ejecutarla borrará **la conversación completa del equipo sobre citas de pacientes**, que es registro operativo de la clínica y no dato personal del empleado. El criterio correcto para ese campo es el mismo `SET_NULL` de `created_by`, o anonimizar el autor.

---

### B-AGE-11 · `AgendaBlock` protege menos que `Appointment` contra el borrado de un médico
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/models.py:242-257` (`CASCADE`) frente a `MailySoft/backend/apps/agenda/models.py:331-347` (`PROTECT`)
- **Qué dice la documentación:** nada.
- **Qué hace el código:** en la misma app, `Appointment.doctor` y `Appointment.consultorio` son `PROTECT` —no se puede borrar en duro un médico con citas— mientras que `AgendaBlock.doctor` y `AgendaBlock.consultorio` son `CASCADE`. No hay razón escrita para la diferencia.
- **Consecuencia concreta:** el borrado en duro de un médico falla por sus citas (`PROTECT`), así que la incoherencia no se manifiesta hoy. Se manifestará si alguien limpia datos de prueba o escribe un comando de purga por consultorio: al eliminar un consultorio, sus bloqueos desaparecen en silencio y los horarios que estaban cerrados vuelven a quedar libres para agendar, sin que nadie lo note hasta que se agende encima.

---

### B-AGE-12 · `series_id` está documentado como "siempre None en v1" y la API ya crea series
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/models.py:300-301` y `MailySoft/backend/apps/agenda/models.py:475-485` frente a `MailySoft/backend/apps/agenda/services.py:726` y `MailySoft/backend/apps/agenda/urls.py:45-49`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:189` lista las series como parte del módulo `agenda`, es decir, funcionalidad existente. El **código** dice lo contrario en dos docstrings: "GANCHO v2: series_id es un UUID nullable para futura funcionalidad… En v1 siempre es None. NO modelar Series aún".
- **Qué hace el código:** existe `POST /api/v1/agenda/citas/serie/`, `appointment_create_series` genera un `uuid4()` y lo escribe en cada cita (`services.py:726`, `:753`). El docstring del modelo quedó fosilizado. Peor: `series_id` **no se expone en ninguna respuesta** (`serializers.py:193-212`) y está en la lista de campos inmutables (`services.py:113-114`), así que después del 201 inicial **no existe forma de volver a agrupar las citas de una serie** por la API.
- **Consecuencia concreta:** un paciente con 12 sesiones de fisioterapia cancela el tratamiento. No hay "cancelar la serie": recepción tiene que cancelar las 12 citas una por una y no tiene forma de saber cuáles pertenecen a la serie más que por memoria o por leerlas del calendario. El campo que resolvería el problema existe en la base, se llena, y está oculto.

---

### B-AGE-13 · No hay barredora de recordatorios: si se pierde la cola, se pierden en silencio
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/reminders.py:82-85` (único disparador) y `MailySoft/backend/config/settings/base.py:303-310` (`CELERY_BEAT_SCHEDULE` sin ninguna tarea de agenda)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:190` presenta los recordatorios como "motor Celery". Nada dice sobre recuperación.
- **Qué hace el código:** el envío depende exclusivamente del `eta` que Celery guarda en Redis al encolar. No existe ninguna tarea periódica que busque `AppointmentReminder` en estado `PENDING` con `scheduled_at` ya vencido. Detalle revelador: el modelo declara el índice `reminder_scheduled_status_idx (scheduled_at, status)` con el comentario "Worker query: buscar los PENDING próximos a enviarse" (`models.py:762-766`) — **ese índice no tiene hoy ninguna consulta que lo justifique**, y es peso muerto en cada escritura de recordatorio.
- **Consecuencia concreta:** Railway reinicia el servicio de Redis, o Redis desaloja claves por presión de memoria. Los recordatorios de las próximas 24 horas de todas las clínicas se pierden y quedan `PENDING` para siempre. Ninguna alerta, ningún reintento, ninguna diferencia visible en la interfaz: la cita sigue mostrando "Pendiente". El índice ya construido para la barredora vuelve la corrección barata; hoy solo falta la tarea.

---

### B-AGE-14 · `reminder_list_for_appointment` no lo consume ninguna vista
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/selectors.py:304-314`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** el selector existe y está testeado (`apps/agenda/tests/test_reminders.py:920`, `:945`), pero **ninguna vista lo importa**: `views.py:34-45` no lo trae, y una búsqueda en `MailySoft/backend/apps/` solo lo encuentra en su definición y en los tests. Los recordatorios llegan al cliente por el `prefetch_related("reminders")` del serializer de cita (`selectors.py:164`, `:214`).
- **Consecuencia concreta:** código sin consumidor que un lector futuro tomará como "existe un endpoint de recordatorios" y construirá encima. No es superficie de ataque —no está expuesto— pero sí es la señal, junto con la ausencia de `RequiresRecordatorios` (B-AGE-08), de que la funcionalidad de recordatorios quedó a medio conectar. Es la clase de resto que conviene borrar o rutear conscientemente, no dejar en el limbo.

---

### B-AGE-15 · Cancelar una cita no exige motivo, y el motivo viaja en el cuerpo de un DELETE
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:553` y `MailySoft/backend/apps/agenda/views.py:587`
- **Qué dice la documentación:** el docstring del propio service dice "`reason`: Motivo (**requerido al cancelar**, opcional en otros casos)" (`services.py:806`). El modelo declara `cancellation_reason` como "Motivo de cancelación (se registra al cancelar)" (`models.py:434-438`).
- **Qué hace el código:** `appointment_change_status` **nunca** valida que `reason` venga (`services.py:829-832`: lo asigna tal cual, aunque sea `""`). En `DELETE /agenda/citas/<id>/` el motivo se lee de `request.data.get("reason","")`, es decir **del cuerpo de una petición DELETE** (`views.py:553`) — semántica que muchos clientes HTTP, proxies y `fetch` con `body` en DELETE tratan de forma inconsistente. En `POST /estado/` el campo es `allow_blank=True, default=""` (`views.py:587`).
- **Consecuencia concreta:** la mayoría de las cancelaciones quedan con `cancellation_reason = ""`. Cuando el dueño revise por qué se cayeron 30 citas del mes en la sede Norte, la bitácora le dirá quién y cuándo, pero no por qué, que es justo el dato que necesitaba. Y si el frontend deja de mandar cuerpo en el DELETE —o un proxy lo descarta—, el motivo se pierde sin ningún error visible.

---

### B-AGE-16 · La bitácora de agenda guarda el nombre del paciente en claro
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/models.py:528-532` (`__str__`) usado como `resource_repr` en `MailySoft/backend/apps/agenda/services.py:605`, `:856`, `:1082`, `:1173`, `:1230`; `patient_id` en `metadata` en `services.py:606-610`
- **Qué dice la documentación:** la regla dura del repo (`CLAUDE.md`, "Reglas duras", punto 5) exige registrar "con un identificador **no-PII** del recurso". `MailySoft/docs/01-analisis.md:299` presume "minimización de PII en la bitácora" como algo ya implementado.
- **Qué hace el código:** `Appointment.__str__` devuelve `"<nombre completo del paciente> — 2026-08-13 10:00 UTC [Agendada]"`, y ese string se manda tal cual como `resource_repr` en las cinco acciones auditadas de cita. También se guarda `patient_id` en `metadata`. La nota de agenda hace lo mismo vía `str(note)` (`notes.py:110`, `models.py:633-640`).
- **Consecuencia concreta:** la bitácora —que se conserva por requisito normativo y que se exportaría como evidencia— acumula nombres de pacientes asociados a fechas de consulta. Un `AuditLog` es la tabla que más tiempo vive y menos se depura; convertirla en un padrón de "quién fue al médico y cuándo" es exactamente lo que la minimización de PII intenta evitar. La corrección es barata (usar el `id` de la cita como `resource_repr`), pero **cambia el formato de un registro histórico**: hay que decidir si se migra lo ya escrito.

---

### B-AGE-17 · La respuesta de cita omite datos que la pantalla necesita
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/serializers.py:191-213`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:161` dice que en `AgendaPage` se puede "Agendar, reagendar, reactivar, cambiar estado…"; §3.1.4 de este contrato registra que el modelo guarda `cancellation_reason`, `cancelled_by`, `no_show_registered_by`, `reschedule_count` y `series_id`.
- **Qué hace el código:** `AppointmentOutputSerializer.Meta.fields` no incluye ninguno de esos cinco campos. Es el **único** serializer de salida de cita de la app, así que no hay otra ruta para obtenerlos.
- **Consecuencia concreta:** al abrir una cita cancelada, la interfaz no puede decir **por qué** se canceló ni **quién** la canceló, aunque el dato exista en la base; tampoco puede advertir "esta cita ya se movió 4 veces" antes de moverla otra vez, ni agrupar una serie (B-AGE-12). El contrato de lectura quedó por debajo del modelo: si mañana el front quiere mostrarlo, hay que tocar backend, y ese es exactamente el ida y vuelta que el contrato existe para evitar.

---

### B-AGE-18 · La respuesta de serie mezcla dos husos horarios
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:416-419`
- **Qué dice la documentación:** §1.7 fija que DRF serializa en el huso activo, que es `America/Mexico_City`.
- **Qué hace el código:** las citas de `created[]` pasan por `AppointmentOutputSerializer`, así que salen con desplazamiento `-06:00`. Pero `skipped[].starts_at` se construye a mano con `x["starts_at"].isoformat()`, sobre el datetime tal como se generó, es decir **en UTC**. La misma respuesta JSON lleva los dos formatos.
- **Consecuencia concreta:** recepción arma una serie de 12 sesiones a las 10:00; se agendan 10 y se saltan 2. El resumen muestra las creadas a las "10:00" y las saltadas a las "16:00" — las mismas 10:00 expresadas en UTC. Quien lea la pantalla concluirá que el sistema intentó agendar a otra hora, y reintentará mal. Un error de zona horaria en una agenda médica es el tipo de bug que se descubre con un paciente en la sala de espera.

---

### B-AGE-19 · `reminder_offsets_minutes` no tiene tope de tamaño ni de valor
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:722-726` y `MailySoft/backend/apps/agenda/services.py:1249-1297`
- **Qué dice la documentación:** nada. El modelo solo dice "Lista de enteros: minutos antes de la cita" (`models.py:105-111`).
- **Qué hace el código:** el serializer valida que cada elemento sea un entero ≥1, y nada más: ni longitud máxima de la lista, ni valor máximo, ni unicidad. `agenda_config_update` tampoco lo revisa (solo valida `slot_interval_minutes` y la coherencia de horas). `schedule_reminders_for_appointment` itera la lista completa y crea una fila y **una tarea Celery por cada offset** en **cada** cita (`reminders.py:56-85`).
- **Consecuencia concreta:** un `PATCH /agenda/config/` con `reminder_offsets_minutes` de 500 elementos —accesible a owner y admin, sin ser un rol de plataforma— hace que cada cita creada genere 500 filas y 500 tareas encoladas. Con la agenda de una clínica de dos sedes eso son decenas de miles de tareas en la cola compartida de Celery, que es la misma que genera los PDFs de recetas de **todas** las clínicas. No es una escalada de privilegios, pero sí un pie de amplificación que un cliente puede pisar por accidente al experimentar con la configuración.

---

### B-AGE-20 · No se puede vaciar el motivo de una cita
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:497`
- **Qué dice la documentación:** nada. El modelo declara `reason` con `blank=True, default=""` (`models.py:398-403`), es decir, vacío es un valor válido.
- **Qué hace el código:** en el `InputSerializer` del PATCH, `specialty` y `notes` llevan `allow_blank=True` pero `reason` **no** (`views.py:497-499`). Mandar `{"reason": ""}` devuelve **400** `{"reason": ["Este campo no puede estar en blanco."]}`.
- **Consecuencia concreta:** recepción escribe por error el motivo de otro paciente en una cita y **no puede borrarlo**: solo puede sustituirlo por otro texto. En un campo que la propia app clasifica como dato clínico —es la razón por la que `finance` no ve la agenda (`permissions.py:70-78`)— no poder retirar un dato mal capturado es un problema de calidad de datos, no de comodidad.

---

### B-AGE-21 · Un nombre de tipo de cita repetido devuelve 500
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:820-827` y `MailySoft/backend/apps/agenda/views.py:874-878`; constraint en `MailySoft/backend/apps/agenda/models.py:201-205`
- **Qué dice la documentación:** nada. `MailySoft/docs/01-analisis.md:164` dice que los tipos de cita se administran desde `PersonalPage`.
- **Qué hace el código:** el constraint `appointment_type_name_uniq` exige nombre único por clínica entre los no borrados. `appointment_type_create` hace `objects.create(...)` sin comprobación previa (`appointment_types.py:31-37`) y la vista solo captura `DjangoValidationError` (`views.py:826`): el `IntegrityError` de PostgreSQL **se propaga sin capturar** → **500**. En el `PATCH` es peor: `appointment_type_update` se llama **sin ningún `try/except`** (`views.py:874-878`). Detalle que agrava la probabilidad: la baja de la API es `is_active=False`, no `deleted_at` (`appointment_types.py:79-80`), así que **un tipo desactivado sigue ocupando su nombre**.
- **Consecuencia concreta:** el administrador desactiva "Primera vez" y meses después intenta volver a crearlo. Recibe un 500, un evento en Sentry y ninguna explicación en pantalla; el flujo correcto —reactivar el existente— ni siquiera está expuesto, porque el `PATCH` de tipo de cita no admite `is_active` (`views.py:842-850`). Un tipo desactivado es, en la práctica, irrecuperable por la API.

---

### B-AGE-22 · El tablero del día está limitado a 25 citas por página, sin `page_size`
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/agenda/views.py:243-248`; `PAGE_SIZE` en `MailySoft/backend/config/settings/base.py:215`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:161` describe `AgendaPage` como "Tablero por día, por consultorio, con columna fija de Telemedicina/Externo" — una vista que por definición necesita **todas** las citas del día a la vista.
- **Qué hace el código:** `PageNumberPagination()` estándar con `PAGE_SIZE=25` y **sin `page_size_query_param`** (§1.7.1): el cliente no puede pedir más de 25 por página bajo ninguna combinación de parámetros; solo puede pedir la página 2, 3, etc.
- **Consecuencia concreta:** una clínica con dos sedes, cuatro médicos y citas de 20 minutos supera 25 citas en una jornada con facilidad. Si el frontend pide una sola página —**NO VERIFICADO**: no leí `MailySoft/web-soft/`, que está fuera de mi alcance—, el tablero **pinta las primeras 25 y oculta el resto sin avisar**, y recepción agenda encima creyendo que hay hueco (el anti-empalme sí lo impedirá, pero la planeación visual ya fue errónea). La verificación de qué hace el front hoy es el primer paso antes de decidir si esto se corrige agregando `page_size_query_param` o si ya se maneja.
## Expediente

> Brechas detectadas al extraer el contrato de `apps/expediente` el 2026-08-12 (modo inverso).
> Ninguna se corrigió: documentar y arreglar a la vez produce un contrato que no describe ni el
> sistema viejo ni el nuevo. La severidad es **propuesta**; la confirma A4.

### B-EXP-01 · El addendum y el diagnóstico no aplican la regla del médico dueño de la cita
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/expediente/services.py:849-865` (addendum) y
  `MailySoft/backend/apps/expediente/services.py:936-969` (diagnóstico). Contrastar con
  `MailySoft/backend/apps/expediente/services.py:699-709`, que sí la aplica en la nota.
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:283-284` — "Un médico solo puede
  escribir sobre las citas que son suyas." Y `MailySoft/docs/01-analisis.md:117-118` — la corrección
  de una nota "se agrega como **addendum** firmado".
- **Qué hace el código:** `addendum_create` recibe `evolution` y `user` y **no compara** al actor
  con `evolution.doctor.membership.user_id`. `diagnosis_create` tampoco. `AddendumPermission` y
  `DiagnosisPermission` solo filtran por rol (owner/admin/doctor,
  `MailySoft/backend/apps/core/permissions.py:891-893`, `:909-911`). La regla del médico existe
  únicamente en `evolution_note_create` (`services.py:699`),
  `clinical_summary_create` (`services_resumen.py:405`) y la cancelación de citas de calendarización
  (`services_calendarizacion.py:201`).
- **Consecuencia concreta:** en una clínica con dos médicos, el Dr. B puede firmar un addendum con
  su nombre (`Addendum.author = user`, `services.py:863`) sobre la nota inmutable del Dr. A, y
  agregarle diagnósticos con código CIE-10. La nota firmada del Dr. A queda alterada en lo que ve
  quien la lea, sin que el Dr. A lo autorice y sin que el sistema lo impida. Como el addendum es
  append-only, tampoco se puede deshacer.

### B-EXP-02 · Guardar la historia clínica borra en silencio las respuestas de preguntas desactivadas
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/expediente/services.py:360-367`
- **Qué dice la documentación:** el propio modelo, en
  `MailySoft/backend/apps/expediente/models.py:886-889`: "Las respuestas a preguntas desactivadas
  permanecen en custom_answers (**no se purgan**) para preservar trazabilidad histórica del
  expediente." `MailySoft/docs/01-analisis.md:163` habla de "historia clínica configurable" sin
  entrar al detalle.
- **Qué hace el código:** en cada PUT, `_apply_fields` reescribe
  `h.custom_answers = {k: v for k, v in custom_answers.items() if k in valid_ids}` donde `valid_ids`
  son solo las preguntas con `is_active=True` del tenant. Las claves de preguntas desactivadas **se
  descartan y se persisten fuera**. No hay aviso, ni log, ni bitácora del descarte.
- **Consecuencia concreta:** una clínica desactiva la pregunta "¿Consume anticoagulantes?" porque la
  reformuló. El expediente de un paciente que ya la había contestado "Sí, warfarina" conserva la
  respuesta **hasta la siguiente edición de su historia clínica**: en ese momento desaparece de la
  base sin dejar rastro. Es pérdida de dato clínico en el registro que la NOM-004 obliga a
  conservar, y ocurre al guardar cualquier otro campo.

### B-EXP-03 · El PUT de calendarización borra FÍSICAMENTE líneas y sesiones
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/services_calendarizacion.py:331`
  (`stale_session.delete()`) y `MailySoft/backend/apps/expediente/services_calendarizacion.py:605`
  (`stale_item.delete()`, que además arrastra sus sesiones por el `CASCADE` de
  `MailySoft/backend/apps/expediente/models.py:1276-1280`).
- **Qué dice la documentación:** la regla dura del repo — "El borrado en API es lógico: se setea
  `deleted_at` o un `is_active`, nunca `DELETE` físico" (§1.8.3 del contrato, tomada de
  `MailySoft/backend/apps/core/models.py:51`); y la decisión D-EC-5 del propio módulo, escrita en
  `MailySoft/backend/apps/expediente/models.py:20`: "sin borrado físico". `MailySoft/docs/01-analisis.md:299`
  lo enumera entre lo implementado: "borrado lógico en lugar de físico".
- **Qué hace el código:** `TreatmentPlanItem` y `TreatmentSession` son `TenantAwareModel` con
  `deleted_at` disponible, y aun así el reemplazo llama `.delete()` de Django. El esquema padre sí
  se da de baja lógicamente (`services_calendarizacion.py:640-641`); sus hijos no.
- **Consecuencia concreta:** si un médico quita por error una línea de "Aplicación de plasma — 6
  sesiones" y guarda, las 6 filas desaparecen de la base. Lo aplicado (`applied_date`, `status`)
  se pierde con ellas; solo queda la cita cancelada en agenda y una entrada `TREATMENT_PLAN_SAVE`
  en bitácora que **no dice qué se borró** (`metadata` solo trae `items` y `total`,
  `services_calendarizacion.py:622`). No hay forma de reconstruir el esquema anterior.

### B-EXP-04 · Un PUT de calendarización sin `items` vacía el esquema y cancela sus citas
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/serializers.py:1539-1541` (`items` con
  `required=False, default=list`) + `MailySoft/backend/apps/expediente/services_calendarizacion.py:595-605`
  (todo item que no viene se borra y su cita se cancela).
- **Qué dice la documentación:** nada. Hallazgo nuevo.
- **Qué hace el código:** `TreatmentPlanInputSerializer` acepta un PUT sin `items` y le pone `[]`.
  `treatment_plan_replace` interpreta `[]` como "el usuario borró todo": recorre los items
  existentes, cancela la cita de cada sesión con motivo "Sesión eliminada de la calendarización" y
  borra las filas. El comentario del código lo asume explícitamente ("el frontend es responsable de
  reenviar lo que ya existía", `services_calendarizacion.py:246-248`), pero el contrato HTTP no
  distingue "no mandé el campo" de "quiero vaciarlo".
- **Consecuencia concreta:** un cliente que solo quiera renombrar el esquema (`PUT {"title": "..."}`)
  **cancela todas las citas agendadas del paciente** que colgaban de ese esquema. En una clínica con
  dos sedes, esas cancelaciones caen sobre la agenda de la sede donde estaban las citas, y la cita
  cancelada no se puede "descancelar": hay que volver a agendar y el hueco puede haberlo tomado otro
  paciente.

### B-EXP-05 · Ocho lecturas de expediente no se registran en la bitácora
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/views_alergias.py:42` (listar alergias),
  `MailySoft/backend/apps/expediente/views_imagenes.py:64` (indicaciones de enfermería),
  `MailySoft/backend/apps/expediente/views_imagenes.py:110` (listar imágenes),
  `MailySoft/backend/apps/expediente/views_resumen.py:93` (borrador de resumen) y `:199` (listado),
  `MailySoft/backend/apps/expediente/views_plan_integral.py:110` (borrador) y `:144` (listado),
  `MailySoft/backend/apps/expediente/views_calendarizacion.py:139` y `:244`.
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:27` — la clínica "no puede demostrar
  quién vio ni quién modificó el expediente" es el problema que el producto dice resolver;
  `MailySoft/docs/01-analisis.md:287-289` afirma que la bitácora registra "quién, qué acción, sobre
  qué recurso". La regla dura del repo exige registrar "las acciones sensibles".
- **Qué hace el código:** cinco lecturas sí auditan (`MEDICAL_HISTORY_READ`, `VITALSIGNS_READ`,
  `EVOLUTION_READ`, `DIAGNOSIS_READ`, `PATIENT_BOOK_VIEW`), con logging crítico si la bitácora
  falla. Las ocho de arriba no emiten nada. La más grave es el **borrador del resumen clínico**
  (`views_resumen.py:93`): compone historia clínica + nota de evolución + signos vitales del
  paciente y los devuelve completos, es decir, es una lectura del expediente tan amplia como el GET
  de la historia clínica — y es invisible en la bitácora.
- **Consecuencia concreta:** ante una revisión, la clínica puede demostrar quién abrió la historia
  clínica pero no quién leyó el mismo contenido entrando por el borrador del resumen. Un usuario que
  quiera consultar expedientes sin dejar rastro solo tiene que usar esa ruta.

### B-EXP-06 · `created_by` con `PROTECT` en tres modelos, contra el `SET_NULL` del modelo base
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/models.py:1011-1019` (`ClinicalSummary`),
  `MailySoft/backend/apps/expediente/models.py:1164-1172` (`TreatmentPlan`),
  `MailySoft/backend/apps/expediente/models.py:1389-1397` (`LongevityPlan`).
- **Qué dice la documentación:** §1.8.2 del contrato, extraída de
  `MailySoft/backend/apps/core/models.py:63-64`: `created_by` es `SET_NULL` **con la razón escrita**
  (FIX-7) — "Borrar un usuario no bloquea ni arrastra sus registros: quedan con autor nulo".
- **Qué hace el código:** los tres modelos **redeclaran** el campo heredado con
  `on_delete=models.PROTECT`. Los otros 12 modelos de la app usan el heredado `SET_NULL`.
- **Consecuencia concreta:** intentar borrar en duro un usuario que alguna vez generó un resumen
  clínico, un esquema de calendarización o un plan integral revienta con `ProtectedError`, mientras
  que borrar a uno que solo escribió notas de evolución funciona. Es un comportamiento incoherente
  dentro de la misma app y no está justificado en ningún comentario. Hoy el impacto es teórico
  (las bajas de personal son lógicas, §1.6.1), pero cualquier script de depuración de usuarios
  fallará a la mitad, dejando el borrado incompleto.

### B-EXP-07 · El contenido visible de una nota firmada sigue siendo mutable vía imágenes
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/views_imagenes.py:128` (POST) y `:187` (DELETE),
  ambos sobre notas ya creadas y bloqueadas.
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:117-119` — "**la nota nace
  bloqueada**: no se edita ni se borra. Una corrección se agrega como **addendum** firmado.
  Diagnósticos e imágenes de evolución **cuelgan de esa nota**." Y la regla dura 4 del repo: "Lo
  clínico es inmutable".
- **Qué hace el código:** `EvolutionNote` es efectivamente inmutable (constraint en base,
  `models.py:611-614`), pero su colección de imágenes no tiene ventana de tiempo ni candado: se
  pueden agregar hasta 20 y dar de baja lógica cualquiera, meses después de firmada, por cualquier
  owner/admin/doctor de la clínica y sin la regla del médico dueño. El borrado es lógico
  (`services.py:1445-1447`) y sí se audita (`EVOLUTION_IMAGE_REMOVE`), pero la imagen deja de
  aparecer en la nota, en el libro clínico y en su PDF.
- **Consecuencia concreta:** una nota firmada hace tres meses que documentaba una lesión con foto
  puede quedarse sin la foto, o ganar una nueva, sin que nada en la nota lo indique. Si esa nota se
  imprimió antes y después, los dos PDF difieren y ambos se presentan como el mismo documento
  inmutable.

### B-EXP-08 · Calendarización toca cotizaciones y paquetes sin exigir esos módulos
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/views_calendarizacion.py:358`
  (`TreatmentPlanQuoteApi`, guard solo `RequiresCalendarizacion`) y
  `MailySoft/backend/apps/expediente/views_calendarizacion.py:200`
  (`TreatmentPlanFromPackageApi`). La puerta de entrada está en
  `MailySoft/backend/apps/plataforma/services.py:618-624`.
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:200-202` — `calendarizacion`
  "depende de 3, 7, 9" (expediente, servicios, cotizaciones) y "se enciende caso por caso como
  override". `MailySoft/docs/01-analisis.md:217-218` — "Un módulo apagado responde 404, no 403: la
  clínica no sabe que existe algo que no compró."
- **Qué hace el código:** `tenant_entitlements_set` valida **solo que los slugs existan**
  (`modulos_desconocidos`), **no** las dependencias — a diferencia de `Plan.modules`, que sí pasa por
  `validar_modulos` (`apps/plataforma/services.py:724`). Así que un super_admin puede encender
  `calendarizacion` en `modules_on` de una clínica sin `cotizaciones` ni `paquetes`, y esos dos
  endpoints funcionarán: uno crea una `finanzas.Quote` y el otro lee un `finanzas.TreatmentPackage`.
- **Consecuencia concreta:** una clínica que compró el plan Básico y a la que se le concedió
  calendarización como cortesía genera cotizaciones reales que **no puede abrir** (el módulo
  `cotizaciones` responde 404 en su propia pantalla). Quedan documentos comerciales huérfanos, con
  totales, que nadie de la clínica puede consultar ni cancelar.

### B-EXP-09 · Ningún endpoint del expediente acota por sucursal, y esa decisión no está escrita
- **Severidad propuesta:** P2
- **Dónde:** toda la app. Verificado por búsqueda: `sucursal` solo aparece en
  `MailySoft/backend/apps/expediente/views_calendarizacion.py`,
  `MailySoft/backend/apps/expediente/services_calendarizacion.py` y
  `MailySoft/backend/apps/expediente/services.py:783-787` (fanout a enfermería). Ninguna vista llama
  `sucursal_scope_ids`; el punto de entrada de casi todos los endpoints es
  `patient_get` (`MailySoft/backend/apps/pacientes/selectors.py:44`), que solo filtra por tenant.
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:234-235` enumera entre lo incluido
  "alcance de agenda, finanzas y avisos por sede" — el expediente **no** está en esa lista, lo cual
  es coherente. Pero §1.5.5 del contrato ("dónde NO se aplica") tampoco lo registra, y la regla de
  `sucursal_scope.py:92-94` dice que "listados expuestos a roles acotados por sede usan
  `sucursal_scope_ids`".
- **Qué hace el código:** cualquier rol clínico ve el expediente completo de cualquier paciente de
  la clínica, sin importar en qué sede se atendió ni a qué sedes está asignado el usuario. La única
  excepción es agendar/desagendar sesiones de calendarización, que sí valida sede
  (`services_calendarizacion.py:942-948`).
- **Consecuencia concreta:** en una clínica con dos sedes, la enfermera de Norte lee la historia
  clínica, los signos y las notas de evolución de todos los pacientes de Centro. Puede ser la
  decisión correcta (el expediente clínico es del paciente, no de la sede — es lo que asume
  `services_calendarizacion.py:1056-1058` al decir que "el estado de cuenta del paciente es
  compartido entre sedes por diseño"), pero **no está declarada en ningún lado**, así que el
  siguiente que toque el módulo no sabrá si es diseño o descuido.

### B-EXP-10 · El GET de historia clínica devuelve dos formas distintas según exista o no
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/views_historia.py:64-79` (`_empty_history`) frente a
  `MailySoft/backend/apps/expediente/serializers.py:315-332` (`MedicalHistoryOutputSerializer`).
- **Qué dice la documentación:** nada. Hallazgo nuevo.
- **Qué hace el código:** cuando el paciente **sí** tiene historia clínica, la respuesta trae 16
  claves, incluidas `custom_answers` y `active_questions` (el catálogo de preguntas extra con el que
  el frontend pinta el formulario). Cuando **no** la tiene, la vista devuelve un documento vacío de
  14 claves construido a mano, **sin `custom_answers` ni `active_questions`**.
- **Consecuencia concreta:** al abrir el expediente de un paciente nuevo, el frontend recibe una
  respuesta sin el catálogo de preguntas configurables de la clínica. O bien las preguntas extra no
  se pintan la primera vez (y se capturan hasta la segunda edición), o bien el front tiene que pedir
  el catálogo por su cuenta a `/expediente/preguntas-hc/` solo para ese caso. Contrato inconsistente
  en el endpoint más usado del módulo.

### B-EXP-11 · No se puede editar solo las opciones de una pregunta de tipo `select`
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/serializers.py:1015-1032`
  (`MedicalHistoryQuestionInputSerializer.validate`), usado con `partial=True` desde
  `MailySoft/backend/apps/expediente/views_preguntas.py:108`.
- **Qué dice la documentación:** nada. Hallazgo nuevo.
- **Qué hace el código:** en un PATCH parcial que solo manda `options`, la validación lee
  `field_type = data.get("field_type", "")` → cadena vacía, y como `options` viene con contenido cae
  en `field_type != SELECT and options` → 400 `{"options": "Las opciones solo aplican para tipo
  'select'."}`. El serializer no consulta el `field_type` real de la pregunta que se está editando
  (a diferencia del service, que sí lo hace: `services.py:1316`, `:1325`).
- **Consecuencia concreta:** una clínica que quiera agregar una opción a su pregunta "¿Qué seguro
  tiene?" recibe siempre un 400 desde la interfaz de administración, y el único camino es reenviar
  también `field_type: "select"` en el mismo PATCH. Bug de contrato, no de seguridad.

### B-EXP-12 · Las tres reglas por rol de los services son fail-open ante `actor_role` vacío
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/expediente/services_calendarizacion.py:84`,
  `MailySoft/backend/apps/expediente/services_plan_integral.py:76` y
  `MailySoft/backend/apps/expediente/services.py:699`.
- **Qué dice la documentación:** §1.3.1 del contrato afirma que todas las clases de permiso son
  **fail-closed** salvo `OPTIONS`. La documentación no cubre las validaciones de rol que viven en
  services.
- **Qué hace el código:** las tres usan el patrón `if actor_role and actor_role not in ...` /
  `if actor_role == "doctor"`. Un `actor_role` vacío **pasa siempre**: no valida el rol y no aplica
  la regla del médico. Es deliberado y está escrito ("cadena vacía se permite pasar: la validación
  de rol HTTP ya corrió", `services_calendarizacion.py:75-79`), y hoy las 33 vistas lo pasan bien
  con `getattr(request, "active_role", "") or ""`.
- **Consecuencia concreta:** es una barrera que solo protege si el llamador coopera. El día que se
  agregue un endpoint, una tarea Celery o un management command que olvide propagar `actor_role`,
  la regla "un médico solo escribe sobre sus propias citas" desaparece **en silencio**, sin error ni
  log. Comparar con `TenantManager`, que ante la ausencia de contexto de tenant dentro de un request
  devuelve `qs.none()` (§1.1.1): ahí la ausencia cierra, aquí abre.
## Recetas y PDFs

> Brechas extraídas el 2026-08-12 leyendo `apps/recetas/` y `apps/pdfs/` completos. Ninguna se
> corrigió: este documento solo las registra. Detalle del comportamiento actual en
> `docs/_a2-partes/50-recetas-pdfs.md` (§5).

---

### B-REC-01 · No existe ninguna ruta para marcar un medicamento como controlado: el módulo F6 completo es inalcanzable
- **Severidad propuesta:** P0
- **Dónde:** `MailySoft/backend/apps/recetas/management/commands/seed_medicamentos.py:491`, `MailySoft/backend/apps/recetas/serializers.py:100`, `MailySoft/backend/apps/recetas/serializers.py:180`, `MailySoft/backend/apps/recetas/services.py:405`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:239-240` incluye entre lo que el sistema **sí** hace: "Recetas inmutables con PDF, verificación pública por QR firmado con HMAC, y **módulo de controlados**". `MailySoft/docs/01-analisis.md:192` lista `recetas` como módulo con "controlados". `MailySoft/docs/01-analisis.md:278-279` cuenta "recetas y medicamentos controlados" entre los datos sensibles que el sistema maneja.
- **Qué hace el código:** los tres únicos caminos que pueden producir un `controlled_group != "none"` están cerrados. (1) El seed global crea las entradas con `defaults={"commercial_name", "presentation", "is_active"}` y **sin `controlled_group`** (`seed_medicamentos.py:491-495`), pese a que el catálogo incluye Clonazepam, Alprazolam, Diazepam, Lorazepam y Zolpidem (`seed_medicamentos.py:296-316`) → todos quedan en `none`. (2) `MedicationCreateInputSerializer` no declara `controlled_group` (`serializers.py:100-148`) y `medication_create` no acepta el parámetro (`services.py:147-157`) → todo medicamento custom nace en `none`. (3) `PrescriptionItemInputSerializer` no declara `controlled_group` (`serializers.py:180-297`) y la whitelist de ítems rechaza claves no declaradas con 400 (`serializers.py:583-587`) → la rama `elif raw_group in valid_groups` de `services.py:405-407` es código muerto vía HTTP. No hay `admin.py` en la app (verificado por listado de archivos), así que tampoco hay una vía manual. Los tests que cubren F6 llaman al **service** directamente y se saltan el serializer (`apps/recetas/tests/test_f6_controlled.py:92-102`), por eso la suite pasa en verde.
- **Consecuencia concreta:** un médico emite una receta de **Clonazepam 2 mg** eligiéndolo del catálogo global. El sistema la trata como receta común: **no exige el folio del recetario especial COFEPRIS** (`services.py:629-634` nunca se dispara), guarda `valid_until = NULL` en vez de 30 días, la registra en bitácora como `PRESCRIPTION_CREATE` en lugar de `PRESCRIPTION_CONTROLLED_CREATE` (`services.py:702-706`), el PDF sale sin el aviso de controlado (`pdf.py:549`), y el QR público responde `"controlado": false, "vigencia": null` (`views_public.py:179-195`). La clínica cree que tiene control de psicotrópicos y no lo tiene; ante una inspección, la bitácora no distingue una receta de benzodiacepina de una de paracetamol.

---

### B-REC-02 · Cualquier médico puede editar el formato de receta de toda la clínica y crear formatos a nombre de otro médico
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/recetas/services.py:980`, `MailySoft/backend/apps/recetas/services.py:918`, `MailySoft/backend/apps/core/permissions.py:1027`
- **Qué dice la documentación:** el propio permiso promete la validación fina: "Los médicos pueden crear su formato personal (**la validación fina de 'solo el propio médico' la hace el servicio**)" (`apps/core/permissions.py:1011-1013`). El modelo dice que `is_default` es "el formato que se aplica automáticamente a las recetas del tenant" (`apps/recetas/models.py:847-849`). `MailySoft/docs/01-analisis.md:169` asigna `MiConsultorioPage` —donde vive el formato de receta— a "Owner, Admin (Médico en lo suyo)".
- **Qué hace el código:** `prescription_format_update` valida tenant (`services.py:1012`), campos inmutables (`services.py:1015-1019`) y que solo un admin cambie `is_authorized` (`services.py:1022-1025`). **No verifica en ningún punto que el formato pertenezca al médico que lo edita.** Con `PrescriptionFormatPermission.policy["PATCH"]` incluyendo `DOCTOR` (`permissions.py:1027`), cualquier usuario con rol `doctor` puede hacer PATCH sobre **cualquier** `PrescriptionFormat` del tenant, incluido el `is_default` de la clínica, y puede enviar `is_default=True` sobre el suyo (`services.py:1037-1042`). En la creación, `doctor_id` solo se valida contra el tenant (`services.py:918-930`), nunca contra el perfil del actor.
- **Consecuencia concreta:** en una clínica con dos médicos, el Dr. A entra a la configuración, cambia el color, la tipografía y las secciones del formato por defecto de la clínica, y lo marca como suyo. A partir de la siguiente receta emitida, **todas las recetas de la Dra. B salen con el diseño del Dr. A**, sin que ella pueda notarlo hasta que un paciente le muestre el papel. Peor: el Dr. A puede crear un "formato personal" a nombre de la Dra. B; si un owner lo autoriza sin revisar de quién es, ese formato pasa a aplicarse automáticamente a las recetas de ella (`selectors.py:254-268`). Y como la receta es inmutable, los PDF ya emitidos con el formato equivocado no se corrigen.

---

### B-REC-03 · El secreto del QR cae a `SECRET_KEY` sin control, y el token no caduca ni se puede revocar
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/config/settings/base.py:540`, `MailySoft/backend/apps/recetas/verification.py:50`, `MailySoft/backend/apps/recetas/verification.py:66`
- **Qué dice la documentación:** el propio settings lo declara obligatorio: "En producción **OBLIGATORIO** configurar como secreto independiente" (`config/settings/base.py:534`) y "Debe ser distinto de DJANGO_SECRET_KEY (rotación independiente)" (`base.py:531-532`). `MailySoft/docs/01-analisis.md:239` vende "verificación pública por QR firmado con HMAC" como funcionalidad terminada.
- **Qué hace el código:** `PRESCRIPTION_VERIFY_SECRET: str = env("PRESCRIPTION_VERIFY_SECRET", default=SECRET_KEY)` (`base.py:540`), con un segundo fallback dentro del helper (`verification.py:50`). `config/settings/production.py` **no lo exige** (verificado: la cadena no aparece en el archivo), a diferencia de `DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY`, `DJANGO_ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`, que sí revientan al arrancar si faltan (`production.py:19-31`, `:95`). Además, el mensaje firmado es únicamente `str(prescription.id)` (`verification.py:66-68`): el token no incorpora fecha de emisión, versión de clave ni expiración, y no hay ningún mecanismo de revocación.
- **Consecuencia concreta:** dos escenarios, ambos silenciosos. (1) Si `PRESCRIPTION_VERIFY_SECRET` no está en Railway, el token del QR se deriva de `DJANGO_SECRET_KEY`; **el día que se rote la SECRET_KEY por cualquier motivo de seguridad, todos los QR ya impresos dejan de validar de golpe** y cada receta en manos de un paciente pasa a responder 404 en la farmacia. No hay migración posible: la receta es inmutable y el PDF ya está impreso. (2) Si el secreto se filtra, no hay forma de invalidar los tokens existentes salvo rotar la clave, lo que rompe todos los QR válidos a la vez. Y como el token no caduca, quien fotografió un QR conserva acceso permanente al nombre del médico, su cédula y el nombre de la clínica.

---

### B-REC-04 · El throttle anti-enumeración del endpoint público es evadible con `X-Forwarded-For`
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/recetas/views_public.py:44`, `MailySoft/backend/config/settings/base.py:231`
- **Qué dice la documentación:** el docstring de la vista lista el throttle como uno de los cinco controles de seguridad del endpoint: "Throttle: PrescriptionVerifyThrottle (30 req/min **por IP**)" (`views_public.py:75`) y "Protege contra scraping de folios y enumeración de recetas" (`views_public.py:48`).
- **Qué hace el código:** `PrescriptionVerifyThrottle` hereda de `AnonRateThrottle`, que identifica al cliente con `SimpleRateThrottle.get_ident()`. Ese método usa `REMOTE_ADDR` **solo si `NUM_PROXIES` está configurado**; con `NUM_PROXIES = None` (default de DRF) usa el contenido crudo de la cabecera `X-Forwarded-For`. `NUM_PROXIES` no está configurado: verificado por búsqueda en todo `MailySoft/backend/config/`, cero ocurrencias. Es la misma raíz que el riesgo 3 de `MailySoft/docs/01-analisis.md:337-339` sobre la IP de la bitácora.
- **Consecuencia concreta:** el atacante elige su propia clave de cuota rotando la cabecera y consulta el endpoint sin límite práctico. Hoy no permite enumerar recetas —la firma HMAC de 128 bits lo impide (`verification.py:45`)—, pero sí permite martillear el endpoint para tumbarlo: cada petición con firma válida dispara tres queries (receta con `prefetch`, `ClinicSettings`, `INSERT` de bitácora) sobre la base de producción, y el `INSERT` en `AuditLog` no se acota (`views_public.py:153-164`). Un solo QR filtrado basta para inflar la bitácora de esa clínica indefinidamente.

---

### B-REC-05 · Un `global_medication_id` inexistente produce 500 en lugar de 400
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/recetas/services.py:390`, `MailySoft/backend/apps/recetas/services.py:685`
- **Qué dice la documentación:** el docstring de `prescription_create` enumera las razones de `ValidationError` (400) e incluye la validación del catálogo custom, pero no menciona el global (`services.py:495-501`). El comentario en el código dice literalmente: "snapshot conserva 'none'; **la FK queda inválida (se validará en create)**" (`services.py:391`).
- **Qué hace el código:** nada valida esa FK después. `_resolve_item_controlled_groups` traga la excepción con `pass` cuando el `GlobalMedication` no existe (`services.py:388-391`), y el `PrescriptionItem.objects.create(...)` recibe `global_medication_id=item_data.get("global_medication_id")` sin filtrar (`services.py:685`). Al escribir, la restricción de clave foránea de Postgres lanza `IntegrityError`, que la vista **no** captura —solo atrapa `DjangoValidationError` (`views.py:281-289`)— así que sube como 500. Contraste directo: el mismo helper **sí** convierte el caso equivalente del catálogo custom en un `ValidationError` claro (`services.py:399-403`).
- **Consecuencia concreta:** el frontend manda un `global_medication_id` de un medicamento que Maily retiró del catálogo entre que el médico abrió el formulario y lo guardó. El médico recibe un **error 500 genérico** en vez de "ese medicamento ya no existe": pierde la receta completa que acababa de capturar (la transacción hace rollback, `services.py:419`) y no tiene forma de saber cuál de los 20 renglones es el culpable. En Sentry aparece como fallo del servidor, no como error de datos.

---

### B-REC-06 · Dos mecanismos paralelos de PDF asíncrono que hay que mantener y auditar por separado
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/recetas/models.py:1072`, `MailySoft/backend/apps/pdfs/models.py:15`, `MailySoft/backend/apps/pdfs/__init__.py:3`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:245` habla de "PDFs asíncronos con Celery (7 tipos de documento)" como si fuera un solo mecanismo. La propia app lo declara: "Un solo `PdfJob` + una tarea + endpoints de estado/descarga sirven a **TODOS** los PDFs de la app (**recetas**, libro clínico, cotizaciones, reportes…)" (`apps/pdfs/__init__.py:3-5`).
- **Qué hace el código:** recetas conserva su implementación previa y **no** migró al registry. Hay dos modelos (`recetas/models.py:1072` y `pdfs/models.py:15`), dos tareas Celery casi idénticas (`recetas/tasks.py:38` y `pdfs/tasks.py:37`), dos servicios de encolado con la misma lógica duplicada (`recetas/services.py:1241` y `pdfs/services.py:11`), dos tablas con su propia migración de RLS, y **dos pares de endpoints** de estado/descarga (`recetas/urls.py:65-74` y `pdfs/urls.py:8-17`). `register_pdf_kind` nunca se llama para recetas (verificado: las seis llamadas están en `apps/expediente/apps.py:30-45` y `apps/finanzas/apps.py:28-35`).
- **Consecuencia concreta:** cualquier corrección de seguridad sobre la descarga de PDFs hay que aplicarla dos veces o queda a medias. Hoy ya divergen: los endpoints de recetas llevan `RequiresRecetas` y los genéricos no llevan guard de módulo (B-REC-07); los genéricos revalidan el permiso del `kind` y responden 404, los de recetas confían en el `permission_classes` de la vista. Quien lea `apps/pdfs/__init__.py` creerá que arreglando ahí arregló también las recetas.

---

### B-REC-07 · Los endpoints genéricos de PDF no aplican guard de módulo: un módulo apagado sigue sirviendo PDFs
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pdfs/views.py:52`, `MailySoft/backend/apps/pdfs/views.py:84`
- **Qué dice la documentación:** regla dura 3 de `Maily360/CLAUDE.md`: "**Un módulo apagado responde 404, no 403.** La clínica no debe saber que existe algo que no compró." El mecanismo y su razón están en `apps/core/entitlement_guards.py:12-16`.
- **Qué hace el código:** `PdfJobStatusApi` y `PdfJobFileApi` declaran `permission_classes = [IsAuthenticated]` y revalidan **solo el permiso de rol** registrado para el `kind` (`apps/pdfs/views.py:36-42`). No hay ningún `RequiresX`, y no lo puede haber tal como está: el `kind` es dinámico y el registry solo guarda una clase de permiso role-based, no el módulo (`apps/pdfs/registry.py:28-34`). Los endpoints de receta sí lo llevan (`apps/recetas/views.py:425`, `:453`), lo que confirma que es una omisión y no una decisión.
- **Consecuencia concreta:** una clínica baja del plan Pro al Básico y pierde el módulo `cotizaciones`. El endpoint de encolar cotización empieza a responder 404, como debe. Pero un `job_id` de tipo `quote` generado la semana anterior —que el navegador conserva en su historial o que quedó en un enlace compartido— **sigue devolviendo 200 con el PDF**. Lo mismo con `finance_report` al perder `cobranza`. El corte de servicio por plan tiene una fuga por esta puerta.

---

### B-REC-08 · La descarga de un PDF clínico no se registra en la bitácora
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pdfs/views.py:87`, `MailySoft/backend/apps/recetas/views.py:456`
- **Qué dice la documentación:** regla dura 5 de `Maily360/CLAUDE.md`: "Las acciones sensibles se registran en la bitácora (`audit_record`) con un identificador no-PII del recurso. Es requisito normativo, no adorno." `MailySoft/docs/01-analisis.md:287-288` afirma que la bitácora registra "quién, qué acción, sobre qué recurso, con qué rol, en qué clínica y desde qué IP".
- **Qué hace el código:** se audita el **encolado**, no la descarga. `PRESCRIPTION_PDF` se registra al pedir el PDF (`apps/recetas/views.py:390-398`) y `PATIENT_BOOK_PDF` al pedir el libro (`apps/expediente/views_libro.py:141`), pero ni `PdfJobFileApi` (`apps/pdfs/views.py:87-105`) ni `PrescriptionPdfJobFileApi` (`apps/recetas/views.py:456-474`) llaman a `audit_record`. Como el job cacheado o el `job_id` se pueden reusar indefinidamente, la relación entre solicitudes y descargas no es 1:1.
- **Consecuencia concreta:** un usuario pide una vez el libro clínico de un paciente —queda un registro— y después descarga el PDF cincuenta veces desde el mismo enlace, o se lo pasa a un compañero que lo descarga con su propio token. En la bitácora hay **una** línea. Ante una investigación por fuga de expediente, el registro que se usaría como evidencia no muestra quién se llevó el documento ni cuántas veces.

---

### B-REC-09 · La descarga de un PDF genérico solo valida rol, no el recurso ni la sucursal
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pdfs/views.py:36`, `MailySoft/backend/apps/pdfs/registry.py:16`
- **Qué dice la documentación:** el registry lo asume explícitamente: el permiso es "defensa en profundidad sobre el job_id, **que ya es un UUID inadivinable obtenido de un endpoint que verificó permisos**" (`apps/pdfs/registry.py:16-18`). `MailySoft/docs/01-analisis.md:288-289` justifica restringir la bitácora al dueño "para que un administrador de una sede no vea la actividad de otra".
- **Qué hace el código:** `_kind_permission_ok` instancia el permiso del `kind` y llama `has_permission(request, view)` (`apps/pdfs/views.py:36-42`). Esas clases son subclases de `HasClinicRole`, que solo mira `request.active_role` (§1.3.1) y **no implementan `has_object_permission`** (§1.3.6). No hay ninguna comprobación de que el actor tenga relación con el paciente, la cotización o la sede del job. Los `params` del job (que llevan `patient_id`, `sucursal_ids`, etc.) no se consultan en la autorización (`apps/pdfs/models.py:44`).
- **Consecuencia concreta:** dos casos reales del proyecto. (1) Una enfermera que nunca atendió a un paciente, con un `job_id` de `kind="book"` que le llegó por chat interno o que vio en la barra de direcciones de una compañera, descarga el **libro clínico completo** de ese paciente: `EvolutionPermission.GET` incluye `nurse` (§1.3.2 #24). (2) Una `admin` asignada solo a la sede Norte descarga el `finance_report` de la sede Centro, aunque el endpoint que lo generó sí acotó por `sucursal_ids` (`apps/finanzas/views.py:1259-1261`): el filtro de sede se aplicó al **contenido**, no al **acceso al archivo**.

---

### B-REC-10 · Los jobs de PDF y sus archivos no expiran nunca
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pdfs/models.py:15`, `MailySoft/backend/apps/recetas/models.py:1072`, `MailySoft/backend/config/settings/base.py:303`
- **Qué dice la documentación:** nada. Ni `01-analisis.md` ni los docstrings de `apps/pdfs` mencionan retención, limpieza ni caducidad de los PDFs generados.
- **Qué hace el código:** `PdfJob` y `PrescriptionPdfJob` no tienen campo de expiración ni estado `expired`. No existe ninguna tarea periódica que los toque: `CELERY_BEAT_SCHEDULE` solo agenda `apps.plataforma.tasks.avisar_vencimientos` (`config/settings/base.py:303-308`). No hay management command de limpieza (verificado en el listado de `apps/pdfs/` y `apps/recetas/management/`). Un job que queda `pending` porque el worker estaba caído se queda `pending` indefinidamente, y el frontend hace polling "cada ~2 s" sin condición de salida documentada (`apps/pdfs/views.py:48-49`).
- **Consecuencia concreta:** dos efectos que crecen solos. (1) Cada vez que alguien imprime el libro clínico de un paciente se deposita un PDF **con el expediente completo** en el storage de Cloudinary, y ahí se queda para siempre: la superficie de datos de salud almacenados crece sin control y sin política de borrado, que es justo lo que la LFPDPPP exige acotar. (2) Con el worker caído, el usuario ve un spinner eterno sin mensaje de error, y al día siguiente la tabla tiene decenas de filas `pending` que nadie limpia.

---

### B-REC-11 · Si Redis está caído, pedir un PDF devuelve 500 en vez de un job pendiente
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/pdfs/services.py:65`, `MailySoft/backend/apps/recetas/services.py:1290`
- **Qué dice la documentación:** el comentario del propio servicio explica la estrategia de resiliencia pensada: "si un job quedó PENDING/PROCESSING pero su mensaje se perdió (**worker caído/reinicio**), un re-pedido lo vuelve a encolar" (`apps/pdfs/services.py:52-55`). Cubre el worker caído, no el broker caído.
- **Qué hace el código:** la tarea se dispara con `transaction.on_commit(lambda: generate_pdf.delay(str(job.id)))` (`apps/pdfs/services.py:65-66`). Django ejecuta los callbacks de `on_commit` **de inmediato y en el mismo hilo** cuando no hay una transacción atómica envolvente. No la hay: `ATOMIC_REQUESTS` no está configurado (verificado: cero ocurrencias en `MailySoft/backend/config/`), `TenantMiddleware` solo envuelve el request en `transaction.atomic` en modo GUC `local`, que está apagado (§1.1.3), y ni las vistas ni `pdf_job_enqueue` llevan el decorador. Con el broker inaccesible, `.delay()` lanza la excepción de kombu sin capturar y sube como 500.
- **Consecuencia concreta:** una caída de Redis en Railway convierte "el PDF tarda un poco" en "**Error del servidor**" en la cara del médico que quiere imprimir la receta del paciente que tiene enfrente. Además la fila del job ya quedó creada en estado `pending`, así que cuando Redis vuelva el usuario tendrá que pedirlo otra vez (lo cual sí funciona, `apps/pdfs/services.py:56`) sin ninguna pista de que eso es lo que debe hacer.

---

### B-REC-12 · Un PDF de receta generado antes de la anulación se sigue sirviendo sin la marca de anulada
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/recetas/services.py:1281`, `MailySoft/backend/apps/recetas/pdf.py:446`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:120-122` describe la receta como "inmutable, con folio consecutivo… **Anular sí; editar no**". Regla dura 4 de `Maily360/CLAUDE.md`: "las recetas no se editan ni se borran: se corrigen con addendum o **se anulan con motivo**". El caché se justifica en el modelo con "como las recetas son INMUTABLES, el PDF de una (receta, formato) **nunca cambia**" (`apps/recetas/models.py:1079-1081`).
- **Qué hace el código:** el PDF **sí** cambia al anular: el contexto calcula `cancelled = prescription.status == PrescriptionStatus.CANCELLED` **en tiempo de render** (`pdf.py:444-446`) y los templates lo usan. Pero el caché es por `(tenant, cache_key)` con `cache_key = f"{prescription_id}|{format_id}|{layout}"` (`services.py:1230-1238`), sin ningún componente que refleje el estado, y `needs_enqueue = job.status != DONE` (`services.py:1281`) hace que un job `done` se reuse tal cual, sin regenerar. `prescription_cancel` no invalida ni borra los jobs de la receta (`services.py:747-845`: cero referencias a `PrescriptionPdfJob`).
- **Consecuencia concreta:** el médico emite la receta, imprime el PDF (se genera y se cachea), detecta que puso 500 mg donde iban 250 mg y **anula con motivo**. Cualquiera que vuelva a descargar el PDF de esa receta —desde el historial del expediente, o con el `job_id` que quedó abierto— obtiene el **PDF original, sin marca de anulada**, indistinguible de una receta válida. La anulación queda registrada en la bitácora y en la API, pero el documento que llega a la farmacia dice lo contrario. Único consuelo: el QR de ese mismo PDF sí responde `"estado": "anulada"` (`views_public.py:115-119`), porque se consulta en vivo.

---

### B-REC-13 · Las recetas no tienen dimensión de sucursal
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/recetas/models.py:383`, `MailySoft/backend/apps/recetas/selectors.py:363`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:234-235` incluye entre lo terminado "Multi-sucursal: sedes por clínica, asignación de personal a sedes, **alcance de agenda, finanzas y avisos por sede**" — nombra tres dominios y no menciona recetas, así que la ausencia no contradice el análisis, pero tampoco está declarada. La regla del módulo transversal sí es explícita: "**listados expuestos a roles acotados por sede usan `sucursal_scope_ids`**" (`apps/clinica/sucursal_scope.py:92-94`, §1.5.4).
- **Qué hace el código:** cero ocurrencias de "sucursal" en toda `apps/recetas/` y toda `apps/pdfs/` (verificado por búsqueda). `Prescription` no tiene FK a `Sucursal` (`models.py:383-568`), `prescription_list` filtra solo por paciente (`selectors.py:403`), y ninguna vista del módulo lee `X-Sucursal-Id` ni llama a `sucursal_scope_ids`.
- **Consecuencia concreta:** en una clínica con sede Centro y sede Norte, la `admin` de Norte —que no ve la agenda ni las finanzas de Centro— abre el expediente de un paciente de Centro y lee todas sus recetas, incluidos diagnóstico y medicamentos, y **puede anular cualquiera de ellas** (`services.py:797-800` da barra libre a `owner` y `admin`). El aislamiento por sede que sí existe en agenda y finanzas no existe aquí, y no hay forma de reconstruir después en qué sede se emitió una receta: el dato nunca se guardó.

---

### B-REC-14 · El autocompletado puede ocultar por completo los medicamentos propios de la clínica
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/recetas/selectors.py:139`
- **Qué dice la documentación:** el docstring promete unión de ambos catálogos: "Une los resultados de GlobalMedication (catálogo global) y Medication (custom de la clínica)" y "El frontend usa `source` para diferenciación visual" (`selectors.py:54-56`, `serializers.py:83`). El modelo justifica el catálogo custom como "autocompletado propio del médico" (`models.py:8`).
- **Qué hace el código:** cada catálogo se consulta y se **corta a `limit` por separado** (`selectors.py:97` y `:121`), después se concatenan, se ordenan alfabéticamente por `generic_name` y se **vuelve a cortar a `limit`** (`selectors.py:139-143`). Con `limit=25` (el default, `selectors.py:39`), si la búsqueda devuelve 25 resultados globales que ordenan antes alfabéticamente, los custom se quedan fuera del corte final.
- **Consecuencia concreta:** una clínica dio de alta "Vitamina D3 gotas 2000 UI" como medicamento custom porque no está en el catálogo global. El médico teclea "vit": salen 25 vitaminas del catálogo global y **la suya no aparece**, aunque la creó él. El médico concluye que el catálogo custom no sirve y vuelve a escribir el nombre a mano cada vez, lo que además rompe la trazabilidad de `medication_id` en el ítem de la receta.

---

### B-REC-15 · Código muerto en el módulo
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/recetas/services.py:405`, `MailySoft/backend/apps/recetas/views.py:576`, `MailySoft/backend/apps/core/permissions.py:1022`, `MailySoft/backend/apps/recetas/templates/recetas/prescription.html`, `MailySoft/backend/apps/recetas/models.py:557-567`
- **Qué dice la documentación:** el encargo de esta fase pide marcar "cada endpoint que exista en el código pero que nadie recuerde para qué sirve… el código muerto que sigue expuesto es superficie de ataque gratis". `MailySoft/docs/01-analisis.md:349-350` ya registra el mismo patrón para las dependencias (`xhtml2pdf`, `channels`).
- **Qué hace el código:** cinco piezas inalcanzables o sin uso. (1) La rama `elif raw_group in valid_groups` de `_resolve_item_controlled_groups` (`services.py:405-407`) no se puede alcanzar vía HTTP porque el serializer rechaza `controlled_group` en los ítems (ver B-REC-01). (2) El `data.pop("is_authorized", None)` de la vista de creación de formatos (`views.py:576-577`) es inalcanzable: `PrescriptionFormatCreateInputSerializer` no declara ese campo y su `validate` rechaza claves desconocidas (`serializers.py:826`), así que la petición muere en 400 antes de llegar ahí. (3) `PrescriptionFormatPermission._DOCTOR_ROLES` (`permissions.py:1022`) se declara y no se usa —ya registrado en §1.3.2 fila 35—. (4) El template `apps/recetas/templates/recetas/prescription.html` no lo referencia nadie: `_TEMPLATE_MAP` solo mapea `compact.html` y `digital.html` (`pdf.py:40-43`) y la búsqueda de `prescription.html` en todo `MailySoft/backend` no arroja resultados. (5) Los índices `rx_tenant_doctor_issued_idx` y `rx_tenant_status_idx` (`models.py:560-567`) no tienen ninguna consulta que los use: no existe listado de recetas por médico ni filtro por estado.
- **Consecuencia concreta:** cada pieza es barata por separado y cara en conjunto. Los dos índices sin consumidor cuestan escritura en **cada** emisión de receta sin devolver nada. El `prescription.html` huérfano es una plantilla que podría contener PII y que nadie revisa cuando se audita el render. Y las dos ramas muertas hacen creer, a quien lea el código para decidir si F6 funciona, que sí existe una vía para marcar controlados — que es exactamente el error que produjo B-REC-01.

---

### B-REC-16 · `GlobalMedication` no excluye registros con borrado lógico
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/recetas/models.py:129`, `MailySoft/backend/apps/recetas/selectors.py:92`
- **Qué dice la documentación:** §1.8.1 de `docs/_a2-partes/00-transversal.md` ya registra el patrón como B-T-04: un modelo que hereda solo de `BaseModel` "usa el manager por defecto de Django y **no** excluye soft-deleted automáticamente". `Maily360/CLAUDE.md` fija que "el borrado en API es lógico".
- **Qué hace el código:** `GlobalMedication(BaseModel)` (`models.py:129`) tiene `deleted_at` heredado pero no `TenantManager`, y `medication_search` filtra únicamente por `is_active=True` sin `deleted_at__isnull=True` (`selectors.py:92`). El catálogo custom `Medication` no tiene el problema porque hereda `TenantAwareModel` y su manager sí lo excluye (§1.1.5).
- **Consecuencia concreta:** es la instancia de B-T-04 en este módulo. Si algún día se retira un medicamento global marcando `deleted_at` en vez de `is_active=False` —que es la convención del resto del sistema—, el medicamento **sigue apareciendo en el autocompletado de todas las clínicas**. Hoy no muerde porque el único escritor es el seed, que nunca borra (`seed_medicamentos.py:487-496`); muerde el día que exista una pantalla de plataforma para mantener el catálogo.
## Finanzas

> Brechas detectadas al extraer el contrato de `apps/finanzas` (modo inverso, 2026-08-12).
> Cada una es una diferencia entre lo que la documentación dice, lo que el código promete en sus
> propios comentarios, y lo que el código hace. **No se corrigió nada**: este documento solo registra.
>
> Rutas relativas a la raíz del repo. Severidad propuesta, sujeta al triage de la fase A4.
>
> Resumen: **3 P0 · 9 P1 · 10 P2** = 22 brechas.

---

### B-FIN-01 · Se puede timbrar dos veces el mismo pago
- **Severidad propuesta:** P0
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:1117-1236` (todo `cfdi_issue`); FK en `MailySoft/backend/apps/finanzas/models.py:763-770`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:138` — *"Con el pago se puede emitir un CFDI 4.0, o cancelarlo con motivo"*, en singular. Nada advierte que un mismo pago admita varios comprobantes.
- **Qué hace el código:** `CfdiDocument.payment` es un `ForeignKey` con `related_name="cfdi_documents"` (plural), no un `OneToOneField`, y `cfdi_issue` **no comprueba en ningún punto** si el pago ya tiene un CFDI en estado `STAMPED`. Tampoco bloquea el pago con `select_for_update`. Dos POST a `/api/v1/finanzas/cfdi/` con el mismo `payment_id` —dos clics del usuario o dos pestañas— producen dos comprobantes, cada uno con su folio consecutivo y su `uuid_sat`.
- **Consecuencia concreta:** la clínica factura $3,000 y el SAT registra $6,000 a nombre del mismo paciente por el mismo cobro. Corregirlo exige cancelar uno de los dos comprobantes ante el SAT, con su motivo, y el paciente recibe dos facturas del mismo servicio. Hoy el daño está contenido porque el PAC es simulado (B-FIN-05 de CFDI, ver B-FIN-12); el día que se conecte un PAC real, esta brecha se convierte en un problema fiscal el primer día.

---

### B-FIN-02 · `quote_accept` sin bloqueo: dos aceptaciones concurrentes duplican los cargos
- **Severidad propuesta:** P0
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:600-623`
- **Qué dice la documentación:** el propio docstring del service afirma *"Es idempotente respecto a la generación: una cotización ya aceptada no vuelve a generar cargos"* (`services.py:594-595`).
- **Qué hace el código:** la guarda `if quote.status not in (DRAFT, SENT)` (`:600`) se evalúa sobre una instancia cargada por `selectors.quote_get` **sin `select_for_update`** y **antes** de abrir `transaction.atomic()` (`:604`). Dos peticiones simultáneas leen ambas `status="sent"`, ambas pasan la guarda, ambas entran a la transacción y ambas ejecutan el bucle que crea un `Charge` por cada `QuoteItem` (`:607-623`). La idempotencia prometida no existe: es una comprobación TOCTOU.
- **Consecuencia concreta:** la recepcionista de la sede Centro hace doble clic en "Aceptar" sobre una cotización de $18,000 con seis renglones. Se generan doce cargos por $36,000. El paciente ve el doble de deuda en su estado de cuenta, y como los cargos duplicados no tienen pagos aplicados sí se pueden cancelar uno a uno —pero alguien tiene que darse cuenta antes de cobrar.

---

### B-FIN-03 · La llamada al PAC ocurre dentro de la transacción de base de datos
- **Severidad propuesta:** P0
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:1154-1225` (el `atomic` abre en `:1154`, el `adapter.stamp()` se ejecuta en `:1185`)
- **Qué dice la documentación:** nada. El comentario del código solo cubre el caso feliz del rollback: *"transaction.atomic se revierte al elevar; el folio NO se consume"* (`services.py:1206`).
- **Qué hace el código:** dentro del mismo `transaction.atomic()` se toma un `select_for_update` sobre `ClinicFiscalConfig` (`:1156`) y después se hace la llamada de red al PAC (`:1185`). El lock de la fila de configuración fiscal se mantiene durante toda la petición HTTP externa, y no hay timeout declarado en ninguna parte del adapter. Además es un *dual write* sin compensación: si el PAC responde `success=True` y la transacción falla después —caída de la conexión a Postgres, deploy a mitad de la petición—, el comprobante queda timbrado ante el SAT y **sin ninguna fila en la base**.
- **Consecuencia concreta:** dos efectos. (1) Rendimiento: mientras una clínica timbra, cualquier otro timbrado de **esa misma clínica** espera bloqueado; con un PAC lento eso agota conexiones de la base. (2) Integridad fiscal: un CFDI existe en el SAT que el sistema no sabe que emitió, así que nadie lo puede cancelar desde la aplicación ni aparece en el reporte; se descubre en la declaración mensual.

---

### B-FIN-04 · La validación "no se permiten pagos a favor" corre fuera de la transacción y sin bloqueo
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:996-1012` (comprobación) frente a `:1014` (apertura del `atomic`)
- **Qué dice la documentación:** el comentario del código es categórico: *"No se permiten saldos a favor: el pago no puede exceder la deuda pendiente total del paciente"* (`services.py:996-997`). Más abajo, el mismo archivo se contradice: *"Lo que sobre (si pagó de más) queda como saldo a favor del paciente"* (`:1065`).
- **Qué hace el código:** `deuda_pendiente` se calcula sumando en Python el `balance` de los cargos `PENDING|PARTIAL` **antes** de abrir la transacción y **sin `select_for_update`**. Dos cobros concurrentes del mismo importe sobre el mismo paciente pasan los dos. El segundo entra al `atomic`, el `select_for_update` del bucle de auto-asignación (`:1070`) re-evalúa el filtro cuando se libera el lock, ya no encuentra cargos abiertos, y el pago se persiste **con cero `PaymentAllocation`**.
- **Consecuencia concreta:** el paciente paga $2,500 en la caja de Norte y, en el mismo minuto, alguien registra el mismo cobro desde Centro. Quedan dos `Payment` de $2,500, un solo cargo liquidado y un pago colgando sin aplicar. El cierre diario suma $5,000 de cobranza contra $2,500 de producción, el dashboard muestra un `collection_rate` del 200 % y el estado de cuenta del paciente arroja saldo negativo — el mismo saldo a favor que la validación dice impedir. Y como no hay forma de borrar un pago (B-FIN-09), no hay manera de arreglarlo desde la aplicación.

---

### B-FIN-05 · `quote_set_status` no valida el estado de origen: una cotización aceptada se puede rechazar
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:637-653`
- **Qué dice la documentación:** el modelo declara la máquina de estados `DRAFT → SENT → (ACCEPTED | REJECTED | EXPIRED)` (`MailySoft/backend/apps/finanzas/models.py:192-193`), en la que `ACCEPTED` es terminal.
- **Qué hace el código:** el service solo valida el **destino** (`if status not in {REJECTED, EXPIRED}`, `:639-641`) y nunca el origen. `PATCH /api/v1/finanzas/cotizaciones/<id>/` con `{"status": "rejected"}` funciona sobre una cotización ya aceptada. Los `Charge` que esa aceptación generó **no se tocan**: siguen `PENDING` y siguen contando como producción. Tampoco se impide `rejected → expired` ni la vuelta.
- **Consecuencia concreta:** una cotización de $40,000 se acepta, genera sus cargos, y luego alguien la marca "Rechazada" para limpiar la vista de cotizaciones. La deuda de $40,000 sigue viva en cuentas por cobrar sin ningún documento comercial que la respalde. Al revés también rompe: el reporte cuenta esa cotización como rechazada en el embudo de conversión (`selectors.py:665-668`) mientras su dinero está en el aging.

---

### B-FIN-06 · La vigencia de la cotización (`valid_until`) no se hace valer en ningún punto
- **Severidad propuesta:** P1
- **Dónde:** campo en `MailySoft/backend/apps/finanzas/models.py:225`; se guarda en `services.py:484`; se imprime en `MailySoft/backend/apps/finanzas/pdf.py:370`. **No aparece en ninguna comparación.**
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:134-135` — *"Recepción o el médico arma una cotización con renglones, descuento por monto o por porcentaje, y **vigencia**"*. Se presenta como una regla de negocio del flujo comercial.
- **Qué hace el código:** el campo se captura, se persiste y se imprime en el PDF, y ahí termina. `quote_accept` no lo compara contra la fecha actual (`services.py:591-634`), no existe ninguna tarea de Celery que marque cotizaciones vencidas —verificado: la app no tiene `tasks.py` ni entrada en Celery beat—, y el estado `EXPIRED` solo se alcanza si un humano lo pone a mano con un PATCH. Búsqueda de `valid_until` en todo `apps/`: en finanzas solo esos tres usos.
- **Consecuencia concreta:** una cotización con precios de enero y vigencia a 15 días se acepta en agosto sin ninguna resistencia del sistema, y genera cargos con el precio viejo. El "estado" de una cotización en el embudo del reporte nunca refleja las vencidas: la métrica de conversión (`selectors.py:665-669`) divide entre enviadas + aceptadas + rechazadas + vencidas, y ese último sumando es siempre lo que alguien haya marcado a mano.

---

### B-FIN-07 · Sin validación de cantidad ni precio: una línea negativa genera un cargo negativo
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:537-552` (`_create_quote_item`) y `:608-623` (`quote_accept`)
- **Qué dice la documentación:** nada sobre el signo. El modelo describe `line_total` como *"nunca negativo"* (`MailySoft/backend/apps/finanzas/models.py:391-392`) y `charge_create` sí exige monto positivo (`services.py:888-889`).
- **Qué hace el código:** `quantity` y `unit_price` llegan como dicts libres (`views.py:541`, `ItemSerializer` está declarado pero **no se usa**, `views.py:516-521`) y el service los convierte sin cota: `Decimal(str(raw.get("quantity", "1")))` (`:537`). Con un valor negativo, `base` es negativo; `_effective_discount` devuelve `ZERO` porque `max(ZERO, min(raw, base))` con `base < 0` colapsa a cero (`:110`); y `line_total = base − 0` **queda negativo**, contradiciendo el docstring del modelo. Al aceptar, `quote_accept` construye el `Charge` con `Charge.objects.create(amount=item.line_total)` **saltándose `charge_create`** (`:608-623`), así que la validación de monto positivo nunca se ejecuta.
- **Consecuencia concreta:** una cotización con un renglón de `quantity: -1` produce un cargo de monto negativo. Ese cargo entra como `PENDING`, su `balance` negativo **resta** de la deuda del paciente en `payment_register` (`:998-1007`) y baja la producción del reporte. Es una vía para fabricar un descuento que no queda registrado como descuento en ninguna parte, y para descuadrar el cierre diario sin tocar ningún permiso especial: basta con el rol `reception`.

---

### B-FIN-08 · `Charge.appointment` nunca se puebla: el filtro `?appointment=` y el desglose por doctor son código muerto
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/finanzas/views.py:773` (el campo se declara en el `InputSerializer`) frente a `:829-837` (la llamada al service que **no lo pasa**)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:136` — *"Al aceptarse se generan cargos (cuentas por cobrar), **que pueden colgar de una cita**"*. El propio código lo repite: el filtro está documentado como *"cargos ligados a una cita concreta (para el libro)"* (`views.py:763`) y el reporte promete un desglose *"por doctor (via `appointment__doctor`)"* (`selectors.py:732`).
- **Qué hace el código:** `ChargeListCreateApi.InputSerializer` acepta `appointment_id`, lo valida como UUID… y la vista nunca lo pasa a `services.charge_create`, que sí tiene el parámetro (`services.py:868`). El otro camino de creación, `quote_accept`, tampoco lo setea (`:608-623`). Verificado por búsqueda de `charge_create(` en todo `apps/`: los dos únicos llamadores de producción —la vista y `seed_finanzas.py:143`— omiten `appointment`. **Ningún cargo de producción tiene cita.**
- **Consecuencia concreta:** tres funciones prometidas que devuelven vacío o cero, en silencio. (1) El bloque "estado de cuenta de la visita" del libro clínico consulta `?appointment=<uuid>` y siempre recibe una lista vacía. (2) El desglose `by_doctor` del reporte financiero agrupa el 100 % de la producción bajo *"Sin cita (cobro manual / cotización)"* (`selectors.py:1010`): el dueño nunca puede ver cuánto produjo cada médico. (3) El backfill de sedes de la migración `0008` que intentaba deducir la sucursal del cargo desde su cita (`finanzas/migrations/0008_backfill_charge_payment_quote_sucursal.py:60-63`) no tuvo nada que backfillar por esa vía.

---

### B-FIN-09 · No existe forma de revertir un pago, y el error lo dice
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/finanzas/views.py:959-976` (`PaymentDetailApi` solo implementa GET); `MailySoft/backend/apps/core/permissions.py:443-446` (`FinancePaymentPermission` solo declara GET y POST); mensaje en `MailySoft/backend/apps/finanzas/services.py:927-929`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:166` lista como acción de `FinanzasPage` *"Registrar pagos, emitir y cancelar CFDI, exportar"* — no menciona corregir un pago. La regla dura nº 4 de `CLAUDE.md` protege **lo clínico**, no lo financiero.
- **Qué hace el código:** no hay PATCH, ni DELETE, ni ningún service de cancelación o reversa de `Payment`. Y `charge_cancel` rechaza cualquier cargo con dinero aplicado con el mensaje *"No se puede cancelar un cargo con pagos aplicados. **Cancela primero los pagos.**"* (`:927-929`) — una instrucción que apunta a una acción que la API no ofrece. `PaymentAllocation.charge` es `PROTECT` (`models.py:716`), así que tampoco hay salida por borrado en duro.
- **Consecuencia concreta:** recepción registra $5,000 en efectivo cuando eran $500, o lo carga al paciente equivocado. Ese pago queda para siempre: no se puede editar, no se puede borrar, el cargo que liquidó no se puede cancelar, y el estado de cuenta del paciente queda mal de forma permanente. La única salida hoy es que el equipo de plataforma entre al `/admin` de Django con superusuario y borre filas a mano —lo que además rompe `Charge.amount_paid` (B-FIN-18).

---

### B-FIN-10 · Un valor no numérico en un item o en una asignación devuelve 500, no 400
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:537-540` (`Decimal(str(raw.get("quantity", "1")))`) y `:1030` (`_q2(Decimal(str(raw.get("amount", "0"))))`)
- **Qué dice la documentación:** el contrato de errores de la capa transversal (§1.7.2 de `docs/_a2-partes/00-transversal.md`) solo contempla 400 para entradas inválidas.
- **Qué hace el código:** `items` y `allocations` viajan como `ListField(DictField())` sin esquema (`views.py:541`, `:908-910`), y el service convierte con `Decimal(str(...))`. Un valor como `"abc"` o `null` levanta `decimal.InvalidOperation`, que **no** es `django.core.exceptions.ValidationError` y por tanto no la atrapa el `except DjangoValidationError` de la vista (`views.py:611`, `:954`). La excepción sube sin manejar → **500**, con su traza en Sentry.
- **Consecuencia concreta:** cualquier bug del frontend que mande una cantidad vacía en una línea de cotización, o un importe no numérico en una asignación de pago, se ve como caída del servidor en lugar de como error de captura. El usuario no recibe ningún mensaje accionable y el ruido llega a Sentry como incidente.

---

### B-FIN-11 · El nombre único de paquete/concepto ignora el borrado lógico → IntegrityError 500
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/finanzas/models.py:450-455` (`finanzas_package_name_uniq`) y `:103-108` (`finanzas_concept_name_uniq`); comprobación previa en `services.py:733-736` y `:208-211`; soft-delete en `services.py:841-844`
- **Qué dice la documentación:** §1.8.3 de `docs/_a2-partes/00-transversal.md` fija la regla del proyecto: *"El borrado en API es lógico: se setea `deleted_at`… nunca `DELETE` físico"*.
- **Qué hace el código:** `UniqueConstraint(fields=["tenant", "name"])` **sin `condition=Q(deleted_at__isnull=True)`**, mientras que el service comprueba la colisión **excluyendo** los borrados (`all_objects.filter(..., deleted_at__isnull=True)`). Las dos capas usan criterios distintos: el service da vía libre y la base rechaza. Con paquetes es alcanzable de inmediato, porque `package_delete` sí hace soft-delete.
- **Consecuencia concreta:** el dueño da de baja el "Paquete Rejuvenecimiento 6 sesiones" y meses después lo vuelve a crear con el mismo nombre comercial. El service lo deja pasar, Postgres lanza `IntegrityError` y la API responde **500**. Desde la interfaz parece que el sistema se rompió; en realidad el nombre está ocupado por una fila invisible que nadie puede ver ni recuperar.

---

### B-FIN-12 · Cero validación de los datos fiscales del emisor y del receptor
- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:357-388` (`clinic_fiscal_config_update`), `:1148-1152` (única validación en `cfdi_issue`), `MailySoft/backend/apps/finanzas/views.py:335-340` y `:991-999` (los `InputSerializer`)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:142-143` lo señala como el riesgo principal del flujo comercial: *"Qué puede salir mal: que el CFDI se emita con datos fiscales mal capturados"*.
- **Qué hace el código:** la única barrera es `max_length`. `rfc` acepta 13 caracteres cualesquiera, `tax_regime` cinco, `postal_code` cinco, `cfdi_use` cinco, `payment_form` dos y `payment_method` tres — ninguno se contrasta contra los catálogos del SAT (`c_RegimenFiscal`, `c_UsoCFDI`, `c_FormaPago`), ni con expresión regular, ni con dígito verificador. `cfdi_issue` solo exige que el RFC del emisor no esté vacío (`:1149`) y que el receptor traiga RFC y razón social no vacíos (`:1151`). Contrasta con el resto del proyecto, que sí tiene validadores propios para la cédula profesional (`MailySoft/backend/apps/core/validators.py:35`).
- **Consecuencia concreta:** un `payment_method` capturado como `"PPP"` en vez de `"PPD"`, o un RFC con un dígito cambiado, se persiste sin queja y se envía al PAC. Con el adapter simulado el error no se ve nunca: el timbrado "tiene éxito" y el comprobante queda guardado como válido. Con un PAC real, el rechazo llega en la respuesta HTTP y el usuario ve un 400 genérico sin saber qué campo corregir.

---

### B-FIN-13 · Sin constraint único de folio fiscal
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/models.py:901-913` (el `Meta` de `CfdiDocument` declara dos índices y **ningún** `UniqueConstraint`); asignación en `services.py:1156-1159`
- **Qué dice la documentación:** el modelo describe `series` + `next_folio` como *"el folio interno consecutivo del comprobante"* (`models.py:121`).
- **Qué hace el código:** la unicidad depende exclusivamente del `select_for_update` sobre `ClinicFiscalConfig` en tiempo de ejecución. No hay `UniqueConstraint(tenant, series, folio)` ni sobre `uuid_sat`. Nada en la base impide dos comprobantes con el mismo folio si alguien crea un `CfdiDocument` por otra vía —`/admin` con superusuario, un management command futuro, una migración de datos.
- **Consecuencia concreta:** el consecutivo fiscal es un requisito de forma; si se duplica, la contabilidad de la clínica queda inconsistente y el error solo se descubre al conciliar. Es la clase de invariante que debe estar en la base, no solo en un service.

---

### B-FIN-14 · Un médico con `doctors_see_costs` lista los cargos pero recibe 403 al abrir uno
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/views.py:766` (lista usa `ChargeListPermission`) frente a `:855` (detalle usa `FinanceChargePermission`); definición de ambas en `MailySoft/backend/apps/core/permissions.py:546-587` y `:417-432`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:144` presenta el interruptor como una decisión binaria de la clínica: *"que un médico vea el estado de cuenta de su paciente cuando la clínica no quería (hay un interruptor por clínica, `doctors_see_costs`)"*. No sugiere que el permiso cambie entre listar y ver el detalle.
- **Qué hace el código:** `ChargeListPermission` contempla al doctor condicionado al flag (`permissions.py:582-583`); `FinanceChargePermission` usa `FINANCE_VIEW_ROLES` (`:428`), que **no incluye a doctor bajo ninguna condición**. Resultado: `GET /api/v1/finanzas/cargos/?patient_id=X` → 200; `GET /api/v1/finanzas/cargos/<id>/` sobre uno de esos mismos cargos → 403.
- **Consecuencia concreta:** la clínica enciende el interruptor para que el médico vea el adeudo de su paciente en consulta. El médico ve la lista de cargos y al hacer clic en uno recibe un error de permisos. Desde la interfaz parece un fallo intermitente; en realidad son dos clases de permiso que no se pusieron de acuerdo.

---

### B-FIN-15 · El detalle de concepto y paquete no se acota por sede; el listado sí
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/views.py:273-285` (`ConceptDetailApi._get_or_404`) y `:453-467` (`PackageDetailApi._get_or_404`), comparados con `:229` y `:405`
- **Qué dice la documentación:** la propia app fija el criterio en el helper: *"el DETALLE/ACCIÓN por id (GET/PATCH/DELETE/POST de una acción) debe acotar EXACTAMENTE igual [que el listado], o un admin acotado a una sede puede leer/operar objetos de OTRA sede por su id"* (`views.py:136-142`). Es la regla que sí se aplicó a cotizaciones, cargos, pagos y CFDI.
- **Qué hace el código:** el detalle de concepto y de paquete resuelve con `selectors.concept_get` / `package_get` y **no llama a `_scope_or_404`**, a diferencia de `_quote_get_scoped` (`:616`), `ChargeDetailApi._get_or_404` (`:866`), `PaymentDetailApi` (`:973`) y `_cfdi_get_scoped` (`:1056`). El listado sí filtra por disponibilidad de sede.
- **Consecuencia concreta:** en una clínica con dos sedes, un admin acotado a Norte no ve en su listado el servicio "Aplicación de toxina — Centro", pero si obtiene su UUID (por ejemplo desde el `concept` que devuelve un cargo del estado de cuenta compartido del paciente) puede leer su ficha y su precio. El impacto es bajo —un precio de catálogo, no datos clínicos ni dinero— pero es una excepción no declarada a una regla que el propio archivo enuncia.

---

### B-FIN-16 · El CFDI se emite con `subtotal == total`: no hay impuestos ni conceptos
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:1176-1177` (creación) y `:1200-1201` (payload al PAC)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:199` y `:241` describen el módulo como *"Facturación CFDI 4.0"*, sin matices sobre su alcance.
- **Qué hace el código:** `subtotal = payment.amount` y `total = payment.amount`, siempre. El payload enviado al adapter tiene 14 claves y **ninguna línea de concepto** ni nodo de impuestos (`:1186-1202`). Las claves SAT del catálogo (`ServiceConcept.sat_product_key` y `sat_unit_key`, `models.py:71` y `:80`), que el modelo describe como *"Requerida para CFDI"*, **nunca se leen**: verificado por búsqueda, solo aparecen en el modelo y en los serializers del catálogo.
- **Consecuencia concreta:** un CFDI 4.0 real exige el nodo `Conceptos` con `ClaveProdServ` y `ClaveUnidad` por línea, y `Impuestos` cuando aplican. Aunque los servicios médicos suelen ir exentos de IVA, el comprobante que se está construyendo hoy no es timbrable tal cual: falta la mitad de la estructura. La clínica captura sus claves SAT en el catálogo creyendo que sirven para algo.

---

### B-FIN-17 · Los endpoints analíticos devuelven `Decimal` fuera de serializer
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/selectors.py:445-452`, `:601-616`, `:928-962`, `:1120-1133`; vistas `views.py:1126`, `:1151`, `:1206`, `:1315`
- **Qué dice la documentación:** nada. El resto de la API pasa por `ModelSerializer` con `DecimalField`, cuyo formato de salida lo gobierna `COERCE_DECIMAL_TO_STRING`.
- **Qué hace el código:** dashboard, reporte de periodo, cierre diario y estado de cuenta devuelven **un `dict` crudo con instancias de `Decimal` dentro**, sin pasar por ningún serializer, así que la conversión a JSON la decide el encoder por defecto de DRF y no el código de la app. La ambigüedad está reconocida en la propia suite: el helper de tests se llama `_D` y su docstring dice *"Convierte un monto JSON (string o número, según COERCE_DECIMAL_TO_STRING)"* (`MailySoft/backend/apps/finanzas/tests/test_sucursal_finanzas.py:174`) — es decir, ni los tests saben qué forma tiene la respuesta. Además, `collection_rate` (`selectors.py:559`) y `collection_pct` (`:820`) son divisiones `Decimal/Decimal` sin cuantizar, con la precisión completa del contexto decimal. **NO VERIFICADO** el comportamiento exacto del encoder: `rest_framework` no está vendorizado en el repo y no se puede leer su fuente desde aquí; lo verificable es que ningún `DecimalField` de serializer interviene en esa ruta.
- **Consecuencia concreta:** dos contratos distintos para el mismo dato. `GET /finanzas/pagos/` devuelve `amount` con el formato del serializer, y `GET /finanzas/dashboard/` devuelve `total_income` con el del encoder. El frontend tiene que tratarlos distinto, y si el encoder convierte a `float` los montos grandes pierden exactitud justo en el lugar donde se muestran los totales del negocio.

---

### B-FIN-18 · Borrar un pago desde `/admin` deja `Charge.amount_paid` desincronizado
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/models.py:708-713` (`PaymentAllocation.payment` es `CASCADE`); `MailySoft/backend/apps/finanzas/admin.py:94-104` (`PaymentAdmin` y `PaymentAllocationAdmin` con borrado habilitado para superusuario, `:44-45`)
- **Qué dice la documentación:** el admin se declara como *"herramienta EXCLUSIVA del equipo interno… para soporte/auditoría"* (`admin.py:4-6`), sin advertencia sobre efectos colaterales.
- **Qué hace el código:** `Charge.amount_paid` es un campo **materializado** que solo mantiene `_apply_charge_status` desde `payment_register` (`services.py:1055-1056`, `:1091-1092`). No hay señal `post_delete` sobre `PaymentAllocation` que lo recalcule —`finanzas/cache.py:71` conecta señales para `Payment`, `Charge` y `Quote`, pero solo para invalidar caché, no para recalcular saldos. Borrar un `Payment` arrastra sus asignaciones en cascada y deja el cargo diciendo que cobró un dinero que ya no existe.
- **Consecuencia concreta:** es exactamente la salida de emergencia que hoy queda para arreglar B-FIN-09, y arreglarla por ahí deja el cargo en estado `PAID` con `amount_paid` apuntando a asignaciones inexistentes. El aging, el `outstanding` del dashboard y el estado de cuenta del paciente quedan mal, sin ningún rastro de por qué.

---

### B-FIN-19 · `_NO_TENANT` es una instancia de `Response` compartida entre peticiones
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/views.py:114-117`; se devuelve en 8 sitios (`:239`, `:345`, `:352`, `:416`, `:592`, `:810`, `:935`, `:1025`, `:1370`)
- **Qué dice la documentación:** nada.
- **Qué hace el código:** un único objeto `Response` creado a nivel de módulo y devuelto desde varias vistas. DRF le asigna `accepted_renderer`, `accepted_media_type` y `renderer_context` en `finalize_response` **sobre la misma instancia** en cada petición que la usa: es estado mutable compartido entre hilos del servidor.
- **Consecuencia concreta:** con Gunicorn multihilo, dos peticiones simultáneas que caigan en esta rama podrían pisarse los atributos de renderizado. El riesgo real es bajo porque la rama es casi inalcanzable —`TenantAPIView.check_permissions` ya responde 403 antes si no hay membresía (§1.1.2)—, pero es un patrón que no debe copiarse a una vista que sí se ejecute con frecuencia.

---

### B-FIN-20 · El panel de retención se recalcula entero en cada petición, sin caché ni cota temporal
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/retention.py:315` (`retention_panel_build`), `:151-214` (agregación sin cota), `:555-573` (`IN` con todos los pacientes activos)
- **Qué dice la documentación:** el propio endpoint lo admite: *"El endpoint puede tardar >200 ms en clínicas grandes… En v2 se añadirá caché de 1h o tarea Celery periódica"* (`views.py:1357-1358`).
- **Qué hace el código:** a diferencia del dashboard y del reporte, que sí pasan por `finance_cache_get_or_set` (`selectors.py:507`, `:757`), el panel de retención **no toca la caché**. La agregación base recorre **todo el histórico** de citas atendidas del tenant sin cota de fecha (`Max("starts_at")` / `Min("starts_at")`, `:196-197`), no solo el periodo analizado; después hay un bucle Python por paciente (`:219`), un ordenamiento en memoria de todos los gastos (`:248`) y, en las métricas, un `set` con todos los pacientes activos que se reinyecta como `patient_id__in` (`:555-573`). Detalle menor añadido: la recencia se calcula contra medianoche **UTC** (`:216`) mientras el proyecto opera en `America/Mexico_City` (§1.7), lo que puede desplazar un día la clasificación en los bordes.
- **Consecuencia concreta:** para 1-3 usuarios concurrentes y clínicas normales es perfectamente aceptable hoy — y por eso es P2, no P1. Lo que hay que dejar escrito es que **el coste crece con el histórico completo, no con lo que se consulta**: una clínica con cinco años de citas paga los cinco años en cada carga de la pestaña, y no hay TTL que amortigüe un refresco repetido.

---

### B-FIN-21 · El "folio" de la cotización son 8 caracteres del UUID, sin unicidad
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/views.py:732` y `MailySoft/backend/apps/finanzas/pdf.py:358` (`str(quote.id).replace("-","")[:8].upper()`)
- **Qué dice la documentación:** el PDF lo presenta al paciente como *"Folio"* y el comentario del código lo justifica como *"legible para el paciente"* (`pdf.py:357`).
- **Qué hace el código:** trunca el UUID a 8 dígitos hexadecimales (32 bits) y lo usa como identificador visible del documento y como nombre del archivo descargado. No es único ni por tenant ni globalmente, y no existe ningún campo de folio en el modelo `Quote` (`models.py:189-303`) — a diferencia de `CfdiDocument`, que sí tiene `series` + `folio`.
- **Consecuencia concreta:** dos cotizaciones distintas pueden mostrarse al paciente con el mismo "folio", y dos PDFs distintos descargarse con el mismo nombre de archivo, sobrescribiéndose en la carpeta de descargas. La probabilidad es baja para una clínica pequeña, pero el dato se usa como referencia de negocio en una conversación con el cliente ("le mando la cotización A3F91C2B"), que es justo donde una colisión cuesta caro.

---

### B-FIN-22 · `_create_quote_item` no revalida el tenant del concepto
- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/finanzas/services.py:530-535`, comparado con `_create_package_item` en `:679-683`
- **Qué dice la documentación:** el docstring del módulo declara la convención: *"Validación de aislamiento: `related.tenant_id == tenant.id` (defensa en profundidad sobre RLS)"* (`services.py:11-12`).
- **Qué hace el código:** la línea de paquete sí llama `_ensure_same_tenant(tenant=tenant, obj=concept, ...)` (`:683`); la línea de cotización **no**. Se apoya únicamente en que `ServiceConcept.objects` es el `TenantManager`. Dentro de un request eso basta, pero `quote_create` también se invoca desde `apps/expediente/services_calendarizacion.py:59` y desde `seed_finanzas.py`, y fuera del ciclo de request el `TenantManager` **no filtra por tenant a propósito** (§1.1.5).
- **Consecuencia concreta:** no hay una explotación conocida hoy —los dos llamadores alternativos operan sobre el tenant correcto—, pero es la única de las dos funciones hermanas que se queda con una sola barrera. Si mañana `quote_create` se llama desde una tarea de Celery, esa barrera desaparece y el `concept_id` del payload deja de estar acotado.
## Mi Consultorio y Personal

> Brechas encontradas al extraer §7 (`apps/clinica`, menos `sucursal_scope.py`) y §8
> (`apps/personal`, más la autorización de `/api/v1/miembros/`) el 2026-08-12.
> Ninguna se corrigió: este documento es inventario, no parche.
> Severidades: **P0** cruza tenants o pierde datos · **P1** rompe una función o permite escalar
> dentro del tenant · **P2** deuda, inconsistencia o código muerto.
>
> **Resultado del punto P0 encargado (quién restablece la contraseña de quién): cerrado.** No hay
> escalamiento — ver §8.3.3. Lo que sí quedó abierto es B-PER-08.

---

### B-CLI-01 · Reasignar sedes de un miembro ignora la jerarquía de roles

- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/clinica/views.py:1133` y `MailySoft/backend/apps/clinica/services.py:1382-1441`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:65-66` — "Los roles operativos se
  acotan por sucursal. El `owner` ve todas las sedes; todos los demás, incluido `admin`, solo las que
  tienen asignadas". La decisión del dueño del 2026-07-16, escrita en
  `MailySoft/backend/apps/tenancy/services.py:96-100`, añade que un actor no owner "nunca modifica a
  un dueño ni a otro admin, **de ninguna forma**".
- **Qué hace el código:** `MembershipSucursalesApi` resuelve la membresía objetivo con
  `membership_get` (`MailySoft/backend/apps/tenancy/selectors.py:191`), que **solo aísla por
  tenant** — existiendo `membership_get_in_scope` (`selectors.py:204`) justo al lado, que es el que
  usan el detalle y el avatar de miembro. El service `membership_sucursales_set` valida la
  diferencia simétrica contra `allowed_sucursales` del actor (`services.py:1421-1431`) y los dos
  anti-lockout, pero **nunca comprueba el rol del objetivo**.
- **Consecuencia concreta:** en una clínica con dos sedes, el administrador de Centro puede hacer
  `GET /api/v1/clinica/membresias/<id>/sucursales/` sobre la membresía del **dueño** o de su par de
  Norte, y con un `PUT` quitarle Centro. Contra el dueño el daño es cosmético (su alcance no depende
  de esta tabla), pero contra el otro admin es real: le corta el acceso a Centro. En `PATCH
  /api/v1/miembros/<id>/` esa misma persona ni siquiera vería que el otro admin existe (404).

---

### B-CLI-02 · Una sucursal desactivada desaparece y no hay forma de volver a activarla

- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/clinica/views.py:970` y `MailySoft/backend/apps/clinica/sucursal_scope.py:175-179`
- **Qué dice la documentación:** nada. `MailySoft/docs/01-analisis.md:51` solo dice que el dueño
  "administra sucursales".
- **Qué hace el código:** `GET /api/v1/clinica/sucursales/` devuelve `allowed_sucursales`, que filtra
  `is_active=True`. No hay query param `only_active` (a diferencia de `/clinica/equipo/`,
  `views.py:846`, y de `/personal/consultorios/`, `views.py:356`), y el selector "plano"
  `sucursal_list(only_active=False)` existe (`selectors.py:266`) pero **no lo usa ninguna vista**. La
  reactivación sí existe (`sucursal_activate`, `services.py:1212`) y se alcanza con
  `PATCH /clinica/sucursales/<id>/ {"is_active": true}`, que resuelve el id contra
  `actor_sucursal_ids` (sí incluye inactivas).
- **Consecuencia concreta:** una clínica con dos sedes desactiva Norte por remodelación. Norte
  desaparece del selector y de todo listado. Para reabrirla, el dueño necesita el UUID de Norte, que
  ninguna respuesta de la API le devuelve ya. Si el front no lo guardó, la sede solo se recupera
  desde `/admin/` o con SQL — y mientras tanto sigue consumiendo cupo de `max_sucursales`
  (B-CLI-12).

---

### B-CLI-03 · No se puede borrar el logo, los membretes, el sello ni la foto

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/services.py:227-232` y `MailySoft/backend/apps/clinica/services.py:542-550`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** los serializers declaran `allow_null=True` en `logo`, `letterhead_full`,
  `letterhead_half` (`serializers.py:174`, `:191-192`), `sello` y `foto` (`serializers.py:435-436`),
  así que enviar `null` pasa la validación. Pero los services solo asignan el campo
  `if <imagen> is not None`, de modo que el `null` **se descarta en silencio** y la imagen anterior
  se conserva. `doctor_credential_update` sí lo hace bien, con un `logo_provided` explícito
  (`services.py:812-814`).
- **Consecuencia concreta:** una clínica que cambia de identidad visual y quiere quedarse **sin**
  membrete (para imprimir sobre papel preimpreso) no puede: la API devuelve 200 y el PDF sigue
  saliendo con el membrete viejo. La única salida es subir una imagen en blanco. Además, cada
  reemplazo deja el archivo anterior huérfano en Cloudinary; nadie lo borra.

---

### B-CLI-04 · El catálogo de equipo no tiene guard de módulo

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/views.py:839` y `MailySoft/backend/apps/clinica/views.py:886`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:194` lista el módulo `personal` como
  "Doctores, consultorios, horarios, **equipo**".
- **Qué hace el código:** `ClinicTeamMemberListCreateApi` y `ClinicTeamMemberDetailApi` declaran
  `permission_classes = [IsAuthenticated, ClinicTeamPermission]` — sin `RequiresPersonal` ni ningún
  otro `RequiresX`. La única importación de `entitlement_guards` en toda la app es
  `assert_within_limit` (`services.py:40`). Las seis rutas de `apps/personal` sí llevan el guard
  (`apps/personal/views.py:74`, `:189`, `:329`, `:420`, `:557`, `:672`).
- **Consecuencia concreta:** una clínica en un plan sin el módulo `personal` (hoy solo el plan `solo`,
  `seed_planes.py:73`, que está apagado) recibiría 404 en doctores y consultorios pero **200** en
  `/clinica/equipo/`. Rompe la regla dura 3 del proyecto ("un módulo apagado responde 404"): la
  clínica ve que existe una función que no compró. Hoy el impacto es teórico porque el único plan sin
  `personal` está desactivado.

---

### B-CLI-05 · La validación de credenciales no acota por sede y la bandeja no pagina

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/views.py:771-785` y `MailySoft/backend/apps/clinica/views.py:797-826`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:169` — "La bandeja de validación de
  credenciales es de Owner/Admin".
- **Qué hace el código:** tres cosas.
  1. El rol se compara a mano contra los literales `("owner","admin")` en vez de usar una clase de
     permiso — es la brecha transversal **B-T-08** (§1.3.6), aquí solo se confirma.
  2. `doctor_credentials_for_tenant` (`selectors.py:167-171`) devuelve **todas** las credenciales
     activas del tenant en un array plano, sin paginador.
  3. Ni la bandeja ni `PATCH /clinica/credenciales/<id>/validar/` acotan por sede:
     `doctor_credential_get` (`selectors.py:191`) solo aísla por tenant.
- **Consecuencia concreta:** el administrador de Centro valida (o rechaza, con motivo) la cédula de
  especialidad de un médico que solo trabaja en Norte y al que no conoce. Y en una clínica con 20
  médicos a 4 credenciales cada uno, la bandeja devuelve 80 objetos en una sola respuesta, cada uno
  con su URL de logo.

---

### B-CLI-06 · El tope de líneas del membrete no coincide entre serializer y modelo

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/serializers.py:193-194` contra `MailySoft/backend/apps/clinica/models.py:215-230`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** el modelo declara `MaxValueValidator(200)` con el comentario "Máximo 200
  (anti-DoS: evita generar PDFs con alturas descomunales)"; el serializer de entrada acota a
  `max_value=100`. Como la única puerta de escritura es el serializer, el tope real es 100 y el
  validador del modelo nunca se alcanza por API.
- **Consecuencia concreta:** ninguna hoy. Es una discrepancia que hará dudar al siguiente que lea el
  modelo y crea que 200 es el límite. Mismo caso al revés que la migración
  `0003_add_max_value_validator_letterhead_spaces.py`, que existe precisamente para poner ese tope.

---

### B-CLI-07 · La unicidad de nombre de sucursal no excluye los registros soft-borrados

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/models.py:734-737` (migración `0016_sucursal_membershipsucursal_and_more.py:182-187`) contra `MailySoft/backend/apps/clinica/services.py:1111`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** el service comprueba duplicados con `deleted_at__isnull=True`, es decir
  ignora los soft-borrados; la constraint de base de datos `sucursal_tenant_name_uniq` es
  incondicional. Los demás modelos de la app sí condicionan la constraint
  (`clinic_settings_tenant_active_uniq`, `clinic_category_tenant_name_active_uniq`,
  `doctor_membership_active_uniq`). `Consultorio` tiene exactamente el mismo desajuste
  (`apps/personal/models.py:216-219` contra `apps/personal/services.py:528-532`).
- **Consecuencia concreta:** hoy inalcanzable, porque ninguna ruta pone `deleted_at` en una
  `Sucursal` (el DELETE solo desactiva). El día que alguien agregue el borrado lógico de sedes —o lo
  haga a mano en producción—, recrear "Sucursal Norte" pasará la validación del service y reventará
  con `IntegrityError` → **500**, no 400.

---

### B-CLI-08 · Las asignaciones de sede se borran en duro

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/services.py:1444-1446`
- **Qué dice la documentación:** la regla del proyecto, en `MailySoft/backend/apps/core/models.py:51`
  y en la sección de modelos base: "El borrado en API es lógico: se setea `deleted_at` o un
  `is_active`, nunca `DELETE` físico".
- **Qué hace el código:** `membership_sucursales_set` hace
  `MembershipSucursal.all_objects.filter(...).exclude(sucursal_id__in=unique_ids).delete()` — borrado
  físico, aunque el modelo hereda `deleted_at` y el selector `membership_sucursales_list` filtra por
  él (`selectors.py:308-311`), lo que sugiere que se esperaba soft-delete.
- **Consecuencia concreta:** no queda rastro en la tabla de que a alguien se le quitó una sede; solo
  la bitácora `MEMBERSHIP_SUCURSALES_SET` guarda la lista resultante. Si un admin le corta Centro a
  otro admin (B-CLI-01), reconstruir quién tenía qué antes exige leer la bitácora entrada por
  entrada.

---

### B-CLI-09 · Código muerto en la app clinica

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/selectors.py:266`, `MailySoft/backend/apps/clinica/selectors.py:46`, `MailySoft/backend/apps/clinica/services.py:113`, `:121`, `:125`, `MailySoft/backend/apps/clinica/models.py:453-461`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** verificado por búsqueda en todo `MailySoft/backend` excluyendo tests, nadie
  usa:
  - `sucursal_list()` — el listado plano de sedes, que es justo lo que haría falta para B-CLI-02.
  - `clinic_settings_get_strict()` — variante que lanza `DoesNotExist`.
  - `_SETTINGS_IMMUTABLE`, `_CATEGORY_IMMUTABLE`, `_DOCTOR_EXTRA_IMMUTABLE` — tres frozensets de
    campos inmutables que ningún service consulta (los que sí se usan son `_TEMPLATE_IMMUTABLE`,
    `_TEAM_MEMBER_IMMUTABLE` y `_SUCURSAL_IMMUTABLE`).
  - `DoctorUniversity.clean()` lee `self._doctor_cache_tenant_id`, atributo que **nadie escribe**:
    la validación es un no-op permanente.
- **Consecuencia concreta:** los tres frozensets muertos son los peligrosos: quien lea
  `_SETTINGS_IMMUTABLE` supondrá que el upsert de configuración protege `tenant_id` y `created_by`,
  y no es cierto — lo que los protege es que el serializer de entrada no los declara. Si alguien
  añade un campo al serializer creyendo que el frozenset lo cubre, abre un mass-assignment.

---

### B-CLI-10 · Una etiqueta de paciente desactivada bloquea su nombre para siempre

- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/clinica/models.py:389-394` contra `MailySoft/backend/apps/clinica/services.py:469-470`
- **Qué dice la documentación:** nada. `MailySoft/docs/01-analisis.md:162` solo menciona "etiquetas"
  en la pantalla de pacientes.
- **Qué hace el código:** la constraint de unicidad es `(tenant, name) WHERE deleted_at IS NULL`,
  pero la baja de la API (`patient_category_deactivate`) pone `is_active=False` y **deja
  `deleted_at` en NULL**. El listado filtra `is_active=True` (`selectors.py:118`) y
  `PatientCategoryDetailApi` solo implementa `delete` (`views.py:367`): no hay PATCH ni reactivación.
- **Consecuencia concreta:** la clínica crea la etiqueta "Convenio IMSS", la desactiva por error y
  ya no puede volver a crearla: `POST /clinica/categorias/` responde 400 "Ya existe una categoría con
  el nombre 'Convenio IMSS' en esta clínica" mientras la etiqueta no aparece en ninguna lista. Es un
  callejón sin salida visible desde la interfaz, y solo se sale con SQL o desde `/admin/`.

---

### B-CLI-11 · Recepción y finanzas no pueden leer la configuración de la clínica

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/permissions.py:37-40`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:169` dice que `MiConsultorioPage` es
  de "Owner, Admin (Médico en lo suyo)" — es decir, coincide en que recepción y finanzas no
  configuran. No dice nada sobre si necesitan **leer** el logo o el nombre comercial.
- **Qué hace el código:** `ClinicSettingsPermission.policy["GET"] = CLINICAL_READ`, que es
  `{owner, admin, doctor, nurse, readonly}` (§1.3). Recepción y finanzas reciben **403** en
  `GET /api/v1/clinica/configuracion/`. Es el único endpoint de lectura de la app cerrado a esos dos
  roles: el catálogo de categorías, el de sucursales y el perfil médico están abiertos a los siete.
- **Consecuencia concreta:** **NO VERIFICADO** — el impacto real depende de si `web-soft` pide ese
  endpoint para pintar la cabecera o la vista previa de una cotización, y este trabajo no leyó
  `MailySoft/web-soft/`. Si lo pide sin condicionar por rol, la recepcionista y la persona de
  finanzas ven un 403 en consola y, en el peor caso, una cabecera sin logo. Vale la pena revisarlo
  antes de decidir si se amplía el permiso o se corrige el front.

---

### B-CLI-12 · Las sucursales desactivadas siguen consumiendo el cupo del plan

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/services.py:1116-1120`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:203` — "Multi-sucursal no es un
  módulo: es el límite `max_sucursales` del plan". No dice cómo se cuenta.
- **Qué hace el código:** el conteo es
  `Sucursal.all_objects.filter(tenant=tenant, deleted_at__isnull=True).count()` — filtra por
  `deleted_at`, no por `is_active`. Como el DELETE de la API solo desactiva, una sede dada de baja
  sigue contando. `max_consultorios` tiene exactamente el mismo criterio
  (`apps/personal/services.py:537-541`) → B-PER-07.
- **Consecuencia concreta:** una clínica Premium que baja a Pro (`max_sucursales=1`,
  `seed_planes.py:122`) y desactiva Norte para cumplir, sigue con dos filas contadas y no puede
  crear ninguna sede nueva. Combinado con B-CLI-02 —que le impide siquiera ver Norte para
  entenderlo— el mensaje "el plan permite 1 sucursales y ya hay 2" resulta incomprensible desde la
  interfaz.

---

### B-CLI-13 · El docstring de `Sucursal` cita una migración que no existe

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/models.py:682`
- **Qué dice la documentación:** el propio docstring: "cada tenant tiene una única 'Sucursal
  Principal' (`is_default=True`) creada por la migración de backfill 0019".
- **Qué hace el código:** `apps/clinica/migrations/` llega hasta `0018_rls_membership_sucursales.py`.
  El backfill real es `MailySoft/backend/apps/personal/migrations/0009_backfill_sucursal_principal.py:54-63`,
  que además asigna consultorios, `Doctor.sucursales` y `MembershipSucursal`.
- **Consecuencia concreta:** menor, pero cuesta tiempo: quien investigue por qué una clínica tiene
  esa sede buscará en la app equivocada. Importa más de lo que parece porque esa migración es la que
  explica por qué **todos** los registros previos a multi-sede tienen sede y los creados después
  pueden no tenerla — que es la raíz de B-PER-02.

---

### B-CLI-14 · Dos índices sin ninguna consulta que los justifique

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/clinica/models.py:604-607` y `MailySoft/backend/apps/clinica/models.py:258-260`
- **Qué dice la documentación:** nada.
- **Qué hace el código:**
  - `cred_tenant_doctor_kind_idx (tenant, doctor, kind)`: ningún selector ni service filtra
    `DoctorCredential` por `kind` (verificado en `apps/clinica` y `apps/recetas`). Las dos consultas
    reales filtran por `doctor` (`selectors.py:150`) o por `validation_status`
    (`apps/recetas/pdf.py:301-306`), y ya las cubre `cred_tenant_doctor_idx`.
  - `ClinicSettings.doctors_see_costs` con `db_index=True`: la tabla tiene **una fila por clínica** y
    la única consulta que existe busca por `tenant_id` (`apps/core/permissions.py:461`).
- **Consecuencia concreta:** cada alta o edición de credencial paga la escritura de un índice que
  nadie lee, y cada `PUT` de configuración lo mismo. Con el volumen actual (1-3 usuarios) es
  irrelevante en tiempo; se anota porque el criterio del contrato es que un índice sin consulta que
  lo necesite es peso muerto, y estos dos son ejemplos limpios para quitar de una sola migración.

---

### B-PER-01 · El detalle de un médico no se acota por sede, a diferencia del listado

- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/personal/views.py:240-248` y `MailySoft/backend/apps/personal/selectors.py:38-42`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:65-66` — "Los roles operativos se
  acotan por sucursal. El `owner` ve todas las sedes; todos los demás, incluido `admin`, solo las que
  tienen asignadas".
- **Qué hace el código:** `DoctorListCreateApi.get` acota siempre con `sucursal_scope_ids(request)`
  (`views.py:118`), y el docstring dice explícitamente que ese es el cierre del "Objetivo A" de
  seguridad. Pero `DoctorDetailApi._get_doctor_or_404` llama a `doctor_get(doctor_id=...)` **sin**
  `sucursal_ids`, y ese selector solo aísla por tenant. Los dos hermanos de la misma app sí lo hacen
  bien: `consultorio_get(..., sucursal_ids=...)` (`views.py:453-456`) y
  `schedule_get(..., sucursal_ids=...)` (`views.py:684-687`), ambos con el razonamiento escrito al
  lado. `doctor_get` ni siquiera acepta el parámetro.
- **Consecuencia concreta:** el administrador de Centro no ve al médico de Norte en la lista, pero si
  obtiene su `doctor_id` por cualquier vía (una cita antigua, una receta, la bandeja de credenciales
  de B-CLI-05) puede hacer `GET` de su ficha completa, `PATCH` de su cédula profesional y, sobre
  todo, `DELETE` — que lo desactiva y lo deja sin poder recetar ni recibir citas en Norte. Es la
  misma clase de hueco que los cierres A4/A5 arreglaron para consultorios y horarios, y que aquí se
  quedó abierta.

---

### B-PER-02 · Un médico sin sedes asignadas desaparece de todos los listados acotados

- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/personal/selectors.py:81-82` contra `MailySoft/backend/apps/personal/models.py:109-118`
- **Qué dice la documentación:** el propio modelo: "Sucursales donde ESTE médico puede atender
  (multi-sede — Fase 1). **Vacío = sin restricción** (compatibilidad retro: clínicas de una sola sede
  no necesitan asignar nada)". El service lo repite: "Una lista vacía elimina todas las restricciones
  de sucursal para ese médico (puede atender en cualquier sede del tenant)"
  (`MailySoft/backend/apps/personal/services.py:370-372`).
- **Qué hace el código:** el filtro del listado es `qs.filter(sucursales__id__in=sucursal_ids)`, un
  `INNER JOIN` sobre la tabla intermedia: **un médico sin ninguna fila no puede casar nunca**.
  "Vacío" no significa "todas": significa "ninguna". `consultorio_list`
  (`selectors.py:155-156`) y `schedule_list_for_doctor` (`selectors.py:230-231`) tienen el mismo
  problema con `sucursal_id__in` sobre una FK nullable: los registros con `sucursal = NULL` quedan
  fuera.
- **Consecuencia concreta:** la clínica con dos sedes tiene un médico que rota entre ambas y decide
  no restringirlo: le manda `PATCH /personal/doctores/<id>/ {"sucursal_ids": []}`, que la API acepta
  y documenta como "sin restricción". A partir de ese momento **ese médico no aparece en ninguna
  lista** para nadie que tenga alcance parcial ni para quien seleccione una sede en el header —
  incluido el dueño. La agenda queda sin poder seleccionarlo. La única forma de que reaparezca es
  volver a asignarle sedes explícitamente, o quitar el header y ser owner. Lo mismo aplica a un
  consultorio creado antes de que la clínica tuviera sedes.

---

### B-PER-03 · El alta de personal no obliga a cambiar la contraseña inicial

- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/tenancy/services.py:268-274`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:97` — "El dueño da de alta a su
  equipo creando cuentas con contraseña inicial. **No hay invitación por correo.**" Y
  `MailySoft/docs/01-analisis.md:102` nombra el riesgo textualmente: "Qué puede salir mal: … que la
  contraseña temporal se comparta por WhatsApp y nadie la cambie."
- **Qué hace el código:** `member_create` construye el `User` con `email`, `first_name`, `last_name`,
  `is_active=True` e `is_platform_staff=False`, y **no toca `must_change_password`**, que queda en su
  default `False` (`MailySoft/backend/apps/authn/models.py:77-78`). Los dos flujos equivalentes de
  plataforma sí lo encienden: alta de clínica (`apps/plataforma/services.py:283-284`) y alta de staff
  interno (`apps/plataforma/services.py:1061`). El candado de §1.2.4 existe y funciona; nadie lo
  arma para el personal de la clínica.
- **Consecuencia concreta:** el dueño da de alta a la recepcionista tecleando "Clinica2026", se lo
  manda por WhatsApp y esa contraseña sigue siendo válida un año después. El sistema **nunca** se lo
  pide cambiar: no hay pantalla de cambio forzado, no hay caducidad, no hay aviso. El dueño la
  conoce, el grupo de WhatsApp también, y la bitácora atribuirá a la recepcionista todo lo que se
  haga con esa cuenta. Es el mismo riesgo que el análisis anticipó y que el código mitiga en los
  otros dos flujos de alta.

---

### B-PER-04 · Un médico o un consultorio desactivado no se puede reactivar por API

- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/personal/services.py:50-64` y `MailySoft/backend/apps/personal/views.py:422-439`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:164` — `PersonalPage` permite "CRUD
  de personal y consultorios". Un CRUD implica poder deshacer una baja.
- **Qué hace el código:**
  - `Doctor`: `is_active` está en `_DOCTOR_IMMUTABLE_FIELDS`, así que `doctor_update` lo rechaza con
    400 ("FIX-F1: evita backdoor de activación/desactivación por PATCH"), y el `InputSerializer` ni
    siquiera lo declara (`views.py:217-220`). Existe `doctor_deactivate` (`services.py:204`) pero
    **no existe `doctor_activate`**.
  - `Consultorio`: `is_active` **no** está en `_CONSULTORIO_IMMUTABLE_FIELDS` (`services.py:70-72`),
    pero el `InputSerializer` del PATCH no lo expone, así que tampoco hay manera de enviarlo. Existe
    `consultorio_deactivate` y no `consultorio_activate`.
  - Ambos listados sí saben mostrarlos: `?only_active=false` (`views.py:115-116`, `:356-357`).
  - Contraste: `Sucursal` y `ClinicTeamMember` **sí** tienen su service de activación
    (`apps/clinica/services.py:1212`, `:1014`).
- **Consecuencia concreta:** una recepcionista da de baja por error el consultorio "Box 2" de Norte.
  El dueño lo ve en la lista con `only_active=false`, pero no hay ningún endpoint que lo devuelva a
  activo. Además, mientras siga desactivado sigue consumiendo cupo del plan (B-PER-07) y
  `doctor_set_consultorios` rechaza asignarlo (`services.py:299-302`). Lo mismo con un médico
  desactivado por error: hay que ir a `/admin/` o a la base de datos.

---

### B-PER-05 · El alta de un perfil de médico no comprueba la sede de la membresía

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/personal/views.py:146-166`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:65-66` (alcance por sucursal).
- **Qué hace el código:** `DoctorListCreateApi.post` resuelve el `membership_id` con `membership_get`
  (tenant-scoped, `apps/tenancy/selectors.py:191`) y `doctor_create` valida el rol
  (`ROLES_QUE_PUEDEN_EJERCER`), el tenant y el duplicado — **nada sobre sedes**. `apps/tenancy` sí
  tiene `membership_get_in_scope` para este caso exacto.
- **Consecuencia concreta:** el administrador de Centro puede crear el perfil profesional de una
  persona que solo trabaja en Norte, fijándole cédula, especialidad y duración de cita. El perfil
  nace **sin sedes asignadas**, con lo que además cae directamente en B-PER-02 y no aparece en ningún
  listado acotado. Impacto acotado porque no expone datos, pero es la puerta de entrada a B-PER-01.

---

### B-PER-06 · Los horarios no se editan, no se reactivan y no comprueban solapamiento

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/personal/views.py:669` y `MailySoft/backend/apps/personal/services.py:695-698`
- **Qué dice la documentación:** nada específico. `MailySoft/docs/01-analisis.md:194` incluye
  "horarios" en el módulo `personal`.
- **Qué hace el código:** `DoctorScheduleDetailApi` solo implementa `delete`, así que `GET` y `PATCH`
  sobre `/api/v1/personal/horarios/<id>/` devuelven **405**; no existe `schedule_update` ni
  `schedule_activate`. Y el propio service escribe el TODO: "En v1 no se valida solapamiento entre
  bloques de horario del mismo día. TODO(v2): validar que no existan bloques solapados para el mismo
  doctor/día."
- **Consecuencia concreta:** para corregir un "L 9:00-14:00" que debía ser "L 9:00-13:00" hay que
  borrarlo y crearlo de nuevo, y el borrado es irreversible. Peor: nada impide crear "L 9:00-14:00" y
  "L 13:00-18:00" para el mismo médico en dos consultorios de sedes distintas, con lo que el motor de
  disponibilidad ofrece esa hora en las dos sedes a la vez. El anti-empalme de citas existe (§ agenda)
  y compensa parcialmente, pero la disponibilidad publicada ya es incorrecta.

---

### B-PER-07 · Los consultorios desactivados siguen consumiendo el cupo del plan

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/personal/services.py:537-541`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:208-213` lista `max_consultorios` por
  plan sin explicar cómo se cuenta.
- **Qué hace el código:** igual que B-CLI-12: el conteo filtra por `deleted_at__isnull=True`, no por
  `is_active`, así que un consultorio desactivado cuenta.
- **Consecuencia concreta:** una clínica en plan Básico (`max_consultorios=1`, `seed_planes.py:102`)
  que crea "Consultorio 1", lo desactiva porque se equivocó en el nombre e intenta crear
  "Consultorio A", recibe 400: "El plan de esta clínica permite 1 consultorios y ya hay 1". Y como no
  puede reactivar el primero (B-PER-04) ni renombrarlo sin reactivarlo, se queda atascada sin ningún
  camino desde la interfaz.

---

### B-PER-08 · Restablecer la contraseña de un empleado no cierra su sesión

- **Severidad propuesta:** P1
- **Dónde:** `MailySoft/backend/apps/tenancy/services.py:425-436`
- **Qué dice la documentación:** nada en `01-analisis.md`. Pero el propio código documenta el patrón
  correcto **dos veces**: `MailySoft/backend/apps/authn/services.py:75-76` ("Invalidar sesiones
  activas emitidas antes del cambio — mismo patrón que `platform_staff_password_reset`") y
  `MailySoft/backend/apps/plataforma/services.py:1277-1280` ("Invalidar sesiones activas:
  blacklistear todos los refresh tokens vigentes emitidos para este usuario").
- **Qué hace el código:** `member_update` con `password` hace `validate_password`, `set_password`,
  `save(update_fields=["password"])` y audita `MEMBER_PASSWORD`. No blacklistea nada y no enciende
  `must_change_password`. Con `ROTATE_REFRESH_TOKENS=False` (§1.2.1), el refresh de 7 días del
  usuario objetivo sigue siendo válido y le permite renovar su access token indefinidamente durante
  esa semana.
- **Consecuencia concreta:** la clínica despide a la recepcionista de Centro y el administrador le
  "cambia la contraseña" creyendo que la deja fuera. La recepcionista sigue dentro hasta 7 días: su
  cookie `maily_refresh` no se invalidó y puede seguir consultando pacientes y agenda. La acción que
  sí funciona de inmediato es `PATCH /api/v1/miembros/<id>/ {"blocked": true}`, porque SimpleJWT
  rechaza el token de un usuario con `is_active=False` — pero nada en la API le dice al administrador
  que esa es la opción correcta, y la interfaz ofrece las dos como equivalentes
  (`MailySoft/docs/01-analisis.md:164`: "bloqueo de cuentas, restablecer contraseña").

---

### B-PER-09 · El módulo `personal` del catálogo no coincide con la app `personal`

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/core/modules.py:24` frente a `MailySoft/backend/apps/clinica/urls.py:116-124` y `MailySoft/backend/apps/agenda/views.py:784`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:194` define el módulo `personal` como
  "Doctores, consultorios, horarios, **equipo**". `MailySoft/docs/01-analisis.md:164` mete en la
  pantalla `PersonalPage` también los **tipos de cita**.
- **Qué hace el código:** el catálogo de **equipo** vive en `apps/clinica` y no lleva guard
  (B-CLI-04). Los **tipos de cita** viven en `apps/agenda` (`AppointmentType`,
  `apps/agenda/models.py:173`), con `AppointmentTypePermission` y el guard `RequiresAgenda`. El
  **alta de personal**, el bloqueo y las contraseñas viven en `apps/tenancy` y **no llevan ningún
  guard de módulo** (§1.9). La app `personal` solo contiene doctores, consultorios y horarios.
- **Consecuencia concreta:** una clínica que contrate `personal` pero no `agenda` verá la pantalla de
  Personal a medias: podrá gestionar médicos y consultorios pero recibirá 404 en tipos de cita, sin
  ninguna pista de por qué. Y al revés: apagar el módulo `personal` no apaga el alta de personal, que
  es lo que el nombre del módulo promete. El contrato tiene que decir explícitamente que "módulo
  `personal`" ≠ "gestión de personal", o alguien construirá contra la promesa equivocada.

---

### B-PER-10 · El plan `solo` deja al médico individual sin poder recetar

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/tenancy/management/commands/seed_planes.py:73-77` y `MailySoft/backend/apps/personal/views.py:74`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:210` describe el plan Solo como "Para
  el médico que trabaja por su cuenta", con módulos clínicos incluidos (agenda, expediente, recetas).
- **Qué hace el código:** el plan `solo` trae `modules = _CLINICO` (agenda, recordatorios,
  expediente, recetas, notas) y **no incluye `personal`**. Como las seis rutas de `apps/personal`
  llevan `RequiresPersonal`, ese médico recibe 404 al intentar crear su propio perfil `Doctor`. Y sin
  perfil no hay `cedula_profesional`, que es lo único que autoriza emitir una receta
  (`MailySoft/backend/apps/recetas/services.py:519`).
- **Consecuencia concreta:** un médico en plan Solo puede agendar y escribir notas pero **no puede
  emitir una sola receta**, que es la razón por la que compró el software. Hoy el impacto es cero
  porque el plan nace apagado a propósito (`seed_planes.py:83`, con la justificación comercial
  escrita). Si alguien lo enciende sin agregarle `personal`, el plan es invendible.

---

### B-PER-11 · El PATCH de un médico aplica tres services sin transacción común

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/personal/views.py:273-298`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** la vista llama en secuencia `doctor_update` → `doctor_set_consultorios` →
  `doctor_set_sucursales`, cada uno con su propio `save()` / `.set()` y su propio `audit_record`, sin
  ningún `transaction.atomic()` que los envuelva. Los services de sedes de `apps/clinica` sí abren
  transacción cuando tocan varias tablas (`apps/clinica/services.py:1443`).
- **Consecuencia concreta:** un `PATCH` que cambie a la vez la especialidad, los consultorios y las
  sedes puede fallar en el tercer paso —por ejemplo con "No puedes otorgar ni quitar sedes en las que
  tú mismo no tienes acceso" (`apps/personal/services.py:456-458`)— y devolver **400** habiendo ya
  aplicado los dos primeros. El usuario ve un error y asume que no se guardó nada; la especialidad y
  los consultorios ya cambiaron, y la bitácora tiene dos entradas de una operación que "falló".

---

### B-PER-12 · El consultorio de un horario no se valida contra el alcance de sede del actor

- **Severidad propuesta:** P2
- **Dónde:** `MailySoft/backend/apps/personal/views.py:632-639`
- **Qué dice la documentación:** el docstring de la propia app, en
  `MailySoft/backend/apps/personal/views.py:444-451`: "usa `sucursal_scope_ids(request)` — el MISMO
  criterio que el listado — para que el detalle/PATCH/DELETE por id acoten EXACTAMENTE igual".
- **Qué hace el código:** `DoctorScheduleListCreateApi.post` resuelve el `consultorio_id` con
  `consultorio_get(consultorio_id=...)` **sin** `sucursal_ids`, a diferencia de
  `ConsultorioDetailApi._get_consultorio_or_404`, que sí lo pasa. La defensa que queda es indirecta:
  `resolve_write_sucursal` toma la sede del consultorio y la valida contra `allowed_sucursales`
  (§1.5.3), así que la escritura acaba rechazándose con 400 — pero **antes** el actor ya confirmó por
  el código de respuesta que ese consultorio existe en el tenant (404 contra 400).
- **Consecuencia concreta:** el administrador de Centro puede enumerar ids de consultorio y
  distinguir "no existe" de "existe en Norte" por la diferencia entre 404 y 400. No obtiene datos ni
  escribe nada, pero es una fuga de existencia que el resto de la app cierra a propósito con 404
  uniforme.
## Notificaciones, autenticación, bitácora y portal interno

> Brechas encontradas al extraer el contrato de `apps/notificaciones`, `apps/authn`, `apps/audit` y
> `apps/plataforma` el 2026-08-12. Rutas relativas a la raíz del repo; `apps/…` abrevia
> `MailySoft/backend/apps/…`. **Nada de esto se corrigió**: documentar y arreglar a la vez produce un
> contrato que no describe ni el sistema viejo ni el nuevo.
>
> Resumen: **27 brechas** — 0 P0 · 8 P1 · 19 P2.
> Por app: notificaciones 5 (1 P1) · autenticación 6 (2 P1) · bitácora 7 (3 P1) · plataforma 9 (2 P1).

---

### B-NTF-01 · El nombre del paciente y el texto clínico viajan en la notificación y se quedan ahí
- **Severidad propuesta:** P1
- **Dónde:** `apps/agenda/notes.py:143` (título) y `:144` (cuerpo); persistidos en
  `apps/notificaciones/models.py:97-105`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:340-342` lo marca como riesgo abierto
  — *"El aviso de una nota de equipo incluye el nombre del paciente y un extracto de la nota. Hay que
  decidirlo y documentarlo, no dejarlo sin decidir."*
- **Qué hace el código:** `title = f"Nueva nota en la cita de {appointment.patient.full_name}"` y
  `body = body[:200]` (el texto que un médico escribió sobre esa cita). Los destinatarios incluyen a
  **toda la recepción de la sede** (`notes.py:128-132`). El registro es denormalizado a propósito
  (`models.py:5-9`), se guarda en `notificaciones_notifications` y no tiene caducidad ni endpoint de
  borrado. Contraste directo: el mismo sistema ya sabe hacerlo bien — la notificación de enfermería
  usa título y cuerpo fijos y navega con `target_type=patient` + `target_id`
  (`apps/expediente/services.py:792-796`, con la decisión escrita en `:775-776`).
- **Consecuencia concreta:** el nombre de un paciente queda escrito de forma permanente en una tabla
  que ningún proceso purga, junto a un extracto de lo que su médico escribió, y llega a recepción.
  Bajo LFPDPPP es un tratamiento de datos personales sin minimización ni plazo de conservación; ante
  una fuga de la base, la tabla de notificaciones es tan sensible como el expediente.

### B-NTF-02 · Las notificaciones no caducan ni se pueden borrar
- **Severidad propuesta:** P2
- **Dónde:** `apps/notificaciones/urls.py:25-46` (no hay ruta de borrado) ·
  `apps/notificaciones/models.py:57` (solo el `deleted_at` heredado, que nadie escribe)
- **Qué dice la documentación:** nada.
- **Qué hace el código:** los cuatro endpoints son leer, contar y marcar leída. No existe `DELETE`
  (responde 405), no hay comando de purga ni tarea de Celery que limpie
  (`apps/plataforma/tasks.py` solo avisa vencimientos). Una notificación leída hace ocho meses sigue
  en la tabla con su título intacto.
- **Consecuencia concreta:** la tabla crece sin cota con el contenido de B-NTF-01 dentro. Cuando se
  decida qué hacer con la PII de los títulos, no habrá forma de limpiar lo ya escrito sin un
  `UPDATE` manual en producción.

### B-NTF-03 · El reparto de avisos de `notas` no es best-effort y puede tumbar la creación de la nota
- **Severidad propuesta:** P2
- **Dónde:** `apps/notas/services.py:408-439`
- **Qué dice la documentación:** nada. El patrón contrario sí está declarado en el resto del sistema
  (`apps/expediente/services.py:772-776`: *"disponibilidad clínica > entrega garantizada de avisos"*).
- **Qué hace el código:** los otros cuatro puntos de disparo envuelven `notification_fanout` en
  `try/except` (`apps/agenda/blocks.py:125-159`, `apps/agenda/notes.py:121-174`,
  `apps/expediente/services.py:778-804`, `apps/clinica/services.py:57-75` y `:83-106`). El de
  `notas` no. Si el fanout falla —por ejemplo porque `filter_recipients_by_sucursal` revienta al
  resolver sucursales—, la excepción se propaga y la nota **no se crea**.
- **Consecuencia concreta:** un fallo de la campana, que es un adorno, impide guardar un aviso a todo
  el equipo. Comportamiento inconsistente entre módulos que hace imposible razonar sobre qué pasa
  cuando el reparto falla.

### B-NTF-04 · El filtro de destinatarios por sede hace una consulta por persona
- **Severidad propuesta:** P2
- **Dónde:** `apps/notificaciones/recipients.py:137-142`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** la comprensión de lista ejecuta
  `allowed_sucursales(user=recipient, tenant=tenant).filter(id=sucursal_id).exists()` **por cada
  destinatario candidato**. Un broadcast a 20 personas son 20 consultas adicionales, más la de los
  owners (`:128-135`), más el `bulk_create`.
- **Consecuencia concreta:** con 1–3 usuarios concurrentes es invisible. Es deuda anotada, no un
  problema hoy: se resuelve con una sola consulta a `MembershipSucursal` cuando el número lo exija.
  Registrarlo evita que alguien lo "descubra" con un perfilado dentro de seis meses.

### B-NTF-05 · El aviso de credencial por validar no se acota por sede
- **Severidad propuesta:** P2
- **Dónde:** `apps/clinica/services.py:62-73`
- **Qué dice la documentación:** nada. La regla general de sedes para la campana está escrita en
  `apps/notificaciones/recipients.py:90-107` (decisión del 2026-07-16).
- **Qué hace el código:** `users_with_roles(tenant, roles=["owner","admin"])` sin pasar por
  `filter_recipients_by_sucursal`, a diferencia de reuniones, notas de rol, broadcasts e indicaciones
  de enfermería.
- **Consecuencia concreta:** en una clínica con dos sedes, el administrador de Norte recibe la
  campana de una credencial de un médico de Centro, con el nombre del médico en el título. No es una
  fuga de otro negocio (lo sostiene RLS), pero contradice la regla que el resto del sistema sí
  aplica.

---

### B-AUT-01 · No hay bloqueo por cuenta: el único freno al login es un throttle por IP
- **Severidad propuesta:** P1
- **Dónde:** `apps/authn/views.py:157-158` (`throttle_scope = "auth_login"`) ·
  `MailySoft/backend/config/settings/base.py:216-232` (5/min) · `apps/audit/signals.py:79-86`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md` no lo menciona entre los riesgos.
  El propio código dice *"Throttle estricto (auth_login, 5/min) para frenar fuerza bruta de
  credenciales"* (`apps/authn/views.py:149`).
- **Qué hace el código:** `ScopedRateThrottle` sobre un endpoint anónimo usa **la IP** como clave.
  Los intentos fallidos se registran en la bitácora con el hash del correo
  (`apps/audit/signals.py:51-56`) pero **nada actúa sobre ese registro**: no hay bloqueo temporal de
  cuenta, ni backoff creciente, ni alerta. Verificado: no existe ninguna lectura de `LOGIN_FAILED`
  fuera de los endpoints de consulta.
- **Consecuencia concreta:** un atacante con 200 IPs prueba 1 000 contraseñas por minuto contra la
  cuenta del dueño de una clínica sin cruzar ningún umbral. El único requisito de la contraseña es
  10 caracteres (`base.py:417`). Una cuenta de `owner` comprometida entrega el expediente completo de
  todos los pacientes de esa clínica y la bitácora que probaría el acceso. Efecto colateral del mismo
  diseño: una clínica entera tras un NAT comparte el cupo de 5/min y se autobloquea.

### B-AUT-02 · El Django admin es una segunda puerta que no respeta la matriz de roles de plataforma
- **Severidad propuesta:** P1
- **Dónde:** `apps/plataforma/services.py:1058` (`is_staff=True` para todo el equipo) ·
  `apps/authn/admin.py:29-31` (`is_platform_staff` y `platform_role` editables) y `:32-43`
  (`is_superuser`, `groups`, `user_permissions` editables)
- **Qué dice la documentación:** el propio modelo afirma lo contrario: *"Permite acceder al Django
  Admin. **NO** implica ser staff de plataforma."* (`apps/authn/models.py:63`). Y
  `apps/plataforma/services.py:1103-1113` describe con detalle las reglas anti-escalada del endpoint
  de edición de staff.
- **Qué hace el código:** `platform_staff_create` pone `is_staff=True` a los tres roles, así que
  `super_admin`, `sales` y `engineering` **pueden entrar a `/admin/`**. `UserAdmin` expone
  `platform_role` e `is_platform_staff` como campos de formulario. Quien tenga además el permiso
  `authn.change_user` cambia su propio `platform_role` a `super_admin` sin pasar por
  `platform_staff_update`, que es el único sitio donde viven las reglas "no te cambies tu propio
  rol" (`services.py:1140-1146`) y "debe quedar otro super_admin activo" (`:1160-1180`). Nada de eso
  se audita: el admin de Django no llama a `audit_record`.
- **Consecuencia concreta:** las reglas anti-escalada del panel son evitables por una vía paralela y
  sin rastro en la bitácora. Un miembro de `sales` con un permiso de Django mal concedido se convierte
  en `super_admin` y desde ahí crea clínicas, cambia planes y resetea contraseñas del equipo. Hoy
  depende de que nadie conceda permisos de modelo a esos usuarios, que es exactamente el tipo de
  control que no debería descansar en la disciplina.

### B-AUT-03 · `createsuperuser` produce un staff de plataforma sin rol, que falla en todo menos en la puerta
- **Severidad propuesta:** P2
- **Dónde:** `apps/authn/managers.py:72-74`
- **Qué dice la documentación:** nada.
- **Qué hace el código:** `create_superuser` fuerza `is_staff`, `is_superuser` **e
  `is_platform_staff`** a `True`, pero deja `platform_role` en su default `""`. Ese usuario pasa
  `IsPlatformStaff` (`apps/core/permissions.py:1153-1159`) y falla las nueve clases que exigen un rol
  concreto (§1.3.4 #42–#50), porque `"" not in _PLATFORM_ROLES_*`.
- **Consecuencia concreta:** el superusuario de emergencia, que es justo el que se usa cuando algo se
  rompe, recibe 403 en **todos** los endpoints del panel de plataforma. Y a la vez tiene acceso total
  por `/admin/`, donde no hay ninguna de las reglas de negocio. El resultado es que en un incidente
  se opera por el camino sin salvaguardas.

### B-AUT-04 · Tres docstrings afirman que el refresh rota; el settings dice que no
- **Severidad propuesta:** P2
- **Dónde:** `apps/authn/views.py:30` y `:248` · `apps/plataforma/services.py:1279` ·
  contra `MailySoft/backend/config/settings/base.py:266-267`
- **Qué dice la documentación:** `docs/_a2-partes/00-transversal.md` §1.2.1 ya lo extrajo bien:
  `ROTATE_REFRESH_TOKENS=False`, `BLACKLIST_AFTER_ROTATION=False`, con la razón escrita en el propio
  settings (sesiones que se caían al recargar).
- **Qué hace el código:** `CookieTokenRefreshView` dice *"Si ROTATE_REFRESH_TOKENS=True (activo en
  base.py), el nuevo refresh se deposita en la cookie"*. La rama que lo haría
  (`apps/authn/views.py:274-276`) **nunca se ejecuta hoy**.
- **Consecuencia concreta:** quien lea el código —humano o agente— asume que un refresh robado se
  invalida al primer uso legítimo. No es así: vive 7 días completos. Una decisión de seguridad
  documentada al revés es peor que no documentada, porque genera confianza falsa.

### B-AUT-05 · El logout blacklistea el refresh de la cookie sin comprobar de quién es
- **Severidad propuesta:** P2
- **Dónde:** `apps/authn/views.py:308-313`
- **Qué dice la documentación:** nada. El docstring solo describe el flujo feliz
  (`apps/authn/views.py:294-301`).
- **Qué hace el código:** toma el valor de la cookie `maily_refresh`, construye un `RefreshToken` y
  lo blacklistea. No compara el claim de usuario del token con `request.user`.
- **Consecuencia concreta:** un atacante que consiga inyectar el refresh de la víctima en su propia
  cookie —que es difícil: `httpOnly`, `SameSite=Strict`, `Path=/api/v1/auth/` y `@csrf_protect`
  encima— cierra la sesión de la víctima desde su propia cuenta. El impacto real es una denegación de
  servicio dirigida, no un robo de datos. Se anota porque la comprobación es una línea y hoy no está.

### B-AUT-06 · Un inicio de sesión exitoso puede quedar sin registro en la bitácora
- **Severidad propuesta:** P2
- **Dónde:** `apps/authn/views.py:200-209` dentro de `_audit_login_success`
- **Qué dice la documentación:** `MailySoft/CLAUDE.md` (regla dura 5) exige que las acciones
  sensibles se registren en la bitácora por requisito normativo. `docs/01-analisis.md:287` dice que
  la bitácora existe y registra "quién, qué acción, sobre qué recurso".
- **Qué hace el código:** para auditar el `LOGIN`, la vista **vuelve a buscar al usuario por correo**
  (`User.objects.get(**{username_field: email_value})`) porque SimpleJWT no le devuelve la instancia.
  Si esa búsqueda falla, hace `logger.warning` y **retorna sin escribir nada**; el login responde 200
  igual. Todo el bloque está además dentro de un `try/except Exception` que solo loguea
  (`:225-230`).
- **Consecuencia concreta:** hay caminos —usuario borrado entre la validación y la auditoría,
  cualquier fallo transitorio de base de datos— en los que alguien entra al sistema y en la bitácora
  no queda constancia. Para un registro que se presenta como evidencia normativa, "a veces no
  escribe" es un defecto de fondo, no un detalle de implementación.

---

### B-AUD-01 · La IP de la bitácora se toma de `X-Forwarded-For` sin lista de proxies confiables
- **Severidad propuesta:** P1
- **Dónde:** cuatro sitios idénticos — `apps/core/views.py:177-182` ·
  `apps/authn/views.py:183-188` · `apps/audit/signals.py:64-68` ·
  `apps/plataforma/views.py:153-158`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:337-339` lo declara como riesgo
  abierto: *"Cualquier cliente puede falsificar la IP que queda registrada en la bitácora de
  auditoría — que es justamente el registro que se usaría como evidencia."* **Confirmado.**
- **Qué hace el código:** `x_forwarded.split(",")[0].strip()` — se toma el **primer** elemento de la
  cabecera, que es exactamente el valor que escribió el cliente; el proxy inverso solo **añade** al
  final. No existe ninguna lista de proxies confiables: verificado por búsqueda de `ipware`,
  `TRUSTED_PROXIES` y `USE_X_FORWARDED_*` en todo `MailySoft/backend/`, sin coincidencias fuera de
  esos cuatro sitios y de un test (`apps/audit/tests/test_integration.py:520`). El sistema **sí** sabe
  que hay un proxy delante: `SECURE_PROXY_SSL_HEADER` está configurado (§1.7.4).
- **Consecuencia concreta:** `curl -H "X-Forwarded-For: 8.8.8.8"` deja `8.8.8.8` escrito en
  `audit_logs.ip_address`. Un empleado que consulta expedientes que no le corresponden puede sembrar
  la IP de otra persona en cada acceso, y también en los `LOGIN_FAILED` de un ataque. La bitácora
  sigue registrando **qué** pasó y **quién** (el actor viene del JWT, no de una cabecera), pero el
  campo `ip_address` no vale como evidencia. Y como la lógica está copiada en cuatro archivos,
  arreglarla en uno solo da una falsa sensación de haberlo resuelto.

### B-AUD-02 · Cualquier staff de plataforma —incluido `sales`— lee la bitácora cross-tenant por el Django admin
- **Severidad propuesta:** P1
- **Dónde:** `apps/audit/admin.py:90-98` (`has_view_permission` y `has_module_perms`) y `:72`
  (`get_queryset` con `all_objects`), habilitado por `apps/plataforma/services.py:1058`
  (`is_staff=True`)
- **Qué dice la documentación:** el docstring del propio admin dice *"Solo usuarios con
  is_platform_staff=True pueden acceder"* (`apps/audit/admin.py:7`) — describe el comportamiento, no
  la contradicción. Y `apps/core/permissions.py:1229` con `_PLATFORM_ROLES_AUDIT` (`:1100-1102`)
  excluye a `sales` de la bitácora **a propósito**.
- **Qué hace el código:** los dos métodos de permiso del admin se sobreescriben para devolver `True`
  con solo mirar `is_platform_staff`, ignorando el `platform_role` y los permisos de modelo de
  Django. `get_queryset` usa `all_objects`, y como un usuario de plataforma no tiene membresía, el
  GUC queda vacío y RLS abre todas las filas (§1.1.1). El changelist tiene búsqueda por
  `actor__email`, `resource_repr`, `description`, `request_id` e `ip_address` (`admin.py:42`).
- **Consecuencia concreta:** el control que separa a ventas de la bitácora de los clientes existe en
  la API y **no existe** en el admin. Un miembro de `sales` lee, filtrando por clínica, quién
  consultó qué expediente en cualquier clínica del país, con IPs, correos y `resource_repr` —que
  incluye números de expediente y folios de receta—, además de los `LOGIN_FAILED` globales con su
  `email_hint`. Es la definición de una matriz de permisos con un hueco.

### B-AUD-03 · Las dos barreras de PostgreSQL que sostienen la inmutabilidad son inertes con un rol superuser
- **Severidad propuesta:** P1
- **Dónde:** `apps/audit/migrations/0002_enable_rls.py:99-118` (el `REVOKE` condicionado a
  `NOT rolsuper`) y `:45-48` (`FORCE ROW LEVEL SECURITY`)
- **Qué dice la documentación:** la propia migración lo admite a medias: *"En desarrollo el rol de la
  app es el mismo superuser que creó la BD… El REVOKE explícito se añade en hardening de producción"*
  (`0002:14-20`). Y `docs/_a2-partes/00-transversal.md` §1.1.4 documenta que la suite corre con rol
  superuser y que `python manage.py check_db_role` **no está en CI**.
- **Qué hace el código:** el bloque `DO $$` solo ejecuta el `REVOKE UPDATE, DELETE` si
  `current_user` **no** es superuser (`:104-110`); si lo es, no hace nada y no falla. Y PostgreSQL
  exime a los superusers de RLS incluso con `FORCE`. Con un rol superuser quedan en pie **solo** las
  tres barreras de Python (`models.py:426-438`, `:440-446`, `:31-35`).
- **Consecuencia concreta:** si el rol de conexión de producción es superuser —cosa que hoy nadie
  verifica automáticamente—, un `cursor.execute("UPDATE audit_logs …")`, un `psql` o cualquier
  herramienta de administración modifica o borra renglones de la bitácora sin dejar rastro. Una
  bitácora falsificable no prueba nada. El diagnóstico ya existe (`check_db_role`) y está fuera de
  CI: es una brecha de proceso tanto como de código.

### B-AUD-04 · Los filtros inválidos de la bitácora de clínica se ignoran en silencio
- **Severidad propuesta:** P2
- **Dónde:** `apps/audit/views.py:63-67`, `:70-75` y `:82-91`
- **Qué dice la documentación:** el docstring de la vista lista los parámetros como si siempre
  aplicaran (`apps/audit/views.py:44-52`).
- **Qué hace el código:** cada conversión está en un `try/except ValueError: pass`. Un `actor_id`,
  `resource_id`, `date_from` o `date_to` mal formados no dan 400: **el filtro simplemente no se
  aplica**. Peor, `date_from` y `date_to` comparten el mismo `try`, así que un `date_to` inválido
  anula también un `date_from` válido. El endpoint gemelo de plataforma sí valida con serializer y
  responde 400 (`apps/plataforma/views.py:640-641`).
- **Consecuencia concreta:** un dueño que audita "qué hizo Ana el 3 de agosto" con un parámetro mal
  escrito ve la bitácora completa creyendo que ve lo de Ana, o ve un rango que no pidió. Un error de
  auditoría silencioso es peor que un error visible.

### B-AUD-05 · La documentación interna del código dice "owner y admin"; el permiso es solo owner
- **Severidad propuesta:** P2
- **Dónde:** `apps/audit/views.py:6` y `:41` · `apps/audit/serializers.py:5` y `:34-35` · contra
  `apps/audit/permissions.py:22` y `:33-35`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:50-51` está **correcto**: el dueño es
  el "único que ve la bitácora de auditoría" y el admin "no ve la bitácora".
- **Qué hace el código:** `AUDIT_ROLES = frozenset({Role.OWNER})`. Los docstrings de la vista y del
  serializer se quedaron en la versión anterior al cambio del 2026-07-16, que sí está bien explicado
  en `apps/audit/permissions.py:10-14`.
- **Consecuencia concreta:** el serializer justifica exponer `metadata` completo "porque el endpoint
  ya está restringido a owner/admin". Si alguien re-evalúa esa exposición leyendo el comentario,
  razonará sobre un público equivocado. Riesgo bajo hoy, pero es el tipo de comentario obsoleto que
  provoca la decisión errónea dentro de un año.

### B-AUD-06 · La regla "sin PII" solo cubre `metadata`; `description` y `resource_repr` llevan datos personales sistemáticamente
- **Severidad propuesta:** P2
- **Dónde:** política declarada en `apps/audit/models.py:294` y `:385-388` · incumplida en
  `apps/plataforma/services.py:352-356`, `:439-443`, `:545-550`, `:646-648`, `:1077-1080`,
  `:1211-1214`, `:1297-1300` · `apps/plataforma/tasks.py:105-109` y `:162-167` ·
  `apps/authn/views.py:222` · `apps/authn/services.py:93`
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:299` presenta la "minimización de PII
  en la bitácora" como una de las decisiones acertadas del sistema.
- **Qué hace el código:** la regla escrita habla **solo** de `metadata`. Los dos campos de texto libre
  quedan fuera: `resource_repr = user.email` en `LOGIN`, `PASSWORD_CHANGE` y todos los eventos de
  staff; `description` incluye el correo del actor y el nombre de la clínica en **todos** los
  services de plataforma. Además, según §1.9 del contrato transversal, `member_create` sí mete el
  correo en `metadata` — **NO VERIFICADO** directamente: `apps/tenancy/services.py:314-325` está
  fuera del alcance que leí. Y `user_agent` guarda 512 caracteres de huella de dispositivo en cada
  evento.
- **Consecuencia concreta:** la bitácora, que es la tabla que más crece y la que menos se revisa,
  contiene correos, nombres comerciales y huellas de dispositivo sin plazo de conservación. La regla
  declarada da por resuelto un problema que solo está resuelto en un tercio de los campos, y quien
  añada un `audit_record` nuevo leerá el `help_text` y creerá que basta con cuidar `metadata`.

### B-AUD-07 · La retención de 10 años se afirma en el código y no está implementada
- **Severidad propuesta:** P2
- **Dónde:** `apps/audit/views.py:31` (*"la bitácora retiene 10 años"*)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:299` menciona el borrado lógico en
  lugar de físico como decisión acertada, pero no habla de retención de la bitácora.
- **Qué hace el código:** no existe ningún comando ni tarea de purga. Verificado por búsqueda de
  `purge`, `retention` y `cleanup` en `MailySoft/backend/apps/`: las únicas coincidencias son el
  panel de retención de pacientes de finanzas, sin relación. La bitácora crece indefinidamente.
- **Consecuencia concreta:** hoy el efecto es solo de costo y de rendimiento (cinco índices sobre una
  tabla que solo crece). El problema real aparece cuando haya que **cumplir** el plazo: sin proceso
  de purga, la obligación de conservar 10 años convive con la de no conservar más de lo necesario, y
  ninguna de las dos se puede demostrar.

---

### B-PLA-01 · En el panel de plataforma, el único aislamiento es el `permission_class` que cada vista recuerde declarar
- **Severidad propuesta:** P1
- **Dónde:** `apps/plataforma/views.py:117-132` (`PlatformAPIView` con
  `permission_classes = [IsAuthenticated]`) · `apps/plataforma/selectors.py:4-14`
- **Qué dice la documentación:** el propio código lo explica bien y hasta lo advierte:
  *"REGLA: estas vistas SOLO se usan para el equipo interno de Maily. NUNCA exponer un endpoint de
  clínica usando PlatformAPIView"* (`views.py:18-19`). `docs/_a2-partes/00-transversal.md` §1.1.5 lo
  lista como uso legítimo de `all_objects`.
- **Qué hace el código:** `PlatformAPIView` no resuelve membresía y no fija el GUC, con lo cual **las
  dos barreras de §1.1.1 quedan apagadas a la vez**: la de Django porque los selectors usan
  `all_objects`, y la de PostgreSQL porque `current_tenant_id() IS NULL` hace verdadera la condición
  `OR` de toda policy. Su `permission_classes` de clase es `[IsAuthenticated]` a secas: una subclase
  que no lo sobreescriba queda accesible a **cualquier usuario autenticado de cualquier clínica**.
  Hoy las 13 vistas declaran su permiso —verificado una por una— y las tres que resuelven por método
  usan `get_permissions()`, que sustituye por completo el atributo de clase (§1.3.6).
- **Consecuencia concreta:** no hay ningún fallo explotable hoy. Lo que hay es un **fail-open por
  omisión** en la única capa del sistema que ve datos de todas las clínicas: el día que alguien
  agregue una vista al panel y olvide una línea, un recepcionista autenticado podrá listar las
  clínicas de la competencia, o algo peor, sin que ningún test lo detecte. El default debería ser
  `IsPlatformStaff`, no `IsAuthenticated`.

### B-PLA-02 · La clínica no puede ver en su bitácora ninguna acción que la plataforma hace sobre ella
- **Severidad propuesta:** P1
- **Dónde:** `tenant=None` en `apps/plataforma/services.py:349`, `:436`, `:542`, `:642`, `:833`,
  `:930`, `:1074`, `:1208`, `:1294` y `apps/plataforma/tasks.py:102`, `:159` · efecto en
  `apps/audit/selectors.py:44-46` y `apps/audit/migrations/0003_fix_audit_select_policy.py:26-31`
- **Qué dice la documentación:** el código lo justifica como *"evento de plataforma, no de clínica"*
  en cada llamada. `MailySoft/docs/01-analisis.md:287` afirma que la bitácora registra "quién, qué
  acción, sobre qué recurso".
- **Qué hace el código:** todos los eventos de plataforma se graban con `tenant=NULL`. El endpoint de
  bitácora de clínica filtra por `TenantManager`, y desde la migración `0003` la policy RLS ya no
  incluye `OR tenant_id IS NULL`. Resultado: `TENANT_STATUS_CHANGE`, `SUBSCRIPTION_CHANGE`,
  `TENANT_ENTITLEMENTS_SET`, `PLAN_UPDATE`, `TRIAL_EXPIRED` y `SUBSCRIPTION_EXPIRED` son **invisibles
  para el dueño de la clínica afectada**. El `tenant_id` sí queda dentro de `metadata`
  (`services.py:359`, `:446`, `:553`, `:650`), pero el filtro `?tenant_id=` del panel consulta la
  **columna** (`selectors.py:332-333`), no el JSON.
- **Consecuencia concreta:** a una clínica le suspenden el servicio, le apagan el módulo de recetas o
  le cambian el plan, y en su bitácora —el registro que por norma debe explicar qué pasó con su
  sistema— no hay una sola línea. Cuando el dueño pregunte "¿quién apagó esto y cuándo?", la
  respuesta solo existe en un panel al que él no tiene acceso. Y el propio equipo de Maily no puede
  filtrar esos eventos por clínica desde su panel, porque el filtro mira la columna vacía.

### B-PLA-03 · El listado de suscripciones se materializa completo en memoria antes de paginar
- **Severidad propuesta:** P2
- **Dónde:** `apps/plataforma/selectors.py:548-557` y `:590` · consumido en
  `apps/plataforma/views.py:841-851`
- **Qué dice la documentación:** el código lo justifica explícitamente
  (`selectors.py:523-528`): el filtro de alerta no se puede empujar a SQL sin duplicar
  `_calcular_alerta`, y el volumen de clínicas es bajo.
- **Qué hace el código:** `platform_subscriptions_list` devuelve una **lista de dicts**, no un
  QuerySet; el paginador recibe la lista ya construida. Pedir `?page=1&page_size=20` recorre las N
  clínicas igual. `platform_subscriptions_resumen` llama a la lista completa solo para contar
  alertas.
- **Consecuencia concreta:** con decenas de clínicas es la decisión correcta y hay que respetarla.
  Se anota para que quede el número que la invalidaría: cuando el catálogo pase de unos cientos de
  clínicas, cada carga del panel de suscripciones y de su resumen recorrerá la tabla entera dos
  veces.

### B-PLA-04 · `engineering` recibe nombres y correos de todo el personal de cualquier clínica
- **Severidad propuesta:** P2
- **Dónde:** `apps/plataforma/selectors.py:241-251` · expuesto por
  `apps/plataforma/views.py:325-348` con `PlatformClinicReadPermission`
  (`apps/core/permissions.py:1176`, los tres roles)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md:74` describe el alcance de
  `engineering` como *"Métricas, salud del sistema, bitácora cross-tenant"* — **no** menciona el
  padrón de personal de las clínicas.
- **Qué hace el código:** la ficha de detalle devuelve `members[]` con `full_name`, `email`, `role` y
  `is_active` de cada miembro, y el permiso de lectura de clínicas admite a los tres roles de
  plataforma sin distinción.
- **Consecuencia concreta:** un perfil cuyo trabajo es diagnosticar infraestructura obtiene el
  directorio completo de empleados de todos los clientes. No es una fuga entre clínicas, es un exceso
  de privilegio interno: el mismo dato que `sales` necesita para vender, `engineering` no lo necesita
  para nada. Es también la diferencia entre la documentación y el código que este ejercicio existe
  para encontrar.

### B-PLA-05 · El override de derechos no valida dependencias entre módulos; el catálogo de planes sí
- **Severidad propuesta:** P2
- **Dónde:** `apps/plataforma/services.py:610-624` (solo `modulos_desconocidos`) frente a
  `apps/plataforma/services.py:720-724` (`validar_modulos` en planes)
- **Qué dice la documentación:** `apps/core/modules.py:162` declara la regla y su razón —
  `validar_modulos` **no** expande solo, porque *"un plan con cotizaciones y sin servicios es error
  de captura, no algo que adivinar"* (§1.4.1).
- **Qué hace el código:** `tenant_entitlements_set` solo comprueba que los slugs existan. Se puede
  encender `cotizaciones` sin `servicios`, `paquetes` sin `servicios`, `cfdi` sin `cobranza` o
  `calendarizacion` sin `expediente` para una clínica concreta. `entitlements_for_tenant` los suma
  tal cual (§1.4.3).
- **Consecuencia concreta:** una clínica termina con un módulo encendido que no puede funcionar
  porque le falta aquello de lo que depende: el menú aparece y la pantalla no carga, o carga vacía.
  Y el diagnóstico es difícil, porque el plan se ve coherente y el problema está en la fila de
  ajustes a la medida.

### B-PLA-06 · Las contraseñas temporales no caducan
- **Severidad propuesta:** P2
- **Dónde:** `apps/plataforma/services.py:76-111` (`_generar_password_temporal`), usada en `:251`,
  `:1051` y `:1267`
- **Qué dice la documentación:** nada sobre caducidad. El código sí documenta bien lo demás: 16
  caracteres criptográficos, nunca persistida ni logueada, devuelta una sola vez
  (`services.py:88-91`, `views.py:264-267`).
- **Qué hace el código:** la temporal se guarda como hash normal y enciende `must_change_password`.
  No hay campo de expiración ni verificación de antigüedad: un dueño dado de alta hace ocho meses que
  nunca entró conserva su temporal válida indefinidamente. Tampoco hay forma de reenviarla: si se
  pierde, la única salida es un reset (`super_admin` para staff; el dueño de la clínica para sus
  miembros, §1.9).
- **Consecuencia concreta:** la contraseña viaja en el cuerpo de una respuesta HTTP y el operador la
  transmite por el canal que tenga a mano —correo, WhatsApp, un papel—. Sin caducidad, ese canal
  queda siendo una credencial válida para siempre. Un histórico de chat comprometido entrega la
  cuenta de dueño de una clínica que nunca llegó a entrar.

### B-PLA-07 · Nombres y docstrings del panel que no describen lo que hacen
- **Severidad propuesta:** P2
- **Dónde:** `apps/plataforma/views.py:939` (`PlatformClinicaEntitlementsApi` protegida por
  `PlatformPlanWritePermission`) · `apps/plataforma/urls.py:6-23` · `apps/plataforma/views.py:21-31`
- **Qué dice la documentación:** los propios docstrings del módulo pretenden ser el índice de rutas y
  permisos del panel.
- **Qué hace el código:** el permiso que protege el ajuste de derechos de una clínica se llama
  "escritura de planes"; el rol que exige (`super_admin`) es correcto, pero el nombre apunta al
  recurso equivocado. Además, el docstring de rutas de `urls.py` **no lista**
  `clinicas/<id>/entitlements/`, y el de `views.py` no lista métricas, planes, suscripciones ni
  entitlements: seis de las dieciocho operaciones no aparecen en el índice que el propio archivo
  ofrece.
- **Consecuencia concreta:** quien audite los permisos leyendo los docstrings —que es lo que invita a
  hacer el archivo— concluirá que el panel tiene menos superficie de la que tiene. El endpoint que
  puede regalar cualquier módulo a cualquier clínica es justamente uno de los que faltan en la lista.

### B-PLA-08 · Cada carga del panel de sistema dispara un broadcast por el broker de Celery
- **Severidad propuesta:** P2
- **Dónde:** `apps/plataforma/system_health.py:130-133`, consumido por
  `apps/plataforma/views.py:685-688`
- **Qué dice la documentación:** el propio código dice que el panel refresca cada 30 s
  (`system_health.py:210`).
- **Qué hace el código:** `celery_app.control.ping(timeout=2)` es un mensaje de control que se
  difunde a todos los workers y espera respuestas hasta 2 segundos. No hay caché del resultado ni
  throttle propio en la vista; solo aplica el global de 300/min por usuario.
- **Consecuencia concreta:** con dos personas mirando el panel son 4 broadcasts por minuto y hasta 2
  segundos de latencia por request. Irrelevante hoy. Se anota porque es el tipo de endpoint que se
  deja abierto en una pantalla toda la jornada y porque un `cache.get_or_set` de 15 segundos lo
  resuelve cuando haga falta — no antes.

### B-PLA-09 · No hay camino para dar de baja definitiva a una clínica ni para exportar sus datos
- **Severidad propuesta:** P2
- **Dónde:** ausencia verificada en `apps/plataforma/urls.py:46-126` (no hay `DELETE` ni endpoint de
  exportación) · impedimento estructural en `apps/core/models.py` (`tenant` con `PROTECT`, §1.8.2)
- **Qué dice la documentación:** `MailySoft/docs/01-analisis.md` no menciona baja definitiva ni
  portabilidad de datos entre los pendientes.
- **Qué hace el código:** el único "borrado" de una clínica es `status=suspended`
  (`apps/plataforma/services.py:429-430`), que corta el acceso pero conserva todo. El `PROTECT` de
  `TenantAwareModel.tenant` impide el borrado físico en cuanto exista **un solo** registro de
  negocio, y `AuditLog.tenant` también es `PROTECT` (`apps/audit/models.py:300-302`).
- **Consecuencia concreta:** una clínica que se da de baja y ejerce su derecho de cancelación bajo
  LFPDPPP no tiene ningún proceso que atenderla, y tampoco puede llevarse sus datos a otro sistema.
  La decisión de conservar la bitácora es correcta y defendible; la de no tener **ninguna** ruta
  documentada para el resto no lo es. Es una decisión de producto pendiente, no un bug — pero hoy no
  está tomada en ningún sitio.
