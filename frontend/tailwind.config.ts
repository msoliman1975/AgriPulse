import type { Config } from "tailwindcss";
import tailwindRtl from "tailwindcss-rtl";

// Design tokens.
//
// AgriPulse's palette is intentionally muted: dark green primary for
// agronomic association, sand tones for surfaces (Egypt context), neutral
// slates for text. Tokens are defined here as Tailwind extensions so they
// can be used uniformly via class names; raw CSS uses CSS variables in
// src/styles/tokens.css.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand
        brand: {
          50: "#f1f7f3",
          100: "#dcecdf",
          200: "#bcd9c2",
          300: "#92be9c",
          400: "#629d75",
          500: "#3f7d57",
          600: "#2f6243",
          700: "#274e36",
          800: "#22402d",
          900: "#1c3525",
          950: "#0f1d14",
        },
        // Sand surfaces
        sand: {
          50: "#fbf8f1",
          100: "#f5efde",
          200: "#ebdfbb",
          300: "#dec78d",
          400: "#cea95c",
          500: "#bf913e",
          600: "#a47832",
          700: "#825c2c",
          800: "#6b4a29",
          900: "#5a3e26",
        },
        // AgriPulse semantic tokens (UX_SPEC.md Â§9). Coexist with brand/sand;
        // pages built against the new IA prefer `ap.*` for surface,
        // semantic, activity-type, and growth-stage colors.
        ap: {
          bg: "#f7f6f1",
          panel: "#ffffff",
          line: "#e8e5db",
          ink: "#1f2420",
          muted: "#6c7268",
          primary: "#356b30",
          "primary-soft": "#dceadb",
          good: "#4f8e4a",
          accent: "#1f6f9a",
          warn: "#c98a18",
          "warn-soft": "#f7e7c2",
          crit: "#b24430",
          "crit-soft": "#f3d2c9",
          plant: "#4f8e4a",
          fert: "#1f6f9a",
          spray: "#8d4ab0",
          prune: "#c98a18",
          harv: "#b24430",
          irrig: "#2a8a9c",
          "stage-flow": "#f0c75b",
          "stage-frset": "#b8d4a3",
          "stage-frdev": "#84b078",
          "stage-ripen": "#d6a546",
          "stage-harv": "#c46b50",
          "stage-post": "#cfd1ca",
        },
      },
      fontFamily: {
        // Falls back to OS UI fonts; Arabic-friendly fonts come in last so
        // both scripts render with consistent metrics.
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Cairo",
          "Tahoma",
          "Arial",
          "sans-serif",
        ],
      },
      // Soft elevation matching agronomic-app feel.
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)",
      },
    },
  },
  // tailwindcss-rtl rewrites *-l/*-r utilities into logical *-s/*-e where
  // appropriate so dir="rtl" mirrors automatically. We still prefer logical
  // utility classes (`ms-`, `me-`, `ps-`, `pe-`) where Tailwind ships them
  // natively (Tailwind 3.3+).
  plugins: [tailwindRtl],
} satisfies Config;
