import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { QuotesFunnel } from '../../../api/finanzas'
import { formatPercent } from '../../../lib/format'

interface Props {
  funnel: QuotesFunnel
}

const STEP_COLORS = ['#1D4ED8', '#0F766E', '#16A34A']

export default function EmbudoChart({ funnel }: Props) {
  // Embudo: total enviadas (sent + accepted) → aceptadas.
  const sentTotal = funnel.sent + funnel.accepted
  const steps = [
    { stage: 'Enviadas', value: sentTotal },
    { stage: 'En seguimiento', value: funnel.sent },
    { stage: 'Aceptadas', value: funnel.accepted },
  ]

  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>
          Embudo de cotizaciones
        </h3>
        <span
          className="text-xs font-semibold px-2 py-0.5 rounded-full"
          style={{ background: 'rgba(22,163,74,0.12)', color: '#16A34A' }}
        >
          Conversión {formatPercent(funnel.conversion_rate)}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={steps} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis
            type="category"
            dataKey="stage"
            tick={{ fontSize: 12, fill: '#7A756C' }}
            axisLine={false}
            tickLine={false}
            width={110}
          />
          <Tooltip
            formatter={(v: number) => [`${v} cotizaciones`, '']}
            contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
            cursor={{ fill: 'rgba(0,0,0,0.03)' }}
          />
          <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={28}>
            {steps.map((_, i) => (
              <Cell key={i} fill={STEP_COLORS[i]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <div className="grid grid-cols-3 gap-2 mt-2 text-center">
        <Stat label="Aceptadas" value={funnel.accepted} tint="#16A34A" />
        <Stat label="Rechazadas" value={funnel.rejected} tint="#B91C1C" />
        <Stat label="Vencidas" value={funnel.expired} tint="#B45309" />
      </div>
    </div>
  )
}

function Stat({ label, value, tint }: { label: string; value: number; tint: string }) {
  return (
    <div className="rounded-xl py-1.5" style={{ background: `${tint}12` }}>
      <div className="text-base font-bold" style={{ color: tint }}>{value}</div>
      <div className="text-[11px]" style={{ color: '#7A756C' }}>{label}</div>
    </div>
  )
}
