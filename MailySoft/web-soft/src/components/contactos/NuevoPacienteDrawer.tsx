import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Info, AlertCircle, Loader2 } from 'lucide-react'
import { useCreatePatient } from '../../hooks/pacientes'
import { erroresDe } from '../../lib/apiErrors'
import type { Sex } from '../../types/paciente'
import {
  MSG, errorDeCampo, esCurpValido, esEmailValido, esTelefonoValido,
} from '../../lib/validacion'

interface NuevoPacienteDrawerProps {
  open: boolean
  onClose: () => void
}

const SECCION = 'text-xs font-semibold uppercase tracking-wide text-amber-700/80 mb-3'

const FORM_VACIO = {
  first_name: '', paternal_surname: '', maternal_surname: '',
  date_of_birth: '', sex: '' as '' | Sex, phone: '', email: '', curp: '', notes: '',
}

export default function NuevoPacienteDrawer({ open, onClose }: NuevoPacienteDrawerProps) {
  const [form, setForm] = useState(FORM_VACIO)
  const [errores, setErrores] = useState<string[]>([])
  const crear = useCreatePatient()

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm(prev => ({ ...prev, [k]: e.target.value }))

  // Errores de FORMATO (solo UX). Vacío = sin error. El backend revalida.
  const errPhone = errorDeCampo(form.phone, esTelefonoValido, MSG.telefono)
  const errEmail = errorDeCampo(form.email, esEmailValido, MSG.email)
  const errCurp = errorDeCampo(form.curp, esCurpValido, MSG.curp)
  const formatoInvalido = Boolean(errPhone || errEmail || errCurp)

  const cerrar = () => {
    setForm(FORM_VACIO)
    setErrores([])
    onClose()
  }

  const guardar = async () => {
    setErrores([])
    // Validación mínima en cliente (el backend valida a fondo).
    const faltan: string[] = []
    if (!form.first_name.trim()) faltan.push('El nombre es obligatorio.')
    if (!form.paternal_surname.trim()) faltan.push('El apellido paterno es obligatorio.')
    if (!form.date_of_birth) faltan.push('La fecha de nacimiento es obligatoria.')
    if (!form.sex) faltan.push('El sexo es obligatorio.')
    if (!form.phone.trim()) faltan.push('El teléfono es obligatorio.')
    if (faltan.length) { setErrores(faltan); return }
    if (formatoInvalido) {
      setErrores(['Revisa los campos marcados en rojo antes de guardar.'])
      return
    }

    try {
      await crear.mutateAsync({
        first_name: form.first_name.trim(),
        paternal_surname: form.paternal_surname.trim(),
        maternal_surname: form.maternal_surname.trim(),
        date_of_birth: form.date_of_birth,
        sex: form.sex as Sex,
        phone: form.phone.trim(),
        curp: form.curp.trim(),
        email: form.email.trim(),
        notes: form.notes.trim(),
      })
      cerrar()
    } catch (err) {
      setErrores(erroresDe(err, 'No se pudo guardar el paciente.'))
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 py-10 overflow-y-auto"
          style={{ background: 'rgba(40,28,8,0.4)', backdropFilter: 'blur(6px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={cerrar}
        >
          <motion.div
            className="relative w-full max-w-lg rounded-3xl overflow-hidden"
            style={{
              background: 'rgba(255,255,255,0.82)',
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
            {/* Header */}
            <div className="flex items-center justify-between px-7 py-5 border-b border-white/40">
              <h2 className="text-lg font-bold text-gray-900">Nuevo paciente</h2>
              <button onClick={cerrar} className="text-gray-400 hover:text-gray-700 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Cuerpo */}
            <div className="px-7 py-6 space-y-7">

              {/* Errores */}
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
                    <input className="input" value={form.first_name} onChange={set('first_name')} placeholder="María" />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="label">Apellido paterno</label>
                      <input className="input" value={form.paternal_surname} onChange={set('paternal_surname')} placeholder="González" />
                    </div>
                    <div>
                      <label className="label">Apellido materno</label>
                      <input className="input" value={form.maternal_surname} onChange={set('maternal_surname')} placeholder="Pérez" />
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
                    <input
                      className={`input${errPhone ? ' input-error' : ''}`}
                      inputMode="tel"
                      value={form.phone}
                      onChange={set('phone')}
                      placeholder="55 1234 5678"
                    />
                    {errPhone && <p className="mt-1 text-xs text-red-600">{errPhone}</p>}
                  </div>
                  <div>
                    <label className="label">Email <span className="text-gray-400 font-normal">(opcional)</span></label>
                    <input
                      type="email"
                      className={`input${errEmail ? ' input-error' : ''}`}
                      inputMode="email"
                      value={form.email}
                      onChange={set('email')}
                      placeholder="paciente@correo.mx"
                    />
                    {errEmail && <p className="mt-1 text-xs text-red-600">{errEmail}</p>}
                  </div>
                </div>
              </section>

              <section>
                <p className={SECCION}>Identificación</p>
                <div>
                  <label className="label">CURP <span className="text-gray-400 font-normal">(opcional)</span></label>
                  <input
                    className={`input uppercase${errCurp ? ' input-error' : ''}`}
                    maxLength={18}
                    value={form.curp}
                    onChange={set('curp')}
                    placeholder="18 caracteres"
                  />
                  {errCurp && <p className="mt-1 text-xs text-red-600">{errCurp}</p>}
                </div>
              </section>

              <section>
                <p className={SECCION}>Notas</p>
                <textarea className="input resize-none" rows={3} value={form.notes} onChange={set('notes')} placeholder="Observaciones, alergias, antecedentes…" />
              </section>

              <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(201,162,39,0.10)', border: '1px solid rgba(201,162,39,0.25)' }}>
                <Info className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#C9A227' }} />
                <p className="text-xs text-amber-800">El número de expediente se asignará automáticamente al guardar.</p>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between gap-3 px-7 py-4 border-t border-white/40" style={{ background: 'rgba(255,255,255,0.25)' }}>
              <button onClick={cerrar} disabled={crear.isPending} className="btn-secondary flex-1 disabled:opacity-60">Cancelar</button>
              <button
                onClick={guardar}
                disabled={crear.isPending || formatoInvalido}
                className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}
              >
                {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : 'Guardar paciente'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
