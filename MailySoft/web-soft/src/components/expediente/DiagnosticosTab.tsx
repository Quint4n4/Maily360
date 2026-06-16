/**
 * DiagnosticosTab — pestaña Diagnósticos.
 * Lista (activos + resueltos) + alta + botón "Resolver" (baja lógica).
 */

import { useState } from 'react'
import { ClipboardCheck, Plus, Loader2, CheckCircle2, X } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Diagnosis, DiagnosisInput, DiagnosisKind } from '../../types/expediente'
import { useCreateDiagnosis, useDiagnoses, useResolveDiagnosis } from '../../hooks/expediente'
import { formatFechaCorta } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import { Card, Cargando, ErroresAlerta, Vacio, DIAGNOSIS_KIND_OPTIONS } from './ui'

interface DiagnosticosTabProps {
  paciente: PatientOut
  /** owner/admin/doctor pueden crear y resolver. */
  puedeEditar: boolean
}

export default function DiagnosticosTab({ paciente, puedeEditar }: DiagnosticosTabProps) {
  const { data: diagsData, isLoading, isError } = useDiagnoses(paciente.id)
  const crear = useCreateDiagnosis(paciente.id)
  const resolver = useResolveDiagnosis(paciente.id)
  const [abierto, setAbierto] = useState(false)
  const [form, setForm] = useState<DiagnosisInput>({ description: '', cie_code: '', kind: 'presuntivo' })
  const [errores, setErrores] = useState<string[]>([])

  const diags: Diagnosis[] = diagsData?.results ?? []

  const guardar = async () => {
    setErrores([])
    if (!form.description.trim()) { setErrores(['La descripción es obligatoria.']); return }
    try {
      await crear.mutateAsync({
        description: form.description.trim(),
        cie_code: form.cie_code?.trim() || undefined,
        kind: form.kind,
      })
      setForm({ description: '', cie_code: '', kind: 'presuntivo' })
      setAbierto(false)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {puedeEditar && (
        <Card
          title="Nuevo diagnóstico" icon={Plus}
          action={
            <button type="button" onClick={() => setAbierto(a => !a)} className="text-xs font-semibold text-amber-700 hover:text-amber-800">
              {abierto ? 'Ocultar' : 'Agregar'}
            </button>
          }
        >
          {abierto ? (
            <div className="space-y-3">
              <ErroresAlerta errores={errores} />
              <div className="grid gap-3" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
                <div>
                  <label className="label">Descripción</label>
                  <input className="input" value={form.description}
                    onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                    placeholder="Ej. Diabetes mellitus tipo 2" />
                </div>
                <div>
                  <label className="label">CIE-10 (opcional)</label>
                  <input className="input" value={form.cie_code}
                    onChange={e => setForm(f => ({ ...f, cie_code: e.target.value }))}
                    placeholder="Ej. E11" />
                </div>
                <div>
                  <label className="label">Tipo</label>
                  <select className="input" value={form.kind}
                    onChange={e => setForm(f => ({ ...f, kind: e.target.value as DiagnosisKind }))}>
                    {DIAGNOSIS_KIND_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => { setAbierto(false); setErrores([]) }} className="btn-secondary px-4 py-2">Cancelar</button>
                <button type="button" onClick={guardar} disabled={crear.isPending}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                  style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                  {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : <><Plus className="w-4 h-4" /> Registrar diagnóstico</>}
                </button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">Registra diagnósticos presuntivos o definitivos. Se pueden resolver más tarde.</p>
          )}
        </Card>
      )}

      <Card title="Diagnósticos" icon={ClipboardCheck}>
        {isLoading ? (
          <Cargando texto="Cargando diagnósticos…" />
        ) : isError ? (
          <p className="text-sm text-red-600 text-center py-6">No se pudieron cargar los diagnósticos.</p>
        ) : diags.length === 0 ? (
          <Vacio texto="Aún no hay diagnósticos registrados." />
        ) : (
          <div className="space-y-2">
            {diags.map(d => {
              const resuelto = d.status === 'resuelto'
              return (
                <div key={d.id} className="flex items-center justify-between rounded-xl px-4 py-3 bg-white/60"
                  style={{ opacity: resuelto ? 0.65 : 1 }}>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className={`text-sm font-medium text-gray-800 ${resuelto ? 'line-through' : ''}`}>
                        {d.description}
                      </p>
                      {d.cie_code && (
                        <span className="text-[11px] rounded px-1.5 py-0.5" style={{ background: 'rgba(201,162,39,0.12)', color: '#9A7B1E' }}>
                          {d.cie_code}
                        </span>
                      )}
                      <span className="badge" style={{ background: '#FBF1D9', color: '#9A7B1E' }}>{d.kind_display}</span>
                      <span className="badge" style={resuelto
                        ? { background: '#DCF3E6', color: '#1F6E47' }
                        : { background: '#E7F6EE', color: '#2E7D5B' }}>
                        {d.status_display}
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 mt-0.5">{formatFechaCorta(d.created_at)}</p>
                  </div>
                  {puedeEditar && !resuelto && (
                    <button type="button" onClick={() => resolver.mutate(d.id)} disabled={resolver.isPending}
                      className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 hover:text-emerald-800 shrink-0 ml-2 disabled:opacity-50">
                      {resolver.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />} Resolver
                    </button>
                  )}
                  {resuelto && <X className="w-4 h-4 text-gray-300 shrink-0 ml-2" />}
                </div>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}
