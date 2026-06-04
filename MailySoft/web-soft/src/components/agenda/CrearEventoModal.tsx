import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X } from 'lucide-react'

/* ─── Tipos ─────────────────────────────────────────────────────────────── */
type TipoEvento = 'cita' | 'reunion' | 'bloqueo'
type ModoPaciente = 'seleccionar' | 'nuevo'
type TipoCita = 'primera' | 'subsecuente' | 'urgente'
type Modalidad = 'consultorio' | 'telefonica' | 'video' | 'fuera'

interface CrearEventoModalProps {
  open: boolean
  onClose: () => void
  fecha: string
  horaInicio: string
  consultorio?: string
}

const PACIENTES_DEMO = [
  'Reyes Benítez Alondra',
  'María González Pérez',
  'Roberto Sánchez Luna',
  'Lucía Ramírez Soto',
  'Jorge Mendoza Ríos',
]

const HORAS_FIN = ['09:30', '10:00', '10:30', '11:00', '11:30', '12:00']

const INPUT = 'w-full rounded-xl border border-white/60 bg-white/70 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20'

/* ─── Pill ──────────────────────────────────────────────────────────────── */
function Pill({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-5 py-2.5 rounded-full text-sm font-semibold transition-all duration-150 active:scale-[0.98]"
      style={
        selected
          ? { background: '#C9A227', color: '#fff', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }
          : { background: 'rgba(255,255,255,0.55)', color: '#9A7B1E', border: '1px solid rgba(255,255,255,0.7)' }
      }
    >
      {label}
    </button>
  )
}

