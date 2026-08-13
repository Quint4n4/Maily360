# Desplegar Maily Soft en Railway (piloto de clínica)

Guía paso a paso para subir el sistema a Railway para un **piloto supervisado**
(el personal de la clínica lo prueba con datos de prueba). El backend Django
sirve también el frontend React en **un solo dominio** (lo exige el login con
cookies seguras), y los archivos subidos van a **Cloudinary**.

> El desarrollo **local no cambia**: sigue con `docker compose up`. Esta guía es
> solo para el despliegue en Railway.

---

## Arquitectura

```
Railway (proyecto "maily-demo")
├─ 🟢 Postgres (plugin)      → base de datos      (variable DATABASE_URL)
├─ 🔴 Redis (plugin)         → cola + caché       (variable REDIS_URL)
├─ 🐍 web (Docker)           → Django API + admin + FRONTEND React   ← público
└─ ⚙️  worker (Docker)        → Celery (genera los PDFs)
Cloudinary (externo)         → logos, firmas, fotos
```

---

## 0) Lo que necesitas

- Cuenta en **Railway** (railway.app) — con el plan Hobby basta para un piloto.
- Cuenta en **Cloudinary** (cloudinary.com) — capa gratuita.
- El repo `Quint4n4/Maily360` en GitHub (ya lo tienes).

---

## 1) Cloudinary → obtén tu `CLOUDINARY_URL`

1. Entra a cloudinary.com → crea cuenta / inicia sesión.
2. En el **Dashboard**, sección **Account Details**, copia el **API Environment
   variable**. Se ve así:
   ```
   CLOUDINARY_URL=cloudinary://123456789:abcdEFGhiJKlmno@tu-cloud-name
   ```
3. Guárdalo, lo pegas en Railway más adelante.

> ⚠️ Para el piloto (datos de prueba) está bien así. Cuando metan **fotos de
> pacientes reales**, activa la **entrega autenticada** de Cloudinary (URLs
> firmadas), por privacidad clínica (LFPDPPP / NOM-024).

---

## 2) Proyecto en Railway + Postgres + Redis

1. En Railway: **New Project** → **Deploy from GitHub repo** → elige
   `Quint4n4/Maily360`. (Autoriza Railway en GitHub si te lo pide.)
2. En el proyecto, **+ New** → **Database** → **Add PostgreSQL**.
3. **+ New** → **Database** → **Add Redis**.

Con esto ya tienes `Postgres` y `Redis`; sus variables (`DATABASE_URL`,
`REDIS_URL`) se referencian solas más abajo.

---

## 3) Servicio **web** (backend + frontend)

Railway habrá creado un servicio del repo. Ese será el **web**:

1. Abre el servicio → **Settings**:
   - **Root Directory**: `MailySoft`  ← IMPORTANTE (el proyecto vive en esa subcarpeta).
   - **Builder**: Railway detecta el `Dockerfile` automáticamente (por el `railway.json`).
   - **Networking** → **Generate Domain** (te da algo como `maily-demo-production.up.railway.app`).
2. Renómbralo a `web` (Settings → Service Name) para no confundirte.

---

## 4) Variables del servicio web

En el servicio **web** → pestaña **Variables** → pega (usa **Raw Editor** y pega
todo de una vez). Toma como base `MailySoft/.env.production.example`:

```
DJANGO_SETTINGS_MODULE=config.settings.production

DJANGO_SECRET_KEY=<pega-una-cadena-larga-aleatoria>
JWT_SIGNING_KEY=<pega-OTRA-distinta>
PRESCRIPTION_VERIFY_SECRET=<pega-OTRA-para-el-QR>

DJANGO_ALLOWED_HOSTS=.railway.app
CSRF_TRUSTED_ORIGINS=https://*.railway.app
CORS_ALLOWED_ORIGINS=

DATABASE_URL=<URL del rol de app maily_app — ver nota abajo>
MIGRATION_DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}
CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}

CLOUDINARY_URL=<pega-tu-CLOUDINARY_URL-de-Cloudinary>
DJANGO_DEFAULT_FILE_STORAGE=cloudinary_storage.storage.MediaCloudinaryStorage

PRESCRIPTION_VERIFY_BASE_URL=https://TU-APP.up.railway.app

SENTRY_DSN=<el DSN de tu proyecto en Sentry>
SENTRY_ENVIRONMENT=production

DEMO_OWNER_PASSWORD=<una-clave-fuerte-para-el-login-del-personal>
```

