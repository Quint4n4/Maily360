/**
 * EstadoCuentaVisita — bloque "Estado de cuenta de la visita" dentro de un
 * capítulo del libro clínico (Fase 1 del plan finanzas-pacientes-unificacion).
 *
 * Lista los cargos de ESA visita + el saldo de la visita. Si no hay cargos,
 * muestra un texto discreto. Solo se renderiza si el rol puede ver costos
 * (puedeVerEstadoCuenta); el llamador (CapituloPage) ya hace ese gating.
 *
 * Filtro por visita:
 *   BookCapitulo NO expone `appointment_id` (ver src/types/expediente.ts), por lo
 *   que filtramos por la FECHA del capítulo: fetchStatement(patientId,
 *   {date_from: fecha, date_to: fecha}) vía useStatement. El estado de cuenta de
 *   ese día trae los movimientos (cargos/pagos) de la visita con su saldo corrido.
 */

import { Loader2, Receipt } from 'lucide-react'

import { useStatement } from '../../hooks/finanzas'
import { formatMoney, toIsoDate } from '../../lib/format'

const ORO_OSCURO = '#854F0B'

interface Props {
  patientId: string
  /** Fecha del capítulo (ISO datetime); se usa como date_from y date_to. */
  fechaCapitulo: string
}

export default function EstadoCuentaVisita({ patientId, fechaCapitulo }: Props) {
  const dia = toIsoDate(fechaCapitulo)
  const statement = useStatement(patientId, { date_from: dia, date_to: dia })

  // Errores (incl. 403) se silencian aquí: el bloque es secundario dentro del
  // capítulo y no debe romper la lectura del libro. El gating ya lo hizo el padre.
  if (statement.isError) return null

  const cargos = (statement.data?.movements ?? []).filter(m => m.type === 'charge')
  const saldoVisita = statement.data?.balance ?? 0

  return (
    <div className="mt-5 pt-4 border-t border-amber-900/10">
      <p
        className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700/70 mb-2"
      >
        <Receipt className="w-3.5 h-3.5" /> Estado de cuenta de la visita
      </p>

      {statement.isLoading ? (
        <p className="inline-flex items-center gap-2 text-xs text-gray-400">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Cargando cargos…
        </p>
      ) : cargos.length === 0 ? (
        <p className="text-xs text-gray-400 italic">Sin cargos en esta visita.</p>
      ) : (
        <div className="space-y-1.5">
          {cargos.map(m => (
            <div
              key={m.id}
              className="flex items-center justify-between gap-3 rounded-lg px-3 py-2"
              style={{ background: 'rgba(201,162,39,0.07)' }}
            >
              <span className="text-sm text-gray-700 min-w-0 truncate">{m.description}</span>
              <span className="text-sm font-semibold shrink-0" style={{ color: ORO_OSCURO }}>
                {formatMoney(m.charge)}
              </span>
            </div>
          ))}
          <div className="flex items-center justify-between gap-3 px-3 pt-1">
            <span className="text-[11px] uppercase tracking-wide text-gray-400">Saldo a la fecha</span>
            <span className="text-sm font-bold" style={{ color: ORO_OSCURO }}>
              {formatMoney(saldoVisita)}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
