import { TrendingUp, Wallet, AlertTriangle, Receipt, Percent } from 'lucide-react'
import type { DashboardKpis } from '../../api/finanzas'
import { formatMoney, formatPercent } from '../../lib/format'

interface KpiCardsProps {
  kpis: DashboardKpis
}

const GOLD = '#C9A227'

interface CardDef {
  label: string
  value: string
  icon: typeof TrendingUp
  tint: string
}

export default function KpiCards({ kpis }: KpiCardsProps) {
  const cards: CardDef[] = [
    { label: 'Ingresos del periodo', value: formatMoney(kpis.total_income), icon: TrendingUp, tint: '#0F766E' },
    { label: 'Cuentas por cobrar', value: formatMoney(kpis.outstanding), icon: AlertTriangle, tint: '#B45309' },
    { label: 'Ticket promedio', value: formatMoney(kpis.average_ticket), icon: Receipt, tint: '#1D4ED8' },
    { label: '% Cobrado', value: formatPercent(kpis.collection_rate), icon: Percent, tint: GOLD },
    { label: 'Total facturado', value: formatMoney(kpis.total_charged), icon: Wallet, tint: '#7C3AED' },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
      {cards.map(({ label, value, icon: Icon, tint }) => (
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
        </div>
      ))}
    </div>
  )
}
