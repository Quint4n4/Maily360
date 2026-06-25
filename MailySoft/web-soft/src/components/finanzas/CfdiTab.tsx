import { useState } from 'react'
import { Loader2, FileText, Ban, ExternalLink } from 'lucide-react'

import type { PatientLite } from '../../api/pacientes'
import { useCancelCfdi, useCfdiList, useIssueCfdi, usePayments } from '../../hooks/finanzas'
import { can, type Role } from '../../auth/permisos'
import { formatMoney, formatDateTime } from '../../lib/format'
import PatientPicker from './PatientPicker'

interface Props {
  role: Role
}

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-neutral',
  stamped: 'badge-success',
  cancelled: 'badge-danger',
}

export default function CfdiTab({ role }: Props) {
  const [patient, setPatient] = useState<PatientLite | null>(null)
  const [paymentId, setPaymentId] = useState('')
  const [rfc, setRfc] = useState('')
  const [name, setName] = useState('')
  const [open, setOpen] = useState(false)

  const cfdis = useCfdiList(patient ? { patient_id: patient.id } : {})
  const payments = usePayments(patient ? { patient_id: patient.id } : {})
  const issue = useIssueCfdi()
  const cancel = useCancelCfdi()
  const canIssue = can(role, 'issueCfdi')

  const submit = () => {
    if (!paymentId || !rfc || !name) return
    issue.mutate(
      { payment_id: paymentId, receptor_rfc: rfc, receptor_name: name },
      {
        onSuccess: () => {
          setPaymentId('')
          setRfc('')
          setName('')
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
            <h3 className="text-sm font-semibold" style={{ color: '#2A241B' }}>Comprobantes CFDI 4.0</h3>
            {canIssue && (
              <button className="btn-ghost" onClick={() => setOpen((v) => !v)}>
                <FileText className="w-4 h-4" /> Emitir CFDI
              </button>
            )}
          </div>

          {open && canIssue && (
            <div className="rounded-xl p-3 mb-3 space-y-2" style={{ background: 'rgba(0,0,0,0.03)' }}>
              <select className="input" value={paymentId} onChange={(e) => setPaymentId(e.target.value)}>
                <option value="">Selecciona el pago a timbrar…</option>
                {(payments.data?.results ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {formatDateTime(p.received_at)} · {p.method_display} · {formatMoney(p.amount)}
                  </option>
                ))}
              </select>
              <input className="input" placeholder="RFC del receptor" value={rfc} onChange={(e) => setRfc(e.target.value.toUpperCase())} />
              <input className="input" placeholder="Razón social del receptor" value={name} onChange={(e) => setName(e.target.value)} />
              {issue.isError && (
                <p className="text-xs" style={{ color: '#B91C1C' }}>{(issue.error as Error).message}</p>
              )}
              <button className="btn-primary w-full" onClick={submit} disabled={issue.isPending}>
                {issue.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Timbrar comprobante'}
              </button>
            </div>
          )}

          {cfdis.isLoading ? (
            <div className="flex items-center justify-center py-10" style={{ color: '#9A958C' }}>
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : (
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left" style={{ color: '#9A958C' }}>
                    <th className="py-1.5 font-medium">Folio fiscal</th>
                    <th className="py-1.5 font-medium">Estado</th>
                    <th className="py-1.5 font-medium text-right">Total</th>
                    <th className="py-1.5 font-medium text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {(cfdis.data?.results ?? []).map((c) => (
                    <tr key={c.id} className="border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }}>
                      <td className="py-1.5 font-mono" style={{ color: '#2A241B' }}>
                        {c.uuid_sat ? `${c.uuid_sat.slice(0, 18)}…` : `${c.series}${c.folio ?? ''}`}
                      </td>
                      <td className="py-1.5">
                        <span className={`badge ${STATUS_BADGE[c.status]}`}>{c.status_display}</span>
                      </td>
                      <td className="py-1.5 text-right font-medium" style={{ color: '#2A241B' }}>{formatMoney(c.total)}</td>
                      <td className="py-1.5 text-right flex items-center justify-end gap-1">
                        {c.pdf_url && (
                          <a className="btn-ghost px-2 py-1" href={c.pdf_url} target="_blank" rel="noreferrer" title="PDF">
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                        {canIssue && c.status === 'stamped' && (
                          <button
                            className="btn-ghost px-2 py-1"
                            title="Cancelar CFDI"
                            onClick={() => cancel.mutate({ cfdiId: c.id })}
                          >
                            <Ban className="w-3.5 h-3.5" style={{ color: '#B91C1C' }} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {(cfdis.data?.results?.length ?? 0) === 0 && (
                    <tr>
                      <td colSpan={4} className="py-6 text-center" style={{ color: '#9A958C' }}>
                        Sin comprobantes.
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
