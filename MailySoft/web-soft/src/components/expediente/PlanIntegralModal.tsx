/**
 * PlanIntegralModal — genera el "Plan Integral de Longevidad y Medicina
 * Regenerativa" que se ENTREGA al paciente (constancia a nivel PACIENTE, no de
 * una consulta).
 *
 * El backend arma un BORRADOR auto-rellenado: encabezado NO editable (clínica +
 * paciente) + 8 secciones de texto (4 auto-rellenadas desde el expediente y 4
 * vacías) + un `esquema` de tratamientos calendarizados (proveniente de un plan
 * de tratamiento opcional) + los planes disponibles. El médico ajusta las
 * secciones, opcionalmente elige un esquema de calendarización y, al "Generar",
 * se guarda la constancia (POST) y se produce el PDF con el membrete de la
 * clínica, que se muestra en el VisorPdf (ver / descargar / imprimir).
 *
 * Permiso (solo UX): el botón que abre este modal solo se muestra a roles
 * clínicos (owner/admin/doctor). El backend es la autoridad y responde 403 a los
 * demás; aquí reflejamos ese 403 con un mensaje claro.
 *
 * Reutiliza infra existente: `usePlanIntegralBorrador`/`useCrearPlanIntegral`
 * (TanStack Query), `getPlanIntegralPdf` (flujo PDF async vía pdfJobBlob),
 * `VisorPdf` y `useLocalDraft` (autoguardado local). Estilo glass, mismo lenguaje
 * visual que el resto del expediente.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Sparkles, X, Loader2, AlertTriangle, FileDown, Info, ListChecks,
  FlaskConical, Plus, Trash2, Users, FileText,
} from 'lucide-react'

import type {
  PlanIntegralEncabezado,
  PlanIntegralEquipoItem,
  PlanIntegralEsquemaItem,
  PlanIntegralGabineteStudy,
  PlanIntegralInput,
  PlanIntegralLabResult,
  PlanIntegralSecciones,
} from '../../types/planIntegral'
import type { Analito } from '../../types/analitos'
import type { PlantillaDocumentoSection } from '../../types/plantillasDocumento'
import { ApiError } from '../../lib/http'
import { usePlanIntegralBorrador, useCrearPlanIntegral } from '../../hooks/planIntegral'
import { useAnalitos } from '../../hooks/analitos'
import { usePlantillasDocumento } from '../../hooks/plantillasDocumento'
import { getPlanIntegralPdf } from '../../api/planIntegral'
import { erroresDe } from '../../lib/apiErrors'
import { formatFechaCorta } from '../../lib/fecha'
import { useAuth } from '../../auth/AuthContext'
import { useLocalDraft } from '../../hooks/useLocalDraft'
import { draftKey } from '../../lib/draftKeys'
import BorradorRecuperadoAviso from '../common/BorradorRecuperadoAviso'
import { useAviso } from '../common/DialogProvider'
import VisorPdf from '../VisorPdf'

const ORO = '#C9A227'
const ORO_OSCURO = '#854F0B'

/** Las 8 secciones editables, EN ORDEN, con su etiqueta clara. */
const SECCIONES: { key: keyof PlanIntegralSecciones; label: string; rows: number }[] = [
  { key: 'alergias', label: 'Alergias', rows: 3 },
  { key: 'antecedentes', label: 'Antecedentes de importancia', rows: 3 },
  { key: 'tratamientos_actuales', label: 'Tratamientos actuales', rows: 3 },
  { key: 'estudios', label: 'Reporte de estudios de laboratorio y gabinete', rows: 4 },
  { key: 'reporte_medico', label: 'Reporte médico', rows: 4 },
  { key: 'condiciones_mejorar', label: 'Principales condiciones a mejorar', rows: 3 },
  { key: 'interconsulta', label: 'Interconsulta de departamentos', rows: 3 },
  { key: 'seguimiento', label: 'Seguimiento y acompañamiento', rows: 3 },
]

const SECCIONES_VACIAS: PlanIntegralSecciones = {
  alergias: '',
  antecedentes: '',
  tratamientos_actuales: '',
  condiciones_mejorar: '',
  estudios: '',
  reporte_medico: '',
  interconsulta: '',
  seguimiento: '',
}

