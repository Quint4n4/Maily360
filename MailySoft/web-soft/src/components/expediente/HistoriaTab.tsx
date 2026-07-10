/**
 * HistoriaTab — pestaña Historia Clínica (NOM-004).
 * Acordeón por bloques con las claves reales del backend.
 * GET para cargar (documento vivo), PUT para guardar (upsert).
 * El bloque gineco-obstétrico se oculta si el paciente no es sexo F.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Save, Loader2, FileText, ListChecks, NotebookPen } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type {
  CustomAnswers,
  CustomAnswerValue,
  ExploracionFisicaBasal,
  ExploracionSistema,
  GinecoObstetricos,
  HabitosAlimenticios,
  HeredoFamiliares,
  MedicalHistory,
  MedicalHistoryInput,
  MedicalHistoryQuestion,
  NoPatologicos,
  PersonalesPatologicos,
  ViviendaChoice,
} from '../../types/expediente'
import { useMedicalHistory, useUpsertMedicalHistory } from '../../hooks/expediente'
import { useAuth } from '../../auth/AuthContext'
import { useLocalDraft } from '../../hooks/useLocalDraft'
import { draftKey } from '../../lib/draftKeys'
import BorradorRecuperadoAviso from '../common/BorradorRecuperadoAviso'
import { erroresDe } from '../../lib/apiErrors'
import {
  AGO_FIELDS, AHF_FIELDS, APNP_FIELDS, APP_FIELDS, HABITOS_FIELDS, NUCLEO_TITULOS_SET,
} from '../../lib/nucleoHistoriaClinica'
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
  /** Respuestas a las preguntas extra de la clínica: { <question_id>: valor }. */
  custom_answers: CustomAnswers
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
    custom_answers: { ...h.custom_answers },
  }
}

/** Agrupa las preguntas extra activas por sección, conservando el orden del backend. */
function agruparPorSeccion(
  questions: MedicalHistoryQuestion[],
): { section: string; preguntas: MedicalHistoryQuestion[] }[] {
  const orden: string[] = []
  const mapa = new Map<string, MedicalHistoryQuestion[]>()
  for (const q of questions) {
    const sec = q.section || 'General'
    if (!mapa.has(sec)) { mapa.set(sec, []); orden.push(sec) }
    mapa.get(sec)!.push(q)
  }
  return orden.map(section => ({
    section,
    preguntas: [...(mapa.get(section) ?? [])].sort((a, b) => a.order - b.order),
  }))
}

/** Valor por defecto de una respuesta extra vacía según su tipo. */
function respuestaVacia(q: MedicalHistoryQuestion): CustomAnswerValue {
  return q.field_type === 'boolean' ? false : ''
}

/** true si la respuesta a una pregunta requerida está "sin contestar". */
function respuestaFaltante(q: MedicalHistoryQuestion, valor: CustomAnswerValue): boolean {
  if (q.field_type === 'boolean') return false // un checkbox siempre tiene valor (sí/no)
  if (valor === null || valor === undefined) return true
  if (typeof valor === 'string') return valor.trim() === ''
  return false
}

