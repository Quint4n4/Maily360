"""
AppConfig de la app audit.

ready() conecta la señal user_login_failed de Django.

Decisión de diseño — LOGIN vs señales:
    SimpleJWT NO dispara django.contrib.auth.signals.user_logged_in por defecto.
    Para el evento LOGIN (éxito de autenticación JWT), la opción más robusta y
    confiable es un MailyTokenObtainPairView custom en apps/authn que, tras
    validar credenciales, llame a audit_record(action=LOGIN, ...).

    La señal user_login_failed SÍ se dispara cuando la autenticación falla
    con cualquier backend de Django (incluyendo ModelBackend + DRF/SimpleJWT
    cuando authenticate() se llama internamente). Se conecta aquí.

    El evento LOGIN de éxito se registra en MailyTokenObtainPairView (apps/authn/views.py).
"""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """Configuración de la app audit."""

    name = "apps.audit"
    verbose_name = "Auditoría NOM-024"

    def ready(self) -> None:
        """Conecta señales de autenticación al arranque de Django."""
        # Import local para evitar importar modelos antes de que Django los inicialice.
        from django.contrib.auth.signals import user_login_failed

        from apps.audit.signals import handle_login_failed

        user_login_failed.connect(handle_login_failed)
