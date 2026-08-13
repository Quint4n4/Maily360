# Deuda técnica de MailySoft — backlog único, agrupado por causa raíz

> Fase A3 de la adopción del modelo de trabajo. Producido el **2026-08-13** con el agente `reviewer`
> en **modo auditoría**: no se bloqueó nada, no se corrigió ni una línea de código.
>
> **Qué es esto:** el backlog único del proyecto. Consolida los hallazgos abiertos de los cuatro
> documentos previos **más** siete auditorías nuevas sobre lo que nadie había mirado, y los agrupa
> **por causa raíz**, no por documento de origen.
>
> **Qué NO es:** una quinta lista de hallazgos. Si buscas el detalle de una brecha concreta, sigue
> el ID a su documento de origen; aquí está el arreglo que la cierra junto con las otras.

---

## Cómo se lee este documento

**La escala de gravedad es esta y no se redefine:**

| | Criterio |
|---|---|
| **P0** | Un usuario ve datos de otra clínica o de otra sede · endpoint sin permisos · secreto expuesto · pérdida de datos · escalada de privilegios |
| **P1** | Falla con un cliente real: acción que revienta, dato clínico o fiscal incorrecto, capacidad comprada que no funciona |
| **P2** | Inconsistencia real sin consecuencia operativa inmediata |

Ante la duda entre dos niveles, se subió. Un hallazgo que cumple la definición de P0 es P0 aunque no
haya exploit demostrado.

**Una corrección de clasificación que este documento aplica.** La auditoría de tests propuso seis
hallazgos como P0 por ausencia de cobertura. Se reclasificaron cinco a P1, con este criterio: *un
test que falta no es, por sí solo, «un usuario ve datos de otra clínica»*. Se verificó por AST que
hoy las **144 clases de vista declaran `permission_classes`** y que ninguna está abierta. El hueco
es la red que faltaría mañana, no un agujero de hoy — y decirlo de otro modo repetiría el error de
clasificación que el resumen ejecutivo de A2 ya tuvo que corregir. La excepción es CR-01: ahí el
hueco de test sostiene una afirmación falsa sobre producción, y hereda su gravedad.

**Trazabilidad de los identificadores:**

| Prefijo | Origen |
|---|---|
| `B-*` | `00-brechas.md` — 167 brechas de backend (A2) |
| `F-*`, `D-1…D-8` | `00-brechas-frontend.md` — 76 brechas de frontend (A2) |
| `D-TEST-*` | A3 · tests del backend |
| `D-DEP-*` | A3 · dependencias y despliegue |
| `D-PERF-*` | A3 · consultas y rendimiento |
| `D-TXN-*` | A3 · transacciones, Celery y manejo de errores |
| `D-FE-*` | A3 · pruebas del frontend, CI y build |
| `D-DOC-*` | A3 · los 20 documentos de `docs/design/` contra el código |

## Método, y sus límites

Siete auditorías en paralelo sobre lo que las fases previas no cubrieron, más verificación propia de
las causas raíz. Lo que este documento **no** puede afirmar:

- **No se leyó el entorno real de Railway.** El conector de Railway de esta máquina apunta a otro
  proyecto y la sesión no puede autenticar uno nuevo. Todo lo que dice «si falta esta variable en
  Railway» describe el comportamiento del código, no una constatación de que falte. **Tres P0 de
  este documento se confirman o se descartan mirando el panel de Railway: es lo primero que hay que
  hacer en A4.**
- **No se ejecutó ninguna suite ni se midió ninguna consulta.** No hay base de datos disponible en
  esta sesión. Los conteos de consultas son derivaciones del código y así se marcan.
- **El árbol no está limpio.** El backend coincide con el último commit (`4f97230`), pero el
  frontend tiene **37 archivos modificados sin commitear** (+1 241 / −992), incluidos
  `index.css`, `tailwind.config.js` y 20 componentes. Los hallazgos `F-*` se verificaron contra
  `4f97230`; los `D-FE-*` y `D-PERF-*` de frontend, contra el árbol de trabajo. Antes de A4 conviene
  commitear o descartar esos cambios: hoy no hay un estado del frontend al que referirse sin
  ambigüedad.
- **`pip-audit` y `npm audit` sí corrieron con red**, contra OSV y PyPI. Los CVE citados son reales.

---

## Resumen

**27 causas raíz cubren 276 hallazgos.** Ocho de las causas son P0.

| | |
|---|---:|
| Causas raíz | **27** |
| Hallazgos que cubren | **276** |
| …de `00-brechas.md` (backend, A2) | 89 |
| …de `00-brechas-frontend.md` (frontend, A2) | 50 |
| …nuevos de A3 | 137 |
| Hallazgos nuevos producidos en A3 | 149 |

**Ocho causas raíz P0:**

| | Causa raíz | Cierra |
|---|---|---:|
| **CR-19** | La bitácora traga el fallo de su INSERT sin savepoint: **la nota clínica se revierte y la API responde 201** | 3 |
| **CR-01** | Producción se conecta a Postgres con rol superusuario: **RLS está inerte** | 5 |
| **CR-02** | Los defaults de desarrollo deciden dónde viven los datos y con qué clave se firman | 11 |
| **CR-20** | Comprobar-luego-actualizar sin lock: **el dinero se duplica o se pierde** | 7 |
| **CR-03** | No existe capa de permisos por objeto | 13 |
| **CR-04** | La resolución por id garantiza el tenant y **nunca la sede** | 19 |
| **CR-05** | El Django admin es una segunda puerta sin las reglas del producto | 4 |
| **CR-16** | `seed_e2e_user` sin guardia de entorno puede tomar la clínica más antigua | 1 |

**Las tres cosas que este documento añade y que ninguna fase anterior podía ver:**

1. **CR-19 es el hallazgo más grave de toda la adopción**, y está reproducido empíricamente contra
   PostgreSQL: hoy es posible que un médico guarde una nota de evolución, la API responda 201 y **la
   nota no exista**. No hacía falta buscar una fuga entre clínicas: había una pérdida silenciosa de
   datos clínicos alcanzable con un header HTTP.
2. **Tres causas raíz estructurales explican 43 hallazgos** (CR-02, CR-03 y CR-04): una guardia de
   arranque que falta, una capa de DRF que no se usa, y una firma de función que no recibe la sede.
   Las tres se cierran con un cambio de forma, no con 43 parches. A ellas se suma CR-27, que cierra
   61 hallazgos de documentación de una sola vez.
3. **El resumen de A2 estimó cuatro causas raíz; las cuatro resultaron más grandes al medirlas.** El
   detalle-por-id pasó de 12 hallazgos a **34 puntos de entrada estructurales**; el borrado lógico,
   de 8 a **30 constraints sin `condition`**; la autoridad por pertenencia resultó ser **cero
   `has_object_permission` en todo el proyecto**; y la PII en bitácora llegó acompañada de que la
   escritura de esa bitácora es *best-effort* silenciosa.

**Y una tranquilizadora, que también es un resultado:** ninguna de las siete auditorías encontró un
camino por el que una clínica lea los datos de otra a través de la API. Las 144 vistas declaran su
permiso, el aislamiento por tenant del manager de Django funciona dentro del request, y el frontend
no filtra nada por el bundle. Lo que está roto es la **segunda** barrera (CR-01), el aislamiento
entre **sedes** (CR-04) y la puerta de al lado (CR-05).

---

