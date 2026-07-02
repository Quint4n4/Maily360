/**
 * VerificarRecetaPage — pantalla PÚBLICA de verificación de autenticidad (F5).
 *
 * Se abre al escanear el QR de una receta: GET verificar-receta/<id>/?sig=<token>.
 * Es pública (sin login, fuera de RequireAuth). Confirma que la receta es
 * genuina mostrando SOLO datos no sensibles (folio, estado, fecha, médico +
 * cédula, clínica). Por privacidad (NOM-024 / LFPDPPP) NUNCA muestra datos del
 * paciente, medicamentos ni diagnóstico. Mismo lenguaje visual dorado que las
 * recetas.
 */

import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { CircleCheck, CircleX, Ban, Loader2, Stethoscope, ShieldCheck } from 'lucide-react'
import { verificarReceta, type PrescriptionVerifyResult } from '../api/recetas'

type Fase = 'cargando' | 'ok' | 'error'

const ORO = '#9A7B1E'
const ORO_CLARO = '#C9A227'

function formatoFecha(iso: string): string {
  // "2026-07-01" o "2026-07-01T..." → "01/07/2026"
  const soloFecha = iso.slice(0, 10)
  const [a, m, d] = soloFecha.split('-')
  return d && m && a ? `${d}/${m}/${a}` : iso
}

export default function VerificarRecetaPage() {
  const { id } = useParams<{ id: string }>()
  const [params] = useSearchParams()
  const sig = params.get('sig') ?? ''
  const [fase, setFase] = useState<Fase>('cargando')
  const [data, setData] = useState<PrescriptionVerifyResult | null>(null)

  useEffect(() => {
    let cancelado = false
    if (!id || !sig) {
      setFase('error')
      return
    }
    verificarReceta(id, sig)
      .then((r) => {
        if (!cancelado) {
          setData(r)
          setFase('ok')
        }
      })
      .catch(() => {
        if (!cancelado) setFase('error')
      })
    return () => {
      cancelado = true
    }
  }, [id, sig])

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center p-4"
      style={{ background: 'linear-gradient(135deg, #b89a52 0%, #d8c690 45%, #f1e8cf 100%)' }}
    >
      <div className="w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden">
        <div className="h-2" style={{ background: `linear-gradient(90deg, ${ORO}, ${ORO_CLARO})` }} />
        <div className="px-6 py-7 sm:px-8">
          {fase === 'cargando' && <Cargando />}
          {fase === 'error' && <ErrorView />}
          {fase === 'ok' && data && <Resultado data={data} />}
        </div>
        <div
          className="px-6 py-3 text-[11px] leading-snug text-gray-400 border-t border-gray-100 text-center"
        >
          Verificación de autenticidad · Maily360. Por privacidad (NOM-004 / NOM-024)
          no se muestran datos del paciente ni medicamentos.
        </div>
      </div>
    </div>
  )
}

function Cargando() {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-gray-500">
      <Loader2 className="animate-spin" size={34} style={{ color: ORO_CLARO }} />
      <p className="text-sm">Verificando receta…</p>
    </div>
  )
}

function ErrorView() {
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <div className="rounded-full p-3" style={{ background: '#FEECEC' }}>
        <CircleX size={40} className="text-red-600" />
      </div>
      <h1 className="text-lg font-bold text-gray-800">No se pudo verificar</h1>
      <p className="text-sm text-gray-500 max-w-xs">
        La receta no existe o el código QR no es válido. Si la recibiste impresa,
        verifica con la clínica que la emitió.
      </p>
    </div>
  )
}

function Fila({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-gray-100 last:border-b-0">
      <span className="text-xs uppercase tracking-wide text-gray-400 pt-0.5">{etiqueta}</span>
      <span className="text-sm font-medium text-gray-800 text-right">{valor}</span>
    </div>
  )
}

function Resultado({ data }: { data: PrescriptionVerifyResult }) {
  const anulada = data.estado === 'anulada'
  return (
    <div>
      {/* Encabezado: clínica + sello de verificación */}
      <div className="text-center mb-5">
        <div className="flex items-center justify-center gap-1.5 mb-1">
          <ShieldCheck size={16} style={{ color: ORO }} />
          <span className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: ORO }}>
            Verificación de receta
          </span>
        </div>
        <h1 className="text-xl font-bold" style={{ color: ORO }}>
          {data.clinica || 'Clínica'}
        </h1>
      </div>

      {/* Estado grande */}
      {anulada ? (
        <div
          className="flex items-center gap-3 rounded-xl px-4 py-3 mb-5"
          style={{ background: '#FEECEC' }}
        >
          <Ban size={28} className="text-red-600 shrink-0" />
          <div>
            <p className="font-bold text-red-700">Receta ANULADA</p>
            <p className="text-xs text-red-600">No debe surtirse: fue cancelada por la clínica.</p>
          </div>
        </div>
      ) : (
        <div
          className="flex items-center gap-3 rounded-xl px-4 py-3 mb-5"
          style={{ background: '#ECFDF3' }}
        >
          <CircleCheck size={28} className="text-emerald-600 shrink-0" />
          <div>
            <p className="font-bold text-emerald-700">Receta auténtica y vigente</p>
            <p className="text-xs text-emerald-600">Emitida por la clínica, firma verificada.</p>
          </div>
        </div>
      )}

      {/* Detalles no sensibles */}
      <div className="rounded-xl px-4 py-1" style={{ background: '#FBF6E8' }}>
        <Fila etiqueta="Folio" valor={`Nº ${data.folio}`} />
        <Fila etiqueta="Fecha de emisión" valor={formatoFecha(data.fecha_emision)} />
        <Fila etiqueta="Médico" valor={data.medico.nombre || '—'} />
        <Fila etiqueta="Cédula profesional" valor={data.medico.cedula_profesional || '—'} />
      </div>

      {/* Controlado (sin exponer qué medicamento) */}
      {data.controlado && (
        <div
          className="mt-4 flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
          style={{ background: '#FEF3C7', color: '#92400E' }}
        >
          <Stethoscope size={16} className="shrink-0" />
          <span>
            Contiene medicamento controlado
            {data.vigencia ? ` · vigente hasta ${formatoFecha(data.vigencia)}` : ''}
          </span>
        </div>
      )}
    </div>
  )
}
