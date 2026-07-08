"""
Modelos del dominio finanzas.

Subdominios:
  - Catálogos:     ServiceConcept (conceptos cobrables) + ClinicFiscalConfig (datos del emisor).
  - Cotizaciones:  Quote + QuoteItem (presupuestos previos al cobro).
  - Cuentas:       Charge (cuentas por cobrar del paciente).
  - Cobros:        Payment + PaymentAllocation (pagos y su aplicación a cargos).
  - Facturación:   CfdiDocument (comprobante fiscal CFDI 4.0 timbrado por el PAC).

Todos heredan de TenantAwareModel: tenant FK, created_by, soft-delete, UUID, timestamps.
Las tablas usan el prefijo `finanzas_`.

Montos: DecimalField(max_digits=12, decimal_places=2). NUNCA float para dinero.
"""

from decimal import Decimal

from django.db import models

from apps.core.models import TenantAwareModel

# Precisión monetaria estándar de la plataforma (hasta 9,999,999,999.99).
_MONEY_MAX_DIGITS = 12
_MONEY_DECIMALS = 2
ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------


class ServiceConcept(TenantAwareModel):
    """Concepto/servicio cobrable del catálogo de la clínica.

    Es la base de las líneas de cotización y de los cargos. El precio aquí es
    una referencia (`base_price`); el precio efectivo se copia (snapshot) en
    cada QuoteItem/Charge para que un cambio posterior del catálogo no altere
    documentos ya emitidos.

    Las claves SAT (producto/servicio y unidad) son opcionales aquí y solo se
    requieren al timbrar un CFDI.
    """

    name = models.CharField(
        max_length=160,
        help_text="Nombre del servicio o concepto cobrable.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Descripción opcional del concepto.",
    )
    base_price = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Precio de referencia (MXN). Se copia como snapshot en cotizaciones y cargos.",
    )
    sat_product_key = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Clave de producto/servicio del SAT (ClaveProdServ). Requerida para CFDI.",
    )
    sat_unit_key = models.CharField(
        max_length=10,
        blank=True,
        default="E48",
        help_text="Clave de unidad del SAT (ClaveUnidad). Default E48 = Unidad de servicio.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = concepto desactivado (no aparece en nuevos documentos).",
    )

    class Meta:
        db_table = "finanzas_service_concepts"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="finanzas_concept_name_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} (${self.base_price})"


class ClinicFiscalConfig(TenantAwareModel):
    """Datos fiscales del emisor (la clínica) para timbrar CFDI 4.0.

    Un único registro por tenant. NO almacena secretos: los certificados (CSD)
    y las credenciales del PAC (Facturama) se leen del entorno (django-environ),
    nunca de esta tabla ni del código.

    `series` + `next_folio` controlan el folio interno consecutivo del comprobante.
    """

    rfc = models.CharField(
        max_length=13,
        blank=True,
        default="",
        help_text="RFC del emisor (clínica). 12-13 caracteres.",
    )
    legal_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Razón social del emisor tal como aparece en la Constancia de Situación Fiscal.",
    )
    tax_regime = models.CharField(
        max_length=5,
        blank=True,
        default="",
        help_text="Régimen fiscal del emisor (clave SAT c_RegimenFiscal, ej. 601, 612).",
    )
    postal_code = models.CharField(
        max_length=5,
        blank=True,
        default="",
        help_text="Código postal del domicilio fiscal del emisor (LugarExpedicion).",
    )
    series = models.CharField(
        max_length=10,
        default="A",
        help_text="Serie del comprobante interno.",
    )
    next_folio = models.PositiveIntegerField(
        default=1,
        help_text="Próximo folio consecutivo interno a asignar.",
    )

    class Meta:
        db_table = "finanzas_fiscal_configs"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant"],
                name="finanzas_fiscal_config_tenant_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"Config fiscal {self.rfc or 'sin RFC'} ({self.tenant_id})"


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------


