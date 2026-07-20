"""
Resolución de la sucursal activa y del alcance de sucursales del usuario.

IMPORTANTE — lo que este módulo NO es (docs/design/sucursales-plan-implementacion.md,
principio 2): NO es una barrera de seguridad de base de datos. El aislamiento
duro entre negocios sigue siendo por tenant_id vía RLS de PostgreSQL, sin
cambios. La sucursal es un filtro OPERATIVO de segunda dimensión: scoping en
la capa de servicio/permiso para que cada usuario vea/opere solo en las sedes
que le corresponden DENTRO de su propio tenant. Un bug aquí NUNCA expone datos
de OTRO tenant (RLS lo sigue garantizando); en el peor caso expondría datos de
OTRA SUCURSAL del MISMO negocio — aceptado por diseño (ver "Decisiones
tomadas" en docs/design/sucursales-arquitectura-analisis.md).

Funciones:
    allowed_sucursales(*, user, tenant) -> QuerySet[Sucursal]
        Sucursales activas que el usuario puede operar.
          - owner: SIEMPRE todas (es el dueño del negocio).
          - Cualquier otro rol (admin incluido): solo las asignadas vía
            MembershipSucursal. Un "admin de sucursal" es un admin con UNA
            sede asignada; un "admin de negocio" se logra asignándole TODAS
            las sedes explícitamente — ya no hay atajo automático por rol.
          - Fallback anti-lockout: si el usuario no tiene NINGUNA fila de
            MembershipSucursal (nunca se le asignó nada) y el tenant SÍ
            tiene sucursales, se le da solo la sucursal `is_default=True`
            (fail-closed: nunca "todas" por omisión).

    resolve_active_sucursal(request) -> Sucursal | None
        Lee el header X-Sucursal-Id del request. Si no viene, retorna None
        (sin filtro = comportamiento retro-compatible, todas las sucursales).
        Si viene, valida contra allowed_sucursales(); si el usuario no tiene
        acceso a esa sede, levanta PermissionDenied (403) — DRF lo traduce
        automáticamente a una respuesta HTTP sin que la vista lo capture.

    resolve_write_sucursal(*, tenant, user, sucursal_id, consultorio_sucursal_id,
                            active_sucursal_id) -> Sucursal | None
        Resuelve la sucursal a asignar en una ESCRITURA (cita, cargo, pago,
        cotización, bloqueo de agenda, horario laboral) con precedencia fija
        (multi-sede — Fase 2). Usada por apps.agenda.services,
        apps.personal.services, apps.finanzas.views y
        apps.expediente.views_calendarizacion para no duplicar la lógica de
        resolución en cada módulo.

        Autorización (cierre de hueco — admin de sucursal): la sede
        RESUELTA (por cualquiera de las 4 vías de precedencia, incluida la
        predeterminada del tenant) se valida contra `allowed_sucursales` del
        `user`. Un admin de Centro no puede crear un cobro/cita en Norte, ni
        mandando `sucursal_id` explícito en el body ni omitiendo el header y
        cayendo por default en una sede que no es la suya.

    actor_sucursal_ids(*, user, tenant) -> set[uuid.UUID] | None
        Variante "dura" de `allowed_sucursales` para AUTORIZACIÓN (no para
        selectores de UI): mismo criterio de alcance por rol/membresía, pero
        SIN excluir sedes desactivadas. Un admin acotado a una sede sigue
        cubriendo esa sede en esta función aunque la hayan desactivado — así
        `sucursal_scope_ids` no puede inferir "alcance total" solo porque el
        denominador de sedes ACTIVAS bajó (ver docs/design/sucursales-
        hallazgos-seguridad.md, Clúster B), y `SucursalDetailApi` puede seguir
        resolviendo (y reactivando) una sede ya desactivada que sí es suya.
        None = alcance total (owner).

    sucursal_scope_ids(request) -> list[uuid.UUID] | None
        Resuelve el ALCANCE de lectura para un LISTADO (cierra el hueco de
        seguridad de Objetivo A — ver docs/design/sucursales-plan-implementacion.md
        Fase 3): a diferencia de `resolve_active_sucursal` (que sin header
        devuelve None = "sin filtro"), esta función SIEMPRE acota:
          - Header presente y permitido → [esa_id] (si no permitido, 403 igual
            que `resolve_active_sucursal`).
          - Sin header, usuario con alcance PARCIAL (acotado a algunas sedes
            vía MembershipSucursal, o al fallback anti-lockout de la sede
            default) → lista de sus sedes permitidas (activas).
          - Sin header, usuario con alcance TOTAL (owner, o cualquier rol
            cuyas MembershipSucursal cubran TODAS las sedes del tenant —
            activas E INACTIVAS, vía `actor_sucursal_ids` — "admin de
            negocio") → None (vista consolidada, incluye legado sin
            sucursal). IMPORTANTE (Clúster B, corregido): el criterio de
            "cubre todo" YA NO cuenta contra el total de sedes ACTIVAS —
            desactivar/borrar una sede ajena NUNCA amplía el alcance de un
            admin acotado a las demás.
          - Tenant sin ninguna sucursal configurada (ni activa ni inactiva)
            → None (compatibilidad retro, no rompe tenants que nunca
            adoptaron multi-sede).
        Los selectors de listado filtran con `sucursal_id__in=[...]` cuando
        el resultado es una lista, o no filtran cuando es None.

Uso típico en una vista TenantAPIView (listado SIN scoping de seguridad,
solo conveniencia — ya no se usa así para listados expuestos a roles
acotados a sede; ver sucursal_scope_ids arriba):
    sucursal = resolve_active_sucursal(request)
    sucursal_id = sucursal.id if sucursal is not None else None
    qs = consultorio_list(sucursal_id=sucursal_id)

Uso recomendado para listados (cierra el hueco de seguridad):
    sucursal_ids = sucursal_scope_ids(request)
    qs = consultorio_list(sucursal_ids=sucursal_ids)
"""

