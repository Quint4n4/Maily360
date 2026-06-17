/**
 * EvolucionTab — pestaña Evolución.
 * Lista de notas inmutables (solo lectura) con sus addenda; alta de nota desde una
 * cita ATTENDED del paciente; agregar addendum a una nota.
 *
 * La exploración por aparatos usa TARJETAS estilo legacy: una cuadrícula con la
 * imagen anatómica de cada sistema + un semáforo de 4 colores (no_evaluado /
 * normal / observación / alterado) + un campo de detalle "Más" que aparece al
 * elegir un estado distinto de "no evaluado". Solo se envían al backend los
 * sistemas con estado ≠ no_evaluado (regla D-EC).
 */

import { useMemo, useRef, useState } from 'react'
import {
  Stethoscope, Plus, Loader2, MessageSquarePlus, Lock, X, Activity, ChevronDown,
  ImagePlus, Trash2, ImageIcon,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Appointment } from '../../types/agenda'
import type {
  EvolutionImage, EvolutionNote, EvolutionNoteInput, ExploracionEvolucion,
  ExploracionEvolucionEstado, ExploracionSistema, VitalSignsRecord,
} from '../../types/expediente'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import {
  useCreateAddendum, useCreateEvolutionNote, useDeleteEvolutionImage, useEvolutionImages,
  useEvolutionNotes, useUploadEvolutionImage, useVitalSigns,
} from '../../hooks/expediente'
import { formatFechaHora } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import {
  Card, Cargando, ErroresAlerta, Vacio, EXPLORACION_EVOLUCION_OPTIONS, SISTEMA_LABEL,
  SistemaIcono, SistemaLabelConIcono,
} from './ui'

const SISTEMAS: ExploracionSistema[] = [
  'cerebro', 'sistema_nervioso', 'ocular', 'endocrino', 'corazon', 'circulatorio',
  'respiratorio', 'hepatico', 'pancreas', 'renal', 'gastrointestinal', 'osteoarticular',
  'tendomuscular', 'reproductor', 'inmunologico', 'extremidades', 'piel_tegumentos', 'otros',
]

/**
 * Campos de texto de la nota de evolución, en el orden y con los nombres del
 * legacy. La "Exploración Física" no es un campo de texto: es la cuadrícula de
 * tarjetas, que se intercala entre «Estudios» y «Diagnósticos Actuales».
 */
const TEXTO_CAMPOS: { key: keyof NotaTexto; label: string }[] = [
  { key: 'antecedentes', label: 'Antecedentes Patológicos' },
  { key: 'interrogatorio', label: 'Interrogatorio' },
  { key: 'estudios', label: 'Estudios' },
]

const TEXTO_CAMPOS_POST: { key: keyof NotaTexto; label: string }[] = [
  { key: 'diagnosticos_texto', label: 'Diagnósticos Actuales' },
  { key: 'tratamiento', label: 'Tratamiento' },
  { key: 'plan_recomendaciones', label: 'Plan y Recomendaciones' },
  { key: 'indicaciones_enfermeria', label: 'Indicaciones para Enfermería' },
]

/** Todos los campos de texto en orden, para la vista de solo lectura de la nota. */
const TEXTO_CAMPOS_ALL = [...TEXTO_CAMPOS, ...TEXTO_CAMPOS_POST]

interface NotaTexto {
  antecedentes: string
  interrogatorio: string
  estudios: string
  diagnosticos_texto: string
  tratamiento: string
  plan_recomendaciones: string
  indicaciones_enfermeria: string
}

interface EvolucionTabProps {
  paciente: PatientOut
  /** owner/admin/doctor pueden crear evoluciones y addenda. */
  puedeEditar: boolean
}

