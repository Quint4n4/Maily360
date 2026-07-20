import { useState } from 'react'
import {
  Loader2, Mail, ChevronLeft, ChevronRight, Lock, Building2,
  Crown, Shield, Stethoscope, HeartPulse, Bell, Wallet, Eye,
} from 'lucide-react'
import { useMembers } from '../../hooks/miembros'
import { useAuth } from '../../auth/AuthContext'
import { ROLES } from '../../auth/permisos'
import type { ClinicRole } from '../../auth/permisos'
import type { Member } from '../../types/personal'
import MiembroDetalleDrawer from './MiembroDetalleDrawer'

/** Orden fijo + icono por rol. */
const ROLES_META: { key: ClinicRole; label: string; icon: typeof Crown }[] = [
  { key: 'owner',     label: 'Dueño',         icon: Crown },
  { key: 'admin',     label: 'Administrador', icon: Shield },
  { key: 'doctor',    label: 'Médico',        icon: Stethoscope },
  { key: 'nurse',     label: 'Enfermería',    icon: HeartPulse },
  { key: 'reception', label: 'Recepción',     icon: Bell },
  { key: 'finance',   label: 'Finanzas',      icon: Wallet },
  { key: 'readonly',  label: 'Solo lectura',  icon: Eye },
]
const ROLE_LABEL: Record<ClinicRole, string> = ROLES.reduce(
  (acc, r) => ({ ...acc, [r.key]: r.label }), {} as Record<ClinicRole, string>,
)

function iniciales(nombre: string): string {
  const w = nombre.trim().split(/\s+/).filter(Boolean)
  return ((w[0]?.[0] ?? '') + (w[1]?.[0] ?? '')).toUpperCase() || '?'
}

interface Props {
  /** Solo se consulta si el rol puede gestionar miembros (Dueño/Admin). */
  enabled: boolean
}

export default function EquipoTab({ enabled }: Props) {
  const { data: miembros, isLoading, isError } = useMembers(enabled)
  const { user, clinicRole } = useAuth()
  const [rolSel, setRolSel] = useState<ClinicRole | null>(null)

  // Multi-sede (clúster F, jerarquía de roles): un admin de sucursal solo
  // gestiona al equipo operativo de su sede — no ve a los dueños. El backend ya
  // omite a los dueños/otros-admins de la lista; aquí ocultamos además el
  // GRUPO "Dueño" para que no aparezca vacío. El dueño sigue viendo todo.
  const esOwner = clinicRole === 'owner'
  const rolesVisibles = esOwner ? ROLES_META : ROLES_META.filter(r => r.key !== 'owner')
  const [miembroSel, setMiembroSel] = useState<Member | null>(null)

  if (!enabled) {
    return (
      <div className="glass-card rounded-2xl mt-5 py-12 text-center text-sm text-gray-500">
        Solo el Dueño y los Administradores pueden gestionar los miembros de la clínica.
      </div>
    )
  }
  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 mt-16 text-amber-700">
        <Loader2 className="w-5 h-5 animate-spin" /> Cargando equipo…
      </div>
    )
  }
  if (isError) {
    return <div className="glass-card rounded-2xl mt-5 py-10 text-center text-sm text-red-600">No se pudo cargar el equipo.</div>
  }

  const todos = miembros ?? []
  const cuenta = (rol: ClinicRole) => todos.filter(m => m.role === rol).length

  // ── Nivel 2: usuarios del rol seleccionado ──
  if (rolSel !== null) {
    const items = todos.filter(m => m.role === rolSel)
    return (
      <div className="mt-5">
        <button onClick={() => setRolSel(null)}
          className="inline-flex items-center gap-1.5 text-sm font-medium mb-4 hover:underline" style={{ color: '#B8860B' }}>
          <ChevronLeft className="w-4 h-4" /> Roles
        </button>
        <h2 className="text-lg font-bold text-gray-900 mb-4">{ROLE_LABEL[rolSel]} <span className="text-sm font-normal text-gray-400">({items.length})</span></h2>

        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {items.map(m => (
            <button key={m.id} onClick={() => setMiembroSel(m)}
              className="glass-card rounded-2xl p-5 text-left transition-all duration-200 hover:-translate-y-1 hover:shadow-xl"
              style={{ opacity: m.is_blocked ? 0.7 : 1 }}>
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-full overflow-hidden flex items-center justify-center text-sm font-bold shrink-0"
                  style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>
                  {m.user.avatar ? <img src={m.user.avatar} alt="" className="w-full h-full object-cover" /> : iniciales(m.user.full_name || m.user.email)}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-gray-900 leading-tight truncate">{m.user.full_name || '—'}</h3>
                  <div className="flex items-center gap-1.5 text-xs text-gray-500 truncate">
                    <Mail className="w-3.5 h-3.5 shrink-0" /> {m.user.email}
                  </div>
                </div>
                {m.is_blocked && <Lock className="w-4 h-4 shrink-0" style={{ color: '#C0392B' }} />}
              </div>

              {/* Sedes que este usuario puede ver y operar (multi-sede F4). */}
              <div className="flex flex-wrap items-center gap-1.5 mt-3">
                <Building2 className="w-3.5 h-3.5 shrink-0 text-gray-400" />
                {m.role === 'owner' ? (
                  <span className="text-[11px] text-gray-500">Todas las sucursales</span>
                ) : m.sucursales.length > 0 ? (
                  m.sucursales.map(s => (
                    <span key={s.id} className="px-2 py-0.5 rounded-full text-[11px] font-semibold"
                      style={{ background: 'rgba(201,162,39,0.16)', color: '#8A6D12' }}>
                      {s.name}
                    </span>
                  ))
                ) : (
                  <span className="text-[11px] text-gray-400">Sin sedes asignadas (solo la principal)</span>
                )}
              </div>
            </button>
          ))}
          {items.length === 0 && (
            <div className="col-span-full glass-card rounded-2xl py-14 text-center text-sm text-gray-500">
              No hay miembros con este rol todavía.
            </div>
          )}
        </div>

        <MiembroDetalleDrawer
          miembro={miembroSel}
          onClose={() => setMiembroSel(null)}
          puedeEditar={enabled}
          esYoMismo={miembroSel?.user.id === user?.id}
        />
      </div>
    )
  }

  // ── Nivel 1: selector de roles ──
  return (
    <div className="grid gap-4 mt-5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
      {rolesVisibles.map(({ key, label, icon: Icon }) => {
        const n = cuenta(key)
        return (
          <button key={key} onClick={() => setRolSel(key)}
            className="glass-card rounded-2xl p-5 text-left transition-all duration-200 hover:-translate-y-1 hover:shadow-xl flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.14)' }}>
              <Icon className="w-7 h-7" style={{ color: '#C9A227' }} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-base font-semibold text-gray-900">{label}</h3>
              <p className="text-xs text-gray-500">{n} {n === 1 ? 'miembro' : 'miembros'}</p>
            </div>
            <ChevronRight className="w-5 h-5 text-gray-300 shrink-0" />
          </button>
        )
      })}
    </div>
  )
}
