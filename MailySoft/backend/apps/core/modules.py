"""
Catálogo de módulos vendibles y sus dependencias.

Los MÓDULOS viven en el CÓDIGO (aquí), no en la base de datos: un módulo existe
porque hay código que lo implementa, así que no tiene sentido que alguien "cree"
uno desde el panel. Los PLANES (base de datos) solo referencian estos slugs.

El corte NO es por app de Django: `apps.finanzas` contiene cinco módulos
vendibles por separado (servicios, paquetes, cotizaciones, cobranza, CFDI). Por
eso el guard de acceso debe aplicarse por CAPACIDAD, no por app.

Multi-sucursal NO es un módulo: es el límite `max_sucursales`. Un flag aparte
sería una segunda fuente de verdad que puede contradecir al límite.

Ver docs/design/planes-modulos-mapa-dependencias.md para el mapa verificado.
"""

from django.core.exceptions import ValidationError
from django.db import models

from apps.tenancy.models import TenantMembership


class Module(models.TextChoices):
    """Módulos que una clínica puede tener contratados."""

    # --- Clínico: la base. Todos los planes lo traen completo. ---
    AGENDA = "agenda", "Agenda y citas"
    RECORDATORIOS = "recordatorios", "Recordatorios de cita"
    EXPEDIENTE = "expediente", "Expediente clínico"
    RECETAS = "recetas", "Recetas"
    NOTAS = "notas", "Notas y tareas"

    # --- Comercial: el upgrade. ---
    SERVICIOS = "servicios", "Servicios y precios"
    PAQUETES = "paquetes", "Paquetes"
    COTIZACIONES = "cotizaciones", "Cotizaciones"
    COBRANZA = "cobranza", "Cobranza y estado de cuenta"
    CFDI = "cfdi", "Facturación CFDI"

    # --- Especiales: solo por override, no van en planes estándar. ---
    CALENDARIZACION = "calendarizacion", "Calendarización de tratamientos"

    # --- Operación. ---
    PERSONAL = "personal", "Gestión de personal"


#: Dependencias DURAS entre módulos: encender la llave exige encender los valores.
#: Verificadas contra el código (llaves foráneas e importes entre apps).
MODULE_REQUIRES: dict[str, frozenset[str]] = {
    Module.RECORDATORIOS: frozenset({Module.AGENDA}),
    Module.PAQUETES: frozenset({Module.SERVICIOS}),
    Module.COTIZACIONES: frozenset({Module.SERVICIOS}),
    Module.CFDI: frozenset({Module.COBRANZA}),
    # Calendarización cruza lo clínico con lo comercial: arma esquemas de
    # tratamiento con conceptos del catálogo y genera cotizaciones.
    Module.CALENDARIZACION: frozenset(
        {Module.EXPEDIENTE, Module.SERVICIOS, Module.COTIZACIONES}
    ),
}


#: Qué módulo hace ÚTIL a cada rol. Un rol sin su módulo es un usuario que no
#: puede hacer su trabajo: el rol `finance` sin cobranza solo vería agenda y
#: pacientes en modo lectura. Por eso los roles se DERIVAN de los módulos.
ROLE_REQUIRES: dict[str, frozenset[str]] = {
    TenantMembership.Role.OWNER: frozenset(),
    TenantMembership.Role.ADMIN: frozenset(),
    TenantMembership.Role.READONLY: frozenset(),
    TenantMembership.Role.DOCTOR: frozenset({Module.EXPEDIENTE}),
    TenantMembership.Role.NURSE: frozenset({Module.EXPEDIENTE}),
    TenantMembership.Role.RECEPTION: frozenset({Module.AGENDA}),
    TenantMembership.Role.FINANCE: frozenset({Module.COBRANZA}),
}


