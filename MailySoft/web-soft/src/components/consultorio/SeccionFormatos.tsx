/**
 * SeccionFormatos — Galería de formatos de receta (F4).
 *
 * Lista los PrescriptionFormat del tenant y permite crear/editar/borrar. El editor
 * cubre: nombre, plantilla base (con mini-preview), color de acento (picker +
 * validación hex en vivo), tipografía, secciones (checkboxes), modo de membrete
 * y "predeterminado". La vista previa abre el PDF de una receta de ejemplo con el
 * formato aplicado (?format_id= o ?formato=) vía blob con Bearer.
 *
 * Permisos UX: owner/admin gestionan (botones ocultos a no-editables). El backend
 * es la autoridad: ante 403/400 se mapean los errores y se muestran sin romper.
 */

import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  FileText, Loader2, Plus, Save, Star, Trash2, X,
} from 'lucide-react'
import { listPatients } from '../../api/pacientes'
import { listPrescriptions } from '../../api/recetas'
import {
  useCreatePrescriptionFormat,
  useDeletePrescriptionFormat,
  useOpenPrescriptionPdfWithFormat,
  usePrescriptionFormats,
  useUpdatePrescriptionFormat,
} from '../../hooks/recetas'
import { useQuery } from '@tanstack/react-query'
import { erroresDe } from '../../lib/apiErrors'
import { errorDeCampo } from '../../lib/validacion'
import type {
  FormatSectionKey,
  FormatSections,
  LetterheadMode,
  PrescriptionBaseLayout,
  PrescriptionFont,
  PrescriptionFormatCreateInput,
  PrescriptionFormatOut,
  PrescriptionFormatUpdateInput,
} from '../../types/recetas'
import {
  BASE_LAYOUT_OPTIONS,
  FONT_OPTIONS,
  LETTERHEAD_MODE_OPTIONS,
  SECTION_OPTIONS,
} from '../../types/recetas'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

interface Props {
  /** Si false, solo lectura (no se muestran acciones de gestión). */
  editable: boolean
}

/** Color de acento por defecto (gold de la marca). */
const ACCENT_DEFAULT = '#9A7B1E'

/** Regex de color hex #RRGGBB (replica el _HEX_RE del backend). */
const HEX_RE = /^#[0-9A-Fa-f]{6}$/

/** Secciones por defecto (todas activas), igual que el backend. */
const SECCIONES_DEFAULT: FormatSections = {
  signos: true,
  diagnostico: true,
  sueros: true,
  terapias: true,
  indicaciones: true,
}

/**
 * Busca el id de una receta de ejemplo del tenant para la vista previa del PDF.
 * Recorre los primeros pacientes (1ª página) y devuelve la 1ª receta que halle.
 * Si no hay ninguna receta en la clínica, devuelve null (la UI lo indica).
 */
function useSamplePrescriptionId() {
  return useQuery({
    queryKey: ['recetas', 'sample-id'],
    queryFn: async (): Promise<string | null> => {
      const page = await listPatients({ page: 1 })
      // Revisa hasta 10 pacientes para no disparar demasiadas peticiones.
      for (const paciente of page.results.slice(0, 10)) {
        const recetas = await listPrescriptions(paciente.id)
        if (recetas.results.length > 0) return recetas.results[0].id
      }
      return null
    },
    staleTime: 5 * 60_000,
  })
}

