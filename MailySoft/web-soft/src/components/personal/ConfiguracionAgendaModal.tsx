import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Clock, MessageCircle, Hash } from 'lucide-react'
import { Doctor } from '../../data/personal'

interface Props {
  open: boolean
  doctor: Doctor | null
  onClose: () => void
}

const OPCIONES_OFFSET = [15, 30, 60, 120, 1440, 2880]  // minutos

const fmtOffset = (min: number) => {
  if (min % 1440 === 0) { const d = min / 1440; return `${d} ${d === 1 ? 'día' : 'días'} antes` }
  if (min % 60 === 0)   { const h = min / 60;   return `${h} ${h === 1 ? 'hora' : 'horas'} antes` }
  return `${min} minutos antes`
}

/* Switch dorado */
function Switch({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" onClick={() => onChange(!on)}
      className="relative w-11 h-6 rounded-full transition-colors shrink-0"
      style={{ background: on ? '#C9A227' : '#D1D5DB' }}>
      <span className="absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all"
        style={{ left: on ? '22px' : '2px' }} />
    </button>
  )
}

function Seccion({ icon: Icon, title, children, desc }: { icon: typeof Clock; title: string; children: React.ReactNode; desc?: string }) {
  return (
    <div className="rounded-2xl p-5" style={{ background: 'rgba(255,255,255,0.6)', border: '1px solid rgba(255,255,255,0.7)' }}>
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-4 h-4" style={{ color: '#C9A227' }} />
        <h4 className="text-sm font-semibold text-gray-800">{title}</h4>
      </div>
      {desc && <p className="text-xs text-gray-400 mb-3">{desc}</p>}
      <div className={desc ? '' : 'mt-3'}>{children}</div>
    </div>
  )
}

export default function ConfiguracionAgendaModal({ open, doctor, onClose }: Props) {
  const [duracion, setDuracion]       = useState('60')
  const [recordOn, setRecordOn]       = useState(true)
  const [offsets, setOffsets]         = useState<number[]>([1440, 120])
  const [formato, setFormato]         = useState('EXP-####')
  const [reiniciar, setReiniciar]     = useState(false)

  useEffect(() => {
    if (open && doctor) setDuracion(String(doctor.duracion))
  }, [open, doctor])

  const quitarOffset = (min: number) => setOffsets(offsets.filter(o => o !== min))
  const agregarOffset = (min: number) => {
    if (min && !offsets.includes(min)) setOffsets([...offsets, min].sort((a, b) => b - a))
  }

  const guardar = () => {
    /* TODO: PATCH duración → /personal/doctores/<id>/ ; recordatorios/expediente → /agenda/config/ */
    alert('✅ Configuración guardada (demo)')
    onClose()
  }

  return (
    <AnimatePresence>
      {open && doctor && (
        <motion.div
          className="fixed inset-0 z-[60] flex items-start justify-center px-4 py-10 overflow-y-auto"
          style={{ background: 'rgba(40,28,8,0.45)', backdropFilter: 'blur(6px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-lg rounded-3xl overflow-hidden"
            style={{
              background: 'rgba(255,255,255,0.85)',
              backdropFilter: 'blur(30px) saturate(160%)',
              WebkitBackdropFilter: 'blur(30px) saturate(160%)',
              border: '1px solid rgba(255,255,255,0.7)',
              boxShadow: '0 20px 60px rgba(60,42,12,0.3)',
            }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="px-7 py-5 border-b border-white/40">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-gray-900">Configuración de agenda</h2>
                <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-5 h-5" /></button>
              </div>
              <p className="text-sm text-gray-500 mt-0.5">{doctor.nombre}</p>
            </div>

            {/* Cuerpo */}
            <div className="px-7 py-6 space-y-4">

              {/* Duración */}
              <Seccion icon={Clock} title="Duración de la cita" desc="El doctor define cuánto dura una consulta con su paciente.">
                <select value={duracion} onChange={e => setDuracion(e.target.value)} className="input">
                  <option value="15">15 minutos</option>
                  <option value="30">30 minutos</option>
                  <option value="45">45 minutos</option>
                  <option value="60">60 minutos</option>
                  <option value="90">90 minutos</option>
                </select>
              </Seccion>

              {/* Recordatorios */}
              <Seccion icon={MessageCircle} title="Recordatorios por WhatsApp">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-600">Activar recordatorios</span>
                  <Switch on={recordOn} onChange={setRecordOn} />
                </div>
                <div className={recordOn ? '' : 'opacity-40 pointer-events-none'}>
                  <p className="text-xs text-gray-400 mb-2">Se enviarán con esta anticipación:</p>
                  <div className="flex flex-wrap gap-2 mb-3">
                    {offsets.map(o => (
                      <span key={o} className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
                        style={{ background: 'rgba(201,162,39,0.14)', color: '#9A7B1E' }}>
                        {fmtOffset(o)}
                        <button onClick={() => quitarOffset(o)} className="hover:text-red-500"><X className="w-3 h-3" /></button>
                      </span>
                    ))}
                    {offsets.length === 0 && <span className="text-xs text-gray-400 italic">Sin recordatorios.</span>}
                  </div>
                  <select value="" onChange={e => { agregarOffset(Number(e.target.value)); e.target.value = '' }}
                    className="input text-sm">
                    <option value="">+ Agregar recordatorio…</option>
                    {OPCIONES_OFFSET.filter(o => !offsets.includes(o)).map(o => (
                      <option key={o} value={o}>{fmtOffset(o)}</option>
                    ))}
                  </select>
                </div>
              </Seccion>

              {/* Expediente */}
              <Seccion icon={Hash} title="Número de expediente">
                <label className="label">Formato</label>
                <input className="input mb-3" value={formato} onChange={e => setFormato(e.target.value)} placeholder="EXP-####" />
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-600">Reiniciar numeración cada año</span>
                  <Switch on={reiniciar} onChange={setReiniciar} />
                </div>
              </Seccion>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between gap-3 px-7 py-4 border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={onClose} className="btn-secondary flex-1">Cancelar</button>
              <button onClick={guardar}
                className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                Guardar cambios
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
