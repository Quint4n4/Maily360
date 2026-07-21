/**
 * VisitaSignos — paso ① "Enfermería" de la tarjeta "Visita de hoy".
 *
 * Captura rápida de los signos vitales de la visita reusando EXACTAMENTE los
 * mismos hooks/payload que SignosTab (useVitalSigns para leer la última toma,
 * useCreateVitalSigns para registrar). Al guardar, muestra un resumen
 * "guardada ✓" con PA, Temp, Peso y Glucosa. No reescribe la lógica de signos:
 * solo la presenta como un paso compacto dentro de la visita.
 *
 * Es append-only igual que SignosTab; aquí se capturan los signos clave de la
 * consulta de hoy. La tabla/gráficas históricas siguen viviendo en el historial.
 */

import { useMemo, useState } from 'react'
import { Activity, Loader2, Check } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { VitalSignsInput, VitalSignsRecord } from '../../types/expediente'
import { useCreateVitalSigns, useVitalSigns } from '../../hooks/expediente'
import { formatFechaHora } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import type { VitalKey } from '../../lib/validacion'
import { VITAL_RANGES, errorDeSignoVital } from '../../lib/validacion'
import { ErroresAlerta } from './ui'

/** Campos del formulario de la toma de hoy (string en el input → number al enviar). */
interface SignosForm {
  weight_kg: string
  height_m: string
  systolic: string
  diastolic: string
  heart_rate: string
  resp_rate: string
  temperature_c: string
  oxygen_saturation: string
  glucose: string
}

const FORM_VACIO: SignosForm = {
  weight_kg: '', height_m: '', systolic: '', diastolic: '', heart_rate: '',
  resp_rate: '', temperature_c: '', oxygen_saturation: '', glucose: '',
}

/** num | undefined desde un string del input (mismo criterio que SignosTab). */
function num(v: string): number | undefined {
  if (v.trim() === '') return undefined
  const n = Number(v)
  return Number.isNaN(n) ? undefined : n
}

/** Campos del formulario en orden, con etiqueta y unidad. */
const CAMPOS: { key: VitalKey; label: string; unidad: string; placeholder: string }[] = [
  { key: 'systolic', label: 'PA sistólica', unidad: 'mmHg', placeholder: 'Ej. 120' },
  { key: 'diastolic', label: 'PA diastólica', unidad: 'mmHg', placeholder: 'Ej. 80' },
  { key: 'temperature_c', label: 'Temperatura', unidad: '°C', placeholder: 'Ej. 36.5' },
  { key: 'weight_kg', label: 'Peso', unidad: 'kg', placeholder: 'Ej. 70.5' },
  { key: 'height_m', label: 'Talla', unidad: 'm', placeholder: 'Ej. 1.65' },
  { key: 'heart_rate', label: 'FC', unidad: 'lpm', placeholder: 'Ej. 72' },
  { key: 'resp_rate', label: 'FR', unidad: 'rpm', placeholder: 'Ej. 16' },
  { key: 'oxygen_saturation', label: 'SatO₂', unidad: '%', placeholder: 'Ej. 98' },
  { key: 'glucose', label: 'Glucosa', unidad: 'mg/dL', placeholder: 'Ej. 90' },
]

interface VisitaSignosProps {
  paciente: PatientOut
  /**
   * Formulario de captura abierto. Lo controla VisitaDeHoy, que mantiene un
   * solo paso abierto a la vez para que la tarjeta de la visita quepa en
   * pantalla junto al índice de secciones.
   */
  abierto: boolean
  /** Cerrar el paso (al cancelar o después de guardar). */
  onCerrar: () => void
}