import uuid
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from apps.clinica.models import MembershipSucursal, Sucursal
from apps.core.tenant_context import get_current_tenant
from apps.tenancy.models import TenantMembership

if TYPE_CHECKING:
    from apps.authn.models import User
    from apps.tenancy.models import Tenant

_SUCURSAL_HEADER = "X-Sucursal-Id"


def _resolve_membership(*, user: "User", tenant: "Tenant") -> TenantMembership | None:
    """Primera membresía activa de `user` en `tenant` (o None).

    Extraído de `allowed_sucursales` para que `actor_sucursal_ids` use
    exactamente el mismo criterio de resolución de membresía (misma
    ordenación `created_at`, mismo filtro `is_active`/`deleted_at`).
    """
    return (
        TenantMembership.objects.filter(
            user=user,
            tenant=tenant,
            is_active=True,
            deleted_at__isnull=True,
        )
        .order_by("created_at")
        .first()
    )


def allowed_sucursales(*, user: "User", tenant: "Tenant") -> QuerySet[Sucursal]:
    """Sucursales activas que el usuario puede operar dentro del tenant.

    - owner: SIEMPRE TODAS las sucursales activas del tenant (es el dueño del
      negocio; alcance de negocio completo sin necesidad de fila en
      MembershipSucursal).
    - Cualquier otro rol, INCLUIDO admin: solo las sucursales asignadas vía
      MembershipSucursal (activas). Esto es lo que habilita el rol
      "administrador de sucursal" (docs/design/sucursales-arquitectura-
      analisis.md §12): un admin con UNA sola sede asignada administra/ve
      SOLO esa sede. Un "admin de negocio" (como el dueño, pero sin
      facturación) se logra asignándole explícitamente TODAS las sedes.
    - Fallback anti-lockout (fail-closed): si el usuario NO tiene NINGUNA
      fila de MembershipSucursal (nunca se le asignó nada, ni una sola sede)
      y el tenant SÍ tiene sucursales configuradas, se le da acceso SOLO a
      la sucursal predeterminada (`is_default=True`) — nunca "todas" por
      omisión. Si tampoco hay una sucursal marcada como default, el
      resultado es vacío (el usuario necesita que se le asigne una sede
      explícitamente).

    Usa `all_objects` con un filtro EXPLÍCITO por `tenant_id` en lugar de
    depender del TenantManager (thread-local de tenant activo): esta función
    se llama también desde `MeApi` (apps.authn.views), que hereda de APIView
    (no de TenantAPIView) y por lo tanto NUNCA resuelve el tenant en el
    thread-local — depender del manager devolvería un queryset vacío ahí.

    Args:
        user:   Usuario autenticado (puede no tener membresía en `tenant`).
        tenant: Tenant (negocio) sobre el que se resuelve el alcance.

    Returns:
        QuerySet[Sucursal] activas del tenant que el usuario puede operar,
        ordenadas por nombre. Vacío si el usuario no tiene membresía activa
        en ese tenant, o si no tiene ninguna sede asignada y el tenant no
        tiene sucursal predeterminada.
    """
    membership = _resolve_membership(user=user, tenant=tenant)
    if membership is None:
        return Sucursal.all_objects.none()

    base: QuerySet[Sucursal] = Sucursal.all_objects.filter(
        tenant_id=tenant.id,
        is_active=True,
        deleted_at__isnull=True,
    )

    if membership.role == TenantMembership.Role.OWNER:
        return base.order_by("name")

    assigned_ids = list(
        MembershipSucursal.all_objects.filter(
            membership=membership,
            deleted_at__isnull=True,
        ).values_list("sucursal_id", flat=True)
    )

    if not assigned_ids:
        # Fallback anti-lockout: nunca se le asignó ninguna sede (ni fila en
        # MembershipSucursal) → solo la sucursal predeterminada del tenant,
        # NUNCA todas. Si el tenant tampoco tiene una sede default, vacío.
        return base.filter(is_default=True).order_by("name")

    return base.filter(id__in=assigned_ids).order_by("name")


