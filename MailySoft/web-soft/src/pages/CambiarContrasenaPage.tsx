/**
 * CambiarContrasenaPage — cambio de contraseña forzado (o voluntario).
 *
 * Cuando el usuario entra con una contraseña TEMPORAL (must_change_password=true
 * en /me/), el backend responde 403 password_change_required en los endpoints de
 * negocio y RequireAuth lo redirige aquí. La pantalla NO muestra navegación de
 * la app: solo el formulario y "Cerrar sesión" como escape.
 *
 * Al éxito: re-consulta /me/ (must_change_password vuelve a false) y redirige al
 * inicio que corresponda — plataforma si es staff de Maily, clínica si no —
 * con la misma regla que usa LoginPage.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Lock, Eye, EyeOff, AlertCircle, Loader2, KeyRound, LogOut } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { inicioDeRol } from '../auth/permisos'
import { changePassword } from '../api/auth'
import { ApiError } from '../lib/http'
import type { Me } from '../types/api'

/** Inicio según el usuario (misma regla que destinoTrasLogin de LoginPage). */
function destinoInicio(user: Me | null): string {
  if (!user) return '/login'
  if (user.is_platform_staff) return '/plataforma/dashboard'
  if (user.active_role) return inicioDeRol(user.active_role)
  return '/agenda'
}

/** Etiquetas legibles por campo para los errores 400 de DRF. */
const CAMPO_LABEL: Record<string, string> = {
  current_password: 'Contraseña actual',
  new_password: 'Nueva contraseña',
}

/** Traduce el error de la API (actual incorrecta o nueva débil) a texto claro. */
function mensajeDeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.isNetwork) return 'No se pudo conectar con el servidor.'
    if (err.body) {
      if (err.body.detail) return String(err.body.detail)
      const campos = Object.entries(err.body)
        .filter(([k]) => k !== 'detail' && k !== 'code')
        .map(([k, v]) => {
          const msg = Array.isArray(v) ? v.join(' ') : String(v)
          return CAMPO_LABEL[k] ? `${CAMPO_LABEL[k]}: ${msg}` : msg
        })
      if (campos.length) return campos.join(' ')
    }
  }
  return 'No se pudo cambiar la contraseña. Intenta de nuevo.'
}

const INPUT_CLS = 'w-full rounded-xl pl-11 pr-11 py-3 text-base sm:text-sm text-gray-800 placeholder-gray-500 outline-none transition-all duration-150'
const INPUT_STYLE = { background: 'rgba(255,255,255,0.92)', border: '1px solid rgba(255,240,200,0.5)' }

/** Campo de contraseña con candado y ojo (mismo lenguaje visual que LoginPage). */
function CampoPassword({ id, value, onChange, placeholder, autoComplete, autoFocus = false, disabled }: {
  id: string
  value: string
  onChange: (v: string) => void
  placeholder: string
  autoComplete: string
  autoFocus?: boolean
  disabled: boolean
}) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none" style={{ color: '#b89a52' }} />
      <input id={id} type={visible ? 'text' : 'password'} value={value}
        onChange={e => onChange(e.target.value)} placeholder={placeholder}
        autoComplete={autoComplete} autoFocus={autoFocus} disabled={disabled}
        className={INPUT_CLS} style={INPUT_STYLE} />
      <button type="button" tabIndex={-1} onClick={() => setVisible(v => !v)}
        className="absolute right-4 top-1/2 -translate-y-1/2 transition-colors" style={{ color: '#b89a52' }}
        aria-label={visible ? 'Ocultar contraseña' : 'Mostrar contraseña'}>
        {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  )
}