**Genera cada secreto** (3 distintos) con este comando en tu terminal:
```
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

> `${{Postgres.DATABASE_URL}}` y `${{Redis.REDIS_URL}}` son *reference variables*
> de Railway: se autollenan. Si Railway nombró tus plugins distinto (p. ej.
> `Postgres-XXXX`), usa ese nombre.

### Las cuatro que ya no son opcionales

`DJANGO_DEFAULT_FILE_STORAGE`, `PRESCRIPTION_VERIFY_SECRET`,
`PRESCRIPTION_VERIFY_BASE_URL` y `REDIS_URL` son **obligatorias**: si falta
cualquiera, `production.py` aborta el arranque con un `ImproperlyConfigured` que
lista todas las que falten y para qué sirve cada una. El deploy se marca en rojo;
no queda a medias.

Antes tenían un default de desarrollo y la app arrancaba sin ellas — con los
archivos subidos borrándose en cada redespliegue, el QR de las recetas apuntando
a `localhost` y el límite de intentos de login desactivado en silencio.

> Si el arranque se queja de una variable que juras haber puesto, revisa que el
> **nombre** no lleve un espacio al final. Un `SENTRY_DSN ` así tuvo Sentry
> apagado sin una sola señal.

### Los dos roles de base de datos

`DATABASE_URL` y `MIGRATION_DATABASE_URL` **no son la misma cadena**:

| Variable | Rol | Para qué |
|---|---|---|
| `DATABASE_URL` | `maily_app` (NOSUPERUSER NOBYPASSRLS) | El tráfico normal. Al no ser superuser, las políticas RLS le aplican de verdad: es la segunda barrera de aislamiento entre clínicas. |
| `MIGRATION_DATABASE_URL` | `postgres` (`${{Postgres.DATABASE_URL}}`) | Solo `migrate`, que necesita crear tablas y políticas. |

Es la misma cadena de conexión cambiando usuario y contraseña. Cómo se crea el
rol `maily_app`, cómo se verifica y cómo se deshace: `deploy-rol-app-nosuperuser.md`.

Desde este módulo el arranque **verifica ese rol solo** con `check_db_role`: si
la app se conectara con un rol superuser, el contenedor no levanta. Para el
rollback a `postgres` descrito en esa guía, agrega `REQUIRE_DB_ROLE_RLS=false` —
si no, la app se niega a arrancar justo cuando estás intentando volver atrás.

### Sentry

Sin `SENTRY_DSN` la integración queda **dormida**: no se inicializa y no envía
nada. El código está bien; la variable es lo que lo enciende. Ponla en los **dos**
servicios (web y worker), o pierdes los errores de las tareas en segundo plano —
que son justo las que nadie está mirando cuando fallan.

> El DSN se pega tal cual, sin comillas y sin espacios alrededor. Un DSN mal
> formado **impide que la aplicación arranque**: Sentry se inicializa durante el
> arranque de Django, así que un valor inválido tumba el servicio entero.

Guarda → Railway hace el primer **deploy** (compila React + backend, corre
migraciones). Tarda unos minutos.

---

## 5) Servicio **worker** (Celery)

1. En el proyecto: **+ New** → **GitHub Repo** → el mismo `Quint4n4/Maily360`.
2. En ese servicio → **Settings**:
   - **Root Directory**: `MailySoft`
   - **Custom Start Command**:
     ```
     /entrypoint.sh celery -A config.celery worker --loglevel=INFO --concurrency=2
     ```
   - Nómbralo `worker`.
3. **Variables**: las MISMAS que el web **más**:
   ```
   RUN_MIGRATIONS=false
   ```
   (Truco rápido: en el web, Variables → menú "⋮" → puedes copiarlas; o pégalas
   de nuevo. El worker NO necesita dominio ni `DEMO_OWNER_PASSWORD`.)

   Dos precisiones sobre esa copia:
   - **Quita `MIGRATION_DATABASE_URL`**: el worker no migra (`RUN_MIGRATIONS=false`),
     y dejarle a mano el rol privilegiado no compra nada.
   - **Deja `PRESCRIPTION_VERIFY_BASE_URL` y `SENTRY_DSN`**: el worker es quien
     genera el PDF con el QR, y sin DSN sus fallas no se ven en ninguna parte.

> El worker no necesita dominio público (nadie lo visita directo). `RUN_MIGRATIONS=false`
> evita que web y worker migren a la vez.

*(Opcional)* Si más adelante quieren **recordatorios programados**, agrega un
tercer servicio `beat` igual que el worker pero con start command
`/entrypoint.sh celery -A config.celery beat --loglevel=INFO` y `RUN_MIGRATIONS=false`.

---

## 6) Sembrar la clínica demo + login del personal

Cuando el servicio **web** esté verde (deploy exitoso):

1. Abre el servicio **web** → pestaña de **shell/terminal** de Railway (o usa la
   Railway CLI: `railway run --service web bash`).
2. Corre:
   ```
   python manage.py seed_demo
   ```
   Esto crea: la clínica demo, usuarios, pacientes de ejemplo, catálogo de
   medicamentos, pone la contraseña del dueño (la de `DEMO_OWNER_PASSWORD`) y le
   da perfil de médico con cédula (para emitir recetas).

> Si prefieres no usar la terminal de Railway, avísame y lo convertimos en un
> "release command" que corra solo en cada deploy.

---

## 7) Entrégale el acceso al personal

- **URL**: el dominio que generó Railway (paso 3), p. ej.
  `https://maily-demo-production.up.railway.app`
