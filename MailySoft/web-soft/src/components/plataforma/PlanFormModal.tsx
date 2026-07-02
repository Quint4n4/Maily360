import { useState } from 'react'
import { X, Layers, Loader2, AlertCircle, Plus, Trash2 } from 'lucide-react'
import { useCreatePlan, useUpdatePlan } from '../../hooks/plataforma'
import { useAviso } from '../common/DialogProvider'
import { ApiError } from '../../lib/http'
import type { PlanFormInput, PlanPlataforma } from '../../types/plataforma'

interface Props {
  /** Plan a editar; si no viene, el modal crea uno nuevo. */
  plan?: PlanPlataforma
  onClose: () => void
}

const INPUT = 'w-full rounded-xl px-3.5 py-2.5 text-base sm:text-sm text-gray-800 outline-none transition-all'
const INPUT_STYLE = { background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }
const LABEL = 'block text-xs font-semibold mb-1.5'

/** Etiquetas legibles por campo para los errores 400 de DRF. */
const CAMPO_LABEL: Record<string, string> = {
  name: 'Nombre',
  price_monthly: 'Precio mensual',
  description: 'Descripción',
  features: 'Características',
  is_featured: 'Popular',
  is_active: 'Activo',
  order: 'Orden',
}

/** Convierte el error de la API (400 de DRF con {campo: ["..."]}) en un texto legible. */
function textoError(err: unknown): string {
  if (err instanceof ApiError && err.body) {
    if (err.body.detail) return String(err.body.detail)
    const campos = Object.entries(err.body)
      .filter(([k]) => k !== 'detail')
      .map(([k, v]) => {
        const msg = Array.isArray(v) ? v.join(' ') : String(v)
        return CAMPO_LABEL[k] ? `${CAMPO_LABEL[k]}: ${msg}` : msg
      })
    if (campos.length) return campos.join(' ')
  }
  return 'No se pudo guardar el plan. Revisa los datos e intenta de nuevo.'
}

