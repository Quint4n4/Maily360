"""
Vistas del panel interno de plataforma (equipo Maily, cross-tenant).

SEGURIDAD — por qué estas vistas son cross-tenant:
  1. Heredan de PlatformAPIView (no de TenantAPIView) → NO se llama a
     resolve_membership_for_user ni se setea el GUC de PostgreSQL.
  2. El TenantMiddleware siempre inicializa el GUC con '' (string vacío)
     en el finally: `set_config('app.current_tenant_id', '', false)`.
  3. current_tenant_id() PostgreSQL hace NULLIF(..., '')::uuid, así que
     con GUC vacío devuelve NULL.
  4. La policy RLS de todos los modelos TenantAware es:
         USING (tenant_id = current_tenant_id() OR current_tenant_id() IS NULL)
     Cuando current_tenant_id() IS NULL → la condición es TRUE → acceso a TODAS
     las filas de TODOS los tenants.
  5. Por esto, los selectors de plataforma usan Model.all_objects (cross-tenant)
     y NUNCA Model.objects (que solo ve el tenant del request actual).

REGLA: estas vistas SOLO se usan para el equipo interno de Maily. NUNCA
exponer un endpoint de clínica usando PlatformAPIView.

PERMISOS por endpoint:
  GET  /clinicas/          → PlatformClinicReadPermission  (super_admin, sales, engineering)
  POST /clinicas/          → PlatformClinicWritePermission (super_admin, sales)
  GET  /clinicas/<id>/     → PlatformClinicReadPermission  (super_admin, sales, engineering)
  POST /clinicas/<id>/estado/ → PlatformClinicWritePermission (super_admin, sales)
  GET  /auditoria/         → PlatformAuditPermission (super_admin, engineering)
  GET  /sistema/           → PlatformSystemPermission (super_admin, engineering)
"""

import uuid as _uuid_module

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import (
    PlatformAuditPermission,
    PlatformClinicReadPermission,
    PlatformClinicWritePermission,
    PlatformMetricsPermission,
    PlatformPlanWritePermission,
    PlatformStaffListPermission,
    PlatformSubscriptionPermission,
    PlatformSystemPermission,
)
from apps.core.tenant_context import set_request_context
from apps.plataforma.selectors import (
    plan_get,
    platform_audit_log_list,
    platform_clinica_detail,
    platform_clinicas_list,
    platform_dashboard_metrics,
    platform_plan_list,
    platform_staff_list,
    platform_subscription_row_build,
    platform_subscriptions_list,
    platform_subscriptions_resumen,
)
from apps.plataforma.serializers import (
    AuditLogOutputSerializer,
    AuditoriaQueryInputSerializer,
    ClinicaCreateInputSerializer,
    ClinicaCreateOutputSerializer,
    ClinicaDetailOutputSerializer,
    ClinicaEstadoInputSerializer,
    ClinicaOutputSerializer,
    DashboardMetricsOutputSerializer,
    PlanCreateInputSerializer,
    PlanOutputSerializer,
    PlanUpdateInputSerializer,
    PlatformStaffOutputSerializer,
    SubscripcionesQueryInputSerializer,
    SubscripcionesResumenOutputSerializer,
    SubscriptionRowOutputSerializer,
    SystemHealthOutputSerializer,
    TenantSubscriptionInputSerializer,
)
from apps.plataforma.services import (
    plan_create,
    plan_update,
    tenant_and_owner_create,
    tenant_set_status,
    tenant_subscription_set,
)
from apps.plataforma.system_health import system_health_get
from apps.tenancy.models import Plan, Tenant

# ---------------------------------------------------------------------------
# Base view de plataforma
# ---------------------------------------------------------------------------


