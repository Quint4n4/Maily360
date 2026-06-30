import { useState } from 'react'
import { Plus, Loader2, Send, Check, Trash2, FileDown, Info } from 'lucide-react'

import type { PatientLite } from '../../api/pacientes'
import type { QuoteItemInput, ServiceConcept } from '../../api/finanzas'
import { fetchQuotePdfBlob } from '../../api/finanzas'
import { errorMsg } from '../../lib/apiErrors'
import {
  useAcceptQuote,
  useCreateQuote,
  useQuotes,
  useSendQuote,
  useConcepts,
} from '../../hooks/finanzas'
import { can, type Role } from '../../auth/permisos'
import { formatMoney, formatDate } from '../../lib/format'
import PatientPicker from './PatientPicker'
import VisorPdf from '../VisorPdf'

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

/** Renglón en edición. Los montos se guardan como string (input controlado) y se
 *  convierten a number SOLO al enviar al backend. `concept_id` ata el renglón a un
 *  servicio del catálogo (opcional: el usuario puede escribir libre). */
interface DraftItem {
  concept_id: string | null
  description: string
  quantity: string
  unit_price: string
  discount: string
}

const emptyItem = (): DraftItem => ({
  concept_id: null,
  description: '',
  quantity: '1',
  unit_price: '',
  discount: '0',
})

/** Total en vivo de un renglón: cantidad * precio - descuento (nunca < 0). */
function lineTotal(it: DraftItem): number {
  const raw = Number(it.quantity || 0) * Number(it.unit_price || 0) - Number(it.discount || 0)
  return raw > 0 ? raw : 0
}

