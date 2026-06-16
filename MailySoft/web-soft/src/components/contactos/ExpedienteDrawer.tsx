/**
 * ExpedienteDrawer — expediente del paciente con pestañas.
 *
 * Pestañas:
 *   Resumen          — contacto, identificación, NOM-004, próxima cita, historial + alergias.
 *   Historia clínica — formulario NOM-004 por bloques (acordeón).        [solo clínico]
 *   Signos vitales   — captura + tabla (IMC) + gráficas de tendencia.    [solo clínico]
 *   Evolución        — notas inmutables + addenda + alta desde cita.     [solo clínico]
 *   Diagnósticos     — lista + alta + resolver.                          [solo clínico]
 *
 * Las pestañas clínicas solo se muestran si puedeVerExpedienteClinico(role).
 * Los botones de captura/edición se ocultan según puedeEditarClinico / puedeCapturarSignos
 * (solo UX; el backend es la autoridad y devuelve 403).
 */

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  X, Pencil, CalendarPlus, UserX, Loader2, AlertTriangle,
  FileText, Stethoscope, Activity, ClipboardCheck, LayoutGrid,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import { initialsOf } from '../../lib/paciente'
import { useUploadPatientAvatar } from '../../hooks/pacientes'
import { ApiError } from '../../lib/http'
import { useRole } from '../../auth/RoleContext'
import {
  puedeVerExpedienteClinico, puedeEditarClinico, puedeCapturarSignos,
} from '../../auth/permisos'
import AvatarUploader from '../common/AvatarUploader'
import ResumenTab from '../expediente/ResumenTab'
import HistoriaTab from '../expediente/HistoriaTab'
import SignosTab from '../expediente/SignosTab'
import EvolucionTab from '../expediente/EvolucionTab'
import DiagnosticosTab from '../expediente/DiagnosticosTab'

type TabKey = 'resumen' | 'historia' | 'signos' | 'evolucion' | 'diagnosticos'

interface TabDef {
  key: TabKey
  label: string
  icon: LucideIcon
  /** true = solo visible para roles con acceso clínico. */
  clinico: boolean
}

const TABS: TabDef[] = [
  { key: 'resumen', label: 'Resumen', icon: LayoutGrid, clinico: false },
  { key: 'historia', label: 'Historia clínica', icon: FileText, clinico: true },
  { key: 'signos', label: 'Signos vitales', icon: Activity, clinico: true },
  { key: 'evolucion', label: 'Evolución', icon: Stethoscope, clinico: true },
  { key: 'diagnosticos', label: 'Diagnósticos', icon: ClipboardCheck, clinico: true },
]

interface ExpedienteDrawerProps {
  paciente: PatientOut | null
  onClose: () => void
  /** Si puede ver el expediente clínico (deriva del rol; default true por compat). */
  verClinico?: boolean
  /** Si se puede editar/dar de baja al paciente (módulo contactos). */
  puedeEditar?: boolean
  onEditar?: () => void
  onDarDeBaja?: () => void
  dandoDeBaja?: boolean
}

export default function ExpedienteDrawer({
  paciente, onClose, verClinico,
  puedeEditar = false, onEditar, onDarDeBaja, dandoDeBaja = false,
}: ExpedienteDrawerProps) {
  const { role } = useRole()
  // El acceso clínico se decide por rol; verClinico (prop) puede forzarlo a false.
  const accesoClinico = (verClinico ?? true) && puedeVerExpedienteClinico(role)
  const editarClinico = puedeEditarClinico(role)
  const capturarSignos = puedeCapturarSignos(role)

  const [tab, setTab] = useState<TabKey>('resumen')

  // Al abrir otro paciente, volver al Resumen.
  useEffect(() => { setTab('resumen') }, [paciente?.id])

  const subirAvatar = useUploadPatientAvatar()
  const onAvatarFile = (file: File) => {
    if (!paciente) return
    subirAvatar.mutate({ id: paciente.id, file }, {
      onError: e => {
        const d = e instanceof ApiError ? e.body?.detail : null
        window.alert(Array.isArray(d) ? d.join(' ') : (d ?? 'No se pudo subir la imagen.'))
      },
    })
  }

  const tabsVisibles = TABS.filter(t => !t.clinico || accesoClinico)

  return (
    <AnimatePresence>
      {paciente && (
        <motion.div
          className="fixed inset-0 z-50 overflow-y-auto p-4 md:p-8 flex items-start justify-center"
          style={{ background: 'rgba(40,28,8,0.35)', backdropFilter: 'blur(8px)' }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="relative w-full max-w-6xl glass-card rounded-3xl p-6 md:p-8"
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.97 }}
            transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
            onClick={e => e.stopPropagation()}
          >
            {/* Cerrar */}
            <button
              onClick={onClose}
              className="absolute top-5 right-5 z-10 w-9 h-9 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors shadow-sm"
            >
              <X className="w-5 h-5 text-gray-600" />
            </button>

            {/* ════ Cabecera del paciente ════ */}
            <div className="flex items-start gap-5 mb-5">
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
                  <button onClick={onEditar} disabled={!puedeEditar}
                    className="btn-secondary disabled:opacity-40 disabled:cursor-not-allowed">
                    <Pencil className="w-4 h-4" /> Editar
                  </button>
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

            {/* Aviso de expediente provisional */}
            {paciente.is_provisional && (
              <div className="flex items-start gap-3 rounded-2xl px-5 py-4 mb-5" style={{ background: '#FBF1D9', border: '1px solid rgba(201,162,39,0.4)' }}>
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

            {/* ════ Pestañas ════ */}
            <div className="flex flex-wrap gap-1.5 mb-5 border-b border-amber-900/10 pb-3">
              {tabsVisibles.map(t => {
                const Icon = t.icon
                const activo = tab === t.key
                return (
                  <button key={t.key} onClick={() => setTab(t.key)}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium transition-colors"
                    style={activo
                      ? { background: '#C9A227', color: '#fff' }
                      : { background: 'rgba(255,255,255,0.6)', color: '#7A756C' }}>
                    <Icon className="w-4 h-4" /> {t.label}
                  </button>
                )
              })}
            </div>

            {/* ════ Contenido de la pestaña ════ */}
            {tab === 'resumen' && (
              <ResumenTab paciente={paciente} verClinico={accesoClinico} puedeEditarClinico={editarClinico} />
            )}
            {tab === 'historia' && accesoClinico && (
              <HistoriaTab paciente={paciente} puedeEditar={editarClinico} />
            )}
            {tab === 'signos' && accesoClinico && (
              <SignosTab paciente={paciente} puedeCapturar={capturarSignos} />
            )}
            {tab === 'evolucion' && accesoClinico && (
              <EvolucionTab paciente={paciente} puedeEditar={editarClinico} />
            )}
            {tab === 'diagnosticos' && accesoClinico && (
              <DiagnosticosTab paciente={paciente} puedeEditar={editarClinico} />
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