class PlatformAPIView(APIView):
    """Vista base para todos los endpoints del panel interno de plataforma.

    Diferencias con TenantAPIView:
    - NO resuelve TenantMembership.
    - NO setea el GUC de PostgreSQL app.current_tenant_id.
    - SÍ popula el contexto de request (ip/user_agent/request_id) para auditoría.
    - El GUC queda vacío (valor dejado por TenantMiddleware en el finally),
      lo que resulta en current_tenant_id() IS NULL → RLS permite acceso cross-tenant.

    Queries de modelos TenantAware: SIEMPRE usar Model.all_objects.
    NUNCA usar Model.objects en selectors de plataforma.
    """

    # Mínimo: autenticación JWT. Las subclases agregan el permiso de plataforma.
    permission_classes = [IsAuthenticated]

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        """Extiende initial para poblar el contexto de request HTTP.

        No resuelve tenant ni setea GUC. El contexto de request se necesita
        para que audit_record() capture ip/user_agent/request_id sin acoplar
        los services a HTTP.
        """
        super().initial(request, *args, **kwargs)
        # Poblar contexto de auditoría sin tocar el contexto de tenant.
        x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip: str = (
            x_forwarded.split(",")[0].strip()
            if x_forwarded
            else request.META.get("REMOTE_ADDR", "")
        )
        user_agent: str = request.META.get("HTTP_USER_AGENT", "")[:512]
        raw_request_id: str = request.META.get("HTTP_X_REQUEST_ID", "")
        request_id: str = raw_request_id if raw_request_id else _uuid_module.uuid4().hex
        set_request_context(ip=ip, user_agent=user_agent, request_id=request_id)


# ---------------------------------------------------------------------------
# Paginador estándar (igual que el resto del proyecto)
# ---------------------------------------------------------------------------


class _StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ---------------------------------------------------------------------------
# GET /api/v1/plataforma/metricas/
# ---------------------------------------------------------------------------


class PlatformMetricasApi(PlatformAPIView):
    """Dashboard de métricas del panel interno.

    Roles permitidos: super_admin, sales, engineering.
    """

    permission_classes = [IsAuthenticated, PlatformMetricsPermission]

    def get(self, request: Request) -> Response:
        """Devuelve conteos globales de clínicas, usuarios y pacientes."""
        metrics = platform_dashboard_metrics()
        return Response(DashboardMetricsOutputSerializer(metrics).data)


# ---------------------------------------------------------------------------
# GET/POST /api/v1/plataforma/clinicas/
# ---------------------------------------------------------------------------


