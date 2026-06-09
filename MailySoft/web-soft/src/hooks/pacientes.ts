/**
 * Hooks de TanStack Query para el dominio Paciente.
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createPatient,
  createPatientQuick,
  deactivatePatient,
  listPatients,
  updatePatient,
} from '../api/pacientes'
import type {
  PatientCreateInput,
  PatientQuickCreateInput,
  PatientUpdateInput,
} from '../types/paciente'

/** Claves de caché. Todo lo de pacientes cuelga de ['pacientes']. */
export const pacientesKeys = {
  all: ['pacientes'] as const,
  list: (search: string) => ['pacientes', 'list', search] as const,
}

/** Lista paginada (primera página) con búsqueda server-side. */
export function usePatients(search: string) {
  return useQuery({
    queryKey: pacientesKeys.list(search),
    queryFn: () => listPatients({ search }),
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

/** Baja lógica. Invalida la lista al terminar. */
export function useDeactivatePatient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deactivatePatient(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: pacientesKeys.all }),
  })
}
