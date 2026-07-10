/**
 * Hooks de TanStack Query para el "Plan Integral de Longevidad y Medicina
 * Regenerativa" (constancia a nivel PACIENTE). Centralizan las query keys y la
 * invalidación de caché tras crear una constancia.
 *
 * Convención de claves: ['expediente', patientId, 'plan-integral', …].
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  crearPlanIntegral,
  getPlanIntegralBorrador,
  listPlanesIntegrales,
} from '../api/planIntegral'
import type { PlanIntegralInput } from '../types/planIntegral'

/** Claves de caché del Plan Integral (cuelgan del expediente del paciente). */
export const planIntegralKeys = {
  /** Borrador; la clave incluye el treatment_plan_id para cachear cada esquema. */
  borrador: (patientId: string, treatmentPlanId: string) =>
    ['expediente', patientId, 'plan-integral', 'borrador', treatmentPlanId] as const,
  /** Constancias de Plan Integral del paciente. */
  lista: (patientId: string) =>
    ['expediente', patientId, 'plan-integral', 'lista'] as const,
}

/**
 * Borrador del Plan Integral. `treatmentPlanId` opcional: al elegir un plan de
 * tratamiento, se vuelve a pedir el borrador con ese id para actualizar el
 * esquema (la clave incluye el id, así cada esquema se cachea aparte).
 * `enabled` para cargarlo solo cuando corresponde (modal abierto / plan elegido).
 */
export function usePlanIntegralBorrador(
  patientId: string | null,
  treatmentPlanId?: string,
  enabled = true,
) {
  return useQuery({
    queryKey: planIntegralKeys.borrador(patientId ?? '', treatmentPlanId ?? ''),
    queryFn: () => getPlanIntegralBorrador(patientId as string, treatmentPlanId),
    enabled: !!patientId && enabled,
  })
}

/**
 * Guarda la constancia de Plan Integral con el texto editado. Invalida la lista
 * de constancias del paciente. Devuelve el registro (con su id) para el PDF.
 */
export function useCrearPlanIntegral(patientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PlanIntegralInput) => crearPlanIntegral(patientId, body),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: planIntegralKeys.lista(patientId) }),
  })
}

/** Constancias de Plan Integral del paciente (paginado → usar .results). */
export function usePlanesIntegrales(patientId: string | null) {
  return useQuery({
    queryKey: planIntegralKeys.lista(patientId ?? ''),
    queryFn: () => listPlanesIntegrales(patientId as string),
    enabled: !!patientId,
  })
}
