/**
 * AgendarSesionModal — agenda (o reprograma) una SESIÓN de un plan de tratamiento
 * como cita real en la agenda, mostrando la DISPONIBILIDAD del médico/consultorio
 * en el día elegido: los horarios que se empalman con una cita existente salen en
 * ROJO y deshabilitados; los libres son seleccionables.
 *
 * Reutiliza el sistema de agenda ya existente:
 *   - `useAgendaDisponibilidad` para los intervalos ocupados (busy, UTC ISO).
 *   - la lógica `ocupadoEn` de CrearEventoModal (un slot está ocupado si
 *     [inicio, inicio+duración) solapa algún intervalo busy).
 *   - `useDoctors` / `useConsultorios` para los catálogos, filtrando los
 *     consultorios a los del médico (patrón `consPermitidos`).
 *
 * Al confirmar llama `useAgendarSesion(planId)` con el cuerpo del contrato. Un
 * empalme responde 400 `{ detail }` que se muestra con `useAviso`. Al éxito
 * entrega la sesión actualizada al padre (`onAgendada`) y cierra.
 */

import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Loader2, CalendarClock } from 'lucide-react'

import { useDoctors, useConsultorios, useAgendaDisponibilidad } from '../../hooks/agenda'
import { useAgendarSesion } from '../../hooks/calendarizacion'
import { useAuth } from '../../auth/AuthContext'
import { useRole } from '../../auth/RoleContext'
import { combineToISO, toDayKey, to12h } from '../../lib/fecha'
import { INPUT, LABEL } from '../../lib/estilosForm'
import { errorMsg } from '../../lib/apiErrors'
import { useAviso } from '../common/DialogProvider'
import type { SessionAppointment, TreatmentSession } from '../../types/calendarizacion'

const ORO = '#C9A227'
const ROJO = '#C0392B'
const DURACIONES = [15, 30, 45, 60, 90, 120]

/** Rejilla de horarios del día: 07:00 → 21:00 cada 30 min. */
const SLOTS_HORA: string[] = Array.from({ length: 29 }, (_, i) => {
  const h = 7 + Math.floor(i / 2)
  return `${String(h).padStart(2, '0')}:${i % 2 === 0 ? '00' : '30'}`
})

interface Props {
  open: boolean
  onClose: () => void
  planId: string
  /** Id de la sesión persistida a agendar. */
  sessionId: string
  /** Número de sesión (para el encabezado). */
  sessionNumber: number
  /** Descripción del tratamiento (para el encabezado). */
  treatmentLabel: string
  /** Cita actual de la sesión (reagendar), o null (agendar nueva). */
  appointment: SessionAppointment | null
  /** Fecha programada previa 'yyyy-mm-dd' o '' (default si no hay cita). */
  scheduledDate: string
  /** Hora programada previa 'HH:MM' o '' (default si no hay cita). */
  scheduledTime: string
  /** Duración previa en minutos o null (default si no hay cita). */
  durationMinutes: number | null
  /** Médico por defecto del plan. */
  defaultDoctorId: string
  /** Consultorio por defecto del plan. */
  defaultConsultorioId: string
  /** Callback con la sesión actualizada tras agendar con éxito. */
  onAgendada: (session: TreatmentSession) => void
}

