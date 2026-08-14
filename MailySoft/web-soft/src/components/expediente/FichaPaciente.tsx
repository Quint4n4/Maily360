/**
 * FichaPaciente — columna fija (izquierda) del expediente.
 *
 * Orden fijo, de lo que no se puede pasar por alto a lo que se consulta de vez
 * en cuando:
 *   ① Alergias        — hasta arriba, en rojo (solo roles clínicos).
 *   ② Datos generales — rejilla de 2 columnas, VISIBLE sin desplegar.
 *   ③ Próxima consulta.
 *   ④ Bloques plegables: Indicaciones para
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
import {
  Phone, Mail, Fingerprint, StickyNote, User, CalendarClock,
  AlertTriangle, Plus, X, Loader2, MapPin, ChevronDown,
  Droplet, GraduationCap, Briefcase, Cake, Calendar, Tag, Users, Cross, Baby,
  Pencil, AlertCircle, ClipboardList,
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
import {
  CamposContacto, CamposDatosPersonales, CamposDomicilio, CamposNom004,
  SECCION_LABEL, erroresDePaciente, hayErroresFormato, usePacienteForm,
} from '../contactos/pacienteForm'

/**
 * Color de la bandera de alergia: SIEMPRE rojo, sea cual sea la severidad.
 *
 * Antes las leves salían en ámbar. Se ve mejor sobre el papel, pero en la
 * pantalla parte la lista en dos y el ojo lee "esto es grave / esto no",
 * cuando lo que hay que leer es "este paciente es alérgico". La severidad no
 * desaparece: viaja en el texto de la severidad y en el tooltip.
 */
function severidadColor(_sev: AllergySeverity): { bg: string; border: string; color: string } {
  return { bg: 'var(--peligro-tinte)', border: 'var(--peligro-borde)', color: 'var(--peligro)' }
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

      {/* ④ Bloques plegables (lo que se consulta de vez en cuando).
          La Historia clínica ya no vive aquí: pasó a "Secciones del expediente",
          que es donde está el resto del expediente. */}
      {verClinico && (
        <>
          <IndicacionesEnfermeriaBlock patientId={paciente.id} />
          <BloquePlegable titulo="Observaciones" icon={StickyNote}>
            <p className="text-sm text-cuerpo leading-relaxed whitespace-pre-wrap">
              {paciente.notes || 'Sin observaciones registradas.'}
            </p>
          </BloquePlegable>
        </>
      )}

    </div>
  )
}

// ── Bloques plegables de la columna ──────────────────────────────────────────

const BLOQUE_STYLE = {
  background: 'var(--superficie)',
  border: '1px solid var(--borde)',
  boxShadow: '0 1px 2px rgba(10,25,49,0.06), 0 4px 12px rgba(10,25,49,0.05)',
} as const

/**
 * Bloque que se abre/cierra en su sitio. El contador va en el encabezado para
 * que se sepa si hay contenido SIN necesidad de desplegarlo.
 */
function BloquePlegable({
  titulo, icon: Icon, contador, color = 'var(--suave)', abiertoInicial = false, children,
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
        className="w-full flex items-center justify-between gap-2 px-5 py-4 text-left hover:bg-accion-tinte transition-colors"
      >
        <span className="flex items-center gap-2 min-w-0">
          <Icon className="w-4 h-4 shrink-0" style={{ color }} />
          <span className="text-xs font-semibold uppercase tracking-wide truncate" style={{ color }}>
            {titulo}
          </span>
          {contador !== undefined && contador > 0 && (
            <span
              className="text-[11px] font-bold px-1.5 rounded-full shrink-0"
              style={{ background: 'var(--accion-tinte)', color: 'var(--accion)' }}
            >
              {contador}
            </span>
          )}
        </span>
        <ChevronDown
          className={`w-4 h-4 shrink-0 text-suave transition-transform ${abierto ? 'rotate-180' : ''}`}
        />
      </button>
      {abierto && <div className="px-5 pb-5">{children}</div>}
    </div>
  )
}

// ── Datos generales (siempre visibles, sin desplegar) ───────────────────────

