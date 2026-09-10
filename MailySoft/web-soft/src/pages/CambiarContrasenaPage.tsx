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
      <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-tenue pointer-events-none" />
      <input id={id} type={visible ? 'text' : 'password'} value={value}
        onChange={e => onChange(e.target.value)} placeholder={placeholder}
        autoComplete={autoComplete} autoFocus={autoFocus} disabled={disabled}
        className="input pl-10 pr-10" />
      <button type="button" tabIndex={-1} onClick={() => setVisible(v => !v)}
        className="absolute right-3.5 top-1/2 -translate-y-1/2 text-tenue hover:text-cuerpo transition-colors"
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
    /* Mismo lenguaje que LoginPage: fondo plano y tarjeta sólida. */
    <div className="min-h-screen w-full flex items-center justify-center bg-fondo px-4 py-10">

      {/* Tarjeta centrada — SIN navegación de la app (solo salir) */}
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="w-full max-w-md bg-superficie border border-borde rounded-3xl shadow-card-alto
                   px-8 py-10 sm:px-11 sm:py-11"
      >
        {/* Encabezado */}
        <div className="text-center mb-7">
          <div className="mx-auto mb-4 w-14 h-14 rounded-2xl flex items-center justify-center bg-accion-tinte border border-accion-borde">
            <KeyRound className="w-7 h-7 text-accion" />
          </div>
          <h1 className="text-xl font-semibold text-tinta">
            Crea una nueva contraseña
          </h1>
          <p className="text-sm mt-1.5 text-suave">
            {forzado
              ? 'Tu contraseña es temporal. Elige una nueva para continuar.'
              : 'Elige una contraseña nueva para tu cuenta.'}
          </p>
          {user?.email && (
            <p className="text-xs mt-1 font-medium text-cuerpo">
              {user.email}
            </p>
          )}
        </div>

        <form onSubmit={enviar} noValidate className="space-y-4">
          {error && (
            <div role="alert" className="flex items-start gap-2.5 rounded-xl px-4 py-3 bg-peligro-tinte border border-peligro-borde">
              <AlertCircle className="w-4 h-4 text-peligro mt-0.5 shrink-0" />
              <p className="text-peligro text-sm">{error}</p>
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
              className="btn-primary w-full py-3">
              {enviando ? <><Loader2 className="w-4 h-4 animate-spin" /> Guardando…</> : 'Cambiar contraseña'}
            </button>
          </div>
        </form>

        {/* Único escape: cerrar sesión */}
        <div className="text-center mt-6">
          <button type="button" onClick={() => void salir()} disabled={saliendo}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-accion hover:text-accion-hover hover:underline transition-colors disabled:opacity-60">
            <LogOut className="w-3.5 h-3.5" />
            {saliendo ? 'Cerrando sesión…' : 'Cerrar sesión'}
          </button>
        </div>
      </motion.div>
    </div>
  )
}
