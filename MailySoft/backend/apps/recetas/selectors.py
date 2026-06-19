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
from typing import Any, Optional

from django.db.models import QuerySet

from apps.pacientes.models import Patient
from apps.recetas.models import GlobalMedication, Medication, Prescription, PrescriptionFormat


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
    kind: str | None = None,
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
        kind:  Filtrar por tipo de ítem (medicamento|suero|terapia). None = todos.

    Returns:
        Lista de dicts con claves: id, generic_name, commercial_name, form,
        concentration, presentation, source ("global" | "custom").
    """
    q = q.strip()[:MAX_Q_LENGTH]
    if not q:
        return []

    from django.db.models import Q as DQ

    # --- Catálogo global ---
    global_qs_base = (
        GlobalMedication.objects.filter(is_active=True)
        .filter(DQ(generic_name__icontains=q) | DQ(commercial_name__icontains=q))
    )
    if kind is not None:
        global_qs_base = global_qs_base.filter(kind=kind)
    global_qs = global_qs_base.order_by("generic_name")[:limit]

    global_results: list[dict[str, Any]] = [
        {
            "id": str(med.id),
            "generic_name": med.generic_name,
            "commercial_name": med.commercial_name,
            "form": med.form,
            "concentration": med.concentration,
            "presentation": med.presentation,
            "source": "global",
            "kind": med.kind,
            "controlled_group": med.controlled_group,
        }
        for med in global_qs
    ]

    # --- Medicamentos custom del tenant (TenantManager filtra automáticamente) ---
    custom_qs_base = (
        Medication.objects.filter(is_active=True)
        .filter(DQ(generic_name__icontains=q) | DQ(commercial_name__icontains=q))
    )
    if kind is not None:
        custom_qs_base = custom_qs_base.filter(kind=kind)
    custom_qs = custom_qs_base.order_by("generic_name")[:limit]

    custom_results: list[dict[str, Any]] = [
        {
            "id": str(med.id),
            "generic_name": med.generic_name,
            "commercial_name": med.commercial_name,
            "form": med.form,
            "concentration": med.concentration,
            "presentation": med.presentation,
            "source": "custom",
            "kind": med.kind,
            "controlled_group": med.controlled_group,
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


def prescription_format_get(*, format_id: uuid.UUID) -> PrescriptionFormat:
    """Recupera un PrescriptionFormat por UUID (anti-IDOR, tenant-safe).

    Usa el TenantManager (filtra por tenant del contexto activo + excluye
    soft-deleted). Lanza PrescriptionFormat.DoesNotExist si no existe o
    no pertenece al tenant activo. Las vistas capturan DoesNotExist y devuelven 404.

    Args:
        format_id: UUID del formato.

    Returns:
        Instancia de PrescriptionFormat.

    Raises:
        PrescriptionFormat.DoesNotExist: si el formato no existe en el tenant activo.
    """
    return PrescriptionFormat.objects.select_related("doctor", "doctor__membership__user").get(
        id=format_id, is_active=True
    )


def prescription_format_list(
    *,
    tenant: Any,
) -> "QuerySet[PrescriptionFormat]":
    """Retorna todos los formatos activos del tenant, ordenados por -is_default, name.

    Usa TenantManager (filtra automáticamente por tenant activo).
    Precarga la relación doctor para evitar N+1 al serializar.

    Args:
        tenant: Tenant del contexto (solo para tipado; el manager ya filtra).

    Returns:
        QuerySet[PrescriptionFormat] activos del tenant.
    """
    return PrescriptionFormat.objects.filter(is_active=True).select_related(
        "doctor", "doctor__membership", "doctor__membership__user"
    ).order_by("-is_default", "name")


def prescription_format_resolve(
    *,
    prescription: Any,
    format_override_id: Optional[uuid.UUID] = None,
    layout_override: Optional[str] = None,
) -> PrescriptionFormat:
    """Resuelve el PrescriptionFormat para una receta concreta.

    Orden de prioridad:
    1. format_override_id (formato explícito pasado, ej. para vista previa por id).
    2. layout_override (nombre de layout, ej. ?formato=compact — solo para preview).
    3. PrescriptionFormat del médico de la receta con is_authorized=True.
    4. PrescriptionFormat is_default=True del tenant.
    5. Objeto en memoria con defaults de fábrica (sin persistencia en BD).

    Si format_override_id o layout_override producen un objeto inválido, se hace
    fallback silencioso al siguiente nivel.

    Args:
        prescription:      Instancia de Prescription con tenant y doctor precargados.
        format_override_id: UUID explícito de un PrescriptionFormat (vista previa por id).
        layout_override:   Nombre de layout ("standard"|"compact"|"digital") solo para
                           vista previa cuando no se tiene un id.

    Returns:
        PrescriptionFormat (real o en memoria) a usar para el PDF.
    """
    from apps.recetas.pdf import VALID_LAYOUTS

    tenant = prescription.tenant

    # --- 1. Override por UUID explícito ---
    if format_override_id is not None:
        try:
            return (
                PrescriptionFormat.all_objects.select_related("doctor")
                .get(id=format_override_id, tenant=tenant, is_active=True)
            )
        except PrescriptionFormat.DoesNotExist:
            pass  # fallback al siguiente nivel

    # --- 2. Override por nombre de layout (preview rápido) ---
    if layout_override and layout_override in VALID_LAYOUTS:
        fmt = PrescriptionFormat.__new__(PrescriptionFormat)
        # Inicializar solo los campos necesarios para el contexto del PDF.
        fmt.base_layout = layout_override
        fmt.accent_color = "#9A7B1E"
        fmt.font = "helvetica"
        fmt.sections = {}
        fmt.letterhead_mode = "digital"
        fmt.is_default = False
        fmt.is_authorized = False
        fmt.doctor_id = None
        return fmt

    # --- 3. Formato del médico de la receta con is_authorized=True ---
    doctor_id = getattr(prescription, "doctor_id", None)
    if doctor_id is not None:
        fmt_doctor = (
            PrescriptionFormat.all_objects.filter(
                tenant=tenant,
                doctor_id=doctor_id,
                is_authorized=True,
                is_active=True,
                deleted_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )
        if fmt_doctor is not None:
            return fmt_doctor

    # --- 4. Formato default del tenant ---
    fmt_default = (
        PrescriptionFormat.all_objects.filter(
            tenant=tenant,
            is_default=True,
            is_active=True,
            deleted_at__isnull=True,
        )
        .first()
    )
    if fmt_default is not None:
        return fmt_default

    # --- 5. Objeto en memoria con defaults de fábrica ---
    fmt_factory = PrescriptionFormat.__new__(PrescriptionFormat)
    fmt_factory.base_layout = "standard"
    fmt_factory.accent_color = "#9A7B1E"
    fmt_factory.font = "helvetica"
    fmt_factory.sections = {}
    fmt_factory.letterhead_mode = "digital"
    fmt_factory.is_default = False
    fmt_factory.is_authorized = False
    fmt_factory.doctor_id = None
    return fmt_factory


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