// ── Metadatos de los campos de cada bloque (clave → etiqueta) ─────────────────
// Las listas `*_FIELDS` viven en src/lib/nucleoHistoriaClinica.ts (fuente única
// que comparten esta captura y el configurador de preguntas extra).

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
  const { user } = useAuth()
  const [form, setForm] = useState<FormState | null>(null)
  const [errores, setErrores] = useState<string[]>([])
  const [okMsg, setOkMsg] = useState('')
  const esFemenino = paciente.sex === 'F'

  // ── Borrador local (autoguardado en el navegador) ──
  // Clave por usuario+tenant+tipo+paciente para no mezclar borradores.
  const userId = user?.id ?? ''
  const tenantId = user?.active_tenant?.id ?? ''
  const storageKey = draftKey(userId, tenantId, 'historia', paciente.id)
  // Solo se vigila una vez cargada la HC del servidor (fija el baseline) y si el
  // usuario puede editar y hay usuario/tenant. Sin eso, autoguardado apagado.
  const [serverLoaded, setServerLoaded] = useState(false)
  const draftEnabled = puedeEditar && !!userId && !!tenantId && serverLoaded
  const { draft, clearDraft } = useLocalDraft<FormState | null>({
    storageKey,
    value: form,
    enabled: draftEnabled,
  })

  // Preguntas extra ACTIVAS de la clínica (vienen embebidas en la HC, Fase 2).
  const preguntasActivas = useMemo(() => data?.active_questions ?? [], [data])
  const seccionesExtra = useMemo(() => agruparPorSeccion(preguntasActivas), [preguntasActivas])

  // Las preguntas extra cuya sección coincide con un bloque del núcleo NOM-004 se
  // intercalan DENTRO de ese bloque; las de secciones nuevas/personalizadas van en
  // su propio grupo "Preguntas de la clínica" (como antes).
  const extraPorTituloNucleo = useMemo(() => {
    const mapa = new Map<string, MedicalHistoryQuestion[]>()
    for (const grupo of seccionesExtra) {
      if (NUCLEO_TITULOS_SET.has(grupo.section)) mapa.set(grupo.section, grupo.preguntas)
    }
    return mapa
  }, [seccionesExtra])

  const seccionesPersonalizadas = useMemo(
    () => seccionesExtra.filter(g => !NUCLEO_TITULOS_SET.has(g.section)),
    [seccionesExtra],
  )

  // Fase A: sembrar el estado del formulario desde el servidor UNA vez. Este
  // valor es el "baseline" del borrador local; por eso va antes de precargar el
  // borrador. No re-siembra en refetches para no pisar lo que el usuario escribe.
  const seededRef = useRef(false)
  const draftAppliedRef = useRef(false)
  useEffect(() => {
    if (!data || seededRef.current) return
    seededRef.current = true
    setForm(fromHistory(data))
    setServerLoaded(true)
  }, [data])

  // Fase B: si hay un borrador local y el usuario puede editar, precargarlo por
  // encima del estado del servidor (una sola vez).
  useEffect(() => {
    if (!serverLoaded || draftAppliedRef.current) return
    draftAppliedRef.current = true
    if (draft && puedeEditar) setForm(draft.data)
  }, [serverLoaded, draft, puedeEditar])

  // Descarta el borrador y revierte el formulario al estado del servidor.
  const descartarBorrador = () => {
    clearDraft()
    if (data) setForm(fromHistory(data))
  }

  // Setters tipados por bloque (solo los bloques objeto, no los textos planos).
  const setStr = <B extends BlockKey>(block: B) =>
    (key: keyof FormState[B]) =>
      (value: string) =>
        setForm(f => (f ? { ...f, [block]: { ...(f[block] as object), [key]: value } } : f))

  const setTexto = (key: 'antecedentes_importancia' | 'padecimiento_actual' | 'tratamientos_actuales' | 'prioridad_analisis') =>
    (value: string) => setForm(f => (f ? { ...f, [key]: value } : f))

  const setCustom = (questionId: string, value: CustomAnswerValue) =>
    setForm(f => (f ? { ...f, custom_answers: { ...f.custom_answers, [questionId]: value } } : f))

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

    // Validación UX de las preguntas extra requeridas (el backend es la autoridad).
    const faltantes = preguntasActivas
      .filter(q => q.is_required && respuestaFaltante(q, form.custom_answers[q.id] ?? respuestaVacia(q)))
      .map(q => `“${q.label}” es obligatoria.`)
    if (faltantes.length) { setErrores(faltantes); return }

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
      // Solo se envían respuestas de preguntas ACTIVAS; el backend descarta claves inválidas.
      custom_answers: Object.fromEntries(
        preguntasActivas.map(q => [q.id, form.custom_answers[q.id] ?? respuestaVacia(q)]),
      ),
    }
    if (esFemenino) payload.gineco_obstetricos = form.gineco_obstetricos
    try {
      await guardar.mutateAsync(payload)
      setOkMsg('Historia clínica guardada.')
      clearDraft() // se guardó en el servidor: descartar el borrador local
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  // Renderiza, como campos de la HC, las preguntas extra asignadas a un título del
  // núcleo. Se intercalan al final del bloque correspondiente (mismo grid).
  const renderExtrasDe = useCallback((titulo: string) => {
    if (!form) return null
    const preguntas = extraPorTituloNucleo.get(titulo)
    if (!preguntas || preguntas.length === 0) return null
    return preguntas.map(q => (
      <PreguntaExtraField
        key={q.id}
        pregunta={q}
        value={form.custom_answers[q.id] ?? respuestaVacia(q)}
        onChange={v => setCustom(q.id, v)}
        disabled={!puedeEditar}
      />
    ))
  }, [form, extraPorTituloNucleo, puedeEditar])

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
            {renderExtrasDe('Antecedentes heredo-familiares')}
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
            {renderExtrasDe('Antecedentes personales patológicos')}
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
            {renderExtrasDe('Antecedentes no patológicos')}
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
            {renderExtrasDe('Hábitos alimenticios')}
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
            {renderExtrasDe('Antecedentes gineco-obstétricos')}
          </BloqueGrid>
        ),
      })
    }

    list.push({
      id: 'exploracion', titulo: 'Exploración física',
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
                  maxLength={255}
                  value={celda.detalle ?? ''}
                  onChange={e => setSistema(sistema, { detalle: e.target.value })}
                  disabled={!puedeEditar} />
              </div>
            )
          })}
          {extraPorTituloNucleo.has('Exploración física basal') && (
            <BloqueGrid>{renderExtrasDe('Exploración física basal')}</BloqueGrid>
          )}
        </div>
      ),
    })

    list.push({
      id: 'padecimiento', titulo: 'Padecimiento actual y plan',
      render: () => (
        <div className="space-y-3">
          <TextArea label="Padecimiento actual"
            value={form.padecimiento_actual} onChange={setTexto('padecimiento_actual')} disabled={!puedeEditar} />
          {extraPorTituloNucleo.has('Padecimiento actual') && (
            <BloqueGrid>{renderExtrasDe('Padecimiento actual')}</BloqueGrid>
          )}
          <TextArea label="Tratamientos actuales"
            value={form.tratamientos_actuales} onChange={setTexto('tratamientos_actuales')} disabled={!puedeEditar} />
          {extraPorTituloNucleo.has('Tratamientos actuales') && (
            <BloqueGrid>{renderExtrasDe('Tratamientos actuales')}</BloqueGrid>
          )}
          <TextArea label="Prioridad de análisis"
            value={form.prioridad_analisis} onChange={setTexto('prioridad_analisis')} disabled={!puedeEditar} />
          {extraPorTituloNucleo.has('Prioridad de análisis') && (
            <BloqueGrid>{renderExtrasDe('Prioridad de análisis')}</BloqueGrid>
          )}
        </div>
      ),
    })

    return list
  }, [form, esFemenino, puedeEditar, extraPorTituloNucleo, renderExtrasDe])

  if (isLoading) return <Cargando texto="Cargando historia clínica…" />
  if (isError) return <p className="text-sm text-red-600 py-8 text-center">No se pudo cargar la historia clínica.</p>
  if (!form) return null

  return (
    <div className="space-y-4">
      {draft && puedeEditar && serverLoaded && (
        <BorradorRecuperadoAviso savedAt={draft.savedAt} onDescartar={descartarBorrador} />
      )}
      <ErroresAlerta errores={errores} />
      {okMsg && (
        <div className="rounded-xl px-4 py-2.5 text-sm" style={{ background: '#DCF3E6', color: '#1F6E47' }}>{okMsg}</div>
      )}

      <div className="flex flex-col lg:flex-row gap-5 lg:items-start">
        {/* ── Recuadro fijo: Antecedentes de importancia ──
            En escritorio va a la derecha y acompaña el scroll (sticky); en móvil
            aparece arriba. Es texto libre; se guarda con la historia clínica. ── */}
        <aside className="w-full lg:w-[330px] lg:shrink-0 lg:order-2">
          <div className="lg:sticky lg:top-0">
            <div
              className="rounded-2xl p-4"
              style={{
                background: 'rgba(255,255,255,0.85)',
                border: '1.5px solid rgba(201,162,39,0.5)',
                boxShadow: '0 6px 18px rgba(201,162,39,0.15)',
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                <NotebookPen className="w-4 h-4" style={{ color: '#C9A227' }} />
                <h4 className="text-sm font-semibold text-gray-800">Antecedentes de importancia</h4>
              </div>
              <p className="text-xs text-gray-500 mb-2.5">
                Anota aquí lo relevante del paciente. Se guarda con la historia clínica.
              </p>
              <textarea
                className="input resize-none w-full min-h-[220px] lg:min-h-[55vh]"
                maxLength={10000}
                value={form.antecedentes_importancia}
                onChange={e => setTexto('antecedentes_importancia')(e.target.value)}
                disabled={!puedeEditar}
                placeholder="Ej. Dolor en hombro derecho desde hace 2 meses. Visión borrosa. Colitis ocasional. Calambres en extremidades…"
              />
              {extraPorTituloNucleo.has('Antecedentes de importancia') && (
                <div className="mt-3 grid gap-3">{renderExtrasDe('Antecedentes de importancia')}</div>
              )}
            </div>
          </div>
        </aside>

        {/* ── Formulario de la historia clínica (bloques + preguntas + guardar) ── */}
        <div className="flex-1 min-w-0 lg:order-1 space-y-4">
          {bloques.map(b => <Acordeon key={b.id} titulo={b.titulo}>{b.render()}</Acordeon>)}

          {/* ── Preguntas de la clínica (Fase 2) — solo las de SECCIONES NUEVAS.
              Las preguntas asignadas a una sección del núcleo ya se intercalaron
              dentro de su bloque del acordeón (arriba). ── */}
          {seccionesPersonalizadas.length > 0 && (
            <div className="pt-2 space-y-3">
              <div className="flex items-center gap-2 px-1">
                <ListChecks className="w-4 h-4" style={{ color: '#C9A227' }} />
                <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700/80">
                  Preguntas de la clínica
                </h4>
              </div>
              {seccionesPersonalizadas.map(grupo => (
                <Acordeon key={grupo.section} titulo={grupo.section}>
                  <BloqueGrid>
                    {grupo.preguntas.map(q => (
                      <PreguntaExtraField
                        key={q.id}
                        pregunta={q}
                        value={form.custom_answers[q.id] ?? respuestaVacia(q)}
                        onChange={v => setCustom(q.id, v)}
                        disabled={!puedeEditar}
                      />
                    ))}
                  </BloqueGrid>
                </Acordeon>
              ))}
            </div>
          )}

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
      </div>
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
        maxLength={255} onChange={e => onChange(e.target.value)} />
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
      <textarea className="input resize-none" rows={3} maxLength={4000} value={value} disabled={disabled}
        onChange={e => onChange(e.target.value)} />
    </div>
  )
}

/**
 * Campo dinámico de una pregunta extra de la clínica (Fase 2). Renderiza el
 * control según `field_type` y prellena desde la respuesta guardada.
 *   text→input · textarea→textarea · boolean→checkbox · select→dropdown
 *   number→input numérico · date→input date.
 */
function PreguntaExtraField({
  pregunta, value, onChange, disabled,
}: {
  pregunta: MedicalHistoryQuestion
  value: CustomAnswerValue
  onChange: (v: CustomAnswerValue) => void
  disabled?: boolean
}) {
  const label = (
    <label className="label">
      {pregunta.label}
      {pregunta.is_required && <span className="text-red-500"> *</span>}
    </label>
  )

  // El checkbox ocupa la fila completa con el label a la derecha.
  if (pregunta.field_type === 'boolean') {
    return (
      <label className="flex items-center gap-2.5 cursor-pointer select-none py-1.5">
        <input
          type="checkbox"
          className="w-4 h-4 rounded accent-amber-600"
          checked={value === true}
          disabled={disabled}
          onChange={e => onChange(e.target.checked)}
        />
        <span className="text-sm text-gray-800">
          {pregunta.label}
          {pregunta.is_required && <span className="text-red-500"> *</span>}
        </span>
      </label>
    )
  }

  const strValue = typeof value === 'string' || typeof value === 'number' ? String(value) : ''

  if (pregunta.field_type === 'textarea') {
    return (
      <div className="sm:col-span-full">
        {label}
        <textarea className="input resize-none" rows={3} maxLength={4000} value={strValue} disabled={disabled}
          onChange={e => onChange(e.target.value)} />
      </div>
    )
  }

  if (pregunta.field_type === 'select') {
    return (
      <div>
        {label}
        <select className="input" value={strValue} disabled={disabled}
          onChange={e => onChange(e.target.value)}>
          <option value="">Sin especificar</option>
          {pregunta.options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
        </select>
      </div>
    )
  }

  if (pregunta.field_type === 'number') {
    return (
      <div>
        {label}
        <input className="input" type="number" value={strValue} disabled={disabled}
          onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
      </div>
    )
  }

  if (pregunta.field_type === 'date') {
    return (
      <div>
        {label}
        <input className="input" type="date" value={strValue} disabled={disabled}
          onChange={e => onChange(e.target.value)} />
      </div>
    )
  }

  // 'text' (default)
  return (
    <div>
      {label}
      <input className="input" value={strValue} disabled={disabled}
        maxLength={255} onChange={e => onChange(e.target.value)} />
    </div>
  )
}
