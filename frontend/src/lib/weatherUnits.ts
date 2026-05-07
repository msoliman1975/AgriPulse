// Weather unit conversion + formatting. Backend always returns canonical
// SI units (°C, mm, m/s, hPa); these helpers convert at the view layer
// based on the user's `weatherUnit` preference.

import type { WeatherUnitSystem } from "@/prefs/PrefsContext";

const C_TO_F = (c: number): number => (c * 9) / 5 + 32;
const MM_TO_IN = (mm: number): number => mm / 25.4;
const MS_TO_MPH = (ms: number): number => ms * 2.236936;
const HPA_TO_INHG = (hpa: number): number => hpa * 0.02953;

function toNumber(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export interface FormattedTemp {
  display: string;
  unit: string;
}

export function formatTemp(
  c: string | number | null | undefined,
  system: WeatherUnitSystem,
  options: { decimals?: number; emptyDash?: string } = {},
): FormattedTemp {
  const dash = options.emptyDash ?? "—";
  const n = toNumber(c);
  if (n === null) return { display: dash, unit: system === "metric" ? "°C" : "°F" };
  const value = system === "metric" ? n : C_TO_F(n);
  return {
    display: `${value.toFixed(options.decimals ?? 0)}°`,
    unit: system === "metric" ? "°C" : "°F",
  };
}

export function formatPrecip(
  mm: string | number | null | undefined,
  system: WeatherUnitSystem,
  options: { emptyDash?: string } = {},
): string {
  const dash = options.emptyDash ?? "—";
  const n = toNumber(mm);
  if (n === null) return dash;
  if (system === "metric") return `${n.toFixed(1)} mm`;
  return `${MM_TO_IN(n).toFixed(2)} in`;
}

export function formatProbability(
  pct: string | number | null | undefined,
  options: { emptyDash?: string } = {},
): string {
  const dash = options.emptyDash ?? "—";
  const n = toNumber(pct);
  if (n === null) return dash;
  return `${Math.round(n)}%`;
}

export function formatWindSpeed(
  ms: string | number | null | undefined,
  system: WeatherUnitSystem,
): string {
  const n = toNumber(ms);
  if (n === null) return "—";
  if (system === "metric") return `${n.toFixed(1)} m/s`;
  return `${MS_TO_MPH(n).toFixed(1)} mph`;
}

export function formatPressure(
  hpa: string | number | null | undefined,
  system: WeatherUnitSystem,
): string {
  const n = toNumber(hpa);
  if (n === null) return "—";
  if (system === "metric") return `${n.toFixed(0)} hPa`;
  return `${HPA_TO_INHG(n).toFixed(2)} inHg`;
}
