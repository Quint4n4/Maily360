"""
Vistas del dominio finanzas.

Vistas delgadas: parsean el request, llaman selector/service, devuelven Response.
Cero lógica de negocio aquí. Heredan de TenantAPIView (resuelve tenant tras el JWT).

Manejo de errores:
  - <Model>.DoesNotExist     → 404 (no revelar existencia cross-tenant).
  - ValidationError (django) → 400 (con exc.messages).
  - tenant None              → 403.

Fase 2 — nuevos endpoints:
  - PeriodReportApi  : GET /finanzas/reporte/ — dataset KPIs + series para reporte.
  - PeriodReportPdfApi: GET /finanzas/reporte/pdf/ — PDF del reporte (Bearer auth).
  - DailySheetApi    : GET /finanzas/cierre-diario/ — cierre diario de caja.
"""

import datetime
import logging
import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.clinica.sucursal_scope import (
    resolve_active_sucursal,
    resolve_write_sucursal,
    sucursal_scope_ids,
)
from apps.core.permissions import (
    FINANCE_DESK_ROLES,
    CfdiPermission,
    ChargeListPermission,
    FinanceChargePermission,
    FinanceConceptPermission,
    FinanceConfigPermission,
    FinanceDashboardPermission,
    FinancePaymentPermission,
    HasClinicRole,
    PatientStatementPermission,
    QuotePermission,
    RetentionPermission,
    TreatmentPackagePermission,
)
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.finanzas import selectors, services
from apps.finanzas.models import (
    CfdiDocument,
    Charge,
    DiscountType,
    Payment,
    Quote,
    ServiceConcept,
    TreatmentPackage,
)
from apps.finanzas.serializers import (
    CfdiDocumentOutputSerializer,
    ChargeOutputSerializer,
    ClinicFiscalConfigOutputSerializer,
    PaymentOutputSerializer,
    QuoteOutputSerializer,
    ServiceConceptOutputSerializer,
    TreatmentPackageListItemSerializer,
    TreatmentPackageOutputSerializer,
)
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get
from apps.pdfs.services import pdf_job_enqueue

logger = logging.getLogger("apps.finanzas.views")


# ---------------------------------------------------------------------------
# Permiso para endpoints de caja (cierre diario).
# ---------------------------------------------------------------------------


