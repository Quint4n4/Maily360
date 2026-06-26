"""
Services del dominio finanzas.

Toda escritura/modificación pasa por aquí. Las vistas son delgadas: parsean,
llaman al service, devuelven la respuesta.

Convenciones (django-clean-architecture):
  - keyword-only args en toda firma; nombrado acción+entidad.
  - transaction.atomic() en operaciones multi-tabla.
  - audit_record() en cada mutación relevante (sin PII en metadata).
  - Validación de aislamiento: related.tenant_id == tenant.id (defensa en
    profundidad sobre RLS).
  - _IMMUTABLE_FIELDS en updates para evitar cambios de campos sensibles.

El timbrado/cancelación de CFDI delega en el adapter (adapters/cfdi.py); este
módulo nunca llama al PAC directamente.
"""

import datetime
import uuid
from decimal import Decimal
from typing import Any, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from adapters.cfdi import get_cfdi_adapter
from apps.audit.models import ActionType
from apps.audit.services import audit_record
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
from apps.pacientes.models import Patient
from apps.tenancy.models import Tenant

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _ensure_same_tenant(*, tenant: Tenant, obj: Any, label: str) -> None:
    """Valida que `obj` pertenezca al mismo tenant (defensa en profundidad).

    Raises:
        ValidationError: si el objeto pertenece a otro tenant.
    """
    if obj is not None and getattr(obj, "tenant_id", None) != tenant.id:
        raise ValidationError(f"{label} no pertenece a esta clínica.")


def _q2(value: Decimal) -> Decimal:
    """Cuantiza a 2 decimales (centavos)."""
    return value.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Conceptos (catálogo)
# ---------------------------------------------------------------------------


def concept_create(
    *,
    tenant: Tenant,
    user: Any,
    name: str,
    base_price: Decimal = ZERO,
    description: str = "",
    sat_product_key: str = "",
    sat_unit_key: str = "E48",
) -> ServiceConcept:
    """Crea un concepto cobrable en el catálogo del tenant.

    Raises:
        ValidationError: si ya existe un concepto con el mismo nombre.
    """
    if ServiceConcept.all_objects.filter(
        tenant=tenant, name=name, deleted_at__isnull=True
    ).exists():
        raise ValidationError("Ya existe un concepto con ese nombre en esta clínica.")

    concept = ServiceConcept.objects.create(
        tenant=tenant,
        created_by=user,
        name=name,
        base_price=base_price,
        description=description,
        sat_product_key=sat_product_key,
        sat_unit_key=sat_unit_key,
    )
    audit_record(
        action=ActionType.CONCEPT_CREATE,
        resource_type="ServiceConcept",
        actor=user,
        tenant=tenant,
        resource_id=concept.id,
        resource_repr=concept.name,
    )
    return concept


_CONCEPT_IMMUTABLE: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "deleted_at", "updated_at", "is_active"}
)


def concept_update(
    *,
    concept: ServiceConcept,
    user: Any,
    **fields: object,
) -> ServiceConcept:
    """Actualiza campos permitidos de un concepto del catálogo.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable o el nuevo
                         nombre colisiona con otro concepto del tenant.
    """
    attempted = _CONCEPT_IMMUTABLE.intersection(fields.keys())
    if attempted:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(attempted))}."
        )

    new_name = fields.get("name")
    if new_name is not None and new_name != concept.name:
        if ServiceConcept.all_objects.filter(
            tenant=concept.tenant, name=new_name, deleted_at__isnull=True
        ).exclude(id=concept.id).exists():
            raise ValidationError("Ya existe un concepto con ese nombre en esta clínica.")

    for field_name, value in fields.items():
        setattr(concept, field_name, value)
    concept.save(update_fields=list(fields.keys()) + ["updated_at"])

    audit_record(
        action=ActionType.CONCEPT_UPDATE,
        resource_type="ServiceConcept",
        actor=user,
        tenant=concept.tenant,
        resource_id=concept.id,
        resource_repr=concept.name,
        metadata={"changed_fields": sorted(fields.keys())},
    )
    return concept


def concept_deactivate(*, concept: ServiceConcept, user: Any) -> ServiceConcept:
    """Desactiva un concepto (no borra; deja de aparecer en nuevos documentos)."""
    concept.is_active = False
    concept.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.CONCEPT_DEACTIVATE,
        resource_type="ServiceConcept",
        actor=user,
        tenant=concept.tenant,
        resource_id=concept.id,
        resource_repr=concept.name,
    )
    return concept