def actor_sucursal_ids(*, user: "User", tenant: "Tenant") -> set[uuid.UUID] | None:
    """IDs de TODAS las sucursales (activas E INACTIVAS) que el actor puede operar.

    Autorización "dura" — hermana de `allowed_sucursales` con el MISMO
    criterio de rol/membresía (owner → todo; cualquier otro rol → solo lo
    asignado vía `MembershipSucursal`, con el mismo fallback anti-lockout a
    la sede default si no tiene ninguna asignación), pero que NO excluye
    sedes con `is_active=False` del lado del CANDIDATO. `allowed_sucursales`
    sí las excluye a propósito (es para selectores de UI: no ofrecer una
    sede que ya no opera). Esta función es para dos usos de AUTORIZACIÓN
    donde excluir inactivas sería incorrecto o peligroso:

    1. `sucursal_scope_ids` (Clúster B): decidir si un admin "cubre TODAS
       las sedes" no puede depender de cuántas sedes siguen ACTIVAS —
       si no, desactivar una sede ajena "adelgaza" el denominador y un
       admin acotado a las sedes restantes termina viéndose como si
       cubriera "todo", ganando lectura consolidada de la sede ajena
       desactivada (el bug real, verificado con PoC).
    2. `SucursalDetailApi` (Clúster C): un admin debe poder seguir
       resolviendo (GET/PATCH) — y por lo tanto reactivar — una sede
       PROPIA que él mismo desactivó. Si esta autorización excluyera
       sedes inactivas, nadie (ni el owner) podría reactivar una sede
       una vez desactivada.

    Args:
        user:   Usuario autenticado (puede no tener membresía en `tenant`).
        tenant: Tenant (negocio) sobre el que se resuelve el alcance.

    Returns:
        None si el actor es owner (alcance total, activas e inactivas).
        Set de UUIDs en cualquier otro caso — puede ser vacío (sin
        membresía activa en el tenant, o sin sede asignada y sin sede
        default configurada).
    """
    membership = _resolve_membership(user=user, tenant=tenant)
    if membership is None:
        return set()

    if membership.role == TenantMembership.Role.OWNER:
        return None

    base_ids: set[uuid.UUID] = set(
        Sucursal.all_objects.filter(
            tenant_id=tenant.id,
            deleted_at__isnull=True,
        ).values_list("id", flat=True)
    )

    assigned_ids: set[uuid.UUID] = set(
        MembershipSucursal.all_objects.filter(
            membership=membership,
            deleted_at__isnull=True,
        ).values_list("sucursal_id", flat=True)
    )

    if not assigned_ids:
        # Mismo fallback anti-lockout que allowed_sucursales, pero sin exigir
        # que la sede default esté activa (en la práctica siempre lo está:
        # sucursal_deactivate rechaza desactivar la default).
        return set(
            Sucursal.all_objects.filter(
                tenant_id=tenant.id, is_default=True, deleted_at__isnull=True
            ).values_list("id", flat=True)
        )

    # Intersección con base_ids: defensa en profundidad si una MembershipSucursal
    # quedara apuntando a una sucursal ya borrada-dura (deleted_at != None).
    return assigned_ids & base_ids


