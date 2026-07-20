/** Hooks de TanStack Query para la gestión de miembros de la clínica. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSucursalActiva } from '../auth/SucursalContext'
import { createMember, listMembers, updateMember, uploadMemberAvatar } from '../api/miembros'
import type { MemberCreateInput, MemberUpdateInput } from '../types/personal'

/**
 * Query key raíz del listado del equipo (la reusa la asignación de sedes, F4,
 * y las mutaciones para invalidar por prefijo).
 */
export const miembrosKey = ['miembros'] as const

/**
 * Lista de miembros. Solo se debe usar con rol Dueño/Admin (el backend exige eso).
 *
 * Multi-sede (clúster F): el backend acota la lista por la sede activa (header
 * X-Sucursal-Id, que ya manda src/lib/http.ts) — un admin de sucursal solo ve al
 * equipo operativo de su sede. La sede entra en la queryKey para que, al cambiar
 * de sucursal, TanStack Query refresque en vez de mostrar la lista de la sede
 * anterior (mismo patrón que agenda/finanzas). Invalidar `miembrosKey` (prefijo)
 * sigue invalidando todas las variantes por sede.
 */
export function useMembers(enabled = true) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: [...miembrosKey, activeSucursalId],
    queryFn: listMembers,
    enabled,
  })
}

export function useCreateMember() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: MemberCreateInput) => createMember(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: miembrosKey }),
  })
}

export function useUpdateMember() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: MemberUpdateInput }) => updateMember(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: miembrosKey }),
  })
}

export function useUploadMemberAvatar() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) => uploadMemberAvatar(id, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: miembrosKey }),
  })
}
