/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // "Obsidian terminal" — layered near-black with a blue-violet undertone.
        bg: "#05070E",
        surface: "#0A0E18",
        panel: "#0C1220",
        panelBorder: "#1A2333",
        // Signature accent (cyan/teal) — used sparingly for live/interactive cues.
        accent: {
          DEFAULT: "#22D3EE",
          muted: "#0E7490",
          soft: "#0b2f38",
        },
        up: "#34D399", // gains (emerald)
        down: "#FB7185", // losses (rose)
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        mono: [
          '"JetBrains Mono"',
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      boxShadow: {
        panel:
          "inset 0 1px 0 0 rgba(255,255,255,0.04), 0 10px 30px -16px rgba(0,0,0,0.7)",
        glow: "0 0 0 1px rgba(34,211,238,0.30), 0 0 22px -6px rgba(34,211,238,0.45)",
      },
      keyframes: {
        "pulse-dot": {
          "0%,100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.4", transform: "scale(0.85)" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-dot": "pulse-dot 1.8s ease-in-out infinite",
        "fade-in": "fade-in 0.25s ease-out",
      },
    },
  },
  plugins: [],
};
