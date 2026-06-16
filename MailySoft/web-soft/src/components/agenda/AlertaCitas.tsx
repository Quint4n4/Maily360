import { useState, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BellRing, Check, UserX, Loader2, Clock } from 'lucide-react'
import { useTodayAppointmentsLive, useChangeAppointmentStatus } from '../../hooks/agenda'
import { useAuth } from '../../auth/AuthContext'
import { useRole } from '../../auth/RoleContext'
import { localHHMM12 } from '../../lib/fecha'
import { ApiError } from '../../lib/http'
import type { Appointment, AppointmentStatus } from '../../types/agenda'

const SNOOZE_MS = 5 * 60_000   // "Aún no" → recuerda en 5 min
const COOLDOWN_MS = 3 * 60_000 // tras avanzar, pausa antes del siguiente paso

// La pausa (snooze / cooldown) se guarda en localStorage por usuario para que
// sobreviva al refresco de la página (antes vivía en memoria y reaparecía).
const STORAGE_KEY = (uid: string) => `maily.alertaCitas.snooze.${uid}`

function loadSnooze(uid: string): Record<string, number> {
  if (!uid) return {}
  try {
    const raw = localStorage.getItem(STORAGE_KEY(uid))
    if (!raw) return {}
    const obj = JSON.parse(raw) as Record<string, number>
    const now = Date.now()
    const fresh: Record<string, number> = {}
    for (const [k, v] of Object.entries(obj)) if (typeof v === 'number' && v > now) fresh[k] = v
    return fresh
  } catch { return {} }
}
function saveSnooze(uid: string, snooze: Record<string, number>) {
  if (!uid) return
  try { localStorage.setItem(STORAGE_KEY(uid), JSON.stringify(snooze)) } catch { /* cuota llena, ignora */ }
}

type Stage = 'llegada' | 'consulta' | 'cierre'
interface Accion { stage: Stage; next: AppointmentStatus; titulo: string; mensaje: string; primario: string }

/** Devuelve la acción pendiente de una cita "atorada" (su estado quedó atrás del reloj), o null. */
function accionPendiente(a: Appointment, nowMs: number): Accion | null {
  if (a.status === 'cancelled' || a.status === 'attended' || a.status === 'no_show') return null
  const start = new Date(a.starts_at).getTime()
  const end = new Date(a.ends_at).getTime()
  const hora = localHHMM12(a.starts_at)
  const n = a.patient.full_name

  if (a.status === 'in_progress' && nowMs >= end) {
    return { stage: 'cierre', next: 'attended', titulo: '¿Terminó la consulta?', mensaje: `¿Ya se atendió a ${n}? Su cita era a las ${hora}.`, primario: 'Sí, atendida' }
  }
  if (a.status === 'arrived' && nowMs >= start) {
    return { stage: 'consulta', next: 'in_progress', titulo: '¿Pasó a consulta?', mensaje: `¿${n} ya pasó a consulta?`, primario: 'Sí, en consulta' }
  }
  if ((a.status === 'scheduled' || a.status === 'confirmed') && nowMs >= start) {
    const q = a.modality === 'phone' ? `¿Ya contactaste a ${n} por teléfono?`
      : a.modality === 'video' ? `¿Ya iniciaste la videollamada con ${n}?`
      : a.modality === 'offsite' ? `¿Ya estás con ${n}?`
      : `¿Ya llegó ${n}?`
    return { stage: 'llegada', next: 'arrived', titulo: '¡Recuerda tu cita!', mensaje: `${q} Recuerda que tiene cita a las ${hora}.`, primario: 'Sí, ya llegó' }
  }
  return null
}