/** Sección "Formato de receta" de Mi Consultorio. */
export default function SeccionFormatos({ editable }: Props) {
  const formatosQ = usePrescriptionFormats()
  const borrar = useDeletePrescriptionFormat()
  const confirmar = useConfirm()
  const sampleQ = useSamplePrescriptionId()
  const abrirPdf = useOpenPrescriptionPdfWithFormat()

  const [editando, setEditando] = useState<PrescriptionFormatOut | null>(null)
  const [creando, setCreando] = useState(false)
  const [errores, setErrores] = useState<string[]>([])

  const formatos = formatosQ.data ?? []
  const sampleId = sampleQ.data ?? null

  const cerrarEditor = () => { setEditando(null); setCreando(false) }

  const eliminar = async (f: PrescriptionFormatOut) => {
    if (!(await confirmar({
      titulo: 'Eliminar formato',
      mensaje: `¿Eliminar el formato "${f.name}"? Esta acción no se puede deshacer.`,
      peligro: true,
      textoConfirmar: 'Eliminar',
    }))) return
    setErrores([])
    try {
      await borrar.mutateAsync(f.id)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const verPreview = async (formatId: string) => {
    setErrores([])
    if (!sampleId) return
    try {
      await abrirPdf.mutateAsync({ prescriptionId: sampleId, formatId })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  if (formatosQ.isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando formatos…
      </div>
    )
  }
  if (formatosQ.isError) {
    return <AlertaErrores errores={erroresDe(formatosQ.error)} />
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura />}
      <AlertaErrores errores={errores} />

      <div className="flex items-start justify-between gap-3">
        <Nota>
          Personaliza cómo se ve el PDF de tus recetas: plantilla, color, tipografía y secciones.
          La vista previa usa una receta de ejemplo de tu clínica.
        </Nota>
        {editable && (
          <button
            type="button"
            onClick={() => { setCreando(true); setEditando(null) }}
            className="shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
          >
            <Plus className="w-4 h-4" /> Nuevo formato
          </button>
        )}
      </div>

      {/* Lista de formatos */}
      {formatos.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-gray-400">
          <FileText className="w-9 h-9 mb-2 opacity-50" />
          <p className="text-sm">Aún no hay formatos. {editable && 'Crea el primero.'}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {formatos.map((f) => (
            <FormatoCard
              key={f.id}
              formato={f}
              editable={editable}
              sampleDisponible={!!sampleId}
              previewPendiente={abrirPdf.isPending}
              onEditar={() => { setEditando(f); setCreando(false) }}
              onEliminar={() => eliminar(f)}
              onPreview={() => verPreview(f.id)}
            />
          ))}
        </div>
      )}

      {sampleQ.isSuccess && !sampleId && (
        <p className="text-xs text-gray-400 italic">
          Para la vista previa necesitas al menos una receta emitida. Emite una receta y vuelve aquí.
        </p>
      )}

      {/* Editor (crear / editar) en modal */}
      {(creando || editando) && editable && (
        <FormatoEditor
          formato={editando}
          onClose={cerrarEditor}
          onSaved={cerrarEditor}
        />
      )}
    </div>
  )
}

/* ─── Tarjeta de un formato ───────────────────────────────────────────────── */

function FormatoCard({
  formato, editable, sampleDisponible, previewPendiente, onEditar, onEliminar, onPreview,
}: {
  formato: PrescriptionFormatOut
  editable: boolean
  sampleDisponible: boolean
  previewPendiente: boolean
  onEditar: () => void
  onEliminar: () => void
  onPreview: () => void
}) {
  const layout = BASE_LAYOUT_OPTIONS.find((o) => o.value === formato.base_layout)
  const seccionesActivas = SECTION_OPTIONS.filter((s) => formato.sections[s.key]).map((s) => s.label)

  return (
    <div className="rounded-2xl border border-gray-100 bg-white/70 p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="w-4 h-4 rounded-full shrink-0 ring-1 ring-black/10"
              style={{ background: formato.accent_color }}
              title={formato.accent_color}
            />
            <h3 className="text-sm font-semibold text-gray-800 truncate">{formato.name}</h3>
            {formato.is_default && (
              <span
                className="inline-flex items-center gap-1 text-[10px] rounded-full px-1.5 py-0.5"
                style={{ background: 'rgba(201,162,39,0.15)', color: '#9A7B1E' }}
              >
                <Star className="w-3 h-3" /> Predeterminado
              </span>
            )}
            {formato.is_authorized && (
              <span
                className="text-[10px] rounded-full px-1.5 py-0.5"
                style={{ background: 'rgba(46,125,91,0.12)', color: '#2E7D5B' }}
              >
                Autorizado
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            {layout?.label ?? formato.base_layout} ·{' '}
            {FONT_OPTIONS.find((o) => o.value === formato.font)?.label.split(' ')[0] ?? formato.font}
          </p>
        </div>
      </div>

      {seccionesActivas.length > 0 && (
        <p className="text-[11px] text-gray-400">
          Secciones: {seccionesActivas.join(', ')}
        </p>
      )}

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          onClick={onPreview}
          disabled={!sampleDisponible || previewPendiente}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-50 rounded-lg px-3 py-1.5"
          style={{ background: 'rgba(201,162,39,0.10)' }}
          title={sampleDisponible ? 'Ver PDF con este formato' : 'Necesitas una receta de ejemplo'}
        >
          {previewPendiente
            ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Abriendo…</>
            : <><FileText className="w-3.5 h-3.5" /> Vista previa PDF</>}
        </button>

        {editable && (
          <>
            <button
              type="button"
              onClick={onEditar}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-gray-600 hover:text-gray-800 rounded-lg px-3 py-1.5"
              style={{ background: 'rgba(120,120,120,0.10)' }}
            >
              Editar
            </button>
            <button
              type="button"
              onClick={onEliminar}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-600 hover:text-red-700 rounded-lg px-3 py-1.5"
              style={{ background: 'rgba(190,40,40,0.08)' }}
            >
              <Trash2 className="w-3.5 h-3.5" /> Eliminar
            </button>
          </>
        )}
      </div>
    </div>
  )
}

/* ─── Editor de formato (modal con createPortal) ──────────────────────────── */

/** Estado editable del formato (sin campos de solo lectura). */
interface EditorState {
  name: string
  base_layout: PrescriptionBaseLayout
  accent_color: string
  font: PrescriptionFont
  sections: FormatSections
  letterhead_mode: LetterheadMode
  is_default: boolean
}

function estadoInicial(formato: PrescriptionFormatOut | null): EditorState {
  if (formato) {
    return {
      name: formato.name,
      base_layout: formato.base_layout,
      accent_color: formato.accent_color,
      font: formato.font,
      sections: { ...SECCIONES_DEFAULT, ...formato.sections },
      letterhead_mode: formato.letterhead_mode,
      is_default: formato.is_default,
    }
  }
  return {
    name: '',
    base_layout: 'standard',
    accent_color: ACCENT_DEFAULT,
    font: 'helvetica',
    sections: { ...SECCIONES_DEFAULT },
    letterhead_mode: 'digital',
    is_default: false,
  }
}

function FormatoEditor({
  formato, onClose, onSaved,
}: {
  formato: PrescriptionFormatOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const esEdicion = !!formato
  const crear = useCreatePrescriptionFormat()
  const actualizar = useUpdatePrescriptionFormat()
  const [st, setSt] = useState<EditorState>(() => estadoInicial(formato))
  const [errores, setErrores] = useState<string[]>([])

  const pendiente = crear.isPending || actualizar.isPending

  // Validación en vivo del color hex (solo UX; el backend es la autoridad).
  const errorColor = useMemo(
    () => errorDeCampo(st.accent_color, (v) => HEX_RE.test(v), 'Color inválido (usa #RRGGBB)'),
    [st.accent_color],
  )

  const toggleSeccion = (key: FormatSectionKey) =>
    setSt((p) => ({ ...p, sections: { ...p.sections, [key]: !p.sections[key] } }))

  const guardar = async () => {
    setErrores([])
    if (!st.name.trim()) { setErrores(['El nombre del formato es obligatorio.']); return }
    if (!HEX_RE.test(st.accent_color)) {
      setErrores(['El color de acento debe tener el formato #RRGGBB.'])
      return
    }
    try {
      if (esEdicion && formato) {
        const input: PrescriptionFormatUpdateInput = {
          name: st.name.trim(),
          base_layout: st.base_layout,
          accent_color: st.accent_color,
          font: st.font,
          sections: st.sections,
          letterhead_mode: st.letterhead_mode,
          is_default: st.is_default,
        }
        await actualizar.mutateAsync({ id: formato.id, input })
      } else {
        const input: PrescriptionFormatCreateInput = {
          name: st.name.trim(),
          base_layout: st.base_layout,
          accent_color: st.accent_color,
          font: st.font,
          sections: st.sections,
          letterhead_mode: st.letterhead_mode,
          is_default: st.is_default,
        }
        await crear.mutateAsync(input)
      }
      onSaved()
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return createPortal(
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(20,14,4,0.6)', backdropFilter: 'blur(3px)' }}
      role="dialog" aria-modal="true"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl p-6"
        style={{ background: 'rgba(255,255,255,0.98)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 20px 60px rgba(60,42,12,0.3)' }}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">
            {esEdicion ? 'Editar formato' : 'Nuevo formato'}
          </h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <X className="w-5 h-5" />
          </button>
        </div>

        <AlertaErrores errores={errores} />

        <div className="space-y-5">
          {/* Nombre */}
          <div>
            <label className="label" htmlFor="fmt-name">Nombre *</label>
            <input
              id="fmt-name"
              className="input"
              placeholder="Ej. Receta estándar dorada"
              value={st.name}
              onChange={(e) => setSt((p) => ({ ...p, name: e.target.value }))}
            />
          </div>

          {/* Plantilla base con mini-preview */}
          <div>
            <p className="label">Plantilla base</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {BASE_LAYOUT_OPTIONS.map((o) => {
                const activo = st.base_layout === o.value
                return (
                  <button
                    type="button"
                    key={o.value}
                    onClick={() => setSt((p) => ({ ...p, base_layout: o.value }))}
                    className="text-left rounded-xl border p-3 transition-all"
                    style={{
                      borderColor: activo ? st.accent_color : 'rgba(0,0,0,0.08)',
                      background: activo ? 'rgba(201,162,39,0.08)' : 'white',
                      boxShadow: activo ? `0 0 0 1px ${st.accent_color}` : 'none',
                    }}
                  >
                    <MiniPreview layout={o.value} accent={st.accent_color} />
                    <p className="text-sm font-medium text-gray-800 mt-2">{o.label}</p>
                    <p className="text-[11px] text-gray-500 leading-snug">{o.description}</p>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Color + tipografía */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="label" htmlFor="fmt-color">Color de acento</label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  aria-label="Selector de color"
                  className="h-10 w-12 rounded-lg border border-gray-200 cursor-pointer bg-white p-1"
                  value={HEX_RE.test(st.accent_color) ? st.accent_color : ACCENT_DEFAULT}
                  onChange={(e) => setSt((p) => ({ ...p, accent_color: e.target.value }))}
                />
                <input
                  id="fmt-color"
                  className={`input${errorColor ? ' input-error' : ''}`}
                  placeholder="#9A7B1E"
                  value={st.accent_color}
                  onChange={(e) => setSt((p) => ({ ...p, accent_color: e.target.value }))}
                />
              </div>
              {errorColor && <p className="mt-1 text-xs text-red-600">{errorColor}</p>}
            </div>
            <div>
              <label className="label" htmlFor="fmt-font">Tipografía</label>
              <select
                id="fmt-font"
                className="input"
                value={st.font}
                onChange={(e) => setSt((p) => ({ ...p, font: e.target.value as PrescriptionFont }))}
              >
                {FONT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>

          {/* Secciones */}
          <div>
            <p className="label">Secciones visibles</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {SECTION_OPTIONS.map((s) => (
                <label
                  key={s.key}
                  className="flex items-center gap-2 rounded-lg border border-gray-100 bg-white/70 px-3 py-2 cursor-pointer text-sm text-gray-700"
                >
                  <input
                    type="checkbox"
                    className="accent-amber-600"
                    checked={!!st.sections[s.key]}
                    onChange={() => toggleSeccion(s.key)}
                  />
                  {s.label}
                </label>
              ))}
            </div>
          </div>

          {/* Modo de membrete */}
          <div>
            <label className="label" htmlFor="fmt-letterhead">Modo de membrete</label>
            <select
              id="fmt-letterhead"
              className="input"
              value={st.letterhead_mode}
              onChange={(e) => setSt((p) => ({ ...p, letterhead_mode: e.target.value as LetterheadMode }))}
            >
              {LETTERHEAD_MODE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          {/* Predeterminado */}
          <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
            <input
              type="checkbox"
              className="accent-amber-600"
              checked={st.is_default}
              onChange={(e) => setSt((p) => ({ ...p, is_default: e.target.checked }))}
            />
            Usar como formato predeterminado de la clínica
          </label>
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <button type="button" onClick={onClose} className="btn-secondary px-4 py-2">Cancelar</button>
          <button
            type="button"
            onClick={guardar}
            disabled={pendiente}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
          >
            {pendiente
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</>
              : <><Save className="w-4 h-4" /> {esEdicion ? 'Guardar cambios' : 'Crear formato'}</>}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/* ─── Mini-preview de una plantilla (esquemático, no es el PDF real) ────────── */

function MiniPreview({ layout, accent }: { layout: PrescriptionBaseLayout; accent: string }) {
  // Proporción de hoja según el layout (vertical / horizontal media carta / digital).
  const ratio = layout === 'compact' ? '8 / 5' : layout === 'digital' ? '4 / 5' : '3 / 4'
  return (
    <div
      className="w-full rounded-md border border-gray-200 bg-white overflow-hidden"
      style={{ aspectRatio: ratio }}
    >
      <div className="h-1.5 w-full" style={{ background: accent }} />
      <div className="p-1.5 space-y-1">
        <div className="h-1 rounded-full bg-gray-300" style={{ width: '60%' }} />
        <div className="h-1 rounded-full bg-gray-200" style={{ width: '85%' }} />
        <div className="h-1 rounded-full bg-gray-200" style={{ width: '75%' }} />
        <div className="h-1 rounded-full" style={{ width: '40%', background: accent, opacity: 0.5 }} />
      </div>
    </div>
  )
}
