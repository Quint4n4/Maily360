/**
 * Hooks de TanStack Query para las sucursales (sedes) de la clínica (Fase 1).
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 *
 * Convención de claves:
 *   ['sucursales', 'lista'] → lista de sucursales permitidas del usuario
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '../api/sucursales'
import { useAuth } from '../auth/AuthContext'
import { miembrosKey } from './miembros'
import type {
  MembershipSucursalesInput,
  SucursalCreateInput,
  SucursalUpdateInput,
} from '../types/sucursal'

export const sucursalesKeys = {
  all: ['sucursales'] as const,
  lista: () => ['sucursales', 'lista'] as const,
  /** Sedes asignadas a una membresía (Fase 4). */
  deMiembro: (membershipId: string) => ['sucursales', 'miembro', membershipId] as const,
}

/** Lista de sucursales permitidas del usuario (paginada → usar .results). */
export function useSucursales() {
  return useQuery({
    queryKey: sucursalesKeys.lista(),
    queryFn: () => api.listSucursales(),
  })
}

/** Crea una sucursal. Invalida las listas de sucursales. */
export function useCrearSucursal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: SucursalCreateInput) => api.createSucursal(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: sucursalesKeys.all }),
  })
}

/** Actualiza (PATCH) una sucursal. Invalida las listas de sucursales. */
export function useActualizarSucursal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: SucursalUpdateInput }) =>
      api.updateSucursal(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: sucursalesKeys.all }),
  })
}

/** Elimina una sucursal. Invalida las listas de sucursales. */
export function useEliminarSucursal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteSucursal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: sucursalesKeys.all }),
  })
}

// ── Asignación de sedes por miembro (Fase 4) ─────────────────────────────────

/**
 * Sedes asignadas a un miembro. Solo owner/admin pueden consultarlo (el backend
 * responde 403 al resto), por eso `enabled` deja no dispararlo desde otros roles.
 */
export function useMembershipSucursales(membershipId: string | null, enabled = true) {
  return useQuery({
    queryKey: sucursalesKeys.deMiembro(membershipId ?? ''),
    queryFn: () => api.getMembershipSucursales(membershipId as string),
    enabled: enabled && !!membershipId,
  })
}

/**
 * Guarda (PUT, reemplaza) las sedes asignadas a un miembro.
 *
 * Coherencia de caché: cambia lo que ese usuario puede ver, así que se invalida
 * el listado del equipo y las sucursales. Si el miembro editado es UNO MISMO,
 * además se recarga /me (sus sedes permitidas cambiaron) y se invalidan agenda,
 * personal y finanzas, que van acotadas por sede.
 */
export function useGuardarMembershipSucursales() {
  const qc = useQueryClient()
  const { reloadMe } = useAuth()
  return useMutation({
    mutationFn: ({
      membershipId,
      input,
    }: {
      membershipId: string
      input: MembershipSucursalesInput
      /** true si la membresía editada es la del usuario actual. */
      esYoMismo?: boolean
    }) => api.setMembershipSucursales(membershipId, input),
    onSuccess: async (_data, vars) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: miembrosKey }),
        qc.invalidateQueries({ queryKey: sucursalesKeys.all }),
      ])
      if (!vars.esYoMismo) return
      await reloadMe().catch(() => {})
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['agenda'] }),
        qc.invalidateQueries({ queryKey: ['personal'] }),
        qc.invalidateQueries({ queryKey: ['finanzas'] }),
      ])
    },
  })
}
