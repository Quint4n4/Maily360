import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Mail, Lock, Eye, EyeOff, AlertCircle, Loader2 } from 'lucide-react'
import MarcaMaily from '../components/MarcaMaily'
import { useAuth } from '../auth/AuthContext'
import { inicioDeRol } from '../auth/permisos'
import { ApiError } from '../lib/http'
import type { Me } from '../types/api'

interface LoginForm { email: string; password: string }

/** Destino tras login: a dónde iba (state.from), o el inicio según el rol real.
 *  El staff de Maily entra al panel de plataforma; si además tiene clínica,
 *  puede saltar a ella desde el menú del topbar. */
function destinoTrasLogin(profile: Me, from: string | null): string {
  if (from && from !== '/login') return from
  if (profile.is_platform_staff) return '/plataforma/dashboard'
  if (profile.active_role) return inicioDeRol(profile.active_role)
  return '/agenda'
}

/** Traduce un error de la API a un mensaje claro para el usuario. */
function mensajeDeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.isNetwork) return 'No se pudo conectar con el servidor.'
    if (err.status === 401) return 'Correo o contraseña incorrectos. Intenta de nuevo.'
    if (err.status === 429) return 'Demasiados intentos. Espera un momento e inténtalo de nuevo.'
    if (err.body?.detail) return err.body.detail
  }
  return 'No se pudo iniciar sesión. Intenta de nuevo.'
}

const fadeUp = (delay = 0) => ({
  initial:    { opacity: 0, y: 14 },
  animate:    { opacity: 1, y: 0  },
  transition: { duration: 0.5, ease: [0.25, 0.46, 0.45, 0.94] as const, delay },
})

export default function LoginPage() {
  const [form, setForm]                 = useState<LoginForm>({ email: '', password: '' })
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading]       = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [rememberMe, setRememberMe]     = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()

  // A dónde quería ir el usuario antes de que RequireAuth lo mandara a /login.
  const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? null

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setForm(prev => ({ ...prev, [name]: value }))
    if (error) setError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.email || !form.password) { setError('Por favor completa todos los campos.'); return }
    setIsLoading(true); setError(null)
    try {
      // Login real: setea cookie httpOnly de refresh + access en memoria, y trae /me/.
      const profile = await login({ email: form.email.trim(), password: form.password })
      navigate(destinoTrasLogin(profile, from), { replace: true })
    } catch (err) {
      setError(mensajeDeError(err))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    /*
     * Fondo plano y tarjeta sólida.
     *
     * Antes esto era una foto de seda dorada + degradado + viñeta, y encima una
     * tarjeta translúcida con el texto en blanco: "Inicia sesión" y "¿Olvidaste
     * tu contraseña?" quedaban por debajo de 2:1 de contraste sobre las zonas
     * claras de la imagen. Un login es lo primero que ve un cliente y no puede
     * depender de qué parte de una foto le toque detrás a cada palabra.
     *
     * El aire premium ahora lo da la contención: mucho blanco, una tarjeta bien
     * separada y el oro SOLO en la marca. Es la misma lógica de tinta + oro que
     * usa el resto de la app.
     */
    <div className="min-h-screen w-full flex items-center justify-center bg-fondo px-4 py-10">

      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0,  scale: 1    }}
        transition={{ duration: 0.5, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="w-full max-w-md bg-superficie border border-borde rounded-3xl shadow-card-alto
                   px-8 py-10 sm:px-11 sm:py-12"
      >
        {/* Marca — único sitio del login donde vive el oro */}
        {/* Se usa el lockup HORIZONTAL, no el vertical: en el archivo vertical
            la palabra "maily" viene en BLANCO (versión para fondos oscuros) y
            sobre esta tarjeta clara desaparecía — se veía solo el hexágono. */}
        <motion.div {...fadeUp(0)} className="flex justify-center">
          <MarcaMaily variante="horizontal" className="h-14" />
        </motion.div>

        <motion.div {...fadeUp(0.06)} className="text-center mb-8">
          <h2 className="text-lg font-semibold text-tinta mt-6">Inicia sesión</h2>
          <p className="text-sm text-suave mt-1">Accede al panel de tu clínica.</p>
        </motion.div>

        <form onSubmit={handleSubmit} noValidate className="space-y-4">

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div key="err"
                role="alert"
                initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2 }}
                className="flex items-start gap-2.5 rounded-xl px-4 py-3 bg-peligro-tinte border border-peligro-borde"
              >
                <AlertCircle className="w-4 h-4 text-peligro mt-0.5 shrink-0" />
                <p className="text-peligro text-sm">{error}</p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Email */}
          <motion.div {...fadeUp(0.1)}>
            <label className="label" htmlFor="email">Correo electrónico</label>
            <div className="relative">
              <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-tenue pointer-events-none" />
              <input id="email" type="email" name="email" value={form.email} onChange={handleChange}
                placeholder="tucorreo@clinica.com" autoComplete="email" autoFocus disabled={isLoading}
                className="input pl-10"
              />
            </div>
          </motion.div>

          {/* Contraseña */}
          <motion.div {...fadeUp(0.15)}>
            <label className="label" htmlFor="password">Contraseña</label>
            <div className="relative">
              <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-tenue pointer-events-none" />
              <input id="password" type={showPassword ? 'text' : 'password'} name="password"
                value={form.password} onChange={handleChange} placeholder="••••••••"
                autoComplete="current-password" disabled={isLoading}
                className="input pl-10 pr-10"
              />
              <button type="button" tabIndex={-1} onClick={() => setShowPassword(v => !v)}
                aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 text-tenue hover:text-cuerpo transition-colors">
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </motion.div>

          {/* Recuérdame + olvidaste */}
          <motion.div {...fadeUp(0.2)} className="flex items-center justify-between pt-1">
            <button type="button" onClick={() => setRememberMe(v => !v)}
              aria-pressed={rememberMe}
              className="flex items-center gap-2 select-none group">
              <span className={`w-4 h-4 rounded flex items-center justify-center transition-all shrink-0 border
                ${rememberMe ? 'bg-accion border-accion' : 'bg-superficie border-borde group-hover:border-accion-borde'}`}>
                {rememberMe && (
                  <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 12 12">
                    <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                )}
              </span>
              <span className="text-xs font-medium text-cuerpo">Recordarme</span>
            </button>
            <button type="button" className="text-xs font-semibold text-accion hover:text-accion-hover hover:underline transition-colors">
              ¿Olvidaste tu contraseña?
            </button>
          </motion.div>

          {/* Entrar */}
          <motion.div {...fadeUp(0.25)} className="pt-2">
            <button type="submit" disabled={isLoading} className="btn-primary w-full py-3">
              {isLoading ? <><Loader2 className="w-4 h-4 animate-spin" /> Entrando…</> : 'Entrar'}
            </button>
          </motion.div>
        </form>
      </motion.div>
    </div>
  )
}
