import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { AgingBucket } from '../../../api/finanzas'
import { formatMoney } from '../../../lib/format'

interface Props {
  data: AgingBucket[]
  onSelectBucket?: (bucket: string | null) => void
  selectedBucket?: string | null
}

// Verde → ámbar → rojo conforme envejece la deuda.
const BUCKET_COLORS: Record<string, string> = {
  '0-30': '#0F766E',
  '31-60': '#C9A227',
  '61-90': '#B45309',
  '90+': '#B91C1C',
}

export default function AgingChart({ data, onSelectBucket, selectedBucket }: Props) {
  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>
          Antigüedad de cuentas por cobrar
        </h3>
        {selectedBucket && (
          <button
            onClick={() => onSelectBucket?.(null)}
            className="text-xs font-medium hover:underline"
            style={{ color: '#C9A227' }}
          >
            {selectedBucket} días — quitar filtro
          </button>
        )}
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" vertical={false} />
          <XAxis
            dataKey="bucket"
            tick={{ fontSize: 11, fill: '#7A756C' }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `${v} días`}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#9A958C' }}
            axisLine={false}
            tickLine={false}
            width={70}
            tickFormatter={(v) => formatMoney(v).replace('MX$', '$')}
          />
          <Tooltip
            formatter={(v: number, _n, p: { payload?: AgingBucket }) => [
              `${formatMoney(v)} · ${p?.payload?.count ?? 0} cargos`,
              'Saldo',
            ]}
            contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
            cursor={{ fill: 'rgba(201,162,39,0.06)' }}
          />
          <Bar dataKey="amount" radius={[6, 6, 0, 0]} cursor="pointer">
            {data.map((entry) => (
              <Cell
                key={entry.bucket}
                fill={BUCKET_COLORS[entry.bucket] ?? '#9A958C'}
                opacity={!selectedBucket || selectedBucket === entry.bucket ? 1 : 0.35}
                onClick={() =>
                  onSelectBucket?.(selectedBucket === entry.bucket ? null : entry.bucket)
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-[11px] mt-1" style={{ color: '#9A958C' }}>
        Tip: haz clic en un segmento para ver los cargos de ese rango.
      </p>
    </div>
  )
}
