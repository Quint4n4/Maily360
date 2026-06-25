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
  Send, AlertCircle, AlertTriangle, ShieldAlert, CheckCircle2, ChevronDown,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type {
  ControlledGroup,
  ItemKind,
  MedicationFormValue,
  MedicationSearchResult,
  PrescriptionCreateInput,
  PrescriptionDetail,
  PrescriptionItemInput,
  PrescriptionListItem,
  PrescriptionVitalsInput,
  RouteOfAdministration,
} from '../../types/recetas'
import { ITEM_KIND_OPTIONS, ROUTE_OPTIONS, controlledGroupLabel } from '../../types/recetas'
import type { VitalSignsRecord } from '../../types/expediente'
import type { VitalKey } from '../../lib/validacion'
import { errorDeSignoVital } from '../../lib/validacion'
import {
  useCancelPrescription,
  useCreatePrescription,
  useMedicationSearch,
  useOpenPrescriptionPdfWithFormat,
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
  /** Tipo de ítem (COFEPRIS F2): medicamento / suero / terapia. */
  kind: ItemKind
  medication_name: string
  medication_form: string
  medication_concentration: string
  medication_presentation: string
  /** Renglón estructurado COFEPRIS F2. */
  dose: string
  frequency: string
  route: RouteOfAdministration | ''
  duration: string
  /** Nota/observación adicional (opcional). */
  indication: string
  quantity: string
  global_medication_id: string | null
  medication_id: string | null
  /**
   * Grupo COFEPRIS del medicamento elegido del catálogo (F6). Solo para UX:
   * dispara el aviso del renglón y el folio requerido a nivel receta. NO se envía
   * en el item — el backend lo resuelve desde el catálogo vía la trazabilidad
   * (global_medication_id / medication_id) y rechazaría la clave si se enviara.
   */
  controlled_group: ControlledGroup
}

let uidSeq = 0
const nuevoUid = (): string => `r${++uidSeq}`

const renglonVacio = (): RenglonEdit => ({
  uid: nuevoUid(),
  kind: 'medicamento',
  medication_name: '',
  medication_form: '',
  medication_concentration: '',
  medication_presentation: '',
  dose: '',
  frequency: '',
  route: '',
  duration: '',
  indication: '',
  quantity: '',
  global_medication_id: null,
  medication_id: null,
  controlled_group: 'none',
})

// ── Signos vitales editables en la receta (Tarea A) ────────────────────────────

/** Las 9 claves de signos vitales capturables en la receta (orden de UI). */
const VITAL_KEYS: VitalKey[] = [
  'weight_kg', 'height_m', 'heart_rate', 'resp_rate', 'systolic',
  'diastolic', 'temperature_c', 'oxygen_saturation', 'glucose',
]

/** Estado del formulario de signos: cada clave como string del input. */
type SignosForm = Record<VitalKey, string>

const SIGNOS_VACIO: SignosForm = {
  weight_kg: '', height_m: '', heart_rate: '', resp_rate: '', systolic: '',
  diastolic: '', temperature_c: '', oxygen_saturation: '', glucose: '',
}

/** Metadatos de cada campo de signo (etiqueta corta y unidad) para los inputs. */
const VITAL_META: Record<VitalKey, { label: string; unidad: string; placeholder: string }> = {
  weight_kg: { label: 'Peso', unidad: 'kg', placeholder: 'Ej. 70.5' },
  height_m: { label: 'Talla', unidad: 'm', placeholder: 'Ej. 1.65' },
  heart_rate: { label: 'FC', unidad: 'lpm', placeholder: 'Ej. 72' },
  resp_rate: { label: 'FR', unidad: 'rpm', placeholder: 'Ej. 16' },
  systolic: { label: 'TA sistólica', unidad: 'mmHg', placeholder: 'Ej. 120' },
  diastolic: { label: 'TA diastólica', unidad: 'mmHg', placeholder: 'Ej. 80' },
  temperature_c: { label: 'Temperatura', unidad: '°C', placeholder: 'Ej. 36.5' },
  oxygen_saturation: { label: 'SpO₂', unidad: '%', placeholder: 'Ej. 98' },
  glucose: { label: 'Glucosa', unidad: 'mg/dL', placeholder: 'Ej. 90' },
}

