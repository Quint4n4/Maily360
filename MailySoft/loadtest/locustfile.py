"""
Prueba de carga con Locust contra la API de Maily Soft.

Simula usuarios de clínica autenticados navegando (lista de pacientes + dashboard
financiero). Para NO chocar con el throttle de login (5/min), hace UN solo login al
inicio y comparte el token entre todos los usuarios virtuales.

Requisitos:
  - Backend corriendo (Docker, :8000) y usuario E2E sembrado:
        docker compose exec backend python manage.py seed_e2e_user
  - Throttles subidos para la prueba (ver loadtest/README.md), si no el throttle
    `user` (300/min) limita la carga con un solo token.

Correr (headless, 100 usuarios, 60 s):
    locust -f loadtest/locustfile.py --host http://localhost:8000 \
           --headless -u 100 -r 10 -t 60s
"""

import os

import requests
from locust import HttpUser, between, events, task

LOGIN_PATH = "/api/v1/auth/login/"
EMAIL = os.getenv("LOAD_EMAIL", "e2e@maily.local")
PASSWORD = os.getenv("LOAD_PASSWORD", "Demo1234!")

_shared: dict[str, str | None] = {"token": None}


@events.test_start.add_listener
def _login_once(environment, **_kwargs):
    """Un solo login al arrancar → token compartido (evita el throttle de login 5/min)."""
    host = environment.host or "http://localhost:8000"
    resp = requests.post(
        f"{host}{LOGIN_PATH}",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    _shared["token"] = resp.json()["access"]
    print(f"Login OK como {EMAIL} — token compartido entre los usuarios virtuales.")


class ClinicUser(HttpUser):
    """Usuario de clínica navegando: piensa 1-3 s entre acciones (realista)."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.client.headers["Authorization"] = f"Bearer {_shared['token']}"

    @task(3)
    def listar_pacientes(self) -> None:
        self.client.get("/api/v1/pacientes/", name="GET /pacientes/")

    @task(2)
    def dashboard_finanzas(self) -> None:
        self.client.get("/api/v1/finanzas/dashboard/", name="GET /finanzas/dashboard/")