export default function EvolucionTab({ paciente, puedeEditar }: EvolucionTabProps) {
  const { data: notasData, isLoading, isError } = useEvolutionNotes(paciente.id)
  const { data: signosData } = useVitalSigns(paciente.id)
  const [nueva, setNueva] = useState(false)

  const notas: EvolutionNote[] = notasData?.results ?? []
  const signos: VitalSignsRecord[] = useMemo(() => signosData?.results ?? [], [signosData])

  return (
    <div className="space-y-5">
      {puedeEditar && (
        <div className="flex justify-end">
          <button
            type="button" onClick={() => setNueva(true)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
          >
            <Plus className="w-4 h-4" /> Nueva evolución
          </button>
        </div>
      )}

      {nueva && <NuevaEvolucion paciente={paciente} onClose={() => setNueva(false)} />}

      {isLoading ? (
        <Cargando texto="Cargando evoluciones…" />
      ) : isError ? (
        <p className="text-sm text-red-600 text-center py-8">No se pudieron cargar las notas de evolución.</p>
      ) : notas.length === 0 ? (
        <Card title="Notas de evolución" icon={Stethoscope}>
          <Vacio texto="Aún no hay notas de evolución. Se crean a partir de una cita atendida." />
        </Card>
      ) : (
        notas.map(n => (
          <NotaCard
            key={n.id}
            nota={n}
            patientId={paciente.id}
            puedeEditar={puedeEditar}
            vitalSigns={n.vital_signs_id ? signos.find(s => s.id === n.vital_signs_id) ?? null : null}
          />
        ))
      )}
    </div>
  )
}

// ── Snapshot de signos vitales asociados a la nota ────────────────────────────

/** Un dato del panelito de signos (etiqueta + valor + unidad). */
function SignoDato({
  label, value, unidad,
}: { label: string; value: string | number | null | undefined; unidad?: string }) {
  const hay = value != null && value !== ''
  if (!hay) return null
  return (
    <div className="rounded-lg px-2.5 py-1.5 bg-white/60">
      <p className="text-[10px] text-gray-400">{label}</p>
      <p className="text-sm font-semibold text-gray-700">
        {value}{unidad && <span className="text-[11px] font-normal text-gray-400"> {unidad}</span>}
      </p>
    </div>
  )
}

/** Panel con el snapshot de signos vitales que acompañan a la evolución. */
function SignosSnapshot({ signo }: { signo: VitalSignsRecord }) {
  return (
    <div className="rounded-xl px-3 py-3" style={{ background: 'rgba(201,162,39,0.07)', border: '1px solid rgba(201,162,39,0.2)' }}>
      <div className="flex items-center gap-1.5 mb-2">
        <Activity className="w-3.5 h-3.5" style={{ color: '#B8860B' }} />
        <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/80">
          Signos vitales · {formatFechaHora(signo.measured_at)}
        </p>
      </div>
      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))' }}>
        <SignoDato label="Peso" value={signo.weight_kg} unidad="kg" />
        <SignoDato label="Talla" value={signo.height_m} unidad="m" />
        <SignoDato label="IMC" value={signo.imc} />
        <SignoDato
          label="PA"
          value={signo.systolic != null && signo.diastolic != null ? `${signo.systolic}/${signo.diastolic}` : null}
          unidad="mmHg"
        />
        <SignoDato label="FC" value={signo.heart_rate} unidad="lpm" />
        <SignoDato label="FR" value={signo.resp_rate} unidad="rpm" />
        <SignoDato label="Temp" value={signo.temperature_c} unidad="°C" />
        <SignoDato label="SatO₂" value={signo.oxygen_saturation} unidad="%" />
        <SignoDato label="Glucosa" value={signo.glucose} unidad="mg/dL" />
      </div>
    </div>
  )
}

// ── Card de una nota (solo lectura) ───────────────────────────────────────────