> **Las causas raíz que siguen no están ordenadas por gravedad**, sino agrupadas por el área donde
> se arreglan. Para el orden de ataque, ve a [§Orden sugerido para A4](#orden-sugerido-para-a4).

## CR-01 · Producción se conecta a PostgreSQL con un rol superusuario: RLS está inerte

**Gravedad: P0** · **Cierra:** `B-AUD-03`, `B-T-02`, `B-T-03`, `D-DEP-04`, `D-TEST-01`

**Qué pasa.** La segunda barrera de aislamiento entre clínicas —las 95 políticas de Row Level
Security en Postgres— no se aplica en producción, porque PostgreSQL exime a los roles `SUPERUSER`
de RLS pase lo que pase, incluso con `FORCE`. El propio proyecto lo documenta:
[deploy-rol-app-nosuperuser.md:8](MailySoft/docs/deploy-rol-app-nosuperuser.md) — «hoy la app en
Railway se conecta con el usuario `postgres`, que es superuser (`rolsuper=t`, `rolbypassrls=t`) …
las políticas RLS del proyecto están **inertes en producción**» — y su línea 3 dice «guía lista, NO
aplicada en Railway todavía».

Y no hay nada que lo delate, porque **la suite de tests corre con el mismo tipo de rol**: el servicio
de CI arranca Postgres con `POSTGRES_USER: mailysoft` ([ci.yml:31](.github/workflows/ci.yml)), que la
imagen crea como superusuario. Los tres archivos que dicen probar RLS lo reconocen por escrito
([test_tenant_guc_modes.py:396](MailySoft/backend/apps/core/tests/test_tenant_guc_modes.py),
[test_rls_coverage.py:256](MailySoft/backend/apps/core/tests/test_rls_coverage.py)) y por eso
inspeccionan el catálogo en vez de ejercer la policy. El comando de diagnóstico existe
([check_db_role.py](MailySoft/backend/apps/core/management/commands/check_db_role.py)) y **no lo
corre ningún test ni ningún paso de CI**.

Encima, las policies llevan `OR current_tenant_id() IS NULL`
([pacientes/migrations/0002_enable_rls.py:31](MailySoft/backend/apps/pacientes/migrations/0002_enable_rls.py), ×95):
sin contexto fijado, RLS **deja ver todo** en vez de bloquear. Y el guardián de RLS **exige** ese
fallback ([test_rls_coverage.py:245-285](MailySoft/backend/apps/core/tests/test_rls_coverage.py)):
endurecer las policies hoy rompe la suite. El test congela el patrón permisivo.

**Dónde se arregla.** Aplicar el runbook de `deploy-rol-app-nosuperuser.md` en Railway (el soporte
para migrar con un rol privilegiado distinto ya está en
[entrypoint.sh:62](MailySoft/backend/entrypoint.sh), sin usar); crear un rol `NOSUPERUSER` para la
suite y hacer que un test ejecute un `SELECT` que la policy bloquee de verdad; correr `check_db_role`
en CI; y una vez cerrado lo anterior, quitar el fallback `IS NULL` de las policies y del guardián.

**Qué se rompe si no se arregla.** El aislamiento entre clínicas depende hoy de **una sola barrera**:
el `TenantManager` de Django. Cualquier `all_objects`, SQL crudo o consulta fuera del ciclo de
request devuelve filas de todas las clínicas y nada lo impide. Esto corrige lo que
`01-analisis.md §6` afirma sobre la doble barrera: hoy no es doble.

**Agravante propio, verificado en esta auditoría.** El `TenantManager` es *fail-open* fuera del
request, no fail-closed: [core/managers.py:27-36](MailySoft/backend/apps/core/managers.py) —
«Fuera de request (Celery, migraciones, management commands): sin filtro de tenant». Devuelve
**todas las clínicas**, no ninguna. Dentro del request sí falla seguro (queryset vacío). Es decir:
en una tarea de Celery, un comando de consola o una migración de datos, **las dos barreras están
abiertas a la vez**. Hoy no hay fuga demostrada por esta vía porque las cuatro tareas existentes se
comportan bien —`pdfs/tasks.py:56` y `recetas/tasks.py:63` fijan el tenant explícitamente,
`agenda/tasks.py:90` navega por FK desde un objeto ya resuelto, y `plataforma/tasks.py` es
cross-tenant por diseño—, pero es una convención que se recuerda, no un mecanismo que se aplica.

---

## CR-02 · Los defaults de desarrollo deciden en producción dónde viven los datos y con qué clave se firman

**Gravedad: P0** · **Cierra:** `B-REC-03`, `B-PAC-02`, `D-DEP-01`, `D-DEP-02`, `D-DEP-03`,
`D-DEP-05`, `D-DEP-06`, `D-DEP-07`, `D-DEP-08`, `D-DEP-15`, `D-FE-04`

**Qué pasa.** De **53 variables de entorno que el código lee, solo 5 revientan el arranque si
faltan** (`DJANGO_SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`JWT_SIGNING_KEY`). Las otras 48 tienen un default silencioso elegido para que `docker compose up`
funcione sin configurar nada. Seis de esos defaults deciden cosas que en producción no son de
desarrollo:

| Variable | Default | Qué produce si falta en Railway |
|---|---|---|
| `DJANGO_DEFAULT_FILE_STORAGE` | `FileSystemStorage` ([base.py:350](MailySoft/backend/config/settings/base.py)) | **Las imágenes clínicas, firmas y PDFs se escriben en el disco efímero del contenedor y desaparecen en el siguiente deploy.** La BD conserva las rutas: expediente con imágenes rotas, sin recuperación |
| `PRESCRIPTION_VERIFY_SECRET` | `SECRET_KEY` ([base.py:540](MailySoft/backend/config/settings/base.py) y de nuevo en [verification.py:50](MailySoft/backend/apps/recetas/verification.py)) | Rotar `SECRET_KEY` invalida **todos los QR ya impresos**. Filtrar `SECRET_KEY` permite firmar cualquier receta. La variable vacía se comporta igual que ausente |
| `PRESCRIPTION_VERIFY_BASE_URL` | `http://localhost:5173` ([base.py:541](MailySoft/backend/config/settings/base.py)) | **Cada receta impresa lleva un QR que apunta a `localhost`.** Está en `.env.production.example:29` y **falta en el bloque que `DEPLOY-RAILWAY.md:80-99` manda copiar** |
| `REDIS_URL` | `localhost` + `IGNORE_EXCEPTIONS: True` ([base.py:195](MailySoft/backend/config/settings/base.py), [:198](MailySoft/backend/config/settings/base.py)) | El throttle de login (5/min) lee el historial con `cache.get()`; con el caché caído devuelve `None` y **cada petición pasa**. El límite de intentos desaparece sin dejar rastro |
| `DJANGO_EMAIL_BACKEND` | `console.EmailBackend` ([base.py:395](MailySoft/backend/config/settings/base.py)) | Todo correo se imprime en el log de Railway y nadie lo recibe, sin error |
| `SENTRY_DSN` | `""` ([base.py:554](MailySoft/backend/config/settings/base.py)) | Sentry no se inicializa. No está en `DEPLOY-RAILWAY.md` |

Dos casos merecen párrafo aparte:

**El almacenamiento ya falló una vez y se «arregló» con un comentario.** El propio
[base.py:345-347](MailySoft/backend/config/settings/base.py) dice: «Django los IGNORA silenciosamente
(media caía a FileSystemStorage → imágenes 404 en prod)». La corrección fue documentar el incidente
encima del setting, no poner una guardia de arranque. Y la guardia que sí existe
([production.py:117-125](MailySoft/backend/config/settings/production.py), «BAJO-3») protege
**S3, que este proyecto no usa**; para Cloudinary, que es el almacenamiento real, no hay ninguna. Con
la entrega por defecto de Cloudinary cada foto de paciente y cada PDF de receta tiene una URL pública
que responde sin autenticación a quien la tenga — eso es `B-PAC-02`, y la decisión de aceptarlo vive
en una frase de `DEPLOY-RAILWAY.md:44` («para el piloto está bien así»), no en una guardia.

**El timbrado fiscal real es inalcanzable por código, no por configuración.**
[adapters/cfdi.py:187-189](MailySoft/backend/adapters/cfdi.py) lee `settings.FACTURAMA_API_USER`,
`FACTURAMA_API_PASSWORD` y `FACTURAMA_BASE_URL` — y **ningún archivo de `config/settings/` define
esos tres settings**. Poner las variables en Railway no cambia nada: `getattr` devuelve `""` y la
factory retorna **siempre** el adaptador simulado ([cfdi.py:193-199](MailySoft/backend/adapters/cfdi.py)),
que inventa un UUID contra `https://sandbox.cfdi.local/`. La clínica ve «CFDI timbrado», entrega el
comprobante al paciente y **no existe ante el SAT**. Esto resuelve el `NO VERIFICADO` de
`02-contrato.md:4977`: no hace falta verificar Railway, hace falta tocar código.

**Dónde se arregla.** En [config/settings/production.py](MailySoft/backend/config/settings/production.py),
añadiendo guardias de arranque con el patrón que el proyecto **ya sabe escribir** — «BAJO-3» en
`:117-125` y la validación de `DB_TENANT_GUC_MODE` en [base.py:183](MailySoft/backend/config/settings/base.py)
revientan ruidosamente ante un valor inválido. Faltan cuatro más. Y hay que corregir el bloque de
variables de `DEPLOY-RAILWAY.md`, que es lo que alguien copia y pega.

**Qué se rompe si no se arregla.** Un deploy sale verde con la aplicación mal configurada y el
defecto se descubre semanas después: cuando el expediente muestra imágenes rotas, cuando la farmacia
escanea un QR que no abre, o cuando el SAT no reconoce un comprobante. La forma del fallo es siempre
la misma: **no hay error, hay silencio.**

**Un detalle de `django-environ` que rompe tres guardias existentes.** Verificado empíricamente por
la auditoría: `env("X")` sin default lanza `ImproperlyConfigured` cuando la variable **falta**, pero
devuelve `''` sin excepción cuando está **presente y vacía**. Como `backend/.env.example:37-40` trae
`JWT_SIGNING_KEY=` vacía y afirma «sin este valor el backend no arranca», quien copie esa plantilla
obtiene un deploy verde, un healthcheck que pasa y **500 en todos los logins**. La promesa escrita es
falsa y desvía el diagnóstico.

---

## CR-03 · No existe capa de permisos por objeto: la autoridad por pertenencia vive suelta en los services

**Gravedad: P0** (escalada de privilegios en `D-1`/`D-2`) · **Cierra:** `F-1A-06`, `F-1A-07`,
`F-1A-08`, `F-1B-03`, `F-1C-03`, `F-1C-14`, `B-EXP-01`, `B-EXP-12`, `B-AGE-03`, `B-AGE-04`,
`B-REC-02`, `D-1`, `D-2`

**Qué pasa.** DRF tiene dos capas de autorización: `has_permission`, que decide por endpoint y sabe
el rol, y `has_object_permission`, que decide por objeto y sabe si *este* usuario puede tocar *este*
registro. **Este proyecto no usa la segunda en ningún punto:** verificado en esta auditoría, cero
apariciones de `has_object_permission` y cero de `check_object_permissions` en `apps/` y `config/`,
frente a **50 clases de permiso** en [core/permissions.py](MailySoft/backend/apps/core/permissions.py),
todas de nivel endpoint.

Consecuencia directa: toda regla de pertenencia —«el médico solo anula su receta», «el médico solo
escribe sobre sus citas», «el dueño no puede fabricar un segundo dueño»— vive dispersa dentro de los
`services`, en 23 `PermissionDenied` fuera de la capa de permisos. Eso produce tres fallas distintas
que hasta ahora se habían reportado como si fueran independientes:

1. **El frontend no puede expresarla.** `/me/` le entrega un rol, no la lista de objetos propios del
   usuario. Con solo una matriz de rol, la interfaz o muestra de más o esconde de más: los cinco
   hallazgos `F-1A-06`, `F-1A-07`, `F-1A-08`, `F-1B-03`, `F-1C-03`. La auditoría de frontend ya lo
   llamó «el hallazgo estructural»; esta es su causa.
2. **Cuando un service olvida la comprobación, no hay segunda red.** `B-EXP-01` (el addendum y el
   diagnóstico no aplican la regla del médico dueño de la cita), `B-AGE-04` («un médico solo agenda
   para sí mismo» existe solo al crear), `B-AGE-03` (un médico cancela por `/estado/` lo que el
   `DELETE` le niega), `B-REC-02` (cualquier médico edita el formato de receta de otro).
   `B-EXP-12` es el mismo patrón en su forma más peligrosa: las tres reglas por rol de los services
   son **fail-open ante `actor_role` vacío**.
3. **El error sale con forma inconsistente.** Un rechazo por pertenencia llega como 400 o 403 desde
   el service, no como el 403 uniforme de la capa de permisos, y el frontend borra el mensaje al
   mapearlo (`F-1C-14`) justo donde el motivo es lo único que orienta al usuario.

**Los dos casos de escalada de privilegios.** Son `D-1` y `D-2` del documento de frontend, y no son
de frontend: [tenancy/services.py:406-411](MailySoft/backend/apps/tenancy/services.py) — la
comprobación anti-segundo-dueño y la allow-list de roles del plan viven **solo en `member_create`**.
`member_update` no las tiene: un `PATCH /miembros/<id>/` deja la clínica con dos dueños, y en plan
Básico convierte a alguien en `admin` cuando el alta lo rechaza con 400. El frontend ofrece ese
camino ([MiembroDetalleDrawer.tsx:85](MailySoft/web-soft/src/components/personal/MiembroDetalleDrawer.tsx)).

**Dónde se arregla.** Subir las reglas de pertenencia de los services a
[core/permissions.py](MailySoft/backend/apps/core/permissions.py) como `has_object_permission`, y
llamar `check_object_permissions` en las vistas de detalle. Como efecto secundario, el backend puede
entonces exponer la decisión al frontend (un `can_edit`/`can_cancel` por objeto en el serializer),
que es la única forma de que la interfaz deje de adivinar. Los dos casos de escalada se cierran
antes y por separado, en `member_update`.

**Qué se rompe si no se arregla.** Cada regla de negocio nueva que dependa de «es tuyo» hay que
recordar escribirla a mano en cada service que toque el objeto, y olvidarla no rompe ningún test
(ver CR-17). Hoy ya se olvidó cuatro veces.

---

## CR-04 · La resolución por id garantiza el tenant y nunca la sede

**Gravedad: P0** (por definición de la escala: «un usuario ve datos de otra sede») ·
**Cierra:** `B-T-05`, `B-AGE-01`, `B-AGE-09`, `B-PER-01`, `B-PER-05`, `B-PER-12`, `B-FIN-15`,
`B-REC-09`, `B-REC-13`, `B-PAC-03`, `B-EXP-09`, `B-CLI-05`, `B-NTF-05`, `B-NOT-04`, `F-4-01`,
`F-4-03`, `F-4-06`, `F-4-08`, `F-4-09`

**Qué pasa.** El resumen de A2 estimó esta causa en 12 hallazgos. Verificada en esta auditoría, es
estructural y más grande: **34 selectores resuelven un objeto por id y ninguno puede acotar por sede,
porque la sede no está en su firma.**

```
apps/agenda/selectors.py:295      agenda_item_note_get(*, note_id: uuid.UUID)
apps/personal/selectors.py:21     doctor_get(*, doctor_id: uuid.UUID)
apps/finanzas/selectors.py:97     concept_get(*, concept_id: uuid.UUID)
apps/expediente/selectors.py:292  evolution_note_get(*, evolution_id: uuid.UUID)
… 30 más
```

El patrón es idéntico en los 34: `Modelo.objects.get(id=...)`. El `TenantManager` garantiza la
clínica; nada garantiza la sede. El listado hermano **sí** la acota, porque la vista llama
`sucursal_scope_ids(request)` antes de invocar al selector — 12 usos en
[agenda/views.py](MailySoft/backend/apps/agenda/views.py), 25 en
[finanzas/views.py](MailySoft/backend/apps/finanzas/views.py), 11 en
[personal/views.py](MailySoft/backend/apps/personal/views.py). La asimetría no es un descuido puntual
repetido: es que **el alcance por sede se implementó en la capa de vista y la resolución por id vive
en la capa de selector**, donde ese dato no llega.

Cuatro apps no tienen ni un solo uso de `sucursal_scope_ids` en sus vistas: `pacientes`,
`expediente`, `recetas` y `pdfs`. Para `pacientes` y `expediente` eso es **decisión de arquitectura
deliberada y correcta** (el paciente y su expediente se comparten entre sedes:
`sucursales-arquitectura-analisis.md:266,273`), pero `B-PAC-03` y `B-EXP-09` señalan con razón que
**esa decisión no está escrita en el contrato**, así que hoy es indistinguible de un olvido.

**Dónde se arregla.** Dos opciones, y conviene decidirla explícitamente en A4:
(a) meter `sucursal_ids` en la firma de los 34 selectores, o
(b) resolver por id dentro de un helper único que reciba el `request` y aplique
[sucursal_scope.py:429](MailySoft/backend/apps/clinica/sucursal_scope.py) antes de devolver.
La (b) es menos código y hace imposible el olvido; la (a) es más explícita. En cualquiera de las dos,
lo que hay que producir es que **sea imposible resolver por id sin declarar el alcance**.

**Qué se rompe si no se arregla.** En una clínica con dos sedes, la administradora de Norte —que no
ve la agenda de Centro— lee y borra por id la nota que el equipo de Centro escribió sobre una cita
(con nombre de paciente y motivo), hace `PATCH`/`DELETE` sobre el médico de Centro, y abre el detalle
de conceptos y paquetes que su sede no presta. Es el caso de uso que el producto vende como
«privacidad entre sedes» y hoy solo funciona en los listados.

---

## CR-05 · El Django admin es una segunda puerta que no respeta las reglas del producto

**Gravedad: P0** · **Cierra:** `B-AUT-02`, `B-AUD-02`, `B-NOT-09`, `B-FIN-18`

**Qué pasa.** Toda la matriz de roles, el aislamiento por clínica y el registro en bitácora viven en
la capa de API. `/admin/` no pasa por ninguno de los tres:

- **Escalada de privilegios sin rastro:** cualquiera con acceso a `/admin/` edita su propio
  `platform_role` e `is_superuser` ([authn/admin.py:29-43](MailySoft/backend/apps/authn/admin.py)).
  Las reglas anti-escalada existen solo en el portal, y **el admin de Django no escribe en la
  bitácora**, así que no queda huella.
- **Lectura cross-tenant de la bitácora:** un rol de `ventas` lee la bitácora de todas las clínicas
  ([audit/admin.py:90-98](MailySoft/backend/apps/audit/admin.py), `:72`), porque la comprobación solo
  pregunta si es staff de plataforma y consulta con `all_objects`. La API sí lo excluye.
- **Fuga de contenido clínico por el buscador:** `NoteAdmin` no restringe audiencia y permite buscar
  dentro del cuerpo de las notas (`B-NOT-09`).
- **Corrupción silenciosa de saldos:** borrar un pago desde `/admin` deja `Charge.amount_paid`
  desincronizado (`B-FIN-18`), porque la lógica de recálculo está en el service.

**Dónde se arregla.** Decidir primero si `/admin/` debe existir en producción. Si la respuesta es sí
(soporte lo necesita), hay que replicar en cada `ModelAdmin` las tres reglas: `get_queryset` acotado,
`has_*_permission` contra `platform_role`, y `log_addition`/`log_change`/`log_deletion` redirigidos a
`audit_record`. Si la respuesta es no, se apaga por `urls.py` en producción y se cierra la causa raíz
entera con una línea.

**Qué se rompe si no se arregla.** Existen dos sistemas de permisos sobre los mismos datos y solo uno
está auditado. Cualquier endurecimiento que se haga en la API deja intacta la otra puerta.

---

## CR-06 · `BaseModel` no declara manager y 30 de 31 constraints ignoran el borrado lógico

**Gravedad: P1** · **Cierra:** `B-T-12`, `B-T-13`, `B-PAC-04`, `B-FIN-11`, `B-CLI-07`, `B-CLI-10`,
`B-REC-16`, `B-CLI-08`, `B-NOT-08`

**Qué pasa.** [core/models.py:19-39](MailySoft/backend/apps/core/models.py) define `deleted_at` en
`BaseModel` pero **no declara ningún manager**. El `TenantManager` que excluye los borrados
(`managers.py:28`) lo aporta `TenantAwareModel`, un nivel más abajo. Los seis modelos que heredan
`BaseModel` directo — `Tenant`, `TenantMembership`, `Plan`, `TenantEntitlements`,
`TenantSubscription` ([tenancy/models.py:22,78,169,262,325](MailySoft/backend/apps/tenancy/models.py))
y `GlobalMedication` ([recetas/models.py:129](MailySoft/backend/apps/recetas/models.py)) — usan el
manager estándar: **`objects` incluye las filas borradas lógicamente**, y hay que acordarse de
filtrarlas a mano. `B-T-12`, `B-T-13` y `B-REC-16` son tres sitios donde no se hizo.

La otra mitad del problema es la base de datos: **de las 31 `UniqueConstraint` del proyecto, una sola
lleva `condition`**. Las otras 30 cuentan las filas borradas. De ahí salen `B-PAC-04` (la unicidad de
CURP), `B-FIN-11` (el nombre de paquete o concepto), `B-CLI-07` (el nombre de sucursal) y `B-CLI-10`
(la etiqueta de paciente): dar de baja algo y volver a crearlo con el mismo nombre produce un
`IntegrityError` que sale al usuario como **500**, con un mensaje que además miente sobre la causa.

**Dónde se arregla.** Un `SoftDeleteManager` en `BaseModel` (`core/models.py`), y una migración que
añada `condition=Q(deleted_at__isnull=True)` a las 30 constraints. La migración es mecánica pero toca
muchas tablas: conviene hacerla sola, en su propio PR, y verificar que sea reversible.

**Qué se rompe si no se arregla.** Cada vez que alguien escribe un selector nuevo sobre un modelo
`BaseModel` tiene que recordar `deleted_at__isnull=True`, y cada vez que una clínica reutiliza el
nombre de algo que dio de baja, ve un error 500 sin explicación.

---

## CR-07 · No existe reactivación, y el cupo del plan cuenta lo inactivo

**Gravedad: P1** · **Cierra:** `B-T-06`, `B-PAC-05`, `B-PER-04`, `B-PER-07`, `B-CLI-02`, `B-CLI-12`

**Qué pasa.** El producto sabe desactivar y no sabe volver a activar. No hay endpoint de
reactivación para un paciente (`B-PAC-05`), un médico o un consultorio (`B-PER-04`), ni una sucursal
(`B-CLI-02`). Y lo desactivado **sigue consumiendo el cupo del plan**: las sucursales (`B-CLI-12`),
los consultorios (`B-PER-07`) y las membresías (`B-T-06`, donde bloquear a alguien apaga
`user.is_active` y no `membership.is_active`, [tenancy/services.py:441](MailySoft/backend/apps/tenancy/services.py)).

El escenario completo, que es el que llega a soporte: una clínica en plan Básico (tope 3 usuarios)
despide a su recepcionista, la bloquea como indica la interfaz, e intenta dar de alta al reemplazo.
Recibe *«El plan de esta clínica permite 3 usuarios y ya hay 3»*. **No hay salida desde el producto**:
ni borrar, ni liberar el cupo. La única vía es subir de plan o que alguien entre al admin de Django.

**Dónde se arregla.** En los services de cada dominio y en `tenancy/services.py:254-260` (el conteo).
Es una decisión de producto antes que técnica: hay que definir qué significa «dar de baja» para cada
entidad y si libera cupo.

**Qué se rompe si no se arregla.** Un cliente que paga se queda bloqueado por una operación normal de
su negocio, y la única solución disponible es intervención manual sobre la base de datos.

---

## CR-08 · La bitácora lleva PII y se escribe en modo silencioso

**Gravedad: P1** · **Cierra:** `B-AUD-06`, `B-NOT-02`, `B-NOT-03`, `B-NTF-01`, `B-AGE-16`,
`B-AUT-06`, `B-AUD-07`, `D-TEST-10`

**Qué pasa.** La regla dura nº5 del proyecto pide registrar las acciones sensibles «con un
identificador no-PII del recurso». La firma de `audit_record` solo aplica esa restricción a **un**
campo: [audit/services.py:58](MailySoft/backend/apps/audit/services.py) documenta `metadata` como
«contexto adicional SIN PII», mientras `resource_repr` (`:56`) es una «representación legible» y
`description` (`:57`) una «descripción en lenguaje natural». Son exactamente los dos campos donde
cae el nombre del paciente, y ahí caen sistemáticamente (`B-AUD-06`, `B-AGE-16`, `B-NOT-03`). El
mismo patrón se repite en las notificaciones, que copian el cuerpo de la nota y el texto clínico a
la fila de cada destinatario y ahí se quedan (`B-NOT-02`, `B-NTF-01`), sin caducidad (`B-NTF-02`).

**Y la escritura es best-effort por diseño explícito:** `audit_record` «absorbe todas las
excepciones: si el `INSERT` falla, loguea el error y devuelve `None`. El caller nunca recibe una
excepción de auditoría» ([audit/services.py:43-44](MailySoft/backend/apps/audit/services.py)). En un
requisito normativo eso significa que una acción sensible puede completarse **sin dejar rastro** y
nadie se entera salvo que alguien lea los logs de aplicación. `B-AUT-06` es ese caso concreto: un
inicio de sesión exitoso puede quedar sin registro.

Nada de esto lo detecta ninguna prueba: de los **123 `ActionType` distintos, 72 no tienen ninguna
aserción de bitácora** en la suite, incluidos todos los de dinero (`PAYMENT_REGISTER`, `CHARGE_*`,
`CFDI_ISSUE`, `CFDI_CANCEL`) y todos los de cambio de privilegios (`MEMBER_UPDATE`,
`TENANT_ENTITLEMENTS_SET`, `MEMBERSHIP_SUCURSALES_SET`). La verificación anti-PII existe para
exactamente cuatro acciones.

**Dónde se arregla.** En [audit/services.py](MailySoft/backend/apps/audit/services.py): restringir
`description` y `resource_repr` a plantillas sin PII, y decidir qué hacer cuando el `INSERT` falla
(al menos, un contador y una alerta; en las acciones más sensibles, fallar la operación). Y una
prueba parametrizada sobre los 123 `ActionType` que exija aserción de bitácora, que cierra a la vez
`D-TEST-10`.

**Qué se rompe si no se arregla.** Ante una auditoría normativa no hay forma de reconstruir quién
cobró, quién dio acceso a una sede o quién validó una cédula; y la propia bitácora —que es el
documento que se entregaría— contiene los datos personales que debería proteger.

---

## CR-09 · El `*_get` está optimizado y el `*_list` hermano no

**Gravedad: P1** · **Cierra:** `D-PERF-01`, `D-PERF-03`, `D-PERF-04`, `D-PERF-05`, `D-PERF-12`

**Qué pasa.** El mismo modelo tiene dos selectores: el de detalle, que precarga bien sus relaciones,
y el de listado, que no — aunque comparte serializer. El caso más claro:
[finanzas/selectors.py:140](MailySoft/backend/apps/finanzas/selectors.py) (`quote_get`) hace
`prefetch_related("items")` y `:160` (`quote_list`) no, mientras el docstring del propio serializer
([finanzas/serializers.py:128](MailySoft/backend/apps/finanzas/serializers.py)) afirma que
«`quote_get`/`quote_list` ya lo hacen». **El código contradice su propia documentación**, y el
`SerializerMethodField` recorre los ítems una segunda vez: 50 consultas extra por página de 25.

| Listado | Falta | Coste estimado por página |
|---|---|---|
| Citas ([agenda/selectors.py:208](MailySoft/backend/apps/agenda/selectors.py)) | `appointment_type` | hasta 25 consultas |
| Pagos ([finanzas/selectors.py:300](MailySoft/backend/apps/finanzas/selectors.py)) | `allocations` | 25 |
| Cotizaciones ([finanzas/selectors.py:160](MailySoft/backend/apps/finanzas/selectors.py)) | `items` (×2) | 50 |
| Eventos de agenda ([agenda/selectors.py:75](MailySoft/backend/apps/agenda/selectors.py)) | `doctor__membership__user` | 2 por evento, **sin paginar** |
| Evoluciones ([expediente/selectors.py:335](MailySoft/backend/apps/expediente/selectors.py)) | — trae 4 JOINs que el serializer no usa | sobrepeso |

El de citas es el que más duele porque la agenda se auto-refresca cada 60 s
([hooks/agenda.ts:73](MailySoft/web-soft/src/hooks/agenda.ts)): una recepcionista con la pestaña
abierta ocho horas genera del orden de **12 000 consultas al día** solo para pintar el color del tipo
de cita. *(Conteos derivados del código, no medidos: no hubo base de datos en esta sesión.)*

**Dónde se arregla.** En los `selectors.py`. Y para que no vuelva: `django_assert_num_queries` en los
listados prioritarios — hoy solo 5 archivos de 126 cuentan consultas, y el único test que cubre el
listado de citas ([agenda/tests/test_selectors.py:467](MailySoft/backend/apps/agenda/tests/test_selectors.py))
**no pasa por el serializer**, así que da falsa confianza.

**Qué se rompe si no se arregla.** Las pantallas más usadas del producto degradan con el número de
clínicas conectadas, y el síntoma que llega es «el sistema está lento», sin más detalle.

---

## CR-10 · Paginación de DRF por defecto donde la interfaz espera la lista completa

**Gravedad: P1** · **Cierra:** `B-AGE-22`, `B-AGE-07`, `B-PLA-03`, `D-PERF-02`, `D-PERF-05`,
`D-PERF-13`

**Qué pasa.** Todo endpoint pagina a 25 ([base.py:215](MailySoft/backend/config/settings/base.py)),
sin `page_size_query_param`, y el frontend consume varios de ellos como si devolvieran la lista
entera. `B-AGE-22` lo reportó y dejó el lado del frontend en NO VERIFICADO. **Queda verificado, y sí
trunca:** `ListAppointmentsParams`
([api/agenda.ts:21-27](MailySoft/web-soft/src/api/agenda.ts)) no tiene `page` ni `page_size` —
estructuralmente el cliente no puede pedir la página 2 — y
[AgendaPage.tsx:272](MailySoft/web-soft/src/pages/AgendaPage.tsx) consume `apptData?.results ?? []`
sin navegación.

Con orden ascendente por hora, una clínica con 60 citas ve las primeras 25: **desaparece la tarde
completa**, sin ningún aviso. Recepción planifica sobre una agenda incompleta.

Y hay un caso peor, encontrado al verificar este hallazgo:
[hooks/agenda.ts:82](MailySoft/web-soft/src/hooks/agenda.ts) pide el historial de citas de un
paciente **sin rango de fechas**. Un paciente crónico con más de 25 citas muestra 25 en su
expediente, y no existe camino para ver el resto. Eso es un dato clínico incompleto presentado como
completo.

En dirección contraria, tres endpoints no paginan nada y deberían: los eventos de agenda
([agenda/views.py:933](MailySoft/backend/apps/agenda/views.py), que además no exige rango de
fechas — `B-AGE-07`), el estado de cuenta del paciente (`D-PERF-13`, sin tope de movimientos) y los
movimientos del cierre diario.

**Dónde se arregla.** Decidir endpoint por endpoint: o el cliente pagina de verdad, o el endpoint
declara explícitamente que devuelve todo y acota por otra vía (rango de fechas obligatorio). Lo que
no puede seguir es que el backend pagine y el cliente no lo sepa.

**Qué se rompe si no se arregla.** El producto muestra datos incompletos sin decirlo. Es la clase de
fallo que el usuario no reporta como bug, porque no tiene forma de saber que falta algo.

---

## CR-11 · Los filtros de fecha con `__date` invalidan todos los índices de finanzas

**Gravedad: P1** · **Cierra:** `D-PERF-07`, `D-PERF-08`, `D-PERF-11`, `D-PERF-14`

**Qué pasa.** Todos los filtros de fecha de finanzas usan `__date`
([finanzas/selectors.py:528](MailySoft/backend/apps/finanzas/selectors.py), `:1059`, `:398`, `:635`,
`:657`; [retention.py:181](MailySoft/backend/apps/finanzas/retention.py), `:199`, `:363`). Con
`USE_TZ=True` y `TIME_ZONE="America/Mexico_City"`, Django emite
`(issued_at AT TIME ZONE 'America/Mexico_City')::date >= …`, y **ningún índice btree sobre una
columna `timestamptz` es utilizable con esa expresión encima**. No existe ningún índice de expresión
que compense: `CREATE INDEX` no aparece en ninguna migración del proyecto.

Es el mismo problema por otras dos vías: los índices compuestos no incluyen `deleted_at`, que el
manager añade a **toda** consulta ([managers.py:28](MailySoft/backend/apps/core/managers.py)), y los
índices de notificaciones no empiezan por `tenant`
([notificaciones/models.py:128-133](MailySoft/backend/apps/notificaciones/models.py)) aunque RLS
inyecta ese predicado siempre — siendo el endpoint que más se pide del sistema, cada 30 s por la
campana. La convención correcta existe: los índices de `Appointment`, `Charge` y `Patient` sí
empiezan por `tenant`.

**Dónde se arregla.** Reescribir los filtros como rango sobre el `timestamptz`
(`>= inicio_del_día AND < inicio_del_día_siguiente`, calculando los límites en Python con la zona de
la clínica), que además arregla de paso lo que `B-T-20` señala sobre `Tenant.timezone`; y añadir
`deleted_at` y `tenant` a los índices compuestos.

**Qué se rompe si no se arregla.** El coste del cierre diario crece con la antigüedad de la clínica,
no con el volumen del día: **el cliente que lleva más tiempo pagando es el que peor experiencia
tiene.**

---

## CR-12 · El frontend deriva los permisos de una matriz de rol escrita contra un plan, no contra el código

**Gravedad: P1** · **Cierra:** `F-1A-01`, `F-1A-02`, `F-1A-03`, `F-1A-04`, `F-1B-01`, `F-1B-02`,
`F-1B-05`, `F-1B-11`, `F-1C-01`, `F-1C-05`, `F-1C-06`, `F-1C-08`, `F-1D-02`, `F-1D-03`, `F-1D-09`,
`F-1D-11`, `F-1D-12`, `F-4-07`

**Qué pasa.** [auth/permisos.ts](MailySoft/web-soft/src/auth/permisos.ts) es una copia manual de la
matriz de permisos, escrita contra un documento de diseño y no contra
[core/permissions.py](MailySoft/backend/apps/core/permissions.py). Las dos derivaron. El resultado
tiene dos formas simétricas, y las dos cuestan dinero:

- **Botón fantasma:** la interfaz ofrece una acción que el backend rechaza con 403. El usuario
  aprende que «el sistema falla».
- **Función invisible:** el backend concede una capacidad que ninguna pantalla ofrece. La clínica
  pagó por algo que no puede usar y nadie lo sabe — enfermería no puede tocar el directorio de
  pacientes ni registrar alergias, recepción está bloqueada del cierre de caja, `readonly` no entra a
  cotizaciones.

**Dónde se arregla.** La matriz no debe escribirse dos veces. Lo barato es exponerla desde el backend
(un endpoint o un bloque en `/me/` derivado de `core/permissions.py`) y que el frontend la consuma;
lo mínimo, un test que compare ambas y falle al divergir. Cualquiera de las dos convierte esta causa
raíz en imposible, en vez de arreglar 18 hallazgos uno por uno.

**Qué se rompe si no se arregla.** Cada cambio de permisos en el backend introduce nuevos hallazgos
de este tipo sin que nada avise, y el conteo vuelve a crecer.

---

## CR-13 · El arranque de la sesión falla abierto

**Gravedad: P1** · **Cierra:** `F-1D-01`, `F-1D-06`, `F-2-03`, `F-2-10`, `F-5-01`, `F-5-02`,
`D-FE-12`

**Qué pasa.** Mientras `/me/` no responde —o cuando no responde nunca— el frontend tiene que asumir
algo, y no hay un criterio escrito sobre qué. Hoy hay cuatro decisiones del mismo tipo y **tres
apuntan al lado inseguro**:

| Dónde | Cae a | Lado |
|---|---|---|
| [auth/RoleContext.tsx:15](MailySoft/web-soft/src/auth/RoleContext.tsx) | `readonly` | seguro |
| [platform/PlatformRoleContext.tsx:19](MailySoft/web-soft/src/platform/PlatformRoleContext.tsx) | `super_admin` | **inseguro** |
| [App.tsx:50](MailySoft/web-soft/src/App.tsx) (guard de módulo con `capabilities` nulo) | abierto | **inseguro** |
| [auth/useRole.ts:18](MailySoft/web-soft/src/auth/useRole.ts) (hook huérfano) | `owner` | **inseguro** |

Ninguna abre datos por sí sola, porque el backend filtra. Pero `F-1D-01` sí tiene consecuencia hoy:
el menú «Ver como (demo)» deja a cualquier staff de Maily navegar como súper admin. Y el hook
huérfano de `useRole.ts` es una trampa de autocompletado: nadie lo importa (Rollup lo elimina), pero
tiene el mismo nombre que el hook vigente y persiste el rol en `localStorage`, editable desde la
consola.

**Dónde se arregla.** Escribir la regla una vez —«mientras la sesión no esté resuelta, mínimo
privilegio; si `capabilities` es nulo, cerrado»— y aplicarla en los cuatro sitios. Borrar
`auth/useRole.ts` y el selector de demo del build de producción.

**Qué se rompe si no se arregla.** El día que el backend deje de ser la única defensa —o que alguien
mueva una comprobación al cliente— estos cuatro defaults deciden a favor del atacante.

---

## CR-14 · Capacidad implementada y facturada a la que ningún clic llega

**Gravedad: P1** · **Cierra:** `F-1A-05`, `B-REC-01`, `F-1C-02`, `F-2-01`, `F-1A-13`, `F-1A-14`,
`F-1C-09`, `F-1D-08`, `F-1D-13`, `B-FIN-08`, `B-AGE-14`, `D-DEP-08`

**Qué pasa.** Diez funciones completas, implementadas en el backend y en varios casos vendidas en un
plan, no tienen ninguna pantalla alcanzable. Dos son graves por sí solas:

- **`F-1A-05` — el addendum.** Es el único canal para corregir una nota de evolución firmada, la UI
  existe en `EvolucionTab.tsx` y **ningún componente la importa**; el expediente real monta
  `LibroClinico` ([ExpedienteDrawer.tsx:49](MailySoft/web-soft/src/components/contactos/ExpedienteDrawer.tsx)),
  que no lo ofrece. El backend sí expone la ruta
  ([expediente/urls.py:119](MailySoft/backend/apps/expediente/urls.py)). Consecuencia: la regla dura
  nº4 («lo clínico se corrige con addendum») **no tiene hoy cómo cumplirse**. Un error en una nota
  firmada no se puede corregir por ningún camino de la aplicación.
- **`B-REC-01` — los medicamentos controlados.** No existe ninguna ruta para marcar un medicamento
  como controlado: el catálogo se siembra sin el campo y el serializer lo rechaza. Una receta de
  Clonazepam sale como receta común, sin folio de recetario especial y sin vigencia de 30 días.
- **`F-1C-02` — los datos fiscales del emisor.** Una clínica Premium compra CFDI y no hay pantalla
  donde capturar RFC, razón social y régimen: todo timbrado falla. Con `D-DEP-08` encima (el
  adaptador real es inalcanzable por código), la capacidad «facturación» no funciona por dos motivos
  independientes.

**Dónde se arregla.** Producto antes que código: decidir cuáles de las diez se construyen y cuáles se
retiran del catálogo de planes. Vender un módulo que no tiene pantalla es un problema comercial antes
que técnico.

**Qué se rompe si no se arregla.** Se cobra por capacidades que no existen desde la interfaz, y en el
caso del addendum y de los controlados hay además un incumplimiento clínico.

---

## CR-15 · El gating por módulo se evalúa por rol antes que por capacidad, y el frontend no lo pregunta

**Gravedad: P1** · **Cierra:** `F-2-02`, `F-2-04`, `F-2-05`, `F-2-06`, `F-2-07`, `F-2-08`, `F-2-09`,
`B-T-08`, `B-AGE-08`, `B-REC-07`, `B-CLI-04`, `B-EXP-08`, `B-T-07`, `D-TEST-07`, `D-TEST-08`

**Qué pasa.** La regla dura nº3 dice que un módulo apagado responde **404**, no 403: la clínica no
debe saber que existe algo que no compró. Falla en tres capas a la vez.

- **En el backend, por orden de evaluación:** el permiso de rol se evalúa antes que el guard de
  módulo, así que un rol sin acceso recibe 403 —y por tanto sabe que el endpoint existe— tenga o no
  el módulo contratado (`D-3` del documento de frontend). `OPTIONS` se salta ambos y devuelve 200 con
  el nombre de la vista (`B-T-07`).
- **En el backend, por guards ausentes:** los PDFs genéricos (`B-REC-07`), el catálogo de equipo
  (`B-CLI-04`), la calendarización tocando cotizaciones y paquetes (`B-EXP-08`), y el módulo
  `recordatorios`, que **se factura en los cuatro planes y no gatea ni una sola vista**
  ([entitlement_guards.py:93](MailySoft/backend/apps/core/entitlement_guards.py) tiene 0 vistas —
  `B-T-08`, `B-AGE-08`, `F-2-04`).
- **En el frontend, por rutas que preguntan por rol y no por módulo:** siete pantallas (`F-2-02`,
  `F-2-05` a `F-2-09`).

Nada de esto lo cubren las pruebas: **7 de los 12 módulos no tienen ni un test de 404**, y los 5
cubiertos prueban un endpoint de diez ([test_gating_api.py:47](MailySoft/backend/apps/core/tests/test_gating_api.py)).
El helper `require_module`, que sí tiene tres tests, **no lo llama nadie en producción**
(`D-TEST-08`): da la sensación de que el gating fuera del ciclo de request está probado, y no existe.

**Dónde se arregla.** Invertir el orden de evaluación en
[core/permissions.py](MailySoft/backend/apps/core/permissions.py) (módulo antes que rol); añadir los
guards que faltan; y en el frontend, derivar el acceso a la ruta de `capabilities`, no del rol. La
prueba que lo fija es una matriz parametrizada módulo × endpoint.

**Qué se rompe si no se arregla.** Una clínica que no compró Expediente entra por URL a sus 27 vistas
—o, al revés, un módulo comprado responde 404 y el cliente no puede trabajar— y ninguno de los dos
casos rompe CI.

---

## CR-16 · Una semilla de datos de prueba puede tomar la clínica más antigua de producción

**Gravedad: P0** · **Cierra:** `D-FE-01`

**Qué pasa.** [seed_e2e_user.py](MailySoft/backend/apps/authn/management/commands/seed_e2e_user.py)
crea los usuarios de las pruebas E2E con contraseña conocida. Su `help` dice «Solo dev/local»
(`:45`) y **no hay ninguna guardia de código**: `handle()` (`:55`) no comprueba `DEBUG` ni el módulo
de settings. Ejecutarlo desde el shell de Railway:

- con `--platform`, crea o actualiza `e2e-admin@maily.local` con `is_platform_staff=True`,
  `platform_role=SUPER_ADMIN`, `must_change_password=False` y una contraseña que está **publicada en
  el repositorio en tres archivos** (`seed_e2e_user.py:37,41`, y los dos `.spec.ts`);
- sin `--platform`, elige `Tenant.objects.order_by("created_at").first()` (`:64-66`) — es decir,
  **hace `OWNER` del tenant más antiguo**, que en producción es el primer cliente de pago — y hace
  `set_password` incondicionalmente (`:88`, «siempre, para garantizar la contraseña conocida»).

El gatillo requiere hoy que un humano lo ejecute: verificado que
[entrypoint.sh:64-77](MailySoft/backend/entrypoint.sh) solo migra y hace `collectstatic`. Es P0 igual:
la escala de este documento incluye «secreto expuesto» y «escalada de privilegios», y aquí hay ambos
sin ninguna barrera técnica que los impida.

**Dónde se arregla.** Una guardia al principio de `handle()` que aborte si `DEBUG` es falso o si el
módulo de settings es `production`, y rotar la contraseña. Conviene revisar con el mismo criterio los
demás comandos de siembra (`seed_demo`, `seed_finanzas`, `seed_planes`).

**Qué se rompe si no se arregla.** Un comando escrito para local, disponible en el shell de
producción, que en el peor caso reasigna la propiedad de la clínica de un cliente real.

---

## CR-17 · CI no ejerce RLS, no toca el frontend y no importa los settings de producción

**Gravedad: P1** · **Cierra:** `D-TEST-04`, `D-TEST-05`, `D-TEST-06`, `D-TEST-11`, `D-TEST-13`,
`D-TEST-14`, `D-TEST-17`, `D-TEST-18`, `D-TEST-19`, `D-FE-02`, `D-FE-03`, `D-FE-06`, `D-FE-07`,
`D-FE-08`, `D-FE-09`, `D-FE-11`

**Qué pasa.** La suite de backend es grande y bloqueante: 3 140 funciones de test, y el job `test`
no lleva `continue-on-error` ([ci.yml:86-97](.github/workflows/ci.yml)). El problema es su
perímetro.

- **El frontend está entero fuera de CI.** Los cuatro jobs son de Python: no hay `setup-node` ni
  `working-directory: MailySoft/web-soft`. Un PR que rompe el frontend pasa en verde y el error
  aparece en el `docker build` de Railway ([Dockerfile:28](MailySoft/Dockerfile)) — con el merge
  hecho y la migración de backend ya aplicada.
- **`npm run lint` no puede ejecutarse:** el script existe
  ([package.json:10](MailySoft/web-soft/package.json)) y **no hay ningún archivo de configuración de
  ESLint** en `web-soft/`. Los 9 `eslint-disable-next-line react-hooks/exhaustive-deps` del código
  suprimen una regla que nadie evalúa.
- **Los settings de producción no se importan en ningún test** y no hay `manage.py check --deploy`:
  la suite corre con `config.settings.development` y `DJANGO_DEBUG=True`
  ([ci.yml:89,95](.github/workflows/ci.yml)). El flujo de refresh y logout con
  `CSRF_COOKIE_SAMESITE="Strict"` solo se prueba en modo dev.
- **Los e2e no corren en ninguna parte** y no pueden correr desatendidos: exigen backend local,
  dos comandos de siembra a mano, y esperan al throttle real con `waitForTimeout(15_000)` repetido.
  El último commit que los tocó es del 2026-07-03. Tres de sus seis pruebas se auto-saltan si falla
  la primera, y Playwright termina con código 0.
- **Tres tests no pueden fallar:** uno sin ninguna aserción
  ([clinica/tests/test_apis.py:775](MailySoft/backend/apps/clinica/tests/test_apis.py)), uno que
  acepta `201` o `403` indistintamente, y uno que hace `pytest.skip` justo en el escenario que debe
  detectar. Y **hay 8 aserciones de la forma `status_code in (403, 404)`** en tests de seguridad de
  sedes, cuando el contrato distingue explícitamente los dos códigos.
- **El umbral de cobertura está 15 puntos por debajo de la cobertura real** (`--cov-fail-under=80`
  frente al ~95 % declarado): se puede borrar el 15 % de la suite sin que CI diga nada.

**Dónde se arregla.** Un job de Node que corra `npm run build` (que ya incluye `tsc -b`) cierra el
agujero más grande por muy poco esfuerzo. Después: configuración de ESLint, `check --deploy` con
settings de producción, rol NOSUPERUSER para la suite (CR-01), y subir el umbral de cobertura al
nivel real.

**Qué se rompe si no se arregla.** El proyecto tiene una suite que inspira confianza y un perímetro
que no cubre ni el cliente, ni la configuración con la que arranca en producción, ni la barrera de
base de datos que sostiene el aislamiento.

---

## CR-18 · Dependencias sin proceso de actualización ni auditoría bloqueante

**Gravedad: P1** · **Cierra:** `D-DEP-09`, `D-DEP-10`, `D-DEP-11`, `D-DEP-12`, `D-DEP-18`,
`D-DEP-19`, `D-DEP-20`

**Qué pasa.** `pip-audit` y `npm audit` corrieron con red en esta auditoría: **36 vulnerabilidades
conocidas en 7 paquetes del backend** y **12 en el frontend** (6 altas, 6 moderadas). Las que
importan:

| Paquete | Fijado | Advisories | Por qué importa aquí |
|---|---|---|---|
| `pillow` | 12.2.0 | **16** | Procesa **archivos subidos por el usuario** ([core/files.py:27](MailySoft/backend/apps/core/files.py), y los pipelines de PDF). Superficie remota real |
| `django` | 5.2.15 | 3 | Parche menor dentro de la misma LTS |
| `pypdf` | 6.13.3 | 6 | **Entra solo por `xhtml2pdf`, que no se importa en ninguna parte** |
| `weasyprint` | 62.3 | 2 (una sin parche) | Genera todos los PDFs clínicos |
| `react-router-dom` | ^6.25.1 | open redirect → XSS | Es dependencia directa del cliente |

`pip-audit` está declarado como dependencia de desarrollo y **corre en CI con
`continue-on-error: true`** ([ci.yml:186](.github/workflows/ci.yml)): informa y no bloquea. `npm
audit` no corre.

Además hay peso muerto que aporta riesgo sin aportar función: `xhtml2pdf` declarado y nunca
importado (arrastra 6 de las 36 vulnerabilidades y ~8 paquetes), `channels` y `channels-redis` en
`INSTALLED_APPS` con un router de WebSocket vacío sobre un despliegue que arranca WSGI, `boto3` y
`django-storages` sin uso, y un `package-lock.json` huérfano de 87 bytes en la raíz del repositorio
que hace que un escáner de CI crea haber auditado el frontend.

**Dónde se arregla.** Actualizar `pillow`, `django` y `cryptography`; retirar `xhtml2pdf` (moviendo
`pypdf` al grupo de desarrollo, que cuatro tests lo usan), `channels`, `channels-redis`, `boto3` y
`django-storages`; borrar el lock huérfano; y decidir si `pip-audit`/`npm audit` bloquean. Los locks
sí están completos y versionados, y la imagen se construye con `poetry install --only=main` y
`npm ci`: **un deploy instala exactamente lo probado**, que es la mitad difícil del problema y ya
está resuelta.

**Qué se rompe si no se arregla.** La ruta de menor resistencia hacia el proceso que tiene la
conexión a la base de datos es una imagen manipulada subida por cualquier usuario autenticado.

---

## CR-19 · La bitácora se traga el fallo de su propio INSERT sin savepoint: la escritura clínica se revierte y la API responde 201

**Gravedad: P0 — es el hallazgo más grave de esta fase** · **Cierra:** `D-TXN-01`, `D-TXN-02`,
`D-TXN-16`

**Qué pasa.** `audit_record` absorbe cualquier excepción por decisión explícita
([audit/services.py:91-99](MailySoft/backend/apps/audit/services.py), y su docstring en `:43`: «el
caller nunca recibe una excepción de auditoría»). Pero **no abre un `transaction.atomic()` propio**
—verificado: cero apariciones de `atomic` en ese archivo— y se llama desde 23 services que **sí**
están decorados con `@transaction.atomic`.

El mecanismo de Django hace el resto: `Model.save_base` corre bajo `mark_for_rollback_on_error`, que
pone `connection.needs_rollback = True` **antes** de que la excepción llegue al `except`. Cuando el
`atomic()` del service sale sin excepción, `Atomic.__exit__` ve esa marca y hace **ROLLBACK sin
lanzar nada**. El service devuelve normalmente. La vista responde 201.

**El disparador está al alcance de cualquier usuario autenticado.** El `request_id` de la bitácora es
un `CharField(max_length=64)` ([audit/models.py:374-375](MailySoft/backend/apps/audit/models.py)) y
se puebla **sin truncar** desde el header `X-Request-Id`
([core/views.py:184-185](MailySoft/backend/apps/core/views.py)) — nótese que la línea inmediatamente
anterior sí trunca el `user_agent` a 512. La segunda vía es la `ip`, tomada del primer valor de
`X-Forwarded-For` sin validar contra un `GenericIPAddressField`.

La auditoría lo **reprodujo contra el Postgres del contenedor**:

```
audit_record: fallo al escribir entrada de auditoría — value too long for type character varying(64)
>>> el bloque atomic SALIO SIN EXCEPCION (el service devolvería 201)
>>> la nota existe en BD? False
```

**Qué se rompe si no se arregla.** Un médico escribe la nota de evolución del paciente, la API
responde 201, el frontend cierra el expediente. **La nota no existe en la base y la bitácora tampoco
tiene rastro.** Basta un `X-Request-Id` de más de 64 caracteres —un proxy mal configurado, un cliente
móvil, o cualquiera que lo mande a propósito— para que toda una sesión de trabajo escriba en el
vacío: notas de evolución, addenda, recetas, diagnósticos, alergias y signos vitales. Es pérdida
silenciosa de datos clínicos, que es la definición de P0 de este documento.

En los ~40 services donde `audit_record` está **fuera** del `atomic`, el efecto es el inverso y
también grave (`D-TXN-02`): la escritura de negocio commitea y la bitácora queda vacía sin que nada
lo señale más allá de un `logger.error`. Sin métrica ni alerta, el requisito normativo falla en modo
silencioso y no habrá forma de saber desde cuándo.

`D-TXN-16` es el mismo mecanismo con otro `try/except`: en
[expediente/services.py:783-799](MailySoft/backend/apps/expediente/services.py) el bloque
«best-effort» que debería impedir que un aviso tumbe la nota envuelve también dos consultas
(`users_with_role`, `filter_recipients_by_sucursal`), así que si una de ellas falla, **tumba la nota
sin avisar** — justo lo contrario de su propósito.

**Dónde se arregla.** Tres cosas, en este orden: (1) envolver el `log.save()` de `audit_record` en su
propio `transaction.atomic()`, que actúa de savepoint y contiene el fallo; (2) truncar `request_id`
en [core/views.py:185](MailySoft/backend/apps/core/views.py) y validar la `ip` antes de guardarla;
(3) revisar los `try/except` best-effort para que envuelvan solo el efecto secundario, no las
consultas previas. El primero cierra la clase entera de fallo; los otros dos quitan los disparadores
conocidos.

---

## CR-20 · Comprobar-luego-actualizar sin lock ni constraint que lo respalde

**Gravedad: P0** (`D-TXN-09` y `B-FIN-02` corrompen dinero) · **Cierra:** `B-FIN-02`, `B-FIN-04`,
`D-TXN-03`, `D-TXN-08`, `D-TXN-09`, `D-TXN-13`, `D-TXN-14`

**Qué pasa.** Un invariante de negocio se verifica leyendo, y se aplica escribiendo, sin nada que
impida que otra petición se cuele en medio. El proyecto tiene 7 `select_for_update` y 73 `atomic`,
así que el patrón correcto se conoce; está puesto en unos sitios y no en los adyacentes.

| Hallazgo | El invariante | Qué falla |
|---|---|---|
| `B-FIN-02` | una cotización se acepta una vez | la guarda de idempotencia está *antes* del `atomic` y sin lock: doble clic genera $36 000 de una cotización de $18 000 |
| `D-TXN-09` | «no se permiten pagos a favor» | el cálculo de deuda ocurre **fuera** del `atomic` ([finanzas/services.py:998-1013](MailySoft/backend/apps/finanzas/services.py)): dos cajas cobran 2 000 a la vez, ambas pasan, la segunda crea un `Payment` con **cero** `PaymentAllocation`. El corte reporta 4 000 recibidos y los cargos dicen 2 000 pagados |
| `D-TXN-08` | no se cancela un cargo ya pagado | `charge_cancel` ([finanzas/services.py:918-931](MailySoft/backend/apps/finanzas/services.py)) no bloquea la fila que `payment_register` sí bloquea en `:1035`: queda un cargo cancelado con un pago aplicado encima |
| `D-TXN-03` | el folio de receta es único | `select_for_update()` + `.aggregate()` **no emite `FOR UPDATE`** (Django lo descarta al colapsar en agregado; verificado contra PG 16). El `UniqueConstraint` rechaza al segundo médico con un `IntegrityError` que la vista no captura → **500 y la receta capturada se pierde, con el paciente enfrente** |
| `D-TXN-14` | la máquina de estados de la cita | sin `atomic` ni lock: recepción marca «atendida» mientras el médico cancela; gana el último `save()` y la cita queda `ATTENDED` con motivo de cancelación poblado |
| `D-TXN-13` | los cupos del plan | `count() >= tope` sin lock: dos altas simultáneas dejan 6 usuarios en un plan de 5, y nadie factura la diferencia |

**Dónde se arregla.** Mover cada comprobación dentro del `atomic` y bloquear la fila que decide
(`select_for_update`), o —mejor donde se pueda— respaldar el invariante con una constraint de base de
datos, que es lo único que no se olvida. El caso del folio necesita además cambiar el patrón:
`aggregate` no conserva el lock, así que hay que usar una secuencia o bloquear explícitamente la fila
de control.

**Qué se rompe si no se arregla.** Todos estos fallos requieren concurrencia, así que no aparecen en
desarrollo ni en las pruebas, y aparecen exactamente cuando el producto empieza a tener uso real:
dos recepcionistas, dos médicos, dos sedes.

---

## CR-21 · El efecto externo y la transacción, en el orden equivocado

**Gravedad: P1** · **Cierra:** `B-FIN-03`, `B-AGE-02`, `D-TXN-06`, `D-TXN-07`, `D-TXN-11`, `D-TXN-12`

**Qué pasa.** Hay dos formas de equivocarse aquí y el proyecto tiene las dos, a veces en el mismo
módulo:

- **El efecto externo dentro del `atomic`.** El PAC de facturación (`B-FIN-03`, ya reportado), la
  subida a Cloudinary en `evolution_image_add`
  ([expediente/services.py:1064](MailySoft/backend/apps/expediente/services.py) con el `create()` en
  `:1133`) y la invalidación de caché en Redis por señal `post_save`
  ([finanzas/cache.py:71-79](MailySoft/backend/apps/finanzas/cache.py)). La foto de una herida de
  8 MB mantiene tomada una conexión de Postgres 15-30 s; con `CONN_MAX_AGE=60` y varios médicos
  documentando, se agota el pool y **el resto de la clínica** —agenda, caja, recetas— recibe timeouts
  sin relación aparente con las fotos.
- **El efecto externo antes del guardado.** `cfdi_cancel`
  ([finanzas/services.py:1248-1263](MailySoft/backend/apps/finanzas/services.py)) cancela ante el SAT
  y **después** guarda, sin `atomic` ni lock: si el guardado falla, la factura sigue apareciendo
  `STAMPED` en Maily y el paciente la descarga, mientras ante el SAT ya no existe. Es el espejo
  exacto de `B-FIN-03`, que hace lo contrario.

**El caso del caché de finanzas (`D-TXN-06`) tiene consecuencia visible hoy:** la versión de caché se
incrementa dentro de la transacción abierta, así que si otro usuario abre el dashboard en esa ventana
se recalcula **sin ver el pago** y guarda ese total viejo bajo la versión nueva. Durante 5 minutos
(TTL) el corte de caja muestra el cobro de menos y no hay botón que lo refresque.

**Y el encolado (`D-TXN-12`, que confirma y precisa `B-AGE-02`):** de los tres encolados del
proyecto, dos usan `transaction.on_commit` correctamente
([pdfs/services.py:66](MailySoft/backend/apps/pdfs/services.py),
[recetas/services.py:1291](MailySoft/backend/apps/recetas/services.py)) y **uno no**:
[agenda/reminders.py:82](MailySoft/backend/apps/agenda/reminders.py), invocado desde cuatro rutas con
transacción abierta. Si se agenda una serie de 12 sesiones y la novena revienta, las 24 tareas ya
publicadas en Redis siguen ahí con su `eta`. Hoy no corrompe datos porque el `eta` es futuro y la
tarea revalida — **pero esa protección es accidental**: un `reminder_offsets_minutes` de pocos
minutos sí se ejecutaría antes del commit.

**Dónde se arregla.** Sacar toda llamada de red fuera del `atomic`; mover la invalidación de caché a
`on_commit` (el patrón ya está escrito en `pdfs/services.py:66`); y en `cfdi_cancel`, guardar el
intento antes de llamar al PAC y reconciliar después.

---

## CR-22 · Operaciones de varios pasos sin transacción común, y validaciones después de escribir

**Gravedad: P1** · **Cierra:** `B-PER-11`, `D-TXN-04`, `D-TXN-15`

**Qué pasa.** `member_update` ([tenancy/services.py:329-450](MailySoft/backend/apps/tenancy/services.py))
hace cuatro escrituras sin ningún `atomic`, y —esto es lo que lo convierte en P1— **cambia la
contraseña en la línea 428 y valida el anti-autobloqueo en la 440**. El serializer acepta ambos
campos en el mismo `PATCH`.

El escenario completo: el dueño manda `PATCH {password: "NuevaClave", blocked: true}` sobre su propia
membresía. La contraseña **ya se cambió y committeó**; la respuesta es 400 «No puedes bloquear tu
propia cuenta»; la interfaz dice que no se guardó nada. El dueño cierra sesión y **no puede volver a
entrar**: su contraseña vieja ya no sirve y él cree que sigue vigente. Solo un `manage.py` desde
Railway lo rescata.

`D-TXN-15` y `B-PER-11` son la misma forma sin el agravante del orden: `treatment_session_unschedule`
cancela la cita y limpia el FK en dos pasos sin `atomic` —mientras su gemelo `treatment_session_schedule`
sí envuelve todo—, y el `PATCH` de un médico aplica tres services sin transacción común.

**Dónde se arregla.** `@transaction.atomic` en los tres services, y **todas las validaciones antes de
la primera escritura**. Esa segunda parte es la regla que conviene escribir en la skill de backend,
porque es la que se olvida al ampliar un service campo por campo.

---

## CR-23 · Adaptadores simulados que reportan éxito y dejan constancia falsa

**Gravedad: P1** · **Cierra:** `B-AGE-05`, `D-TXN-05`, `D-DEP-08`, `D-DEP-13`

**Qué pasa.** Dos integraciones externas están simuladas, ninguna lo dice en la interfaz, y ambas
escriben en la base un estado que afirma que la operación se completó:

- **WhatsApp.** `get_whatsapp_adapter()` ([adapters/whatsapp.py:106-118](MailySoft/backend/adapters/whatsapp.py))
  retorna el simulado **incondicionalmente** — no hay rama que lea `WHATSAPP_ACCESS_TOKEN`, pese al
  TODO — y siempre devuelve `success=True` con un folio `sim-<12hex>`. La tarea escribe entonces
  `status=SENT` y `sent_at=now()` ([agenda/tasks.py:203-216](MailySoft/backend/apps/agenda/tasks.py)).
  El módulo `recordatorios` **se factura en los cuatro planes**. La pantalla dice «Recordatorio ·
  WhatsApp · Enviado» con hora y folio; el paciente nunca recibió nada; la recepcionista, viendo
  «Enviado», registra no-show en vez de llamar.
- **Facturación.** Ya descrito en CR-02: el adaptador real es inalcanzable **por código**, no por
  configuración, y la clínica entrega al paciente un comprobante que no existe ante el SAT.

Encima, `.env.example` documenta 13 variables que **ningún archivo del proyecto lee** (6 de Stripe, 4
de WhatsApp, 3 de Twilio), y [adapters/whatsapp.py:113](MailySoft/backend/adapters/whatsapp.py)
afirma que `WHATSAPP_ACCESS_TOKEN` «ya está en base.py» — es falso. Alguien puede pegar en Railway un
token de Meta o una clave secreta de Stripe con valor económico real, que quedará guardado en un
entorno sin cumplir ninguna función y sin rotación.

**Dónde se arregla.** Que el estado `SENT` se derive de un acuse externo real y no del retorno del
adaptador; que el adaptador simulado sea imposible de seleccionar cuando `DEBUG` es falso (o que al
menos escriba `SIMULATED`, no `SENT`); y limpiar `.env.example` de las variables que nadie lee.

**Qué se rompe si no se arregla.** El producto genera constancia falsa: la base de datos afirma que
se envió un recordatorio y que se timbró una factura. Cuando el cliente reclame, la evidencia interna
le dará la razón al sistema.

---

## CR-24 · Los workers de Celery no fijan el GUC: acoplamiento oculto con CR-01

**Gravedad: P1** · **Cierra:** `D-TXN-10`

**Qué pasa.** Las tareas de PDF fijan el tenant en la capa de Python
([pdfs/tasks.py:56](MailySoft/backend/apps/pdfs/tasks.py),
[recetas/tasks.py:63](MailySoft/backend/apps/recetas/tasks.py)) pero **nunca llaman
`apply_tenant_guc()`** ([core/tenant_context.py:224-251](MailySoft/backend/apps/core/tenant_context.py)),
que es el único punto que ejecuta `set_config('app.current_tenant_id', …)`. Hoy los PDFs funcionan
solo porque las policies llevan `OR current_tenant_id() IS NULL`.

Esto merece su propia entrada aunque sea pequeño, porque es una **trampa de secuencia**: el día que
se cierre el fallback de CR-01 —que es P0 y hay que hacerlo— **todos los PDFs asíncronos empiezan a
fallar a la vez**: la receta impresa, el libro clínico, el esquema de tratamiento y el reporte de
finanzas. Y el error que verá el usuario será «job failed», sin ninguna relación aparente con un
cambio de seguridad hecho días antes.

**Dónde se arregla.** Añadir `apply_tenant_guc()` a las dos tareas, **antes** de tocar CR-01.

---

## CR-25 · Escrituras que se saltan la capa de modelo

**Gravedad: P2** · **Cierra:** `B-CLI-08`, `B-NOT-08`, `D-TXN-17`, `D-TXN-18`

**Qué pasa.** `queryset.update()` no dispara `auto_now` y `queryset.delete()` no pasa por `save()`:
las dos se saltan el `updated_at`, el borrado lógico y cualquier señal.

- **`updated_at` que miente:** cuatro sitios usan `.update()` sin tocarlo
  ([recetas/services.py:938](MailySoft/backend/apps/recetas/services.py), `:1042`;
  [notificaciones/services.py:184](MailySoft/backend/apps/notificaciones/services.py);
  [agenda/reminders.py:115](MailySoft/backend/apps/agenda/reminders.py)), mientras
  [clinica/services.py:1274](MailySoft/backend/apps/clinica/services.py) lo hace bien. Cuando un
  médico reclame «mis recetas salen con el membrete viejo desde ayer», el `updated_at` dirá que nadie
  tocó nada y la investigación empieza en el lugar equivocado.
- **Borrado físico donde el modelo base define borrado lógico:** cuatro sitios, y el que importa es
  [clinica/services.py:1443-1446](MailySoft/backend/apps/clinica/services.py) — quitar a alguien el
  acceso a una sede **borra físicamente** las filas de `MembershipSucursal`, y la bitácora solo
  guarda la lista final, no cuáles se retiraron. Si mañana hay que demostrar quién tuvo acceso a los
  expedientes de Norte y entre qué fechas, **la respuesta ya no está en la base**.

**Dónde se arregla.** Junto con CR-06 (el `SoftDeleteManager`), porque es el mismo problema visto
desde la otra punta: el borrado lógico depende hoy de que cada autor lo recuerde.

---

## CR-26 · Validación de entrada que sale como 500

**Gravedad: P1** · **Cierra:** `B-REC-05`, `B-FIN-10`, `B-AGE-21`, `B-FIN-11`, `B-PAC-12`

**Qué pasa.** Cinco entradas inválidas producen un error 500 en vez de un 400 con mensaje: un
`global_medication_id` inexistente, un valor no numérico en una línea o una asignación, un nombre de
tipo de cita repetido, y un nombre de paquete que choca con uno borrado lógicamente (que es CR-06
manifestándose como 500). `D-TXN-03` añade el peor: el `IntegrityError` del folio de receta.

Un 500 no es solo estética: se va a Sentry como error del servidor —donde compite con los fallos
reales—, el frontend no puede mostrar nada útil porque no hay cuerpo de error que mapear, y el
usuario pierde lo que estaba capturando.

**Dónde se arregla.** En los serializers (validación previa) y en las vistas, capturando
`IntegrityError` y `DoesNotExist` para convertirlos en 400/404. Es trabajo mecánico y de bajo riesgo:
buen candidato para cerrar en un solo PR.

---

## CR-27 · Los documentos de `docs/design/` ya no describen el sistema, y se contradicen entre sí

**Gravedad: P1** · **Cierra:** los 61 hallazgos de las dos auditorías de `docs/design/`
(`D-AGE-01…09`, `D-AUD-01…04`, `D-EXC-01…03`, `D-EXS-01`, `D-MUL-01…03`, `D-NOT-01…03`,
`D-NTF-01…03`, `D-PAC-01`, `D-REC-01…02`, `D-RFO-01…04`, `D-DOC-50…77`)

**Qué pasa.** Los 20 documentos vivos de `docs/design/` no los había leído ninguna auditoría. Se
verificaron **399 afirmaciones falsables** contra el código y salieron **61 hallazgos**: afirmaciones
caídas o planes que nunca se implementaron. Ninguna abre datos hoy —en todos los casos el código es correcto y el documento es
el que miente— pero el daño llega por quien construya código nuevo creyéndoles, y hay diez
afirmaciones caídas **sobre permisos y aislamiento por sede**, que son las que producen un bug de
seguridad al hacerlo.

| Veredicto | Documentos |
|---|---|
| **CADUCO** | `agenda-modelo-datos.md`, `cotizaciones-plan.md`, `finanzas-pacientes-unificacion-plan.md` |
| **PARCIAL** | `audit-modelo-datos.md`, `expediente-clinico-plan.md`, `multi-citas-disponibilidad.md`, `notas-y-tareas-plan.md`, `notificaciones-plan.md`, `recetas-plan.md`, `recetas-formatos-plan.md`, `sucursales-arquitectura-analisis.md`, `sucursales-mapa-apps.md`, `sucursales-guia-de-pruebas.md`, `frontend-security-testing.md` |
| **VIGENTE** | `pgbouncer-rls-escalabilidad.md`, `sentry-observabilidad.md`, `e2e-playwright.md`, `expediente-saas-rediseno.md`, `pacientes-filtros-clasificacion.md`, `ux-handoff/` |

Las tres afirmaciones caídas que más caro salen:

1. **`audit-modelo-datos.md:93` y `:124` dicen que owner **y admin** leen la bitácora.** El código la
   restringió a solo owner el 2026-07-16, y el motivo está escrito en
   [audit/permissions.py:10-14](MailySoft/backend/apps/audit/permissions.py): «antes era owner+admin,
   lo que dejaba a un admin de una sede ver las acciones de todas las demás». **Un agente que
   "corrija" el código para que coincida con el documento reabre exactamente ese hueco** — y el
   defecto resultante sería P0. Es el caso que el resumen de A2 anticipó.
2. **Tres documentos dan tres versiones distintas de quién difunde avisos.**
   `notas-y-tareas-plan.md:31,94` dice «solo el Dueño»; `notificaciones-plan.md:21` dice cinco roles
   para `role` y solo dueño para `all`; el código dice cinco roles para `role` y **owner o admin**
   para `all` ([notas/services.py:106-108](MailySoft/backend/apps/notas/services.py)). Los dos
   documentos están mal, cada uno de forma distinta, y el segundo se escribió precisamente para
   corregir al primero.
3. **`sucursales-arquitectura-analisis.md §13` —la matriz que alguien consulta para decidir si un
   modelo lleva sede— tiene tres filas caídas:** declara las notas «no por sede» (tienen campo
   `sucursal`), los catálogos de servicios y paquetes «compartidos» (son M2M por sede) y la bitácora
   «filtrable por sede» (no lo es). Un picker de servicios construido sobre esa matriz ofrecería
   servicios de Norte al cobrar en Centro.

Hay además **contradicciones internas** dentro de un mismo documento (`sucursales-mapa-apps.md`
declara «✅ CERRADOS» en su encabezado y describe los mismos huecos como abiertos tres párrafos
después; `recetas-formatos-plan.md` dice dos templates en `:43` y tres en `:233`), y **tres cifras
distintas del tamaño de la suite de tests** en tres documentos —2 379, 2 600 y 3 236— cuando el
conteo real es **3 140**.

**Dónde se arregla.** No archivando en bloque: la auditoría distingue.

- **Archivar a `_legacy/`:** `cotizaciones-plan.md` (plan ejecutado entero),
  `finanzas-pacientes-unificacion-plan.md` (~68 % caído; extraer antes la Fase 3 de RFM/retención a
  un backlog nuevo, porque ese plan sigue siendo válido), `sucursales-guia-de-pruebas.md` (guion de
  UAT de un solo uso), y `agenda-modelo-datos.md` **extrayendo antes a un ADR** sus §5.1, §5.2 y §6,
  que explican *por qué* se eligió `SELECT FOR UPDATE` sobre `MAX()+1`, por qué `Doctor` apunta a la
  membresía y por qué el exclusion constraint lleva `tenant_id` — razonamiento que no está en el
  contrato y que se perdería.
- **Corregir en sitio:** `audit-modelo-datos.md` (cuatro líneas, y una de ellas es la peligrosa),
  `sucursales-arquitectura-analisis.md` (§7 y la matriz §13/§14; el resto es la mejor explicación
  escrita de por qué RLS es solo por tenant), `sucursales-mapa-apps.md` (borrar la sección D),
  `recetas-formatos-plan.md` (tres puntos técnicos; el grueso sobre controlados y vigencia está
  intacto y es el documento más valioso del lote para cumplimiento).
- **Fusionar:** `notas-y-tareas-plan.md` y `notificaciones-plan.md` en uno solo. Individualmente
  están al ~15 % de caída, pero se contradicen en el permiso central del módulo y **ninguno de los
  dos tiene razón**.

**Detalle colateral que conviene arreglar de paso:** siete comentarios del código citan dos
documentos con su ruta vieja `docs/design/…` cuando ya viven en `docs/_legacy/design/`
([clinica/models.py:666](MailySoft/backend/apps/clinica/models.py),
[sucursal_scope.py:4,63](MailySoft/backend/apps/clinica/sucursal_scope.py),
[agenda/selectors.py:34](MailySoft/backend/apps/agenda/selectors.py),
[tenancy/views.py:9](MailySoft/backend/apps/tenancy/views.py), y dos más). Son justo los comentarios
que explican por qué existe cada validación de sede.

---

## Hallazgos que no agrupan

No todo tiene causa raíz compartida. Estos se atienden solos, ordenados por gravedad:

| ID | Qué es | Grav. |
|---|---|---|
| `B-T-01` | No existe `X-Tenant-ID`: un médico con dos clínicas siempre opera sobre la más antigua, y como lo clínico es inmutable, el error no se corrige — se anula y se rehace en el expediente equivocado | P1 |
| `B-PER-08` + `B-PER-03` | Cambiar la contraseña de un empleado no cierra su sesión (la cookie vive 7 días): la recepcionista despedida sigue entrando una semana. Y el alta no fuerza el cambio de contraseña inicial | P1 |
| `B-AUT-01` | Sin bloqueo por cuenta: el único freno al login es un throttle por IP — y CR-02 explica cómo se apaga solo | P1 |
| `B-AUT-05` | El logout mete en la lista negra el refresh de la cookie sin comprobar de quién es | P1 |
| `B-EXP-02` | Guardar la historia clínica borra en silencio las respuestas de preguntas desactivadas | P1 |
| `B-REC-04` | El throttle anti-enumeración del endpoint público es evadible con `X-Forwarded-For` | P1 |
| `B-REC-12` | Un PDF de receta generado antes de la anulación se sigue sirviendo sin la marca de anulada | P1 |
| `B-CLI-01` | Reasignar sedes de un miembro ignora la jerarquía de roles | P1 |
| `B-PER-02` | Un médico sin sedes asignadas desaparece de todos los listados acotados | P1 |
| `B-PLA-02` | La clínica no ve en su bitácora ninguna acción que la plataforma hace sobre ella | P1 |
| `B-PLA-04` | `engineering` recibe nombres y correos de todo el personal de cualquier clínica | P1 |
| `B-PLA-06` | Las contraseñas temporales no caducan | P1 |
| `B-FIN-19` | `_NO_TENANT` es una instancia de `Response` compartida entre peticiones | P1 |
| `B-AUD-01` | La IP de la bitácora sale de `X-Forwarded-For` sin lista de proxies confiables | P1 |
| `D-DEP-16` | `railway.json` sin `healthcheckPath`, y `/healthz/` responde «ok» sin tocar la base | P2 |
| `D-DEP-17` | Sin Content-Security-Policy en una SPA servida desde el mismo origen que la API (el bloque está escrito y comentado en `production.py:73-84`) | P2 |
| `D-FE-05` | Ningún `ErrorBoundary` en toda la app, con 20 rutas en `React.lazy`: tras cada despliegue, un usuario con la pestaña abierta que navegue obtiene **pantalla blanca** | P1 |
| `D-FE-10` | Los borradores clínicos en `localStorage` no se limpian cuando la sesión expira sola — solo en el logout explícito. En un equipo compartido queda PHI en claro hasta 48 h | P1 |
| `D-FE-15` | 22 `.mutate()` sin manejo de error: se pulsa «Aceptar cotización», el backend responde 403 y la interfaz no muestra nada | P2 |
| `D-DEP-18` | La regla de code-splitting apunta a `xlsx` y la dependencia es `exceljs`: la librería cae en el chunk inicial | P2 |
| `D-FE-13` | Dos listas de personal no llevan la sede en su clave de caché: al cambiar de sede muestran los médicos de la anterior mientras refresca | P2 |
| `D-FE-14`, `D-FE-16` | Solo una `VITE_*` está declarada en los tipos (una variable mal escrita compila y queda `undefined`); y el botón «Enviar por WhatsApp» avisa en pantalla que no envía nada | P2 |
| `B-T-20` | `Tenant.timezone` se guarda y casi no se usa (matiz: **sí** se usa en el recordatorio, `agenda/tasks.py:148`) | P2 |

Los ~26 hallazgos de `00-brechas.md` clasificados como ruido (código muerto, docstrings obsoletos) y
los 28 duplicados no se repiten aquí; siguen en su documento de origen.

---

## Lo que se verificó y salió limpio

Importa tanto como lo que falla, y evita volver a auditarlo:

- **Las 144 clases de vista declaran `permission_classes`** (verificado por AST). El único `AllowAny`
  es intencional y documentado: el endpoint público de verificación de recetas
  ([recetas/views_public.py:54](MailySoft/backend/apps/recetas/views_public.py)).
- **La inmutabilidad clínica se sostiene en el código.** Las vistas de evolución y de receta no
  declaran `put`, `patch` ni `delete`
  ([views_evoluciones.py:68](MailySoft/backend/apps/expediente/views_evoluciones.py),
  [recetas/views.py:300](MailySoft/backend/apps/recetas/views.py)); la anulación es un `post` con
  motivo. *(Lo que falta es el test que congele esa decisión — `D-TEST-09`, en CR-17.)*
- **La bitácora es inmutable en las dos capas de Python** y está bien probada:
  [audit/models.py:31-35](MailySoft/backend/apps/audit/models.py) y `:426-446` cubren `save`,
  `save(update_fields=…)`, `delete`, `QuerySet.update` y `QuerySet.delete`, con 6 tests.
- **El manejo de tokens del frontend es correcto:** access token solo en memoria (un F5 lo destruye),
  refresh en cookie `httpOnly` con `path` acotado, doble candado contra el bucle de refresh y promesa
  compartida para peticiones concurrentes. Cero `dangerouslySetInnerHTML`, cero `fetch` fuera del
  cliente central, **cero `any` y cero `@ts-ignore`** en `src/`, `strict: true` activo.
- **Ningún secreto llega al bundle:** las tres `VITE_*` que se leen son la URL de la API y el DSN y
  el ambiente de Sentry. Ningún `.env` real versionado.
- **La configuración de HTTPS y cookies de producción es correcta:** `SECURE_SSL_REDIRECT`, HSTS a un
  año con subdominios y preload, `SECURE_PROXY_SSL_HEADER` bien puesto para el proxy de Railway,
  CORS con lista explícita y sin regex laxo, contenedor como usuario no-root, subida acotada a 5 MB,
  y la documentación de la API cerrada fuera de `DEBUG`.
- **Sentry está configurado sin PII** para cuando se encienda: `send_default_pii=False`,
  `max_request_body_size="never"`, `include_local_variables=False`, en backend y frontend. Y no hay
  ninguna ruta que mande datos de paciente a Sentry.
- **Los locks están completos y versionados**, y la imagen se construye con `poetry install
  --only=main` y `npm ci`: un deploy instala exactamente lo probado.
- **`apps/authn` es el mejor módulo probado del proyecto:** 19 tests con login, refresh y logout HTTP
  reales, cookie `httpOnly`, CSRF exigido en refresh y logout, y registro en bitácora.
- **`apps/recetas` es el modelo a seguir en consultas:** precarga con `Prefetch(..., to_attr=)`,
  `len(obj.items.all())` en vez de `.count()` con el motivo escrito, y un test que lo fija.
- **`pgbouncer-rls-escalabilidad.md` y `sentry-observabilidad.md` describen el código con exactitud**
  — 16 de 17 y 12 de 12 afirmaciones ciertas.
- **El espejo del catálogo de módulos entre frontend y backend está sincronizado**: los 12 slugs,
  etiquetas, dependencias duras, roles y grupos coinciden.
- **Recetas sin campo `sucursal` no es una brecha:** los tres documentos de sucursales la clasifican
  como compartida a propósito, coherentes entre sí y con el código. Queda anotado para que no vuelva
  a levantarse. *(`B-REC-13` sigue vivo por otro motivo: el confinamiento por sede de la **lectura**
  y la **anulación** — CR-04.)*

---

## Lo que este documento NO pudo verificar

| Qué | Por qué | Cómo cerrarlo |
|---|---|---|
| Si `DJANGO_DEFAULT_FILE_STORAGE`, `PRESCRIPTION_VERIFY_SECRET` y `PRESCRIPTION_VERIFY_BASE_URL` están puestas en Railway | Sin acceso al proyecto | **Mirar el panel de Railway.** Decide si CR-02 tiene tres P0 activos o solo el riesgo de que falten |
| Si el rol de la conexión a Postgres en producción es superusuario | Ídem | `python manage.py check_db_role` contra producción. Decide CR-01 |
| Si la entrega de Cloudinary es autenticada o pública | Ídem | Panel de Cloudinary. Decide `B-PAC-02` |
| Si `SENTRY_DSN` está puesto | Ídem | Panel de Railway |
| Si la suite pasa hoy | No hay base de datos en esta sesión | `docker compose exec backend pytest -q` |
| Los conteos de consultas de CR-09, CR-10 y CR-11 | Ídem | Son derivaciones del código; se confirman con `django_assert_num_queries` |
| Si los e2e siguen en verde | No se ejecutaron, y no corren en CI | `npm run test:e2e` con el backend levantado |
| Si hay CVE en las versiones fijadas más allá de los reportados | `pip-audit` y `npm audit` **sí** corrieron con red; los CVE citados son reales | — |

---

## Orden sugerido para A4

No es una priorización cerrada —eso lo decide el triage— sino el orden que sale de cruzar gravedad
con costo:

**Primero, porque cuesta minutos y decide el resto:** abrir el panel de Railway y responder las
cuatro preguntas de la tabla anterior. Tres P0 de este documento dependen de eso.

**Después, por orden de consecuencia:**

1. **CR-19** — el savepoint de `audit_record` y el truncado del `request_id`. Es P0, es pérdida de
   datos clínicos, y el arreglo son pocas líneas.
2. **CR-01** — el rol NOSUPERUSER en Railway (con **CR-24 antes**, o los PDFs caen todos a la vez).
3. **CR-16** — la guardia de entorno de `seed_e2e_user` y rotar su contraseña. Una línea.
4. **CR-02** — las cuatro guardias de arranque en `production.py` y el bloque de variables de
   `DEPLOY-RAILWAY.md`.
5. **CR-20** — los locks del dinero: `payment_register`, `charge_cancel`, `quote_accept` y el folio
   de receta.
6. **CR-03** y **CR-04** — permisos por objeto y alcance por sede en la resolución por id. Son los
   dos arreglos que más hallazgos cierran (32 entre ambos) y los dos más caros; conviene planearlos
   como módulo, no como parche.
7. **CR-17** — el job de Node en CI. Barato, y a partir de ahí el frontend deja de romperse en
   producción.
8. El resto, por gravedad.

**Una decisión de producto que no es técnica y bloquea a CR-14:** cuáles de las diez capacidades
implementadas sin pantalla se construyen y cuáles se retiran del catálogo de planes.

---

## Qué cambia esto en el proceso

Tres de las causas raíz existen porque el `reviewer` no tenía cómo atraparlas. Conviene convertirlas
en puntos de checklist antes de que vuelvan:

- **`security-checklist`:** «toda variable de entorno que decida dónde viven los datos, con qué se
  firma algo o si un efecto externo es real, tiene guardia de arranque en `production.py`» (CR-02), y
  «ningún `except` alrededor de una escritura de base de datos sin `transaction.atomic()` propio»
  (CR-19).
- **`db-schema`:** «toda `UniqueConstraint` sobre un modelo con borrado lógico lleva
  `condition=Q(deleted_at__isnull=True)`» (CR-06).
- **`django-backend`:** «todas las validaciones antes de la primera escritura» (CR-22) y «una regla
  de pertenencia se declara en `has_object_permission`, no dentro del service» (CR-03).
- **`multitenancy`:** «resolver por id sin declarar el alcance de sede es un hallazgo» (CR-04).
