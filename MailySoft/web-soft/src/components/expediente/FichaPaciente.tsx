/**
 * FichaPaciente — columna fija (izquierda) del expediente.
 * Siempre visible: banderas de Alergias (solo roles clínicos) + Contacto +
 * Identificación + Datos NOM-004 + Notas (solo clínico).
 *
 * Edición INLINE: si el usuario puede editar (puedeEditar), un botón "Editar"
 * arriba convierte la ficha en campos editables (reusando los grupos y la lógica
 * del modal grande vía ../contactos/pacienteForm). Las alergias NO entran en este
 * modo (siguen con su propio alta/resolver).
 *
 * El bloque de alergias se movió tal cual desde ResumenTab (misma lógica de
 * alta/resolver); no se duplica nada.
 */

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Phone, Mail, Fingerprint, StickyNote, User,
  AlertTriangle, Plus, X, Loader2, MapPin, Heart,
  Droplet, GraduationCap, Briefcase, Cake, Calendar, Tag, Users, BookOpen, Baby,
  Pencil, AlertCircle, ClipboardList, FileHeart,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Allergy, AllergyInput, AllergySeverity } from '../../types/expediente'
import {
  useAllergies, useCreateAllergy, useNursingInstructions, useResolveAllergy,
} from '../../hooks/expediente'
import { formatFechaHora } from '../../lib/fecha'
import { useUpdatePatient } from '../../hooks/pacientes'
import { edad } from '../../lib/paciente'
import { errorMsg } from '../../lib/apiErrors'
import { Card, Cargando, SEVERITY_OPTIONS } from './ui'
import HistoriaTab from './HistoriaTab'
import {
  CamposContacto, CamposDatosPersonales, CamposDomicilio, CamposNom004,
  SECCION_LABEL, erroresDePaciente, hayErroresFormato, usePacienteForm,
} from '../contactos/pacienteForm'

/** Color de la bandera de alergia según severidad. */
function severidadColor(sev: AllergySeverity): { bg: string; border: string; color: string } {
  if (sev === 'severa') return { bg: 'rgba(192,57,43,0.12)', border: 'rgba(192,57,43,0.4)', color: '#C0392B' }
  if (sev === 'moderada') return { bg: 'rgba(214,124,30,0.12)', border: 'rgba(214,124,30,0.4)', color: '#B8620B' }
  return { bg: 'rgba(201,162,39,0.12)', border: 'rgba(201,162,39,0.35)', color: '#9A7B1E' }
}

/** Una línea de dato con su icono de color (estilo ficha del legacy). */
function DatoIcono({
  icon: Icon, color, label, value,
}: { icon: typeof Phone; color: string; label: string; value: string | null | undefined }) {
  if (!value) return null
  return (
    <div className="flex items-center gap-2.5" title={label}>
      <Icon className="w-4 h-4 shrink-0" style={{ color }} />
      <span className="text-sm text-gray-800">{value}</span>
    </div>
  )
}

interface FichaPacienteProps {
  paciente: PatientOut
  /** Si el rol tiene acceso clínico (muestra alergias + notas). */
  verClinico: boolean
  /** Si el rol puede editar lo clínico (alta/resolver alergias). */
  puedeEditarClinico: boolean
  /** Si el rol puede editar los datos del paciente (botón "Editar" inline). */
  puedeEditar?: boolean
}