export default function CotizacionesTab({ role }: Props) {
  const [patient, setPatient] = useState<PatientLite | null>(null)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<DraftItem[]>([emptyItem()])
  /** Cotización cuyo PDF se previsualiza en el visor (null = visor cerrado). */
  const [pdfQuoteId, setPdfQuoteId] = useState<string | null>(null)

  const quotes = useQuotes(patient ? { patient_id: patient.id } : {})
  const conceptsQuery = useConcepts()
  const createQuote = useCreateQuote()
  const sendQuote = useSendQuote()
  const acceptQuote = useAcceptQuote()
  const canCreate = can(role, 'createQuote')

  const concepts: ServiceConcept[] = conceptsQuery.data?.results ?? []

  const total = items.reduce((acc, it) => acc + lineTotal(it), 0)

  const setItem = (i: number, patch: Partial<DraftItem>) =>
    setItems((p) => p.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  /** Elegir un servicio del catálogo: rellena descripción + precio (ambos editables). */
  const pickConcept = (i: number, conceptId: string) => {
    if (!conceptId) {
      setItem(i, { concept_id: null })
      return
    }
    const c = concepts.find((x) => x.id === conceptId)
    if (!c) return
    setItem(i, {
      concept_id: c.id,
      description: c.name,
      unit_price: String(c.base_price),
    })
  }

  const resetForm = () => {
    setItems([emptyItem()])
    setOpen(false)
  }

  const submit = () => {
    if (!patient) return
    const payloadItems: QuoteItemInput[] = items
      .filter((it) => it.description.trim() && it.unit_price !== '')
      .map((it) => ({
        concept_id: it.concept_id,
        description: it.description.trim(),
        quantity: Number(it.quantity || 1),
        unit_price: Number(it.unit_price),
        discount: Number(it.discount || 0),
      }))
    if (payloadItems.length === 0) return
    createQuote.mutate(
      { patient_id: patient.id, items: payloadItems },
      { onSuccess: resetForm },
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
            <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>
              Cotizaciones
            </h3>
            {canCreate && (
              <button className="btn-ghost" onClick={() => setOpen((v) => !v)}>
                <Plus className="w-4 h-4" /> Nueva cotización
              </button>
            )}
          </div>

          {open && canCreate && (
            <div className="rounded-xl p-3 mb-3 space-y-3" style={{ background: 'rgba(0,0,0,0.03)' }}>
              {/* Encabezados de columnas (md+) */}
              <div className="hidden md:grid gap-2 px-1 text-[11px] font-medium" style={{ gridTemplateColumns: '1.3fr 2fr 64px 110px 96px 90px 28px', color: '#9A958C' }}>
                <span>Servicio</span>
                <span>Descripción</span>
                <span className="text-right">Cant.</span>
                <span className="text-right">Precio</span>
                <span className="text-right">Desc.</span>
                <span className="text-right">Importe</span>
                <span />
              </div>

              {items.map((it, i) => (
                <div
                  key={i}
                  className="grid gap-2 items-center md:grid-cols-[1.3fr_2fr_64px_110px_96px_90px_28px] grid-cols-2"
                >
                  {/* Selector de servicio del catálogo */}
                  <select
                    className="input"
                    value={it.concept_id ?? ''}
                    onChange={(e) => pickConcept(i, e.target.value)}
                    disabled={conceptsQuery.isLoading}
                  >
                    <option value="">Manual…</option>
                    {concepts.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  <input
                    className="input"
                    placeholder="Descripción"
                    maxLength={255}
                    value={it.description}
                    onChange={(e) => setItem(i, { description: e.target.value })}
                  />
                  <input
                    className="input text-right"
                    type="number"
                    min={1}
                    placeholder="Cant."
                    value={it.quantity}
                    onChange={(e) => setItem(i, { quantity: e.target.value })}
                  />
                  <input
                    className="input text-right"
                    type="number"
                    min={0}
                    step="0.01"
                    placeholder="Precio"
                    value={it.unit_price}
                    onChange={(e) => setItem(i, { unit_price: e.target.value })}
                  />
                  <input
                    className="input text-right"
                    type="number"
                    min={0}
                    step="0.01"
                    max={Number(it.quantity || 0) * Number(it.unit_price || 0)}
                    placeholder="Desc."
                    value={it.discount}
                    onChange={(e) => setItem(i, { discount: e.target.value })}
                  />
                  <span className="text-sm text-right font-medium" style={{ color: '#2A241B' }}>
                    {formatMoney(lineTotal(it))}
                  </span>
                  {items.length > 1 ? (
                    <button
                      className="p-1 rounded hover:bg-red-50 justify-self-center"
                      onClick={() => setItems((p) => p.filter((_, j) => j !== i))}
                      title="Quitar renglón"
                    >
                      <Trash2 className="w-4 h-4" style={{ color: '#B91C1C' }} />
                    </button>
                  ) : (
                    <span />
                  )}
                </div>
              ))}

              <button className="btn-ghost" onClick={() => setItems((p) => [...p, emptyItem()])}>
                <Plus className="w-3.5 h-3.5" /> Agregar línea
              </button>

              <div className="flex items-center justify-between pt-1 border-t" style={{ borderColor: 'rgba(0,0,0,0.06)' }}>
                <span className="text-sm font-semibold" style={{ color: '#2A241B' }}>
                  Total: {formatMoney(total)}
                </span>
                <button className="btn-primary" onClick={submit} disabled={createQuote.isPending}>
                  {createQuote.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    'Crear cotización'
                  )}
                </button>
              </div>
              {createQuote.isError && (
                <p className="text-xs" style={{ color: '#B91C1C' }}>
                  {errorMsg(createQuote.error)}
                </p>
              )}
            </div>
          )}

          {/* Aviso: el envío al paciente es manual (no automatizado). */}
          <div className="flex items-start gap-2 rounded-lg px-3 py-2 mb-3 text-xs" style={{ background: 'rgba(59,130,246,0.07)', color: '#3A6EA5' }}>
            <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span>
              Descarga el PDF y compártelo con el paciente por tu medio habitual.
              «Marcar como enviada» solo registra que ya la entregaste — no envía nada automáticamente.
            </span>
          </div>

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
                      <td className="py-1.5" style={{ color: '#7A756C' }}>
                        {formatDate(q.created_at)}
                      </td>
                      <td className="py-1.5">
                        <span className={`badge ${STATUS_BADGE[q.status]}`}>{q.status_display}</span>
                      </td>
                      <td className="py-1.5 text-right font-medium" style={{ color: '#2A241B' }}>
                        {formatMoney(q.total)}
                      </td>
                      <td className="py-1.5 text-right whitespace-nowrap">
                        <button
                          className="btn-ghost px-2 py-1"
                          onClick={() => setPdfQuoteId(q.id)}
                          title="Ver PDF"
                        >
                          <FileDown className="w-3.5 h-3.5" />
                        </button>
                        {canCreate && q.status === 'draft' && (
                          <button
                            className="btn-ghost px-2 py-1"
                            onClick={() => sendQuote.mutate(q.id)}
                            disabled={sendQuote.isPending}
                            title="Marcar como enviada"
                          >
                            <Send className="w-3.5 h-3.5" />
                          </button>
                        )}
                        {canCreate && (q.status === 'draft' || q.status === 'sent') && (
                          <button
                            className="btn-ghost px-2 py-1"
                            onClick={() => acceptQuote.mutate(q.id)}
                            disabled={acceptQuote.isPending}
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

      {pdfQuoteId && (
        <VisorPdf
          titulo="Cotización"
          nombreArchivo={`cotizacion-${pdfQuoteId}.pdf`}
          cargar={() => fetchQuotePdfBlob(pdfQuoteId)}
          onClose={() => setPdfQuoteId(null)}
        />
      )}
    </div>
  )
}
