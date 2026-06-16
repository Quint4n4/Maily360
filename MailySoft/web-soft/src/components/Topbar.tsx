import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BarChart3, CalendarDays, Users, Stethoscope, StickyNote, ChevronDown, LogOut, User, Building2 } from 'lucide-react'
import { useRole } from '../auth/RoleContext'
import { useAuth } from '../auth/AuthContext'
import { Modulo, accesoModulo, ROLE_LABEL } from '../auth/permisos'
import CampanaNotificaciones from './CampanaNotificaciones'

interface TopbarProps {
  active?: Modulo
}

const NAV: { key: Modulo; label: string; icon: typeof BarChart3 }[] = [
  { key: 'finanzas',  label: 'Finanzas',  icon: BarChart3 },
  { key: 'agenda',    label: 'Agenda',    icon: CalendarDays },
  { key: 'contactos', label: 'Pacientes', icon: Users },
  { key: 'personal',  label: 'Personal',  icon: Stethoscope },
  { key: 'notas',     label: 'Notas',     icon: StickyNote },
]

export default function Topbar({ active = 'agenda' }: TopbarProps) {
  const navigate = useNavigate()
  const { role } = useRole()
  const { user, logout, isPlatformStaff } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [cerrando, setCerrando] = useState(false)

  const visibles = NAV.filter(n => accesoModulo(role, n.key))

  const cerrarSesion = async () => {
    if (cerrando) return
    setCerrando(true)
    try {
      await logout()
    } finally {
      navigate('/login', { replace: true })
    }
  }

  const nombreUsuario = user?.full_name?.trim() || 'Mi cuenta'

  return (
    <header className="glass-topbar sticky top-0 z-30 flex items-center justify-between px-6 h-16">

      {/* ── Izquierda: logo + navegación ── */}
      <div className="flex items-center gap-8">
        <span className="text-xl font-bold tracking-tight" style={{ color: '#2A241B' }}>
          maily<span style={{ color: '#C9A227' }}>360</span>
        </span>

        <nav className="flex items-center gap-1">
          {visibles.map(({ key, label, icon: Icon }) => {
            const isActive = key === active
            return (
              <button
                key={key}
                onClick={() => navigate(`/${key}`)}
                className="flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-lg transition-colors"
                style={{
                  background: isActive ? 'rgba(201,162,39,0.14)' : 'transparent',
                  color: isActive ? '#C9A227' : '#7A756C',
                }}
              >
                <Icon className="w-5 h-5" />
                <span className="text-xs font-medium">{label}</span>
              </button>
            )
          })}
        </nav>
      </div>

      {/* ── Derecha: notificaciones + perfil ── */}
      <div className="flex items-center gap-1.5">
        <CampanaNotificaciones />
        <div className="relative">
        <button
          onClick={() => setMenuOpen(v => !v)}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl transition-colors hover:bg-black/5"
        >
          <div className="w-9 h-9 rounded-full overflow-hidden flex items-center justify-center"
            style={{ background: 'rgba(201,162,39,0.18)', border: '1px solid rgba(201,162,39,0.45)' }}>
            {user?.avatar
              ? <img src={user.avatar} alt="" className="w-full h-full object-cover" />
              : <User className="w-4 h-4" style={{ color: '#C9A227' }} />}
          </div>
          <div className="text-left leading-tight">
            <p className="text-sm font-medium" style={{ color: '#2A241B' }}>{nombreUsuario}</p>
            <p className="text-xs" style={{ color: '#9A958C' }}>{ROLE_LABEL[role]}</p>
          </div>
          <ChevronDown className="w-4 h-4" style={{ color: '#9A958C' }} />
        </button>

        {menuOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            <div className="absolute right-0 mt-2 w-64 rounded-xl overflow-hidden z-20 shadow-lg"
              style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(14px)', border: '1px solid rgba(255,255,255,0.7)' }}>

              {/* Identidad real del usuario */}
              <div className="px-4 py-3 border-b border-gray-100">
                <p className="text-sm font-semibold text-gray-800 truncate">{nombreUsuario}</p>
                <p className="text-xs text-gray-500 truncate">{user?.email ?? ''}</p>
                <span className="inline-block mt-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full"
                  style={{ background: 'rgba(201,162,39,0.14)', color: '#B8860B' }}>
                  {ROLE_LABEL[role]}
                </span>
              </div>

              <button className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-gray-700 hover:bg-amber-50 transition-colors">
                <User className="w-4 h-4 text-gray-400" /> Mi perfil
              </button>

              {isPlatformStaff && (
                <button
                  onClick={() => { setMenuOpen(false); navigate('/plataforma/dashboard') }}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm hover:bg-amber-50 transition-colors border-t border-gray-100"
                  style={{ color: '#B8860B', fontWeight: 600 }}
                >
                  <Building2 className="w-4 h-4" /> Panel de Maily
                </button>
              )}

              <button
                onClick={cerrarSesion}
                disabled={cerrando}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors border-t border-gray-100 disabled:opacity-60"
              >
                <LogOut className="w-4 h-4" /> {cerrando ? 'Cerrando…' : 'Cerrar sesión'}
              </button>
            </div>
          </>
        )}
        </div>
      </div>
    </header>
  )
}
