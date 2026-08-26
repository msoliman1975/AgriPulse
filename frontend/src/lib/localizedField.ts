/**
 * Pick the locale-appropriate variant of a bilingual backend field.
 *
 * Many domain rows (alerts, recommendations) carry parallel `*_en` / `*_ar`
 * columns written at generation time. Since the Arabic-names work, the named
 * entities carry the same pair as `name` / `name_ar`. Prefer the Arabic text
 * when the UI is in Arabic, falling back to English when the Arabic variant
 * wasn't authored (older rows, English-only rules).
 *
 * An empty or whitespace-only Arabic value counts as not authored. A form
 * that submits a cleared input sends `""`, and the DB read path uses
 * `COALESCE(NULLIF(name_ar, ''), name)` for the same reason: a blank string
 * would render an empty name rather than fall back.
 *
 * Pass `i18n.language` from `useTranslation()` in React components so the
 * value re-renders on language change; module code can pass the singleton's
 * `i18n.language`.
 */
export function localizedField(
  lang: string | undefined,
  en: string | null,
  ar: string | null | undefined,
): string | null {
  if (lang !== "ar") return en;
  return ar !== null && ar !== undefined && ar.trim() !== "" ? ar : en;
}

/**
 * `localizedField` for a name that always has an English value.
 *
 * Entity names (farm, block, resource, plan, signal) are non-null on the
 * English side, so the caller wants a string, not `string | null`. Blocks are
 * the one case where even the English name may be absent — pass the code as
 * `en` there, which is what the block screens already show.
 */
export function localizedName(
  lang: string | undefined,
  en: string,
  ar: string | null | undefined,
): string {
  return localizedField(lang, en, ar) ?? en;
}
