/**
 * TendenciaChart — gráfica de líneas reutilizable para una serie de signos vitales.
 * Consume una lista de {measured_at, value} (del endpoint /signos/series/).
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SeriesPoint } from '../../types/expediente'
import { formatFechaCorta } from '../../lib/fecha'

interface TendenciaChartProps {
  /** Puntos de la serie (orden ASC por measured_at). */
  data: SeriesPoint[]
  /** Etiqueta del parámetro (p. ej. "Peso (kg)"). */
  label: string
  /** Color de la línea (default dorado de la marca). */
  color?: string
  /** Alto del contenedor en px. */
  height?: number
}

/** Tooltip personalizado: muestra fecha y valor formateados. */
interface TooltipPayloadItem {
  value: number
  payload: SeriesPoint
}
function ChartTooltip({
  active,
  payload,
  label: paramLabel,
}: {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label: string
}) {
  if (!active || !payload || payload.length === 0) return null
  const punto = payload[0]
  return (
    <div className="rounded-lg px-3 py-2 text-xs shadow-md" style={{ background: 'rgba(255,255,255,0.95)', border: '1px solid rgba(201,162,39,0.3)' }}>
      <p className="font-semibold text-gray-800">{paramLabel}: {punto.value}</p>
      <p className="text-gray-500">{formatFechaCorta(punto.payload.measured_at)}</p>
    </div>
  )
}

export default function TendenciaChart({
  data,
  label,
  color = '#C9A227',
  height = 200,
}: TendenciaChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center text-xs text-gray-400 italic" style={{ height }}>
        Sin datos para «{label}» todavía.
      </div>
    )
  }

  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -12 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(60,42,12,0.08)" />
          <XAxis
            dataKey="measured_at"
            tickFormatter={(v: string) => formatFechaCorta(v)}
            tick={{ fontSize: 10, fill: '#9aa0a6' }}
            stroke="rgba(60,42,12,0.15)"
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#9aa0a6' }}
            stroke="rgba(60,42,12,0.15)"
            domain={['auto', 'auto']}
            width={40}
          />
          <Tooltip content={<ChartTooltip label={label} />} />
          <Line
            type="monotone"
            dataKey="value"
            name={label}
            stroke={color}
            strokeWidth={2}
            dot={{ r: 3, fill: color }}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
