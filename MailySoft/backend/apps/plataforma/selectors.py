"""
Selectors del panel interno de plataforma (solo lectura, cross-tenant).

REGLA CRÍTICA: SIEMPRE usar Model.all_objects (nunca Model.objects).
  - Model.objects es el TenantManager, que filtra por el tenant del request.
  - En el contexto de plataforma NO hay tenant en el GUC, por lo que
    current_tenant_id() IS NULL → RLS abre todas las filas. Pero el
    TenantManager tiene su propia lógica Python adicional:
    si is_tenant_context_active() es True y el tenant es None, devuelve qs.none().
  - Como PlatformAPIView NO setea el tenant en el thread-local, get_current_tenant()
    devolverá None → TenantManager.get_queryset() retornaría qs.none().
  - Por eso usamos all_objects, que bypasea el TenantManager completamente.
  - La protección real de aislamiento viene de PostgreSQL RLS + el permiso
    IsPlatformStaff, no del TenantManager.
"""

import uuid
from typing import Any, Optional

from django.db.models import Count, IntegerField, Max, OuterRef, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce

from apps.agenda.models import Appointment
from apps.authn.models import User
from apps.pacientes.models import Patient
from apps.tenancy.models import Tenant, TenantMembership


def platform_clinicas_list(
    *,
    search: str = "",
    status: Optional[str] = None,
) -> "QuerySet[Tenant]":
    """Lista todas las clínicas anotadas con conteos de miembros y pacientes.

    Args:
        search: Filtro por name o slug (icontains). Vacío = sin filtro.
        status: Filtro por Tenant.Status exacto. None = sin filtro.

    Returns:
        QuerySet de Tenant anotado con:
          - member_count: número de TenantMembership activas (is_active=True).
          - patient_count: número de Patient (no soft-deleted) en el tenant.

    Ordena por -created_at (más recientes primero).
    """
    # Subquery para contar miembros activos por tenant.
    active_members_sq = (
        TenantMembership.objects.filter(
            tenant=OuterRef("pk"),
            is_active=True,
            deleted_at__isnull=True,
        )
        .values("tenant")
        .annotate(cnt=Count("id"))
        .values("cnt")
    )

    # Subquery para contar pacientes (no soft-deleted) por tenant.
    # Se usa all_objects porque el TenantManager devolvería qs.none() sin GUC.
    patients_sq = (
        Patient.all_objects.filter(
            tenant=OuterRef("pk"),
            deleted_at__isnull=True,
        )
        .values("tenant")
        .annotate(cnt=Count("id"))
        .values("cnt")
    )

    # Coalesce a 0: una Subquery sin filas devuelve NULL, no 0. Sin esto, las
    # clínicas sin miembros/pacientes saldrían con null y romperían el frontend.
    qs = Tenant.objects.annotate(
        member_count=Coalesce(Subquery(active_members_sq), Value(0), output_field=IntegerField()),
        patient_count=Coalesce(Subquery(patients_sq), Value(0), output_field=IntegerField()),
    )

    if status:
        qs = qs.filter(status=status)

    if search:
        from django.db.models import Q

        qs = qs.filter(Q(name__icontains=search) | Q(slug__icontains=search))

    return qs.order_by("-created_at")


def platform_dashboard_metrics() -> dict[str, Any]:
    """Conteos globales para el dashboard del panel interno.

    Returns:
        Dict con:
          - total_clinicas: int
          - clinicas_por_estado: dict {trial: int, active: int, suspended: int}
          - total_usuarios: int (todos los User activos)
          - total_platform_staff: int (solo is_platform_staff=True)
          - total_pacientes: int (cross-tenant, no soft-deleted)
          - ultimas_clinicas: list de {id, name, status, created_at} (5 más recientes)
    """
    # Conteos de tenants por estado.
    tenant_qs = Tenant.objects.all()
    total_clinicas = tenant_qs.count()
    por_estado = {s: 0 for s in Tenant.Status.values}
    for row in tenant_qs.values("status").annotate(cnt=Count("id")):
        por_estado[row["status"]] = row["cnt"]

    # Usuarios activos e inactivos (todos).
    total_usuarios = User.objects.filter(is_active=True).count()
    total_platform_staff = User.objects.filter(
        is_active=True, is_platform_staff=True
    ).count()

    # Pacientes cross-tenant (all_objects para bypassar TenantManager).
    total_pacientes = Patient.all_objects.filter(deleted_at__isnull=True).count()

    # Últimas 5 clínicas creadas.
    ultimas_clinicas: list[dict[str, Any]] = list(
        tenant_qs.order_by("-created_at").values("id", "name", "status", "created_at")[
            :5
        ]
    )

    return {
        "total_clinicas": total_clinicas,
        "clinicas_por_estado": por_estado,
        "total_usuarios": total_usuarios,
        "total_platform_staff": total_platform_staff,
        "total_pacientes": total_pacientes,
        "ultimas_clinicas": ultimas_clinicas,
    }


