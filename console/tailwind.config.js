/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // WSD trader palette — the consoles sit one click apart in the portal, so a second green would
        // read as a second product. DEFAULT / fg / 50 / 100 / 600 / 700 are mm-trading-dash's own
        // values; the rest fill the ramp so the rungs this console already used (tints for notices, a
        // mid rung for active tabs) keep their contrast instead of collapsing onto one green.
        brand: {
          DEFAULT: "#1e7f53",
          fg: "#ffffff",
          50: "#e9f6ef",
          100: "#c9e9d8",
          200: "#a2d9bd",
          300: "#72c39d",
          400: "#43a87c",
          500: "#2a8f63",
          600: "#1e7f53",
          700: "#186540",
          800: "#144f33",
          900: "#103f29",
          950: "#0a2618",
        },
      },
      fontFamily: {
        // Inter ahead of `system-ui`, which otherwise wins and renders SF Pro — whose thin small sizes
        // are what made the estate's 10–12px chrome unreadable. Both faces self-hosted (see index.css).
        sans: [
          "Inter Variable",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono Variable",
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
};