/* ─── Componente ─────────────────────────────────────────────────────────── */
export default function CrearEventoModal({
  open, onClose, fecha, horaInicio, consultorio,
}: CrearEventoModalProps) {
  const [doctor, setDoctor]             = useState('Dr. Prueba')
  const [horaFin, setHoraFin]           = useState('09:30')
  const [tipoEvento, setTipoEvento]     = useState<TipoEvento | null>(null)
  const [modoPaciente, setModoPaciente] = useState<ModoPaciente | null>(null)
  const [paciente, setPaciente]         = useState('')
  const [tipoCita, setTipoCita]         = useState<TipoCita | null>(null)
  const [modalidad, setModalidad]       = useState<Modalidad | null>(null)
  const [observaciones, setObs]         = useState('')
  const [enviarCorreo, setEnviarCorreo] = useState(false)

  const reset = () => {
    setTipoEvento(null); setModoPaciente(null); setPaciente('')
    setTipoCita(null); setModalidad(null); setObs(''); setEnviarCorreo(false)
  }
  const handleClose = () => { reset(); onClose() }

  const esCita       = tipoEvento === 'cita'
  const muestraTipo  = esCita && !!paciente
  const muestraModal = muestraTipo && !!tipoCita
  const puedeGuardar = (esCita && !!modalidad) || tipoEvento === 'reunion' || tipoEvento === 'bloqueo'

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 py-10 overflow-y-auto"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          onClick={handleClose}
        >
          <motion.div
            className="relative w-full max-w-2xl rounded-3xl overflow-hidden"
            style={{
              background: 'rgba(255,255,255,0.62)',
              backdropFilter: 'blur(30px) saturate(160%)',
              WebkitBackdropFilter: 'blur(30px) saturate(160%)',
              border: '1px solid rgba(255,255,255,0.65)',
              boxShadow: '0 20px 60px rgba(60,42,12,0.25)',
            }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }}
            animate={{ opacity: 1, y: 0,  scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* ── Encabezado glass ── */}
            <div className="px-7 py-5 flex items-start justify-between border-b border-white/40">
              <div>
                <h2 className="text-gray-900 text-xl font-bold">Crear nuevo evento</h2>
                <p className="text-gray-500 text-sm italic mt-0.5">
                  {fecha} a las {horaInicio} hrs.{consultorio ? ` · ${consultorio}` : ''}
                </p>
              </div>
              <button onClick={handleClose} className="text-gray-400 hover:text-gray-700 transition-colors">
                <X className="w-6 h-6" />
              </button>
            </div>

            {/* ── Cuerpo ── */}
            <div className="px-7 py-6 space-y-5">

              {/* Doctor */}
              <select value={doctor} onChange={e => setDoctor(e.target.value)} className={INPUT}>
                <option>Dr. Prueba</option>
                <option>Dra. Martínez</option>
                <option>Dr. Herrera</option>
              </select>

              {/* Horario + tipo de evento */}
              <div className="flex flex-wrap items-end gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Inicia cita</label>
                  <input value={horaInicio} disabled
                    className="w-28 rounded-xl border border-white/50 bg-white/40 px-4 py-2.5 text-sm text-gray-600" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Finaliza cita</label>
                  <select value={horaFin} onChange={e => setHoraFin(e.target.value)} className={`${INPUT} w-32`}>
                    {HORAS_FIN.map(h => <option key={h}>{h} hrs</option>)}
                  </select>
                </div>
                <div className="flex gap-2.5 ml-auto">
                  <Pill label="Cita"    selected={tipoEvento === 'cita'}    onClick={() => { reset(); setTipoEvento('cita') }} />
                  <Pill label="Reunión" selected={tipoEvento === 'reunion'} onClick={() => { reset(); setTipoEvento('reunion') }} />
                  <Pill label="Bloqueo" selected={tipoEvento === 'bloqueo'} onClick={() => { reset(); setTipoEvento('bloqueo') }} />
                </div>
              </div>

              {/* Paciente (solo si es Cita) */}
              <AnimatePresence>
                {esCita && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }} className="space-y-4 overflow-hidden"
                  >
                    <div className="flex flex-wrap items-center gap-3 pt-1">
                      <Pill label="Seleccionar paciente" selected={modoPaciente === 'seleccionar'} onClick={() => setModoPaciente('seleccionar')} />
                      <Pill label="Nuevo paciente"       selected={modoPaciente === 'nuevo'}       onClick={() => setModoPaciente('nuevo')} />
                      {modoPaciente === 'seleccionar' && (
                        <select value={paciente} onChange={e => setPaciente(e.target.value)} className={`${INPUT} flex-1 min-w-[200px]`}>
                          <option value="">Selecciona un paciente…</option>
                          {PACIENTES_DEMO.map(p => <option key={p}>{p}</option>)}
                        </select>
                      )}
                      {modoPaciente === 'nuevo' && (
                        <input value={paciente} onChange={e => setPaciente(e.target.value)}
                          placeholder="Nombre del nuevo paciente" className={`${INPUT} flex-1 min-w-[200px]`} />
                      )}
                    </div>

                    <AnimatePresence>
                      {muestraTipo && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }} className="flex flex-wrap gap-2.5 overflow-hidden"
                        >
                          <Pill label="Cita primera vez" selected={tipoCita === 'primera'}     onClick={() => setTipoCita('primera')} />
                          <Pill label="Cita subsecuente" selected={tipoCita === 'subsecuente'} onClick={() => setTipoCita('subsecuente')} />
                          <Pill label="Cita urgente"     selected={tipoCita === 'urgente'}     onClick={() => setTipoCita('urgente')} />
                        </motion.div>
                      )}
                    </AnimatePresence>

                    <AnimatePresence>
                      {muestraModal && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }} className="flex flex-wrap gap-2.5 overflow-hidden"
                        >
                          <Pill label="Consultorio u oficina" selected={modalidad === 'consultorio'} onClick={() => setModalidad('consultorio')} />
                          <Pill label="Telefónica"            selected={modalidad === 'telefonica'}  onClick={() => setModalidad('telefonica')} />
                          <Pill label="Video llamada"         selected={modalidad === 'video'}       onClick={() => setModalidad('video')} />
                          <Pill label="Fuera de la instalación" selected={modalidad === 'fuera'}     onClick={() => setModalidad('fuera')} />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Observaciones */}
              <AnimatePresence>
                {puedeGuardar && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }} className="overflow-hidden"
                  >
                    <textarea value={observaciones} onChange={e => setObs(e.target.value)}
                      placeholder="Observaciones…" rows={3} className={`${INPUT} resize-none`} />
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Enviar correo */}
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" checked={enviarCorreo} onChange={e => setEnviarCorreo(e.target.checked)} className="w-4 h-4 accent-amber-600" />
                <span className="text-sm text-gray-600">Enviar correo</span>
              </label>
            </div>

            {/* ── Pie: acciones ── */}
            <div className="px-7 py-4 flex items-center justify-between border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={handleClose} className="btn-secondary">Cancelar</button>
              <button
                onClick={() => { alert('✅ Evento guardado (demo)'); handleClose() }}
                disabled={!puedeGuardar}
                className="px-8 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ background: '#C9A227', boxShadow: puedeGuardar ? '0 4px 14px rgba(201,162,39,0.4)' : 'none' }}
              >
                Guardar
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
