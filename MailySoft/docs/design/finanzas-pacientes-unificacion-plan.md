# Plan — Unificación de Finanzas con el Expediente del Paciente

> Estado: **PROPUESTA / por revisar** · Fecha: 2026-06-25 · Autor: equipo Maily
> Relacionado: `expediente-saas-rediseno.md`, `libro-clinico-plan.md`, `pacientes-filtros-clasificacion.md`
> Decisión NO implementar todavía — este documento es para revisión antes de escribir código.

## 1. Objetivo

Unificar el módulo de **finanzas** (ya integrado, ver `apps/finanzas`) con el **expediente / libro del paciente**, de modo que:

1. Cada visita del paciente combine **evolución + receta + estado de cuenta** en un solo lugar.
2. La clínica pueda llevar **cobros de contado y diferido** (planes de pago) por servicio.
3. El dueño obtenga **reportes financieros en PDF** por día/semana/mes/año, con **comparativas**.
4. Exista **analítica de clientes**: más frecuentes, los que más gastan, en riesgo y perdidos, con **tácticas de recuperación**.
5. Todo respete el modelo **multi-tenant (RLS)** y los **permisos por rol** existentes.

## 2. Hallazgos del benchmark (fundamento)

Se investigaron 7 plataformas (SimplePractice, Jane App, Cliniko, Tebra/Kareo, DrChrono, Dentrix/Curve Dental, NexHealth) + herramientas generales (QuickBooks, Stripe, Xero) y modelos de retención (RFM, cohortes, recall).

**Patrón universal del sector:**
> Catálogo de servicios (*fee schedule*) → cargo ligado a la cita → **ledger del paciente** → pagos / planes → reportes.

Conclusiones que guían este plan:
- **El estado de cuenta vive PEGADO al expediente**, no en un módulo admin aparte (DrChrono "Patient Balance Ledger", Dentrix, SimplePractice). Valida la idea del "libro del paciente".
- **El ledger es la fuente de verdad**; la factura/CFDI es una vista derivada. Cada movimiento es una línea inmutable con saldo corrido.
- **Pagos con asignación (allocation) + saldo a favor** (account credit) es el estándar (Cliniko, Jane).
- **Planes de pago como entidad propia** (DrChrono `Patient Payment Plans`) para el "diferido".
- **CFDI desacoplado del cobro**: PUE de contado, PPD para parcialidades. Es el diferenciador mexicano (ninguna plataforma gringa lo hace).
- **Retención por RFM**: segmentar por Recency/Frequency/Monetary. Reactivar cuesta una fracción de adquirir; recall automatizado ROI ~14:1; SMS/WhatsApp es el canal más efectivo (31% resp. vs 14% email).
- **Reportes núcleo**: cierre diario, producción vs cobranza, ingresos por periodo, A/R aging, comparativa MoM/YoY.

Benchmarks numéricos de referencia (mercado dental US, ajustar a datos propios):
- Atrición anual típica ~17% (top prácticas <5%). 40% inactivos tras 18 meses.
- A/R: máximo 10-15% debe superar los 90 días. Collection ratio meta 95-98%.
- No-show promedio 7.4% (meta <5%). Reactivación: 1-6m → 28-34%, 6-12m → 14-22%, 12m+ → 8-15%.

## 3. Decisiones de diseño tomadas

| # | Decisión | Detalle |
|---|---|---|
| D-1 | **Ledger junto al expediente** | El estado de cuenta se ve en el libro del paciente, por visita, no solo en el panel de finanzas. |
| D-2 | **Visibilidad de costos configurable por clínica** | Un flag por tenant decide si los **médicos** ven costos/estado de cuenta. Por defecto: NO. El backend es la autoridad. |
| D-3 | **El ledger se DERIVA (sin tabla nueva)** | El estado de cuenta (movimientos + saldo corrido) se **calcula** en un selector a partir de `Charge`/`Payment`/`PaymentAllocation`; sin tabla `LedgerEntry`. Más simple y nunca se desincroniza. Migrable a tabla si crece el volumen. |
| D-4 | **Cargo con snapshot de precio** | El `Charge` congela precio y descripción del servicio al crearse (como recetas/preguntas). |
| D-5 | **Facturación CFDI = MANUAL (fuera de alcance)** | El sistema lleva cargos, pagos y estado de cuenta; la **factura fiscal (CFDI) se hace por fuera** por ahora. El modelo `CfdiDocument` queda latente para una fase futura con PAC. |
| D-6 | **RFM auto-alimenta etiquetas** | La segmentación calcula y aplica las etiquetas del sistema (VIP, en riesgo, etc.), reusando `PatientCategory.kind`. |
| D-7 | **Retención = solo VISUALIZACIÓN (sin campañas)** | El sistema **muestra** qué clientes no están llegando (en riesgo / perdidos) + métricas; **NO envía** campañas automáticas. El contacto lo hace la clínica manualmente. Envío automático = fase futura (requiere consentimiento). |
| D-8 | **Excel con `exceljs`** | Se reemplaza `xlsx` (CVE sin parche) por `exceljs` para las exportaciones a Excel. |
| D-9 | **Privacidad/consentimiento (a diseñar)** | Aviso de privacidad + consentimiento (LFPDPPP) antes de tratar datos para analítica de retención; permitir baja. Se diseña junto a la Fase 3. |

