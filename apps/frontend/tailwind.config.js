/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // dark-first trading dashboard palette (frontend doc §20.1)
        bg: "#020617", // slate-950
        panel: "#0f172a", // slate-900
        panelBorder: "#1e293b", // slate-800
      },
    },
  },
  plugins: [],
};
