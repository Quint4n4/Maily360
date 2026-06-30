import { useEffect, useState } from 'react'
import { Award, Loader2, Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { useAuth } from '../../auth/AuthContext'
import {
  useCreateCredential,
  useCredentials,
  useDeleteCredential,
  useDoctorActual,
  useUpdateCredential,
  useUpdateDoctorProfile,
} from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import type { CredentialKind, DoctorCredentialOut } from '../../types/credenciales'
import { CREDENTIAL_KIND_OPTIONS } from '../../types/credenciales'
import ImageUploader from './ImageUploader'
import CredencialEstadoBadge from './CredencialEstadoBadge'
import { AlertaErrores, AvisoGuardado, AvisoInfo, Nota } from './Avisos'
import { useConfirm } from '../common/DialogProvider'

/** Sección 6: perfil ampliado del médico (sello, foto, cédulas y credenciales). */
export default function SeccionPerfilMedico() {
  const { user } = useAuth()
  const doctorId = user?.doctor_id ?? null

  const doctorQ = useDoctorActual(doctorId)
  const actualizarPerfil = useUpdateDoctorProfile(doctorId)

  const doctor = doctorQ.data
  const [cedulas, setCedulas] = useState('')
  const [errores, setErrores] = useState<string[]>([])
  const [ok, setOk] = useState(false)
  const [subiendo, setSubiendo] = useState<'sello' | 'foto' | null>(null)

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
          inputMode="numeric"
          maxLength={150}
          placeholder="1234567, 7654321"
          value={cedulas}
          onChange={(e) => setCedulas(e.target.value.replace(/[^\d,\s]/g, ''))}
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

      {/* Credenciales estructuradas (COFEPRIS F2) — cada una con su logo */}
      <SeccionCredenciales doctorId={doctorId} />
    </div>
  )
}

/* ───────────────────────────────────────────────────────────────────────────
   Credenciales estructuradas del médico (COFEPRIS F2)
   El logo de la institución se sube JUNTO con la credencial, así queda pegado a
   su cédula y nunca se descoloca en la receta.
   ─────────────────────────────────────────────────────────────────────────── */

/** Estado del formulario de nueva credencial. */
interface CredencialForm {
  title: string
  institution: string
  credential_number: string
  kind: CredentialKind
}

const CRED_FORM_VACIO: CredencialForm = {
  title: '',
  institution: '',
  credential_number: '',
  kind: 'profesional',
}