def platform_staff_list(*, search: str = "") -> "QuerySet[User]":
    """Lista todos los usuarios con is_platform_staff=True.

    Args:
        search: Filtro por email o nombre completo (icontains). Vacío = sin filtro.

    Returns:
        QuerySet de User (is_platform_staff=True), ordenado por email.
    """
    qs = User.objects.filter(is_platform_staff=True)

    if search:
        from django.db.models import Q, Value
        from django.db.models.functions import Concat

        qs = qs.annotate(
            full_name_search=Concat("first_name", Value(" "), "last_name"),
        ).filter(
            Q(email__icontains=search)
            | Q(full_name_search__icontains=search)
        )

    return qs.order_by("email")


def platform_clinica_detail(*, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Ficha de detalle de una clínica para el panel interno de plataforma.

    Realiza todas las queries necesarias para construir el dict de detalle sin
    N+1: una query para el tenant, una para los miembros, y subqueries para
    los conteos. Usar all_objects en todos los modelos TenantAware (cross-tenant).

    Args:
        tenant_id: UUID del tenant a consultar.

    Returns:
        Dict con:
          - id, name, slug, status, trial_ends_at, created_at
          - member_count: int (membresías activas)
          - patient_count: int (pacientes no soft-deleted)
          - appointment_count: int (todas las citas, incluyendo canceladas)
          - ultima_actividad: datetime | None (max created_at de Appointment del tenant)
          - members: list de dicts con {id, full_name, email, role, role_display, is_active}

    Raises:
        Tenant.DoesNotExist: si no existe un tenant con ese id.
                             La vista captura esto y devuelve 404.
    """
    # Lanza DoesNotExist si no existe → la vista lo convierte en 404.
    # Usamos Tenant.objects (no all_objects) porque Tenant NO es TenantAware;
    # hereda de BaseModel directamente. Tenant.objects es el Manager estándar.
    tenant = Tenant.objects.get(id=tenant_id)

    # Conteo de miembros activos (no soft-deleted).
    member_count: int = TenantMembership.objects.filter(
        tenant=tenant,
        is_active=True,
        deleted_at__isnull=True,
    ).count()

    # Conteo de pacientes no soft-deleted (cross-tenant → all_objects).
    patient_count: int = Patient.all_objects.filter(
        tenant=tenant,
        deleted_at__isnull=True,
    ).count()

    # Conteo de citas totales (incluyendo canceladas, cross-tenant → all_objects).
    appointment_count: int = Appointment.all_objects.filter(
        tenant=tenant,
    ).count()

    # Última actividad: max created_at de Appointment del tenant.
    ultima_qs = Appointment.all_objects.filter(tenant=tenant).aggregate(
        ultima=Max("created_at")
    )
    ultima_actividad = ultima_qs["ultima"]  # None si no hay citas

    # Lista de miembros con select_related para evitar N+1 al acceder a user.
    memberships = (
        TenantMembership.objects.filter(
            tenant=tenant,
            deleted_at__isnull=True,
        )
        .select_related("user")
        .order_by("created_at")
    )

    role_display_map = dict(TenantMembership.Role.choices)

    members: list[dict[str, Any]] = [
        {
            "id": str(m.id),
            "full_name": f"{m.user.first_name} {m.user.last_name}".strip(),
            "email": m.user.email,
            "role": m.role,
            "role_display": role_display_map.get(m.role, m.role),
            "is_active": m.is_active,
        }
        for m in memberships
    ]

    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "status": tenant.status,
        "status_display": tenant.get_status_display(),
        "trial_ends_at": tenant.trial_ends_at,
        "created_at": tenant.created_at,
        "member_count": member_count,
        "patient_count": patient_count,
        "appointment_count": appointment_count,
        "ultima_actividad": ultima_actividad,
        "members": members,
    }
