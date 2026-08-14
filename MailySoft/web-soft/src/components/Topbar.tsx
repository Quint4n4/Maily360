import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BarChart3, CalendarDays, Users, Stethoscope, StickyNote, ScrollText, Package, ChevronDown, LogOut, User, Building2, Briefcase, Layers } from 'lucide-react'
import { Check } from 'lucide-react'
import { useRole } from '../auth/RoleContext'
import { useAuth } from '../auth/AuthContext'
import { useSucursalActiva } from '../auth/SucursalContext'
import { Modulo, accesoModulo, puedeAccederConsultorio, ROLE_LABEL } from '../auth/permisos'
import CampanaNotificaciones from './CampanaNotificaciones'
import MarcaMaily from './MarcaMaily'
import BottomNav from './BottomNav'
import type { ModuloId } from '../lib/modulos'

interface TopbarProps {
  /** Módulo activo del menú, o 'paquetes' (página propia fuera de la matriz de módulos). */
  active?: Modulo | 'paquetes'
}

/**
 * Entradas del menú. `modulo` es el módulo del PLAN que la habilita (distinto
 * de `key`, que es el permiso por ROL): una entrada se pinta solo si el rol la
 * permite Y la clínica la tiene contratada.
 *
 * "Pacientes" no lleva módulo: el expediente del paciente es el núcleo, no se
 * vende por separado.
 */
const NAV: { key: Modulo; label: string; icon: typeof BarChart3; modulo?: ModuloId }[] = [
  { key: 'finanzas',     label: 'Finanzas',     icon: BarChart3,    modulo: 'cobranza' },
  { key: 'cotizaciones', label: 'Cotizaciones', icon: ScrollText,   modulo: 'cotizaciones' },
  { key: 'agenda',       label: 'Agenda',       icon: CalendarDays, modulo: 'agenda' },
  { key: 'contactos',    label: 'Pacientes',    icon: Users },
  { key: 'personal',     label: 'Personal',     icon: Stethoscope,  modulo: 'personal' },
  { key: 'notas',        label: 'Notas',        icon: StickyNote,   modulo: 'notas' },
]

export default function Topbar({ active = 'agenda' }: TopbarProps) {
  const navigate = useNavigate()
  const { role } = useRole()
  const { user, logout, isPlatformStaff, tieneModulo } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [cerrando, setCerrando] = useState(false)

  // Regla de oro: se ve si el ROL lo permite Y el PLAN lo incluye.
  const visibles = NAV.filter(
    n => accesoModulo(role, n.key) && (!n.modulo || tieneModulo(n.modulo)),
  )
  // Paquetes: página propia (no es Modulo del menú). Solo owner/admin la gestionan.
  const puedeVerPaquetes = (role === 'owner' || role === 'admin') && tieneModulo('paquetes')

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
    <>
    <header className="glass-topbar sticky top-0 z-30 flex items-center justify-between px-4 sm:px-6 h-16">

      {/* ── Izquierda: logo + navegación ── */}
      <div className="flex items-center gap-4 md:gap-8">
        <MarcaMaily variante="horizontal" className="h-8" />

        <nav className="hidden md:flex items-center gap-1">
          {visibles.map(({ key, label, icon: Icon }) => {
            const isActive = key === active
            return (
              <button
                key={key}
                onClick={() => navigate(`/${key}`)}
                aria-current={isActive ? 'page' : undefined}
                className={`flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-lg transition-colors ${
                  isActive ? 'bg-accion-tinte text-accion' : 'text-suave hover:text-tinta hover:bg-superficie-sutil'}`}
              >
                <Icon className="w-5 h-5" />
                <span className="text-xs font-medium">{label}</span>
              </button>
            )
          })}
          {puedeVerPaquetes && (
            <button
              onClick={() => navigate('/paquetes')}
              aria-current={active === 'paquetes' ? 'page' : undefined}
              className={`flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-lg transition-colors ${
                active === 'paquetes' ? 'bg-accion-tinte text-accion' : 'text-suave hover:text-tinta hover:bg-superficie-sutil'}`}
            >
              <Package className="w-5 h-5" />
              <span className="text-xs font-medium">Paquetes</span>
            </button>
          )}
        </nav>
      </div>

      {/* ── Derecha: sucursal + notificaciones + perfil ── */}
      <div className="flex items-center gap-1.5">
        <SelectorSucursal />
        <CampanaNotificaciones />
        <div className="relative">
        <button
          onClick={() => setMenuOpen(v => !v)}
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl transition-colors hover:bg-black/5"
        >
          <div className="w-9 h-9 rounded-full overflow-hidden flex items-center justify-center"
            style={{ background: 'var(--accion-tinte)', border: '1px solid var(--accion-borde)' }}>
            {user?.avatar
              ? <img src={user.avatar} alt="" className="w-full h-full object-cover" />
              : <User className="w-4 h-4 text-accion" />}
          </div>
          <div className="text-left leading-tight hidden sm:block">
            <p className="text-sm font-medium text-tinta">{nombreUsuario}</p>
            <p className="text-xs text-suave">{ROLE_LABEL[role]}</p>
          </div>
          <ChevronDown className="w-4 h-4 text-suave" />
        </button>

        {menuOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            <div className="absolute right-0 mt-2 w-64 rounded-xl overflow-hidden z-20 bg-superficie border border-borde shadow-card-alto">

              {/* Identidad real del usuario */}
              <div className="px-4 py-3 border-b border-borde">
                <p className="text-sm font-semibold text-tinta truncate">{nombreUsuario}</p>
                <p className="text-xs text-suave truncate">{user?.email ?? ''}</p>
                <span className="inline-block mt-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-accion-tinte text-accion">
                  {ROLE_LABEL[role]}
                </span>
              </div>

              <button className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-cuerpo hover:bg-accion-tinte transition-colors">
                <User className="w-4 h-4 text-tenue" /> Mi perfil
              </button>

              {puedeAccederConsultorio(role) && (
                <button
                  onClick={() => { setMenuOpen(false); navigate('/mi-consultorio') }}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-cuerpo hover:bg-accion-tinte transition-colors"
                >
                  <Briefcase className="w-4 h-4 text-tenue" /> Mi Consultorio
                </button>
              )}

              {isPlatformStaff && (
                <button
                  onClick={() => { setMenuOpen(false); navigate('/plataforma/dashboard') }}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm font-semibold text-accion hover:bg-accion-tinte transition-colors border-t border-borde"
                >
                  <Building2 className="w-4 h-4" /> Panel de Maily
                </button>
              )}

              <button
                onClick={cerrarSesion}
                disabled={cerrando}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-peligro hover:bg-peligro-tinte transition-colors border-t border-borde disabled:opacity-60"
              >
                <LogOut className="w-4 h-4" /> {cerrando ? 'Cerrando…' : 'Cerrar sesión'}
              </button>
            </div>
          </>
        )}
        </div>
      </div>
    </header>

    <BottomNav
      items={visibles.map(({ key, label, icon: Icon }) => ({
        key,
        label,
        Icon,
        active: key === active,
        onClick: () => navigate(`/${key}`),
      }))}
    />
    </>
  )
}

