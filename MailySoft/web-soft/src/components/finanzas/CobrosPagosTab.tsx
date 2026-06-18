import { useState } from 'react'
import { Plus, Loader2, Ban } from 'lucide-react'

import type { PatientLite } from '../../api/pacientes'
import { useCancelCharge, useCharges, useCreateCharge, usePayments, useRegisterPayment } from '../../hooks/finanzas'
import { can, type Role } from '../../auth/permisos'
import { formatMoney, formatDateTime } from '../../lib/format'
import PatientPicker from './PatientPicker'

interface Props {
  role: Role
}

const STATUS_BADGE: Record<string, string> = {
  pending: 'badge-warning',
  partial: 'badge-info',
  paid: 'badge-success',
  cancelled: 'badge-neutral',
}

export default function CobrosPagosTab({ role }: Props) {
  const [patient, setPatient] = useState<PatientLite | null>(null)
  const patientId = patient?.id

  const charges = useCharges(patientId ? { patient_id: patientId } : {})
  const payments = usePayments(patientId ? { patient_id: patientId } : {})

  return (
    <div className="space-y-4">
      <div className="glass-card rounded-2xl p-4">
        <label className="label">Paciente</label>
        <PatientPicker value={patient} onChange={setPatient} />
        {!patient && (
          <p className="text-xs mt-2" style={{ color: '#9A958C' }}>
            Selecciona un paciente para ver y registrar sus cargos y pagos.
          </p>
        )}
      </div>

      {patient && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <ChargesPanel role={role} patient={patient} charges={charges} />
          <PaymentsPanel role={role} patient={patient} charges={charges} payments={payments} />
        </div>
      )}
    </div>
  )
}

