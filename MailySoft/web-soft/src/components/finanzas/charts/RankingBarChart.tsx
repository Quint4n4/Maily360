import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatMoney } from '../../../lib/format'

/** Fila genérica de ranking: una etiqueta, un importe y un conteo. */
export interface RankingRow {
  name: string
  amount: number
  count: number
}

interface Props {
  title: string
  data: RankingRow[]
  color?: string
  emptyLabel?: string
  /** Etiqueta de la métrica de conteo en el tooltip (ej. "cargos", "actos"). */
  countLabel?: string
}

const GOLD = '#C9A227'

/**
 * Gráfica de barras horizontales reutilizable para rankings (top servicios, por
 * doctor). Genérica a propósito: las dos vistas comparten el mismo shape.
 */
export default function RankingBarChart({
  title,
  data,
  color = GOLD,
  emptyLabel = 'Sin datos en el periodo.',
  countLabel = 'cargos',
}: Props) {
  const rows = data.map((d) => ({ ...d, amount: Number(d.amount), count: Number(d.count) }))
  const height = Math.max(160, rows.length * 34 + 40)

  return (
    <div className="glass-card rounded-2xl p-4">
      <h3 className="text-sm font-semibold mb-3" style={{ color: '#2A241B' }}>
        {title}
      </h3>

      {rows.length === 0 ? (
        <div className="py-10 text-center text-xs" style={{ color: '#9A958C' }}>
          {emptyLabel}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" horizontal={false} />
            <XAxis
              type="number"
              tick={{ fontSize: 11, fill: '#9A958C' }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => formatMoney(v).replace('MX$', '$')}
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 11, fill: '#7A756C' }}
              axisLine={false}
              tickLine={false}
              width={140}
            />
            <Tooltip
              formatter={(v: number, _n, p: { payload?: RankingRow }) => [
                `${formatMoney(v)} · ${p?.payload?.count ?? 0} ${countLabel}`,
                'Importe',
              ]}
              contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
              cursor={{ fill: 'rgba(201,162,39,0.06)' }}
            />
            <Bar dataKey="amount" radius={[0, 6, 6, 0]}>
              {rows.map((r) => (
                <Cell key={r.name} fill={color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