def concept_reactivate(*, concept: ServiceConcept, user: Any) -> ServiceConcept:
    """Reactiva un concepto previamente desactivado (vuelve a aparecer en el catálogo)."""
    concept.is_active = True
    concept.save(update_fields=["is_active", "updated_at"])
    audit_record(
        action=ActionType.CONCEPT_UPDATE,
        resource_type="ServiceConcept",
        actor=user,
        tenant=concept.tenant,
        resource_id=concept.id,
        resource_repr=concept.name,
        metadata={"reactivated": True},
    )
    return concept


# ---------------------------------------------------------------------------
# Configuración fiscal
# ---------------------------------------------------------------------------


def fiscal_config_get_or_create(*, tenant: Tenant, user: Any) -> ClinicFiscalConfig:
    """Obtiene la configuración fiscal del tenant, creándola vacía si no existe."""
    config, _created = ClinicFiscalConfig.all_objects.get_or_create(
        tenant=tenant,
        defaults={"created_by": user},
    )
    return config


_FISCAL_IMMUTABLE: frozenset[str] = frozenset(
    {"id", "tenant", "tenant_id", "created_at", "deleted_at", "updated_at", "next_folio"}
)


def clinic_fiscal_config_update(
    *,
    tenant: Tenant,
    user: Any,
    **fields: object,
) -> ClinicFiscalConfig:
    """Actualiza los datos fiscales del emisor (RFC, razón social, régimen, etc.).

    NO acepta secretos (CSD/credenciales del PAC); esos viven en el entorno.

    Raises:
        ValidationError: si se intenta modificar un campo inmutable.
    """
    attempted = _FISCAL_IMMUTABLE.intersection(fields.keys())
    if attempted:
        raise ValidationError(
            f"No se pueden modificar los campos: {', '.join(sorted(attempted))}."
        )

    config = fiscal_config_get_or_create(tenant=tenant, user=user)
    for field_name, value in fields.items():
        setattr(config, field_name, value)
    config.save(update_fields=list(fields.keys()) + ["updated_at"])

    audit_record(
        action=ActionType.FISCAL_CONFIG_UPDATE,
        resource_type="ClinicFiscalConfig",
        actor=user,
        tenant=tenant,
        resource_id=config.id,
        resource_repr=config.rfc or "config-fiscal",
        metadata={"changed_fields": sorted(fields.keys())},
    )
    return config


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------


def _recalc_quote_totals(*, quote: Quote) -> None:
    """Recalcula subtotal/descuento/total de una cotización desde sus items."""
    subtotal = ZERO
    discount = ZERO
    for item in quote.items.all():
        subtotal += item.quantity * item.unit_price
        discount += item.discount
    quote.subtotal = _q2(subtotal)
    quote.discount_total = _q2(discount)
    quote.total = _q2(subtotal - discount)
    quote.save(update_fields=["subtotal", "discount_total", "total", "updated_at"])


def quote_create(
    *,
    tenant: Tenant,
    user: Any,
    patient: Patient,
    items: list[dict[str, Any]],
    valid_until: Optional[datetime.date] = None,
    notes: str = "",
) -> Quote:
    """Crea una cotización en estado DRAFT con sus líneas.

    Cada item: {concept_id?, description, quantity, unit_price, discount?}.
    El `description` y `unit_price` se guardan como snapshot.

    Raises:
        ValidationError: si el paciente es de otro tenant, no hay items, o un
                         concepto referenciado es de otro tenant.
    """
    _ensure_same_tenant(tenant=tenant, obj=patient, label="El paciente")
    if not items:
        raise ValidationError("La cotización debe tener al menos una línea.")

    with transaction.atomic():
        quote = Quote.objects.create(
            tenant=tenant,
            created_by=user,
            patient=patient,
            status=Quote.Status.DRAFT,
            valid_until=valid_until,
            notes=notes,
        )
        for raw in items:
            _create_quote_item(tenant=tenant, user=user, quote=quote, raw=raw)
        _recalc_quote_totals(quote=quote)

    audit_record(
        action=ActionType.QUOTE_CREATE,
        resource_type="Quote",
        actor=user,
        tenant=tenant,
        resource_id=quote.id,
        resource_repr=str(quote.id),
        metadata={"items": len(items)},
    )
    return quote


