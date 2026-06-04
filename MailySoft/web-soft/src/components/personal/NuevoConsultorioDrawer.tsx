import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Check } from 'lucide-react'

interface Props {
  open: boolean
  onClose: () => void
}

const COLORES = ['#C9A227', '#3A6EA5', '#2E7D5B', '#B23A48', '#7E57C2', '#E8924E', '#0E9594', '#8A6A14']

export default function NuevoConsultorioDrawer({ open, onClose }: Props) {
  const [nombre, setNombre]   = useState('')
  const [ubicacion, setUbic]  = useState('')
  const [color, setColor]     = useState(COLORES[0])

  const guardar = () => {
    /* TODO: POST /api/v1/personal/consultorios/ */
    alert('✅ Consultorio guardado (demo)')
    onClose()
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
              <h2 className="text-lg font-bold text-gray-900">Nuevo consultorio</h2>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-5 h-5" /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              <div>
                <label className="label">Nombre</label>
                <input className="input" value={nombre} onChange={e => setNombre(e.target.value)} placeholder="Consultorio 1" />
              </div>
              <div>
                <label className="label">Ubicación</label>
                <input className="input" value={ubicacion} onChange={e => setUbic(e.target.value)} placeholder="Planta baja, ala norte" />
              </div>
              <div>
                <label className="label">Color en la agenda</label>
                <div className="flex flex-wrap gap-2.5 mt-1">
                  {COLORES.map(c => (
                    <button key={c} onClick={() => setColor(c)}
                      className="w-9 h-9 rounded-full flex items-center justify-center transition-transform hover:scale-110"
                      style={{ background: c, boxShadow: color === c ? `0 0 0 3px #fff, 0 0 0 5px ${c}` : 'none' }}>
                      {color === c && <Check className="w-4 h-4 text-white" />}
                    </button>
                  ))}
                </div>
              </div>

              {/* Vista previa */}
              <div className="rounded-xl p-4 border border-amber-900/5" style={{ background: 'rgba(201,162,39,0.06)' }}>
                <p className="text-xs text-gray-400 mb-2">Vista previa</p>
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full" style={{ background: color }} />
                  <span className="text-sm font-medium text-gray-800">{nombre || 'Consultorio'}</span>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-amber-900/10 bg-white/60">
              <button onClick={onClose} className="btn-secondary flex-1">Cancelar</button>
              <button onClick={guardar}
                className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                Guardar consultorio
              </button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
