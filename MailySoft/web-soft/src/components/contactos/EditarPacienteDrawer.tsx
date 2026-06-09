import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2 } from 'lucide-react'
import { useUpdatePatient } from '../../hooks/pacientes'
import { ApiError } from '../../lib/http'
import type { PatientOut, Sex } from '../../types/paciente'

interface EditarPacienteDrawerProps {
  paciente: PatientOut | null
  onClose: () => void
}

const SECCION = 'text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-3'

/** Extrae mensajes de error legibles de un ApiError de DRF. */
function erroresDe(err: unknown): string[] {
  if (!(err instanceof ApiError)) return ['No se pudo guardar.']
  if (err.isNetwork) return ['No se pudo conectar con el servidor.']
  const body = err.body
  if (!body) return [`Error ${err.status}.`]
  const msgs: string[] = []
  for (const [campo, valor] of Object.entries(body)) {
    const txt = Array.isArray(valor) ? valor.join(' ') : String(valor)
    msgs.push(campo === 'detail' ? txt : `${campo}: ${txt}`)
  }
  return msgs.length ? msgs : [`Error ${err.status}.`]
}

export default function EditarPacienteDrawer({ paciente, onClose }: EditarPacienteDrawerProps) {
  const [form, setForm] = useState({
    first_name: '', paternal_surname: '', maternal_surname: '',
    date_of_birth: '', sex: '' as '' | Sex, phone: '', email: '', curp: '', notes: '',
  })
  const [errores, setErrores] = useState<string[]>([])
  const actualizar = useUpdatePatient()

  // Precargar el formulario cuando cambia el paciente seleccionado.
  useEffect(() => {
    if (!paciente) return
    setErrores([])
    setForm({
      first_name: paciente.first_name,
      paternal_surname: paciente.paternal_surname,
      maternal_surname: paciente.maternal_surname,
      date_of_birth: paciente.date_of_birth ?? '',
      sex: paciente.sex,
      phone: paciente.phone,
      email: paciente.email,
      curp: paciente.curp,
      notes: paciente.notes,
    })
  }, [paciente])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm(prev => ({ ...prev, [k]: e.target.value }))

  const guardar = async () => {
    if (!paciente) return
    setErrores([])
    const faltan: string[] = []
    if (!form.first_name.trim()) faltan.push('El nombre es obligatorio.')
    if (!form.paternal_surname.trim()) faltan.push('El apellido paterno es obligatorio.')
    if (!form.date_of_birth) faltan.push('La fecha de nacimiento es obligatoria.')
    if (!form.sex) faltan.push('El sexo es obligatorio.')
    if (!form.phone.trim()) faltan.push('El teléfono es obligatorio.')
    if (faltan.length) { setErrores(faltan); return }

    try {
      await actualizar.mutateAsync({
        id: paciente.id,
        input: {
          first_name: form.first_name.trim(),
          paternal_surname: form.paternal_surname.trim(),
          maternal_surname: form.maternal_surname.trim(),
          date_of_birth: form.date_of_birth,
          sex: form.sex as Sex,
          phone: form.phone.trim(),
          curp: form.curp.trim(),
          email: form.email.trim(),
          notes: form.notes.trim(),
        },
      })
      onClose()
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <AnimatePresence>
      {paciente && (
        <motion.div
          className="fixed inset-0 z-[60] flex items-start justify-center px-4 py-10 overflow-y-auto"
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-lg rounded-3xl overflow-hidden"
            style={{
              background: 'rgba(255,255,255,0.85)',
              backdropFilter: 'blur(30px) saturate(160%)',
              WebkitBackdropFilter: 'blur(30px) saturate(160%)',
              border: '1px solid rgba(255,255,255,0.7)',
              boxShadow: '0 20px 60px rgba(60,42,12,0.25)',
            }}
            initial={{ opacity: 0, y: 20, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-7 py-5 border-b border-white/40">
              <div>
                <h2 className="text-lg font-bold text-gray-900">Editar paciente</h2>
                <p className="text-xs text-gray-500">{paciente.record_number}</p>
              </div>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-7 py-6 space-y-7">
              {errores.length > 0 && (
                <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                  <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">
                    {errores.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              )}

              <section>
                <p className={SECCION}>Datos personales</p>
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
              </section>

              <section>
                <p className={SECCION}>Contacto</p>
                <div className="space-y-3">
                  <div>
                    <label className="label">Teléfono</label>
                    <input className="input" value={form.phone} onChange={set('phone')} />
                  </div>
                  <div>
                    <label className="label">Email <span className="text-gray-400 font-normal">(opcional)</span></label>
                    <input type="email" className="input" value={form.email} onChange={set('email')} />
                  </div>
                </div>
              </section>

              <section>
                <p className={SECCION}>Identificación</p>
                <div>
                  <label className="label">CURP <span className="text-gray-400 font-normal">(opcional)</span></label>
                  <input className="input uppercase" maxLength={18} value={form.curp} onChange={set('curp')} />
                </div>
              </section>

              <section>
                <p className={SECCION}>Notas</p>
                <textarea className="input resize-none" rows={3} value={form.notes} onChange={set('notes')} />
              </section>
            </div>

            <div className="flex items-center justify-between gap-3 px-7 py-4 border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={onClose} disabled={actualizar.isPending} className="btn-secondary flex-1 disabled:opacity-60">Cancelar</button>
              <button
                onClick={guardar}
                disabled={actualizar.isPending}
                className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                {actualizar.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : 'Guardar cambios'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
