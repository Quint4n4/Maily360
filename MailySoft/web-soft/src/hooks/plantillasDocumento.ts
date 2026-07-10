/**
 * Hooks de TanStack Query para el catálogo de "Plantillas de documento" (Fase 2).
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 *
 * Convención de claves:
 *   ['plantillas-documento', 'lista', section, onlyActive] → lista filtrada
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '../api/plantillasDocumento'
import type {
  PlantillaDocumentoCreateInput,
  PlantillaDocumentoSection,
  PlantillaDocumentoUpdateInput,
} from '../types/plantillasDocumento'

export const plantillasDocumentoKeys = {
  all: ['plantillas-documento'] as const,
  lista: (section: PlantillaDocumentoSection | 'all', onlyActive: boolean) =>
    ['plantillas-documento', 'lista', section, onlyActive] as const,
}

/**
 * Lista de plantillas de documento (paginada → usar .results). `section` filtra
 * por sección (picker "Insertar plantilla"); por defecto solo activas. Para la
 * página de gestión, pasar `{ onlyActive: false }` (incluye inactivas).
 */
export function usePlantillasDocumento(
  opts: { section?: PlantillaDocumentoSection; onlyActive?: boolean } = {},
) {
  const onlyActive = opts.onlyActive ?? true
  return useQuery({
    queryKey: plantillasDocumentoKeys.lista(opts.section ?? 'all', onlyActive),
    queryFn: () => api.listPlantillasDocumento({ section: opts.section, onlyActive }),
  })
}

/** Crea una plantilla. Invalida todas las listas de plantillas de documento. */
export function useCrearPlantillaDocumento() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PlantillaDocumentoCreateInput) => api.createPlantillaDocumento(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: plantillasDocumentoKeys.all }),
  })
}

/** Actualiza (PATCH) una plantilla. Invalida las listas. */
export function useActualizarPlantillaDocumento() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: PlantillaDocumentoUpdateInput }) =>
      api.updatePlantillaDocumento(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: plantillasDocumentoKeys.all }),
  })
}

/** Elimina una plantilla. Invalida las listas. */
export function useEliminarPlantillaDocumento() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deletePlantillaDocumento(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: plantillasDocumentoKeys.all }),
  })
}
