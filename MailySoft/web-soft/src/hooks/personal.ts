/** Hooks de TanStack Query para el panel de Personal (doctores y consultorios). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createConsultorio,
  createDoctor,
  createDoctorSchedule,
  deactivateConsultorio,
  deactivateDoctor,
  deactivateDoctorSchedule,
  listConsultorios,
  listDoctors,
  listDoctorSchedules,
  updateConsultorio,
  updateDoctor,
} from '../api/personal'
import { useSucursalActiva } from '../auth/SucursalContext'
import type {
  ConsultorioCreateInput,
  ConsultorioUpdateInput,
  DoctorCreateInput,
  DoctorScheduleCreateInput,
  DoctorUpdateInput,
} from '../types/personal'

/** Raíz de caché de personal. Mutaciones invalidan esto → agenda y panel refrescan. */
const personalRoot = ['personal'] as const

// ── Doctores ───────────────────────────────────────────────────────────────

/** Lista de doctores para el panel (incluye inactivos). */
export function useDoctorsManage() {
  return useQuery({
    queryKey: ['personal', 'doctores', 'manage'],
    queryFn: () => listDoctors(false),
  })
}

export function useCreateDoctor() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: DoctorCreateInput) => createDoctor(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: personalRoot }),
  })
}

export function useUpdateDoctor() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: DoctorUpdateInput }) => updateDoctor(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: personalRoot }),
  })
}

export function useDeactivateDoctor() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deactivateDoctor(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: personalRoot }),
  })
}

// ── Consultorios ─────────────────────────────────────────────────────────────

/** Lista de consultorios para el panel (incluye inactivos). */
export function useConsultoriosManage() {
  return useQuery({
    queryKey: ['personal', 'consultorios', 'manage'],
    queryFn: () => listConsultorios(false),
  })
}

export function useCreateConsultorio() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: ConsultorioCreateInput) => createConsultorio(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: personalRoot }),
  })
}

export function useUpdateConsultorio() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ConsultorioUpdateInput }) => updateConsultorio(id, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: personalRoot }),
  })
}

export function useDeactivateConsultorio() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deactivateConsultorio(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: personalRoot }),
  })
}

// ── Horarios laborales del médico (por sede — multi-sede F2) ─────────────────

/**
 * Horarios de un médico. El backend filtra por la sede activa (header
 * X-Sucursal-Id), así que la sede va en la queryKey: al cambiar de sucursal la
 * lista se refetchea y NUNCA se sirve la caché de otra sede.
 */
export function useDoctorSchedules(doctorId: string | null) {
  const { activeSucursalId } = useSucursalActiva()
  return useQuery({
    queryKey: ['personal', 'horarios', doctorId, activeSucursalId],
    queryFn: () => listDoctorSchedules(doctorId as string),
    enabled: !!doctorId,
  })
}

/** Crea un bloque de horario (con su sede) para un médico. */
export function useCreateDoctorSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ doctorId, input }: { doctorId: string; input: DoctorScheduleCreateInput }) =>
      createDoctorSchedule(doctorId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: personalRoot }),
  })
}

/** Desactiva (soft) un bloque de horario. */
export function useDeactivateDoctorSchedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (scheduleId: string) => deactivateDoctorSchedule(scheduleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: personalRoot }),
  })
}
