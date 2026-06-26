# Plan — Módulo de Cotizaciones (top-level, ligado a catálogo y agenda)

> Estado: **PROPUESTA / por revisar** · Fecha: 2026-06-26
> Relacionado: `finanzas-pacientes-unificacion-plan.md`, catálogo de servicios (Mi Consultorio → Servicios y precios)

## 1. Objetivo y flujo

Recepción (o admin/doctor/dueño) recibe una llamada preguntando por procedimientos y **arma una cotización ANTES de agendar**, eligiendo servicios del catálogo de la clínica (precios preestablecidos). La cotización se **guarda**, se puede **descargar en PDF** y enviar al paciente. Si el paciente **acepta** y se agenda una cita, la cotización queda **ligada a esa cita** y se ve al abrir la cita.

```
Llamada → Cotización (servicios del catálogo) → PDF → enviar (manual)
        → paciente acepta → Agendar cita (elige la cotización) → al abrir la cita se ve la cotización + motivo
```

## 2. Decisiones tomadas (vía AskUserQuestion, 2026-06-26)

| # | Decisión | Detalle |
|---|---|---|
| C-1 | **Roles que cotizan** | **Recepción, Admin, Doctor, Dueño.** Se AGREGA el doctor (hoy no podía); se deja FUERA a Finanzas y Enfermería. |
| C-2 | **Envío** | **PDF descargable + marcar "enviada".** El envío real lo hace recepción a mano (WhatsApp/correo). Sin envío automático (consistente con retención). |
| C-3 | **Vínculo con la cita** | **Elegir la cotización aceptada al agendar** (vínculo directo, FK). Al abrir la cita se ve esa cotización + el motivo. |
| C-4 | **Acceso** | Módulo **top-level** en la barra superior (junto a Finanzas/Agenda/Pacientes/Personal/Notas), NO escondido en Finanzas (el doctor no entra a Finanzas). |

## 3. Estado actual (lo que YA existe)

- ✅ **Modelo `Quote` + `QuoteItem`** con máquina de estados (draft/sent/accepted/rejected/expired), FK a paciente, subtotal/descuento/total, `valid_until`, `notes`. `QuoteItem` ya tiene `concept` (FK a `ServiceConcept`), `quantity`, `unit_price`, `discount`, `line_total` (snapshots).
- ✅ **Services**: `quote_create`, `quote_send` (→sent), `quote_accept` (→accepted + genera Charges), `quote_set_status`.
- ✅ **Endpoints**: `/finanzas/cotizaciones/` (list/create), `/<id>/` (detalle/patch estado), `/<id>/enviar/`, `/<id>/aceptar/`.
- ✅ **Frontend** `CotizacionesTab` (dentro de Finanzas): crear manual, enviar, aceptar; api/hooks `fetchQuotes/createQuote/sendQuote/acceptQuote`.
- ✅ **`Charge.quote`** (FK) — al aceptar se generan cargos ligados a la cotización.
- ✅ **Catálogo `ServiceConcept`** con precios (gestionable en Mi Consultorio → Servicios y precios).

**Lo que FALTA** (este plan): acceso top-level + rol doctor, crear desde el catálogo (picker), PDF de cotización, vínculo directo Quote↔Appointment, mostrarlo en el detalle de la cita.

## 4. Fases

### Fase 1 — Cotizaciones top-level + crear desde el catálogo
Backend:
- Permiso de cotizaciones → role-set **{owner, admin, doctor, reception}** (C-1). Ajustar/crear el permiso que usan los endpoints de `/finanzas/cotizaciones/` (hoy `FinanceQuotePermission` = owner/admin/finance/reception). Crear `QuotePermission` con el nuevo set para no alterar el resto de finanzas.
- (Opcional) validar `concept_id` pertenece al tenant al crear ítems.

