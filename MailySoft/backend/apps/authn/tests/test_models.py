"""
Tests para apps/authn/models.py y apps/authn/managers.py.

Cubre: UserManager.create_user, create_superuser, restricciones del modelo,
propiedades y representación en cadena.
"""

import pytest
from django.db import IntegrityError

from apps.authn.models import User
from tests.factories import UserFactory


# ---------------------------------------------------------------------------
# UserManager.create_user
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_user_normalizes_email() -> None:
    """Arrange: email con dominio en mayúsculas.
    Act: create_user.
    Assert: el email se guarda con el dominio en minúsculas.
    """
    # Arrange
    raw_email = "Ana@EXAMPLE.COM"

    # Act
    user = User.objects.create_user(email=raw_email, password="supersecreto99!")

    # Assert
    assert user.email == "Ana@example.com"


@pytest.mark.django_db
def test_create_user_requires_email() -> None:
    """Arrange: email vacío.
    Act: create_user.
    Assert: lanza ValueError.
    """
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="email es obligatorio"):
        User.objects.create_user(email="", password="supersecreto99!")


@pytest.mark.django_db
def test_create_user_hashes_password() -> None:
    """Arrange: contraseña en texto plano.
    Act: create_user.
    Assert: la contraseña almacenada es distinta al texto plano (hasheada).
    """
    # Arrange
    raw_password = "texto-plano-inseguro"

    # Act
    user = User.objects.create_user(email="hash@test.com", password=raw_password)

    # Assert
    assert user.password != raw_password
    assert user.check_password(raw_password)  # pero la verificación funciona


@pytest.mark.django_db
def test_create_user_with_none_password_is_unusable() -> None:
    """Un usuario sin contraseña no puede autenticarse con contraseña.

    Útil para cuentas SSO / invitaciones pendientes.
    """
    # Arrange / Act
    user = User.objects.create_user(email="sinpass@test.com", password=None)

    # Assert
    assert not user.has_usable_password()


# ---------------------------------------------------------------------------
# UserManager.create_superuser
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_superuser_sets_is_platform_staff_true() -> None:
    """create_superuser debe establecer is_platform_staff=True por defecto."""
    # Arrange / Act
    superuser = User.objects.create_superuser(
        email="super@maily.test", password="supersecreto99!"
    )

    # Assert
    assert superuser.is_platform_staff is True


@pytest.mark.django_db
def test_create_superuser_sets_is_staff_and_is_superuser() -> None:
    """create_superuser debe forzar is_staff=True e is_superuser=True."""
    # Arrange / Act
    superuser = User.objects.create_superuser(
        email="super2@maily.test", password="supersecreto99!"
    )

    # Assert
    assert superuser.is_staff is True
    assert superuser.is_superuser is True


@pytest.mark.django_db
def test_create_superuser_raises_if_is_staff_false() -> None:
    """Si se pasa is_staff=False explícitamente, create_superuser debe lanzar ValueError."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="is_staff=True"):
        User.objects.create_superuser(
            email="bad@maily.test", password="supersecreto99!", is_staff=False
        )


@pytest.mark.django_db
def test_create_superuser_raises_if_is_superuser_false() -> None:
    """Si se pasa is_superuser=False explícitamente, create_superuser debe lanzar ValueError."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="is_superuser=True"):
        User.objects.create_superuser(
            email="bad2@maily.test", password="supersecreto99!", is_superuser=False
        )


# ---------------------------------------------------------------------------
# Restricciones del modelo
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_email_is_unique() -> None:
    """No se pueden crear dos usuarios con el mismo email.

    Arrange: un usuario ya existe con email X.
    Act: intentar crear otro con el mismo email.
    Assert: lanza IntegrityError.
    """
    # Arrange
    UserFactory(email="duplicado@test.com")

    # Act / Assert
    with pytest.raises(IntegrityError):
        UserFactory(email="duplicado@test.com")


# ---------------------------------------------------------------------------
# Propiedades y métodos del modelo
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_name_property_returns_first_and_last_name() -> None:
    """full_name combina first_name y last_name con espacio."""
    # Arrange
    user = UserFactory(first_name="María", last_name="García")

    # Act
    result = user.full_name

    # Assert
    assert result == "María García"


@pytest.mark.django_db
def test_full_name_property_falls_back_to_email_when_names_empty() -> None:
    """Si first_name y last_name están vacíos, full_name devuelve el email."""
    # Arrange
    user = UserFactory(first_name="", last_name="")

    # Act
    result = user.full_name

    # Assert
    assert result == user.email


@pytest.mark.django_db
def test_full_name_with_only_first_name() -> None:
    """Si solo hay first_name, full_name lo devuelve sin espacio extra."""
    # Arrange
    user = UserFactory(first_name="Carlos", last_name="")

    # Act
    result = user.full_name

    # Assert
    assert result == "Carlos"


@pytest.mark.django_db
def test_str_returns_email() -> None:
    """__str__ devuelve el email del usuario."""
    # Arrange
    user = UserFactory(email="str@test.com")

    # Act
    result = str(user)

    # Assert
    assert result == "str@test.com"


# ---------------------------------------------------------------------------
# Campos predeterminados
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_user_is_active_by_default() -> None:
    """Un usuario recién creado debe estar activo por defecto."""
    # Arrange / Act
    user = User.objects.create_user(email="activo@test.com", password="pass-seguro-1")

    # Assert
    assert user.is_active is True


@pytest.mark.django_db
def test_new_user_is_not_platform_staff_by_default() -> None:
    """Un usuario normal no debe ser platform_staff."""
    # Arrange / Act
    user = User.objects.create_user(email="normal@test.com", password="pass-seguro-1")

    # Assert
    assert user.is_platform_staff is False


@pytest.mark.django_db
def test_user_id_is_uuid() -> None:
    """El PK del usuario debe ser un UUID (no un entero autoincremental)."""
    import uuid

    # Arrange / Act
    user = UserFactory()

    # Assert
    assert isinstance(user.id, uuid.UUID)
