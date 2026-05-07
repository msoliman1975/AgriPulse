import i18n from "i18next";
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
      },
      lng: language,
      fallbackLng: "en",
      defaultNS: "common",
      ns: ["common", "auth", "farms", "imagery", "indices", "weather"],
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
    initialized = true;
  }
  await i18n.changeLanguage(language);
  document.documentElement.setAttribute("lang", language);
  document.documentElement.setAttribute("dir", language === "ar" ? "rtl" : "ltr");
}
