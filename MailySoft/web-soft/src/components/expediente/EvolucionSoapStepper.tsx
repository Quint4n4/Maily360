/**
 * EvolucionSoapStepper — captura de la nota de evolución GUIADA paso a paso (SOAP).
 *
 * Reemplaza, en el flujo de la "Visita de hoy", al formulario monolítico de
 * EvolucionTab/NuevaEvolucion. NO cambia el modelo ni el guardado: usa el MISMO
 * hook (useCreateEvolutionNote) y el MISMO payload (EvolutionNoteInput) que antes.
 * Las evoluciones siguen siendo inmutables; aquí solo se cambia la captura.
 *
 * Mapeo a los campos reales del modelo (sin inventar campos):
 *   S (Subjetivo) → interrogatorio + antecedentes
 *   O (Objetivo)  → signos vitales (heredados de Enfermería, SOLO LECTURA) + estudios
 *                   + exploración física SELECTIVA (solo los aparatos que se agreguen)
 *   A (Análisis)  → diagnosticos_texto (texto libre del diagnóstico de hoy)
 *   P (Plan)      → tratamiento + plan_recomendaciones + indicaciones_enfermeria
 *
 * Colores SOAP: S #185FA5, O #0F6E56, A #534AB7, P #3B6D11.
 *
 * Exploración física selectiva (D-EXP-3): en vez de mostrar los 18 sistemas, un
 * botón "Agregar aparato" deja elegir cuáles se revisaron hoy; solo esos se
 * muestran/guardan, con la MISMA estructura {sistema:{estado,detalle}} de hoy.
 *
 * Tras guardar, ofrece adjuntar imágenes a la nota recién creada (reusa
 * useUploadEvolutionImage) antes de cerrar.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  X, Loader2, Lock, ChevronLeft, ChevronRight, Plus, Trash2, ImagePlus, ImageIcon,
  CheckCircle2, Activity,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Appointment } from '../../types/agenda'
import type {
  EvolutionNote, EvolutionNoteInput, ExploracionEvolucion, ExploracionEvolucionEstado,
  ExploracionSistema, VitalSignsRecord,
} from '../../types/expediente'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import {
  useCreateEvolutionNote, useEvolutionImages, useUploadEvolutionImage,
  useDeleteEvolutionImage, useVitalSigns,
} from '../../hooks/expediente'
import { useAuth } from '../../auth/AuthContext'
import { useLocalDraft } from '../../hooks/useLocalDraft'
import { draftKey } from '../../lib/draftKeys'
import BorradorRecuperadoAviso from '../common/BorradorRecuperadoAviso'
import { formatFechaHora } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import {
  ErroresAlerta, EXPLORACION_EVOLUCION_OPTIONS, SISTEMA_LABEL, SistemaIcono,
} from './ui'

// ── Colores SOAP (D-EXP-2) ─────────────────────────────────────────────────────

const SOAP = {
  S: { letra: 'S', label: 'Subjetivo', color: '#185FA5', desc: 'Lo que cuenta el paciente' },
  O: { letra: 'O', label: 'Objetivo', color: '#0F6E56', desc: 'Lo que tú observas y mides' },
  A: { letra: 'A', label: 'Análisis', color: '#534AB7', desc: 'Tu impresión diagnóstica' },
  P: { letra: 'P', label: 'Plan', color: '#3B6D11', desc: 'Qué se va a hacer' },
} as const

type SoapLetra = keyof typeof SOAP
const PASOS: SoapLetra[] = ['S', 'O', 'A', 'P']

/** Todos los sistemas disponibles para la exploración selectiva. */
const SISTEMAS: ExploracionSistema[] = [
  'cerebro', 'sistema_nervioso', 'ocular', 'endocrino', 'corazon', 'circulatorio',
  'respiratorio', 'hepatico', 'pancreas', 'renal', 'gastrointestinal', 'osteoarticular',
  'tendomuscular', 'reproductor', 'inmunologico', 'extremidades', 'piel_tegumentos', 'otros',
]

/** Campos de texto de la nota (mismos nombres del modelo). */
interface NotaTexto {
  antecedentes: string
  interrogatorio: string
  estudios: string
  diagnosticos_texto: string
  tratamiento: string
  plan_recomendaciones: string
  indicaciones_enfermeria: string
}

