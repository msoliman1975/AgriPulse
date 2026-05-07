import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import enCommon from "./locales/en/common.json";
import enAuth from "./locales/en/auth.json";
import enFarms from "./locales/en/farms.json";
import enImagery from "./locales/en/imagery.json";
import enIndices from "./locales/en/indices.json";
import enWeather from "./locales/en/weather.json";
import arCommon from "./locales/ar/common.json";
import arAuth from "./locales/ar/auth.json";
import arFarms from "./locales/ar/farms.json";
import arImagery from "./locales/ar/imagery.json";
import arIndices from "./locales/ar/indices.json";
import arWeather from "./locales/ar/weather.json";

export type SupportedLanguage = "en" | "ar";

export const SUPPORTED_LANGUAGES: readonly SupportedLanguage[] = ["en", "ar"];
export const DEFAULT_LANGUAGE: SupportedLanguage = "en";

// Per ARCHITECTURE.md § 11, the frontend ships with two locales (en, ar)
// loaded eagerly at this scope (the bundle is small). Future modules add
// their own namespaces lazily via i18next-http-backend.
const resources = {
  en: {
    common: enCommon,
    auth: enAuth,
    farms: enFarms,
    imagery: enImagery,
    indices: enIndices,
    weather: enWeather,
  },
  ar: {
    common: arCommon,
    auth: arAuth,
    farms: arFarms,
    imagery: arImagery,
    indices: arIndices,
    weather: arWeather,
  },
} as const;

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: DEFAULT_LANGUAGE,
    supportedLngs: [...SUPPORTED_LANGUAGES],
    defaultNS: "common",
    ns: ["common", "auth", "farms", "imagery", "indices", "weather"],
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator", "htmlTag"],
      caches: ["localStorage"],
      lookupLocalStorage: "missionagre.lang",
    },
    react: { useSuspense: false },
  });

/**
 * Apply the current language to <html lang> and <html dir>. Called at
 * startup and on every language change. RTL is inferred from the locale
 * rather than hard-coded so additional RTL languages slot in cleanly.
 */
function syncHtmlAttributes(language: string): void {
  const root = document.documentElement;
  root.setAttribute("lang", language);
  root.setAttribute("dir", language === "ar" ? "rtl" : "ltr");
}

i18n.on("languageChanged", syncHtmlAttributes);
syncHtmlAttributes(i18n.language || DEFAULT_LANGUAGE);

export default i18n;
