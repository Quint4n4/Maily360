/**
 * Logotipo oficial de Maily.
 *
 * Un único sitio para la marca: si mañana cambia el archivo, cambia aquí y en
 * ningún otro lado. Antes el logotipo estaba escrito a mano como texto en tres
 * componentes distintos ("maily" + un "360" dorado), que además no es lo que
 * dice el logotipo oficial.
 *
 * Los archivos viven en `public/marca/`. Si falta alguno, en vez de mostrar una
 * imagen rota en la barra superior se cae al nombre en texto: un logotipo que no
 * carga no debería dejar la app sin identificar.
 *
 * NOTA sobre el color: el logotipo es multicolor a propósito, y es la ÚNICA
 * pieza multicolor de la interfaz. No tomar sus colores para botones o badges —
 * el sistema se sostiene sobre "el color marca estado, nunca categoría", y el
 * logo destaca justamente porque todo lo demás alrededor es sobrio.
 */

import { useState } from 'react'

type Variante = 'horizontal' | 'isotipo' | 'vertical'

/*
 * OJO con `vertical`: ese archivo trae la palabra "maily" en BLANCO (pensado
 * para fondos oscuros), así que sobre superficies claras solo se ve el
 * hexágono. Para fondo claro usar `horizontal`, cuyo wordmark es gris.
 */
const ARCHIVO: Record<Variante, string> = {
  horizontal: '/marca/maily-horizontal.png',
  isotipo:    '/marca/maily-isotipo.png',
  vertical:   '/marca/maily-vertical.png',
}

export default function MarcaMaily({
  variante = 'horizontal',
  className = 'h-8',
}: {
  variante?: Variante
  /** Controla el TAMAÑO (alto). El ancho se ajusta solo. */
  className?: string
}) {
  const [sinArchivo, setSinArchivo] = useState(false)

  if (sinArchivo) {
    return (
      <span className="text-xl font-bold tracking-tight text-tinta select-none">maily</span>
    )
  }

  return (
    <img
      src={ARCHIVO[variante]}
      alt="Maily"
      onError={() => setSinArchivo(true)}
      className={`w-auto object-contain select-none ${className}`}
      draggable={false}
    />
  )
}
