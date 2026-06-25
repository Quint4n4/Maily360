/**
 * Capa de API tipada del dominio finanzas.
 *
 * Cada función mapea 1:1 a un endpoint de /api/v1/finanzas/. Los componentes
 * NO llaman a estas funciones directamente: lo hacen vía los hooks de
 * src/hooks/finanzas.ts (TanStack Query).
 */

import { http } from '../lib/http'

// ---------------------------------------------------------------------------
// Tipos compartidos
// ---------------------------------------------------------------------------

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
// Conceptos
// ---------------------------------------------------------------------------

export interface ServiceConcept {
  id: string
  name: string
  description: string
  base_price: number
  sat_product_key: string
  sat_unit_key: string
  is_active: boolean
  created_at: string
}

export function fetchConcepts(): Promise<Paginated<ServiceConcept>> {
  return http.get<Paginated<ServiceConcept>>('/finanzas/conceptos/')
}

export interface ConceptInput {
  name: string
  base_price: number
  description?: string
  sat_product_key?: string
  sat_unit_key?: string
}

export function createConcept(input: ConceptInput): Promise<ServiceConcept> {
  return http.post<ServiceConcept>('/finanzas/conceptos/', input)
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
}

export interface ChargeInput {
  patient_id: string
  description: string
  amount: number
  concept_id?: string | null
}

export function fetchCharges(params: { patient_id?: string; status?: string } = {}): Promise<
  Paginated<Charge>
> {
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
