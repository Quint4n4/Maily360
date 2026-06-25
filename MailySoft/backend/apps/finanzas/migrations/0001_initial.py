"""
Migración inicial del dominio finanzas.

Crea las tablas: finanzas_service_concepts, finanzas_fiscal_configs,
finanzas_quotes, finanzas_quote_items, finanzas_charges, finanzas_payments,
finanzas_payment_allocations, finanzas_cfdi_documents.

La activación de RLS por tenant va en 0002_enable_rls.py.
"""

import uuid
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenancy", "0003_alter_tenantmembership_unique_together_and_more"),
        ("pacientes", "0001_initial"),
        ("agenda", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceConcept",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, help_text="NULL = activo. Rellenar para borrado lógico.", null=True)),
                ("name", models.CharField(help_text="Nombre del servicio o concepto cobrable.", max_length=160)),
                ("description", models.TextField(blank=True, default="", help_text="Descripción opcional del concepto.")),
                ("base_price", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Precio de referencia (MXN). Se copia como snapshot en cotizaciones y cargos.", max_digits=12)),
                ("sat_product_key", models.CharField(blank=True, default="", help_text="Clave de producto/servicio del SAT (ClaveProdServ). Requerida para CFDI.", max_length=10)),
                ("sat_unit_key", models.CharField(blank=True, default="E48", help_text="Clave de unidad del SAT (ClaveUnidad). Default E48 = Unidad de servicio.", max_length=10)),
                ("is_active", models.BooleanField(db_index=True, default=True, help_text="False = concepto desactivado (no aparece en nuevos documentos).")),
                ("created_by", models.ForeignKey(blank=True, help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(help_text="Clínica a la que pertenece este registro.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenancy.tenant")),
            ],
            options={
                "db_table": "finanzas_service_concepts",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="ClinicFiscalConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, help_text="NULL = activo. Rellenar para borrado lógico.", null=True)),
                ("rfc", models.CharField(blank=True, default="", help_text="RFC del emisor (clínica). 12-13 caracteres.", max_length=13)),
                ("legal_name", models.CharField(blank=True, default="", help_text="Razón social del emisor tal como aparece en la Constancia de Situación Fiscal.", max_length=255)),
                ("tax_regime", models.CharField(blank=True, default="", help_text="Régimen fiscal del emisor (clave SAT c_RegimenFiscal, ej. 601, 612).", max_length=5)),
                ("postal_code", models.CharField(blank=True, default="", help_text="Código postal del domicilio fiscal del emisor (LugarExpedicion).", max_length=5)),
                ("series", models.CharField(default="A", help_text="Serie del comprobante interno.", max_length=10)),
                ("next_folio", models.PositiveIntegerField(default=1, help_text="Próximo folio consecutivo interno a asignar.")),
                ("created_by", models.ForeignKey(blank=True, help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(help_text="Clínica a la que pertenece este registro.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenancy.tenant")),
            ],
            options={
                "db_table": "finanzas_fiscal_configs",
            },
        ),
        migrations.CreateModel(
            name="Quote",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, help_text="NULL = activo. Rellenar para borrado lógico.", null=True)),
                ("status", models.CharField(choices=[("draft", "Borrador"), ("sent", "Enviada"), ("accepted", "Aceptada"), ("rejected", "Rechazada"), ("expired", "Vencida")], db_index=True, default="draft", help_text="Estado de la cotización.", max_length=10)),
                ("valid_until", models.DateField(blank=True, help_text="Fecha límite de vigencia de la cotización.", null=True)),
                ("notes", models.TextField(blank=True, default="", help_text="Notas o condiciones de la cotización.")),
                ("subtotal", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Suma de importes de línea antes de descuentos (snapshot).", max_digits=12)),
                ("discount_total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Suma de descuentos aplicados (snapshot).", max_digits=12)),
                ("total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Total a pagar (subtotal - descuentos) (snapshot).", max_digits=12)),
                ("created_by", models.ForeignKey(blank=True, help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("patient", models.ForeignKey(help_text="Paciente al que se dirige la cotización.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="pacientes.patient")),
                ("tenant", models.ForeignKey(help_text="Clínica a la que pertenece este registro.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenancy.tenant")),
            ],
            options={
                "db_table": "finanzas_quotes",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="QuoteItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, help_text="NULL = activo. Rellenar para borrado lógico.", null=True)),
                ("description", models.CharField(help_text="Descripción de la línea (snapshot del concepto al crearse).", max_length=200)),
                ("quantity", models.DecimalField(decimal_places=2, default=Decimal("1.00"), help_text="Cantidad.", max_digits=10)),
                ("unit_price", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Precio unitario (snapshot).", max_digits=12)),
                ("discount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Descuento aplicado a la línea (monto, no porcentaje).", max_digits=12)),
                ("line_total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Importe de la línea = cantidad * precio - descuento (calculado).", max_digits=12)),
                ("concept", models.ForeignKey(blank=True, help_text="Concepto del catálogo (opcional; la descripción es el snapshot).", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="finanzas.serviceconcept")),
                ("created_by", models.ForeignKey(blank=True, help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("quote", models.ForeignKey(help_text="Cotización a la que pertenece la línea.", on_delete=django.db.models.deletion.CASCADE, related_name="items", to="finanzas.quote")),
                ("tenant", models.ForeignKey(help_text="Clínica a la que pertenece este registro.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenancy.tenant")),
            ],
            options={
                "db_table": "finanzas_quote_items",
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="Charge",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, help_text="NULL = activo. Rellenar para borrado lógico.", null=True)),
                ("description", models.CharField(help_text="Descripción del cargo (snapshot).", max_length=200)),
                ("amount", models.DecimalField(decimal_places=2, help_text="Monto total del cargo (MXN).", max_digits=12)),
                ("amount_paid", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Monto liquidado hasta ahora (suma de aplicaciones de pago).", max_digits=12)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("partial", "Parcial"), ("paid", "Pagado"), ("cancelled", "Cancelado")], db_index=True, default="pending", help_text="Estado de cobro del cargo.", max_length=10)),
                ("issued_at", models.DateTimeField(db_index=True, help_text="Fecha de emisión del cargo (para el aging de cuentas por cobrar).")),
                ("appointment", models.ForeignKey(blank=True, help_text="Cita que originó el cargo (opcional).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="agenda.appointment")),
                ("concept", models.ForeignKey(blank=True, help_text="Concepto del catálogo (opcional).", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="finanzas.serviceconcept")),
                ("created_by", models.ForeignKey(blank=True, help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("patient", models.ForeignKey(help_text="Paciente al que se le carga el adeudo.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="pacientes.patient")),
                ("quote", models.ForeignKey(blank=True, help_text="Cotización que originó el cargo (opcional).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="charges", to="finanzas.quote")),
                ("tenant", models.ForeignKey(help_text="Clínica a la que pertenece este registro.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenancy.tenant")),
            ],
            options={
                "db_table": "finanzas_charges",
                "ordering": ["-issued_at"],
            },
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, help_text="NULL = activo. Rellenar para borrado lógico.", null=True)),
                ("amount", models.DecimalField(decimal_places=2, help_text="Monto del pago (MXN).", max_digits=12)),
                ("method", models.CharField(choices=[("cash", "Efectivo"), ("card", "Tarjeta"), ("transfer", "Transferencia"), ("other", "Otro")], db_index=True, default="cash", help_text="Método de pago.", max_length=10)),
                ("reference", models.CharField(blank=True, default="", help_text="Referencia de la transacción (autorización, folio terminal, etc.).", max_length=120)),
                ("received_at", models.DateTimeField(db_index=True, help_text="Fecha y hora en que se recibió el pago.")),
                ("notes", models.TextField(blank=True, default="", help_text="Notas internas del pago.")),
                ("created_by", models.ForeignKey(blank=True, help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("patient", models.ForeignKey(help_text="Paciente que realiza el pago.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="pacientes.patient")),
                ("tenant", models.ForeignKey(help_text="Clínica a la que pertenece este registro.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenancy.tenant")),
            ],
            options={
                "db_table": "finanzas_payments",
                "ordering": ["-received_at"],
            },
        ),
        migrations.CreateModel(
            name="PaymentAllocation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, help_text="NULL = activo. Rellenar para borrado lógico.", null=True)),
                ("amount", models.DecimalField(decimal_places=2, help_text="Monto del pago aplicado a este cargo.", max_digits=12)),
                ("charge", models.ForeignKey(help_text="Cargo al que se aplica el pago.", on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="finanzas.charge")),
                ("created_by", models.ForeignKey(blank=True, help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("payment", models.ForeignKey(help_text="Pago del que proviene esta aplicación.", on_delete=django.db.models.deletion.CASCADE, related_name="allocations", to="finanzas.payment")),
                ("tenant", models.ForeignKey(help_text="Clínica a la que pertenece este registro.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenancy.tenant")),
            ],
            options={
                "db_table": "finanzas_payment_allocations",
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="CfdiDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, help_text="NULL = activo. Rellenar para borrado lógico.", null=True)),
                ("status", models.CharField(choices=[("draft", "Borrador"), ("stamped", "Timbrado"), ("cancelled", "Cancelado")], db_index=True, default="draft", help_text="Estado del comprobante.", max_length=10)),
                ("series", models.CharField(blank=True, default="", help_text="Serie del comprobante.", max_length=10)),
                ("folio", models.PositiveIntegerField(blank=True, help_text="Folio interno consecutivo.", null=True)),
                ("uuid_sat", models.CharField(blank=True, db_index=True, default="", help_text="Folio fiscal (UUID) asignado por el SAT al timbrar.", max_length=36)),
                ("receptor_rfc", models.CharField(help_text="RFC del receptor.", max_length=13)),
                ("receptor_name", models.CharField(help_text="Razón social / nombre del receptor.", max_length=255)),
                ("receptor_tax_regime", models.CharField(blank=True, default="", help_text="Régimen fiscal del receptor (c_RegimenFiscal).", max_length=5)),
                ("receptor_postal_code", models.CharField(blank=True, default="", help_text="Código postal del receptor (DomicilioFiscalReceptor).", max_length=5)),
                ("cfdi_use", models.CharField(default="G03", help_text="Uso del CFDI (c_UsoCFDI, ej. G03 Gastos en general, D01 Honorarios médicos).", max_length=5)),
                ("payment_form", models.CharField(default="01", help_text="Forma de pago SAT (c_FormaPago, ej. 01 Efectivo, 03 Transferencia, 04 Tarjeta).", max_length=2)),
                ("payment_method", models.CharField(default="PUE", help_text="Método de pago SAT (PUE = pago en una exhibición, PPD = parcialidades/diferido).", max_length=3)),
                ("subtotal", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Subtotal del comprobante.", max_digits=12)),
                ("total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="Total del comprobante.", max_digits=12)),
                ("pac_id", models.CharField(blank=True, default="", help_text="Identificador del comprobante en el PAC (Facturama).", max_length=64)),
                ("xml_url", models.URLField(blank=True, default="", help_text="URL del XML timbrado.")),
                ("pdf_url", models.URLField(blank=True, default="", help_text="URL de la representación impresa (PDF).")),
                ("cancellation_reason", models.CharField(blank=True, default="", help_text="Motivo de cancelación SAT (01, 02, 03, 04).", max_length=2)),
                ("stamped_at", models.DateTimeField(blank=True, help_text="Fecha de timbrado.", null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, help_text="Fecha de cancelación.", null=True)),
                ("created_by", models.ForeignKey(blank=True, help_text="Usuario que creó el registro. Null en imports/seeds o si el usuario fue borrado.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("patient", models.ForeignKey(help_text="Paciente receptor del comprobante.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="pacientes.patient")),
                ("payment", models.ForeignKey(blank=True, help_text="Pago que comprueba este CFDI (opcional).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cfdi_documents", to="finanzas.payment")),
                ("tenant", models.ForeignKey(help_text="Clínica a la que pertenece este registro.", on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenancy.tenant")),
            ],
            options={
                "db_table": "finanzas_cfdi_documents",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="serviceconcept",
            constraint=models.UniqueConstraint(fields=("tenant", "name"), name="finanzas_concept_name_uniq"),
        ),
        migrations.AddConstraint(
            model_name="clinicfiscalconfig",
            constraint=models.UniqueConstraint(fields=("tenant",), name="finanzas_fiscal_config_tenant_uniq"),
        ),
        migrations.AddIndex(
            model_name="quote",
            index=models.Index(fields=["tenant", "patient", "status"], name="finanzas_quote_patient_idx"),
        ),
        migrations.AddIndex(
            model_name="charge",
            index=models.Index(fields=["tenant", "patient", "status"], name="finanzas_charge_patient_idx"),
        ),
        migrations.AddIndex(
            model_name="charge",
            index=models.Index(fields=["tenant", "status", "issued_at"], name="finanzas_charge_aging_idx"),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["tenant", "patient"], name="finanzas_payment_patient_idx"),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["tenant", "method", "received_at"], name="finanzas_payment_method_idx"),
        ),
        migrations.AddIndex(
            model_name="paymentallocation",
            index=models.Index(fields=["tenant", "charge"], name="finanzas_alloc_charge_idx"),
        ),
        migrations.AddIndex(
            model_name="cfdidocument",
            index=models.Index(fields=["tenant", "status"], name="finanzas_cfdi_status_idx"),
        ),
        migrations.AddIndex(
            model_name="cfdidocument",
            index=models.Index(fields=["tenant", "patient"], name="finanzas_cfdi_patient_idx"),
        ),
    ]
