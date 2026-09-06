/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Neutral dark base with clear elevation steps (Hermes/Cursor-class:
        // near-black canvas, each surface a visible step lighter than the one
        // below, secondary text stays readable). Surfaces are chromatically
        // neutral with only a hair of cool -- deliberately NOT the old
        // teal-charcoal undertone, which combined with the gold accent read as
        // "olive/retro." Neutralizing the surfaces is what removes the olive.
        bg: "#0f1113", panel: "#181a1d", panel2: "#22262b",
        edge: "#2c3036", edge2: "#3b4046",
        // Neutral cool-grey text: no green tint, no clinical white.
        txt: "#ececef", muted: "#9aa1ab", faint: "#8b919a",
        // Accent: a refined amber kept as the product's identity mark. On a
        // neutral base it reads as intentional warmth, not olive.
        accent: "#e0a45a", accent2: "#23262b",
        // Status hues: legible on the neutral base without the teal lean.
        good: "#4ec08a", warn: "#e0a94e", risk: "#e0796b",
      },
      fontFamily: {
        sans: ["-apple-system","BlinkMacSystemFont","Segoe UI","Roboto","sans-serif"],
        mono: ["ui-monospace","SFMono-Regular","Menlo","monospace"],
      },
    },
  },
  plugins: [],
}