const TEXTO_VACIO: NotaTexto = {
  antecedentes: '', interrogatorio: '', estudios: '', diagnosticos_texto: '',
  tratamiento: '', plan_recomendaciones: '', indicaciones_enfermeria: '',
}

/** Forma del BORRADOR LOCAL de una nota de evolución en progreso. */
interface EvolucionDraft {
  appointmentId: string
  paso: number
  texto: NotaTexto
  explor: ExploracionEvolucion
}

interface EvolucionSoapStepperProps {
  paciente: PatientOut
  onClose: () => void
}

export default function EvolucionSoapStepper({ paciente, onClose }: EvolucionSoapStepperProps) {
  const { data: citasData, isLoading: citasLoading } = useAppointmentsForPatient(paciente.id)
  const { data: signosData } = useVitalSigns(paciente.id)
  const crear = useCreateEvolutionNote(paciente.id)

  const { user } = useAuth()

  const [appointmentId, setAppointmentId] = useState('')
  const [paso, setPaso] = useState(0)
  const [texto, setTexto] = useState<NotaTexto>(TEXTO_VACIO)
  // Solo los aparatos que el médico decidió revisar hoy (exploración selectiva).
  const [explor, setExplor] = useState<ExploracionEvolucion>({})
  const [errores, setErrores] = useState<string[]>([])
  /** Nota recién creada: se ofrece adjuntar imágenes antes de cerrar. */
  const [creada, setCreada] = useState<EvolutionNote | null>(null)

  // ── Borrador local: una nota de evolución en progreso por paciente ──
  const userId = user?.id ?? ''
  const tenantId = user?.active_tenant?.id ?? ''
  const storageKey = draftKey(userId, tenantId, 'evolucion', paciente.id)
  const draftEnabled = !!userId && !!tenantId && !creada
  const draftValue = useMemo<EvolucionDraft>(
    () => ({ appointmentId, paso, texto, explor }),
    [appointmentId, paso, texto, explor],
  )
  const { draft, clearDraft } = useLocalDraft<EvolucionDraft>({
    storageKey,
    value: draftValue,
    enabled: draftEnabled,
  })

  // Precarga del borrador (una sola vez, si hay uno y hay usuario/tenant).
  const draftAppliedRef = useRef(false)
  useEffect(() => {
    if (draftAppliedRef.current) return
    if (!userId || !tenantId) return // esperar a que la sesión esté lista
    draftAppliedRef.current = true
    if (draft) {
      setAppointmentId(draft.data.appointmentId)
      setPaso(draft.data.paso)
      setTexto(draft.data.texto)
      setExplor(draft.data.explor)
    }
  }, [draft, userId, tenantId])

  const descartarBorrador = (): void => {
    clearDraft()
    setAppointmentId('')
    setPaso(0)
    setTexto(TEXTO_VACIO)
    setExplor({})
  }

  // Solo citas ATTENDED del paciente (requisito del backend D-EC-2).
  const citasAtendidas = useMemo<Appointment[]>(
    () => (citasData?.results ?? []).filter(c => c.status === 'attended'),
    [citasData],
  )
  const citaSel = citasAtendidas.find(c => c.id === appointmentId) ?? null

  // Última toma de signos (se hereda al paso O en SOLO LECTURA).
  const ultimaToma: VitalSignsRecord | null = useMemo(
    () => signosData?.results?.[0] ?? null,
    [signosData],
  )

  const setT = (k: keyof NotaTexto) => (e: React.ChangeEvent<HTMLTextAreaElement>) =>
    setTexto(t => ({ ...t, [k]: e.target.value }))

  const setEstado = (sistema: ExploracionSistema, estado: ExploracionEvolucionEstado) =>
    setExplor(prev => ({ ...prev, [sistema]: { ...prev[sistema], estado } }))
  const setDetalle = (sistema: ExploracionSistema, detalle: string) =>
    setExplor(prev => ({ ...prev, [sistema]: { ...prev[sistema], detalle } }))
  const agregarAparato = (sistema: ExploracionSistema) =>
    setExplor(prev => ({ ...prev, [sistema]: { estado: 'normal', detalle: '' } }))
  const quitarAparato = (sistema: ExploracionSistema) =>
    setExplor(prev => {
      const next = { ...prev }
      delete next[sistema]
      return next
    })

  const guardar = async () => {
    setErrores([])
    if (!citaSel) { setErrores(['Elige una cita atendida.']); return }
    const input: EvolutionNoteInput = {
      appointment_id: citaSel.id,
      doctor_id: citaSel.doctor.id,
      ...texto,
    }
    // Solo enviar exploración de sistemas con estado distinto de 'no_evaluado'.
    const explorEnviar: ExploracionEvolucion = {}
    for (const [sistema, celda] of Object.entries(explor)) {
      if (celda?.estado && celda.estado !== 'no_evaluado') {
        explorEnviar[sistema as ExploracionSistema] = celda
      }
    }
    if (Object.keys(explorEnviar).length > 0) input.exploracion_fisica = explorEnviar
    try {
      const nota = await crear.mutateAsync(input)
      clearDraft() // nota creada en el servidor: descartar el borrador local
      setCreada(nota)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  // Pantalla de éxito: adjuntar imágenes a la nota recién creada (opcional).
  if (creada) {
    return <NotaCreadaImagenes nota={creada} onClose={onClose} />
  }

  // Sin cita atendida: el médico no puede crear una evolución (regla del backend).
  if (!citasLoading && citasAtendidas.length === 0) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-gray-700">Evolución (SOAP)</p>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-amber-700">
          Este paciente no tiene citas atendidas. La nota de evolución nace de una cita
          marcada como «Atendida» en la agenda.
        </p>
      </div>
    )
  }

  const enPrimerPaso = paso === 0
  const enUltimoPaso = paso === PASOS.length - 1

  return (
    <div className="space-y-4">
      {/* Encabezado + cerrar */}
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-gray-700">Evolución guiada (SOAP)</p>
        <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700">
          <X className="w-4 h-4" />
        </button>
      </div>

      {draft && draftEnabled && (
        <BorradorRecuperadoAviso savedAt={draft.savedAt} onDescartar={descartarBorrador} />
      )}

      {/* Selección de cita atendida (igual que el flujo anterior) */}
      <div>
        <label className="label">Cita atendida</label>
        {citasLoading ? (
          <p className="text-sm text-gray-400 italic">Cargando citas…</p>
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
          {/* Stepper S → O → A → P */}
          <StepperBarra paso={paso} onPaso={setPaso} />

          <ErroresAlerta errores={errores} />

          {/* Paso activo */}
          <div className="rounded-2xl p-4" style={{ background: 'rgba(255,255,255,0.6)', border: '1px solid rgba(201,162,39,0.18)' }}>
            <CabeceraPaso letra={PASOS[paso]} />

            {PASOS[paso] === 'S' && (
              <div className="space-y-3 mt-3">
                <CampoTexto label="Interrogatorio (motivo y relato de hoy)" value={texto.interrogatorio} onChange={setT('interrogatorio')} rows={3} />
                <CampoTexto label="Antecedentes patológicos" value={texto.antecedentes} onChange={setT('antecedentes')} rows={2} />
              </div>
            )}

            {PASOS[paso] === 'O' && (
              <div className="space-y-4 mt-3">
                <SignosHeredados toma={ultimaToma} />
                <CampoTexto label="Estudios (laboratorio, gabinete…)" value={texto.estudios} onChange={setT('estudios')} rows={2} />
                <ExploracionSelectiva
                  explor={explor}
                  onAgregar={agregarAparato}
                  onQuitar={quitarAparato}
                  onEstado={setEstado}
                  onDetalle={setDetalle}
                />
              </div>
            )}

            {PASOS[paso] === 'A' && (
              <div className="space-y-3 mt-3">
                <CampoTexto
                  label="Diagnóstico / impresión diagnóstica de hoy"
                  value={texto.diagnosticos_texto} onChange={setT('diagnosticos_texto')} rows={3}
                />
                <p className="text-[11px] text-gray-400">
                  Texto libre del diagnóstico de esta visita. Los diagnósticos formales
                  (con CIE-10, presuntivo/definitivo) se administran en el historial del paciente.
                </p>
              </div>
            )}

            {PASOS[paso] === 'P' && (
              <div className="space-y-3 mt-3">
                <CampoTexto label="Tratamiento" value={texto.tratamiento} onChange={setT('tratamiento')} rows={2} />
                <CampoTexto label="Plan y recomendaciones" value={texto.plan_recomendaciones} onChange={setT('plan_recomendaciones')} rows={2} />
                <CampoTexto label="Indicaciones para enfermería" value={texto.indicaciones_enfermeria} onChange={setT('indicaciones_enfermeria')} rows={2} />
              </div>
            )}
          </div>

          {/* Navegación Atrás / Siguiente / Guardar */}
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setPaso(p => Math.max(0, p - 1))}
              disabled={enPrimerPaso}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold btn-secondary disabled:opacity-40"
            >
              <ChevronLeft className="w-4 h-4" /> Atrás
            </button>

            {!enUltimoPaso ? (
              <button
                type="button"
                onClick={() => setPaso(p => Math.min(PASOS.length - 1, p + 1))}
                className="inline-flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                style={{ background: SOAP[PASOS[paso + 1]].color }}
              >
                Siguiente · {SOAP[PASOS[paso + 1]].letra} {SOAP[PASOS[paso + 1]].label}
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button" onClick={guardar} disabled={crear.isPending}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                {crear.isPending
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</>
                  : <><Lock className="w-4 h-4" /> Firmar y guardar</>}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ── Barra del stepper (S → O → A → P) ──────────────────────────────────────────

function StepperBarra({ paso, onPaso }: { paso: number; onPaso: (p: number) => void }) {
  return (
    <div className="flex items-center gap-1.5">
      {PASOS.map((letra, idx) => {
        const cfg = SOAP[letra]
        const activo = idx === paso
        const completado = idx < paso
        return (
          <div key={letra} className="flex items-center gap-1.5 flex-1">
            <button
              type="button"
              onClick={() => onPaso(idx)}
              className="flex items-center gap-2 flex-1 rounded-xl px-2.5 py-2 transition-all text-left"
              style={{
                background: activo ? cfg.color : completado ? `${cfg.color}1A` : 'rgba(255,255,255,0.6)',
                border: activo ? `1px solid ${cfg.color}` : `1px solid ${cfg.color}33`,
              }}
              title={`${cfg.label} — ${cfg.desc}`}
            >
              <span
                className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-sm font-bold"
                style={{
                  background: activo ? '#fff' : cfg.color,
                  color: activo ? cfg.color : '#fff',
                }}
              >
                {cfg.letra}
              </span>
              <span
                className="text-xs font-semibold leading-tight hidden sm:block"
                style={{ color: activo ? '#fff' : cfg.color }}
              >
                {cfg.label}
              </span>
            </button>
          </div>
        )
      })}
    </div>
  )
}

/** Cabecera del paso activo (letra grande + descripción). */
function CabeceraPaso({ letra }: { letra: SoapLetra }) {
  const cfg = SOAP[letra]
  return (
    <div className="flex items-center gap-3">
      <span
        className="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center text-base font-bold text-white"
        style={{ background: cfg.color }}
      >
        {cfg.letra}
      </span>
      <div>
        <p className="text-sm font-bold" style={{ color: cfg.color }}>{cfg.label}</p>
        <p className="text-[11px] text-gray-400 leading-tight">{cfg.desc}</p>
      </div>
    </div>
  )
}

/** Un textarea etiquetado (estilo glass del resto). */
function CampoTexto({
  label, value, onChange, rows = 2,
}: {
  label: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void
  rows?: number
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <textarea className="input resize-none" rows={rows} maxLength={4000} value={value} onChange={onChange} />
    </div>
  )
}

// ── Signos heredados de Enfermería (solo lectura) en el paso O ──────────────────

function SignoChip({
  label, value, unidad,
}: { label: string; value: string | number | null | undefined; unidad?: string }) {
  const hay = value != null && value !== ''
  if (!hay) return null
  return (
    <div className="rounded-lg px-2.5 py-1.5 bg-white/70">
      <p className="text-[10px] text-gray-400">{label}</p>
      <p className="text-sm font-semibold text-gray-700">
        {value}{unidad && <span className="text-[10px] font-normal text-gray-400"> {unidad}</span>}
      </p>
    </div>
  )
}

function SignosHeredados({ toma }: { toma: VitalSignsRecord | null }) {
  return (
    <div className="rounded-xl px-3 py-3" style={{ background: 'rgba(15,110,86,0.06)', border: '1px solid rgba(15,110,86,0.2)' }}>
      <div className="flex items-center gap-1.5 mb-2">
        <Activity className="w-3.5 h-3.5" style={{ color: '#0F6E56' }} />
        <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: '#0F6E56' }}>
          Signos de enfermería {toma ? `· ${formatFechaHora(toma.measured_at)}` : ''}
          <span className="text-gray-400 font-normal normal-case"> · solo lectura</span>
        </p>
      </div>
      {!toma ? (
        <p className="text-xs text-gray-400 italic">
          Sin signos capturados. Captúralos en el paso ① Enfermería de la visita.
        </p>
      ) : (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(90px, 1fr))' }}>
          <SignoChip
            label="PA"
            value={toma.systolic != null && toma.diastolic != null ? `${toma.systolic}/${toma.diastolic}` : null}
            unidad="mmHg"
          />
          <SignoChip label="Temp" value={toma.temperature_c} unidad="°C" />
          <SignoChip label="FC" value={toma.heart_rate} unidad="lpm" />
          <SignoChip label="FR" value={toma.resp_rate} unidad="rpm" />
          <SignoChip label="SatO₂" value={toma.oxygen_saturation} unidad="%" />
          <SignoChip label="Peso" value={toma.weight_kg} unidad="kg" />
          <SignoChip label="IMC" value={toma.imc} />
          <SignoChip label="Glucosa" value={toma.glucose} unidad="mg/dL" />
        </div>
      )}
    </div>
  )
}

// ── Exploración física SELECTIVA (D-EXP-3) ─────────────────────────────────────

function ExploracionSelectiva({
  explor, onAgregar, onQuitar, onEstado, onDetalle,
}: {
  explor: ExploracionEvolucion
  onAgregar: (s: ExploracionSistema) => void
  onQuitar: (s: ExploracionSistema) => void
  onEstado: (s: ExploracionSistema, e: ExploracionEvolucionEstado) => void
  onDetalle: (s: ExploracionSistema, d: string) => void
}) {
  const [menuAbierto, setMenuAbierto] = useState(false)
  const seleccionados = Object.keys(explor) as ExploracionSistema[]
  const disponibles = SISTEMAS.filter(s => !seleccionados.includes(s))

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">
          Exploración física {seleccionados.length > 0 && `· ${seleccionados.length}`}
        </p>
        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuAbierto(v => !v)}
            disabled={disponibles.length === 0}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-40"
          >
            <Plus className="w-3.5 h-3.5" /> Agregar aparato
          </button>
          {menuAbierto && disponibles.length > 0 && (
            <div
              className="absolute right-0 z-30 mt-1 w-56 max-h-64 overflow-y-auto rounded-xl shadow-lg py-1"
              style={{ background: 'rgba(255,255,255,0.98)', border: '1px solid rgba(201,162,39,0.25)' }}
            >
              {disponibles.map(s => (
                <button
                  key={s}
                  type="button"
                  onClick={() => { onAgregar(s); setMenuAbierto(false) }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-amber-50/80 transition-colors"
                >
                  <SistemaIcono sistema={s} className="h-5 w-5 shrink-0" />
                  <span className="text-sm text-gray-700">{SISTEMA_LABEL[s] ?? s}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {seleccionados.length === 0 ? (
        <p className="text-xs text-gray-400 italic">
          Agrega solo los aparatos que revisaste hoy. Lo demás no se guarda.
        </p>
      ) : (
        <div className="space-y-2">
          {seleccionados.map(sistema => (
            <AparatoFila
              key={sistema}
              sistema={sistema}
              estado={explor[sistema]?.estado ?? 'normal'}
              detalle={explor[sistema]?.detalle ?? ''}
              onEstado={e => onEstado(sistema, e)}
              onDetalle={d => onDetalle(sistema, d)}
              onQuitar={() => onQuitar(sistema)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/** Una fila de aparato revisado: icono + semáforo de estado + detalle + quitar. */
function AparatoFila({
  sistema, estado, detalle, onEstado, onDetalle, onQuitar,
}: {
  sistema: ExploracionSistema
  estado: ExploracionEvolucionEstado
  detalle: string
  onEstado: (e: ExploracionEvolucionEstado) => void
  onDetalle: (d: string) => void
  onQuitar: () => void
}) {
  // El semáforo dentro del flujo selectivo no necesita "no evaluado": si se
  // agregó es porque se revisó. Mostramos normal / observación / alterado.
  const opciones = EXPLORACION_EVOLUCION_OPTIONS.filter(o => o.value !== 'no_evaluado')

  return (
    <div className="rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.7)', border: '1px solid rgba(201,162,39,0.2)' }}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-gray-700">
          <SistemaIcono sistema={sistema} className="h-6 w-6" />
          {SISTEMA_LABEL[sistema] ?? sistema}
        </span>
        <button
          type="button" onClick={onQuitar} aria-label="Quitar aparato"
          className="text-gray-400 hover:text-red-600"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {opciones.map(o => {
          const sel = o.value === estado
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => onEstado(o.value)}
              className="inline-flex items-center gap-1.5 text-xs font-semibold rounded-full px-3 py-1.5 transition-all"
              style={{
                background: sel ? o.color : `${o.color}1A`,
                color: sel ? '#fff' : o.color,
                border: `1px solid ${o.color}${sel ? '' : '44'}`,
              }}
            >
              {o.label}
            </button>
          )
        })}
      </div>
      <input
        className="input text-sm mt-2"
        maxLength={255}
        placeholder="Detalle (opcional)…"
        value={detalle}
        onChange={e => onDetalle(e.target.value)}
      />
    </div>
  )
}

// ── Pantalla de éxito: adjuntar imágenes a la nota recién creada ────────────────

/** Tipos de imagen que el navegador deja elegir (UX). El backend valida de verdad. */
const ACCEPT_IMAGEN = 'image/png,image/jpeg,image/webp'

function NotaCreadaImagenes({ nota, onClose }: { nota: EvolutionNote; onClose: () => void }) {
  const { data: imagenes } = useEvolutionImages(nota.id)
  const subir = useUploadEvolutionImage(nota.id)
  const borrar = useDeleteEvolutionImage(nota.id)
  const inputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')

  const lista = imagenes ?? []

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError('')
    try {
      await subir.mutateAsync({ file })
    } catch (err) {
      setError(erroresDe(err).join(' '))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: '#E7F6EE', border: '1px solid rgba(46,125,91,0.25)' }}>
        <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-600" />
        <p className="text-sm text-emerald-800">
          Evolución firmada y guardada. Se agregó como capítulo al libro clínico del paciente.
        </p>
      </div>

      <div>
        <div className="flex items-center justify-between gap-2 mb-2">
          <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">
            <ImageIcon className="w-3.5 h-3.5" /> Imágenes (opcional)
            {lista.length > 0 && <span className="text-gray-400 font-normal normal-case">· {lista.length}</span>}
          </p>
          <button
            type="button"
            onClick={() => { if (!subir.isPending) inputRef.current?.click() }}
            disabled={subir.isPending}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 hover:text-amber-800 disabled:opacity-60"
          >
            {subir.isPending
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Subiendo…</>
              : <><ImagePlus className="w-3.5 h-3.5" /> Agregar imagen</>}
          </button>
        </div>
        <input ref={inputRef} type="file" accept={ACCEPT_IMAGEN} className="hidden" onChange={onFile} />
        {error && <p className="text-xs text-red-600 mb-2">{error}</p>}
        {lista.length === 0 ? (
          <p className="text-xs text-gray-400 italic">Sin imágenes. Puedes adjuntar fotos clínicas ahora o desde el historial.</p>
        ) : (
          <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))' }}>
            {lista.map(img => (
              <div key={img.id} className="group relative">
                <img
                  src={img.image_url}
                  alt={img.caption || 'Imagen de la evolución'}
                  loading="lazy"
                  className="w-full rounded-xl object-cover"
                  style={{ aspectRatio: '1 / 1', border: '1px solid rgba(201,162,39,0.25)' }}
                />
                <button
                  type="button"
                  onClick={() => borrar.mutate(img.id)}
                  aria-label="Eliminar imagen"
                  className="absolute top-1 right-1 rounded-full p-1 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ background: 'rgba(192,57,43,0.92)' }}
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <button
          type="button" onClick={onClose}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white hover:brightness-110"
          style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
        >
          Listo
        </button>
      </div>
    </div>
  )
}
