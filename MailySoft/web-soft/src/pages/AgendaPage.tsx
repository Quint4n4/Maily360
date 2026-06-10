import { useState } from 'react'
import { ChevronLeft, ChevronRight, CalendarCheck, Cake, FileText, CircleDollarSign, UserX, Loader2 } from 'lucide-react'
import Topbar from '../components/Topbar'
import CrearEventoModal from '../components/agenda/CrearEventoModal'
import DetalleCitaModal, { CitaDetalle, EstadoCita } from '../components/agenda/DetalleCitaModal'
import EventoDetalleModal from '../components/agenda/EventoDetalleModal'
import RecordatoriosWidget from '../components/agenda/RecordatoriosWidget'
import ReagendarModal from '../components/agenda/ReagendarModal'
import { useAppointmentsForDay, useConsultorios, useChangeAppointmentStatus, useAgendaBlocksForDay, useReactivateAppointment } from '../hooks/agenda'
import {
  addDays, addMonths, formatLargo, formatMedio, formatFechaHora, localHM, localHHMM,
  durationMin, monthGrid, sameDay, toDayKey,
} from '../lib/fecha'
import { ApiError } from '../lib/http'
import type { Appointment, AppointmentStatus, AgendaBlock } from '../types/agenda'
import { useRole } from '../auth/RoleContext'
import { puedeEditar } from '../auth/permisos'

/* ─── Rejilla horaria 9:00–17:30 ─────────────────────────────────────────── */
const SLOTS = Array.from({ length: 18 }, (_, i) => {
  const h = 9 + Math.floor(i / 2)
  const m = i % 2 === 0 ? 0 : 30
  return { h, m, label: `${h}:${m === 0 ? '00' : '30'}` }
})
const ROW_H = 60
const DIAS_SEMANA = ['L', 'M', 'M', 'J', 'V', 'S', 'D']

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

const NONE_COL = '__none__'

