/**
 * StaffFormModal — alta y edición de miembros del equipo interno de Maily
 * (patrón visual de NuevaClinicaModal / PlanFormModal).
 *
 * Crear:  nombre, apellido, email y rol. Al crear, el backend devuelve la
 *         contraseña temporal UNA sola vez → se muestra con botón de copiar.
 * Editar: nombre, apellido, rol y switch Activo. En TU PROPIA fila (esPropio)
 *         se ocultan rol y Activo (el backend además lo rechaza con 400).
 *
 * Solo super_admin llega aquí (la página ya lo oculta con puedeEditarPlat);
 * el backend es la autoridad y responde 403 a los demás roles.
 */

import { useState } from 'react'
import { X, UserPlus, UserCog, Loader2, Check, Copy, KeyRound, AlertCircle } from 'lucide-react'
import { useCreateStaff, useUpdateStaff } from '../../hooks/plataforma'
import { useAviso } from '../common/DialogProvider'
import { ApiError } from '../../lib/http'
import { esEmailValido } from '../../lib/validacion'
import type { PlatformRoleAsignable, PlatformStaff, StaffCreateResult } from '../../types/plataforma'

const INPUT = 'w-full rounded-xl px-3.5 py-2.5 text-base sm:text-sm text-gray-800 outline-none transition-all'
const INPUT_STYLE = { background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }
const INPUT_DISABLED_STYLE = { background: 'rgba(240,236,226,0.7)', border: '1px solid rgba(201,162,39,0.18)', color: '#8a8378' }
const LABEL = 'block text-xs font-semibold mb-1.5'

/** Los 3 roles del equipo con su descripción corta (para el dropdown). */
const ROLES_STAFF: { value: PlatformRoleAsignable; label: string; desc: string }[] = [
  { value: 'super_admin', label: 'Súper Admin',              desc: 'Acceso total: clínicas, suscripciones, equipo, sistema y auditoría.' },
  { value: 'sales',       label: 'Ventas / Éxito de Cliente', desc: 'Clínicas y suscripciones; sin gestión del equipo ni del sistema.' },
  { value: 'engineering', label: 'Ingeniería',               desc: 'Salud del sistema y auditoría; solo lectura de clínicas.' },
]

/** Etiquetas legibles por campo para los errores 400 de DRF. */
const CAMPO_LABEL: Record<string, string> = {
  email: 'Correo',
  first_name: 'Nombre',
  last_name: 'Apellidos',
  platform_role: 'Rol',
  is_active: 'Activo',
}

/** Convierte el error de la API (400 de DRF con {campo: ["..."]}) en un texto legible. */
function textoError(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.body) {
    if (err.body.detail) return String(err.body.detail)
    const campos = Object.entries(err.body)
      .filter(([k]) => k !== 'detail' && k !== 'code')
      .map(([k, v]) => {
        const msg = Array.isArray(v) ? v.join(' ') : String(v)
        return CAMPO_LABEL[k] ? `${CAMPO_LABEL[k]}: ${msg}` : msg
      })
    if (campos.length) return campos.join(' ')
  }
  return fallback
}

/* ── Panel dorado con la contraseña temporal (se muestra UNA sola vez) ────── */

function PanelPasswordTemporal({ password }: { password: string }) {
  const [copiado, setCopiado] = useState(false)

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(password)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 1800)
    } catch { /* ignore */ }
  }

  return (
    <>
      <div className="rounded-2xl p-4 mb-3" style={{ background: '#FBF6E6', border: '1px solid rgba(201,162,39,0.35)' }}>
        <div className="flex items-center gap-2 mb-2 text-xs font-semibold" style={{ color: '#9A7B1E' }}>
          <KeyRound className="w-4 h-4" /> Contraseña temporal
        </div>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-base font-bold tracking-wide px-3 py-2 rounded-lg" style={{ background: '#fff', color: '#2A241B' }}>
            {password}
          </code>
          <button onClick={copiar} className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white" style={{ background: '#C9A227' }}>
            {copiado ? <><Check className="w-4 h-4" /> Copiado</> : <><Copy className="w-4 h-4" /> Copiar</>}
          </button>
        </div>
      </div>

      <p className="text-xs flex items-start gap-1.5 mb-5" style={{ color: '#C0392B' }}>
        <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
        Compártela de forma segura; se le pedirá cambiarla al entrar. <strong>No se volverá a mostrar.</strong>
      </p>
    </>
  )
}

