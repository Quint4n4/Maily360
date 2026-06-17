/**
 * Hooks de TanStack Query para el Expediente Clínico (A1–A4).
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 *
 * Convención de claves: ['expediente', patientId, <recurso>].
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createAddendum,
  createAllergy,
  createDiagnosis,
  createEvolutionNote,
  createVitalSigns,
  deleteEvolutionImage,
  getEvolutionImages,
  getMedicalHistory,
  getNursingInstructions,
  getVitalSignsSeries,
  listAllergies,
  listDiagnoses,
  listEvolutionNotes,
  listVitalSigns,
  resolveAllergy,
  resolveDiagnosis,
  uploadEvolutionImage,
  upsertMedicalHistory,
} from '../api/expediente'
import type {
  AddendumInput,
  AllergyInput,
  DiagnosisInput,
  EvolutionNoteInput,
  MedicalHistoryInput,
  VitalSignsInput,
} from '../types/expediente'

/** Claves de caché. Todo lo del expediente de un paciente cuelga de ['expediente', patientId]. */
export const expedienteKeys = {
  all: (patientId: string) => ['expediente', patientId] as const,
  alergias: (patientId: string, includeResolved: boolean) =>
    ['expediente', patientId, 'alergias', includeResolved] as const,
  historia: (patientId: string) => ['expediente', patientId, 'historia'] as const,
  signos: (patientId: string) => ['expediente', patientId, 'signos'] as const,
  signosSeries: (patientId: string, since: string) =>
    ['expediente', patientId, 'signos', 'series', since] as const,
  evoluciones: (patientId: string) => ['expediente', patientId, 'evoluciones'] as const,
  evolucionImagenes: (evolutionId: string) =>
    ['expediente', 'evolucion', evolutionId, 'imagenes'] as const,
  indicacionesEnfermeria: (patientId: string) =>
    ['expediente', patientId, 'indicaciones-enfermeria'] as const,
  diagnosticos: (patientId: string, onlyActive: boolean) =>
    ['expediente', patientId, 'diagnosticos', onlyActive] as const,
}

// ── A1 — Alergias ───────────────────────────────────────────────────────────

/** Lista de alergias del paciente (vigentes por defecto). */
export function useAllergies(patientId: string | null, includeResolved = false) {
  return useQuery({
    queryKey: expedienteKeys.alergias(patientId ?? '', includeResolved),
    queryFn: () => listAllergies(patientId as string, includeResolved),
    enabled: !!patientId,
  })
}

/** Alta de alergia. Invalida las alergias del paciente. */
export function useCreateAllergy(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: AllergyInput) => createAllergy(patientId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: expedienteKeys.all(patientId) }),
  })
}

/** Resolver (baja lógica) una alergia. Invalida las alergias del paciente. */
export function useResolveAllergy(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (allergyId: string) => resolveAllergy(allergyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: expedienteKeys.all(patientId) }),
  })
}

// ── A2 — Historia clínica ─────────────────────────────────────────────────────

/** Historia clínica del paciente (documento vivo). */
export function useMedicalHistory(patientId: string | null) {
  return useQuery({
    queryKey: expedienteKeys.historia(patientId ?? ''),
    queryFn: () => getMedicalHistory(patientId as string),
    enabled: !!patientId,
  })
}

/** Upsert de la HC. Invalida la HC del paciente. */
export function useUpsertMedicalHistory(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: MedicalHistoryInput) => upsertMedicalHistory(patientId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: expedienteKeys.historia(patientId) }),
  })
}

// ── A3 — Signos vitales ───────────────────────────────────────────────────────

/** Tomas de signos vitales (primera página, paginada → usar .results). */
export function useVitalSigns(patientId: string | null) {
  return useQuery({
    queryKey: expedienteKeys.signos(patientId ?? ''),
    queryFn: () => listVitalSigns(patientId as string),
    enabled: !!patientId,
  })
}

