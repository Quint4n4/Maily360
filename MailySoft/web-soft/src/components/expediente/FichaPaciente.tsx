/**
 * FichaPaciente — columna fija (izquierda) del expediente.
 *
 * Orden fijo, de lo que no se puede pasar por alto a lo que se consulta de vez
 * en cuando:
 *   ① Alergias        — hasta arriba, en rojo (solo roles clínicos).
 *   ② Datos generales — rejilla de 2 columnas, VISIBLE sin desplegar.
 *   ③ Próxima consulta.
 *   ④ Bloques plegables: Historia clínica (abre modal), Indicaciones para
 *      enfermería y Observaciones.
 *
 * Antes ② eran tres tarjetas apiladas (Contacto / Identificación / NOM-004) que
 * empujaban todo lo demás fuera de la pantalla.
 *
 * Edición INLINE: si el usuario puede editar (puedeEditar), el botón "Editar" de
 * Datos generales convierte la columna en el formulario completo (reusando los
 * grupos y la lógica del modal grande vía ../contactos/pacienteForm). Las
 * alergias NO entran en este modo (siguen con su propio alta/resolver).
 */

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Phone, Mail, Fingerprint, StickyNote, User, CalendarClock,
  AlertTriangle, Plus, X, Loader2, MapPin, ChevronDown, ChevronRight,
  Droplet, GraduationCap, Briefcase, Cake, Calendar, Tag, Users, BookOpen, Baby,
  Pencil, AlertCircle, ClipboardList, FileHeart,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Allergy, AllergyInput, AllergySeverity } from '../../types/expediente'
import type { Appointment } from '../../types/agenda'
import {
  useAllergies, useCreateAllergy, useNursingInstructions, useResolveAllergy,
} from '../../hooks/expediente'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import { formatFechaHora } from '../../lib/fecha'
import { useUpdatePatient } from '../../hooks/pacientes'
import { edad } from '../../lib/paciente'
import { errorMsg } from '../../lib/apiErrors'
import { Card, Cargando, ESTADOS_CITA_INACTIVOS, estadoCitaChip, SEVERITY_OPTIONS } from './ui'
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

  // En modo edición la columna se convierte en el formulario completo; los
  // bloques de consulta (alergias, próxima cita, plegables) se ocultan para no
  // competir con el guardado.
  if (editando) {
    return (
      <FichaEditar
        paciente={paciente}
        verClinico={verClinico}
        onCancelar={() => setEditando(false)}
        onGuardado={() => setEditando(false)}
      />
    )
  }

  return (
    <div className="space-y-4">
      {/* ① Alergias — siempre hasta arriba: es lo que no se puede pasar por alto */}
      {verClinico && <AlergiasBlock patientId={paciente.id} puedeEditar={puedeEditarClinico} />}

      {/* ② Datos generales — visibles de entrada, sin desplegar */}
      <DatosGenerales
        paciente={paciente}
        puedeEditar={puedeEditar}
        onEditar={() => setEditando(true)}
      />

      {/* ③ Próxima consulta */}
      <ProximaConsulta patientId={paciente.id} />

      {/* ④ Bloques plegables (lo que se consulta de vez en cuando) */}
      {verClinico && (
        <>
          <BloqueEnlace
            titulo="Historia clínica"
            icon={FileHeart}
            descripcion="Antecedentes, padecimiento actual y exploración basal"
            onClick={() => setHcAbierta(true)}
          />
          <IndicacionesEnfermeriaBlock patientId={paciente.id} />
          <BloquePlegable titulo="Observaciones" icon={StickyNote}>
            <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">
              {paciente.notes || 'Sin observaciones registradas.'}
            </p>
          </BloquePlegable>
        </>
      )}

      {verClinico && (
        <HistoriaClinicaModal
          paciente={paciente}
          abierto={hcAbierta}
          puedeEditar={puedeEditarClinico}
          onClose={() => setHcAbierta(false)}
        />
      )}
    </div>
  )
}

// ── Bloques plegables de la columna ──────────────────────────────────────────

const BLOQUE_STYLE = {
  background: 'rgba(255,255,255,0.72)',
  backdropFilter: 'blur(14px)',
  border: '1px solid rgba(255,255,255,0.7)',
  boxShadow: '0 6px 20px rgba(60,42,12,0.10)',
} as const

/**
 * Bloque que se abre/cierra en su sitio. El contador va en el encabezado para
 * que se sepa si hay contenido SIN necesidad de desplegarlo.
 */