function NotaCard({
  nota, patientId, puedeEditar, vitalSigns,
}: {
  nota: EvolutionNote
  patientId: string
  puedeEditar: boolean
  vitalSigns: VitalSignsRecord | null
}) {
  const addendum = useCreateAddendum(patientId)
  const [body, setBody] = useState('')
  const [abierto, setAbierto] = useState(false)
  const [error, setError] = useState('')

  const explorAlteradas = Object.entries(nota.exploracion_fisica).filter(
    ([, v]) => v?.estado && v.estado !== 'no_evaluado',
  )

  const enviar = async () => {
    if (!body.trim()) { setError('El texto del addendum no puede estar vacío.'); return }
    setError('')
    try {
      await addendum.mutateAsync({ evolutionId: nota.id, input: { body: body.trim() } })
      setBody('')
      setAbierto(false)
    } catch (err) {
      setError(erroresDe(err).join(' '))
    }
  }

  return (
    <Card title={`Evolución · ${formatFechaHora(nota.created_at)}`} icon={Stethoscope}
      action={<span className="inline-flex items-center gap-1 text-[11px] text-gray-400"><Lock className="w-3 h-3" /> Firmada</span>}
    >
      <div className="space-y-2.5">
        {vitalSigns && <SignosSnapshot signo={vitalSigns} />}

        {TEXTO_CAMPOS_ALL.map(({ key, label }) => {
          const val = nota[key as keyof EvolutionNote] as string
          if (!val) return null
          return (
            <div key={key}>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">{label}</p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{val}</p>
            </div>
          )
        })}

        {explorAlteradas.length > 0 && (
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">Exploración Física</p>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {explorAlteradas.map(([sistema, celda]) => {
                const opt = EXPLORACION_EVOLUCION_OPTIONS.find(o => o.value === celda?.estado)
                return (
                  <span key={sistema} className="inline-flex items-center gap-1 text-[11px] rounded-full px-2.5 py-1"
                    style={{ background: `${opt?.color}1A`, color: opt?.color }}>
                    <SistemaLabelConIcono sistema={sistema} />: {opt?.label}{celda?.detalle ? ` (${celda.detalle})` : ''}
                  </span>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Imágenes de la nota */}
      <div className="mt-4 pt-3 border-t border-amber-900/10">
        <GaleriaImagenes evolutionId={nota.id} puedeEditar={puedeEditar} />
      </div>

      {/* Addenda */}
      {nota.addenda.length > 0 && (
        <div className="mt-4 pt-3 border-t border-amber-900/10 space-y-2">
          {nota.addenda.map(a => (
            <div key={a.id} className="rounded-lg px-3 py-2" style={{ background: 'rgba(201,162,39,0.08)' }}>
              <p className="text-[11px] text-gray-400">Addendum · {formatFechaHora(a.created_at)}</p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{a.body}</p>
            </div>
          ))}
        </div>
      )}

      {/* Agregar addendum */}
      {puedeEditar && (
        <div className="mt-3">
          {abierto ? (
            <div className="space-y-2">
              {error && <p className="text-xs text-red-600">{error}</p>}
              <textarea className="input resize-none" rows={2} placeholder="Escribe el addendum…"
                value={body} onChange={e => setBody(e.target.value)} />
              <div className="flex gap-2 justify-end">
                <button type="button" onClick={() => { setAbierto(false); setError('') }} className="btn-secondary text-xs px-3 py-1.5">Cancelar</button>
                <button type="button" onClick={enviar} disabled={addendum.isPending}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-white px-3 py-1.5 rounded-lg disabled:opacity-60"
                  style={{ background: '#C9A227' }}>
                  {addendum.isPending ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Guardando…</> : 'Agregar addendum'}
                </button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setAbierto(true)}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800">
              <MessageSquarePlus className="w-3.5 h-3.5" /> Agregar addendum
            </button>
          )}
        </div>
      )}
    </Card>
  )
}

// ── Galería de imágenes de la nota ────────────────────────────────────────────

/** Tipos de imagen que el navegador deja elegir (UX). El backend valida de verdad. */
const ACCEPT_IMAGEN = 'image/png,image/jpeg,image/webp'

/**
 * Sección "Imágenes" de una nota de evolución: miniaturas en grid (clic → lightbox),
 * subida multipart (si puedeEditar) y borrado con confirmación (baja lógica).
 * La lista se carga al montar el NotaCard (useQuery con queryKey por evolución).
 */
function GaleriaImagenes({
  evolutionId, puedeEditar,
}: {
  evolutionId: string
  puedeEditar: boolean
}) {
  const { data: imagenes, isLoading, isError } = useEvolutionImages(evolutionId)
  const subir = useUploadEvolutionImage(evolutionId)
  const borrar = useDeleteEvolutionImage(evolutionId)
  const inputRef = useRef<HTMLInputElement>(null)

  const [error, setError] = useState('')
  const [ampliada, setAmpliada] = useState<EvolutionImage | null>(null)
  const [aBorrar, setABorrar] = useState<EvolutionImage | null>(null)

  const lista: EvolutionImage[] = imagenes ?? []

  const onPick = () => {
    if (!subir.isPending) inputRef.current?.click()
  }

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // permite volver a elegir el mismo archivo
    if (!file) return
    setError('')
    try {
      await subir.mutateAsync({ file })
    } catch (err) {
      setError(erroresDe(err).join(' '))
    }
  }

  const confirmarBorrado = async () => {
    if (!aBorrar) return
    setError('')
    try {
      await borrar.mutateAsync(aBorrar.id)
      setABorrar(null)
    } catch (err) {
      setError(erroresDe(err).join(' '))
      setABorrar(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-2">
        <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">
          <ImageIcon className="w-3.5 h-3.5" /> Imágenes
          {lista.length > 0 && <span className="text-gray-400 font-normal normal-case">· {lista.length}</span>}
        </p>
        {puedeEditar && (
          <button
            type="button"
            onClick={onPick}
            disabled={subir.isPending}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60"
          >
            {subir.isPending
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Subiendo…</>
              : <><ImagePlus className="w-3.5 h-3.5" /> Agregar imagen</>}
          </button>
        )}
      </div>

      {puedeEditar && (
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_IMAGEN}
          className="hidden"
          onChange={onFile}
        />
      )}

      {error && <p className="text-xs text-red-600 mb-2">{error}</p>}

      {isLoading ? (
        <p className="inline-flex items-center gap-1.5 text-xs text-gray-400 py-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Cargando imágenes…
        </p>
      ) : isError ? (
        <p className="text-xs text-red-600 py-2">No se pudieron cargar las imágenes.</p>
      ) : lista.length === 0 ? (
        <p className="text-xs text-gray-400 italic py-1">Sin imágenes.</p>
      ) : (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))' }}>
          {lista.map(img => (
            <Miniatura
              key={img.id}
              imagen={img}
              puedeEditar={puedeEditar}
              onAmpliar={() => setAmpliada(img)}
              onBorrar={() => setABorrar(img)}
            />
          ))}
        </div>
      )}

      {ampliada && <Lightbox imagen={ampliada} onClose={() => setAmpliada(null)} />}

      {aBorrar && (
        <ConfirmarBorrado
          pendiente={borrar.isPending}
          onCancel={() => setABorrar(null)}
          onConfirm={confirmarBorrado}
        />
      )}
    </div>
  )
}