function ChargesPanel({
  role,
  patient,
  charges,
}: {
  role: Role
  patient: PatientLite
  charges: ReturnType<typeof useCharges>
}) {
  const [open, setOpen] = useState(false)
  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const createCharge = useCreateCharge()
  const cancelCharge = useCancelCharge()
  const canCreate = can(role, 'createCharge')

  const submit = () => {
    if (!description || !amount) return
    createCharge.mutate(
      { patient_id: patient.id, description, amount: Number(amount) },
      {
        onSuccess: () => {
          setDescription('')
          setAmount('')
          setOpen(false)
        },
      },
    )
  }

  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>Cargos</h3>
        {canCreate && (
          <button className="btn-ghost" onClick={() => setOpen((v) => !v)}>
            <Plus className="w-4 h-4" /> Nuevo cargo
          </button>
        )}
      </div>

      {open && canCreate && (
        <div className="rounded-xl p-3 mb-3 space-y-2" style={{ background: 'rgba(0,0,0,0.03)' }}>
          <input className="input" placeholder="Descripción" value={description} onChange={(e) => setDescription(e.target.value)} />
          <input className="input" type="number" placeholder="Monto" value={amount} onChange={(e) => setAmount(e.target.value)} />
          {createCharge.isError && (
            <p className="text-xs" style={{ color: '#B91C1C' }}>{(createCharge.error as Error).message}</p>
          )}
          <button className="btn-primary w-full" onClick={submit} disabled={createCharge.isPending}>
            {createCharge.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Guardar cargo'}
          </button>
        </div>
      )}

      {charges.isLoading ? (
        <Loading />
      ) : (
        <div className="overflow-auto max-h-[360px]">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left" style={{ color: '#9A958C' }}>
                <th className="py-1.5 font-medium">Concepto</th>
                <th className="py-1.5 font-medium">Estado</th>
                <th className="py-1.5 font-medium text-right">Saldo</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(charges.data?.results ?? []).map((c) => (
                <tr key={c.id} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                  <td className="py-1.5" style={{ color: '#2A241B' }}>{c.description}</td>
                  <td className="py-1.5">
                    <span className={`badge ${STATUS_BADGE[c.status]}`}>{c.status_display}</span>
                  </td>
                  <td className="py-1.5 text-right font-medium" style={{ color: '#2A241B' }}>
                    {formatMoney(c.balance)}
                  </td>
                  <td className="py-1.5 text-right">
                    {can(role, 'createCharge') && c.status !== 'cancelled' && c.amount_paid === 0 && (
                      <button
                        className="p-1 rounded hover:bg-red-50"
                        title="Cancelar cargo"
                        onClick={() => cancelCharge.mutate(c.id)}
                      >
                        <Ban className="w-3.5 h-3.5" style={{ color: '#B91C1C' }} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(charges.data?.results?.length ?? 0) === 0 && <Empty cols={4} />}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function PaymentsPanel({
  role,
  patient,
  charges,
  payments,
}: {
  role: Role
  patient: PatientLite
  charges: ReturnType<typeof useCharges>
  payments: ReturnType<typeof usePayments>
}) {
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState('')
  const [method, setMethod] = useState('cash')
  const [allocations, setAllocations] = useState<Record<string, string>>({})
  const register = useRegisterPayment()
  const canRegister = can(role, 'registerPayment')

  const outstanding = (charges.data?.results ?? []).filter(
    (c) => c.status === 'pending' || c.status === 'partial',
  )

  const submit = () => {
    if (!amount) return
    const allocs = Object.entries(allocations)
      .filter(([, v]) => Number(v) > 0)
      .map(([charge_id, v]) => ({ charge_id, amount: Number(v) }))
    register.mutate(
      { patient_id: patient.id, amount: Number(amount), method: method as never, allocations: allocs },
      {
        onSuccess: () => {
          setAmount('')
          setAllocations({})
          setOpen(false)
        },
      },
    )
  }

  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>Pagos</h3>
        {canRegister && (
          <button className="btn-ghost" onClick={() => setOpen((v) => !v)}>
            <Plus className="w-4 h-4" /> Registrar pago
          </button>
        )}
      </div>

      {open && canRegister && (
        <div className="rounded-xl p-3 mb-3 space-y-2" style={{ background: 'rgba(0,0,0,0.03)' }}>
          <div className="flex gap-2">
            <input className="input" type="number" placeholder="Monto" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <select className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="cash">Efectivo</option>
              <option value="card">Tarjeta</option>
              <option value="transfer">Transferencia</option>
              <option value="other">Otro</option>
            </select>
          </div>

          {outstanding.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium" style={{ color: '#7A756C' }}>Aplicar a cargos (opcional):</p>
              {outstanding.map((c) => (
                <div key={c.id} className="flex items-center gap-2">
                  <span className="flex-1 text-xs truncate" style={{ color: '#2A241B' }}>
                    {c.description} · {formatMoney(c.balance)}
                  </span>
                  <input
                    className="input w-24 py-1"
                    type="number"
                    placeholder="0"
                    value={allocations[c.id] ?? ''}
                    onChange={(e) => setAllocations((prev) => ({ ...prev, [c.id]: e.target.value }))}
                  />
                </div>
              ))}
            </div>
          )}

          {register.isError && (
            <p className="text-xs" style={{ color: '#B91C1C' }}>{(register.error as Error).message}</p>
          )}
          <button className="btn-primary w-full" onClick={submit} disabled={register.isPending}>
            {register.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Registrar pago'}
          </button>
        </div>
      )}

      {payments.isLoading ? (
        <Loading />
      ) : (
        <div className="overflow-auto max-h-[360px]">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left" style={{ color: '#9A958C' }}>
                <th className="py-1.5 font-medium">Fecha</th>
                <th className="py-1.5 font-medium">Método</th>
                <th className="py-1.5 font-medium text-right">Monto</th>
              </tr>
            </thead>
            <tbody>
              {(payments.data?.results ?? []).map((p) => (
                <tr key={p.id} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                  <td className="py-1.5" style={{ color: '#7A756C' }}>{formatDateTime(p.received_at)}</td>
                  <td className="py-1.5" style={{ color: '#2A241B' }}>{p.method_display}</td>
                  <td className="py-1.5 text-right font-medium" style={{ color: '#2A241B' }}>{formatMoney(p.amount)}</td>
                </tr>
              ))}
              {(payments.data?.results?.length ?? 0) === 0 && <Empty cols={3} />}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Loading() {
  return (
    <div className="flex items-center justify-center py-10" style={{ color: '#9A958C' }}>
      <Loader2 className="w-5 h-5 animate-spin" />
    </div>
  )
}

function Empty({ cols }: { cols: number }) {
  return (
    <tr>
      <td colSpan={cols} className="py-6 text-center" style={{ color: '#9A958C' }}>
        Sin registros.
      </td>
    </tr>
  )
}
