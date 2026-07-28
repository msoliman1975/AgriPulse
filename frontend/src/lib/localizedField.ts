/**
 * Pick the locale-appropriate variant of a bilingual backend field.
 *
 * Many domain rows (alerts, recommendations) carry parallel `*_en` / `*_ar`
 * columns written at generation time. Prefer the Arabic text when the UI is
 * in Arabic, falling back to English when the Arabic variant wasn't authored
 * (older rows, English-only rules).
 *
 * Pass `i18n.language` from `useTranslation()` in React components so the
 * value re-renders on language change; module code can pass the singleton's
 * `i18n.language`.
 */
export function localizedField(
  lang: string | undefined,
  en: string | null,
  ar: string | null,
): string | null {
  return lang === "ar" ? (ar ?? en) : en;
}
