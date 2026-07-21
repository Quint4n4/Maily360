/**
 * CitasSection — contenido de la sección "Citas" del acordeón del expediente.
 * Próxima cita + historial de citas (movido tal cual desde ResumenTab).
 * Visible para todos los roles que ven el expediente (no requiere acceso clínico).
 */

import { CalendarClock, ClipboardList, User } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Appointment } from '../../types/agenda'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import { formatFechaHora } from '../../lib/fecha'
import { Card, ESTADOS_CITA_INACTIVOS as ESTADOS_INACTIVOS, estadoCitaChip as estadoChip } from './ui'

interface CitasSectionProps {
  paciente: PatientOut
}

export default function CitasSection({ paciente }: CitasSectionProps) {
  const { data: citasData, isLoading: citasLoading } = useAppointmentsForPatient(paciente.id)
  const citas: Appointment[] = citasData?.results ?? []
  const historial = [...citas].sort((a, b) => b.starts_at.localeCompare(a.starts_at))
  const proxima: Appointment | null =
    [...citas]
      .filter(c => !ESTADOS_INACTIVOS.has(c.status))
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0] ?? null

  return (
    <div className="space-y-4">
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
  )
}
