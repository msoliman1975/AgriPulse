/**
 * Locale-aware date formatting for chart axes and tooltips.
 *
 * Dates localize their month names and ordering to the active UI language
 * (Arabic uses day/month order + Arabic month names). Per ARCHITECTURE.md
 * § 11 the Arabic UI keeps **Western numerals (0–9)** by default, so we use
 * the `ar-u-nu-latn` BCP-47 locale (Arabic language, Latin numbering system)
 * rather than plain `ar` — that would emit Arabic-Indic digits (١٢٣). Numeric
 * *value* axes are not localized here at all; the app renders data numbers in
 * Western digits everywhere (tables, KPI tiles).
 *
 * Build these inside a `useMemo` keyed on `i18n.language` so the axis
 * re-formats when the user switches language.
 */
export function chartDateLocale(lang: string | undefined): string {
  return lang === "ar" ? "ar-u-nu-latn" : "en-US";
}

/** Terse day/month tick for time axes (e.g. "4/6" / "٦/٤"). */
export function makeDateTickFmt(lang: string | undefined): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(chartDateLocale(lang), {
    month: "numeric",
    day: "numeric",
  });
}

/** Fuller date for tooltips (e.g. "Apr 6, 2026" / "٦ أبريل ٢٠٢٦"). */
export function makeDateLabelFmt(lang: string | undefined): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(chartDateLocale(lang), {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
