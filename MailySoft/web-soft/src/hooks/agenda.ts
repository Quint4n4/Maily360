/** Hooks de TanStack Query para Agenda (citas) y los catálogos de Personal. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addAppointmentNote,
  addBlockNote,
  changeAppointmentStatus,
  createAgendaBlock,
  createAppointment,
  deleteAgendaNote,
  listAppointmentNotes,
  listBlockNotes,
  createAppointmentType,
  deactivateAppointmentType,
  deleteAgendaBlock,
  listAgendaBlocks,
  listAppointments,
  listAppointmentTypes,
  reactivateAppointment,
  rescheduleAppointment,
  updateAgendaBlock,
  updateAppointmentType,
} from '../api/agenda'
import { listConsultorios, listDoctors } from '../api/personal'
import { dayRangeUTC, toDayKey } from '../lib/fecha'
import type {
  AgendaBlockCreateInput,
  AgendaBlockUpdateInput,
  AppointmentStatus,
  AppointmentTypeCreateInput,
  AppointmentTypeUpdateInput,
  CreateAppointmentInput,
} from '../types/agenda'

export const agendaKeys = {
  all: ['agenda'] as const,
  day: (dayKey: string) => ['agenda', 'citas', dayKey] as const,
}

/** Citas de un día (dayKey = 'yyyy-mm-dd' local). */
export function useAppointmentsForDay(dayKey: string) {
  const { from, to } = dayRangeUTC(dayKey)
  return useQuery({
    queryKey: agendaKeys.day(dayKey),
    queryFn: () => listAppointments({ date_from: from, date_to: to }),
  })
}

/** Citas de HOY en vivo (refresca cada 60s) para el vigilante de alertas de citas. */
export function useTodayAppointmentsLive(enabled: boolean) {
  const today = toDayKey(new Date())
  const { from, to } = dayRangeUTC(today)
  return useQuery({
    queryKey: agendaKeys.day(today),
    queryFn: () => listAppointments({ date_from: from, date_to: to }),
    enabled,
    refetchInterval: enabled ? 60_000 : false,
  })
}

/** Citas de un paciente (para su expediente). Clave bajo ['agenda'] → se refresca al cambiar estados. */
export function useAppointmentsForPatient(patientId: string | null) {
  return useQuery({
    queryKey: ['agenda', 'citas', 'paciente', patientId],
    queryFn: () => listAppointments({ patient_id: patientId as string }),
    enabled: !!patientId,
  })
}

// ── Eventos de agenda (reuniones / bloqueos) ────────────────────────────────

/** Eventos (reuniones/bloqueos) de un día. Clave bajo ['agenda'] → se refresca junto con las citas. */
export function useAgendaBlocksForDay(dayKey: string) {
  const { from, to } = dayRangeUTC(dayKey)
  return useQuery({
    queryKey: ['agenda', 'eventos', dayKey],
    queryFn: () => listAgendaBlocks({ date_from: from, date_to: to }),
  })
}

export function useCreateAgendaBlock() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: AgendaBlockCreateInput) => createAgendaBlock(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}

export function useUpdateAgendaBlock() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: AgendaBlockUpdateInput }) => updateAgendaBlock(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}

export function useDeleteAgendaBlock() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteAgendaBlock(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}

// ── Notas colaborativas (hilo en cita / evento) ─────────────────────────────

type ItemKind = 'cita' | 'evento'
const itemNotesKey = (kind: ItemKind, id: string) => ['agenda', 'item-notes', kind, id] as const

export function useAgendaItemNotes(kind: ItemKind, id: string | null) {
  return useQuery({
    queryKey: ['agenda', 'item-notes', kind, id],
    queryFn: () => (kind === 'cita' ? listAppointmentNotes(id as string) : listBlockNotes(id as string)),
    enabled: !!id,
  })
}

export function useAddAgendaItemNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, id, body }: { kind: ItemKind; id: string; body: string }) =>
      kind === 'cita' ? addAppointmentNote(id, body) : addBlockNote(id, body),
    onSuccess: (_d, vars) => qc.invalidateQueries({ queryKey: itemNotesKey(vars.kind, vars.id) }),
  })
}

export function useDeleteAgendaItemNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ noteId }: { noteId: string }) => deleteAgendaNote(noteId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agenda', 'item-notes'] }),
  })
}

/** Catálogo de doctores activos (cambia poco → staleTime alto). */
export function useDoctors() {
  return useQuery({
    queryKey: ['personal', 'doctores', 'activos'],
    queryFn: () => listDoctors(true),
    staleTime: 5 * 60_000,
  })
}

/** Catálogo de consultorios activos (cambia poco → staleTime alto). */
export function useConsultorios() {
  return useQuery({
    queryKey: ['personal', 'consultorios', 'activos'],
    queryFn: () => listConsultorios(true),
    staleTime: 5 * 60_000,
  })
}

/** Alta de cita. Invalida toda la agenda al terminar. */
export function useCreateAppointment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateAppointmentInput) => createAppointment(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}

// ── Tipos de cita ────────────────────────────────────────────────────────

const tiposKey = ['agenda', 'tipos-cita'] as const

/** Tipos de cita activos (para el selector al agendar). */
export function useAppointmentTypes() {
  return useQuery({
    queryKey: [...tiposKey, 'activos'],
    queryFn: () => listAppointmentTypes(true),
    staleTime: 60_000,
  })
}

/** Todos los tipos de cita (panel de administración, incluye inactivos). */
export function useAppointmentTypesManage() {
  return useQuery({
    queryKey: [...tiposKey, 'manage'],
    queryFn: () => listAppointmentTypes(false),
  })
}

function useTipoMutation<TArgs>(fn: (a: TArgs) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    // Invalida los tipos Y la agenda (las citas embeben el color del tipo).
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: tiposKey })
      qc.invalidateQueries({ queryKey: agendaKeys.all })
    },
  })
}

export function useCreateAppointmentType() {
  return useTipoMutation((input: AppointmentTypeCreateInput) => createAppointmentType(input))
}
export function useUpdateAppointmentType() {
  return useTipoMutation(({ id, input }: { id: string; input: AppointmentTypeUpdateInput }) => updateAppointmentType(id, input))
}
export function useDeactivateAppointmentType() {
  return useTipoMutation((id: string) => deactivateAppointmentType(id))
}

/** Reagendar una cita (nuevo día/horario; reactiva si estaba cancelada). */
export function useRescheduleAppointment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: { starts_at: string; ends_at?: string | null } }) =>
      rescheduleAppointment(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}

/** Reactivar una cita cancelada (mismo horario). */
export function useReactivateAppointment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => reactivateAppointment(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}

/** Cambio de estado de una cita. Devuelve la cita actualizada e invalida la agenda. */
export function useChangeAppointmentStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status, reason }: { id: string; status: AppointmentStatus; reason?: string }) =>
      changeAppointmentStatus(id, status, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}
