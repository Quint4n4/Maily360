/**
 * pacienteForm — lógica y campos COMPARTIDOS para editar un paciente.
 *
 * Única fuente de verdad para: estado del formulario, precarga desde el paciente,
 * selects/choices, validaciones, construcción del PATCH y mapeo de errores 400 de DRF.
 *
 * Lo consumen tanto el modal grande (EditarPacienteDrawer, edición desde la lista)
 * como la edición inline dentro de la ficha del expediente (FichaPaciente). Así no
 * se duplica ni la lógica ni los campos.
 */

import { useState, useEffect } from 'react'
import type { ChangeEvent } from 'react'
import { Check } from 'lucide-react'
import { erroresDe } from '../../lib/apiErrors'
import type {
  BloodType, Education, MaritalStatus, PatientOut, PatientUpdateInput, Sex,
} from '../../types/paciente'
import { useCategories } from '../../hooks/clinica'
import { BLOOD_OPTIONS, EDUCATION_OPTIONS, MARITAL_OPTIONS } from '../expediente/ui'
import {
  MSG, errorDeCampo, esCPValido, esCurpValido, esEmailValido, esTelefonoValido,
} from '../../lib/validacion'

export const SECCION_LABEL = 'text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-3'

/** Forma del estado del formulario (todo en strings, como los inputs). */
export interface PacienteFormState {
  first_name: string
  paternal_surname: string
  maternal_surname: string
  date_of_birth: string
  sex: '' | Sex
  phone: string
  phone_secondary: string
  phone_label: string
  email: string
  curp: string
  notes: string
  // Domicilio
  address_street: string
  address_neighborhood: string
  city: string
  state: string
  postal_code: string
  // NOM-004
  birthplace: string
  marital_status: MaritalStatus
  education: Education
  occupation: string
  religion: string
  blood_type: BloodType
  category: string
  /** IDs de las etiquetas del catálogo asignadas al paciente. */
  category_ids: string[]
  is_deceased: boolean
  deceased_at: string
  custom_consultation_fee: string
}

const VACIO: PacienteFormState = {
  first_name: '', paternal_surname: '', maternal_surname: '',
  date_of_birth: '', sex: '', phone: '', phone_secondary: '', phone_label: '',
  email: '', curp: '', notes: '',
  address_street: '', address_neighborhood: '', city: '', state: '', postal_code: '',
  birthplace: '', marital_status: '', education: '', occupation: '', religion: '',
  blood_type: '', category: '', category_ids: [], is_deceased: false, deceased_at: '', custom_consultation_fee: '',
}

/** Pasa los datos del paciente al estado editable del formulario. */
function desdePaciente(p: PatientOut): PacienteFormState {
  return {
    first_name: p.first_name,
    paternal_surname: p.paternal_surname,
    maternal_surname: p.maternal_surname,
    date_of_birth: p.date_of_birth ?? '',
    sex: p.sex,
    phone: p.phone,
    phone_secondary: p.phone_secondary,
    phone_label: p.phone_label,
    email: p.email,
    curp: p.curp,
    notes: p.notes,
    address_street: p.address_street,
    address_neighborhood: p.address_neighborhood,
    city: p.city,
    state: p.state,
    postal_code: p.postal_code,
    birthplace: p.birthplace,
    marital_status: p.marital_status,
    education: p.education,
    occupation: p.occupation,
    religion: p.religion,
    blood_type: p.blood_type,
    category: p.category,
    category_ids: p.categories.map(c => c.id),
    is_deceased: p.is_deceased,
    deceased_at: p.deceased_at ?? '',
    custom_consultation_fee: p.custom_consultation_fee ?? '',
  }
}

/** Setter genérico de un campo de texto/select (devuelve un onChange). */
export type FieldSetter = (k: keyof PacienteFormState) => (
  e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
) => void

export interface UsePacienteFormResult {
  form: PacienteFormState
  setForm: React.Dispatch<React.SetStateAction<PacienteFormState>>
  set: FieldSetter
  /** Valida los campos obligatorios; devuelve la lista de mensajes (vacía si OK). */
  validar: () => string[]
  /** Construye el cuerpo del PATCH a partir del estado actual. */
  construirInput: () => PatientUpdateInput
  /** Recarga el formulario desde el paciente (descarta cambios). */
  reset: () => void
}

