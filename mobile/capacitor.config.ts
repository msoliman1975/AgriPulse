import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "cloud.agripulse.scout",
  appName: "AgriPulse Scout",
  webDir: "dist",
  server: {
    // Capacitor defaults the Android scheme to https, so the app would be
    // served from https://localhost. A dev api on http://10.0.2.2:8000 is then
    // insecure content on a secure origin and the WebView blocks every request
    // — with allowMixedContent:false, silently. Serving the app over http
    // instead keeps origin and api on the same scheme, so no mixed content
    // exists to block. The origin also becomes http://localhost, which is what
    // CORS_ALLOWED_ORIGINS must list.
    //
    // Revisit for a release build talking to https://app.agripulse.cloud:
    // there both sides are https and this override should be dropped.
    androidScheme: "http",
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