/** Modal para crear o editar un plan comercial (solo super_admin; el backend valida). */
export default function PlanFormModal({ plan, onClose }: Props) {
  const crear = useCreatePlan()
  const editar = useUpdatePlan()
  const aviso = useAviso()
  const esEdicion = !!plan
  const guardando = crear.isPending || editar.isPending

  const [nombre, setNombre] = useState(plan?.name ?? '')
  const [precio, setPrecio] = useState(plan?.price_monthly ?? '')
  const [descripcion, setDescripcion] = useState(plan?.description ?? '')
  const [features, setFeatures] = useState<string[]>(plan?.features?.length ? plan.features : [''])
  const [destacado, setDestacado] = useState(plan?.is_featured ?? false)
  const [activo, setActivo] = useState(plan?.is_active ?? true)
  const [orden, setOrden] = useState(String(plan?.order ?? 0))
  const [error, setError] = useState<string | null>(null)

  const setFeature = (i: number, valor: string) =>
    setFeatures(fs => fs.map((f, j) => (j === i ? valor : f)))
  const quitarFeature = (i: number) => setFeatures(fs => fs.filter((_, j) => j !== i))
  const agregarFeature = () => setFeatures(fs => [...fs, ''])

  const enviar = async () => {
    setError(null)
    const name = nombre.trim()
    if (!name) {
      setError('Escribe el nombre del plan.')
      return
    }
    const precioNum = Number(precio)
    if (precio.trim() === '' || !Number.isFinite(precioNum) || precioNum < 0) {
      setError('Indica un precio mensual válido (0 o mayor).')
      return
    }
    const ordenNum = Number(orden)
    const body: PlanFormInput = {
      name,
      price_monthly: precioNum.toFixed(2), // decimal como string, p. ej. "1500.00"
      description: descripcion.trim(),
      features: features.map(f => f.trim()).filter(Boolean),
      is_featured: destacado,
      is_active: activo,
      order: Number.isFinite(ordenNum) ? Math.trunc(ordenNum) : 0,
    }
    try {
      const res = esEdicion
        ? await editar.mutateAsync({ planId: plan.id, input: body })
        : await crear.mutateAsync(body)
      onClose()
      void aviso({
        tipo: 'exito',
        titulo: esEdicion ? 'Plan actualizado' : 'Plan creado',
        mensaje: `El plan ${res.name} se guardó correctamente.`,
      })
    } catch (e) {
      setError(textoError(e))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(30,22,8,0.45)', backdropFilter: 'blur(4px)' }}>
      <div className="relative w-full max-w-md max-h-[90vh] overflow-y-auto rounded-3xl p-7"
        style={{ background: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(22px)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 24px 60px rgba(60,42,12,0.3)' }}>
        <button onClick={onClose} className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors">
          <X className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-3 mb-5">
          <div className="w-11 h-11 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(201,162,39,0.16)' }}>
            <Layers className="w-6 h-6" style={{ color: '#C9A227' }} />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900">{esEdicion ? 'Editar plan' : 'Nuevo plan'}</h2>
            <p className="text-sm text-gray-500">
              {esEdicion ? plan.name : 'Plan comercial de la plataforma'}
            </p>
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
            <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="plan-nombre">Nombre *</label>
            <input id="plan-nombre" className={INPUT} style={INPUT_STYLE} value={nombre}
              onChange={e => setNombre(e.target.value)} placeholder="Ej. Profesional" maxLength={100} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="plan-precio">Precio mensual (MXN) *</label>
              <input id="plan-precio" type="number" min={0} step="0.01" inputMode="decimal"
                className={INPUT} style={INPUT_STYLE} value={precio}
                onChange={e => setPrecio(e.target.value)} placeholder="1500.00" />
            </div>
            <div>
              <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="plan-orden">Orden</label>
              <input id="plan-orden" type="number" min={0} step={1} inputMode="numeric"
                className={INPUT} style={INPUT_STYLE} value={orden}
                onChange={e => setOrden(e.target.value)} />
            </div>
          </div>

          <div>
            <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="plan-desc">Descripción</label>
            <input id="plan-desc" className={INPUT} style={INPUT_STYLE} value={descripcion}
              onChange={e => setDescripcion(e.target.value)} placeholder="Para clínicas en crecimiento" maxLength={200} />
          </div>

          <div>
            <span className={LABEL} style={{ color: '#9A7B1E' }}>Características</span>
            <div className="space-y-2">
              {features.map((f, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input className={INPUT} style={INPUT_STYLE} value={f}
                    onChange={e => setFeature(i, e.target.value)}
                    placeholder="Ej. Agenda ilimitada" maxLength={120}
                    aria-label={`Característica ${i + 1}`} />
                  <button type="button" onClick={() => quitarFeature(i)}
                    className="w-9 h-9 shrink-0 rounded-xl flex items-center justify-center text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                    aria-label={`Quitar característica ${i + 1}`}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
            <button type="button" onClick={agregarFeature}
              className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold transition-colors hover:brightness-90"
              style={{ color: '#9A7B1E' }}>
              <Plus className="w-3.5 h-3.5" /> Agregar característica
            </button>
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-2 pt-1">
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input type="checkbox" checked={destacado} onChange={e => setDestacado(e.target.checked)}
                className="w-4 h-4 rounded" style={{ accentColor: '#C9A227' }} />
              Popular (destacado)
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input type="checkbox" checked={activo} onChange={e => setActivo(e.target.checked)}
                className="w-4 h-4 rounded" style={{ accentColor: '#C9A227' }} />
              Activo
            </label>
          </div>
          {!activo && (
            <p className="text-[11px] text-gray-400">
              Un plan inactivo deja de ofrecerse a clínicas nuevas; las que ya lo tienen no cambian.
            </p>
          )}
        </div>

        <button onClick={enviar} disabled={guardando}
          className="w-full mt-6 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-60" style={{ background: '#C9A227' }}>
          {guardando ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : <>{esEdicion ? 'Guardar cambios' : 'Crear plan'}</>}
        </button>
      </div>
    </div>
  )
}