## 4. Modelo de datos

### Ya existe (apps/finanzas)
- `ServiceConcept` — catálogo de servicios (precio base, claves SAT, activo).
- `Quote` + `QuoteItem` — cotizaciones.
- `Charge` — cargo (FK a **patient**, **concept**, **appointment**, **quote**; amount, amount_paid, status pending/partial/paid/cancelled).
- `Payment` + `PaymentAllocation` — pagos con asignación a cargos.
- `CfdiDocument` — CFDI 4.0.
- `ClinicFiscalConfig` — datos fiscales del emisor.

### A agregar
- **`ServiceFeeSchedule`** (opcional, Fase futura): precios alternos por servicio (particular, convenio, membresía). En Fase 1 basta `base_price`.
- **`Charge` — snapshot** de `concept_name` y `unit_price` al crearse (campos nuevos), para no depender del catálogo vivo (D-4).
- **Ledger DERIVADO (D-3)**: NO se crea tabla nueva. Un selector `account_statement_build(patient)` calcula los movimientos (cargo/pago/ajuste/crédito) y el saldo corrido a partir de `Charge`/`Payment`/`PaymentAllocation`. Si en el futuro se requiere auditoría fiscal estricta o alto volumen, se migra a una tabla `LedgerEntry` explícita.
- **`PaymentPlan`** + **`PaymentPlanInstallment`** (Fase 3 de finanzas): monto total, nº de cuotas, periodicidad, mensualidad calculada, estado por cuota. Para el "diferido" formal.
- **`Adjustment`** (ajuste/descuento/condonación): movimiento que reduce saldo sin pago (write-off del benchmark).
- **`ClinicSettings.doctors_see_costs: bool`** (D-2) — flag de visibilidad.
- **`PatientFinancialSnapshot`** (Fase 3, opcional/caché): métricas RFM precalculadas por paciente (last_visit, visits_12m, spent_12m, segmento) para no recalcular en cada consulta.

## 5. Fases

### Fase 1 — Estado de cuenta en el libro del paciente
**Meta:** ver y cobrar la cuenta del paciente desde el expediente, por visita.

Backend:
- Snapshot de precio/descripcion en `Charge` (D-4) + migración.
- Selector `account_statement_build(patient)` → ledger corrido (movimientos + saldo) y saldo actual.
- `Adjustment` (descuentos/condonaciones) con permiso de finanzas.
- Endpoint estado de cuenta ya existe (`/finanzas/estado-cuenta/<patient_id>/`); ampliar con saldo corrido y filtros por fecha.
- Flag `doctors_see_costs` en `ClinicSettings` + lógica de permiso condicional (D-2).

Frontend (libro del paciente):
- **Badge de saldo** en el encabezado del expediente (`Saldo: $X por cobrar / a favor`).
- En cada **capítulo/visita**: bloque colapsable **"Estado de cuenta de la visita"** (cargos de esa cita + pagos + saldo), junto a evolución y receta.
- **Pestaña "Estado de cuenta"** del paciente: ledger completo + filtros + **generar PDF** (WeasyPrint). La factura CFDI se hace **manual** por ahora (D-5).
- Acción **"Cobrar"** desde la cita: asignar pago a los cargos de la visita; remanente → crédito.
- Gating por rol + flag de clínica.

### Fase 2 — Reportes financieros + PDF
**Meta:** que el dueño vea cómo va el negocio por periodo y exporte PDF.

Backend:
- Ampliar `dashboard` con: producción vs cobranza, ingresos por periodo (día/sem/mes/año), **A/R aging** (0-30/31-60/61-90/90+), comparativa MoM/YoY, por método de pago, por doctor, por servicio, ticket promedio, ajustes/descuentos.
- Selectores agregados eficientes (agrupación por fecha) + caché si hace falta.
- Endpoint **reporte de periodo** que devuelve el dataset para el PDF.
- Generador de **PDF de reporte financiero** (WeasyPrint): 1-2 páginas con KPIs + gráficas + tablas (ver §6).

Frontend (panel finanzas → Dashboard ampliado):
- Filtros día/semana/mes/año + comparativa.
- Gráficas: **línea** (ingreso/cobranza con periodo anterior), **barra horizontal apilada** (A/R aging), **dona** (métodos de pago), **barras** (por doctor/servicio) — con `recharts` (ya instalado).
- **Cierre diario (day sheet)** como reporte/imprimible.
- Botón **exportar PDF** del periodo + **Excel** (con `exceljs` — reemplaza a `xlsx` por su CVE, D-8; + `jspdf`).