export default function CambiarContrasenaPage() {
  const { user, reloadMe, logout } = useAuth()
  const navigate = useNavigate()

  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [confirmar, setConfirmar] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [saliendo, setSaliendo] = useState(false)

  const forzado = user?.must_change_password ?? false

  const salir = async () => {
    setSaliendo(true)
    try {
      await logout()
    } finally {
      navigate('/login', { replace: true })
    }
  }

  const enviar = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!actual || !nueva || !confirmar) {
      setError('Por favor completa todos los campos.')
      return
    }
    // Validación de cliente (solo UX; el backend vuelve a validar la fortaleza).
    if (nueva.length < 8) {
      setError('La nueva contraseña debe tener al menos 8 caracteres.')
      return
    }
    if (nueva !== confirmar) {
      setError('La nueva contraseña y su confirmación no coinciden.')
      return
    }
    setEnviando(true)
    try {
      await changePassword({ current_password: actual, new_password: nueva })
      // Refresca /me/ para que must_change_password quede en false en el contexto
      // (si no, RequireAuth nos regresaría aquí).
      await reloadMe()
      navigate(destinoInicio(user), { replace: true })
    } catch (err) {
      setError(mensajeDeError(err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="relative min-h-screen w-full flex items-center justify-center overflow-hidden">
      {/* Fondo dorado (mismo lenguaje que LoginPage) */}
      <div className="absolute inset-0"
        style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />
      <div className="absolute inset-0 bg-cover bg-center" style={{ backgroundImage: "url('/fondo.jpg')" }} />
      <div className="absolute inset-0"
        style={{ background: 'radial-gradient(ellipse 70% 70% at 50% 50%, rgba(40,28,8,0.30) 0%, rgba(40,28,8,0.10) 45%, transparent 75%)' }} />

      {/* Card glass centrada — SIN navegación de la app (solo salir) */}
      <motion.div
        initial={{ opacity: 0, y: 26, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="relative w-full max-w-md mx-4"
        style={{
          background: 'rgba(255, 255, 255, 0.10)',
          backdropFilter: 'blur(22px) saturate(140%)',
          WebkitBackdropFilter: 'blur(22px) saturate(140%)',
          border: '1px solid rgba(255, 240, 200, 0.40)',
          borderRadius: '28px',
          boxShadow: '0 20px 60px rgba(60,42,12,0.30), 0 1px 0 rgba(255,255,255,0.45) inset',
          padding: '44px 40px',
        }}
      >
        <div className="absolute top-0 left-12 right-12 h-px pointer-events-none"
          style={{ background: 'linear-gradient(90deg, transparent, rgba(255,245,215,0.9), transparent)' }} />

        {/* Encabezado */}
        <div className="text-center mb-7">
          <div className="mx-auto mb-4 w-14 h-14 rounded-2xl flex items-center justify-center"
            style={{ background: 'rgba(255,255,255,0.16)', border: '1px solid rgba(255,240,200,0.45)' }}>
            <KeyRound className="w-7 h-7" style={{ color: '#FBE7A8' }} />
          </div>
          <h1 className="text-xl font-semibold text-white" style={{ textShadow: '0 2px 12px rgba(40,28,8,0.75)' }}>
            Crea una nueva contraseña
          </h1>
          <p className="text-sm mt-1.5" style={{ color: 'rgba(255,252,245,0.9)', textShadow: '0 1px 8px rgba(40,28,8,0.7)' }}>
            {forzado
              ? 'Tu contraseña es temporal. Elige una nueva para continuar.'
              : 'Elige una contraseña nueva para tu cuenta.'}
          </p>
          {user?.email && (
            <p className="text-xs mt-1 font-medium" style={{ color: '#FBE7A8', textShadow: '0 1px 8px rgba(40,28,8,0.85)' }}>
              {user.email}
            </p>
          )}
        </div>

        <form onSubmit={enviar} noValidate className="space-y-4">
          {error && (
            <div className="flex items-start gap-2.5 rounded-xl px-4 py-3"
              style={{ background: 'rgba(190,40,40,0.18)', border: '1px solid rgba(255,180,180,0.45)' }}>
              <AlertCircle className="w-4 h-4 text-red-200 mt-0.5 shrink-0" />
              <p className="text-red-100 text-sm">{error}</p>
            </div>
          )}

          <CampoPassword id="password-actual" value={actual} onChange={v => { setActual(v); if (error) setError(null) }}
            placeholder="Contraseña actual (la temporal)" autoComplete="current-password" autoFocus disabled={enviando} />

          <CampoPassword id="password-nueva" value={nueva} onChange={v => { setNueva(v); if (error) setError(null) }}
            placeholder="Nueva contraseña (mínimo 8 caracteres)" autoComplete="new-password" disabled={enviando} />

          <CampoPassword id="password-confirmar" value={confirmar} onChange={v => { setConfirmar(v); if (error) setError(null) }}
            placeholder="Confirma la nueva contraseña" autoComplete="new-password" disabled={enviando} />

          <div className="pt-2">
            <button type="submit" disabled={enviando}
              className="btn-login w-full flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold disabled:opacity-60">
              {enviando ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : 'Cambiar contraseña'}
            </button>
          </div>
        </form>

        {/* Único escape: cerrar sesión */}
        <div className="text-center mt-6">
          <button type="button" onClick={() => void salir()} disabled={saliendo}
            className="inline-flex items-center gap-1.5 text-xs font-semibold transition-colors hover:underline disabled:opacity-60"
            style={{ color: '#FBE7A8', textShadow: '0 1px 8px rgba(40,28,8,0.95), 0 0 2px rgba(40,28,8,0.7)' }}>
            <LogOut className="w-3.5 h-3.5" />
            {saliendo ? 'Cerrando sesión…' : 'Cerrar sesión'}
          </button>
        </div>
      </motion.div>
    </div>
  )
}
