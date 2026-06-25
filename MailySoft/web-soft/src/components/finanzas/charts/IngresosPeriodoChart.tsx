import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { IncomeByDay } from '../../../api/finanzas'
import { formatMoney } from '../../../lib/format'

type Granularity = 'day' | 'week' | 'month'

interface Props {
  data: IncomeByDay[]
  /** Drill-down: al hacer clic en un punto, refiltra las tablas por esa fecha. */
  onSelectDate?: (date: string | null) => void
  selectedDate?: string | null
}

const GOLD = '#C9A227'

function bucketKey(date: string, granularity: Granularity): string {
  const d = new Date(date)
  if (granularity === 'day') return date
  if (granularity === 'month') return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  // semana ISO aproximada: año-Wnn
  const firstJan = new Date(d.getFullYear(), 0, 1)
  const week = Math.ceil(((d.getTime() - firstJan.getTime()) / 86400000 + firstJan.getDay() + 1) / 7)
  return `${d.getFullYear()}-W${String(week).padStart(2, '0')}`
}

export default function IngresosPeriodoChart({ data, onSelectDate, selectedDate }: Props) {
  const [granularity, setGranularity] = useState<Granularity>('day')

  const series = useMemo(() => {
    const map = new Map<string, number>()
    for (const row of data) {
      const key = bucketKey(row.date, granularity)
      map.set(key, (map.get(key) ?? 0) + Number(row.amount))
    }
    return Array.from(map.entries()).map(([label, amount]) => ({ label, amount }))
  }, [data, granularity])

  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>
          Ingresos por periodo
        </h3>
        <div className="flex items-center gap-1 rounded-lg p-0.5" style={{ background: 'rgba(0,0,0,0.04)' }}>
          {(['day', 'week', 'month'] as Granularity[]).map((g) => (
            <button
              key={g}
              onClick={() => setGranularity(g)}
              className="px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
              style={{
                background: granularity === g ? GOLD : 'transparent',
                color: granularity === g ? '#fff' : '#7A756C',
              }}
            >
              {g === 'day' ? 'Día' : g === 'week' ? 'Semana' : 'Mes'}
            </button>
          ))}
        </div>
      </div>

      {selectedDate && (
        <button
          onClick={() => onSelectDate?.(null)}
          className="text-xs mb-2 font-medium hover:underline"
          style={{ color: GOLD }}
        >
          Filtrando por {selectedDate} — quitar filtro
        </button>
      )}

      <ResponsiveContainer width="100%" height={240}>
        <AreaChart
          data={series}
          margin={{ top: 8, right: 8, left: -10, bottom: 0 }}
          onClick={(state: { activeLabel?: string }) => {
            if (granularity === 'day' && state?.activeLabel) {
              onSelectDate?.(state.activeLabel)
            }
          }}
        >
          <defs>
            <linearGradient id="incomeGold" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={GOLD} stopOpacity={0.5} />
              <stop offset="100%" stopColor={GOLD} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#9A958C' }} axisLine={false} tickLine={false} />
          <YAxis
            tick={{ fontSize: 11, fill: '#9A958C' }}
            axisLine={false}
            tickLine={false}
            width={70}
            tickFormatter={(v) => formatMoney(v).replace('MX$', '$')}
          />
          <Tooltip
            formatter={(v: number) => [formatMoney(v), 'Ingresos']}
            contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
          />
          <Area
            type="monotone"
            dataKey="amount"
            stroke={GOLD}
            strokeWidth={2}
            fill="url(#incomeGold)"
            activeDot={{ r: 5, style: { cursor: 'pointer' } }}
          />
        </AreaChart>
      </ResponsiveContainer>
      {granularity === 'day' && (
        <p className="text-[11px] mt-1" style={{ color: '#9A958C' }}>
          Tip: haz clic en un punto para filtrar los movimientos por ese día.
        </p>
      )}
    </div>
  )
}
