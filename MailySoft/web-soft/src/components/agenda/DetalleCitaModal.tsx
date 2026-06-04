import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Check, MessageCircle, RotateCcw, MapPin, FileText, Stethoscope, User, AlertCircle } from 'lucide-react'

export type EstadoCita =
  | 'agendada' | 'confirmada' | 'llego' | 'en_consulta' | 'atendida' | 'cancelada' | 'no_asistio'

export interface CitaDetalle {
  paciente: string
  doctor: string
  consultorioName: string
  consultorioColor: string
  horario: string   // "9:00 – 10:00"
  fecha: string     // "Jueves 4 de Junio, 2026"
  motivo: string
  especialidad: string
  notas: string
  estadoInicial: EstadoCita
}

const FLUJO: EstadoCita[] = ['agendada', 'confirmada', 'llego', 'en_consulta', 'atendida']
const PASO_LABEL: Record<string, string> = {
  agendada: 'Agendada', confirmada: 'Confirmada', llego: 'Llegó',
  en_consulta: 'En consulta', atendida: 'Atendida',
}
const META: Record<EstadoCita, { label: string; bg: string; color: string }> = {
  agendada:    { label: 'Agendada',    bg: '#F3F4F6', color: '#6B7280' },
  confirmada:  { label: 'Confirmada',  bg: '#E7F6EE', color: '#2E7D5B' },
  llego:       { label: 'Llegó',       bg: '#E8F0FB', color: '#3A6EA5' },
  en_consulta: { label: 'En consulta', bg: '#FBF1D9', color: '#9A7B1E' },
  atendida:    { label: 'Atendida',    bg: '#DCF3E6', color: '#1F6E47' },
  cancelada:   { label: 'Cancelada',   bg: '#FDE8E8', color: '#C0392B' },
  no_asistio:  { label: 'No asistió',  bg: '#FDE8E8', color: '#C0392B' },
}
const SIGUIENTE: Partial<Record<EstadoCita, { label: string; next: EstadoCita }>> = {
  agendada:    { label: 'Confirmar cita',  next: 'confirmada' },
  confirmada:  { label: 'Marcar llegada',  next: 'llego' },
  llego:       { label: 'Iniciar consulta', next: 'en_consulta' },
  en_consulta: { label: 'Marcar atendida', next: 'atendida' },
}

const RECORDATORIOS = [
  { texto: '24 horas antes', fecha: '03 jun 2026 · 11:00', estado: 'Enviado' },
  { texto: '2 horas antes',  fecha: '04 jun 2026 · 07:00', estado: 'Pendiente' },
]
const REC_META: Record<string, { bg: string; color: string }> = {
  Enviado:   { bg: '#E7F6EE', color: '#2E7D5B' },
  Pendiente: { bg: '#FBF1D9', color: '#9A7B1E' },
  Falló:     { bg: '#FDE8E8', color: '#C0392B' },
}

function Dato({ icon: Icon, label, value, dot }: { icon: typeof User; label: string; value: string; dot?: string }) {
  return (
    <div className="flex items-start gap-3 py-2">
      <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.12)' }}>
        <Icon className="w-4 h-4" style={{ color: '#C9A227' }} />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-gray-400">{label}</p>
        <p className="text-sm text-gray-800 font-medium flex items-center gap-1.5">
          {dot && <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: dot }} />}
          {value || '—'}
        </p>
      </div>
    </div>
  )
}

