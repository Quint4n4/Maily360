/**
 * SignosTab — pestaña Signos Vitales (append-only).
 * Formulario de captura + tabla de tomas (con IMC) + gráficas de tendencia (series).
 */

import { useState } from 'react'
import {
  Activity, Plus, Loader2, TrendingUp,
  Scale, Ruler, Heart, Wind, Gauge, Thermometer, Droplet, FlaskConical, ClipboardList,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { ExtraParamKey, SeriesKey, VitalSignsInput, VitalSignsRecord } from '../../types/expediente'
import { useCreateVitalSigns, useVitalSigns, useVitalSignsSeries } from '../../hooks/expediente'
import { formatFechaHora } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import type { VitalKey } from '../../lib/validacion'
import { VITAL_RANGES, errorDeSignoVital } from '../../lib/validacion'
import { Card, Cargando, ErroresAlerta, Vacio } from './ui'
import TendenciaChart from './TendenciaChart'

/** Campos numéricos del formulario (string en el input → number al enviar). */
interface SignosForm {
  measured_at: string
  weight_kg: string
  height_m: string
  heart_rate: string
  resp_rate: string
  systolic: string
  diastolic: string
  temperature_c: string
  oxygen_saturation: string
  glucose: string
  colesterol: string
  trigliceridos: string
  urea: string
  creatinina: string
  hemoglobina: string
  notes: string
}

const FORM_VACIO: SignosForm = {
  measured_at: '', weight_kg: '', height_m: '', heart_rate: '', resp_rate: '',
  systolic: '', diastolic: '', temperature_c: '', oxygen_saturation: '', glucose: '',
  colesterol: '', trigliceridos: '', urea: '', creatinina: '', hemoglobina: '', notes: '',
}

const EXTRA_KEYS: ExtraParamKey[] = ['colesterol', 'trigliceridos', 'urea', 'creatinina', 'hemoglobina']

/** Signos vitales con rango fisiológico validable en vivo (VITAL_RANGES). */
const VITALES_VALIDABLES: { key: VitalKey; label: string }[] = [
  { key: 'weight_kg', label: 'Peso' },
  { key: 'height_m', label: 'Estatura' },
  { key: 'heart_rate', label: 'Frecuencia Cardiaca' },
  { key: 'resp_rate', label: 'Frecuencia Respiratoria' },
  { key: 'systolic', label: 'Presión Sistólica' },
  { key: 'diastolic', label: 'Presión Diastólica' },
  { key: 'temperature_c', label: 'Temperatura' },
  { key: 'oxygen_saturation', label: 'Saturación de Oxígeno' },
  { key: 'glucose', label: 'Glucosa' },
]

/** num | undefined desde un string del input. */
function num(v: string): number | undefined {
  if (v.trim() === '') return undefined
  const n = Number(v)
  return Number.isNaN(n) ? undefined : n
}

/** Series disponibles para graficar (clave → etiqueta + unidad). */
const SERIES_GRAFICAS: { key: SeriesKey; label: string }[] = [
  { key: 'weight_kg', label: 'Peso (kg)' },
  { key: 'imc', label: 'IMC' },
  { key: 'systolic', label: 'Presión sistólica (mmHg)' },
  { key: 'diastolic', label: 'Presión diastólica (mmHg)' },
  { key: 'heart_rate', label: 'Frecuencia cardíaca (lpm)' },
  { key: 'glucose', label: 'Glucosa (mg/dL)' },
  { key: 'oxygen_saturation', label: 'SatO₂ (%)' },
  { key: 'temperature_c', label: 'Temperatura (°C)' },
]

interface SignosTabProps {
  paciente: PatientOut
  /** owner/admin/doctor/nurse pueden capturar. */
  puedeCapturar: boolean
}

export default function SignosTab({ paciente, puedeCapturar }: SignosTabProps) {
  const { data: tomasData, isLoading, isError } = useVitalSigns(paciente.id)
  const { data: series } = useVitalSignsSeries(paciente.id)
  const crear = useCreateVitalSigns(paciente.id)
  const [form, setForm] = useState<SignosForm>(FORM_VACIO)
  const [errores, setErrores] = useState<string[]>([])
  const [abierto, setAbierto] = useState(true)
  const [graficaSel, setGraficaSel] = useState<SeriesKey>('weight_kg')

  const tomas: VitalSignsRecord[] = tomasData?.results ?? []

  const set = (k: keyof SignosForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const guardar = async () => {
    setErrores([])
    // Validar rangos de los signos vitales en vivo (el backend es la autoridad).
    const errSignos: string[] = []
    for (const c of VITALES_VALIDABLES) {
      const msg = errorDeSignoVital(c.key, form[c.key])
      if (msg) errSignos.push(`${c.label}: ${msg}.`)
    }
    if (errSignos.length > 0) { setErrores(errSignos); return }
    const extra_params: VitalSignsInput['extra_params'] = {}
    for (const k of EXTRA_KEYS) {
      const v = num(form[k])
      if (v !== undefined) extra_params[k] = v
    }
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
      notes: form.notes.trim() || undefined,
    }
    if (form.measured_at) input.measured_at = new Date(form.measured_at).toISOString()
    if (Object.keys(extra_params).length > 0) input.extra_params = extra_params
    try {
      await crear.mutateAsync(input)
      setForm(FORM_VACIO)
      setAbierto(false)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const serieActual = series ? series[graficaSel] : []
  const labelActual = SERIES_GRAFICAS.find(s => s.key === graficaSel)?.label ?? ''

  return (
    <div className="space-y-5">
      {/* Captura */}
      {puedeCapturar && (
        <Card
          title="Nueva toma"
          icon={Plus}
          action={
            <button type="button" onClick={() => setAbierto(a => !a)} className="text-xs font-semibold text-amber-700 hover:text-amber-800">
              {abierto ? 'Ocultar' : 'Capturar'}
            </button>
          }
        >
          {abierto ? (
            <div className="space-y-3">
              <ErroresAlerta errores={errores} />
              <Campo label="Fecha/hora de la toma" type="datetime-local" value={form.measured_at} onChange={set('measured_at')} />
              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
                <Campo label="Peso" value={form.weight_kg} onChange={set('weight_kg')} icon={Scale} iconColor="#16a34a" placeholder="Ej. 70.5 kg" vitalKey="weight_kg" />
                <Campo label="Estatura" value={form.height_m} onChange={set('height_m')} icon={Ruler} iconColor="#2563eb" placeholder="Ej. 1.65 m" vitalKey="height_m" />
                <Campo label="Frecuencia Cardiaca" value={form.heart_rate} onChange={set('heart_rate')} icon={Heart} iconColor="#dc2626" placeholder="Ej. 72 lpm" vitalKey="heart_rate" />
                <Campo label="Frecuencia Respiratoria" value={form.resp_rate} onChange={set('resp_rate')} icon={Wind} iconColor="#7c3aed" placeholder="Ej. 16 rpm" vitalKey="resp_rate" />
                <Campo label="Presión Sistólica" value={form.systolic} onChange={set('systolic')} icon={Gauge} iconColor="#ea580c" placeholder="Ej. 120 mmHg" vitalKey="systolic" />
                <Campo label="Presión Diastólica" value={form.diastolic} onChange={set('diastolic')} icon={Gauge} iconColor="#ea580c" placeholder="Ej. 80 mmHg" vitalKey="diastolic" />
                <Campo label="Temperatura" value={form.temperature_c} onChange={set('temperature_c')} icon={Thermometer} iconColor="#0d9488" placeholder="Ej. 36.5 °C" vitalKey="temperature_c" />
                <Campo label="Saturación de Oxígeno" value={form.oxygen_saturation} onChange={set('oxygen_saturation')} icon={Activity} iconColor="#ca8a04" placeholder="Ej. 98 %" vitalKey="oxygen_saturation" />
                <Campo label="Glucosa" value={form.glucose} onChange={set('glucose')} icon={Droplet} iconColor="#0284c7" placeholder="Ej. 90 mg/dL" vitalKey="glucose" />
              </div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 pt-2">Laboratorio (opcional)</p>
              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
                <Campo label="Colesterol" value={form.colesterol} onChange={set('colesterol')} icon={FlaskConical} iconColor="#b45309" placeholder="Ej. 180" min={50} max={800} />
                <Campo label="Triglicéridos" value={form.trigliceridos} onChange={set('trigliceridos')} icon={FlaskConical} iconColor="#b45309" placeholder="Ej. 150" min={20} max={2000} />
                <Campo label="Urea" value={form.urea} onChange={set('urea')} icon={FlaskConical} iconColor="#b45309" placeholder="Ej. 30" min={5} max={300} />
                <Campo label="Creatinina" value={form.creatinina} onChange={set('creatinina')} icon={FlaskConical} iconColor="#b45309" placeholder="Ej. 0.9" min={0.1} max={20} />
                <Campo label="Hemoglobina" value={form.hemoglobina} onChange={set('hemoglobina')} icon={Droplet} iconColor="#dc2626" placeholder="Ej. 14" min={3} max={25} />
              </div>
              <Campo label="Observaciones" type="text" value={form.notes} onChange={set('notes')} icon={ClipboardList} iconColor="#9A7B1E" placeholder="Ej. Paciente estable, sin novedades" />
              <div className="flex justify-end">
                <button
                  type="button" onClick={guardar} disabled={crear.isPending}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                  style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
                >
                  {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : <><Plus className="w-4 h-4" /> Registrar toma</>}
                </button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">Captura peso, talla, presión, temperatura, SatO₂, glucosa y laboratorio.</p>
          )}
        </Card>
      )}

      {/* Última toma (la más reciente, destacada) */}
      {!isLoading && !isError && tomas.length > 0 && (
        <Card title="Última toma" icon={Activity}>
          <p className="text-xs text-gray-400 mb-3">
            {formatFechaHora(tomas[0].measured_at)}
            {tomas[0].created_by_name && <> · Capturado por {tomas[0].created_by_name}</>}
          </p>
          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))' }}>
            <DatoToma label="Peso" value={tomas[0].weight_kg} unidad="kg" />
            <DatoToma label="Estatura" value={tomas[0].height_m} unidad="m" />
            <DatoToma label="IMC" value={tomas[0].imc} destacado />
            <DatoToma
              label="Presión Arterial"
              value={tomas[0].systolic != null && tomas[0].diastolic != null ? `${tomas[0].systolic}/${tomas[0].diastolic}` : null}
              unidad="mmHg"
            />
            <DatoToma label="Frecuencia Cardiaca" value={tomas[0].heart_rate} unidad="lpm" />
            <DatoToma label="Frecuencia Respiratoria" value={tomas[0].resp_rate} unidad="rpm" />
            <DatoToma label="Temperatura" value={tomas[0].temperature_c} unidad="°C" />
            <DatoToma label="Saturación de Oxígeno" value={tomas[0].oxygen_saturation} unidad="%" />
            <DatoToma label="Glucosa" value={tomas[0].glucose} unidad="mg/dL" />
          </div>
        </Card>
      )}

      {/* Gráfica de tendencia */}
      <Card title="Tendencia" icon={TrendingUp}
        action={
          <select className="input py-1 text-xs" style={{ width: 'auto' }}
            value={graficaSel} onChange={e => setGraficaSel(e.target.value as SeriesKey)}>
            {SERIES_GRAFICAS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        }
      >
        <TendenciaChart data={serieActual} label={labelActual} />
      </Card>

      {/* Tabla de tomas */}
      <Card title="Tomas registradas" icon={Activity}>
        {isLoading ? (
          <Cargando texto="Cargando tomas…" />
        ) : isError ? (
          <p className="text-sm text-red-600 text-center py-6">No se pudieron cargar las tomas.</p>
        ) : tomas.length === 0 ? (
          <Vacio texto="Aún no hay tomas de signos vitales." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 text-left border-b border-amber-900/10">
                  <th className="py-2 pr-3 font-medium">Fecha</th>
                  <th className="py-2 px-3 font-medium">Peso</th>
                  <th className="py-2 px-3 font-medium">Talla</th>
                  <th className="py-2 px-3 font-medium">IMC</th>
                  <th className="py-2 px-3 font-medium">PA</th>
                  <th className="py-2 px-3 font-medium">FC</th>
                  <th className="py-2 px-3 font-medium">FR</th>
                  <th className="py-2 px-3 font-medium">Temp</th>
                  <th className="py-2 px-3 font-medium">SatO₂</th>
                  <th className="py-2 px-3 font-medium">Glucosa</th>
                </tr>
              </thead>
              <tbody>
                {tomas.map(t => (
                  <tr key={t.id} className="border-b border-amber-900/5 last:border-0">
                    <td className="py-2 pr-3 text-gray-700 whitespace-nowrap">
                      {formatFechaHora(t.measured_at)}
                      {t.created_by_name && (
                        <span className="block text-[10px] font-normal text-gray-400">
                          Capturado por {t.created_by_name}
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-gray-700">{t.weight_kg ?? '—'}</td>
                    <td className="py-2 px-3 text-gray-700">{t.height_m ?? '—'}</td>
                    <td className="py-2 px-3 font-semibold" style={{ color: '#B8860B' }}>{t.imc ?? '—'}</td>
                    <td className="py-2 px-3 text-gray-700">
                      {t.systolic != null && t.diastolic != null ? `${t.systolic}/${t.diastolic}` : '—'}
                    </td>
                    <td className="py-2 px-3 text-gray-700">{t.heart_rate ?? '—'}</td>
                    <td className="py-2 px-3 text-gray-700">{t.resp_rate ?? '—'}</td>
                    <td className="py-2 px-3 text-gray-700">{t.temperature_c ?? '—'}</td>
                    <td className="py-2 px-3 text-gray-700">{t.oxygen_saturation ?? '—'}</td>
                    <td className="py-2 px-3 text-gray-700">{t.glucose ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function Campo({
  label, value, onChange, type = 'number', icon: Icon, iconColor = '#9A7B1E', placeholder, vitalKey, min, max,
}: {
  label: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void
  type?: string
  icon?: typeof Activity
  iconColor?: string
  placeholder?: string
  /** Si es un signo vital validable, su clave para validar rango en vivo (VITAL_RANGES). */
  vitalKey?: VitalKey
  /** Rango plausible para inputs NO vitales (p. ej. laboratorio); solo hint de UX. */
  min?: number
  max?: number
}) {
  const error = vitalKey ? errorDeSignoVital(vitalKey, value) : null
  const rango = vitalKey ? VITAL_RANGES[vitalKey] : null
  return (
    <div>
      <label className="label">{label}</label>
      <div className="flex items-stretch gap-2">
        {Icon && (
          <span
            className="flex items-center justify-center w-9 rounded-lg shrink-0"
            style={{ background: 'rgba(201,162,39,0.10)' }}
          >
            <Icon className="w-4 h-4" style={{ color: iconColor }} />
          </span>
        )}
        <input
          className={`input flex-1${error ? ' input-error' : ''}`}
          type={type} step="any"
          inputMode={type === 'number' ? 'decimal' : undefined}
          min={rango ? rango[0] : min}
          max={rango ? rango[1] : max}
          value={value} onChange={onChange} placeholder={placeholder}
          aria-invalid={error ? true : undefined}
        />
      </div>
      {error && <p className="text-[11px] text-red-600 mt-0.5">{error}</p>}
    </div>
  )
}

/** Un dato de la "Última toma" (etiqueta arriba, valor grande). */
function DatoToma({
  label, value, unidad, destacado,
}: { label: string; value: string | number | null | undefined; unidad?: string; destacado?: boolean }) {
  const hay = value != null && value !== ''
  return (
    <div className="rounded-xl px-3 py-2 bg-white/60">
      <p className="text-[11px] text-gray-400">{label}</p>
      <p className="text-base font-semibold" style={{ color: destacado ? '#B8860B' : '#374151' }}>
        {hay ? value : '—'}
        {hay && unidad && <span className="text-xs font-normal text-gray-400"> {unidad}</span>}
      </p>
    </div>
  )
}
