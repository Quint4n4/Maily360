/** Hooks de TanStack Query para la gestión de miembros de la clínica. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createMember, listMembers, updateMember, uploadMemberAvatar } from '../api/miembros'
import type { MemberCreateInput, MemberUpdateInput } from '../types/personal'

const miembrosKey = ['miembros'] as const

/** Lista de miembros. Solo se debe usar con rol Dueño/Admin (el backend exige eso). */
export function useMembers(enabled = true) {
  return useQuery({
    queryKey: miembrosKey,
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
