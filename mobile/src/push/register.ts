/**
 * Register this handset so a dispatched visit can actually reach the scout.
 *
 * Called after sign-in and on every cold start of an already-signed-in app,
 * because FCM rotates tokens on reinstall, restore and occasionally at
 * Google's discretion. A token registered once at first launch and never
 * refreshed is how a phone quietly stops buzzing months later.
 *
 * The backend upserts on the token string, so re-registering is cheap and
 * moves a reassigned token to its new owner rather than leaving the previous
 * scout's row pointing at a handset they no longer hold.
 *
 * Failure here is deliberately non-fatal. Push is a convenience: the visit
 * list is the source of truth and reconciles on open, so a scout with a broken
 * registration still sees their work — they just find it by looking rather
 * than by being told.
 */

import { Capacitor } from "@capacitor/core";
import { PushNotifications } from "@capacitor/push-notifications";

import { registerDevice } from "@/api/client";

let inFlight: Promise<void> | null = null;

/** Native only. The browser build has no FCM token to offer. */
export function pushSupported(): boolean {
  return Capacitor.isNativePlatform() && Capacitor.isPluginAvailable("PushNotifications");
}

async function run(): Promise<void> {
  // Ask, then check — on Android 13+ POST_NOTIFICATIONS is a runtime grant,
  // and a scout who declines must not be nagged into a loop on every launch.
  let status = await PushNotifications.checkPermissions();
  if (status.receive === "prompt" || status.receive === "prompt-with-rationale") {
    status = await PushNotifications.requestPermissions();
  }
  if (status.receive !== "granted") {
    console.info("push: permission not granted; visits still list normally");
    return;
  }

  await new Promise<void>((resolve) => {
    // `registration` fires asynchronously after register(); the token is not a
    // return value, which is why this is wrapped rather than awaited directly.
    void PushNotifications.addListener("registration", (token) => {
      registerDevice(token.value)
        .catch((err: unknown) => console.warn("push: backend registration failed", err))
        .finally(() => resolve());
    });
    void PushNotifications.addListener("registrationError", (err) => {
      console.warn("push: FCM registration failed", err);
      resolve();
    });
    void PushNotifications.register();
  });
}

/**
 * Idempotent per app session: several screens may call this on mount, and
 * registering twice would race two upserts for the same token.
 */
export function ensureDeviceRegistered(): Promise<void> {
  if (!pushSupported()) {
    console.info("push: not a native platform; skipping device registration");
    return Promise.resolve();
  }
  inFlight ??= run().catch((err: unknown) => {
    console.warn("push: registration aborted", err);
  });
  return inFlight;
}

/** Called on sign-out so the next scout on this handset re-registers cleanly. */
export function resetDeviceRegistration(): void {
  inFlight = null;
}
