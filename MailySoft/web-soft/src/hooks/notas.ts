/** Hooks de TanStack Query para Notas y Tareas. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSucursalActiva } from '../auth/SucursalContext'
import { createNote, deleteNote, listNotes, listReminders, toggleNoteDone, updateNote } from '../api/notas'
import type { NoteCreateInput, NoteUpdateInput } from '../types/nota'

const notasKey = ['notas'] as const

/**
 * Notas visibles para mí (con filtros opcionales).
 *
 * Multi-sede: el backend acota los AVISOS de la clínica por la sede activa
 * (header X-Sucursal-Id, que ya manda src/lib/http.ts). La sede entra en la
 * queryKey para que, al cambiar de sucursal, TanStack Query refresque la lista
 * en vez de mostrar los avisos de la sede anterior (las notas personales no
 * cambian entre sedes). Invalidar `notasKey` (prefijo) invalida todas.
 */
export function useNotes(filters: { is_task?: boolean; done?: boolean } = {}) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: [...notasKey, 'list', filters, activeSucursalId],
    queryFn: () => listNotes(filters),
  })
}

/** Mis recordatorios en un rango de fechas (para el widget de la agenda y la luz).
 *  `enabled` permite NO consultar hasta tener sesión (evita pegarle a la API
 *  durante el bootstrap de auth y provocar un refresh en paralelo). */
export function useReminders(params: { date_from?: string; date_to?: string }, enabled = true) {
  return useQuery({
    queryKey: [...notasKey, 'recordatorios', params],
    queryFn: () => listReminders(params),
    enabled,
  })
}

function useNotaMutation<T>(fn: (a: T) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: notasKey }),
  })
}

export function useCreateNote() {
  return useNotaMutation((input: NoteCreateInput) => createNote(input))
}
export function useUpdateNote() {
  return useNotaMutation(({ id, input }: { id: string; input: NoteUpdateInput }) => updateNote(id, input))
}
export function useDeleteNote() {
  return useNotaMutation((id: string) => deleteNote(id))
}
export function useToggleNoteDone() {
  return useNotaMutation((id: string) => toggleNoteDone(id))
}
