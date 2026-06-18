/**
 * RecetasTab — sección Recetas del expediente (B1.4).
 *
 * Dos bloques:
 *   1. Nueva receta (solo a quien puede emitir — UX): buscador de medicamentos con
 *      autocompletar (global vs custom + texto libre), renglones de tratamiento
 *      (medicamento + indicación requerida + cantidad), recomendaciones, "mostrar
 *      signos" (última toma como referencia) y "copiar de una receta previa".
 *      Al guardar → POST crear, invalida historial y ofrece ver el PDF.
 *   2. Historial: recetas del paciente (paginado, recientes primero) con folio,
 *      fecha, médico, estado (Activa/Anulada) y nº de medicamentos. Acciones:
 *      Ver PDF (blob con Bearer), Copiar a nueva, Anular (motivo; emisor/owner/admin).
 *
 * El backend es la autoridad de permisos: ante 403/400 se mapean los errores DRF
 * y se muestran sin romper la pantalla.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Pill, Plus, Loader2, X, FileText, Copy, Ban, Search, Trash2, Activity,
  Send, AlertCircle, CheckCircle2, ChevronDown,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type {
  MedicationFormValue,
  MedicationSearchResult,
  PrescriptionCreateInput,
  PrescriptionDetail,
  PrescriptionItemInput,
  PrescriptionListItem,
  PrescriptionVitalsSnapshot,
} from '../../types/recetas'
import type { VitalSignsRecord } from '../../types/expediente'
import {
  useCancelPrescription,
  useCreatePrescription,
  useMedicationSearch,
  useOpenPrescriptionPdf,
  usePrescriptions,
} from '../../hooks/recetas'
import { getPrescription } from '../../api/recetas'
import { useAviso } from '../common/DialogProvider'
import { useVitalSigns } from '../../hooks/expediente'
import { useTemplates } from '../../hooks/clinica'
import { formatFechaHora } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import {
  Card, Cargando, ErroresAlerta, Vacio, MEDICATION_FORM_OPTIONS, formaLabel,
} from './ui'

interface RecetasTabProps {
  paciente: PatientOut
  /** owner/admin/doctor pueden emitir y anular recetas (UX; el backend manda). */
  puedeEmitir: boolean
  puedeAnular: boolean
}

/** Renglón de tratamiento en edición (estado local del formulario). */
interface RenglonEdit {
  /** id local estable para keys de React (no se envía al backend). */
  uid: string
  medication_name: string
  medication_form: string
  medication_concentration: string
  medication_presentation: string
  indication: string
  quantity: string
  global_medication_id: string | null
  medication_id: string | null
}

let uidSeq = 0
const nuevoUid = (): string => `r${++uidSeq}`

const renglonVacio = (): RenglonEdit => ({
  uid: nuevoUid(),
  medication_name: '',
  medication_form: '',
  medication_concentration: '',
  medication_presentation: '',
  indication: '',
  quantity: '',
  global_medication_id: null,
  medication_id: null,
})

export default function RecetasTab({ paciente, puedeEmitir, puedeAnular }: RecetasTabProps) {
  const { data: recetasData, isLoading, isError } = usePrescriptions(paciente.id)
  const [nueva, setNueva] = useState(false)
  /** Prellenado pendiente cuando se pulsa "Copiar a nueva" desde el historial. */
  const [prefill, setPrefill] = useState<PrescriptionDetail | null>(null)

  const recetas: PrescriptionListItem[] = recetasData?.results ?? []

  const abrirNuevaVacia = () => {
    setPrefill(null)
    setNueva(true)
  }
  const abrirNuevaConPrefill = (detalle: PrescriptionDetail) => {
    setPrefill(detalle)
    setNueva(true)
  }

  return (
    <div className="space-y-5">
      {puedeEmitir && !nueva && (
        <div className="flex justify-end">
          <button
            type="button" onClick={abrirNuevaVacia}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
          >
            <Plus className="w-4 h-4" /> Nueva receta
          </button>
        </div>
      )}

      {nueva && (
        <NuevaReceta
          paciente={paciente}
          prefill={prefill}
          onClose={() => { setNueva(false); setPrefill(null) }}
        />
      )}

      {isLoading ? (
        <Cargando texto="Cargando recetas…" />
      ) : isError ? (
        <p className="text-sm text-red-600 text-center py-8">No se pudieron cargar las recetas.</p>
      ) : recetas.length === 0 ? (
        <Card title="Recetas" icon={Pill}>
          <Vacio texto="Aún no hay recetas emitidas para este paciente." />
        </Card>
      ) : (
        recetas.map(r => (
          <RecetaCard
            key={r.id}
            receta={r}
            patientId={paciente.id}
            puedeEmitir={puedeEmitir}
            puedeAnular={puedeAnular}
            onCopiar={abrirNuevaConPrefill}
          />
        ))
      )}
    </div>
  )
}