function SeccionCredenciales({ doctorId }: { doctorId: string }) {
  const credencialesQ = useCredentials(doctorId)
  const crear = useCreateCredential(doctorId)
  const actualizar = useUpdateCredential(doctorId)
  const borrar = useDeleteCredential(doctorId)
  const confirmar = useConfirm()

  const [form, setForm] = useState<CredencialForm>(CRED_FORM_VACIO)
  const [logo, setLogo] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [editandoId, setEditandoId] = useState<string | null>(null)
  const [errores, setErrores] = useState<string[]>([])

  const pendiente = crear.isPending || actualizar.isPending
  const editando = editandoId !== null

  const set = <K extends keyof CredencialForm>(k: K) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm((p) => ({ ...p, [k]: e.target.value as CredencialForm[K] }))

  const elegirLogo = (file: File) => {
    setLogo(file)
    setPreview(URL.createObjectURL(file))
  }

  const limpiar = () => {
    setForm(CRED_FORM_VACIO)
    setLogo(null)
    setPreview(null)
    setEditandoId(null)
    setErrores([])
  }

  const iniciarEdicion = (c: DoctorCredentialOut) => {
    setEditandoId(c.id)
    setForm({
      title: c.title,
      institution: c.institution,
      credential_number: c.credential_number,
      kind: c.kind,
    })
    setLogo(null)
    setPreview(c.logo_url)
    setErrores([])
  }

  const guardar = async () => {
    setErrores([])
    if (!form.title.trim()) { setErrores(['El título es obligatorio.']); return }
    if (!form.institution.trim()) { setErrores(['La institución es obligatoria.']); return }
    try {
      if (editandoId) {
        await actualizar.mutateAsync({
          id: editandoId,
          input: {
            title: form.title.trim(),
            institution: form.institution.trim(),
            kind: form.kind,
            credential_number: form.credential_number.trim(),
            logo: logo ?? undefined,
          },
        })
      } else {
        await crear.mutateAsync({
          title: form.title.trim(),
          institution: form.institution.trim(),
          kind: form.kind,
          credential_number: form.credential_number.trim(),
          logo: logo ?? undefined,
        })
      }
      limpiar()
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const eliminar = async (c: DoctorCredentialOut) => {
    if (!(await confirmar({
      titulo: 'Eliminar credencial',
      mensaje: `¿Eliminar "${c.title}"?`,
      peligro: true,
      textoConfirmar: 'Eliminar',
    }))) return
    setErrores([])
    try {
      await borrar.mutateAsync(c.id)
      if (editandoId === c.id) limpiar()
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const credenciales = credencialesQ.data ?? []

  return (
    <div className="space-y-4">
      <div>
        <p className="label mb-0">Credenciales (COFEPRIS)</p>
        <Nota>
          Cédula profesional, de especialidad y posgrados con la institución que los expide y su
          logo opcional. <strong>Un administrador las revisa</strong>: solo las credenciales
          <strong> validadas</strong> aparecen en la receta. Al agregar o editar una, queda
          “pendiente de validación”.
        </Nota>
      </div>

      <AlertaErrores errores={errores} />

      {/* Lista */}
      {credencialesQ.isLoading ? (
        <div className="flex items-center justify-center py-8 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando credenciales…
        </div>
      ) : credencialesQ.isError ? (
        <AlertaErrores errores={erroresDe(credencialesQ.error)} />
      ) : credenciales.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-gray-400">
          <Award className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">Aún no agregas credenciales.</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {credenciales.map((c) => (
            <li
              key={c.id}
              className={`flex items-center justify-between gap-3 rounded-2xl border bg-white/70 p-3 ${
                editandoId === c.id ? 'border-amber-300 ring-1 ring-amber-200' : 'border-gray-100'
              }`}
            >
              <div className="flex items-center gap-3 min-w-0">
                {c.logo_url ? (
                  <img src={c.logo_url} alt="" className="h-10 w-10 object-contain shrink-0" />
                ) : (
                  <div className="h-10 w-10 rounded-lg bg-gray-50 flex items-center justify-center shrink-0">
                    <Award className="w-4 h-4 text-gray-300" />
                  </div>
                )}
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-gray-800 truncate">{c.title}</span>
                    <span
                      className="text-[10px] rounded-full px-1.5 py-0.5"
                      style={{ background: 'rgba(201,162,39,0.15)', color: '#9A7B1E' }}
                    >
                      {c.kind_display}
                    </span>
                    <CredencialEstadoBadge status={c.validation_status} label={c.validation_status_display} />
                  </div>
                  <p className="text-xs text-gray-500">
                    {[c.institution, c.credential_number ? `Céd. ${c.credential_number}` : '']
                      .filter(Boolean).join(' · ') || '—'}
                  </p>
                  {c.validation_status === 'rechazada' && c.validation_note && (
                    <p className="text-[11px] text-red-600 mt-0.5">Motivo del rechazo: {c.validation_note}</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => iniciarEdicion(c)}
                  className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors"
                  aria-label="Editar credencial"
                >
                  <Pencil className="w-4 h-4" />
                </button>
                <button
                  onClick={() => eliminar(c)}
                  disabled={borrar.isPending}
                  className="p-1.5 rounded-lg text-red-500 hover:bg-red-50 transition-colors disabled:opacity-50"
                  aria-label="Eliminar credencial"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Alta / edición */}
      <div className="rounded-2xl border border-gray-100 bg-white/60 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-gray-700">
            {editando ? 'Editar credencial' : 'Agregar credencial'}
          </p>
          {editando && (
            <button
              onClick={limpiar}
              className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
            >
              <X className="w-3.5 h-3.5" /> Cancelar edición
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-[140px_1fr] gap-4 items-start">
          <div>
            <p className="label">Logo (opcional)</p>
            <ImageUploader
              src={preview}
              label="Logo institución"
              onFile={elegirLogo}
              height={96}
            />
            {editando && (
              <p className="text-[11px] text-gray-400 mt-1">Sube uno nuevo para reemplazarlo.</p>
            )}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="cred-title">Título / grado *</label>
              <input
                id="cred-title"
                className="input"
                maxLength={150}
                placeholder="Ej. Médico Cirujano"
                value={form.title}
                onChange={set('title')}
              />
            </div>
            <div>
              <label className="label" htmlFor="cred-inst">Institución *</label>
              <input
                id="cred-inst"
                className="input"
                maxLength={150}
                placeholder="Ej. UNAM"
                value={form.institution}
                onChange={set('institution')}
              />
            </div>
            <div>
              <label className="label" htmlFor="cred-num">Número de cédula</label>
              <input
                id="cred-num"
                className="input"
                inputMode="numeric"
                maxLength={150}
                placeholder="Ej. 1234567"
                value={form.credential_number}
                onChange={(e) =>
                  setForm((p) => ({ ...p, credential_number: e.target.value.replace(/\D/g, '') }))
                }
              />
            </div>
            <div>
              <label className="label" htmlFor="cred-kind">Tipo</label>
              <select id="cred-kind" className="input" value={form.kind} onChange={set('kind')}>
                {CREDENTIAL_KIND_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          {editando && (
            <button className="btn-secondary px-4 py-2" onClick={limpiar} disabled={pendiente}>
              Cancelar
            </button>
          )}
          <button className="btn-primary" onClick={guardar} disabled={pendiente}>
            {pendiente
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : editando ? <Save className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
            {editando ? 'Guardar cambios' : 'Agregar credencial'}
          </button>
        </div>
      </div>
    </div>
  )
}
