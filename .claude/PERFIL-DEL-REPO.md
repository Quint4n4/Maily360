# PERFIL DEL REPO

> El único lugar donde vive lo local: ninguna skill de la biblioteca menciona una ruta, un nombre de
> librería, un nombre de campo ni un nombre de app — todas las piden aquí.
>
> Repo: `Maily360` (proyecto en `MailySoft/`) · Última actualización: `2026-09-09`
>
> **Todas las rutas de este archivo son relativas a la raíz del repo (`Maily360/`), no a
> `MailySoft/`.** Confundir los dos niveles ya costó una sesión de trabajo; ver `CLAUDE.md`.

---

## Las tres reglas (repetidas aquí a propósito, porque este archivo se lee solo)

1. **La lista de claves es cerrada.** Ninguna skill consulta una clave que no esté en este archivo.
   Agregar una clave es un cambio del plugin, no una decisión local.
2. **Clave ausente = `NO VERIFICABLE` y alto.** Si una skill necesita una clave que no está
   rellenada, el punto se marca `NO VERIFICABLE`, se anota qué clave faltó y no se sigue.
   **Nunca se adivina, nunca se infiere del código.**
3. **`ninguno` es un valor; la ausencia no lo es.** `estado_servidor: ninguno — axios + useState`
   declara una decisión y habilita un `N/A` legítimo. La clave vacía es un hueco.

Y la que evita el problema que este archivo viene a resolver:

> **`CLAUDE.md` apunta aquí y no repite ni un valor. Si difieren, gana el perfil.**
> `CLAUDE.md` se queda con la prosa: el porqué, las trampas heredadas, lo que está en producción y
> no se toca. Este archivo se queda con los hechos.

---

## 1 · Proyecto

| Clave | Valor | La consume |
|---|---|---|
| `proyecto.nombre` | `Maily360 / MailySoft` | todas |
| `proyecto.etapa` | `desarrollo` | `db-schema`, `protocolo-de-revision` |
| `proyecto.fecha_adopcion` | `2026-08-11` | `protocolo-de-revision` (modo auditoría) |
| `proyecto.raiz_backend` | `MailySoft/backend` | `django-backend`, `security-checklist` |
| `proyecto.raiz_frontend` | `MailySoft/web-soft` | `react-frontend`, `auditoria-frontend`, `security-checklist` |
| `proyecto.contrato` | `MailySoft/docs/02-contrato.md` | todas |

`MailySoft/web-platform/` está vacío (solo `.gitkeep`) y no cuenta como raíz de frontend.

**`etapa: desarrollo` — confirmado por Emanuel el 2026-09-09.** El despliegue de Railway existe pero
**no tiene datos reales de ninguna clínica**: es semilla y demo. Consecuencias, y no son menores:

- `db-schema` **no** exige plan de migración de datos: la base se puede borrar y recrear.
- El `CLAUDE.md` decía `producción temprana` y el tablero de módulos habla de «no tumbar tu
  producción». **Los dos están desactualizados**, no este archivo.
- Lo único que se rompe al recrear la base son las **demos comerciales**. Si hay una agendada,
  se avisa antes; no es un dato de paciente, es una venta.

**Esta clave cambia a `produccion-temprana` el día que entre la primera clínica de pago**, y ese
día M1, M2, M4 y M5 dejan de ser deuda y pasan a ser bloqueantes de lanzamiento.

---

## 2 · Aislamiento

| Clave | Valor | La consume |
|---|---|---|
| `aislamiento.ambito` | `tenant` | `aislamiento-de-datos`, `auditoria-frontend`, `django-backend` |
| `aislamiento.nombre_de_negocio` | `clínica` | `aislamiento-de-datos` (escenarios) |
| `aislamiento.campo` | `tenant` | `aislamiento-de-datos`, `db-schema`, `django-backend` |
| `aislamiento.mecanismo` | `manager+rls` | `aislamiento-de-datos` |
| `aislamiento.modelo_base` | `TenantAwareModel` (`MailySoft/backend/apps/core/models.py:42`) | `aislamiento-de-datos` |
| `aislamiento.escape` | `all_objects` (`apps/core/models.py:73`) | `aislamiento-de-datos` |
| `aislamiento.origen` | `tabla-de-membresias` | `aislamiento-de-datos` |
| `aislamiento.test_de_fuga` | `MailySoft/backend/apps/core/tests/test_zzz_tenant_isolation.py` | `aislamiento-de-datos` |
| `aislamiento.ancla` | `ninguno` — el mecanismo no es `manual-por-vista` | `aislamiento-de-datos` |