function BloquePlegable({
  titulo, icon: Icon, contador, color = '#9A7B1E', abiertoInicial = false, children,
}: {
  titulo: string
  icon: LucideIcon
  contador?: number
  color?: string
  abiertoInicial?: boolean
  children: React.ReactNode
}) {
  const [abierto, setAbierto] = useState(abiertoInicial)
  return (
    <div className="rounded-2xl overflow-hidden" style={BLOQUE_STYLE}>
      <button
        type="button"
        onClick={() => setAbierto(a => !a)}
        aria-expanded={abierto}
        className="w-full flex items-center justify-between gap-2 px-5 py-4 text-left hover:bg-white/50 transition-colors"
      >
        <span className="flex items-center gap-2 min-w-0">
          <Icon className="w-4 h-4 shrink-0" style={{ color }} />
          <span className="text-xs font-semibold uppercase tracking-wide truncate" style={{ color }}>
            {titulo}
          </span>
          {contador !== undefined && contador > 0 && (
            <span
              className="text-[11px] font-bold px-1.5 rounded-full shrink-0"
              style={{ background: 'rgba(201,162,39,0.16)', color: '#9A7B1E' }}
            >
              {contador}
            </span>
          )}
        </span>
        <ChevronDown
          className={`w-4 h-4 shrink-0 text-gray-400 transition-transform ${abierto ? 'rotate-180' : ''}`}
        />
      </button>
      {abierto && <div className="px-5 pb-5">{children}</div>}
    </div>
  )
}

