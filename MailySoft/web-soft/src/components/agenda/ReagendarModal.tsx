import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2, CalendarClock, User } from 'lucide-react'
import { useRescheduleAppointment } from '../../hooks/agenda'
import { toDayKey, localHHMM, combineToISO, durationMin } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import { INPUT, LABEL } from '../../lib/estilosForm'
import type { Appointment } from '../../types/agenda'

interface Props {
  cita: Appointment | null
  onClose: () => void
}

const DURACIONES = [30, 45, 60, 90]

export default function ReagendarModal({ cita, onClose }: Props) {
  const [fecha, setFecha] = useState('')
  const [hora, setHora] = useState('09:00')
  const [duracion, setDuracion] = useState(30)
  const [errores, setErrores] = useState<string[]>([])
  const reagendar = useRescheduleAppointment()

  useEffect(() => {
    if (!cita) return
    setFecha(toDayKey(new Date(cita.starts_at)))
    setHora(localHHMM(cita.starts_at))
    setDuracion(durationMin(cita.starts_at, cita.ends_at) || 30)
    setErrores([])
  }, [cita])

  if (!cita) return null
  const cancelada = cita.status === 'cancelled'

  const guardar = async () => {
    setErrores([])
    if (!fecha) { setErrores(['Elige la fecha.']); return }
    const startISO = combineToISO(fecha, hora)
    const endISO = new Date(new Date(startISO).getTime() + duracion * 60_000).toISOString()
    try {
      await reagendar.mutateAsync({ id: cita.id, input: { starts_at: startISO, ends_at: endISO } })
      onClose()
    } catch (err) { setErrores(erroresDe(err, 'No se pudo reagendar la cita.')) }
  }

  return (
    <AnimatePresence>
      {cita && (
        <motion.div
          className="fixed inset-0 z-[60] flex items-start justify-center px-4 py-12 overflow-y-auto"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{ background: 'rgba(40,28,8,0.45)', backdropFilter: 'blur(6px)' }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-md rounded-3xl overflow-hidden"
            style={{ background: 'rgba(255,255,255,0.88)', backdropFilter: 'blur(30px) saturate(160%)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 20px 60px rgba(60,42,12,0.25)' }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25 }}
            onClick={e => e.stopPropagation()}
          >
            <div className="px-7 py-5 flex items-start justify-between border-b border-white/40">
              <div>
                <h2 className="text-gray-900 text-xl font-bold flex items-center gap-2">
                  <CalendarClock className="w-5 h-5" style={{ color: '#C9A227' }} /> Reagendar cita
                </h2>
                <p className="text-gray-500 text-sm mt-1 flex items-center gap-1.5">
                  <User className="w-3.5 h-3.5" /> {cita.patient.full_name} · {cita.doctor.full_name}
                </p>
              </div>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-6 h-6" /></button>
            </div>

            <div className="px-7 py-6 space-y-5">
              {cancelada && (
                <div className="flex items-start gap-2 rounded-xl px-4 py-2.5 text-xs" style={{ background: 'rgba(46,125,91,0.10)', color: '#1F6E47', border: '1px solid rgba(46,125,91,0.25)' }}>
                  <CalendarClock className="w-4 h-4 mt-0.5 shrink-0" />
                  Al reagendar, la cita cancelada se <b>reactiva</b> en el nuevo horario.
                </div>
              )}
              {errores.length > 0 && (
                <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                  <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">{errores.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
              )}

              <div>
                <label className={LABEL}>Nuevo día</label>
                <input type="date" className={INPUT} value={fecha} onChange={e => setFecha(e.target.value)} />
              </div>
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <label className={LABEL}>Hora</label>
                  <input type="time" className={INPUT} value={hora} onChange={e => setHora(e.target.value)} />
                </div>
                <div>
                  <label className={LABEL}>Duración</label>
                  <select className={INPUT} value={duracion} onChange={e => setDuracion(Number(e.target.value))}>
                    {DURACIONES.map(d => <option key={d} value={d}>{d} min</option>)}
                  </select>
                </div>
              </div>
            </div>

            <div className="px-7 py-4 flex items-center justify-between border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={onClose} disabled={reagendar.isPending} className="btn-secondary disabled:opacity-60">Cancelar</button>
              <button onClick={guardar} disabled={reagendar.isPending}
                className="px-8 py-2.5 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                {reagendar.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Reagendando…</> : 'Reagendar'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