export default function AgendaPage() {
  const [selectedDate, setSelectedDate] = useState(() => new Date())
  const [modalOpen, setModalOpen] = useState(false)
  const [slotSel, setSlotSel] = useState<{ hora: string; consultorioId: string | null; consultorioName: string }>(
    { hora: '09:00', consultorioId: null, consultorioName: '' },
  )
  const [citaSel, setCitaSel] = useState<Appointment | null>(null)
  const [eventoSel, setEventoSel] = useState<AgendaBlock | null>(null)
  const [reagendarCita, setReagendarCita] = useState<Appointment | null>(null)
  const [modalMode, setModalMode] = useState<'cita' | 'block' | 'meeting'>('cita')
  const { role } = useRole()
  const editar = puedeEditar(role, 'agenda')
  const cambiarEstado = useChangeAppointmentStatus()
  const reactivar = useReactivateAppointment()

  const dayKey = toDayKey(selectedDate)
  const { data: apptData, isLoading: loadingCitas, isError } = useAppointmentsForDay(dayKey)
  const { data: consData, isLoading: loadingCons } = useConsultorios()
  const { data: eventos } = useAgendaBlocksForDay(dayKey)

  const citas: Appointment[] = apptData?.results ?? []
  const bloques: AgendaBlock[] = eventos ?? []
  const consultorios = (consData?.results ?? []).filter(c => c.is_active)

  // Columnas del tablero = consultorios; + "Sin consultorio" si hay citas sin asignar.
  type Col = { id: string; name: string; color: string }
  const cols: Col[] = consultorios.map(c => ({ id: c.id, name: c.name, color: c.color_hex || '#C9A227' }))
  const hayHuerfanas = citas.some(a => !a.consultorio || !cols.find(c => c.id === a.consultorio!.id))
  if (hayHuerfanas) cols.push({ id: NONE_COL, name: 'Sin consultorio', color: '#9A958C' })

  const colIndexDe = (a: Appointment): number => {
    const id = a.consultorio?.id
    const idx = cols.findIndex(c => c.id === id)
    if (idx >= 0) return idx
    return cols.findIndex(c => c.id === NONE_COL)
  }

  const abrirCrear = (hora: string, col: Col) => {
    if (!editar) return
    setSlotSel({
      hora: hora.length === 4 ? `0${hora}` : hora,
      consultorioId: col.id === NONE_COL ? null : col.id,
      consultorioName: col.id === NONE_COL ? '' : col.name,
    })
    setModalMode('cita')
    setModalOpen(true)
  }

  // Mapea una cita real al shape de presentación del modal de detalle.
  const toDetalle = (a: Appointment): CitaDetalle => {
    const col = cols[colIndexDe(a)]
    return {
      id: a.id,
      paciente: a.patient.full_name,
      doctor: a.doctor.full_name,
      consultorioName: a.consultorio?.name ?? 'Sin consultorio',
      consultorioColor: col?.color ?? '#C9A227',
      horario: `${localHHMM(a.starts_at)} – ${localHHMM(a.ends_at)}`,
      fecha: formatLargo(selectedDate),
      motivo: a.appointment_type?.name || a.reason,
      especialidad: a.specialty,
      notas: a.notes,
      estadoInicial: ESTADO_MAP[a.status],
      recordatorios: a.reminders.map(r => ({
        texto: r.channel_display,
        fecha: formatFechaHora(r.scheduled_at),
        estado: r.status_display,
      })),
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
          window.alert(msg)
        },
      },
    )
  }

  const gridCols = `70px repeat(${Math.max(1, cols.length)}, 1fr)`

  return (
    <div className="min-h-screen relative">
      {/* Fondo */}
      <div className="fixed inset-0 -z-10" style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="fixed inset-0 -z-10 bg-cover bg-center" style={{ backgroundImage: "url('/fondo-agenda.jpg')" }} />
      <div className="fixed inset-0 -z-10" style={{ background: 'rgba(255,255,255,0.20)' }} />

      <Topbar active="agenda" />

      <div className="flex gap-5 p-5 max-w-[1500px] mx-auto">

        {/* ════════ Panel izquierdo ════════ */}
        <aside className="w-80 shrink-0 space-y-4">

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

          {/* Accesos rápidos */}
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
        </aside>

        {/* ════════ Panel derecho — rejilla ════════ */}
        <main className="glass-card flex-1 rounded-2xl overflow-hidden">

          {/* Título del día */}
          <div className="px-5 py-3 border-b border-white/50 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <CalendarCheck className="w-4 h-4" style={{ color: '#C9A227' }} />
              {formatLargo(selectedDate)}
            </h2>
            <span className="text-xs text-gray-500">
              {loadingCitas ? 'Cargando…' : `${citas.length} cita${citas.length === 1 ? '' : 's'}`}
            </span>
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
            <>
              {/* Encabezado de columnas */}
              <div className="grid border-b border-white/50" style={{ gridTemplateColumns: gridCols }}>
                <div className="py-3 text-center text-xs font-bold text-gray-500">Hr.</div>
                {cols.map(c => (
                  <div key={c.id} className="py-3 text-center text-sm font-semibold border-l border-white/50" style={{ color: '#374151' }}>
                    <span className="inline-flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ background: c.color }} />
                      {c.name}
                    </span>
                  </div>
                ))}
              </div>

              {/* Cuerpo */}
              <div className="relative grid" style={{ gridTemplateColumns: gridCols, gridAutoRows: `${ROW_H}px` }}>
                {SLOTS.map((s, r) => (
                  <div key={`row-${r}`} className="contents">
                    <div className="flex items-start justify-center pt-1 text-xs text-gray-500 border-b border-white/40"
                      style={{ gridColumn: 1, gridRow: r + 1 }}>
                      {s.label}
                    </div>
                    {cols.map((c, ci) => (
                      <button
                        key={`cell-${r}-${ci}`}
                        onClick={editar ? () => abrirCrear(s.label, c) : undefined}
                        className={`border-b border-l border-white/40 transition-colors ${editar ? 'hover:bg-white/40 cursor-pointer' : 'cursor-default'}`}
                        style={{ gridColumn: ci + 2, gridRow: r + 1 }}
                      />
                    ))}
                  </div>
                ))}

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
                  const sub = b.doctor ? b.doctor.full_name : (b.consultorio ? b.consultorio.name : 'Toda la clínica')
                  return (
                    <div
                      key={b.id}
                      onClick={() => setEventoSel(b)}
                      title="Ver / editar evento"
                      className="relative m-0.5 rounded-xl px-3 py-1 overflow-hidden flex flex-col items-center justify-center text-center cursor-pointer"
                      style={{
                        gridColumn,
                        gridRow: `${safeStart + 1} / span ${span}`,
                        background: esBloqueo
                          ? 'repeating-linear-gradient(45deg, rgba(120,113,108,0.16), rgba(120,113,108,0.16) 9px, rgba(120,113,108,0.27) 9px, rgba(120,113,108,0.27) 18px)'
                          : 'rgba(58,110,165,0.16)',
                        border: esBloqueo ? '1px dashed rgba(120,113,108,0.55)' : '1px solid rgba(58,110,165,0.45)',
                        zIndex: 3,
                      }}
                    >
                      <p className="text-[11px] font-bold truncate w-full" style={{ color: esBloqueo ? '#6B7280' : '#3A6EA5' }}>
                        {b.title || b.kind_display}
                      </p>
                      <p className="text-[10px] truncate w-full" style={{ color: '#9CA3AF' }}>
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
                          : `${tipoColor}26`,
                        borderLeft: `4px solid ${esCancelada ? '#C0392B' : tipoColor}`,
                        backdropFilter: 'blur(6px)',
                        boxShadow: '0 2px 10px rgba(60,42,12,0.12)',
                        zIndex: 5,
                      }}
                    >
                      {esCancelada ? (
                        <>
                          <p className="text-[11px] font-medium text-gray-500 line-through truncate w-full px-2">{a.patient.full_name}</p>
                          <p className="font-extrabold" style={{ color: '#C0392B', fontSize: span >= 2 ? '1.05rem' : '0.72rem', letterSpacing: '0.06em' }}>CANCELADA</p>
                        </>
                      ) : (
                        <>
                          {/* punto del consultorio (la columna también lo indica) */}
                          <span className="absolute top-2.5 right-3 w-2.5 h-2.5 rounded-full"
                            style={{ background: col.color, boxShadow: `0 0 0 3px ${col.color}22` }} />
                          <p className="text-xs font-semibold text-gray-900 leading-tight truncate w-full px-3">{a.patient.full_name}</p>
                          {subtitulo && <p className="text-[11px] font-medium truncate w-full" style={{ color: tipoColor }}>{subtitulo}</p>}
                          {span >= 2 && (
                            <span className="inline-block mt-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium"
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
            </>
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
      />

      <DetalleCitaModal
        cita={citaSel ? toDetalle(citaSel) : null}
        onClose={() => setCitaSel(null)}
        soloLectura={!editar}
        onCambiarEstado={handleCambiarEstado}
        cambiando={cambiarEstado.isPending}
        reactivando={reactivar.isPending}
        onReactivar={citaSel ? () => { const id = citaSel.id; reactivar.mutate(id, { onError: e => window.alert(e instanceof ApiError ? (Array.isArray(e.body?.detail) ? e.body.detail.join(' ') : e.body?.detail ?? 'No se pudo reactivar.') : 'No se pudo reactivar.') }); setCitaSel(null) } : undefined}
        onReagendar={citaSel ? () => { setReagendarCita(citaSel); setCitaSel(null) } : undefined}
      />

      <ReagendarModal cita={reagendarCita} onClose={() => setReagendarCita(null)} />

      <EventoDetalleModal
        evento={eventoSel}
        onClose={() => setEventoSel(null)}
        soloLectura={!editar}
      />
    </div>
  )
}
