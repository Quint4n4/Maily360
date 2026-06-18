"""
Selectors de la app recetas — sub-fases B1.1 y B1.2.

Lecturas/queries: NUNCA modifican datos.
El TenantManager (objects) filtra por tenant activo + excluye soft-deleted en Medication,
Prescription y PrescriptionItem. GlobalMedication usa el manager estándar (sin tenant).

Convención: keyword-only args, nombrado acción+entidad.

REGLA: toda lectura por id usa un selector; NUNCA Model.objects.get inline en la view.

Funciones públicas (B1.1):
    medication_search  — une GlobalMedication + Medication del tenant, filtra por `q`,
                         limita a `limit` resultados. Usado por el autocompletado.
    medication_get     — recupera un Medication custom por UUID (anti-IDOR, tenant-safe).

Funciones públicas (B1.2):
    prescription_get   — receta por UUID (anti-IDOR, tenant-safe, ítems precargados).
    prescription_list  — historial de recetas de un paciente (paginable, -issued_at).
"""

import uuid
from typing import Any

from django.db.models import QuerySet

from apps.pacientes.models import Patient
from apps.recetas.models import GlobalMedication, Medication, Prescription


# Límite máximo de resultados del autocompletado.
# 25 resulta natural en un dropdown; evita cargas masivas en búsquedas vacías.
SEARCH_LIMIT: int = 25

# Tope defensivo de longitud del término de búsqueda (B1.1 audit M1).
# Ningún nombre de medicamento supera 200 chars (modelo max_length=200); cortar
# evita pasar entradas arbitrariamente grandes a dos queries ILIKE por request (DoS).
MAX_Q_LENGTH: int = 200


def medication_search(
    *,
    q: str,
    limit: int = SEARCH_LIMIT,
) -> list[dict[str, Any]]:
    """Busca medicamentos en el catálogo global + Medication custom del tenant activo.

    Une los resultados de GlobalMedication (catálogo global) y Medication (custom
    de la clínica). Filtra por `q` (icontains en generic_name y commercial_name)
    y `is_active=True`. Ordena por generic_name. Limita a `limit` resultados.

    La búsqueda es case-insensitive en ambos campos. Si `q` está vacío o en blanco,
    devuelve lista vacía (el autocompletado no carga todo el catálogo sin input).

    Multi-tenant: los medicamentos globales son de todos. Los custom se filtran
    automáticamente por el TenantManager.

    Salida marcada con `source`:
        "global"  → GlobalMedication.
        "custom"  → Medication (del tenant).

    La construcción final en Python (en lugar de UNION en SQL) es deliberada:
      - Los catálogos son pequeños (≤ 500 globales + ≤ 200 custom es el caso típico).
      - Evita complejidad con UNION en ORM entre modelos distintos.
      - Un `limit` de 25 hace que el corte sea irrelevante en tiempo de respuesta.
    Si el catálogo crece significativamente, migrar a ElasticSearch o una vista SQL.

    Args:
        q:     Texto de búsqueda (icontains). Si vacío, devuelve [].
        limit: Máximo de resultados combinados. Default=SEARCH_LIMIT (25).

    Returns:
        Lista de dicts con claves: id, generic_name, commercial_name, form,
        concentration, presentation, source ("global" | "custom").
    """
    q = q.strip()[:MAX_Q_LENGTH]
    if not q:
        return []

    from django.db.models import Q as DQ

    # --- Catálogo global ---
    global_qs = (
        GlobalMedication.objects.filter(is_active=True)
        .filter(DQ(generic_name__icontains=q) | DQ(commercial_name__icontains=q))
        .order_by("generic_name")[:limit]
    )

    global_results: list[dict[str, Any]] = [
        {
            "id": str(med.id),
            "generic_name": med.generic_name,
            "commercial_name": med.commercial_name,
            "form": med.form,
            "concentration": med.concentration,
            "presentation": med.presentation,
            "source": "global",
        }
        for med in global_qs
    ]

    # --- Medicamentos custom del tenant (TenantManager filtra automáticamente) ---
    custom_qs = (
        Medication.objects.filter(is_active=True)
        .filter(DQ(generic_name__icontains=q) | DQ(commercial_name__icontains=q))
        .order_by("generic_name")[:limit]
    )

    custom_results: list[dict[str, Any]] = [
        {
            "id": str(med.id),
            "generic_name": med.generic_name,
            "commercial_name": med.commercial_name,
            "form": med.form,
            "concentration": med.concentration,
            "presentation": med.presentation,
            "source": "custom",
        }
        for med in custom_qs
    ]

    # Combinar y cortar al límite total, ordenando por generic_name.
    combined = sorted(
        global_results + custom_results,
        key=lambda m: m["generic_name"].lower(),
    )
    return combined[:limit]


def medication_get(*, medication_id: uuid.UUID) -> Medication:
    """Recupera un Medication custom por UUID (anti-IDOR, tenant-safe).

    Usado por: B1.2 (alta de renglón de receta). NO usar Medication.objects.get()
    directamente en vistas; usar este selector para conservar el filtro de tenant.

    Usa el TenantManager (filtra por tenant del contexto activo + excluye
    soft-deleted). Lanza Medication.DoesNotExist si no existe o no pertenece
    al tenant activo. Las vistas capturan DoesNotExist y devuelven 404.

    Args:
        medication_id: UUID del medicamento custom.

    Returns:
        Instancia de Medication.

    Raises:
        Medication.DoesNotExist: si el medicamento no existe en el tenant activo.
    """
    return Medication.objects.get(id=medication_id)


# ---------------------------------------------------------------------------
# Prescription selectors (B1.2)
# ---------------------------------------------------------------------------


def prescription_get(*, prescription_id: uuid.UUID) -> Prescription:
    """Retorna una receta por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo + excluye
    soft-deleted). Lanza Prescription.DoesNotExist si no existe o no pertenece
    al tenant activo. Las vistas capturan DoesNotExist y devuelven 404 (anti-IDOR).

    Precarga `items` (ordenados por `order`), `doctor__membership__user`,
    `patient` y `cancelled_by` para evitar N+1 al serializar el detalle completo.

    Args:
        prescription_id: UUID de la receta.

    Returns:
        Instancia de Prescription con relaciones precargadas.

    Raises:
        Prescription.DoesNotExist: si la receta no existe en el tenant activo.
    """
    return (
        Prescription.objects.select_related(
            "patient",
            "doctor",
            "doctor__membership",
            "doctor__membership__user",
            "appointment",
            "evolution_note",
            "cancelled_by",
        )
        .prefetch_related("items")
        .get(id=prescription_id)
    )


def prescription_list(*, patient: Patient) -> "QuerySet[Prescription]":
    """Retorna el QuerySet de recetas de un paciente, orden -issued_at.

    Filtra por tenant del contexto activo (TenantManager) y por patient en
    defensa en profundidad (anti-IDOR). Precarga doctor e ítems para evitar N+1.
    Incluye todas las recetas: activas y anuladas (el historial muestra el estado).

    Args:
        patient: Paciente cuyas recetas se recuperan.

    Returns:
        QuerySet[Prescription] ordenado por -issued_at.
    """
    return (
        Prescription.objects.select_related(
            "doctor",
            "doctor__membership",
            "doctor__membership__user",
        )
        .prefetch_related("items")
        .filter(patient=patient)
        .order_by("-issued_at")
    )
