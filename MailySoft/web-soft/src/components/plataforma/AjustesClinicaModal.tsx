/**
 * AjustesClinicaModal — ajustes a la medida de UNA clínica (override del plan).
 *
 * Es lo que hace vendible el caso dental: el super-admin enciende un módulo
 * suelto o revoca otro sobre el plan, sin crear un plan nuevo. Trabaja sobre los
 * módulos EFECTIVOS (plan + ajustes ya aplicados) y calcula qué mandar como
 * modules_on / modules_off comparando contra los del plan base.
 */

import { useState } from 'react'
import { X, Loader2, AlertCircle, Info } from 'lucide-react'
import { useSetClinicaEntitlements } from '../../hooks/plataforma'
import { ApiError } from '../../lib/http'
import {
  MODULO_GRUPOS, MODULO_LABEL, dependientesDe, expandirDependencias,
} from '../../lib/modulos'
import type { ModuloId } from '../../lib/modulos'
import type { ClinicaEntitlements } from '../../types/plataforma'

interface Props {
  tenantId: string
  clinicaNombre: string
  entitlements: ClinicaEntitlements
  onClose: () => void
}

function textoError(err: unknown): string {
  if (err instanceof ApiError && err.body) {
    if (err.body.detail) return String(err.body.detail)
    const campos = Object.entries(err.body)
      .filter(([k]) => k !== 'detail')
      .map(([, v]) => (Array.isArray(v) ? v.join(' ') : String(v)))
    if (campos.length) return campos.join(' ')
  }
  return 'No se pudieron guardar los ajustes.'
}

export default function AjustesClinicaModal({ tenantId, clinicaNombre, entitlements, onClose }: Props) {
  const guardar = useSetClinicaEntitlements()
  // Los módulos del PLAN base (efectivos menos lo que ya se concedió por override,
  // más lo que se revocó): así al guardar sabemos qué es on/off respecto al plan.
  const modulosPlan = new Set<ModuloId>(
    entitlements.modules
      .filter(m => !entitlements.override.modules_on.includes(m))
      .concat(entitlements.override.modules_off),
  )

  const [activos, setActivos] = useState<ModuloId[]>(entitlements.modules)
  const [notas, setNotas] = useState(entitlements.override.notes)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState('')

  const set = new Set(activos)
  const alternar = (id: ModuloId) => {
    if (set.has(id)) {
      const arrastrados = dependientesDe(id, activos)
      setActivos(activos.filter(m => m !== id && !arrastrados.includes(m)))
      setAviso(arrastrados.length
        ? `Se apagó también ${arrastrados.map(m => MODULO_LABEL[m]).join(', ')}.`
        : '')
    } else {
      const conDeps = expandirDependencias([...activos, id])
      setActivos(conDeps)
      const nuevos = conDeps.filter(m => !set.has(m) && m !== id)
      setAviso(nuevos.length
        ? `Se encendió también ${nuevos.map(m => MODULO_LABEL[m]).join(', ')}.`
        : '')
    }
  }

  const enviar = async () => {
    setError(null)
    const activosSet = new Set(activos)
    // on = encendido que el plan NO trae; off = apagado que el plan SÍ trae.
    const modules_on = activos.filter(m => !modulosPlan.has(m))
    const modules_off = [...modulosPlan].filter(m => !activosSet.has(m))
    try {
      await guardar.mutateAsync({
        tenantId,
        input: { modules_on, modules_off, notes: notas.trim() },
      })
      onClose()
    } catch (e) {
      setError(textoError(e))
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ background: 'rgba(30,22,8,0.5)', backdropFilter: 'blur(4px)' }}>
      <div className="relative w-full max-w-xl max-h-[90vh] overflow-y-auto rounded-3xl p-7"
        style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(22px)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 24px 60px rgba(60,42,12,0.3)' }}>
        <button onClick={onClose} className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors">
          <X className="w-4 h-4" />
        </button>

        <h2 className="text-lg font-bold text-gray-900">Ajustes a la medida</h2>
        <p className="text-sm text-gray-500 mb-1">{clinicaNombre} · plan {entitlements.plan_name}</p>
        <p className="text-[11px] text-gray-400 mb-5">
          Enciende o apaga módulos sobre el plan sin cambiarlo. Ideal para casos que no caben en un plan fijo.
        </p>

        {error && (
          <div className="flex items-start gap-2 rounded-xl px-3.5 py-2.5 mb-4" style={{ background: 'rgba(192,57,43,0.1)', border: '1px solid rgba(192,57,43,0.25)' }}>
            <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div className="space-y-4">
          {MODULO_GRUPOS.map(grupo => (
            <div key={grupo.titulo}>
              <p className="text-[11px] font-semibold text-gray-500 mb-1.5">{grupo.titulo}</p>
              <div className="grid gap-1.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
                {grupo.modulos.map(id => {
                  const on = set.has(id)
                  const enPlan = modulosPlan.has(id)
                  return (
                    <button key={id} type="button" onClick={() => alternar(id)}
                      className="flex items-center justify-between gap-2 rounded-xl px-3 py-2 text-left transition-colors"
                      style={{ background: on ? 'rgba(201,162,39,0.10)' : 'rgba(0,0,0,0.02)', border: `1px solid ${on ? 'rgba(201,162,39,0.45)' : 'rgba(0,0,0,0.08)'}` }}>
                      <span className="text-sm text-gray-800">{MODULO_LABEL[id]}</span>
                      {on !== enPlan && (
                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full shrink-0"
                          style={on ? { background: '#DCF3E6', color: '#1F6E47' } : { background: '#FDE8E8', color: '#C0392B' }}>
                          {on ? '+extra' : 'quitado'}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        {aviso && (
          <p className="flex items-start gap-1.5 text-[11px] mt-3" style={{ color: '#854F0B' }}>
            <Info className="w-3.5 h-3.5 shrink-0 mt-px" /> {aviso}
          </p>
        )}

        <div className="mt-4">
          <label className="text-xs font-semibold mb-1.5 block" style={{ color: '#9A7B1E' }}>
            Motivo del trato (obligatorio)
          </label>
          <input className="w-full rounded-xl px-3.5 py-2.5 text-sm text-gray-800 outline-none"
            style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }}
            value={notas} onChange={e => setNotas(e.target.value)}
            placeholder="Ej. Clínica dental: no usa recetas" maxLength={2000} />
          <p className="text-[10px] text-gray-400 mt-0.5">Sin el motivo, nadie sabrá si el ajuste sigue vigente al renovar.</p>
        </div>

        <div className="flex gap-2 mt-6">
          <button onClick={onClose} className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-gray-600" style={{ background: 'rgba(0,0,0,0.05)' }}>
            Cancelar
          </button>
          <button onClick={enviar} disabled={guardar.isPending || !notas.trim()}
            className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-50" style={{ background: '#C9A227' }}>
            {guardar.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : 'Guardar ajustes'}
          </button>
        </div>
      </div>
    </div>
  )
}
