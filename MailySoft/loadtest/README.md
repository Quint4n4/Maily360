# Pruebas de carga (Locust)

Simulan muchos usuarios concurrentes golpeando la API para medir throughput,
latencia y encontrar cuellos de botella. El escenario está en `locustfile.py`.

## Cómo correr

1. Backend corriendo (Docker) + usuario E2E sembrado:
   ```bash
   docker compose exec backend python manage.py seed_finanzas
   docker compose exec backend python manage.py seed_e2e_user
   ```
2. Instalar Locust en un venv con **Python 3.12** (el 3.14 rompe con gevent/greenlet):
   ```bash
   python3.12 -m venv .venv-load
   .venv-load/bin/pip install locust
   ```
3. Correr (headless, 60 usuarios, 30 s):
   ```bash
   .venv-load/bin/locust -f loadtest/locustfile.py --host http://localhost:8000 \
       --headless -u 60 -r 15 -t 30s
   ```
   Sin `--headless` abre la UI web en http://localhost:8089 (gráficas en vivo).

## Throttles

El throttle `user` (300/min) limita la carga con UN solo token (el locustfile reusa
un token para no chocar con el throttle de login 5/min). Para medir capacidad real,
súbelo temporalmente y **RECREA** el backend (`restart` NO recarga el env):

```bash
# en backend/.env.dev:  DRF_THROTTLE_USER=1000000/minute
docker compose up -d backend
# ... correr la prueba ...
# revertir a 300/minute y up -d de nuevo
```

## Hallazgos (2026-06-29, dev local)

| Carga | Resultado |
|---|---|
| 5 usuarios | 0 fallos, ~35 ms |
| **60 usuarios** | **0 fallos**, mediana **13 ms**, p95 79 ms, ~29 req/s (dashboard 7 ms por el caché) |
| 200 usuarios | colapso: `FATAL: sorry, too many clients already` (Postgres sin conexiones) |

**El cuello a alta concurrencia es el LÍMITE DE CONEXIONES de Postgres** — justo lo
que predijimos en [`../docs/design/pgbouncer-rls-escalabilidad.md`](../docs/design/pgbouncer-rls-escalabilidad.md).
Confirmado empíricamente: el caché de Redis funciona (dashboard 7 ms) y la app es
rápida con decenas de usuarios; el muro es la conexión a la BD, no la lógica.

### Caveats importantes

- Es el servidor de **DESARROLLO** (`runserver` + `DEBUG=True`), que abre una conexión
  por hilo SIN límite → agota Postgres bajo mucha concurrencia. **Producción** usa
  gunicorn con workers ACOTADOS (~8 conexiones por réplica) → aguanta mucho más.
- Para números autoritativos: correr contra **staging** con config de producción
  (gunicorn, `DEBUG=False`) y, al escalar a muchas réplicas, pgbouncer.
