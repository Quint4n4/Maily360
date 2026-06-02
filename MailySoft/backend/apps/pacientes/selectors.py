"""
Selectors de la app pacientes.

Lecturas/queries: NUNCA modifican datos. Las vistas y servicios que necesiten
leer pacientes deben pasar por aquí, nunca hacer queries directas en views.

El TenantManager (objects) filtra automáticamente por el tenant activo en el
thread-local cuando context_active=True. En el contexto de un request HTTP, esto
garantiza que nunca se lean datos de otra clínica.
"""

import uuid
from typing import Optional

from django.db.models import Q, QuerySet

from apps.pacientes.models import Patient


def patient_get(*, patient_id: uuid.UUID) -> Patient:
    """Retorna un paciente por su UUID.

    Usa el TenantManager (filtra por tenant del contexto activo).
    Lanza Patient.DoesNotExist si no existe o no pertenece al tenant activo.
    Las vistas deben capturar DoesNotExist y devolver 404.

    Args:
        patient_id: UUID del paciente a recuperar.

    Returns:
        Instancia de Patient.

    Raises:
        Patient.DoesNotExist: si el paciente no existe en el tenant activo.
    """
    return Patient.objects.get(id=patient_id)


def patient_list(*, search: Optional[str] = "") -> QuerySet[Patient]:
    """Retorna el QuerySet de pacientes activos del tenant actual.

    Si se provee `search`, filtra por nombre, apellidos, teléfono o número
    de expediente usando OR icontains. La paginación la aplica la vista.

    Usa select_related en tenant para evitar N+1 si se serializa el tenant.
    Ordena por -created_at (más reciente primero).

    Args:
        search: término de búsqueda libre. Si es vacío o None, retorna todos
                los pacientes activos del tenant.

    Returns:
        QuerySet[Patient] filtrado y ordenado. Sin paginar (responsabilidad de la vista).
    """
    # FIX-B5: eliminado select_related("tenant") — el OutputSerializer no serializa
    # campos del tenant, por lo que era un JOIN innecesario.
    qs: QuerySet[Patient] = Patient.objects.filter(is_active=True)

    if search:
        # TODO(perf): cuando el volumen de pacientes supere ~50k por tenant,
        # considerar índice pg_trgm (GIN) sobre first_name + paternal_surname
        # para búsqueda full-text eficiente. Ver: CREATE EXTENSION IF NOT EXISTS pg_trgm.
        qs = qs.filter(
            Q(first_name__icontains=search)
            | Q(paternal_surname__icontains=search)
            | Q(maternal_surname__icontains=search)
            | Q(phone__icontains=search)
            | Q(record_number__icontains=search)
        )

    return qs.order_by("-created_at")
