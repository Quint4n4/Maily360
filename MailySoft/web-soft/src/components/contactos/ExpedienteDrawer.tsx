import { motion, AnimatePresence } from 'framer-motion'
import {
  X, Phone, Mail, Fingerprint, Pencil, CalendarPlus,
  CalendarClock, StickyNote, ClipboardList, UserX, Loader2, AlertTriangle, User,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import { initialsOf, edad } from '../../lib/paciente'
import { useUploadPatientAvatar } from '../../hooks/pacientes'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import { formatFechaHora } from '../../lib/fecha'
import { ApiError } from '../../lib/http'
import type { Appointment, AppointmentStatus } from '../../types/agenda'
import AvatarUploader from '../common/AvatarUploader'

/** Estilo del chip de estado de una cita. */
function estadoChip(s: AppointmentStatus): { bg: string; color: string } {
  if (s === 'attended') return { bg: '#DCF3E6', color: '#1F6E47' }
  if (s === 'confirmed' || s === 'arrived' || s === 'in_progress') return { bg: '#E7F6EE', color: '#2E7D5B' }
  if (s === 'cancelled' || s === 'no_show') return { bg: '#FDE8E8', color: '#C0392B' }
  return { bg: '#FBF1D9', color: '#9A7B1E' } // scheduled
}
/** Estados terminales/no-activos: no cuentan como "próxima cita". */
const ESTADOS_INACTIVOS = new Set<AppointmentStatus>(['attended', 'cancelled', 'no_show'])

interface ExpedienteDrawerProps {
  paciente: PatientOut | null
  onClose: () => void
  verClinico?: boolean
  /** Si se puede editar/dar de baja (según rol). */
  puedeEditar?: boolean
  onEditar?: () => void
  onDarDeBaja?: () => void
  dandoDeBaja?: boolean
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

export default function ExpedienteDrawer({
  paciente, onClose, verClinico = true,
  puedeEditar = false, onEditar, onDarDeBaja, dandoDeBaja = false,
}: ExpedienteDrawerProps) {
  const years = paciente ? edad(paciente.date_of_birth ?? '') : null
  const subirAvatar = useUploadPatientAvatar()
  const onAvatarFile = (file: File) => {
    if (!paciente) return
    subirAvatar.mutate({ id: paciente.id, file }, {
      onError: e => {
        const d = e instanceof ApiError ? e.body?.detail : null
        window.alert(Array.isArray(d) ? d.join(' ') : (d ?? 'No se pudo subir la imagen.'))
      },
    })
  }

  // Citas reales del paciente (próxima + historial). Se refresca al cambiar estados.
  const { data: citasData, isLoading: citasLoading } = useAppointmentsForPatient(paciente?.id ?? null)
  const citas: Appointment[] = citasData?.results ?? []
  const historial = [...citas].sort((a, b) => b.starts_at.localeCompare(a.starts_at))
  const proxima: Appointment | null = [...citas]
    .filter(c => !ESTADOS_INACTIVOS.has(c.status))
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0] ?? null
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

            {/* Aviso de expediente provisional */}
            {paciente.is_provisional && (
              <div className="flex items-start gap-3 rounded-2xl px-5 py-4 mb-5" style={{ background: '#FBF1D9', border: '1px solid rgba(201,162,39,0.4)' }}>
                <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0" style={{ color: '#9A7B1E' }} />
                <div>
                  <p className="text-sm font-semibold" style={{ color: '#9A7B1E' }}>Expediente provisional</p>
                  <p className="text-xs" style={{ color: '#9A7B1E' }}>
                    Este paciente se creó al agendar con datos mínimos. Falta completar su información personal
                    (fecha de nacimiento, sexo, contacto). {puedeEditar ? 'Usa “Editar” para completarlo.' : ''}
                  </p>
                </div>
              </div>
            )}

            {/* ════ Grid principal: cards alrededor del rostro ════ */}
            <div className="grid gap-5 items-stretch" style={{ gridTemplateColumns: '1fr 1.15fr 1fr' }}>

              {/* ── Columna izquierda ── */}
              <div className="space-y-5">
                <Card title="Contacto" icon={Phone}>
                  <div className="space-y-2.5">
                    <div className="flex items-center gap-2.5">
                      <Phone className="w-4 h-4 text-gray-400 shrink-0" />
                      <span className="text-sm text-gray-800">{paciente.phone || '—'}</span>
                    </div>
                    <div className="flex items-center gap-2.5">
                      <Mail className="w-4 h-4 text-gray-400 shrink-0" />
                      <span className="text-sm text-gray-800 truncate">{paciente.email || '—'}</span>
                    </div>
                  </div>
                </Card>

                <Card title="Identificación" icon={Fingerprint}>
                  <Linea label="CURP" value={paciente.curp} />
                  <Linea label="Nacimiento" value={paciente.date_of_birth ?? ''} />
                  <Linea label="Edad" value={years !== null ? `${years} años` : '—'} />
                  <Linea label="Sexo" value={paciente.sex_display || '—'} />
                </Card>
              </div>

              {/* ── Centro: iniciales ── */}
              <div className="flex flex-col items-center text-center justify-start pt-2">
                <div className="relative mb-4">
                  {/* anillo dorado decorativo */}
                  <div className="absolute -inset-3 rounded-full"
                    style={{ background: 'conic-gradient(from 120deg, #E8C766, #C9A227, #F5E6B8, #C9A227, #E8C766)', filter: 'blur(10px)', opacity: 0.55 }} />
                  {/* foto o iniciales (editable) */}
                  <AvatarUploader
                    src={paciente.avatar}
                    initials={initialsOf(paciente)}
                    size={176}
                    editable={puedeEditar}
                    uploading={subirAvatar.isPending}
                    onFile={onAvatarFile}
                  />
                </div>

                <h2 className="text-2xl font-bold text-gray-900 leading-tight">{paciente.full_name}</h2>
                <p className="text-sm text-gray-500 mt-0.5">{paciente.record_number}</p>
                <span className={`badge mt-2 ${paciente.is_active ? 'badge-success' : 'badge-neutral'}`}>
                  {paciente.is_active ? 'Activo' : 'Inactivo'}
                </span>

                <div className="flex gap-3 mt-5 w-full max-w-[280px]">
                  <button
                    onClick={onEditar}
                    disabled={!puedeEditar}
                    className="btn-secondary flex-1 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <Pencil className="w-4 h-4" /> Editar
                  </button>
                  <button
                    className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                    style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
                  >
                    <CalendarPlus className="w-4 h-4" /> Agendar
                  </button>
                </div>

                {/* Dar de baja (solo si está activo y el rol puede editar) */}
                {puedeEditar && paciente.is_active && (
                  <button
                    onClick={onDarDeBaja}
                    disabled={dandoDeBaja}
                    className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-red-600 hover:text-red-700 hover:underline transition-colors disabled:opacity-60"
                  >
                    {dandoDeBaja
                      ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Dando de baja…</>
                      : <><UserX className="w-3.5 h-3.5" /> Dar de baja</>}
                  </button>
                )}
              </div>

              {/* ── Columna derecha ── */}
              <div className="space-y-5">
                <Card title="Próxima cita" icon={CalendarClock}>
                  {citasLoading ? (
                    <p className="text-sm text-gray-400 italic">Cargando…</p>
                  ) : proxima ? (
                    <div>
                      <p className="text-base font-bold text-gray-900">{formatFechaHora(proxima.starts_at)}</p>
                      <p className="text-sm text-gray-500 mt-0.5">
                        {proxima.doctor.full_name}{proxima.consultorio ? ` · ${proxima.consultorio.name}` : ''}
                      </p>
                      <span className="badge mt-2" style={{ background: estadoChip(proxima.status).bg, color: estadoChip(proxima.status).color }}>
                        {proxima.status_display}
                      </span>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-400 italic">Sin cita próxima.</p>
                  )}
                </Card>

                {verClinico && (
                  <Card title="Notas" icon={StickyNote}>
                    <p className="text-sm text-gray-600 leading-relaxed">
                      {paciente.notes || 'Sin notas registradas.'}
                    </p>
                  </Card>
                )}
              </div>
            </div>

            {/* ════ Fila inferior: historial de citas (administrativo — lo ve también recepción) ════ */}
            <div className="mt-5">
                <Card title="Historial de citas" icon={ClipboardList}>
                  {citasLoading ? (
                    <p className="text-sm text-gray-400 italic py-3 text-center">Cargando…</p>
                  ) : historial.length === 0 ? (
                    <p className="text-sm text-gray-400 italic py-3 text-center">Sin citas registradas todavía.</p>
                  ) : (
                    <div className="space-y-2">
                      {historial.map(h => {
                        const chip = estadoChip(h.status)
                        const motivo = h.appointment_type?.name || h.reason || 'Cita'
                        return (
                          <div key={h.id} className="flex items-center justify-between rounded-xl px-4 py-2.5 bg-white/60">
                            <div className="flex items-center gap-3 min-w-0">
                              <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.12)' }}>
                                <User className="w-4 h-4" style={{ color: '#C9A227' }} />
                              </div>
                              <div className="min-w-0">
                                <p className="text-sm font-medium text-gray-800 truncate">{motivo}</p>
                                <p className="text-xs text-gray-400">{formatFechaHora(h.starts_at)} · {h.doctor.full_name}</p>
                              </div>
                            </div>
                            <span className="badge shrink-0 ml-2" style={{ background: chip.bg, color: chip.color }}>{h.status_display}</span>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </Card>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