class Quote(TenantAwareModel):
    """Cotización (presupuesto) para un paciente.

    Máquina de estados:
        DRAFT → SENT → (ACCEPTED | REJECTED | EXPIRED)

    Los totales (subtotal, discount_total, total) son snapshots calculados a
    partir de los QuoteItem por el servicio; no se editan a mano vía API.
    Al aceptarse, `quote_accept` genera un Charge por cada item.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        SENT = "sent", "Enviada"
        ACCEPTED = "accepted", "Aceptada"
        REJECTED = "rejected", "Rechazada"
        EXPIRED = "expired", "Vencida"

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Paciente al que se dirige la cotización.",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        help_text="Estado de la cotización.",
    )
    valid_until = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha límite de vigencia de la cotización.",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Notas o condiciones de la cotización.",
    )
    subtotal = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Suma de importes de línea antes de descuentos (snapshot).",
    )
    discount_total = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Suma de descuentos aplicados (snapshot).",
    )
    total = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Total a pagar (subtotal - descuentos) (snapshot).",
    )

    class Meta:
        db_table = "finanzas_quotes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["tenant", "patient", "status"],
                name="finanzas_quote_patient_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Cotización {self.id} — {self.get_status_display()} (${self.total})"


class QuoteItem(TenantAwareModel):
    """Línea de una cotización.

    `description` y `unit_price` son snapshots: si el concepto del catálogo
    cambia luego, la cotización conserva los valores con los que se creó.
    `line_total` = quantity * unit_price - discount (lo calcula el servicio).
    """

    quote = models.ForeignKey(
        Quote,
        on_delete=models.CASCADE,
        related_name="items",
        help_text="Cotización a la que pertenece la línea.",
    )
    concept = models.ForeignKey(
        ServiceConcept,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        help_text="Concepto del catálogo (opcional; la descripción es el snapshot).",
    )
    description = models.CharField(
        max_length=200,
        help_text="Descripción de la línea (snapshot del concepto al crearse).",
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text="Cantidad.",
    )
    unit_price = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Precio unitario (snapshot).",
    )
    discount = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Descuento aplicado a la línea (monto, no porcentaje).",
    )
    line_total = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Importe de la línea = cantidad * precio - descuento (calculado).",
    )

    class Meta:
        db_table = "finanzas_quote_items"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.description} x{self.quantity} (${self.line_total})"


# ---------------------------------------------------------------------------
# Paquetes de tratamientos (catálogo reutilizable — Fase 3, Calendarización)
# ---------------------------------------------------------------------------


class TreatmentPackage(TenantAwareModel):
    """Paquete reutilizable de tratamientos del catálogo.

    Agrupa varias líneas (`TreatmentPackageItem`, cada una un `ServiceConcept`
    con un número de sesiones) bajo un nombre comercial (p. ej. "Paquete
    Rejuvenecimiento 6 sesiones"). Sirve como plantilla: `expediente.
    services_calendarizacion.treatment_plan_create_from_package` arma un
    `TreatmentPlan` NUEVO copiando (snapshot) el nombre/precio de cada
    concepto al momento de generarlo — el paquete en sí nunca se snapshotea,
    solo sus líneas se leen en vivo del catálogo (`base_price` vigente).
    """

    name = models.CharField(
        max_length=160,
        help_text="Nombre comercial del paquete de tratamientos.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Descripción opcional del paquete.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False = paquete desactivado (no aparece en el catálogo).",
    )

    class Meta:
        db_table = "finanzas_treatment_packages"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="finanzas_package_name_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"Paquete {self.name}"


class TreatmentPackageItem(TenantAwareModel):
    """Línea de un paquete de tratamientos: un concepto del catálogo + sesiones.

    A diferencia de `QuoteItem`/`TreatmentPlanItem`, esta línea NO guarda
    snapshot de nombre/precio: el paquete es una plantilla viva, siempre
    referencia al `ServiceConcept` vigente. El snapshot ocurre recién al
    generar un `TreatmentPlan` desde el paquete.
    """

    package = models.ForeignKey(
        TreatmentPackage,
        on_delete=models.CASCADE,
        related_name="items",
        help_text="Paquete al que pertenece esta línea.",
    )
    service_concept = models.ForeignKey(
        ServiceConcept,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Concepto/tratamiento del catálogo.",
    )
    sessions = models.PositiveSmallIntegerField(
        default=1,
        help_text="Número de sesiones de este tratamiento dentro del paquete.",
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Posición de la línea en la tabla del paquete.",
    )

    class Meta:
        db_table = "finanzas_treatment_package_items"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"PaqueteItem({self.id}) — paquete {self.package_id}"


# ---------------------------------------------------------------------------
# Cuentas por cobrar
# ---------------------------------------------------------------------------


class Charge(TenantAwareModel):
    """Cargo / cuenta por cobrar de un paciente.

    Representa un adeudo concreto (una consulta, un servicio cotizado, etc.).
    `amount_paid` es la suma de las PaymentAllocation que lo liquidan; el
    servicio lo mantiene y deriva `status` automáticamente:
        amount_paid == 0           → PENDING
        0 < amount_paid < amount   → PARTIAL
        amount_paid >= amount      → PAID
    `balance` (propiedad) = amount - amount_paid.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PARTIAL = "partial", "Parcial"
        PAID = "paid", "Pagado"
        CANCELLED = "cancelled", "Cancelado"

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Paciente al que se le carga el adeudo.",
    )
    concept = models.ForeignKey(
        ServiceConcept,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        help_text="Concepto del catálogo (opcional).",
    )
    description = models.CharField(
        max_length=200,
        help_text="Descripción del cargo (snapshot).",
    )
    appointment = models.ForeignKey(
        "agenda.Appointment",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        help_text="Cita que originó el cargo (opcional).",
    )
    quote = models.ForeignKey(
        Quote,
        on_delete=models.SET_NULL,
        related_name="charges",
        null=True,
        blank=True,
        help_text="Cotización que originó el cargo (opcional).",
    )
    amount = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        help_text="Monto total del cargo (MXN).",
    )
    amount_paid = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Monto liquidado hasta ahora (suma de aplicaciones de pago).",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        help_text="Estado de cobro del cargo.",
    )
    issued_at = models.DateTimeField(
        db_index=True,
        help_text="Fecha de emisión del cargo (para el aging de cuentas por cobrar).",
    )

    class Meta:
        db_table = "finanzas_charges"
        ordering = ["-issued_at"]
        indexes = [
            models.Index(
                fields=["tenant", "patient", "status"],
                name="finanzas_charge_patient_idx",
            ),
            models.Index(
                fields=["tenant", "status", "issued_at"],
                name="finanzas_charge_aging_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Cargo {self.description} (${self.amount}, {self.get_status_display()})"

    @property
    def balance(self) -> Decimal:
        """Saldo pendiente del cargo (amount - amount_paid)."""
        return self.amount - self.amount_paid


# ---------------------------------------------------------------------------
# Cobros / Pagos
# ---------------------------------------------------------------------------


class Payment(TenantAwareModel):
    """Pago recibido de un paciente.

    Un pago puede aplicarse a uno o varios cargos mediante PaymentAllocation
    (parcialidades). La suma de las aplicaciones no puede exceder el monto del
    pago; el remanente queda como crédito a favor del paciente.
    """

    class Method(models.TextChoices):
        CASH = "cash", "Efectivo"
        CARD = "card", "Tarjeta"
        TRANSFER = "transfer", "Transferencia"
        OTHER = "other", "Otro"

    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Paciente que realiza el pago.",
    )
    amount = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        help_text="Monto del pago (MXN).",
    )
    method = models.CharField(
        max_length=10,
        choices=Method.choices,
        default=Method.CASH,
        db_index=True,
        help_text="Método de pago.",
    )
    reference = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Referencia de la transacción (autorización, folio terminal, etc.).",
    )
    received_at = models.DateTimeField(
        db_index=True,
        help_text="Fecha y hora en que se recibió el pago.",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Notas internas del pago.",
    )

    class Meta:
        db_table = "finanzas_payments"
        ordering = ["-received_at"]
        indexes = [
            models.Index(
                fields=["tenant", "patient"],
                name="finanzas_payment_patient_idx",
            ),
            models.Index(
                fields=["tenant", "method", "received_at"],
                name="finanzas_payment_method_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Pago ${self.amount} ({self.get_method_display()})"


class PaymentAllocation(TenantAwareModel):
    """Aplicación de un pago a un cargo concreto (soporta parcialidades).

    Permite que un solo pago liquide varios cargos y que un cargo se liquide
    con varios pagos. `amount` es la porción del pago aplicada a ese cargo.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="allocations",
        help_text="Pago del que proviene esta aplicación.",
    )
    charge = models.ForeignKey(
        Charge,
        on_delete=models.PROTECT,
        related_name="allocations",
        help_text="Cargo al que se aplica el pago.",
    )
    amount = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        help_text="Monto del pago aplicado a este cargo.",
    )

    class Meta:
        db_table = "finanzas_payment_allocations"
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["tenant", "charge"],
                name="finanzas_alloc_charge_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Aplicación ${self.amount} → cargo {self.charge_id}"


# ---------------------------------------------------------------------------
# Facturación CFDI 4.0
# ---------------------------------------------------------------------------


class CfdiDocument(TenantAwareModel):
    """Comprobante Fiscal Digital por Internet (CFDI 4.0).

    Se emite (timbra) a través del PAC (Facturama). El folio fiscal (`uuid_sat`),
    el XML y el PDF los devuelve el PAC tras el timbrado.

    Máquina de estados:
        DRAFT → STAMPED → CANCELLED

    Se asocia opcionalmente al pago que comprueba. Las URLs de XML/PDF apuntan
    al PAC o a almacenamiento propio; el comprobante autoritativo vive en el SAT.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        STAMPED = "stamped", "Timbrado"
        CANCELLED = "cancelled", "Cancelado"

    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        related_name="cfdi_documents",
        null=True,
        blank=True,
        help_text="Pago que comprueba este CFDI (opcional).",
    )
    patient = models.ForeignKey(
        "pacientes.Patient",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Paciente receptor del comprobante.",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        help_text="Estado del comprobante.",
    )
    # --- Folio interno + folio fiscal del SAT ---
    series = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Serie del comprobante.",
    )
    folio = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Folio interno consecutivo.",
    )
    uuid_sat = models.CharField(
        max_length=36,
        blank=True,
        default="",
        db_index=True,
        help_text="Folio fiscal (UUID) asignado por el SAT al timbrar.",
    )
    # --- Datos del receptor (snapshot al emitir) ---
    receptor_rfc = models.CharField(
        max_length=13,
        help_text="RFC del receptor.",
    )
    receptor_name = models.CharField(
        max_length=255,
        help_text="Razón social / nombre del receptor.",
    )
    receptor_tax_regime = models.CharField(
        max_length=5,
        blank=True,
        default="",
        help_text="Régimen fiscal del receptor (c_RegimenFiscal).",
    )
    receptor_postal_code = models.CharField(
        max_length=5,
        blank=True,
        default="",
        help_text="Código postal del receptor (DomicilioFiscalReceptor).",
    )
    cfdi_use = models.CharField(
        max_length=5,
        default="G03",
        help_text="Uso del CFDI (c_UsoCFDI, ej. G03 Gastos en general, D01 Honorarios médicos).",
    )
    payment_form = models.CharField(
        max_length=2,
        default="01",
        help_text="Forma de pago SAT (c_FormaPago, ej. 01 Efectivo, 03 Transferencia, 04 Tarjeta).",
    )
    payment_method = models.CharField(
        max_length=3,
        default="PUE",
        help_text="Método de pago SAT (PUE = pago en una exhibición, PPD = parcialidades/diferido).",
    )
    subtotal = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Subtotal del comprobante.",
    )
    total = models.DecimalField(
        max_digits=_MONEY_MAX_DIGITS,
        decimal_places=_MONEY_DECIMALS,
        default=ZERO,
        help_text="Total del comprobante.",
    )
    # --- Artefactos del PAC ---
    pac_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Identificador del comprobante en el PAC (Facturama).",
    )
    xml_url = models.URLField(
        blank=True,
        default="",
        help_text="URL del XML timbrado.",
    )
    pdf_url = models.URLField(
        blank=True,
        default="",
        help_text="URL de la representación impresa (PDF).",
    )
    cancellation_reason = models.CharField(
        max_length=2,
        blank=True,
        default="",
        help_text="Motivo de cancelación SAT (01, 02, 03, 04).",
    )
    stamped_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha de timbrado.",
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha de cancelación.",
    )

    class Meta:
        db_table = "finanzas_cfdi_documents"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["tenant", "status"],
                name="finanzas_cfdi_status_idx",
            ),
            models.Index(
                fields=["tenant", "patient"],
                name="finanzas_cfdi_patient_idx",
            ),
        ]

    def __str__(self) -> str:
        ref = self.uuid_sat or f"{self.series}{self.folio or ''}"
        return f"CFDI {ref} — {self.get_status_display()} (${self.total})"
