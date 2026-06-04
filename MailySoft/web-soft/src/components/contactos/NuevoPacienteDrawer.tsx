import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Info } from 'lucide-react'

interface NuevoPacienteDrawerProps {
  open: boolean
  onClose: () => void
}

const SECCION = 'text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-3'

export default function NuevoPacienteDrawer({ open, onClose }: NuevoPacienteDrawerProps) {
  const [form, setForm] = useState({
    firstName: '', paternal: '', maternal: '',
    fechaNac: '', sexo: '', telefono: '', email: '', curp: '', notas: '',
  })

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm(prev => ({ ...prev, [k]: e.target.value }))

  const guardar = () => {
    /* TODO: POST /api/v1/pacientes/ con los campos del backend */
    alert('✅ Paciente guardado (demo) — el número de expediente se asignaría automáticamente.')
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
              <h2 className="text-lg font-bold text-gray-900">Nuevo paciente</h2>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Cuerpo */}
            <div className="px-7 py-6 space-y-7">
              <section>
                <p className={SECCION}>Datos personales</p>
                <div className="space-y-3">
                  <div>
                    <label className="label">Nombre(s)</label>
                    <input className="input" value={form.firstName} onChange={set('firstName')} placeholder="María" />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="label">Apellido paterno</label>
                      <input className="input" value={form.paternal} onChange={set('paternal')} placeholder="González" />
                    </div>
                    <div>
                      <label className="label">Apellido materno</label>
                      <input className="input" value={form.maternal} onChange={set('maternal')} placeholder="Pérez" />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="label">Fecha de nacimiento</label>
                      <input type="date" className="input" value={form.fechaNac} onChange={set('fechaNac')} />
                    </div>
                    <div>
                      <label className="label">Sexo</label>
                      <select className="input" value={form.sexo} onChange={set('sexo')}>
                        <option value="">Selecciona…</option>
                        <option value="F">Femenino</option>
                        <option value="M">Masculino</option>
                        <option value="O">Otro</option>
                      </select>
                    </div>
                  </div>
                </div>
              </section>

              <section>
                <p className={SECCION}>Contacto</p>
                <div className="space-y-3">
                  <div>
                    <label className="label">Teléfono</label>
                    <input className="input" value={form.telefono} onChange={set('telefono')} placeholder="55 1234 5678" />
                  </div>
                  <div>
                    <label className="label">Email <span className="text-gray-400 font-normal">(opcional)</span></label>
                    <input type="email" className="input" value={form.email} onChange={set('email')} placeholder="paciente@correo.mx" />
                  </div>
                </div>
              </section>

              <section>
                <p className={SECCION}>Identificación</p>
                <div>
                  <label className="label">CURP <span className="text-gray-400 font-normal">(opcional)</span></label>
                  <input className="input uppercase" maxLength={18} value={form.curp} onChange={set('curp')} placeholder="18 caracteres" />
                </div>
              </section>

              <section>
                <p className={SECCION}>Notas</p>
                <textarea className="input resize-none" rows={3} value={form.notas} onChange={set('notas')} placeholder="Observaciones, alergias, antecedentes…" />
              </section>

              <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(201,162,39,0.10)', border: '1px solid rgba(201,162,39,0.25)' }}>
                <Info className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#C9A227' }} />
                <p className="text-xs text-amber-800">El número de expediente se asignará automáticamente al guardar.</p>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between gap-3 px-7 py-4 border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={onClose} className="btn-secondary flex-1">Cancelar</button>
              <button
                onClick={guardar}
                className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                Guardar paciente
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
