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
          750: '#1e293b',
        }
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}