import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LayoutDashboard, Building2, CreditCard, UserCog, Activity, ChevronDown, LogOut, User, Check, Stethoscope } from 'lucide-react'
import { usePlatformRole } from './PlatformRoleContext'
import { PlatModulo, accesoModuloPlat, inicioPlat, ROLES_PLAT, ROLE_PLAT_LABEL } from './permisos'
import { useAuth } from '../auth/AuthContext'
import { inicioDeRol } from '../auth/permisos'
import BottomNav from '../components/BottomNav'

interface Props {
  active?: PlatModulo
}

const NAV: { key: PlatModulo; label: string; icon: typeof LayoutDashboard }[] = [
  { key: 'dashboard',     label: 'Panel',         icon: LayoutDashboard },
  { key: 'clinicas',      label: 'Clínicas',      icon: Building2 },
  { key: 'suscripciones', label: 'Suscripciones', icon: CreditCard },
  { key: 'usuarios',      label: 'Equipo',        icon: UserCog },
  { key: 'sistema',       label: 'Sistema',       icon: Activity },
]

export default function PlatformTopbar({ active = 'dashboard' }: Props) {
  const navigate = useNavigate()
  const { role, setRole } = usePlatformRole()
  const { user, clinicRole, logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [cerrando, setCerrando] = useState(false)

  const visibles = NAV.filter(n => accesoModuloPlat(role, n.key))

  const cambiarRol = (r: typeof role) => {
    setRole(r); setMenuOpen(false); navigate(inicioPlat(r))
  }

  const cerrarSesion = async () => {
    if (cerrando) return
    setCerrando(true)
    try {
      await logout()
    } finally {
      navigate('/login', { replace: true })
    }
  }

  return (
    <>
    <header className="glass-topbar sticky top-0 z-30 flex items-center justify-between px-4 sm:px-6 h-16">
      <div className="flex items-center gap-4 md:gap-8">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold tracking-tight" style={{ color: '#2A241B' }}>
            maily<span style={{ color: '#C9A227' }}>360</span>
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
            style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
            Plataforma
          </span>
        </div>

        <nav className="hidden md:flex items-center gap-1">
          {visibles.map(({ key, label, icon: Icon }) => {
            const isActive = key === active
            return (
              <button key={key} onClick={() => navigate(`/plataforma/${key === 'dashboard' ? 'dashboard' : key}`)}
                className="flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-lg transition-colors"
                style={{ background: isActive ? 'rgba(201,162,39,0.14)' : 'transparent', color: isActive ? '#C9A227' : '#7A756C' }}>
                <Icon className="w-5 h-5" />
                <span className="text-xs font-medium">{label}</span>
              </button>
            )
          })}
        </nav>
      </div>

      <div className="relative">
        <button onClick={() => setMenuOpen(v => !v)}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl transition-colors hover:bg-black/5">
          <div className="w-9 h-9 rounded-full flex items-center justify-center"
            style={{ background: 'rgba(201,162,39,0.18)', border: '1px solid rgba(201,162,39,0.45)' }}>
            <User className="w-4 h-4" style={{ color: '#C9A227' }} />
          </div>
          <div className="text-left leading-tight hidden sm:block">
            <p className="text-sm font-medium" style={{ color: '#2A241B' }}>{user?.full_name?.trim() || 'Equipo Maily'}</p>
            <p className="text-xs" style={{ color: '#9A958C' }}>{ROLE_PLAT_LABEL[role]}</p>
          </div>
          <ChevronDown className="w-4 h-4" style={{ color: '#9A958C' }} />
        </button>

        {menuOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            <div className="absolute right-0 mt-2 w-64 rounded-xl overflow-hidden z-20 shadow-lg"
              style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(14px)', border: '1px solid rgba(255,255,255,0.7)' }}>
              <div className="px-4 pt-2.5 pb-1 border-b border-gray-100">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/70">Ver como (demo)</p>
              </div>
              {ROLES_PLAT.map(r => (
                <button key={r.key} onClick={() => cambiarRol(r.key)}
                  className="w-full flex items-center justify-between px-4 py-2 text-sm transition-colors hover:bg-amber-50"
                  style={{ color: r.key === role ? '#B8860B' : '#374151', fontWeight: r.key === role ? 600 : 400 }}>
                  {r.label}
                  {r.key === role && <Check className="w-4 h-4" style={{ color: '#C9A227' }} />}
                </button>
              ))}
              {clinicRole && (
                <button onClick={() => { setMenuOpen(false); navigate(inicioDeRol(clinicRole)) }}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm hover:bg-amber-50 transition-colors border-t border-gray-100"
                  style={{ color: '#B8860B', fontWeight: 600 }}>
                  <Stethoscope className="w-4 h-4" /> Ir a mi clínica
                </button>
              )}
              <button onClick={cerrarSesion} disabled={cerrando}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors border-t border-gray-100 disabled:opacity-60">
                <LogOut className="w-4 h-4" /> {cerrando ? 'Cerrando…' : 'Cerrar sesión'}
              </button>
            </div>
          </>
        )}
      </div>
    </header>

    <BottomNav
      items={visibles.map(({ key, label, icon: Icon }) => ({
        key,
        label,
        Icon,
        active: key === active,
        onClick: () => navigate(`/plataforma/${key}`),
      }))}
    />
    </>
  )
}