/** Miniatura de una imagen: clic la amplía; si puedeEditar muestra botón de borrar. */
function Miniatura({
  imagen, puedeEditar, onAmpliar, onBorrar,
}: {
  imagen: EvolutionImage
  puedeEditar: boolean
  onAmpliar: () => void
  onBorrar: () => void
}) {
  return (
    <div className="group relative">
      <button
        type="button"
        onClick={onAmpliar}
        className="block w-full overflow-hidden rounded-xl transition-all hover:brightness-95"
        style={{
          aspectRatio: '1 / 1',
          border: '1px solid rgba(201,162,39,0.25)',
          boxShadow: '0 2px 8px rgba(60,42,12,0.08)',
        }}
        title={imagen.caption || 'Ver imagen'}
      >
        <img
          src={imagen.image_url}
          alt={imagen.caption || 'Imagen de la evolución'}
          loading="lazy"
          className="w-full h-full object-cover"
        />
      </button>
      {imagen.caption && (
        <p className="mt-1 text-[10px] text-gray-500 leading-tight line-clamp-2">{imagen.caption}</p>
      )}
      {puedeEditar && (
        <button
          type="button"
          onClick={onBorrar}
          aria-label="Eliminar imagen"
          title="Eliminar imagen"
          className="absolute top-1 right-1 rounded-full p-1 text-white opacity-0 group-hover:opacity-100 transition-opacity"
          style={{ background: 'rgba(192,57,43,0.92)' }}
        >
          <Trash2 className="w-3 h-3" />
        </button>
      )}
    </div>
  )
}

