import { useState } from 'react'
import { X, CreditCard, Loader2, AlertCircle } from 'lucide-react'
import { useSetClinicaSuscripcion } from '../../hooks/plataforma'
import { useAviso } from '../common/DialogProvider'
import { ApiError } from '../../lib/http'
import { toDayKey } from '../../lib/fecha'
import type { BillingCycle, PlanPlataforma, SuscripcionRow } from '../../types/plataforma'

interface Props {
  /** Clínica a la que se le asigna/cambia el plan. */
  row: SuscripcionRow
  /** Catálogo de planes (se filtran los activos). */
  planes: PlanPlataforma[]
  onClose: () => void
}

const INPUT = 'w-full rounded-xl px-3.5 py-2.5 text-base sm:text-sm text-gray-800 outline-none transition-all'
const INPUT_STYLE = { background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }
const LABEL = 'block text-xs font-semibold mb-1.5'

/** Convierte el error de la API en un texto legible. */
function textoError(err: unknown): string {
  if (err instanceof ApiError && err.body) {
    if (err.body.detail) return String(err.body.detail)
    const campos = Object.entries(err.body)
      .filter(([k]) => k !== 'detail')
      .map(([, v]) => (Array.isArray(v) ? v.join(' ') : String(v)))
    if (campos.length) return campos.join(' ')
  }
  return 'No se pudo guardar la suscripción. Revisa los datos e intenta de nuevo.'
}

/** Modal para asignar o cambiar el plan de una clínica (el padre lo monta solo cuando hay fila). */
export default function AsignarPlanModal({ row, planes, onClose }: Props) {
  const guardar = useSetClinicaSuscripcion()
  const aviso = useAviso()
  const activos = planes.filter(p => p.is_active).sort((a, b) => a.order - b.order)

  const [planId, setPlanId] = useState(row.plan_id ?? '')
  const [ciclo, setCiclo] = useState<BillingCycle>(row.billing_cycle ?? 'monthly')
  const [fechaFin, setFechaFin] = useState(row.current_period_end?.slice(0, 10) ?? '')
  const [error, setError] = useState<string | null>(null)

  const hoy = toDayKey(new Date())

  const enviar = async () => {
    setError(null)
    if (!planId) {
      setError('Elige un plan.')
      return
    }
    if (!fechaFin) {
      setError('Indica la fecha de fin del periodo.')
      return
    }
    if (fechaFin <= hoy) {
      setError('La fecha de fin del periodo debe ser posterior a hoy.')
      return
    }
    try {
      const res = await guardar.mutateAsync({
        tenantId: row.tenant_id,
        input: { plan_id: planId, billing_cycle: ciclo, current_period_end: fechaFin },
      })
      onClose()
      void aviso({
        tipo: 'exito',
        titulo: 'Suscripción guardada',
        mensaje: `Plan ${res.plan_name ?? ''} asignado a ${res.tenant_name}.`,
      })
    } catch (e) {
      setError(textoError(e))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(30,22,8,0.45)', backdropFilter: 'blur(4px)' }}>
      <div className="relative w-full max-w-md rounded-3xl p-7"
        style={{ background: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(22px)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 24px 60px rgba(60,42,12,0.3)' }}>
        <button onClick={onClose} className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors">
          <X className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-3 mb-5">
          <div className="w-11 h-11 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(201,162,39,0.16)' }}>
            <CreditCard className="w-6 h-6" style={{ color: '#C9A227' }} />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900">{row.plan_id ? 'Cambiar plan' : 'Asignar plan'}</h2>
            <p className="text-sm text-gray-500">{row.tenant_name}</p>
          </div>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-xl px-3.5 py-2.5 mb-4" style={{ background: 'rgba(192,57,43,0.1)', border: '1px solid rgba(192,57,43,0.25)' }}>
            <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div className="space-y-3.5">
          <div>
            <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="susc-plan">Plan</label>
            <select id="susc-plan" className={INPUT} style={INPUT_STYLE} value={planId} onChange={e => setPlanId(e.target.value)}>
              <option value="">Elige un plan…</option>
              {activos.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="susc-ciclo">Ciclo de cobro</label>
            <select id="susc-ciclo" className={INPUT} style={INPUT_STYLE} value={ciclo} onChange={e => setCiclo(e.target.value as BillingCycle)}>
              <option value="monthly">Mensual</option>
              <option value="annual">Anual</option>
            </select>
          </div>

          <div>
            <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="susc-fin">Fin del periodo actual</label>
            <input id="susc-fin" type="date" className={INPUT} style={INPUT_STYLE} min={hoy}
              value={fechaFin} onChange={e => setFechaFin(e.target.value)} />
            <p className="text-[11px] text-gray-400 mt-1">Al vencer solo se avisa; la suspensión es manual.</p>
          </div>
        </div>

        <button onClick={enviar} disabled={guardar.isPending}
          className="w-full mt-6 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-60" style={{ background: '#C9A227' }}>
          {guardar.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : <>Guardar suscripción</>}
        </button>
      </div>
    </div>
  )
}