export default function DetalleCitaModal({ cita, onClose }: { cita: CitaDetalle | null; onClose: () => void }) {
  const [estado, setEstado] = useState<EstadoCita>('agendada')
  useEffect(() => { if (cita) setEstado(cita.estadoInicial) }, [cita])

  if (!cita) return <AnimatePresence />

  const ini = cita.paciente.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
  const currentIdx = FLUJO.indexOf(estado)
  const terminalCancel = estado === 'cancelada' || estado === 'no_asistio'
  const terminal = estado === 'atendida' || terminalCancel
  const siguiente = SIGUIENTE[estado]
  const m = META[estado]

  return (
    <AnimatePresence>
      {cita && (
        <motion.div
          className="fixed inset-0 z-50 overflow-y-auto p-4 md:p-8 flex items-start justify-center"
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-3xl rounded-3xl overflow-hidden bg-white shadow-2xl"
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* ── Encabezado ── */}
            <div className="px-7 py-5 flex items-start gap-4 border-b border-gray-100">
              <div className="w-14 h-14 rounded-full flex items-center justify-center text-lg font-bold shrink-0"
                style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
                {ini}
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-xl font-bold text-gray-900 truncate">{cita.paciente}</h2>
                <p className="text-sm text-gray-500">{cita.fecha} · {cita.horario}</p>
              </div>
              <span className="px-3 py-1 rounded-full text-xs font-semibold shrink-0" style={{ background: m.bg, color: m.color }}>
                {m.label}
              </span>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors shrink-0">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* ── Línea de estados ── */}
            {!terminalCancel ? (
              <div className="px-7 py-5 border-b border-gray-100">
                <div className="flex items-center">
                  {FLUJO.map((paso, i) => {
                    const done = i <= currentIdx
                    const isCurrent = i === currentIdx
                    return (
                      <div key={paso} className="flex items-center flex-1 last:flex-none">
                        <div className="flex flex-col items-center">
                          <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-colors"
                            style={{
                              background: done ? '#C9A227' : '#F3F4F6',
                              color: done ? '#fff' : '#9CA3AF',
                              boxShadow: isCurrent ? '0 0 0 4px rgba(201,162,39,0.25)' : 'none',
                            }}>
                            {done ? <Check className="w-4 h-4" /> : i + 1}
                          </div>
                          <span className="text-[10px] mt-1.5 font-medium whitespace-nowrap"
                            style={{ color: done ? '#9A7B1E' : '#9CA3AF' }}>
                            {PASO_LABEL[paso]}
                          </span>
                        </div>
                        {i < FLUJO.length - 1 && (
                          <div className="flex-1 h-0.5 mx-1 mb-5 rounded" style={{ background: i < currentIdx ? '#C9A227' : '#E5E7EB' }} />
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            ) : (
              <div className="px-7 py-4 border-b border-gray-100">
                <div className="flex items-center gap-2.5 rounded-xl px-4 py-3" style={{ background: '#FDE8E8', border: '1px solid #F5C6C6' }}>
                  <AlertCircle className="w-4 h-4 shrink-0" style={{ color: '#C0392B' }} />
                  <p className="text-sm font-medium" style={{ color: '#C0392B' }}>
                    Esta cita está marcada como «{m.label}».
                  </p>
                </div>
              </div>
            )}

            {/* ── Cuerpo: detalles + recordatorios ── */}
            <div className="grid md:grid-cols-2 gap-6 px-7 py-6">
              {/* Detalles */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-2">Detalles de la cita</p>
                <Dato icon={User}       label="Doctor"       value={cita.doctor} />
                <Dato icon={MapPin}     label="Consultorio"  value={cita.consultorioName} dot={cita.consultorioColor} />
                <Dato icon={FileText}   label="Motivo"       value={cita.motivo} />
                <Dato icon={Stethoscope} label="Especialidad" value={cita.especialidad} />
                {cita.notas && <Dato icon={FileText} label="Notas" value={cita.notas} />}
              </div>

              {/* Recordatorios WhatsApp */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-2">Recordatorios por WhatsApp</p>
                <div className="space-y-2.5">
                  {RECORDATORIOS.map((r, i) => {
                    const rm = REC_META[r.estado]
                    return (
                      <div key={i} className="flex items-center justify-between rounded-xl px-4 py-3 bg-gray-50 border border-gray-100">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ background: '#E7F6EE' }}>
                            <MessageCircle className="w-4 h-4" style={{ color: '#25D366' }} />
                          </div>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-800">{r.texto}</p>
                            <p className="text-xs text-gray-400">{r.fecha}</p>
                          </div>
                        </div>
                        <span className="px-2.5 py-0.5 rounded-full text-xs font-medium shrink-0" style={{ background: rm.bg, color: rm.color }}>
                          {r.estado}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            {/* ── Acciones ── */}
            <div className="px-7 py-4 border-t border-gray-100 bg-gray-50 flex items-center justify-between gap-3">
              <div>
                {!terminal && (
                  <button onClick={() => setEstado('cancelada')}
                    className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:brightness-95"
                    style={{ color: '#C0392B', background: '#FDE8E8' }}>
                    Cancelar cita
                  </button>
                )}
              </div>
              <div className="flex items-center gap-3">
                {estado === 'atendida' && (
                  <span className="text-sm font-semibold" style={{ color: '#1F6E47' }}>✓ Cita atendida</span>
                )}
                {!terminal && (
                  <button onClick={() => alert('Reagendar (demo)')} className="btn-secondary">
                    <RotateCcw className="w-4 h-4" /> Reagendar
                  </button>
                )}
                {siguiente && (
                  <button onClick={() => setEstado(siguiente.next)}
                    className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                    style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                    <Check className="w-4 h-4" /> {siguiente.label}
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
