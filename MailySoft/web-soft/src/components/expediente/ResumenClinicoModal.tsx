/**
 * ResumenClinicoModal — genera el "Resumen Clínico" que se ENTREGA al paciente.
 *
 * Desde una nota de evolución (consulta), el médico abre este modal: el backend
 * arma un BORRADOR auto-rellenado (encabezado NO editable con los datos de la
 * clínica, el paciente y los signos vitales de la visita + 6 secciones de texto
 * editables). El médico ajusta las secciones y, al "Generar", se guarda una
 * constancia (POST) y se produce el PDF con el membrete de la clínica, que se
 * muestra en el VisorPdf (ver / descargar / imprimir).
 *
 * Permiso (solo UX): el botón que abre este modal solo se muestra a roles
 * clínicos (owner/admin/doctor). El backend es la autoridad y responde 403 a
 * los demás; aquí reflejamos ese 403 con un mensaje claro.
 *
 * Reutiliza infra existente: `useResumenBorrador`/`useCrearResumen` (TanStack
 * Query), `getResumenClinicoPdf` (flujo PDF async unificado vía pdfJobBlob) y el
 * componente `VisorPdf`. Estilo glass, mismo lenguaje visual que el expediente.
 */

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ClipboardList, X, Loader2, AlertTriangle, FileDown, Activity, Info,
} from 'lucide-react'

import type { ResumenSecciones } from '../../types/expediente'
import { ApiError } from '../../lib/http'
import { useResumenBorrador, useCrearResumen } from '../../hooks/expediente'
import { getResumenClinicoPdf } from '../../api/expediente'
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

/** Las 6 secciones editables, en orden, con su etiqueta clara. */
const SECCIONES: { key: keyof ResumenSecciones; label: string; rows: number }[] = [
  { key: 'identificacion', label: 'Ficha de identificación', rows: 3 },
  { key: 'antecedentes', label: 'Antecedentes', rows: 3 },
  { key: 'padecimiento_actual', label: 'Padecimiento actual', rows: 3 },
  { key: 'exploracion_fisica', label: 'Exploración física', rows: 3 },
  { key: 'diagnostico_manejo', label: 'Diagnóstico y manejo', rows: 4 },
  { key: 'indicaciones', label: 'Indicaciones', rows: 4 },
]

const SECCIONES_VACIAS: ResumenSecciones = {
  identificacion: '',
  antecedentes: '',
  padecimiento_actual: '',
  exploracion_fisica: '',
  diagnostico_manejo: '',
  indicaciones: '',
}

/** 'M' | 'F' | 'X' | '' → etiqueta legible. */
function sexoLabel(sexo: 'M' | 'F' | 'X' | ''): string {
  if (sexo === 'M') return 'Masculino'
  if (sexo === 'F') return 'Femenino'
  if (sexo === 'X') return 'Otro'
  return '—'
}

interface ResumenClinicoModalProps {
  /** Evolución (consulta) de la que se genera el resumen. */
  evolutionId: string
  /** Paciente dueño de la evolución (para invalidar la lista de constancias). */
  patientId?: string
  onClose: () => void
}

