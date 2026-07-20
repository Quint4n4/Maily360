/**
 * Capa de API tipada del dominio finanzas.
 *
 * Cada función mapea 1:1 a un endpoint de /api/v1/finanzas/. Los componentes
 * NO llaman a estas funciones directamente: lo hacen vía los hooks de
 * src/hooks/finanzas.ts (TanStack Query).
 */

import { http } from '../lib/http'
import type { SucursalRef } from '../types/sucursal'
import { pdfJobBlob } from './pdfs'

// ---------------------------------------------------------------------------
// Tipos compartidos
// ---------------------------------------------------------------------------

/**
 * Multi-sede (Fase 3): dónde se generó el movimiento.
 *
 * Reglas de negocio (las respeta el backend; el front solo las refleja):
 *  - Caja / reportes / dashboard / cierre diario / retención / antigüedad y el
 *    listado GENERAL de cargos y pagos se filtran por el header `X-Sucursal-Id`.
 *    Sin header, el backend consolida sobre las sedes PERMITIDAS del usuario.
 *  - El ESTADO DE CUENTA POR PACIENTE devuelve TODOS sus movimientos, de todas
 *    las sedes (la cuenta del paciente es compartida). No se filtra.
 */
export type { SucursalRef }

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface DateRangeParams {
  date_from?: string
  date_to?: string
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export interface DashboardKpis {
  total_income: number
  total_charged: number
  outstanding: number
  average_ticket: number
  collection_rate: number
  payments_count: number
}

export interface IncomeByDay {
  date: string
  amount: number
}

export interface IncomeByConcept {
  concept: string
  amount: number
}

export interface IncomeByMethod {
  method: string
  label: string
  amount: number
  count: number
}

export interface AgingBucket {
  bucket: string
  amount: number
  count: number
}

export interface QuotesFunnel {
  draft: number
  sent: number
  accepted: number
  rejected: number
  expired: number
  conversion_rate: number
}

export interface DashboardMetrics {
  range: { date_from: string; date_to: string }
  kpis: DashboardKpis
  income_by_day: IncomeByDay[]
  income_by_concept: IncomeByConcept[]
  income_by_method: IncomeByMethod[]
  aging: AgingBucket[]
  quotes_funnel: QuotesFunnel
}

export function fetchDashboard(params: DateRangeParams = {}): Promise<DashboardMetrics> {
  return http.get<DashboardMetrics>('/finanzas/dashboard/', params)
}

// ---------------------------------------------------------------------------
// Fase 2 — Reporte de periodo
//
// Los nombres de campo reflejan EXACTO el dict de
// apps/finanzas/selectors.py::finance_period_report (no inventar). Todos los
// montos llegan como string decimal o number desde DRF; se tipan como
// `number` y se normalizan con toNumber/formatMoney en la UI.
// ---------------------------------------------------------------------------

/** Granularidad de la serie temporal del reporte. */
export type ReportGroup = 'day' | 'week' | 'month'

/** Parámetros del reporte de periodo: rango requerido + agrupación. */
export interface PeriodReportParams {
  date_from: string
  date_to: string
  group?: ReportGroup
}

/** Un bucket de antigüedad de A/R (mismo shape que AgingBucket del dashboard). */
export type ReportAgingBucket = AgingBucket

/** Desglose por método de pago (mismo shape que IncomeByMethod). */
export type ReportByMethod = IncomeByMethod

/** Top servicios por producción (cargos del periodo). */
export interface ReportByService {
  concept_id: string | null
  name: string
  amount: number
  count: number
}

/** Producción por doctor (vía appointment__doctor; "Sin cita" agrupa cobros manuales). */
export interface ReportByDoctor {
  doctor_id: string | null
  name: string
  amount: number
  count: number
}

/** Punto de la serie temporal: producción y cobranza por periodo agrupado. */
export interface ReportSeriesPoint {
  period: string
  production: number
  collection: number
}

/**
 * Dataset completo del reporte de periodo. Refleja 1:1 finance_period_report().
 * Los Δ% pueden venir null cuando el periodo anterior fue cero (sin base de comparación).
 */
export interface PeriodReport {
  range: { date_from: string; date_to: string }
  prev_range: { date_from: string; date_to: string }
  group: ReportGroup
  // KPIs actuales
  production: number
  collection: number
  collection_pct: number
  ar_total: number
  aging: ReportAgingBucket[]
  average_ticket: number
  charges_count: number
  // Comparativa con el periodo anterior
  prev_production: number
  prev_collection: number
  prev_collection_pct: number
  delta_production_pct: number | null
  delta_collection_pct: number | null
  delta_collection_rate_ppt: number | null
  // Desglose
  by_method: ReportByMethod[]
  by_service: ReportByService[]
  by_doctor: ReportByDoctor[]
  series: ReportSeriesPoint[]
  // Ajustes (placeholder backend: 0 + nota; el modelo Adjustment no existe aún)
  adjustments_total: number
  adjustments_note: string
}

/** GET /finanzas/reporte/ — dataset de KPIs/series/aging/método/servicio/doctor + comparativa. */
export function fetchPeriodReport(params: PeriodReportParams): Promise<PeriodReport> {
  return http.get<PeriodReport>('/finanzas/reporte/', params)
}

/**
 * GET /finanzas/reporte/pdf/ — PDF del reporte de periodo (Blob).
 * Flujo asíncrono (Celery): el endpoint ENCOLA y `pdfJobBlob` hace el polling y la
 * descarga por dentro. El reporte es mutable → siempre fresco (sin caché).
 * El token nunca va en la URL: viaja en el header Authorization del cliente central.
 */
export async function fetchReportPdfBlob(params: {
  date_from: string
  date_to: string
  group?: ReportGroup
}): Promise<Blob> {
  const qs = new URLSearchParams({ date_from: params.date_from, date_to: params.date_to })
  if (params.group) qs.set('group', params.group)
  return pdfJobBlob(`/finanzas/reporte/pdf/?${qs.toString()}`)
}

/**
 * Descarga el PDF del reporte y dispara la descarga del archivo en el navegador.
 * Mismo patrón blob + object URL que getPatientBookPdf (libro clínico): intenta
 * abrir en pestaña nueva; si el navegador la bloquea, cae a descarga directa.
 */
export async function downloadReportPdf(params: {
  date_from: string
  date_to: string
  group?: ReportGroup
}): Promise<void> {
  const blob = await fetchReportPdfBlob(params)
  const url = URL.createObjectURL(blob)
  const filename = `reporte-${params.date_from}-${params.date_to}.pdf`
  const win = window.open(url, '_blank', 'noopener,noreferrer')
  if (!win) {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

// ---------------------------------------------------------------------------
// Fase 2 — Cierre diario (day sheet)
//
// Refleja EXACTO apps/finanzas/selectors.py::finance_daily_sheet.
// ---------------------------------------------------------------------------

/** Movimiento del cierre diario: cargo o pago. Los campos opcionales dependen del tipo. */
export interface DailySheetMovement {
  at: string
  type: 'charge' | 'payment'
  patient_id: string
  amount: number
  // Solo en cargos:
  description?: string
  status?: ChargeStatus
  // Solo en pagos:
  method?: PaymentMethod
  method_label?: string
  reference?: string
  /**
   * Sede donde se generó el movimiento (multi-sede). El cierre diario ya viene
   * filtrado por la sede activa (header), pero se muestra la columna "Sede" para
   * que el consolidado ("Todas las sucursales") sea legible. Opcional: los
   * movimientos históricos (o un backend aún sin el campo) llegan sin él.
   */
  sucursal?: SucursalRef | null
}

/** Totales-resumen del cierre diario. */
export interface DailySheetTotals {
  charges_count: number
  payments_count: number
  production: number
  collection: number
}

/** Cierre de caja de un día concreto (producción/cobranza/ajustes + desglose + movimientos). */
export interface DailySheet {
  date: string
  production: number
  collection: number
  adjustments_total: number
  collection_pct: number
  by_method: ReportByMethod[]
  movements: DailySheetMovement[]
  totals: DailySheetTotals
}

/** GET /finanzas/cierre-diario/?date=YYYY-MM-DD — cierre de caja del día. */
export function fetchDailySheet(date: string): Promise<DailySheet> {
  return http.get<DailySheet>('/finanzas/cierre-diario/', { date })
}

// ---------------------------------------------------------------------------
// Fase 3 — Panel de retención (RFM) — SOLO VISUALIZACIÓN (D-7: sin campañas)
//
// Refleja EXACTO el dict de apps/finanzas/retention.py::retention_panel_build
// (selector llamado desde RetentionPanelApi). No inventar nombres de campo.
// Los montos llegan como string decimal o number desde DRF; se tipan como
// `number` y se normalizan con toNumber/formatMoney en la UI.
// ---------------------------------------------------------------------------

/** Segmentos RFM devueltos por el backend (claves EXACTAS de `segments`). */
export type RetentionSegment =
  | 'nuevo'
  | 'vip'
  | 'frecuente'
  | 'en_riesgo'
  | 'perdido'
  | 'ocasional'

/** Conteo de pacientes por segmento. Una clave por cada RetentionSegment. */
export type RetentionSegments = Record<RetentionSegment, number>

/**
 * Una entrada de las listas accionables (`at_risk_list` / `lost_list`).
 * `last_visited` es la fecha ISO (YYYY-MM-DD) de la última cita atendida o null.
 * `recency_days` puede venir null si el paciente nunca tuvo cita registrada.
 */
export interface RetentionActionablePatient {
  patient_id: string
  full_name: string
  phone: string
  email: string
  last_visited: string | null
  recency_days: number | null
  spent_12m: number
  freq_12m: number
}

/**
 * Métricas globales del panel. retention_rate / no_show_rate / pct_with_future_appt
 * pueden venir null cuando no hay base de cálculo (denominador 0).
 * avg_ticket siempre llega como número (0 si no hubo pagos).
 */
export interface RetentionMetrics {
  retention_rate: number | null
  avg_ticket: number
  no_show_rate: number | null
  pct_with_future_appt: number | null
  patients_seen_12m: number
  patients_seen_prev_12m: number
}

/**
 * Dataset completo del panel de retención. Refleja 1:1 retention_panel_build().
 * `total_at_risk` / `total_lost` son los totales reales (pueden superar el cap de
 * 500 con que vienen las listas); `truncated` es true si alguna lista fue recortada.
 */
export interface RetentionPanel {
  segments: RetentionSegments
  at_risk_list: RetentionActionablePatient[]
  lost_list: RetentionActionablePatient[]
  total_at_risk: number
  total_lost: number
  truncated: boolean
  metrics: RetentionMetrics
}

/** GET /finanzas/retencion/ — panel RFM (distribución + listas accionables + métricas). */
export function fetchRetention(): Promise<RetentionPanel> {
  return http.get<RetentionPanel>('/finanzas/retencion/')
}

// ---------------------------------------------------------------------------
// Conceptos
// ---------------------------------------------------------------------------

export interface ServiceConcept {
  id: string
  name: string
  description: string
  /**
   * Descripción CLÍNICA del tratamiento (independiente de `description`, que es
   * la comercial/fiscal). Se muestra por cada tratamiento en el Plan Integral de
   * Longevidad y Medicina Regenerativa del paciente. '' si no se capturó.
   */
  clinical_description: string
  base_price: number
  sat_product_key: string
  sat_unit_key: string
  is_active: boolean
  created_at: string
  /**
   * Sedes DONDE está disponible este servicio (multi-sede). **`[]` = todas las
   * sedes.** El precio es el mismo en todas (no hay precio por sede).
   */
  sucursales: SucursalRef[]
}

export function fetchConcepts(
  opts: { includeInactive?: boolean } = {},
): Promise<Paginated<ServiceConcept>> {
  return http.get<Paginated<ServiceConcept>>(
    '/finanzas/conceptos/',
    opts.includeInactive ? { only_active: 'false' } : {},
  )
}

export interface ConceptInput {
  name: string
  base_price: number
  description?: string
  /** Descripción clínica del tratamiento (aparece en el Plan Integral del paciente). */
  clinical_description?: string
  sat_product_key?: string
  sat_unit_key?: string
  /** Solo en PATCH: reactivar un concepto previamente desactivado. */
  is_active?: boolean
  /**
   * Sedes DONDE queda disponible (multi-sede). **`[]` = todas las sedes.** En
   * PATCH, omitirlo = no tocar la asignación actual. Solo el dueño puede enviarlo.
   */
  sucursal_ids?: string[]
}

export function createConcept(input: ConceptInput): Promise<ServiceConcept> {
  return http.post<ServiceConcept>('/finanzas/conceptos/', input)
}

export function updateConcept(id: string, input: Partial<ConceptInput>): Promise<ServiceConcept> {
  return http.patch<ServiceConcept>(`/finanzas/conceptos/${id}/`, input)
}

export function deactivateConcept(id: string): Promise<void> {
  return http.delete<void>(`/finanzas/conceptos/${id}/`)
}

// ---------------------------------------------------------------------------
// Cotizaciones
// ---------------------------------------------------------------------------

export type QuoteStatus = 'draft' | 'sent' | 'accepted' | 'rejected' | 'expired'

export interface QuoteItem {
  id: string
  concept: string | null
  description: string
  quantity: number
  unit_price: number
  discount: number
  line_total: number
}

export interface Quote {
  id: string
  patient: string
  status: QuoteStatus
  status_display: string
  valid_until: string | null
  notes: string
  subtotal: number
  discount_total: number
  total: number
  items: QuoteItem[]
  created_at: string
  /** Sede DONDE se generó la cotización. null en cotizaciones históricas. */
  sucursal: SucursalRef | null
}

export interface QuoteItemInput {
  concept_id?: string | null
  description?: string
  quantity?: number
  unit_price?: number
  discount?: number
}

export interface QuoteInput {
  patient_id: string
  valid_until?: string | null
  notes?: string
  items: QuoteItemInput[]
}

export function fetchQuotes(params: { patient_id?: string; status?: string } = {}): Promise<
  Paginated<Quote>
> {
  return http.get<Paginated<Quote>>('/finanzas/cotizaciones/', params)
}

export function createQuote(input: QuoteInput): Promise<Quote> {
  return http.post<Quote>('/finanzas/cotizaciones/', input)
}

export function sendQuote(quoteId: string): Promise<Quote> {
  return http.post<Quote>(`/finanzas/cotizaciones/${quoteId}/enviar/`)
}

export function acceptQuote(quoteId: string): Promise<Quote> {
  return http.post<Quote>(`/finanzas/cotizaciones/${quoteId}/aceptar/`)
}

/**
 * GET /finanzas/cotizaciones/<id>/pdf/ — PDF de la cotización como Blob.
 * Flujo asíncrono (Celery): el endpoint ENCOLA y `pdfJobBlob` hace el polling y la
 * descarga por dentro. La cotización es mutable → siempre fresco (sin caché).
 * El token nunca va en la URL. Lo consume el visor inline (VisorPdf) y downloadQuotePdf.
 */
export async function fetchQuotePdfBlob(quoteId: string): Promise<Blob> {
  return pdfJobBlob(`/finanzas/cotizaciones/${quoteId}/pdf/`)
}

/**
 * Descarga el PDF de la cotización y lo abre/guarda. Mismo patrón blob + object
 * URL que downloadReportPdf / getPatientBookPdf: intenta abrir en pestaña nueva;
 * si el navegador la bloquea, cae a descarga directa.
 */
export async function downloadQuotePdf(quoteId: string): Promise<void> {
  const blob = await fetchQuotePdfBlob(quoteId)
  const url = URL.createObjectURL(blob)
  const filename = `cotizacion-${quoteId}.pdf`
  const win = window.open(url, '_blank', 'noopener,noreferrer')
  if (!win) {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

// ---------------------------------------------------------------------------
// Cargos
// ---------------------------------------------------------------------------

export type ChargeStatus = 'pending' | 'partial' | 'paid' | 'cancelled'

export interface Charge {
  id: string
  patient: string
  concept: string | null
  description: string
  appointment: string | null
  quote: string | null
  amount: number
  amount_paid: number
  balance: number
  status: ChargeStatus
  status_display: string
  issued_at: string
  created_at: string
  /** Sede DONDE se generó el cargo. null en cargos históricos (pre-sucursales). */
  sucursal: SucursalRef | null
}

export interface ChargeInput {
  patient_id: string
  description: string
  amount: number
  concept_id?: string | null
}

export interface ChargesParams {
  patient_id?: string
  status?: string
  /** UUID de la cita: filtra los cargos de UNA visita (estado de cuenta de la visita). */
  appointment?: string
}

export function fetchCharges(params: ChargesParams = {}): Promise<Paginated<Charge>> {
  return http.get<Paginated<Charge>>('/finanzas/cargos/', params)
}

export function createCharge(input: ChargeInput): Promise<Charge> {
  return http.post<Charge>('/finanzas/cargos/', input)
}

export function cancelCharge(chargeId: string): Promise<void> {
  return http.delete<void>(`/finanzas/cargos/${chargeId}/`)
}

// ---------------------------------------------------------------------------
// Pagos
// ---------------------------------------------------------------------------

export type PaymentMethod = 'cash' | 'card' | 'transfer' | 'other'

export interface PaymentAllocation {
  id: string
  charge: string
  amount: number
}

export interface Payment {
  id: string
  patient: string
  amount: number
  method: PaymentMethod
  method_display: string
  reference: string
  received_at: string
  notes: string
  allocations: PaymentAllocation[]
  created_at: string
  /** Sede DONDE se cobró el pago. null en pagos históricos (pre-sucursales). */
  sucursal: SucursalRef | null
}

export interface PaymentInput {
  patient_id: string
  amount: number
  method?: PaymentMethod
  reference?: string
  notes?: string
  allocations?: { charge_id: string; amount: number }[]
}

export function fetchPayments(params: { patient_id?: string; method?: string } = {}): Promise<
  Paginated<Payment>
> {
  return http.get<Paginated<Payment>>('/finanzas/pagos/', params)
}

export function registerPayment(input: PaymentInput): Promise<Payment> {
  return http.post<Payment>('/finanzas/pagos/', input)
}

// ---------------------------------------------------------------------------
// CFDI
// ---------------------------------------------------------------------------

export type CfdiStatus = 'draft' | 'stamped' | 'cancelled'

export interface CfdiDocument {
  id: string
  payment: string | null
  patient: string
  status: CfdiStatus
  status_display: string
  series: string
  folio: number | null
  uuid_sat: string
  receptor_rfc: string
  receptor_name: string
  cfdi_use: string
  payment_form: string
  payment_method: string
  subtotal: number
  total: number
  xml_url: string
  pdf_url: string
  stamped_at: string | null
  cancelled_at: string | null
  created_at: string
}

export interface CfdiIssueInput {
  payment_id: string
  receptor_rfc: string
  receptor_name: string
  receptor_tax_regime?: string
  receptor_postal_code?: string
  cfdi_use?: string
  payment_form?: string
  payment_method?: string
}

export function fetchCfdiList(params: { patient_id?: string; status?: string } = {}): Promise<
  Paginated<CfdiDocument>
> {
  return http.get<Paginated<CfdiDocument>>('/finanzas/cfdi/', params)
}

export function issueCfdi(input: CfdiIssueInput): Promise<CfdiDocument> {
  return http.post<CfdiDocument>('/finanzas/cfdi/', input)
}

export function cancelCfdi(cfdiId: string, reason = '02'): Promise<CfdiDocument> {
  return http.post<CfdiDocument>(`/finanzas/cfdi/${cfdiId}/cancelar/`, { reason })
}

// ---------------------------------------------------------------------------
// Estado de cuenta
// ---------------------------------------------------------------------------

export interface StatementMovement {
  id: string
  date: string
  type: 'charge' | 'payment'
  description: string
  charge: number
  payment: number
  balance: number
  reference: string
  /**
   * Sede DONDE se generó el movimiento. El estado de cuenta del paciente es
   * COMPARTIDO entre sedes (trae todos sus movimientos, de cualquier sucursal),
   * por eso se muestra la sede de cada línea. Opcional: los movimientos
   * históricos (o un backend aún sin el campo) llegan sin él.
   */
  sucursal?: SucursalRef | null
}

export interface AccountStatement {
  movements: StatementMovement[]
  total_charged: number
  total_paid: number
  balance: number
  charges_count: number
  payments_count: number
  patient: { id: string; full_name: string; record_number: string }
}

export function fetchStatement(
  patientId: string,
  params: DateRangeParams = {},
): Promise<AccountStatement> {
  return http.get<AccountStatement>(`/finanzas/estado-cuenta/${patientId}/`, params)
}

// ---------------------------------------------------------------------------
// Config fiscal
// ---------------------------------------------------------------------------

export interface FiscalConfig {
  id: string
  rfc: string
  legal_name: string
  tax_regime: string
  postal_code: string
  series: string
  next_folio: number
  created_at: string
}

export function fetchFiscalConfig(): Promise<FiscalConfig> {
  return http.get<FiscalConfig>('/finanzas/config/')
}

export function updateFiscalConfig(input: Partial<FiscalConfig>): Promise<FiscalConfig> {
  return http.patch<FiscalConfig>('/finanzas/config/', input)
}
