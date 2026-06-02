"""
Manager del modelo User custom.

Se define aquí (y no en models.py) para evitar imports circulares:
models.py importa managers.py, nunca al revés.
"""

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager

if TYPE_CHECKING:
    from apps.authn.models import User


class UserManager(BaseUserManager["User"]):
    """Manager para el modelo User email-based de Maily Soft.

    Compatibilidad completa con `createsuperuser` y la lógica de auth de Django.
    """

    use_in_migrations = True

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> "User":
        """Crea y guarda un usuario normal.

        Args:
            email: Dirección de correo electrónico (obligatoria, se normaliza).
            password: Contraseña en texto plano (opcional; si es None, el usuario
                      no podrá autenticarse con contraseña).
            **extra_fields: Campos adicionales del modelo User.

        Returns:
            Instancia de User guardada en base de datos.

        Raises:
            ValueError: Si `email` es una cadena vacía.
        """
        if not email:
            raise ValueError("El email es obligatorio para crear un usuario.")
        email = self.normalize_email(email)
        user: "User" = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str,
        **extra_fields: Any,
    ) -> "User":
        """Crea un superusuario con acceso completo al Django admin y a la plataforma.

        Args:
            email: Dirección de correo electrónico.
            password: Contraseña en texto plano.
            **extra_fields: Campos adicionales; is_staff e is_superuser
                            se fuerzan a True automáticamente.

        Returns:
            Instancia de User guardada en base de datos con privilegios de superusuario.

        Raises:
            ValueError: Si is_staff o is_superuser se pasan explícitamente como False.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_platform_staff", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("El superusuario debe tener is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("El superusuario debe tener is_superuser=True.")

        return self.create_user(email, password, **extra_fields)
