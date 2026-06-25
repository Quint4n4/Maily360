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
import type { IncomeByConcept } from '../../../api/finanzas'
import { formatMoney } from '../../../lib/format'

interface Props {
  data: IncomeByConcept[]
  onSelectConcept?: (concept: string | null) => void
  selectedConcept?: string | null
}

const GOLD = '#C9A227'
const DIM = '#E4D8AE'

export default function IngresosConceptoChart({ data, onSelectConcept, selectedConcept }: Props) {
  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>
          Ingresos por concepto
        </h3>
        {selectedConcept && (
          <button
            onClick={() => onSelectConcept?.(null)}
            className="text-xs font-medium hover:underline"
            style={{ color: GOLD }}
          >
            {selectedConcept} — quitar filtro
          </button>
        )}
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
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
            dataKey="concept"
            tick={{ fontSize: 11, fill: '#7A756C' }}
            axisLine={false}
            tickLine={false}
            width={120}
          />
          <Tooltip
            formatter={(v: number) => [formatMoney(v), 'Importe']}
            contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
            cursor={{ fill: 'rgba(201,162,39,0.06)' }}
          />
          <Bar dataKey="amount" radius={[0, 6, 6, 0]} cursor="pointer">
            {data.map((entry) => (
              <Cell
                key={entry.concept}
                fill={!selectedConcept || selectedConcept === entry.concept ? GOLD : DIM}
                onClick={() =>
                  onSelectConcept?.(selectedConcept === entry.concept ? null : entry.concept)
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-[11px] mt-1" style={{ color: '#9A958C' }}>
        Tip: haz clic en una barra para filtrar la tabla por ese concepto.
      </p>
    </div>
  )
}
