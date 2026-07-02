/** Hooks de TanStack Query para el panel interno de plataforma (equipo Maily). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createClinica,
  getClinicaDetail,
  getPlatformMetrics,
  listPlatformAuditoria,
  listPlatformClinicas,
  listPlatformStaff,
  setClinicaEstado,
  type ListClinicasParams,
} from '../api/plataforma'
import type { AuditoriaFiltros, ClinicaCreateInput } from '../types/plataforma'

export const platKeys = {
  all: ['plataforma'] as const,
  metrics: () => ['plataforma', 'metricas'] as const,
  clinicas: (p: ListClinicasParams) => ['plataforma', 'clinicas', p.search ?? '', p.status ?? ''] as const,
  clinicaDetail: (id: string) => ['plataforma', 'clinica', id] as const,
  staff: (search: string) => ['plataforma', 'usuarios', search] as const,
  auditoria: (p: AuditoriaFiltros) => ['plataforma', 'auditoria', p] as const,
}

/** Métricas del dashboard de plataforma. */
export function usePlatformMetrics() {
  return useQuery({ queryKey: platKeys.metrics(), queryFn: getPlatformMetrics })
}

/** Lista de clínicas (cross-tenant) con búsqueda + filtro de estado. */
export function usePlatformClinicas(params: ListClinicasParams = {}) {
  return useQuery({ queryKey: platKeys.clinicas(params), queryFn: () => listPlatformClinicas(params) })
}

/** Lista del equipo interno de Maily. */
export function usePlatformStaff(search = '') {
  return useQuery({ queryKey: platKeys.staff(search), queryFn: () => listPlatformStaff({ search }) })
}

/** Log de auditoría cross-tenant. `enabled` permite apagarla si el rol no tiene acceso. */
export function usePlatformAuditoria(params: AuditoriaFiltros = {}, enabled = true) {
  return useQuery({
    queryKey: platKeys.auditoria(params),
    queryFn: () => listPlatformAuditoria(params),
    enabled,
  })
}

/** Suspender / reactivar una clínica. Invalida métricas y lista al terminar. */
export function useSetClinicaEstado() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'active' | 'suspended' }) => setClinicaEstado(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: platKeys.all }),
  })
}

/** Alta de clínica nueva. Invalida métricas y lista al terminar. */
export function useCreateClinica() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: ClinicaCreateInput) => createClinica(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: platKeys.all }),
  })
}

/** Ficha de detalle de una clínica. */
export function useClinicaDetail(id: string | null) {
  return useQuery({
    queryKey: platKeys.clinicaDetail(id ?? ''),
    queryFn: () => getClinicaDetail(id as string),
    enabled: !!id,
  })
}
