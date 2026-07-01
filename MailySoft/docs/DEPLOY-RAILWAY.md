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

DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}
CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}

CLOUDINARY_URL=<pega-tu-CLOUDINARY_URL-de-Cloudinary>
DJANGO_DEFAULT_FILE_STORAGE=cloudinary_storage.storage.MediaCloudinaryStorage

DEMO_OWNER_PASSWORD=<una-clave-fuerte-para-el-login-del-personal>
```

**Genera cada secreto** (3 distintos) con este comando en tu terminal:
```
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

> `${{Postgres.DATABASE_URL}}` y `${{Redis.REDIS_URL}}` son *reference variables*
> de Railway: se autollenan. Si Railway nombró tus plugins distinto (p. ej.
> `Postgres-XXXX`), usa ese nombre.

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