**Autoridad:** `TenantMembership` (`apps/tenancy/models.py:78`), resuelta por
`resolve_membership_for_user()` en `apps/core/tenant_context.py:113`. Solo membresías
`is_active=True` y tenants en estado `active` o `trial`. **El cliente nunca manda el tenant.**

**Cobertura de RLS:** `apps/core/tests/test_rls_coverage.py` falla en CI si un `TenantAwareModel`
no tiene su migración de política.

⚠ **Deuda conocida, anotada porque es cara** (de `00-AVISO-AUDITORIA-PREVIA.md`): los workers de
Celery nunca fijan el tenant y funcionan gracias al fallback `OR current_tenant_id() IS NULL` de las
políticas. **Cerrar ese fallback antes de arreglar los workers (módulo M4) tumba todos los PDFs
asíncronos el mismo día.** El orden M4 → M5 no es negociable.

---

## 3 · Backend

| Clave | Valor | La consume |
|---|---|---|
| `backend.framework` | `Django 5.2.15 + DRF 3.17.1` | `django-backend` |
| `backend.forma_de_vistas` | `apiview-y-path` | `django-backend` |
| `backend.capa_de_servicios` | `services-y-selectors` | `django-backend`, `aislamiento-de-datos` |
| `backend.envoltura_respuesta` | `drf-plano` — errores como `{"detail": ...}` | `django-backend`, `react-frontend` |
| `backend.paginacion` | `drf: count/next/previous` — `PageNumberPagination`, `PAGE_SIZE=25` | `django-backend`, `react-frontend` |
| `backend.autenticacion` | `mixto` — JWT en la API, sesión Django en `/admin` | `security-checklist`, `react-frontend` |
| `backend.revocacion_de_sesion` | `si: blacklist de SimpleJWT en logout y en cambio de contraseña` | `security-checklist` |
| `backend.borrado` | `logico` — `deleted_at` en `BaseModel` (`apps/core/models.py:31`) | `db-schema`, `security-checklist` |
| `backend.bitacora_auditoria` | `audit_record` (`apps/audit/services.py:29`) → modelo `AuditLog` | `security-checklist` |
| `backend.tareas_asincronas` | `celery` | `django-backend` |

**`forma_de_vistas`:** verificado por conteo — 0 archivos con `ViewSet`, 15 con `APIView`. La clase
base propia es `TenantAPIView`, que resuelve el tenant y puebla el contexto HTTP de la bitácora.

**`revocacion_de_sesion` — verificado provocando el efecto el 2026-09-09**, no leyendo `settings.py`.
Secuencia: login → `/auth/refresh/` con la cookie **200** → `/auth/logout/` **205** → se reenvía el
**mismo** refresh viejo → **401**. Revoca de verdad.

`ROTATE_REFRESH_TOKENS=False` y `BLACKLIST_AFTER_ROTATION=False` (`config/settings/base.py:266`) son
deliberados y están documentados en el código: la rotación causaba cierres de sesión intermitentes.
Quien revise no debe reportarlos como hallazgo sin antes rehacer la prueba de arriba.

---

## 4 · Frontend

