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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, IntegerField, Max, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.timezone import now

from apps.agenda.models import Appointment
from apps.audit.models import AuditLog
from apps.authn.models import User
from apps.pacientes.models import Patient
from apps.tenancy.models import Plan, Tenant, TenantMembership, TenantSubscription


def platform_clinicas_list(
    *,
    search: str = "",
    status: str | None = None,
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
    total_platform_staff = User.objects.filter(is_active=True, is_platform_staff=True).count()

    # Pacientes cross-tenant (all_objects para bypassar TenantManager).
    total_pacientes = Patient.all_objects.filter(deleted_at__isnull=True).count()

    # Últimas 5 clínicas creadas.
    ultimas_clinicas: list[dict[str, Any]] = list(
        tenant_qs.order_by("-created_at").values("id", "name", "status", "created_at")[:5]
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
        ).filter(Q(email__icontains=search) | Q(full_name_search__icontains=search))

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
    ultima_qs = Appointment.all_objects.filter(tenant=tenant).aggregate(ultima=Max("created_at"))
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


def platform_audit_log_list(
    *,
    tenant_id: uuid.UUID | None = None,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str = "",
) -> "QuerySet[AuditLog]":
    """Lista la bitácora de auditoría cross-tenant para el panel de plataforma.

    Args:
        tenant_id: filtra por clínica exacta. None = sin filtro (todas las clínicas).
        action: filtra por ActionType exacto. None/vacío = sin filtro.
        actor_id: filtra por el usuario que realizó la acción. None = sin filtro.
        date_from: filtra created_at >= date_from (datetime ISO completo).
        date_to: filtra created_at <= date_to (datetime ISO completo).
        search: icontains sobre description o el email del actor. Vacío = sin filtro.

    Returns:
        QuerySet de AuditLog (Model.all_objects, cross-tenant) con
        select_related("actor", "tenant"), ordenado por -created_at.
    """
    qs = AuditLog.all_objects.select_related("actor", "tenant")

    if tenant_id is not None:
        qs = qs.filter(tenant_id=tenant_id)

    if action:
        qs = qs.filter(action=action)

    if actor_id is not None:
        qs = qs.filter(actor_id=actor_id)

    if date_from is not None:
        qs = qs.filter(created_at__gte=date_from)

    if date_to is not None:
        qs = qs.filter(created_at__lte=date_to)

    if search:
        qs = qs.filter(Q(description__icontains=search) | Q(actor__email__icontains=search))

    return qs.order_by("-created_at")


# ---------------------------------------------------------------------------
# Suscripciones y planes (Fase 3)
# ---------------------------------------------------------------------------

#: Ventana de "por vencer": vence en <= N días (pero todavía no venció).
_ALERTA_DIAS_POR_VENCER: int = 7


def platform_plan_list() -> "QuerySet[Plan]":
    """Lista TODOS los planes activos e inactivos, ordenados por `order`.

    Sin paginar (contrato fijo: GET /plataforma/planes/ devuelve una lista
    simple, no un objeto paginado) — el catálogo de planes es pequeño y
    completo por diseño (unas pocas filas).

    Fase 3.1: este selector SIEMPRE incluye planes inactivos a propósito — el
    portal de plataforma los muestra atenuados (el dueño necesita verlos para
    poder reactivarlos). No confundir con la asignación de suscripción
    (tenant_subscription_set), que sí rechaza explícitamente planes inactivos;
    esa validación vive en el service y es independiente de este selector.
    """
    return Plan.objects.all().order_by("order", "name")


def plan_get(*, plan_id: uuid.UUID) -> Plan:
    """Obtiene un Plan por id para uso en servicios de escritura (Fase 3.1).

    Plan es catálogo global (no TenantAware), así que no hay aislamiento por
    tenant que aplicar aquí — pero se centraliza en un selector de todos modos
    para que ningún service/vista haga `Plan.objects.get(...)` inline (patrón
    consistente con el resto del proyecto) y para tener un único punto de
    cambio si en el futuro se agrega soft-delete u otra condición de lectura.

    Args:
        plan_id: UUID del plan a buscar.

    Returns:
        La instancia Plan.

    Raises:
        Plan.DoesNotExist: si no existe un plan con ese id.
    """
    return Plan.objects.get(id=plan_id)


def _calcular_alerta(
    *,
    tenant_status: str,
    trial_ends_at: datetime | None,
    current_period_end: date | None,
    reference_now: datetime | None = None,
    reference_today: date | None = None,
) -> str | None:
    """Calcula la alerta de vencimiento de una fila tenant+suscripción.

    Se resuelve en Python (no en SQL) a propósito: mezcla una regla sobre
    datetime (trial_ends_at, con hora) con otra sobre date (current_period_end,
    solo fecha) y una prioridad vencido > por_vencer entre dos fuentes
    independientes (trial vs. suscripción) — expresarlo como Case/When anidado
    en el ORM sería menos legible y más difícil de testear que esta función
    pura, sin perder rendimiento real (el volumen de tenants es bajo y no hay
    N+1: los selectors ya precargan todo con una query).

    Prioridad: vencido > por_vencer. Un tenant puede tener AMBAS condiciones
    (trial vencido Y suscripción vencida) pero el contrato solo permite un
    valor: se prioriza "trial_vencido" sobre "periodo_vencido" porque el
    trial es lógicamente anterior/más urgente que una suscripción ya asignada.

    Args:
        tenant_status: Tenant.Status del tenant (trial/active/suspended).
        trial_ends_at: fecha/hora de fin de trial (None si no aplica).
        current_period_end: fecha de fin del periodo de suscripción (None si
            el tenant no tiene TenantSubscription).
        reference_now: instante de referencia para "ahora" (inyectable en tests).
        reference_today: fecha de referencia para "hoy" (inyectable en tests).

    Returns:
        Uno de "trial_vencido" | "trial_por_vencer" | "periodo_vencido" |
        "periodo_por_vencer" | None.
    """
    reference_now = reference_now or now()
    reference_today = reference_today or reference_now.date()

    trial_vencido = False
    trial_por_vencer = False
    if tenant_status == Tenant.Status.TRIAL and trial_ends_at is not None:
        if trial_ends_at < reference_now:
            trial_vencido = True
        elif trial_ends_at <= reference_now + timedelta(days=_ALERTA_DIAS_POR_VENCER):
            trial_por_vencer = True

    periodo_vencido = False
    periodo_por_vencer = False
    if current_period_end is not None:
        if current_period_end < reference_today:
            periodo_vencido = True
        elif current_period_end <= reference_today + timedelta(days=_ALERTA_DIAS_POR_VENCER):
            periodo_por_vencer = True

    # Prioridad: vencido > por_vencer; trial > periodo (dentro de cada nivel).
    if trial_vencido:
        return "trial_vencido"
    if periodo_vencido:
        return "periodo_vencido"
    if trial_por_vencer:
        return "trial_por_vencer"
    if periodo_por_vencer:
        return "periodo_por_vencer"
    return None


def platform_subscription_row_build(
    *,
    tenant: Tenant,
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    """Construye el dict de una fila del listado de suscripciones para un tenant.

    `tenant` debe venir con `.subscription` precargado por select_related
    (falla silenciosa a None si no existe: OneToOne inverso ausente) para no
    generar una query adicional por fila.

    Args:
        tenant: instancia de Tenant, idealmente con select_related("subscription__plan").
        reference_now: instante de referencia para el cálculo de alerta (tests).

    Returns:
        Dict con el contrato fijo de una fila de suscripción.
    """
    try:
        subscription: TenantSubscription | None = tenant.subscription
    except TenantSubscription.DoesNotExist:
        subscription = None

    alerta = _calcular_alerta(
        tenant_status=tenant.status,
        trial_ends_at=tenant.trial_ends_at,
        current_period_end=subscription.current_period_end if subscription else None,
        reference_now=reference_now,
    )

    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "tenant_status": tenant.status,
        "trial_ends_at": tenant.trial_ends_at,
        "plan_id": subscription.plan_id if subscription else None,
        "plan_name": subscription.plan.name if subscription else None,
        "plan_slug": subscription.plan.slug if subscription else None,
        "billing_cycle": subscription.billing_cycle if subscription else None,
        "current_period_end": subscription.current_period_end if subscription else None,
        "plan_price_monthly": subscription.plan.price_monthly if subscription else None,
        "alerta": alerta,
    }


def platform_subscriptions_list(
    *,
    search: str = "",
    plan_id: uuid.UUID | None = None,
    alerta: str | None = None,
    reference_now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Lista una fila por Tenant (todas las clínicas, con o sin suscripción).

    "Left join" lógico: se recorren TODOS los tenants (Tenant.objects, no es
    TenantAware) con select_related de su suscripción+plan (OneToOne inverso,
    una sola query, sin N+1); los tenants sin TenantSubscription simplemente
    devuelven None en los campos de plan.

    El filtro `alerta` se aplica DESPUÉS de calcular la alerta en Python
    (no se puede empujar a SQL sin duplicar la lógica de `_calcular_alerta`);
    el volumen de tenants es bajo (catálogo de clínicas de la plataforma, no
    una tabla de negocio de alto volumen), así que evaluarlo en Python es la
    opción más simple y testeable sin costo real de performance.

    Args:
        search: icontains sobre nombre/slug del tenant. Vacío = sin filtro.
        plan_id: filtra por plan asignado exacto. None = sin filtro.
        alerta: "vencidas" (solo alertas *_vencido) | "por_vencer" (solo
            alertas *_por_vencer) | None (sin filtro, todas las filas).
        reference_now: instante de referencia para el cálculo de alerta (tests).

    Returns:
        Lista de dicts (contrato fijo), ordenada por nombre de tenant.
    """
    qs = Tenant.objects.select_related("subscription", "subscription__plan").order_by("name")

    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(slug__icontains=search))

    if plan_id is not None:
        qs = qs.filter(subscription__plan_id=plan_id)

    rows = [
        platform_subscription_row_build(tenant=tenant, reference_now=reference_now) for tenant in qs
    ]

    if alerta == "vencidas":
        rows = [r for r in rows if r["alerta"] in ("trial_vencido", "periodo_vencido")]
    elif alerta == "por_vencer":
        rows = [r for r in rows if r["alerta"] in ("trial_por_vencer", "periodo_por_vencer")]

    return rows


def platform_subscriptions_resumen(*, reference_now: datetime | None = None) -> dict[str, Any]:
    """Resumen agregado de suscripciones para el panel de plataforma.

    Returns:
        Dict con:
          - total_clinicas: int (todas las clínicas, tengan o no suscripción).
          - sin_plan: int (tenants sin TenantSubscription).
          - por_plan: list de {plan_id, plan_name, count}.
          - alertas: dict con los 4 conteos de alerta.
          - mrr_estimado: Decimal — suma de price_monthly de suscripciones
            cuyo TENANT tiene status=active (no cuenta trial ni suspended,
            aunque tengan un plan asignado: MRR real es solo ingreso activo).
    """
    total_clinicas = Tenant.objects.count()
    sin_plan = Tenant.objects.filter(subscription__isnull=True).count()

    por_plan_qs = (
        TenantSubscription.objects.values("plan_id", "plan__name")
        .annotate(count=Count("id"))
        .order_by("plan__order", "plan__name")
    )
    por_plan = [
        {"plan_id": row["plan_id"], "plan_name": row["plan__name"], "count": row["count"]}
        for row in por_plan_qs
    ]

    mrr_estimado: Decimal = TenantSubscription.objects.filter(
        tenant__status=Tenant.Status.ACTIVE
    ).aggregate(total=Sum("plan__price_monthly"))["total"] or Decimal("0")

    rows = platform_subscriptions_list(reference_now=reference_now)
    alertas = {
        "trial_vencido": sum(1 for r in rows if r["alerta"] == "trial_vencido"),
        "trial_por_vencer": sum(1 for r in rows if r["alerta"] == "trial_por_vencer"),
        "periodo_vencido": sum(1 for r in rows if r["alerta"] == "periodo_vencido"),
        "periodo_por_vencer": sum(1 for r in rows if r["alerta"] == "periodo_por_vencer"),
    }

    return {
        "total_clinicas": total_clinicas,
        "sin_plan": sin_plan,
        "por_plan": por_plan,
        "alertas": alertas,
        "mrr_estimado": mrr_estimado,
    }
