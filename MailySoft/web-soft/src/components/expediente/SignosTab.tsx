/**
 * SignosTab — pestaña Signos Vitales (append-only).
 * Formulario de captura + tabla de tomas (con IMC) + gráficas de tendencia (series).
 */

import { useState } from 'react'
import { Activity, Plus, Loader2, TrendingUp } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { ExtraParamKey, SeriesKey, VitalSignsInput, VitalSignsRecord } from '../../types/expediente'
import { useCreateVitalSigns, useVitalSigns, useVitalSignsSeries } from '../../hooks/expediente'
import { formatFechaHora } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
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
  const [abierto, setAbierto] = useState(false)
  const [graficaSel, setGraficaSel] = useState<SeriesKey>('weight_kg')

  const tomas: VitalSignsRecord[] = tomasData?.results ?? []

  const set = (k: keyof SignosForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const guardar = async () => {
    setErrores([])
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
              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
                <Campo label="Fecha/hora de la toma" type="datetime-local" value={form.measured_at} onChange={set('measured_at')} />
                <Campo label="Peso (kg)" value={form.weight_kg} onChange={set('weight_kg')} />
                <Campo label="Talla (m)" value={form.height_m} onChange={set('height_m')} />
                <Campo label="FC (lpm)" value={form.heart_rate} onChange={set('heart_rate')} />
                <Campo label="FR (rpm)" value={form.resp_rate} onChange={set('resp_rate')} />
                <Campo label="Sistólica (mmHg)" value={form.systolic} onChange={set('systolic')} />
                <Campo label="Diastólica (mmHg)" value={form.diastolic} onChange={set('diastolic')} />
                <Campo label="Temperatura (°C)" value={form.temperature_c} onChange={set('temperature_c')} />
                <Campo label="SatO₂ (%)" value={form.oxygen_saturation} onChange={set('oxygen_saturation')} />
                <Campo label="Glucosa (mg/dL)" value={form.glucose} onChange={set('glucose')} />
              </div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 pt-2">Laboratorio (opcional)</p>
              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
                <Campo label="Colesterol" value={form.colesterol} onChange={set('colesterol')} />
                <Campo label="Triglicéridos" value={form.trigliceridos} onChange={set('trigliceridos')} />
                <Campo label="Urea" value={form.urea} onChange={set('urea')} />
                <Campo label="Creatinina" value={form.creatinina} onChange={set('creatinina')} />
                <Campo label="Hemoglobina" value={form.hemoglobina} onChange={set('hemoglobina')} />
              </div>
              <div>
                <label className="label">Observaciones</label>
                <input className="input" value={form.notes} onChange={set('notes')} />
              </div>
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
                    <td className="py-2 pr-3 text-gray-700 whitespace-nowrap">{formatFechaHora(t.measured_at)}</td>
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
  label, value, onChange, type = 'number',
}: { label: string; value: string; onChange: (e: React.ChangeEvent<HTMLInputElement>) => void; type?: string }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input className="input" type={type} step="any" value={value} onChange={onChange} />
    </div>
  )
}
