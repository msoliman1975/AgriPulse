import type { ChangeEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { SUPPORTED_LANGUAGES, type SupportedLanguage } from "@/i18n";

export function LanguageToggle(): ReactNode {
  const { i18n, t } = useTranslation("common");

  const onChange = (event: ChangeEvent<HTMLSelectElement>): void => {
    void i18n.changeLanguage(event.target.value);
  };

  const current: SupportedLanguage = (SUPPORTED_LANGUAGES as readonly string[]).includes(
    i18n.resolvedLanguage ?? "",
  )
    ? (i18n.resolvedLanguage as SupportedLanguage)
    : "en";

  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <span className="sr-only">{t("shell.languageToggle")}</span>
      <select
        aria-label={t("shell.languageToggle")}
        value={current}
        onChange={onChange}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
      >
        <option value="en">{t("shell.languageEnglish")}</option>
        <option value="ar">{t("shell.languageArabic")}</option>
      </select>
    </label>
  );
}
