/**
 * Hooks de TanStack Query para el dominio finanzas.
 *
 * Encapsulan la capa src/api/finanzas.ts: cache, estados de carga/error e
 * invalidación. Los componentes solo consumen estos hooks.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '../api/finanzas'

// ---------------------------------------------------------------------------
// Query keys centralizadas
// ---------------------------------------------------------------------------

export const finanzasKeys = {
  all: ['finanzas'] as const,
  dashboard: (range: api.DateRangeParams) => ['finanzas', 'dashboard', range] as const,
  report: (params: api.PeriodReportParams) => ['finanzas', 'report', params] as const,
  dailySheet: (date: string) => ['finanzas', 'dailySheet', date] as const,
  retencion: () => ['finanzas', 'retencion'] as const,
  concepts: () => ['finanzas', 'concepts'] as const,
  quotes: (params: object) => ['finanzas', 'quotes', params] as const,
  charges: (params: object) => ['finanzas', 'charges', params] as const,
  payments: (params: object) => ['finanzas', 'payments', params] as const,
  cfdi: (params: object) => ['finanzas', 'cfdi', params] as const,
  statement: (patientId: string, range: api.DateRangeParams) =>
    ['finanzas', 'statement', patientId, range] as const,
  fiscalConfig: () => ['finanzas', 'fiscalConfig'] as const,
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export function useDashboard(range: api.DateRangeParams = {}) {
  return useQuery({
    queryKey: finanzasKeys.dashboard(range),
    queryFn: () => api.fetchDashboard(range),
  })
}

// ---------------------------------------------------------------------------
// Fase 2 — Reporte de periodo
// ---------------------------------------------------------------------------

/** Dataset completo del reporte financiero del periodo (KPIs + series + desglose). */
export function useReporte(params: api.PeriodReportParams) {
  return useQuery({
    queryKey: finanzasKeys.report(params),
    queryFn: () => api.fetchPeriodReport(params),
    enabled: Boolean(params.date_from && params.date_to),
  })
}

/**
 * Dispara la descarga del PDF del reporte. Mutación (efecto secundario: abre/
 * descarga un archivo); no cachea. La UI muestra isPending mientras genera.
 */
export function useDescargarReportePdf() {
  return useMutation({
    mutationFn: (params: { date_from: string; date_to: string; group?: api.ReportGroup }) =>
      api.downloadReportPdf(params),
  })
}

// ---------------------------------------------------------------------------
// Fase 2 — Cierre diario (day sheet)
// ---------------------------------------------------------------------------

/** Cierre de caja de un día. `date` en formato YYYY-MM-DD. */
export function useCierreDiario(date: string) {
  return useQuery({
    queryKey: finanzasKeys.dailySheet(date),
    queryFn: () => api.fetchDailySheet(date),
    enabled: Boolean(date),
  })
}

// ---------------------------------------------------------------------------
// Fase 3 — Panel de retención (RFM)
// ---------------------------------------------------------------------------

/** Panel de retención RFM: distribución por segmento + listas accionables + métricas. */
export function useRetencion() {
  return useQuery({
    queryKey: finanzasKeys.retencion(),
    queryFn: () => api.fetchRetention(),
  })
}

// ---------------------------------------------------------------------------
// Conceptos
// ---------------------------------------------------------------------------

export function useConcepts(opts: { includeInactive?: boolean } = {}) {
  return useQuery({
    queryKey: [...finanzasKeys.concepts(), opts.includeInactive ?? false],
    queryFn: () => api.fetchConcepts(opts),
  })
}

export function useCreateConcept() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: api.ConceptInput) => api.createConcept(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: finanzasKeys.concepts() }),
  })
}

export function useUpdateConcept() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<api.ConceptInput> }) =>
      api.updateConcept(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: finanzasKeys.concepts() }),
  })
}

export function useDeactivateConcept() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deactivateConcept(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: finanzasKeys.concepts() }),
  })
}

// ---------------------------------------------------------------------------
// Cotizaciones
// ---------------------------------------------------------------------------

export function useQuotes(params: { patient_id?: string; status?: string } = {}) {
  return useQuery({
    queryKey: finanzasKeys.quotes(params),
    queryFn: () => api.fetchQuotes(params),
  })
}

export function useCreateQuote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: api.QuoteInput) => api.createQuote(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'quotes'] }),
  })
}

export function useSendQuote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (quoteId: string) => api.sendQuote(quoteId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'quotes'] }),
  })
}

export function useAcceptQuote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (quoteId: string) => api.acceptQuote(quoteId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['finanzas', 'quotes'] })
      qc.invalidateQueries({ queryKey: ['finanzas', 'charges'] })
    },
  })
}

/**
 * Dispara la descarga del PDF de una cotización. Mutación (efecto secundario:
 * abre/descarga un archivo); no cachea. La UI muestra isPending mientras genera.
 */
export function useDownloadQuotePdf() {
  return useMutation({
    mutationFn: (quoteId: string) => api.downloadQuotePdf(quoteId),
  })
}

// ---------------------------------------------------------------------------
// Cargos
// ---------------------------------------------------------------------------

export function useCharges(params: api.ChargesParams = {}) {
  return useQuery({
    queryKey: finanzasKeys.charges(params),
    queryFn: () => api.fetchCharges(params),
  })
}

export function useCreateCharge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: api.ChargeInput) => api.createCharge(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'charges'] }),
  })
}

export function useCancelCharge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (chargeId: string) => api.cancelCharge(chargeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'charges'] }),
  })
}

// ---------------------------------------------------------------------------
// Pagos
// ---------------------------------------------------------------------------

export function usePayments(params: { patient_id?: string; method?: string } = {}) {
  return useQuery({
    queryKey: finanzasKeys.payments(params),
    queryFn: () => api.fetchPayments(params),
  })
}

export function useRegisterPayment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: api.PaymentInput) => api.registerPayment(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['finanzas', 'payments'] })
      qc.invalidateQueries({ queryKey: ['finanzas', 'charges'] })
      qc.invalidateQueries({ queryKey: ['finanzas', 'dashboard'] })
    },
  })
}

// ---------------------------------------------------------------------------
// CFDI
// ---------------------------------------------------------------------------

export function useCfdiList(params: { patient_id?: string; status?: string } = {}) {
  return useQuery({
    queryKey: finanzasKeys.cfdi(params),
    queryFn: () => api.fetchCfdiList(params),
  })
}

export function useIssueCfdi() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: api.CfdiIssueInput) => api.issueCfdi(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'cfdi'] }),
  })
}

export function useCancelCfdi() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ cfdiId, reason }: { cfdiId: string; reason?: string }) =>
      api.cancelCfdi(cfdiId, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'cfdi'] }),
  })
}

// ---------------------------------------------------------------------------
// Estado de cuenta
// ---------------------------------------------------------------------------

export function useStatement(patientId: string | null, range: api.DateRangeParams = {}) {
  return useQuery({
    queryKey: finanzasKeys.statement(patientId ?? '', range),
    queryFn: () => api.fetchStatement(patientId as string, range),
    enabled: !!patientId,
  })
}

// ---------------------------------------------------------------------------
// Config fiscal
// ---------------------------------------------------------------------------

export function useFiscalConfig() {
  return useQuery({
    queryKey: finanzasKeys.fiscalConfig(),
    queryFn: () => api.fetchFiscalConfig(),
  })
}
