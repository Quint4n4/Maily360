import { useState } from 'react'
import { Plus, Loader2, Send, Check, Trash2 } from 'lucide-react'

import type { PatientLite } from '../../api/pacientes'
import type { QuoteItemInput } from '../../api/finanzas'
import { useAcceptQuote, useCreateQuote, useQuotes, useSendQuote } from '../../hooks/finanzas'
import { can, type Role } from '../../auth/permisos'
import { formatMoney, formatDate } from '../../lib/format'
import PatientPicker from './PatientPicker'

interface Props {
  role: Role
}

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-neutral',
  sent: 'badge-info',
  accepted: 'badge-success',
  rejected: 'badge-danger',
  expired: 'badge-warning',
}

interface DraftItem {
  description: string
  quantity: string
  unit_price: string
}

export default function CotizacionesTab({ role }: Props) {
  const [patient, setPatient] = useState<PatientLite | null>(null)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<DraftItem[]>([{ description: '', quantity: '1', unit_price: '' }])

  const quotes = useQuotes(patient ? { patient_id: patient.id } : {})
  const createQuote = useCreateQuote()
  const sendQuote = useSendQuote()
  const acceptQuote = useAcceptQuote()
  const canCreate = can(role, 'createQuote')

  const total = items.reduce((acc, it) => acc + Number(it.quantity || 0) * Number(it.unit_price || 0), 0)

  const submit = () => {
    if (!patient) return
    const payloadItems: QuoteItemInput[] = items
      .filter((it) => it.description && it.unit_price)
      .map((it) => ({
        description: it.description,
        quantity: Number(it.quantity || 1),
        unit_price: Number(it.unit_price),
      }))
    if (payloadItems.length === 0) return
    createQuote.mutate(
      { patient_id: patient.id, items: payloadItems },
      {
        onSuccess: () => {
          setItems([{ description: '', quantity: '1', unit_price: '' }])
          setOpen(false)
        },
      },
    )
  }

  return (
    <div className="space-y-4">
      <div className="glass-card rounded-2xl p-4">
        <label className="label">Paciente</label>
        <PatientPicker value={patient} onChange={setPatient} />
      </div>

      {patient && (
        <div className="glass-card rounded-2xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>Cotizaciones</h3>
            {canCreate && (
              <button className="btn-ghost" onClick={() => setOpen((v) => !v)}>
                <Plus className="w-4 h-4" /> Nueva cotización
              </button>
            )}
          </div>

          {open && canCreate && (
            <div className="rounded-xl p-3 mb-3 space-y-2" style={{ background: 'rgba(0,0,0,0.03)' }}>
              {items.map((it, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    className="input flex-1"
                    placeholder="Descripción"
                    value={it.description}
                    onChange={(e) => setItems((p) => p.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))}
                  />
                  <input
                    className="input w-16"
                    type="number"
                    placeholder="Cant."
                    value={it.quantity}
                    onChange={(e) => setItems((p) => p.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))}
                  />
                  <input
                    className="input w-28"
                    type="number"
                    placeholder="Precio"
                    value={it.unit_price}
                    onChange={(e) => setItems((p) => p.map((x, j) => (j === i ? { ...x, unit_price: e.target.value } : x)))}
                  />
                  {items.length > 1 && (
                    <button
                      className="p-1 rounded hover:bg-red-50"
                      onClick={() => setItems((p) => p.filter((_, j) => j !== i))}
                    >
                      <Trash2 className="w-4 h-4" style={{ color: '#B91C1C' }} />
                    </button>
                  )}
                </div>
              ))}
              <button
                className="btn-ghost"
                onClick={() => setItems((p) => [...p, { description: '', quantity: '1', unit_price: '' }])}
              >
                <Plus className="w-3.5 h-3.5" /> Agregar línea
              </button>

              <div className="flex items-center justify-between pt-1">
                <span className="text-sm font-semibold" style={{ color: '#2A241B' }}>
                  Total: {formatMoney(total)}
                </span>
                <button className="btn-primary" onClick={submit} disabled={createQuote.isPending}>
                  {createQuote.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Crear cotización'}
                </button>
              </div>
              {createQuote.isError && (
                <p className="text-xs" style={{ color: '#B91C1C' }}>{(createQuote.error as Error).message}</p>
              )}
            </div>
          )}

          {quotes.isLoading ? (
            <div className="flex items-center justify-center py-10" style={{ color: '#9A958C' }}>
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : (
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left" style={{ color: '#9A958C' }}>
                    <th className="py-1.5 font-medium">Fecha</th>
                    <th className="py-1.5 font-medium">Estado</th>
                    <th className="py-1.5 font-medium text-right">Total</th>
                    <th className="py-1.5 font-medium text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {(quotes.data?.results ?? []).map((q) => (
                    <tr key={q.id} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                      <td className="py-1.5" style={{ color: '#7A756C' }}>{formatDate(q.created_at)}</td>
                      <td className="py-1.5">
                        <span className={`badge ${STATUS_BADGE[q.status]}`}>{q.status_display}</span>
                      </td>
                      <td className="py-1.5 text-right font-medium" style={{ color: '#2A241B' }}>{formatMoney(q.total)}</td>
                      <td className="py-1.5 text-right">
                        {canCreate && q.status === 'draft' && (
                          <button className="btn-ghost px-2 py-1" onClick={() => sendQuote.mutate(q.id)} title="Enviar">
                            <Send className="w-3.5 h-3.5" />
                          </button>
                        )}
                        {canCreate && (q.status === 'draft' || q.status === 'sent') && (
                          <button
                            className="btn-ghost px-2 py-1"
                            onClick={() => acceptQuote.mutate(q.id)}
                            title="Aceptar (genera cargos)"
                          >
                            <Check className="w-3.5 h-3.5" style={{ color: '#16A34A' }} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {(quotes.data?.results?.length ?? 0) === 0 && (
                    <tr>
                      <td colSpan={4} className="py-6 text-center" style={{ color: '#9A958C' }}>
                        Sin cotizaciones.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
