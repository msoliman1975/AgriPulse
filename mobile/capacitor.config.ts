import type { CapacitorConfig } from "@capacitor/cli";

// Which backend this binary is built against. Set SCOUT_ENV=production for a
// build that talks to https://api.agripulse.cloud; anything else keeps the dev
// shape. It has to be an env var rather than a Vite mode because `cap sync`
// bakes the value below into android/app/src/main/assets/capacitor.config.json,
// and the Capacitor CLI never reads .env files. Set it for BOTH `vite build`
// and `cap sync` or the bundle and the shell will disagree about the origin.
const isProduction = process.env.SCOUT_ENV === "production";

const config: CapacitorConfig = {
  appId: "cloud.agripulse.scout",
  appName: "AgriPulse Scout",
  webDir: "dist",
  server: {
    // Capacitor defaults the Android scheme to https, so the app is served from
    // https://localhost. Against production that is exactly right: the api is
    // https too, so there is no mixed content and the origin the api must allow
    // in CORS_ALLOWED_ORIGINS is https://localhost.
    //
    // A dev api on http://10.0.2.2:8000 is the opposite case — insecure content
    // on a secure origin, which the WebView blocks silently under
    // allowMixedContent:false. Serving the app over http instead puts origin
    // and api on the same scheme, so no mixed content exists to block.
    androidScheme: isProduction ? "https" : "http",
  },
  android: {
    // The app draws its own notifications from FCM *data* messages, so the OS
    // must not also draw one — see notifications/push.py.
    allowMixedContent: false,
  },
  plugins: {
    PushNotifications: { presentationOptions: ["badge", "sound", "alert"] },
  },
};

export default config;
