import { ar, enUS, type Locale } from "date-fns/locale";
import { useTranslation } from "react-i18next";

/**
 * Resolve the date-fns ``Locale`` matching the active i18n language.
 *
 * Wraps ``react-i18next`` so callers can pass the locale to
 * ``formatDistanceToNow`` / ``format`` and get translated relative
 * times ("منذ ساعة" instead of "an hour ago"). New languages add a
 * branch here; defaulting to ``enUS`` is intentional so a missing
 * translation never crashes the page.
 */
export function useDateLocale(): Locale {
  const { i18n } = useTranslation();
  return i18n.language === "ar" ? ar : enUS;
}
