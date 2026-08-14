/** @type {import('tailwindcss').Config} */

/*
 * ─────────────────────────────────────────────────────────────────────────────
 * SISTEMA DE COLOR DE MAILY360
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * Regla única que sostiene todo: EL COLOR MARCA ESTADO, NUNCA CATEGORÍA.
 *   · "cancelada", "vencido", "alergia"  → estado   → color semántico.
 *   · "Edad", "Sexo", "Escolaridad"      → categoría → todos en `suave`.
 *
 * Los tres papeles están separados a propósito (antes el oro hacía los tres a
 * la vez, y por eso nada destacaba):
 *   · `marca`   = identidad. Logo, login, membretes de PDF, sello VIP.
 *   · `accion`  = lo que se puede pulsar. Botones, enlaces, ítem activo.
 *   · estados   = éxito / aviso / peligro. Cerrados: no se inventan colores fuera.
 *
 * Todos los valores están medidos contra WCAG 2.1 AA sobre `fondo` (#F6FAFD),
 * que es el peor caso por ser más oscuro que el blanco:
 *
 *   tinta   #0A1931  16.73    cuerpo  #22303F  12.81    suave  #4A5567  7.18
 *   tenue   #5F6B7D   5.15    accion  #1A3D63  10.58    exito  #1F6E47  5.92
 *   aviso   #856404   5.24    peligro #B3261E   6.23
 *
 * Dos tokens NO alcanzan para texto y por eso llevan nombre propio, para que no
 * se usen por error (los gráficos solo exigen 3:1, el texto exige 4.5:1):
 *
 *   marca       #C9A227  2.31 → SOLO relleno y marca. Nunca texto sobre claro.
 *   aviso-icono #B8860B  3.10 → SOLO iconos. El texto de un aviso va en `aviso`.
 *
 * Se EXTIENDE la paleta de Tailwind en vez de reemplazarla: la migración es
 * vista por vista y los archivos aún sin migrar siguen usando gray-*, red-*, etc.
 */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        /* ── Marca (identidad) ────────────────────────────────────────────── */
        'marca':            '#C9A227',
        'marca-oscuro':     '#A8871F',
        'marca-tinte':      '#FBF3D9',
        'marca-borde':      '#EBD9A0',

        /* ── Acción (lo pulsable) ─────────────────────────────────────────── */
        'accion':           '#1A3D63',
        'accion-hover':     '#0A1931',
        'accion-tinte':     '#EEF4FA',
        'accion-borde':     '#B3CFE5',

        /* ── Texto ────────────────────────────────────────────────────────── */
        'tinta':            '#0A1931',   // títulos
        'cuerpo':           '#22303F',   // texto normal
        'suave':            '#4A5567',   // secundario (etiquetas de campo)
        'tenue':            '#5F6B7D',   // terciario — el más claro que aún pasa AA

        /* ── Superficies ──────────────────────────────────────────────────── */
        'fondo':            '#F6FAFD',   // fondo de página (plano, sin imagen)
        'superficie':       '#FFFFFF',   // tarjetas
        'superficie-sutil': '#F1F6FB',   // filas alternas, encabezados de tabla
        'borde':            '#E3EAF2',
        'borde-fuerte':     '#4A7FA7',   // iconos y bordes con énfasis (3:1)

        /* ── Estados ──────────────────────────────────────────────────────── */
        'exito':            '#1F6E47',
        'exito-tinte':      '#E7F6EE',
        'exito-borde':      '#B7E0C9',

        'aviso':            '#856404',   // texto del aviso
        'aviso-icono':      '#B8860B',   // solo iconos (3.10)
        'aviso-tinte':      '#FEF6E0',
        'aviso-borde':      '#F0D48A',

        'peligro':          '#B3261E',
        'peligro-hover':    '#8C1D18',
        'peligro-tinte':    '#F9DEDC',
        'peligro-borde':    '#F1B9B4',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        /* Sombras frías, alineadas con la tinta azul (antes eran cálidas por el oro). */
        'card':      '0 1px 2px rgba(10,25,49,0.06), 0 4px 12px rgba(10,25,49,0.05)',
        'card-alto': '0 2px 4px rgba(10,25,49,0.07), 0 12px 28px rgba(10,25,49,0.08)',
        'accion':    '0 4px 14px rgba(26,61,99,0.22)',
        'accion-lg': '0 8px 24px rgba(26,61,99,0.28)',
      },
      animation: {
        'fade-in-up': 'fadeInUp 0.5s ease-out forwards',
        'fade-in':    'fadeIn 0.3s ease-out forwards',
      },
      keyframes: {
        fadeInUp: {
          '0%':   { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)'    },
        },
        fadeIn: {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
