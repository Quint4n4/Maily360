/**
 * HistoriaTab — pestaña Historia Clínica (NOM-004).
 * Acordeón por bloques con las claves reales del backend.
 * GET para cargar (documento vivo), PUT para guardar (upsert).
 * El bloque gineco-obstétrico se oculta si el paciente no es sexo F.
 */

import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, Save, Loader2, FileText } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type {
  ExploracionFisicaBasal,
  ExploracionSistema,
  GinecoObstetricos,
  HabitosAlimenticios,
  HeredoFamiliares,
  MedicalHistory,
  MedicalHistoryInput,
  NoPatologicos,
  PersonalesPatologicos,
  ViviendaChoice,
} from '../../types/expediente'
import { useMedicalHistory, useUpsertMedicalHistory } from '../../hooks/expediente'
import { erroresDe } from '../../lib/apiErrors'
import {
  Cargando, ErroresAlerta, EXPLORACION_BASAL_OPTIONS, SistemaLabelConIcono, VIVIENDA_OPTIONS,
} from './ui'

/** Estado editable de la HC en el formulario (todos los bloques presentes). */
interface FormState {
  heredo_familiares: HeredoFamiliares
  personales_patologicos: PersonalesPatologicos
  no_patologicos: NoPatologicos
  habitos_alimenticios: HabitosAlimenticios
  gineco_obstetricos: GinecoObstetricos
  exploracion_fisica_basal: ExploracionFisicaBasal
  antecedentes_importancia: string
  padecimiento_actual: string
  tratamientos_actuales: string
  prioridad_analisis: string
}

/** Bloques objeto (JSON) de la HC — excluye los campos de texto plano. */
type BlockKey =
  | 'heredo_familiares'
  | 'personales_patologicos'
  | 'no_patologicos'
  | 'habitos_alimenticios'
  | 'gineco_obstetricos'

/** Construye el estado del formulario desde la HC recibida. */
function fromHistory(h: MedicalHistory): FormState {
  return {
    heredo_familiares: { ...h.heredo_familiares },
    personales_patologicos: { ...h.personales_patologicos },
    no_patologicos: { ...h.no_patologicos },
    habitos_alimenticios: { ...h.habitos_alimenticios },
    gineco_obstetricos: { ...h.gineco_obstetricos },
    exploracion_fisica_basal: { ...h.exploracion_fisica_basal },
    antecedentes_importancia: h.antecedentes_importancia,
    padecimiento_actual: h.padecimiento_actual,
    tratamientos_actuales: h.tratamientos_actuales,
    prioridad_analisis: h.prioridad_analisis,
  }
}

// ── Metadatos de los campos string de cada bloque (clave → etiqueta) ──────────

const AHF_FIELDS: { key: keyof HeredoFamiliares; label: string }[] = [
  { key: 'diabetes', label: 'Diabetes' },
  { key: 'hipertension_arterial', label: 'Hipertensión arterial' },
  { key: 'cardiopatias', label: 'Cardiopatías' },
  { key: 'hepatopatias', label: 'Hepatopatías' },
  { key: 'urologicos', label: 'Urológicos' },
  { key: 'neurologicos', label: 'Neurológicos' },
  { key: 'respiratorias', label: 'Respiratorias' },
  { key: 'cancer', label: 'Cáncer' },
  { key: 'alergicas', label: 'Alérgicas' },
  { key: 'metabolicas', label: 'Metabólicas' },
  { key: 'sanguineas', label: 'Sanguíneas' },
  { key: 'articulares', label: 'Articulares' },
  { key: 'inmunologicas', label: 'Inmunológicas' },
  { key: 'malformaciones', label: 'Malformaciones' },
  { key: 'dermatologicas', label: 'Dermatológicas' },
  { key: 'otros', label: 'Otros' },
]

