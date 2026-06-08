import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2, Search } from 'lucide-react'
import { usePatients } from '../../hooks/pacientes'
import { useDoctors, useConsultorios, useCreateAppointment } from '../../hooks/agenda'
import { combineToISO } from '../../lib/fecha'
import { ApiError } from '../../lib/http'

type TipoCita = 'Primera vez' | 'Subsecuente' | 'Urgente'

interface CrearEventoModalProps {
  open: boolean
  onClose: () => void
  dayKey: string
  fechaLarga: string
  horaInicio: string
  consultorioId?: string | null
  consultorioName?: string
}

const INPUT = 'w-full rounded-xl border border-white/60 bg-white/70 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/20'
const LABEL = 'block text-xs font-medium text-gray-500 mb-1'
const TIPOS: TipoCita[] = ['Primera vez', 'Subsecuente', 'Urgente']
const DURACIONES = [30, 45, 60, 90]

function erroresDe(err: unknown): string[] {
  if (!(err instanceof ApiError)) return ['No se pudo agendar la cita.']
  if (err.isNetwork) return ['No se pudo conectar con el servidor.']
  const body = err.body
  if (!body) return [`Error ${err.status}.`]
  const msgs: string[] = []
  for (const [campo, valor] of Object.entries(body)) {
    const txt = Array.isArray(valor) ? valor.join(' ') : String(valor)
    msgs.push(campo === 'detail' ? txt : `${campo}: ${txt}`)
  }
  return msgs.length ? msgs : [`Error ${err.status}.`]
}

function Pill({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="px-4 py-2 rounded-full text-sm font-semibold transition-all duration-150 active:scale-[0.98]"
      style={selected
        ? { background: '#C9A227', color: '#fff', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }
        : { background: 'rgba(255,255,255,0.55)', color: '#9A7B1E', border: '1px solid rgba(255,255,255,0.7)' }}>
      {label}
    </button>
  )
}

