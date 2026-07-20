/**
 * Hooks de TanStack Query para Agenda (citas) y los catálogos de Personal.
 *
 * MULTI-SEDE (Fase 2): el backend filtra citas, bloqueos y disponibilidad por la
 * sucursal activa (header `X-Sucursal-Id`, que ya manda src/lib/http.ts). Por eso
 * el id de la sede activa forma parte de la QUERY KEY de todo lo que dependa de la
 * sede: así, al cambiar de sucursal, TanStack Query trata los datos como otra
 * entrada de caché (refetch) y jamás pinta el calendario de la sede anterior.
 * El backend sigue siendo la autoridad del filtrado; la key solo cuida la caché.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addAppointmentNote,
  addBlockNote,
  changeAppointmentStatus,
  createAgendaBlock,
  createAppointment,
  createAppointmentSeries,
  getAgendaDisponibilidad,
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
import { useSucursalActiva } from '../auth/SucursalContext'
import { dayRangeUTC, toDayKey } from '../lib/fecha'
import type {
  AgendaBlockCreateInput,
  AgendaBlockUpdateInput,
  AppointmentStatus,
  AppointmentTypeCreateInput,
  AppointmentTypeUpdateInput,
  CreateAppointmentInput,
  CreateAppointmentSeriesInput,
} from '../types/agenda'

export const agendaKeys = {
  all: ['agenda'] as const,
  /** Citas de un día EN UNA SEDE. La sede va en la key: al cambiarla, refetch. */
  day: (dayKey: string, sucursalId: string | null) => ['agenda', 'citas', dayKey, sucursalId] as const,
}

/** Citas de un día (dayKey = 'yyyy-mm-dd' local) en la SEDE ACTIVA. */
export function useAppointmentsForDay(dayKey: string) {
  const { activeSucursalId } = useSucursalActiva()
  const { from, to } = dayRangeUTC(dayKey)
  return useQuery({
    queryKey: agendaKeys.day(dayKey, activeSucursalId),
    queryFn: () => listAppointments({ date_from: from, date_to: to }),
  })
}

/** Citas de HOY en vivo (refresca cada 60s) para el vigilante de alertas de citas. */
export function useTodayAppointmentsLive(enabled: boolean) {
  const { activeSucursalId } = useSucursalActiva()
  const today = toDayKey(new Date())
  const { from, to } = dayRangeUTC(today)
  return useQuery({
    queryKey: agendaKeys.day(today, activeSucursalId),
    queryFn: () => listAppointments({ date_from: from, date_to: to }),
    enabled,
    refetchInterval: enabled ? 60_000 : false,
  })
}

/** Citas de un paciente (para su expediente). Clave bajo ['agenda'] → se refresca al cambiar estados. */
export function useAppointmentsForPatient(patientId: string | null) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: ['agenda', 'citas', 'paciente', patientId, activeSucursalId],
    queryFn: () => listAppointments({ patient_id: patientId as string }),
    enabled: !!patientId,
  })
}

// ── Eventos de agenda (reuniones / bloqueos) ────────────────────────────────

/**
 * Eventos (reuniones/bloqueos) de un día EN LA SEDE ACTIVA. Clave bajo ['agenda']
 * → se refresca junto con las citas; la sede va en la key → refetch al cambiarla.
 */
export function useAgendaBlocksForDay(dayKey: string) {
  const { activeSucursalId } = useSucursalActiva()
  const { from, to } = dayRangeUTC(dayKey)
  return useQuery({
    queryKey: ['agenda', 'eventos', dayKey, activeSucursalId],
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

/**
 * Catálogo de doctores activos DE LA SEDE ACTIVA (el backend filtra por el header).
 * La sede va en la key: con staleTime alto, sin ella se serviría la caché de la
 * sede anterior y el modal ofrecería médicos de otra sucursal.
 */
export function useDoctors() {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: ['personal', 'doctores', 'activos', activeSucursalId],
    queryFn: () => listDoctors(true),
    staleTime: 5 * 60_000,
  })
}

/** Catálogo de consultorios activos DE LA SEDE ACTIVA (mismo criterio que los doctores). */
export function useConsultorios() {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: ['personal', 'consultorios', 'activos', activeSucursalId],
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

export function useCreateAppointmentSeries() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateAppointmentSeriesInput) => createAppointmentSeries(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}

/**
 * Intervalos ocupados de un médico/consultorio en un rango (para pintar disponibilidad).
 *
 * OJO (regla de negocio F2): el MÉDICO ES GLOBAL entre sedes — si está ocupado en
 * otra sucursal, el backend lo devuelve como ocupado también aquí. No asumas que
 * otra sede está libre. La sede va en la key solo para no mezclar cachés.
 */
export function useAgendaDisponibilidad(params: {
  doctorId: string
  consultorioId: string | null
  from: string // ISO
  to: string // ISO
  enabled: boolean
}) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: ['agenda', 'disponibilidad', params.doctorId, params.consultorioId, params.from, params.to, activeSucursalId],
    queryFn: () => getAgendaDisponibilidad({
      doctor_id: params.doctorId,
      consultorio_id: params.consultorioId,
      date_from: params.from,
      date_to: params.to,
    }),
    enabled: params.enabled && !!params.doctorId && !!params.from && !!params.to,
    staleTime: 30_000,
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
