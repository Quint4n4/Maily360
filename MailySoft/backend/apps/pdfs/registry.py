"""Registro de generadores de PDF por `kind`.

Cada módulo registra su generador + su permiso en su AppConfig.ready():

    # apps/expediente/apps.py
    def ready(self):
        from apps.pdfs.registry import register_pdf_kind
        from apps.expediente.pdf_jobs import build_book_pdf
        from apps.core.permissions import EvolutionPermission
        register_pdf_kind("book", builder=build_book_pdf, permission=EvolutionPermission)

Un builder tiene la firma:

    build(*, params: dict, tenant) -> tuple[bytes, str]   # (pdf_bytes, filename)

`permission` es una clase de permiso DRF (role-based) con la que los endpoints de
estado/descarga revalidan el acceso (defensa en profundidad sobre el job_id, que
ya es un UUID inadivinable obtenido de un endpoint que verificó permisos).
"""

from dataclasses import dataclass
from typing import Any, Callable

#: build(*, params: dict, tenant) -> (pdf_bytes, filename)
PdfBuilder = Callable[..., tuple[bytes, str]]


@dataclass(frozen=True)
class PdfKindSpec:
    """Generador + permiso de un tipo de PDF."""

    builder: PdfBuilder
    permission: type[Any]


_REGISTRY: dict[str, PdfKindSpec] = {}


def register_pdf_kind(
    kind: str, *, builder: PdfBuilder, permission: type[Any]
) -> None:
    """Registra el generador y el permiso de un tipo de PDF."""
    _REGISTRY[kind] = PdfKindSpec(builder=builder, permission=permission)


def get_pdf_kind(kind: str) -> PdfKindSpec:
    """Devuelve el spec del kind; lanza KeyError si no está registrado."""
    try:
        return _REGISTRY[kind]
    except KeyError as exc:
        raise KeyError(f"No hay PDF kind registrado para {kind!r}.") from exc
