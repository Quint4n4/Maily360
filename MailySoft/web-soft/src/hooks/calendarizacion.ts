/**
 * Hooks de TanStack Query para la Calendarización de tratamientos (Fase 1).
 * Centralizan las query keys y la invalidación de caché tras mutaciones.
 *
 * Convención de claves:
 *   ['calendarizaciones', patientId]  → lista del paciente
 *   ['calendarizacion', planId]       → detalle de un plan
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import * as api from '../api/calendarizacion'
import { agendaKeys } from './agenda'
import type {
  AgendarSesionInput,
  CalendarizacionCreateInput,
  CalendarizacionUpdateInput,
} from '../types/calendarizacion'

export const calendarizacionKeys = {
  lista: (patientId: string) => ['calendarizaciones', patientId] as const,
  detalle: (planId: string) => ['calendarizacion', planId] as const,
}

/** Lista de calendarizaciones del paciente (paginada → usar .results). */
export function useCalendarizaciones(patientId: string | null) {
  return useQuery({
    queryKey: calendarizacionKeys.lista(patientId ?? ''),
    queryFn: () => api.listCalendarizaciones(patientId as string),
    enabled: !!patientId,
  })
}

/** Detalle de un plan. `enabled` para cargarlo solo cuando hay un plan elegido. */
export function useCalendarizacion(planId: string | null, enabled = true) {
  return useQuery({
    queryKey: calendarizacionKeys.detalle(planId ?? ''),
    queryFn: () => api.getCalendarizacion(planId as string),
    enabled: !!planId && enabled,
  })
}

/** Crea un plan (vacío o con contenido). Invalida la lista del paciente. */
export function useCrearCalendarizacion(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CalendarizacionCreateInput) => api.crearCalendarizacion(patientId, body),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: calendarizacionKeys.lista(patientId) }),
  })
}

/**
 * Guarda (PUT) un plan con el estado completo. Actualiza la caché del detalle con
 * la respuesta e invalida la lista (cambian total / conteos / estado).
 */
export function useGuardarCalendarizacion(planId: string, patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CalendarizacionUpdateInput) => api.guardarCalendarizacion(planId, body),
    onSuccess: (data) => {
      qc.setQueryData(calendarizacionKeys.detalle(planId), data)
      qc.invalidateQueries({ queryKey: calendarizacionKeys.lista(patientId) })
    },
  })
}

/**
 * Agenda (o reprograma) la cita real de una sesión. Devuelve la sesión actualizada
 * (con `appointment`). Invalida el detalle del plan y TODA la agenda (aparece la
 * cita nueva en el calendario). El componente usa la sesión devuelta para refrescar
 * su estado local sin recargar todo el editor.
 */
export function useAgendarSesion(planId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, body }: { sessionId: string; body: AgendarSesionInput }) =>
      api.agendarSesion(sessionId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarizacionKeys.detalle(planId) })
      qc.invalidateQueries({ queryKey: agendaKeys.all })
    },
  })
}

/** Quita la cita de una sesión de la agenda. Invalida el detalle del plan y la agenda. */
export function useQuitarAgendaSesion(planId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => api.quitarAgendaSesion(sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarizacionKeys.detalle(planId) })
      qc.invalidateQueries({ queryKey: agendaKeys.all })
    },
  })
}

/** Elimina un plan. Invalida la lista del paciente. */
export function useEliminarCalendarizacion(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (planId: string) => api.eliminarCalendarizacion(planId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: calendarizacionKeys.lista(patientId) }),
  })
}

/**
 * Genera una cotización (borrador) desde el plan (Fase 2). Devuelve {quote_id,
 * status, total}. Invalida el detalle del plan (ahora trae `quote_id`) y las
 * cotizaciones de finanzas (aparece la nueva cotización en su lista).
 */
export function useGenerarCotizacion(planId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.generarCotizacion(planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarizacionKeys.detalle(planId) })
      qc.invalidateQueries({ queryKey: ['finanzas', 'quotes'] })
    },
  })
}

/**
 * Crea una nueva calendarización desde un paquete (Fase 3c). Devuelve el detalle
 * de la calendarización creada. Invalida la lista del paciente para que aparezca.
 */
export function useCrearDesdePaquete(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (packageId: string) =>
      api.crearCalendarizacionDesdePaquete(patientId, { package_id: packageId }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: calendarizacionKeys.lista(patientId) }),
  })
}
