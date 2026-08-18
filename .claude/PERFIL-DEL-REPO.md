# PERFIL DEL REPO

> Copia este archivo a `.claude/PERFIL-DEL-REPO.md` en la raíz del repo y rellena **todas** las
> claves. Es el único lugar donde vive lo local: ninguna skill de la biblioteca menciona una ruta,
> un nombre de librería, un nombre de campo ni un nombre de app — todas las piden aquí.
>
> Repo: `<nombre>` · Última actualización: `<AAAA-MM-DD>`

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

| Clave | Valor | Valores permitidos | La consume |
|---|---|---|---|
| `proyecto.nombre` | | texto | todas |
| `proyecto.etapa` | | `desarrollo` · `produccion-temprana` · `produccion` | `db-schema`, `protocolo-de-revision` |
| `proyecto.fecha_adopcion` | | `AAAA-MM-DD` · `ninguna` | `protocolo-de-revision` (modo auditoría) |
| `proyecto.raiz_backend` | | ruta relativa · `ninguno` | `django-backend`, `security-checklist` |
| `proyecto.raiz_frontend` | | lista de rutas · `ninguno` | `react-frontend`, `auditoria-frontend`, `security-checklist` |
| `proyecto.contrato` | | ruta de `02-contrato.md` · `ninguno` | todas |

`proyecto.etapa` no es decorativa: en `produccion` un cambio de esquema arrastra datos reales y
`db-schema` exige decir qué pasa con lo que ya existe antes de proponerlo. En `desarrollo` no.

---

## 2 · Aislamiento

| Clave | Valor | Valores permitidos | La consume |
|---|---|---|---|
| `aislamiento.ambito` | | `tenant` · `sede` · `ninguno` | `aislamiento-de-datos`, `auditoria-frontend`, `django-backend` |
| `aislamiento.nombre_de_negocio` | | texto: cómo lo llama el cliente | `aislamiento-de-datos` (escenarios) |
| `aislamiento.campo` | | nombre del campo en los modelos · `ninguno` | `aislamiento-de-datos`, `db-schema`, `django-backend` |
| `aislamiento.mecanismo` | | `manager-por-defecto` · `rls` · `manager+rls` · `manual-por-vista` · `ninguno` | `aislamiento-de-datos` |
| `aislamiento.modelo_base` | | nombre de la clase base · `ninguno` | `aislamiento-de-datos` |
| `aislamiento.escape` | | nombre del manager sin filtro · `ninguno` | `aislamiento-de-datos` |
| `aislamiento.origen` | | `subdominio` · `claim-del-token` · `campo-del-usuario` · `tabla-de-membresias` · `ninguno` | `aislamiento-de-datos` |
| `aislamiento.test_de_fuga` | | ruta del archivo de test · `ninguno` | `aislamiento-de-datos` |
| `aislamiento.ancla` | | token de búsqueda cuando el mecanismo es manual · `ninguno` | `aislamiento-de-datos` |

`aislamiento.ambito: ninguno` es la única forma legítima de que `aislamiento-de-datos` se declare
`N/A`. Un repo multi-sucursal **no** es `ninguno`: es `sede`.

`aislamiento.ancla` existe porque con `mecanismo: manual-por-vista` no hay un mecanismo central que
auditar — hay que ir vista por vista, y el ancla (`grep -rn "BUSCAR>> …"`) es lo único que hace esa
revisión repetible.

**`aislamiento.origen` es la AUTORIDAD, no el transporte.** Dice de dónde saca el servidor *qué
ámbitos puede ver este usuario*, y por eso no admite ninguna cabecera ni parámetro: eso lo escribe
el cliente. Cuál de sus ámbitos está usando ahora es otra cosa, viaja por
`frontend.transporte_del_ambito`, y el servidor la cruza contra los autorizados antes de usarla.

---

## 3 · Backend

| Clave | Valor | Valores permitidos | La consume |
|---|---|---|---|
| `backend.framework` | | texto con versión | `django-backend` |
| `backend.forma_de_vistas` | | `viewsets-y-routers` · `apiview-y-path` · `mixto` | `django-backend` |
| `backend.capa_de_servicios` | | `services-y-selectors` · `parcial: <dónde vive hoy>` · `ninguna` | `django-backend`, `aislamiento-de-datos` |
| `backend.envoltura_respuesta` | | `drf-plano` · `{success,message,data,errors}` · otra (describir) | `django-backend`, `react-frontend` |
| `backend.paginacion` | | `drf: count/next/previous` · `{items,pagination}` · `ninguna` | `django-backend`, `react-frontend` |
| `backend.autenticacion` | | `jwt` · `sesion-cookie` · `mixto` | `security-checklist`, `react-frontend` |
| `backend.revocacion_de_sesion` | | `si: <mecanismo>` · `ninguna` · `no-aplica` | `security-checklist` |
| `backend.borrado` | | `logico` · `fisico` · `mixto: <dónde cada uno>` | `db-schema`, `security-checklist` |
| `backend.bitacora_auditoria` | | nombre de la función o modelo · `ninguna` | `security-checklist` |
| `backend.tareas_asincronas` | | `celery` · `ninguna — en el hilo de la petición` | `django-backend` |

`backend.revocacion_de_sesion` está aquí y no en el código por una razón concreta: es la clave del
P0 que dio origen a la Regla 1 del protocolo. Un repo puede tener `BLACKLIST_AFTER_ROTATION = True`
y no tener revocación, porque la aplicación que la implementa no está instalada. **Este campo se
rellena habiendo provocado el efecto**, no habiendo leído el `settings.py`.

