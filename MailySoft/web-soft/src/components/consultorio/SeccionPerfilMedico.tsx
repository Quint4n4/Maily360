import { useEffect, useState } from 'react'
import { GraduationCap, Loader2, Plus, Save, Trash2 } from 'lucide-react'
import { useAuth } from '../../auth/AuthContext'
import {
  useCreateUniversity,
  useDeleteUniversity,
  useDoctorActual,
  useUniversities,
  useUpdateDoctorProfile,
} from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import type { DoctorUniversityOut } from '../../types/clinica'
import ImageUploader from './ImageUploader'
import { AlertaErrores, AvisoGuardado, AvisoInfo, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

/** Sección 6: perfil ampliado del médico (sello, foto, cédulas, universidades). */
export default function SeccionPerfilMedico() {
  const { user } = useAuth()
  const doctorId = user?.doctor_id ?? null

  const doctorQ = useDoctorActual(doctorId)
  const universidadesQ = useUniversities(doctorId)
  const actualizarPerfil = useUpdateDoctorProfile(doctorId)
  const crearUni = useCreateUniversity(doctorId)
  const borrarUni = useDeleteUniversity(doctorId)
  const confirmar = useConfirm()

  const doctor = doctorQ.data
  const [cedulas, setCedulas] = useState('')
  const [errores, setErrores] = useState<string[]>([])
  const [ok, setOk] = useState(false)
  const [subiendo, setSubiendo] = useState<'sello' | 'foto' | null>(null)

  // Estado de la nueva universidad.
  const [uniNombre, setUniNombre] = useState('')
  const [uniLogo, setUniLogo] = useState<File | null>(null)
  const [uniPreview, setUniPreview] = useState<string | null>(null)

  useEffect(() => {
    if (doctor) setCedulas(doctor.cedulas_adicionales)
  }, [doctor])

  // Sin médico asociado: el usuario no es doctor en esta clínica.
  if (!doctorId) {
    return (
      <AvisoInfo texto="Tu cuenta no tiene un perfil de médico en esta clínica, así que no hay sello, foto ni cédulas que configurar aquí. Si eres médico, pide a un administrador que te dé de alta como doctor." />
    )
  }

  if (doctorQ.isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando tu perfil médico…
      </div>
    )
  }
  if (doctorQ.isError) {
    return <AlertaErrores errores={erroresDe(doctorQ.error)} />
  }

  const subirImagen = (campo: 'sello' | 'foto') => async (file: File) => {
    setErrores([])
    setOk(false)
    setSubiendo(campo)
    try {
      await actualizarPerfil.mutateAsync({ [campo]: file })
      setOk(true)
    } catch (err) {
      setErrores(erroresDe(err))
    } finally {
      setSubiendo(null)
    }
  }

  const guardarCedulas = async () => {
    setErrores([])
    setOk(false)
    try {
      await actualizarPerfil.mutateAsync({ cedulas_adicionales: cedulas.trim() })
      setOk(true)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const elegirLogoUni = (file: File) => {
    setUniLogo(file)
    setUniPreview(URL.createObjectURL(file))
  }

  const agregarUniversidad = async () => {
    setErrores([])
    if (!uniLogo) {
      setErrores(['Selecciona el logo de la universidad.'])
      return
    }
    try {
      await crearUni.mutateAsync({ logo: uniLogo, name: uniNombre.trim() })
      setUniLogo(null)
      setUniPreview(null)
      setUniNombre('')
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const borrarUniversidad = async (u: DoctorUniversityOut) => {
    if (!(await confirmar({ titulo: 'Eliminar universidad', mensaje: `¿Eliminar ${u.name || 'esta universidad'}?`, peligro: true, textoConfirmar: 'Eliminar' }))) return
    setErrores([])
    try {
      await borrarUni.mutateAsync(u.id)
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const universidades = universidadesQ.data ?? []

  return (
    <div className="space-y-7">
      <AlertaErrores errores={errores} />
      <AvisoGuardado visible={ok} />

      {/* Sello + foto */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <div className="space-y-2">
          <p className="label">Sello del médico</p>
          <div className="max-w-xs">
            <ImageUploader
              src={doctor?.sello}
              label="Subir sello"
              uploading={subiendo === 'sello'}
              onFile={subirImagen('sello')}
              height={130}
            />
          </div>
          <Nota>Se imprime en recetas y documentos. Se sube al elegirlo.</Nota>
        </div>
        <div className="space-y-2">
          <p className="label">Foto del médico</p>
          <div className="max-w-xs">
            <ImageUploader
              src={doctor?.foto}
              label="Subir foto"
              uploading={subiendo === 'foto'}
              onFile={subirImagen('foto')}
              height={130}
            />
          </div>
        </div>
      </div>

      {/* Cédulas adicionales */}
      <div>
        <label className="label" htmlFor="cedulas">Cédulas adicionales</label>
        <input
          id="cedulas"
          className="input max-w-xl"
          placeholder="1234567, 7654321"
          value={cedulas}
          onChange={(e) => setCedulas(e.target.value)}
        />
        <Nota>Sepáralas con coma. La cédula profesional principal se edita en Personal.</Nota>
        <div className="mt-3">
          <button className="btn-primary" onClick={guardarCedulas} disabled={actualizarPerfil.isPending}>
            {actualizarPerfil.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</>
            ) : (
              <><Save className="w-4 h-4" /> Guardar cédulas</>
            )}
          </button>
        </div>
      </div>

      {/* Universidades */}
      <div className="space-y-4">
        <p className="label mb-0">Universidades</p>

        {/* Galería */}
        {universidadesQ.isLoading ? (
          <div className="flex items-center justify-center py-8 text-gray-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando universidades…
          </div>
        ) : universidadesQ.isError ? (
          <AlertaErrores errores={erroresDe(universidadesQ.error)} />
        ) : universidades.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-gray-400">
            <GraduationCap className="w-8 h-8 mb-2 opacity-50" />
            <p className="text-sm">Aún no agregas universidades.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {universidades.map((u) => (
              <div
                key={u.id}
                className="relative group rounded-2xl border border-gray-100 bg-white/70 p-3 flex flex-col items-center gap-2"
              >
                <img src={u.logo} alt={u.name} className="h-16 object-contain" />
                <p className="text-xs text-gray-600 text-center truncate w-full">{u.name || '—'}</p>
                <button
                  onClick={() => borrarUniversidad(u)}
                  className="absolute top-1.5 right-1.5 p-1.5 rounded-lg bg-white/90 text-red-500 opacity-0 group-hover:opacity-100 hover:bg-red-50 transition-all"
                  aria-label="Eliminar universidad"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Agregar nueva */}
        <div className="rounded-2xl border border-gray-100 bg-white/60 p-4 space-y-3">
          <p className="text-sm font-medium text-gray-700">Agregar universidad</p>
          <div className="grid grid-cols-1 sm:grid-cols-[160px_1fr_auto] gap-3 items-end">
            <div className="max-w-[160px]">
              <ImageUploader
                src={uniPreview}
                label="Logo"
                onFile={elegirLogoUni}
                height={90}
              />
            </div>
            <div>
              <label className="label" htmlFor="uni-name">Nombre (opcional)</label>
              <input
                id="uni-name"
                className="input"
                value={uniNombre}
                onChange={(e) => setUniNombre(e.target.value)}
              />
            </div>
            <button className="btn-primary" onClick={agregarUniversidad} disabled={crearUni.isPending}>
              {crearUni.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Agregar
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
