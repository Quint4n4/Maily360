"""
URLs de la app authn.

Registra los endpoints del dominio de autenticación bajo el prefijo
/api/v1/ definido en config/urls.py.

Actualmente:
    GET /api/v1/me/  — perfil del usuario autenticado (MeApi).

Los endpoints SimpleJWT (login, refresh, verify) se registran directamente
en config/urls.py y NO se duplican aquí.
"""

from django.urls import path

from apps.authn.views import MeApi

urlpatterns = [
    path("me/", MeApi.as_view(), name="me"),
]
