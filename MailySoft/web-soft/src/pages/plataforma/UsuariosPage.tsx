/**
 * UsuariosPage — equipo interno de Maily (Fase 4: gestión completa).
 *
 * Solo super_admin ve las acciones (puedeEditarPlat(role,'usuarios')); para el
 * resto la página es de solo lectura. El backend es la autoridad: responde 403
 * a quien no sea super_admin aunque la UI fallara en ocultar algo.
 *
 * En TU PROPIA fila: puedes editar tu nombre, pero no desactivarte, cambiarte
 * el rol ni restablecerte la contraseña (el backend además lo rechaza con 400).
 */

import { useState, useEffect, Fragment } from 'react'
import { Search, UserCog, UserPlus, UserCheck, Pencil, KeyRound, Loader2, AlertCircle } from 'lucide-react'
import PlatformLayout from '../../platform/PlatformLayout'
import { usePlatformStaff, useResetStaffPassword, useUpdateStaff } from '../../hooks/plataforma'
import { usePlatformRole } from '../../platform/PlatformRoleContext'
import { puedeEditarPlat } from '../../platform/permisos'
import { useAuth } from '../../auth/AuthContext'
import { useAviso, useConfirm } from '../../components/common/DialogProvider'
import StaffFormModal, { TempPasswordModal } from '../../components/plataforma/StaffFormModal'
import { ApiError } from '../../lib/http'
import type { PlatformStaff } from '../../types/plataforma'

const ini = (n: string) => n.split(' ').slice(0, 2).map(w => w[0] ?? '').join('').toUpperCase() || '?'

/** Convierte el error de la API en un texto legible (detail o errores por campo). */
function textoError(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.body) {
    if (err.body.detail) return String(err.body.detail)
    const campos = Object.entries(err.body)
      .filter(([k]) => k !== 'detail' && k !== 'code')
      .map(([, v]) => (Array.isArray(v) ? v.join(' ') : String(v)))
    if (campos.length) return campos.join(' ')
  }
  return fallback
}

/** Botón chico de acción por fila (icono + texto). */
const BTN_FILA = 'inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold transition-colors'

/** Estado del modal de alta/edición. */
type ModalStaff = { modo: 'crear' } | { modo: 'editar'; staff: PlatformStaff } | null

