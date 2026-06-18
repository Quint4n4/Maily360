import { useEffect, useState } from 'react'
import { Loader2, Plus, Save, Trash2 } from 'lucide-react'
import { useClinicSettings, useUpdateClinicSettings } from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import { MSG, errorDeCampo, esTelefonoValido } from '../../lib/validacion'
import type { WhatsAppContact } from '../../types/clinica'
import { AlertaErrores, AvisoGuardado, AvisoInfo, AvisoSoloLectura, Nota } from './Avisos'

interface Props {
  editable: boolean
}

/** Sección 3: opciones de receta (médico responsable + contactos WhatsApp). */
export default function SeccionRecetas({ editable }: Props) {
  const settingsQ = useClinicSettings()
  const guardar = useUpdateClinicSettings()
  const settings = settingsQ.data

  const [usarResponsable, setUsarResponsable] = useState(false)
  const [contactos, setContactos] = useState<WhatsAppContact[]>([])
  const [errores, setErrores] = useState<string[]>([])
  const [ok, setOk] = useState(false)

  useEffect(() => {
    if (settings) {
      setUsarResponsable(settings.recipe_use_responsible_doctor)
      setContactos(settings.recipe_whatsapp_contacts)
    }
  }, [settings])

  const setContacto = (i: number, campo: keyof WhatsAppContact, valor: string) =>
    setContactos((prev) => prev.map((c, idx) => (idx === i ? { ...c, [campo]: valor } : c)))

  const agregar = () => setContactos((prev) => [...prev, { nombre: '', numero: '' }])
  const quitar = (i: number) => setContactos((prev) => prev.filter((_, idx) => idx !== i))

  // Error de FORMATO del número por contacto (solo UX). El backend revalida.
  const errorNumero = (numero: string): string | null =>
    errorDeCampo(numero, esTelefonoValido, MSG.whatsapp)
  const formatoInvalido = contactos.some((c) => errorNumero(c.numero) !== null)

  const onGuardar = async () => {
    setErrores([])
    setOk(false)
    // El backend rechaza nombre/numero vacíos; validamos antes para un mensaje claro.
    const limpios = contactos.map((c) => ({ nombre: c.nombre.trim(), numero: c.numero.trim() }))
    const incompleto = limpios.some((c) => !c.nombre || !c.numero)
    if (incompleto) {
      setErrores(['Cada contacto de WhatsApp necesita nombre y número.'])
      return
    }
    if (formatoInvalido) {
      setErrores(['Revisa los números de WhatsApp marcados en rojo antes de guardar.'])
      return
    }
    try {
      await guardar.mutateAsync({
        recipe_use_responsible_doctor: usarResponsable,
        recipe_whatsapp_contacts: limpios,
      })
      setOk(true)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  if (settingsQ.isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando opciones de receta…
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

      {/* Toggle médico responsable */}
      <div className="flex items-start justify-between gap-4 rounded-2xl border border-gray-100 bg-white/60 px-4 py-3.5">
        <div>
          <p className="text-sm font-medium text-gray-800">Usar el médico responsable en la receta</p>
          <Nota>
            Si se activa, la receta mostrará al médico responsable de la consulta como firmante,
            en lugar del médico que la redacta.
          </Nota>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={usarResponsable}
          disabled={!editable}
          onClick={() => setUsarResponsable((v) => !v)}
          className="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50"
          style={{ background: usarResponsable ? '#C9A227' : '#D1CCC2' }}
        >
          <span
            className="inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform"
            style={{ transform: usarResponsable ? 'translateX(22px)' : 'translateX(2px)' }}
          />
        </button>
      </div>

      {/* Contactos WhatsApp */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="label mb-0">Contactos de WhatsApp para envío de recetas</p>
          {editable && (
            <button type="button" className="btn-ghost" onClick={agregar}>
              <Plus className="w-4 h-4" /> Agregar
            </button>
          )}
        </div>

        <AvisoInfo texto="El envío por WhatsApp está simulado por ahora. Aquí defines los contactos a los que se enviarían las recetas." />

        {contactos.length === 0 ? (
          <p className="text-sm text-gray-400 py-2">Aún no hay contactos. {editable && 'Agrega el primero con “Agregar”.'}</p>
        ) : (
          <div className="space-y-2">
            {contactos.map((c, i) => {
              const errNum = errorNumero(c.numero)
              return (
                <div key={i}>
                  <div className="flex items-center gap-2">
                    <input
                      className="input flex-1"
                      placeholder="Nombre"
                      value={c.nombre}
                      onChange={(e) => setContacto(i, 'nombre', e.target.value)}
                      disabled={!editable}
                    />
                    <input
                      className={`input flex-1${errNum ? ' input-error' : ''}`}
                      inputMode="tel"
                      placeholder="Número"
                      value={c.numero}
                      onChange={(e) => setContacto(i, 'numero', e.target.value)}
                      disabled={!editable}
                    />
                    {editable && (
                      <button
                        type="button"
                        onClick={() => quitar(i)}
                        className="p-2 rounded-lg text-red-500 hover:bg-red-50 transition-colors"
                        aria-label="Quitar contacto"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                  {errNum && <p className="mt-1 text-xs text-red-600">{errNum}</p>}
                </div>
              )
            })}
          </div>
        )}
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
