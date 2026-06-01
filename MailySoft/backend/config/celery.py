"""
Configuración de Celery para Maily Soft.

El worker se inicia con:
    celery -A config.celery worker -l INFO
    celery -A config.celery beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("mailysoft")

# Lee la config desde Django settings con prefijo CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autodiscover tasks en todos los INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> None:  # type: ignore[no-untyped-def]
    """Tarea de prueba para verificar que Celery funciona."""
    print(f"Request: {self.request!r}")
