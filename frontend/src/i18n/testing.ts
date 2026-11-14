import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enCommon from "./locales/en/common.json";
import enAuth from "./locales/en/auth.json";
import enAccount from "./locales/en/account.json";
import enFarms from "./locales/en/farms.json";
import enImagery from "./locales/en/imagery.json";
import enIndices from "./locales/en/indices.json";
import enWeather from "./locales/en/weather.json";
import enAdmin from "./locales/en/admin.json";
import enSignals from "./locales/en/signals.json";
import enFarmConsole from "./locales/en/farmConsole.json";
import enInsights from "./locales/en/insights.json";
import enWeatherIndices from "./locales/en/weatherIndices.json";
import enWeatherRisk from "./locales/en/weatherRisk.json";
import enDecisionTrees from "./locales/en/decisionTrees.json";
import enDecisionTreesBeta from "./locales/en/decisionTreesBeta.json";
import enDecisionTreesEstate from "./locales/en/decisionTreesEstate.json";
import enSources from "./locales/en/sources.json";
import enInputs from "./locales/en/inputs.json";
import enBulkUpdates from "./locales/en/bulkUpdates.json";
import enActionCenter from "./locales/en/actionCenter.json";
import enUsers from "./locales/en/users.json";
import enFarmHealth from "./locales/en/farmHealth.json";
import enTimeline from "./locales/en/timeline.json";
import enInvestors from "./locales/en/investors.json";
import enAgriOperation from "./locales/en/agriOperation.json";
import enBoard from "./locales/en/board.json";
import enPlanTemplates from "./locales/en/planTemplates.json";
import enReports from "./locales/en/reports.json";
import enFieldAccess from "./locales/en/fieldAccess.json";
import enIntegrationsHealth from "./locales/en/integrationsHealth.json";
import enIntegrations from "./locales/en/integrations.json";
import arCommon from "./locales/ar/common.json";
import arAuth from "./locales/ar/auth.json";
import arAccount from "./locales/ar/account.json";
import arFarms from "./locales/ar/farms.json";
import arImagery from "./locales/ar/imagery.json";
import arIndices from "./locales/ar/indices.json";
import arWeather from "./locales/ar/weather.json";
import arAdmin from "./locales/ar/admin.json";
import arSignals from "./locales/ar/signals.json";
import arFarmConsole from "./locales/ar/farmConsole.json";
import arInsights from "./locales/ar/insights.json";
import arWeatherIndices from "./locales/ar/weatherIndices.json";
import arWeatherRisk from "./locales/ar/weatherRisk.json";
import arDecisionTrees from "./locales/ar/decisionTrees.json";
import arDecisionTreesBeta from "./locales/ar/decisionTreesBeta.json";
import arDecisionTreesEstate from "./locales/ar/decisionTreesEstate.json";
import arSources from "./locales/ar/sources.json";
import arInputs from "./locales/ar/inputs.json";
import arBulkUpdates from "./locales/ar/bulkUpdates.json";
import arActionCenter from "./locales/ar/actionCenter.json";
import arUsers from "./locales/ar/users.json";
import arFarmHealth from "./locales/ar/farmHealth.json";
import arTimeline from "./locales/ar/timeline.json";
import arInvestors from "./locales/ar/investors.json";
import arAgriOperation from "./locales/ar/agriOperation.json";
import arBoard from "./locales/ar/board.json";
import arPlanTemplates from "./locales/ar/planTemplates.json";
import arReports from "./locales/ar/reports.json";
import arFieldAccess from "./locales/ar/fieldAccess.json";
import arIntegrationsHealth from "./locales/ar/integrationsHealth.json";
import arIntegrations from "./locales/ar/integrations.json";

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
          account: enAccount,
          farms: enFarms,
          imagery: enImagery,
          indices: enIndices,
          weather: enWeather,
          admin: enAdmin,
          signals: enSignals,
          farmConsole: enFarmConsole,
          insights: enInsights,
          weatherIndices: enWeatherIndices,
          weatherRisk: enWeatherRisk,
          decisionTrees: enDecisionTrees,
          decisionTreesBeta: enDecisionTreesBeta,
          decisionTreesEstate: enDecisionTreesEstate,
          sources: enSources,
          inputs: enInputs,
          bulkUpdates: enBulkUpdates,
          actionCenter: enActionCenter,
          users: enUsers,
          farmHealth: enFarmHealth,
          timeline: enTimeline,
          investors: enInvestors,
          agriOperation: enAgriOperation,
          board: enBoard,
          planTemplates: enPlanTemplates,
          reports: enReports,
          fieldAccess: enFieldAccess,
          integrationsHealth: enIntegrationsHealth,
          integrations: enIntegrations,
        },
        ar: {
          common: arCommon,
          auth: arAuth,
          account: arAccount,
          farms: arFarms,
          imagery: arImagery,
          indices: arIndices,
          weather: arWeather,
          admin: arAdmin,
          signals: arSignals,
          farmConsole: arFarmConsole,
          insights: arInsights,
          weatherIndices: arWeatherIndices,
          weatherRisk: arWeatherRisk,
          decisionTrees: arDecisionTrees,
          decisionTreesBeta: arDecisionTreesBeta,
          decisionTreesEstate: arDecisionTreesEstate,
          sources: arSources,
          inputs: arInputs,
          bulkUpdates: arBulkUpdates,
          actionCenter: arActionCenter,
          users: arUsers,
          farmHealth: arFarmHealth,
          timeline: arTimeline,
          investors: arInvestors,
          agriOperation: arAgriOperation,
          board: arBoard,
          planTemplates: arPlanTemplates,
          reports: arReports,
          fieldAccess: arFieldAccess,
          integrationsHealth: arIntegrationsHealth,
          integrations: arIntegrations,
        },
      },
      lng: language,
      fallbackLng: "en",
      defaultNS: "common",
      ns: [
        "common",
        "auth",
        "account",
        "farms",
        "imagery",
        "indices",
        "weather",
        "admin",
        "signals",
        "farmConsole",
        "bulkUpdates",
        "actionCenter",
        "users",
        "timeline",
        "investors",
        "agriOperation",
        "board",
        "planTemplates",
      ],
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
    initialized = true;
  }
  await i18n.changeLanguage(language);
  document.documentElement.setAttribute("lang", language);
  document.documentElement.setAttribute("dir", language === "ar" ? "rtl" : "ltr");
}
