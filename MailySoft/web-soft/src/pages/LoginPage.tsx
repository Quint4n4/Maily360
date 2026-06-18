import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Mail, Lock, Eye, EyeOff, AlertCircle, Loader2 } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { inicioDeRol } from '../auth/permisos'
import { ApiError } from '../lib/http'
import type { Me } from '../types/api'
<<<<<<< Updated upstream
=======

import { login } from '../api/auth'
>>>>>>> Stashed changes

interface LoginForm { email: string; password: string }

/** Destino tras login: a dónde iba (state.from), o el inicio según el rol real. */
function destinoTrasLogin(profile: Me, from: string | null): string {
  if (from && from !== '/login') return from
  if (profile.active_role) return inicioDeRol(profile.active_role)
  if (profile.is_platform_staff) return '/plataforma/dashboard'
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
<<<<<<< Updated upstream
=======
<<<<<<< HEAD
      await login(form.email, form.password)
      navigate('/finanzas')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo conectar con el servidor.')
=======
>>>>>>> Stashed changes
      // Login real: setea cookie httpOnly de refresh + access en memoria, y trae /me/.
      const profile = await login({ email: form.email.trim(), password: form.password })
      navigate(destinoTrasLogin(profile, from), { replace: true })
    } catch (err) {
      setError(mensajeDeError(err))
<<<<<<< Updated upstream
=======
>>>>>>> 9f3cd4149619be4d5c604a117d939f7904aad547
>>>>>>> Stashed changes
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen w-full flex items-center justify-center overflow-hidden">

      {/* ── Fondo: gradiente dorado de respaldo (siempre visible) ── */}
      <div className="absolute inset-0"
        style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }} />

      {/* ── Imagen de fondo (guarda tu malla dorada en public/fondo.jpg) ── */}
      <div className="absolute inset-0 bg-cover bg-center"
        style={{ backgroundImage: "url('/fondo.jpg')" }} />

      {/* ── Vignette cálida para anclar la card y dar contraste al texto ── */}
      <div className="absolute inset-0"
        style={{ background: 'radial-gradient(ellipse 70% 70% at 50% 50%, rgba(40,28,8,0.30) 0%, rgba(40,28,8,0.10) 45%, transparent 75%)' }} />

      {/* ── Card glass transparente ── */}
      <motion.div
        initial={{ opacity: 0, y: 26, scale: 0.97 }}
        animate={{ opacity: 1, y: 0,  scale: 1    }}
        transition={{ duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="relative w-full max-w-md mx-4"
        style={{
          background:           'rgba(255, 255, 255, 0.10)',
          backdropFilter:       'blur(22px) saturate(140%)',
          WebkitBackdropFilter: 'blur(22px) saturate(140%)',
          border:               '1px solid rgba(255, 240, 200, 0.40)',
          borderRadius:         '28px',
          boxShadow:            '0 20px 60px rgba(60,42,12,0.30), 0 1px 0 rgba(255,255,255,0.45) inset',
          padding:              '52px 44px',
        }}
      >
        {/* Línea especular superior */}
        <div className="absolute top-0 left-12 right-12 h-px pointer-events-none"
          style={{ background: 'linear-gradient(90deg, transparent, rgba(255,245,215,0.9), transparent)' }} />

        {/* Marca — solo el nombre */}
        <motion.div {...fadeUp(0)} className="text-center mb-8">
          <h1 className="text-3xl font-bold tracking-tight"
            style={{ color: '#fff', textShadow: '0 2px 14px rgba(40,28,8,0.7), 0 0 2px rgba(40,28,8,0.5)' }}>
            maily<span style={{ color: '#FBE7A8' }}>360</span>
          </h1>
        </motion.div>

        {/* Subtítulo */}
        <motion.div {...fadeUp(0.06)} className="text-center mb-8">
          <h2 className="text-xl font-semibold text-white"
            style={{ textShadow: '0 2px 12px rgba(40,28,8,0.75)' }}>
            Inicia sesión
          </h2>
          <p className="text-sm mt-1" style={{ color: 'rgba(255,252,245,0.9)', textShadow: '0 1px 8px rgba(40,28,8,0.7)' }}>
            Accede al panel de tu clínica.
          </p>
        </motion.div>

        <form onSubmit={handleSubmit} noValidate className="space-y-4">

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div key="err"
                initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2 }}
                className="flex items-start gap-2.5 rounded-xl px-4 py-3"
                style={{ background: 'rgba(190,40,40,0.18)', border: '1px solid rgba(255,180,180,0.45)' }}
              >
                <AlertCircle className="w-4 h-4 text-red-200 mt-0.5 shrink-0" />
                <p className="text-red-100 text-sm">{error}</p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Email */}
          <motion.div {...fadeUp(0.1)}>
            <div className="relative">
              <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none"
                style={{ color: '#b89a52' }} />
              <input id="email" type="email" name="email" value={form.email} onChange={handleChange}
                placeholder="Correo electrónico" autoComplete="email" autoFocus disabled={isLoading}
                className="w-full rounded-xl pl-11 pr-4 py-3 text-sm text-gray-800 placeholder-gray-500 outline-none transition-all duration-150"
                style={{ background: 'rgba(255,255,255,0.92)', border: '1px solid rgba(255,240,200,0.5)' }}
              />
            </div>
          </motion.div>

          {/* Contraseña */}
          <motion.div {...fadeUp(0.15)}>
            <div className="relative">
              <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none"
                style={{ color: '#b89a52' }} />
              <input id="password" type={showPassword ? 'text' : 'password'} name="password"
                value={form.password} onChange={handleChange} placeholder="Contraseña"
                autoComplete="current-password" disabled={isLoading}
                className="w-full rounded-xl pl-11 pr-11 py-3 text-sm text-gray-800 placeholder-gray-500 outline-none transition-all duration-150"
                style={{ background: 'rgba(255,255,255,0.92)', border: '1px solid rgba(255,240,200,0.5)' }}
              />
              <button type="button" tabIndex={-1} onClick={() => setShowPassword(v => !v)}
                className="absolute right-4 top-1/2 -translate-y-1/2 transition-colors"
                style={{ color: '#b89a52' }}>
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </motion.div>

          {/* Recuérdame + olvidaste */}
          <motion.div {...fadeUp(0.2)} className="flex items-center justify-between pt-1">
            <button type="button" onClick={() => setRememberMe(v => !v)}
              className="flex items-center gap-2 select-none">
              <span className="w-4 h-4 rounded flex items-center justify-center transition-all shrink-0"
                style={{
                  background: rememberMe ? '#C9A227' : 'rgba(40,28,8,0.20)',
                  border: rememberMe ? '1px solid #C9A227' : '1px solid rgba(255,248,230,0.85)',
                  boxShadow: '0 1px 4px rgba(40,28,8,0.35)',
                }}>
                {rememberMe && (
                  <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 12 12">
                    <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                )}
              </span>
              <span className="text-xs font-medium" style={{ color: '#ffffff', textShadow: '0 1px 8px rgba(40,28,8,0.85)' }}>Recordarme</span>
            </button>
            <button type="button" className="text-xs font-semibold transition-colors hover:underline"
              style={{ color: '#FBE7A8', textShadow: '0 1px 8px rgba(40,28,8,0.95), 0 0 2px rgba(40,28,8,0.7)' }}>
              ¿Olvidaste tu contraseña?
            </button>
          </motion.div>

          {/* Entrar */}
          <motion.div {...fadeUp(0.25)} className="pt-2">
            <button type="submit" disabled={isLoading}
              className="btn-login w-full flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold disabled:opacity-60">
              {isLoading ? <><Loader2 className="w-4 h-4 animate-spin" /> Entrando…</> : 'Entrar'}
            </button>
          </motion.div>
        </form>
      </motion.div>
    </div>
  )
}
