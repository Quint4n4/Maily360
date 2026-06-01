"""
ASGI config para Maily Soft.

Maneja tanto HTTP (Django) como WebSockets (Channels).
"""

import os

import django
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django.setup()

# Importar websocket_urlpatterns después de django.setup()
# from apps.realtime.routing import websocket_urlpatterns  # activar en paso futuro

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(
                    []  # websocket_urlpatterns aquí cuando se implemente
                )
            )
        ),
    }
)
