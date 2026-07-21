import { useEffect, useState } from 'react'
import { Clock, Loader2, Save } from 'lucide-react'

import { useActualizarAgendaConfig, useAgendaConfig } from '../../hooks/agendaConfig'
import { INTERVALOS_REJILLA } from '../../types/agendaConfig'
import { erroresDe } from '../../lib/apiErrors'
import { AlertaErrores, AvisoGuardado, AvisoSoloLectura, Nota } from './Avisos'

interface Props {
  editable: boolean
}

/** Etiqueta legible de una hora en formato 12h (8 → "8:00 am", 18 → "6:00 pm"). */
function etiquetaHora(h: number): string {
  if (h === 24) return '12:00 am (medianoche)'
  const ampm = h < 12 ? 'am' : 'pm'
  const h12 = h % 12 === 0 ? 12 : h % 12
  return `${h12}:00 ${ampm}`
}

const HORAS_APERTURA = Array.from({ length: 24 }, (_, i) => i) // 0–23
const HORAS_CIERRE = Array.from({ length: 24 }, (_, i) => i + 1) // 1–24

/**
 * Sección "Horario de la agenda": define el rango horario que abarca la agenda
 * y cada cuántos minutos hay una línea en la rejilla. Aplica a TODA la clínica.
 *
 * La duración de la consulta de CADA médico se configura aparte, en su ficha de
 * Personal (Doctor.default_appointment_duration tiene precedencia sobre la
 * duración por defecto de la clínica).
 */
export default function SeccionHorarioAgenda({ editable }: Props) {
  const configQ = useAgendaConfig()
  const actualizar = useActualizarAgendaConfig()

  const [inicio, setInicio] = useState(9)
  const [fin, setFin] = useState(18)
  const [intervalo, setIntervalo] = useState(30)
  const [duracion, setDuracion] = useState(30)
  const [errores, setErrores] = useState<string[]>([])
  const [guardado, setGuardado] = useState(false)

  // Precargar con lo que ya está configurado.
  useEffect(() => {
    const c = configQ.data
    if (!c) return
    setInicio(c.agenda_start_hour)
    setFin(c.agenda_end_hour)
    setIntervalo(c.slot_interval_minutes)
    setDuracion(c.default_appointment_duration)
  }, [configQ.data])

  const guardar = async () => {
    setErrores([])
    setGuardado(false)
    if (fin <= inicio) {
      setErrores(['La hora de cierre debe ser posterior a la de apertura.'])
      return
    }
    try {
      await actualizar.mutateAsync({
        agenda_start_hour: inicio,
        agenda_end_hour: fin,
        slot_interval_minutes: intervalo,
        default_appointment_duration: duracion,
      })
      setGuardado(true)
      setTimeout(() => setGuardado(false), 2500)
    } catch (err) {
      setErrores(erroresDe(err, 'No se pudo guardar el horario.'))
    }
  }

  if (configQ.isLoading) {
    return (
      <div className="flex items-center justify-center py-10 text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando horario…
      </div>
    )
  }

  const franjas = Math.max(0, Math.ceil(((fin - inicio) * 60) / intervalo))

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver el horario, pero solo el Dueño y el Administrador lo cambian." />}
      <Nota>
        Define el horario que abarca la agenda y cada cuántos minutos aparece una línea.
        Aplica a toda la clínica. La duración de consulta de cada médico se ajusta en su
        ficha, dentro de <strong>Personal</strong>.
      </Nota>

      <AlertaErrores errores={errores} />
      <AvisoGuardado visible={guardado} />

      <div
        className="rounded-2xl p-4 space-y-4"
        style={{ background: 'rgba(255,255,255,0.72)', border: '1px solid rgba(201,162,39,0.18)' }}
      >
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
          <div>
            <label className="label">La agenda abre a las</label>
            <select className="input" value={inicio} disabled={!editable}
              onChange={e => setInicio(Number(e.target.value))}>
              {HORAS_APERTURA.map(h => <option key={h} value={h}>{etiquetaHora(h)}</option>)}
            </select>
          </div>
          <div>
            <label className="label">y cierra a las</label>
            <select className="input" value={fin} disabled={!editable}
              onChange={e => setFin(Number(e.target.value))}>
              {HORAS_CIERRE.map(h => <option key={h} value={h}>{etiquetaHora(h)}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Una línea cada</label>
            <select className="input" value={intervalo} disabled={!editable}
              onChange={e => setIntervalo(Number(e.target.value))}>
              {INTERVALOS_REJILLA.map(i => <option key={i} value={i}>{i} minutos</option>)}
            </select>
          </div>
          <div>
            <label className="label">Duración de consulta por defecto</label>
            <input type="number" className="input" min={5} max={480} step={5} value={duracion}
              disabled={!editable}
              onChange={e => setDuracion(Number(e.target.value))} />
            <p className="text-[11px] text-gray-500 mt-1">
              Se usa cuando el médico no tiene una duración propia.
            </p>
          </div>
        </div>

        {/* Vista previa en palabras: que se entienda sin ir a la agenda. */}
        <div className="flex items-start gap-2 rounded-xl px-3 py-2.5 text-sm"
          style={{ background: 'rgba(201,162,39,0.10)', color: '#7A6320' }}>
          <Clock className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            La agenda mostrará de <strong>{etiquetaHora(inicio)}</strong> a{' '}
            <strong>{etiquetaHora(fin)}</strong>, con una línea cada{' '}
            <strong>{intervalo} min</strong> ({franjas} franjas).
            {fin <= inicio && ' ⚠️ El cierre debe ser posterior a la apertura.'}
          </span>
        </div>

        {editable && (
          <div className="flex justify-end">
            <button className="btn-primary" onClick={guardar} disabled={actualizar.isPending || fin <= inicio}>
              {actualizar.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Guardar horario
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
