/**
 * SeccionFormatos — "Configuración de recetas" (formatos del PDF).
 *
 * Lista los PrescriptionFormat del tenant y permite crear/editar/borrar. El editor
 * cubre: nombre, plantilla base (Paciente / Farmacia), color de acento, tipografía,
 * secciones visibles, "predeterminado" y asignación a un médico. Incluye una
 * MAQUETA EN VIVO (aproximada) que reacciona al color y a las secciones, y un botón
 * de vista previa del PDF real.
 *
 * Permisos UX: owner/admin gestionan. El backend es la autoridad (403/400 mapeados).
 */

import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  FileText, Loader2, Plus, Save, Star, Trash2, X,
} from 'lucide-react'
import { listPatients } from '../../api/pacientes'
import { listDoctors } from '../../api/personal'
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
  PrescriptionBaseLayout,
  PrescriptionFont,
  PrescriptionFormatCreateInput,
  PrescriptionFormatOut,
  PrescriptionFormatUpdateInput,
  PrescriptionTheme,
} from '../../types/recetas'
import {
  BASE_LAYOUT_OPTIONS,
  FONT_OPTIONS,
  SECTION_OPTIONS,
  THEME_OPTIONS,
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

/** Secciones por defecto (todas activas), igual que el backend (get_sections_full). */
const SECCIONES_DEFAULT: FormatSections = {
  signos: true,
  edad_sexo: true,
  diagnostico: true,
  alergias: true,
  sueros: true,
  terapias: true,
  indicaciones: true,
  vigencia: true,
  contacto_clinica: true,
  qr: true,
}

/**
 * Busca el id de una receta de ejemplo del tenant para la vista previa del PDF.
 * Recorre los primeros pacientes (1ª página) y devuelve la 1ª receta que halle.
 */
function useSamplePrescriptionId() {
  return useQuery({
    queryKey: ['recetas', 'sample-id'],
    queryFn: async (): Promise<string | null> => {
      const page = await listPatients({ page: 1 })
      for (const paciente of page.results.slice(0, 10)) {
        const recetas = await listPrescriptions(paciente.id)
        if (recetas.results.length > 0) return recetas.results[0].id
      }
      return null
    },
    staleTime: 5 * 60_000,
  })
}

/** Sección "Configuración de recetas" de Mi Consultorio. */
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
          Hay dos tipos de receta: <strong>Paciente</strong> (hoja completa, con recomendaciones) y{' '}
          <strong>Farmacia</strong> (media carta, para comprar medicamentos). Personaliza color,
          tipografía y qué secciones aparecen; la maqueta se actualiza al instante.
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
          Para la vista previa en PDF necesitas al menos una receta emitida. La maqueta en vivo
          sí funciona sin recetas.
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
            {formato.doctor_id && !formato.is_authorized && (
              <span
                className="text-[10px] rounded-full px-1.5 py-0.5"
                style={{ background: 'rgba(120,120,120,0.12)', color: '#555' }}
              >
                Por médico
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
  theme: PrescriptionTheme
  sections: FormatSections
  is_default: boolean
  doctor_id: string | null
  is_authorized: boolean
}

function estadoInicial(formato: PrescriptionFormatOut | null): EditorState {
  if (formato) {
    return {
      name: formato.name,
      base_layout: formato.base_layout,
      accent_color: formato.accent_color,
      font: formato.font,
      theme: formato.theme ?? 'ondas',
      sections: { ...SECCIONES_DEFAULT, ...formato.sections },
      is_default: formato.is_default,
      doctor_id: formato.doctor_id,
      is_authorized: formato.is_authorized,
    }
  }
  return {
    name: '',
    base_layout: 'digital',
    accent_color: ACCENT_DEFAULT,
    font: 'helvetica',
    theme: 'ondas',
    sections: { ...SECCIONES_DEFAULT },
    is_default: false,
    doctor_id: null,
    is_authorized: false,
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
  const doctoresQ = useQuery({
    queryKey: ['doctores', 'para-formato'],
    queryFn: () => listDoctors(true),
    staleTime: 5 * 60_000,
  })
  const doctores = doctoresQ.data?.results ?? []
  const [st, setSt] = useState<EditorState>(() => estadoInicial(formato))
  const [errores, setErrores] = useState<string[]>([])

  const pendiente = crear.isPending || actualizar.isPending

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
          theme: st.theme,
          sections: st.sections,
          is_default: st.is_default,
          doctor_id: st.doctor_id,
          is_authorized: st.doctor_id ? st.is_authorized : false,
        }
        await actualizar.mutateAsync({ id: formato.id, input })
      } else {
        const input: PrescriptionFormatCreateInput = {
          name: st.name.trim(),
          base_layout: st.base_layout,
          accent_color: st.accent_color,
          font: st.font,
          theme: st.theme,
          sections: st.sections,
          is_default: st.is_default,
          doctor_id: st.doctor_id,
        }
        const creado = await crear.mutateAsync(input)
        if (st.doctor_id && st.is_authorized && creado?.id) {
          await actualizar.mutateAsync({ id: creado.id, input: { is_authorized: true } })
        }
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
        className="w-full max-w-5xl max-h-[92vh] flex flex-col rounded-2xl"
        style={{ background: 'rgba(255,255,255,0.98)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 20px 60px rgba(60,42,12,0.3)' }}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h3 className="text-lg font-semibold text-gray-800">
            {esEdicion ? 'Editar formato' : 'Nuevo formato'}
          </h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_minmax(0,380px)] gap-6 overflow-y-auto px-6 py-5">
          {/* ── Formulario ── */}
          <div className="space-y-5">
            <AlertaErrores errores={errores} />

            {/* Nombre */}
            <div>
              <label className="label" htmlFor="fmt-name">Nombre *</label>
              <input
                id="fmt-name"
                className="input"
                maxLength={150}
                placeholder="Ej. Receta dorada"
                value={st.name}
                onChange={(e) => setSt((p) => ({ ...p, name: e.target.value }))}
              />
            </div>

            {/* Plantilla base */}
            <div>
              <p className="label">Tipo de receta</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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

            {/* Estilo decorativo */}
            <div>
              <label className="label" htmlFor="fmt-theme">Estilo (decoración)</label>
              <select
                id="fmt-theme"
                className="input"
                value={st.theme}
                onChange={(e) => setSt((p) => ({ ...p, theme: e.target.value as PrescriptionTheme }))}
              >
                {THEME_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <p className="text-[11px] text-gray-500 mt-1">
                {THEME_OPTIONS.find((o) => o.value === st.theme)?.description}
              </p>
            </div>

            {/* Secciones */}
            <div>
              <p className="label">Secciones visibles</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
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
              <p className="text-[11px] text-gray-400 mt-1">
                El médico, sus cédulas, el folio, el paciente, la fecha y los medicamentos
                siempre aparecen (no se pueden ocultar).
              </p>
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

            {/* Asignar a un médico */}
            <div className="rounded-xl border border-gray-100 bg-white/60 p-3 space-y-3">
              <div>
                <label className="label" htmlFor="fmt-doctor">Asignar a un médico (opcional)</label>
                <select
                  id="fmt-doctor"
                  className="input"
                  value={st.doctor_id ?? ''}
                  onChange={(e) =>
                    setSt((p) => ({
                      ...p,
                      doctor_id: e.target.value || null,
                      is_authorized: e.target.value ? p.is_authorized : false,
                    }))
                  }
                >
                  <option value="">— Formato general de la clínica —</option>
                  {doctores.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.full_name}{d.specialty ? ` · ${d.specialty}` : ''}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-gray-500 mt-1">
                  Si eliges un médico, este formato será el suyo. Útil cuando la clínica tiene
                  varias especialidades y cada doctor quiere su propia receta.
                </p>
              </div>

              {st.doctor_id && (
                <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
                  <input
                    type="checkbox"
                    className="accent-amber-600"
                    checked={st.is_authorized}
                    onChange={(e) => setSt((p) => ({ ...p, is_authorized: e.target.checked }))}
                  />
                  Autorizar: usar automáticamente este formato en las recetas de ese médico
                </label>
              )}
            </div>
          </div>

          {/* ── Maqueta en vivo ── */}
          <div className="lg:sticky lg:top-0 self-start">
            <PreviewReceta st={st} />
          </div>
        </div>

        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-100">
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

/* ─── Mini-preview de una plantilla (esquemático) ─────────────────────────── */

function MiniPreview({ layout, accent }: { layout: PrescriptionBaseLayout; accent: string }) {
  // Paciente = hoja vertical; Farmacia = media carta horizontal.
  const ratio = layout === 'compact' ? '8 / 5' : '3 / 4'
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

/* ─── Maqueta en vivo de la receta (aproximada, reacciona a color + secciones) ── */

function PreviewReceta({ st }: { st: EditorState }) {
  const accent = HEX_RE.test(st.accent_color) ? st.accent_color : ACCENT_DEFAULT
  const esPaciente = st.base_layout === 'digital'
  const S = st.sections
  const lbl: React.CSSProperties = { color: accent, fontWeight: 600 }
  const num: React.CSSProperties = {
    background: `${accent}28`, color: accent, borderRadius: '50%',
    padding: '0 3px', fontWeight: 700,
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
      <p className="text-[11px] text-gray-500 mb-2 flex items-center gap-1">
        <FileText className="w-3.5 h-3.5" /> Maqueta en vivo · {esPaciente ? 'Paciente' : 'Farmacia'}
      </p>
      <div
        className="mx-auto bg-white border border-gray-200 overflow-hidden"
        style={{
          width: esPaciente ? '76%' : '100%',
          aspectRatio: esPaciente ? '0.77' : '1.55',
          fontSize: '6px',
          lineHeight: 1.35,
          color: '#333',
          padding: '7px 9px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
          position: 'relative',
        }}
      >
        <ThemeDecorMini theme={st.theme} accent={accent} />
        {/* Encabezado */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <div style={{ width: '24px', height: '24px', borderRadius: '4px', background: '#f3eecf', flexShrink: 0 }} />
          <div style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ color: accent, fontWeight: 700, fontSize: '9px', letterSpacing: '0.3px' }}>TU CLÍNICA</div>
            <div style={{ fontWeight: 600 }}>Dr. Ejemplo López</div>
            <div style={{ color: '#888' }}>Especialidad</div>
          </div>
          {S.qr && <div style={{ width: '22px', height: '22px', background: '#222', flexShrink: 0 }} />}
        </div>

        {/* Credenciales (siempre) */}
        <div style={{ display: 'flex', gap: '5px', justifyContent: 'center', marginTop: '3px', textAlign: 'center' }}>
          <div style={{ flex: 1 }}><div style={lbl}>Cédula profesional</div><div>Céd. 1234567</div></div>
          <div style={{ flex: 1, borderLeft: `1px solid ${accent}44` }}><div style={lbl}>Especialidad</div><div>Céd. 7654321</div></div>
        </div>
        <div style={{ borderBottom: `1px solid ${accent}`, margin: '4px 0' }} />

        {/* Cuerpo */}
        <div style={{ display: esPaciente ? 'block' : 'flex', gap: '7px' }}>
          <div style={{ flex: esPaciente ? undefined : 2, minWidth: 0 }}>
            <span style={{ border: `1px solid ${accent}`, color: accent, borderRadius: '6px', padding: '0 4px', fontWeight: 600 }}>Folio Nº 5</span>
            <div style={{ marginTop: '2px' }}><span style={lbl}>Paciente:</span> Juan Pérez{S.edad_sexo && ' · 34 años · M'}</div>
            <div><span style={lbl}>Fecha:</span> 22/06/2026</div>
            {S.diagnostico && <div><span style={lbl}>Diagnóstico:</span> Gripa</div>}
            {S.alergias && <div><span style={lbl}>Alergias:</span> Penicilina</div>}

            <div style={{ color: accent, fontWeight: 700, fontSize: '8px', marginTop: '4px', borderBottom: `1px solid ${accent}`, paddingBottom: '1px' }}>MEDICAMENTOS</div>
            <div style={{ marginTop: '2px' }}>
              <div><span style={num}>1</span> <b style={{ color: '#1a1a1a' }}>Amoxicilina</b> · 250 mg</div>
              <div style={{ color: '#555', marginLeft: '8px' }}><span style={lbl}>Dosis:</span> 1 tab · <span style={lbl}>Frecuencia:</span> cada 8 h · <span style={lbl}>Durante:</span> 7 días</div>
              <div style={{ marginTop: '2px' }}><span style={num}>2</span> <b style={{ color: '#1a1a1a' }}>Paracetamol</b> · 500 mg</div>
              <div style={{ color: '#555', marginLeft: '8px' }}><span style={lbl}>Dosis:</span> 1 tab · <span style={lbl}>Frecuencia:</span> cada 6 h · <span style={lbl}>Durante:</span> 5 días</div>
            </div>
            {S.sueros && <div style={{ color: accent, fontWeight: 600, marginTop: '3px' }}>Sueros / soluciones</div>}
            {S.terapias && <div style={{ color: accent, fontWeight: 600, marginTop: '2px' }}>Terapias / procedimientos</div>}
          </div>

          {/* Datos del paciente: a la derecha en farmacia */}
          {!esPaciente && S.signos && (
            <div style={{ flex: 1, background: '#fcf8ee', border: `1px solid ${accent}66`, borderRadius: '4px', padding: '3px 4px', alignSelf: 'flex-start' }}>
              <div style={{ ...lbl, fontSize: '6px' }}>DATOS DEL PACIENTE</div>
              <div>Peso: 75 kg</div>
              <div>Talla: 1.73 m</div>
              <div>Presión: 118/76</div>
              <div>Temp.: 36.5 °C</div>
            </div>
          )}
        </div>

        {/* Datos del paciente: en banda en formato Paciente */}
        {esPaciente && S.signos && (
          <div style={{ background: '#fcf8ee', border: `1px solid ${accent}66`, borderRadius: '4px', padding: '3px 5px', marginTop: '3px' }}>
            <span style={lbl}>Datos del paciente:</span> Peso 75 kg · Talla 1.73 m · Presión 118/76 · Temp. 36.5 °C
          </div>
        )}

        {/* Recomendaciones: solo en formato Paciente */}
        {esPaciente && S.indicaciones && (
          <div style={{ background: '#fcf8ee', borderLeft: `2px solid ${accent}`, padding: '3px 5px', marginTop: '3px' }}>
            <div style={lbl}>RECOMENDACIONES</div>
            <div>Reposo relativo, abundantes líquidos y dieta blanda.</div>
          </div>
        )}

        {S.vigencia && <div style={{ color: '#888', marginTop: '3px' }}>Vigencia de la receta: 22/07/2026</div>}

        {/* Pie */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginTop: '5px', borderTop: '1px solid #eee', paddingTop: '3px' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ borderTop: '1px solid #999', width: '52px', margin: '0 auto' }} />
            <span style={{ color: '#999' }}>Firma y sello</span>
          </div>
          {S.contacto_clinica && (
            <div style={{ textAlign: 'right', color: '#999' }}>Calle Ejemplo 123, Ciudad<br />Tel. 555 123 4567</div>
          )}
        </div>
      </div>
      <p className="text-[10px] text-gray-400 mt-2 italic">
        Aproximada. Usa “Vista previa PDF” en la tarjeta para ver el resultado exacto.
      </p>
    </div>
  )
}

/* ─── Decoración de la maqueta según el estilo (aproximada) ────────────────── */

function ThemeDecorMini({ theme, accent }: { theme: PrescriptionTheme; accent: string }) {
  const base: React.CSSProperties = { position: 'absolute', pointerEvents: 'none' }
  if (theme === 'minimal') return null
  if (theme === 'barra') {
    return <div style={{ ...base, top: 0, left: 0, width: '4px', height: '100%', background: accent }} />
  }
  if (theme === 'geometrico') {
    return (
      <>
        <div style={{ ...base, top: '-14px', right: '-14px', width: '46px', height: '46px', borderRadius: '50%', background: accent, opacity: 0.10 }} />
        <div style={{ ...base, top: '-5px', right: '-5px', width: '22px', height: '22px', borderRadius: '50%', background: accent, opacity: 0.16 }} />
        <div style={{ ...base, bottom: '-12px', left: '-12px', width: '36px', height: '36px', borderRadius: '50%', background: accent, opacity: 0.10 }} />
      </>
    )
  }
  // ondas (por defecto)
  return (
    <>
      <div style={{ ...base, top: 0, right: 0, width: '58px', height: '34px', background: accent, opacity: 0.12, borderBottomLeftRadius: '60px' }} />
      <div style={{ ...base, bottom: 0, left: 0, width: '68px', height: '20px', background: accent, opacity: 0.10, borderTopRightRadius: '60px' }} />
    </>
  )
}