/**
 * Selector de sucursal (sede) activa. Solo se muestra si el usuario tiene MÁS de
 * una sede permitida; con una sola (o ninguna) queda oculto. Al cambiar,
 * `setActiveSucursal` persiste la elección y refresca los datos por sede
 * (personal/consultorios/agenda/finanzas). El backend filtra por el header
 * X-Sucursal-Id.
 *
 * Opción "Todas las sucursales" (consolidado): pasa la sede activa a null → el
 * cliente http NO manda el header y el backend consolida sobre las sedes
 * PERMITIDAS del usuario (dueño → todas; admin de sede → solo la suya). Aplica a
 * caja/reportes/dashboard; el estado de cuenta del paciente siempre es compartido.
 */
function SelectorSucursal() {
  const { sucursales, activeSucursal, esTodas, puedeVerTodas, setActiveSucursal } = useSucursalActiva()
  const [abierto, setAbierto] = useState(false)

  // Con una sola sede (o sin sedes) no hay nada que elegir → oculto.
  if (sucursales.length <= 1) return null

  const etiqueta = esTodas ? 'Todas las sucursales' : activeSucursal?.name ?? 'Sucursal'

  return (
    <div className="relative">
      <button
        onClick={() => setAbierto((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-xl transition-colors hover:bg-black/5"
        title="Cambiar de sucursal"
      >
        <Building2 className="w-4 h-4 text-borde-fuerte" />
        <span className="text-sm font-medium max-w-[140px] truncate hidden sm:block text-tinta">
          {etiqueta}
        </span>
        <ChevronDown className="w-4 h-4 text-suave" />
      </button>

      {abierto && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setAbierto(false)} />
          <div
            className="absolute right-0 mt-2 w-60 rounded-xl overflow-hidden z-20 bg-superficie border border-borde shadow-card-alto"
          >
            <div className="px-4 py-2.5 border-b border-borde">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-suave">Sucursal activa</p>
            </div>

            {/* Consolidado: solo con más de una sede permitida. */}
            {puedeVerTodas && (
              <button
                onClick={() => { setActiveSucursal(null); setAbierto(false) }}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-cuerpo hover:bg-accion-tinte transition-colors text-left border-b border-gray-100"
                style={esTodas ? { color: 'var(--accion)', fontWeight: 600, background: 'var(--accion-tinte)' } : undefined}
              >
                <Layers className="w-4 h-4 shrink-0" style={{ color: esTodas ? 'var(--accion)' : 'var(--tenue)' }} />
                <span className="flex-1 min-w-0 truncate">Todas las sucursales</span>
                {esTodas && <Check className="w-4 h-4 shrink-0 text-accion" />}
              </button>
            )}

            {sucursales.map((s) => {
              const activa = s.id === activeSucursal?.id
              return (
                <button
                  key={s.id}
                  onClick={() => { setActiveSucursal(s.id); setAbierto(false) }}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-cuerpo hover:bg-accion-tinte transition-colors text-left"
                  style={activa ? { color: 'var(--accion)', fontWeight: 600, background: 'var(--accion-tinte)' } : undefined}
                >
                  <Building2 className="w-4 h-4 shrink-0" style={{ color: activa ? 'var(--accion)' : 'var(--tenue)' }} />
                  <span className="flex-1 min-w-0 truncate">{s.name}</span>
                  {s.is_default && !activa && <span className="text-[10px] text-suave">Principal</span>}
                  {activa && <Check className="w-4 h-4 shrink-0 text-accion" />}
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
