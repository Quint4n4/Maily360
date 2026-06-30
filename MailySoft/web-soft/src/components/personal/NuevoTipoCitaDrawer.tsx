import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Check, AlertCircle, Loader2 } from 'lucide-react'
import { useCreateAppointmentType, useUpdateAppointmentType } from '../../hooks/agenda'
import { erroresDe } from '../../lib/apiErrors'

export interface TipoCitaEdit {
  id: string
  name: string
  color_hex: string
}

interface Props {
  open: boolean
  onClose: () => void
  editing?: TipoCitaEdit | null
}

const COLORES = ['#2E7D5B', '#3A6EA5', '#C0392B', '#C9A227', '#7E57C2', '#E8924E', '#0E9594', '#9A958C']

export default function NuevoTipoCitaDrawer({ open, onClose, editing }: Props) {
  const [nombre, setNombre] = useState('')
  const [color, setColor] = useState(COLORES[0])
  const [errores, setErrores] = useState<string[]>([])
  const crear = useCreateAppointmentType()
  const actualizar = useUpdateAppointmentType()
  const esEdicion = !!editing
  const guardando = crear.isPending || actualizar.isPending

  useEffect(() => {
    if (!open) return
    setErrores([])
    if (editing) { setNombre(editing.name); setColor(editing.color_hex || COLORES[0]) }
    else { setNombre(''); setColor(COLORES[0]) }
  }, [open, editing])

  const swatches = color && !COLORES.includes(color) ? [color, ...COLORES] : COLORES

  const guardar = async () => {
    setErrores([])
    if (!nombre.trim()) { setErrores(['El nombre es obligatorio.']); return }
    const payload = { name: nombre.trim(), color_hex: color }
    try {
      if (editing) await actualizar.mutateAsync({ id: editing.id, input: payload })
      else await crear.mutateAsync(payload)
      onClose()
    } catch (err) { setErrores(erroresDe(err, 'No se pudo guardar el tipo de cita.')) }
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40"
            style={{ background: 'rgba(40,28,8,0.45)', backdropFilter: 'blur(4px)' }}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside
            className="fixed top-0 right-0 z-50 h-full w-full max-w-md flex flex-col"
            style={{ background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(24px)', borderLeft: '1px solid rgba(201,162,39,0.3)' }}
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
          >
            <div className="flex items-center justify-between px-6 py-5 border-b border-amber-900/10">
              <h2 className="text-lg font-bold text-gray-900">{esEdicion ? 'Editar tipo de cita' : 'Nuevo tipo de cita'}</h2>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-5 h-5" /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              {errores.length > 0 && (
                <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                  <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">{errores.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
              )}

              <div>
                <label className="label">Nombre</label>
                <input className="input" maxLength={150} value={nombre} onChange={e => setNombre(e.target.value)} placeholder="Primera vez, Seguimiento, Urgente…" />
              </div>
              <div>
                <label className="label">Color en la agenda</label>
                <div className="flex flex-wrap gap-2.5 mt-1">
                  {swatches.map(c => (
                    <button key={c} onClick={() => setColor(c)}
                      className="w-9 h-9 rounded-full flex items-center justify-center transition-transform hover:scale-110"
                      style={{ background: c, boxShadow: color === c ? `0 0 0 3px #fff, 0 0 0 5px ${c}` : 'none' }}>
                      {color === c && <Check className="w-4 h-4 text-white" />}
                    </button>
                  ))}
                </div>
              </div>

              {/* Vista previa de la tarjeta en la agenda */}
              <div className="rounded-xl p-4" style={{ background: `${color}26`, borderLeft: `4px solid ${color}` }}>
                <p className="text-xs text-gray-400 mb-1">Vista previa en la agenda</p>
                <p className="text-sm font-semibold text-gray-900">Nombre del paciente</p>
                <p className="text-[11px] font-medium" style={{ color }}>{nombre || 'Tipo de cita'}</p>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-amber-900/10 bg-white/60">
              <button onClick={onClose} disabled={guardando} className="btn-secondary flex-1 disabled:opacity-60">Cancelar</button>
              <button onClick={guardar} disabled={guardando}
                className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                {guardando ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : (esEdicion ? 'Guardar cambios' : 'Guardar tipo')}
              </button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
