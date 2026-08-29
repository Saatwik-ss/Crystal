/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        gray: {
          950: '#0d0d0d',
          900: '#141414',
          850: '#161616',
          800: '#181818',
          750: '#1f1f1f',
          700: '#252526',
          650: '#2a2a2b',
          600: '#333333',
          500: '#525252',
          400: '#9ca3af',
          300: '#d1d5db',
          200: '#e5e7eb',
          100: '#f3f4f6',
        }
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}