/**
 * Hook con el estado del formulario de edición de un paciente.
 * Precarga desde `paciente` y se re-sincroniza cuando cambia.
 */
export function usePacienteForm(paciente: PatientOut | null): UsePacienteFormResult {
  const [form, setForm] = useState<PacienteFormState>(
    paciente ? desdePaciente(paciente) : VACIO,
  )

  useEffect(() => {
    setForm(paciente ? desdePaciente(paciente) : VACIO)
  }, [paciente])

  const set: FieldSetter = k => e =>
    setForm(prev => ({ ...prev, [k]: e.target.value }))

  const reset = () => setForm(paciente ? desdePaciente(paciente) : VACIO)

  const validar = (): string[] => {
    const faltan: string[] = []
    if (!form.first_name.trim()) faltan.push('El nombre es obligatorio.')
    if (!form.paternal_surname.trim()) faltan.push('El apellido paterno es obligatorio.')
    if (!form.date_of_birth) faltan.push('La fecha de nacimiento es obligatoria.')
    if (!form.sex) faltan.push('El sexo es obligatorio.')
    if (!form.phone.trim()) faltan.push('El teléfono es obligatorio.')
    return faltan
  }

  const construirInput = (): PatientUpdateInput => {
    const feeStr = form.custom_consultation_fee.trim()
    const fee = feeStr === '' ? null : Number(feeStr)
    return {
      first_name: form.first_name.trim(),
      paternal_surname: form.paternal_surname.trim(),
      maternal_surname: form.maternal_surname.trim(),
      date_of_birth: form.date_of_birth,
      sex: form.sex as Sex,
      phone: form.phone.trim(),
      curp: form.curp.trim(),
      email: form.email.trim(),
      notes: form.notes.trim(),
      // Domicilio + NOM-004
      address_street: form.address_street.trim(),
      address_neighborhood: form.address_neighborhood.trim(),
      city: form.city.trim(),
      state: form.state.trim(),
      postal_code: form.postal_code.trim(),
      birthplace: form.birthplace.trim(),
      marital_status: form.marital_status,
      education: form.education,
      occupation: form.occupation.trim(),
      religion: form.religion.trim(),
      blood_type: form.blood_type,
      phone_secondary: form.phone_secondary.trim(),
      phone_label: form.phone_label.trim(),
      category: form.category.trim(),
      category_ids: form.category_ids,
      is_deceased: form.is_deceased,
      deceased_at: form.is_deceased ? (form.deceased_at || null) : null,
      custom_consultation_fee: fee !== null && Number.isNaN(fee) ? null : fee,
    }
  }

  return { form, setForm, set, validar, construirInput, reset }
}

/** Mensajes de error legibles para los formularios de paciente (usa la canónica). */
export function erroresDePaciente(err: unknown): string[] {
  return erroresDe(err, 'No se pudo guardar.')
}

/**
 * Errores de FORMATO (solo UX) de los campos del formulario de paciente.
 * Replica los regex del backend (la autoridad). Un campo vacío NO marca error
 * (la obligatoriedad se maneja en `validar`). Devuelve un mapa campo→mensaje
 * solo con los campos inválidos; vacío = todo OK.
 */
export type ErroresFormatoPaciente = Partial<Record<
  'phone' | 'phone_secondary' | 'email' | 'postal_code' | 'curp', string
>>

export function erroresFormatoPaciente(form: PacienteFormState): ErroresFormatoPaciente {
  const e: ErroresFormatoPaciente = {}
  const phone = errorDeCampo(form.phone, esTelefonoValido, MSG.telefono)
  if (phone) e.phone = phone
  const phone2 = errorDeCampo(form.phone_secondary, esTelefonoValido, MSG.telefono)
  if (phone2) e.phone_secondary = phone2
  const email = errorDeCampo(form.email, esEmailValido, MSG.email)
  if (email) e.email = email
  const cp = errorDeCampo(form.postal_code, esCPValido, MSG.cp)
  if (cp) e.postal_code = cp
  const curp = errorDeCampo(form.curp, esCurpValido, MSG.curp)
  if (curp) e.curp = curp
  return e
}

