import { TrendingUp, Wallet, AlertTriangle, Receipt, Percent, ArrowUpRight } from 'lucide-react'
import type { DashboardKpis } from '../../api/finanzas'
import { formatMoney, formatPercent } from '../../lib/format'

interface KpiCardsProps {
  kpis: DashboardKpis
  /** Navega a otra pestaña de Finanzas al hacer clic en una tarjeta (solo UX). */
  onNavigate?: (tab: string) => void
}

const GOLD = '#C9A227'

interface CardDef {
  label: string
  value: string
  icon: typeof TrendingUp
  tint: string
  /** Pestaña destino al hacer clic (si aplica). */
  target?: string
  /** Texto del enlace de detalle. */
  action?: string
}

export default function KpiCards({ kpis, onNavigate }: KpiCardsProps) {
  const cards: CardDef[] = [
    { label: 'Ingresos del periodo', value: formatMoney(kpis.total_income), icon: TrendingUp, tint: '#0F766E', target: 'reportes', action: 'Ver reporte' },
    { label: 'Cuentas por cobrar', value: formatMoney(kpis.outstanding), icon: AlertTriangle, tint: '#B45309', target: 'cobros', action: 'Ver cuentas' },
    { label: 'Ticket promedio', value: formatMoney(kpis.average_ticket), icon: Receipt, tint: '#1D4ED8', target: 'reportes', action: 'Ver reporte' },
    { label: '% Cobrado', value: formatPercent(kpis.collection_rate), icon: Percent, tint: GOLD, target: 'reportes', action: 'Ver reporte' },
    { label: 'Total facturado', value: formatMoney(kpis.total_charged), icon: Wallet, tint: '#7C3AED', target: 'reportes', action: 'Ver reporte' },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
      {cards.map(({ label, value, icon: Icon, tint, target, action }) => {
        const clickable = Boolean(target && onNavigate)

        const inner = (
          <>
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
            {clickable && (
              <span
                className="mt-0.5 inline-flex items-center gap-1 text-[11px] font-medium"
                style={{ color: tint }}
              >
                {action}
                <ArrowUpRight className="w-3 h-3" />
              </span>
            )}
          </>
        )

        if (clickable) {
          return (
            <button
              key={label}
              type="button"
              onClick={() => onNavigate?.(target as string)}
              aria-label={`${label}: ${value}. ${action}`}
              className="glass-card rounded-2xl p-4 flex flex-col gap-2 text-left w-full cursor-pointer transition-transform duration-150 hover:-translate-y-0.5 hover:shadow-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
            >
              {inner}
            </button>
          )
        }

        return (
          <div key={label} className="glass-card rounded-2xl p-4 flex flex-col gap-2">
            {inner}
          </div>
        )
      })}
    </div>
  )
}
