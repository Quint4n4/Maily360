/**
 * Hooks de TanStack Query para el dominio finanzas.
 *
 * Encapsulan la capa src/api/finanzas.ts: cache, estados de carga/error e
 * invalidación. Los componentes solo consumen estos hooks.
 *
 * MULTI-SEDE (Fase 3). El backend filtra por el header `X-Sucursal-Id` (lo manda
 * el cliente http con la sede activa; sin header = consolidado sobre las sedes
 * permitidas). Como la respuesta depende de la sede, la SEDE ACTIVA forma parte
 * de la query key de todo lo que es CAJA de la sede:
 *
 *   dashboard · reporte · cierre diario · retención/RFM · antigüedad (va dentro
 *   del dashboard/reporte) · listado general de cargos y pagos.
 *
 * EXCEPCIÓN deliberada: el ESTADO DE CUENTA POR PACIENTE es COMPARTIDO entre
 * sedes (el backend devuelve todos sus movimientos, de cualquier sucursal). Su
 * key NO lleva la sede: cambiar de sede no cambia su resultado y meterla solo
 * fragmentaría la caché.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '../api/finanzas'
import { useSucursalActiva } from '../auth/SucursalContext'

/** Sede activa en la query key: null = consolidado ("Todas las sucursales"). */
type SucursalKey = string | null

// ---------------------------------------------------------------------------
// Query keys centralizadas
// ---------------------------------------------------------------------------

export const finanzasKeys = {
  all: ['finanzas'] as const,
  dashboard: (range: api.DateRangeParams, sucursalId: SucursalKey) =>
    ['finanzas', 'dashboard', range, sucursalId] as const,
  report: (params: api.PeriodReportParams, sucursalId: SucursalKey) =>
    ['finanzas', 'report', params, sucursalId] as const,
  dailySheet: (date: string, sucursalId: SucursalKey) =>
    ['finanzas', 'dailySheet', date, sucursalId] as const,
  retencion: (sucursalId: SucursalKey) => ['finanzas', 'retencion', sucursalId] as const,
  /** Catálogo de servicios: el backend lo acota por la sede activa → va en la key. */
  concepts: (sucursalId: SucursalKey) => ['finanzas', 'concepts', sucursalId] as const,
  quotes: (params: object, sucursalId: SucursalKey) =>
    ['finanzas', 'quotes', params, sucursalId] as const,
  charges: (params: object, sucursalId: SucursalKey) =>
    ['finanzas', 'charges', params, sucursalId] as const,
  payments: (params: object, sucursalId: SucursalKey) =>
    ['finanzas', 'payments', params, sucursalId] as const,
  cfdi: (params: object) => ['finanzas', 'cfdi', params] as const,
  /** Estado de cuenta del paciente: COMPARTIDO entre sedes → sin sucursal en la key. */
  statement: (patientId: string, range: api.DateRangeParams) =>
    ['finanzas', 'statement', patientId, range] as const,
  fiscalConfig: () => ['finanzas', 'fiscalConfig'] as const,
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export function useDashboard(range: api.DateRangeParams = {}) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: finanzasKeys.dashboard(range, activeSucursalId),
    queryFn: () => api.fetchDashboard(range),
  })
}

// ---------------------------------------------------------------------------
// Fase 2 — Reporte de periodo
// ---------------------------------------------------------------------------

/** Dataset completo del reporte financiero del periodo (KPIs + series + desglose). */
export function useReporte(params: api.PeriodReportParams) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: finanzasKeys.report(params, activeSucursalId),
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

/** Cierre de caja de un día EN LA SEDE ACTIVA. `date` en formato YYYY-MM-DD. */
export function useCierreDiario(date: string) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: finanzasKeys.dailySheet(date, activeSucursalId),
    queryFn: () => api.fetchDailySheet(date),
    enabled: Boolean(date),
  })
}

// ---------------------------------------------------------------------------
// Fase 3 — Panel de retención (RFM)
// ---------------------------------------------------------------------------

/** Panel de retención RFM (de la SEDE ACTIVA, o consolidado si no hay sede). */
export function useRetencion() {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: finanzasKeys.retencion(activeSucursalId),
    queryFn: () => api.fetchRetention(),
  })
}

// ---------------------------------------------------------------------------
// Conceptos
// ---------------------------------------------------------------------------

/**
 * Catálogo de servicios (conceptos). El backend lo filtra por la sede activa
 * (header `X-Sucursal-Id`), así que la sede entra en la query key: al cambiar de
 * sucursal se refetchea y en cada sede solo aparecen sus servicios (mismo patrón
 * que agenda/miembros/notas). Owner sin sede activa ("Todas") ve todo.
 */
export function useConcepts(opts: { includeInactive?: boolean } = {}) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: [...finanzasKeys.concepts(activeSucursalId), opts.includeInactive ?? false],
    queryFn: () => api.fetchConcepts(opts),
  })
}

export function useCreateConcept() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: api.ConceptInput) => api.createConcept(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'concepts'] }),
  })
}

export function useUpdateConcept() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<api.ConceptInput> }) =>
      api.updateConcept(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'concepts'] }),
  })
}

export function useDeactivateConcept() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deactivateConcept(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finanzas', 'concepts'] }),
  })
}

// ---------------------------------------------------------------------------
// Cotizaciones
// ---------------------------------------------------------------------------

export function useQuotes(params: { patient_id?: string; status?: string } = {}) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: finanzasKeys.quotes(params, activeSucursalId),
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

/**
 * Listado de cargos. El backend lo filtra por la sede activa (header), así que la
 * sede va en la query key: al cambiar de sucursal se refetchea y nunca se sirve
 * la caché de otra sede. (El estado de cuenta del paciente, que sí es compartido,
 * usa `useStatement`, no este hook.)
 */
export function useCharges(params: api.ChargesParams = {}) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: finanzasKeys.charges(params, activeSucursalId),
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

/** Listado de pagos. Filtrado por sede en el backend → la sede va en la key. */
export function usePayments(params: { patient_id?: string; method?: string } = {}) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: finanzasKeys.payments(params, activeSucursalId),
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

/**
 * Estado de cuenta del paciente — COMPARTIDO ENTRE SEDES: el backend devuelve
 * TODOS sus movimientos (de cualquier sucursal) y NO lo filtra por el header.
 * Por eso la sede activa NO entra en la query key.
 */
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
