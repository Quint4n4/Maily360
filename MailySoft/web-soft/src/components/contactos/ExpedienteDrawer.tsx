/**
 * ExpedienteDrawer — expediente del paciente "CENTRADO EN LA VISITA" (rediseño Fase 1).
 *
 *   Header (franja superior, ancho completo): avatar + nombre + nº de expediente
 *     + chips (Activo/Inactivo, VIP, Finado) + acciones (Agendar, Dar de baja, X).
 *
 *   Cuerpo (dos columnas con scroll independiente):
 *     Izquierda (fija ~360px): FichaPaciente — identificación, alergias,
 *       indicaciones de enfermería + botón "Editar datos" (lo que ya existía).
 *     Derecha  (flex-1):
 *       - "Visita de hoy" (VisitaDeHoy): ① Enfermería → ② Evolución SOAP → ③ Receta.
 *       - Historial (HistorialExpediente): franja de citas + Libro clínico.
 *
 * Se eliminó la pila de acordeones (Acordeon/AcordeonItem, SignosTab, HistoriaTab,
 * EvolucionTab, DiagnosticosTab, RecetasTab, CitasSection en ese formato). TODAS
 * las funciones siguen accesibles:
 *   - Signos → paso ① de la visita (VisitaSignos, mismos hooks).
 *   - Evolución + exploración + imágenes + addenda → SOAP guiado / libro clínico.
 *   - Recetas → botón directo "+ Receta" en la visita (mismo NuevaReceta).
 *   - Historia clínica viva + evoluciones → Libro clínico (sin cambios).
 *   - Citas → franja-recordatorio del historial.
 *   - Diagnósticos formales (CIE-10) → ver "Pendientes" del reporte (Fase 2).
 *
 * Las secciones clínicas solo se muestran si puedeVerExpedienteClinico(role).
 * Los botones de captura/edición se ocultan según los permisos de rol (solo UX;
 * el backend es la autoridad y devuelve 403).
 */

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, CalendarPlus, UserX, Loader2, AlertTriangle, CalendarClock, Wallet } from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import { initialsOf } from '../../lib/paciente'
import { useUploadPatientAvatar } from '../../hooks/pacientes'
import { useStatement } from '../../hooks/finanzas'
import { useClinicSettings } from '../../hooks/clinica'
import { formatMoney } from '../../lib/format'
import { ApiError } from '../../lib/http'
import { useRole } from '../../auth/RoleContext'
import {
  puedeVerExpedienteClinico, puedeEditarClinico, puedeCapturarSignos, puedeEmitirReceta,
  puedeAnularReceta, puedeVerEstadoCuenta, puedeCobrar,
} from '../../auth/permisos'
import AvatarUploader from '../common/AvatarUploader'
import { useAviso } from '../common/DialogProvider'
import FichaPaciente from '../expediente/FichaPaciente'
import VisitaDeHoy from '../expediente/VisitaDeHoy'
import HistorialExpediente from '../expediente/HistorialExpediente'
import RecetasTab from '../expediente/RecetasTab'
import CitasSection from '../expediente/CitasSection'
import EstadoCuentaExpediente from '../expediente/EstadoCuentaExpediente'

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

  // Estado de cuenta (Fase 1 finanzas-pacientes): visibilidad gobernada por el rol
  // + el flag por clínica `doctors_see_costs`. El backend es la autoridad (403).
  const clinicSettings = useClinicSettings()
  const doctorsSeeCosts = clinicSettings.data?.doctors_see_costs ?? false
  const verEstadoCuenta = puedeVerEstadoCuenta(role, doctorsSeeCosts)
  const cobrar = puedeCobrar(role)

  // Pestaña activa del panel derecho: el expediente o el estado de cuenta.
  const [tab, setTab] = useState<'expediente' | 'cuenta'>('expediente')

  // Saldo para el badge del encabezado. Solo se consulta si el rol puede verlo.
  const statement = useStatement(verEstadoCuenta && paciente ? paciente.id : null)
  const balance = statement.data?.balance ?? null

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
            <div className="shrink-0 px-4 sm:px-6 md:px-8 pt-6 pb-5 border-b border-amber-900/10">
              <button
                onClick={onClose}
                className="absolute top-5 right-5 z-10 w-9 h-9 rounded-full flex items-center justify-center bg-white/70 hover:bg-white transition-colors shadow-sm"
              >
                <X className="w-5 h-5 text-gray-600" />
              </button>

              <div className="flex flex-col sm:flex-row sm:items-start gap-4 sm:gap-5">
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
                  <h2 className="text-2xl font-bold text-gray-900 leading-tight break-words">{paciente.full_name}</h2>
                  <p className="text-sm text-gray-500 mt-0.5">{paciente.record_number}</p>
                  <div className="flex items-center flex-wrap gap-2 mt-2">
                    <span className={`badge ${paciente.is_active ? 'badge-success' : 'badge-neutral'}`}>
                      {paciente.is_active ? 'Activo' : 'Inactivo'}
                    </span>
                    {paciente.is_vip && <span className="badge" style={{ background: '#FBF1D9', color: '#9A7B1E' }}>VIP</span>}
                    {paciente.is_deceased && <span className="badge badge-neutral">Finado</span>}
                    {verEstadoCuenta && balance !== null && <SaldoBadge balance={balance} />}
                  </div>
                </div>

                {/* Acciones del paciente */}
                <div className="flex flex-col gap-2 shrink-0 w-full sm:w-auto mr-0 sm:mr-10">
                  <div className="flex gap-2">
                    <button
                      className="inline-flex items-center justify-center gap-2 w-full sm:w-auto px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:brightness-110"
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
            <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-5 p-4 sm:p-6 md:p-8 overflow-y-auto lg:overflow-hidden">
              {/* Columna izquierda: ficha fija (identificación + alergias + enfermería + editar) */}
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

              {/* Columna central/derecha: pestañas Expediente / Estado de cuenta */}
              <section className="flex-1 min-w-0 lg:h-full lg:overflow-y-auto lg:pr-1 space-y-6">
                {/* Selector de pestañas (solo si hay más de una disponible) */}
                {verEstadoCuenta && (
                  <div className="flex gap-2">
                    <TabButton
                      activo={tab === 'expediente'}
                      onClick={() => setTab('expediente')}
                      icon={<CalendarClock className="w-4 h-4" />}
                    >
                      Expediente
                    </TabButton>
                    <TabButton
                      activo={tab === 'cuenta'}
                      onClick={() => setTab('cuenta')}
                      icon={<Wallet className="w-4 h-4" />}
                    >
                      Estado de cuenta
                    </TabButton>
                  </div>
                )}

                {/* Pestaña: estado de cuenta */}
                {verEstadoCuenta && tab === 'cuenta' ? (
                  <EstadoCuentaExpediente paciente={paciente} puedeCobrar={cobrar} />
                ) : accesoClinico ? (
                  <>
                    <VisitaDeHoy
                      paciente={paciente}
                      puedeCapturarSignos={capturarSignos}
                      puedeEditarClinico={editarClinico}
                      puedeEmitirReceta={emitirReceta}
                    />
                    <HistorialExpediente
                      paciente={paciente}
                      verClinico={accesoClinico}
                      verEstadoCuenta={verEstadoCuenta}
                    />
                    {/* Historial de recetas emitidas (ver PDF / copiar a nueva / anular). */}
                    <RecetasTab
                      paciente={paciente}
                      puedeEmitir={emitirReceta}
                      puedeAnular={puedeAnularReceta(role)}
                    />
                  </>
                ) : (
                  // Roles sin acceso clínico (recepción/finanzas): solo citas.
                  <div className="space-y-4">
                    <div className="flex items-center gap-2">
                      <CalendarClock className="w-4 h-4" style={{ color: '#C9A227' }} />
                      <h3 className="text-sm font-semibold uppercase tracking-wide text-amber-700/80">Citas</h3>
                    </div>
                    <CitasSection paciente={paciente} />
                  </div>
                )}
              </section>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/**
 * Badge de saldo del paciente en el encabezado.
 *   > 0 → "Saldo: $X por cobrar" (ámbar/rojo).
 *   ≤ 0 → "Sin adeudo" (verde). No existen saldos a favor (el backend los impide).
 */
function SaldoBadge({ balance }: { balance: number }) {
  if (balance > 0) {
    const fuerte = balance >= 1000
    return (
      <span
        className="badge"
        style={{
          background: fuerte ? '#FDE8E8' : '#FBF1D9',
          color: fuerte ? '#C0392B' : '#9A7B1E',
        }}
      >
        Saldo: {formatMoney(balance)} por cobrar
      </span>
    )
  }
  return <span className="badge badge-success">Sin adeudo</span>
}

/** Botón de pestaña del panel derecho (activo en dorado). */
function TabButton({
  activo, onClick, icon, children,
}: {
  activo: boolean
  onClick: () => void
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all"
      style={{
        background: activo ? '#C9A227' : 'rgba(255,255,255,0.7)',
        color: activo ? '#fff' : '#854F0B',
        border: activo ? '1px solid #C9A227' : '1px solid rgba(201,162,39,0.3)',
        boxShadow: activo ? '0 4px 14px rgba(201,162,39,0.35)' : 'none',
      }}
    >
      {icon} {children}
    </button>
  )
}
