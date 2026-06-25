import { TrendingUp, TrendingDown, Wallet, AlertTriangle, Receipt, Percent, Minus } from 'lucide-react'

import type { PeriodReport } from '../../api/finanzas'
import { formatMoney, formatPercent, formatDeltaPercent } from '../../lib/format'

interface Props {
  report: PeriodReport
}

const GOLD = '#C9A227'
const POS = '#0F766E'
const NEG = '#B91C1C'

interface CardDef {
  label: string
  value: string
  icon: typeof TrendingUp
  tint: string
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
      value: formatMoney(report.production),
      icon: TrendingUp,
      tint: '#7C3AED',
      delta: formatDeltaPercent(report.delta_production_pct),
      deltaDir: dir(report.delta_production_pct),
    },
    {
      label: 'Cobranza',
      value: formatMoney(report.collection),
      icon: Wallet,
      tint: POS,
      delta: formatDeltaPercent(report.delta_collection_pct),
      deltaDir: dir(report.delta_collection_pct),
    },
    {
      label: '% Cobranza',
      value: formatPercent(report.collection_pct),
      icon: Percent,
      tint: GOLD,
      // El backend manda Δ en puntos porcentuales (delta_collection_rate_ppt).
      delta:
        report.delta_collection_rate_ppt === null
          ? null
          : `${report.delta_collection_rate_ppt > 0 ? '+' : ''}${(
              report.delta_collection_rate_ppt * 100
            ).toFixed(1)} pp`,
      deltaDir: dir(report.delta_collection_rate_ppt),
    },
    {
      label: 'Cuentas por cobrar',
      value: formatMoney(report.ar_total),
      icon: AlertTriangle,
      tint: '#B45309',
      delta: null,
      deltaDir: null,
    },
    {
      label: 'Ticket promedio',
      value: formatMoney(report.average_ticket),
      icon: Receipt,
      tint: '#1D4ED8',
      delta: null,
      deltaDir: null,
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
      {cards.map(({ label, value, icon: Icon, tint, delta, deltaDir }) => {
        const deltaColor = deltaDir === 'up' ? POS : deltaDir === 'down' ? NEG : '#9A958C'
        const DeltaIcon = deltaDir === 'up' ? TrendingUp : deltaDir === 'down' ? TrendingDown : Minus
        return (
          <div key={label} className="glass-card rounded-2xl p-4 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium" style={{ color: '#7A756C' }}>{label}</span>
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center"
                style={{ background: `${tint}1A` }}
              >
                <Icon className="w-4 h-4" style={{ color: tint }} />
              </div>
            </div>
            <span className="text-xl font-bold tracking-tight" style={{ color: '#2A241B' }}>
              {value}
            </span>
            {delta !== null ? (
              <span className="inline-flex items-center gap-1 text-xs font-medium" style={{ color: deltaColor }}>
                <DeltaIcon className="w-3.5 h-3.5" />
                {delta}
                <span style={{ color: '#9A958C' }} className="font-normal">vs. anterior</span>
              </span>
            ) : (
              <span className="text-xs" style={{ color: '#C2BDB3' }}>—</span>
            )}
          </div>
        )
      })}
    </div>
  )
}