- **Usuario**: `owner@demo.maily.mx`
- **Contraseña**: la que pusiste en `DEMO_OWNER_PASSWORD`

Ese usuario es **dueño + médico con cédula**, así que puede crear pacientes,
citas, recetas (con la hora, genérico/comercial y todo el cumplimiento legal), etc.

*(Opcional, más seguro)* Aprieta los dominios: cambia en el web
`DJANGO_ALLOWED_HOSTS` a tu dominio exacto (sin `https://`) y `CSRF_TRUSTED_ORIGINS`
a `https://tu-dominio.up.railway.app`.

---

## 8) Iterar (cambios que pida la clínica)

Tu flujo de trabajo diario:

1. Desarrollas **en local** como siempre (`docker compose up`, front en :5173).
2. Cuando algo está listo: `git commit` + `git push origin main`.
3. Railway detecta el push y **redeploya solo** (web y worker).

Así local y producción quedan sincronizados. Las migraciones nuevas corren solas
en cada deploy (servicio web).

---

## Solución de problemas

| Síntoma | Causa probable | Arreglo |
|---|---|---|
| `ImproperlyConfigured: Faltan variables de entorno obligatorias` | falta una de las cuatro obligatorias | el propio mensaje las lista todas; revisa espacios en el **nombre** de la variable |
| El log repite un error de arranque y reintenta 30 veces | Django no levanta: variable inválida, settings roto, dependencia | el error real está en el log — léelo. **No** asumas que es la base de datos |
| `El rol de base de datos EVADE Row Level Security` | `DATABASE_URL` apunta al rol `postgres` en vez de `maily_app` | corrige `DATABASE_URL`; si es un rollback a propósito, `REQUIRE_DB_ROLE_RLS=false` |
| Deploy falla en build | node_modules/venv en el contexto | ya está el `.dockerignore`; revisa el log de build |
| 400 Bad Request / DisallowedHost | dominio no está en ALLOWED_HOSTS | deja `DJANGO_ALLOWED_HOSTS=.railway.app` |
| 500 al subir imágenes | `CLOUDINARY_URL` mal o falta `DJANGO_DEFAULT_FILE_STORAGE` | revisa esas 2 variables en el web |
| Los PDF no se generan | worker caído o sin Redis | revisa logs del `worker` y que `REDIS_URL` esté puesta |
| CSRF 403 al hacer login | falta el origen en CSRF_TRUSTED_ORIGINS | deja `https://*.railway.app` (o tu dominio exacto) |
| Login "no encuentra usuario" | falta correr el seed | corre `python manage.py seed_demo` en el web |

---

## Notas de seguridad (piloto → producción real)

- Los **secretos** (`DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY`, etc.) son solo de
  Railway; nunca en el código ni en git.
- Para **pacientes reales**: activa entrega autenticada en Cloudinary (URLs
  firmadas) y aprieta `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` al dominio real.
- El Postgres de Railway es conexión directa (sin pgbouncer), así que el
  aislamiento multi-tenant con RLS funciona sin cambios.
