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
        // AgriPulse semantic tokens (UX_SPEC.md §9). The only palette — the
        // pre-rename `brand.*` and `sand.*` scales were deleted once their
        // last usages went (DS-8). Re-adding a second scale here is how the
        // drift restarts, so don't.
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
      // Type scale as tokens (DS-9). Page titles drifted across text-2xl /
      // xl / lg / base / sm before <PageHeader> centralised them; naming the
      // roles means the scale is a decision you make once, not a number you
      // pick per file. The lint rule stops raw <h1>; these stop the raw size.
      fontSize: {
        "page-title": ["1.5rem", { lineHeight: "2rem", letterSpacing: "-0.015em" }],
        "section-title": ["1.125rem", { lineHeight: "1.75rem" }],
        "card-title": ["0.875rem", { lineHeight: "1.25rem" }],
        meta: ["0.6875rem", { lineHeight: "1rem" }],
      },
      // One card radius. `rounded-xl` and `rounded-lg` both claimed to be
      // "the card" and appeared on the same detail page.
      borderRadius: {
        card: "0.75rem",
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
