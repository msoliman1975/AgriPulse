/**
 * Two languages, typed catalogues, no i18next: the app has a handful of
 * screens, the same choice Scout made. Arabic is the default (decision 13 of
 * the design), and both languages print Western digits 0-9.
 */
import { ar } from "./locales/ar";
import { en, type MessageKey } from "./locales/en";

export type { MessageKey } from "./locales/en";
export type Lang = "ar" | "en";

const CATALOGUES = { ar, en } as const;
export const LANGS: Lang[] = ["ar", "en"];
export const ENDONYM: Record<Lang, string> = { ar: "العربية", en: "English" };

export function isLang(v: unknown): v is Lang {
  return v === "ar" || v === "en";
}

export function dirOf(lang: Lang): "rtl" | "ltr" {
  return lang === "ar" ? "rtl" : "ltr";
}

export function t(lang: Lang, key: MessageKey, vars: Record<string, string | number> = {}): string {
  let s: string = CATALOGUES[lang][key] ?? en[key];
  for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
  return s;
}

/** Western digits in both languages: the Latin numbering system for Arabic. */
function locale(lang: Lang): string {
  return lang === "ar" ? "ar-EG-u-nu-latn" : "en-GB";
}

export function formatNumber(lang: Lang, n: number, digits = 2): string {
  return new Intl.NumberFormat(locale(lang), { maximumFractionDigits: digits }).format(n);
}

/** ISO date (YYYY-MM-DD) shown as-is: it reads the same in both languages. */
export function formatDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

export function formatDateTime(lang: Lang, ms: number): string {
  return new Intl.DateTimeFormat(locale(lang), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(ms));
}

/** One feddan is 4,200.83 m², the unit Egyptian growers use. */
export const M2_PER_FEDDAN = 4200.83;

export function formatFeddan(lang: Lang, areaM2: number | string): string {
  return `${formatNumber(lang, Number(areaM2) / M2_PER_FEDDAN, 2)} ${t(lang, "unit.feddan")}`;
}

/** Whole years from a planting date to today; null when no date. */
export function treeAgeYears(plantingDate: string | null, today = new Date()): number | null {
  if (!plantingDate) return null;
  const [y, m, d] = plantingDate.slice(0, 10).split("-").map(Number);
  let age = today.getFullYear() - y;
  if (today.getMonth() + 1 < m || (today.getMonth() + 1 === m && today.getDate() < d)) age -= 1;
  return Math.max(age, 0);
}
