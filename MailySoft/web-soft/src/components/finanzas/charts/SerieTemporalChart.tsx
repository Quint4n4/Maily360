import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { PeriodReport } from '../../../api/finanzas'
import { formatMoney } from '../../../lib/format'

interface Props {
  report: PeriodReport
}

const PROD = '#7C3AED'
const COLL = '#0F766E'

/** Etiqueta del eje X según la granularidad: el periodo viene en ISO desde el backend. */
function periodLabel(period: string, group: PeriodReport['group']): string {
  if (group === 'month') return period.slice(0, 7) // YYYY-MM
  return period // YYYY-MM-DD (día / inicio de semana)
}

export default function SerieTemporalChart({ report }: Props) {
  const data = report.series.map((pt) => ({
    label: periodLabel(pt.period, report.group),
    production: Number(pt.production),
    collection: Number(pt.collection),
  }))

  // Promedio del periodo anterior, repartido entre los puntos, como referencia
  // visual de "el periodo anterior" (el backend solo manda totales prev, no serie).
  const n = data.length || 1
  const prevProdAvg = Number(report.prev_production) / n
  const prevCollAvg = Number(report.prev_collection) / n

  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>
          Producción y cobranza por periodo
        </h3>
        <span className="text-[11px]" style={{ color: '#9A958C' }}>
          Agrupado por {report.group === 'day' ? 'día' : report.group === 'week' ? 'semana' : 'mes'}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
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
            formatter={(v: number, name) => [
              formatMoney(v),
              name === 'production' ? 'Producción' : 'Cobranza',
            ]}
            contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
          />
          <Legend
            formatter={(value) => (value === 'production' ? 'Producción' : 'Cobranza')}
            wrapperStyle={{ fontSize: 11 }}
          />
          {/* Referencias del periodo anterior (promedio por punto) — superpuestas. */}
          {report.prev_production > 0 && (
            <ReferenceLine
              y={prevProdAvg}
              stroke={PROD}
              strokeDasharray="4 4"
              strokeOpacity={0.5}
              ifOverflow="extendDomain"
            />
          )}
          {report.prev_collection > 0 && (
            <ReferenceLine
              y={prevCollAvg}
              stroke={COLL}
              strokeDasharray="4 4"
              strokeOpacity={0.5}
              ifOverflow="extendDomain"
            />
          )}
          <Line type="monotone" dataKey="production" stroke={PROD} strokeWidth={2} dot={{ r: 2 }} />
          <Line type="monotone" dataKey="collection" stroke={COLL} strokeWidth={2} dot={{ r: 2 }} />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-[11px] mt-1" style={{ color: '#9A958C' }}>
        Las líneas punteadas marcan el promedio del periodo anterior como referencia.
      </p>
    </div>
  )
}