### Fase 3 — Analítica de clientes (RFM) — visualización
**Meta:** saber quién es frecuente, quién gasta más, quién está en riesgo o perdido (para que la clínica decida a quién contactar). **Sin envío automático** (D-7).

Backend:
- Cálculo **RFM** por paciente (Recency, Frequency, Monetary en ventana de 12 meses), tarea Celery periódica → `PatientFinancialSnapshot`.
- **Segmentación** con umbrales (config por clínica, valores por defecto del benchmark):
  - VIP/Campeón: vino <6m + ≥2 visitas/año + top 20% gasto.
  - VIP por gasto: top 10% monto 12m.
  - Frecuente: ≥2-3 visitas/año, vino <6m.
  - En riesgo: antes regular, sin visita 4-6m.
  - Perdido: sin visita 12m+.
- **Auto-aplicar etiquetas** del sistema (D-6) reusando `PatientCategory.kind` (extender kinds: at_risk, lost, frequent, top_spender).
- Métricas: tasa de retención, CLV, tasa de reactivación, no-show rate, % con próxima cita.
- **Sin campañas automáticas** (D-7): el sistema solo **identifica y lista** los segmentos en riesgo / perdidos para que la clínica los contacte por fuera. (El envío automático con `MetaWhatsAppAdapter` + consentimiento queda como fase futura — D-9.)

Frontend:
- **Panel de retención**: distribución por segmento, lista accionable de "en riesgo" y "perdidos", métricas clave.
- Filtros del panel de pacientes por segmento RFM (extiende los chips existentes).
- Ver/exportar la lista de pacientes **en riesgo** y **perdidos** (con su contacto) para que la clínica los llame/escriba manualmente.

## 6. PDF de reporte financiero (estructura)
1-2 páginas, reusando WeasyPrint:
- **Encabezado**: logo/clínica, periodo (día/sem/mes/año), "vs periodo anterior", fecha de generación.
- **Fila de 4-6 KPIs**: Producción, Cobranza, Collection %, Ingreso neto, A/R total, Ticket promedio — cada uno con Δ% MoM/YoY.
- **Gráfica línea**: ingreso/cobranza del periodo con la línea del periodo anterior superpuesta.
- **Gráfica barras apiladas horizontales**: A/R aging por cubeta.
- **Gráfica dona**: método de pago o mezcla de servicios.
- **Tabla**: ingreso por doctor (producción, cobranza, %).
- **Tabla**: top servicios por ingreso + ajustes del periodo.
- **Pie**: totales MTD/YTD + nota de exclusiones.

## 7. Roles y multi-tenant
- Multi-tenant ya resuelto: todo `TenantAwareModel` + RLS; cada clínica define su catálogo, precios y umbrales.
- Matriz (autoridad: backend, `apps/core/permissions.py`):
  - Catálogo de servicios / config fiscal: **Dueño, Admin**.
  - Registrar procedimiento (qué se hizo): **Médico** (costo visible solo si `doctors_see_costs`).
  - Cobrar / registrar pago: **Recepción, Finanzas, Dueño, Admin**.
  - Cargos / CFDI / ajustes: **Dueño, Admin, Finanzas** (Recepción NO factura).
  - Reportes / métricas / panel de retención: **Dueño, Admin, Finanzas** (Médico/Enfermería NO).
  - Ver panel de retención / lista de clientes que no llegan: **Dueño, Admin, Finanzas**.

## 8. Decisiones resueltas y riesgos
**Resueltas (este ciclo, ver §3):**
- ✅ **Ledger DERIVADO** en selector, sin tabla nueva (D-3).
- ✅ **Excel con `exceljs`** en vez de `xlsx` por su CVE (D-8).
- ✅ **CFDI = manual / fuera de alcance** por ahora (D-5); `CfdiDocument` queda latente para fase futura con PAC.
- ✅ **Sin campañas automáticas** (D-7): solo visualización de quién no llega.

**Pendientes / a diseñar:**
- **Privacidad (LFPDPPP)** (D-9): aviso de privacidad + consentimiento antes de tratar datos de pacientes para analítica de retención; permitir baja. Definir junto a la Fase 3.
- **Umbrales RFM** por defecto son del mercado dental US; cada clínica debe poder ajustarlos.

**Fase futura (fuera de este plan):**
- Timbrado **CFDI real** con un PAC.
- **Envío automático** de recordatorios/campañas (`MetaWhatsAppAdapter` + credenciales Meta + consentimiento).

## 9. Fuentes del benchmark
Cobros/ledger: SimplePractice, Jane App, Cliniko, Tebra, DrChrono, Dentrix/Curve, NexHealth (help centers oficiales).
Reportes/KPIs: ADA, Dentrix Magazine (5 KPIs), Pearly (A/R benchmark), Databox, SimplePractice/Jane/Curve/Tebra analytics.
Retención/RFM: CleverTap, Optimove (RFM); RevenueWell, Dentrix Magazine, Clerri (reactivación); DoctorLogic (CLV/retención); Amplitude/Saras (cohortes); Doctoralia (campañas LatAm).
