/**
 * SedeIndicador — piezas compartidas de multi-sede para las pestañas de Finanzas
 * (Fase 3).
 *
 * Regla de negocio que refleja esta UI:
 *  - CAJA de la sede (dashboard, reportes, cierre diario, retención, listado
 *    general de cobros y pagos) → PRIVADA de cada sucursal. Se filtra por el
 *    header `X-Sucursal-Id`; sin sede activa el backend consolida las sedes
 *    permitidas del usuario ("Todas las sucursales").
 *  - ESTADO DE CUENTA del paciente → COMPARTIDO entre sedes: trae todos sus
 *    movimientos, de cualquier sucursal.
 *
 * El backend es la autoridad: si el usuario pide una sede que no tiene permitida
 * responde 403, y aquí solo lo traducimos a un mensaje claro.
 */

import { Building2, Layers } from 'lucide-react'

import { useSucursalActiva } from '../../auth/SucursalContext'
import { esSinPermiso, errorMsg } from '../../lib/apiErrors'
import type { SucursalRef } from '../../types/sucursal'

/**
 * Etiqueta discreta con la sede que se está viendo: "Sede: {nombre}" o
 * "Todas las sucursales". No se pinta si el usuario solo tiene una sede (o
 * ninguna): en ese caso no hay ambigüedad que resolver.
 */
export default function SedeIndicador({ className = '' }: { className?: string }) {
  const { sucursales, activeSucursal, esTodas } = useSucursalActiva()

  if (sucursales.length <= 1) return null

  const Icono = esTodas ? Layers : Building2
  const texto = esTodas ? 'Todas las sucursales' : `Sede: ${activeSucursal?.name ?? '—'}`

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium ${className}`}
      style={{ background: 'rgba(201,162,39,0.10)', color: '#B8860B' }}
      title={
        esTodas
          ? 'Estás viendo el consolidado de todas tus sucursales'
          : 'Estás viendo solo los movimientos de esta sede'
      }
    >
      <Icono className="w-3 h-3" />
      {texto}
    </span>
  )
}

/** Nombre de la sede de un movimiento, o '—' si no la tiene (histórico). */
export function nombreSede(sucursal: SucursalRef | null | undefined): string {
  return sucursal?.name ?? '—'
}

/**
 * Mensaje de error de una pantalla de finanzas por sede. Distingue el 403 del
 * backend (sede no permitida) del resto de fallos. El backend es la autoridad:
 * la UI solo lo explica, no lo decide.
 */
export function mensajeErrorSede(err: unknown, fallback: string): string {
  if (esSinPermiso(err)) {
    return 'No tienes permiso para ver la información de esta sucursal. Cambia de sede en el selector de arriba.'
  }
  return `${fallback} ${errorMsg(err)}`.trim()
}
