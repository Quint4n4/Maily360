/** Hooks de TanStack Query para la configuración de agenda de la clínica. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAgendaConfig, updateAgendaConfig } from '../api/agendaConfig'
import type { AgendaConfigUpdateInput } from '../types/agendaConfig'

export const agendaConfigKey = ['agenda', 'config'] as const

/**
 * Configuración de agenda (horario de apertura/cierre e intervalo de rejilla).
 *
 * NO lleva la sede en la queryKey: es configuración de la CLÍNICA (aplica a
 * todas las sucursales por igual), no algo privado por sede.
 */
export function useAgendaConfig() {
  return useQuery({
    queryKey: agendaConfigKey,
    queryFn: getAgendaConfig,
    // La agenda se pinta con esto: que no parpadee entre navegaciones.
    staleTime: 5 * 60 * 1000,
  })
}

/** Actualiza la configuración (solo owner/admin; el backend responde 403 al resto). */
export function useActualizarAgendaConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: AgendaConfigUpdateInput) => updateAgendaConfig(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaConfigKey }),
  })
}
