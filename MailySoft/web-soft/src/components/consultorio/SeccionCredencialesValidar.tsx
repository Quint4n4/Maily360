/**
 * SeccionCredencialesValidar — Bandeja de validación del administrador.
 *
 * Lista las credenciales que capturan los médicos de la clínica y permite al
 * owner/admin validarlas o rechazarlas (con motivo). Solo las VALIDADAS aparecen
 * en la receta. La verificación real (que la cédula exista) la hace el admin en
 * el portal de la SEP; aquí se registra el resultado.
 */

import { useState } from 'react'
import { Award, Check, Loader2, ShieldX } from 'lucide-react'
import { useCredentialsToValidate, useValidateCredential } from '../../hooks/clinica'
import { erroresDe } from '../../lib/apiErrors'
import type { DoctorCredentialOut } from '../../types/credenciales'
import { AlertaErrores, AvisoSoloLectura, Nota } from './Avisos'
import CredencialEstadoBadge from './CredencialEstadoBadge'

interface Props {
  /** Si false, solo lectura (sin acciones de validar/rechazar). */
  editable: boolean
}

type Filtro = 'pendiente' | 'todas'

/** Sección "Credenciales por validar" de Mi Consultorio (owner/admin). */
export default function SeccionCredencialesValidar({ editable }: Props) {
  const [filtro, setFiltro] = useState<Filtro>('pendiente')
  const credsQ = useCredentialsToValidate(filtro === 'pendiente' ? 'pendiente' : undefined)
  const validar = useValidateCredential()

  const [errores, setErrores] = useState<string[]>([])
  const [rechazandoId, setRechazandoId] = useState<string | null>(null)
  const [motivo, setMotivo] = useState('')

  const creds = credsQ.data ?? []

  const aprobar = async (c: DoctorCredentialOut) => {
    setErrores([])
    try {
      await validar.mutateAsync({ id: c.id, input: { status: 'validada' } })
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  const confirmarRechazo = async (c: DoctorCredentialOut) => {
    setErrores([])
    try {
      await validar.mutateAsync({ id: c.id, input: { status: 'rechazada', note: motivo.trim() } })
      setRechazandoId(null)
      setMotivo('')
    } catch (err) {
      setErrores(erroresDe(err))
    }
  }

  return (
    <div className="space-y-5">
      {!editable && <AvisoSoloLectura />}
      <AlertaErrores errores={errores} />

      <div className="flex items-start justify-between gap-3">
        <Nota>
          Revisa las credenciales que capturan los médicos. Solo las <strong>validadas</strong>
          {' '}aparecen en la receta. Verifica que la cédula exista en el portal de la SEP antes de validar.
        </Nota>
        <a
          className="shrink-0 text-xs font-semibold text-amber-700 underline"
          href="https://www.cedulaprofesional.sep.gob.mx/"
          target="_blank"
          rel="noreferrer"
        >
          Portal SEP ↗
        </a>
      </div>

      {/* Filtro */}
      <div className="flex gap-2">
        {(['pendiente', 'todas'] as Filtro[]).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFiltro(f)}
            className="text-xs font-semibold rounded-full px-3 py-1.5 transition-colors"
            style={{
              background: filtro === f ? 'rgba(201,162,39,0.16)' : 'rgba(120,120,120,0.08)',
              color: filtro === f ? '#9A7B1E' : '#6B6459',
            }}
          >
            {f === 'pendiente' ? 'Pendientes' : 'Todas'}
          </button>
        ))}
      </div>

      {/* Lista */}
      {credsQ.isLoading ? (
        <div className="flex items-center justify-center py-12 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Cargando credenciales…
        </div>
      ) : credsQ.isError ? (
        <AlertaErrores errores={erroresDe(credsQ.error)} />
      ) : creds.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-gray-400">
          <Award className="w-9 h-9 mb-2 opacity-50" />
          <p className="text-sm">
            {filtro === 'pendiente' ? 'No hay credenciales pendientes por validar.' : 'No hay credenciales.'}
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {creds.map((c) => (
            <li key={c.id} className="rounded-2xl border border-gray-100 bg-white/70 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  {c.logo_url ? (
                    <img src={c.logo_url} alt="" className="h-10 w-10 object-contain shrink-0" />
                  ) : (
                    <div className="h-10 w-10 rounded-lg bg-gray-50 flex items-center justify-center shrink-0">
                      <Award className="w-4 h-4 text-gray-300" />
                    </div>
                  )}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-gray-800 truncate">{c.title}</span>
                      <CredencialEstadoBadge status={c.validation_status} label={c.validation_status_display} />
                    </div>
                    <p className="text-xs text-gray-500">
                      <span className="font-medium text-gray-700">{c.doctor_name}</span> · {c.kind_display}
                    </p>
                    <p className="text-xs text-gray-500">
                      {[c.institution, c.credential_number ? `Céd. ${c.credential_number}` : '']
                        .filter(Boolean).join(' · ') || '—'}
                    </p>
                    {c.validation_status === 'rechazada' && c.validation_note && (
                      <p className="text-[11px] text-red-600 mt-0.5">Motivo: {c.validation_note}</p>
                    )}
                  </div>
                </div>

                {editable && rechazandoId !== c.id && (
                  <div className="flex gap-1 shrink-0">
                    {c.validation_status !== 'validada' && (
                      <button
                        type="button"
                        onClick={() => aprobar(c)}
                        disabled={validar.isPending}
                        className="inline-flex items-center gap-1 text-xs font-semibold rounded-lg px-3 py-1.5 disabled:opacity-50"
                        style={{ background: 'rgba(46,125,91,0.12)', color: '#2E7D5B' }}
                      >
                        <Check className="w-3.5 h-3.5" /> Validar
                      </button>
                    )}
                    {c.validation_status !== 'rechazada' && (
                      <button
                        type="button"
                        onClick={() => { setRechazandoId(c.id); setMotivo('') }}
                        className="inline-flex items-center gap-1 text-xs font-semibold rounded-lg px-3 py-1.5"
                        style={{ background: 'rgba(190,40,40,0.08)', color: '#B22222' }}
                      >
                        <ShieldX className="w-3.5 h-3.5" /> {c.validation_status === 'validada' ? 'Revocar' : 'Rechazar'}
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* Form de rechazo inline */}
              {editable && rechazandoId === c.id && (
                <div className="mt-3 flex flex-col sm:flex-row gap-2">
                  <input
                    className="input flex-1"
                    maxLength={255}
                    placeholder="Motivo (ej. cédula no encontrada en el portal de la SEP)"
                    value={motivo}
                    onChange={(e) => setMotivo(e.target.value)}
                  />
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => confirmarRechazo(c)}
                      disabled={validar.isPending}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-white rounded-lg px-3 py-1.5 disabled:opacity-50"
                      style={{ background: '#B22222' }}
                    >
                      {validar.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldX className="w-3.5 h-3.5" />}
                      Confirmar rechazo
                    </button>
                    <button
                      type="button"
                      onClick={() => { setRechazandoId(null); setMotivo('') }}
                      className="btn-secondary px-3 py-1.5 text-xs"
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