export default function FichaPaciente({
  paciente, verClinico, puedeEditarClinico, puedeEditar = false,
}: FichaPacienteProps) {
  const [editando, setEditando] = useState(false)
  const [hcAbierta, setHcAbierta] = useState(false)

  return (
    <div className="space-y-4">
      {/* Banderas de alergias (solo roles clínicos) — fuera del modo edición */}
      {verClinico && <AlergiasBlock patientId={paciente.id} puedeEditar={puedeEditarClinico} />}

      {/* Indicaciones para enfermería (solo roles clínicos) */}
      {verClinico && <IndicacionesEnfermeriaBlock patientId={paciente.id} />}

      {/* Acceso a la Historia Clínica (se llena una vez y se actualiza) */}
      {verClinico && !editando && (
        <button
          type="button"
          onClick={() => setHcAbierta(true)}
          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
          style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
        >
          <FileHeart className="w-4 h-4" /> Historia clínica
        </button>
      )}

      {verClinico && (
        <HistoriaClinicaModal
          paciente={paciente}
          abierto={hcAbierta}
          puedeEditar={puedeEditarClinico}
          onClose={() => setHcAbierta(false)}
        />
      )}

      {editando ? (
        <FichaEditar
          paciente={paciente}
          verClinico={verClinico}
          onCancelar={() => setEditando(false)}
          onGuardado={() => setEditando(false)}
        />
      ) : (
        <FichaLectura
          paciente={paciente}
          verClinico={verClinico}
          puedeEditar={puedeEditar}
          onEditar={() => setEditando(true)}
        />
      )}
    </div>
  )
}

// ── Modal de Historia Clínica (captura + render dinámico) ────────────────────

/**
 * Modal que monta HistoriaTab: núcleo NOM-004 + preguntas extra de la clínica.
 * Se abre desde la columna izquierda del expediente. La edición respeta
 * `puedeEditar` (puedeEditarClinico); el backend es la autoridad y devuelve 403.
 */