/** ¿Hay algún error de formato? (para deshabilitar Guardar). */
export function hayErroresFormato(form: PacienteFormState): boolean {
  return Object.keys(erroresFormatoPaciente(form)).length > 0
}

// ── Secciones de campos reutilizables ────────────────────────────────────────

interface CamposProps {
  form: PacienteFormState
  set: FieldSetter
  setForm: React.Dispatch<React.SetStateAction<PacienteFormState>>
}

/** Mensaje de error de formato debajo de un campo (UX). */
function MensajeError({ texto }: { texto?: string }) {
  if (!texto) return null
  return <p className="mt-1 text-xs text-red-600">{texto}</p>
}

/** Datos personales: nombre(s), apellidos, fecha de nacimiento, sexo. */
export function CamposDatosPersonales({ form, set }: CamposProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className="label">Nombre(s)</label>
        <input className="input" value={form.first_name} onChange={set('first_name')} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Apellido paterno</label>
          <input className="input" value={form.paternal_surname} onChange={set('paternal_surname')} />
        </div>
        <div>
          <label className="label">Apellido materno</label>
          <input className="input" value={form.maternal_surname} onChange={set('maternal_surname')} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Fecha de nacimiento</label>
          <input type="date" className="input" value={form.date_of_birth} onChange={set('date_of_birth')} />
        </div>
        <div>
          <label className="label">Sexo</label>
          <select className="input" value={form.sex} onChange={set('sex')}>
            <option value="">Selecciona…</option>
            <option value="F">Femenino</option>
            <option value="M">Masculino</option>
            <option value="X">Otro</option>
          </select>
        </div>
      </div>
    </div>
  )
}

/** Contacto: teléfono, teléfono secundario, etiqueta, email. */
export function CamposContacto({ form, set }: CamposProps) {
  const errs = erroresFormatoPaciente(form)
  return (
    <div className="space-y-3">
      <div>
        <label className="label">Teléfono</label>
        <input
          className={`input${errs.phone ? ' input-error' : ''}`}
          inputMode="tel"
          value={form.phone}
          onChange={set('phone')}
        />
        <MensajeError texto={errs.phone} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Teléfono secundario <span className="text-gray-400 font-normal">(opcional)</span></label>
          <input
            className={`input${errs.phone_secondary ? ' input-error' : ''}`}
            inputMode="tel"
            value={form.phone_secondary}
            onChange={set('phone_secondary')}
          />
          <MensajeError texto={errs.phone_secondary} />
        </div>
        <div>
          <label className="label">Etiqueta <span className="text-gray-400 font-normal">(ej. Casa)</span></label>
          <input className="input" value={form.phone_label} onChange={set('phone_label')} />
        </div>
      </div>
      <div>
        <label className="label">Email <span className="text-gray-400 font-normal">(opcional)</span></label>
        <input
          type="email"
          className={`input${errs.email ? ' input-error' : ''}`}
          inputMode="email"
          value={form.email}
          onChange={set('email')}
        />
        <MensajeError texto={errs.email} />
      </div>
    </div>
  )
}

/** Domicilio: calle y número, colonia, ciudad, estado, código postal. */
export function CamposDomicilio({ form, set }: CamposProps) {
  const errs = erroresFormatoPaciente(form)
  return (
    <div className="space-y-3">
      <div>
        <label className="label">Calle y número</label>
        <input className="input" value={form.address_street} onChange={set('address_street')} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Colonia</label>
          <input className="input" value={form.address_neighborhood} onChange={set('address_neighborhood')} />
        </div>
        <div>
          <label className="label">Código postal</label>
          <input
            className={`input${errs.postal_code ? ' input-error' : ''}`}
            inputMode="numeric"
            maxLength={5}
            value={form.postal_code}
            onChange={set('postal_code')}
          />
          <MensajeError texto={errs.postal_code} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Ciudad</label>
          <input className="input" value={form.city} onChange={set('city')} />
        </div>
        <div>
          <label className="label">Estado</label>
          <input className="input" value={form.state} onChange={set('state')} />
        </div>
      </div>
    </div>
  )
}

