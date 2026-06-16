/**
 * EvolucionTab — pestaña Evolución.
 * Lista de notas inmutables (solo lectura) con sus addenda; alta de nota desde una
 * cita ATTENDED del paciente; agregar addendum a una nota.
 */

import { useMemo, useState } from 'react'
import { Stethoscope, Plus, Loader2, MessageSquarePlus, Lock, X } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Appointment } from '../../types/agenda'
import type {
  EvolutionNote, EvolutionNoteInput, ExploracionEvolucion, ExploracionSistema,
} from '../../types/expediente'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import { useCreateAddendum, useCreateEvolutionNote, useEvolutionNotes } from '../../hooks/expediente'
import { formatFechaHora } from '../../lib/fecha'
import { erroresDe } from '../../lib/apiErrors'
import {
  Card, Cargando, ErroresAlerta, Vacio, EXPLORACION_EVOLUCION_OPTIONS, SISTEMA_LABEL,
} from './ui'

const SISTEMAS: ExploracionSistema[] = [
  'cerebro', 'sistema_nervioso', 'ocular', 'endocrino', 'corazon', 'circulatorio',
  'respiratorio', 'hepatico', 'pancreas', 'renal', 'gastrointestinal', 'osteoarticular',
  'tendomuscular', 'reproductor', 'inmunologico', 'extremidades', 'piel_tegumentos', 'otros',
]

/** Campos de texto de la nota de evolución. */
const TEXTO_CAMPOS: { key: keyof NotaTexto; label: string }[] = [
  { key: 'antecedentes', label: 'Antecedentes' },
  { key: 'interrogatorio', label: 'Interrogatorio' },
  { key: 'estudios', label: 'Estudios' },
  { key: 'diagnosticos_texto', label: 'Diagnósticos (texto)' },
  { key: 'tratamiento', label: 'Tratamiento' },
  { key: 'plan_recomendaciones', label: 'Plan y recomendaciones' },
  { key: 'indicaciones_enfermeria', label: 'Indicaciones de enfermería' },
]

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
  const [nueva, setNueva] = useState(false)

  const notas: EvolutionNote[] = notasData?.results ?? []

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
        notas.map(n => <NotaCard key={n.id} nota={n} patientId={paciente.id} puedeEditar={puedeEditar} />)
      )}
    </div>
  )
}

// ── Card de una nota (solo lectura) ───────────────────────────────────────────

function NotaCard({ nota, patientId, puedeEditar }: { nota: EvolutionNote; patientId: string; puedeEditar: boolean }) {
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
        {TEXTO_CAMPOS.map(({ key, label }) => {
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
            <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">Exploración física</p>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {explorAlteradas.map(([sistema, celda]) => {
                const opt = EXPLORACION_EVOLUCION_OPTIONS.find(o => o.value === celda?.estado)
                return (
                  <span key={sistema} className="inline-flex items-center gap-1 text-[11px] rounded-full px-2.5 py-1"
                    style={{ background: `${opt?.color}1A`, color: opt?.color }}>
                    {SISTEMA_LABEL[sistema]}: {opt?.label}{celda?.detalle ? ` (${celda.detalle})` : ''}
                  </span>
                )
              })}
            </div>
          </div>
        )}
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
  const [errores, setErrores] = useState<string[]>([])

  // Solo citas ATTENDED del paciente (requisito del backend D-EC-2).
  const citasAtendidas = useMemo<Appointment[]>(
    () => (citasData?.results ?? []).filter(c => c.status === 'attended'),
    [citasData],
  )
  const citaSel = citasAtendidas.find(c => c.id === appointmentId) ?? null

  const setT = (k: keyof NotaTexto) => (e: React.ChangeEvent<HTMLTextAreaElement>) =>
    setTexto(t => ({ ...t, [k]: e.target.value }))

  const setSistema = (sistema: ExploracionSistema, patch: Partial<{ estado: string; detalle: string }>) =>
    setExplor(prev => ({ ...prev, [sistema]: { ...prev[sistema], ...patch } }))

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
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
              {TEXTO_CAMPOS.map(({ key, label }) => (
                <div key={key}>
                  <label className="label">{label}</label>
                  <textarea className="input resize-none" rows={2} value={texto[key]} onChange={setT(key)} />
                </div>
              ))}
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-2">Exploración física</p>
              <div className="space-y-2">
                {SISTEMAS.map(sistema => {
                  const celda = explor[sistema] ?? {}
                  return (
                    <div key={sistema} className="grid items-center gap-2" style={{ gridTemplateColumns: '160px 160px 1fr' }}>
                      <span className="text-sm text-gray-700">{SISTEMA_LABEL[sistema]}</span>
                      <select className="input" value={celda.estado ?? 'no_evaluado'}
                        onChange={e => setSistema(sistema, { estado: e.target.value })}>
                        {EXPLORACION_EVOLUCION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                      <input className="input" placeholder="Detalle (opcional)" value={celda.detalle ?? ''}
                        onChange={e => setSistema(sistema, { detalle: e.target.value })} />
                    </div>
                  )
                })}
              </div>
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