| Clave | Valor | La consume |
|---|---|---|
| `frontend.apps` | `web-soft — clínica y portal interno de plataforma — MailySoft/web-soft` | `react-frontend`, `auditoria-frontend` |
| `frontend.estado_servidor` | `tanstack-query` | `react-frontend`, `auditoria-frontend` |
| `frontend.estilos` | `tailwind` | `react-frontend` |
| `frontend.cliente_http` | `MailySoft/web-soft/src/lib/http.ts` | `react-frontend`, `auditoria-frontend`, `security-checklist` |
| `frontend.libreria_http` | `fetch` | `react-frontend`, `auditoria-frontend` |
| `frontend.almacen_token` | `memoria` | `security-checklist`, `react-frontend` |
| `frontend.cache_offline` | `ninguna` | `auditoria-frontend` |
| `frontend.transporte_del_ambito` | `implicito-en-el-token` | `auditoria-frontend` |
| `frontend.matriz_de_permisos` | `MailySoft/web-soft/src/auth/permisos.ts` | `auditoria-frontend` |
| `frontend.espejo_de_modulos` | `MailySoft/web-soft/src/lib/modulos.ts` | `auditoria-frontend` |

**Una sola app de Vite con dos áreas**, no dos apps: `src/pages/` es la clínica y
`src/pages/plataforma/` + `src/platform/` es el portal interno. Comparten `main.tsx` y bundle.
`src/platform/permisos.ts` es la matriz del portal interno, hermana de la declarada arriba.

**`almacen_token: memoria` es la mitad del patrón, y la otra mitad importa:** el *access* token vive
solo en una variable de módulo (`src/lib/tokenStore.ts`), y el *refresh* en la cookie httpOnly
`maily_refresh`, que JS no puede leer. Nada de sesión se guarda en `localStorage`. La clave admite un
solo valor y `memoria` es el que describe lo que un XSS podría alcanzar.

`localStorage` sí se usa, pero **nunca para credenciales**: sucursal activa (`maily.sucursal`), rol
para gating de UX, pausas de recordatorios y borradores de formulario.

---

## 5 · Verificadores

Comandos copiables, **desde la raíz del repo (`Maily360/`)**. Todos probados el 2026-09-09.

| Clave | Valor | La consume |
|---|---|---|
| `verificadores.entorno` | `docker compose -f MailySoft/docker-compose.yml exec -T backend` | todas |
| `verificadores.tests_backend` | `docker compose -f MailySoft/docker-compose.yml exec -T backend pytest -q` | todas |
| `verificadores.tests_frontend` | `ninguno` — ver nota | `react-frontend`, `auditoria-frontend` |
| `verificadores.tipos` | `docker compose -f MailySoft/docker-compose.yml exec -T backend mypy apps/ --ignore-missing-imports` | `django-backend`, `react-frontend` |
| `verificadores.lint` | `docker compose -f MailySoft/docker-compose.yml exec -T backend ruff check .` | `django-backend` |
| `verificadores.ci` | `.github/workflows/ci.yml` | `protocolo-de-revision` |
| `verificadores.migraciones` | `agente` | `db-schema` |

**`tests_frontend: ninguno` es una lectura correcta del repo, no un descuido de este archivo.**
`npm run test:e2e` existe (Playwright, desde `MailySoft/web-soft/`) pero **no corre en CI y no hay
una sola prueba unitaria de frontend**. Consecuencia obligada del protocolo: todo punto de
`react-frontend` o `auditoria-frontend` cuyo verificador sea un test sale `NO VERIFICABLE` y se
acumula en la lista de despliegue. El tipado del frontend sí se comprueba con
`npm run build` (`tsc -b`), también fuera de CI.

**Candados de CI:** `pytest` es **bloqueante** — **3.418 tests** colectados el 2026-09-09, cobertura
≥80%. `ruff`, `black`, `mypy` y `pip-audit` son **informativos** (`continue-on-error`) por deuda
acumulada de años sin CI; `ruff check .` reporta **587 hallazgos** hoy. Un `PASA` que se apoye en
mypy o ruff se apoya en un candado que no bloquea nada: dilo en la revisión.

> El encabezado de `.github/workflows/ci.yml:9` dice «~2.379 tests». Está desactualizado: son 3.418.
> Se corrige cuando se toque el workflow.

---

## 6 · Cumplimiento

