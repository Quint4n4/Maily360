import { useState } from 'react'
import { Loader2, Printer, Lock } from 'lucide-react'

import type { Role } from '../../auth/permisos'
import { puedeCobrar } from '../../auth/permisos'
import { useCierreDiario } from '../../hooks/finanzas'
import { formatMoney, formatPercent, formatDateTime, toIsoDate } from '../../lib/format'

interface Props {
  role: Role
}

const GOLD = '#C9A227'

export default function CierreDiarioTab({ role }: Props) {
  const [date, setDate] = useState<string>(toIsoDate(new Date()))
  const { data: sheet, isLoading, isError, error } = useCierreDiario(date)

  // Gating de UX: solo caja (owner/admin/finance/reception). El backend es la
  // autoridad y devuelve 403 igualmente.
  if (!puedeCobrar(role)) {
    return (
      <div className="glass-card rounded-2xl p-10 text-center">
        <Lock className="w-8 h-8 mx-auto mb-3" style={{ color: '#9A958C' }} />
        <p className="text-sm" style={{ color: '#7A756C' }}>
          Tu rol (<strong>{role}</strong>) no tiene acceso al cierre diario de caja.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Controles (se ocultan al imprimir) */}
      <div className="glass-card rounded-2xl p-3 flex items-center justify-between flex-wrap gap-3 print:hidden">
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium" style={{ color: '#7A756C' }}>Fecha del cierre</label>
          <input
            type="date"
            className="input py-1.5 text-sm"
            value={date}
            max={toIsoDate(new Date())}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
        <button className="btn-secondary" disabled={!sheet} onClick={() => window.print()}>
          <Printer className="w-4 h-4" /> Imprimir
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20" style={{ color: '#9A958C' }}>
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      )}

      {isError && (
        <div className="glass-card rounded-2xl p-6 text-sm" style={{ color: '#B91C1C' }}>
          No se pudo cargar el cierre del día. {(error as Error)?.message ?? ''}
        </div>
      )}

      {sheet && (
        <div className="glass-card rounded-2xl p-5 space-y-5" id="cierre-imprimible">
          <div>
            <h2 className="text-lg font-bold" style={{ color: '#2A241B' }}>Cierre de caja</h2>
            <p className="text-sm" style={{ color: '#7A756C' }}>{date}</p>
          </div>

          {/* Resumen del día */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SummaryCard label="Producción" value={formatMoney(sheet.production)} tint="#7C3AED" />
            <SummaryCard label="Cobranza" value={formatMoney(sheet.collection)} tint="#0F766E" />
            <SummaryCard label="Ajustes" value={formatMoney(sheet.adjustments_total)} tint="#B45309" />
            <SummaryCard label="% Cobranza" value={formatPercent(sheet.collection_pct)} tint={GOLD} />
          </div>

          {/* Desglose por método */}
          <div>
            <h3 className="text-sm font-semibold mb-2" style={{ color: '#2A241B' }}>
              Cobranza por método
            </h3>
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left" style={{ color: '#9A958C' }}>
                    <th className="py-1.5 font-medium">Método</th>
                    <th className="py-1.5 font-medium text-right">Importe</th>
                    <th className="py-1.5 font-medium text-right">Pagos</th>
                  </tr>
                </thead>
                <tbody>
                  {sheet.by_method.map((m) => (
                    <tr key={m.method} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                      <td className="py-1.5" style={{ color: '#2A241B' }}>{m.label}</td>
                      <td className="py-1.5 text-right font-medium" style={{ color: '#2A241B' }}>
                        {formatMoney(m.amount)}
                      </td>
                      <td className="py-1.5 text-right" style={{ color: '#7A756C' }}>{m.count}</td>
                    </tr>
                  ))}
                  {sheet.by_method.length === 0 && (
                    <tr>
                      <td colSpan={3} className="py-6 text-center" style={{ color: '#9A958C' }}>
                        Sin pagos en este día.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Movimientos del día */}
          <div>
            <h3 className="text-sm font-semibold mb-2" style={{ color: '#2A241B' }}>
              Movimientos del día ({sheet.totals.charges_count} cargos · {sheet.totals.payments_count} pagos)
            </h3>
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left" style={{ color: '#9A958C' }}>
                    <th className="py-1.5 font-medium">Hora</th>
                    <th className="py-1.5 font-medium">Tipo</th>
                    <th className="py-1.5 font-medium">Detalle</th>
                    <th className="py-1.5 font-medium text-right">Monto</th>
                  </tr>
                </thead>
                <tbody>
                  {sheet.movements.map((m, idx) => (
                    <tr key={`${m.type}-${idx}`} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                      <td className="py-1.5" style={{ color: '#7A756C' }}>{formatDateTime(m.at)}</td>
                      <td className="py-1.5">
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                          style={{
                            background: m.type === 'payment' ? 'rgba(15,118,110,0.12)' : 'rgba(124,58,237,0.12)',
                            color: m.type === 'payment' ? '#0F766E' : '#7C3AED',
                          }}
                        >
                          {m.type === 'payment' ? 'Pago' : 'Cargo'}
                        </span>
                      </td>
                      <td className="py-1.5" style={{ color: '#2A241B' }}>
                        {m.type === 'payment'
                          ? `${m.method_label ?? ''}${m.reference ? ` · ${m.reference}` : ''}`
                          : m.description ?? ''}
                      </td>
                      <td
                        className="py-1.5 text-right font-medium"
                        style={{ color: m.type === 'payment' ? '#0F766E' : '#7C3AED' }}
                      >
                        {formatMoney(m.amount)}
                      </td>
                    </tr>
                  ))}
                  {sheet.movements.length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-8 text-center" style={{ color: '#9A958C' }}>
                        No hubo movimientos este día.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
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
