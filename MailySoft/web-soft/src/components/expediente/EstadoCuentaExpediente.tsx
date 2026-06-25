/**
 * EstadoCuentaExpediente — pestaña "Estado de cuenta" DENTRO del expediente
 * del paciente (Fase 1 del plan finanzas-pacientes-unificacion).
 *
 * Muestra el ledger completo del paciente (movimientos con saldo corrido) +
 * totales (cobrado / pagado / saldo). Incluye el botón "Registrar pago" (solo si
 * puedeCobrar) que abre PagoModal para asignar el pago a los cargos pendientes.
 *
 * Reutiliza la lógica de EstadoCuentaTab (panel de finanzas) adaptada al layout
 * del drawer. El gating de visibilidad lo decide el llamador (ExpedienteDrawer)
 * con puedeVerEstadoCuenta; aquí solo controlamos el botón de cobro.
 */

import { useState } from 'react'
import { Loader2, CreditCard, AlertTriangle } from 'lucide-react'

import type { PatientOut } from '../../types/paciente'
import { useStatement, useCharges } from '../../hooks/finanzas'
import { formatMoney, formatDate } from '../../lib/format'
import { ApiError } from '../../lib/http'
import PagoModal from './PagoModal'

const ORO = '#C9A227'

interface Props {
  paciente: PatientOut
  /** Si el rol puede cobrar (caja): muestra el botón "Registrar pago". */
  puedeCobrar: boolean
}

export default function EstadoCuentaExpediente({ paciente, puedeCobrar }: Props) {
  const statement = useStatement(paciente.id)
  // Cargos del paciente: necesarios para que PagoModal ofrezca la asignación.
  const charges = useCharges(puedeCobrar ? { patient_id: paciente.id } : {})
  const [pagoAbierto, setPagoAbierto] = useState(false)

  if (statement.isLoading) {
    return (
      <div className="flex items-center justify-center py-16" style={{ color: '#9A958C' }}>
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    )
  }

  if (statement.isError || !statement.data) {
    const esPermiso = statement.error instanceof ApiError && statement.error.status === 403
    return (
      <div
        className="flex items-start gap-3 rounded-2xl px-5 py-4"
        style={{ background: 'rgba(192,57,43,0.08)', border: '1px solid rgba(192,57,43,0.28)' }}
      >
        <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0 text-red-500" />
        <div>
          <p className="text-sm font-semibold text-red-700">
            {esPermiso
              ? 'No tienes permiso para ver el estado de cuenta.'
              : 'No se pudo cargar el estado de cuenta.'}
          </p>
          <p className="text-xs text-red-600/80 mt-0.5">
            {esPermiso ? 'El acceso a costos lo define tu clínica.' : 'Intenta de nuevo en un momento.'}
          </p>
        </div>
      </div>
    )
  }

  const data = statement.data

  return (
    <div className="space-y-4">
      {/* Encabezado + acción */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-base font-bold" style={{ color: '#2A241B' }}>
            Estado de cuenta
          </h3>
          <p className="text-sm" style={{ color: '#7A756C' }}>
            {data.patient.full_name} · Exp. {data.patient.record_number}
          </p>
        </div>
        {puedeCobrar && (
          <button
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
            style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
            onClick={() => setPagoAbierto(true)}
          >
            <CreditCard className="w-4 h-4" /> Registrar pago
          </button>
        )}
      </div>

      {/* Resumen de totales */}
      <div className="grid grid-cols-3 gap-3">
        <SummaryCard label="Total cargos" value={formatMoney(data.total_charged)} tint="#7C3AED" />
        <SummaryCard label="Total pagos" value={formatMoney(data.total_paid)} tint="#0F766E" />
        <SummaryCard label="Saldo" value={formatMoney(data.balance)} tint={ORO} />
      </div>

      {/* Tabla de movimientos (ledger con saldo corrido) */}
      <div
        className="rounded-2xl p-4 overflow-auto"
        style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(201,162,39,0.18)' }}
      >
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
            {data.movements.map(m => (
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
            {data.movements.length === 0 && (
              <tr>
                <td colSpan={5} className="py-8 text-center" style={{ color: '#9A958C' }}>
                  Este paciente no tiene movimientos.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {pagoAbierto && (
        <PagoModal
          patientId={paciente.id}
          patientName={data.patient.full_name}
          cargos={charges.data?.results ?? []}
          onClose={() => setPagoAbierto(false)}
        />
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