/** Modal simple que muestra la imagen en grande. Clic fuera o la X cierra. */
function Lightbox({ imagen, onClose }: { imagen: EvolutionImage; onClose: () => void }) {
  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(20,14,4,0.78)', backdropFilter: 'blur(4px)' }}
      role="dialog"
      aria-modal="true"
    >
      <div className="relative max-w-3xl max-h-full" onClick={e => e.stopPropagation()}>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar"
          className="absolute -top-3 -right-3 rounded-full p-1.5 text-gray-700 bg-white shadow-lg hover:text-gray-900"
        >
          <X className="w-4 h-4" />
        </button>
        <img
          src={imagen.image_url}
          alt={imagen.caption || 'Imagen de la evolución'}
          className="max-w-full max-h-[80vh] rounded-xl object-contain"
          style={{ boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}
        />
        {imagen.caption && (
          <p className="mt-2 text-center text-sm text-white/90">{imagen.caption}</p>
        )}
      </div>
    </div>
  )
}

/** Diálogo de confirmación de borrado (baja lógica). */
function ConfirmarBorrado({
  pendiente, onCancel, onConfirm,
}: {
  pendiente: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div
      onClick={onCancel}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(20,14,4,0.6)', backdropFilter: 'blur(3px)' }}
      role="dialog"
      aria-modal="true"
    >
      <div
        onClick={e => e.stopPropagation()}
        className="w-full max-w-sm rounded-2xl p-5"
        style={{
          background: 'rgba(255,255,255,0.96)',
          border: '1px solid rgba(255,255,255,0.7)',
          boxShadow: '0 20px 60px rgba(60,42,12,0.3)',
        }}
      >
        <div className="flex items-center gap-2 mb-2">
          <Trash2 className="w-4 h-4 text-red-500" />
          <h4 className="text-sm font-semibold text-gray-800">Eliminar imagen</h4>
        </div>
        <p className="text-sm text-gray-600 mb-4">
          ¿Seguro que quieres eliminar esta imagen de la nota? Esta acción no se puede deshacer.
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn-secondary text-xs px-3 py-1.5">
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pendiente}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-white px-3 py-1.5 rounded-lg disabled:opacity-60"
            style={{ background: '#C0392B' }}
          >
            {pendiente ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Eliminando…</> : 'Eliminar'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Tarjeta de exploración por aparato (estilo legacy) ─────────────────────────

/** Estado por defecto cuando un sistema aún no se ha tocado. */
const ESTADO_DEFAULT: ExploracionEvolucionEstado = 'no_evaluado'

function ExploracionCard({
  sistema, estado, detalle, onEstado, onDetalle,
}: {
  sistema: ExploracionSistema
  estado: ExploracionEvolucionEstado
  detalle: string
  onEstado: (estado: ExploracionEvolucionEstado) => void
  onDetalle: (detalle: string) => void
}) {
  const opt = EXPLORACION_EVOLUCION_OPTIONS.find(o => o.value === estado)
  const evaluado = estado !== 'no_evaluado'

  return (
    <div
      className="rounded-2xl p-3 flex flex-col items-center text-center transition-all"
      style={{
        background: 'rgba(255,255,255,0.6)',
        border: evaluado ? `1.5px solid ${opt?.color}` : '1px solid rgba(201,162,39,0.18)',
        boxShadow: evaluado ? `0 4px 12px ${opt?.color}26` : '0 2px 8px rgba(60,42,12,0.06)',
      }}
    >
      <p className="text-[11px] font-semibold text-gray-700 leading-tight mb-2 min-h-[28px] flex items-center">
        {SISTEMA_LABEL[sistema] ?? sistema}
      </p>

      {/* Imagen anatómica grande */}
      <SistemaIcono sistema={sistema} className="h-12 w-12 mb-2.5" />

      {/* Semáforo de 4 botones de color */}
      <div className="flex items-center justify-center gap-1.5 mb-2">
        {EXPLORACION_EVOLUCION_OPTIONS.map(o => {
          const sel = o.value === estado
          return (
            <button
              key={o.value}
              type="button"
              title={o.label}
              aria-label={o.label}
              aria-pressed={sel}
              onClick={() => onEstado(o.value)}
              className="rounded-full transition-all"
              style={{
                width: sel ? 22 : 18,
                height: sel ? 22 : 18,
                background: o.color,
                border: sel ? '2px solid #fff' : '2px solid transparent',
                boxShadow: sel ? `0 0 0 2px ${o.color}` : 'none',
                opacity: sel ? 1 : 0.5,
              }}
            />
          )
        })}
      </div>

      {/* Campo "Más" / detalle — solo al elegir un estado distinto de "no evaluado" */}
      {evaluado && (
        <input
          className="input text-xs py-1.5 mt-0.5 w-full"
          placeholder="Más…"
          value={detalle}
          onChange={e => onDetalle(e.target.value)}
        />
      )}
    </div>
  )
}

// ── Formulario de nueva evolución ─────────────────────────────────────────────

const TEXTO_VACIO: NotaTexto = {
  antecedentes: '', interrogatorio: '', estudios: '', diagnosticos_texto: '',
  tratamiento: '', plan_recomendaciones: '', indicaciones_enfermeria: '',
}

function NuevaEvolucion({ paciente, onClose }: { paciente: PatientOut; onClose: () => void }) {
  const { data: citasData, isLoading: citasLoading } = useAppointmentsForPatient(paciente.id)
  const crear = useCreateEvolutionNote(paciente.id)
  const [appointmentId, setAppointmentId] = useState('')
  const [texto, setTexto] = useState<NotaTexto>(TEXTO_VACIO)
  const [explor, setExplor] = useState<ExploracionEvolucion>({})
  const [mostrarExplor, setMostrarExplor] = useState(false)
  const [errores, setErrores] = useState<string[]>([])

  // Solo citas ATTENDED del paciente (requisito del backend D-EC-2).
  const citasAtendidas = useMemo<Appointment[]>(
    () => (citasData?.results ?? []).filter(c => c.status === 'attended'),
    [citasData],
  )
  const citaSel = citasAtendidas.find(c => c.id === appointmentId) ?? null

  const setT = (k: keyof NotaTexto) => (e: React.ChangeEvent<HTMLTextAreaElement>) =>
    setTexto(t => ({ ...t, [k]: e.target.value }))

  const setEstado = (sistema: ExploracionSistema, estado: ExploracionEvolucionEstado) =>
    setExplor(prev => ({ ...prev, [sistema]: { ...prev[sistema], estado } }))

  const setDetalle = (sistema: ExploracionSistema, detalle: string) =>
    setExplor(prev => ({ ...prev, [sistema]: { ...prev[sistema], detalle } }))

  const guardar = async () => {
    setErrores([])
    if (!citaSel) { setErrores(['Elige una cita atendida.']); return }
    // El doctor de la evolución debe ser el doctor de la cita (backend lo valida).
    const input: EvolutionNoteInput = {
      appointment_id: citaSel.id,
      doctor_id: citaSel.doctor.id,
      ...texto,
    }
    // Solo enviar exploración de sistemas con estado distinto de 'no_evaluado'.
    const explorEnviar: ExploracionEvolucion = {}
    for (const [sistema, celda] of Object.entries(explor)) {
      if (celda?.estado && celda.estado !== 'no_evaluado') explorEnviar[sistema as ExploracionSistema] = celda
    }
    if (Object.keys(explorEnviar).length > 0) input.exploracion_fisica = explorEnviar
    try {
      await crear.mutateAsync(input)
      onClose()
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <Card title="Nueva nota de evolución" icon={Plus}
      action={<button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700"><X className="w-4 h-4" /></button>}
    >
      <div className="space-y-4">
        <ErroresAlerta errores={errores} />

        <div>
          <label className="label">Cita atendida</label>
          {citasLoading ? (
            <p className="text-sm text-gray-400 italic">Cargando citas…</p>
          ) : citasAtendidas.length === 0 ? (
            <p className="text-sm text-amber-700">
              Este paciente no tiene citas atendidas. La nota de evolución nace de una cita marcada como «Atendida».
            </p>
          ) : (
            <select className="input" value={appointmentId} onChange={e => setAppointmentId(e.target.value)}>
              <option value="">Selecciona una cita…</option>
              {citasAtendidas.map(c => (
                <option key={c.id} value={c.id}>
                  {formatFechaHora(c.starts_at)} · {c.doctor.full_name}
                </option>
              ))}
            </select>
          )}
        </div>

        {citaSel && (
          <>
            {/* Todos los campos de texto, en el orden del legacy */}
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
              {TEXTO_CAMPOS_ALL.map(({ key, label }) => (
                <div key={key}>
                  <label className="label">{label}</label>
                  <textarea className="input resize-none" rows={2} value={texto[key]} onChange={setT(key)} />
                </div>
              ))}
            </div>

            {/* Exploración por aparatos — opcional, colapsable, al final (estilo legacy) */}
            <div className="border-t border-amber-900/10 pt-3">
              <button
                type="button"
                onClick={() => setMostrarExplor(v => !v)}
                className="inline-flex items-center gap-2 text-sm font-semibold text-amber-700 hover:text-amber-800"
              >
                <Stethoscope className="w-4 h-4" />
                {mostrarExplor ? 'Ocultar exploración por aparatos' : 'Exploración por aparatos (opcional)'}
                <ChevronDown className={`w-4 h-4 transition-transform ${mostrarExplor ? 'rotate-180' : ''}`} />
              </button>
              {mostrarExplor && (
                <div className="mt-3">
                  <p className="text-[11px] text-gray-400 mb-3">
                    Elige el estado de cada aparato con el semáforo. Solo se guardan los que evalúes.
                  </p>
                  <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))' }}>
                    {SISTEMAS.map(sistema => {
                      const celda = explor[sistema] ?? {}
                      return (
                        <ExploracionCard
                          key={sistema}
                          sistema={sistema}
                          estado={celda.estado ?? ESTADO_DEFAULT}
                          detalle={celda.detalle ?? ''}
                          onEstado={estado => setEstado(sistema, estado)}
                          onDetalle={detalle => setDetalle(sistema, detalle)}
                        />
                      )
                    })}
                  </div>
                  <div className="flex flex-wrap items-center gap-3 mt-3">
                    {EXPLORACION_EVOLUCION_OPTIONS.map(o => (
                      <span key={o.value} className="inline-flex items-center gap-1.5 text-[11px] text-gray-500">
                        <span className="w-3 h-3 rounded-full" style={{ background: o.color }} /> {o.label}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className="btn-secondary px-4 py-2">Cancelar</button>
              <button type="button" onClick={guardar} disabled={crear.isPending}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : <><Lock className="w-4 h-4" /> Firmar y guardar</>}
              </button>
            </div>
          </>
        )}
      </div>
    </Card>
  )
}
