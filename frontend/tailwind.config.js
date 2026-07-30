/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        predict: {
          50: '#f0f7ff',
          100: '#e0effe',
          200: '#bbddfd',
          300: '#7bc2fc',
          400: '#38a3f7',
          500: '#0e87eb',
          600: '#0069c9',
          700: '#0254a3',
          800: '#064885',
          900: '#0a3d6e',
        },
      },
    },
  },
  plugins: [],
}