class PlatformClinicasListApi(PlatformAPIView):
    """Listado paginado de clínicas (cross-tenant) y alta de clínica nueva.

    GET  → super_admin, sales, engineering  (PlatformClinicReadPermission)
    POST → super_admin, sales               (PlatformClinicWritePermission)

    Los permisos se resuelven por método HTTP. DRF evalúa permission_classes
    en orden; como el GET_permission y el POST_permission son clases separadas
    y DRF evalúa si CUALQUIERA devuelve True para el método, se necesita una
    vista que delegue al permiso correcto según el método.

    Implementación: la vista maneja el permiso manualmente en cada método
    para evitar mezclar dos permission classes que se solapan. El patrón
    elegido instancia el permission correcto y llama has_permission() inline.
    """

    # Solo autenticación base; el permiso real se evalúa por método.
    permission_classes = [IsAuthenticated]

    def get_permissions(self) -> list:
        """Devuelve la lista de permisos según el método HTTP."""
        if self.request.method == "POST":
            return [IsAuthenticated(), PlatformClinicWritePermission()]
        # GET, HEAD, OPTIONS
        return [IsAuthenticated(), PlatformClinicReadPermission()]

    def get(self, request: Request) -> Response:
        """Lista todas las clínicas con member_count y patient_count."""
        search: str = request.query_params.get("search", "")
        status_filter: str | None = request.query_params.get("status") or None

        qs = platform_clinicas_list(search=search, status=status_filter)

        paginator = _StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = ClinicaOutputSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = ClinicaOutputSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request: Request) -> Response:
        """Crea una clínica nueva con su dueño y datos semilla.

        SEGURIDAD: devuelve la contraseña temporal en la respuesta.
        El frontend DEBE mostrarla exactamente una vez.
        """
        s = ClinicaCreateInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            resultado = tenant_and_owner_create(
                actor=request.user,  # type: ignore[arg-type]
                name=data["name"],
                owner_email=data["owner_email"],
                owner_first_name=data["owner_first_name"],
                owner_last_name=data["owner_last_name"],
                timezone=data.get("timezone", "America/Mexico_City"),
                trial_days=data.get("trial_days", 60),
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        except IntegrityError as exc:
            # Carrera al generar el slug (check-then-act): dos altas simultáneas
            # produjeron el mismo slug entre la verificación y el INSERT.
            raise serializers.ValidationError(
                "Conflicto al crear la clínica (identificador duplicado). Intenta de nuevo."
            ) from exc

        # Construir el payload de salida.
        # `tenant` necesita member_count y patient_count para ClinicaOutputSerializer.
        # Recién creada: 1 miembro (el owner), 0 pacientes.
        tenant = resultado["tenant"]
        tenant.member_count = 1  # type: ignore[attr-defined]
        tenant.patient_count = 0  # type: ignore[attr-defined]

        output = {
            "tenant": tenant,
            "owner_email": resultado["owner"].user.email,
            "temporary_password": resultado["temporary_password"],
        }

        # MEDIO-1: la respuesta contiene la contraseña temporal de primer acceso.
        # Prohibir explícitamente que cualquier proxy/CDN la cachee.
        response = Response(
            ClinicaCreateOutputSerializer(output).data,
            status=status.HTTP_201_CREATED,
        )
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response["Pragma"] = "no-cache"
        return response


# ---------------------------------------------------------------------------
# GET /api/v1/plataforma/clinicas/<tenant_id>/
# ---------------------------------------------------------------------------


class PlatformClinicaDetailApi(PlatformAPIView):
    """Ficha de detalle de una clínica (cross-tenant).

    GET → super_admin, sales, engineering (PlatformClinicReadPermission).
    """

    permission_classes = [IsAuthenticated, PlatformClinicReadPermission]

    def get(self, request: Request, tenant_id: _uuid_module.UUID) -> Response:
        """Devuelve la ficha de detalle de la clínica indicada."""
        try:
            detail = platform_clinica_detail(tenant_id=tenant_id)
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Clínica no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(ClinicaDetailOutputSerializer(detail).data)


# ---------------------------------------------------------------------------
# POST /api/v1/plataforma/clinicas/<tenant_id>/estado/
# ---------------------------------------------------------------------------


class PlatformClinicaEstadoApi(PlatformAPIView):
    """Cambia el estado de una clínica (suspender o reactivar).

    POST → super_admin, sales.
    """

    permission_classes = [IsAuthenticated, PlatformClinicWritePermission]

    def post(self, request: Request, tenant_id: _uuid_module.UUID) -> Response:
        """Cambia el estado de la clínica indicada."""
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Clínica no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = ClinicaEstadoInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            updated = tenant_set_status(
                tenant=tenant,
                actor=request.user,  # type: ignore[arg-type]
                status=s.validated_data["status"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

        return Response(ClinicaOutputSerializer(updated).data)


# ---------------------------------------------------------------------------
# GET /api/v1/plataforma/usuarios/
# ---------------------------------------------------------------------------


class PlatformUsuariosListApi(PlatformAPIView):
    """Listado de usuarios del equipo de plataforma.

    GET → solo super_admin.
    """

    permission_classes = [IsAuthenticated, PlatformStaffListPermission]

    def get(self, request: Request) -> Response:
        """Lista todos los usuarios con is_platform_staff=True."""
        search: str = request.query_params.get("search", "")

        qs = platform_staff_list(search=search)

        paginator = _StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = PlatformStaffOutputSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = PlatformStaffOutputSerializer(qs, many=True)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# GET /api/v1/plataforma/auditoria/
# ---------------------------------------------------------------------------


class PlatformAuditoriaListApi(PlatformAPIView):
    """Bitácora de auditoría cross-tenant (solo lectura).

    GET → super_admin, engineering (PlatformAuditPermission). Sales queda fuera.

    AuditLog es append-only: no existe endpoint de escritura sobre este recurso.
    """

    permission_classes = [IsAuthenticated, PlatformAuditPermission]

    def get(self, request: Request) -> Response:
        """Lista la bitácora de auditoría con filtros opcionales.

        Query params (todos opcionales): tenant_id, action, actor_id,
        date_from, date_to (datetime ISO), search.
        Valores con formato inválido (UUID/fecha) devuelven 400.
        """
        query = AuditoriaQueryInputSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data

        qs = platform_audit_log_list(
            tenant_id=filters.get("tenant_id"),
            action=filters.get("action") or None,
            actor_id=filters.get("actor_id"),
            date_from=filters.get("date_from"),
            date_to=filters.get("date_to"),
            search=filters.get("search", ""),
        )

        paginator = _StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = AuditLogOutputSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = AuditLogOutputSerializer(qs, many=True)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# GET /api/v1/plataforma/sistema/
# ---------------------------------------------------------------------------


class PlatformSistemaApi(PlatformAPIView):
    """Salud real del sistema (BD/Redis/Celery/cola de PDFs), sin datos inventados.

    GET → super_admin, engineering (PlatformSystemPermission). Sales queda fuera.

    Cada check (apps.plataforma.system_health) está aislado con try/except:
    la caída de un servicio individual nunca produce un 500, solo se refleja
    en su status ("down") y en overall_status ("degraded"/"down").
    """

    permission_classes = [IsAuthenticated, PlatformSystemPermission]

    def get(self, request: Request) -> Response:
        """Devuelve el snapshot de salud del sistema (contrato fijo con el frontend)."""
        health = system_health_get()
        return Response(SystemHealthOutputSerializer(health).data)


# ---------------------------------------------------------------------------
# GET /api/v1/plataforma/planes/
# ---------------------------------------------------------------------------


class PlatformPlanesListApi(PlatformAPIView):
    """Catálogo de planes de suscripción (sin paginar) y alta de plan nuevo.

    GET  → super_admin, sales (PlatformSubscriptionPermission). Incluye
           TODOS los planes, activos e inactivos (platform_plan_list no
           filtra por is_active — el portal los muestra atenuados).
    POST → solo super_admin (PlatformPlanWritePermission, Fase 3.1). Sales
           puede leer y asignar planes existentes, pero no define precios.

    Mismo patrón que PlatformClinicasListApi: permiso resuelto por método
    vía get_permissions() en lugar de mezclar dos permission classes que se
    solapan en permission_classes.
    """

    permission_classes = [IsAuthenticated]

    def get_permissions(self) -> list:
        """Devuelve la lista de permisos según el método HTTP."""
        if self.request.method == "POST":
            return [IsAuthenticated(), PlatformPlanWritePermission()]
        # GET, HEAD, OPTIONS
        return [IsAuthenticated(), PlatformSubscriptionPermission()]

    def get(self, request: Request) -> Response:
        """Lista todos los planes (activos e inactivos) ordenados por `order`."""
        qs = platform_plan_list()
        return Response(PlanOutputSerializer(qs, many=True).data)

    def post(self, request: Request) -> Response:
        """Crea un plan nuevo en el catálogo. Solo super_admin."""
        s = PlanCreateInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            plan = plan_create(
                actor=request.user,  # type: ignore[arg-type]
                name=data["name"],
                price_monthly=data["price_monthly"],
                description=data.get("description", ""),
                is_featured=data.get("is_featured", False),
                features=data.get("features") or [],
                is_active=data.get("is_active", True),
                order=data.get("order"),
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        except IntegrityError as exc:
            # Carrera al generar el slug (check-then-act), igual que en
            # tenant_and_owner_create.
            raise serializers.ValidationError(
                "Conflicto al crear el plan (identificador duplicado). Intenta de nuevo."
            ) from exc

        return Response(PlanOutputSerializer(plan).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# PATCH /api/v1/plataforma/planes/<plan_id>/
# ---------------------------------------------------------------------------


class PlatformPlanDetailApi(PlatformAPIView):
    """Edición de un plan existente del catálogo (Fase 3.1).

    PATCH → solo super_admin (PlatformPlanWritePermission).
    PUT y DELETE no están ruteados → 405 (no hay delete físico: Plan tiene
    PROTECT desde TenantSubscription; desactivar es is_active=False vía
    este mismo PATCH).
    """

    permission_classes = [IsAuthenticated, PlatformPlanWritePermission]

    def patch(self, request: Request, plan_id: _uuid_module.UUID) -> Response:
        """Actualiza un subconjunto de campos del plan indicado."""
        try:
            plan_get(plan_id=plan_id)
        except Plan.DoesNotExist:
            return Response(
                {"detail": "Plan no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = PlanUpdateInputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        try:
            updated = plan_update(
                actor=request.user,  # type: ignore[arg-type]
                plan_id=plan_id,
                **s.validated_data,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

        return Response(PlanOutputSerializer(updated).data)


# ---------------------------------------------------------------------------
# GET /api/v1/plataforma/suscripciones/
# ---------------------------------------------------------------------------


class PlatformSuscripcionesListApi(PlatformAPIView):
    """Listado paginado de suscripciones: una fila por clínica.

    GET → super_admin, sales (PlatformSubscriptionPermission).
    """

    permission_classes = [IsAuthenticated, PlatformSubscriptionPermission]

    def get(self, request: Request) -> Response:
        """Lista todas las clínicas con su suscripción (o sin ella) y su alerta."""
        query = SubscripcionesQueryInputSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data

        rows = platform_subscriptions_list(
            search=filters.get("search", ""),
            plan_id=filters.get("plan_id"),
            alerta=filters.get("alerta") or None,
        )

        paginator = _StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        if page is not None:
            serializer = SubscriptionRowOutputSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = SubscriptionRowOutputSerializer(rows, many=True)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# GET /api/v1/plataforma/suscripciones/resumen/
# ---------------------------------------------------------------------------


class PlatformSuscripcionesResumenApi(PlatformAPIView):
    """Resumen agregado de suscripciones (conteos, alertas, MRR estimado).

    GET → super_admin, sales (PlatformSubscriptionPermission).
    """

    permission_classes = [IsAuthenticated, PlatformSubscriptionPermission]

    def get(self, request: Request) -> Response:
        """Devuelve el resumen agregado para el panel de suscripciones."""
        resumen = platform_subscriptions_resumen()
        return Response(SubscripcionesResumenOutputSerializer(resumen).data)


# ---------------------------------------------------------------------------
# POST /api/v1/plataforma/clinicas/<tenant_id>/suscripcion/
# ---------------------------------------------------------------------------


class PlatformClinicaSuscripcionApi(PlatformAPIView):
    """Asigna o cambia el plan de suscripción de una clínica.

    POST → super_admin, sales (PlatformSubscriptionPermission).
    """

    permission_classes = [IsAuthenticated, PlatformSubscriptionPermission]

    def post(self, request: Request, tenant_id: _uuid_module.UUID) -> Response:
        """Crea o actualiza la suscripción de la clínica indicada."""
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Clínica no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        s = TenantSubscriptionInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            tenant_subscription_set(
                tenant=tenant,
                actor=request.user,  # type: ignore[arg-type]
                plan_id=data["plan_id"],
                billing_cycle=data["billing_cycle"],
                current_period_end=data["current_period_end"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

        # Refresca el tenant con la suscripción recién asignada para construir
        # la fila de salida con el mismo shape que el listado.
        tenant.refresh_from_db()
        row = platform_subscription_row_build(tenant=tenant)
        return Response(SubscriptionRowOutputSerializer(row).data)
