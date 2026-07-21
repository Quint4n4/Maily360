"""
Serializers de salida del dominio finanzas.

Solo formatean/validan la salida; cero lógica de negocio. Los InputSerializer
se definen inline en cada view (cerca del contrato que validan).
"""

from decimal import Decimal

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
    TreatmentPackage,
    TreatmentPackageItem,
)


class _SucursalNestedSerializer(serializers.Serializer):
    """Representación mínima de la sucursal donde se generó el documento (Fase 3).

    Puede ser None (dato legado sin backfillar, o tenant sin sucursales).
    """

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


class ServiceConceptOutputSerializer(serializers.ModelSerializer):
    """Salida de un concepto cobrable.

    `sucursales` (multi-sede — decisión del dueño, 2026-07-16): lista
    [{id, name}] de las sedes donde el servicio está disponible. VACÍA =
    disponible en TODAS las sedes del tenant (convención del M2M vacío). El
    PRECIO (`base_price`) es el mismo en todas las sedes; esto solo informa
    disponibilidad.
    """

    sucursales = _SucursalNestedSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceConcept
        fields = [
            "id",
            "name",
            "description",
            "clinical_description",
            "base_price",
            "sat_product_key",
            "sat_unit_key",
            "is_active",
            "sucursales",
            "created_at",
        ]
        read_only_fields = fields


class QuoteItemOutputSerializer(serializers.ModelSerializer):
    """Salida de una línea de cotización.

    `discount` es el VALOR CAPTURADO (monto en $ o porcentaje, según
    `discount_type`); `discount_amount` es el descuento EFECTIVO ya
    calculado en $ (snapshot) — úsalo para mostrar/sumar sin reinterpretar
    `discount_type`.
    """

    class Meta:
        model = QuoteItem
        fields = [
            "id",
            "concept",
            "description",
            "quantity",
            "unit_price",
            "discount_type",
            "discount",
            "discount_amount",
            "line_total",
        ]
        read_only_fields = fields


class QuoteOutputSerializer(serializers.ModelSerializer):
    """Salida de una cotización con sus items.

    `discount_total` = descuento de renglón + descuento general (el total
    rebajado, en $). `global_discount_amount` desglosa cuánto de ese total
    corresponde SOLO al descuento general (derivado, no almacenado, para no
    duplicar el snapshot: `discount_total - Σ item.discount_amount`).
    """

    items = QuoteItemOutputSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    sucursal = _SucursalNestedSerializer(read_only=True, allow_null=True)
    global_discount_amount = serializers.SerializerMethodField()

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
            "global_discount_type",
            "global_discount_value",
            "global_discount_amount",
            "total",
            "items",
            "sucursal",
            "created_at",
        ]
        read_only_fields = fields

    def get_global_discount_amount(self, obj: Quote) -> str:
        """Descuento general EFECTIVO en $ (derivado de snapshots ya calculados).

        Requiere que `items` venga precargado (`quote_get`/`quote_list` ya lo
        hacen vía `prefetch_related("items")`) para no disparar una query extra.
        """
        line_discounts = sum((item.discount_amount for item in obj.items.all()), Decimal("0.00"))
        return str(obj.discount_total - line_discounts)


def _package_price(package: TreatmentPackage) -> Decimal:
    """Precio del paquete = suma(concept.base_price * sessions), leído EN VIVO.

    A diferencia de Quote/TreatmentPlan (que guardan snapshot), el paquete es
    una plantilla del catálogo: el precio mostrado siempre refleja el
    `base_price` vigente de cada `ServiceConcept`. Requiere que `items` venga
    precargado con `service_concept` (ver `apps.finanzas.selectors.package_get`
    / `package_list`) para no disparar N+1.
    """
    return sum(
        (item.service_concept.base_price * item.sessions for item in package.items.all()),
        Decimal("0.00"),
    )


class TreatmentPackageItemOutputSerializer(serializers.Serializer):
    """Salida de una línea de paquete (nombre/precio leídos en vivo del catálogo)."""

    concept_id = serializers.UUIDField(source="service_concept_id", read_only=True)
    description = serializers.SerializerMethodField()
    unit_price = serializers.SerializerMethodField()
    sessions = serializers.IntegerField(read_only=True)
    order = serializers.IntegerField(read_only=True)

    def get_description(self, obj: TreatmentPackageItem) -> str:
        return obj.service_concept.name

    def get_unit_price(self, obj: TreatmentPackageItem) -> str:
        return str(obj.service_concept.base_price)


class TreatmentPackageOutputSerializer(serializers.ModelSerializer):
    """Detalle de un paquete de tratamientos, con sus líneas anidadas.

    `sucursales` (multi-sede — decisión del dueño, 2026-07-16): lista
    [{id, name}] de las sedes donde el paquete está disponible. VACÍA =
    disponible en TODAS las sedes del tenant (convención del M2M vacío). El
    PRECIO no cambia por sede; esto solo informa disponibilidad.
    """

    price = serializers.SerializerMethodField()
    items = TreatmentPackageItemOutputSerializer(many=True, read_only=True)
    sucursales = _SucursalNestedSerializer(many=True, read_only=True)

    class Meta:
        model = TreatmentPackage
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "price",
            "items",
            "sucursales",
            "created_at",
        ]
        read_only_fields = fields

    def get_price(self, obj: TreatmentPackage) -> str:
        return str(_package_price(obj))


class TreatmentPackageListItemSerializer(serializers.ModelSerializer):
    """Salida resumida de un paquete para el listado (sin líneas anidadas)."""

    items_count = serializers.SerializerMethodField()
    sessions_total = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    sucursales = _SucursalNestedSerializer(many=True, read_only=True)

    class Meta:
        model = TreatmentPackage
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "items_count",
            "sessions_total",
            "price",
            "sucursales",
            "created_at",
        ]
        read_only_fields = fields

    def get_items_count(self, obj: TreatmentPackage) -> int:
        return len(obj.items.all())

    def get_sessions_total(self, obj: TreatmentPackage) -> int:
        return sum(item.sessions for item in obj.items.all())

    def get_price(self, obj: TreatmentPackage) -> str:
        return str(_package_price(obj))


class ChargeOutputSerializer(serializers.ModelSerializer):
    """Salida de un cargo / cuenta por cobrar."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    sucursal = _SucursalNestedSerializer(read_only=True, allow_null=True)

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
            "sucursal",
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
    sucursal = _SucursalNestedSerializer(read_only=True, allow_null=True)

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
            "sucursal",
            "created_at",
        ]
        read_only_fields = fields


class CfdiDocumentOutputSerializer(serializers.ModelSerializer):
    """Salida de un comprobante CFDI."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    sucursal = _SucursalNestedSerializer(read_only=True, allow_null=True)

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
            "sucursal",
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
