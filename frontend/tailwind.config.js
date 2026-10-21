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
        // Warm graphite neutrals: tinted toward the signal hue, never pure grey.
        ink: {
          50: '#f4f3ee',
          100: '#e7e5dc',
          200: '#d0cdc0',
          300: '#b3b0a2',
          400: '#908d80',
          500: '#6e6c61',
          600: '#525047',
          700: '#3b3a34',
          800: '#2b2a26',
          850: '#22211e',
          900: '#1a1a17',
          950: '#121210',
        },
        // Control-room signal accent (yellow-green, hue ~75deg).
        signal: {
          200: '#eef8b8',
          300: '#e1f28a',
          400: '#d2ea5c',
          500: '#bcd630',
          600: '#98ad1f',
          700: '#6f7f16',
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
