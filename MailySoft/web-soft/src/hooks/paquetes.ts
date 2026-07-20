/**
 * Hooks de TanStack Query para el catálogo de paquetes de tratamiento (Fase 3).
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 *
 * Convención de claves:
 *   ['paquetes', 'lista', onlyActive] → lista de paquetes
 *   ['paquetes', 'detalle', id]       → detalle de un paquete
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '../api/paquetes'
import { useSucursalActiva } from '../auth/SucursalContext'
import type { PackageCreateInput, PackageUpdateInput } from '../types/paquetes'

export const paquetesKeys = {
  all: ['paquetes'] as const,
  lista: (onlyActive: boolean, sucursalId: string | null) =>
    ['paquetes', 'lista', onlyActive, sucursalId] as const,
  detalle: (id: string) => ['paquetes', 'detalle', id] as const,
}

/**
 * Lista de paquetes (paginada → usar .results). Por defecto solo activos (pickers);
 * pasar `{ onlyActive: false }` para la página de gestión (incluye inactivos).
 *
 * Multi-sede: el backend acota la lista por la sede activa (header `X-Sucursal-Id`,
 * que ya manda src/lib/http.ts), así que la sede entra en la query key: al cambiar
 * de sucursal se refetchea y en cada sede solo aparecen sus paquetes. Owner sin
 * sede activa ("Todas") ve todo. Invalidar `paquetesKeys.all` (prefijo) sigue
 * invalidando todas las variantes por sede.
 */
export function usePaquetes(opts: { onlyActive?: boolean } = {}) {
  const onlyActive = opts.onlyActive ?? true
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: paquetesKeys.lista(onlyActive, activeSucursalId),
    queryFn: () => api.listPaquetes({ onlyActive }),
  })
}

/** Detalle de un paquete. `enabled` para cargarlo solo cuando se necesita. */
export function usePaquete(id: string | null, enabled = true) {
  return useQuery({
    queryKey: paquetesKeys.detalle(id ?? ''),
    queryFn: () => api.getPaquete(id as string),
    enabled: !!id && enabled,
  })
}

/** Crea un paquete. Invalida las listas de paquetes. */
export function useCrearPaquete() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PackageCreateInput) => api.createPaquete(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: paquetesKeys.all }),
  })
}

/** Guarda (PATCH) un paquete. Actualiza la caché del detalle e invalida las listas. */
export function useGuardarPaquete(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PackageUpdateInput) => api.updatePaquete(id, input),
    onSuccess: (data) => {
      qc.setQueryData(paquetesKeys.detalle(id), data)
      qc.invalidateQueries({ queryKey: paquetesKeys.all })
    },
  })
}

/** Elimina un paquete. Invalida las listas de paquetes. */
export function useEliminarPaquete() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deletePaquete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: paquetesKeys.all }),
  })
}
