import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Check, MessageCircle, MapPin, FileText, Stethoscope, User, AlertCircle, Loader2, UserX, RotateCcw, CalendarClock, Video, FolderOpen, ScrollText, FileDown } from 'lucide-react'
import NotasHilo from './NotasHilo'
import { useDownloadQuotePdf } from '../../hooks/finanzas'
import { formatMoney } from '../../lib/format'

export type EstadoCita =
  | 'agendada' | 'confirmada' | 'llego' | 'en_consulta' | 'atendida' | 'cancelada' | 'no_asistio'

export interface RecordatorioVista {
  texto: string
  fecha: string
  estado: string
}

/** Cotización vinculada a la cita (resumen para mostrar + descargar PDF). */
export interface CotizacionVista {
  id: string
  total: number | string
  statusDisplay: string
}

export interface CitaDetalle {
  id: string
  paciente: string
  /** Id del paciente — para abrir su expediente desde la agenda. */
  pacienteId: string
  doctor: string
  consultorioName: string
  consultorioColor: string
  modalidad: string
  horario: string   // "9:00 – 10:00"
  fecha: string     // "Jueves 4 de Junio, 2026"
  motivo: string
  especialidad: string
  notas: string
  estadoInicial: EstadoCita
  recordatorios?: RecordatorioVista[]
  /** Cotización vinculada (o null si la cita no tiene cotización). */
  cotizacion?: CotizacionVista | null
}