def resolve_active_sucursal(request: Request) -> Sucursal | None:
    """Resuelve la sucursal activa del request a partir del header X-Sucursal-Id.

    Retro-compatibilidad (principio 1 del plan): si el header no viene, NO se
    aplica ningún filtro de sucursal (equivalente a "todas las sucursales
    permitidas del usuario") — una clínica de una sola sede no manda el
    header nunca y no nota ningún cambio.

    Args:
        request: DRF request de una vista TenantAPIView (tenant ya resuelto
                 en el thread-local por TenantAPIView.check_permissions()).

    Returns:
        La Sucursal activa, o None si el header no vino en el request.

    Raises:
        rest_framework.exceptions.PermissionDenied: si el header trae un valor
            que no es un UUID válido, o si la sucursal indicada no existe o
            no está entre las permitidas del usuario (allowed_sucursales).
    """
    raw_id = (request.headers.get(_SUCURSAL_HEADER) or "").strip()
    if not raw_id:
        return None

    try:
        sucursal_id = uuid.UUID(raw_id)
    except ValueError as exc:
        raise PermissionDenied(
            "El identificador de sucursal (X-Sucursal-Id) no es un UUID válido."
        ) from exc

    tenant = get_current_tenant()
    if tenant is None:
        raise PermissionDenied("No se encontró un tenant activo para resolver la sucursal.")

    sucursal = allowed_sucursales(user=request.user, tenant=tenant).filter(id=sucursal_id).first()
    if sucursal is None:
        raise PermissionDenied(
            "No tienes acceso a la sucursal indicada en X-Sucursal-Id, o no existe."
        )
    return sucursal