---

## 4 · Frontend

| Clave | Valor | Valores permitidos | La consume |
|---|---|---|---|
| `frontend.apps` | | lista `nombre — para quién — ruta` · `ninguna` | `react-frontend`, `auditoria-frontend` |
| `frontend.estado_servidor` | | `tanstack-query` · `ninguno — <qué usa en su lugar>` | `react-frontend`, `auditoria-frontend` |
| `frontend.estilos` | | `tailwind` · `css-plano` · otro | `react-frontend` |
| `frontend.cliente_http` | | ruta del único módulo que hace peticiones · `ninguno — disperso` | `react-frontend`, `auditoria-frontend`, `security-checklist` |
| `frontend.libreria_http` | | nombre del identificador con el que se hacen peticiones (`axios`, `ky`, `fetch`…) | `react-frontend`, `auditoria-frontend` |
| `frontend.almacen_token` | | `memoria` · `memoria+sessionStorage` · `sessionStorage` · `localStorage` · `cookie-httponly` | `security-checklist`, `react-frontend` |
| `frontend.cache_offline` | | `<librería> en <ruta>` · `ninguna` | `auditoria-frontend` |
| `frontend.transporte_del_ambito` | | `cabecera:<nombre>` · `implicito-en-el-token` · `parametro` · `ninguno` | `auditoria-frontend` |
| `frontend.matriz_de_permisos` | | ruta del archivo · `ninguna` | `auditoria-frontend` |
| `frontend.espejo_de_modulos` | | ruta del archivo · `ninguno` | `auditoria-frontend` |

`frontend.estado_servidor: ninguno` **no** vuelve `N/A` el cruce de caché de `auditoria-frontend`.
Cambia dónde buscar: sin caché de servidor, el dato del ámbito anterior sobrevive en el estado de
los componentes y en `frontend.cache_offline`. Es el mismo riesgo en otro sitio.

---

## 5 · Verificadores

Los comandos de esta sección son los que las skills escriben en la columna **Cómo se comprueba**.
Tienen que ser copiables y correr tal cual desde la raíz del repo.

| Clave | Valor | Valores permitidos | La consume |
|---|---|---|---|
| `verificadores.entorno` | | prefijo de ejecución (ej. `docker compose run --rm backend`) · `ninguno` | todas |
| `verificadores.tests_backend` | | comando completo · `ninguno` | todas |
| `verificadores.tests_frontend` | | comando completo · `ninguno` | `react-frontend`, `auditoria-frontend` |
| `verificadores.tipos` | | comando completo · `ninguno` | `django-backend`, `react-frontend` |
| `verificadores.lint` | | comando completo · `ninguno` | `django-backend` |
| `verificadores.ci` | | ruta del workflow · `ninguno` | `protocolo-de-revision` |
| `verificadores.migraciones` | | quién las corre: `agente` · `solo-emanuel` | `db-schema` |

`verificadores.migraciones: solo-emanuel` significa que ninguna skill ni ningún agente ejecuta
`makemigrations` ni `migrate`. Un punto que exige provocar un efecto de migración se marca
`NO VERIFICABLE` y se muda a `docs/05-despliegue.md`, en vez de correrlo.

Si `verificadores.tests_backend: ninguno`, **todo punto cuyo verificador sea un test** sale de la
revisión como `NO VERIFICABLE` y se acumula en la lista de despliegue. Eso es una lectura correcta
del estado del repo, no un fallo del checklist.

---

## 6 · Cumplimiento

| Clave | Valor | Valores permitidos | La consume |
|---|---|---|---|
| `cumplimiento.datos_sensibles` | | `ninguno` · `si: <qué dato y de quién>` | `security-checklist`, `db-schema` |
| `cumplimiento.monitoreo_errores` | | `sentry` · otro · `ninguno` | `security-checklist` |
| `cumplimiento.registros_inmutables` | | lista de modelos que no se editan ni se borran · `ninguno` | `security-checklist` |
| `cumplimiento.estados_con_razon` | | lista de transiciones que exigen razón cerrada · `ninguna` | `security-checklist` |
| `cumplimiento.consulta_legal` | | `pendiente` · `hecha AAAA-MM-DD` | `security-checklist` |

`cumplimiento.consulta_legal: pendiente` significa que `security-checklist` **no tiene puntos
legales**. No significa que no apliquen. Los requisitos legales no se le preguntan a un modelo: se
consultan una vez con un abogado y el resultado se convierte en puntos fijos de la skill.

---

## 7 · Excepciones locales

Una desviación documentada aquí **pasa**. Una desviación no documentada **bloquea**.

| # | Qué regla se desvía | Por qué | Qué la volvería a hacer aplicable |
|---|---|---|---|
| E1 | | | |

Ejemplo del formato:

| # | Qué regla se desvía | Por qué | Qué la volvería a hacer aplicable |
|---|---|---|---|
| E1 | `react-frontend`: el 401 refresca y reintenta una vez | En la PWA del cliente no hay refresh: limpia sesión y manda a login | Si la PWA adopta refresh, se borra esta excepción |

Sin este bloque, un auditor reporta la misma desviación correcta como bug en cada revisión, y la
tercera vez que pasa dejan de leerse las revisiones.