const APP_FIELDS: { key: keyof PersonalesPatologicos; label: string }[] = [
  { key: 'enfermedades_infancia', label: 'Enfermedades de la infancia' },
  { key: 'diabetes', label: 'Diabetes' },
  { key: 'hipertension', label: 'Hipertensión' },
  { key: 'respiratorias', label: 'Respiratorias' },
  { key: 'oftalmico', label: 'Oftálmico' },
  { key: 'cardiovasculares', label: 'Cardiovasculares' },
  { key: 'neurologicos', label: 'Neurológicos' },
  { key: 'gastrointestinales', label: 'Gastrointestinales' },
  { key: 'hepatopatias', label: 'Hepatopatías' },
  { key: 'metabolicas', label: 'Metabólicas' },
  { key: 'urologicos', label: 'Urológicos' },
  { key: 'circulatorio', label: 'Circulatorio' },
  { key: 'traumaticas', label: 'Traumáticas' },
  { key: 'articulares', label: 'Articulares' },
  { key: 'dermatologicas', label: 'Dermatológicas' },
  { key: 'quirurgicos', label: 'Quirúrgicos' },
  { key: 'transfusionales', label: 'Transfusionales' },
  { key: 'vectores', label: 'Vectores' },
  { key: 'autoinmunes', label: 'Autoinmunes' },
  { key: 'emocionales', label: 'Emocionales' },
  { key: 'adicciones', label: 'Adicciones' },
  { key: 'hospitalizaciones_previas', label: 'Hospitalizaciones previas' },
  { key: 'pesticidas', label: 'Pesticidas' },
  { key: 'dx_cancer', label: 'Diagnóstico de cáncer' },
  { key: 'otros', label: 'Otros' },
]

const APNP_FIELDS: { key: keyof NoPatologicos; label: string }[] = [
  { key: 'servicios_basicos', label: 'Servicios básicos' },
  { key: 'actividad_fisica', label: 'Actividad física' },
  { key: 'tabaquismo', label: 'Tabaquismo' },
  { key: 'alcoholismo', label: 'Alcoholismo' },
  { key: 'otras_toxicomanias', label: 'Otras toxicomanías' },
  { key: 'inmunizaciones', label: 'Inmunizaciones' },
  { key: 'ultima_desparasitacion', label: 'Última desparasitación' },
  { key: 'otros', label: 'Otros' },
]

const HABITOS_FIELDS: { key: keyof HabitosAlimenticios; label: string }[] = [
  { key: 'dieta_especial', label: 'Dieta especial' },
  { key: 'intolerancias_alimentarias', label: 'Intolerancias alimentarias' },
  { key: 'consumo_agua_litros', label: 'Consumo de agua (litros)' },
  { key: 'suplementos', label: 'Suplementos' },
]

const AGO_FIELDS: { key: keyof GinecoObstetricos; label: string }[] = [
  { key: 'menarca', label: 'Menarca' },
  { key: 'ritmo_menstrual', label: 'Ritmo menstrual' },
  { key: 'alteraciones', label: 'Alteraciones' },
  { key: 'fum', label: 'FUM (última menstruación)' },
  { key: 'ivsa', label: 'IVSA' },
  { key: 'numero_parejas', label: 'Número de parejas' },
  { key: 'gestas', label: 'Gestas' },
  { key: 'abortos', label: 'Abortos' },
  { key: 'partos', label: 'Partos' },
  { key: 'cesareas', label: 'Cesáreas' },
  { key: 'fup', label: 'FUP (último parto)' },
  { key: 'metodo_planificacion', label: 'Método de planificación' },
  { key: 'citologia_vaginal', label: 'Citología vaginal' },
  { key: 'colposcopia', label: 'Colposcopia' },
  { key: 'usg_pelvico', label: 'USG pélvico' },
  { key: 'mastografia', label: 'Mastografía' },
  { key: 'usg_mamas', label: 'USG de mamas' },
  { key: 'menopausia_climaterio', label: 'Menopausia / climaterio' },
  { key: 'tratamientos_hormonales', label: 'Tratamientos hormonales' },
]

const SISTEMAS: ExploracionSistema[] = [
  'cerebro', 'sistema_nervioso', 'ocular', 'endocrino', 'corazon', 'circulatorio',
  'respiratorio', 'hepatico', 'pancreas', 'renal', 'gastrointestinal', 'osteoarticular',
  'tendomuscular', 'reproductor', 'inmunologico', 'extremidades', 'piel_tegumentos', 'otros',
]

interface HistoriaTabProps {
  paciente: PatientOut
  /** owner/admin/doctor pueden editar; el resto solo lectura. */
  puedeEditar: boolean
}

