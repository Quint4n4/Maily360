/**
 * Hooks de TanStack Query para Recetas (B1.1–B1.3).
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 *
 * Convención de claves:
 *   ['recetas', patientId]            → todo lo de un paciente (historial)
 *   ['recetas', 'detalle', id]        → detalle de una receta
 *   ['medicamentos', 'buscar', q]     → autocompletado del catálogo
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  cancelPrescription,
  createMedication,
  createPrescription,
  createPrescriptionFormat,
  deletePrescriptionFormat,
  getPrescription,
  getPrescriptionPdf,
  getPrescriptionPdfWithFormat,
  listPrescriptionFormats,
  listPrescriptions,
  searchMedications,
  updatePrescriptionFormat,
} from '../api/recetas'
import type {
  ItemKind,
  MedicationCreateInput,
  PrescriptionCancelInput,
  PrescriptionCreateInput,
  PrescriptionFormatCreateInput,
  PrescriptionFormatUpdateInput,
} from '../types/recetas'

/** Claves de caché del dominio recetas. */
export const recetasKeys = {
  delPaciente: (patientId: string) => ['recetas', patientId] as const,
  detalle: (prescriptionId: string) => ['recetas', 'detalle', prescriptionId] as const,
  buscarMedicamentos: (q: string, kind?: ItemKind) =>
    ['medicamentos', 'buscar', q, kind ?? 'todos'] as const,
  formatos: ['recetas', 'formatos'] as const,
}

// ── B1.1 — Autocompletado de medicamentos ──────────────────────────────────────

/**
 * Autocompletado de medicamentos. Se habilita solo con `q` no vacío para no
 * llamar al backend en cada montaje. El debounce del input lo hace el caller.
 */
export function useMedicationSearch(q: string, enabled = true, kind?: ItemKind) {
  const term = q.trim()
  return useQuery({
    queryKey: recetasKeys.buscarMedicamentos(term, kind),
    queryFn: ({ signal }) => searchMedications(term, 25, signal, kind),
    enabled: enabled && term.length >= 1,
    // El catálogo cambia poco: mantenemos resultados frescos un rato.
    staleTime: 60_000,
  })
}

/** Alta de un medicamento custom. Invalida el autocompletado. */
export function useCreateMedication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: MedicationCreateInput) => createMedication(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['medicamentos', 'buscar'] }),
  })
}

// ── B1.2 — Recetas ─────────────────────────────────────────────────────────────

/** Historial de recetas del paciente (primera página, paginado → usar .results). */
export function usePrescriptions(patientId: string | null) {
  return useQuery({
    queryKey: recetasKeys.delPaciente(patientId ?? ''),
    queryFn: () => listPrescriptions(patientId as string),
    enabled: !!patientId,
  })
}

/** Detalle de una receta. Se usa para "copiar de previa" (carga bajo demanda). */
export function usePrescriptionDetail(prescriptionId: string | null) {
  return useQuery({
    queryKey: recetasKeys.detalle(prescriptionId ?? ''),
    queryFn: () => getPrescription(prescriptionId as string),
    enabled: !!prescriptionId,
  })
}

/** Emite una receta. Invalida el historial del paciente. Devuelve el detalle. */
export function useCreatePrescription(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PrescriptionCreateInput) => createPrescription(patientId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: recetasKeys.delPaciente(patientId) }),
  })
}

/** Anula una receta con motivo. Invalida el historial del paciente y su detalle. */
export function useCancelPrescription(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ prescriptionId, input }: { prescriptionId: string; input: PrescriptionCancelInput }) =>
      cancelPrescription(prescriptionId, input),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: recetasKeys.delPaciente(patientId) })
      qc.invalidateQueries({ queryKey: recetasKeys.detalle(vars.prescriptionId) })
    },
  })
}

// ── B1.3 — PDF ───────────────────────────────────────────────────────────────

/**
 * Descarga el PDF (Bearer) y lo abre en una pestaña nueva mediante un object URL
 * temporal que se revoca tras un momento. Devuelve un mutation para manejar
 * loading/error desde la UI.
 *
 * Por qué mutation y no query: la apertura del PDF es una acción puntual del
 * usuario (clic en "Ver PDF"), no un dato cacheable por receta.
 */
export function useOpenPrescriptionPdf() {
  return useMutation({
    mutationFn: async (prescriptionId: string): Promise<void> => {
      const blob = await getPrescriptionPdf(prescriptionId)
      const url = URL.createObjectURL(blob)
      // Abrir en pestaña nueva. El navegador muestra el visor de PDF inline.
      window.open(url, '_blank', 'noopener,noreferrer')
      // Revocar tras un margen para que la pestaña alcance a cargar el recurso.
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    },
  })
}

/**
 * Abre el PDF de una receta de ejemplo con un override de formato (vista previa
 * de la galería). Acepta `formatId` (formato persistido) o `formato` (layout por
 * nombre). Mismo patrón blob+object URL que useOpenPrescriptionPdf.
 */
export function useOpenPrescriptionPdfWithFormat() {
  return useMutation({
    mutationFn: async (params: {
      prescriptionId: string
      formato?: string
      formatId?: string
    }): Promise<void> => {
      const blob = await getPrescriptionPdfWithFormat(params.prescriptionId, {
        formato: params.formato,
        formatId: params.formatId,
      })
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener,noreferrer')
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    },
  })
}

// ── F3 — Formatos de receta (galería) ──────────────────────────────────────────

/** Lista de formatos del tenant (array directo). */
export function usePrescriptionFormats() {
  return useQuery({
    queryKey: recetasKeys.formatos,
    queryFn: listPrescriptionFormats,
  })
}

/** Crea un formato. Invalida la lista. */
export function useCreatePrescriptionFormat() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PrescriptionFormatCreateInput) => createPrescriptionFormat(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: recetasKeys.formatos }),
  })
}

/** Actualiza un formato (PATCH parcial). Invalida la lista. */
export function useUpdatePrescriptionFormat() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: PrescriptionFormatUpdateInput }) =>
      updatePrescriptionFormat(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: recetasKeys.formatos }),
  })
}

/** Borra un formato. Invalida la lista. */
export function useDeletePrescriptionFormat() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deletePrescriptionFormat(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: recetasKeys.formatos }),
  })
}
