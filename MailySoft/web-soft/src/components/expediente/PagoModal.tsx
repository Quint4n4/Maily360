/**
 * PagoModal — registrar un pago del paciente desde el expediente (Fase 1).
 *
 * Captura monto, método y referencia, y permite asignar el pago a los cargos
 * pendientes (allocations: [{charge_id, amount}]). Tras pagar, el hook
 * useRegisterPayment invalida statement/charges/payments/dashboard (ya lo hace).
 *
 * Solo UX: el botón que lo abre se muestra si puedeCobrar(role); el backend es la
 * autoridad y responde 403 si el rol/clínica no puede cobrar (se refleja como error).
 */

import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { X, Loader2 } from 'lucide-react'

import type { Charge, PaymentMethod } from '../../api/finanzas'
import { useRegisterPayment } from '../../hooks/finanzas'
import { ApiError } from '../../lib/http'
import { formatMoney } from '../../lib/format'

const ORO = '#C9A227'

const METODOS: { value: PaymentMethod; label: string }[] = [
  { value: 'cash', label: 'Efectivo' },
  { value: 'card', label: 'Tarjeta' },
  { value: 'transfer', label: 'Transferencia' },
  { value: 'other', label: 'Otro' },
]

interface PagoModalProps {
  patientId: string
  patientName: string
  /** Cargos del paciente para ofrecer asignación (se filtran los pendientes/parciales). */
  cargos: Charge[]
  onClose: () => void
  onSuccess?: () => void
}

export default function PagoModal({
  patientId,
  patientName,
  cargos,
  onClose,
  onSuccess,
}: PagoModalProps) {
  const [amount, setAmount] = useState('')
  const [method, setMethod] = useState<PaymentMethod>('cash')
  const [reference, setReference] = useState('')
  const [allocations, setAllocations] = useState<Record<string, string>>({})
  const register = useRegisterPayment()

  const pendientes = useMemo(
    () => cargos.filter(c => c.status === 'pending' || c.status === 'partial'),
    [cargos],
  )

  const asignado = useMemo(
    () =>
      Object.values(allocations).reduce((sum, v) => {
        const n = Number(v)
        return sum + (Number.isFinite(n) && n > 0 ? n : 0)
      }, 0),
    [allocations],
  )

  const montoNum = Number(amount)
  const montoValido = Number.isFinite(montoNum) && montoNum > 0
  const errorMsg = register.isError
    ? register.error instanceof ApiError
      ? typeof register.error.body?.detail === 'string'
        ? register.error.body.detail
        : 'No se pudo registrar el pago.'
      : (register.error as Error).message
    : null

  const submit = () => {
    if (!montoValido) return
    const allocs = Object.entries(allocations)
      .filter(([, v]) => Number(v) > 0)
      .map(([charge_id, v]) => ({ charge_id, amount: Number(v) }))
    register.mutate(
      {
        patient_id: patientId,
        amount: montoNum,
        method,
        reference: reference.trim() || undefined,
        allocations: allocs.length > 0 ? allocs : undefined,
      },
      {
        onSuccess: () => {
          onSuccess?.()
          onClose()
        },
      },
    )
  }

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
      role="dialog"
      aria-modal="true"
    >
      <motion.div
        onClick={e => e.stopPropagation()}
        initial={{ opacity: 0, y: 16, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className="relative w-full max-w-md glass-card rounded-2xl p-5 max-h-[90vh] overflow-y-auto"
      >
        <button
          onClick={onClose}
          aria-label="Cerrar"
          className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors"
        >
          <X className="w-4 h-4 text-gray-600" />
        </button>

        <h3 className="text-lg font-bold" style={{ color: '#2A241B' }}>
          Registrar pago
        </h3>
        <p className="text-sm mb-4" style={{ color: '#7A756C' }}>
          {patientName}
        </p>

        <div className="space-y-3">
          <div>
            <label className="label">Monto</label>
            <input
              className="input"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              placeholder="0.00"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              autoFocus
            />
          </div>

          <div className="flex gap-2">
            <div className="flex-1">
              <label className="label">Método</label>
              <select
                className="input"
                value={method}
                onChange={e => setMethod(e.target.value as PaymentMethod)}
              >
                {METODOS.map(m => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="label">Referencia (opcional)</label>
              <input
                className="input"
                placeholder="Folio / autorización"
                value={reference}
                onChange={e => setReference(e.target.value)}
              />
            </div>
          </div>

          {pendientes.length > 0 && (
            <div className="rounded-xl p-3 space-y-2" style={{ background: 'rgba(0,0,0,0.03)' }}>
              <p className="text-xs font-medium" style={{ color: '#7A756C' }}>
                El pago se aplica solo a los cargos más antiguos. Opcional: repártelo a mano.
              </p>
              {pendientes.map(c => (
                <div key={c.id} className="flex items-center gap-2">
                  <span className="flex-1 text-xs truncate" style={{ color: '#2A241B' }}>
                    {c.description} · {formatMoney(c.balance)}
                  </span>
                  <input
                    className="input w-24 py-1"
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.01"
                    placeholder="0"
                    value={allocations[c.id] ?? ''}
                    onChange={e =>
                      setAllocations(prev => ({ ...prev, [c.id]: e.target.value }))
                    }
                  />
                </div>
              ))}
              {asignado > 0 && (
                <p className="text-[11px] text-right" style={{ color: '#7A756C' }}>
                  Asignado: {formatMoney(asignado)}
                  {montoValido && asignado > montoNum && (
                    <span style={{ color: '#B91C1C' }}> · supera el monto</span>
                  )}
                </p>
              )}
            </div>
          )}

          {errorMsg && (
            <p className="text-xs" style={{ color: '#B91C1C' }}>
              {errorMsg}
            </p>
          )}

          <button
            className="btn-primary w-full justify-center"
            onClick={submit}
            disabled={!montoValido || register.isPending || (montoValido && asignado > montoNum)}
            style={{ background: ORO }}
          >
            {register.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              'Registrar pago'
            )}
          </button>
        </div>
      </motion.div>
    </div>
  )
}
