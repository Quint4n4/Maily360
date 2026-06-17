/**
 * Hooks de TanStack Query para el dominio Paciente.
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createPatient,
  createPatientQuick,
  deactivatePatient,
  getPatient,
  listPatients,
  setPatientClassification,
  updatePatient,
  uploadPatientAvatar,
} from '../api/pacientes'
import type {
  PatientClassifyInput,
  PatientCreateInput,
  PatientQuickCreateInput,
  PatientSegment,
  PatientUpdateInput,
} from '../types/paciente'

export interface UsePatientsParams {
  search?: string
  segment?: PatientSegment
  dateFrom?: string
  dateTo?: string
}

/** Claves de caché. Todo lo de pacientes cuelga de ['pacientes']. */
export const pacientesKeys = {
  all: ['pacientes'] as const,
  list: (p: UsePatientsParams) =>
    ['pacientes', 'list', p.segment ?? 'all', p.search ?? '', p.dateFrom ?? '', p.dateTo ?? ''] as const,
  detail: (id: string) => ['pacientes', 'detail', id] as const,
}

/** Detalle de un paciente por id (para abrir su expediente directo, p. ej. desde la campana). */
export function usePatient(id: string | null) {
  return useQuery({
    queryKey: pacientesKeys.detail(id ?? ''),
    queryFn: () => getPatient(id as string),
    enabled: !!id,
  })
}

/** Lista paginada (primera página) con búsqueda + segmento server-side.
 *  Con segment='date' la consulta queda deshabilitada hasta tener ambas fechas. */
export function usePatients(params: UsePatientsParams = {}) {
  const { search = '', segment = 'all', dateFrom, dateTo } = params
  const faltanFechas = segment === 'date' && (!dateFrom || !dateTo)
  return useQuery({
    queryKey: pacientesKeys.list(params),
    queryFn: () => listPatients({ search, segment, date_from: dateFrom, date_to: dateTo }),
    enabled: !faltanFechas,
  })
}

/** Alta de paciente. Invalida la lista al terminar. */
export function useCreatePatient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PatientCreateInput) => createPatient(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: pacientesKeys.all }),
  })
}

/** Alta rápida/provisional. Invalida la lista al terminar. */
export function useCreatePatientQuick() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PatientQuickCreateInput) => createPatientQuick(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: pacientesKeys.all }),
  })
}

/** Actualización parcial. Invalida la lista al terminar. */
export function useUpdatePatient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: PatientUpdateInput }) => updatePatient(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: pacientesKeys.all }),
  })
}

/** Subir foto del paciente. Invalida la lista al terminar. */
export function useUploadPatientAvatar() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) => uploadPatientAvatar(id, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: pacientesKeys.all }),
  })
}

/** Baja lógica. Invalida la lista al terminar. */
export function useDeactivatePatient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deactivatePatient(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: pacientesKeys.all }),
  })
}

/** Marca/desmarca favorito y/o VIP. Invalida la lista al terminar. */
export function useSetPatientClassification() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: PatientClassifyInput }) =>
      setPatientClassification(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: pacientesKeys.all }),
  })
}
