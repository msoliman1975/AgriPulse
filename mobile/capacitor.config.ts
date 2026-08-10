import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "cloud.agripulse.scout",
  appName: "AgriPulse Scout",
  webDir: "dist",
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