/** Bloque que en vez de desplegarse abre una pantalla aparte (modal). */
function BloqueEnlace({
  titulo, icon: Icon, descripcion, onClick,
}: {
  titulo: string
  icon: LucideIcon
  descripcion: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center justify-between gap-2 rounded-2xl px-5 py-4 text-left hover:bg-white/50 transition-colors"
      style={BLOQUE_STYLE}
    >
      <span className="flex items-center gap-2 min-w-0">
        <Icon className="w-4 h-4 shrink-0" style={{ color: '#9A7B1E' }} />
        <span className="min-w-0">
          <span className="block text-xs font-semibold uppercase tracking-wide" style={{ color: '#9A7B1E' }}>
            {titulo}
          </span>
          <span className="block text-[11px] text-gray-400 truncate">{descripcion}</span>
        </span>
      </span>
      <ChevronRight className="w-4 h-4 shrink-0 text-gray-400" />
    </button>
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

// ── Datos generales (siempre visibles, sin desplegar) ───────────────────────

/**
 * Una celda etiqueta–valor de la rejilla de datos generales, con el icono de
 * color que identifica al campo (los mismos de la ficha anterior: el color
 * ayuda a encontrar el dato sin leer la etiqueta).
 */
function Dato({
  icon: Icon, color, label, value, full = false,
}: {
  icon: LucideIcon
  color: string
  label: string
  value: string | null | undefined
  full?: boolean
}) {
  return (
    <div className={`flex items-start gap-2 min-w-0 ${full ? 'col-span-2' : ''}`}>
      <Icon className="w-4 h-4 shrink-0 mt-0.5" style={{ color }} />
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
        <p className="text-sm text-gray-800 break-words">{value || '—'}</p>
      </div>
    </div>
  )
}

/**
 * Identificación + contacto + datos NOM-004 en una sola rejilla de dos columnas.
 * Antes eran tres tarjetas apiladas que empujaban el resto de la columna hacia
 * abajo; el médico necesita esto de un vistazo al abrir el expediente.
 */
function DatosGenerales({
  paciente, puedeEditar, onEditar,
}: {
  paciente: PatientOut
  puedeEditar: boolean
  onEditar: () => void
}) {
  const years = edad(paciente.date_of_birth ?? '')

  const domicilio = [paciente.address_street, paciente.address_neighborhood, paciente.city, paciente.state]
    .filter(Boolean)
    .join(', ')

  const telefono = paciente.phone_secondary
    ? `${paciente.phone || '—'} · ${paciente.phone_secondary}${paciente.phone_label ? ` (${paciente.phone_label})` : ''}`
    : paciente.phone

  return (
    <Card
      title="Datos generales"
      icon={User}
      action={puedeEditar && (
        <button
          type="button"
          onClick={onEditar}
          className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700 hover:text-amber-800"
        >
          <Pencil className="w-3.5 h-3.5" /> Editar
        </button>
      )}
    >
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Dato icon={Cake} color="#db2777" label="Edad" value={years !== null ? `${years} años` : null} />
        <Dato icon={Calendar} color="#7c3aed" label="Nacimiento" value={paciente.date_of_birth} />
        <Dato icon={User} color="#0284c7" label="Sexo" value={paciente.sex_display} />
        <Dato icon={Users} color="#e11d48" label="Estado civil" value={paciente.marital_status_display} />
        <Dato icon={Briefcase} color="#b45309" label="Ocupación" value={paciente.occupation} />
        <Dato icon={Droplet} color="#dc2626" label="Tipo de sangre" value={paciente.blood_type_display} />
        <Dato icon={GraduationCap} color="#4f46e5" label="Escolaridad" value={paciente.education_display} />
        <Dato icon={BookOpen} color="#7c3aed" label="Religión" value={paciente.religion} />
        <Dato icon={Fingerprint} color="#64748b" label="CURP" value={paciente.curp} full />
        <Dato icon={Phone} color="#0891b2" label="Teléfono" value={telefono} full />
        <Dato icon={Mail} color="#2563eb" label="Correo" value={paciente.email} full />
        <Dato icon={Baby} color="#059669" label="Lugar de nacimiento" value={paciente.birthplace} full />
        <Dato
          icon={MapPin} color="#ea580c" label="Domicilio"
          value={domicilio ? `${domicilio}${paciente.postal_code ? ` · CP ${paciente.postal_code}` : ''}` : null}
          full
        />
        {paciente.category && (
          <Dato icon={Tag} color="#0d9488" label="Categoría" value={paciente.category} full />
        )}
        {paciente.is_deceased && (
          <Dato
            icon={AlertTriangle} color="#6b7280" label="Defunción"
            value={paciente.deceased_at ? `Finado · ${paciente.deceased_at}` : 'Finado'}
            full
          />
        )}
      </div>
    </Card>
  )
}

// ── Próxima consulta ─────────────────────────────────────────────────────────

/**
 * Próxima cita agendada del paciente. Misma regla que la sección de citas: la
 * más cercana que no esté atendida/cancelada/no-asistió.
 */
function ProximaConsulta({ patientId }: { patientId: string }) {
  const { data, isLoading } = useAppointmentsForPatient(patientId)
  const citas: Appointment[] = data?.results ?? []
  const proxima =
    [...citas]
      .filter(c => !ESTADOS_CITA_INACTIVOS.has(c.status))
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0] ?? null

  return (
    <Card title="Próxima consulta" icon={CalendarClock}>
      {isLoading ? (
        <p className="text-sm text-gray-400 italic">Cargando…</p>
      ) : proxima ? (
        <div>
          <p className="text-base font-bold text-gray-900">{formatFechaHora(proxima.starts_at)}</p>
          <p className="text-sm text-gray-500 mt-0.5">
            {proxima.doctor.full_name}{proxima.consultorio ? ` · ${proxima.consultorio.name}` : ''}
          </p>
          <span
            className="badge mt-2"
            style={{
              background: estadoCitaChip(proxima.status).bg,
              color: estadoCitaChip(proxima.status).color,
            }}
          >
            {proxima.status_display}
          </span>
        </div>
      ) : (
        <p className="text-sm text-gray-400 italic">Sin cita próxima.</p>
      )}
    </Card>
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
 * Indicaciones para enfermería más recientes derivadas de las notas de
 * evolución. Solo lectura; se nutre del endpoint
 * GET /expediente/<id>/indicaciones-enfermeria/.
 *
 * Es un bloque plegable: el contador del encabezado avisa si hay indicaciones
 * pendientes de leer sin ocupar la columna cuando no las hay. Se abre solo
 * cuando existen, para que enfermería no tenga que buscarlas.
 */
function IndicacionesEnfermeriaBlock({ patientId }: { patientId: string }) {
  const { data, isLoading, isError } = useNursingInstructions(patientId)
  const indicaciones = data ?? []

  const TEAL = '#0E7C7B'

  return (
    <BloquePlegable
      titulo="Indicaciones para enfermería"
      icon={ClipboardList}
      color={TEAL}
      contador={indicaciones.length}
      abiertoInicial={indicaciones.length > 0}
      key={`enf-${indicaciones.length > 0}`}
    >
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
    </BloquePlegable>
  )
}
