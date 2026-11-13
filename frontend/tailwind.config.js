/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'] },
      colors: { brand: { 400: '#818cf8', 500: '#6366f1', 600: '#4f46e5' } },
    },
  },
  plugins: [],
};
