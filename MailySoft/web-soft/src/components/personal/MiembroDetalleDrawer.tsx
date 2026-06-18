import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  X, Mail, ShieldCheck, Fingerprint, Stethoscope, FileText,
  Lock, Unlock, KeyRound, Eye, EyeOff, Loader2, AlertCircle, Check,
} from 'lucide-react'
import { useUpdateMember, useUploadMemberAvatar } from '../../hooks/miembros'
import { useDoctorsManage, useCreateDoctor, useUpdateDoctor, useConsultoriosManage } from '../../hooks/personal'
import { useAuth } from '../../auth/AuthContext'
import AvatarUploader from '../common/AvatarUploader'
import { useConfirm } from '../common/DialogProvider'
import { ApiError } from '../../lib/http'
import { ROLES } from '../../auth/permisos'
import type { ClinicRole } from '../../auth/permisos'
import type { Member } from '../../types/personal'
import { formatMedio } from '../../lib/fecha'

interface Props {
  miembro: Member | null
  onClose: () => void
  puedeEditar?: boolean
  esYoMismo?: boolean
}

function iniciales(nombre: string): string {
  const w = nombre.trim().split(/\s+/).filter(Boolean)
  return ((w[0]?.[0] ?? '') + (w[1]?.[0] ?? '')).toUpperCase() || '?'
}

function erroresDe(err: unknown): string[] {
  if (!(err instanceof ApiError)) return ['No se pudo guardar.']
  if (err.isNetwork) return ['No se pudo conectar con el servidor.']
  const body = err.body
  if (!body) return [`Error ${err.status}.`]
  const msgs: string[] = []
  for (const [campo, valor] of Object.entries(body)) {
    const txt = Array.isArray(valor) ? valor.join(' ') : String(valor)
    msgs.push(campo === 'detail' || campo === 'password' ? txt : `${campo}: ${txt}`)
  }
  return msgs.length ? msgs : [`Error ${err.status}.`]
}

/* Tarjeta de sección estilo ficha. */
function Card({ title, icon: Icon, children }: { title: string; icon: typeof Mail; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl p-5" style={{ background: 'rgba(255,255,255,0.72)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 6px 20px rgba(60,42,12,0.08)' }}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4" style={{ color: '#C9A227' }} />
        <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700/80">{title}</h4>
      </div>
      {children}
    </div>
  )
}
function Linea({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-amber-900/5 last:border-0">
      <span className="text-xs text-gray-400">{label}</span>
      <span className="text-sm text-gray-800 font-medium text-right truncate ml-2">{value || '—'}</span>
    </div>
  )
}

