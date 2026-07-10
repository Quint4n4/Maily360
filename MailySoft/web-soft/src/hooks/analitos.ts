/**
 * Hooks de TanStack Query para el catálogo de analitos (Fase 3).
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 *
 * Convención de claves:
 *   ['analitos', 'lista', onlyActive] → lista de analitos
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '../api/analitos'
import type { AnalitoCreateInput, AnalitoUpdateInput } from '../types/analitos'

export const analitosKeys = {
  all: ['analitos'] as const,
  lista: (onlyActive: boolean) => ['analitos', 'lista', onlyActive] as const,
}

/**
 * Lista de analitos (paginada → usar .results). Por defecto solo activos (picker
 * del Plan Integral); pasar `{ onlyActive: false }` para la gestión (incluye inactivos).
 */
export function useAnalitos(opts: { onlyActive?: boolean } = {}) {
  const onlyActive = opts.onlyActive ?? true
  return useQuery({
    queryKey: analitosKeys.lista(onlyActive),
    queryFn: () => api.listAnalitos({ onlyActive }),
  })
}

/** Crea un analito. Invalida las listas de analitos. */
export function useCrearAnalito() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: AnalitoCreateInput) => api.createAnalito(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: analitosKeys.all }),
  })
}

/** Actualiza (PATCH) un analito. Invalida las listas de analitos. */
export function useActualizarAnalito() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: AnalitoUpdateInput }) =>
      api.updateAnalito(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: analitosKeys.all }),
  })
}

/** Elimina un analito. Invalida las listas de analitos. */
export function useEliminarAnalito() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteAnalito(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: analitosKeys.all }),
  })
}
