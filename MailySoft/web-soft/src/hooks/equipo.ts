/**
 * Hooks de TanStack Query para el equipo / departamentos de la clínica (Fase 4).
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 *
 * Convención de claves:
 *   ['equipo', 'lista'] → lista de integrantes
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '../api/equipo'
import type {
  EquipoMiembroCreateInput,
  EquipoMiembroUpdateInput,
} from '../types/equipo'

export const equipoKeys = {
  all: ['equipo'] as const,
  lista: (onlyActive: boolean) => ['equipo', 'lista', onlyActive] as const,
}

/**
 * Lista del equipo (paginada → usar .results). Por defecto solo activos; la
 * gestión pasa `onlyActive: false` para ver y reactivar los desactivados.
 */
export function useEquipo(opts: { onlyActive?: boolean } = {}) {
  const onlyActive = opts.onlyActive ?? true
  return useQuery({
    queryKey: equipoKeys.lista(onlyActive),
    queryFn: () => api.listEquipo({ onlyActive }),
  })
}

/** Crea un integrante. Invalida las listas del equipo. */
export function useCrearEquipoMiembro() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: EquipoMiembroCreateInput) => api.createEquipoMiembro(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: equipoKeys.all }),
  })
}

/** Actualiza (PATCH) un integrante. Invalida las listas del equipo. */
export function useActualizarEquipoMiembro() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: EquipoMiembroUpdateInput }) =>
      api.updateEquipoMiembro(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: equipoKeys.all }),
  })
}

/** Elimina un integrante. Invalida las listas del equipo. */
export function useEliminarEquipoMiembro() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteEquipoMiembro(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: equipoKeys.all }),
  })
}
