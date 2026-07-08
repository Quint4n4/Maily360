import { lazy, Suspense, ReactElement, useEffect } from 'react'
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { onPasswordChangeRequired } from './lib/http'
import { RoleProvider, useRole } from './auth/RoleContext'
import { Modulo, accesoModulo, inicioDeRol, puedeAccederConsultorio } from './auth/permisos'
import { PlatformRoleProvider, usePlatformRole } from './platform/PlatformRoleContext'
import { DialogProvider } from './components/common/DialogProvider'
import { PlatModulo, accesoModuloPlat, inicioPlat } from './platform/permisos'
import AlertaCitas from './components/agenda/AlertaCitas'
import LuzRecordatorios from './components/agenda/LuzRecordatorios'

// Páginas con carga diferida (code-splitting): cada ruta es su propio chunk,
// así el bundle inicial no arrastra Finanzas (recharts/jspdf/xlsx) ni el resto
// hasta que se visita esa ruta.
const LoginPage = lazy(() => import('./pages/LoginPage'))
const VerificarRecetaPage = lazy(() => import('./pages/VerificarRecetaPage'))
const CambiarContrasenaPage = lazy(() => import('./pages/CambiarContrasenaPage'))
const AgendaPage = lazy(() => import('./pages/AgendaPage'))
const ContactosPage = lazy(() => import('./pages/ContactosPage'))
const PersonalPage = lazy(() => import('./pages/PersonalPage'))
const FinanzasPage = lazy(() => import('./pages/FinanzasPage'))
const CotizacionesPage = lazy(() => import('./pages/CotizacionesPage'))
const PaquetesPage = lazy(() => import('./pages/PaquetesPage'))
const NotasPage = lazy(() => import('./pages/NotasPage'))
const MiConsultorioPage = lazy(() => import('./pages/MiConsultorioPage'))
const DashboardPlataformaPage = lazy(() => import('./pages/plataforma/DashboardPage'))
const ClinicasPage = lazy(() => import('./pages/plataforma/ClinicasPage'))
const SuscripcionesPage = lazy(() => import('./pages/plataforma/SuscripcionesPage'))
const UsuariosPage = lazy(() => import('./pages/plataforma/UsuariosPage'))
const SistemaPage = lazy(() => import('./pages/plataforma/SistemaPage'))
const AuditoriaPage = lazy(() => import('./pages/plataforma/AuditoriaPage'))

/* App de la clínica: exige sesión válida (RequireAuth) y luego protege por rol */
function Guard({ modulo, children }: { modulo: Modulo; children: ReactElement }) {
  const { role } = useRole()
  if (!accesoModulo(role, modulo)) return <Navigate to={inicioDeRol(role)} replace />
  return children
}

/* Atajo: ruta de clínica protegida por sesión + rol */
function ClinicRoute({ modulo, children }: { modulo: Modulo; children: ReactElement }) {
  return (
    <RequireAuth>
      <Guard modulo={modulo}>{children}</Guard>
    </RequireAuth>
  )
}

/* Guard de rol para "Mi Consultorio" (owner/admin/doctor). */
function ConsultorioGuard({ children }: { children: ReactElement }) {
  const { role } = useRole()
  if (!puedeAccederConsultorio(role)) return <Navigate to={inicioDeRol(role)} replace />
  return children
}

/* "Mi Consultorio": ruta de clínica protegida por sesión + rol (owner/admin/doctor).
   No encaja en un Modulo del menú, así que usa su propio guard de rol. */
function ConsultorioRoute({ children }: { children: ReactElement }) {
  return (
    <RequireAuth>
      <ConsultorioGuard>{children}</ConsultorioGuard>
    </RequireAuth>
  )
}

/* Panel de plataforma: exige sesión + ser staff de Maily + rol de plataforma */
function PlatGuard({ modulo, children }: { modulo: PlatModulo; children: ReactElement }) {
  const { isPlatformStaff, clinicRole } = useAuth()
  const { role } = usePlatformRole()
  // No es staff de Maily → de vuelta a su app de clínica (o al login).
  if (!isPlatformStaff) return <Navigate to={clinicRole ? inicioDeRol(clinicRole) : '/login'} replace />
  if (!accesoModuloPlat(role, modulo)) return <Navigate to={inicioPlat(role)} replace />
  return children
}

/* Atajo: ruta de plataforma protegida por sesión + staff + rol */
function PlatformRoute({ modulo, children }: { modulo: PlatModulo; children: ReactElement }) {
  return (
    <RequireAuth>
      <PlatGuard modulo={modulo}>{children}</PlatGuard>
    </RequireAuth>
  )
}

