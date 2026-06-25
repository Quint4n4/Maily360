"""
Vistas del dominio finanzas.

Vistas delgadas: parsean el request, llaman selector/service, devuelven Response.
Cero lógica de negocio aquí. Heredan de TenantAPIView (resuelve tenant tras el JWT).

Manejo de errores:
  - <Model>.DoesNotExist     → 404 (no revelar existencia cross-tenant).
  - ValidationError (django) → 400 (con exc.messages).
  - tenant None              → 403.
"""

import datetime
import uuid
from decimal import Decimal
from typing import Any, Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import (
    CfdiPermission,
    ChargeListPermission,
    FinanceChargePermission,
    FinanceConceptPermission,
    FinanceConfigPermission,
    FinanceDashboardPermission,
    FinancePaymentPermission,
    FinanceQuotePermission,
    PatientStatementPermission,
)
from apps.core.tenant_context import get_current_tenant
from apps.core.views import TenantAPIView
from apps.finanzas import selectors, services
from apps.finanzas.models import (
    CfdiDocument,
    Charge,
    Payment,
    Quote,
    ServiceConcept,
)
from apps.finanzas.serializers import (
    CfdiDocumentOutputSerializer,
    ChargeOutputSerializer,
    ClinicFiscalConfigOutputSerializer,
    PaymentOutputSerializer,
    QuoteOutputSerializer,
    ServiceConceptOutputSerializer,
)
from apps.pacientes.models import Patient
from apps.pacientes.selectors import patient_get


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