/** Series temporales para gráficas. `since` opcional ('yyyy-mm-dd'). */
export function useVitalSignsSeries(patientId: string | null, since = '') {
  return useQuery({
    queryKey: expedienteKeys.signosSeries(patientId ?? '', since),
    queryFn: () => getVitalSignsSeries(patientId as string, since || undefined),
    enabled: !!patientId,
  })
}

/** Captura de una toma. Invalida las tomas y las series del paciente. */
export function useCreateVitalSigns(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: VitalSignsInput) => createVitalSigns(patientId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: expedienteKeys.signos(patientId) }),
  })
}

// ── A4 — Notas de evolución ───────────────────────────────────────────────────

/** Notas de evolución del paciente (primera página, paginada → usar .results). */
export function useEvolutionNotes(patientId: string | null) {
  return useQuery({
    queryKey: expedienteKeys.evoluciones(patientId ?? ''),
    queryFn: () => listEvolutionNotes(patientId as string),
    enabled: !!patientId,
  })
}

/** Alta de nota de evolución. Invalida las evoluciones (y diagnósticos, por si nacen de ahí). */
export function useCreateEvolutionNote(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: EvolutionNoteInput) => createEvolutionNote(patientId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: expedienteKeys.all(patientId) }),
  })
}

/** Addendum sobre una nota. Invalida las evoluciones del paciente. */
export function useCreateAddendum(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ evolutionId, input }: { evolutionId: string; input: AddendumInput }) =>
      createAddendum(evolutionId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: expedienteKeys.evoluciones(patientId) }),
  })
}

// ── A4 — Imágenes de la nota de evolución ─────────────────────────────────────

/** Imágenes adjuntas a una nota de evolución. Se carga al montar el NotaCard. */
export function useEvolutionImages(evolutionId: string | null) {
  return useQuery({
    queryKey: expedienteKeys.evolucionImagenes(evolutionId ?? ''),
    queryFn: () => getEvolutionImages(evolutionId as string),
    enabled: !!evolutionId,
  })
}

/** Sube una imagen (multipart) a la nota. Invalida la lista de imágenes de esa nota. */
export function useUploadEvolutionImage(evolutionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, caption }: { file: File; caption?: string }) =>
      uploadEvolutionImage(evolutionId, file, caption),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: expedienteKeys.evolucionImagenes(evolutionId) }),
  })
}

/** Baja lógica de una imagen. Invalida la lista de imágenes de esa nota. */
export function useDeleteEvolutionImage(evolutionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (imageId: string) => deleteEvolutionImage(imageId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: expedienteKeys.evolucionImagenes(evolutionId) }),
  })
}

// ── A4 — Indicaciones para enfermería ─────────────────────────────────────────

/** Indicaciones para enfermería del paciente (derivadas de las evoluciones). */
export function useNursingInstructions(patientId: string | null) {
  return useQuery({
    queryKey: expedienteKeys.indicacionesEnfermeria(patientId ?? ''),
    queryFn: () => getNursingInstructions(patientId as string),
    enabled: !!patientId,
  })
}

// ── A4 — Diagnósticos ─────────────────────────────────────────────────────────

/** Diagnósticos del paciente (activos + resueltos por defecto). */
export function useDiagnoses(patientId: string | null, onlyActive = false) {
  return useQuery({
    queryKey: expedienteKeys.diagnosticos(patientId ?? '', onlyActive),
    queryFn: () => listDiagnoses(patientId as string, onlyActive),
    enabled: !!patientId,
  })
}

/** Alta de diagnóstico. Invalida los diagnósticos del paciente. */
export function useCreateDiagnosis(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: DiagnosisInput) => createDiagnosis(patientId, input),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['expediente', patientId, 'diagnosticos'] }),
  })
}

/** Resolver un diagnóstico. Invalida los diagnósticos del paciente. */
export function useResolveDiagnosis(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (diagnosisId: string) => resolveDiagnosis(diagnosisId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['expediente', patientId, 'diagnosticos'] }),
  })
}
