/** Hooks de TanStack Query para Agenda (citas) y los catálogos de Personal. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changeAppointmentStatus, createAppointment, listAppointments } from '../api/agenda'
import { listConsultorios, listDoctors } from '../api/personal'
import { dayRangeUTC } from '../lib/fecha'
import type { AppointmentStatus, CreateAppointmentInput } from '../types/agenda'

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

/** Catálogo de doctores (cambia poco → staleTime alto). */
export function useDoctors() {
  return useQuery({
    queryKey: ['personal', 'doctores'],
    queryFn: listDoctors,
    staleTime: 5 * 60_000,
  })
}

/** Catálogo de consultorios (cambia poco → staleTime alto). */
export function useConsultorios() {
  return useQuery({
    queryKey: ['personal', 'consultorios'],
    queryFn: listConsultorios,
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

/** Cambio de estado de una cita. Devuelve la cita actualizada e invalida la agenda. */
export function useChangeAppointmentStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status, reason }: { id: string; status: AppointmentStatus; reason?: string }) =>
      changeAppointmentStatus(id, status, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: agendaKeys.all }),
  })
}
