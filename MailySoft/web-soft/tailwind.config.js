/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        'teal':    '0 4px 14px rgba(13,148,136,0.25)',
        'teal-lg': '0 8px 24px rgba(13,148,136,0.30)',
        'card':    '0 0 0 1px rgba(0,0,0,0.05), 0 2px 8px rgba(0,0,0,0.06)',
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