| Clave | Valor | La consume |
|---|---|---|
| `cumplimiento.datos_sensibles` | `si: expediente clínico de pacientes — antecedentes, alergias, diagnósticos, signos vitales, notas de evolución y recetas` | `security-checklist`, `db-schema` |
| `cumplimiento.monitoreo_errores` | `sentry` | `security-checklist` |
| `cumplimiento.registros_inmutables` | `EvolutionNote`, `Addendum`, `VitalSignsRecord`, `Prescription`, `PrescriptionItem`, `AuditLog` | `security-checklist` |
| `cumplimiento.estados_con_razon` | `Prescription → cancelled (cancellation_reason)`, `Appointment → cancelled (cancellation_reason)` | `security-checklist` |
| `cumplimiento.consulta_legal` | `pendiente` | `security-checklist` |

**`monitoreo_errores: sentry` cubre el backend únicamente.** El frontend no reporta a Sentry: el
`Dockerfile` compila el bundle dentro de la imagen y no tiene ningún `ARG` para recibir
`VITE_SENTRY_DSN`, así que ponerla en Railway no haría nada — sin fallar. Es el módulo M0.4.

**`AuditLog` es append-only en dos capas:** `save()`/`delete()` de instancia y el `QuerySet`
(`apps/audit/models.py:21`), para que `.filter(...).update()` tampoco pueda tocarlo.

⚠ **`consulta_legal: pendiente` — confirmado por Emanuel el 2026-09-09.** No ha habido consulta
con un abogado sobre datos de pacientes ni expediente clínico electrónico.

Consecuencia inmediata: `security-checklist` **no emite ningún punto legal**. Eso es deliberado, no
un hueco del checklist — un modelo cita artículos inexistentes con total aplomo y aquí nadie tiene
cómo detectarlo. Lo que sí exige la skill son los mínimos técnicos: cifrado en tránsito, control de
acceso por rol y bitácora de accesos.

**Queda como riesgo abierto y con dueño: se resuelve antes de vender a la primera clínica**, no
antes de escribir la siguiente línea de código. El día que exista la consulta, esta clave pasa a
`hecha AAAA-MM-DD` y lo que dijo el abogado se convierte en **puntos fijos de la skill**.

---

## 7 · Excepciones locales

Una desviación documentada aquí **pasa**. Una desviación no documentada **bloquea**.

| # | Qué regla se desvía | Por qué | Qué la volvería a hacer aplicable |
|---|---|---|---|
| E1 | `verificadores.migraciones: agente` en un repo `produccion-temprana` con datos reales de pacientes | Decisión de Emanuel el 2026-09-09, sobre la recomendación contraria: el agente genera y aplica migraciones en el Docker **local**, donde el daño es reversible, a cambio de velocidad | Si una migración generada por un agente llega a producción sin que Emanuel la haya leído completa, o si entra la segunda clínica de pago |
| E2 | `aislamiento.ambito` declara `tenant` y deja la **sede** (sucursal) fuera del alcance de `aislamiento-de-datos` | El repo tiene dos ámbitos anidados y la clave admite uno. El grave es el de arriba: que el expediente de una clínica llegue a otra. El filtrado por sucursal viaja en la cabecera `X-Sucursal-Id` y hoy tiene un bug abierto (CR-04), programado para el módulo M6 | Cuando M6 cierre CR-04, revisar si conviene una segunda pasada declarando `sede` |

**Lo que NO está aquí es deliberado.** Cuatro cosas se detectaron al rellenar este archivo y **no**
se documentan como excepción, para que el `reviewer` las encuentre y las bloquee:
`src/pages/plataforma/SistemaPage.tsx` hace `fetch` fuera del cliente central; la matriz de permisos
solo cubre Finanzas; el frontend no tiene tests en CI; y ningún test permanente prueba la revocación
del refresh (la de §3 se hizo a mano y se borró).

---

## Cómo se mantiene este archivo

Se actualiza **en el mismo PR** que cambia el hecho que describe. Un perfil desactualizado es peor
que uno vacío: el vacío marca `NO VERIFICABLE` y detiene; el desactualizado deja pasar un `PASA`
falso. Cada valor de aquí se rellenó verificándolo contra el código o provocando el efecto — si
cambias uno, cámbialo igual.