export default function VisitaSignos({ paciente, abierto, onCerrar }: VisitaSignosProps) {
  const { data: tomasData, isLoading } = useVitalSigns(paciente.id)
  const crear = useCreateVitalSigns(paciente.id)
  const [form, setForm] = useState<SignosForm>(FORM_VACIO)
  const [errores, setErrores] = useState<string[]>([])

  const tomas: VitalSignsRecord[] = useMemo(() => tomasData?.results ?? [], [tomasData])
  const ultima: VitalSignsRecord | null = tomas[0] ?? null

  const set = (k: keyof SignosForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const guardar = async () => {
    setErrores([])
    const input: VitalSignsInput = {
      weight_kg: num(form.weight_kg),
      height_m: num(form.height_m),
      heart_rate: num(form.heart_rate),
      resp_rate: num(form.resp_rate),
      systolic: num(form.systolic),
      diastolic: num(form.diastolic),
      temperature_c: num(form.temperature_c),
      oxygen_saturation: num(form.oxygen_saturation),
      glucose: num(form.glucose),
    }
    // Evitar mandar una toma totalmente vacía.
    const algunValor = Object.values(input).some(v => v !== undefined)
    if (!algunValor) {
      setErrores(['Captura al menos un signo vital para guardar la toma.'])
      return
    }
    // Validar rangos de signos en vivo (el backend es la autoridad).
    const errSignos: string[] = []
    for (const c of CAMPOS) {
      const msg = errorDeSignoVital(c.key, form[c.key])
      if (msg) errSignos.push(`${c.label}: ${msg}.`)
    }
    if (errSignos.length > 0) { setErrores(errSignos); return }
    try {
      await crear.mutateAsync(input)
      setForm(FORM_VACIO)
      onCerrar()
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const pa = ultima && ultima.systolic != null && ultima.diastolic != null
    ? `${ultima.systolic}/${ultima.diastolic} mmHg`
    : null

  // Cerrado: resumen de una línea con la última toma. Los signos del día son
  // dato de consulta constante, así que siguen a la vista sin abrir el paso.
  if (!abierto) {
    if (isLoading) return <p className="text-xs text-gray-400 italic">Cargando signos…</p>
    if (!ultima) return <p className="text-xs text-gray-400 italic">Sin signos capturados aún.</p>
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        <ResumenDato label="PA" value={pa} />
        <ResumenDato label="Temp" value={ultima.temperature_c} unidad="°C" />
        <ResumenDato label="Peso" value={ultima.weight_kg} unidad="kg" />
        <ResumenDato label="Glucosa" value={ultima.glucose} unidad="mg/dL" />
        <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
          <Check className="w-3 h-3" style={{ color: '#0E7C7B' }} />
          {formatFechaHora(ultima.measured_at)}
          {ultima.created_by_name ? ` · ${ultima.created_by_name}` : ''}
        </span>
      </div>
    )
  }

  return (
    <div className="space-y-3 rounded-xl p-3.5" style={{ background: 'rgba(255,255,255,0.6)', border: '1px solid rgba(14,124,123,0.2)' }}>
      <ErroresAlerta errores={errores} />
      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))' }}>
        {CAMPOS.map(c => {
          const error = errorDeSignoVital(c.key, form[c.key])
          const [min, max] = VITAL_RANGES[c.key]
          return (
            <div key={c.key}>
              <label className="label">
                {c.label} <span className="text-gray-400 font-normal">({c.unidad})</span>
              </label>
              <input
                className={`input${error ? ' input-error' : ''}`}
                type="number" step="any" inputMode="decimal"
                min={min} max={max}
                placeholder={c.placeholder}
                value={form[c.key]}
                onChange={set(c.key)}
                aria-invalid={error ? true : undefined}
              />
              {error && <p className="text-[11px] text-red-600 mt-0.5">{error}</p>}
            </div>
          )
        })}
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={() => { onCerrar(); setErrores([]); setForm(FORM_VACIO) }}
          className="btn-secondary text-xs px-3 py-1.5"
        >
          Cancelar
        </button>
        <button
          type="button" onClick={guardar} disabled={crear.isPending}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-white px-4 py-1.5 rounded-lg disabled:opacity-60"
          style={{ background: '#0E7C7B' }}
        >
          {crear.isPending
            ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Guardando…</>
            : <><Activity className="w-3.5 h-3.5" /> Guardar signos</>}
        </button>
      </div>
    </div>
  )
}

/** Un dato del resumen de signos (pastilla). */
function ResumenDato({
  label, value, unidad,
}: { label: string; value: string | number | null | undefined; unidad?: string }) {
  const hay = value != null && value !== ''
  if (!hay) return null
  return (
    <span className="inline-flex items-baseline gap-1 rounded-lg px-2.5 py-1 bg-white/70">
      <span className="text-[10px] text-gray-400">{label}</span>
      <span className="text-sm font-semibold text-gray-700">
        {value}{unidad && <span className="text-[10px] font-normal text-gray-400"> {unidad}</span>}
      </span>
    </span>
  )
}
