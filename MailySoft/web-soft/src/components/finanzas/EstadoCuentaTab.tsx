import { useState } from 'react'
import { Loader2, FileDown, FileSpreadsheet } from 'lucide-react'
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'

import type { PatientLite } from '../../api/pacientes'
import { useStatement } from '../../hooks/finanzas'
import { formatMoney, formatDate } from '../../lib/format'
import { exportStatementPdf, exportStatementExcel } from '../../lib/exportEstadoCuenta'
import PatientPicker from './PatientPicker'

const GOLD = '#C9A227'

export default function EstadoCuentaTab() {
  const [patient, setPatient] = useState<PatientLite | null>(null)
  const statement = useStatement(patient?.id ?? null)

  return (
    <div className="space-y-4">
      <div className="glass-card rounded-2xl p-4">
        <label className="label">Paciente</label>
        <PatientPicker value={patient} onChange={setPatient} />
      </div>

      {patient && statement.isLoading && (
        <div className="flex items-center justify-center py-16" style={{ color: '#9A958C' }}>
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      )}

      {patient && statement.data && (
        <div className="glass-card rounded-2xl p-5">
          {/* Encabezado + export */}
          <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
            <div>
              <h2 className="text-lg font-bold" style={{ color: '#2A241B' }}>Estado de cuenta</h2>
              <p className="text-sm" style={{ color: '#7A756C' }}>
                {statement.data.patient.full_name} · Exp. {statement.data.patient.record_number}
              </p>
            </div>
            <div className="flex gap-2">
              <button className="btn-secondary" onClick={() => exportStatementPdf(statement.data!)}>
                <FileDown className="w-4 h-4" /> PDF
              </button>
              <button className="btn-secondary" onClick={() => void exportStatementExcel(statement.data!)}>
                <FileSpreadsheet className="w-4 h-4" /> Excel
              </button>
            </div>
          </div>

          {/* Resumen de saldo */}
          <div className="grid grid-cols-3 gap-3 mb-4">
            <SummaryCard label="Total cargos" value={formatMoney(statement.data.total_charged)} tint="#7C3AED" />
            <SummaryCard label="Total pagos" value={formatMoney(statement.data.total_paid)} tint="#0F766E" />
            <SummaryCard label="Saldo" value={formatMoney(statement.data.balance)} tint={GOLD} />
          </div>

          {/* Mini-gráfica de evolución del saldo */}
          {statement.data.movements.length > 0 && (
            <div className="rounded-xl p-3 mb-4" style={{ background: 'rgba(0,0,0,0.02)' }}>
              <h3 className="text-xs font-semibold mb-2" style={{ color: '#7A756C' }}>
                Evolución del saldo
              </h3>
              <ResponsiveContainer width="100%" height={160}>
                <LineChart
                  data={statement.data.movements.map((m) => ({ date: formatDate(m.date), balance: m.balance }))}
                  margin={{ top: 6, right: 8, left: -10, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9A958C' }} axisLine={false} tickLine={false} />
                  <YAxis
                    tick={{ fontSize: 10, fill: '#9A958C' }}
                    axisLine={false}
                    tickLine={false}
                    width={64}
                    tickFormatter={(v) => formatMoney(v).replace('MX$', '$')}
                  />
                  <Tooltip
                    formatter={(v: number) => [formatMoney(v), 'Saldo']}
                    contentStyle={{ borderRadius: 12, border: '1px solid rgba(0,0,0,0.08)', fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="balance" stroke={GOLD} strokeWidth={2} dot={{ r: 2 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Tabla de movimientos */}
          <div className="overflow-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left" style={{ color: '#9A958C' }}>
                  <th className="py-2 font-medium">Fecha</th>
                  <th className="py-2 font-medium">Concepto</th>
                  <th className="py-2 font-medium text-right">Cargo</th>
                  <th className="py-2 font-medium text-right">Pago</th>
                  <th className="py-2 font-medium text-right">Saldo</th>
                </tr>
              </thead>
              <tbody>
                {statement.data.movements.map((m) => (
                  <tr key={m.id} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                    <td className="py-2" style={{ color: '#7A756C' }}>{formatDate(m.date)}</td>
                    <td className="py-2" style={{ color: '#2A241B' }}>{m.description}</td>
                    <td className="py-2 text-right" style={{ color: '#7C3AED' }}>
                      {m.charge ? formatMoney(m.charge) : ''}
                    </td>
                    <td className="py-2 text-right" style={{ color: '#0F766E' }}>
                      {m.payment ? formatMoney(m.payment) : ''}
                    </td>
                    <td className="py-2 text-right font-medium" style={{ color: '#2A241B' }}>
                      {formatMoney(m.balance)}
                    </td>
                  </tr>
                ))}
                {statement.data.movements.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-8 text-center" style={{ color: '#9A958C' }}>
                      Este paciente no tiene movimientos.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function SummaryCard({ label, value, tint }: { label: string; value: string; tint: string }) {
  return (
    <div className="rounded-xl p-3" style={{ background: `${tint}10`, border: `1px solid ${tint}22` }}>
      <div className="text-[11px]" style={{ color: '#7A756C' }}>{label}</div>
      <div className="text-lg font-bold" style={{ color: tint }}>{value}</div>
    </div>
  )
}
