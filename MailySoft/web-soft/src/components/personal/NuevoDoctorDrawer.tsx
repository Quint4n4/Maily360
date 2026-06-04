import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X } from 'lucide-react'

interface Props {
  open: boolean
  onClose: () => void
}

export default function NuevoDoctorDrawer({ open, onClose }: Props) {
  const [form, setForm] = useState({
    nombre: '', email: '', especialidad: '', cedula: '', duracion: '60', bio: '',
  })
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm(prev => ({ ...prev, [k]: e.target.value }))

  const guardar = () => {
    /* TODO: POST /api/v1/personal/doctores/ */
    alert('✅ Doctor guardado (demo)')
    onClose()
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 py-10 overflow-y-auto"
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-lg rounded-3xl overflow-hidden"
            style={{
              background: 'rgba(255,255,255,0.82)',
              backdropFilter: 'blur(30px) saturate(160%)',
              WebkitBackdropFilter: 'blur(30px) saturate(160%)',
              border: '1px solid rgba(255,255,255,0.7)',
              boxShadow: '0 20px 60px rgba(60,42,12,0.25)',
            }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-7 py-5 border-b border-white/40">
              <h2 className="text-lg font-bold text-gray-900">Nuevo doctor</h2>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-5 h-5" /></button>
            </div>

            {/* Cuerpo */}
            <div className="px-7 py-6 space-y-4">
              <div>
                <label className="label">Nombre completo</label>
                <input className="input" value={form.nombre} onChange={set('nombre')} placeholder="Dra. Laura Martínez" />
              </div>
              <div>
                <label className="label">Correo electrónico</label>
                <input type="email" className="input" value={form.email} onChange={set('email')} placeholder="doctor@maily360.mx" />
              </div>
              <div>
                <label className="label">Especialidad</label>
                <input className="input" value={form.especialidad} onChange={set('especialidad')} placeholder="Medicina regenerativa" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Cédula profesional</label>
                  <input className="input" value={form.cedula} onChange={set('cedula')} placeholder="7654321" />
                </div>
                <div>
                  <label className="label">Duración default</label>
                  <select className="input" value={form.duracion} onChange={set('duracion')}>
                    <option value="15">15 min</option>
                    <option value="30">30 min</option>
                    <option value="45">45 min</option>
                    <option value="60">60 min</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Bio corta <span className="text-gray-400 font-normal">(opcional)</span></label>
                <textarea className="input resize-none" rows={3} value={form.bio} onChange={set('bio')} placeholder="Experiencia, enfoque…" />
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between gap-3 px-7 py-4 border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={onClose} className="btn-secondary flex-1">Cancelar</button>
              <button onClick={guardar}
                className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                Guardar doctor
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
