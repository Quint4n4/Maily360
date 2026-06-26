import { ReactElement } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { RoleProvider, useRole } from './auth/RoleContext'
import { Modulo, accesoModulo, inicioDeRol, puedeAccederConsultorio } from './auth/permisos'
import { PlatformRoleProvider, usePlatformRole } from './platform/PlatformRoleContext'
import { DialogProvider } from './components/common/DialogProvider'
import { PlatModulo, accesoModuloPlat, inicioPlat } from './platform/permisos'
import LoginPage from './pages/LoginPage'
import AgendaPage from './pages/AgendaPage'
import ContactosPage from './pages/ContactosPage'
import PersonalPage from './pages/PersonalPage'
import FinanzasPage from './pages/FinanzasPage'
import CotizacionesPage from './pages/CotizacionesPage'
import NotasPage from './pages/NotasPage'
import MiConsultorioPage from './pages/MiConsultorioPage'
import AlertaCitas from './components/agenda/AlertaCitas'
import LuzRecordatorios from './components/agenda/LuzRecordatorios'
import DashboardPlataformaPage from './pages/plataforma/DashboardPage'
import ClinicasPage from './pages/plataforma/ClinicasPage'
import SuscripcionesPage from './pages/plataforma/SuscripcionesPage'
import UsuariosPage from './pages/plataforma/UsuariosPage'
import SistemaPage from './pages/plataforma/SistemaPage'

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

export default function App() {
  return (
    <AuthProvider>
      <RoleProvider>
        <PlatformRoleProvider>
          <DialogProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            {/* ── App de la clínica (sesión real) ── */}
            <Route path="/agenda"    element={<ClinicRoute modulo="agenda"><AgendaPage /></ClinicRoute>} />
            <Route path="/contactos" element={<ClinicRoute modulo="contactos"><ContactosPage /></ClinicRoute>} />
            <Route path="/personal"  element={<ClinicRoute modulo="personal"><PersonalPage /></ClinicRoute>} />
            <Route path="/notas"     element={<ClinicRoute modulo="notas"><NotasPage /></ClinicRoute>} />
            <Route path="/finanzas"  element={<ClinicRoute modulo="finanzas"><FinanzasPage /></ClinicRoute>} />
            <Route path="/cotizaciones" element={<ClinicRoute modulo="cotizaciones"><CotizacionesPage /></ClinicRoute>} />
            <Route path="/mi-consultorio" element={<ConsultorioRoute><MiConsultorioPage /></ConsultorioRoute>} />

            {/* ── Panel interno de Maily (datos reales: dashboard/clínicas/usuarios) ── */}
            <Route path="/plataforma" element={<Navigate to="/plataforma/dashboard" replace />} />
            <Route path="/plataforma/dashboard"     element={<PlatformRoute modulo="dashboard"><DashboardPlataformaPage /></PlatformRoute>} />
            <Route path="/plataforma/clinicas"      element={<PlatformRoute modulo="clinicas"><ClinicasPage /></PlatformRoute>} />
            <Route path="/plataforma/suscripciones" element={<PlatformRoute modulo="suscripciones"><SuscripcionesPage /></PlatformRoute>} />
            <Route path="/plataforma/usuarios"      element={<PlatformRoute modulo="usuarios"><UsuariosPage /></PlatformRoute>} />
            <Route path="/plataforma/sistema"       element={<PlatformRoute modulo="sistema"><SistemaPage /></PlatformRoute>} />

            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>

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
