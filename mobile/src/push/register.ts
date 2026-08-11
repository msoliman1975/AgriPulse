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

import { registerDevice, revokeDevice } from "@/api/client";

let inFlight: Promise<void> | null = null;
// The FCM token arrives in a listener rather than as a return value, so
// sign-out has nothing to revoke unless we hold on to it here.
let lastToken: string | null = null;

/** Native only. The browser build has no FCM token to offer. */
export function pushSupported(): boolean {
  return Capacitor.isNativePlatform() && Capacitor.isPluginAvailable("PushNotifications");
}

async function run(farmId: string): Promise<void> {
  // Registration is farm-gated: a Scout holds no tenant role, so the wrong
  // farm is a guaranteed 403 and the phone silently never buzzes. The farm now
  // comes from the caller, which resolved it from the token, rather than from
  // a build-time constant that could name somebody else's farm entirely.
  if (!farmId) {
    console.warn("push: no farm resolved yet; skipping device registration");
    return;
  }

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
      lastToken = token.value;
      registerDevice(token.value, farmId)
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
export function ensureDeviceRegistered(farmId: string): Promise<void> {
  if (!pushSupported()) {
    console.info("push: not a native platform; skipping device registration");
    return Promise.resolve();
  }
  inFlight ??= run(farmId).catch((err: unknown) => {
    console.warn("push: registration aborted", err);
  });
  return inFlight;
}

/**
 * Called on sign-out. Tells the server to stop pushing to this handset, then
 * clears the in-session guard so the next scout registers under their own
 * account.
 *
 * Awaited by the caller before the session is cleared and the app reloads:
 * the request needs the access token, and a reload mid-flight cancels it.
 * Failure is non-fatal — the next registration reassigns the token anyway —
 * but leaving it out entirely means a drawered phone keeps buzzing for
 * somebody who has left.
 */
export async function releaseDevice(): Promise<void> {
  const token = lastToken;
  inFlight = null;
  lastToken = null;
  if (!token) return;
  try {
    await revokeDevice(token);
  } catch (err) {
    console.warn("push: could not revoke this device", err);
  }
}