def _parse_date(value: Optional[str]) -> Optional[datetime.date]:
    """Parsea YYYY-MM-DD a date, o None si vacío."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


# ===========================================================================
# Conceptos (catálogo)
# ===========================================================================


class ConceptListCreateApi(TenantAPIView):
    """GET  /api/v1/finanzas/conceptos/ — lista de conceptos cobrables.
    POST /api/v1/finanzas/conceptos/ — crea un concepto (owner/admin).
    """

    permission_classes = [IsAuthenticated, FinanceConceptPermission]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=160)
        description = serializers.CharField(default="", allow_blank=True)
        base_price = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
        sat_product_key = serializers.CharField(max_length=10, default="", allow_blank=True)
        sat_unit_key = serializers.CharField(max_length=10, default="E48", allow_blank=True)

    def get(self, request: Request) -> Response:
        only_active = request.query_params.get("only_active", "true").lower() != "false"
        qs = selectors.concept_list(only_active=only_active)
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
    """GET/PATCH/DELETE /api/v1/finanzas/conceptos/<uuid>/."""

    permission_classes = [IsAuthenticated, FinanceConceptPermission]

    class InputSerializer(serializers.Serializer):
        name = serializers.CharField(max_length=160, required=False)
        description = serializers.CharField(required=False, allow_blank=True)
        base_price = serializers.DecimalField(
            max_digits=12, decimal_places=2, required=False
        )
        sat_product_key = serializers.CharField(max_length=10, required=False, allow_blank=True)
        sat_unit_key = serializers.CharField(max_length=10, required=False, allow_blank=True)

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
        try:
            concept = services.concept_update(
                concept=concept, user=request.user, **s.validated_data
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
# Cotizaciones
# ===========================================================================


class QuoteListCreateApi(TenantAPIView):
    """GET  /api/v1/finanzas/cotizaciones/ — lista de cotizaciones.
    POST /api/v1/finanzas/cotizaciones/ — crea una cotización (borrador).
    """

    permission_classes = [IsAuthenticated, FinanceQuotePermission]

    class ItemSerializer(serializers.Serializer):
        concept_id = serializers.UUIDField(required=False, allow_null=True)
        description = serializers.CharField(max_length=200, required=False, allow_blank=True)
        quantity = serializers.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))
        unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
        discount = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class InputSerializer(serializers.Serializer):
        patient_id = serializers.UUIDField()
        valid_until = serializers.DateField(required=False, allow_null=True)
        notes = serializers.CharField(default="", allow_blank=True)
        items = serializers.ListField(child=serializers.DictField(), allow_empty=False)

    def get(self, request: Request) -> Response:
        patient_id = request.query_params.get("patient_id")
        qs = selectors.quote_list(
            patient_id=patient_id or None,
            status=request.query_params.get("status"),
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            QuoteOutputSerializer(page, many=True).data
        )

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            patient = patient_get(patient_id=s.validated_data["patient_id"])
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            quote = services.quote_create(
                tenant=tenant,
                user=request.user,
                patient=patient,
                items=s.validated_data["items"],
                valid_until=s.validated_data.get("valid_until"),
                notes=s.validated_data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(QuoteOutputSerializer(quote).data, status=status.HTTP_201_CREATED)


class QuoteDetailApi(TenantAPIView):
    """GET  /api/v1/finanzas/cotizaciones/<uuid>/  — detalle.
    PATCH /api/v1/finanzas/cotizaciones/<uuid>/  — rechazar/vencer (status).
    """

    permission_classes = [IsAuthenticated, FinanceQuotePermission]

    class InputSerializer(serializers.Serializer):
        status = serializers.ChoiceField(
            choices=[Quote.Status.REJECTED, Quote.Status.EXPIRED]
        )

    def _get_or_404(self, quote_id: uuid.UUID) -> "tuple[Quote | None, Response | None]":
        try:
            return selectors.quote_get(quote_id=quote_id), None
        except Quote.DoesNotExist:
            return None, Response(
                {"detail": "Cotización no encontrada."}, status=status.HTTP_404_NOT_FOUND
            )

    def get(self, request: Request, quote_id: uuid.UUID) -> Response:
        quote, err = self._get_or_404(quote_id)
        if err is not None:
            return err
        return Response(QuoteOutputSerializer(quote).data)

    def patch(self, request: Request, quote_id: uuid.UUID) -> Response:
        quote, err = self._get_or_404(quote_id)
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

    permission_classes = [IsAuthenticated, FinanceQuotePermission]

    def post(self, request: Request, quote_id: uuid.UUID) -> Response:
        try:
            quote = selectors.quote_get(quote_id=quote_id)
        except Quote.DoesNotExist:
            return Response(
                {"detail": "Cotización no encontrada."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            quote = services.quote_send(quote=quote, user=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(QuoteOutputSerializer(quote).data)


class QuoteAcceptApi(TenantAPIView):
    """POST /api/v1/finanzas/cotizaciones/<uuid>/aceptar/ — acepta y genera cargos."""

    permission_classes = [IsAuthenticated, FinanceQuotePermission]

    def post(self, request: Request, quote_id: uuid.UUID) -> Response:
        try:
            quote = selectors.quote_get(quote_id=quote_id)
        except Quote.DoesNotExist:
            return Response(
                {"detail": "Cotización no encontrada."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            quote = services.quote_accept(quote=quote, user=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(QuoteOutputSerializer(quote).data)


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
        raw_appointment = request.query_params.get("appointment") or None
        appointment_id: Optional[uuid.UUID] = None
        if raw_appointment:
            try:
                appointment_id = uuid.UUID(raw_appointment)
            except ValueError:
                return Response(
                    {"detail": "El parámetro 'appointment' debe ser un UUID válido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        qs = selectors.charge_list(
            patient_id=request.query_params.get("patient_id") or None,
            status=request.query_params.get("status"),
            appointment_id=appointment_id,
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            ChargeOutputSerializer(page, many=True).data
        )

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            patient = patient_get(patient_id=s.validated_data["patient_id"])
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

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
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ChargeOutputSerializer(charge).data, status=status.HTTP_201_CREATED)


class ChargeDetailApi(TenantAPIView):
    """GET    /api/v1/finanzas/cargos/<uuid>/  — detalle.
    DELETE /api/v1/finanzas/cargos/<uuid>/  — cancela el cargo.
    """

    permission_classes = [IsAuthenticated, FinanceChargePermission]

    def _get_or_404(self, charge_id: uuid.UUID) -> "tuple[Charge | None, Response | None]":
        try:
            return selectors.charge_get(charge_id=charge_id), None
        except Charge.DoesNotExist:
            return None, Response(
                {"detail": "Cargo no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

    def get(self, request: Request, charge_id: uuid.UUID) -> Response:
        charge, err = self._get_or_404(charge_id)
        if err is not None:
            return err
        return Response(ChargeOutputSerializer(charge).data)

    def delete(self, request: Request, charge_id: uuid.UUID) -> Response:
        charge, err = self._get_or_404(charge_id)
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
        method = serializers.ChoiceField(choices=Payment.Method.choices, default=Payment.Method.CASH)
        reference = serializers.CharField(max_length=120, default="", allow_blank=True)
        notes = serializers.CharField(default="", allow_blank=True)
        allocations = serializers.ListField(
            child=serializers.DictField(), required=False, default=list
        )

    def get(self, request: Request) -> Response:
        qs = selectors.payment_list(
            patient_id=request.query_params.get("patient_id") or None,
            method=request.query_params.get("method"),
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            PaymentOutputSerializer(page, many=True).data
        )

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            patient = patient_get(patient_id=s.validated_data["patient_id"])
        except Patient.DoesNotExist:
            return Response(
                {"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
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
            return Response(
                {"detail": "Pago no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
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
        qs = selectors.cfdi_list(
            patient_id=request.query_params.get("patient_id") or None,
            status=request.query_params.get("status"),
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            CfdiDocumentOutputSerializer(page, many=True).data
        )

    def post(self, request: Request) -> Response:
        tenant = _require_tenant()
        if tenant is None:
            return _NO_TENANT
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            payment = selectors.payment_get(payment_id=s.validated_data["payment_id"])
        except Payment.DoesNotExist:
            return Response(
                {"detail": "Pago no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
        data = dict(s.validated_data)
        data.pop("payment_id")
        try:
            cfdi = services.cfdi_issue(
                tenant=tenant, user=request.user, payment=payment, **data
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            CfdiDocumentOutputSerializer(cfdi).data, status=status.HTTP_201_CREATED
        )


class CfdiDetailApi(TenantAPIView):
    """GET /api/v1/finanzas/cfdi/<uuid>/ — detalle de un comprobante."""

    permission_classes = [IsAuthenticated, CfdiPermission]

    def get(self, request: Request, cfdi_id: uuid.UUID) -> Response:
        try:
            cfdi = selectors.cfdi_get(cfdi_id=cfdi_id)
        except CfdiDocument.DoesNotExist:
            return Response(
                {"detail": "CFDI no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(CfdiDocumentOutputSerializer(cfdi).data)


class CfdiCancelApi(TenantAPIView):
    """POST /api/v1/finanzas/cfdi/<uuid>/cancelar/ — cancela un comprobante."""

    permission_classes = [IsAuthenticated, CfdiPermission]

    class InputSerializer(serializers.Serializer):
        reason = serializers.ChoiceField(choices=["01", "02", "03", "04"], default="02")

    def post(self, request: Request, cfdi_id: uuid.UUID) -> Response:
        try:
            cfdi = selectors.cfdi_get(cfdi_id=cfdi_id)
        except CfdiDocument.DoesNotExist:
            return Response(
                {"detail": "CFDI no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
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
            return Response(
                {"detail": "Paciente no encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
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
    """GET /api/v1/finanzas/dashboard/ — KPIs y series para las gráficas."""

    permission_classes = [IsAuthenticated, FinanceDashboardPermission]

    def get(self, request: Request) -> Response:
        metrics = selectors.finance_dashboard_metrics(
            date_from=_parse_date(request.query_params.get("date_from")),
            date_to=_parse_date(request.query_params.get("date_to")),
        )
        return Response(metrics)
