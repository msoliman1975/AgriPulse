import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enCommon from "./locales/en/common.json";
import enAuth from "./locales/en/auth.json";
import arCommon from "./locales/ar/common.json";
import arAuth from "./locales/ar/auth.json";

/**
 * Test-only i18n bootstrap. Identical resources to the production
 * `./index.ts`, minus the LanguageDetector — tests pin a language
 * explicitly so render assertions are deterministic.
 */
let initialized = false;

export async function setupTestI18n(language: "en" | "ar" = "en"): Promise<void> {
  if (!initialized) {
    await i18n.use(initReactI18next).init({
      resources: {
        en: { common: enCommon, auth: enAuth },
        ar: { common: arCommon, auth: arAuth },
      },
      lng: language,
      fallbackLng: "en",
      defaultNS: "common",
      ns: ["common", "auth"],
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
    initialized = true;
  }
  await i18n.changeLanguage(language);
  document.documentElement.setAttribute("lang", language);
  document.documentElement.setAttribute("dir", language === "ar" ? "rtl" : "ltr");
}
