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
// Conceptos
// ---------------------------------------------------------------------------

export function useConcepts() {
  return useQuery({
    queryKey: finanzasKeys.concepts(),
    queryFn: () => api.fetchConcepts(),
  })
}

export function useCreateConcept() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: api.ConceptInput) => api.createConcept(input),
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
