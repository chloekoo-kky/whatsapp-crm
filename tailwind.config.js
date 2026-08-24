/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./leads/templates/**/*.html", "./leads/**/*.py"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
