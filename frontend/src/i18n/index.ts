import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import enCommon from "./locales/en/common.json";
import enAuth from "./locales/en/auth.json";
import enFarms from "./locales/en/farms.json";
import enImagery from "./locales/en/imagery.json";
import enIndices from "./locales/en/indices.json";
import enWeather from "./locales/en/weather.json";
import enRecommendations from "./locales/en/recommendations.json";
import enSignals from "./locales/en/signals.json";
import enInsights from "./locales/en/insights.json";
import enAlerts from "./locales/en/alerts.json";
import enRules from "./locales/en/rules.json";
import enImageryWeatherConfig from "./locales/en/imageryWeatherConfig.json";
import enUsers from "./locales/en/users.json";
import enAdmin from "./locales/en/admin.json";
import enDecisionTrees from "./locales/en/decisionTrees.json";
import enSettings from "./locales/en/settings.json";
import enIntegrationsHealth from "./locales/en/integrationsHealth.json";
import enIntegrations from "./locales/en/integrations.json";
import arCommon from "./locales/ar/common.json";
import arAuth from "./locales/ar/auth.json";
import arFarms from "./locales/ar/farms.json";
import arImagery from "./locales/ar/imagery.json";
import arIndices from "./locales/ar/indices.json";
import arWeather from "./locales/ar/weather.json";
import arRecommendations from "./locales/ar/recommendations.json";
import arSignals from "./locales/ar/signals.json";
import arInsights from "./locales/ar/insights.json";
import arAlerts from "./locales/ar/alerts.json";
import arRules from "./locales/ar/rules.json";
import arImageryWeatherConfig from "./locales/ar/imageryWeatherConfig.json";
import arUsers from "./locales/ar/users.json";
import arAdmin from "./locales/ar/admin.json";
import arDecisionTrees from "./locales/ar/decisionTrees.json";
import arSettings from "./locales/ar/settings.json";
import arIntegrationsHealth from "./locales/ar/integrationsHealth.json";
import arIntegrations from "./locales/ar/integrations.json";

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
    recommendations: enRecommendations,
    signals: enSignals,
    insights: enInsights,
    alerts: enAlerts,
    rules: enRules,
    imageryWeatherConfig: enImageryWeatherConfig,
    admin: enAdmin,
    decisionTrees: enDecisionTrees,
    users: enUsers,
    settings: enSettings,
    integrationsHealth: enIntegrationsHealth,
    integrations: enIntegrations,
  },
  ar: {
    common: arCommon,
    auth: arAuth,
    farms: arFarms,
    imagery: arImagery,
    indices: arIndices,
    weather: arWeather,
    recommendations: arRecommendations,
    signals: arSignals,
    insights: arInsights,
    alerts: arAlerts,
    rules: arRules,
    imageryWeatherConfig: arImageryWeatherConfig,
    admin: arAdmin,
    decisionTrees: arDecisionTrees,
    users: arUsers,
    settings: arSettings,
    integrationsHealth: arIntegrationsHealth,
    integrations: arIntegrations,
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
    ns: [
      "common",
      "auth",
      "farms",
      "imagery",
      "indices",
      "weather",
      "recommendations",
      "signals",
      "insights",
      "alerts",
      "rules",
      "imageryWeatherConfig",
      "admin",
      "decisionTrees",
      "users",
      "settings",
      "integrationsHealth",
      "integrations",
    ],
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
