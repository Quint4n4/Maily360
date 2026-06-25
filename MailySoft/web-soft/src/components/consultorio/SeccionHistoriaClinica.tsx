/**
 * SeccionHistoriaClinica — form builder de las preguntas EXTRA de la Historia
 * Clínica (Fase 2). El núcleo NOM-004 de la HC es fijo y NO se configura aquí.
 *
 * Permite (solo owner/admin; el backend devuelve 403 al resto):
 *   - Listar las preguntas agrupadas por sección.
 *   - Crear una pregunta (label, tipo, opciones para 'select', requerida, orden).
 *   - Editar y borrar (baja lógica) cada pregunta.
 *
 * Reúsa el patrón de las otras secciones de Mi Consultorio (ver SeccionCategorias).
 */

import { useMemo, useState } from 'react'
import { ChevronDown, Loader2, Plus, ListChecks, Pencil, Trash2, GripVertical, X, Save, Lock } from 'lucide-react'
import {
  useCreateHistoryQuestion,
  useDeleteHistoryQuestion,
  useHistoryQuestions,
  useUpdateHistoryQuestion,
} from '../../hooks/expediente'
import { erroresDe } from '../../lib/apiErrors'
import { NUCLEO_SECCIONES, NUCLEO_TITULOS } from '../../lib/nucleoHistoriaClinica'
import type { NucleoSeccion } from '../../lib/nucleoHistoriaClinica'
import type {
  MedicalHistoryQuestion,
  MedicalHistoryQuestionInput,
  QuestionFieldType,
} from '../../types/expediente'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  editable: boolean
}

/** Etiquetas legibles de los tipos de campo (reflejan los choices del backend). */
const FIELD_TYPE_OPTIONS: { value: QuestionFieldType; label: string }[] = [
  { value: 'text', label: 'Texto corto' },
  { value: 'textarea', label: 'Texto largo' },
  { value: 'boolean', label: 'Sí / No' },
  { value: 'select', label: 'Lista de opciones' },
  { value: 'number', label: 'Número' },
  { value: 'date', label: 'Fecha' },
]

const FIELD_TYPE_LABEL: Record<QuestionFieldType, string> = {
  text: 'Texto corto',
  textarea: 'Texto largo',
  boolean: 'Sí / No',
  select: 'Lista de opciones',
  number: 'Número',
  date: 'Fecha',
}

/** Valor especial del selector de sección para crear una sección personalizada. */
const SECCION_NUEVA = '__nueva__'

/** Borrador de una pregunta (alta o edición). */
interface Borrador {
  label: string
  field_type: QuestionFieldType
  /** Opciones del 'select' como texto multilínea (una por línea). */
  optionsText: string
  section: string
  order: string
  is_required: boolean
}

const BORRADOR_VACIO: Borrador = {
  label: '', field_type: 'text', optionsText: '', section: '', order: '0', is_required: false,
}

function borradorDe(q: MedicalHistoryQuestion): Borrador {
  return {
    label: q.label,
    field_type: q.field_type,
    optionsText: q.options.join('\n'),
    section: q.section,
    order: String(q.order),
    is_required: q.is_required,
  }
}

/** Convierte un borrador a payload validándolo en el front (UX). */
function aPayload(b: Borrador): { input: MedicalHistoryQuestionInput } | { errores: string[] } {
  const errores: string[] = []
  const label = b.label.trim()
  if (!label) errores.push('Escribe el texto de la pregunta.')
  const options = b.optionsText.split('\n').map(o => o.trim()).filter(Boolean)
  if (b.field_type === 'select' && options.length === 0) {
    errores.push('Una "Lista de opciones" necesita al menos una opción.')
  }
  if (errores.length) return { errores }
  return {
    input: {
      label,
      field_type: b.field_type,
      options: b.field_type === 'select' ? options : [],
      section: b.section.trim(),
      order: Number(b.order) || 0,
      is_required: b.is_required,
    },
  }
}

