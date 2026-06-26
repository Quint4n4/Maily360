/**
 * EstadoCuentaExpediente — pestaña "Estado de cuenta" DENTRO del expediente
 * del paciente (Fase 1 del plan finanzas-pacientes-unificacion).
 *
 * Dos vistas:
 *  - "Por cargo" (default): cada servicio con cobrado / pagado / saldo y su
 *    estado (Pagado/Parcial/Pendiente). Responde "¿qué debe de qué?".
 *  - "Movimientos": el ledger cronológico con saldo corrido (como estado de banco).
 * Arriba: totales (cobrado / pagado / saldo) + botón "Registrar pago" (si puedeCobrar).
 *
 * El gating de visibilidad lo decide el llamador (ExpedienteDrawer) con
 * puedeVerEstadoCuenta; aquí solo controlamos el botón de cobro.
 */

import { useState, type ReactNode } from 'react'
import { Loader2, CreditCard, AlertTriangle } from 'lucide-react'

import type { PatientOut } from '../../types/paciente'
import type { ChargeStatus } from '../../api/finanzas'
import { useStatement, useCharges } from '../../hooks/finanzas'
import { formatMoney, formatDate } from '../../lib/format'
import { ApiError } from '../../lib/http'
import PagoModal from './PagoModal'

const ORO = '#C9A227'

/** Color e intención visual por estado del cargo. */
const ESTADO_COLOR: Record<ChargeStatus, string> = {
  paid: '#0F766E', // verde — pagado
  partial: '#B45309', // ámbar — abonó pero falta
  pending: '#B91C1C', // rojo — sin pagar
  cancelled: '#9A958C', // gris — cancelado
}

interface Props {
  paciente: PatientOut
  /** Si el rol puede cobrar (caja): muestra el botón "Registrar pago". */
  puedeCobrar: boolean
}

type Vista = 'cargos' | 'movimientos'

export default function EstadoCuentaExpediente({ paciente, puedeCobrar }: Props) {
  const statement = useStatement(paciente.id)
  // Cargos del paciente: alimentan la vista "Por cargo" y la asignación del PagoModal.
  const charges = useCharges({ patient_id: paciente.id })
  const [pagoAbierto, setPagoAbierto] = useState(false)
  const [vista, setVista] = useState<Vista>('cargos')

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
  const cargos = charges.data?.results ?? []
  // Solo importa cuánto debe: el backend ya no permite saldos a favor.
  const deuda = Math.max(0, data.balance)

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

      {/* Métrica única: cuánto debe */}
      <div
        className="inline-flex items-baseline gap-3 rounded-xl px-5 py-3"
        style={{ background: `${ORO}10`, border: `1px solid ${ORO}22` }}
      >
        <span className="text-[11px] uppercase tracking-wide" style={{ color: '#7A756C' }}>
          Saldo por cobrar
        </span>
        <span className="text-2xl font-bold" style={{ color: deuda > 0 ? ORO : '#0F766E' }}>
          {deuda > 0 ? formatMoney(deuda) : 'Al corriente'}
        </span>
      </div>

      {/* Selector de vista */}
      <div className="inline-flex rounded-xl p-1 gap-1" style={{ background: 'rgba(0,0,0,0.04)' }}>
        <VistaBtn activa={vista === 'cargos'} onClick={() => setVista('cargos')}>Por cargo</VistaBtn>
        <VistaBtn activa={vista === 'movimientos'} onClick={() => setVista('movimientos')}>Movimientos</VistaBtn>
      </div>

      {vista === 'cargos' ? (
        /* ---- Vista POR CARGO: qué se debe de qué ---- */
        <div
          className="rounded-2xl p-4 overflow-auto"
          style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(201,162,39,0.18)' }}
        >
          {charges.isLoading ? (
            <div className="flex items-center justify-center py-8" style={{ color: '#9A958C' }}>
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left" style={{ color: '#9A958C' }}>
                  <th className="py-2 font-medium">Servicio</th>
                  <th className="py-2 font-medium">Fecha</th>
                  <th className="py-2 font-medium text-right">Cobrado</th>
                  <th className="py-2 font-medium text-right">Pagado</th>
                  <th className="py-2 font-medium text-right">Saldo</th>
                  <th className="py-2 font-medium text-center">Estado</th>
                </tr>
              </thead>
              <tbody>
                {cargos.map(c => (
                  <tr key={c.id} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                    <td className="py-2" style={{ color: '#2A241B' }}>{c.description}</td>
                    <td className="py-2" style={{ color: '#7A756C' }}>{formatDate(c.issued_at)}</td>
                    <td className="py-2 text-right" style={{ color: '#2A241B' }}>{formatMoney(c.amount)}</td>
                    <td className="py-2 text-right" style={{ color: '#0F766E' }}>{formatMoney(c.amount_paid)}</td>
                    <td className="py-2 text-right font-medium" style={{ color: '#2A241B' }}>{formatMoney(c.balance)}</td>
                    <td className="py-2 text-center">
                      <EstadoBadge status={c.status} label={c.status_display} />
                    </td>
                  </tr>
                ))}
                {cargos.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-8 text-center" style={{ color: '#9A958C' }}>
                      Este paciente no tiene cargos.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        /* ---- Vista MOVIMIENTOS: ledger cronológico con saldo corrido ---- */
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
      )}

      {pagoAbierto && (
        <PagoModal
          patientId={paciente.id}
          patientName={data.patient.full_name}
          cargos={cargos}
          onClose={() => setPagoAbierto(false)}
        />
      )}
    </div>
  )
}

function VistaBtn({
  activa,
  onClick,
  children,
}: {
  activa: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors"
      style={
        activa
          ? { background: '#fff', color: '#2A241B', boxShadow: '0 1px 3px rgba(0,0,0,0.08)' }
          : { background: 'transparent', color: '#7A756C' }
      }
    >
      {children}
    </button>
  )
}

function EstadoBadge({ status, label }: { status: ChargeStatus; label: string }) {
  const color = ESTADO_COLOR[status] ?? '#9A958C'
  return (
    <span
      className="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold"
      style={{ background: `${color}1A`, color }}
    >
      {label}
    </span>
  )
}