/**
 * Secciones editables que ofrecen "Insertar plantilla ▾". La clave de la sección
 * del modal coincide con la `section` de la plantilla de documento (Fase 2).
 */
const PLANTILLA_POR_SECCION: Partial<Record<keyof PlanIntegralSecciones, PlantillaDocumentoSection>> = {
  reporte_medico: 'reporte_medico',
  seguimiento: 'seguimiento',
  interconsulta: 'interconsulta',
  estudios: 'estudios',
  condiciones_mejorar: 'condiciones_mejorar',
}

/**
 * ¿El resultado cae fuera del rango [ref_low, ref_high]? Mismo criterio que el
 * backend: solo aplica si el resultado es numérico; cada límite se ignora si es
 * null/vacío. Un resultado no numérico NUNCA se marca fuera de rango.
 */
function fueraDeRango(result: string, refLow: string | null, refHigh: string | null): boolean {
  const r = Number(result)
  if (result.trim() === '' || !Number.isFinite(r)) return false
  const low = refLow != null && refLow !== '' ? Number(refLow) : null
  const high = refHigh != null && refHigh !== '' ? Number(refHigh) : null
  if (low != null && Number.isFinite(low) && r < low) return true
  if (high != null && Number.isFinite(high) && r > high) return true
  return false
}

/**
 * Valor autoguardado como borrador local: las 8 secciones + el plan elegido + lo
 * CAPTURADO (laboratorio y gabinete). No se guarda el catálogo ni el equipo (que
 * es solo lectura), solo lo que el médico escribe.
 */
interface PlanIntegralDraftValue {
  secciones: PlanIntegralSecciones
  treatment_plan_id: string
  lab_results: PlanIntegralLabResult[]
  gabinete_studies: PlanIntegralGabineteStudy[]
}

interface PlanIntegralModalProps {
  /** Paciente para el que se genera el Plan Integral. */
  patientId: string
  onClose: () => void
}