def resolve_write_sucursal(
    *,
    tenant: "Tenant",
    user: "User",
    sucursal_id: uuid.UUID | None,
    consultorio_sucursal_id: uuid.UUID | None = None,
    active_sucursal_id: uuid.UUID | None = None,
) -> Sucursal | None:
    """Resuelve la sucursal a asignar en una escritura (cita, bloqueo, horario).

    Centraliza la precedencia de resolución de sucursal (multi-sede — Fase 2)
    para que apps.agenda.services, apps.personal.services, apps.finanzas.views
    y apps.expediente.views_calendarizacion no la dupliquen.

    Precedencia:
      1. `sucursal_id` — explícito, lo que mandó el cliente en el body.
      2. `consultorio_sucursal_id` — la sede del consultorio asignado al
         registro (si lo hay). Tiene prioridad sobre la sede activa del
         header porque el consultorio ya "ancla" una sede concreta; usarla
         evita un choque de coherencia consultorio↔sucursal más adelante.
      3. `active_sucursal_id` — la sucursal activa del request (header
         X-Sucursal-Id), que la vista resuelve con `resolve_active_sucursal`
         y pasa al service.
      4. La sucursal predeterminada (`is_default=True`) del tenant.

    Usa `all_objects` con un filtro EXPLÍCITO por `tenant_id` (no el
    TenantManager/thread-local): esta función la llaman servicios que pueden
    ejecutarse desde Celery/management commands sin contexto de request.

    Si un candidato (`consultorio_sucursal_id` o `active_sucursal_id`) no
    corresponde a una sucursal válida del tenant, se ignora silenciosamente y
    se prueba el siguiente nivel de precedencia — ya fueron validados aguas
    arriba (el consultorio es del mismo tenant; `active_sucursal_id` ya pasó
    por `resolve_active_sucursal`). Solo `sucursal_id` EXPLÍCITO levanta error
    inmediato si no es válido, porque es un dato que el cliente controla
    directamente y merece un mensaje claro.

    AUTORIZACIÓN (cierre de hueco — admin de sucursal): una vez resuelta la
    sede candidata por CUALQUIERA de las 4 vías de precedencia (incluida la
    predeterminada del tenant), se valida contra `allowed_sucursales(user,
    tenant)`. Si no está entre las permitidas del actor, se rechaza. Esto
    cierra dos rutas de fuga que `resolve_active_sucursal` NO cubre por sí
    solo (ese solo valida el header, no el body ni el fallback):
      - Un cliente que manda `sucursal_id` EXPLÍCITO en el body de una sede
        ajena (sin pasar por el header X-Sucursal-Id).
      - Un actor acotado a una sede NO default que omite el header: sin este
        chequeo, caería silenciosamente en la sede predeterminada del
        tenant, que puede no ser la suya.

    COMPATIBILIDAD RETRO (principio 1 del plan de sucursales): si el tenant no
    tiene NINGUNA sucursal (ni siquiera una predeterminada) — p. ej. un tenant
    recién creado, o uno anterior a la Fase 1 sobre el que aún no corrió el
    backfill — se retorna `None` en vez de levantar un error. Todos los FK
    `sucursal` de agenda/personal nacen NULLABLE precisamente para esto: un
    negocio que todavía no adopta multi-sede sigue operando exactamente igual
    que antes de la Fase 2, sin sucursal en sus citas/horarios/eventos. Como
    no hay sucursal resuelta, el chequeo de autorización no aplica.

    Args:
        tenant:                   Tenant (negocio) del registro que se crea/edita.
        user:                      Usuario que realiza la escritura (auditoría y
                                   autorización de sede).
        sucursal_id:               Sucursal explícita indicada por el cliente, o None.
        consultorio_sucursal_id:   Sucursal del consultorio asignado, o None.
        active_sucursal_id:        Sucursal activa del request (header), o None.

    Returns:
        Instancia Sucursal, o None si no se pudo resolver ninguna (tenant sin
        sucursales configuradas — compatibilidad retro).

    Raises:
        ValidationError: si `sucursal_id` fue indicado EXPLÍCITAMENTE pero no
            existe en este tenant, o si la sede resuelta (por cualquier vía)
            no está entre las sucursales permitidas del `user`.
    """
    resolved: Sucursal | None

    if sucursal_id is not None:
        resolved = Sucursal.all_objects.filter(
            id=sucursal_id, tenant_id=tenant.id, deleted_at__isnull=True
        ).first()
        if resolved is None:
            raise ValidationError("Sucursal no encontrada en esta clínica.")
    elif (
        consultorio_sucursal_id is not None
        and (
            candidate := Sucursal.all_objects.filter(
                id=consultorio_sucursal_id, tenant_id=tenant.id, deleted_at__isnull=True
            ).first()
        )
        is not None
    ):
        resolved = candidate
    elif (
        active_sucursal_id is not None
        and (
            candidate := Sucursal.all_objects.filter(
                id=active_sucursal_id, tenant_id=tenant.id, deleted_at__isnull=True
            ).first()
        )
        is not None
    ):
        resolved = candidate
    else:
        resolved = Sucursal.all_objects.filter(
            tenant_id=tenant.id, is_default=True, deleted_at__isnull=True
        ).first()

    if resolved is not None and not (
        allowed_sucursales(user=user, tenant=tenant).filter(id=resolved.id).exists()
    ):
        raise ValidationError("No tienes acceso a esa sucursal para esta operación.")

    return resolved