interface Props {
  cita: CitaDetalle | null
  onClose: () => void
  /** Puede mover estados operativos (En sala/En consulta/Atendida/No asistió). Incluye enfermería. */
  puedeCambiarEstado?: boolean
  /** Puede CANCELAR la cita. Excluye enfermería (el backend también lo bloquea). */
  puedeCancelar?: boolean
  /** Puede reagendar/reactivar (acciones de agendado). Excluye enfermería. */
  puedeAgendar?: boolean
  onCambiarEstado?: (nuevo: EstadoCita) => void
  cambiando?: boolean
  /** Reactivar una cita cancelada (mismo horario). */
  onReactivar?: () => void
  reactivando?: boolean
  /** Abrir el modal de reagendar (nuevo día/hora). */
  onReagendar?: () => void
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
/** Botón para AVANZAR al siguiente paso del flujo. */
const SIGUIENTE: Partial<Record<EstadoCita, { label: string; next: EstadoCita }>> = {
  agendada:    { label: 'Confirmar cita',   next: 'confirmada' },
  confirmada:  { label: 'Marcar llegada',   next: 'llego' },
  llego:       { label: 'Iniciar consulta', next: 'en_consulta' },
  en_consulta: { label: 'Marcar atendida',  next: 'atendida' },
}
/** Transiciones válidas (espejo de VALID_TRANSITIONS del backend). */
const TRANSICIONES: Record<EstadoCita, EstadoCita[]> = {
  agendada:    ['confirmada', 'cancelada', 'no_asistio'],
  confirmada:  ['llego', 'cancelada', 'no_asistio'],
  llego:       ['en_consulta', 'cancelada', 'no_asistio'],
  en_consulta: ['atendida'],
  atendida:    [],
  cancelada:   [],
  no_asistio:  [],
}

function recMeta(estado: string): { bg: string; color: string } {
  const e = estado.toLowerCase()
  if (e.includes('env')) return { bg: '#E7F6EE', color: '#2E7D5B' }
  if (e.includes('pend')) return { bg: '#FBF1D9', color: '#9A7B1E' }
  if (e.includes('fall') || e.includes('cancel')) return { bg: '#FDE8E8', color: '#C0392B' }
  return { bg: '#F3F4F6', color: '#6B7280' }
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

export default function DetalleCitaModal({ cita, onClose, puedeCambiarEstado = false, puedeCancelar = false, puedeAgendar = false, onCambiarEstado, cambiando = false, onReactivar, reactivando = false, onReagendar }: Props) {
  const navigate = useNavigate()
  const [estado, setEstado] = useState<EstadoCita>('agendada')
  const downloadPdf = useDownloadQuotePdf()
  useEffect(() => { if (cita) setEstado(cita.estadoInicial) }, [cita])

  if (!cita) return <AnimatePresence />

  const ini = cita.paciente.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
  const currentIdx = FLUJO.indexOf(estado)
  const terminalCancel = estado === 'cancelada' || estado === 'no_asistio'
  const terminal = estado === 'atendida' || terminalCancel
  const siguiente = SIGUIENTE[estado]
  const permitidas = TRANSICIONES[estado]
  const m = META[estado]
  const esReagendable = estado === 'agendada' || estado === 'confirmada'
  const recordatorios = cita.recordatorios ?? []

  const cambiar = (nuevo: EstadoCita) => {
    if (cambiando) return
    onCambiarEstado?.(nuevo)
  }

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
                <button
                  onClick={() => { navigate(`/contactos?paciente=${cita.pacienteId}`); onClose() }}
                  className="mt-1.5 inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 transition-colors"
                >
                  <FolderOpen className="w-3.5 h-3.5" /> Ver expediente
                </button>
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
                <Dato icon={User}        label="Doctor"       value={cita.doctor} />
                <Dato icon={Video}       label="Modalidad"    value={cita.modalidad} />
                <Dato icon={MapPin}      label="Consultorio"  value={cita.consultorioName} dot={cita.consultorioColor} />
                <Dato icon={FileText}    label="Motivo"       value={cita.motivo} />
                <Dato icon={Stethoscope} label="Especialidad" value={cita.especialidad} />
                {cita.notas && <Dato icon={FileText} label="Notas" value={cita.notas} />}

                {/* Cotización vinculada — solo si la cita tiene una. */}
                {cita.cotizacion && (
                  <div className="mt-3 rounded-xl p-3 flex items-center justify-between gap-3"
                    style={{ background: 'rgba(201,162,39,0.08)', border: '1px solid rgba(201,162,39,0.3)' }}>
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.16)' }}>
                        <ScrollText className="w-4 h-4" style={{ color: '#C9A227' }} />
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs text-gray-400">Cotización</p>
                        <p className="text-sm font-semibold text-gray-800">
                          {formatMoney(cita.cotizacion.total)} · {cita.cotizacion.statusDisplay}
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={() => cita.cotizacion && downloadPdf.mutate(cita.cotizacion.id)}
                      disabled={downloadPdf.isPending}
                      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors hover:brightness-95 disabled:opacity-60 shrink-0"
                      style={{ color: '#9A7B1E', background: 'rgba(201,162,39,0.16)' }}
                      title="Descargar PDF de la cotización"
                    >
                      {downloadPdf.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
                      PDF
                    </button>
                  </div>
                )}
              </div>

              {/* Recordatorios (reales) */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-2">Recordatorios</p>
                <div className="space-y-2.5">
                  {recordatorios.length === 0 && (
                    <p className="text-sm text-gray-400 italic">Sin recordatorios programados.</p>
                  )}
                  {recordatorios.map((r, i) => {
                    const rm = recMeta(r.estado)
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

            {/* ── Notas del equipo (hilo colaborativo) ── */}
            <div className="px-7 pb-5">
              <NotasHilo kind="cita" itemId={cita.id} />
            </div>

            {/* ── Acciones ── */}
            <div className="px-7 py-4 border-t border-gray-100 bg-gray-50 flex items-center justify-between gap-3">
              {(!puedeCambiarEstado && !puedeAgendar) ? (
                <p className="text-sm text-gray-500 w-full text-center">Estás viendo esta cita en modo solo lectura.</p>
              ) : estado === 'cancelada' ? (
                <>
                  <p className="text-sm font-medium" style={{ color: '#C0392B' }}>Cita cancelada</p>
                  <div className="flex items-center gap-2.5">
                    {puedeAgendar && onReagendar && (
                      <button onClick={onReagendar} disabled={reactivando}
                        className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:bg-gray-200 disabled:opacity-50"
                        style={{ color: '#6B7280', background: '#F3F4F6' }}>
                        <CalendarClock className="w-4 h-4" /> Reagendar
                      </button>
                    )}
                    {puedeAgendar && onReactivar && (
                      <button onClick={onReactivar} disabled={reactivando}
                        className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                        style={{ background: '#2E7D5B', boxShadow: '0 4px 14px rgba(46,125,91,0.4)' }}>
                        {reactivando ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />} Reactivar cita
                      </button>
                    )}
                  </div>
                </>
              ) : terminal ? (
                <p className="text-sm font-medium w-full text-center" style={{ color: m.color }}>
                  {estado === 'atendida' ? '✓ Cita atendida' : `Cita ${m.label.toLowerCase()}`}
                </p>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    {puedeCancelar && permitidas.includes('cancelada') && (
                      <button onClick={() => cambiar('cancelada')} disabled={cambiando}
                        className="px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:brightness-95 disabled:opacity-50"
                        style={{ color: '#C0392B', background: '#FDE8E8' }}>
                        Cancelar
                      </button>
                    )}
                    {puedeCambiarEstado && permitidas.includes('no_asistio') && (
                      <button onClick={() => cambiar('no_asistio')} disabled={cambiando}
                        className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:bg-gray-200 disabled:opacity-50"
                        style={{ color: '#6B7280', background: '#F3F4F6' }}>
                        <UserX className="w-4 h-4" /> No asistió
                      </button>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    {puedeAgendar && esReagendable && onReagendar && (
                      <button onClick={onReagendar} disabled={cambiando}
                        className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:bg-gray-200 disabled:opacity-50"
                        style={{ color: '#6B7280', background: '#F3F4F6' }}>
                        <CalendarClock className="w-4 h-4" /> Reagendar
                      </button>
                    )}
                    {puedeCambiarEstado && siguiente && (
                      <button onClick={() => cambiar(siguiente.next)} disabled={cambiando}
                        className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                        style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                        {cambiando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                        {siguiente.label}
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