export default function MiembroDetalleDrawer({ miembro, onClose, puedeEditar = false, esYoMismo = false }: Props) {
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [rol, setRol] = useState<ClinicRole>('readonly')
  const [newPass, setNewPass] = useState('')
  const [verPass, setVerPass] = useState(false)
  const [errores, setErrores] = useState<string[]>([])
  const [okMsg, setOkMsg] = useState('')
  // Datos profesionales (perfil médico).
  const [cedula, setCedula] = useState('')
  const [especialidad, setEspecialidad] = useState('')
  const [duracion, setDuracion] = useState('30')
  const [bio, setBio] = useState('')
  const [consSel, setConsSel] = useState<string[]>([])
  const actualizar = useUpdateMember()
  const { data: docData } = useDoctorsManage()
  const { data: consData } = useConsultoriosManage()
  const consultorios = (consData?.results ?? []).filter(c => c.is_active)
  const crearDoctor = useCreateDoctor()
  const actualizarDoctor = useUpdateDoctor()
  const subirAvatar = useUploadMemberAvatar()
  const { reloadMe } = useAuth()
  const confirmar = useConfirm()

  // Perfil médico asociado (por email) si el miembro es médico.
  const doctorPerfil = miembro && miembro.role === 'doctor'
    ? (docData?.results ?? []).find(d => d.user_email === miembro.user.email)
    : undefined

  // Depender del ID (no del objeto) para no reiniciar los campos cuando la
  // lista se refetchea (foco de ventana, etc.) y borrar lo que el usuario escribe.
  useEffect(() => {
    if (!miembro) return
    setErrores([]); setOkMsg(''); setNewPass(''); setVerPass(false)
    setFirstName(miembro.user.first_name)
    setLastName(miembro.user.last_name)
    setRol(miembro.role)
  }, [miembro?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  // Igual que arriba: depender del ID del perfil, no del objeto, para que un
  // refetch de la lista de doctores no borre lo que se está editando.
  useEffect(() => {
    setCedula(doctorPerfil?.cedula_profesional ?? '')
    setEspecialidad(doctorPerfil?.specialty ?? '')
    setDuracion(String(doctorPerfil?.default_appointment_duration ?? 30))
    setBio(doctorPerfil?.bio_short ?? '')
    setConsSel((doctorPerfil?.consultorios ?? []).map(c => c.id))
  }, [doctorPerfil?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  if (!miembro) return <AnimatePresence />

  const guardar = async () => {
    setErrores([]); setOkMsg('')
    if (!firstName.trim()) { setErrores(['El nombre es obligatorio.']); return }
    try {
      await actualizar.mutateAsync({ id: miembro.id, input: { first_name: firstName.trim(), last_name: lastName.trim(), role: rol } })
      onClose()
    } catch (err) { setErrores(erroresDe(err)) }
  }

  const restablecer = async () => {
    setErrores([]); setOkMsg('')
    if (newPass.length < 10) { setErrores(['La contraseña debe tener al menos 10 caracteres.']); return }
    try {
      await actualizar.mutateAsync({ id: miembro.id, input: { password: newPass } })
      setNewPass(''); setOkMsg('Contraseña actualizada. Compártela con el miembro.')
    } catch (err) { setErrores(erroresDe(err)) }
  }

  const toggleBloqueo = async () => {
    const accion = miembro.is_blocked ? 'reactivar' : 'bloquear'
    if (!(await confirmar({
      titulo: miembro.is_blocked ? 'Reactivar cuenta' : 'Bloquear cuenta',
      mensaje: `¿Seguro que quieres ${accion} la cuenta de ${miembro.user.full_name}?`,
      peligro: !miembro.is_blocked,
      textoConfirmar: miembro.is_blocked ? 'Reactivar' : 'Bloquear',
    }))) return
    try {
      await actualizar.mutateAsync({ id: miembro.id, input: { blocked: !miembro.is_blocked } })
      onClose()
    } catch (err) { setErrores(erroresDe(err)) }
  }

  const guardandoDoctor = crearDoctor.isPending || actualizarDoctor.isPending
  const guardarProfesional = async () => {
    setErrores([]); setOkMsg('')
    const dur = parseInt(duracion, 10)
    if (Number.isNaN(dur) || dur < 5 || dur > 480) { setErrores(['La duración de cita debe estar entre 5 y 480 minutos.']); return }
    const payload = {
      cedula_profesional: cedula.trim(),
      specialty: especialidad.trim(),
      default_appointment_duration: dur,
      bio_short: bio.trim(),
    }
    try {
      if (doctorPerfil) {
        await actualizarDoctor.mutateAsync({ id: doctorPerfil.id, input: { ...payload, consultorio_ids: consSel } })
      } else {
        await crearDoctor.mutateAsync({ membership_id: miembro.id, ...payload })
      }
      setOkMsg(doctorPerfil ? 'Datos profesionales guardados.' : 'Perfil médico creado.')
    } catch (err) { setErrores(erroresDe(err)) }
  }

  return (
    <AnimatePresence>
      {miembro && (
        <motion.div
          className="fixed inset-0 z-50 overflow-y-auto p-4 md:p-8 flex items-start justify-center"
          style={{ background: 'rgba(40,28,8,0.35)', backdropFilter: 'blur(8px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-5xl glass-card rounded-3xl p-6 md:p-8"
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            <button onClick={onClose} className="absolute top-5 right-5 z-10 w-9 h-9 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors shadow-sm">
              <X className="w-5 h-5 text-gray-600" />
            </button>

            <p className="text-xs font-semibold uppercase tracking-widest text-amber-700/70 mb-5">Ficha del miembro</p>

            {/* Centro: avatar + nombre + rol + estado */}
            <div className="flex flex-col items-center text-center mb-6">
              <div className="relative mb-3">
                <div className="absolute -inset-2 rounded-full" style={{ background: 'conic-gradient(from 120deg, #E8C766, #C9A227, #F5E6B8, #C9A227, #E8C766)', filter: 'blur(8px)', opacity: 0.5 }} />
                <div className="relative">
                  <AvatarUploader
                    src={miembro.user.avatar}
                    initials={iniciales(miembro.user.full_name || miembro.user.email)}
                    size={112}
                    editable={puedeEditar}
                    uploading={subirAvatar.isPending}
                    onFile={f => subirAvatar.mutate({ id: miembro.id, file: f }, {
                      onSuccess: () => { if (esYoMismo) void reloadMe().catch(() => {}) },
                      onError: e => setErrores(erroresDe(e)),
                    })}
                  />
                </div>
              </div>
              <h2 className="text-2xl font-bold text-gray-900">{miembro.user.full_name || '—'}</h2>
              <p className="text-sm mt-0.5" style={{ color: '#B8860B' }}>{miembro.role_display}</p>
              <span className={`badge mt-2 ${miembro.is_blocked ? '' : 'badge-success'}`} style={miembro.is_blocked ? { background: '#FDE8E8', color: '#C0392B' } : undefined}>
                {miembro.is_blocked ? 'Bloqueado' : 'Activo'}
              </span>
            </div>

            {/* Tarjetas de información */}
            <div className="grid gap-5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
              <Card title="Contacto" icon={Mail}>
                <div className="flex items-center gap-2.5">
                  <Mail className="w-4 h-4 text-gray-400 shrink-0" />
                  <span className="text-sm text-gray-800 truncate">{miembro.user.email}</span>
                </div>
              </Card>

              <Card title="Cuenta" icon={ShieldCheck}>
                <Linea label="Estado" value={miembro.is_blocked ? 'Bloqueada' : 'Activa'} />
                <Linea label="Miembro desde" value={formatMedio(new Date(miembro.created_at))} />
              </Card>

              {miembro.role === 'doctor' && (
                <Card title="Datos profesionales" icon={Stethoscope}>
                  {doctorPerfil ? (
                    <>
                      <Linea label="Cédula" value={doctorPerfil.cedula_profesional} />
                      <Linea label="Especialidad" value={doctorPerfil.specialty} />
                      <Linea label="Duración de cita" value={`${doctorPerfil.default_appointment_duration} min`} />
                    </>
                  ) : (
                    <p className="text-sm text-gray-400 italic">Sin perfil médico aún (cédula/especialidad pendientes).</p>
                  )}
                </Card>
              )}

              {miembro.role === 'doctor' && doctorPerfil?.bio_short && (
                <Card title="Biografía" icon={FileText}>
                  <p className="text-sm text-gray-600 leading-relaxed">{doctorPerfil.bio_short}</p>
                </Card>
              )}
            </div>

            {/* Edición */}
            {puedeEditar && (
              <div className="mt-6 rounded-2xl p-5" style={{ background: 'rgba(201,162,39,0.06)', border: '1px solid rgba(201,162,39,0.18)' }}>
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-3 flex items-center gap-2">
                  <Fingerprint className="w-4 h-4" /> Editar miembro
                </p>

                {errores.length > 0 && (
                  <div className="flex items-start gap-2.5 rounded-xl px-4 py-3 mb-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
                    <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                    <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">{errores.map((e, i) => <li key={i}>{e}</li>)}</ul>
                  </div>
                )}
                {okMsg && (
                  <div className="flex items-center gap-2 rounded-xl px-4 py-3 mb-3 text-sm" style={{ background: '#E7F6EE', color: '#1F6E47' }}>
                    <Check className="w-4 h-4 shrink-0" /> {okMsg}
                  </div>
                )}

                <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
                  {/* Datos + rol */}
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="label">Nombre(s)</label>
                        <input className="input" value={firstName} onChange={e => setFirstName(e.target.value)} />
                      </div>
                      <div>
                        <label className="label">Apellidos</label>
                        <input className="input" value={lastName} onChange={e => setLastName(e.target.value)} />
                      </div>
                    </div>
                    <div>
                      <label className="label">Rol</label>
                      <select className="input" value={rol} onChange={e => setRol(e.target.value as ClinicRole)}>
                        {ROLES.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
                      </select>
                    </div>
                    <button onClick={guardar} disabled={actualizar.isPending}
                      className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                      style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                      {actualizar.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : 'Guardar cambios'}
                    </button>
                  </div>

                  {/* Contraseña + bloqueo */}
                  <div className="space-y-3">
                    <div>
                      <label className="label flex items-center gap-1.5"><KeyRound className="w-3.5 h-3.5" style={{ color: '#C9A227' }} /> Restablecer contraseña</label>
                      <div className="relative">
                        <input type={verPass ? 'text' : 'password'} className="input pr-10" value={newPass} onChange={e => setNewPass(e.target.value)} placeholder="Nueva contraseña (mín. 10)" />
                        <button type="button" tabIndex={-1} onClick={() => setVerPass(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                          {verPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>
                      <p className="text-[11px] text-gray-400 mt-1">No se puede ver la actual (está cifrada). Aquí defines una nueva.</p>
                      <button onClick={restablecer} disabled={actualizar.isPending || !newPass}
                        className="w-full mt-2 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-colors disabled:opacity-50"
                        style={{ color: '#9A7B1E', background: 'rgba(201,162,39,0.14)' }}>
                        <KeyRound className="w-4 h-4" /> Restablecer contraseña
                      </button>
                    </div>

                    <button onClick={toggleBloqueo} disabled={actualizar.isPending || esYoMismo}
                      title={esYoMismo ? 'No puedes bloquear tu propia cuenta' : ''}
                      className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-colors disabled:opacity-40"
                      style={miembro.is_blocked ? { color: '#1F6E47', background: 'rgba(46,125,91,0.10)' } : { color: '#C0392B', background: 'rgba(192,57,43,0.08)' }}>
                      {miembro.is_blocked ? <><Unlock className="w-4 h-4" /> Reactivar cuenta</> : <><Lock className="w-4 h-4" /> Bloquear cuenta</>}
                    </button>
                  </div>
                </div>

                {/* Datos profesionales (solo si el miembro es médico) */}
                {miembro.role === 'doctor' && (
                  <div className="mt-4 pt-4 border-t border-amber-900/10">
                    <p className="text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-3 flex items-center gap-2">
                      <Stethoscope className="w-4 h-4" /> Datos profesionales
                      {!doctorPerfil && <span className="text-[11px] font-normal text-gray-400">(sin perfil — se creará)</span>}
                    </p>
                    <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                      <div>
                        <label className="label">Cédula profesional</label>
                        <input className="input" value={cedula} onChange={e => setCedula(e.target.value)} placeholder="Ej. 1234567" />
                      </div>
                      <div>
                        <label className="label">Especialidad</label>
                        <input className="input" value={especialidad} onChange={e => setEspecialidad(e.target.value)} placeholder="Ej. Medicina general" />
                      </div>
                      <div>
                        <label className="label">Duración de cita (min)</label>
                        <input type="number" min={5} max={480} className="input" value={duracion} onChange={e => setDuracion(e.target.value)} />
                      </div>
                    </div>
                    <div className="mt-3">
                      <label className="label">Biografía <span className="text-gray-400 font-normal">(opcional)</span></label>
                      <textarea className="input resize-none" rows={2} value={bio} onChange={e => setBio(e.target.value)} placeholder="Breve descripción profesional…" />
                    </div>
                    {doctorPerfil && (
                      <div className="mt-3">
                        <label className="label">Consultorios asignados <span className="text-gray-400 font-normal">(vacío = puede usar cualquiera)</span></label>
                        {consultorios.length === 0 ? (
                          <p className="text-xs text-gray-400">No hay consultorios. Créalos en Personal → Consultorios.</p>
                        ) : (
                          <div className="flex flex-wrap gap-2 mt-1">
                            {consultorios.map(c => {
                              const on = consSel.includes(c.id)
                              return (
                                <button key={c.id} type="button"
                                  onClick={() => setConsSel(s => s.includes(c.id) ? s.filter(x => x !== c.id) : [...s, c.id])}
                                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-all"
                                  style={on ? { background: '#C9A227', color: '#fff' } : { background: 'rgba(255,255,255,0.6)', color: '#7A756C', border: '1px solid rgba(201,162,39,0.3)' }}>
                                  {on && <Check className="w-3.5 h-3.5" />} {c.name}
                                </button>
                              )
                            })}
                          </div>
                        )}
                        <p className="text-[11px] text-gray-400 mt-1.5">Solo podrá agendar citas en los consultorios marcados.</p>
                      </div>
                    )}
                    <button onClick={guardarProfesional} disabled={guardandoDoctor}
                      className="w-full mt-3 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                      style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                      {guardandoDoctor ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : (doctorPerfil ? 'Guardar datos profesionales' : 'Crear perfil médico')}
                    </button>
                  </div>
                )}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
