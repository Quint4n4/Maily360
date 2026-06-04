import { motion, AnimatePresence } from 'framer-motion'
import {
  X, Phone, Mail, Fingerprint, Pencil, CalendarPlus,
  CalendarClock, StickyNote, ClipboardList, User,
} from 'lucide-react'
import { Paciente, fullName, initials, edad, SEXO_LABEL, HISTORIAL } from '../../data/pacientes'

interface ExpedienteDrawerProps {
  paciente: Paciente | null
  onClose: () => void
}

const estadoChip: Record<string, string> = {
  'Atendida':   'badge-success',
  'Cancelada':  'badge-danger',
  'No asistió': 'badge-neutral',
}

/* Card de sección reutilizable */
function Card({
  title, icon: Icon, children, className = '',
}: { title: string; icon: typeof Phone; children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-2xl p-5 ${className}`}
      style={{
        background: 'rgba(255,255,255,0.72)',
        backdropFilter: 'blur(14px)',
        border: '1px solid rgba(255,255,255,0.7)',
        boxShadow: '0 6px 20px rgba(60,42,12,0.10)',
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4" style={{ color: '#C9A227' }} />
        <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700/80">{title}</h4>
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

export default function ExpedienteDrawer({ paciente, onClose }: ExpedienteDrawerProps) {
  return (
    <AnimatePresence>
      {paciente && (
        <motion.div
          className="fixed inset-0 z-50 overflow-y-auto p-4 md:p-8 flex items-start justify-center"
          style={{ background: 'rgba(40,28,8,0.35)', backdropFilter: 'blur(8px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-6xl glass-card rounded-3xl p-6 md:p-8"
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0,  scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* Cerrar */}
            <button
              onClick={onClose}
              className="absolute top-5 right-5 z-10 w-9 h-9 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors shadow-sm"
            >
              <X className="w-5 h-5 text-gray-600" />
            </button>

            <p className="text-xs font-semibold uppercase tracking-widest text-amber-700/70 mb-5">Expediente del paciente</p>

            {/* ════ Grid principal: cards alrededor del rostro ════ */}
            <div className="grid gap-5 items-stretch" style={{ gridTemplateColumns: '1fr 1.15fr 1fr' }}>

              {/* ── Columna izquierda ── */}
              <div className="space-y-5">
                <Card title="Contacto" icon={Phone}>
                  <div className="space-y-2.5">
                    <div className="flex items-center gap-2.5">
                      <Phone className="w-4 h-4 text-gray-400 shrink-0" />
                      <span className="text-sm text-gray-800">{paciente.telefono}</span>
                    </div>
                    <div className="flex items-center gap-2.5">
                      <Mail className="w-4 h-4 text-gray-400 shrink-0" />
                      <span className="text-sm text-gray-800 truncate">{paciente.email || '—'}</span>
                    </div>
                  </div>
                </Card>

                <Card title="Identificación" icon={Fingerprint}>
                  <Linea label="CURP" value={paciente.curp} />
                  <Linea label="Nacimiento" value={paciente.fechaNac} />
                  <Linea label="Edad" value={`${edad(paciente.fechaNac)} años`} />
                  <Linea label="Sexo" value={SEXO_LABEL[paciente.sexo]} />
                </Card>
              </div>

              {/* ── Centro: rostro ── */}
              <div className="flex flex-col items-center text-center justify-start pt-2">
                <div className="relative mb-4">
                  {/* anillo dorado decorativo */}
                  <div className="absolute -inset-3 rounded-full"
                    style={{ background: 'conic-gradient(from 120deg, #E8C766, #C9A227, #F5E6B8, #C9A227, #E8C766)', filter: 'blur(10px)', opacity: 0.55 }} />
                  {/* foto / iniciales */}
                  <div className="relative w-44 h-44 rounded-full overflow-hidden flex items-center justify-center text-5xl font-bold"
                    style={{ background: 'rgba(201,162,39,0.18)', color: '#B8860B', border: '4px solid rgba(255,255,255,0.85)', boxShadow: '0 12px 36px rgba(60,42,12,0.30)' }}>
                    <span className="absolute">{initials(paciente)}</span>
                    <img
                      src={`https://i.pravatar.cc/300?img=${(parseInt(paciente.id) * 7) % 70 + 1}`}
                      alt={fullName(paciente)}
                      className="relative w-full h-full object-cover"
                      onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                    />
                  </div>
                </div>

                <h2 className="text-2xl font-bold text-gray-900 leading-tight">{fullName(paciente)}</h2>
                <p className="text-sm text-gray-500 mt-0.5">{paciente.expediente}</p>
                <span className={`badge mt-2 ${paciente.activo ? 'badge-success' : 'badge-neutral'}`}>
                  {paciente.activo ? 'Activo' : 'Inactivo'}
                </span>

                <div className="flex gap-3 mt-5 w-full max-w-[280px]">
                  <button className="btn-secondary flex-1"><Pencil className="w-4 h-4" /> Editar</button>
                  <button
                    className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                    style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
                  >
                    <CalendarPlus className="w-4 h-4" /> Agendar
                  </button>
                </div>
              </div>

              {/* ── Columna derecha ── */}
              <div className="space-y-5">
                <Card title="Próxima cita" icon={CalendarClock}>
                  {paciente.activo ? (
                    <div>
                      <p className="text-lg font-bold text-gray-900">12 jun 2026 · 10:00</p>
                      <p className="text-sm text-gray-500 mt-0.5">Dra. Martínez · Consultorio 1</p>
                      <span className="badge badge-primary mt-2">Confirmada</span>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-400 italic">Sin cita próxima.</p>
                  )}
                </Card>

                <Card title="Notas" icon={StickyNote}>
                  <p className="text-sm text-gray-600 leading-relaxed">
                    {paciente.notas || 'Sin notas registradas.'}
                  </p>
                </Card>
              </div>
            </div>

            {/* ════ Fila inferior: historial (ancho completo) ════ */}
            <div className="mt-5">
              <Card title="Historial de citas" icon={ClipboardList}>
                <div className="space-y-2">
                  {(HISTORIAL[paciente.id] ?? []).map((h, i) => (
                    <div key={i} className="flex items-center justify-between rounded-xl px-4 py-2.5 bg-white/60">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.12)' }}>
                          <User className="w-4 h-4" style={{ color: '#C9A227' }} />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-800 truncate">{h.motivo}</p>
                          <p className="text-xs text-gray-400">{h.fecha} · {h.doctor}</p>
                        </div>
                      </div>
                      <span className={`badge ${estadoChip[h.estado]}`}>{h.estado}</span>
                    </div>
                  ))}
                  {(HISTORIAL[paciente.id] ?? []).length === 0 && (
                    <p className="text-sm text-gray-400 italic py-3 text-center">Sin citas registradas todavía.</p>
                  )}
                </div>
              </Card>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
