/**
 * HistorialExpediente — bloque INFERIOR del expediente rediseñado.
 *
 * Reúne el historial del paciente para consultar (no para capturar la visita):
 *   - Una franja-recordatorio de CITAS (próxima + últimas), solo lectura, con
 *     useAppointmentsForPatient.
 *   - El componente LibroClinico EXISTENTE tal cual (Historia clínica viva +
 *     capítulos/evoluciones + PDF). No se modifica; solo se integra aquí.
 */

import { CalendarClock, BookOpen, History } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Appointment, AppointmentStatus } from '../../types/agenda'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import { formatFechaHora } from '../../lib/fecha'
import LibroClinico from './LibroClinico'

/** Estilo del chip de estado de una cita (mismo criterio que CitasSection). */
function estadoChip(s: AppointmentStatus): { bg: string; color: string } {
  if (s === 'attended') return { bg: '#DCF3E6', color: '#1F6E47' }
  if (s === 'confirmed' || s === 'arrived' || s === 'in_progress') return { bg: '#E7F6EE', color: '#2E7D5B' }
  if (s === 'cancelled' || s === 'no_show') return { bg: '#FDE8E8', color: '#C0392B' }
  return { bg: '#FBF1D9', color: '#9A7B1E' }
}
const ESTADOS_INACTIVOS = new Set<AppointmentStatus>(['attended', 'cancelled', 'no_show'])

interface HistorialExpedienteProps {
  paciente: PatientOut
  /** Si el rol tiene acceso clínico (muestra el libro clínico). */
  verClinico: boolean
  /** Si el rol ve costos: el libro muestra el estado de cuenta por visita. */
  verEstadoCuenta?: boolean
}

export default function HistorialExpediente({
  paciente,
  verClinico,
  verEstadoCuenta = false,
}: HistorialExpedienteProps) {
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <History className="w-4 h-4" style={{ color: '#C9A227' }} />
        <h3 className="text-sm font-semibold uppercase tracking-wide text-amber-700/80">Historial del paciente</h3>
      </div>

      {/* Franja-recordatorio de citas (solo consultar) */}
      <CitasRecordatorio paciente={paciente} />

      {/* Libro clínico (componente existente, sin cambios) */}
      {verClinico && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <BookOpen className="w-4 h-4" style={{ color: '#C9A227' }} />
            <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700/80">Libro clínico</h4>
          </div>
          <LibroClinico paciente={paciente} verEstadoCuenta={verEstadoCuenta} />
        </div>
      )}
    </div>
  )
}

// ── Franja-recordatorio de citas ───────────────────────────────────────────────

function CitasRecordatorio({ paciente }: { paciente: PatientOut }) {
  const { data: citasData, isLoading } = useAppointmentsForPatient(paciente.id)
  const citas: Appointment[] = citasData?.results ?? []

  const proxima: Appointment | null =
    [...citas]
      .filter(c => !ESTADOS_INACTIVOS.has(c.status))
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0] ?? null

  // Últimas citas (más reciente primero), tope de 5 para la franja.
  const recientes = [...citas]
    .sort((a, b) => b.starts_at.localeCompare(a.starts_at))
    .slice(0, 5)

  return (
    <div
      className="rounded-2xl p-4"
      style={{ background: 'rgba(255,255,255,0.6)', border: '1px solid rgba(201,162,39,0.18)' }}
    >
      <div className="flex items-center gap-2 mb-3">
        <CalendarClock className="w-4 h-4" style={{ color: '#C9A227' }} />
        <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700/80">Citas</h4>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-400 italic">Cargando citas…</p>
      ) : (
        <div className="space-y-3">
          {/* Próxima cita */}
          {proxima ? (
            <div className="rounded-xl px-4 py-3" style={{ background: 'rgba(201,162,39,0.08)', border: '1px solid rgba(201,162,39,0.2)' }}>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70 mb-0.5">Próxima cita</p>
              <p className="text-sm font-bold text-gray-900">{formatFechaHora(proxima.starts_at)}</p>
              <p className="text-xs text-gray-500">
                {proxima.doctor.full_name}{proxima.consultorio ? ` · ${proxima.consultorio.name}` : ''}
              </p>
            </div>
          ) : (
            <p className="text-sm text-gray-400 italic">Sin cita próxima agendada.</p>
          )}

          {/* Últimas citas (recordatorio horizontal) */}
          {recientes.length > 0 && (
            <div className="flex gap-2 overflow-x-auto pb-1 -mx-0.5 px-0.5">
              {recientes.map(c => {
                const chip = estadoChip(c.status)
                const motivo = c.appointment_type?.name || c.reason || 'Cita'
                return (
                  <div
                    key={c.id}
                    className="shrink-0 rounded-xl px-3 py-2 bg-white/70"
                    style={{ border: '1px solid rgba(201,162,39,0.15)', minWidth: 160 }}
                  >
                    <p className="text-xs font-medium text-gray-800 truncate">{motivo}</p>
                    <p className="text-[11px] text-gray-400">{formatFechaHora(c.starts_at)}</p>
                    <span className="badge mt-1 text-[10px]" style={{ background: chip.bg, color: chip.color }}>
                      {c.status_display}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
