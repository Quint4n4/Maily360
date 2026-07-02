"""
URLs de la app authn.

Registra los endpoints del dominio de autenticación bajo el prefijo
/api/v1/ definido en config/urls.py.

Actualmente:
    GET  /api/v1/me/               — perfil del usuario autenticado (MeApi).
    POST /api/v1/auth/change-password/ — cambio de contraseña (PasswordChangeApi).

Los endpoints SimpleJWT (login, refresh, verify) se registran directamente
en config/urls.py y NO se duplican aquí.
"""

from django.urls import path

from apps.authn.views import MeApi, PasswordChangeApi

urlpatterns = [
    path("me/", MeApi.as_view(), name="me"),
    path("auth/change-password/", PasswordChangeApi.as_view(), name="password-change"),
]