/* Vigilante del 403 password_change_required: si el backend bloquea un endpoint
   de negocio porque la contraseña es temporal (p. ej. must_change_password cambió
   a media sesión tras un reset), navega a la pantalla de cambio. Se suscribe al
   cliente http central (que no conoce React) con el mismo patrón que
   tokenStore.onAccessTokenChange. */
function VigilanteCambioPassword() {
  const navigate = useNavigate()
  const { reloadMe } = useAuth()

  useEffect(() => {
    return onPasswordChangeRequired(() => {
      // Sincroniza /me/ (must_change_password) — /me/ sí funciona en este estado.
      void reloadMe().catch(() => {})
      navigate('/cambiar-contrasena', { replace: true })
    })
  }, [navigate, reloadMe])

  return null
}

/* Fallback mientras carga el chunk de una página (code-splitting). */
function PantallaCargando() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '60vh',
        color: '#7A756C',
        fontSize: 14,
      }}
    >
      Cargando…
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <RoleProvider>
        <PlatformRoleProvider>
          <DialogProvider>
          <Suspense fallback={<PantallaCargando />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* Verificación pública de receta (QR) — SIN login, fuera de RequireAuth */}
            <Route path="/verificar-receta/:id" element={<VerificarRecetaPage />} />

            {/* Cambio de contraseña (forzado si es temporal) — sesión sí, rol no.
                Aplica a clínica Y plataforma; sin navegación de la app. */}
            <Route path="/cambiar-contrasena" element={<RequireAuth><CambiarContrasenaPage /></RequireAuth>} />

            {/* ── App de la clínica (sesión real) ── */}
            <Route path="/agenda"    element={<ClinicRoute modulo="agenda"><AgendaPage /></ClinicRoute>} />
            <Route path="/contactos" element={<ClinicRoute modulo="contactos"><ContactosPage /></ClinicRoute>} />
            <Route path="/personal"  element={<ClinicRoute modulo="personal"><PersonalPage /></ClinicRoute>} />
            <Route path="/notas"     element={<ClinicRoute modulo="notas"><NotasPage /></ClinicRoute>} />
            <Route path="/finanzas"  element={<ClinicRoute modulo="finanzas"><FinanzasPage /></ClinicRoute>} />
            <Route path="/cotizaciones" element={<ClinicRoute modulo="cotizaciones"><CotizacionesPage /></ClinicRoute>} />
            {/* Paquetes (catálogo reutilizable): gating fino de rol (owner/admin) dentro
                de la propia página, no es un Modulo del menú → solo RequireAuth aquí. */}
            <Route path="/paquetes" element={<RequireAuth><PaquetesPage /></RequireAuth>} />
            <Route path="/mi-consultorio" element={<ConsultorioRoute><MiConsultorioPage /></ConsultorioRoute>} />

            {/* ── Panel interno de Maily (datos reales: dashboard/clínicas/usuarios) ── */}
            <Route path="/plataforma" element={<Navigate to="/plataforma/dashboard" replace />} />
            <Route path="/plataforma/dashboard"     element={<PlatformRoute modulo="dashboard"><DashboardPlataformaPage /></PlatformRoute>} />
            <Route path="/plataforma/clinicas"      element={<PlatformRoute modulo="clinicas"><ClinicasPage /></PlatformRoute>} />
            <Route path="/plataforma/suscripciones" element={<PlatformRoute modulo="suscripciones"><SuscripcionesPage /></PlatformRoute>} />
            <Route path="/plataforma/usuarios"      element={<PlatformRoute modulo="usuarios"><UsuariosPage /></PlatformRoute>} />
            <Route path="/plataforma/sistema"       element={<PlatformRoute modulo="sistema"><SistemaPage /></PlatformRoute>} />
            <Route path="/plataforma/auditoria"     element={<PlatformRoute modulo="auditoria"><AuditoriaPage /></PlatformRoute>} />

            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
          </Suspense>

          {/* Vigilante global: 403 password_change_required → /cambiar-contrasena */}
          <VigilanteCambioPassword />
          {/* Vigilante global: alerta cuando una cita de hoy se queda atrás de su estado */}
          <AlertaCitas />
          {/* Luz amarilla global: recordatorios de hoy ya vencidos y pendientes */}
          <LuzRecordatorios />
          </DialogProvider>
        </PlatformRoleProvider>
      </RoleProvider>
    </AuthProvider>
  )
}
