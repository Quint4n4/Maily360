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
from typing import Any, Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import (
    FINANCE_DESK_ROLES,
    CfdiPermission,
    ChargeListPermission,
    FinanceChargePermission,
    FinanceConceptPermission,
    FinanceConfigPermission,
    FinanceDashboardPermission,
    FinancePaymentPermission,
    FinanceQuotePermission,
    HasClinicRole,
    PatientStatementPermission,
    QuotePermission,
    RetentionPermission,
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
# PdfRenderer — reutiliza el patrón exacto de apps/recetas/views.py
# ---------------------------------------------------------------------------


class _PdfRenderer(BaseRenderer):
    """Renderer que permite a DRF negociar Accept: application/pdf.

    La vista devuelve HttpResponse directo, pero DRF ejecuta la negociación de
    contenido al entrar. Sin este renderer, un cliente que envíe
    Accept: application/pdf recibiría 406. El método render() no se usa
    (la vista responde con HttpResponse crudo).
    """

    media_type = "application/pdf"
    format = "pdf"
    charset = None

    def render(self, data: Any, accepted_media_type: Any = None, renderer_context: Any = None) -> Any:  # type: ignore[override]
        return data


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
        # Toggle de estado: se maneja por separado (reactivar/desactivar), no como campo editable.
        is_active = serializers.BooleanField(required=False)

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
        try:
            # El toggle de estado va por su propio service (no por concept_update,
            # que trata is_active como inmutable).
            if is_active is not None:
                if is_active:
                    concept = services.concept_reactivate(concept=concept, user=request.user)
                else:
                    concept = services.concept_deactivate(concept=concept, user=request.user)
            if data:
                concept = services.concept_update(
                    concept=concept, user=request.user, **data
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

    permission_classes = [IsAuthenticated, QuotePermission]

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

    permission_classes = [IsAuthenticated, QuotePermission]

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

    permission_classes = [IsAuthenticated, QuotePermission]

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

    permission_classes = [IsAuthenticated, QuotePermission]

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


class QuotePdfApi(TenantAPIView):
    """GET /api/v1/finanzas/cotizaciones/<uuid>/pdf/ — PDF de la cotización.

    Devuelve el PDF con Content-Disposition: inline para abrir en el navegador.
    Requiere Accept: application/pdf; sin ese header DRF responde 406.

    Permiso: QuotePermission (mismos roles que el resto de endpoints de cotización).
    Auth: Bearer token (el endpoint NO es público — contiene datos del paciente).

    Seguridad:
        - WeasyPrint usa _secure_fetcher: bloquea LFI/SSRF (solo data URIs).
        - X-Frame-Options: DENY, X-Content-Type-Options: nosniff.
        - Si la generación falla, devuelve 500 con mensaje genérico (sin stack trace).
    """

    permission_classes = [IsAuthenticated, QuotePermission]
    renderer_classes = [_PdfRenderer]

    def get(self, request: Request, quote_id: uuid.UUID) -> HttpResponse:
        try:
            quote = selectors.quote_get(quote_id=quote_id)
        except Quote.DoesNotExist:
            return HttpResponse(
                content=b"Cotizaci\xf3n no encontrada.",
                status=404,
                content_type="text/plain; charset=utf-8",
            )

        tenant = get_current_tenant()

        from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
        from apps.finanzas.pdf import quote_pdf_build  # noqa: PLC0415

        clinic_settings = (
            clinic_settings_get(tenant_id=tenant.id) if tenant is not None else None
        )

        try:
            pdf_bytes = quote_pdf_build(quote=quote, clinic_settings=clinic_settings)
        except RuntimeError as exc:
            logger.error(
                "QuotePdfApi: error al generar PDF de cotización %s — %s",
                quote_id,
                exc,
            )
            return HttpResponse(
                content=b"Error al generar el PDF. Intente nuevamente.",
                status=500,
                content_type="text/plain",
            )

        folio_short = str(quote.id).replace("-", "")[:8].upper()
        filename = f"cotizacion-{folio_short}.pdf"
        response = HttpResponse(content=pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"
        return response


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
    renderer_classes = [_PdfRenderer]

    def get(self, request: Request) -> HttpResponse:
        today = datetime.date.today()
        date_from = _parse_date(request.query_params.get("date_from")) or (
            today - datetime.timedelta(days=30)
        )
        date_to = _parse_date(request.query_params.get("date_to")) or today

        if date_from > date_to:
            return HttpResponse(
                content=b"date_from no puede ser posterior a date_to.",
                status=400,
                content_type="text/plain",
            )

        group = request.query_params.get("group", "day")
        if group not in _VALID_GROUPS:
            group = "day"

        tenant = get_current_tenant()

        from apps.clinica.selectors import clinic_settings_get  # noqa: PLC0415
        from apps.finanzas.pdf import finance_report_pdf_build  # noqa: PLC0415

        clinic_settings = (
            clinic_settings_get(tenant_id=tenant.id) if tenant is not None else None
        )

        report = selectors.finance_period_report(
            date_from=date_from,
            date_to=date_to,
            group=group,
        )

        try:
            pdf_bytes = finance_report_pdf_build(report=report, clinic_settings=clinic_settings)
        except RuntimeError as exc:
            logger.error(
                "PeriodReportPdfApi: error al generar PDF — %s",
                exc,
            )
            return HttpResponse(
                content=b"Error al generar el PDF. Intente nuevamente.",
                status=500,
                content_type="text/plain",
            )

        filename = f"reporte-{date_from}-{date_to}.pdf"
        response = HttpResponse(content=pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"
        return response


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

        sheet = selectors.finance_daily_sheet(date=sheet_date)
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
    """

    permission_classes = [IsAuthenticated, RetentionPermission]

    def get(self, request: Request) -> Response:
        tenant = get_current_tenant()
        if tenant is None:
            return _NO_TENANT

        from apps.finanzas.retention import retention_panel_build  # noqa: PLC0415

        panel = retention_panel_build(tenant_id=tenant.id)
        return Response(panel)