/**
 * Identificación + NOM-004: CURP, lugar de nacimiento, tipo de sangre, estado
 * civil, escolaridad, ocupación, religión, categoría, finado (+ defunción) y
 * costo de consulta personalizado.
 */
export function CamposNom004({ form, set, setForm }: CamposProps) {
  const errs = erroresFormatoPaciente(form)
  // Favorito/VIP se asignan con la ⭐/👑 en la tarjeta, no aquí: solo etiquetas personalizadas.
  const { data: categoriasData } = useCategories()
  const categorias = (categoriasData?.results ?? []).filter(c => c.kind === 'custom')

  const toggleEtiqueta = (id: string) =>
    setForm(prev => ({
      ...prev,
      category_ids: prev.category_ids.includes(id)
        ? prev.category_ids.filter(x => x !== id)
        : [...prev.category_ids, id],
    }))

  return (
    <div className="space-y-3">
      <div>
        <label className="label">CURP <span className="text-gray-400 font-normal">(opcional)</span></label>
        <input
          className={`input uppercase${errs.curp ? ' input-error' : ''}`}
          maxLength={18}
          value={form.curp}
          onChange={set('curp')}
        />
        <MensajeError texto={errs.curp} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Lugar de nacimiento</label>
          <input className="input" value={form.birthplace} onChange={set('birthplace')} />
        </div>
        <div>
          <label className="label">Tipo de sangre</label>
          <select className="input" value={form.blood_type} onChange={set('blood_type')}>
            {BLOOD_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Estado civil</label>
          <select className="input" value={form.marital_status} onChange={set('marital_status')}>
            {MARITAL_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Escolaridad</label>
          <select className="input" value={form.education} onChange={set('education')}>
            {EDUCATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Ocupación</label>
          <input className="input" value={form.occupation} onChange={set('occupation')} />
        </div>
        <div>
          <label className="label">Religión</label>
          <input className="input" value={form.religion} onChange={set('religion')} />
        </div>
      </div>
      <div>
        <label className="label">Etiquetas <span className="text-gray-400 font-normal">(opcional)</span></label>
        {categorias.length === 0 ? (
          <p className="text-xs text-gray-400">
            Aún no hay etiquetas. Créalas en Mi Consultorio → Categorías de pacientes.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {categorias.map(c => {
              const activo = form.category_ids.includes(c.id)
              return (
                <button key={c.id} type="button" onClick={() => toggleEtiqueta(c.id)}
                  className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-semibold transition-all"
                  style={activo
                    ? { background: '#1D6F5C', color: '#fff' }
                    : { background: 'rgba(0,0,0,0.05)', color: '#555' }}>
                  {activo && <Check className="w-3.5 h-3.5" />}
                  {c.name}
                </button>
              )
            })}
          </div>
        )}
      </div>
      <div>
        <label className="label">Costo de consulta <span className="text-gray-400 font-normal">(opcional)</span></label>
        <input
          type="number" min={0} step="0.01" className="input"
          placeholder="Tarifa estándar"
          value={form.custom_consultation_fee}
          onChange={set('custom_consultation_fee')}
        />
      </div>
      <div className="rounded-xl px-3 py-2.5" style={{ background: 'rgba(0,0,0,0.025)', border: '1px solid rgba(0,0,0,0.05)' }}>
        <label className="flex items-center gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            className="w-4 h-4 accent-amber-600"
            checked={form.is_deceased}
            onChange={e => setForm(prev => ({
              ...prev,
              is_deceased: e.target.checked,
              deceased_at: e.target.checked ? prev.deceased_at : '',
            }))}
          />
          <span className="text-sm text-gray-700">Paciente finado</span>
        </label>
        {form.is_deceased && (
          <div className="mt-3">
            <label className="label">Fecha de defunción <span className="text-gray-400 font-normal">(opcional)</span></label>
            <input type="date" className="input" value={form.deceased_at} onChange={set('deceased_at')} />
          </div>
        )}
      </div>
    </div>
  )
}
