import { useState } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { IncomeByMethod } from '../../../api/finanzas'
import { formatMoney } from '../../../lib/format'

interface Props {
  data: IncomeByMethod[]
  onSelectMethod?: (method: string | null) => void
  selectedMethod?: string | null
}

const COLORS: Record<string, string> = {
  cash: '#0F766E',
  card: '#1D4ED8',
  transfer: '#C9A227',
  other: '#9A958C',
}

export default function MetodosPagoChart({ data, onSelectMethod, selectedMethod }: Props) {
  const [hidden, setHidden] = useState<Set<string>>(new Set())

  const visible = data.filter((d) => !hidden.has(d.method))
  const total = visible.reduce((acc, d) => acc + Number(d.amount), 0)

  const toggle = (method: string) => {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(method)) next.delete(method)
      else next.add(method)
      return next
    })
  }

  return (
    <div className="glass-card rounded-2xl p-4">
      <h3 className="text-sm font-semibold mb-3" style={{ color: '#2A241B' }}>
        Métodos de pago
      </h3>

      <div className="flex items-center gap-4">
        <ResponsiveContainer width="55%" height={200}>
          <PieChart>
            <Pie
              data={visible}
              dataKey="amount"
              nameKey="label"
              cx="50%"
              cy="50%"
              innerRadius={48}
              outerRadius={78}
              paddingAngle={2}
              onClick={(entry: { method?: string }) =>
                entry?.method &&
                onSelectMethod?.(selectedMethod === entry.method ? null : entry.method)
              }
            >
              {visible.map((entry) => (
                <Cell
                  key={entry.method}
                  fill={COLORS[entry.method] ?? '#9A958C'}
                  opacity={!selectedMethod || selectedMethod === entry.method ? 1 : 0.35}
                  cursor="pointer"
                />
              ))}
            </Pie>
            <Tooltip
              formatter={(v: number, _n, p: { payload?: { label?: string } }) => [
                `${formatMoney(v)} (${total ? ((v / total) * 100).toFixed(1) : 0}%)`,
                p?.payload?.label ?? '',
              ]}
              contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
            />
          </PieChart>
        </ResponsiveContainer>

        {/* Leyenda interactiva (toggle) */}
        <div className="flex-1 flex flex-col gap-1.5">
          {data.map((d) => {
            const isHidden = hidden.has(d.method)
            return (
              <button
                key={d.method}
                onClick={() => toggle(d.method)}
                className="flex items-center justify-between gap-2 text-xs px-2 py-1 rounded-lg transition-colors hover:bg-black/5"
                style={{ opacity: isHidden ? 0.4 : 1 }}
              >
                <span className="flex items-center gap-2">
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ background: COLORS[d.method] ?? '#9A958C' }}
                  />
                  <span style={{ color: '#2A241B' }}>{d.label}</span>
                </span>
                <span className="font-medium" style={{ color: '#7A756C' }}>
                  {formatMoney(d.amount)}
                </span>
              </button>
            )
          })}
          {data.length === 0 && (
            <span className="text-xs" style={{ color: '#9A958C' }}>Sin pagos en el periodo.</span>
          )}
        </div>
      </div>
    </div>
  )
}
