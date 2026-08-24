/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Professional dark trading dashboard palette (§58).
        surface: {
          950: '#0a0d12',
          900: '#0f141b',
          850: '#141b24',
          800: '#1a222d',
          700: '#243040',
          600: '#33445a',
        },
        accent: '#38bdf8',
        bullish: '#22c55e',
        bearish: '#ef4444',
        caution: '#f59e0b',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