// ── Card de una receta del historial ──────────────────────────────────────────

function RecetaCard({
  receta, patientId, puedeEmitir, puedeAnular, onCopiar,
}: {
  receta: PrescriptionListItem
  patientId: string
  puedeEmitir: boolean
  puedeAnular: boolean
  onCopiar: (detalle: PrescriptionDetail) => void
}) {
  const abrirPdf = useOpenPrescriptionPdf()
  const anular = useCancelPrescription(patientId)
  const aviso = useAviso()
  const [confirmAnular, setConfirmAnular] = useState(false)
  const [copiando, setCopiando] = useState(false)
  const [error, setError] = useState('')

  const anulada = receta.status === 'cancelled'

  const verPdf = async () => {
    setError('')
    try {
      await abrirPdf.mutateAsync(receta.id)
    } catch (err) {
      setError(erroresDe(err).join(' '))
    }
  }

  const copiar = async () => {
    setError('')
    setCopiando(true)
    try {
      // GET detalle → prellenar el formulario nuevo (incluye items completos).
      const detalle = await getPrescription(receta.id)
      onCopiar(detalle)
    } catch (err) {
      setError(erroresDe(err).join(' '))
    } finally {
      setCopiando(false)
    }
  }

  const enviarWhatsApp = () => {
    void aviso({
      titulo: 'Envío por WhatsApp (simulado)',
      mensaje: 'Esta función aún no envía mensajes reales; es una vista previa de la integración.',
      tipo: 'info',
    })
  }

  return (
    <Card
      title={`Receta · Folio ${receta.folio}`}
      icon={Pill}
      action={
        <span
          className="badge"
          style={anulada
            ? { background: '#F3DADA', color: '#A33' }
            : { background: '#E7F6EE', color: '#2E7D5B' }}
        >
          {anulada ? 'Anulada' : 'Activa'}
        </span>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600">
          <span>{formatFechaHora(receta.issued_at)}</span>
          {receta.doctor.full_name && (
            <span className="text-gray-700 font-medium">{receta.doctor.full_name}</span>
          )}
          {receta.doctor.cedula_profesional && (
            <span className="text-xs text-gray-400">Céd. {receta.doctor.cedula_profesional}</span>
          )}
          <span className="text-xs rounded-full px-2 py-0.5" style={{ background: 'rgba(201,162,39,0.12)', color: '#9A7B1E' }}>
            {receta.items_count} {receta.items_count === 1 ? 'medicamento' : 'medicamentos'}
          </span>
        </div>

        {receta.recommendations && (
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">Recomendaciones</p>
            <p className="text-sm text-gray-700 whitespace-pre-wrap">{receta.recommendations}</p>
          </div>
        )}

        {anulada && receta.cancellation_reason && (
          <div className="rounded-lg px-3 py-2" style={{ background: 'rgba(190,40,40,0.08)' }}>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-red-700/80">Motivo de anulación</p>
            <p className="text-sm text-red-700">{receta.cancellation_reason}</p>
          </div>
        )}

        {error && <p className="text-xs text-red-600">{error}</p>}

        {/* Acciones */}
        <div className="flex flex-wrap gap-2 pt-1">
          <button
            type="button" onClick={verPdf} disabled={abrirPdf.isPending}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60 rounded-lg px-3 py-1.5"
            style={{ background: 'rgba(201,162,39,0.10)' }}
          >
            {abrirPdf.isPending
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Abriendo…</>
              : <><FileText className="w-3.5 h-3.5" /> Ver PDF</>}
          </button>

          <button
            type="button" onClick={enviarWhatsApp}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 hover:text-emerald-800 rounded-lg px-3 py-1.5"
            style={{ background: 'rgba(37,211,102,0.12)' }}
          >
            <Send className="w-3.5 h-3.5" /> Enviar por WhatsApp
          </button>

          {puedeEmitir && (
            <button
              type="button" onClick={copiar} disabled={copiando}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-gray-600 hover:text-gray-800 disabled:opacity-60 rounded-lg px-3 py-1.5"
              style={{ background: 'rgba(120,120,120,0.10)' }}
            >
              {copiando
                ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Cargando…</>
                : <><Copy className="w-3.5 h-3.5" /> Copiar a nueva</>}
            </button>
          )}

          {puedeAnular && !anulada && (
            <button
              type="button" onClick={() => setConfirmAnular(true)}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-600 hover:text-red-700 rounded-lg px-3 py-1.5"
              style={{ background: 'rgba(190,40,40,0.08)' }}
            >
              <Ban className="w-3.5 h-3.5" /> Anular
            </button>
          )}
        </div>
      </div>

      {confirmAnular && (
        <AnularReceta
          pendiente={anular.isPending}
          onCancel={() => setConfirmAnular(false)}
          onConfirm={async reason => {
            setError('')
            try {
              await anular.mutateAsync({ prescriptionId: receta.id, input: { reason } })
              setConfirmAnular(false)
            } catch (err) {
              setError(erroresDe(err).join(' '))
              setConfirmAnular(false)
            }
          }}
        />
      )}
    </Card>
  )
}

// ── Diálogo de anulación (motivo requerido) ────────────────────────────────────

function AnularReceta({
  pendiente, onCancel, onConfirm,
}: {
  pendiente: boolean
  onCancel: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')

  const confirmar = () => {
    if (!reason.trim()) { setErr('El motivo de anulación es obligatorio.'); return }
    setErr('')
    onConfirm(reason.trim())
  }

  return createPortal(
    <div
      onClick={onCancel}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(20,14,4,0.6)', backdropFilter: 'blur(3px)' }}
      role="dialog" aria-modal="true"
    >
      <div
        onClick={e => e.stopPropagation()}
        className="w-full max-w-sm rounded-2xl p-5"
        style={{ background: 'rgba(255,255,255,0.96)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 20px 60px rgba(60,42,12,0.3)' }}
      >
        <div className="flex items-center gap-2 mb-2">
          <Ban className="w-4 h-4 text-red-500" />
          <h4 className="text-sm font-semibold text-gray-800">Anular receta</h4>
        </div>
        <p className="text-sm text-gray-600 mb-3">
          La receta quedará marcada como anulada (no se borra). Indica el motivo.
        </p>
        {err && <p className="text-xs text-red-600 mb-2">{err}</p>}
        <textarea
          className="input resize-none" rows={2} placeholder="Motivo de la anulación…"
          value={reason} onChange={e => setReason(e.target.value)}
        />
        <div className="flex justify-end gap-2 mt-3">
          <button type="button" onClick={onCancel} className="btn-secondary text-xs px-3 py-1.5">Cancelar</button>
          <button
            type="button" onClick={confirmar} disabled={pendiente}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-white px-3 py-1.5 rounded-lg disabled:opacity-60"
            style={{ background: '#C0392B' }}
          >
            {pendiente ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Anulando…</> : 'Anular receta'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

// ── Snapshot / última toma de signos (referencia) ──────────────────────────────

function SignoDato({ label, value, unidad }: { label: string; value: string | number | null | undefined; unidad?: string }) {
  if (value == null || value === '') return null
  return (
    <div className="rounded-lg px-2.5 py-1.5 bg-white/60">
      <p className="text-[10px] text-gray-400">{label}</p>
      <p className="text-sm font-semibold text-gray-700">
        {value}{unidad && <span className="text-[11px] font-normal text-gray-400"> {unidad}</span>}
      </p>
    </div>
  )
}

/** Panel de signos: acepta la última toma (VitalSignsRecord) o el snapshot de una receta. */
function SignosPanel({ signo }: { signo: VitalSignsRecord | PrescriptionVitalsSnapshot }) {
  // measured_at puede no existir en un snapshot vacío.
  const measuredAt = 'measured_at' in signo ? signo.measured_at : null
  const pa = signo.systolic != null && signo.diastolic != null ? `${signo.systolic}/${signo.diastolic}` : null
  return (
    <div className="rounded-xl px-3 py-3" style={{ background: 'rgba(201,162,39,0.07)', border: '1px solid rgba(201,162,39,0.2)' }}>
      <div className="flex items-center gap-1.5 mb-2">
        <Activity className="w-3.5 h-3.5" style={{ color: '#B8860B' }} />
        <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/80">
          Signos vitales{measuredAt ? ` · ${formatFechaHora(measuredAt)}` : ''}
        </p>
      </div>
      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))' }}>
        <SignoDato label="Peso" value={signo.weight_kg} unidad="kg" />
        <SignoDato label="Talla" value={signo.height_m} unidad="m" />
        <SignoDato label="IMC" value={signo.imc} />
        <SignoDato label="PA" value={pa} unidad="mmHg" />
        <SignoDato label="FC" value={signo.heart_rate} unidad="lpm" />
        <SignoDato label="FR" value={signo.resp_rate} unidad="rpm" />
        <SignoDato label="Temp" value={signo.temperature_c} unidad="°C" />
        <SignoDato label="SatO₂" value={signo.oxygen_saturation} unidad="%" />
        <SignoDato label="Glucosa" value={signo.glucose} unidad="mg/dL" />
      </div>
    </div>
  )
}

// ── Formulario de nueva receta ─────────────────────────────────────────────────

function NuevaReceta({
  paciente, prefill, onClose,
}: {
  paciente: PatientOut
  prefill: PrescriptionDetail | null
  onClose: () => void
}) {
  const crear = useCreatePrescription(paciente.id)
  const abrirPdf = useOpenPrescriptionPdf()
  const { data: signosData } = useVitalSigns(paciente.id)

  // Renglones: prellenados si "copiar de previa", o uno vacío de arranque.
  const [renglones, setRenglones] = useState<RenglonEdit[]>(() => {
    if (prefill && prefill.items.length > 0) {
      return prefill.items.map(it => ({
        uid: nuevoUid(),
        medication_name: it.medication_name,
        medication_form: it.medication_form,
        medication_concentration: it.medication_concentration,
        medication_presentation: it.medication_presentation,
        indication: it.indication,
        quantity: it.quantity,
        // La trazabilidad al catálogo NO se copia: el texto es la fuente de verdad.
        global_medication_id: null,
        medication_id: null,
      }))
    }
    return [renglonVacio()]
  })
  const [recommendations, setRecommendations] = useState(prefill?.recommendations ?? '')
  const [mostrarSignos, setMostrarSignos] = useState(false)
  // Plantillas de receta (Mi Consultorio) para precargar las recomendaciones.
  const plantillasReceta = useTemplates('recipe').data?.results ?? []
  /** Inserta el cuerpo de una plantilla en las recomendaciones (append si ya hay texto). */
  const usarPlantilla = (body: string) => {
    if (!body) return
    setRecommendations(prev => (prev.trim() ? `${prev.trim()}\n\n${body}` : body))
  }
  const [errores, setErrores] = useState<string[]>([])
  /** Receta recién creada: ofrecer "Ver PDF" antes de cerrar. */
  const [creada, setCreada] = useState<PrescriptionDetail | null>(null)

  const ultimaToma: VitalSignsRecord | null = useMemo(
    () => signosData?.results?.[0] ?? null,
    [signosData],
  )

  const setRenglon = (uid: string, patch: Partial<RenglonEdit>) =>
    setRenglones(rs => rs.map(r => (r.uid === uid ? { ...r, ...patch } : r)))

  const agregarRenglon = () => {
    if (renglones.length >= 20) return
    setRenglones(rs => [...rs, renglonVacio()])
  }
  const quitarRenglon = (uid: string) =>
    setRenglones(rs => (rs.length <= 1 ? rs : rs.filter(r => r.uid !== uid)))

  const guardar = async () => {
    setErrores([])
    const llenos = renglones.filter(r => r.medication_name.trim() || r.indication.trim())
    if (llenos.length === 0) {
      setErrores(['Agrega al menos un medicamento con su indicación.'])
      return
    }
    const sinNombre = llenos.some(r => !r.medication_name.trim())
    const sinIndicacion = llenos.some(r => !r.indication.trim())
    if (sinNombre) { setErrores(['Cada renglón necesita el nombre del medicamento.']); return }
    if (sinIndicacion) { setErrores(['Cada renglón necesita una indicación (dosis, frecuencia y duración).']); return }

    const items: PrescriptionItemInput[] = llenos.map(r => {
      const item: PrescriptionItemInput = {
        medication_name: r.medication_name.trim(),
        indication: r.indication.trim(),
      }
      if (r.medication_presentation.trim()) item.medication_presentation = r.medication_presentation.trim()
      if (r.medication_form.trim()) item.medication_form = r.medication_form.trim()
      if (r.medication_concentration.trim()) item.medication_concentration = r.medication_concentration.trim()
      if (r.quantity.trim()) item.quantity = r.quantity.trim()
      if (r.global_medication_id) item.global_medication_id = r.global_medication_id
      if (r.medication_id) item.medication_id = r.medication_id
      return item
    })

    const input: PrescriptionCreateInput = { items }
    if (recommendations.trim()) input.recommendations = recommendations.trim()
    if (prefill?.appointment_id) input.appointment_id = prefill.appointment_id
    if (prefill?.evolution_note_id) input.evolution_note_id = prefill.evolution_note_id

    try {
      const detalle = await crear.mutateAsync(input)
      setCreada(detalle)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  // Pantalla de éxito: ofrecer ver el PDF.
  if (creada) {
    return (
      <Card title="Receta emitida" icon={CheckCircle2}>
        <div className="space-y-4">
          <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: '#E7F6EE', border: '1px solid rgba(46,125,91,0.25)' }}>
            <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-600" />
            <p className="text-sm text-emerald-800">
              Receta <strong>folio {creada.folio}</strong> emitida correctamente.
            </p>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => abrirPdf.mutate(creada.id)}
              disabled={abrirPdf.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60"
              style={{ background: 'rgba(201,162,39,0.10)' }}
            >
              {abrirPdf.isPending
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Abriendo…</>
                : <><FileText className="w-4 h-4" /> Ver PDF</>}
            </button>
            <button
              type="button" onClick={onClose}
              className="inline-flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold text-white hover:brightness-110"
              style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
            >
              Listo
            </button>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <Card
      title={prefill ? `Nueva receta (copiada del folio ${prefill.folio})` : 'Nueva receta'}
      icon={Plus}
      action={<button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700"><X className="w-4 h-4" /></button>}
    >
      <div className="space-y-4">
        <ErroresAlerta errores={errores} />

        {/* Mostrar signos (última toma como referencia) */}
        <div>
          <button
            type="button"
            onClick={() => setMostrarSignos(v => !v)}
            className="inline-flex items-center gap-2 text-sm font-semibold text-amber-700 hover:text-amber-800"
          >
            <Activity className="w-4 h-4" />
            {mostrarSignos ? 'Ocultar signos' : 'Mostrar signos'}
            <ChevronDown className={`w-4 h-4 transition-transform ${mostrarSignos ? 'rotate-180' : ''}`} />
          </button>
          {mostrarSignos && (
            <div className="mt-2">
              {ultimaToma
                ? <SignosPanel signo={ultimaToma} />
                : <p className="text-xs text-gray-400 italic">Este paciente no tiene tomas de signos registradas.</p>}
              <p className="text-[11px] text-gray-400 mt-1.5">
                Referencia: el sistema congela la última toma en la receta al emitirla.
              </p>
            </div>
          )}
        </div>

        {/* Renglones de tratamiento */}
        <div className="space-y-3">
          {renglones.map((r, idx) => (
            <RenglonTratamiento
              key={r.uid}
              renglon={r}
              indice={idx + 1}
              puedeQuitar={renglones.length > 1}
              onChange={patch => setRenglon(r.uid, patch)}
              onQuitar={() => quitarRenglon(r.uid)}
            />
          ))}
          {renglones.length < 20 && (
            <button
              type="button" onClick={agregarRenglon}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800"
            >
              <Plus className="w-3.5 h-3.5" /> Agregar medicamento
            </button>
          )}
        </div>

        {/* Recomendaciones */}
        <div>
          <div className="flex items-center justify-between gap-2">
            <label className="label">Recomendaciones (opcional)</label>
            {plantillasReceta.length > 0 && (
              <select
                className="text-xs rounded-lg border border-gray-200 bg-white/80 px-2 py-1 text-gray-600 cursor-pointer"
                value=""
                onChange={e => {
                  const t = plantillasReceta.find(p => p.id === e.target.value)
                  if (t) usarPlantilla(t.body)
                }}
                title="Insertar el texto de una plantilla de receta"
              >
                <option value="">Usar plantilla…</option>
                {plantillasReceta.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            )}
          </div>
          <textarea
            className="input resize-none" rows={2}
            placeholder="Indicaciones generales, cuidados, próxima cita…"
            value={recommendations} onChange={e => setRecommendations(e.target.value)}
          />
        </div>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-secondary px-4 py-2">Cancelar</button>
          <button
            type="button" onClick={guardar} disabled={crear.isPending}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
            style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
          >
            {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Emitiendo…</> : <><Pill className="w-4 h-4" /> Emitir receta</>}
          </button>
        </div>
      </div>
    </Card>
  )
}

// ── Un renglón de tratamiento (con buscador de medicamentos) ───────────────────

function RenglonTratamiento({
  renglon, indice, puedeQuitar, onChange, onQuitar,
}: {
  renglon: RenglonEdit
  indice: number
  puedeQuitar: boolean
  onChange: (patch: Partial<RenglonEdit>) => void
  onQuitar: () => void
}) {
  return (
    <div
      className="rounded-2xl p-4"
      style={{ background: 'rgba(255,255,255,0.6)', border: '1px solid rgba(201,162,39,0.18)' }}
    >
      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">Medicamento {indice}</span>
        {puedeQuitar && (
          <button
            type="button" onClick={onQuitar} aria-label="Quitar medicamento"
            className="text-gray-400 hover:text-red-600"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Buscador con autocompletar (texto libre permitido) */}
      <BuscadorMedicamento
        valorNombre={renglon.medication_name}
        onTextoLibre={nombre => onChange({
          medication_name: nombre,
          // Si el usuario escribe a mano, ya no hay vínculo al catálogo.
          global_medication_id: null,
          medication_id: null,
        })}
        onSeleccionar={med => onChange({
          medication_name: med.generic_name,
          medication_form: med.form,
          medication_concentration: med.concentration,
          medication_presentation: med.presentation,
          global_medication_id: med.source === 'global' ? med.id : null,
          medication_id: med.source === 'custom' ? med.id : null,
        })}
      />

      {/* Detalle del medicamento (precargado al elegir; editable) */}
      <div className="grid gap-2.5 mt-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
        <div>
          <label className="label">Forma</label>
          <select
            className="input"
            value={isFormaConocida(renglon.medication_form) ? renglon.medication_form : ''}
            onChange={e => onChange({ medication_form: e.target.value })}
          >
            <option value="">—</option>
            {MEDICATION_FORM_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Concentración</label>
          <input
            className="input" placeholder="Ej. 500 mg"
            value={renglon.medication_concentration}
            onChange={e => onChange({ medication_concentration: e.target.value })}
          />
        </div>
        <div>
          <label className="label">Presentación</label>
          <input
            className="input" placeholder="Ej. Caja con 20"
            value={renglon.medication_presentation}
            onChange={e => onChange({ medication_presentation: e.target.value })}
          />
        </div>
        <div>
          <label className="label">Cantidad (opcional)</label>
          <input
            className="input" placeholder="Ej. 1 caja"
            value={renglon.quantity}
            onChange={e => onChange({ quantity: e.target.value })}
          />
        </div>
      </div>

      <div className="mt-2.5">
        <label className="label">Indicación *</label>
        <textarea
          className="input resize-none" rows={2}
          placeholder="Ej. 1 tableta cada 8 horas por 7 días con alimentos"
          value={renglon.indication}
          onChange={e => onChange({ indication: e.target.value })}
        />
      </div>
    </div>
  )
}

/** true si el valor de forma corresponde a un choice conocido (para el select). */
function isFormaConocida(form: string): form is MedicationFormValue {
  return MEDICATION_FORM_OPTIONS.some(o => o.value === form)
}

// ── Buscador de medicamentos con autocompletar (debounce) ──────────────────────

function BuscadorMedicamento({
  valorNombre, onTextoLibre, onSeleccionar,
}: {
  valorNombre: string
  onTextoLibre: (nombre: string) => void
  onSeleccionar: (med: MedicationSearchResult) => void
}) {
  const [texto, setTexto] = useState(valorNombre)
  const [debounced, setDebounced] = useState('')
  const [abierto, setAbierto] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  // Sincroniza el input si el valor cambia desde fuera (ej. prefill de copiar).
  useEffect(() => { setTexto(valorNombre) }, [valorNombre])

  // Debounce de 300 ms antes de consultar el backend.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(texto.trim()), 300)
    return () => clearTimeout(t)
  }, [texto])

  // Solo busca cuando el desplegable está abierto (foco en el input).
  const { data, isFetching } = useMedicationSearch(debounced, abierto)
  const resultados: MedicationSearchResult[] = data ?? []

  // Cerrar el desplegable al hacer clic fuera.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setAbierto(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const elegir = (med: MedicationSearchResult) => {
    onSeleccionar(med)
    setTexto(med.generic_name)
    setAbierto(false)
  }

  return (
    <div ref={wrapRef} className="relative">
      <label className="label">Medicamento *</label>
      <div className="relative">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input
          className="input pl-9"
          placeholder="Buscar en el catálogo o escribir libremente…"
          value={texto}
          onChange={e => { setTexto(e.target.value); onTextoLibre(e.target.value); setAbierto(true) }}
          onFocus={() => setAbierto(true)}
        />
      </div>

      {abierto && debounced.length >= 1 && (
        <div
          className="absolute z-30 mt-1 w-full max-h-64 overflow-y-auto rounded-xl shadow-lg"
          style={{ background: 'rgba(255,255,255,0.98)', border: '1px solid rgba(201,162,39,0.25)' }}
        >
          {isFetching ? (
            <p className="inline-flex items-center gap-1.5 text-xs text-gray-400 px-3 py-2.5">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Buscando…
            </p>
          ) : resultados.length === 0 ? (
            <p className="text-xs text-gray-400 px-3 py-2.5">
              Sin coincidencias. Puedes usar «{debounced}» como texto libre.
            </p>
          ) : (
            <ul className="py-1">
              {resultados.map(med => (
                <li key={`${med.source}-${med.id}`}>
                  <button
                    type="button"
                    onClick={() => elegir(med)}
                    className="w-full text-left px-3 py-2 hover:bg-amber-50/80 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-800">{med.generic_name}</span>
                      <span
                        className="text-[10px] rounded-full px-1.5 py-0.5"
                        style={med.source === 'global'
                          ? { background: 'rgba(201,162,39,0.15)', color: '#9A7B1E' }
                          : { background: 'rgba(46,125,91,0.12)', color: '#2E7D5B' }}
                      >
                        {med.source === 'global' ? 'Catálogo' : 'Mi clínica'}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500">
                      {[med.commercial_name, med.concentration, formaLabel(med.form), med.presentation]
                        .filter(Boolean).join(' · ') || 'Sin detalle'}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="border-t border-amber-900/10 px-3 py-2 flex items-center gap-1.5">
            <AlertCircle className="w-3 h-3 text-gray-400" />
            <span className="text-[10px] text-gray-400">
              ¿No aparece? Escríbelo libremente; quedará tal cual en la receta.
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
