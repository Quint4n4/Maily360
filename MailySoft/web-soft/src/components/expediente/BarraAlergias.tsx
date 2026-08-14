/**
 * Barra de alergias para los flujos donde se PRESCRIBE.
 *
 * Por qué existe: el formulario de receta no mostraba las alergias por ningún
 * lado. Se podía emitir una receta completa sin que el sistema avisara nunca de
 * que el paciente es alérgico, porque las alergias solo vivían en la ficha del
 * expediente y en el libro clínico — otra pantalla.
 *
 * Tres decisiones que no son de estilo:
 *
 *  1. "Sin alergias registradas" NO es lo mismo que "no tiene alergias". Si
 *     nadie las ha capturado, el médico debe saber que está viendo un hueco en
 *     el expediente, no un alta clínica. Por eso el estado vacío lo dice.
 *
 *  2. Si la consulta FALLA, no se muestra el estado vacío. Un error de red
 *     pintado como "sin alergias" es peor que no mostrar nada: afirma algo
 *     falso justo donde más caro sale.
 *
 *  3. El color no viaja solo: cada alergia lleva icono + la palabra "ALERGIAS"
 *     + la severidad en texto. Alrededor de 8% de los hombres no distingue bien
 *     rojo de verde.
 */

import { AlertTriangle, Loader2, ShieldQuestion } from 'lucide-react'
import { useAllergies } from '../../hooks/expediente'
import type { Allergy } from '../../types/expediente'

/**
 * Tono del chip: SIEMPRE rojo, sea cual sea la severidad. Partirlo en dos
 * colores hacía leer "esto es grave / esto no" cuando lo que hay que leer es
 * "este paciente es alérgico". La severidad sigue escrita en el chip.
 */
function tonoSeveridad(_a: Allergy): { bg: string; borde: string; texto: string } {
  return { bg: 'var(--peligro-tinte)', borde: 'var(--peligro-borde)', texto: 'var(--peligro)' }
}

export default function BarraAlergias({ patientId }: { patientId: string }) {
  const { data, isLoading, isError } = useAllergies(patientId)
  const alergias = data ?? []

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-xl px-4 py-2.5 bg-superficie-sutil border border-borde">
        <Loader2 className="w-4 h-4 animate-spin text-suave shrink-0" />
        <span className="text-xs text-suave">Revisando alergias del paciente…</span>
      </div>
    )
  }

  // El fallo se anuncia: nunca se degrada a "sin alergias".
  if (isError) {
    return (
      <div className="flex items-start gap-2.5 rounded-xl px-4 py-3 bg-aviso-tinte border border-aviso-borde">
        <ShieldQuestion className="w-4 h-4 mt-0.5 shrink-0 text-aviso-icono" />
        <p className="text-xs text-aviso">
          <strong>No se pudieron verificar las alergias</strong> de este paciente.
          Consúltalas en el expediente antes de recetar.
        </p>
      </div>
    )
  }

  if (alergias.length === 0) {
    return (
      <div className="flex items-start gap-2.5 rounded-xl px-4 py-2.5 bg-superficie-sutil border border-borde">
        <ShieldQuestion className="w-4 h-4 mt-0.5 shrink-0 text-suave" />
        <p className="text-xs text-suave">
          <strong className="text-cuerpo">Sin alergias registradas.</strong>{' '}
          Que no haya registro no significa que el paciente no tenga alergias: si no se le ha
          preguntado, conviene hacerlo antes de recetar.
        </p>
      </div>
    )
  }

  const haySevera = alergias.some(a => a.severity === 'severa')

  return (
    <div
      className="rounded-xl px-4 py-3 bg-peligro-tinte border border-peligro-borde"
      // `alert` para que un lector de pantalla lo anuncie al entrar al formulario.
      role="alert"
    >
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4 shrink-0 text-peligro" />
        <h4 className="text-xs font-bold uppercase tracking-wide text-peligro">
          Alergias ({alergias.length}){haySevera && ' · incluye una severa'}
        </h4>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {alergias.map(a => {
          const t = tonoSeveridad(a)
          return (
            <span
              key={a.id}
              className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1"
              style={{ background: t.bg, border: `1px solid ${t.borde}` }}
            >
              <AlertTriangle className="w-3 h-3 shrink-0" style={{ color: t.texto }} aria-hidden />
              <span className="text-xs font-semibold" style={{ color: t.texto }}>{a.substance}</span>
              {a.severity_display && (
                <span className="text-[11px]" style={{ color: t.texto }}>· {a.severity_display}</span>
              )}
              {a.reaction && <span className="text-[11px] text-suave">· {a.reaction}</span>}
            </span>
          )
        })}
      </div>
    </div>
  )
}