Frontend:
- Nuevo **módulo `cotizaciones`** en `Topbar.tsx` (icono p. ej. `ScrollText`), con `accesoModulo(role,'cotizaciones')` = {owner, admin, doctor, reception}.
- **Ruta** en `App.tsx` → `CotizacionesPage` (página standalone; reutiliza el contenido de `CotizacionesTab`). Mantener también el acceso desde Finanzas o quitarlo de ahí (decisión menor; sugerido: dejarlo solo top-level para no duplicar).
- **Crear desde catálogo**: en el form de la cotización, un **picker de servicios** (`useConcepts` activos) → al elegir un servicio se rellenan `description` + `unit_price` (editable); permitir `quantity` y `discount` por renglón; varios renglones; total en vivo. (Mejora del ingreso manual actual.)
- `permisos.ts`: `createQuote` → {owner, admin, doctor, reception}; agregar `accesoModulo` para 'cotizaciones'.

### Fase 2 — PDF de cotización + enviar
Backend:
- `quote_pdf_build()` (WeasyPrint, reusar patrón de `apps/finanzas/pdf.py` / recetas): encabezado de la clínica, datos del paciente, tabla de renglones (servicio, cantidad, precio, descuento, importe), subtotal/descuento/total, vigencia (`valid_until`), folio/fecha. Sin servir en URL pública (Bearer).
- Endpoint `GET /finanzas/cotizaciones/<id>/pdf/` con `Accept: application/pdf` (PdfRenderer).

Frontend:
- Botón **"Descargar PDF"** en la cotización (patrón blob, como el reporte financiero).
- Botón **"Marcar como enviada"** (usa `quote_send` → estado `sent`). Texto que aclare que el envío al paciente es manual.

### Fase 3 — Vínculo con la agenda
Backend:
- **`Appointment.quote`** (FK → `Quote`, nullable, `SET_NULL`) + migración de agenda.
- `appointment_create` (y el asistente de cita) acepta `quote_id` opcional; valida que la cotización sea del mismo paciente y esté `accepted`.
- Serializer/selector de la cita incluye un resumen de la cotización vinculada (id, folio, total, status).

Frontend:
- Al **agendar** (asistente de cita / modal de crear cita): selector opcional **"Cotización"** que lista las cotizaciones **aceptadas** del paciente elegido. Además el **motivo** (`reason`) ya existe — reforzar que se capture.
- **`DetalleCitaModal`**: mostrar el **motivo** + la **cotización vinculada** (resumen: total + estado) con botón **ver/descargar PDF**. Si no hay, nada.

## 5. Roles y permisos (autoridad: backend)
- **Crear / ver / enviar / descargar PDF de cotizaciones**: owner, admin, doctor, reception.
- Finanzas, Enfermería, Solo-lectura: NO (decisión C-1). *(Nota: el dueño/admin siempre pueden; readonly podría ver en el futuro si se pide.)*
- Aceptar cotización (genera cargos): **owner, admin, doctor, reception** (los mismos 4 que cotizan). **El doctor SÍ puede aceptar** — durante la consulta puede cerrar la venta de un artículo/procedimiento y agilizar el servicio (decisión 2026-06-26).
- Vincular cotización a la cita: quien agenda (owner/admin/doctor/reception), según permisos de agenda existentes.

## 6. Riesgos / notas
- **Migración de agenda** (`Appointment.quote`): coordinar con la sesión paralela (que ha tocado pacientes/expediente). Verificar `git status` y hacer add selectivo al commitear.
- **El doctor accede a cotizaciones** por primera vez: el módulo top-level NO debe exponerle otros datos financieros (solo cotizaciones). El backend sigue siendo la autoridad.
- **Sin envío automático**: el PDF se descarga y se manda a mano (C-2). Envío por WhatsApp/correo = fase futura (requiere Meta API + consentimiento).
- **Editar cotización**: hoy no se puede editar una cotización tras crearla (solo crear/enviar/aceptar/rechazar). Si se requiere editar borradores, es trabajo adicional (no incluido).
