import { Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import AgendaPage from './pages/AgendaPage'
import ContactosPage from './pages/ContactosPage'
import PersonalPage from './pages/PersonalPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/agenda" element={<AgendaPage />} />
      <Route path="/contactos" element={<ContactosPage />} />
      <Route path="/personal" element={<PersonalPage />} />
      {/* Aquí se agregarán las demás rutas (finanzas, config, etc.) */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