function HistoriaClinicaModal({
  paciente, abierto, puedeEditar, onClose,
}: {
  paciente: PatientOut
  abierto: boolean
  puedeEditar: boolean
  onClose: () => void
}) {
  return (
    <AnimatePresence>
      {abierto && (
        <motion.div
          className="fixed inset-0 z-[60] p-2 sm:p-4 flex items-center justify-center"
          style={{ background: 'rgba(40,28,8,0.35)', backdropFilter: 'blur(8px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full glass-card rounded-3xl flex flex-col overflow-hidden"
            style={{ maxWidth: '900px', height: '92vh' }}
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            <div className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-amber-900/10">
              <div className="flex items-center gap-2.5">
                <FileHeart className="w-5 h-5" style={{ color: '#C9A227' }} />
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-widest text-amber-700/70">Historia clínica</p>
                  <h3 className="text-base font-bold text-gray-900 leading-tight">{paciente.full_name}</h3>
                </div>
              </div>
              <button
                onClick={onClose}
                className="w-9 h-9 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors shadow-sm"
              >
                <X className="w-5 h-5 text-gray-600" />
              </button>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-5 sm:p-6">
              <HistoriaTab paciente={paciente} puedeEditar={puedeEditar} />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ── Modo lectura ─────────────────────────────────────────────────────────────

function FichaLectura({
  paciente, verClinico, puedeEditar, onEditar,
}: {
  paciente: PatientOut
  verClinico: boolean
  puedeEditar: boolean
  onEditar: () => void
}) {
  const years = edad(paciente.date_of_birth ?? '')

  const domicilio = [paciente.address_street, paciente.address_neighborhood, paciente.city, paciente.state]
    .filter(Boolean)
    .join(', ')

  return (
    <div className="space-y-4">
      {puedeEditar && (
        <button
          type="button"
          onClick={onEditar}
          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all hover:brightness-105"
          style={{
            background: 'rgba(255,255,255,0.72)',
            border: '1px solid rgba(201,162,39,0.45)',
            color: '#9A7B1E',
            boxShadow: '0 4px 14px rgba(201,162,39,0.18)',
          }}
        >
          <Pencil className="w-4 h-4" /> Editar
        </button>
      )}

      <Card title="Contacto" icon={Phone}>
        <div className="space-y-2.5">
          <div className="flex items-center gap-2.5">
            <Phone className="w-4 h-4 text-gray-400 shrink-0" />
            <span className="text-sm text-gray-800">{paciente.phone || '—'}</span>
          </div>
          {paciente.phone_secondary && (
            <div className="flex items-center gap-2.5">
              <Phone className="w-4 h-4 text-gray-400 shrink-0" />
              <span className="text-sm text-gray-800">
                {paciente.phone_secondary}
                {paciente.phone_label ? ` (${paciente.phone_label})` : ''}
              </span>
            </div>
          )}
          <div className="flex items-center gap-2.5">
            <Mail className="w-4 h-4 text-gray-400 shrink-0" />
            <span className="text-sm text-gray-800 truncate">{paciente.email || '—'}</span>
          </div>
          {domicilio && (
            <div className="flex items-start gap-2.5">
              <MapPin className="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
              <span className="text-sm text-gray-800">
                {domicilio}{paciente.postal_code ? ` · CP ${paciente.postal_code}` : ''}
              </span>
            </div>
          )}
        </div>
      </Card>

      <Card title="Identificación" icon={Fingerprint}>
        <div className="space-y-2.5">
          <DatoIcono icon={Fingerprint} color="#64748b" label="CURP" value={paciente.curp} />
          <DatoIcono icon={Calendar} color="#7c3aed" label="Fecha de nacimiento" value={paciente.date_of_birth} />
          <DatoIcono icon={Cake} color="#db2777" label="Edad" value={years !== null ? `${years} años` : null} />
          <DatoIcono icon={User} color="#0284c7" label="Sexo" value={paciente.sex_display} />
          <DatoIcono icon={Baby} color="#059669" label="Lugar de nacimiento" value={paciente.birthplace} />
        </div>
      </Card>

      <Card title="Datos NOM-004" icon={Heart}>
        <div className="space-y-2.5">
          <DatoIcono icon={Users} color="#e11d48" label="Estado civil" value={paciente.marital_status_display} />
          <DatoIcono icon={GraduationCap} color="#4f46e5" label="Escolaridad" value={paciente.education_display} />
          <DatoIcono icon={Briefcase} color="#b45309" label="Ocupación" value={paciente.occupation} />
          <DatoIcono icon={BookOpen} color="#7c3aed" label="Religión" value={paciente.religion} />
          <DatoIcono icon={Droplet} color="#dc2626" label="Tipo de sangre" value={paciente.blood_type_display} />
          <DatoIcono icon={Tag} color="#0d9488" label="Categoría" value={paciente.category} />
          <DatoIcono
            icon={AlertTriangle} color="#6b7280" label="Defunción"
            value={paciente.is_deceased ? (paciente.deceased_at ? `Finado · ${paciente.deceased_at}` : 'Finado') : null}
          />
        </div>
      </Card>

      {verClinico && (
        <Card title="Notas" icon={StickyNote}>
          <p className="text-sm text-gray-600 leading-relaxed">{paciente.notes || 'Sin notas registradas.'}</p>
        </Card>
      )}
    </div>
  )
}

// ── Modo edición inline ──────────────────────────────────────────────────────

function FichaEditar({
  paciente, verClinico, onCancelar, onGuardado,
}: {
  paciente: PatientOut
  verClinico: boolean
  onCancelar: () => void
  onGuardado: () => void
}) {
  const { form, set, setForm, validar, construirInput } = usePacienteForm(paciente)
  const [errores, setErrores] = useState<string[]>([])
  const actualizar = useUpdatePatient()

  const formatoInvalido = hayErroresFormato(form)

  const guardar = async () => {
    const faltan = validar()
    if (faltan.length) { setErrores(faltan); return }
    if (formatoInvalido) {
      setErrores(['Revisa los campos marcados en rojo antes de guardar.'])
      return
    }
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: paciente.id, input: construirInput() })
      onGuardado()
    } catch (err) {
      setErrores(erroresDePaciente(err))
    }
  }

  return (
    <div className="space-y-4">
      {errores.length > 0 && (
        <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
          <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">
            {errores.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </div>
      )}

      <Card title="Datos personales" icon={User}>
        <CamposDatosPersonales form={form} set={set} setForm={setForm} />
      </Card>

      <Card title="Contacto" icon={Phone}>
        <CamposContacto form={form} set={set} setForm={setForm} />
      </Card>

      <Card title="Domicilio" icon={MapPin}>
        <CamposDomicilio form={form} set={set} setForm={setForm} />
      </Card>

      <Card title="Identificación y datos NOM-004" icon={Fingerprint}>
        <CamposNom004 form={form} set={set} setForm={setForm} />
      </Card>

      {verClinico && (
        <Card title="Notas" icon={StickyNote}>
          <p className={SECCION_LABEL}>Notas</p>
          <textarea className="input resize-none" rows={3} maxLength={4000} value={form.notes} onChange={set('notes')} />
        </Card>
      )}

      {/* Guardar / Cancelar */}
      <div className="flex items-center gap-3">
        <button
          type="button" onClick={onCancelar} disabled={actualizar.isPending}
          className="btn-secondary flex-1 disabled:opacity-60"
        >
          Cancelar
        </button>
        <button
          type="button" onClick={guardar} disabled={actualizar.isPending || formatoInvalido}
          className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
          style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
        >
          {actualizar.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : 'Guardar cambios'}
        </button>
      </div>
    </div>
  )
}

// ── Bloque de alergias (banderas) ────────────────────────────────────────────

function AlergiasBlock({ patientId, puedeEditar }: { patientId: string; puedeEditar: boolean }) {
  const { data: alergias, isLoading, isError } = useAllergies(patientId)
  const crear = useCreateAllergy(patientId)
  const resolver = useResolveAllergy(patientId)
  const [abierto, setAbierto] = useState(false)
  const [form, setForm] = useState<AllergyInput>({ substance: '', reaction: '', severity: '' })
  const [error, setError] = useState('')

  const vigentes = alergias ?? []

  const guardar = async () => {
    if (!form.substance.trim()) { setError('La sustancia es obligatoria.'); return }
    setError('')
    try {
      await crear.mutateAsync({
        substance: form.substance.trim(),
        reaction: form.reaction?.trim() || undefined,
        severity: form.severity || undefined,
      })
      setForm({ substance: '', reaction: '', severity: '' })
      setAbierto(false)
    } catch (err) {
      setError(errorMsg(err))
    }
  }

  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: vigentes.length > 0 ? 'rgba(192,57,43,0.07)' : 'rgba(255,255,255,0.72)',
        backdropFilter: 'blur(14px)',
        border: vigentes.length > 0 ? '1px solid rgba(192,57,43,0.3)' : '1px solid rgba(255,255,255,0.7)',
        boxShadow: '0 6px 20px rgba(60,42,12,0.10)',
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" style={{ color: vigentes.length > 0 ? '#C0392B' : '#C9A227' }} />
          <h4 className="text-xs font-semibold uppercase tracking-wide" style={{ color: vigentes.length > 0 ? '#C0392B' : '#9A7B1E' }}>
            Alergias {vigentes.length > 0 && `(${vigentes.length})`}
          </h4>
        </div>
        {puedeEditar && !abierto && (
          <button
            type="button" onClick={() => setAbierto(true)}
            className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700 hover:text-amber-800"
          >
            <Plus className="w-3.5 h-3.5" /> Agregar
          </button>
        )}
      </div>

      {isLoading && <Cargando texto="Cargando alergias…" />}
      {isError && <p className="text-sm text-red-600">No se pudieron cargar las alergias.</p>}

      {!isLoading && !isError && vigentes.length === 0 && !abierto && (
        <p className="text-sm text-gray-500 italic">Sin alergias registradas.</p>
      )}

      {vigentes.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {vigentes.map((a: Allergy) => {
            const c = severidadColor(a.severity)
            return (
              <div
                key={a.id}
                className="inline-flex items-center gap-2 rounded-full pl-3 pr-2 py-1.5"
                style={{ background: c.bg, border: `1px solid ${c.border}` }}
              >
                <span className="text-sm font-semibold" style={{ color: c.color }}>{a.substance}</span>
                {a.severity_display && (
                  <span className="text-[11px] font-medium" style={{ color: c.color }}>· {a.severity_display}</span>
                )}
                {a.reaction && <span className="text-[11px] text-gray-500">· {a.reaction}</span>}
                {puedeEditar && (
                  <button
                    type="button"
                    title="Resolver alergia"
                    onClick={() => resolver.mutate(a.id)}
                    disabled={resolver.isPending}
                    className="w-5 h-5 rounded-full flex items-center justify-center hover:bg-white/60 transition-colors disabled:opacity-50"
                  >
                    <X className="w-3.5 h-3.5" style={{ color: c.color }} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Formulario de alta */}
      {abierto && puedeEditar && (
        <div className="mt-4 rounded-xl p-4 bg-white/70 space-y-3">
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="grid gap-3" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <div>
              <label className="label">Sustancia / alérgeno</label>
              <input
                className="input" maxLength={150} value={form.substance}
                onChange={e => setForm(f => ({ ...f, substance: e.target.value }))}
                placeholder="Ej. Penicilina"
              />
            </div>
            <div>
              <label className="label">Severidad</label>
              <select
                className="input" value={form.severity}
                onChange={e => setForm(f => ({ ...f, severity: e.target.value as AllergySeverity }))}
              >
                {SEVERITY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="label">Reacción (opcional)</label>
            <input
              className="input" maxLength={255} value={form.reaction}
              onChange={e => setForm(f => ({ ...f, reaction: e.target.value }))}
              placeholder="Ej. Urticaria generalizada"
            />
          </div>
          <div className="flex gap-2 justify-end">
            <button type="button" onClick={() => { setAbierto(false); setError('') }} className="btn-secondary text-xs px-3 py-1.5">
              Cancelar
            </button>
            <button
              type="button" onClick={guardar} disabled={crear.isPending}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-white px-3 py-1.5 rounded-lg disabled:opacity-60"
              style={{ background: '#C9A227' }}
            >
              {crear.isPending ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Guardando…</> : 'Guardar alergia'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Indicaciones para enfermería ──────────────────────────────────────────────

/**
 * Panel destacado (acento teal) con las indicaciones para enfermería más
 * recientes derivadas de las notas de evolución. Solo lectura; se nutre del
 * endpoint GET /expediente/<id>/indicaciones-enfermeria/.
 */
function IndicacionesEnfermeriaBlock({ patientId }: { patientId: string }) {
  const { data, isLoading, isError } = useNursingInstructions(patientId)
  const indicaciones = data ?? []

  const TEAL = '#0E7C7B'

  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: 'rgba(14,124,123,0.06)',
        backdropFilter: 'blur(14px)',
        border: '1px solid rgba(14,124,123,0.28)',
        boxShadow: '0 6px 20px rgba(14,124,123,0.10)',
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <ClipboardList className="w-4 h-4" style={{ color: TEAL }} />
        <h4 className="text-xs font-semibold uppercase tracking-wide" style={{ color: TEAL }}>
          Indicaciones para Enfermería {indicaciones.length > 0 && `(${indicaciones.length})`}
        </h4>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-4 text-sm" style={{ color: TEAL }}>
          <Loader2 className="w-4 h-4 animate-spin" /> Cargando…
        </div>
      ) : isError ? (
        <p className="text-sm text-red-600">No se pudieron cargar las indicaciones.</p>
      ) : indicaciones.length === 0 ? (
        <p className="text-sm text-gray-400 italic">Sin indicaciones para enfermería.</p>
      ) : (
        <div className="space-y-2.5">
          {indicaciones.map(ind => (
            <div
              key={ind.id}
              className="rounded-xl px-3 py-2.5"
              style={{ background: 'rgba(255,255,255,0.7)', borderLeft: `3px solid ${TEAL}` }}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-[11px] font-semibold" style={{ color: TEAL }}>{ind.doctor}</span>
                <span className="text-[11px] text-gray-400">{formatFechaHora(ind.fecha)}</span>
              </div>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{ind.indicaciones}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
