import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BarChart3, CalendarDays, Users, Stethoscope, ChevronDown, LogOut, User } from 'lucide-react'

type Section = 'finanzas' | 'agenda' | 'contactos' | 'personal'

interface TopbarProps {
  active?: Section
}

const NAV: { key: Section; label: string; icon: typeof BarChart3 }[] = [
  { key: 'finanzas',  label: 'Finanzas',  icon: BarChart3 },
  { key: 'agenda',    label: 'Agenda',    icon: CalendarDays },
  { key: 'contactos', label: 'Contactos', icon: Users },
  { key: 'personal',  label: 'Personal',  icon: Stethoscope },
]

export default function Topbar({ active = 'agenda' }: TopbarProps) {
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <header className="glass-topbar sticky top-0 z-30 flex items-center justify-between px-6 h-16">

      {/* ── Izquierda: logo + navegación ── */}
      <div className="flex items-center gap-8">
        <span className="text-xl font-bold tracking-tight" style={{ color: '#2A241B' }}>
          maily<span style={{ color: '#C9A227' }}>360</span>
        </span>

        <nav className="flex items-center gap-1">
          {NAV.map(({ key, label, icon: Icon }) => {
            const isActive = key === active
            return (
              <button
                key={key}
                onClick={() => {
                  if (key === 'agenda') navigate('/agenda')
                  else if (key === 'contactos') navigate('/contactos')
                  else if (key === 'personal') navigate('/personal')
                }}
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

      {/* ── Derecha: perfil ── */}
      <div className="relative">
        <button
          onClick={() => setMenuOpen(v => !v)}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl transition-colors hover:bg-black/5"
        >
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center"
            style={{ background: 'rgba(201,162,39,0.18)', border: '1px solid rgba(201,162,39,0.45)' }}
          >
            <User className="w-4 h-4" style={{ color: '#C9A227' }} />
          </div>
          <span className="text-sm font-medium" style={{ color: '#2A241B' }}>Dr. Prueba</span>
          <ChevronDown className="w-4 h-4" style={{ color: '#9A958C' }} />
        </button>

        {menuOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            <div
              className="absolute right-0 mt-2 w-48 rounded-xl overflow-hidden z-20 shadow-lg"
              style={{ background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.7)' }}
            >
              <button className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-gray-700 hover:bg-amber-50 transition-colors">
                <User className="w-4 h-4 text-gray-400" /> Mi perfil
              </button>
              <button
                onClick={() => navigate('/login')}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors border-t border-gray-100"
              >
                <LogOut className="w-4 h-4" /> Cerrar sesión
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  )
}