/** Agrupa las preguntas por sección, ordenadas por `order`. */
function agrupar(questions: MedicalHistoryQuestion[]) {
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

export default function SeccionHistoriaClinica({ editable }: Props) {
  const preguntasQ = useHistoryQuestions()
  const crear = useCreateHistoryQuestion()
  const actualizar = useUpdateHistoryQuestion()
  const borrar = useDeleteHistoryQuestion()
  const confirmar = useConfirm()

  const [errores, setErrores] = useState<string[]>([])
  const [agregando, setAgregando] = useState(false)
  const [nuevo, setNuevo] = useState<Borrador>(BORRADOR_VACIO)
  const [editId, setEditId] = useState<string | null>(null)
  const [edicion, setEdicion] = useState<Borrador>(BORRADOR_VACIO)

  // Solo preguntas activas (el backend ya filtra a las del tenant).
  const activas = useMemo(
    () => (preguntasQ.data ?? []).filter(q => q.is_active),
    [preguntasQ.data],
  )
  const grupos = useMemo(() => agrupar(activas), [activas])

  const onCrear = async () => {
    setErrores([])
    const r = aPayload(nuevo)
    if ('errores' in r) { setErrores(r.errores); return }
    try {
      await crear.mutateAsync(r.input)
      setNuevo(BORRADOR_VACIO)
      setAgregando(false)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const iniciarEdicion = (q: MedicalHistoryQuestion) => {
    setErrores([])
    setEditId(q.id)
    setEdicion(borradorDe(q))
  }

  const onGuardarEdicion = async () => {
    if (!editId) return
    setErrores([])
    const r = aPayload(edicion)
    if ('errores' in r) { setErrores(r.errores); return }
    try {
      await actualizar.mutateAsync({ id: editId, input: r.input })
      setEditId(null)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onBorrar = async (q: MedicalHistoryQuestion) => {
    if (!(await confirmar({
      titulo: 'Eliminar pregunta',
      mensaje: `¿Eliminar la pregunta “${q.label}”? Las respuestas ya capturadas se conservan en los expedientes.`,
      peligro: true,
      textoConfirmar: 'Eliminar',
    }))) return
    setErrores([])
    try {
      await borrar.mutateAsync(q.id)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura texto="Puedes ver las preguntas, pero solo Dueño/Administrador las edita." />}
      <Nota>
        Estas preguntas se agregan <strong>encima</strong> de la historia clínica oficial (NOM-004), que
        no se puede modificar. Aparecerán en el expediente de cada paciente, agrupadas por sección.
      </Nota>

      {/* Núcleo NOM-004 a detalle: acordeón de SOLO LECTURA con todas las preguntas
          fijas de cada sección (igual que la HC del paciente, pero candado/gris). */}
      <div className="rounded-2xl p-4" style={{ background: 'rgba(29,111,92,0.06)', border: '1px solid rgba(29,111,92,0.18)' }}>
        <div className="flex items-center gap-2 mb-1.5">
          <Lock className="w-4 h-4" style={{ color: '#0F6E56' }} />
          <h3 className="text-sm font-semibold" style={{ color: '#085041' }}>Incluido por norma (NOM-004) · no editable</h3>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          Estas secciones ya vienen en la historia clínica de cada paciente y cumplen la norma.
          Despliega cada una para ver sus preguntas a detalle. Tus preguntas se agregan debajo.
        </p>
        <div className="space-y-2">
          {NUCLEO_SECCIONES.map(seccion => (
            <AcordeonNucleo key={seccion.id} seccion={seccion} />
          ))}
        </div>
      </div>

      <AlertaErrores errores={errores} />

      {editable && !agregando && (
        <button className="btn-primary" onClick={() => { setAgregando(true); setErrores([]) }}>
          <Plus className="w-4 h-4" /> Agregar pregunta
        </button>
      )}

      {/* Formulario de alta */}
      {editable && agregando && (
        <EditorPregunta
          borrador={nuevo}
          setBorrador={setNuevo}
          guardando={crear.isPending}
          onGuardar={onCrear}
          onCancelar={() => { setAgregando(false); setNuevo(BORRADOR_VACIO); setErrores([]) }}
          textoGuardar="Crear pregunta"
        />
      )}

      {/* Listado */}
      {preguntasQ.isLoading ? (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando preguntas…
        </div>
      ) : preguntasQ.isError ? (
        <AlertaErrores errores={erroresDe(preguntasQ.error)} />
      ) : activas.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-gray-400">
          <ListChecks className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">Aún no hay preguntas configuradas.</p>
        </div>
      ) : (
        <div className="space-y-5">
          {grupos.map(grupo => (
            <div key={grupo.section} className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-700/80">
                {grupo.section}
              </h3>
              <div className="space-y-2">
                {grupo.preguntas.map(q =>
                  editId === q.id ? (
                    <EditorPregunta
                      key={q.id}
                      borrador={edicion}
                      setBorrador={setEdicion}
                      guardando={actualizar.isPending}
                      onGuardar={onGuardarEdicion}
                      onCancelar={() => { setEditId(null); setErrores([]) }}
                      textoGuardar="Guardar cambios"
                    />
                  ) : (
                    <FilaPregunta
                      key={q.id}
                      pregunta={q}
                      editable={editable}
                      onEditar={() => iniciarEdicion(q)}
                      onBorrar={() => onBorrar(q)}
                      borrando={borrar.isPending}
                    />
                  ),
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Acordeón de SOLO LECTURA de una sección del núcleo NOM-004 ────────────────
//
// Replica el patrón del acordeón de la HC del paciente (HistoriaTab) pero en gris
// y con candado: deja claro que estas preguntas YA vienen por norma y NO se editan.

function AcordeonNucleo({ seccion }: { seccion: NucleoSeccion }) {
  const [open, setOpen] = useState(false)
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(29,111,92,0.18)' }}
    >
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-white/50 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-semibold" style={{ color: '#085041' }}>
          <Lock className="w-3.5 h-3.5" style={{ color: '#0F6E56' }} />
          {seccion.titulo}
          <span className="text-[11px] font-normal text-gray-400">
            ({seccion.preguntas.length} {seccion.preguntas.length === 1 ? 'campo' : 'campos'})
          </span>
        </span>
        <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="px-4 pb-3 pt-1">
          <div className="grid gap-1.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
            {seccion.preguntas.map(p => (
              <div
                key={p.key}
                className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5"
                style={{ background: 'rgba(245,245,244,0.8)', border: '1px solid rgba(0,0,0,0.05)' }}
              >
                <span className="flex items-center gap-1.5 text-xs text-gray-500 min-w-0">
                  <Lock className="w-3 h-3 shrink-0 text-gray-400" />
                  <span className="truncate">{p.label}</span>
                </span>
                <span className="text-[10px] text-gray-400 shrink-0">{FIELD_TYPE_LABEL[p.field_type]}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Fila de una pregunta (modo lectura) ──────────────────────────────────────

function FilaPregunta({
  pregunta, editable, onEditar, onBorrar, borrando,
}: {
  pregunta: MedicalHistoryQuestion
  editable: boolean
  onEditar: () => void
  onBorrar: () => void
  borrando: boolean
}) {
  return (
    <div
      className="flex items-center gap-3 rounded-xl px-3.5 py-2.5"
      style={{ background: 'rgba(255,255,255,0.72)', border: '1px solid rgba(201,162,39,0.18)' }}
    >
      <GripVertical className="w-4 h-4 text-gray-300 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-800">{pregunta.label}</span>
          {pregunta.is_required && <span className="badge badge-warning">Obligatoria</span>}
        </div>
        <div className="flex items-center gap-2 mt-0.5 text-[11px] text-gray-400">
          <span>{FIELD_TYPE_LABEL[pregunta.field_type]}</span>
          <span>· orden {pregunta.order}</span>
          {pregunta.field_type === 'select' && pregunta.options.length > 0 && (
            <span className="truncate">· {pregunta.options.join(', ')}</span>
          )}
        </div>
      </div>
      {editable && (
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onEditar}
            className="p-1.5 rounded-lg text-amber-700 hover:bg-amber-50 transition-colors"
            aria-label="Editar pregunta"
          >
            <Pencil className="w-4 h-4" />
          </button>
          <button
            onClick={onBorrar}
            disabled={borrando}
            className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
            aria-label="Eliminar pregunta"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}

// ── Editor de una pregunta (alta o edición) ──────────────────────────────────

function EditorPregunta({
  borrador, setBorrador, guardando, onGuardar, onCancelar, textoGuardar,
}: {
  borrador: Borrador
  setBorrador: (b: Borrador) => void
  guardando: boolean
  onGuardar: () => void
  onCancelar: () => void
  textoGuardar: string
}) {
  const set = <K extends keyof Borrador>(key: K, value: Borrador[K]) =>
    setBorrador({ ...borrador, [key]: value })

  // ¿La sección actual es del núcleo o es personalizada?
  const seccionEsNucleo = NUCLEO_TITULOS.includes(borrador.section)
  // Activa el modo "sección nueva" si ya hay un texto personalizado (al editar) o
  // si el usuario elige explícitamente "Otra sección nueva…".
  const [usarNueva, setUsarNueva] = useState(borrador.section !== '' && !seccionEsNucleo)

  // Valor del <select>: el título del núcleo, o el sentinel de "sección nueva".
  const selectValue = usarNueva || (!seccionEsNucleo && borrador.section !== '')
    ? SECCION_NUEVA
    : borrador.section

  const onCambiarSeccion = (value: string) => {
    if (value === SECCION_NUEVA) {
      setUsarNueva(true)
      set('section', '') // se captura en el input revelado
    } else {
      setUsarNueva(false)
      set('section', value) // título del núcleo (o '' = "Sin sección")
    }
  }

  return (
    <div
      className="rounded-2xl p-4 space-y-3"
      style={{ background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }}
    >
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
        <div className="sm:col-span-full">
          <label className="label">Pregunta</label>
          <input
            className="input"
            placeholder="Ej. ¿Practica algún deporte?"
            value={borrador.label}
            onChange={e => set('label', e.target.value)}
          />
        </div>

        <div>
          <label className="label">Tipo de respuesta</label>
          <select
            className="input"
            value={borrador.field_type}
            onChange={e => set('field_type', e.target.value as QuestionFieldType)}
          >
            {FIELD_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        <div>
          <label className="label">Sección (grupo)</label>
          <select
            className="input"
            value={selectValue}
            onChange={e => onCambiarSeccion(e.target.value)}
          >
            <option value="">Sin sección (General)</option>
            <optgroup label="Secciones de la HC (NOM-004)">
              {NUCLEO_TITULOS.map(t => <option key={t} value={t}>{t}</option>)}
            </optgroup>
            <option value={SECCION_NUEVA}>Otra sección nueva…</option>
          </select>
          {selectValue === SECCION_NUEVA && (
            <input
              className="input mt-2"
              placeholder="Nombre de la sección nueva (ej. Estilo de vida)"
              value={borrador.section}
              onChange={e => set('section', e.target.value)}
              autoFocus
            />
          )}
          <p className="text-[11px] text-gray-400 mt-1">
            Si eliges una sección de la HC, la pregunta aparecerá dentro de ese bloque del expediente.
          </p>
        </div>

        <div>
          <label className="label">Orden</label>
          <input
            className="input"
            type="number"
            min={0}
            value={borrador.order}
            onChange={e => set('order', e.target.value)}
          />
        </div>
      </div>

      {borrador.field_type === 'select' && (
        <div>
          <label className="label">Opciones (una por línea)</label>
          <textarea
            className="input resize-none"
            rows={3}
            placeholder={'Opción 1\nOpción 2\nOpción 3'}
            value={borrador.optionsText}
            onChange={e => set('optionsText', e.target.value)}
          />
        </div>
      )}

      <label className="flex items-center gap-2.5 cursor-pointer select-none">
        <input
          type="checkbox"
          className="w-4 h-4 rounded accent-amber-600"
          checked={borrador.is_required}
          onChange={e => set('is_required', e.target.checked)}
        />
        <span className="text-sm text-gray-700">Respuesta obligatoria</span>
      </label>

      <div className="flex items-center justify-end gap-2 pt-1">
        <button className="btn-secondary" onClick={onCancelar} disabled={guardando}>
          <X className="w-4 h-4" /> Cancelar
        </button>
        <button className="btn-primary" onClick={onGuardar} disabled={guardando}>
          {guardando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {textoGuardar}
        </button>
      </div>
    </div>
  )
}
