import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { ReportAgingBucket } from '../../../api/finanzas'
import { formatMoney } from '../../../lib/format'

interface Props {
  data: ReportAgingBucket[]
}

// Verde → ámbar → naranja → rojo conforme envejece la deuda.
const BUCKET_COLORS: Record<string, string> = {
  '0-30': '#0F766E',
  '31-60': '#C9A227',
  '61-90': '#B45309',
  '90+': '#B91C1C',
}

/** Orden canónico de los buckets (el backend ya los manda así, pero lo aseguramos). */
const ORDER = ['0-30', '31-60', '61-90', '90+']

export default function AgingApiladoChart({ data }: Props) {
  // Pivotar a UNA fila con una serie por bucket → barra horizontal apilada.
  const sorted = [...data].sort((a, b) => ORDER.indexOf(a.bucket) - ORDER.indexOf(b.bucket))
  const row: Record<string, number> = { name: 0 as unknown as number }
  for (const b of sorted) row[b.bucket] = Number(b.amount)
  const total = sorted.reduce((acc, b) => acc + Number(b.amount), 0)

  return (
    <div className="glass-card rounded-2xl p-4">
      <h3 className="text-sm font-semibold mb-3" style={{ color: '#2A241B' }}>
        Antigüedad de cuentas por cobrar
      </h3>

      {total === 0 ? (
        <div className="py-10 text-center text-xs" style={{ color: '#9A958C' }}>
          Sin saldos pendientes.
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={90}>
            <BarChart layout="vertical" data={[row]} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="name" hide />
              <Tooltip
                formatter={(v: number, name) => [formatMoney(v), `${name} días`]}
                contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
                cursor={{ fill: 'rgba(201,162,39,0.06)' }}
              />
              {sorted.map((b, i) => (
                <Bar
                  key={b.bucket}
                  dataKey={b.bucket}
                  stackId="ar"
                  radius={
                    i === 0
                      ? [6, 0, 0, 6]
                      : i === sorted.length - 1
                        ? [0, 6, 6, 0]
                        : [0, 0, 0, 0]
                  }
                >
                  <Cell fill={BUCKET_COLORS[b.bucket] ?? '#9A958C'} />
                </Bar>
              ))}
            </BarChart>
          </ResponsiveContainer>

          {/* Leyenda con monto + nº de cargos por bucket. */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
            {sorted.map((b) => (
              <div key={b.bucket} className="flex items-center gap-2 text-xs">
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ background: BUCKET_COLORS[b.bucket] ?? '#9A958C' }}
                />
                <div className="flex flex-col leading-tight">
                  <span style={{ color: '#2A241B' }}>{b.bucket} días</span>
                  <span className="font-medium" style={{ color: '#7A756C' }}>
                    {formatMoney(b.amount)} · {b.count}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