def _create_quote_item(
    *,
    tenant: Tenant,
    user: Any,
    quote: Quote,
    raw: dict[str, Any],
) -> QuoteItem:
    """Crea una línea de cotización a partir de un dict de entrada (con snapshot)."""
    concept: Optional[ServiceConcept] = None
    concept_id = raw.get("concept_id")
    if concept_id:
        concept = ServiceConcept.objects.filter(id=concept_id).first()
        if concept is None:
            raise ValidationError("Concepto no encontrado en esta clínica.")

    quantity = Decimal(str(raw.get("quantity", "1")))
    unit_price = Decimal(str(raw.get("unit_price", concept.base_price if concept else "0")))
    discount = Decimal(str(raw.get("discount", "0")))
    description = raw.get("description") or (concept.name if concept else "")
    if not description:
        raise ValidationError("Cada línea requiere una descripción o un concepto.")

    line_total = _q2(quantity * unit_price - discount)
    if line_total < ZERO:
        raise ValidationError("El descuento no puede superar el importe de la línea.")

    return QuoteItem.objects.create(
        tenant=tenant,
        created_by=user,
        quote=quote,
        concept=concept,
        description=description,
        quantity=quantity,
        unit_price=_q2(unit_price),
        discount=_q2(discount),
        line_total=line_total,
    )


def quote_send(*, quote: Quote, user: Any) -> Quote:
    """Marca una cotización como enviada (DRAFT → SENT).

    Raises:
        ValidationError: si la cotización no está en borrador.
    """
    if quote.status != Quote.Status.DRAFT:
        raise ValidationError("Solo se pueden enviar cotizaciones en borrador.")
    quote.status = Quote.Status.SENT
    quote.save(update_fields=["status", "updated_at"])
    audit_record(
        action=ActionType.QUOTE_STATUS,
        resource_type="Quote",
        actor=user,
        tenant=quote.tenant,
        resource_id=quote.id,
        resource_repr=str(quote.id),
        metadata={"new_status": Quote.Status.SENT},
    )
    return quote


def quote_accept(*, quote: Quote, user: Any) -> Quote:
    """Acepta una cotización (→ ACCEPTED) y genera un Charge por cada línea.

    Solo desde DRAFT o SENT. Es idempotente respecto a la generación: una
    cotización ya aceptada no vuelve a generar cargos.

    Raises:
        ValidationError: si la cotización ya está aceptada/rechazada/vencida.
    """
    if quote.status not in (Quote.Status.DRAFT, Quote.Status.SENT):
        raise ValidationError(
            "Solo se pueden aceptar cotizaciones en borrador o enviadas."
        )

    now = timezone.now()
    with transaction.atomic():
        quote.status = Quote.Status.ACCEPTED
        quote.save(update_fields=["status", "updated_at"])
        for item in quote.items.all():
            Charge.objects.create(
                tenant=quote.tenant,
                created_by=user,
                patient=quote.patient,
                concept=item.concept,
                description=item.description,
                quote=quote,
                amount=item.line_total,
                amount_paid=ZERO,
                status=Charge.Status.PENDING,
                issued_at=now,
            )

    audit_record(
        action=ActionType.QUOTE_STATUS,
        resource_type="Quote",
        actor=user,
        tenant=quote.tenant,
        resource_id=quote.id,
        resource_repr=str(quote.id),
        metadata={"new_status": Quote.Status.ACCEPTED, "charges_created": quote.items.count()},
    )
    return quote


def quote_set_status(*, quote: Quote, user: Any, status: str) -> Quote:
    """Cambia el estado de una cotización a rejected/expired (transiciones simples)."""
    valid = {Quote.Status.REJECTED, Quote.Status.EXPIRED}
    if status not in valid:
        raise ValidationError("Estado de cotización no permitido por esta acción.")
    quote.status = status
    quote.save(update_fields=["status", "updated_at"])
    audit_record(
        action=ActionType.QUOTE_STATUS,
        resource_type="Quote",
        actor=user,
        tenant=quote.tenant,
        resource_id=quote.id,
        resource_repr=str(quote.id),
        metadata={"new_status": status},
    )
    return quote


# ---------------------------------------------------------------------------
# Cargos
# ---------------------------------------------------------------------------


