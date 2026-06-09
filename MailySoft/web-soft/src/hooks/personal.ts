/** Hooks de TanStack Query para el panel de Personal (doctores y consultorios). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createConsultorio,
  createDoctor,
  deactivateConsultorio,
  deactivateDoctor,
  listConsultorios,
  listDoctors,
  updateConsultorio,
  updateDoctor,
} from '../api/personal'
import type {
  ConsultorioCreateInput,
  ConsultorioUpdateInput,
  DoctorCreateInput,
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