class FinanceDeskPermission(HasClinicRole):
    """Permisos para endpoints de caja (cierre diario).

    Matriz:
        GET → FINANCE_DESK_ROLES: owner, admin, finance, reception.
    """

    policy: dict[str, frozenset[str]] = {
        "GET": FINANCE_DESK_ROLES,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_tenant() -> Any:
    """Retorna el tenant activo o None (la vista responde 403 si es None)."""
    return get_current_tenant()


_NO_TENANT = Response(
    {"detail": "No se encontró un tenant activo para este request."},
    status=status.HTTP_403_FORBIDDEN,
)


def _parse_date(value: str | None) -> datetime.date | None:
    """Parsea YYYY-MM-DD a date, o None si vacío."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def _scope_or_404(
    request: Request, sucursal_id: uuid.UUID | None, not_found_detail: str
) -> Response | None:
    """404 si `sucursal_id` está fuera del alcance de sedes del actor.

    Multi-sede — Fase 3, cierre de hueco (docs/design/
    sucursales-hallazgos-seguridad.md, clústers A6/A7/D): el LISTADO general
    de cargos/cotizaciones/CFDI ya se acota con `sucursal_scope_ids`; el
    DETALLE/ACCIÓN por id (GET/PATCH/DELETE/POST de una acción) debe acotar
    EXACTAMENTE igual, o un admin acotado a una sede puede leer/operar
    objetos de OTRA sede por su id — el id se obtiene del estado de cuenta
    del paciente, que es compartido entre sedes a propósito.

    Legado (`sucursal_id is None`) siempre pasa, igual que en los listados
    (compatibilidad retro: dato sin backfillar, o tenant sin sucursales).

    Args:
        request:           request de una vista TenantAPIView.
        sucursal_id:       sede del objeto ya resuelto (None = legado).
        not_found_detail:  mensaje del 404 (mismo texto que el selector usa
                            para "no encontrado", para no revelar que el
                            objeto existe en otra sede).

    Returns:
        None si el objeto está dentro de alcance (o legado/alcance total);
        una Response 404 en caso contrario.

    Raises:
        rest_framework.exceptions.PermissionDenied: mismos casos que
            `sucursal_scope_ids` (header inválido o sede no permitida).
    """
    if sucursal_id is None:
        return None
    scope_ids = sucursal_scope_ids(request)
    if scope_ids is None or sucursal_id in scope_ids:
        return None
    return Response({"detail": not_found_detail}, status=status.HTTP_404_NOT_FOUND)


def _resolve_write_sucursal(request: Request, tenant: Any) -> Any:
    """Resuelve la sucursal DONDE SE GENERA un cargo/pago/cotización (Fase 3).

    Usa la sede activa del request (header X-Sucursal-Id, ya validada contra
    las sedes permitidas del usuario por `resolve_active_sucursal`) y cae a
    la sede predeterminada del tenant si no hay header. Retorna None si el
    tenant no tiene ninguna sucursal configurada (compatibilidad retro).

    Si no hay header y la sede predeterminada del tenant no está entre las
    sucursales permitidas del usuario (p. ej. un admin de sucursal Norte
    cuando la default es Centro), `resolve_write_sucursal` levanta
    ValidationError en lugar de dejarlo cobrar/cotizar en la sede ajena.
    """
    active_sucursal = resolve_active_sucursal(request)
    return resolve_write_sucursal(
        tenant=tenant,
        user=request.user,
        sucursal_id=None,
        active_sucursal_id=active_sucursal.id if active_sucursal is not None else None,
    )


# ===========================================================================
# Conceptos (catálogo)
# ===========================================================================


class ConceptListCreateApi(TenantAPIView):
    """GET  /api/v1/finanzas/conceptos/ — lista de conceptos cobrables.
    POST /api/v1/finanzas/conceptos/ — crea un concepto (solo owner).
    """

    permission_classes = [IsAuthenticated, FinanceConceptPermission]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=160)
        description = serializers.CharField(default="", allow_blank=True)
        clinical_description = serializers.CharField(default="", allow_blank=True)
        base_price = serializers.DecimalField(
            max_digits=12, decimal_places=2, default=Decimal("0.00")
        )
        sat_product_key = serializers.CharField(max_length=10, default="", allow_blank=True)
        sat_unit_key = serializers.CharField(max_length=10, default="E48", allow_blank=True)
        # Multi-sede (decisión del dueño, 2026-07-16): sedes donde el servicio
        # está disponible. Vacía = disponible en TODAS las sedes.
        sucursal_ids = serializers.ListField(
            child=serializers.UUIDField(), required=False, default=list
        )

    def get(self, request: Request) -> Response:
        """Lista el catálogo de conceptos del tenant actual.

        Multi-sede (decisión del dueño, 2026-07-16): se acota al alcance de
        sucursales del usuario (`sucursal_scope_ids`) — un concepto con M2M
        `sucursales` vacío es visible en cualquier sede; uno con sedes
        explícitas solo es visible donde está asignado. El GET NO restringe
        por rol (admin y staff siguen viendo el catálogo para cobrar/cotizar).
        """
        only_active = request.query_params.get("only_active", "true").lower() != "false"
        qs = selectors.concept_list(
            only_active=only_active, sucursal_ids=sucursal_scope_ids(request)
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = ServiceConceptOutputSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            concept = services.concept_create(tenant=tenant, user=request.user, **s.validated_data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            ServiceConceptOutputSerializer(concept).data, status=status.HTTP_201_CREATED
        )


class ConceptDetailApi(TenantAPIView):
    """GET/PATCH/DELETE /api/v1/finanzas/conceptos/<uuid>/.

    PATCH/DELETE: solo owner (decisión del dueño, 2026-07-16).
    """

    permission_classes = [IsAuthenticated, FinanceConceptPermission]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=160, required=False)
        description = serializers.CharField(required=False, allow_blank=True)
        clinical_description = serializers.CharField(required=False, allow_blank=True)
        base_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
        sat_product_key = serializers.CharField(max_length=10, required=False, allow_blank=True)
        sat_unit_key = serializers.CharField(max_length=10, required=False, allow_blank=True)
        # Toggle de estado: se maneja por separado (reactivar/desactivar), no como campo editable.
        is_active = serializers.BooleanField(required=False)
        # Multi-sede (decisión del dueño, 2026-07-16): si se envía, REEMPLAZA
        # por completo las sedes donde el servicio está disponible (vacía =
        # todas). Si se omite, la disponibilidad actual no se toca.
        sucursal_ids = serializers.ListField(child=serializers.UUIDField(), required=False)

    def _get_or_404(self, concept_id: uuid.UUID) -> "tuple[ServiceConcept | None, Response | None]":
        try:
            return selectors.concept_get(concept_id=concept_id), None
        except ServiceConcept.DoesNotExist:
            return None, Response(
                {"detail": "Concepto no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

    def get(self, request: Request, concept_id: uuid.UUID) -> Response:
        concept, err = self._get_or_404(concept_id)
        if err is not None:
            return err
        return Response(ServiceConceptOutputSerializer(concept).data)

    def patch(self, request: Request, concept_id: uuid.UUID) -> Response:
        concept, err = self._get_or_404(concept_id)
        if err is not None:
            return err
        s = self.InputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = dict(s.validated_data)
        is_active = data.pop("is_active", None)
        sucursal_ids = data.pop("sucursal_ids", None)
        try:
            # El toggle de estado va por su propio service (no por concept_update,
            # que trata is_active como inmutable).
            if is_active is not None:
                if is_active:
                    concept = services.concept_reactivate(concept=concept, user=request.user)
                else:
                    concept = services.concept_deactivate(concept=concept, user=request.user)
            if data or sucursal_ids is not None:
                concept = services.concept_update(
                    concept=concept, user=request.user, sucursal_ids=sucursal_ids, **data
                )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ServiceConceptOutputSerializer(concept).data)

    def delete(self, request: Request, concept_id: uuid.UUID) -> Response:
        concept, err = self._get_or_404(concept_id)
        if err is not None:
            return err
        services.concept_deactivate(concept=concept, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Configuración fiscal
# ===========================================================================


class FiscalConfigApi(TenantAPIView):
    """GET/PATCH /api/v1/finanzas/config/ — datos fiscales del emisor (owner/admin)."""

    permission_classes = [IsAuthenticated, FinanceConfigPermission]

    class InputSerializer(serializers.Serializer):
        rfc = serializers.CharField(max_length=13, required=False, allow_blank=True)
        legal_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
        tax_regime = serializers.CharField(max_length=5, required=False, allow_blank=True)
        postal_code = serializers.CharField(max_length=5, required=False, allow_blank=True)
        series = serializers.CharField(max_length=10, required=False)

    def get(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        config = services.fiscal_config_get_or_create(tenant=tenant, user=request.user)
        return Response(ClinicFiscalConfigOutputSerializer(config).data)

    def patch(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        if not s.validated_data:
            return Response(
                {"detail": "No se proporcionaron campos para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            config = services.clinic_fiscal_config_update(
                tenant=tenant, user=request.user, **s.validated_data
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ClinicFiscalConfigOutputSerializer(config).data)


# ===========================================================================
# Paquetes de tratamientos (catálogo reutilizable — Fase 3, Calendarización)
# ===========================================================================


class PackageListCreateApi(TenantAPIView):
    """GET  /api/v1/finanzas/paquetes/ — catálogo de paquetes de tratamientos.
    POST /api/v1/finanzas/paquetes/ — crea un paquete (solo owner).

    Cada item de entrada: {concept_id, sessions?, order?}. La forma exacta
    de cada línea se valida en el service (mismo patrón que Cotizaciones /
    Calendarización: `items` llega como lista de dicts libres).
    """

    permission_classes = [IsAuthenticated, TreatmentPackagePermission]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=160)
        description = serializers.CharField(default="", allow_blank=True)
        is_active = serializers.BooleanField(default=True)
        items = serializers.ListField(child=serializers.DictField(), allow_empty=False)
        # Multi-sede (decisión del dueño, 2026-07-16): sedes donde el paquete
        # está disponible. Vacía = disponible en TODAS las sedes.
        sucursal_ids = serializers.ListField(
            child=serializers.UUIDField(), required=False, default=list
        )

    def get(self, request: Request) -> Response:
        """Lista el catálogo de paquetes del tenant actual.

        Multi-sede (decisión del dueño, 2026-07-16): se acota al alcance de
        sucursales del usuario (`sucursal_scope_ids`), mismo criterio que
        `ConceptListCreateApi.get`. El GET NO restringe por rol.
        """
        only_active = request.query_params.get("only_active", "true").lower() != "false"
        qs = selectors.package_list(
            only_active=only_active, sucursal_ids=sucursal_scope_ids(request)
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            TreatmentPackageListItemSerializer(page, many=True).data
        )

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            package = services.package_create(tenant=tenant, user=request.user, **s.validated_data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            TreatmentPackageOutputSerializer(package).data, status=status.HTTP_201_CREATED
        )


class PackageDetailApi(TenantAPIView):
    """GET    /api/v1/finanzas/paquetes/<uuid>/ — detalle.
    PATCH  /api/v1/finanzas/paquetes/<uuid>/ — reemplaza (items opcional). Solo owner.
    DELETE /api/v1/finanzas/paquetes/<uuid>/ — baja lógica. Solo owner.

    PATCH es un REEMPLAZO del paquete (no un patch parcial de campos sueltos):
    `name`/`description`/`is_active` siempre se reescriben con lo enviado.
    Si `items` se omite, se conservan los items actuales tal cual (se
    reenvían al service para no perderlos, ya que `package_replace` siempre
    borra y recrea). `sucursal_ids` sí es opcional de verdad: si se omite, la
    disponibilidad actual no se toca (a diferencia de `items`).
    """

    permission_classes = [IsAuthenticated, TreatmentPackagePermission]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=160)
        description = serializers.CharField(default="", allow_blank=True)
        is_active = serializers.BooleanField(default=True)
        items = serializers.ListField(child=serializers.DictField(), required=False)
        # Multi-sede (decisión del dueño, 2026-07-16): si se envía, REEMPLAZA
        # por completo las sedes donde el paquete está disponible (vacía =
        # todas). Si se omite, la disponibilidad actual no se toca.
        sucursal_ids = serializers.ListField(child=serializers.UUIDField(), required=False)

    def _get_or_404(
        self, package_id: uuid.UUID
    ) -> "tuple[TreatmentPackage | None, Response | None]":
        try:
            return selectors.package_get(package_id=package_id), None
        except TreatmentPackage.DoesNotExist:
            return None, Response(
                {"detail": "Paquete no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

    def get(self, request: Request, package_id: uuid.UUID) -> Response:
        package, err = self._get_or_404(package_id)
        if err is not None:
            return err
        return Response(TreatmentPackageOutputSerializer(package).data)

    def patch(self, request: Request, package_id: uuid.UUID) -> Response:
        package, err = self._get_or_404(package_id)
        if err is not None:
            return err
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        items = data.pop("items", None)
        if items is None:
            # No se enviaron items nuevos: conserva los actuales (el service
            # siempre borra y recrea, así que hay que reenviarlos tal cual).
            items = [
                {
                    "concept_id": str(item.service_concept_id),
                    "sessions": item.sessions,
                    "order": item.order,
                }
                for item in package.items.all()
            ]
        try:
            package = services.package_replace(
                package=package, user=request.user, items=items, **data
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(TreatmentPackageOutputSerializer(package).data)

    def delete(self, request: Request, package_id: uuid.UUID) -> Response:
        package, err = self._get_or_404(package_id)
        if err is not None:
            return err
        services.package_delete(package=package, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Cotizaciones
# ===========================================================================


class QuoteListCreateApi(TenantAPIView):
    """GET  /api/v1/finanzas/cotizaciones/ — lista de cotizaciones.
    POST /api/v1/finanzas/cotizaciones/ — crea una cotización (borrador).
    """

    permission_classes = [IsAuthenticated, QuotePermission]

    # NOTA: este ItemSerializer documenta la forma esperada de cada línea,
    # pero `InputSerializer.items` (abajo) usa un ListField/DictField suelto:
    # la validación real de cada renglón ocurre en el servicio
    # (`apps.finanzas.services._create_quote_item` / `_validate_discount_value`),
    # que es quien lanza ValidationError → 400. Preexistente a este cambio.
    class ItemSerializer(serializers.Serializer):
        concept_id = serializers.UUIDField(required=False, allow_null=True)
        description = serializers.CharField(max_length=200, required=False, allow_blank=True)
        quantity = serializers.DecimalField(
            max_digits=10, decimal_places=2, default=Decimal("1.00")
        )
        unit_price = serializers.DecimalField(
            max_digits=12, decimal_places=2, default=Decimal("0.00")
        )
        discount_type = serializers.ChoiceField(
            choices=DiscountType.choices, default=DiscountType.AMOUNT
        )
        discount = serializers.DecimalField(
            max_digits=12, decimal_places=2, default=Decimal("0.00")
        )

    class InputSerializer(serializers.Serializer):
        patient_id = serializers.UUIDField()
        valid_until = serializers.DateField(required=False, allow_null=True)
        notes = serializers.CharField(default="", allow_blank=True)
        items = serializers.ListField(child=serializers.DictField(), allow_empty=False)
        global_discount_type = serializers.ChoiceField(
            choices=DiscountType.choices, default=DiscountType.AMOUNT
        )
        global_discount_value = serializers.DecimalField(
            max_digits=12, decimal_places=2, default=Decimal("0.00"), min_value=Decimal("0.00")
        )

        def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
            """Rango del descuento general: porcentaje solo entre 0 y 100.

            La validación de NEGATIVO ya la cubre `min_value` del campo; el
            servicio (`quote_create` → `_validate_discount_value`) repite
            ambas validaciones como defensa en profundidad (se puede llamar
            sin pasar por este serializer, p. ej. desde
            `apps.expediente.services_calendarizacion`).
            """
            is_percent = attrs.get("global_discount_type") == DiscountType.PERCENT
            value = attrs.get("global_discount_value", Decimal("0.00"))
            if is_percent and value > Decimal("100"):
                raise serializers.ValidationError(
                    {
                        "global_discount_value": (
                            "El descuento general en porcentaje no puede superar 100."
                        )
                    }
                )
            return attrs

    def get(self, request: Request) -> Response:
        """Lista cotizaciones del tenant actual.

        Multi-sede — Fase 3: cuando se consulta por `patient_id` (historial
        del paciente), NO se acota por sede (compartido entre sedes). Sin
        `patient_id` (listado general), se acota al alcance de sucursales del
        usuario (`sucursal_scope_ids`) — privado por sede.
        """
        patient_id = request.query_params.get("patient_id") or None
        scope_ids = None if patient_id else sucursal_scope_ids(request)
        qs = selectors.quote_list(
            patient_id=patient_id,
            status=request.query_params.get("status"),
            sucursal_ids=scope_ids,
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(QuoteOutputSerializer(page, many=True).data)

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            patient = patient_get(patient_id=s.validated_data["patient_id"])
        except Patient.DoesNotExist:
            return Response({"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        try:
            quote = services.quote_create(
                tenant=tenant,
                user=request.user,
                patient=patient,
                items=s.validated_data["items"],
                valid_until=s.validated_data.get("valid_until"),
                notes=s.validated_data.get("notes", ""),
                sucursal=_resolve_write_sucursal(request, tenant),
                global_discount_type=s.validated_data["global_discount_type"],
                global_discount_value=s.validated_data["global_discount_value"],
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(QuoteOutputSerializer(quote).data, status=status.HTTP_201_CREATED)


def _quote_get_scoped(
    request: Request, quote_id: uuid.UUID
) -> "tuple[Quote | None, Response | None]":
    """Resuelve una cotización por id, acotada al alcance de sedes del actor.

    Multi-sede — Fase 3 (cierre de A6 — docs/design/
    sucursales-hallazgos-seguridad.md): usado por TODO el ciclo de vida por
    id (detalle/PATCH/enviar/aceptar) — antes solo el listado y la creación
    se acotaban por sede, y `QuoteAcceptApi` podía generar `Charge` en una
    sede ajena.
    """
    try:
        quote = selectors.quote_get(quote_id=quote_id)
    except Quote.DoesNotExist:
        return None, Response(
            {"detail": "Cotización no encontrada."}, status=status.HTTP_404_NOT_FOUND
        )
    err = _scope_or_404(request, quote.sucursal_id, "Cotización no encontrada.")
    if err is not None:
        return None, err
    return quote, None


class QuoteDetailApi(TenantAPIView):
    """GET  /api/v1/finanzas/cotizaciones/<uuid>/  — detalle.
    PATCH /api/v1/finanzas/cotizaciones/<uuid>/  — rechazar/vencer (status).
    """

    permission_classes = [IsAuthenticated, QuotePermission]

    class InputSerializer(serializers.Serializer):
        status = serializers.ChoiceField(choices=[Quote.Status.REJECTED, Quote.Status.EXPIRED])

    def get(self, request: Request, quote_id: uuid.UUID) -> Response:
        quote, err = _quote_get_scoped(request, quote_id)
        if err is not None:
            return err
        return Response(QuoteOutputSerializer(quote).data)

    def patch(self, request: Request, quote_id: uuid.UUID) -> Response:
        quote, err = _quote_get_scoped(request, quote_id)
        if err is not None:
            return err
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            quote = services.quote_set_status(
                quote=quote, user=request.user, status=s.validated_data["status"]
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(QuoteOutputSerializer(quote).data)


class QuoteSendApi(TenantAPIView):
    """POST /api/v1/finanzas/cotizaciones/<uuid>/enviar/ — marca como enviada."""

    permission_classes = [IsAuthenticated, QuotePermission]

    def post(self, request: Request, quote_id: uuid.UUID) -> Response:
        quote, err = _quote_get_scoped(request, quote_id)
        if err is not None:
            return err
        try:
            quote = services.quote_send(quote=quote, user=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(QuoteOutputSerializer(quote).data)


class QuoteAcceptApi(TenantAPIView):
    """POST /api/v1/finanzas/cotizaciones/<uuid>/aceptar/ — acepta y genera cargos."""

    permission_classes = [IsAuthenticated, QuotePermission]

    def post(self, request: Request, quote_id: uuid.UUID) -> Response:
        quote, err = _quote_get_scoped(request, quote_id)
        if err is not None:
            return err
        try:
            quote = services.quote_accept(quote=quote, user=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(QuoteOutputSerializer(quote).data)


class QuotePdfApi(TenantAPIView):
    """GET /api/v1/finanzas/cotizaciones/<uuid>/pdf/ — encola el PDF de la cotización.

    El PDF se genera en SEGUNDO PLANO (Celery, infra apps.pdfs) para no bloquear los
    workers de la API (riesgo P0). Devuelve 202 {job_id, status}; el frontend hace
    polling de GET /pdfs/job/<job_id>/ y descarga con .../file/ al estar "done".

    La cotización es MUTABLE (se edita), así que NO se cachea (cache_key="").
    Permiso QuotePermission. Anti-IDOR por tenant (404).
    """

    permission_classes = [IsAuthenticated, QuotePermission]

    def get(self, request: Request, quote_id: uuid.UUID) -> Response:
        try:
            quote = selectors.quote_get(quote_id=quote_id)
        except Quote.DoesNotExist:
            return Response(
                {"detail": "Cotización no encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Multi-sede — cierre de hueco (clúster A6 aplicado al PDF): generar el
        # PDF revela montos/paciente/conceptos de la cotización, así que el
        # endpoint debe acotarse por sede igual que el detalle y las acciones
        # de cotización, o un admin de otra sede se lleva el PDF por su id.
        err = _scope_or_404(request, quote.sucursal_id, "Cotización no encontrada.")
        if err is not None:
            return err

        tenant = get_current_tenant()
        folio_short = str(quote.id).replace("-", "")[:8].upper()
        job = pdf_job_enqueue(
            tenant=tenant,
            kind="quote",
            params={"quote_id": str(quote.id)},
            user=request.user,
            cache_key="",
            filename=f"cotizacion-{folio_short}.pdf",
        )
        return Response(
            {"job_id": str(job.id), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )


# ===========================================================================
# Cargos
# ===========================================================================


class ChargeListCreateApi(TenantAPIView):
    """GET  /api/v1/finanzas/cargos/ — lista de cargos.
    POST /api/v1/finanzas/cargos/ — crea un cargo (owner/admin/finance).

    Permisos:
        GET  → FINANCE_VIEW_ROLES siempre; doctor solo si doctors_see_costs (D-2).
        POST → FINANCE_CORE_ROLES (owner/admin/finance).

    Filtros GET soportados:
        ?patient_id=<uuid>    — cargos de un paciente.
        ?status=<str>         — pending | partial | paid | cancelled.
        ?appointment=<uuid>   — cargos ligados a una cita concreta (para el libro).
    """

    permission_classes = [IsAuthenticated, ChargeListPermission]

    class InputSerializer(serializers.Serializer):
        patient_id = serializers.UUIDField()
        description = serializers.CharField(max_length=200)
        amount = serializers.DecimalField(max_digits=12, decimal_places=2)
        concept_id = serializers.UUIDField(required=False, allow_null=True)
        appointment_id = serializers.UUIDField(required=False, allow_null=True)

    def get(self, request: Request) -> Response:
        """Lista cargos del tenant actual.

        Multi-sede — Fase 3: cuando se consulta por `patient_id` (estado de
        cuenta del paciente) o por `appointment` (bloque de la visita en el
        libro), NO se acota por sede — son vistas del expediente/cuenta del
        paciente, compartidas entre sedes. El listado GENERAL (sin esos
        filtros — p. ej. la pestaña "Cargos" de caja) SÍ se acota al alcance
        de sucursales del usuario (`sucursal_scope_ids`).
        """
        raw_patient = request.query_params.get("patient_id") or None
        raw_appointment = request.query_params.get("appointment") or None
        appointment_id: uuid.UUID | None = None
        if raw_appointment:
            try:
                appointment_id = uuid.UUID(raw_appointment)
            except ValueError:
                return Response(
                    {"detail": "El parámetro 'appointment' debe ser un UUID válido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        scope_ids = None if (raw_patient or appointment_id) else sucursal_scope_ids(request)
        qs = selectors.charge_list(
            patient_id=raw_patient,
            status=request.query_params.get("status"),
            appointment_id=appointment_id,
            sucursal_ids=scope_ids,
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(ChargeOutputSerializer(page, many=True).data)

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            patient = patient_get(patient_id=s.validated_data["patient_id"])
        except Patient.DoesNotExist:
            return Response({"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        concept = None
        concept_id = s.validated_data.get("concept_id")
        if concept_id:
            try:
                concept = selectors.concept_get(concept_id=concept_id)
            except ServiceConcept.DoesNotExist:
                return Response(
                    {"detail": "Concepto no encontrado."}, status=status.HTTP_404_NOT_FOUND
                )

        try:
            charge = services.charge_create(
                tenant=tenant,
                user=request.user,
                patient=patient,
                amount=s.validated_data["amount"],
                description=s.validated_data["description"],
                concept=concept,
                sucursal=_resolve_write_sucursal(request, tenant),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ChargeOutputSerializer(charge).data, status=status.HTTP_201_CREATED)


class ChargeDetailApi(TenantAPIView):
    """GET    /api/v1/finanzas/cargos/<uuid>/  — detalle.
    DELETE /api/v1/finanzas/cargos/<uuid>/  — cancela el cargo.

    Multi-sede — Fase 3 (cierre de A7 — docs/design/
    sucursales-hallazgos-seguridad.md): el detalle/cancelación por id se
    acota EXACTAMENTE igual que el listado GENERAL de cargos
    (`ChargeListCreateApi.get`, sin `patient_id`) — un admin acotado a una
    sede no puede leer ni cancelar un cargo de otra sede por su id, aunque lo
    haya obtenido del estado de cuenta compartido del paciente.
    """

    permission_classes = [IsAuthenticated, FinanceChargePermission]

    def _get_or_404(
        self, request: Request, charge_id: uuid.UUID
    ) -> "tuple[Charge | None, Response | None]":
        try:
            charge = selectors.charge_get(charge_id=charge_id)
        except Charge.DoesNotExist:
            return None, Response(
                {"detail": "Cargo no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
        err = _scope_or_404(request, charge.sucursal_id, "Cargo no encontrado.")
        if err is not None:
            return None, err
        return charge, None

    def get(self, request: Request, charge_id: uuid.UUID) -> Response:
        charge, err = self._get_or_404(request, charge_id)
        if err is not None:
            return err
        return Response(ChargeOutputSerializer(charge).data)

    def delete(self, request: Request, charge_id: uuid.UUID) -> Response:
        charge, err = self._get_or_404(request, charge_id)
        if err is not None:
            return err
        try:
            services.charge_cancel(charge=charge, user=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Pagos
# ===========================================================================


class PaymentListCreateApi(TenantAPIView):
    """GET  /api/v1/finanzas/pagos/ — lista de pagos.
    POST /api/v1/finanzas/pagos/ — registra un pago (caja: incluye recepción).
    """

    permission_classes = [IsAuthenticated, FinancePaymentPermission]

    class InputSerializer(serializers.Serializer):
        patient_id = serializers.UUIDField()
        amount = serializers.DecimalField(max_digits=12, decimal_places=2)
        method = serializers.ChoiceField(
            choices=Payment.Method.choices, default=Payment.Method.CASH
        )
        reference = serializers.CharField(max_length=120, default="", allow_blank=True)
        notes = serializers.CharField(default="", allow_blank=True)
        allocations = serializers.ListField(
            child=serializers.DictField(), required=False, default=list
        )

    def get(self, request: Request) -> Response:
        """Lista pagos del tenant actual.

        Multi-sede — Fase 3: cuando se consulta por `patient_id` (estado de
        cuenta del paciente), NO se acota por sede (compartido entre sedes).
        El listado GENERAL (sin `patient_id` — p. ej. la pestaña "Pagos" de
        caja) SÍ se acota al alcance de sucursales del usuario
        (`sucursal_scope_ids`).
        """
        raw_patient = request.query_params.get("patient_id") or None
        scope_ids = None if raw_patient else sucursal_scope_ids(request)
        qs = selectors.payment_list(
            patient_id=raw_patient,
            method=request.query_params.get("method"),
            sucursal_ids=scope_ids,
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(PaymentOutputSerializer(page, many=True).data)

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            patient = patient_get(patient_id=s.validated_data["patient_id"])
        except Patient.DoesNotExist:
            return Response({"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        try:
            payment = services.payment_register(
                tenant=tenant,
                user=request.user,
                patient=patient,
                amount=s.validated_data["amount"],
                method=s.validated_data["method"],
                reference=s.validated_data.get("reference", ""),
                notes=s.validated_data.get("notes", ""),
                allocations=s.validated_data.get("allocations", []),
                sucursal=_resolve_write_sucursal(request, tenant),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PaymentOutputSerializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentDetailApi(TenantAPIView):
    """GET /api/v1/finanzas/pagos/<uuid>/ — detalle de un pago."""

    permission_classes = [IsAuthenticated, FinancePaymentPermission]

    def get(self, request: Request, payment_id: uuid.UUID) -> Response:
        try:
            payment = selectors.payment_get(payment_id=payment_id)
        except Payment.DoesNotExist:
            return Response({"detail": "Pago no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        # Multi-sede — cierre de hueco (clúster A7 aplicado a PAGOS): el detalle
        # por id debe acotarse por sede igual que cargos/cotizaciones/CFDI, o un
        # admin de otra sede podría leer un pago por su id (el id se obtiene del
        # estado de cuenta compartido del paciente).
        err = _scope_or_404(request, payment.sucursal_id, "Pago no encontrado.")
        if err is not None:
            return err
        return Response(PaymentOutputSerializer(payment).data)


# ===========================================================================
# CFDI 4.0
# ===========================================================================


class CfdiListCreateApi(TenantAPIView):
    """GET  /api/v1/finanzas/cfdi/ — lista de comprobantes.
    POST /api/v1/finanzas/cfdi/ — emite (timbra) un CFDI desde un pago.
    """

    permission_classes = [IsAuthenticated, CfdiPermission]

    class InputSerializer(serializers.Serializer):
        payment_id = serializers.UUIDField()
        receptor_rfc = serializers.CharField(max_length=13)
        receptor_name = serializers.CharField(max_length=255)
        receptor_tax_regime = serializers.CharField(max_length=5, default="", allow_blank=True)
        receptor_postal_code = serializers.CharField(max_length=5, default="", allow_blank=True)
        cfdi_use = serializers.CharField(max_length=5, default="G03")
        payment_form = serializers.CharField(max_length=2, default="01")
        payment_method = serializers.CharField(max_length=3, default="PUE")

    def get(self, request: Request) -> Response:
        """Lista comprobantes CFDI del tenant actual.

        Multi-sede — Fase 3 (cierre de clúster D — docs/design/
        sucursales-hallazgos-seguridad.md): cuando se consulta por
        `patient_id` (historial fiscal del paciente), NO se acota por sede
        (compartido entre sedes, mismo criterio que cargos/pagos/
        cotizaciones). El listado GENERAL SÍ se acota al alcance de
        sucursales del usuario (`sucursal_scope_ids`).
        """
        patient_id = request.query_params.get("patient_id") or None
        scope_ids = None if patient_id else sucursal_scope_ids(request)
        qs = selectors.cfdi_list(
            patient_id=patient_id,
            status=request.query_params.get("status"),
            sucursal_ids=scope_ids,
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(CfdiDocumentOutputSerializer(page, many=True).data)

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            payment = selectors.payment_get(payment_id=s.validated_data["payment_id"])
        except Payment.DoesNotExist:
            return Response({"detail": "Pago no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        data = dict(s.validated_data)
        data.pop("payment_id")
        try:
            cfdi = services.cfdi_issue(tenant=tenant, user=request.user, payment=payment, **data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CfdiDocumentOutputSerializer(cfdi).data, status=status.HTTP_201_CREATED)


def _cfdi_get_scoped(
    request: Request, cfdi_id: uuid.UUID
) -> "tuple[CfdiDocument | None, Response | None]":
    """Resuelve un CFDI por id, acotado al alcance de sedes del actor.

    Multi-sede — Fase 3 (cierre de clúster D — docs/design/
    sucursales-hallazgos-seguridad.md): el detalle y la cancelación por id se
    acotan EXACTAMENTE igual que el listado GENERAL de CFDI (sin
    `patient_id`) — un admin acotado a una sede no debe leer ni cancelar el
    comprobante de otra sede por su id.
    """
    try:
        cfdi = selectors.cfdi_get(cfdi_id=cfdi_id)
    except CfdiDocument.DoesNotExist:
        return None, Response({"detail": "CFDI no encontrado."}, status=status.HTTP_404_NOT_FOUND)
    err = _scope_or_404(request, cfdi.sucursal_id, "CFDI no encontrado.")
    if err is not None:
        return None, err
    return cfdi, None


class CfdiDetailApi(TenantAPIView):
    """GET /api/v1/finanzas/cfdi/<uuid>/ — detalle de un comprobante."""

    permission_classes = [IsAuthenticated, CfdiPermission]

    def get(self, request: Request, cfdi_id: uuid.UUID) -> Response:
        cfdi, err = _cfdi_get_scoped(request, cfdi_id)
        if err is not None:
            return err
        return Response(CfdiDocumentOutputSerializer(cfdi).data)


class CfdiCancelApi(TenantAPIView):
    """POST /api/v1/finanzas/cfdi/<uuid>/cancelar/ — cancela un comprobante."""

    permission_classes = [IsAuthenticated, CfdiPermission]

    class InputSerializer(serializers.Serializer):
        reason = serializers.ChoiceField(choices=["01", "02", "03", "04"], default="02")

    def post(self, request: Request, cfdi_id: uuid.UUID) -> Response:
        cfdi, err = _cfdi_get_scoped(request, cfdi_id)
        if err is not None:
            return err
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cfdi = services.cfdi_cancel(
                cfdi=cfdi, user=request.user, reason=s.validated_data["reason"]
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CfdiDocumentOutputSerializer(cfdi).data)


# ===========================================================================
# Estado de cuenta
# ===========================================================================


class AccountStatementApi(TenantAPIView):
    """GET /api/v1/finanzas/estado-cuenta/<patient_id>/ — estado de cuenta del paciente.

    Permisos:
        GET → FINANCE_VIEW_ROLES siempre; doctor solo si doctors_see_costs (D-2).
    """

    permission_classes = [IsAuthenticated, PatientStatementPermission]

    def get(self, request: Request, patient_id: uuid.UUID) -> Response:
        try:
            patient = patient_get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return Response({"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        statement = selectors.account_statement_build(
            patient_id=patient_id,
            date_from=_parse_date(request.query_params.get("date_from")),
            date_to=_parse_date(request.query_params.get("date_to")),
        )
        statement["patient"] = {
            "id": str(patient.id),
            "full_name": patient.full_name,
            "record_number": patient.record_number,
        }
        return Response(statement)


# ===========================================================================
# Dashboard
# ===========================================================================


class DashboardApi(TenantAPIView):
    """GET /api/v1/finanzas/dashboard/ — KPIs y series para las gráficas.

    Multi-sede — Fase 3 (privado por sede): se acota al alcance de sucursales
    del usuario (`sucursal_scope_ids`). Un admin/finanzas acotado a una sede
    ve solo esa sede (con o sin header); el dueño ve consolidado sin sede
    activa, o esa sede con el header.
    """

    permission_classes = [IsAuthenticated, FinanceDashboardPermission]

    def get(self, request: Request) -> Response:
        metrics = selectors.finance_dashboard_metrics(
            date_from=_parse_date(request.query_params.get("date_from")),
            date_to=_parse_date(request.query_params.get("date_to")),
            sucursal_ids=sucursal_scope_ids(request),
        )
        return Response(metrics)


# ===========================================================================
# Fase 2 — Reporte de periodo
# ===========================================================================

_VALID_GROUPS: frozenset[str] = frozenset({"day", "week", "month"})


class PeriodReportApi(TenantAPIView):
    """GET /api/v1/finanzas/reporte/ — dataset completo para el reporte de periodo.

    Parámetros:
        date_from   — YYYY-MM-DD (requerido; se usa hoy - 30 días si falta).
        date_to     — YYYY-MM-DD (requerido; se usa hoy si falta).
        group       — day | week | month (default: day).

    Devuelve el dict de finance_period_report: KPIs del periodo, comparativa con el
    anterior, series temporales, desglose por método/servicio/doctor y A/R aging.

    Permiso: FinanceDashboardPermission (GET → owner, admin, finance, readonly).

    Multi-sede — Fase 3 (privado por sede): se acota al alcance de sucursales
    del usuario (`sucursal_scope_ids`), igual que DashboardApi.
    """

    permission_classes = [IsAuthenticated, FinanceDashboardPermission]

    def get(self, request: Request) -> Response:
        today = datetime.date.today()
        date_from = _parse_date(request.query_params.get("date_from")) or (
            today - datetime.timedelta(days=30)
        )
        date_to = _parse_date(request.query_params.get("date_to")) or today

        if date_from > date_to:
            return Response(
                {"detail": "date_from no puede ser posterior a date_to."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        group = request.query_params.get("group", "day")
        if group not in _VALID_GROUPS:
            return Response(
                {"detail": f"group debe ser uno de: {', '.join(sorted(_VALID_GROUPS))}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report = selectors.finance_period_report(
            date_from=date_from,
            date_to=date_to,
            group=group,
            sucursal_ids=sucursal_scope_ids(request),
        )
        return Response(report)


class PeriodReportPdfApi(TenantAPIView):
    """GET /api/v1/finanzas/reporte/pdf/ — PDF del reporte de periodo.

    Mismo rango que PeriodReportApi (date_from / date_to). Devuelve el PDF
    con Content-Disposition: inline para abrir en el navegador.

    Permiso: FinanceDashboardPermission (owner, admin, finance, readonly).
    Auth: Bearer token (el endpoint NO es público — el PDF contiene datos financieros).

    Seguridad:
        - WeasyPrint usa _secure_fetcher: solo data URIs (bloquea LFI/SSRF).
        - X-Frame-Options: DENY, X-Content-Type-Options: nosniff.
        - Si la generación falla, devuelve 500 con mensaje genérico.
    """

    permission_classes = [IsAuthenticated, FinanceDashboardPermission]

    def get(self, request: Request) -> Response:
        today = datetime.date.today()
        date_from = _parse_date(request.query_params.get("date_from")) or (
            today - datetime.timedelta(days=30)
        )
        date_to = _parse_date(request.query_params.get("date_to")) or today

        if date_from > date_to:
            return Response(
                {"detail": "date_from no puede ser posterior a date_to."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        group = request.query_params.get("group", "day")
        if group not in _VALID_GROUPS:
            group = "day"

        tenant = get_current_tenant()

        # Multi-sede — Fase 3 (privado por sede): el alcance se resuelve AQUÍ
        # (con el usuario/header del request actual) y se congela en los
        # params del job — la tarea de Celery corre sin request y no puede
        # volver a resolverlo.
        scope_ids = sucursal_scope_ids(request)

        # Reporte MUTABLE (datos vivos) → sin caché; se regenera fresco en Celery.
        job = pdf_job_enqueue(
            tenant=tenant,
            kind="finance_report",
            params={
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "group": group,
                "sucursal_ids": (
                    [str(sid) for sid in scope_ids] if scope_ids is not None else None
                ),
            },
            user=request.user,
            cache_key="",
            filename=f"reporte-{date_from}-{date_to}.pdf",
        )
        return Response(
            {"job_id": str(job.id), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )


# ===========================================================================
# Fase 2 — Cierre diario (day sheet)
# ===========================================================================


class DailySheetApi(TenantAPIView):
    """GET /api/v1/finanzas/cierre-diario/ — cierre de caja del día.

    Parámetros:
        date — YYYY-MM-DD (default: hoy).

    Devuelve producción, cobranza, ajustes, desglose por método y lista de
    movimientos del día (cargos + pagos) ordenados cronológicamente.

    Permiso: FinanceDeskPermission → FINANCE_DESK_ROLES (owner, admin, finance, reception).
    Reception puede consultar el cierre de caja propio del día; no puede ver el
    panel analítico (DashboardApi / PeriodReportApi).

    Multi-sede — Fase 3 (privado por sede): la caja es de la sede — se acota
    al alcance de sucursales del usuario (`sucursal_scope_ids`). Reception
    normalmente está acotada a UNA sede vía MembershipSucursal, así que ve
    solo el cierre de esa sede.
    """

    permission_classes = [IsAuthenticated, FinanceDeskPermission]

    def get(self, request: Request) -> Response:
        raw_date = request.query_params.get("date")
        if raw_date:
            parsed = _parse_date(raw_date)
            if parsed is None:
                return Response(
                    {"detail": "El parámetro 'date' debe tener formato YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            sheet_date = parsed
        else:
            sheet_date = datetime.date.today()

        sheet = selectors.finance_daily_sheet(
            date=sheet_date, sucursal_ids=sucursal_scope_ids(request)
        )
        return Response(sheet)


# ===========================================================================
# Fase 3 — Panel de retención (RFM)
# ===========================================================================


class RetentionPanelApi(TenantAPIView):
    """GET /api/v1/finanzas/retencion/ — panel de analítica de retención RFM.

    Calcula en VIVO (sin tabla intermedia) la segmentación RFM de todos los
    pacientes del tenant. No modifica ningún registro (solo lectura).

    Decisión D-7 (plan §3): solo visualización. El sistema identifica y lista
    los segmentos en riesgo / perdidos para que la clínica los contacte de forma
    manual. NO se envía ninguna campaña automática.

    Segmentos devueltos en ``segments``:
      - nuevo      : 1.ª cita atendida en los últimos 90 días.
      - vip        : top 20% gasto 12m + recencia <6m + ≥2 visitas/año.
      - frecuente  : ≥2 visitas/año + recencia <6m.
      - en_riesgo  : antes regular (≥2 visitas en el año previo) pero sin
                     visita en los últimos 150 días.
      - perdido    : sin ninguna visita atendida en los últimos 365 días.
      - ocasional  : el resto.

    Listas accionables:
      - ``at_risk_list`` / ``lost_list``: hasta 500 registros (cap documentado)
        con nombre, teléfono, email, última visita y gasto 12m.
      - ``total_at_risk`` / ``total_lost``: total real (puede superar el cap).
      - ``truncated``: True si alguna lista fue recortada.

    Métricas:
      - ``retention_rate``       : pacientes vistos 12m / pacientes vistos 12-24m previos.
      - ``avg_ticket``           : pago promedio de los últimos 12 meses.
      - ``no_show_rate``         : tasa de inasistencias (NO_SHOW / (NO_SHOW + ATTENDED)).
      - ``pct_with_future_appt`` : % de pacientes activos con cita futura agendada.

    Permiso: RetentionPermission → owner, admin, finance, readonly.
    Recepción, médicos y enfermería NO acceden (analítica de dirección).

    El endpoint puede tardar >200ms en clínicas grandes (aggregación sobre citas
    históricas). En v2 se añadirá caché de 1h o tarea Celery periódica.

    Multi-sede — Fase 3 (privado por sede): se acota al alcance de sucursales
    del usuario (`sucursal_scope_ids`) — un admin de sede analiza la
    retención de SU sede; el dueño ve el panel consolidado del negocio.
    """

    permission_classes = [IsAuthenticated, RetentionPermission]

    def get(self, request: Request) -> Response:
        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        from apps.finanzas.retention import retention_panel_build  # noqa: PLC0415

        panel = retention_panel_build(tenant_id=tenant.id, sucursal_ids=sucursal_scope_ids(request))
        return Response(panel)