def charge_create(
    *,
    tenant: Tenant,
    user: Any,
    patient: Patient,
    amount: Decimal,
    description: str,
    concept: Optional[ServiceConcept] = None,
    appointment: Optional[Any] = None,
    issued_at: Optional[datetime.datetime] = None,
) -> Charge:
    """Crea un cargo (cuenta por cobrar) para un paciente.

    Raises:
        ValidationError: si el monto no es positivo o las relaciones son de otro tenant.
    """
    _ensure_same_tenant(tenant=tenant, obj=patient, label="El paciente")
    _ensure_same_tenant(tenant=tenant, obj=concept, label="El concepto")
    _ensure_same_tenant(tenant=tenant, obj=appointment, label="La cita")

    if amount is None or amount <= ZERO:
        raise ValidationError("El monto del cargo debe ser mayor a cero.")
    if not description:
        raise ValidationError("El cargo requiere una descripción.")

    charge = Charge.objects.create(
        tenant=tenant,
        created_by=user,
        patient=patient,
        concept=concept,
        description=description,
        appointment=appointment,
        amount=_q2(amount),
        amount_paid=ZERO,
        status=Charge.Status.PENDING,
        issued_at=issued_at or timezone.now(),
    )
    audit_record(
        action=ActionType.CHARGE_CREATE,
        resource_type="Charge",
        actor=user,
        tenant=tenant,
        resource_id=charge.id,
        resource_repr=charge.description,
        metadata={"amount": str(charge.amount)},
    )
    return charge


def charge_cancel(*, charge: Charge, user: Any) -> Charge:
    """Cancela un cargo.

    Raises:
        ValidationError: si el cargo ya tiene pagos aplicados o ya está cancelado.
    """
    if charge.status == Charge.Status.CANCELLED:
        raise ValidationError("El cargo ya está cancelado.")
    if charge.amount_paid > ZERO:
        raise ValidationError(
            "No se puede cancelar un cargo con pagos aplicados. Cancela primero los pagos."
        )
    charge.status = Charge.Status.CANCELLED
    charge.save(update_fields=["status", "updated_at"])
    audit_record(
        action=ActionType.CHARGE_CANCEL,
        resource_type="Charge",
        actor=user,
        tenant=charge.tenant,
        resource_id=charge.id,
        resource_repr=charge.description,
    )
    return charge


def _apply_charge_status(*, charge: Charge) -> None:
    """Deriva y persiste el status del cargo a partir de amount_paid."""
    if charge.amount_paid <= ZERO:
        charge.status = Charge.Status.PENDING
    elif charge.amount_paid < charge.amount:
        charge.status = Charge.Status.PARTIAL
    else:
        charge.status = Charge.Status.PAID
    charge.save(update_fields=["amount_paid", "status", "updated_at"])


# ---------------------------------------------------------------------------
# Pagos
# ---------------------------------------------------------------------------