export default function AgendarSesionModal({
  open, onClose, planId, sessionId, sessionNumber, treatmentLabel, appointment,
  scheduledDate, scheduledTime, durationMinutes, defaultDoctorId, defaultConsultorioId,
  onAgendada,
}: Props) {
  const aviso = useAviso()
  const agendar = useAgendarSesion(planId)
  const { user } = useAuth()
  const { role } = useRole()
  // Un médico solo agenda para sí mismo (misma regla que la agenda / el backend).
  const soloPropio = role === 'doctor'

  const { data: docData } = useDoctors()
  const { data: consData } = useConsultorios()
  const doctores = useMemo(() => (docData?.results ?? []).filter((d) => d.is_active), [docData])
  const consultorios = useMemo(() => (consData?.results ?? []).filter((c) => c.is_active), [consData])

  const [doctorId, setDoctorId] = useState('')
  const [consId, setConsId] = useState('')
  const [fecha, setFecha] = useState('')
  const [duracion, setDuracion] = useState(30)
  const [hora, setHora] = useState('')

  // Prefill al abrir: prioriza los datos de la cita existente (reagendar).
  useEffect(() => {
    if (!open) return
    // Un doctor queda fijo en sí mismo; el administrador usa la cita/plan.
    setDoctorId(soloPropio ? (user?.doctor_id || '') : (appointment?.doctor_id || defaultDoctorId || ''))
    setConsId(appointment?.consultorio_id || defaultConsultorioId || '')
    setFecha(scheduledDate || toDayKey(new Date()))
    setDuracion(durationMinutes ?? 30)
    setHora(scheduledTime || '')
  }, [open, appointment, defaultDoctorId, defaultConsultorioId, scheduledDate, scheduledTime, durationMinutes, soloPropio, user])

  // Consultorios permitidos: si el médico tiene asignados, solo esos.
  const docSel = doctores.find((d) => d.id === doctorId)
  const consPermitidos = docSel && docSel.consultorios.length > 0 ? docSel.consultorios : consultorios

  // Si al cambiar de médico el consultorio elegido ya no le pertenece, se limpia.
  useEffect(() => {
    if (consId && docSel && docSel.consultorios.length > 0 && !docSel.consultorios.some((c) => c.id === consId)) {
      setConsId('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doctorId])

  // Disponibilidad del día elegido (para el médico + consultorio).
  const dispFrom = fecha ? combineToISO(fecha, '00:00') : ''
  const dispTo = fecha ? combineToISO(fecha, '23:59') : ''
  const { data: dispData, isFetching: dispLoading } = useAgendaDisponibilidad({
    doctorId, consultorioId: consId || null, from: dispFrom, to: dispTo,
    enabled: open && !!doctorId && !!fecha,
  })

  // Al reagendar, la PROPIA cita de esta sesión aparece en busy: se excluye para no
  // pintar su horario actual como ocupado.
  const busy = useMemo(() => {
    const raw = dispData?.busy ?? []
    if (!appointment) return raw
    const apptStart = new Date(appointment.starts_at).getTime()
    return raw.filter((b) => new Date(b.start).getTime() !== apptStart)
  }, [dispData, appointment])

  const slotOcupado = (startISO: string, endISO: string): boolean =>
    busy.some(
      (b) =>
        new Date(startISO).getTime() < new Date(b.end).getTime() &&
        new Date(endISO).getTime() > new Date(b.start).getTime(),
    )

  const ahora = Date.now()
  /** Un slot está ocupado si su [inicio, inicio+duración) solapa un intervalo busy. */
  const ocupadoEn = (time: string): boolean => {
    if (!fecha) return false
    const sISO = combineToISO(fecha, time)
    const eISO = new Date(new Date(sISO).getTime() + duracion * 60_000).toISOString()
    return slotOcupado(sISO, eISO)
  }
  /** Slot en el pasado (no agendable). */
  const enPasado = (time: string): boolean =>
    fecha ? new Date(combineToISO(fecha, time)).getTime() < ahora : false

  const confirmar = (): void => {
    if (!doctorId) { void aviso({ mensaje: 'Selecciona un médico.', tipo: 'error' }); return }
    if (!fecha) { void aviso({ mensaje: 'Selecciona una fecha.', tipo: 'error' }); return }
    if (!hora) { void aviso({ mensaje: 'Selecciona una hora disponible.', tipo: 'error' }); return }
    if (ocupadoEn(hora)) {
      void aviso({ mensaje: 'Ese horario está ocupado; elige uno libre.', tipo: 'error' })
      return
    }
    const startISO = combineToISO(fecha, hora)
    const endISO = new Date(new Date(startISO).getTime() + duracion * 60_000).toISOString()
    agendar.mutate(
      {
        sessionId,
        body: {
          scheduled_date: fecha,
          scheduled_time: hora,
          starts_at: startISO,
          ends_at: endISO,
          duration_minutes: duracion,
          doctor_id: doctorId,
          consultorio_id: consId || null,
        },
      },
      {
        onSuccess: (session) => {
          onAgendada(session)
          void aviso({ mensaje: 'Sesión agendada en la agenda.', tipo: 'exito' })
          onClose()
        },
        // El 400 de empalme trae { detail }; errorMsg lo extrae.
        onError: (e) => void aviso({ mensaje: errorMsg(e), tipo: 'error' }),
      },
    )
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 py-10 overflow-y-auto"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-xl rounded-3xl overflow-hidden"
            style={{ background: 'rgba(255,255,255,0.85)', backdropFilter: 'blur(30px) saturate(160%)', border: '1px solid rgba(255,255,255,0.65)', boxShadow: '0 20px 60px rgba(60,42,12,0.25)' }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Encabezado */}
            <div className="px-7 py-5 flex items-start justify-between border-b border-white/40">
              <div>
                <h2 className="text-gray-900 text-lg font-bold inline-flex items-center gap-2">
                  <CalendarClock className="w-5 h-5" style={{ color: ORO }} />
                  {appointment ? 'Reagendar sesión' : 'Agendar sesión'}
                </h2>
                <p className="text-gray-500 text-sm mt-0.5">
                  Sesión {sessionNumber}{treatmentLabel ? ` · ${treatmentLabel}` : ''}
                </p>
              </div>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-6 h-6" /></button>
            </div>

            <div className="px-7 py-6 space-y-4">
              {/* Médico + consultorio */}
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className={LABEL}>Médico</label>
                  {soloPropio ? (
                    <div className={`${INPUT} flex items-center justify-between`} style={{ background: 'rgba(255,255,255,0.4)' }}>
                      <span>{docSel?.full_name || user?.full_name}</span>
                      <span className="text-xs font-semibold" style={{ color: ORO }}>Tú</span>
                    </div>
                  ) : (
                    <select className={INPUT} value={doctorId} onChange={(e) => setDoctorId(e.target.value)}>
                      <option value="">Selecciona…</option>
                      {doctores.map((d) => <option key={d.id} value={d.id}>{d.full_name}</option>)}
                    </select>
                  )}
                </div>
                <div>
                  <label className={LABEL}>Consultorio</label>
                  <select className={INPUT} value={consId} onChange={(e) => setConsId(e.target.value)}>
                    <option value="">Sin consultorio</option>
                    {consPermitidos.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              </div>

              {/* Fecha + duración */}
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className={LABEL}>Fecha</label>
                  <input
                    className={INPUT}
                    type="date"
                    value={fecha}
                    min={toDayKey(new Date())}
                    onChange={(e) => setFecha(e.target.value)}
                  />
                </div>
                <div>
                  <label className={LABEL}>Duración</label>
                  <select className={INPUT} value={duracion} onChange={(e) => setDuracion(Number(e.target.value))}>
                    {DURACIONES.map((d) => <option key={d} value={d}>{d} min</option>)}
                  </select>
                </div>
              </div>

              {/* Selector de hora con disponibilidad */}
              <div>
                <label className={`${LABEL} flex items-center justify-between`}>
                  <span>Hora</span>
                  {dispLoading && <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" />}
                </label>
                <p className="text-[11px] mb-2" style={{ color: '#9A958C' }}>
                  Los horarios <span style={{ color: ROJO, fontWeight: 600 }}>ocupados</span> aparecen en rojo. Toca uno libre para elegirlo.
                </p>
                {!doctorId ? (
                  <p className="text-xs text-gray-400">Selecciona un médico para ver la disponibilidad.</p>
                ) : (
                  <div className="grid gap-1.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(64px, 1fr))' }}>
                    {SLOTS_HORA.map((t) => {
                      const ocupado = ocupadoEn(t)
                      const pasado = enPasado(t)
                      const bloqueado = ocupado || pasado
                      const sel = hora === t
                      return (
                        <button
                          key={t}
                          type="button"
                          disabled={bloqueado}
                          onClick={() => setHora(t)}
                          title={ocupado ? 'Ocupado' : pasado ? 'Ya pasó' : to12h(t)}
                          className="text-[11px] px-1.5 py-1.5 rounded-lg transition-colors text-center"
                          style={
                            ocupado
                              ? { background: '#FDE8E8', color: ROJO, textDecoration: 'line-through', cursor: 'not-allowed' }
                              : pasado
                                ? { background: 'rgba(0,0,0,0.04)', color: '#C4BFB6', cursor: 'not-allowed' }
                                : sel
                                  ? { background: ORO, color: '#fff', fontWeight: 600, boxShadow: '0 3px 10px rgba(201,162,39,0.4)' }
                                  : { background: 'rgba(255,255,255,0.75)', color: '#5A5246', border: '1px solid rgba(0,0,0,0.08)' }
                          }
                        >
                          {to12h(t)}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* Pie */}
            <div className="px-7 py-4 flex items-center justify-between border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={onClose} disabled={agendar.isPending} className="btn-secondary disabled:opacity-60">Cancelar</button>
              <button
                onClick={confirmar}
                disabled={agendar.isPending}
                className="px-8 py-2.5 inline-flex items-center gap-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-50"
                style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                {agendar.isPending
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> Agendando…</>
                  : (appointment ? 'Reagendar' : 'Agendar')}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