/**
 * Una celda etiqueta–valor de la rejilla de datos generales, con el icono de
 * color que identifica al campo (los mismos de la ficha anterior: el color
 * ayuda a encontrar el dato sin leer la etiqueta).
 */
/**
 * Una celda etiqueta–valor de "Datos generales".
 *
 * NO acepta color: aquí estaban los 13 iconos en 13 colores distintos (pastel
 * rosa para "Edad", birrete morado para "Escolaridad"…). Ninguno significaba
 * nada y le robaban fuerza al rojo de las alergias, que sí significa algo.
 */
function Dato({
  icon: Icon, label, value, full = false, sinEtiqueta = false,
}: {
  icon: LucideIcon
  label: string
  value: string | null | undefined
  full?: boolean
  /**
   * Oculta la etiqueta y la deja en el tooltip: el icono orienta y el valor
   * habla por sí mismo. Con esto la ficha entra sin desplazar, que es el
   * objetivo de toda la reestructuración.
   *
   * El precio es que el icono pasa a ser el ÚNICO indicio visible de qué campo
   * es, así que cada uno tiene que ser inconfundible (por eso religión lleva
   * una cruz y no un libro). Donde el icono no basta queda el tooltip, y para
   * lectores de pantalla la etiqueta sigue leyéndose.
   */
  sinEtiqueta?: boolean
}) {
  // Sin etiqueta y sin valor, la fila sería un icono y un guion: ocupa alto y
  // no dice nada. Con etiqueta sí valía la pena ("CURP —" informa que falta).
  if (sinEtiqueta && !value) return null

  return (
    <div
      className={`flex gap-2 min-w-0 ${sinEtiqueta ? 'items-center' : 'items-start'} ${full ? 'col-span-2' : ''}`}
      title={sinEtiqueta ? label : undefined}
    >
      <Icon className={`w-4 h-4 shrink-0 text-tenue ${sinEtiqueta ? '' : 'mt-0.5'}`} />
      <div className="min-w-0">
        {sinEtiqueta
          /* Sin etiqueta a la vista, un lector de pantalla solo oiría el valor
             suelto; así sigue leyendo "Edad: 26 años". */
          ? <span className="sr-only">{label}: </span>
          : <p className="text-[10px] font-semibold uppercase tracking-wide text-suave">{label}</p>}
        <p className="text-sm text-cuerpo break-words">{value || '—'}</p>
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
  /*
   * Los cuatro datos de consulta quedan siempre a la vista; el resto de la ficha
   * NOM-004 se pliega aquí. Antes solo se llegaba a ellos por "Editar", y ese es
   * mal camino para CONSULTAR: quien quiere mirar el CURP no piensa en editar,
   * piensa que el dato se perdió.
   */
  const [verTodo, setVerTodo] = useState(false)

  const domicilio = [paciente.address_street, paciente.address_neighborhood, paciente.city, paciente.state]
    .filter(Boolean)
    .join(', ')

  // Solo los números: la etiqueta ("casa", "trabajo") alarga la línea y no
  // cambia nada de lo que se hace con el teléfono, que es marcarlo.
  const telefono = paciente.phone_secondary
    ? `${paciente.phone || '—'} · ${paciente.phone_secondary}`
    : paciente.phone

  return (
    <Card
      title="Datos generales"
      icon={User}
      action={puedeEditar && (
        <button
          type="button"
          onClick={onEditar}
          className="inline-flex items-center gap-1 text-xs font-semibold text-accion hover:text-accion-hover"
        >
          <Pencil className="w-3.5 h-3.5" /> Editar
        </button>
      )}
    >
      {/*
        Solo los cuatro datos que se consultan de un vistazo en consulta.
        Antes había 13 campos (CURP, escolaridad, religión, lugar de nacimiento,
        domicilio…) que empujaban el resto del expediente fuera de la pantalla y
        que casi nunca se miran en el momento de atender. Siguen todos ahí: el
        botón "Editar" abre la ficha completa.
      */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Dato sinEtiqueta icon={Cake} label="Edad" value={years !== null ? `${years} años` : null} />
        <Dato sinEtiqueta icon={User} label="Sexo" value={paciente.sex_display} />
        <Dato sinEtiqueta icon={Droplet} label="Tipo de sangre" value={paciente.blood_type_display} />
        <Dato sinEtiqueta icon={Phone} label="Teléfono" value={telefono} />
        {/* La defunción no es un dato más: cambia por completo cómo se lee el
            expediente, así que se queda aunque el resto se haya recortado. */}
        {paciente.is_deceased && (
          <Dato
            sinEtiqueta icon={AlertTriangle} label="Defunción"
            value={paciente.deceased_at ? `Finado · ${paciente.deceased_at}` : 'Finado'}
            full
          />
        )}

        {/* Resto de la ficha, plegado */}
        {verTodo && (
          <>
            <Dato sinEtiqueta icon={Calendar} label="Nacimiento" value={paciente.date_of_birth} />
            <Dato sinEtiqueta icon={Users} label="Estado civil" value={paciente.marital_status_display} />
            <Dato sinEtiqueta icon={Briefcase} label="Ocupación" value={paciente.occupation} />
            <Dato sinEtiqueta icon={GraduationCap} label="Escolaridad" value={paciente.education_display} />
            <Dato sinEtiqueta icon={Cross} label="Religión" value={paciente.religion} />
            <Dato sinEtiqueta icon={Baby} label="Lugar de nacimiento" value={paciente.birthplace} />
            <Dato sinEtiqueta icon={Fingerprint} label="CURP" value={paciente.curp} full />
            <Dato sinEtiqueta icon={Mail} label="Correo" value={paciente.email} full />
            <Dato
              sinEtiqueta icon={MapPin} label="Domicilio"
              value={domicilio ? `${domicilio}${paciente.postal_code ? ` · CP ${paciente.postal_code}` : ''}` : null}
              full
            />
            {paciente.category && (
              <Dato sinEtiqueta icon={Tag} label="Categoría" value={paciente.category} full />
            )}
          </>
        )}
      </div>

      <button
        type="button"
        onClick={() => setVerTodo(v => !v)}
        aria-expanded={verTodo}
        className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-accion hover:text-accion-hover"
      >
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${verTodo ? 'rotate-180' : ''}`} />
        {verTodo ? 'Ver menos' : 'Ver todos los datos'}
      </button>
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
        <p className="text-sm text-suave italic">Cargando…</p>
      ) : proxima ? (
        <div>
          <p className="text-base font-bold text-tinta">{formatFechaHora(proxima.starts_at)}</p>
          <p className="text-sm text-suave mt-0.5">
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
        <p className="text-sm text-suave italic">Sin cita próxima.</p>
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
          className="btn-primary flex-1 disabled:opacity-60"
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
  /*
   * Con muchas alergias el bloque crecía sin tope y empujaba el resto del
   * expediente fuera de pantalla. Se muestran las primeras y el resto se pliega
   * tras un "+N más": el número ya avisa de que hay más, que es lo que importa
   * para no dar nada por sentado.
   */
  const TOPE = 3
  const [verTodas, setVerTodas] = useState(false)

  const vigentes = alergias ?? []
  const visibles = verTodas ? vigentes : vigentes.slice(0, TOPE)
  const ocultas = vigentes.length - visibles.length

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
      className={`rounded-2xl p-5 border shadow-card ${
        vigentes.length > 0
          ? 'bg-peligro-tinte border-peligro-borde'
          : 'bg-superficie border-borde'}`}
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className={`w-4 h-4 ${vigentes.length > 0 ? 'text-peligro' : 'text-borde-fuerte'}`} />
          <h4 className={`text-xs font-semibold uppercase tracking-wide ${
            vigentes.length > 0 ? 'text-peligro' : 'text-suave'}`}>
            Alergias {vigentes.length > 0 && `(${vigentes.length})`}
          </h4>
        </div>
        {puedeEditar && !abierto && (
          <button
            type="button" onClick={() => setAbierto(true)}
            className="inline-flex items-center gap-1 text-xs font-semibold text-accion hover:text-accion-hover"
          >
            <Plus className="w-3.5 h-3.5" /> Agregar
          </button>
        )}
      </div>

      {isLoading && <Cargando texto="Cargando alergias…" />}
      {isError && <p className="text-sm text-peligro">No se pudieron cargar las alergias.</p>}

      {!isLoading && !isError && vigentes.length === 0 && !abierto && (
        <p className="text-sm text-suave italic">Sin alergias registradas.</p>
      )}

      {vigentes.length > 0 && (
        <ul className="space-y-0.5">
          {visibles.map((a: Allergy) => {
            const c = severidadColor(a.severity)
            // La severidad ya no ocupa una palabra: la lleva el TONO (rojo para
            // severa/moderada, ámbar para leve) y el texto al pasar el cursor.
            const detalle = [a.severity_display, a.reaction].filter(Boolean).join(' · ')
            return (
              <li key={a.id} className="group/al flex items-baseline gap-1.5 min-w-0">
                <span
                  className="text-sm font-semibold shrink-0"
                  style={{ color: c.color }}
                  title={detalle ? `${a.substance} · ${detalle}` : a.substance}
                >
                  {a.substance}
                </span>
                {a.reaction && (
                  <span className="text-xs text-suave truncate">· {a.reaction}</span>
                )}
                {puedeEditar && (
                  <button
                    type="button"
                    title="Resolver alergia"
                    onClick={() => resolver.mutate(a.id)}
                    disabled={resolver.isPending}
                    aria-label={`Resolver alergia a ${a.substance}`}
                    className="acciones-hover ml-auto shrink-0 w-5 h-5 rounded-full flex items-center justify-center
                               opacity-0 group-hover/al:opacity-100 focus:opacity-100 transition-opacity
                               hover:bg-superficie disabled:opacity-50"
                  >
                    <X className="w-3.5 h-3.5" style={{ color: c.color }} />
                  </button>
                )}
              </li>
            )
          })}

          {(ocultas > 0 || verTodas) && (
            <li>
              <button
                type="button"
                onClick={() => setVerTodas(v => !v)}
                className="inline-flex items-center gap-1 text-xs font-semibold text-peligro hover:underline"
              >
                {verTodas
                  ? <><ChevronDown className="w-3.5 h-3.5 rotate-180" /> Ver menos</>
                  : <><ChevronDown className="w-3.5 h-3.5" /> +{ocultas} más</>}
              </button>
            </li>
          )}
        </ul>
      )}

      {/* Formulario de alta */}
      {abierto && puedeEditar && (
        <div className="mt-4 rounded-xl p-4 bg-white/70 space-y-3">
          {error && <p className="text-xs text-peligro">{error}</p>}
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
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-white bg-accion hover:bg-accion-hover px-3 py-1.5 rounded-lg transition-colors disabled:opacity-60"
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

  return (
    <BloquePlegable
      titulo="Indicaciones para enfermería"
      icon={ClipboardList}
      color={'var(--suave)'}
      contador={indicaciones.length}
      abiertoInicial={indicaciones.length > 0}
      key={`enf-${indicaciones.length > 0}`}
    >
      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-4 text-sm text-accion">
          <Loader2 className="w-4 h-4 animate-spin" /> Cargando…
        </div>
      ) : isError ? (
        <p className="text-sm text-peligro">No se pudieron cargar las indicaciones.</p>
      ) : indicaciones.length === 0 ? (
        <p className="text-sm text-suave italic">Sin indicaciones para enfermería.</p>
      ) : (
        <div className="space-y-2.5">
          {indicaciones.map(ind => (
            <div
              key={ind.id}
              className="rounded-xl px-3 py-2.5 bg-superficie-sutil border-l-[3px] border-borde-fuerte" 
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-[11px] font-semibold text-accion">{ind.doctor}</span>
                <span className="text-[11px] text-suave">{formatFechaHora(ind.fecha)}</span>
              </div>
              <p className="text-sm text-cuerpo whitespace-pre-wrap">{ind.indicaciones}</p>
            </div>
          ))}
        </div>
      )}
    </BloquePlegable>
  )
}
