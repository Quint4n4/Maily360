/**
 * ExpedienteDrawer — expediente del paciente en layout de DOS COLUMNAS (estilo legacy).
 *
 *   Header (franja superior, ancho completo): avatar + nombre + nº de expediente
 *     + chips (Activo/Inactivo, VIP, Finado) + acciones (Editar, Agendar, Dar de baja, X).
 *
 *   Cuerpo (dos columnas con scroll independiente):
 *     Izquierda (fija ~360px): FichaPaciente — alergias + contacto + identificación + NOM-004.
 *     Derecha  (flex-1):       Historia Clínica en ACORDEÓN:
 *       1. Enfermería (SignosTab, abierta por defecto)   [solo clínico]
 *       2. Historia clínica (HistoriaTab)                [solo clínico]
 *       3. Evolución (EvolucionTab)                      [solo clínico]
 *       4. Diagnósticos (DiagnosticosTab)                [solo clínico]
 *       5. Citas (CitasSection)                          [todos los que ven el expediente]
 *
 * Las secciones clínicas solo se muestran si puedeVerExpedienteClinico(role).
 * Los botones de captura/edición se ocultan según puedeEditarClinico / puedeCapturarSignos
 * (solo UX; el backend es la autoridad y devuelve 403).
 */

import { motion, AnimatePresence } from 'framer-motion'
import {
  X, CalendarPlus, UserX, Loader2, AlertTriangle,
  FileText, Stethoscope, Activity, ClipboardCheck, CalendarClock, Pill,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import { initialsOf } from '../../lib/paciente'
import { useUploadPatientAvatar } from '../../hooks/pacientes'
import { ApiError } from '../../lib/http'
import { useRole } from '../../auth/RoleContext'
import {
  puedeVerExpedienteClinico, puedeEditarClinico, puedeCapturarSignos,
  puedeEmitirReceta, puedeAnularReceta,
} from '../../auth/permisos'
import AvatarUploader from '../common/AvatarUploader'
import { useAviso } from '../common/DialogProvider'
import FichaPaciente from '../expediente/FichaPaciente'
import { Acordeon, AcordeonItem } from '../expediente/Acordeon'
import HistoriaTab from '../expediente/HistoriaTab'
import SignosTab from '../expediente/SignosTab'
import EvolucionTab from '../expediente/EvolucionTab'
import DiagnosticosTab from '../expediente/DiagnosticosTab'
import RecetasTab from '../expediente/RecetasTab'
import CitasSection from '../expediente/CitasSection'

interface ExpedienteDrawerProps {
  paciente: PatientOut | null
  onClose: () => void
  /** Si puede ver el expediente clínico (deriva del rol; default true por compat). */
  verClinico?: boolean
  /** Si se puede editar/dar de baja al paciente (módulo contactos). */
  puedeEditar?: boolean
  onDarDeBaja?: () => void
  dandoDeBaja?: boolean
}

export default function ExpedienteDrawer({
  paciente, onClose, verClinico,
  puedeEditar = false, onDarDeBaja, dandoDeBaja = false,
}: ExpedienteDrawerProps) {
  const { role } = useRole()
  // El acceso clínico se decide por rol; verClinico (prop) puede forzarlo a false.
  const accesoClinico = (verClinico ?? true) && puedeVerExpedienteClinico(role)
  const editarClinico = puedeEditarClinico(role)
  const capturarSignos = puedeCapturarSignos(role)
  const emitirReceta = puedeEmitirReceta(role)
  const anularReceta = puedeAnularReceta(role)

  const subirAvatar = useUploadPatientAvatar()
  const aviso = useAviso()
  const onAvatarFile = (file: File) => {
    if (!paciente) return
    subirAvatar.mutate({ id: paciente.id, file }, {
      onError: e => {
        const d = e instanceof ApiError ? e.body?.detail : null
        void aviso({
          mensaje: Array.isArray(d) ? d.join(' ') : (d ?? 'No se pudo subir la imagen.'),
          tipo: 'error',
        })
      },
    })
  }

  return (
    <AnimatePresence>
      {paciente && (
        <motion.div
          className="fixed inset-0 z-50 p-2 sm:p-4 flex items-center justify-center"
          style={{ background: 'rgba(40,28,8,0.35)', backdropFilter: 'blur(8px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full glass-card rounded-3xl flex flex-col overflow-hidden"
            style={{ maxWidth: '95vw', height: '95vh' }}
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* ════ Header (franja superior, ancho completo) ════ */}
            <div className="shrink-0 px-6 md:px-8 pt-6 pb-5 border-b border-amber-900/10">
              <button
                onClick={onClose}
                className="absolute top-5 right-5 z-10 w-9 h-9 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors shadow-sm"
              >
                <X className="w-5 h-5 text-gray-600" />
              </button>

              <div className="flex items-start gap-5">
                <div className="relative shrink-0">
                  <div className="absolute -inset-2 rounded-full"
                    style={{ background: 'conic-gradient(from 120deg, #E8C766, #C9A227, #F5E6B8, #C9A227, #E8C766)', filter: 'blur(8px)', opacity: 0.5 }} />
                  <AvatarUploader
                    src={paciente.avatar}
                    initials={initialsOf(paciente)}
                    size={96}
                    editable={puedeEditar}
                    uploading={subirAvatar.isPending}
                    onFile={onAvatarFile}
                  />
                </div>

                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-semibold uppercase tracking-widest text-amber-700/70">Expediente del paciente</p>
                  <h2 className="text-2xl font-bold text-gray-900 leading-tight truncate">{paciente.full_name}</h2>
                  <p className="text-sm text-gray-500 mt-0.5">{paciente.record_number}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <span className={`badge ${paciente.is_active ? 'badge-success' : 'badge-neutral'}`}>
                      {paciente.is_active ? 'Activo' : 'Inactivo'}
                    </span>
                    {paciente.is_vip && <span className="badge" style={{ background: '#FBF1D9', color: '#9A7B1E' }}>VIP</span>}
                    {paciente.is_deceased && <span className="badge badge-neutral">Finado</span>}
                  </div>
                </div>

                {/* Acciones del paciente */}
                <div className="flex flex-col gap-2 shrink-0 mr-10">
                  <div className="flex gap-2">
                    <button
                      className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
                      style={{ background: '#C9A227', boxShadow: '0 4px 14px rgba(201,162,39,0.4)' }}>
                      <CalendarPlus className="w-4 h-4" /> Agendar
                    </button>
                  </div>
                  {puedeEditar && paciente.is_active && (
                    <button onClick={onDarDeBaja} disabled={dandoDeBaja}
                      className="inline-flex items-center justify-center gap-1.5 text-xs font-medium text-red-600 hover:text-red-700 hover:underline transition-colors disabled:opacity-60">
                      {dandoDeBaja
                        ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Dando de baja…</>
                        : <><UserX className="w-3.5 h-3.5" /> Dar de baja</>}
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* ════ Cuerpo en dos columnas (scroll independiente) ════ */}
            <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-5 p-6 md:p-8 overflow-y-auto lg:overflow-hidden">
              {/* Columna izquierda: ficha fija */}
              <aside className="w-full lg:w-[380px] lg:shrink-0 lg:h-full lg:overflow-y-auto lg:pr-1">
                {/* Aviso de expediente provisional */}
                {paciente.is_provisional && (
                  <div className="flex items-start gap-3 rounded-2xl px-5 py-4 mb-4" style={{ background: '#FBF1D9', border: '1px solid rgba(201,162,39,0.4)' }}>
                    <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0" style={{ color: '#9A7B1E' }} />
                    <div>
                      <p className="text-sm font-semibold" style={{ color: '#9A7B1E' }}>Expediente provisional</p>
                      <p className="text-xs" style={{ color: '#9A7B1E' }}>
                        Este paciente se creó al agendar con datos mínimos. Falta completar su información personal
                        (fecha de nacimiento, sexo, contacto). {puedeEditar ? 'Usa «Editar» para completarlo.' : ''}
                      </p>
                    </div>
                  </div>
                )}
                <FichaPaciente
                  paciente={paciente}
                  verClinico={accesoClinico}
                  puedeEditarClinico={editarClinico}
                  puedeEditar={puedeEditar}
                />
              </aside>

              {/* Columna derecha: Historia Clínica en acordeón */}
              <section className="flex-1 min-w-0 lg:h-full lg:overflow-y-auto lg:pr-1">
                <Acordeon>
                  {accesoClinico && (
                    <>
                      <AcordeonItem title="Enfermería" icon={Activity} defaultOpen>
                        {() => <SignosTab paciente={paciente} puedeCapturar={capturarSignos} />}
                      </AcordeonItem>
                      <AcordeonItem title="Historia clínica" icon={FileText}>
                        {() => <HistoriaTab paciente={paciente} puedeEditar={editarClinico} />}
                      </AcordeonItem>
                      <AcordeonItem title="Evolución" icon={Stethoscope}>
                        {() => <EvolucionTab paciente={paciente} puedeEditar={editarClinico} />}
                      </AcordeonItem>
                      <AcordeonItem title="Diagnósticos" icon={ClipboardCheck}>
                        {() => <DiagnosticosTab paciente={paciente} puedeEditar={editarClinico} />}
                      </AcordeonItem>
                      <AcordeonItem title="Recetas" icon={Pill}>
                        {() => (
                          <RecetasTab
                            paciente={paciente}
                            puedeEmitir={emitirReceta}
                            puedeAnular={anularReceta}
                          />
                        )}
                      </AcordeonItem>
                    </>
                  )}
                  <AcordeonItem title="Citas" icon={CalendarClock} defaultOpen={!accesoClinico}>
                    {() => <CitasSection paciente={paciente} />}
                  </AcordeonItem>
                </Acordeon>
              </section>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