/* ── Modal del resultado de "Restablecer contraseña" ──────────────────────── */

interface TempPasswordModalProps {
  /** Correo del miembro al que se le restableció la contraseña. */
  email: string
  /** La contraseña temporal nueva (viene UNA sola vez del backend). */
  password: string
  onClose: () => void
}

/** Muestra la contraseña temporal generada por el reset (una sola vez, con copiar). */
export function TempPasswordModal({ email, password, onClose }: TempPasswordModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(30,22,8,0.45)', backdropFilter: 'blur(4px)' }}>
      <div className="relative w-full max-w-lg rounded-3xl p-7"
        style={{ background: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(22px)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 24px 60px rgba(60,42,12,0.3)' }}>
        <button onClick={onClose} className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors">
          <X className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="w-11 h-11 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(46,158,91,0.14)' }}>
            <Check className="w-6 h-6" style={{ color: '#2E9E5B' }} />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900">Contraseña restablecida</h2>
            <p className="text-sm text-gray-500">{email}</p>
          </div>
        </div>

        <p className="text-sm text-gray-600 mb-3">
          <strong>{email}</strong> ya puede entrar con esta contraseña temporal:
        </p>

        <PanelPasswordTemporal password={password} />

        <button onClick={onClose} className="w-full py-2.5 rounded-xl text-sm font-semibold text-white" style={{ background: '#C9A227' }}>
          Listo
        </button>
      </div>
    </div>
  )
}

/* ── Modal principal: crear / editar miembro ──────────────────────────────── */

interface Props {
  /** Miembro a editar; si no viene, el modal da de alta uno nuevo. */
  staff?: PlatformStaff
  /** true si el miembro editado es el propio usuario logueado (oculta rol y Activo). */
  esPropio?: boolean
  onClose: () => void
}

export default function StaffFormModal({ staff, esPropio = false, onClose }: Props) {
  const crear = useCreateStaff()
  const editar = useUpdateStaff()
  const aviso = useAviso()
  const esEdicion = !!staff
  const guardando = crear.isPending || editar.isPending

  const [nombre, setNombre] = useState(staff?.first_name ?? '')
  const [apellido, setApellido] = useState(staff?.last_name ?? '')
  const [email, setEmail] = useState(staff?.email ?? '')
  // '' (sin rol asignado) es falsy → cae al default 'sales'.
  const [rol, setRol] = useState<PlatformRoleAsignable>(staff?.platform_role || 'sales')
  const [activo, setActivo] = useState(staff?.is_active ?? true)
  const [error, setError] = useState<string | null>(null)
  const [resultado, setResultado] = useState<StaffCreateResult | null>(null)

  const rolSeleccionado = ROLES_STAFF.find(r => r.value === rol)

  const enviar = async () => {
    setError(null)
    if (!nombre.trim() || !apellido.trim()) {
      setError('Completa el nombre y los apellidos.')
      return
    }
    if (!esEdicion) {
      if (!email.trim()) {
        setError('Escribe el correo del nuevo miembro (será su usuario de acceso).')
        return
      }
      if (!esEmailValido(email.trim())) {
        setError('El correo no es válido.')
        return
      }
    }

    try {
      if (esEdicion) {
        // PATCH con subconjunto: en tu propia fila NO se mandan rol ni is_active
        // (el backend los rechaza con 400).
        const body = esPropio
          ? { first_name: nombre.trim(), last_name: apellido.trim() }
          : { first_name: nombre.trim(), last_name: apellido.trim(), platform_role: rol, is_active: activo }
        const res = await editar.mutateAsync({ userId: staff.id, input: body })
        onClose()
        void aviso({
          tipo: 'exito',
          titulo: 'Miembro actualizado',
          mensaje: `Los datos de ${res.full_name || res.email} se guardaron correctamente.`,
        })
      } else {
        const res = await crear.mutateAsync({
          email: email.trim(),
          first_name: nombre.trim(),
          last_name: apellido.trim(),
          platform_role: rol,
        })
        setResultado(res)
      }
    } catch (e) {
      setError(textoError(e, esEdicion
        ? 'No se pudo guardar el miembro. Revisa los datos e intenta de nuevo.'
        : 'No se pudo crear el miembro. Revisa los datos e intenta de nuevo.'))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(30,22,8,0.45)', backdropFilter: 'blur(4px)' }}>
      <div className="relative w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-3xl p-7"
        style={{ background: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(22px)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 24px 60px rgba(60,42,12,0.3)' }}>
        <button onClick={onClose} className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors">
          <X className="w-4 h-4" />
        </button>

        {resultado ? (
          /* ── Éxito del alta: contraseña temporal (mostrar UNA sola vez) ── */
          <div>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-11 h-11 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(46,158,91,0.14)' }}>
                <Check className="w-6 h-6" style={{ color: '#2E9E5B' }} />
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900">¡Miembro creado!</h2>
                <p className="text-sm text-gray-500">{resultado.full_name || resultado.email} · {resultado.platform_role_display}</p>
              </div>
            </div>

            <p className="text-sm text-gray-600 mb-3">
              <strong>{resultado.email}</strong> ya puede entrar con esta contraseña temporal:
            </p>

            <PanelPasswordTemporal password={resultado.temporary_password} />

            <button onClick={onClose} className="w-full py-2.5 rounded-xl text-sm font-semibold text-white" style={{ background: '#C9A227' }}>
              Listo
            </button>
          </div>
        ) : (
          /* ── Formulario de alta / edición ── */
          <div>
            <div className="flex items-center gap-3 mb-5">
              <div className="w-11 h-11 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(201,162,39,0.16)' }}>
                {esEdicion
                  ? <UserCog className="w-6 h-6" style={{ color: '#C9A227' }} />
                  : <UserPlus className="w-6 h-6" style={{ color: '#C9A227' }} />}
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900">{esEdicion ? 'Editar miembro' : 'Nuevo miembro'}</h2>
                <p className="text-sm text-gray-500">
                  {esEdicion ? staff.email : 'Integrante del equipo interno de Maily.'}
                </p>
              </div>
            </div>

            {error && (
              <div className="flex items-start gap-2 rounded-xl px-3.5 py-2.5 mb-4" style={{ background: 'rgba(192,57,43,0.1)', border: '1px solid rgba(192,57,43,0.25)' }}>
                <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            <div className="space-y-3.5">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="staff-nombre">Nombre(s)</label>
                  <input id="staff-nombre" className={INPUT} style={INPUT_STYLE} value={nombre}
                    onChange={e => setNombre(e.target.value)} placeholder="Ana" maxLength={150} autoFocus />
                </div>
                <div>
                  <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="staff-apellido">Apellidos</label>
                  <input id="staff-apellido" className={INPUT} style={INPUT_STYLE} value={apellido}
                    onChange={e => setApellido(e.target.value)} placeholder="García" maxLength={150} />
                </div>
              </div>

              <div>
                <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="staff-email">
                  Correo {esEdicion ? '(no se puede cambiar)' : '(su usuario de acceso)'}
                </label>
                <input id="staff-email" className={INPUT}
                  style={esEdicion ? INPUT_DISABLED_STYLE : INPUT_STYLE}
                  type="email" value={email} disabled={esEdicion}
                  onChange={e => setEmail(e.target.value)} placeholder="ana@maily.mx" maxLength={254} />
              </div>

              {/* En tu propia fila el rol no se toca (el backend lo rechaza con 400). */}
              {!esPropio && (
                <div>
                  <label className={LABEL} style={{ color: '#9A7B1E' }} htmlFor="staff-rol">Rol en la plataforma</label>
                  <select id="staff-rol" className={INPUT} style={INPUT_STYLE} value={rol}
                    onChange={e => setRol(e.target.value as PlatformRoleAsignable)}>
                    {ROLES_STAFF.map(r => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                  {rolSeleccionado && (
                    <p className="text-[11px] text-gray-500 mt-1.5">{rolSeleccionado.desc}</p>
                  )}
                </div>
              )}

              {/* Switch Activo: solo en edición y nunca sobre uno mismo. */}
              {esEdicion && !esPropio && (
                <div className="pt-1">
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input type="checkbox" checked={activo} onChange={e => setActivo(e.target.checked)}
                      className="w-4 h-4 rounded" style={{ accentColor: '#C9A227' }} />
                    Activo
                  </label>
                  {!activo && (
                    <p className="text-[11px] text-gray-400 mt-1">
                      Un miembro inactivo no puede iniciar sesión ni usar el panel.
                    </p>
                  )}
                </div>
              )}
            </div>

            <button onClick={enviar} disabled={guardando}
              className="w-full mt-6 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-60" style={{ background: '#C9A227' }}>
              {guardando
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</>
                : <>{esEdicion ? 'Guardar cambios' : 'Crear miembro'}</>}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
