/**
 * HorariosDoctor — horario laboral de un médico, POR SEDE (multi-sede, Fase 2).
 *
 * El horario de un médico es por sucursal: puede atender L-V 9-14 en la sede
 * Centro y S 9-13 en la sede Norte. Por eso cada bloque lleva su sucursal, y al
 * crear uno se elige la sede (por defecto, la activa).
 *
 * Contrato del backend (apps/personal):
 *   GET    /personal/doctores/<id>/horarios/   → Paginated<DoctorSchedule>
 *   POST   /personal/doctores/<id>/horarios/   → DoctorSchedule (con sucursal_id)
 *   DELETE /personal/horarios/<id>/            → 204 (baja suave)
 * No hay PATCH: editar = dar de baja el bloque y crear el nuevo.
 */

import { useState } from 'react'
import { AlertCircle, Building2, CalendarClock, Loader2, Plus, Trash2 } from 'lucide-react'

import { useCreateDoctorSchedule, useDeactivateDoctorSchedule, useDoctorSchedules } from '../../hooks/personal'
import { useSucursales } from '../../hooks/sucursales'
import { useSucursalActiva } from '../../auth/SucursalContext'
import { useConfirm } from '../common/DialogProvider'
import { erroresDe } from '../../lib/apiErrors'
import { to12h } from '../../lib/fecha'
import type { Weekday } from '../../types/personal'

/** Días del backend (Weekday): 0 = Lunes … 6 = Domingo. */
const DIAS: { key: Weekday; label: string }[] = [
  { key: 0, label: 'Lunes' },
  { key: 1, label: 'Martes' },
  { key: 2, label: 'Miércoles' },
  { key: 3, label: 'Jueves' },
  { key: 4, label: 'Viernes' },
  { key: 5, label: 'Sábado' },
  { key: 6, label: 'Domingo' },
]

/** 'HH:MM:SS' (o 'HH:MM') del backend → '9:00 am' para mostrar. */
function horaBonita(t: string): string {
  return to12h(t.slice(0, 5))
}

interface Props {
  doctorId: string
  /** Si es false, la sección es de solo lectura (no se crea ni se borra). */
  puedeEditar?: boolean
}