def payment_register(
    *,
    tenant: Tenant,
    user: Any,
    patient: Patient,
    amount: Decimal,
    method: str = Payment.Method.CASH,
    reference: str = "",
    notes: str = "",
    received_at: Optional[datetime.datetime] = None,
    allocations: Optional[list[dict[str, Any]]] = None,
) -> Payment:
    """Registra un pago y, opcionalmente, lo aplica a uno o varios cargos.

    `allocations`: lista de {charge_id, amount}. La suma de las aplicaciones no
    puede exceder `amount`. Cada cargo se actualiza (amount_paid + status).

    Raises:
        ValidationError: si el monto no es positivo, un cargo es de otro tenant
                         o ya está cancelado/pagado de más, o la suma de
                         aplicaciones excede el monto del pago.
    """
    _ensure_same_tenant(tenant=tenant, obj=patient, label="El paciente")
    if amount is None or amount <= ZERO:
        raise ValidationError("El monto del pago debe ser mayor a cero.")

    allocations = allocations or []
    amount = _q2(amount)

    # No se permiten saldos a favor: el pago no puede exceder la deuda pendiente
    # total del paciente (suma de saldos de sus cargos pendientes/parciales).
    deuda_pendiente = sum(
        (
            c.balance
            for c in Charge.objects.filter(
                patient=patient,
                status__in=[Charge.Status.PENDING, Charge.Status.PARTIAL],
            )
        ),
        ZERO,
    )
    if amount > deuda_pendiente:
        raise ValidationError(
            f"El pago ({amount}) excede el saldo pendiente del paciente "
            f"({deuda_pendiente}). No se permiten pagos a favor."
        )

    with transaction.atomic():
        payment = Payment.objects.create(
            tenant=tenant,
            created_by=user,
            patient=patient,
            amount=amount,
            method=method,
            reference=reference,
            notes=notes,
            received_at=received_at or timezone.now(),
        )

        allocated_total = ZERO
        for raw in allocations:
            charge_id = raw.get("charge_id")
            alloc_amount = _q2(Decimal(str(raw.get("amount", "0"))))
            if alloc_amount <= ZERO:
                raise ValidationError("El monto de cada aplicación debe ser positivo.")

            # select_for_update para evitar carreras al actualizar amount_paid.
            charge = (
                Charge.objects.select_for_update().filter(id=charge_id).first()
            )
            if charge is None:
                raise ValidationError("Cargo no encontrado en esta clínica.")
            if charge.patient_id != patient.id:
                raise ValidationError("El cargo no corresponde al paciente del pago.")
            if charge.status == Charge.Status.CANCELLED:
                raise ValidationError("No se puede aplicar un pago a un cargo cancelado.")

            if alloc_amount > charge.balance:
                raise ValidationError(
                    "La aplicación excede el saldo pendiente del cargo "
                    f"({charge.balance})."
                )

            PaymentAllocation.objects.create(
                tenant=tenant,
                created_by=user,
                payment=payment,
                charge=charge,
                amount=alloc_amount,
            )
            charge.amount_paid = _q2(charge.amount_paid + alloc_amount)
            _apply_charge_status(charge=charge)
            allocated_total += alloc_amount

        if allocated_total > amount:
            raise ValidationError(
                "La suma de las aplicaciones excede el monto del pago."
            )

        # Auto-asignación en cascada: el remanente que no se asignó manualmente
        # se aplica a los cargos pendientes/parciales más antiguos del paciente,
        # para que el pago SIEMPRE baje la deuda sin depender de captura manual.
        # Lo que sobre (si pagó de más) queda como saldo a favor del paciente.
        remaining = amount - allocated_total
        if remaining > ZERO:
            ya_aplicados = [a.get("charge_id") for a in allocations if a.get("charge_id")]
            pendientes = (
                Charge.objects.select_for_update()
                .filter(
                    patient=patient,
                    status__in=[Charge.Status.PENDING, Charge.Status.PARTIAL],
                )
                .exclude(id__in=ya_aplicados)
                .order_by("issued_at", "created_at")
            )
            for charge in pendientes:
                if remaining <= ZERO:
                    break
                aplicar = min(remaining, charge.balance)
                if aplicar <= ZERO:
                    continue
                PaymentAllocation.objects.create(
                    tenant=tenant,
                    created_by=user,
                    payment=payment,
                    charge=charge,
                    amount=aplicar,
                )
                charge.amount_paid = _q2(charge.amount_paid + aplicar)
                _apply_charge_status(charge=charge)
                allocated_total += aplicar
                remaining -= aplicar

    audit_record(
        action=ActionType.PAYMENT_REGISTER,
        resource_type="Payment",
        actor=user,
        tenant=tenant,
        resource_id=payment.id,
        resource_repr=str(payment.id),
        metadata={
            "amount": str(payment.amount),
            "method": method,
            "allocations": len(allocations),
        },
    )
    return payment


# ---------------------------------------------------------------------------
# CFDI 4.0
# ---------------------------------------------------------------------------


