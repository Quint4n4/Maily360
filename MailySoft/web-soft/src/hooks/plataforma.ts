/** Hooks de TanStack Query para el panel interno de plataforma (equipo Maily). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createClinica,
  createPlatformPlan,
  createPlatformStaff,
  getClinicaDetail,
  getPlatformMetrics,
  getPlatformSistema,
  getSuscripcionesResumen,
  listPlatformAuditoria,
  listPlatformClinicas,
  listPlatformPlanes,
  listPlatformStaff,
  listPlatformSuscripciones,
  resetStaffPassword,
  setClinicaEstado,
  setClinicaSuscripcion,
  updatePlatformPlan,
  updatePlatformStaff,
  type ListClinicasParams,
} from '../api/plataforma'
import type {
  AuditoriaFiltros,
  ClinicaCreateInput,
  PlanFormInput,
  StaffFormInput,
  StaffUpdateInput,
  SuscripcionAsignarInput,
  SuscripcionesFiltros,
} from '../types/plataforma'

export const platKeys = {
  all: ['plataforma'] as const,
  metrics: () => ['plataforma', 'metricas'] as const,
  clinicas: (p: ListClinicasParams) => ['plataforma', 'clinicas', p.search ?? '', p.status ?? ''] as const,
  clinicaDetail: (id: string) => ['plataforma', 'clinica', id] as const,
  /** Prefijo de TODAS las listas de staff (para invalidar sin importar la búsqueda). */
  staffAll: ['plataforma', 'usuarios'] as const,
  staff: (search: string) => ['plataforma', 'usuarios', search] as const,
  auditoria: (p: AuditoriaFiltros) => ['plataforma', 'auditoria', p] as const,
  sistema: () => ['plataforma', 'sistema'] as const,
  planes: () => ['plataforma', 'planes'] as const,
  suscripciones: (p: SuscripcionesFiltros) => ['plataforma', 'suscripciones', 'lista', p] as const,
  suscripcionesResumen: () => ['plataforma', 'suscripciones', 'resumen'] as const,
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

/** Alta de un miembro del equipo Maily (solo super_admin). Invalida la lista
 *  de staff y las métricas (total_platform_staff del dashboard). */
export function useCreateStaff() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: StaffFormInput) => createPlatformStaff(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: platKeys.staffAll })
      qc.invalidateQueries({ queryKey: platKeys.metrics() })
    },
  })
}

/** Editar nombre/rol/activo de un miembro (solo super_admin). Invalida la lista. */
export function useUpdateStaff() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, input }: { userId: string; input: StaffUpdateInput }) =>
      updatePlatformStaff(userId, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: platKeys.staffAll })
      qc.invalidateQueries({ queryKey: platKeys.metrics() })
    },
  })
}

/** Restablecer la contraseña de un miembro (solo super_admin). La contraseña
 *  temporal viene UNA sola vez en la respuesta. */
export function useResetStaffPassword() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => resetStaffPassword(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: platKeys.staffAll }),
  })
}

/** Salud del sistema (super_admin / engineering). Auto-refresca cada 30 s,
 *  mismo patrón de polling que la campana de notificaciones. */
export function usePlatformSistema() {
  return useQuery({
    queryKey: platKeys.sistema(),
    queryFn: getPlatformSistema,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })
}

/** Catálogo de planes comerciales. `enabled` la apaga si el rol no tiene acceso. */
export function usePlatformPlanes(enabled = true) {
  return useQuery({ queryKey: platKeys.planes(), queryFn: listPlatformPlanes, enabled })
}

/** Clínicas con su suscripción (búsqueda + filtro de plan/alerta + paginación). */
export function usePlatformSuscripciones(params: SuscripcionesFiltros = {}, enabled = true) {
  return useQuery({
    queryKey: platKeys.suscripciones(params),
    queryFn: () => listPlatformSuscripciones(params),
    enabled,
  })
}

/** KPIs de suscripciones (conteos por plan, alertas de vencimiento, MRR).
 *  `enabled` permite apagarla para roles sin acceso al módulo (engineering → 403). */
export function useSuscripcionesResumen(enabled = true) {
  return useQuery({
    queryKey: platKeys.suscripcionesResumen(),
    queryFn: getSuscripcionesResumen,
    enabled,
  })
}

/** Crear un plan comercial (solo super_admin). Invalida planes, suscripciones y resumen. */
export function useCreatePlan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: PlanFormInput) => createPlatformPlan(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: platKeys.planes() })
      qc.invalidateQueries({ queryKey: ['plataforma', 'suscripciones'] }) // lista + resumen
    },
  })
}

/** Editar un plan comercial (solo super_admin). Invalida planes, suscripciones y resumen
 *  (el nombre/precio del plan se refleja en la tabla y en el MRR). */
export function useUpdatePlan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ planId, input }: { planId: string; input: Partial<PlanFormInput> }) =>
      updatePlatformPlan(planId, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: platKeys.planes() })
      qc.invalidateQueries({ queryKey: ['plataforma', 'suscripciones'] }) // lista + resumen
    },
  })
}

/** Asignar / cambiar el plan de una clínica. Invalida suscripciones, resumen y clínicas. */
export function useSetClinicaSuscripcion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ tenantId, input }: { tenantId: string; input: SuscripcionAsignarInput }) =>
      setClinicaSuscripcion(tenantId, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['plataforma', 'suscripciones'] }) // lista + resumen
      qc.invalidateQueries({ queryKey: ['plataforma', 'clinicas'] })
      qc.invalidateQueries({ queryKey: platKeys.metrics() })
    },
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
