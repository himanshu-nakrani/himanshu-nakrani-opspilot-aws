/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'ui-sans-serif', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        // Cool graphite neutrals with a faint blue cast. No pure greys, no pure black.
        ink: {
          50: '#f3f4f6',
          100: '#e3e5e9',
          200: '#c7cad1',
          300: '#a3a8b2',
          400: '#848a96',
          500: '#757b88',
          600: '#4a4f5a',
          700: '#363a43',
          800: '#272a31',
          850: '#1e2127',
          900: '#17191e',
          950: '#0e0f12',
        },
        // Interaction accent: focus, selection, active filter. Never used for status.
        signal: {
          200: '#d6e2ff',
          300: '#b3c8ff',
          400: '#8eabff',
          500: '#6d8df5',
          600: '#5371dc',
          700: '#3e58b0',
        },
        // Healthy / verified. Only ever means "this is fine".
        ok: {
          300: '#86dfab',
          400: '#52cc88',
          500: '#33b06c',
        },
      },
      fontSize: {
        '2xs': ['11px', { lineHeight: '16px' }],
      },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'rise-in': { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        'slide-in': { from: { transform: 'translateX(100%)' }, to: { transform: 'translateX(0)' } },
        'pulse-dot': { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.35' } },
      },
      animation: {
        'fade-in': 'fade-in 150ms ease-out',
        'rise-in': 'rise-in 220ms cubic-bezier(0.2, 0.7, 0.2, 1) both',
        'slide-in': 'slide-in 200ms cubic-bezier(0.2, 0.7, 0.2, 1)',
        'pulse-dot': 'pulse-dot 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
