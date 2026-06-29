import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertCircle, Loader2, Eye, EyeOff, ShieldCheck } from 'lucide-react'
import { useCreateMember } from '../../hooks/miembros'
import { erroresDe } from '../../lib/apiErrors'
import { ROLES } from '../../auth/permisos'
import type { ClinicRole } from '../../auth/permisos'

interface Props {
  open: boolean
  onClose: () => void
}

const FORM_VACIO = {
  first_name: '', last_name: '', email: '', password: '', role: '' as '' | ClinicRole,
}

export default function NuevoMiembroDrawer({ open, onClose }: Props) {
  const [form, setForm] = useState(FORM_VACIO)
  const [verPass, setVerPass] = useState(false)
  const [errores, setErrores] = useState<string[]>([])
  const crear = useCreateMember()

  useEffect(() => {
    if (open) { setForm(FORM_VACIO); setErrores([]); setVerPass(false) }
  }, [open])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(prev => ({ ...prev, [k]: e.target.value }))

  const guardar = async () => {
    setErrores([])
    const faltan: string[] = []
    if (!form.first_name.trim()) faltan.push('El nombre es obligatorio.')
    if (!form.email.trim()) faltan.push('El correo es obligatorio.')
    if (!form.password) faltan.push('La contraseña es obligatoria.')
    if (form.password && form.password.length < 10) faltan.push('La contraseña debe tener al menos 10 caracteres.')
    if (!form.role) faltan.push('Selecciona un rol.')
    if (faltan.length) { setErrores(faltan); return }

    try {
      await crear.mutateAsync({
        email: form.email.trim(),
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        password: form.password,
        role: form.role as ClinicRole,
      })
      onClose()
    } catch (err) {
      setErrores(erroresDe(err, 'No se pudo crear el miembro.'))
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40"
            style={{ background: 'rgba(40,28,8,0.45)', backdropFilter: 'blur(4px)' }}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside
            className="fixed top-0 right-0 z-50 h-full w-full max-w-md flex flex-col"
            style={{ background: 'rgba(255,255,255,0.94)', backdropFilter: 'blur(24px)', borderLeft: '1px solid rgba(201,162,39,0.3)' }}
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
          >
            <div className="flex items-center justify-between px-6 py-5 border-b border-amber-900/10">
              <h2 className="text-lg font-bold text-gray-900">Nuevo miembro</h2>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-5 h-5" /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              {errores.length > 0 && (
                <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(190,40,40,0.10)', border: '1px solid rgba(190,40,40,0.25)' }}>
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
                  <ul className="text-xs text-red-700 space-y-0.5 list-disc list-inside">
                    {errores.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Nombre(s)</label>
                  <input className="input" value={form.first_name} onChange={set('first_name')} placeholder="María" />
                </div>
                <div>
                  <label className="label">Apellidos</label>
                  <input className="input" value={form.last_name} onChange={set('last_name')} placeholder="González Pérez" />
                </div>
              </div>

              <div>
                <label className="label">Correo electrónico</label>
                <input type="email" className="input" value={form.email} onChange={set('email')} placeholder="maria@clinica.mx" />
              </div>

              <div>
                <label className="label">Contraseña</label>
                <div className="relative">
                  <input type={verPass ? 'text' : 'password'} className="input pr-10" value={form.password} onChange={set('password')} placeholder="Mínimo 10 caracteres" />
                  <button type="button" tabIndex={-1} onClick={() => setVerPass(v => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                    {verPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <div className="flex items-start gap-1.5 mt-1.5 text-[11px] text-gray-500">
                  <ShieldCheck className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: '#C9A227' }} />
                  <span>Mínimo 10 caracteres. No puede ser solo números ni una contraseña común.</span>
                </div>
              </div>

              <div>
                <label className="label">Rol</label>
                <select className="input" value={form.role} onChange={set('role')}>
                  <option value="">Selecciona un rol…</option>
                  {ROLES.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
                </select>
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-amber-900/10 bg-white/60">
              <button onClick={onClose} disabled={crear.isPending} className="btn-secondary flex-1 disabled:opacity-60">Cancelar</button>
              <button onClick={guardar} disabled={crear.isPending}
                className="flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
                style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Creando…</> : 'Crear miembro'}
              </button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
