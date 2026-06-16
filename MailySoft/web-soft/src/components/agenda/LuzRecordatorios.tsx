import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlarmClock, X } from 'lucide-react'
import { useReminders } from '../../hooks/notas'
import { useAuth } from '../../auth/AuthContext'
import { dayRangeUTC, toDayKey } from '../../lib/fecha'

/** Al descartar, la luz se oculta este tiempo (para no parpadear sin fin). */
const SNOOZE_MS = 4 * 60 * 60_000 // 4 horas
const STORAGE_KEY = (uid: string) => `maily.luzRecordatorios.snooze.${uid}`

function loadSnooze(uid: string): number {
  if (!uid) return 0
  try {
    const raw = localStorage.getItem(STORAGE_KEY(uid))
    const v = raw ? Number(raw) : 0
    return Number.isFinite(v) ? v : 0
  } catch {
    return 0
  }
}
function saveSnooze(uid: string, until: number) {
  if (!uid) return
  try {
    localStorage.setItem(STORAGE_KEY(uid), String(until))
  } catch {
    /* cuota llena, ignora */
  }
}

/**
 * Luz amarilla parpadeante (esquina inferior derecha): se enciende cuando el
 * usuario tiene recordatorios de HOY cuya hora ya llegó y siguen pendientes.
 * Es solo del usuario logueado. Clic → lleva a la agenda (donde está el panel
 * "Mis recordatorios"). La "×" la oculta unas horas.
 */
export default function LuzRecordatorios() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const uid = user?.id ?? ''

  const hoy = toDayKey(new Date())
  const { from, to } = dayRangeUTC(hoy)
  // Solo consulta cuando ya hay sesión: evita disparar un request (y un refresh
  // en paralelo) durante el bootstrap de auth al recargar la página.
  const { data } = useReminders({ date_from: from, date_to: to }, !!user)

  const [nowMs, setNowMs] = useState(() => Date.now())
  const [snoozeUntil, setSnoozeUntil] = useState<number>(() => loadSnooze(uid))

  useEffect(() => {
    setSnoozeUntil(loadSnooze(uid))
  }, [uid])

  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 30_000)
    return () => window.clearInterval(id)
  }, [])

  // Recordatorios de hoy cuya hora ya pasó y siguen pendientes (tareas sin hacer).
  const vencidos = useMemo(() => {
    const list = data?.results ?? []
    return list.filter(n => {
      if (!n.remind_at) return false
      if (n.is_task && n.done) return false
      return new Date(n.remind_at).getTime() <= nowMs
    })
  }, [data, nowMs])

  const count = vencidos.length
  const oculto = nowMs < snoozeUntil

  if (!user || count === 0 || oculto) return null

  const descartar = (e: React.MouseEvent) => {
    e.stopPropagation()
    const until = Date.now() + SNOOZE_MS
    setSnoozeUntil(until)
    saveSnooze(uid, until)
  }

  const etiqueta =
    count === 1 ? '1 recordatorio pendiente' : `${count} recordatorios pendientes`

  return (
    <div className="fixed bottom-6 right-6 z-[90]">
      <button
        onClick={() => navigate('/agenda')}
        title={etiqueta}
        aria-label={etiqueta}
        className="relative flex items-center justify-center"
      >
        {/* Anillo que late (la "luz parpadeando") */}
        <span
          className="absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping"
          style={{ background: '#C9A227' }}
        />
        {/* Botón sólido */}
        <span
          className="relative inline-flex items-center justify-center w-14 h-14 rounded-full shadow-lg transition-transform hover:scale-105"
          style={{ background: '#C9A227', boxShadow: '0 6px 20px rgba(201,162,39,0.55)' }}
        >
          <AlarmClock className="w-6 h-6 text-white" />
          <span
            className="absolute -top-0.5 -right-0.5 min-w-[20px] h-[20px] px-1 rounded-full flex items-center justify-center text-[11px] font-bold text-white"
            style={{ background: '#C0392B', border: '2px solid #fff' }}
          >
            {count > 9 ? '9+' : count}
          </span>
        </span>
      </button>

      {/* Descartar (oculta unas horas) */}
      <button
        onClick={descartar}
        title="Ocultar por ahora"
        aria-label="Ocultar recordatorios"
        className="absolute -top-1 -left-1 w-5 h-5 rounded-full flex items-center justify-center shadow transition-colors hover:bg-gray-100"
        style={{ background: '#fff', border: '1px solid rgba(0,0,0,0.1)' }}
      >
        <X className="w-3 h-3" style={{ color: '#6B7280' }} />
      </button>
    </div>
  )
}