export default function PlanIntegralModal({ patientId, onClose }: PlanIntegralModalProps) {
  const aviso = useAviso()
  const { user } = useAuth()

  // Borrador BASE (sin plan): siembra encabezado + 8 secciones + planes + esquema base.
  const {
    data: borradorBase, isLoading, isError, error,
  } = usePlanIntegralBorrador(patientId, undefined, true)

  // Plan de tratamiento elegido para la calendarización ('' = sin calendarización).
  const [treatmentPlanId, setTreatmentPlanId] = useState('')
  // Borrador CON plan: solo se usa para ACTUALIZAR el esquema (no re-siembra secciones).
  const { data: borradorConPlan, isFetching: cargandoEsquema } = usePlanIntegralBorrador(
    patientId, treatmentPlanId || undefined, !!treatmentPlanId,
  )

  const crear = useCrearPlanIntegral(patientId)

  // Texto editable de las 8 secciones (se siembra desde el borrador base al cargar).
  const [secciones, setSecciones] = useState<PlanIntegralSecciones>(SECCIONES_VACIAS)
  // Estudios estructurados capturados (Fase 3): laboratorio + gabinete.
  const [labResults, setLabResults] = useState<PlanIntegralLabResult[]>([])
  const [gabineteStudies, setGabineteStudies] = useState<PlanIntegralGabineteStudy[]>([])
  // Equipo de la clínica (solo lectura; snapshot que trae el borrador — Fase 4).
  const [equipo, setEquipo] = useState<PlanIntegralEquipoItem[]>([])
  // Esquema mostrado (solo lectura). Base al cargar; se reemplaza al elegir un plan.
  const [esquema, setEsquema] = useState<PlanIntegralEsquemaItem[]>([])
  // Id de la constancia recién generada: null = aún no; string = abrir VisorPdf.
  const [pdfPlanId, setPdfPlanId] = useState<string | null>(null)

  // Catálogo de analitos (solo activos) para el picker de laboratorio.
  const analitosQ = useAnalitos({ onlyActive: true })
  const analitos = useMemo<Analito[]>(() => analitosQ.data?.results ?? [], [analitosQ.data])

  // Esquema base (sin plan), para revertir si el usuario deselecciona el plan.
  const esquemaBaseRef = useRef<PlanIntegralEsquemaItem[]>([])

  // ── Borrador local del Plan Integral (por paciente) ──
  const userId = user?.id ?? ''
  const tenantId = user?.active_tenant?.id ?? ''
  const storageKey = draftKey(userId, tenantId, 'plan_integral', patientId)
  const [serverLoaded, setServerLoaded] = useState(false)
  const draftEnabled = !!userId && !!tenantId && serverLoaded && !pdfPlanId
  const draftValue = useMemo<PlanIntegralDraftValue>(
    () => ({
      secciones,
      treatment_plan_id: treatmentPlanId,
      lab_results: labResults,
      gabinete_studies: gabineteStudies,
    }),
    [secciones, treatmentPlanId, labResults, gabineteStudies],
  )
  const { draft, clearDraft } = useLocalDraft<PlanIntegralDraftValue>({
    storageKey,
    value: draftValue,
    enabled: draftEnabled,
  })

  // Fase A: sembrar desde el servidor una sola vez (baseline del borrador).
  const seededRef = useRef(false)
  const draftAppliedRef = useRef(false)
  useEffect(() => {
    if (!borradorBase || seededRef.current) return
    seededRef.current = true
    setSecciones(borradorBase.secciones)
    setEsquema(borradorBase.esquema)
    esquemaBaseRef.current = borradorBase.esquema
    // Estudios estructurados y equipo (Fase 3/4): defensivo por si el backend
    // aún no incluye estos campos en el borrador (contrato en construcción).
    setLabResults(borradorBase.lab_results ?? [])
    setGabineteStudies(borradorBase.gabinete_studies ?? [])
    setEquipo(borradorBase.equipo ?? [])
    setServerLoaded(true)
  }, [borradorBase])

  // Fase B: precargar el borrador local por encima (una sola vez).
  useEffect(() => {
    if (!serverLoaded || draftAppliedRef.current) return
    draftAppliedRef.current = true
    if (draft) {
      setSecciones(draft.data.secciones)
      setTreatmentPlanId(draft.data.treatment_plan_id)
      setLabResults(draft.data.lab_results ?? [])
      setGabineteStudies(draft.data.gabinete_studies ?? [])
    }
  }, [serverLoaded, draft])

  // Al llegar el borrador CON plan, actualiza SOLO el esquema (no las secciones).
  useEffect(() => {
    if (treatmentPlanId && borradorConPlan) setEsquema(borradorConPlan.esquema)
  }, [treatmentPlanId, borradorConPlan])

  const onCambiarPlan = (id: string): void => {
    setTreatmentPlanId(id)
    // Sin plan: revertir al esquema base de inmediato (sin esperar red).
    if (!id) setEsquema(esquemaBaseRef.current)
  }

  const descartarBorrador = (): void => {
    clearDraft()
    if (borradorBase) {
      setSecciones(borradorBase.secciones)
      setTreatmentPlanId('')
      setEsquema(borradorBase.esquema)
      setLabResults(borradorBase.lab_results ?? [])
      setGabineteStudies(borradorBase.gabinete_studies ?? [])
    }
  }

  const setCampo = (key: keyof PlanIntegralSecciones) =>
    (e: React.ChangeEvent<HTMLTextAreaElement>) =>
      setSecciones(s => ({ ...s, [key]: e.target.value }))

  /**
   * Inserta el `body` de una plantilla en la sección indicada. Enfoque claro y
   * no destructivo: si la sección está vacía, reemplaza; si ya tiene texto,
   * añade la plantilla al final separada por una línea en blanco.
   */
  const insertarPlantilla = (key: keyof PlanIntegralSecciones, body: string): void =>
    setSecciones(s => {
      const actual = s[key]
      const nuevo = actual.trim() === '' ? body : `${actual.trimEnd()}\n\n${body}`
      return { ...s, [key]: nuevo }
    })

  const generar = async () => {
    try {
      // Solo se envían filas con contenido útil. El laboratorio requiere nombre
      // Y resultado (el backend rechaza un resultado en blanco), y se mandan solo
      // los campos permitidos (nada de flags internos como el de fuera-de-rango).
      // El equipo NO se manda: el backend lo snapshotea desde la configuración.
      const labLimpio = labResults
        .filter(r => r.name.trim() !== '' && r.result.trim() !== '')
        .map(r => ({
          ...(r.analyte_id ? { analyte_id: r.analyte_id } : {}),
          name: r.name,
          unit: r.unit,
          ref_low: r.ref_low,
          ref_high: r.ref_high,
          result: r.result,
        }))
      const gabineteLimpio = gabineteStudies
        .filter(g => g.name.trim() !== '')
        .map(g => ({ name: g.name, conclusion: g.conclusion }))
      const body: PlanIntegralInput = {
        ...secciones,
        ...(treatmentPlanId ? { treatment_plan_id: treatmentPlanId } : {}),
        ...(labLimpio.length ? { lab_results: labLimpio } : {}),
        ...(gabineteLimpio.length ? { gabinete_studies: gabineteLimpio } : {}),
      }
      const plan = await crear.mutateAsync(body)
      clearDraft() // generado en el servidor: descartar el borrador local
      setPdfPlanId(plan.id)
    } catch (err) {
      await aviso({
        tipo: 'error',
        titulo: 'No se pudo generar el Plan Integral',
        mensaje: erroresDe(err).join(' '),
      })
    }
  }

  const enc = borradorBase?.encabezado
  const planes = borradorBase?.planes_disponibles ?? []

  return createPortal(
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[70] p-2 sm:p-4 flex items-center justify-center"
        style={{ background: 'rgba(40,28,8,0.35)', backdropFilter: 'blur(8px)' }}
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
        role="dialog"
        aria-modal="true"
      >
        <motion.div
          className="relative w-full glass-card rounded-3xl flex flex-col overflow-hidden"
          style={{ maxWidth: '860px', height: '92vh' }}
          initial={{ opacity: 0, y: 24, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 24, scale: 0.97 }}
          transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
          onClick={e => e.stopPropagation()}
        >
          {/* ── Encabezado del modal ── */}
          <div className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-amber-900/10">
            <div className="flex items-center gap-2.5">
              <Sparkles className="w-5 h-5" style={{ color: ORO }} />
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-widest text-amber-700/70">
                  Plan Integral de Longevidad y Medicina Regenerativa
                </p>
                <h3 className="text-base font-bold text-gray-900 leading-tight">
                  {enc?.paciente_nombre ?? 'Paciente'}
                </h3>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Cerrar"
              className="w-9 h-9 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors shadow-sm"
            >
              <X className="w-5 h-5 text-gray-600" />
            </button>
          </div>

          {/* ── Cuerpo ── */}
          <div className="flex-1 min-h-0 overflow-y-auto p-5 sm:p-6">
            {isLoading ? (
              <div className="flex items-center justify-center gap-2 py-16 text-amber-700 text-sm">
                <Loader2 className="w-5 h-5 animate-spin" /> Preparando el Plan Integral…
              </div>
            ) : isError || !borradorBase ? (
              <ErrorBorrador error={error} />
            ) : (
              <div className="space-y-5">
                {draft && draftEnabled && (
                  <BorradorRecuperadoAviso savedAt={draft.savedAt} onDescartar={descartarBorrador} />
                )}
                {/* Nota informativa */}
                <div
                  className="flex items-start gap-2.5 rounded-2xl px-4 py-3"
                  style={{ background: 'rgba(201,162,39,0.10)', border: '1px solid rgba(201,162,39,0.28)' }}
                >
                  <Info className="w-4 h-4 mt-0.5 shrink-0" style={{ color: ORO_OSCURO }} />
                  <p className="text-xs text-amber-900/80 leading-relaxed">
                    Este documento es el Plan Integral que se entrega al paciente. Se guarda una
                    copia como constancia.
                  </p>
                </div>

                {/* Encabezado NO editable: datos del paciente + clínica */}
                {enc && <EncabezadoPlan enc={enc} />}

                {/* Selector de esquema de tratamiento (calendarización) */}
                <EsquemaSelector
                  planes={planes}
                  treatmentPlanId={treatmentPlanId}
                  onCambiar={onCambiarPlan}
                  esquema={esquema}
                  cargando={!!treatmentPlanId && cargandoEsquema}
                />

                {/* Secciones editables */}
                <div className="space-y-4">
                  {SECCIONES.map(({ key, label, rows }) => {
                    const seccionPlantilla = PLANTILLA_POR_SECCION[key]
                    return (
                      <div key={key}>
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <label className="block text-[11px] font-semibold uppercase tracking-wide text-amber-700/80">
                            {label}
                          </label>
                          {seccionPlantilla && (
                            <InsertarPlantilla
                              section={seccionPlantilla}
                              onInsertar={(body) => insertarPlantilla(key, body)}
                            />
                          )}
                        </div>
                        <textarea
                          className="input resize-none w-full"
                          rows={rows}
                          maxLength={8000}
                          value={secciones[key]}
                          onChange={setCampo(key)}
                        />
                        {/* Debajo de "Estudios": captura estructurada de lab + gabinete. */}
                        {key === 'estudios' && (
                          <EstudiosEstructurados
                            analitos={analitos}
                            analitosCargando={analitosQ.isLoading}
                            labResults={labResults}
                            setLabResults={setLabResults}
                            gabineteStudies={gabineteStudies}
                            setGabineteStudies={setGabineteStudies}
                          />
                        )}
                      </div>
                    )
                  })}
                </div>

                {/* Equipo de la clínica (solo lectura; se snapshotea al generar) */}
                <EquipoResumen equipo={equipo} />
              </div>
            )}
          </div>

          {/* ── Pie: acción ── */}
          {borradorBase && !isLoading && (
            <div className="shrink-0 flex items-center justify-end gap-2 px-6 py-4 border-t border-amber-900/10">
              <button type="button" onClick={onClose} className="btn-secondary px-4 py-2">
                Cerrar
              </button>
              <button
                type="button"
                onClick={generar}
                disabled={crear.isPending}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                style={{ background: ORO, boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                {crear.isPending
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> Generando…</>
                  : <><FileDown className="w-4 h-4" /> Generar y descargar PDF</>}
              </button>
            </div>
          )}
        </motion.div>
      </motion.div>

      {/* Visor del PDF de la constancia recién generada */}
      {pdfPlanId && (
        <VisorPdf
          titulo={`Plan Integral · ${enc?.paciente_nombre ?? ''}`.trim()}
          nombreArchivo={`plan-integral-${enc?.fecha ?? ''}.pdf`}
          cargar={() => getPlanIntegralPdf(pdfPlanId)}
          onClose={() => setPdfPlanId(null)}
        />
      )}
    </AnimatePresence>,
    document.body,
  )
}

/** Mensaje de error del borrador (distingue 403 de otros). */
function ErrorBorrador({ error }: { error: unknown }) {
  const esPermiso = error instanceof ApiError && error.status === 403
  return (
    <div
      className="flex items-start gap-3 rounded-2xl px-5 py-4"
      style={{ background: 'rgba(192,57,43,0.08)', border: '1px solid rgba(192,57,43,0.28)' }}
    >
      <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0 text-red-500" />
      <div>
        <p className="text-sm font-semibold text-red-700">
          {esPermiso
            ? 'No tienes permiso para generar el Plan Integral.'
            : 'No se pudo preparar el Plan Integral.'}
        </p>
        <p className="text-xs text-red-600/80 mt-0.5">
          {esPermiso
            ? 'El Plan Integral solo está disponible para roles clínicos.'
            : 'Intenta de nuevo en un momento.'}
        </p>
      </div>
    </div>
  )
}

/** Tarjeta del encabezado NO editable: clínica + datos del paciente. */
function EncabezadoPlan({ enc }: { enc: PlanIntegralEncabezado }) {
  return (
    <div
      className="rounded-2xl p-4 sm:p-5"
      style={{ background: 'rgba(255,255,255,0.72)', border: '1px solid rgba(201,162,39,0.28)' }}
    >
      <p className="text-sm font-bold text-gray-900">{enc.clinica_nombre}</p>
      <div
        className="grid gap-x-4 gap-y-2 mt-3"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}
      >
        <Dato label="Paciente" value={enc.paciente_nombre} />
        <Dato label="Edad" value={enc.paciente_edad != null ? `${enc.paciente_edad} años` : '—'} />
        <Dato label="Fecha" value={enc.fecha ? formatFechaCorta(enc.fecha) : '—'} />
      </div>
    </div>
  )
}

/**
 * Selector del "Esquema de tratamiento" (calendarización) + vista de solo lectura
 * del esquema elegido: por cada tratamiento su nº de sesiones y su descripción
 * clínica (que se edita en el catálogo de servicios).
 */
function EsquemaSelector({
  planes, treatmentPlanId, onCambiar, esquema, cargando,
}: {
  planes: import('../../types/planIntegral').PlanIntegralPlanDisponible[]
  treatmentPlanId: string
  onCambiar: (id: string) => void
  esquema: PlanIntegralEsquemaItem[]
  cargando: boolean
}) {
  return (
    <div
      className="rounded-2xl p-4 sm:p-5 space-y-3"
      style={{ background: 'rgba(14,124,123,0.06)', border: '1px solid rgba(14,124,123,0.22)' }}
    >
      <div className="flex items-center gap-2">
        <ListChecks className="w-4 h-4" style={{ color: '#0E7C7B' }} />
        <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: '#0E7C7B' }}>
          Esquema de tratamiento
        </p>
      </div>

      <div>
        <label className="block text-[11px] font-medium text-gray-500 mb-1">
          Calendarización (opcional)
        </label>
        <select
          className="input w-full"
          value={treatmentPlanId}
          onChange={e => onCambiar(e.target.value)}
        >
          <option value="">Sin calendarización</option>
          {planes.map(p => (
            <option key={p.id} value={p.id}>
              {p.title} · {p.items_count} tratamiento{p.items_count === 1 ? '' : 's'}
            </option>
          ))}
        </select>
      </div>

      {/* Esquema (solo lectura) */}
      {cargando ? (
        <div className="flex items-center gap-2 py-3 text-sm text-teal-700">
          <Loader2 className="w-4 h-4 animate-spin" /> Cargando esquema…
        </div>
      ) : esquema.length === 0 ? (
        <p className="text-xs text-gray-400 py-1">
          {planes.length === 0
            ? 'Este paciente no tiene esquemas de tratamiento disponibles.'
            : 'Elige un esquema para incluir los tratamientos calendarizados.'}
        </p>
      ) : (
        <>
          <ul className="space-y-2">
            {esquema.map((item, i) => (
              <li
                key={`${item.description}-${i}`}
                className="rounded-xl px-3.5 py-2.5"
                style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(14,124,123,0.18)' }}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-gray-800">{item.description}</span>
                  <span className="text-xs font-semibold shrink-0" style={{ color: '#0E7C7B' }}>
                    {item.quantity} sesion{item.quantity === 1 ? '' : 'es'}
                  </span>
                </div>
                {item.clinical_description && (
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed whitespace-pre-line">
                    {item.clinical_description}
                  </p>
                )}
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-gray-400">
            Las descripciones se editan en el catálogo de servicios.
          </p>
        </>
      )}
    </div>
  )
}

/** Fila etiqueta–valor del encabezado. */
function Dato({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-gray-400">{label}</span>
      <span className="text-sm text-gray-800">{value}</span>
    </div>
  )
}

/**
 * Selector "Insertar plantilla ▾" (Fase 2): lista las plantillas de documento de
 * la sección dada (solo activas) y, al elegir una, inserta su `body` en la sección.
 * Si no hay plantillas para esa sección, no se muestra nada.
 */
function InsertarPlantilla({
  section, onInsertar,
}: {
  section: PlantillaDocumentoSection
  onInsertar: (body: string) => void
}) {
  const { data } = usePlantillasDocumento({ section, onlyActive: true })
  const plantillas = data?.results ?? []
  if (plantillas.length === 0) return null
  return (
    <select
      className="text-[11px] font-medium rounded-lg px-2 py-1 border cursor-pointer"
      style={{ color: '#854F0B', borderColor: 'rgba(201,162,39,0.4)', background: 'rgba(255,255,255,0.7)' }}
      value=""
      onChange={(e) => {
        const p = plantillas.find(x => x.id === e.target.value)
        if (p) onInsertar(p.body)
        e.target.value = '' // vuelve al placeholder para poder reinsertar
      }}
      aria-label="Insertar plantilla"
    >
      <option value="">Insertar plantilla ▾</option>
      {plantillas.map(p => (
        <option key={p.id} value={p.id}>{p.name}</option>
      ))}
    </select>
  )
}

/**
 * Captura ESTRUCTURADA de estudios (Fase 3), debajo del texto libre de "Estudios":
 *   - Gabinete: filas {name, conclusion} con agregar/quitar.
 *   - Laboratorio: se agrega una fila eligiendo un analito del catálogo; muestra
 *     nombre · unidad · rango (solo lectura) + input de resultado. La fila se pinta
 *     en ROJO si el resultado es numérico y cae fuera de [ref_low, ref_high].
 */
function EstudiosEstructurados({
  analitos, analitosCargando, labResults, setLabResults, gabineteStudies, setGabineteStudies,
}: {
  analitos: Analito[]
  analitosCargando: boolean
  labResults: PlanIntegralLabResult[]
  setLabResults: React.Dispatch<React.SetStateAction<PlanIntegralLabResult[]>>
  gabineteStudies: PlanIntegralGabineteStudy[]
  setGabineteStudies: React.Dispatch<React.SetStateAction<PlanIntegralGabineteStudy[]>>
}) {
  const agregarLabDeAnalito = (analyteId: string): void => {
    const a = analitos.find(x => x.id === analyteId)
    if (!a) return
    setLabResults(rows => [
      ...rows,
      { analyte_id: a.id, name: a.name, unit: a.unit, ref_low: a.ref_low, ref_high: a.ref_high, result: '' },
    ])
  }
  const setLabResult = (i: number, result: string): void =>
    setLabResults(rows => rows.map((r, j) => (j === i ? { ...r, result } : r)))
  const quitarLab = (i: number): void =>
    setLabResults(rows => rows.filter((_, j) => j !== i))

  const setGabinete = (i: number, patch: Partial<PlanIntegralGabineteStudy>): void =>
    setGabineteStudies(rows => rows.map((g, j) => (j === i ? { ...g, ...patch } : g)))
  const agregarGabinete = (): void =>
    setGabineteStudies(rows => [...rows, { name: '', conclusion: '' }])
  const quitarGabinete = (i: number): void =>
    setGabineteStudies(rows => rows.filter((_, j) => j !== i))

  return (
    <div
      className="mt-3 rounded-2xl p-4 space-y-4"
      style={{ background: 'rgba(14,124,123,0.05)', border: '1px solid rgba(14,124,123,0.2)' }}
    >
      {/* ── Laboratorio ── */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <FlaskConical className="w-4 h-4" style={{ color: '#0E7C7B' }} />
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: '#0E7C7B' }}>
            Laboratorio
          </p>
        </div>

        {labResults.length > 0 && (
          <ul className="space-y-2">
            {labResults.map((r, i) => {
              const fuera = fueraDeRango(r.result, r.ref_low, r.ref_high)
              return (
                <li
                  key={`${r.analyte_id ?? r.name}-${i}`}
                  className="rounded-xl px-3 py-2.5 flex items-center gap-3"
                  style={{
                    background: fuera ? 'rgba(220,38,38,0.08)' : 'rgba(255,255,255,0.7)',
                    border: `1px solid ${fuera ? 'rgba(220,38,38,0.45)' : 'rgba(14,124,123,0.18)'}`,
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <span
                      className="text-sm font-medium"
                      style={{ color: fuera ? '#B91C1C' : '#1f2937' }}
                    >
                      {r.name}
                    </span>
                    <span className="text-[11px] text-gray-400 ml-2">
                      {r.unit ? `${r.unit} · ` : ''}Ref: {rangoRef(r.ref_low, r.ref_high)}
                    </span>
                  </div>
                  <input
                    className="input w-28 text-right"
                    placeholder="Resultado"
                    value={r.result}
                    onChange={(e) => setLabResult(i, e.target.value)}
                    style={fuera ? { borderColor: 'rgba(220,38,38,0.5)', color: '#B91C1C' } : undefined}
                  />
                  <button
                    type="button"
                    onClick={() => quitarLab(i)}
                    className="p-1 rounded hover:bg-red-50 shrink-0"
                    title="Quitar analito"
                    aria-label="Quitar analito"
                  >
                    <Trash2 className="w-4 h-4" style={{ color: '#B91C1C' }} />
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {/* Selector para agregar una fila de laboratorio desde el catálogo */}
        <select
          className="input w-full"
          value=""
          disabled={analitosCargando}
          onChange={(e) => { if (e.target.value) agregarLabDeAnalito(e.target.value); e.target.value = '' }}
          aria-label="Agregar analito"
        >
          <option value="">
            {analitosCargando
              ? 'Cargando analitos…'
              : analitos.length === 0
                ? 'No hay analitos en el catálogo'
                : 'Agregar analito del catálogo…'}
          </option>
          {analitos.map(a => (
            <option key={a.id} value={a.id}>
              {a.name}{a.unit ? ` (${a.unit})` : ''}
            </option>
          ))}
        </select>
        {analitos.length === 0 && !analitosCargando && (
          <p className="text-[11px] text-gray-400">
            El catálogo de analitos se configura en “Mi Consultorio”.
          </p>
        )}
      </div>

      {/* ── Gabinete ── */}
      <div className="space-y-2 pt-1">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4" style={{ color: '#0E7C7B' }} />
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: '#0E7C7B' }}>
            Gabinete
          </p>
        </div>

        {gabineteStudies.map((g, i) => (
          <div
            key={i}
            className="rounded-xl px-3 py-2.5 space-y-2"
            style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(14,124,123,0.18)' }}
          >
            <div className="flex items-center gap-2">
              <input
                className="input flex-1"
                placeholder="Estudio (p. ej. Radiografía de tórax)"
                maxLength={200}
                value={g.name}
                onChange={(e) => setGabinete(i, { name: e.target.value })}
              />
              <button
                type="button"
                onClick={() => quitarGabinete(i)}
                className="p-1 rounded hover:bg-red-50 shrink-0"
                title="Quitar estudio"
                aria-label="Quitar estudio"
              >
                <Trash2 className="w-4 h-4" style={{ color: '#B91C1C' }} />
              </button>
            </div>
            <textarea
              className="input resize-none w-full"
              rows={2}
              maxLength={2000}
              placeholder="Conclusión / hallazgos"
              value={g.conclusion}
              onChange={(e) => setGabinete(i, { conclusion: e.target.value })}
            />
          </div>
        ))}

        <button
          type="button"
          onClick={agregarGabinete}
          className="inline-flex items-center gap-1.5 text-sm font-medium px-3 py-2 rounded-xl transition-colors hover:bg-black/5"
          style={{ color: '#0E7C7B', border: '1px dashed rgba(14,124,123,0.4)' }}
        >
          <Plus className="w-4 h-4" /> Agregar estudio de gabinete
        </button>
      </div>
    </div>
  )
}

/** Quita ceros de relleno de un decimal ("70.0000" -> "70"). */
function fmtRef(v: string | null): string | null {
  if (v == null || v.trim() === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? String(n) : v
}

/** Rango de referencia legible para las filas de laboratorio del modal. */
function rangoRef(refLow: string | null, refHigh: string | null): string {
  const low = fmtRef(refLow)
  const high = fmtRef(refHigh)
  if (low != null && high != null) return `${low}–${high}`
  if (low != null) return `≥ ${low}`
  if (high != null) return `≤ ${high}`
  return 'sin rango'
}

/**
 * Resumen (solo lectura) del equipo de la clínica en el Plan Integral (Fase 4).
 * No se edita aquí: se configura en los datos de la clínica y el backend lo
 * snapshotea al generar la constancia.
 */
function EquipoResumen({ equipo }: { equipo: PlanIntegralEquipoItem[] }) {
  if (equipo.length === 0) return null
  return (
    <div
      className="rounded-2xl p-4 sm:p-5 space-y-2"
      style={{ background: 'rgba(255,255,255,0.72)', border: '1px solid rgba(201,162,39,0.28)' }}
    >
      <div className="flex items-center gap-2">
        <Users className="w-4 h-4" style={{ color: ORO_OSCURO }} />
        <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/80">
          Equipo de la clínica
        </p>
      </div>
      <ul className="space-y-1">
        {equipo.map((m, i) => (
          <li key={`${m.departamento}-${m.nombre}-${i}`} className="text-sm text-gray-700">
            <span className="font-semibold">{m.departamento}</span>
            {' — '}
            {m.nombre}
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-gray-400">Se configura en los datos de la clínica.</p>
    </div>
  )
}