export default function HorariosDoctor({ doctorId, puedeEditar = false }: Props) {
  const { activeSucursalId, activeSucursal } = useSucursalActiva()
  const { data: sucData } = useSucursales()
  const sucursales = (sucData?.results ?? []).filter(s => s.is_active)
  const usaSedes = sucursales.length > 0

  const { data, isLoading, isError } = useDoctorSchedules(doctorId)
  const crear = useCreateDoctorSchedule()
  const borrar = useDeactivateDoctorSchedule()
  const confirmar = useConfirm()

  const [dia, setDia] = useState<Weekday>(0)
  const [inicio, setInicio] = useState('09:00')
  const [fin, setFin] = useState('14:00')
  const [sucursalId, setSucursalId] = useState<string>(activeSucursalId ?? '')
  const [errores, setErrores] = useState<string[]>([])

  const horarios = data?.results ?? []

  const agregar = async () => {
    setErrores([])
    if (fin <= inicio) { setErrores(['La hora de fin debe ser posterior a la de inicio.']); return }
    if (usaSedes && !sucursalId) { setErrores(['Elige la sucursal del horario.']); return }
    try {
      await crear.mutateAsync({
        doctorId,
        input: {
          day_of_week: dia,
          start_time: inicio,
          end_time: fin,
          // Solo mandamos la sede si la clínica usa sucursales; si no, el backend la deriva.
          sucursal_id: usaSedes ? sucursalId : null,
        },
      })
    } catch (err) { setErrores(erroresDe(err, 'No se pudo guardar el horario.')) }
  }

  const quitar = async (id: string, etiqueta: string) => {
    if (!(await confirmar({
      titulo: 'Quitar horario',
      mensaje: `¿Quitar el horario ${etiqueta}?`,
      peligro: true,
      textoConfirmar: 'Quitar',
    }))) return
    setErrores([])
    try { await borrar.mutateAsync(id) } catch (err) { setErrores(erroresDe(err, 'No se pudo quitar el horario.')) }
  }

  return (
    <div className="mt-4 pt-4 border-t border-amber-900/10">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-3 flex items-center gap-2">
        <CalendarClock className="w-4 h-4" /> Horario laboral
        {usaSedes && <span className="text-[11px] font-normal text-gray-400">(por sucursal)</span>}
      </p>

      {errores.length > 0 && (
        <div className="flex items-start gap-2.5 rounded-xl px-4 py-3 mb-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
          <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">{errores.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </div>
      )}

      {isLoading && (
        <p className="text-xs text-gray-400 inline-flex items-center gap-1.5">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Cargando horarios…
        </p>
      )}
      {isError && <p className="text-xs text-red-600">No se pudieron cargar los horarios.</p>}

      {!isLoading && !isError && (
        horarios.length === 0 ? (
          <p className="text-xs text-gray-400">
            Sin horarios{activeSucursal ? ` en ${activeSucursal.name}` : ''}. Agrega uno abajo.
          </p>
        ) : (
          <div className="space-y-1.5">
            {horarios.map(h => {
              const etiqueta = `${h.day_of_week_display} ${horaBonita(h.start_time)}–${horaBonita(h.end_time)}`
              return (
                <div key={h.id} className="flex items-center justify-between gap-2 rounded-xl px-3 py-2"
                  style={{ background: 'rgba(255,255,255,0.6)', border: '1px solid rgba(201,162,39,0.2)' }}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{etiqueta}</p>
                    <p className="text-[11px] text-gray-500 flex items-center gap-1.5 truncate">
                      {/* A qué SEDE pertenece este horario (multi-sede F2). */}
                      <Building2 className="w-3 h-3 shrink-0" style={{ color: '#C9A227' }} />
                      {h.sucursal?.name ?? 'Sin sucursal'}
                      {h.consultorio && <span className="text-gray-400">· {h.consultorio.name}</span>}
                    </p>
                  </div>
                  {puedeEditar && (
                    <button type="button" onClick={() => void quitar(h.id, etiqueta)} disabled={borrar.isPending}
                      title="Quitar horario"
                      className="p-1.5 rounded-lg transition-colors hover:bg-red-50 disabled:opacity-50">
                      <Trash2 className="w-4 h-4" style={{ color: '#C0392B' }} />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )
      )}

      {puedeEditar && (
        <div className="mt-3 grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
          <div>
            <label className="label">Día</label>
            <select className="input" value={dia} onChange={e => setDia(Number(e.target.value) as Weekday)}>
              {DIAS.map(d => <option key={d.key} value={d.key}>{d.label}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Desde</label>
            <input type="time" className="input" value={inicio} onChange={e => setInicio(e.target.value)} />
          </div>
          <div>
            <label className="label">Hasta</label>
            <input type="time" className="input" value={fin} onChange={e => setFin(e.target.value)} />
          </div>
          {usaSedes && (
            <div>
              <label className="label">Sucursal</label>
              <select className="input" value={sucursalId} onChange={e => setSucursalId(e.target.value)}>
                <option value="">Selecciona…</option>
                {sucursales.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          )}
          <div className="flex items-end">
            <button type="button" onClick={() => void agregar()} disabled={crear.isPending}
              className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-colors disabled:opacity-60"
              style={{ color: '#9A7B1E', background: 'rgba(201,162,39,0.14)' }}>
              {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Agregando…</> : <><Plus className="w-4 h-4" /> Agregar horario</>}
            </button>
          </div>
        </div>
      )}
      {puedeEditar && usaSedes && (
        <p className="text-[11px] text-gray-400 mt-1.5">
          El horario es <b>por sede</b>: el médico puede tener horarios distintos en cada sucursal.
        </p>
      )}
    </div>
  )
}