export default function UsuariosPage() {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [modal, setModal] = useState<ModalStaff>(null)
  const [resetInfo, setResetInfo] = useState<{ email: string; password: string } | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350)
    return () => clearTimeout(t)
  }, [query])

  const { data, isLoading, isError } = usePlatformStaff(debounced)
  const lista = data?.results ?? []
  const total = data?.count ?? 0

  const { user } = useAuth()
  const { role } = usePlatformRole()
  const puedeEditar = puedeEditarPlat(role, 'usuarios')

  const actualizar = useUpdateStaff()
  const resetPassword = useResetStaffPassword()
  const confirmar = useConfirm()
  const aviso = useAviso()

  const esPropio = (u: PlatformStaff) => u.id === user?.id

  const restablecer = async (u: PlatformStaff) => {
    const ok = await confirmar({
      titulo: 'Restablecer contraseña',
      mensaje: `Se generará una contraseña temporal nueva para ${u.email}. Su contraseña actual dejará de funcionar y deberá cambiarla al entrar.`,
      textoConfirmar: 'Restablecer',
    })
    if (!ok) return
    try {
      const res = await resetPassword.mutateAsync(u.id)
      setResetInfo({ email: u.email, password: res.temporary_password })
    } catch (e) {
      void aviso({ tipo: 'error', mensaje: textoError(e, 'No se pudo restablecer la contraseña.') })
    }
  }

  const reactivar = async (u: PlatformStaff) => {
    const ok = await confirmar({
      titulo: 'Reactivar miembro',
      mensaje: `${u.full_name || u.email} volverá a poder iniciar sesión en el panel.`,
      textoConfirmar: 'Reactivar',
    })
    if (!ok) return
    try {
      await actualizar.mutateAsync({ userId: u.id, input: { is_active: true } })
      void aviso({ tipo: 'exito', titulo: 'Miembro reactivado', mensaje: `${u.full_name || u.email} ya está activo.` })
    } catch (e) {
      void aviso({ tipo: 'error', mensaje: textoError(e, 'No se pudo reactivar al miembro.') })
    }
  }

  /** Acciones por fila (desktop y móvil comparten esta lógica). */
  const accionesDe = (u: PlatformStaff) => {
    if (!puedeEditar) return null
    const propio = esPropio(u)
    return (
      <span className="flex items-center gap-1.5 flex-wrap">
        <button onClick={() => setModal({ modo: 'editar', staff: u })}
          className={BTN_FILA} style={{ color: '#9A7B1E', background: 'rgba(201,162,39,0.12)' }}
          title={propio ? 'Editar tu nombre' : 'Editar miembro'}>
          <Pencil className="w-3.5 h-3.5" /> Editar
        </button>
        {/* Restablecer: no sobre uno mismo (usa /cambiar-contrasena) ni sobre inactivos (el backend da 400). */}
        {!propio && u.is_active && (
          <button onClick={() => void restablecer(u)} disabled={resetPassword.isPending}
            className={`${BTN_FILA} disabled:opacity-60`} style={{ color: '#6B7280', background: 'rgba(0,0,0,0.05)' }}
            title="Generar una contraseña temporal nueva">
            <KeyRound className="w-3.5 h-3.5" /> Restablecer
          </button>
        )}
        {!propio && !u.is_active && (
          <button onClick={() => void reactivar(u)} disabled={actualizar.isPending}
            className={`${BTN_FILA} disabled:opacity-60`} style={{ color: '#047857', background: 'rgba(4,120,87,0.10)' }}
            title="Permitir que vuelva a entrar">
            <UserCheck className="w-3.5 h-3.5" /> Reactivar
          </button>
        )}
      </span>
    )
  }

  const gridCols = puedeEditar ? '2fr 2fr 1fr 1fr 1.4fr' : '2fr 2fr 1fr 1fr'

  return (
    <PlatformLayout active="usuarios">
      <div className="glass-card rounded-2xl px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Equipo Maily</h1>
            <p className="text-sm text-gray-500">
              {isLoading ? 'Cargando…' : `${total} usuario${total === 1 ? '' : 's'} interno${total === 1 ? '' : 's'} de la plataforma`}
            </p>
          </div>
          {puedeEditar && (
            <button onClick={() => setModal({ modo: 'crear' })}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-white shrink-0"
              style={{ background: '#C9A227' }}>
              <UserPlus className="w-4 h-4" /> Nuevo miembro
            </button>
          )}
        </div>
        <div className="relative mt-4 max-w-md">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
          <input value={query} onChange={e => setQuery(e.target.value)}
            placeholder="Buscar por nombre o correo" className="input pl-10" style={{ background: 'rgba(255,255,255,0.7)' }} />
        </div>
      </div>

      {isError && (
        <div className="glass-card rounded-2xl py-10 px-6 flex items-center justify-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
          <p className="text-sm text-red-600">No se pudo cargar el equipo. ¿Tienes permiso de Súper Admin?</p>
        </div>
      )}

      {isLoading && !isError && (
        <div className="flex items-center justify-center gap-2 py-16 text-amber-700">
          <Loader2 className="w-5 h-5 animate-spin" /> Cargando equipo…
        </div>
      )}

      {!isLoading && !isError && (
        <div className="glass-card rounded-2xl overflow-hidden">
          {/* Encabezado de tabla (solo escritorio) */}
          <div className="hidden md:grid items-center px-6 py-3 text-xs font-semibold text-gray-500 border-b border-white/40"
            style={{ gridTemplateColumns: gridCols }}>
            <span>Nombre</span><span>Correo</span><span>Rol</span><span>Estado</span>
            {puedeEditar && <span>Acciones</span>}
          </div>
          {lista.map(u => (
            <Fragment key={u.id}>
              {/* Móvil: tarjeta apilada */}
              <div className="md:hidden px-4 py-3.5 border-b border-white/30">
                <div className="flex items-center gap-3">
                  <span className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                    style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>{ini(u.full_name)}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-800 truncate">
                      {u.full_name || '—'}{esPropio(u) && <span className="text-xs text-gray-400 font-normal"> (tú)</span>}
                    </p>
                    <p className="text-xs text-gray-500 truncate">{u.email}</p>
                  </div>
                  <span className={`badge shrink-0 ${u.is_active ? 'badge-success' : 'badge-neutral'}`}>{u.is_active ? 'Activo' : 'Inactivo'}</span>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-gray-500 mt-2">
                  <UserCog className="w-3.5 h-3.5 text-gray-400 shrink-0" /> {u.platform_role_display || '—'}
                </div>
                {puedeEditar && <div className="mt-2.5">{accionesDe(u)}</div>}
              </div>

              {/* Escritorio: fila de tabla */}
              <div className="hidden md:grid items-center px-6 py-3 border-b border-white/30"
                style={{ gridTemplateColumns: gridCols }}>
                <span className="flex items-center gap-3 min-w-0">
                  <span className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                    style={{ background: 'rgba(201,162,39,0.16)', color: '#B8860B' }}>{ini(u.full_name)}</span>
                  <span className="text-sm font-medium text-gray-800 truncate">
                    {u.full_name || '—'}{esPropio(u) && <span className="text-xs text-gray-400 font-normal"> (tú)</span>}
                  </span>
                </span>
                <span className="text-sm text-gray-600 truncate">{u.email}</span>
                <span className="flex items-center gap-1.5 text-sm text-gray-600">
                  <UserCog className="w-3.5 h-3.5 text-gray-400" /> {u.platform_role_display || '—'}
                </span>
                <span><span className={`badge ${u.is_active ? 'badge-success' : 'badge-neutral'}`}>{u.is_active ? 'Activo' : 'Inactivo'}</span></span>
                {puedeEditar && <span>{accionesDe(u)}</span>}
              </div>
            </Fragment>
          ))}
          {lista.length === 0 && (
            <p className="px-4 sm:px-6 py-12 text-center text-sm text-gray-400">No hay usuarios con ese criterio.</p>
          )}
        </div>
      )}

      {/* Modal de alta / edición */}
      {modal && (
        <StaffFormModal
          staff={modal.modo === 'editar' ? modal.staff : undefined}
          esPropio={modal.modo === 'editar' && esPropio(modal.staff)}
          onClose={() => setModal(null)}
        />
      )}

      {/* Contraseña temporal generada por el reset (se muestra UNA sola vez) */}
      {resetInfo && (
        <TempPasswordModal email={resetInfo.email} password={resetInfo.password} onClose={() => setResetInfo(null)} />
      )}
    </PlatformLayout>
  )
}
