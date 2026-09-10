/**
 * Los tres números del Resumen.
 *
 * Eran cinco y ahora son tres. Qué salió y por qué:
 *
 *  · «Ticket promedio» — se eliminó. Daba DOS valores distintos con el mismo
 *    nombre según la pestaña ($774 en el panel viejo contra $941 aquí), porque
 *    cada uno lo calculaba distinto: cobranza÷pagos frente a producción÷cargos.
 *    Además no respondía ninguna pregunta que se tome a diario.
 *
 *  · «Cuentas por cobrar» — se movió a su propia pantalla (Cobranza), donde va
 *    acompañado de su antigüedad y de quién debe. Como número suelto no era
 *    accionable: saber que hay $23,830 no dice a quién hay que llamar.
 *
 * Los tres que quedan llevan SIEMPRE su comparación contra el periodo anterior.
 * Un número sin contexto no dice si está bien o mal: $36,390 de cobranza es una
 * buena o mala noticia según lo del mes pasado, y eso es lo que se lee aquí.
 *
 * Nada de colores decorativos: los tres iconos van en el mismo tono neutro. El
 * color solo aparece en el Δ, y ahí SÍ significa algo (subió / bajó).
 */

import { TrendingUp, TrendingDown, Wallet, Percent, Minus } from 'lucide-react'

import type { PeriodReport } from '../../api/finanzas'
import { formatMoney, formatPercent, formatDeltaPercent } from '../../lib/format'

interface Props {
  report: PeriodReport
}

interface CardDef {
  label: string
  /** Qué responde este número, en una línea. */
  ayuda: string
  value: string
  icon: typeof TrendingUp
  /** Δ ya formateado (con signo) o null si no aplica. */
  delta: string | null
  /** Sentido del Δ para colorear (null = neutro/gris). */
  deltaDir: 'up' | 'down' | null
}

/** Determina la dirección del Δ a partir del valor numérico crudo (null → neutro). */
function dir(value: number | null): 'up' | 'down' | null {
  if (value === null || value === 0) return null
  return value > 0 ? 'up' : 'down'
}

export default function ReporteKpiCards({ report }: Props) {
  const cards: CardDef[] = [
    {
      label: 'Producción',
      ayuda: 'Lo que se cobró en trabajo hecho',
      value: formatMoney(report.production),
      icon: TrendingUp,
      delta: formatDeltaPercent(report.delta_production_pct),
      deltaDir: dir(report.delta_production_pct),
    },
    {
      label: 'Cobranza',
      ayuda: 'Lo que realmente entró a caja',
      value: formatMoney(report.collection),
      icon: Wallet,
      delta: formatDeltaPercent(report.delta_collection_pct),
      deltaDir: dir(report.delta_collection_pct),
    },
    {
      label: '% Cobrado',
      ayuda: 'Cuánto de lo producido ya se cobró',
      value: formatPercent(report.collection_pct),
      icon: Percent,
      // El backend manda Δ en puntos porcentuales (delta_collection_rate_ppt).
      delta:
        report.delta_collection_rate_ppt === null
          ? null
          : `${report.delta_collection_rate_ppt > 0 ? '+' : ''}${(
              report.delta_collection_rate_ppt * 100
            ).toFixed(1)} pp`,
      deltaDir: dir(report.delta_collection_rate_ppt),
    },
  ]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {cards.map(({ label, ayuda, value, icon: Icon, delta, deltaDir }) => {
        const DeltaIcon = deltaDir === 'up' ? TrendingUp : deltaDir === 'down' ? TrendingDown : Minus
        const deltaClase =
          deltaDir === 'up' ? 'text-exito' : deltaDir === 'down' ? 'text-peligro' : 'text-suave'
        return (
          <div key={label} className="card p-4 flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-suave">{label}</span>
              <Icon className="w-4 h-4 shrink-0 text-borde-fuerte" />
            </div>

            <span className="text-2xl font-bold tracking-tight text-tinta tabular-nums">
              {value}
            </span>

            {delta !== null ? (
              <span className={`inline-flex items-center gap-1 text-xs font-semibold ${deltaClase}`}>
                <DeltaIcon className="w-3.5 h-3.5" />
                {delta}
                <span className="font-normal text-suave">vs. periodo anterior</span>
              </span>
            ) : (
              <span className="text-xs text-suave">Sin periodo anterior para comparar</span>
            )}

            <p className="text-[11px] text-suave leading-snug">{ayuda}</p>
          </div>
        )
      })}
    </div>
  )
}