export default function HistoriaTab({ paciente, puedeEditar }: HistoriaTabProps) {
  const { data, isLoading, isError } = useMedicalHistory(paciente.id)
  const guardar = useUpsertMedicalHistory(paciente.id)
  const [form, setForm] = useState<FormState | null>(null)
  const [errores, setErrores] = useState<string[]>([])
  const [okMsg, setOkMsg] = useState('')
  const esFemenino = paciente.sex === 'F'

  useEffect(() => {
    if (data) setForm(fromHistory(data))
  }, [data])

  // Setters tipados por bloque (solo los bloques objeto, no los textos planos).
  const setStr = <B extends BlockKey>(block: B) =>
    (key: keyof FormState[B]) =>
      (value: string) =>
        setForm(f => (f ? { ...f, [block]: { ...(f[block] as object), [key]: value } } : f))

  const setTexto = (key: 'antecedentes_importancia' | 'padecimiento_actual' | 'tratamientos_actuales' | 'prioridad_analisis') =>
    (value: string) => setForm(f => (f ? { ...f, [key]: value } : f))

  const setSistema = (sistema: ExploracionSistema, patch: Partial<{ estado: string; detalle: string }>) =>
    setForm(f => {
      if (!f) return f
      const prev = f.exploracion_fisica_basal[sistema] ?? {}
      return {
        ...f,
        exploracion_fisica_basal: {
          ...f.exploracion_fisica_basal,
          [sistema]: { ...prev, ...patch },
        },
      }
    })

  const onGuardar = async () => {
    if (!form) return
    setErrores([]); setOkMsg('')
    // Construir payload: gineco solo si es femenino (el backend rechaza si no lo es).
    const payload: MedicalHistoryInput = {
      heredo_familiares: form.heredo_familiares,
      personales_patologicos: form.personales_patologicos,
      no_patologicos: form.no_patologicos,
      habitos_alimenticios: form.habitos_alimenticios,
      exploracion_fisica_basal: form.exploracion_fisica_basal,
      antecedentes_importancia: form.antecedentes_importancia,
      padecimiento_actual: form.padecimiento_actual,
      tratamientos_actuales: form.tratamientos_actuales,
      prioridad_analisis: form.prioridad_analisis,
    }
    if (esFemenino) payload.gineco_obstetricos = form.gineco_obstetricos
    try {
      await guardar.mutateAsync(payload)
      setOkMsg('Historia clínica guardada.')
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const bloques = useMemo(() => {
    if (!form) return []
    const set = setStr
    const list: { id: string; titulo: string; render: () => JSX.Element }[] = [
      {
        id: 'ahf', titulo: 'Antecedentes heredo-familiares',
        render: () => (
          <BloqueGrid>
            <NumberField
              label="Número de hermanos"
              value={form.heredo_familiares.numero_hermanos ?? null}
              onChange={v => setForm(f => (f ? { ...f, heredo_familiares: { ...f.heredo_familiares, numero_hermanos: v } } : f))}
              disabled={!puedeEditar}
            />
            {AHF_FIELDS.map(({ key, label }) => (
              <TextField key={key} label={label}
                value={(form.heredo_familiares[key] as string | null | undefined) ?? ''}
                onChange={set('heredo_familiares')(key)} placeholder="Negado" disabled={!puedeEditar} />
            ))}
          </BloqueGrid>
        ),
      },
      {
        id: 'app', titulo: 'Antecedentes personales patológicos',
        render: () => (
          <BloqueGrid>
            {APP_FIELDS.map(({ key, label }) => (
              <TextField key={key} label={label}
                value={(form.personales_patologicos[key] as string | null | undefined) ?? ''}
                onChange={set('personales_patologicos')(key)} placeholder="Negado" disabled={!puedeEditar} />
            ))}
          </BloqueGrid>
        ),
      },
      {
        id: 'apnp', titulo: 'Antecedentes no patológicos',
        render: () => (
          <BloqueGrid>
            <div>
              <label className="label">Casa habitación</label>
              <select className="input"
                value={(form.no_patologicos.casa_habitacion as string | undefined) ?? ''}
                onChange={e => set('no_patologicos')('casa_habitacion')(e.target.value as ViviendaChoice | '')}
                disabled={!puedeEditar}>
                {VIVIENDA_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            {APNP_FIELDS.map(({ key, label }) => (
              <TextField key={key} label={label}
                value={(form.no_patologicos[key] as string | null | undefined) ?? ''}
                onChange={set('no_patologicos')(key)} placeholder="Sin alteraciones" disabled={!puedeEditar} />
            ))}
          </BloqueGrid>
        ),
      },
      {
        id: 'habitos', titulo: 'Hábitos alimenticios',
        render: () => (
          <BloqueGrid>
            <NumberField
              label="Número de comidas al día"
              value={form.habitos_alimenticios.numero_comidas_dia ?? null}
              onChange={v => setForm(f => (f ? { ...f, habitos_alimenticios: { ...f.habitos_alimenticios, numero_comidas_dia: v } } : f))}
              disabled={!puedeEditar}
            />
            {HABITOS_FIELDS.map(({ key, label }) => (
              <TextField key={key} label={label}
                value={(form.habitos_alimenticios[key] as string | null | undefined) ?? ''}
                onChange={set('habitos_alimenticios')(key)} disabled={!puedeEditar} />
            ))}
          </BloqueGrid>
        ),
      },
    ]

    if (esFemenino) {
      list.push({
        id: 'ago', titulo: 'Antecedentes gineco-obstétricos',
        render: () => (
          <BloqueGrid>
            {AGO_FIELDS.map(({ key, label }) => (
              <TextField key={key} label={label}
                value={(form.gineco_obstetricos[key] as string | null | undefined) ?? ''}
                onChange={set('gineco_obstetricos')(key)} disabled={!puedeEditar} />
            ))}
          </BloqueGrid>
        ),
      })
    }

    list.push({
      id: 'exploracion', titulo: 'Exploración física basal',
      render: () => (
        <div className="space-y-2">
          {SISTEMAS.map(sistema => {
            const celda = form.exploracion_fisica_basal[sistema] ?? {}
            return (
              <div key={sistema} className="grid items-center gap-2" style={{ gridTemplateColumns: '160px 180px 1fr' }}>
                <span className="text-sm text-gray-700"><SistemaLabelConIcono sistema={sistema} /></span>
                <select className="input"
                  value={celda.estado ?? 'sin_alteraciones'}
                  onChange={e => setSistema(sistema, { estado: e.target.value })}
                  disabled={!puedeEditar}>
                  {EXPLORACION_BASAL_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <input className="input"
                  placeholder="Detalle (opcional)"
                  value={celda.detalle ?? ''}
                  onChange={e => setSistema(sistema, { detalle: e.target.value })}
                  disabled={!puedeEditar} />
              </div>
            )
          })}
        </div>
      ),
    })

    list.push({
      id: 'padecimiento', titulo: 'Padecimiento actual y plan',
      render: () => (
        <div className="space-y-3">
          <TextArea label="Antecedentes de importancia"
            value={form.antecedentes_importancia} onChange={setTexto('antecedentes_importancia')} disabled={!puedeEditar} />
          <TextArea label="Padecimiento actual"
            value={form.padecimiento_actual} onChange={setTexto('padecimiento_actual')} disabled={!puedeEditar} />
          <TextArea label="Tratamientos actuales"
            value={form.tratamientos_actuales} onChange={setTexto('tratamientos_actuales')} disabled={!puedeEditar} />
          <TextArea label="Prioridad de análisis"
            value={form.prioridad_analisis} onChange={setTexto('prioridad_analisis')} disabled={!puedeEditar} />
        </div>
      ),
    })

    return list
  }, [form, esFemenino, puedeEditar])

  if (isLoading) return <Cargando texto="Cargando historia clínica…" />
  if (isError) return <p className="text-sm text-red-600 py-8 text-center">No se pudo cargar la historia clínica.</p>
  if (!form) return null

  return (
    <div className="space-y-4">
      <ErroresAlerta errores={errores} />
      {okMsg && (
        <div className="rounded-xl px-4 py-2.5 text-sm" style={{ background: '#DCF3E6', color: '#1F6E47' }}>{okMsg}</div>
      )}

      {bloques.map(b => <Acordeon key={b.id} titulo={b.titulo}>{b.render()}</Acordeon>)}

      {puedeEditar && (
        <div className="flex justify-end pt-2">
          <button
            type="button" onClick={onGuardar} disabled={guardar.isPending}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
          >
            {guardar.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : <><Save className="w-4 h-4" /> Guardar historia clínica</>}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Sub-componentes de formulario ─────────────────────────────────────────────

function Acordeon({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.72)', border: '1px solid rgba(255,255,255,0.7)' }}>
      <button
        type="button" onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left hover:bg-white/40 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-800">
          <FileText className="w-4 h-4" style={{ color: '#C9A227' }} /> {titulo}
        </span>
        <ChevronDown className={`w-4 h-4 text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && <div className="px-5 pb-5 pt-1">{children}</div>}
    </div>
  )
}

function BloqueGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>{children}</div>
}

function TextField({
  label, value, onChange, placeholder, disabled,
}: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input className="input" value={value} placeholder={placeholder} disabled={disabled}
        onChange={e => onChange(e.target.value)} />
    </div>
  )
}

function NumberField({
  label, value, onChange, disabled,
}: { label: string; value: number | null; onChange: (v: number | null) => void; disabled?: boolean }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input className="input" type="number" min={0} value={value ?? ''} disabled={disabled}
        onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))} />
    </div>
  )
}

function TextArea({
  label, value, onChange, disabled,
}: { label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div>
      <label className="label">{label}</label>
      <textarea className="input resize-none" rows={3} value={value} disabled={disabled}
        onChange={e => onChange(e.target.value)} />
    </div>
  )
}
