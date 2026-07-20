import { useState } from 'react'
import { ChevronLeft, ChevronRight, CalendarCheck, Cake, FileText, CircleDollarSign, UserX, Loader2, Users, Ban, Stethoscope, Phone, Video, MapPin, Clock, Building2, type LucideIcon } from 'lucide-react'
import Topbar from '../components/Topbar'
import CrearEventoModal from '../components/agenda/CrearEventoModal'
import DetalleCitaModal, { CitaDetalle, EstadoCita } from '../components/agenda/DetalleCitaModal'
import EventoDetalleModal from '../components/agenda/EventoDetalleModal'
import RecordatoriosWidget from '../components/agenda/RecordatoriosWidget'
import ReagendarModal from '../components/agenda/ReagendarModal'
import { useAppointmentsForDay, useConsultorios, useChangeAppointmentStatus, useAgendaBlocksForDay, useReactivateAppointment, useDoctors } from '../hooks/agenda'
import {
  addDays, addMonths, formatLargo, formatMedio, formatFechaHora, localHM, localHHMM12,
  durationMin, monthGrid, sameDay, toDayKey, to12h,
} from '../lib/fecha'
import { ApiError } from '../lib/http'
import type { Appointment, AppointmentStatus, AgendaBlock, AppointmentModality } from '../types/agenda'
import { useRole } from '../auth/RoleContext'
import { useAuth } from '../auth/AuthContext'
import { useSucursalActiva } from '../auth/SucursalContext'
import { puedeAgendar, puedeCambiarEstadoCita, puedeCancelarCita } from '../auth/permisos'
import { useAviso } from '../components/common/DialogProvider'

/* ─── Rejilla horaria 9:00–17:30 ─────────────────────────────────────────── */
const SLOTS = Array.from({ length: 18 }, (_, i) => {
  const h = 9 + Math.floor(i / 2)
  const m = i % 2 === 0 ? 0 : 30
  const label = `${h}:${m === 0 ? '00' : '30'}` // valor REAL en 24h (para guardar)
  return { h, m, label, display: to12h(label) } // texto en 12h (solo para mostrar)
})
const ROW_H = 60
const DIAS_SEMANA = ['L', 'M', 'M', 'J', 'V', 'S', 'D']

/* Líneas de la cuadrícula — tono cálido VISIBLE (antes eran blancas casi invisibles). */
const GRID_LINE = 'rgba(120,113,108,0.30)'
const GRID_LINE_STRONG = 'rgba(120,113,108,0.45)'

const QUICK_LINKS = [
  { icon: Cake,             label: 'Cumpleaños',           color: '#C9A227' },
  { icon: FileText,         label: 'Hoja diaria',          color: '#9A7B1E' },
  { icon: CircleDollarSign, label: 'Cuentas por cobrar',   color: '#C0392B' },
  { icon: UserX,            label: 'Contactos cancelados', color: '#C0392B' },
]

/* Mapea el estado del backend al del modal de detalle. */
const ESTADO_MAP: Record<AppointmentStatus, EstadoCita> = {
  scheduled: 'agendada', confirmed: 'confirmada', arrived: 'llego',
  in_progress: 'en_consulta', attended: 'atendida', cancelled: 'cancelada', no_show: 'no_asistio',
}
/* Y de vuelta: estado del modal → estado del backend (para el POST /estado/). */
const STATUS_MAP: Record<EstadoCita, AppointmentStatus> = {
  agendada: 'scheduled', confirmada: 'confirmed', llego: 'arrived',
  en_consulta: 'in_progress', atendida: 'attended', cancelada: 'cancelled', no_asistio: 'no_show',
}
/* Estilo del chip de estado sobre la tarjeta de cita. */
function estiloEstado(s: AppointmentStatus): { bg: string; color: string } {
  if (s === 'confirmed' || s === 'attended' || s === 'arrived') return { bg: '#E7F6EE', color: '#2E7D5B' }
  if (s === 'cancelled' || s === 'no_show') return { bg: '#FDE8E8', color: '#C0392B' }
  return { bg: '#FBF1D9', color: '#9A7B1E' }
}