export default function ResumenClinicoModal({
  evolutionId, patientId, onClose,
}: ResumenClinicoModalProps) {
  const aviso = useAviso()
  const { user } = useAuth()
  const { data: borrador, isLoading, isError, error } = useResumenBorrador(evolutionId, true)
  const crear = useCrearResumen(evolutionId, patientId)

  // Texto editable de las 6 secciones. Se siembra desde el borrador al cargar.
  const [secciones, setSecciones] = useState<ResumenSecciones>(SECCIONES_VACIAS)
  // Id de la constancia recién generada: null = aún no; string = abrir VisorPdf.
  const [pdfSummaryId, setPdfSummaryId] = useState<string | null>(null)

  // ── Borrador local del resumen (por evolución) ──
  const userId = user?.id ?? ''
  const tenantId = user?.active_tenant?.id ?? ''
  const storageKey = draftKey(userId, tenantId, 'resumen', evolutionId)
  // Se vigila solo tras sembrar el borrador del servidor (fija el baseline).
  const [serverLoaded, setServerLoaded] = useState(false)
  const draftEnabled = !!userId && !!tenantId && serverLoaded && !pdfSummaryId
  const { draft, clearDraft } = useLocalDraft<ResumenSecciones>({
    storageKey,
    value: secciones,
    enabled: draftEnabled,
  })

  // Fase A: sembrar desde el servidor una sola vez (baseline del borrador).
  const seededRef = useRef(false)
  const draftAppliedRef = useRef(false)
  useEffect(() => {
    if (!borrador || seededRef.current) return
    seededRef.current = true
    setSecciones(borrador.secciones)
    setServerLoaded(true)
  }, [borrador])

  // Fase B: precargar el borrador local por encima (una sola vez).
  useEffect(() => {
    if (!serverLoaded || draftAppliedRef.current) return
    draftAppliedRef.current = true
    if (draft) setSecciones(draft.data)
  }, [serverLoaded, draft])

  const descartarBorrador = (): void => {
    clearDraft()
    if (borrador) setSecciones(borrador.secciones)
  }

  const setCampo = (key: keyof ResumenSecciones) =>
    (e: React.ChangeEvent<HTMLTextAreaElement>) =>
      setSecciones(s => ({ ...s, [key]: e.target.value }))

  const generar = async () => {
    try {
      const resumen = await crear.mutateAsync(secciones)
      clearDraft() // generado en el servidor: descartar el borrador local
      setPdfSummaryId(resumen.id)
    } catch (err) {
      await aviso({
        tipo: 'error',
        titulo: 'No se pudo generar el resumen',
        mensaje: erroresDe(err).join(' '),
      })
    }
  }

  const enc = borrador?.encabezado

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
          style={{ maxWidth: '820px', height: '92vh' }}
          initial={{ opacity: 0, y: 24, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 24, scale: 0.97 }}
          transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
          onClick={e => e.stopPropagation()}
        >
          {/* ── Encabezado del modal ── */}
          <div className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-amber-900/10">
            <div className="flex items-center gap-2.5">
              <ClipboardList className="w-5 h-5" style={{ color: ORO }} />
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-widest text-amber-700/70">
                  Resumen clínico
                </p>
                <h3 className="text-base font-bold text-gray-900 leading-tight">
                  {enc?.patient_name ?? 'Paciente'}
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
                <Loader2 className="w-5 h-5 animate-spin" /> Preparando el resumen…
              </div>
            ) : isError || !borrador ? (
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
                    Este documento es el resumen que se entrega al paciente. Se guarda una copia
                    como constancia.
                  </p>
                </div>

                {/* Encabezado NO editable: datos + signos vitales */}
                {enc && <EncabezadoResumen enc={enc} />}

                {/* Secciones editables */}
                <div className="space-y-4">
                  {SECCIONES.map(({ key, label, rows }) => (
                    <div key={key}>
                      <label className="block text-[11px] font-semibold uppercase tracking-wide text-amber-700/80 mb-1">
                        {label}
                      </label>
                      <textarea
                        className="input resize-none w-full"
                        rows={rows}
                        maxLength={8000}
                        value={secciones[key]}
                        onChange={setCampo(key)}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ── Pie: acción ── */}
          {borrador && !isLoading && (
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
      {pdfSummaryId && (
        <VisorPdf
          titulo={`Resumen clínico · ${enc?.patient_name ?? ''}`.trim()}
          nombreArchivo={`resumen-clinico-${enc?.fecha ?? ''}.pdf`}
          cargar={() => getResumenClinicoPdf(pdfSummaryId)}
          onClose={() => setPdfSummaryId(null)}
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
            ? 'No tienes permiso para generar el resumen clínico.'
            : 'No se pudo preparar el resumen clínico.'}
        </p>
        <p className="text-xs text-red-600/80 mt-0.5">
          {esPermiso
            ? 'El resumen solo está disponible para roles clínicos.'
            : 'Intenta de nuevo en un momento.'}
        </p>
      </div>
    </div>
  )
}

/** Tarjeta del encabezado NO editable: datos del paciente + signos vitales. */
function EncabezadoResumen({
  enc,
}: {
  enc: import('../../types/expediente').ResumenEncabezado
}) {
  return (
    <div
      className="rounded-2xl p-4 sm:p-5"
      style={{ background: 'rgba(255,255,255,0.72)', border: '1px solid rgba(201,162,39,0.28)' }}
    >
      <p className="text-sm font-bold text-gray-900">{enc.clinic_name}</p>
      <div
        className="grid gap-x-4 gap-y-2 mt-3"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}
      >
        <Dato label="Paciente" value={enc.patient_name} />
        <Dato label="Edad" value={enc.edad != null ? `${enc.edad} años` : '—'} />
        <Dato label="Sexo" value={sexoLabel(enc.sexo)} />
        <Dato label="Fecha" value={enc.fecha ? formatFechaCorta(enc.fecha) : '—'} />
      </div>

      {/* Signos vitales de la visita */}
      <div className="mt-4 pt-3 border-t border-amber-900/10">
        <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: '#0E7C7B' }}>
          <Activity className="w-3.5 h-3.5" /> Signos vitales
        </p>
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))' }}>
          <Signo label="T/A" value={enc.ta} unidad="mmHg" />
          <Signo label="FC" value={enc.fc} unidad="lpm" />
          <Signo label="FR" value={enc.fr} unidad="rpm" />
          <Signo label="Temp" value={enc.temp_c} unidad="°C" />
          <Signo label="Peso" value={enc.peso_kg} unidad="kg" />
          <Signo label="Talla" value={enc.talla_m} unidad="m" />
        </div>
      </div>
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

/** Tarjeta de un signo vital (muestra "—" si no hay dato). */
function Signo({
  label, value, unidad,
}: { label: string; value: string | number | null; unidad?: string }) {
  const hay = value != null && value !== ''
  return (
    <div
      className="rounded-xl px-3 py-2 text-center"
      style={{ background: 'rgba(14,124,123,0.07)', border: '1px solid rgba(14,124,123,0.2)' }}
    >
      <p className="text-[10px] uppercase tracking-wide" style={{ color: '#0E7C7B' }}>{label}</p>
      <p className="text-base font-bold text-gray-800 leading-tight">
        {hay ? value : '—'}
        {hay && unidad && <span className="text-[10px] font-normal text-gray-400"> {unidad}</span>}
      </p>
    </div>
  )
}