def cfdi_issue(
    *,
    tenant: Tenant,
    user: Any,
    payment: Payment,
    receptor_rfc: str,
    receptor_name: str,
    cfdi_use: str = "G03",
    payment_form: str = "01",
    payment_method: str = "PUE",
    receptor_tax_regime: str = "",
    receptor_postal_code: str = "",
) -> CfdiDocument:
    """Emite (timbra) un CFDI 4.0 a partir de un pago, vía el PAC.

    Flujo:
      1. Valida config fiscal del emisor y que el pago sea del tenant.
      2. Crea el CfdiDocument en DRAFT, asigna folio interno consecutivo.
      3. Llama al adapter (PAC) para timbrar.
      4. Si timbra: persiste uuid_sat/xml_url/pdf_url y pasa a STAMPED.
         Si falla: deja el documento en DRAFT y eleva ValidationError.

    Raises:
        ValidationError: si falta config fiscal, el pago es de otro tenant, o
                         el PAC rechaza el timbrado.
    """
    _ensure_same_tenant(tenant=tenant, obj=payment, label="El pago")

    config = ClinicFiscalConfig.all_objects.filter(tenant=tenant).first()
    if config is None or not config.rfc:
        raise ValidationError(
            "Configura los datos fiscales del emisor (RFC) antes de timbrar."
        )
    if not receptor_rfc or not receptor_name:
        raise ValidationError("El receptor requiere RFC y razón social.")

    with transaction.atomic():
        # Asignar folio interno consecutivo de forma segura.
        config = ClinicFiscalConfig.all_objects.select_for_update().get(id=config.id)
        folio = config.next_folio
        config.next_folio = folio + 1
        config.save(update_fields=["next_folio", "updated_at"])

        cfdi = CfdiDocument.objects.create(
            tenant=tenant,
            created_by=user,
            payment=payment,
            patient=payment.patient,
            status=CfdiDocument.Status.DRAFT,
            series=config.series,
            folio=folio,
            receptor_rfc=receptor_rfc,
            receptor_name=receptor_name,
            receptor_tax_regime=receptor_tax_regime,
            receptor_postal_code=receptor_postal_code,
            cfdi_use=cfdi_use,
            payment_form=payment_form,
            payment_method=payment_method,
            subtotal=payment.amount,
            total=payment.amount,
        )

        adapter = get_cfdi_adapter()
        result = adapter.stamp(
            payload={
                "emisor_rfc": config.rfc,
                "emisor_name": config.legal_name,
                "emisor_tax_regime": config.tax_regime,
                "emisor_postal_code": config.postal_code,
                "receptor_rfc": receptor_rfc,
                "receptor_name": receptor_name,
                "receptor_tax_regime": receptor_tax_regime,
                "receptor_postal_code": receptor_postal_code,
                "cfdi_use": cfdi_use,
                "payment_form": payment_form,
                "payment_method": payment_method,
                "series": config.series,
                "folio": folio,
                "subtotal": payment.amount,
                "total": payment.amount,
            }
        )

        if not result.success:
            # transaction.atomic se revierte al elevar; el folio NO se consume.
            raise ValidationError(f"El PAC rechazó el timbrado: {result.error}")

        cfdi.status = CfdiDocument.Status.STAMPED
        cfdi.uuid_sat = result.uuid_sat
        cfdi.pac_id = result.pac_id
        cfdi.xml_url = result.xml_url
        cfdi.pdf_url = result.pdf_url
        cfdi.stamped_at = timezone.now()
        cfdi.save(
            update_fields=[
                "status",
                "uuid_sat",
                "pac_id",
                "xml_url",
                "pdf_url",
                "stamped_at",
                "updated_at",
            ]
        )

    audit_record(
        action=ActionType.CFDI_ISSUE,
        resource_type="CfdiDocument",
        actor=user,
        tenant=tenant,
        resource_id=cfdi.id,
        resource_repr=cfdi.uuid_sat or f"{cfdi.series}{cfdi.folio}",
        metadata={"total": str(cfdi.total)},
    )
    return cfdi


def cfdi_cancel(*, cfdi: CfdiDocument, user: Any, reason: str = "02") -> CfdiDocument:
    """Cancela un CFDI timbrado, vía el PAC.

    Raises:
        ValidationError: si el comprobante no está timbrado o el PAC rechaza
                         la cancelación.
    """
    if cfdi.status != CfdiDocument.Status.STAMPED:
        raise ValidationError("Solo se pueden cancelar comprobantes timbrados.")

    adapter = get_cfdi_adapter()
    result = adapter.cancel(
        pac_id=cfdi.pac_id,
        uuid_sat=cfdi.uuid_sat,
        reason=reason,
    )
    if not result.success:
        raise ValidationError(f"El PAC rechazó la cancelación: {result.error}")

    cfdi.status = CfdiDocument.Status.CANCELLED
    cfdi.cancellation_reason = reason
    cfdi.cancelled_at = timezone.now()
    cfdi.save(
        update_fields=["status", "cancellation_reason", "cancelled_at", "updated_at"]
    )

    audit_record(
        action=ActionType.CFDI_CANCEL,
        resource_type="CfdiDocument",
        actor=user,
        tenant=cfdi.tenant,
        resource_id=cfdi.id,
        resource_repr=cfdi.uuid_sat or f"{cfdi.series}{cfdi.folio}",
        metadata={"reason": reason},
    )
    return cfdi
