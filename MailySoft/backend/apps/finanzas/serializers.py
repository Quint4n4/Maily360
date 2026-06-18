"""
Serializers de salida del dominio finanzas.

Solo formatean/validan la salida; cero lógica de negocio. Los InputSerializer
se definen inline en cada view (cerca del contrato que validan).
"""

from rest_framework import serializers

from apps.finanzas.models import (
    CfdiDocument,
    Charge,
    ClinicFiscalConfig,
    Payment,
    PaymentAllocation,
    Quote,
    QuoteItem,
    ServiceConcept,
)


class ServiceConceptOutputSerializer(serializers.ModelSerializer):
    """Salida de un concepto cobrable."""

    class Meta:
        model = ServiceConcept
        fields = [
            "id",
            "name",
            "description",
            "base_price",
            "sat_product_key",
            "sat_unit_key",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class QuoteItemOutputSerializer(serializers.ModelSerializer):
    """Salida de una línea de cotización."""

    class Meta:
        model = QuoteItem
        fields = [
            "id",
            "concept",
            "description",
            "quantity",
            "unit_price",
            "discount",
            "line_total",
        ]
        read_only_fields = fields


class QuoteOutputSerializer(serializers.ModelSerializer):
    """Salida de una cotización con sus items."""

    items = QuoteItemOutputSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Quote
        fields = [
            "id",
            "patient",
            "status",
            "status_display",
            "valid_until",
            "notes",
            "subtotal",
            "discount_total",
            "total",
            "items",
            "created_at",
        ]
        read_only_fields = fields


class ChargeOutputSerializer(serializers.ModelSerializer):
    """Salida de un cargo / cuenta por cobrar."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    balance = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = Charge
        fields = [
            "id",
            "patient",
            "concept",
            "description",
            "appointment",
            "quote",
            "amount",
            "amount_paid",
            "balance",
            "status",
            "status_display",
            "issued_at",
            "created_at",
        ]
        read_only_fields = fields


class PaymentAllocationOutputSerializer(serializers.ModelSerializer):
    """Salida de una aplicación de pago."""

    class Meta:
        model = PaymentAllocation
        fields = ["id", "charge", "amount"]
        read_only_fields = fields


class PaymentOutputSerializer(serializers.ModelSerializer):
    """Salida de un pago con sus aplicaciones."""

    allocations = PaymentAllocationOutputSerializer(many=True, read_only=True)
    method_display = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "patient",
            "amount",
            "method",
            "method_display",
            "reference",
            "received_at",
            "notes",
            "allocations",
            "created_at",
        ]
        read_only_fields = fields


class CfdiDocumentOutputSerializer(serializers.ModelSerializer):
    """Salida de un comprobante CFDI."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = CfdiDocument
        fields = [
            "id",
            "payment",
            "patient",
            "status",
            "status_display",
            "series",
            "folio",
            "uuid_sat",
            "receptor_rfc",
            "receptor_name",
            "receptor_tax_regime",
            "receptor_postal_code",
            "cfdi_use",
            "payment_form",
            "payment_method",
            "subtotal",
            "total",
            "pac_id",
            "xml_url",
            "pdf_url",
            "cancellation_reason",
            "stamped_at",
            "cancelled_at",
            "created_at",
        ]
        read_only_fields = fields


class ClinicFiscalConfigOutputSerializer(serializers.ModelSerializer):
    """Salida de la configuración fiscal del emisor (sin secretos)."""

    class Meta:
        model = ClinicFiscalConfig
        fields = [
            "id",
            "rfc",
            "legal_name",
            "tax_regime",
            "postal_code",
            "series",
            "next_folio",
            "created_at",
        ]
        read_only_fields = fields
