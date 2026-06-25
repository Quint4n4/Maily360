import { useState } from 'react'
import { X, Building2, Loader2, Check, Copy, KeyRound, AlertCircle } from 'lucide-react'
import { useCreateClinica } from '../../hooks/plataforma'
import { ApiError } from '../../lib/http'
import type { ClinicaCreateResult } from '../../types/plataforma'

interface Props {
  open: boolean
  onClose: () => void
}

const INPUT = 'w-full rounded-xl px-3.5 py-2.5 text-base sm:text-sm text-gray-800 outline-none transition-all'
const INPUT_STYLE = { background: 'rgba(255,255,255,0.85)', border: '1px solid rgba(201,162,39,0.3)' }
const LABEL = 'block text-xs font-semibold mb-1.5'

/** Convierte el error de la API en un texto legible. */
function textoError(err: unknown): string {
  if (err instanceof ApiError && err.body) {
    if (err.body.detail) return String(err.body.detail)
    const campos = Object.entries(err.body)
      .filter(([k]) => k !== 'detail')
      .map(([, v]) => (Array.isArray(v) ? v.join(' ') : String(v)))
    if (campos.length) return campos.join(' ')
  }
  return 'No se pudo crear la clínica. Revisa los datos e intenta de nuevo.'
}

export default function NuevaClinicaModal({ open, onClose }: Props) {
  const crear = useCreateClinica()
  const [nombre, setNombre] = useState('')
  const [dueñoNombre, setDueñoNombre] = useState('')
  const [dueñoApellido, setDueñoApellido] = useState('')
  const [dueñoEmail, setDueñoEmail] = useState('')
  const [diasPrueba, setDiasPrueba] = useState(60)
  const [error, setError] = useState<string | null>(null)
  const [resultado, setResultado] = useState<ClinicaCreateResult | null>(null)
  const [copiado, setCopiado] = useState(false)

  if (!open) return null

  const cerrar = () => {
    setNombre(''); setDueñoNombre(''); setDueñoApellido(''); setDueñoEmail('')
    setDiasPrueba(60); setError(null); setResultado(null); setCopiado(false)
    onClose()
  }

  const enviar = async () => {
    setError(null)
    if (!nombre.trim() || !dueñoNombre.trim() || !dueñoApellido.trim() || !dueñoEmail.trim()) {
      setError('Completa el nombre de la clínica y los datos del dueño.')
      return
    }
    try {
      const res = await crear.mutateAsync({
        name: nombre.trim(),
        owner_first_name: dueñoNombre.trim(),
        owner_last_name: dueñoApellido.trim(),
        owner_email: dueñoEmail.trim(),
        trial_days: diasPrueba,
      })
      setResultado(res)
    } catch (e) {
      setError(textoError(e))
    }
  }

  const copiar = async () => {
    if (!resultado) return
    try {
      await navigator.clipboard.writeText(resultado.temporary_password)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 1800)
    } catch { /* ignore */ }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(30,22,8,0.45)', backdropFilter: 'blur(4px)' }}>
      <div className="relative w-full max-w-lg rounded-3xl p-7"
        style={{ background: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(22px)', border: '1px solid rgba(255,255,255,0.7)', boxShadow: '0 24px 60px rgba(60,42,12,0.3)' }}>
        <button onClick={cerrar} className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors">
          <X className="w-4 h-4" />
        </button>

        {resultado ? (
          /* ── Éxito: contraseña temporal (mostrar una sola vez) ── */
          <div>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-11 h-11 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(46,158,91,0.14)' }}>
                <Check className="w-6 h-6" style={{ color: '#2E9E5B' }} />
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900">¡Clínica creada!</h2>
                <p className="text-sm text-gray-500">{resultado.tenant.name}</p>
              </div>
            </div>

            <p className="text-sm text-gray-600 mb-3">
              El dueño <strong>{resultado.owner_email}</strong> ya puede entrar con esta contraseña temporal:
            </p>

            <div className="rounded-2xl p-4 mb-3" style={{ background: '#FBF6E6', border: '1px solid rgba(201,162,39,0.35)' }}>
              <div className="flex items-center gap-2 mb-2 text-xs font-semibold" style={{ color: '#9A7B1E' }}>
                <KeyRound className="w-4 h-4" /> Contraseña temporal
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-base font-bold tracking-wide px-3 py-2 rounded-lg" style={{ background: '#fff', color: '#2A241B' }}>
                  {resultado.temporary_password}
                </code>
                <button onClick={copiar} className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white" style={{ background: '#C9A227' }}>
                  {copiado ? <><Check className="w-4 h-4" /> Copiado</> : <><Copy className="w-4 h-4" /> Copiar</>}
                </button>
              </div>
            </div>

            <p className="text-xs flex items-start gap-1.5 mb-5" style={{ color: '#C0392B' }}>
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              Guárdala y compártesela al dueño ahora. <strong>No se volverá a mostrar.</strong>
            </p>

            <button onClick={cerrar} className="w-full py-2.5 rounded-xl text-sm font-semibold text-white" style={{ background: '#C9A227' }}>
              Listo
            </button>
          </div>
        ) : (
          /* ── Formulario de alta ── */
          <div>
            <div className="flex items-center gap-3 mb-5">
              <div className="w-11 h-11 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(201,162,39,0.16)' }}>
                <Building2 className="w-6 h-6" style={{ color: '#C9A227' }} />
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900">Nueva clínica</h2>
                <p className="text-sm text-gray-500">Se creará en modo prueba con su dueño.</p>
              </div>
            </div>

            {error && (
              <div className="flex items-start gap-2 rounded-xl px-3.5 py-2.5 mb-4" style={{ background: 'rgba(192,57,43,0.1)', border: '1px solid rgba(192,57,43,0.25)' }}>
                <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            <div className="space-y-3.5">
              <div>
                <label className={LABEL} style={{ color: '#9A7B1E' }}>Nombre de la clínica</label>
                <input className={INPUT} style={INPUT_STYLE} value={nombre} onChange={e => setNombre(e.target.value)} placeholder="Ej. Clínica San José" autoFocus />
              </div>

              <div className="pt-1">
                <p className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: '#B8860B' }}>Dueño de la clínica</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={LABEL} style={{ color: '#9A7B1E' }}>Nombre(s)</label>
                    <input className={INPUT} style={INPUT_STYLE} value={dueñoNombre} onChange={e => setDueñoNombre(e.target.value)} placeholder="Juan" />
                  </div>
                  <div>
                    <label className={LABEL} style={{ color: '#9A7B1E' }}>Apellidos</label>
                    <input className={INPUT} style={INPUT_STYLE} value={dueñoApellido} onChange={e => setDueñoApellido(e.target.value)} placeholder="Pérez" />
                  </div>
                </div>
              </div>

              <div>
                <label className={LABEL} style={{ color: '#9A7B1E' }}>Correo del dueño (su usuario de acceso)</label>
                <input className={INPUT} style={INPUT_STYLE} type="email" value={dueñoEmail} onChange={e => setDueñoEmail(e.target.value)} placeholder="dueno@clinica.mx" />
              </div>

              <div>
                <label className={LABEL} style={{ color: '#9A7B1E' }}>Días de prueba</label>
                <input className={`${INPUT} w-28`} style={INPUT_STYLE} type="number" min={1} max={365} value={diasPrueba} onChange={e => setDiasPrueba(Number(e.target.value))} />
              </div>
            </div>

            <button onClick={enviar} disabled={crear.isPending}
              className="w-full mt-6 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-60" style={{ background: '#C9A227' }}>
              {crear.isPending ? <><Loader2 className="w-4 h-4 animate-spin" /> Creando…</> : <>Crear clínica</>}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