def sucursal_scope_ids(request: Request) -> list[uuid.UUID] | None:
    """Resuelve el alcance de sucursales para un LISTADO (huella de seguridad).

    A diferencia de `resolve_active_sucursal` — donde "sin header" significaba
    "sin filtro, todas las sedes" incluso para un usuario acotado a una sola
    sede — esta función SIEMPRE acota a lo que el usuario puede ver, con o sin
    header. Objetivo A del plan de sucursales (Fase 3): antes de esto, un
    usuario limitado a la Sucursal A podía ver datos de la Sucursal B con solo
    omitir `X-Sucursal-Id`.

    Precedencia:
      1. Header `X-Sucursal-Id` presente y permitido → `[esa_id]`. Si el
         header trae una sede no permitida (o inválida), levanta
         `PermissionDenied` (403) — delegado en `resolve_active_sucursal`.
      2. Sin header, alcance PARCIAL (el usuario tiene menos sedes permitidas
         que el total de sedes activas del tenant, vía `MembershipSucursal`,
         o cae en el fallback anti-lockout de la sede default) → lista de
         sus ids permitidos. Puede ser `[]` si no tiene ninguna membresía
         activa (el filtro `sucursal_id__in=[]` no devuelve nada).
      3. Sin header, alcance TOTAL (owner, o cualquier rol NO owner cuyas
         `MembershipSucursal` cubren TODAS las sedes del tenant — activas E
         INACTIVAS, vía `actor_sucursal_ids` — "admin de negocio") → `None`
         (vista consolidada: incluye legado con `sucursal IS NULL`).
      4. Tenant sin ninguna sucursal configurada (ni activa ni inactiva) →
         `None` (compatibilidad retro; el tenant nunca adoptó multi-sede).

    Args:
        request: DRF request de una vista TenantAPIView (tenant ya resuelto
                 en el thread-local por TenantAPIView.check_permissions()).

    Returns:
        Lista de UUIDs de sucursal a la que acotar el listado, o None si no
        debe aplicarse ningún filtro (vista consolidada o tenant sin sedes).

    Raises:
        rest_framework.exceptions.PermissionDenied: mismos casos que
            `resolve_active_sucursal` (header inválido o sede no permitida),
            y si no hay tenant activo para resolver el alcance.
    """
    sucursal = resolve_active_sucursal(request)
    if sucursal is not None:
        return [sucursal.id]

    tenant = get_current_tenant()
    if tenant is None:
        raise PermissionDenied("No se encontró un tenant activo para resolver la sucursal.")

    actor_ids = actor_sucursal_ids(user=request.user, tenant=tenant)
    if actor_ids is None:
        # owner: alcance total siempre, sin importar sedes desactivadas.
        return None

    total_ids: set[uuid.UUID] = set(
        Sucursal.all_objects.filter(tenant_id=tenant.id, deleted_at__isnull=True).values_list(
            "id", flat=True
        )
    )

    if not total_ids:
        # Tenant sin NINGUNA sucursal (ni activa ni inactiva): compatibilidad
        # retro, nunca adoptó multi-sede.
        return None

    if actor_ids.issuperset(total_ids):
        # El actor tiene MembershipSucursal para TODAS las sedes del tenant,
        # incluidas las inactivas ("admin de negocio"): vista consolidada.
        # CORREGIDO (Clúster B): antes se comparaba contra el conteo de
        # sedes ACTIVAS, así que desactivar una sede ajena "adelgazaba" el
        # denominador y ampliaba por accidente el alcance de un admin
        # acotado a las sedes restantes. Ahora el denominador es SIEMPRE
        # el total real de sedes del tenant (activas e inactivas).
        return None

    # Alcance PARCIAL: lista explícita de las sedes ACTIVAS permitidas (las
    # inactivas no aportan datos "nuevos" de lectura para reportes/listados
    # de este actor — solo importan para decidir arriba si cubre TODO).
    return list(allowed_sucursales(user=request.user, tenant=tenant).values_list("id", flat=True))