/** Prellena el formulario de signos con la última toma (string vacío si falta). */
function signosDesdeToma(toma: VitalSignsRecord | null): SignosForm {
  if (!toma) return { ...SIGNOS_VACIO }
  const val = (v: string | number | null): string => (v == null ? '' : String(v))
  return {
    weight_kg: val(toma.weight_kg),
    height_m: val(toma.height_m),
    heart_rate: val(toma.heart_rate),
    resp_rate: val(toma.resp_rate),
    systolic: val(toma.systolic),
    diastolic: val(toma.diastolic),
    temperature_c: val(toma.temperature_c),
    oxygen_saturation: val(toma.oxygen_saturation),
    glucose: val(toma.glucose),
  }
}

/** IMC en vivo (peso / talla²) a 1 decimal, o null si falta/inválido peso o talla. */
function calcularIMC(peso: string, talla: string): number | null {
  const p = Number(peso.trim())
  const t = Number(talla.trim())
  if (!peso.trim() || !talla.trim() || Number.isNaN(p) || Number.isNaN(t) || t <= 0) return null
  const imc = p / (t * t)
  if (!Number.isFinite(imc)) return null
  return Math.round(imc * 10) / 10
}

/** Normaliza un valor de vía desconocido (compat. recetas viejas) a '' o válido. */
function normalizarVia(route: string): RouteOfAdministration | '' {
  return ROUTE_OPTIONS.some((o) => o.value === route) ? (route as RouteOfAdministration) : ''
}

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
  const abrirPdf = useOpenPrescriptionPdfWithFormat()
  const anular = useCancelPrescription(patientId)
  const aviso = useAviso()
  const [confirmAnular, setConfirmAnular] = useState(false)
  const [copiando, setCopiando] = useState(false)
  const [error, setError] = useState('')

  const anulada = receta.status === 'cancelled'

  /** Abre el PDF en el layout indicado: 'compact' = Farmacia, 'digital' = Paciente. */
  const verPdf = async (formato: 'compact' | 'digital') => {
    setError('')
    try {
      await abrirPdf.mutateAsync({ prescriptionId: receta.id, formato })
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
          {receta.doctor.cedulas_validadas?.length ? (
            <span
              className="text-xs text-gray-400"
              title={receta.doctor.cedulas_validadas.map((c) => `Céd. ${c}`).join(' · ')}
            >
              Céd. {receta.doctor.cedulas_validadas[0]}
              {receta.doctor.cedulas_validadas.length > 1 &&
                ` +${receta.doctor.cedulas_validadas.length - 1}`}
            </span>
          ) : receta.doctor.cedula_profesional ? (
            <span className="text-xs text-gray-400">Céd. {receta.doctor.cedula_profesional}</span>
          ) : null}
          <span className="text-xs rounded-full px-2 py-0.5" style={{ background: 'rgba(201,162,39,0.12)', color: '#9A7B1E' }}>
            {receta.items_count} {receta.items_count === 1 ? 'medicamento' : 'medicamentos'}
          </span>
        </div>

        {receta.diagnosis && (
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">Diagnóstico</p>
            <p className="text-sm text-gray-700 whitespace-pre-wrap">{receta.diagnosis}</p>
          </div>
        )}

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
            type="button" onClick={() => verPdf('compact')} disabled={abrirPdf.isPending}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60 rounded-lg px-3 py-1.5"
            style={{ background: 'rgba(201,162,39,0.10)' }}
            title="Receta para llevar a la farmacia (media carta)"
          >
            <FileText className="w-3.5 h-3.5" /> Farmacia
          </button>
          <button
            type="button" onClick={() => verPdf('digital')} disabled={abrirPdf.isPending}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60 rounded-lg px-3 py-1.5"
            style={{ background: 'rgba(201,162,39,0.10)' }}
            title="Receta del paciente (hoja completa, con recomendaciones)"
          >
            <FileText className="w-3.5 h-3.5" /> Paciente
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

// ── Editor de signos vitales en la receta (Tarea A) ────────────────────────────

/** Un input numérico de signo vital con validación de rango en vivo. */
function SignoInput({
  vitalKey, value, onChange,
}: {
  vitalKey: VitalKey
  value: string
  onChange: (valor: string) => void
}) {
  const meta = VITAL_META[vitalKey]
  const error = errorDeSignoVital(vitalKey, value)
  return (
    <div>
      <label className="label">
        {meta.label} <span className="text-gray-400 font-normal">({meta.unidad})</span>
      </label>
      <input
        className={`input${error ? ' input-error' : ''}`}
        type="number" step="any" inputMode="decimal"
        placeholder={meta.placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
      />
      {error && <p className="text-[11px] text-red-600 mt-0.5">{error}</p>}
    </div>
  )
}

/**
 * Sección de signos vitales editable de la receta. Prellena con la última toma
 * de Enfermería (editable por el médico) y muestra el IMC calculado en vivo.
 * Todos los campos son opcionales; al guardar solo se envían los que tengan valor.
 */
function SignosVitalesEditor({
  signos, onChange, imc, prellenadoDesde,
}: {
  signos: SignosForm
  onChange: (k: VitalKey, valor: string) => void
  imc: number | null
  prellenadoDesde: VitalSignsRecord | null
}) {
  return (
    <div
      className="mt-2 rounded-xl px-3 py-3"
      style={{ background: 'rgba(201,162,39,0.07)', border: '1px solid rgba(201,162,39,0.2)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2.5">
        <p className="text-[11px] text-gray-500">
          {prellenadoDesde
            ? `Prellenado con la última toma · ${formatFechaHora(prellenadoDesde.measured_at)}. Edita o completa.`
            : 'Sin tomas previas: captura los signos directamente (todos opcionales).'}
        </p>
        {imc != null && (
          <span
            className="text-xs font-semibold rounded-lg px-2.5 py-1"
            style={{ background: 'rgba(201,162,39,0.15)', color: '#9A7B1E' }}
          >
            IMC {imc}
          </span>
        )}
      </div>
      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))' }}>
        {VITAL_KEYS.map(k => (
          <SignoInput key={k} vitalKey={k} value={signos[k]} onChange={v => onChange(k, v)} />
        ))}
      </div>
      <p className="text-[11px] text-gray-400 mt-2">
        Todos los signos son opcionales. Si dejas todo vacío, la receta congela la
        última toma de Enfermería. La edad no se captura aquí: se toma de la fecha de
        nacimiento del paciente.
      </p>
    </div>
  )
}

// ── Formulario de nueva receta ─────────────────────────────────────────────────

/**
 * Formulario de nueva receta. Exportado para reusarse fuera del acordeón (la
 * tarjeta "Visita de hoy" del expediente rediseñado lo monta directo, sin pasar
 * por RecetasTab). Mismo flujo de guardado (useCreatePrescription) y PDF.
 */
export function NuevaReceta({
  paciente, prefill, onClose,
}: {
  paciente: PatientOut
  prefill: PrescriptionDetail | null
  onClose: () => void
}) {
  const crear = useCreatePrescription(paciente.id)
  const abrirPdf = useOpenPrescriptionPdfWithFormat()
  const { data: signosData } = useVitalSigns(paciente.id)

  // Renglones: prellenados si "copiar de previa", o uno vacío de arranque.
  const [renglones, setRenglones] = useState<RenglonEdit[]>(() => {
    if (prefill && prefill.items.length > 0) {
      return prefill.items.map(it => ({
        uid: nuevoUid(),
        kind: it.kind,
        medication_name: it.medication_name,
        medication_form: it.medication_form,
        medication_concentration: it.medication_concentration,
        medication_presentation: it.medication_presentation,
        dose: it.dose,
        frequency: it.frequency,
        route: normalizarVia(it.route),
        duration: it.duration,
        indication: it.indication,
        quantity: it.quantity,
        // La trazabilidad al catálogo NO se copia: el texto es la fuente de verdad.
        // Sin trazabilidad el grupo controlado se reevalúa al volver a elegir del
        // catálogo; al copiar arranca en 'none' (el médico re-selecciona si aplica).
        global_medication_id: null,
        medication_id: null,
        controlled_group: 'none',
      }))
    }
    return [renglonVacio()]
  })
  const [diagnosis, setDiagnosis] = useState(prefill?.diagnosis ?? '')
  const [recommendations, setRecommendations] = useState(prefill?.recommendations ?? '')
  const [mostrarSignos, setMostrarSignos] = useState(false)
  // Tarea A — signos vitales editables (prellenados con la última toma).
  const [signos, setSignos] = useState<SignosForm>({ ...SIGNOS_VACIO })
  const [signosPrellenados, setSignosPrellenados] = useState(false)
  // Tarea B — folio del recetario especial COFEPRIS (requerido si hay controlados).
  const [controlledFolio, setControlledFolio] = useState('')
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

  // Prellena los signos con la última toma UNA sola vez (cuando llega del backend),
  // sin pisar lo que el médico ya haya escrito.
  useEffect(() => {
    if (signosPrellenados || !ultimaToma) return
    setSignos(signosDesdeToma(ultimaToma))
    setSignosPrellenados(true)
  }, [ultimaToma, signosPrellenados])

  const setSigno = (k: VitalKey, valor: string) =>
    setSignos(s => ({ ...s, [k]: valor }))

  // IMC en vivo (referencia; el backend también lo deriva).
  const imcVivo = useMemo(
    () => calcularIMC(signos.weight_kg, signos.height_m),
    [signos.weight_kg, signos.height_m],
  )

  // Tarea B — ¿la receta tiene algún renglón con medicamento controlado?
  const gruposControlados = useMemo(
    () => renglones.filter(r => r.controlled_group !== 'none').map(r => r.controlled_group),
    [renglones],
  )
  const hayControlado = gruposControlados.length > 0

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
    // Un renglón cuenta como "lleno" si tiene nombre o algún dato del tratamiento.
    const llenos = renglones.filter(
      r => r.medication_name.trim() || r.dose.trim() || r.frequency.trim()
        || r.duration.trim() || r.indication.trim(),
    )
    if (llenos.length === 0) {
      setErrores(['Agrega al menos un renglón de tratamiento con su nombre.'])
      return
    }
    if (llenos.some(r => !r.medication_name.trim())) {
      setErrores(['Cada renglón necesita el nombre del medicamento, suero o terapia.'])
      return
    }
    // COFEPRIS F2: para kind=medicamento, dosis/frecuencia/vía/duración son obligatorios (UX).
    const errFaltantes: string[] = []
    llenos.forEach((r, i) => {
      if (r.kind !== 'medicamento') return
      const faltan: string[] = []
      if (!r.dose.trim()) faltan.push('dosis')
      if (!r.frequency.trim()) faltan.push('frecuencia')
      if (!r.route) faltan.push('vía')
      if (!r.duration.trim()) faltan.push('duración')
      if (faltan.length > 0) {
        errFaltantes.push(`Medicamento ${i + 1}: falta ${faltan.join(', ')} (obligatorio por COFEPRIS).`)
      }
    })
    if (errFaltantes.length > 0) { setErrores(errFaltantes); return }

    // Tarea A — validar rangos de signos en vivo (el backend es la autoridad).
    const errSignos: string[] = []
    for (const k of VITAL_KEYS) {
      const msg = errorDeSignoVital(k, signos[k])
      if (msg) errSignos.push(`${VITAL_META[k].label}: ${msg}.`)
    }
    if (errSignos.length > 0) { setErrores(errSignos); return }

    // Tarea B — folio del recetario especial obligatorio si hay controlados.
    if (hayControlado && !controlledFolio.trim()) {
      setErrores([
        'La receta contiene medicamentos controlados (COFEPRIS). El folio del '
        + 'recetario especial es obligatorio.',
      ])
      return
    }

    const items: PrescriptionItemInput[] = llenos.map(r => {
      const item: PrescriptionItemInput = {
        kind: r.kind,
        medication_name: r.medication_name.trim(),
      }
      if (r.dose.trim()) item.dose = r.dose.trim()
      if (r.frequency.trim()) item.frequency = r.frequency.trim()
      if (r.route) item.route = r.route
      if (r.duration.trim()) item.duration = r.duration.trim()
      if (r.indication.trim()) item.indication = r.indication.trim()
      if (r.medication_presentation.trim()) item.medication_presentation = r.medication_presentation.trim()
      if (r.medication_form.trim()) item.medication_form = r.medication_form.trim()
      if (r.medication_concentration.trim()) item.medication_concentration = r.medication_concentration.trim()
      if (r.quantity.trim()) item.quantity = r.quantity.trim()
      if (r.global_medication_id) item.global_medication_id = r.global_medication_id
      if (r.medication_id) item.medication_id = r.medication_id
      return item
    })

    const input: PrescriptionCreateInput = { items }
    if (diagnosis.trim()) input.diagnosis = diagnosis.trim()
    if (recommendations.trim()) input.recommendations = recommendations.trim()
    if (prefill?.appointment_id) input.appointment_id = prefill.appointment_id
    if (prefill?.evolution_note_id) input.evolution_note_id = prefill.evolution_note_id

    // Tarea A — enviar `vitals` solo con las claves que tengan valor numérico.
    // Si ninguna tiene valor, NO se envía `vitals` (el backend usa la última toma).
    const vitals: PrescriptionVitalsInput = {}
    for (const k of VITAL_KEYS) {
      const v = signos[k].trim()
      if (v !== '') vitals[k] = Number(v)
    }
    if (Object.keys(vitals).length > 0) input.vitals = vitals

    // Tarea B — folio del recetario especial (solo si hay controlados).
    if (hayControlado && controlledFolio.trim()) input.controlled_folio = controlledFolio.trim()

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
          <p className="text-xs text-gray-500">
            Se generan dos versiones: la de <strong>farmacia</strong> (para comprar los medicamentos)
            y la del <strong>paciente</strong> (hoja completa con recomendaciones, para enviar o imprimir).
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => abrirPdf.mutate({ prescriptionId: creada.id, formato: 'compact' })}
              disabled={abrirPdf.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60"
              style={{ background: 'rgba(201,162,39,0.10)' }}
            >
              <FileText className="w-4 h-4" /> Farmacia
            </button>
            <button
              type="button"
              onClick={() => abrirPdf.mutate({ prescriptionId: creada.id, formato: 'digital' })}
              disabled={abrirPdf.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60"
              style={{ background: 'rgba(201,162,39,0.10)' }}
            >
              <FileText className="w-4 h-4" /> Paciente (digital)
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

        {/* Signos vitales EDITABLES (Tarea A): prellenados con la última toma. */}
        <div>
          <button
            type="button"
            onClick={() => setMostrarSignos(v => !v)}
            className="inline-flex items-center gap-2 text-sm font-semibold text-amber-700 hover:text-amber-800"
          >
            <Activity className="w-4 h-4" />
            {mostrarSignos ? 'Ocultar signos vitales' : 'Capturar signos vitales'}
            <ChevronDown className={`w-4 h-4 transition-transform ${mostrarSignos ? 'rotate-180' : ''}`} />
          </button>
          {mostrarSignos && (
            <SignosVitalesEditor
              signos={signos}
              onChange={setSigno}
              imc={imcVivo}
              prellenadoDesde={ultimaToma}
            />
          )}
        </div>

        {/* Diagnóstico (recomendado, COFEPRIS) */}
        <div>
          <label className="label" htmlFor="receta-diagnostico">Diagnóstico</label>
          <textarea
            id="receta-diagnostico"
            className="input resize-none" rows={2}
            placeholder="Ej. Faringoamigdalitis bacteriana aguda"
            value={diagnosis} onChange={e => setDiagnosis(e.target.value)}
          />
          <p className="text-[11px] text-gray-400 mt-1">
            Recomendado por COFEPRIS: una receta sin diagnóstico se considera incompleta.
          </p>
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

        {/* Folio del recetario especial COFEPRIS — solo si hay controlados (Tarea B) */}
        {hayControlado && (
          <div
            className="rounded-2xl p-4"
            style={{ background: 'rgba(190,40,40,0.06)', border: '1px solid rgba(190,40,40,0.25)' }}
          >
            <div className="flex items-center gap-2 mb-1.5">
              <ShieldAlert className="w-4 h-4 text-red-600" />
              <span className="text-[11px] font-semibold uppercase tracking-wide text-red-700/80">
                Receta con medicamentos controlados
              </span>
            </div>
            <label className="label" htmlFor="receta-folio-controlado">
              Folio del recetario especial (COFEPRIS) *
            </label>
            <input
              id="receta-folio-controlado"
              className={`input${hayControlado && !controlledFolio.trim() ? ' input-error' : ''}`}
              placeholder="Folio del recetario especial emitido por COFEPRIS"
              value={controlledFolio}
              onChange={e => setControlledFolio(e.target.value)}
            />
            <p className="text-[11px] text-red-700/70 mt-1">
              Obligatorio: la receta incluye medicamentos del grupo{' '}
              {Array.from(new Set(gruposControlados)).join(', ')}. Sin este folio no puede emitirse.
            </p>
          </div>
        )}

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
  // COFEPRIS: el renglón estructurado es obligatorio solo para medicamentos.
  const esMedicamento = renglon.kind === 'medicamento'
  const kindLabel = ITEM_KIND_OPTIONS.find(o => o.value === renglon.kind)?.label ?? 'Medicamento'
  // Resalta en rojo los obligatorios vacíos (solo para medicamento).
  const reqVacio = (valor: string): boolean => esMedicamento && !valor.trim()
  const viaVacia = esMedicamento && !renglon.route

  return (
    <div
      className="rounded-2xl p-4"
      style={{ background: 'rgba(255,255,255,0.6)', border: '1px solid rgba(201,162,39,0.18)' }}
    >
      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">
          {kindLabel} {indice}
        </span>
        {puedeQuitar && (
          <button
            type="button" onClick={onQuitar} aria-label="Quitar renglón"
            className="text-gray-400 hover:text-red-600"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Tipo de ítem (medicamento / suero / terapia) */}
      <div className="mb-2.5">
        <label className="label">Tipo</label>
        <select
          className="input"
          value={renglon.kind}
          onChange={e => onChange({ kind: e.target.value as ItemKind })}
        >
          {ITEM_KIND_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {/* Buscador con autocompletar (texto libre permitido), filtrado por tipo */}
      <BuscadorMedicamento
        kind={renglon.kind}
        valorNombre={renglon.medication_name}
        onTextoLibre={nombre => onChange({
          medication_name: nombre,
          // Si el usuario escribe a mano, ya no hay vínculo al catálogo: se pierde
          // la trazabilidad y el grupo controlado vuelve a 'none' (texto libre).
          global_medication_id: null,
          medication_id: null,
          controlled_group: 'none',
        })}
        onSeleccionar={med => onChange({
          medication_name: med.generic_name,
          medication_form: med.form,
          medication_concentration: med.concentration,
          medication_presentation: med.presentation,
          global_medication_id: med.source === 'global' ? med.id : null,
          medication_id: med.source === 'custom' ? med.id : null,
          // F6: el grupo controlado del catálogo se guarda solo para UX (aviso +
          // folio). El backend lo re-resuelve desde la FK; no lo enviamos en el item.
          controlled_group: med.controlled_group,
        })}
      />

      {/* Aviso de medicamento controlado en el renglón (Tarea B) */}
      {renglon.controlled_group !== 'none' && (
        <div
          className="mt-2 flex items-center gap-2 rounded-lg px-3 py-2"
          style={{ background: 'rgba(190,40,40,0.08)', border: '1px solid rgba(190,40,40,0.22)' }}
        >
          <AlertTriangle className="w-4 h-4 shrink-0 text-red-600" />
          <span className="text-xs font-semibold text-red-700">
            Medicamento controlado — {controlledGroupLabel(renglon.controlled_group)}
          </span>
        </div>
      )}

      {/* Renglón estructurado COFEPRIS: dosis / frecuencia / vía / duración */}
      <div className="grid gap-2.5 mt-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
        <div>
          <label className="label">Dosis{esMedicamento && ' *'}</label>
          <input
            className={`input${reqVacio(renglon.dose) ? ' input-error' : ''}`}
            placeholder="Ej. 1 tableta"
            value={renglon.dose}
            onChange={e => onChange({ dose: e.target.value })}
          />
        </div>
        <div>
          <label className="label">Frecuencia{esMedicamento && ' *'}</label>
          <input
            className={`input${reqVacio(renglon.frequency) ? ' input-error' : ''}`}
            placeholder="Ej. cada 8 horas"
            value={renglon.frequency}
            onChange={e => onChange({ frequency: e.target.value })}
          />
        </div>
        <div>
          <label className="label">Vía{esMedicamento && ' *'}</label>
          <select
            className={`input${viaVacia ? ' input-error' : ''}`}
            value={renglon.route}
            onChange={e => onChange({ route: e.target.value as RouteOfAdministration | '' })}
          >
            <option value="">—</option>
            {ROUTE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Duración{esMedicamento && ' *'}</label>
          <input
            className={`input${reqVacio(renglon.duration) ? ' input-error' : ''}`}
            placeholder="Ej. por 7 días"
            value={renglon.duration}
            onChange={e => onChange({ duration: e.target.value })}
          />
        </div>
      </div>

      {esMedicamento && (
        <p className="text-[11px] text-gray-400 mt-1.5">
          COFEPRIS exige dosis, frecuencia, vía y duración sin abreviaturas para medicamentos.
        </p>
      )}

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
        <label className="label">Nota / observación (opcional)</label>
        <textarea
          className="input resize-none" rows={2}
          placeholder="Ej. tomar con alimentos; suspender si hay reacción"
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
  kind, valorNombre, onTextoLibre, onSeleccionar,
}: {
  /** Filtra el catálogo por tipo de ítem (COFEPRIS F2). */
  kind: ItemKind
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

  // Solo busca cuando el desplegable está abierto (foco en el input). Filtra por kind.
  const { data, isFetching } = useMedicationSearch(debounced, abierto, kind)
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

  const nombreLabel = kind === 'suero' ? 'Suero *' : kind === 'terapia' ? 'Terapia *' : 'Medicamento *'

  return (
    <div ref={wrapRef} className="relative">
      <label className="label">{nombreLabel}</label>
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
