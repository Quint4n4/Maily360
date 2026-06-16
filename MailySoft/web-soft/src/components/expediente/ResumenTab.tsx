/**
 * ResumenTab — pestaña Resumen del expediente.
 * Contacto + identificación + datos NOM-004 + próxima cita + historial de citas
 * + banderas de Alergias (prominentes, rojas) con alta y resolver.
 */

import { useState } from 'react'
import {
  Phone, Mail, Fingerprint, CalendarClock, ClipboardList, StickyNote, User,
  AlertTriangle, Plus, X, Loader2, MapPin, Heart,
} from 'lucide-react'
import type { PatientOut } from '../../types/paciente'
import type { Appointment, AppointmentStatus } from '../../types/agenda'
import type { Allergy, AllergyInput, AllergySeverity } from '../../types/expediente'
import { useAppointmentsForPatient } from '../../hooks/agenda'
import { useAllergies, useCreateAllergy, useResolveAllergy } from '../../hooks/expediente'
import { edad } from '../../lib/paciente'
import { formatFechaHora } from '../../lib/fecha'
import { errorMsg } from '../../lib/apiErrors'
import { Card, Linea, Cargando, SEVERITY_OPTIONS } from './ui'

/** Estilo del chip de estado de una cita. */
function estadoChip(s: AppointmentStatus): { bg: string; color: string } {
  if (s === 'attended') return { bg: '#DCF3E6', color: '#1F6E47' }
  if (s === 'confirmed' || s === 'arrived' || s === 'in_progress') return { bg: '#E7F6EE', color: '#2E7D5B' }
  if (s === 'cancelled' || s === 'no_show') return { bg: '#FDE8E8', color: '#C0392B' }
  return { bg: '#FBF1D9', color: '#9A7B1E' }
}
const ESTADOS_INACTIVOS = new Set<AppointmentStatus>(['attended', 'cancelled', 'no_show'])

/** Color de la bandera de alergia según severidad. */
function severidadColor(sev: AllergySeverity): { bg: string; border: string; color: string } {
  if (sev === 'severa') return { bg: 'rgba(192,57,43,0.12)', border: 'rgba(192,57,43,0.4)', color: '#C0392B' }
  if (sev === 'moderada') return { bg: 'rgba(214,124,30,0.12)', border: 'rgba(214,124,30,0.4)', color: '#B8620B' }
  return { bg: 'rgba(201,162,39,0.12)', border: 'rgba(201,162,39,0.35)', color: '#9A7B1E' }
}

interface ResumenTabProps {
  paciente: PatientOut
  verClinico: boolean
  puedeEditarClinico: boolean
}

