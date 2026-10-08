import type { CapacitorConfig } from "@capacitor/cli";

// Set INVESTOR_ENV=production for a build against https://api.agripulse.cloud,
// for BOTH `vite build` and `cap sync`: the Capacitor CLI bakes this file into
// the APK and never reads .env files. Production serves the app from
// https://localhost, the origin the api already allows for Scout.
const isProduction = process.env.INVESTOR_ENV === "production";

const config: CapacitorConfig = {
  appId: "cloud.agripulse.investor",
  appName: "AgriPulse Investor",
  webDir: "dist",
  server: {
    androidScheme: isProduction ? "https" : "http",
  },
  android: {
    allowMixedContent: false,
  },
};

export default config;
