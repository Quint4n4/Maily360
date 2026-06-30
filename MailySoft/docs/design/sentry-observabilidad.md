# Sentry — observabilidad de errores

> Estado: **integrado, dormido en local** · 2026-06-29
>
> Sentry captura automáticamente las excepciones (con stack trace) del backend, del
> worker de Celery y del frontend, y te alerta. Está montado para **activarse solo en
> producción** sin enviar nada en local.

## Cómo está montado

- **Backend** (`config/settings/base.py`): se inicializa **solo si existe `SENTRY_DSN`**.
  Sin esa variable (caso local) Sentry queda dormido. Como el settings lo importan
  gunicorn y el worker de Celery, captura errores **web y de tareas en 2º plano**
  (p. ej. una falla al generar un PDF).
- **Frontend** (`src/main.tsx`): se inicializa **solo si existe `VITE_SENTRY_DSN`**
  (al construir). Captura los errores de JavaScript del navegador.

### Privacidad (app de salud — NOM-024 / LFPDPPP)

Configurado para **NO enviar datos de pacientes** a Sentry:

| Ajuste | Efecto |
|---|---|
| `send_default_pii=False` | sin identidad de usuario ni IP |
| `max_request_body_size="never"` | sin cuerpos de request (donde van nombre, CURP…) |
| `include_local_variables=False` | sin variables locales en los tracebacks |

Aun así: si se sube `traces_sample_rate` o se relajan estos ajustes, revisar que no
se filtre PHI. Sentry también permite scrubbing del lado del servidor.

## Cómo activarlo en producción (Railway)

1. Crea una cuenta en **sentry.io** y un proyecto (uno **Django** para el backend,
   otro **React** para el frontend, o uno solo si prefieres).
2. Copia el **DSN** de cada proyecto (Settings → Client Keys (DSN)).
3. En Railway, en las variables de entorno del servicio:
   - **Backend** (web y worker): `SENTRY_DSN=<dsn>` · `SENTRY_ENVIRONMENT=production`
   - **Frontend** (al construir): `VITE_SENTRY_DSN=<dsn>` · `VITE_SENTRY_ENVIRONMENT=production`
4. Redespliega. Listo: a partir de ahí los errores caen en Sentry con alertas.

> El frontend necesita la variable **al momento de `npm run build`** (Vite la incrusta
> en el bundle), no en tiempo de ejecución.

## Cómo probar que funciona

Con el DSN puesto, fuerza un error de prueba:

- Backend (shell): `import sentry_sdk; sentry_sdk.capture_message("prueba Sentry")` →
  debe aparecer en el dashboard de Sentry.
- Frontend: `throw new Error("prueba Sentry")` en la consola → aparece en Sentry.

## Variables

| Variable | Dónde | Default | Para qué |
|---|---|---|---|
| `SENTRY_DSN` | backend | "" (dormido) | activa Sentry en el backend/worker |
| `SENTRY_ENVIRONMENT` | backend | `production` | etiqueta de ambiente |
| `SENTRY_TRACES_SAMPLE_RATE` | backend | `0.0` | muestreo de performance tracing |
| `VITE_SENTRY_DSN` | frontend (build) | "" (dormido) | activa Sentry en el navegador |
| `VITE_SENTRY_ENVIRONMENT` | frontend (build) | `MODE` de Vite | etiqueta de ambiente |