/** Vigilante global: si una cita de hoy cruzó su hora y su estado no avanzó, alerta para mantenerlo al día. */
export default function AlertaCitas() {
  const { user } = useAuth()
  const { role } = useRole()
  // Solo recepción (todas las citas) o el médico de la cita (las suyas) reciben la
  // alerta. Dueño/admin/enfermería NO — ellos no están "atendiendo" al paciente.
  const esRecepcion = role === 'reception'
  const esDoctor = !!user?.doctor_id
  const activo = !!user && (esRecepcion || esDoctor)
  const uid = user?.id ?? ''

  const { data } = useTodayAppointmentsLive(activo)
  const cambiar = useChangeAppointmentStatus()
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [snooze, setSnooze] = useState<Record<string, number>>(() => loadSnooze(uid))
  const [errorMsg, setErrorMsg] = useState('')

  // Cargar/persistir la pausa por usuario (sobrevive al refresco).
  useEffect(() => { setSnooze(loadSnooze(uid)) }, [uid])
  useEffect(() => { if (uid) saveSnooze(uid, snooze) }, [uid, snooze])

  useEffect(() => {
    if (!activo) return
    const id = window.setInterval(() => setNowMs(Date.now()), 30_000)
    return () => window.clearInterval(id)
  }, [activo])

  const citas = useMemo(() => {
    const all = data?.results ?? []
    // El médico solo se alerta de SUS citas; recepción, de todas.
    return esDoctor ? all.filter(a => a.doctor.id === user?.doctor_id) : all
  }, [data, esDoctor, user?.doctor_id])

  const pendiente = useMemo(() => {
    const ordenadas = [...citas].sort((a, b) => a.starts_at.localeCompare(b.starts_at))
    for (const a of ordenadas) {
      const acc = accionPendiente(a, nowMs)
      if (acc && nowMs >= (snooze[a.id] ?? 0)) return { cita: a, acc }
    }
    return null
  }, [citas, nowMs, snooze])

  // Limpia el error al cambiar de cita/paso.
  useEffect(() => { setErrorMsg('') }, [pendiente?.cita.id, pendiente?.acc.stage])

  if (!activo || !pendiente) return null
  const { cita, acc } = pendiente

  const avanzar = (status: AppointmentStatus) => {
    setErrorMsg('')
    cambiar.mutate(
      { id: cita.id, status },
      {
        onSuccess: () => setSnooze(s => ({ ...s, [cita.id]: Date.now() + COOLDOWN_MS })),
        onError: (e) => {
          const d = e instanceof ApiError ? e.body?.detail : null
          setErrorMsg(Array.isArray(d) ? d.join(' ') : (d ?? 'No se pudo actualizar el estado. Intenta de nuevo.'))
        },
      },
    )
  }
  const posponer = () => { setErrorMsg(''); setSnooze(s => ({ ...s, [cita.id]: Date.now() + SNOOZE_MS })) }

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[100] flex items-center justify-center px-4"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        style={{ background: 'rgba(40,28,8,0.5)', backdropFilter: 'blur(8px)' }}
      >
        <motion.div
          key={cita.id + acc.stage}
          className="relative w-full max-w-md rounded-3xl overflow-hidden text-center"
          style={{ background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(30px) saturate(160%)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 24px 70px rgba(60,42,12,0.3)' }}
          initial={{ opacity: 0, y: 24, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 24, scale: 0.95 }}
          transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
        >
          <div className="px-8 pt-8 pb-4">
            <div className="w-16 h-16 mx-auto rounded-full flex items-center justify-center mb-4" style={{ background: 'rgba(201,162,39,0.15)' }}>
              <BellRing className="w-8 h-8" style={{ color: '#C9A227' }} />
            </div>
            <h2 className="text-xl font-bold text-gray-900">{acc.titulo}</h2>
            <p className="text-gray-600 mt-2">{acc.mensaje}</p>
            <p className="text-xs text-gray-400 mt-3 inline-flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" /> {localHHMM12(cita.starts_at)} · {cita.doctor.full_name}
              {cita.modality !== 'office' && ` · ${cita.modality_display}`}
            </p>
            {errorMsg && (
              <p className="text-sm text-red-600 mt-3 px-3 py-2 rounded-lg" style={{ background: 'rgba(190,40,40,0.10)' }}>{errorMsg}</p>
            )}
          </div>

          <div className="px-8 pb-7 pt-2 space-y-2.5">
            <button onClick={() => avanzar(acc.next)} disabled={cambiar.isPending}
              className="w-full inline-flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-bold text-white transition-all hover:brightness-110 disabled:opacity-60"
              style={{ background: '#2E7D5B', boxShadow: '0 4px 14px rgba(46,125,91,0.4)' }}>
              {cambiar.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} {acc.primario}
            </button>

            <div className="flex gap-2.5">
              {acc.stage === 'llegada' && (
                <button onClick={() => avanzar('no_show')} disabled={cambiar.isPending}
                  className="flex-1 inline-flex items-center justify-center gap-1.5 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:brightness-95 disabled:opacity-60"
                  style={{ color: '#C0392B', background: '#FDE8E8' }}>
                  <UserX className="w-4 h-4" /> No asistió
                </button>
              )}
              <button onClick={posponer} disabled={cambiar.isPending}
                className="flex-1 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:bg-gray-200 disabled:opacity-60"
                style={{ color: '#6B7280', background: '#F3F4F6' }}>
                Aún no
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
