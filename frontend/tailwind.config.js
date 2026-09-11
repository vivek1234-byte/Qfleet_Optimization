/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Full 50-950 ramps. The previous config defined only 50/100/500/600/900,
        // so classes like `hover:bg-primary-700` — which the pages actually used —
        // silently produced no style at all.
        primary: {
          50: '#eff9ff',
          100: '#dcf1ff',
          200: '#b2e5ff',
          300: '#6dd2ff',
          400: '#20bbfd',
          500: '#06a3ee',
          600: '#0082cb',
          700: '#0067a4',
          800: '#055887',
          900: '#0a4970',
          950: '#062e4a',
        },
        eco: {
          50: '#edfcf4',
          100: '#d3f8e3',
          200: '#aaefcc',
          300: '#72e0af',
          400: '#39c98d',
          500: '#15af73',
          600: '#098d5c',
          700: '#06714d',
          800: '#07593e',
          900: '#074934',
          950: '#02291d',
        },
        ink: {
          50: '#f6f7f9',
          100: '#eceef2',
          200: '#d5dae3',
          300: '#b0bacb',
          400: '#8595ae',
          500: '#667794',
          600: '#51607b',
          700: '#424e64',
          800: '#3a4354',
          900: '#343b48',
          950: '#1c212b',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(16 24 40 / 0.04), 0 1px 3px 0 rgb(16 24 40 / 0.06)',
        'card-hover': '0 4px 6px -1px rgb(16 24 40 / 0.08), 0 2px 4px -2px rgb(16 24 40 / 0.06)',
        pop: '0 12px 32px -8px rgb(16 24 40 / 0.18)',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'none' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.25s ease-out both',
        shimmer: 'shimmer 1.6s infinite',
      },
      screens: {
        '3xl': '1800px',
      },
    },
  },
  plugins: [],
}
