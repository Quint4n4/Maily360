import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BadgeCheck,
  Bell,
  CalendarClock,
  CheckCheck,
  ClipboardList,
  Loader2,
  Megaphone,
  MessageSquare,
  Send,
  ShieldAlert,
  type LucideIcon,
} from 'lucide-react'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadCount,
} from '../hooks/notificaciones'
import type { Notification, NotificationKind } from '../types/notificacion'

/** Icono + colores por tipo de notificación. */
const META: Record<NotificationKind, { icon: LucideIcon; color: string; bg: string }> = {
  meeting: { icon: CalendarClock, color: '#3A6EA5', bg: 'rgba(58,110,165,0.12)' },
  team_note: { icon: MessageSquare, color: '#2E7D5B', bg: 'rgba(46,125,91,0.12)' },
  role_note: { icon: Send, color: '#B8860B', bg: 'rgba(201,162,39,0.16)' },
  broadcast: { icon: Megaphone, color: '#B45309', bg: 'rgba(180,83,9,0.12)' },
  nursing_instruction: { icon: ClipboardList, color: '#0E7C7B', bg: 'rgba(14,124,123,0.12)' },
  credential_review: { icon: ShieldAlert, color: '#9A7B1E', bg: 'rgba(201,162,39,0.16)' },
  credential_result: { icon: BadgeCheck, color: '#2E7D5B', bg: 'rgba(46,125,91,0.12)' },
}

/** Tiempo relativo legible ("hace 5 min"). */
function hace(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'ahora'
  if (min < 60) return `hace ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `hace ${h} h`
  const d = Math.floor(h / 24)
  if (d < 7) return `hace ${d} d`
  return new Date(iso).toLocaleDateString('es-MX', { day: 'numeric', month: 'short' })
}

/** A dónde lleva el clic de una notificación, según su objeto destino. */
function rutaDe(n: Notification): string | null {
  if (n.target_type === 'appointment' || n.target_type === 'agenda_block') return '/agenda'
  if (n.target_type === 'note') return '/notas'
  // Indicación para enfermería (u otro destino de paciente): abrir su expediente.
  if (n.target_type === 'patient' && n.target_id) return `/contactos?paciente=${n.target_id}`
  return null
}

/** Campana de notificaciones del Topbar: badge de no leídas + menú desplegable. */
export default function CampanaNotificaciones() {
  const navigate = useNavigate()
  const [abierto, setAbierto] = useState(false)

  const { data: conteo } = useUnreadCount()
  const { data: lista, isLoading } = useNotifications({ enabled: abierto })
  const marcarLeida = useMarkNotificationRead()
  const marcarTodas = useMarkAllNotificationsRead()

  const noLeidas = conteo?.unread ?? 0
  const items = lista?.results ?? []

  const abrirItem = (n: Notification) => {
    if (!n.is_read) marcarLeida.mutate(n.id)
    const ruta = rutaDe(n)
    setAbierto(false)
    if (ruta) navigate(ruta)
  }

  return (
    <div className="relative">
      <button
        onClick={() => setAbierto(v => !v)}
        className="relative flex items-center justify-center w-10 h-10 rounded-xl transition-colors hover:bg-black/5"
        aria-label="Notificaciones"
        title="Notificaciones"
      >
        <Bell className="w-5 h-5" style={{ color: noLeidas > 0 ? '#C9A227' : '#7A756C' }} />
        {noLeidas > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
            style={{ background: '#C0392B' }}
          >
            {noLeidas > 9 ? '9+' : noLeidas}
          </span>
        )}
      </button>

      {abierto && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setAbierto(false)} />
          <div
            className="absolute right-0 mt-2 w-80 rounded-xl overflow-hidden z-20 shadow-lg"
            style={{
              background: 'rgba(255,255,255,0.97)',
              backdropFilter: 'blur(14px)',
              border: '1px solid rgba(255,255,255,0.7)',
            }}
          >
            {/* Encabezado */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-800">Notificaciones</span>
              {noLeidas > 0 && (
                <button
                  onClick={() => marcarTodas.mutate()}
                  disabled={marcarTodas.isPending}
                  className="flex items-center gap-1 text-[11px] font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-50"
                >
                  <CheckCheck className="w-3.5 h-3.5" /> Marcar todas
                </button>
              )}
            </div>

            {/* Lista */}
            <div className="max-h-[380px] overflow-y-auto">
              {isLoading ? (
                <div className="flex items-center justify-center gap-2 py-8 text-amber-700 text-sm">
                  <Loader2 className="w-4 h-4 animate-spin" /> Cargando…
                </div>
              ) : items.length === 0 ? (
                <p className="px-4 py-8 text-center text-xs text-gray-400 italic">
                  No tienes notificaciones.
                </p>
              ) : (
                items.map((n, i) => {
                  const meta = META[n.kind]
                  const Icono = meta.icon
                  return (
                    <button
                      key={n.id}
                      onClick={() => abrirItem(n)}
                      className="w-full flex items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-amber-50/60"
                      style={{
                        borderTop: i > 0 ? '1px solid rgba(0,0,0,0.05)' : 'none',
                        background: n.is_read ? 'transparent' : 'rgba(201,162,39,0.06)',
                      }}
                    >
                      <span
                        className="mt-0.5 w-8 h-8 rounded-full shrink-0 flex items-center justify-center"
                        style={{ background: meta.bg }}
                      >
                        <Icono className="w-4 h-4" style={{ color: meta.color }} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p
                          className={`text-sm leading-tight ${n.is_read ? 'text-gray-700' : 'font-semibold text-gray-900'}`}
                        >
                          {n.title}
                        </p>
                        {n.body && (
                          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{n.body}</p>
                        )}
                        <p className="text-[11px] text-gray-400 mt-1">
                          {n.actor ? `${n.actor.full_name} · ` : ''}
                          {hace(n.created_at)}
                        </p>
                      </div>
                      {!n.is_read && (
                        <span
                          className="mt-1.5 w-2 h-2 rounded-full shrink-0"
                          style={{ background: '#C9A227' }}
                        />
                      )}
                    </button>
                  )
                })
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
