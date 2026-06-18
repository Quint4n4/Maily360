import { ReactElement } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { RoleProvider, useRole } from './auth/RoleContext'
import { Modulo, accesoModulo, inicioDeRol } from './auth/permisos'
import { PlatformRoleProvider, usePlatformRole } from './platform/PlatformRoleContext'
import { PlatModulo, accesoModuloPlat, inicioPlat } from './platform/permisos'
import LoginPage from './pages/LoginPage'
import AgendaPage from './pages/AgendaPage'
import ContactosPage from './pages/ContactosPage'
import PersonalPage from './pages/PersonalPage'
import FinanzasPage from './pages/FinanzasPage'
<<<<<<< Updated upstream
import NotasPage from './pages/NotasPage'
import AlertaCitas from './components/agenda/AlertaCitas'
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

/* Panel de plataforma: protege por rol de plataforma (aún con datos mock, sin backend) */
function PlatGuard({ modulo, children }: { modulo: PlatModulo; children: ReactElement }) {
  const { role } = usePlatformRole()
  if (!accesoModuloPlat(role, modulo)) return <Navigate to={inicioPlat(role)} replace />
  return children
}

export default function App() {
  return (
=======
<<<<<<< HEAD

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/finanzas" element={<FinanzasPage />} />
      <Route path="/agenda" element={<AgendaPage />} />
      <Route path="/contactos" element={<ContactosPage />} />
      <Route path="/personal" element={<PersonalPage />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
=======
import NotasPage from './pages/NotasPage'
import AlertaCitas from './components/agenda/AlertaCitas'
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

/* Panel de plataforma: protege por rol de plataforma (aún con datos mock, sin backend) */
function PlatGuard({ modulo, children }: { modulo: PlatModulo; children: ReactElement }) {
  const { role } = usePlatformRole()
  if (!accesoModuloPlat(role, modulo)) return <Navigate to={inicioPlat(role)} replace />
  return children
}

export default function App() {
  return (
>>>>>>> Stashed changes
    <AuthProvider>
      <RoleProvider>
        <PlatformRoleProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            {/* ── App de la clínica (sesión real) ── */}
            <Route path="/agenda"    element={<ClinicRoute modulo="agenda"><AgendaPage /></ClinicRoute>} />
            <Route path="/contactos" element={<ClinicRoute modulo="contactos"><ContactosPage /></ClinicRoute>} />
            <Route path="/personal"  element={<ClinicRoute modulo="personal"><PersonalPage /></ClinicRoute>} />
            <Route path="/notas"     element={<ClinicRoute modulo="notas"><NotasPage /></ClinicRoute>} />
            <Route path="/finanzas"  element={<ClinicRoute modulo="finanzas"><FinanzasPage /></ClinicRoute>} />

            {/* ── Panel interno de Maily (mock; sin backend todavía) ── */}
            <Route path="/plataforma" element={<Navigate to="/plataforma/dashboard" replace />} />
            <Route path="/plataforma/dashboard"     element={<PlatGuard modulo="dashboard"><DashboardPlataformaPage /></PlatGuard>} />
            <Route path="/plataforma/clinicas"      element={<PlatGuard modulo="clinicas"><ClinicasPage /></PlatGuard>} />
            <Route path="/plataforma/suscripciones" element={<PlatGuard modulo="suscripciones"><SuscripcionesPage /></PlatGuard>} />
            <Route path="/plataforma/usuarios"      element={<PlatGuard modulo="usuarios"><UsuariosPage /></PlatGuard>} />
            <Route path="/plataforma/sistema"       element={<PlatGuard modulo="sistema"><SistemaPage /></PlatGuard>} />

            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>

          {/* Vigilante global: alerta cuando una cita de hoy se queda atrás de su estado */}
          <AlertaCitas />
        </PlatformRoleProvider>
      </RoleProvider>
    </AuthProvider>
<<<<<<< Updated upstream
=======
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes
  )
}
