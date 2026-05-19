/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{astro,html,js,ts,md,mdx}"],
  theme: {
    extend: {
      colors: {
        leaf: {
          50: "#f1faf6",
          100: "#dcf1e6",
          200: "#b5e0c8",
          300: "#7fc7a4",
          400: "#3eae7c",
          500: "#1d9e75",
          600: "#0f8d63",
          700: "#0f6e56",
          800: "#085041",
          900: "#04342c",
        },
        pulse: { DEFAULT: "#e24b4a", soft: "#fbe1e0" },
        ink: { DEFAULT: "#1f2420", soft: "#2c2c2a" },
        muted: { DEFAULT: "#6c7268", soft: "#9aa097" },
        sand: { 50: "#fbfaf5", 100: "#f7f6f1", 200: "#efeee6", 300: "#e8e5db" },
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "system-ui",
          "sans-serif",
        ],
        display: [
          "Inter",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "system-ui",
          "sans-serif",
        ],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(0,0,0,.04), 0 6px 18px rgba(20,40,15,.06)",
        card: "0 1px 3px rgba(0,0,0,.05), 0 12px 32px rgba(20,40,15,.08)",
      },
      maxWidth: { content: "1180px" },
    },
  },
  plugins: [],
};
