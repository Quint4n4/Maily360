import { motion, AnimatePresence } from 'framer-motion'
import { X, Info, UserPlus } from 'lucide-react'

interface Props {
  open: boolean
  onClose: () => void
}

/**
 * Alta de doctor: por ahora informativa.
 * Crear un doctor requiere que el usuario YA sea miembro de la clínica (con rol
 * Médico). El backend liga el doctor a una membresía existente (membership_id),
 * así que primero hay que construir la gestión de miembros/invitaciones.
 */
export default function NuevoDoctorDrawer({ open, onClose }: Props) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40"
            style={{ background: 'rgba(40,28,8,0.45)', backdropFilter: 'blur(4px)' }}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside
            className="fixed top-0 right-0 z-50 h-full w-full max-w-md flex flex-col"
            style={{ background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(24px)', borderLeft: '1px solid rgba(201,162,39,0.3)' }}
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
          >
            <div className="flex items-center justify-between px-6 py-5 border-b border-amber-900/10">
              <h2 className="text-lg font-bold text-gray-900">Nuevo doctor</h2>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-700 transition-colors"><X className="w-5 h-5" /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
              <div className="w-14 h-14 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(201,162,39,0.14)' }}>
                <UserPlus className="w-7 h-7" style={{ color: '#C9A227' }} />
              </div>

              <div className="flex items-start gap-2.5 rounded-xl px-4 py-3" style={{ background: 'rgba(201,162,39,0.10)', border: '1px solid rgba(201,162,39,0.25)' }}>
                <Info className="w-4 h-4 mt-0.5 shrink-0" style={{ color: '#C9A227' }} />
                <div className="text-sm text-amber-800 space-y-2">
                  <p>Para dar de alta un doctor, primero el usuario debe ser <b>miembro de la clínica</b> con rol <b>Médico</b>.</p>
                  <p>La gestión de miembros e invitaciones llegará pronto; en cuanto exista, podrás convertir a un miembro en doctor desde aquí.</p>
                  <p className="text-xs">Mientras tanto, un administrador puede crearlos desde el panel de Django admin.</p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end px-6 py-4 border-t border-amber-900/10 bg-white/60">
              <button onClick={onClose} className="btn-secondary">Entendido</button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
