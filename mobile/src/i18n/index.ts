/**
 * The locale registry, and the only place that knows which languages exist.
 *
 * **Adding a language** is three lines and one file:
 *   1. `src/i18n/locales/<code>.ts` exporting a complete `Messages`
 *   2. an entry in `LOCALES` below
 *   3. the code in the backend's `app/shared/i18n.py` so it can be stored
 *      against a person
 *
 * Step 3 matters: the API happily storing a language the app has no catalogue
 * for produces a user whose setting silently does nothing.
 *
 * No i18next. The app is a handful of screens, the catalogues are typed, and
 * pulling the web app's stack in would buy plurals and interpolation we do not
 * yet use at the cost of a runtime we would have to configure identically.
 * When the capture form arrives and needs counts, revisit.
 */

import { ar } from "@/i18n/locales/ar";
import { en } from "@/i18n/locales/en";
import type { LocaleDef, MessageKey } from "@/i18n/types";

export type { MessageKey } from "@/i18n/types";

export const LOCALES = {
  ar: { code: "ar", endonym: "العربية", dir: "rtl", messages: ar },
  en: { code: "en", endonym: "English", dir: "ltr", messages: en },
} as const satisfies Record<string, LocaleDef>;

export type Lang = keyof typeof LOCALES;

export const LANGS = Object.keys(LOCALES) as Lang[];

/** Arabic first: this app is for the field, not the office. */
export const DEFAULT_LANG: Lang = "ar";

export function isLang(value: unknown): value is Lang {
  return typeof value === "string" && value in LOCALES;
}

export function dirOf(lang: Lang): "rtl" | "ltr" {
  return LOCALES[lang].dir;
}

/**
 * Look up a string. Falls back to English rather than rendering the key: the
 * types make a gap impossible in this repo, but a catalogue could still arrive
 * incomplete from a future translation pipeline, and a scout should see a
 * usable word instead of `visits.claim`.
 */
export function t(lang: Lang, key: MessageKey): string {
  return LOCALES[lang].messages[key] ?? en[key];
}

/**
 * "18h" / "2d" / overdue — the countdown the visit ring shows.
 *
 * Rounds rather than floors, for the same reason the push copy does: a visit
 * raised with within_hours=24 is a moment short of 24h by the time it renders,
 * and "23h" reads as if the scout has already lost an hour.
 */
export function dueIn(lang: Lang, dueBy: string | null): string {
  if (!dueBy) return "";
  const ms = new Date(dueBy).getTime() - Date.now();
  if (ms < 0) return t(lang, "due.overdue");
  const hours = Math.round(ms / 3_600_000);
  return hours < 48 ? `${Math.max(hours, 1)}h` : `${Math.round(hours / 24)}d`;
}
