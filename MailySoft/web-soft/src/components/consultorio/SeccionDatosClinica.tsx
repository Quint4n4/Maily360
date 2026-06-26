import { useEffect, useState } from 'react'
import { Loader2, Save } from 'lucide-react'
import { useClinicSettings, useUpdateClinicSettings } from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import {
  MSG, errorDeCampo, esEmailValido, esTelefonoValido, sinHTML,
} from '../../lib/validacion'
import ImageUploader from './ImageUploader'
import { AlertaErrores, AvisoGuardado, AvisoSoloLectura, Nota } from './Avisos'

interface Props {
  /** Si false, los campos quedan deshabilitados (solo lectura). */
  editable: boolean
}

/** Tipo de validación de formato (solo UX) aplicada a un campo. */
type Validacion = 'telefono' | 'email' | 'social'

/**
 * Valida el FORMATO de un campo de la clínica. Devuelve el mensaje de error o
 * `null` (válido / vacío). Replica los regex del backend (la autoridad).
 */
function errorClinica(valor: string, validacion?: Validacion): string | null {
  switch (validacion) {
    case 'telefono':
      return errorDeCampo(valor, esTelefonoValido, MSG.telefono)
    case 'email':
      return errorDeCampo(valor, esEmailValido, MSG.email)
    case 'social':
      return errorDeCampo(valor, sinHTML, MSG.html)
    default:
      return null
  }
}

/** Campos de texto editables en esta sección. */
const CAMPOS = [
  { key: 'commercial_name', label: 'Nombre comercial', type: 'text' },
  { key: 'address', label: 'Dirección', type: 'text' },
  { key: 'address_2', label: 'Dirección 2 (opcional)', type: 'text' },
  { key: 'phone', label: 'Teléfono', type: 'tel', inputMode: 'tel', validacion: 'telefono' },
  { key: 'mobile', label: 'Celular', type: 'tel', inputMode: 'tel', validacion: 'telefono' },
  { key: 'email', label: 'Correo electrónico', type: 'email', inputMode: 'email', validacion: 'email' },
  { key: 'website', label: 'Sitio web', type: 'url' },
  { key: 'facebook', label: 'Facebook', type: 'text', validacion: 'social' },
  { key: 'instagram', label: 'Instagram', type: 'text', validacion: 'social' },
  { key: 'youtube', label: 'YouTube', type: 'text', validacion: 'social' },
] as const

type CampoKey = (typeof CAMPOS)[number]['key']
type FormState = Record<CampoKey, string>

const FORM_VACIO: FormState = {
  commercial_name: '',
  address: '', address_2: '', phone: '', mobile: '', email: '',
  website: '', facebook: '', instagram: '', youtube: '',
}

/** Sección 1: datos de la clínica (logo + contacto + redes). */
export default function SeccionDatosClinica({ editable }: Props) {
  const settingsQ = useClinicSettings()
  const guardar = useUpdateClinicSettings()
  const [form, setForm] = useState<FormState>(FORM_VACIO)
  const [errores, setErrores] = useState<string[]>([])
  const [ok, setOk] = useState(false)
  const [subiendoLogo, setSubiendoLogo] = useState(false)

  // Cargar valores del backend al formulario cuando llegan / cambian.
  const settings = settingsQ.data
  useEffect(() => {
    if (settings) {
      setForm({
        commercial_name: settings.commercial_name,
        address: settings.address,
        address_2: settings.address_2,
        phone: settings.phone,
        mobile: settings.mobile,
        email: settings.email,
        website: settings.website,
        facebook: settings.facebook,
        instagram: settings.instagram,
        youtube: settings.youtube,
      })
    }
  }, [settings])

  const set = (k: CampoKey) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((p) => ({ ...p, [k]: e.target.value }))

  // Errores de FORMATO por campo (solo UX). El backend revalida y es la autoridad.
  const erroresCampo: Partial<Record<CampoKey, string>> = {}
  for (const c of CAMPOS) {
    const validacion = 'validacion' in c ? c.validacion : undefined
    const msg = errorClinica(form[c.key], validacion)
    if (msg) erroresCampo[c.key] = msg
  }
  const formatoInvalido = Object.keys(erroresCampo).length > 0

  const onGuardar = async () => {
    setErrores([])
    setOk(false)
    if (formatoInvalido) {
      setErrores(['Revisa los campos marcados en rojo antes de guardar.'])
      return
    }
    try {
      await guardar.mutateAsync({ ...form })
      setOk(true)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const onLogo = async (file: File) => {
    setErrores([])
    setOk(false)
    setSubiendoLogo(true)
    try {
      await guardar.mutateAsync({ logo: file })
      setOk(true)
    } catch (err) {
      setErrores(erroresDe(err))
    } finally {
      setSubiendoLogo(false)
    }
  }

  if (settingsQ.isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando configuración…
      </div>
    )
  }
  if (settingsQ.isError) {
    return <AlertaErrores errores={erroresDe(settingsQ.error)} />
  }

  return (
    <div className="space-y-6">
      {!editable && <AvisoSoloLectura />}
      <AlertaErrores errores={errores} />
      <AvisoGuardado visible={ok} />

      {/* Logo */}
      <div>
        <p className="label">Logo de la clínica</p>
        <div className="max-w-xs">
          <ImageUploader
            src={settings?.logo}
            label="Subir logo"
            uploading={subiendoLogo}
            onFile={editable ? onLogo : () => undefined}
            height={130}
          />
        </div>
        <Nota>Aparece en el encabezado de la app y en documentos. Se sube al elegirlo.</Nota>
      </div>

      {/* Campos de texto */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {CAMPOS.map((c) => {
          const { key, label, type } = c
          const inputMode = 'inputMode' in c ? c.inputMode : undefined
          const err = erroresCampo[key]
          return (
            <div key={key}>
              <label className="label" htmlFor={`clinic-${key}`}>{label}</label>
              <input
                id={`clinic-${key}`}
                type={type}
                inputMode={inputMode}
                className={`input${err ? ' input-error' : ''}`}
                value={form[key]}
                onChange={set(key)}
                disabled={!editable}
              />
              {err && <p className="mt-1 text-xs text-red-600">{err}</p>}
            </div>
          )
        })}
      </div>

      {/* El color de los documentos se toma del Formato de receta (fuente única) */}
      <div>
        <p className="label">Color de marca de tus documentos</p>
        <Nota>
          El color de tus PDFs (recetas, reportes, cotizaciones y expediente) se toma del
          color de acento de tu <strong>Formato de receta</strong>. Para cambiarlo, ve a
          «Configuración de recetas».
        </Nota>
      </div>

      {editable && (
        <div className="flex justify-end">
          <button className="btn-primary" onClick={onGuardar} disabled={guardar.isPending || formatoInvalido}>
            {guardar.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</>
            ) : (
              <><Save className="w-4 h-4" /> Guardar cambios</>
            )}
          </button>
        </div>
      )}
    </div>
  )
}