/* Icono según la modalidad de la cita (presencial vs fuera de consultorio). */
function iconoModalidad(m: AppointmentModality): LucideIcon {
  if (m === 'phone') return Phone
  if (m === 'video') return Video
  if (m === 'offsite') return MapPin
  return Stethoscope // office / consultorio
}

const NONE_COL = '__none__'

export default function AgendaPage() {
  const [selectedDate, setSelectedDate] = useState(() => new Date())
  const [modalOpen, setModalOpen] = useState(false)
  // Confirmación al agendar en un horario que ya pasó (modal glass, no alert nativo).
  const [pendientePasado, setPendientePasado] = useState<{ hora: string; col: { id: string; name: string; color: string } } | null>(null)
  const [slotSel, setSlotSel] = useState<{ hora: string; consultorioId: string | null; consultorioName: string; modality: AppointmentModality }>(
    { hora: '09:00', consultorioId: null, consultorioName: '', modality: 'office' },
  )
  const [citaSel, setCitaSel] = useState<Appointment | null>(null)
  const [eventoSel, setEventoSel] = useState<AgendaBlock | null>(null)
  const [reagendarCita, setReagendarCita] = useState<Appointment | null>(null)
  const [modalMode, setModalMode] = useState<'cita' | 'block' | 'meeting'>('cita')
  const { role } = useRole()
  const { user } = useAuth()
  // Sede activa (multi-sede F2). El calendario ya viene filtrado por ella desde el
  // backend (header X-Sucursal-Id); aquí solo la nombramos en la UI.
  const { activeSucursal } = useSucursalActiva()
  const sedeNombre = activeSucursal?.name ?? ''
  const agendar = puedeAgendar(role)           // crear/reagendar/eventos (NO enfermería)
  const cambiarStatus = puedeCambiarEstadoCita(role) // cambiar estado (incluye enfermería)
  const cancelar = puedeCancelarCita(role)     // cancelar cita (NO enfermería)
  const gestor = role === 'owner' || role === 'admin'
  const soyDoctor = !!user?.doctor_id
  const cambiarEstado = useChangeAppointmentStatus()
  const reactivar = useReactivateAppointment()
  const aviso = useAviso()

  const dayKey = toDayKey(selectedDate)
  // Un horario "ya pasó" si su hora de inicio es anterior a ahora (no se agenda en el pasado).
  const ahora = new Date()
  const slotEsPasado = (s: { h: number; m: number }): boolean => {
    const dt = new Date(selectedDate)
    dt.setHours(s.h, s.m, 0, 0)
    return dt.getTime() < ahora.getTime()
  }
  const { data: apptData, isLoading: loadingCitas, isError } = useAppointmentsForDay(dayKey)
  const { data: consData, isLoading: loadingCons } = useConsultorios()
  const { data: eventos } = useAgendaBlocksForDay(dayKey)
  const { data: docData } = useDoctors()

  // Consultorios asignados al médico logueado (si los tiene).
  const miDoctor = soyDoctor ? (docData?.results ?? []).find(d => d.id === user?.doctor_id) : undefined
  const misConsultorioIds = (miDoctor?.consultorios ?? []).map(c => c.id)
  const doctorRestringido = soyDoctor && misConsultorioIds.length > 0

  // Un médico restringido solo ve eventos de su alcance: de toda la clínica,
  // suyos, o de SUS consultorios. Así no se cuelan bandas de otros consultorios.
  const todosBloques: AgendaBlock[] = eventos ?? []
  const bloques: AgendaBlock[] = doctorRestringido
    ? todosBloques.filter(b =>
        (!b.doctor && !b.consultorio) ||
        b.doctor?.id === user?.doctor_id ||
        (!!b.consultorio && misConsultorioIds.includes(b.consultorio.id)))
    : todosBloques
  // Un médico solo ve SUS citas; el resto ve todas.
  const todasCitas: Appointment[] = apptData?.results ?? []
  const citas: Appointment[] = soyDoctor ? todasCitas.filter(a => a.doctor.id === user?.doctor_id) : todasCitas
  // Un médico con consultorios asignados solo ve ESOS consultorios; el resto, todos.
  const consultoriosActivos = (consData?.results ?? []).filter(c => c.is_active)
  const consultorios = doctorRestringido ? consultoriosActivos.filter(c => misConsultorioIds.includes(c.id)) : consultoriosActivos
  // Citas del médico logueado, ordenadas (para su cuadro "Mis citas de hoy").
  const misCitas = soyDoctor ? [...citas].sort((a, b) => a.starts_at.localeCompare(b.starts_at)) : []

  // Columnas del tablero = consultorios + una columna FIJA para citas no presenciales
  // (telefónica / video / fuera de la instalación) y cualquier cita sin sala.
  type Col = { id: string; name: string; color: string }
  const cols: Col[] = consultorios.map(c => ({ id: c.id, name: c.name, color: c.color_hex || '#C9A227' }))
  cols.push({ id: NONE_COL, name: 'Telemedicina / Externo', color: '#3A6EA5' })

  const colIndexDe = (a: Appointment): number => {
    const id = a.consultorio?.id
    const idx = cols.findIndex(c => c.id === id)
    if (idx >= 0) return idx
    return cols.findIndex(c => c.id === NONE_COL)
  }

  const abrirCrear = (hora: string, col: Col) => {
    if (!agendar) return
    const esTele = col.id === NONE_COL
    setSlotSel({
      hora: hora.length === 4 ? `0${hora}` : hora,
      consultorioId: esTele ? null : col.id,
      consultorioName: esTele ? '' : col.name,
      // La columna Telemedicina/Externo crea una cita NO presencial (sin consultorio).
      modality: esTele ? 'video' : 'office',
    })
    setModalMode('cita')
    setModalOpen(true)
  }

  const confirmarPasado = () => {
    const p = pendientePasado
    setPendientePasado(null)
    if (p) abrirCrear(p.hora, p.col)
  }

  // Mapea una cita real al shape de presentación del modal de detalle.
  const toDetalle = (a: Appointment): CitaDetalle => {
    const col = cols[colIndexDe(a)]
    return {
      id: a.id,
      paciente: a.patient.full_name,
      pacienteId: a.patient.id,
      doctor: a.doctor.full_name,
      consultorioName: a.consultorio?.name ?? 'Sin consultorio',
      consultorioColor: col?.color ?? '#C9A227',
      // Sede de la cita (multi-sede F2): null si la clínica no usa sucursales.
      sucursalName: a.sucursal?.name ?? null,
      modalidad: a.modality_display,
      horario: `${localHHMM12(a.starts_at)} – ${localHHMM12(a.ends_at)}`,
      fecha: formatLargo(selectedDate),
      tipoCita: a.appointment_type?.name ?? '',
      aQueVenia: a.reason,
      especialidad: a.specialty,
      notas: a.notes,
      estadoInicial: ESTADO_MAP[a.status],
      recordatorios: a.reminders.map(r => ({
        texto: r.channel_display,
        fecha: formatFechaHora(r.scheduled_at),
        estado: r.status_display,
      })),
      cotizacion: a.quote
        ? { id: a.quote.id, total: a.quote.total, statusDisplay: a.quote.status_display }
        : null,
    }
  }

  const handleCambiarEstado = (nuevo: EstadoCita) => {
    if (!citaSel) return
    cambiarEstado.mutate(
      { id: citaSel.id, status: STATUS_MAP[nuevo] },
      {
        onSuccess: (updated) => setCitaSel(updated),
        onError: (e) => {
          const detail = e instanceof ApiError ? e.body?.detail : null
          const msg = Array.isArray(detail) ? detail.join(' ') : (detail ?? 'No se pudo cambiar el estado de la cita.')
          void aviso({ mensaje: msg, tipo: 'error' })
        },
      },
    )
  }

  const gridCols = `60px repeat(${Math.max(1, cols.length)}, minmax(132px, 1fr))`

  return (
    <div className="min-h-screen relative">
      {/* Fondo */}
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="agenda" />

      <div className="flex flex-col lg:flex-row gap-4 lg:gap-5 p-3 sm:p-5 max-w-[1500px] mx-auto">

        {/* ════════ Panel izquierdo (en móvil va DEBAJO del horario) ════════ */}
        <aside className="w-full lg:w-80 lg:shrink-0 space-y-4 order-2 lg:order-none">

          {/* Calendario */}
          <div className="glass-card rounded-2xl p-5">
            <div className="flex items-center justify-between mb-4">
              <button onClick={() => setSelectedDate(d => addDays(d, -1))}
                className="p-1 rounded-lg hover:bg-white/40 text-gray-500" title="Día anterior">
                <ChevronLeft className="w-5 h-5" />
              </button>
              <span className="text-sm font-semibold text-gray-800">{formatMedio(selectedDate)}</span>
              <button onClick={() => setSelectedDate(d => addDays(d, 1))}
                className="p-1 rounded-lg hover:bg-white/40 text-gray-500" title="Día siguiente">
                <ChevronRight className="w-5 h-5" />
              </button>
            </div>

            <div className="grid grid-cols-7 gap-1 mb-1">
              {DIAS_SEMANA.map((d, i) => (
                <div key={i} className="text-center text-xs font-semibold text-gray-500 py-1">{d}</div>
              ))}
            </div>

            <div className="grid grid-cols-7 gap-1">
              {monthGrid(selectedDate).map((d, i) => (
                <div key={i} className="aspect-square flex items-center justify-center">
                  {d && (
                    <button
                      onClick={() => setSelectedDate(d)}
                      className="w-8 h-8 rounded-full text-sm flex items-center justify-center transition-colors hover:bg-white/50"
                      style={sameDay(d, selectedDate)
                        ? { background: '#C9A227', color: '#fff', fontWeight: 600 }
                        : sameDay(d, new Date())
                          ? { color: '#B8860B', fontWeight: 600, border: '1px solid rgba(201,162,39,0.5)' }
                          : { color: '#374151' }}
                    >
                      {d.getDate()}
                    </button>
                  )}
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between mt-4 pt-4 border-t border-white/40 text-sm">
              <button onClick={() => setSelectedDate(d => addMonths(d, -1))} className="text-gray-600 hover:text-gray-800">Mes ant.</button>
              <button onClick={() => setSelectedDate(new Date())} className="font-semibold" style={{ color: '#C9A227' }}>Hoy</button>
              <button onClick={() => setSelectedDate(d => addMonths(d, 1))} className="text-gray-600 hover:text-gray-800">Mes sig.</button>
            </div>
          </div>

          {/* Mis recordatorios (personal, del día seleccionado) */}
          <RecordatoriosWidget dayKey={dayKey} />

          {/* Médico → sus citas del día. Dueño/Admin → accesos rápidos. */}
          {soyDoctor ? (
            <div className="glass-card rounded-2xl overflow-hidden">
              <div className="px-5 py-3 border-b border-white/40 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                  <CalendarCheck className="w-4 h-4" style={{ color: '#C9A227' }} /> Mis citas de hoy
                </span>
                {misCitas.length > 0 && (
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: 'rgba(201,162,39,0.15)', color: '#B8860B' }}>{misCitas.length}</span>
                )}
              </div>
              {misCitas.length === 0 ? (
                <p className="px-5 py-6 text-center text-xs text-gray-400 italic">No tienes citas este día.</p>
              ) : (
                <div className="max-h-[320px] overflow-y-auto">
                  {misCitas.map((a, i) => {
                    const est = estiloEstado(a.status)
                    return (
                      <button key={a.id} onClick={() => setCitaSel(a)}
                        className="w-full flex items-center gap-3 px-5 py-3 hover:bg-white/40 transition-colors text-left"
                        style={{ borderTop: i > 0 ? '1px solid rgba(255,255,255,0.45)' : 'none' }}>
                        <span className="text-xs font-bold text-gray-700 tabular-nums shrink-0">{localHHMM12(a.starts_at)}</span>
                        <span className="flex-1 min-w-0">
                          <span className="block text-sm font-medium text-gray-800 truncate">{a.patient.full_name}</span>
                          <span className="block text-[11px] truncate" style={{ color: a.appointment_type?.color_hex || '#9CA3AF' }}>{a.appointment_type?.name || a.modality_display}</span>
                        </span>
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full shrink-0" style={{ background: est.bg, color: est.color }}>{a.status_display}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ) : gestor ? (
            <div className="glass-card rounded-2xl overflow-hidden">
              {QUICK_LINKS.map(({ icon: Icon, label, color }, i) => (
                <button key={label}
                  className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-white/40 transition-colors text-left"
                  style={{ borderTop: i > 0 ? '1px solid rgba(255,255,255,0.45)' : 'none' }}>
                  <Icon className="w-5 h-5 shrink-0" style={{ color }} />
                  <span className="text-sm font-medium" style={{ color }}>{label}</span>
                </button>
              ))}
            </div>
          ) : null}
        </aside>

        {/* ════════ Panel derecho — rejilla (en móvil va ARRIBA) ════════ */}
        <main className="glass-card flex-1 min-w-0 rounded-2xl overflow-hidden order-1 lg:order-none">

          {/* Título del día */}
          <div className="px-3 sm:px-5 py-3 border-b border-white/50 flex items-center justify-between gap-2">
            <div className="flex items-center gap-1 sm:gap-2 min-w-0">
              {/* Navegación de día (solo móvil; en escritorio se usa el calendario) */}
              <button onClick={() => setSelectedDate(d => addDays(d, -1))}
                className="lg:hidden p-1.5 -ml-1 rounded-lg hover:bg-white/40 text-gray-500 shrink-0" title="Día anterior">
                <ChevronLeft className="w-5 h-5" />
              </button>
              <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2 min-w-0">
                <CalendarCheck className="w-4 h-4 shrink-0" style={{ color: '#C9A227' }} />
                <span className="truncate">{formatLargo(selectedDate)}</span>
              </h2>
              <button onClick={() => setSelectedDate(d => addDays(d, 1))}
                className="lg:hidden p-1.5 rounded-lg hover:bg-white/40 text-gray-500 shrink-0" title="Día siguiente">
                <ChevronRight className="w-5 h-5" />
              </button>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {/* Sede activa: el calendario muestra SOLO esta sucursal. */}
              {sedeNombre && (
                <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold"
                  style={{ background: 'rgba(201,162,39,0.14)', color: '#9A7B1E' }}>
                  <Building2 className="w-3.5 h-3.5" /> {sedeNombre}
                </span>
              )}
              <span className="text-xs text-gray-500">
                {loadingCitas ? 'Cargando…' : `${citas.length} cita${citas.length === 1 ? '' : 's'}`}
              </span>
            </div>
          </div>

          {(loadingCons || loadingCitas) && (
            <div className="flex items-center justify-center gap-2 py-16 text-amber-700">
              <Loader2 className="w-5 h-5 animate-spin" /> Cargando agenda…
            </div>
          )}

          {isError && !loadingCitas && (
            <div className="py-16 text-center text-sm text-red-600">No se pudieron cargar las citas.</div>
          )}

          {!loadingCons && !loadingCitas && cols.length === 0 && (
            <div className="py-16 text-center text-sm text-gray-500">
              No hay consultorios configurados todavía. Créalos en el panel de Personal para poder agendar.
            </div>
          )}

          {!loadingCons && !loadingCitas && cols.length > 0 && (
            <div className="overflow-x-auto">
              {/* Encabezado de columnas */}
              <div className="grid border-b" style={{ gridTemplateColumns: gridCols, borderColor: GRID_LINE_STRONG }}>
                <div className="py-3 text-center text-sm font-bold text-gray-500">Hr.</div>
                {cols.map(c => (
                  <div key={c.id} className="py-3 px-1 text-center text-[13px] sm:text-[15px] font-semibold border-l" style={{ color: '#374151', borderColor: GRID_LINE_STRONG }}>
                    <span className="inline-flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ background: c.color }} />
                      {c.name}
                    </span>
                  </div>
                ))}
              </div>

              {/* Cuerpo */}
              <div className="relative grid" style={{ gridTemplateColumns: gridCols, gridAutoRows: `${ROW_H}px` }}>
                {SLOTS.map((s, r) => {
                  const pasado = slotEsPasado(s)
                  return (
                    <div key={`row-${r}`} className="contents">
                      <div className="flex items-start justify-center pt-1 text-xs sm:text-sm border-b"
                        style={{ gridColumn: 1, gridRow: r + 1, borderColor: GRID_LINE, color: pasado ? '#C4BFB6' : '#6B7280' }}>
                        {s.display}
                      </div>
                      {cols.map((c, ci) => {
                        const onCell = () => {
                          if (pasado) { setPendientePasado({ hora: s.label, col: c }); return }
                          abrirCrear(s.label, c)
                        }
                        return (
                          <button
                            key={`cell-${r}-${ci}`}
                            onClick={agendar ? onCell : undefined}
                            title={pasado ? 'Este horario ya pasó' : undefined}
                            className={`border-b border-l transition-colors ${agendar ? 'hover:bg-white/40 cursor-pointer' : 'cursor-default'}`}
                            style={{ gridColumn: ci + 2, gridRow: r + 1, borderColor: GRID_LINE, background: pasado ? 'rgba(120,113,108,0.05)' : undefined }}
                          />
                        )
                      })}
                    </div>
                  )
                })}

                {/* Bloqueos / Reuniones (bandas) */}
                {bloques.map(b => {
                  const { h, m } = localHM(b.starts_at)
                  const startIdx = b.all_day ? 0 : (h - 9) * 2 + (m >= 30 ? 1 : 0)
                  if (startIdx >= SLOTS.length) return null
                  const safeStart = Math.max(0, startIdx)
                  const span = b.all_day
                    ? SLOTS.length
                    : Math.max(1, Math.min(SLOTS.length - safeStart, Math.round((durationMin(b.starts_at, b.ends_at) || 30) / 30)))
                  const ci = b.consultorio ? cols.findIndex(c => c.id === b.consultorio!.id) : -1
                  const gridColumn = ci >= 0 ? `${ci + 2}` : `2 / span ${Math.max(1, cols.length)}`
                  const esBloqueo = b.kind === 'block'
                  // Un evento sin doctor ni consultorio aplica a TODA LA SEDE ACTIVA (F2),
                  // no a las demás sucursales: lo nombramos para que no se malinterprete.
                  const sub = b.doctor
                    ? b.doctor.full_name
                    : b.consultorio
                      ? b.consultorio.name
                      : (sedeNombre ? `Toda la sucursal ${sedeNombre}` : 'Toda la clínica')
                  const Icono = esBloqueo ? Ban : Users
                  const tinta = esBloqueo ? '#A32D2D' : '#3A6EA5'
                  const subTinta = esBloqueo ? '#C0625C' : '#5B7DA8'
                  return (
                    <div
                      key={b.id}
                      onClick={() => setEventoSel(b)}
                      title="Ver / editar evento"
                      className="relative m-0.5 rounded-xl px-3 py-1 overflow-hidden flex flex-col items-center justify-center text-center gap-0.5 cursor-pointer"
                      style={{
                        gridColumn,
                        gridRow: `${safeStart + 1} / span ${span}`,
                        background: esBloqueo
                          ? 'repeating-linear-gradient(45deg, rgba(192,57,43,0.12), rgba(192,57,43,0.12) 8px, rgba(192,57,43,0.24) 8px, rgba(192,57,43,0.24) 16px)'
                          : 'rgba(58,110,165,0.16)',
                        border: esBloqueo ? '1px dashed rgba(192,57,43,0.6)' : '1px solid rgba(58,110,165,0.45)',
                        zIndex: 3,
                      }}
                    >
                      <Icono className="w-5 h-5 shrink-0" style={{ color: tinta }} strokeWidth={2.2} />
                      <p className="text-sm font-bold truncate w-full leading-tight" style={{ color: tinta }}>
                        {b.title || b.kind_display}
                      </p>
                      <p className="text-xs font-medium truncate w-full" style={{ color: subTinta }}>
                        {esBloqueo ? 'Bloqueado' : 'Reunión'} · {sub}
                      </p>
                    </div>
                  )
                })}

                {/* Citas */}
                {citas.map(a => {
                  const { h, m } = localHM(a.starts_at)
                  const startIdx = (h - 9) * 2 + (m >= 30 ? 1 : 0)
                  if (startIdx < 0 || startIdx >= SLOTS.length) return null
                  const dur = durationMin(a.starts_at, a.ends_at) || 30
                  const span = Math.max(1, Math.min(SLOTS.length - startIdx, Math.round(dur / 30)))
                  const ci = colIndexDe(a)
                  if (ci < 0) return null
                  const col = cols[ci]
                  const est = estiloEstado(a.status)
                  const esCancelada = a.status === 'cancelled'
                  // Color del TIPO de cita: tiñe toda la tarjeta (gris si no tiene tipo).
                  const tipoColor = a.appointment_type?.color_hex || '#9A958C'
                  const subtitulo = a.appointment_type?.name || a.reason || ''
                  const ModIcon = iconoModalidad(a.modality)
                  return (
                    <div
                      key={a.id}
                      onClick={() => setCitaSel(a)}
                      className="relative m-1 rounded-3xl px-3 py-1.5 overflow-hidden cursor-pointer transition-transform hover:scale-[1.01] flex flex-col items-center justify-center text-center leading-tight"
                      style={{
                        gridColumn: ci + 2,
                        gridRow: `${startIdx + 1} / span ${span}`,
                        background: esCancelada
                          ? 'repeating-linear-gradient(45deg, rgba(192,57,43,0.12), rgba(192,57,43,0.12) 8px, rgba(192,57,43,0.24) 8px, rgba(192,57,43,0.24) 16px)'
                          : `${tipoColor}3D`,
                        borderLeft: `5px solid ${esCancelada ? '#C0392B' : tipoColor}`,
                        backdropFilter: 'blur(6px)',
                        boxShadow: '0 2px 10px rgba(60,42,12,0.12)',
                        zIndex: 5,
                      }}
                    >
                      {esCancelada ? (
                        <>
                          <p className="text-xs font-medium text-gray-500 line-through truncate w-full px-2">{a.patient.full_name}</p>
                          <p className="font-extrabold" style={{ color: '#C0392B', fontSize: span >= 2 ? '1.1rem' : '0.8rem', letterSpacing: '0.06em' }}>CANCELADA</p>
                        </>
                      ) : (
                        <>
                          {/* punto del consultorio (la columna también lo indica) */}
                          <span className="absolute top-2 right-2.5 w-2.5 h-2.5 rounded-full"
                            style={{ background: col.color, boxShadow: `0 0 0 3px ${col.color}22` }} />
                          <div className="flex items-center justify-center gap-1.5 w-full px-2 min-w-0">
                            <ModIcon className="w-4 h-4 shrink-0" style={{ color: tipoColor }} strokeWidth={2.2} />
                            <p className="text-sm font-bold text-gray-900 leading-tight truncate min-w-0">{a.patient.full_name}</p>
                          </div>
                          {subtitulo && <p className="text-xs font-semibold truncate w-full" style={{ color: tipoColor }}>{subtitulo}</p>}
                          {span >= 2 && (
                            <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
                              style={{ background: est.bg, color: est.color }}>
                              {a.status_display}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </main>
      </div>

      <CrearEventoModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        dayKey={dayKey}
        fechaLarga={formatLargo(selectedDate)}
        horaInicio={slotSel.hora}
        consultorioId={slotSel.consultorioId}
        consultorioName={slotSel.consultorioName}
        initialMode={modalMode}
        initialModality={slotSel.modality}
      />

      {/* Confirmación: agendar en un horario que ya pasó */}
      {pendientePasado && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center px-4"
          style={{ background: 'rgba(40,28,8,0.45)', backdropFilter: 'blur(6px)' }}
          onClick={() => setPendientePasado(null)}>
          <div className="relative w-full max-w-sm rounded-3xl overflow-hidden text-center"
            style={{ background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(30px) saturate(160%)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 24px 70px rgba(60,42,12,0.3)' }}
            onClick={e => e.stopPropagation()}>
            <div className="px-7 pt-7 pb-5">
              <div className="w-14 h-14 mx-auto rounded-full flex items-center justify-center mb-4" style={{ background: 'rgba(201,162,39,0.15)' }}>
                <Clock className="w-7 h-7" style={{ color: '#C9A227' }} />
              </div>
              <h2 className="text-lg font-bold text-gray-900">Este horario ya pasó</h2>
              <p className="text-gray-600 text-sm mt-1.5">
                Las <b>{to12h(pendientePasado.hora)}</b> ya pasaron. ¿Seguro que quieres agendar en este horario?
              </p>
            </div>
            <div className="px-7 pb-7 flex gap-2.5">
              <button onClick={() => setPendientePasado(null)}
                className="flex-1 py-2.5 rounded-xl text-sm font-semibold transition-colors hover:brightness-95"
                style={{ color: '#6B7280', background: '#F3F4F6' }}>
                Cancelar
              </button>
              <button onClick={confirmarPasado}
                className="flex-1 py-2.5 rounded-xl text-sm font-bold text-white transition-all hover:brightness-110"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                Sí, agendar
              </button>
            </div>
          </div>
        </div>
      )}

      <DetalleCitaModal
        cita={citaSel ? toDetalle(citaSel) : null}
        onClose={() => setCitaSel(null)}
        puedeCambiarEstado={cambiarStatus}
        puedeCancelar={cancelar}
        puedeAgendar={agendar}
        onCambiarEstado={handleCambiarEstado}
        cambiando={cambiarEstado.isPending}
        reactivando={reactivar.isPending}
        onReactivar={citaSel ? () => { const id = citaSel.id; reactivar.mutate(id, { onError: e => void aviso({ mensaje: e instanceof ApiError ? (Array.isArray(e.body?.detail) ? e.body.detail.join(' ') : e.body?.detail ?? 'No se pudo reactivar.') : 'No se pudo reactivar.', tipo: 'error' }) }); setCitaSel(null) } : undefined}
        onReagendar={citaSel ? () => { setReagendarCita(citaSel); setCitaSel(null) } : undefined}
      />

      <ReagendarModal cita={reagendarCita} onClose={() => setReagendarCita(null)} />

      <EventoDetalleModal
        evento={eventoSel}
        onClose={() => setEventoSel(null)}
        soloLectura={!agendar}
      />
    </div>
  )
}