export default function CrearEventoModal({
  open, onClose, dayKey, fechaLarga, horaInicio, consultorioId, consultorioName,
}: CrearEventoModalProps) {
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [pacienteId, setPacienteId] = useState('')
  const [doctorId, setDoctorId] = useState('')
  const [consId, setConsId] = useState<string>('')
  const [duracion, setDuracion] = useState(30)
  const [tipo, setTipo] = useState<TipoCita | null>(null)
  const [notas, setNotas] = useState('')
  const [errores, setErrores] = useState<string[]>([])

  const { data: pacData, isLoading: loadingPac } = usePatients(debounced)
  const { data: docData } = useDoctors()
  const { data: consData } = useConsultorios()
  const crear = useCreateAppointment()

  const pacientes = pacData?.results ?? []
  const doctores = (docData?.results ?? []).filter(d => d.is_active)
  const consultorios = (consData?.results ?? []).filter(c => c.is_active)

  // Debounce de la búsqueda de pacientes.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  // Al abrir: preseleccionar consultorio (de la columna clicada) y resetear.
  useEffect(() => {
    if (!open) return
    setConsId(consultorioId ?? '')
    setErrores([])
  }, [open, consultorioId])

  const reset = () => {
    setSearch(''); setDebounced(''); setPacienteId(''); setDoctorId('')
    setDuracion(30); setTipo(null); setNotas(''); setErrores([])
  }
  const cerrar = () => { reset(); onClose() }

  const guardar = async () => {
    setErrores([])
    const faltan: string[] = []
    if (!pacienteId) faltan.push('Selecciona un paciente.')
    if (!doctorId) faltan.push('Selecciona un doctor.')
    if (!tipo) faltan.push('Indica el tipo de cita.')
    if (faltan.length) { setErrores(faltan); return }

    const startISO = combineToISO(dayKey, horaInicio)
    const endISO = new Date(new Date(startISO).getTime() + duracion * 60_000).toISOString()
    const doctorSel = doctores.find(d => d.id === doctorId)

    try {
      await crear.mutateAsync({
        patient_id: pacienteId,
        doctor_id: doctorId,
        consultorio_id: consId || null,
        starts_at: startISO,
        ends_at: endISO,
        reason: tipo as string,
        specialty: doctorSel?.specialty ?? '',
        notes: notas.trim(),
      })
      cerrar()
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 py-10 overflow-y-auto"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          onClick={cerrar}
        >
          <motion.div
            className="relative w-full max-w-2xl rounded-3xl overflow-hidden"
            style={{
              background: 'rgba(255,255,255,0.78)',
              backdropFilter: 'blur(30px) saturate(160%)',
              WebkitBackdropFilter: 'blur(30px) saturate(160%)',
              border: '1px solid rgba(255,255,255,0.65)',
              boxShadow: '0 20px 60px rgba(60,42,12,0.25)',
            }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* Encabezado */}
            <div className="px-7 py-5 flex items-start justify-between border-b border-white/40">
              <div>
                <h2 className="text-gray-900 text-xl font-bold">Agendar cita</h2>
                <p className="text-gray-500 text-sm italic mt-0.5">
                  {fechaLarga} · {horaInicio} hrs{consultorioName ? ` · ${consultorioName}` : ''}
                </p>
              </div>
              <button onClick={cerrar} className="text-gray-400 hover:text-gray-700 transition-colors">
                <X className="w-6 h-6" />
              </button>
            </div>

            {/* Cuerpo */}
            <div className="px-7 py-6 space-y-5">

              {errores.length > 0 && (
                <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                  <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">
                    {errores.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              )}

              {/* Paciente */}
              <div>
                <label className={LABEL}>Paciente</label>
                <div className="relative mb-2">
                  <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                  <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Buscar paciente…" className={`${INPUT} pl-10`} />
                </div>
                <select value={pacienteId} onChange={e => setPacienteId(e.target.value)} className={INPUT}>
                  <option value="">{loadingPac ? 'Cargando…' : 'Selecciona un paciente…'}</option>
                  {pacientes.map(p => <option key={p.id} value={p.id}>{p.full_name} · {p.record_number}</option>)}
                </select>
              </div>

              {/* Doctor + consultorio */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={LABEL}>Doctor</label>
                  <select value={doctorId} onChange={e => setDoctorId(e.target.value)} className={INPUT}>
                    <option value="">Selecciona…</option>
                    {doctores.map(d => <option key={d.id} value={d.id}>{d.full_name}</option>)}
                  </select>
                </div>
                <div>
                  <label className={LABEL}>Consultorio</label>
                  <select value={consId} onChange={e => setConsId(e.target.value)} className={INPUT}>
                    <option value="">Sin consultorio</option>
                    {consultorios.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              </div>

              {/* Horario */}
              <div className="flex flex-wrap items-end gap-4">
                <div>
                  <label className={LABEL}>Inicia</label>
                  <input value={`${horaInicio} hrs`} disabled className="w-28 rounded-xl border border-white/50 bg-white/40 px-4 py-2.5 text-sm text-gray-600" />
                </div>
                <div>
                  <label className={LABEL}>Duración</label>
                  <select value={duracion} onChange={e => setDuracion(Number(e.target.value))} className={`${INPUT} w-36`}>
                    {DURACIONES.map(d => <option key={d} value={d}>{d} min</option>)}
                  </select>
                </div>
              </div>

              {/* Tipo de cita */}
              <div>
                <label className={LABEL}>Tipo de cita</label>
                <div className="flex flex-wrap gap-2.5">
                  {TIPOS.map(t => <Pill key={t} label={t} selected={tipo === t} onClick={() => setTipo(t)} />)}
                </div>
              </div>

              {/* Observaciones */}
              <div>
                <label className={LABEL}>Observaciones <span className="text-gray-400 font-normal">(opcional)</span></label>
                <textarea value={notas} onChange={e => setNotas(e.target.value)} rows={3} className={`${INPUT} resize-none`} placeholder="Notas de la cita…" />
              </div>
            </div>

            {/* Pie */}
            <div className="px-7 py-4 flex items-center justify-between border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={cerrar} disabled={crear.isPending} className="btn-secondary disabled:opacity-60">Cancelar</button>
              <button
                onClick={guardar}
                disabled={crear.isPending}
                className="px-8 py-2.5 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Agendando…</> : 'Agendar cita'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
