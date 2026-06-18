import { useEffect, useState } from 'react'
import { Loader2, Save } from 'lucide-react'
import { useClinicSettings, useUpdateClinicSettings } from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import ImageUploader from './ImageUploader'
import { AlertaErrores, AvisoGuardado, AvisoInfo, AvisoSoloLectura, Nota } from './Avisos'

interface Props {
  editable: boolean
}

/** Sección 2: membrete para impresión (encabezados de recetas/documentos). */
export default function SeccionMembrete({ editable }: Props) {
  const settingsQ = useClinicSettings()
  const guardar = useUpdateClinicSettings()
  const settings = settingsQ.data

  const [fullSpaces, setFullSpaces] = useState('0')
  const [halfSpaces, setHalfSpaces] = useState('0')
  const [errores, setErrores] = useState<string[]>([])
  const [ok, setOk] = useState(false)
  const [subiendo, setSubiendo] = useState<'full' | 'half' | null>(null)

  useEffect(() => {
    if (settings) {
      setFullSpaces(String(settings.letterhead_full_spaces))
      setHalfSpaces(String(settings.letterhead_half_spaces))
    }
  }, [settings])

  const subirImagen = (campo: 'letterhead_full' | 'letterhead_half') => async (file: File) => {
    setErrores([])
    setOk(false)
    setSubiendo(campo === 'letterhead_full' ? 'full' : 'half')
    try {
      await guardar.mutateAsync({ [campo]: file })
      setOk(true)
    } catch (err) {
      setErrores(erroresDe(err))
    } finally {
      setSubiendo(null)
    }
  }

  const onGuardarEspacios = async () => {
    setErrores([])
    setOk(false)
    const full = Number(fullSpaces)
    const half = Number(halfSpaces)
    const fuera = [full, half].some((n) => !Number.isInteger(n) || n < 0 || n > 100)
    if (fuera) {
      setErrores(['Los espacios deben ser un número entero entre 0 y 100.'])
      return
    }
    try {
      await guardar.mutateAsync({ letterhead_full_spaces: full, letterhead_half_spaces: half })
      setOk(true)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  if (settingsQ.isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando membrete…
      </div>
    )
  }
  if (settingsQ.isError) {
    return <AlertaErrores errores={erroresDe(settingsQ.error)} />
  }

  return (
    <div className="space-y-6">
      {!editable && <AvisoSoloLectura />}
      <AvisoInfo texto="El membrete es el papel con encabezado que se usa al imprimir recetas y documentos. Los 'espacios' definen cuántas líneas en blanco dejar arriba para no encimar el texto sobre el diseño impreso." />
      <AlertaErrores errores={errores} />
      <AvisoGuardado visible={ok} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Membrete completo */}
        <div className="space-y-3">
          <p className="label">Membrete completo (hoja completa)</p>
          <ImageUploader
            src={settings?.letterhead_full}
            label="Subir membrete completo"
            uploading={subiendo === 'full'}
            onFile={editable ? subirImagen('letterhead_full') : () => undefined}
            height={170}
          />
          <div>
            <label className="label" htmlFor="full-spaces">Espacios superiores (0-100)</label>
            <input
              id="full-spaces"
              type="number"
              min={0}
              max={100}
              className="input"
              value={fullSpaces}
              onChange={(e) => setFullSpaces(e.target.value)}
              disabled={!editable}
            />
          </div>
        </div>

        {/* Medio membrete */}
        <div className="space-y-3">
          <p className="label">Medio membrete (media hoja)</p>
          <ImageUploader
            src={settings?.letterhead_half}
            label="Subir medio membrete"
            uploading={subiendo === 'half'}
            onFile={editable ? subirImagen('letterhead_half') : () => undefined}
            height={170}
          />
          <div>
            <label className="label" htmlFor="half-spaces">Espacios superiores (0-100)</label>
            <input
              id="half-spaces"
              type="number"
              min={0}
              max={100}
              className="input"
              value={halfSpaces}
              onChange={(e) => setHalfSpaces(e.target.value)}
              disabled={!editable}
            />
          </div>
        </div>
      </div>

      <Nota>Formatos aceptados: JPG, PNG o WEBP. Las imágenes se suben al elegirlas.</Nota>

      {editable && (
        <div className="flex justify-end">
          <button className="btn-primary" onClick={onGuardarEspacios} disabled={guardar.isPending}>
            {guardar.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</>
            ) : (
              <><Save className="w-4 h-4" /> Guardar espacios</>
            )}
          </button>
        </div>
      )}
    </div>
  )
}