#: Agrupación para la interfaz del super-admin (orden de despliegue).
MODULE_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Clínico",
        [
            Module.AGENDA,
            Module.RECORDATORIOS,
            Module.EXPEDIENTE,
            Module.RECETAS,
            Module.NOTAS,
        ],
    ),
    (
        "Comercial",
        [
            Module.SERVICIOS,
            Module.PAQUETES,
            Module.COTIZACIONES,
            Module.COBRANZA,
            Module.CFDI,
        ],
    ),
    ("Especiales", [Module.CALENDARIZACION]),
    ("Operación", [Module.PERSONAL]),
]


ALL_MODULES: frozenset[str] = frozenset(Module.values)


def modulos_desconocidos(modules: list[str] | set[str]) -> set[str]:
    """Devuelve los slugs que no existen en el catálogo.

    Args:
        modules: Slugs a revisar.

    Returns:
        Conjunto de slugs desconocidos (vacío si todos son válidos).
    """
    return set(modules) - ALL_MODULES


def expandir_dependencias(modules: list[str] | set[str]) -> set[str]:
    """Agrega las dependencias duras de cada módulo, en cascada.

    Ejemplo: {'calendarizacion'} → {'calendarizacion', 'expediente', 'servicios',
    'cotizaciones'} (cotizaciones a su vez arrastra servicios).

    Args:
        modules: Slugs elegidos.

    Returns:
        Conjunto con los módulos elegidos MÁS todo lo que requieren.
    """
    resultado = set(modules)
    pendientes = list(resultado)
    while pendientes:
        actual = pendientes.pop()
        for requerido in MODULE_REQUIRES.get(actual, frozenset()):
            if requerido not in resultado:
                resultado.add(requerido)
                pendientes.append(requerido)
    return resultado


def dependencias_faltantes(modules: list[str] | set[str]) -> dict[str, set[str]]:
    """Detecta módulos encendidos cuyas dependencias NO están encendidas.

    Args:
        modules: Slugs elegidos.

    Returns:
        Dict {módulo: dependencias que le faltan}. Vacío si el conjunto es
        consistente.
    """
    activos = set(modules)
    faltantes: dict[str, set[str]] = {}
    for modulo in activos:
        requeridos = MODULE_REQUIRES.get(modulo, frozenset())
        ausentes = requeridos - activos
        if ausentes:
            faltantes[modulo] = ausentes
    return faltantes


def validar_modulos(modules: list[str] | set[str]) -> None:
    """Valida que los módulos existan y que sus dependencias estén cubiertas.

    NO expande automáticamente: guardar un plan con "Cotizaciones" pero sin
    "Servicios" es un error de captura que hay que señalar, no adivinar. La
    interfaz del super-admin usa `expandir_dependencias` para ayudar antes de
    llegar aquí.

    Args:
        modules: Slugs elegidos.

    Raises:
        ValidationError: si hay slugs desconocidos o dependencias sin cubrir.
    """
    desconocidos = modulos_desconocidos(modules)
    if desconocidos:
        raise ValidationError(
            f"Módulos desconocidos: {', '.join(sorted(desconocidos))}."
        )

    faltantes = dependencias_faltantes(modules)
    if faltantes:
        detalle = "; ".join(
            f"'{Module(mod).label}' requiere "
            f"{', '.join(sorted(Module(d).label for d in deps))}"
            for mod, deps in sorted(faltantes.items())
        )
        raise ValidationError(f"Faltan módulos requeridos: {detalle}.")


def roles_disponibles(modules: list[str] | set[str]) -> set[str]:
    """Roles que tienen sentido con los módulos contratados.

    Args:
        modules: Slugs contratados por la clínica.

    Returns:
        Conjunto de roles asignables como strings planos (no miembros del enum,
        para que serialicen limpio en la API). Dueño, administrador y
        solo-lectura siempre están; el resto depende de su módulo.
    """
    activos = set(modules)
    return {
        str(rol.value)
        for rol, requeridos in ROLE_REQUIRES.items()
        if requeridos <= activos
    }
