import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2 } from 'lucide-react'
import { useUpdatePatient } from '../../hooks/pacientes'
import type { PatientOut } from '../../types/paciente'
import {
  CamposContacto, CamposDatosPersonales, CamposDomicilio, CamposNom004,
  SECCION_LABEL, erroresDePaciente, usePacienteForm,
} from './pacienteForm'

interface EditarPacienteDrawerProps {
  paciente: PatientOut | null
  onClose: () => void
}

export default function EditarPacienteDrawer({ paciente, onClose }: EditarPacienteDrawerProps) {
  const { form, set, setForm, validar, construirInput } = usePacienteForm(paciente)
  const [errores, setErrores] = useState<string[]>([])
  const actualizar = useUpdatePatient()

  // Limpiar errores al cambiar de paciente.
  useEffect(() => { setErrores([]) }, [paciente])

  const guardar = async () => {
    if (!paciente) return
    const faltan = validar()
    if (faltan.length) { setErrores(faltan); return }
    setErrores([])
    try {
      await actualizar.mutateAsync({ id: paciente.id, input: construirInput() })
      onClose()
    } catch (err) {
      setErrores(erroresDePaciente(err))
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
                <p className={SECCION_LABEL}>Datos personales</p>
                <CamposDatosPersonales form={form} set={set} setForm={setForm} />
              </section>

              <section>
                <p className={SECCION_LABEL}>Contacto</p>
                <CamposContacto form={form} set={set} setForm={setForm} />
              </section>

              <section>
                <p className={SECCION_LABEL}>Domicilio</p>
                <CamposDomicilio form={form} set={set} setForm={setForm} />
              </section>

              <section>
                <p className={SECCION_LABEL}>Identificación y datos NOM-004</p>
                <CamposNom004 form={form} set={set} setForm={setForm} />
              </section>

              <section>
                <p className={SECCION_LABEL}>Notas</p>
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
