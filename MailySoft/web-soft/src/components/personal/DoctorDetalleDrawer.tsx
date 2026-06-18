import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  X, Mail, Fingerprint, Pencil, CalendarClock,
  StickyNote, CalendarDays, Plus, Trash2, Settings,
} from 'lucide-react'
import { Doctor, HORARIOS, initialesDoctor } from '../../data/personal'
import ConfiguracionAgendaModal from './ConfiguracionAgendaModal'
import { useAviso } from '../common/DialogProvider'

interface Props {
  doctor: Doctor | null
  onClose: () => void
  soloLectura?: boolean
}

function Card({
  title, icon: Icon, children, action,
}: { title: string; icon: typeof Mail; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="rounded-2xl p-5"
      style={{ background: 'rgba(255,255,255,0.72)', backdropFilter: 'blur(14px)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 6px 20px rgba(60,42,12,0.10)' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4" style={{ color: '#C9A227' }} />
          <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700/80">{title}</h4>
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

function Linea({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-amber-900/5 last:border-0">
      <span className="text-xs text-gray-400">{label}</span>
      <span className="text-sm text-gray-800 font-medium text-right truncate ml-2">{value || '—'}</span>
    </div>
  )
}

export default function DoctorDetalleDrawer({ doctor, onClose, soloLectura = false }: Props) {
  const [configOpen, setConfigOpen] = useState(false)
  const aviso = useAviso()
  const horarios = doctor ? (HORARIOS[doctor.id] ?? []) : []

  return (
    <>
    <AnimatePresence>
      {doctor && (
        <motion.div
          className="fixed inset-0 z-50 overflow-y-auto p-4 md:p-8 flex items-start justify-center"
          style={{ background: 'rgba(40,28,8,0.35)', backdropFilter: 'blur(8px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-6xl glass-card rounded-3xl p-6 md:p-8"
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* Cerrar */}
            <button onClick={onClose}
              className="absolute top-5 right-5 z-10 w-9 h-9 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors shadow-sm">
              <X className="w-5 h-5 text-gray-600" />
            </button>

            <p className="text-xs font-semibold uppercase tracking-widest text-amber-700/70 mb-5">Ficha del doctor</p>

            {/* ════ Grid: cards alrededor del rostro ════ */}
            <div className="grid gap-5 items-stretch" style={{ gridTemplateColumns: '1fr 1.15fr 1fr' }}>

              {/* ── Izquierda ── */}
              <div className="space-y-5">
                <Card title="Contacto" icon={Mail}>
                  <div className="flex items-center gap-2.5">
                    <Mail className="w-4 h-4 text-gray-400 shrink-0" />
                    <span className="text-sm text-gray-800 truncate">{doctor.email || '—'}</span>
                  </div>
                </Card>

                <Card title="Datos profesionales" icon={Fingerprint}>
                  <Linea label="Cédula" value={doctor.cedula} />
                  <Linea label="Duración de cita" value={`${doctor.duracion} min`} />
                  <Linea label="Especialidad" value={doctor.especialidad} />
                </Card>
              </div>

              {/* ── Centro: rostro ── */}
              <div className="flex flex-col items-center text-center justify-start pt-2">
                <div className="relative mb-4">
                  <div className="absolute -inset-3 rounded-full"
                    style={{ background: 'conic-gradient(from 120deg, #E8C766, #C9A227, #F5E6B8, #C9A227, #E8C766)', filter: 'blur(10px)', opacity: 0.55 }} />
                  <div className="relative w-44 h-44 rounded-full overflow-hidden flex items-center justify-center text-5xl font-bold"
                    style={{ background: 'rgba(201,162,39,0.18)', color: '#B8860B', border: '4px solid rgba(255,255,255,0.85)', boxShadow: '0 12px 36px rgba(60,42,12,0.30)' }}>
                    <span className="absolute">{initialesDoctor(doctor.nombre)}</span>
                    <img
                      src={`https://i.pravatar.cc/300?img=${(parseInt(doctor.id) * 13 + 5) % 70 + 1}`}
                      alt={doctor.nombre}
                      className="relative w-full h-full object-cover"
                      onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                    />
                  </div>
                </div>

                <h2 className="text-2xl font-bold text-gray-900 leading-tight">{doctor.nombre}</h2>
                <p className="text-sm mt-0.5" style={{ color: '#B8860B' }}>{doctor.especialidad}</p>
                <span className={`badge mt-2 ${doctor.activo ? 'badge-success' : 'badge-neutral'}`}>
                  {doctor.activo ? 'Activo' : 'Inactivo'}
                </span>

                {!soloLectura && (
                  <div className="flex gap-3 mt-5 w-full max-w-[280px]">
                    <button className="btn-secondary flex-1"><Pencil className="w-4 h-4" /> Editar</button>
                    <button
                      onClick={() => setConfigOpen(true)}
                      className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                      style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                      <Settings className="w-4 h-4" /> Configuración
                    </button>
                  </div>
                )}
              </div>

              {/* ── Derecha ── */}
              <div className="space-y-5">
                <Card title="Disponibilidad" icon={CalendarClock}>
                  {horarios.length > 0 ? (
                    <div>
                      <p className="text-lg font-bold text-gray-900">{horarios.length} días por semana</p>
                      <p className="text-sm text-gray-500 mt-0.5">{horarios.map(h => h.dia).join(' · ')}</p>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-400 italic">Sin horarios configurados.</p>
                  )}
                </Card>

                <Card title="Biografía" icon={StickyNote}>
                  <p className="text-sm text-gray-600 leading-relaxed">
                    {doctor.bio || 'Sin biografía registrada.'}
                  </p>
                </Card>
              </div>
            </div>

            {/* ════ Horarios de atención (ancho completo) ════ */}
            <div className="mt-5">
              <Card
                title="Horarios de atención" icon={CalendarDays}
                action={!soloLectura ? (
                  <button onClick={() => void aviso({ mensaje: 'Agregar horario (demo)', tipo: 'info' })}
                    className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
                    style={{ color: '#B8860B', background: 'rgba(201,162,39,0.12)' }}>
                    <Plus className="w-3.5 h-3.5" /> Agregar
                  </button>
                ) : undefined}
              >
                <div className="grid gap-2 md:grid-cols-2">
                  {horarios.map((h, i) => (
                    <div key={i} className="flex items-center justify-between rounded-xl px-4 py-2.5 bg-white/60">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.12)' }}>
                          <CalendarDays className="w-4 h-4" style={{ color: '#C9A227' }} />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-800">{h.dia}</p>
                          <p className="text-xs text-gray-400">{h.inicio} – {h.fin} · {h.consultorio}</p>
                        </div>
                      </div>
                      {!soloLectura && (
                        <button onClick={() => void aviso({ mensaje: 'Eliminar horario (demo)', tipo: 'info' })} className="text-gray-300 hover:text-red-500 transition-colors shrink-0">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  ))}
                  {horarios.length === 0 && (
                    <p className="text-sm text-gray-400 italic py-3 text-center md:col-span-2">Sin horarios configurados todavía.</p>
                  )}
                </div>
              </Card>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>

    <ConfiguracionAgendaModal open={configOpen} doctor={doctor} onClose={() => setConfigOpen(false)} />
    </>
  )
}