export default function ResumenTab({ paciente, verClinico, puedeEditarClinico }: ResumenTabProps) {
  const years = edad(paciente.date_of_birth ?? '')

  const { data: citasData, isLoading: citasLoading } = useAppointmentsForPatient(paciente.id)
  const citas: Appointment[] = citasData?.results ?? []
  const historial = [...citas].sort((a, b) => b.starts_at.localeCompare(a.starts_at))
  const proxima: Appointment | null =
    [...citas]
      .filter(c => !ESTADOS_INACTIVOS.has(c.status))
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0] ?? null

  const domicilio = [paciente.address_street, paciente.address_neighborhood, paciente.city, paciente.state]
    .filter(Boolean)
    .join(', ')

  return (
    <div className="space-y-5">
      {/* Banderas de alergias (solo roles clínicos) */}
      {verClinico && <AlergiasBlock patientId={paciente.id} puedeEditar={puedeEditarClinico} />}

      <div className="grid gap-5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
        <Card title="Contacto" icon={Phone}>
          <div className="space-y-2.5">
            <div className="flex items-center gap-2.5">
              <Phone className="w-4 h-4 text-gray-400 shrink-0" />
              <span className="text-sm text-gray-800">{paciente.phone || '—'}</span>
            </div>
            {paciente.phone_secondary && (
              <div className="flex items-center gap-2.5">
                <Phone className="w-4 h-4 text-gray-400 shrink-0" />
                <span className="text-sm text-gray-800">
                  {paciente.phone_secondary}
                  {paciente.phone_label ? ` (${paciente.phone_label})` : ''}
                </span>
              </div>
            )}
            <div className="flex items-center gap-2.5">
              <Mail className="w-4 h-4 text-gray-400 shrink-0" />
              <span className="text-sm text-gray-800 truncate">{paciente.email || '—'}</span>
            </div>
            {domicilio && (
              <div className="flex items-start gap-2.5">
                <MapPin className="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
                <span className="text-sm text-gray-800">
                  {domicilio}{paciente.postal_code ? ` · CP ${paciente.postal_code}` : ''}
                </span>
              </div>
            )}
          </div>
        </Card>

        <Card title="Identificación" icon={Fingerprint}>
          <Linea label="CURP" value={paciente.curp} />
          <Linea label="Nacimiento" value={paciente.date_of_birth ?? ''} />
          <Linea label="Edad" value={years !== null ? `${years} años` : '—'} />
          <Linea label="Sexo" value={paciente.sex_display || '—'} />
          <Linea label="Lugar de nacimiento" value={paciente.birthplace} />
        </Card>

        <Card title="Datos NOM-004" icon={Heart}>
          <Linea label="Estado civil" value={paciente.marital_status_display} />
          <Linea label="Escolaridad" value={paciente.education_display} />
          <Linea label="Ocupación" value={paciente.occupation} />
          <Linea label="Religión" value={paciente.religion} />
          <Linea label="Tipo de sangre" value={paciente.blood_type_display} />
          {paciente.category && <Linea label="Categoría" value={paciente.category} />}
        </Card>

        <Card title="Próxima cita" icon={CalendarClock}>
          {citasLoading ? (
            <p className="text-sm text-gray-400 italic">Cargando…</p>
          ) : proxima ? (
            <div>
              <p className="text-base font-bold text-gray-900">{formatFechaHora(proxima.starts_at)}</p>
              <p className="text-sm text-gray-500 mt-0.5">
                {proxima.doctor.full_name}{proxima.consultorio ? ` · ${proxima.consultorio.name}` : ''}
              </p>
              <span className="badge mt-2" style={{ background: estadoChip(proxima.status).bg, color: estadoChip(proxima.status).color }}>
                {proxima.status_display}
              </span>
            </div>
          ) : (
            <p className="text-sm text-gray-400 italic">Sin cita próxima.</p>
          )}
        </Card>
      </div>

      {verClinico && (
        <Card title="Notas" icon={StickyNote}>
          <p className="text-sm text-gray-600 leading-relaxed">{paciente.notes || 'Sin notas registradas.'}</p>
        </Card>
      )}

      <Card title="Historial de citas" icon={ClipboardList}>
        {citasLoading ? (
          <p className="text-sm text-gray-400 italic py-3 text-center">Cargando…</p>
        ) : historial.length === 0 ? (
          <p className="text-sm text-gray-400 italic py-3 text-center">Sin citas registradas todavía.</p>
        ) : (
          <div className="space-y-2">
            {historial.map(h => {
              const chip = estadoChip(h.status)
              const motivo = h.appointment_type?.name || h.reason || 'Cita'
              return (
                <div key={h.id} className="flex items-center justify-between rounded-xl px-4 py-2.5 bg-white/60">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: 'rgba(201,162,39,0.12)' }}>
                      <User className="w-4 h-4" style={{ color: '#C9A227' }} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{motivo}</p>
                      <p className="text-xs text-gray-400">{formatFechaHora(h.starts_at)} · {h.doctor.full_name}</p>
                    </div>
                  </div>
                  <span className="badge shrink-0 ml-2" style={{ background: chip.bg, color: chip.color }}>{h.status_display}</span>
                </div>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}

// ── Bloque de alergias (banderas) ────────────────────────────────────────────

function AlergiasBlock({ patientId, puedeEditar }: { patientId: string; puedeEditar: boolean }) {
  const { data: alergias, isLoading, isError } = useAllergies(patientId)
  const crear = useCreateAllergy(patientId)
  const resolver = useResolveAllergy(patientId)
  const [abierto, setAbierto] = useState(false)
  const [form, setForm] = useState<AllergyInput>({ substance: '', reaction: '', severity: '' })
  const [error, setError] = useState('')

  const vigentes = alergias ?? []

  const guardar = async () => {
    if (!form.substance.trim()) { setError('La sustancia es obligatoria.'); return }
    setError('')
    try {
      await crear.mutateAsync({
        substance: form.substance.trim(),
        reaction: form.reaction?.trim() || undefined,
        severity: form.severity || undefined,
      })
      setForm({ substance: '', reaction: '', severity: '' })
      setAbierto(false)
    } catch (err) {
      setError(errorMsg(err))
    }
  }

  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: vigentes.length > 0 ? 'rgba(192,57,43,0.07)' : 'rgba(255,255,255,0.72)',
        backdropFilter: 'blur(14px)',
        border: vigentes.length > 0 ? '1px solid rgba(192,57,43,0.3)' : '1px solid rgba(255,255,255,0.7)',
        boxShadow: '0 6px 20px rgba(60,42,12,0.10)',
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" style={{ color: vigentes.length > 0 ? '#C0392B' : '#C9A227' }} />
          <h4 className="text-xs font-semibold uppercase tracking-wide" style={{ color: vigentes.length > 0 ? '#C0392B' : '#9A7B1E' }}>
            Alergias {vigentes.length > 0 && `(${vigentes.length})`}
          </h4>
        </div>
        {puedeEditar && !abierto && (
          <button
            type="button" onClick={() => setAbierto(true)}
            className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700 hover:text-amber-800"
          >
            <Plus className="w-3.5 h-3.5" /> Agregar
          </button>
        )}
      </div>

      {isLoading && <Cargando texto="Cargando alergias…" />}
      {isError && <p className="text-sm text-red-600">No se pudieron cargar las alergias.</p>}

      {!isLoading && !isError && vigentes.length === 0 && !abierto && (
        <p className="text-sm text-gray-500 italic">Sin alergias registradas.</p>
      )}

      {vigentes.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {vigentes.map((a: Allergy) => {
            const c = severidadColor(a.severity)
            return (
              <div
                key={a.id}
                className="inline-flex items-center gap-2 rounded-full pl-3 pr-2 py-1.5"
                style={{ background: c.bg, border: `1px solid ${c.border}` }}
              >
                <span className="text-sm font-semibold" style={{ color: c.color }}>{a.substance}</span>
                {a.severity_display && (
                  <span className="text-[11px] font-medium" style={{ color: c.color }}>· {a.severity_display}</span>
                )}
                {a.reaction && <span className="text-[11px] text-gray-500">· {a.reaction}</span>}
                {puedeEditar && (
                  <button
                    type="button"
                    title="Resolver alergia"
                    onClick={() => resolver.mutate(a.id)}
                    disabled={resolver.isPending}
                    className="w-5 h-5 rounded-full flex items-center justify-center hover:bg-white/60 transition-colors disabled:opacity-50"
                  >
                    <X className="w-3.5 h-3.5" style={{ color: c.color }} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Formulario de alta */}
      {abierto && puedeEditar && (
        <div className="mt-4 rounded-xl p-4 bg-white/70 space-y-3">
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="grid gap-3" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <div>
              <label className="label">Sustancia / alérgeno</label>
              <input
                className="input" value={form.substance}
                onChange={e => setForm(f => ({ ...f, substance: e.target.value }))}
                placeholder="Ej. Penicilina"
              />
            </div>
            <div>
              <label className="label">Severidad</label>
              <select
                className="input" value={form.severity}
                onChange={e => setForm(f => ({ ...f, severity: e.target.value as AllergySeverity }))}
              >
                {SEVERITY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="label">Reacción (opcional)</label>
            <input
              className="input" value={form.reaction}
              onChange={e => setForm(f => ({ ...f, reaction: e.target.value }))}
              placeholder="Ej. Urticaria generalizada"
            />
          </div>
          <div className="flex gap-2 justify-end">
            <button type="button" onClick={() => { setAbierto(false); setError('') }} className="btn-secondary text-xs px-3 py-1.5">
              Cancelar
            </button>
            <button
              type="button" onClick={guardar} disabled={crear.isPending}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-white px-3 py-1.5 rounded-lg disabled:opacity-60"
              style={{ background: '#C9A227' }}
            >
              {crear.isPending ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Guardando…</> : 'Guardar alergia'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
