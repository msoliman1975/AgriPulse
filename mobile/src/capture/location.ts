/**
 * Where the scout is standing, when they choose to say so.
 *
 * Uses the WebView's own geolocation rather than a Capacitor plugin. That is a
 * deliberate trade: Capacitor's WebChromeClient already answers the browser
 * permission prompt and asks Android for ACCESS_FINE_LOCATION, so the web API
 * needs no native code of ours — and adding a plugin would mean a native
 * rebuild of the APK for a capability the WebView already has.
 *
 * Position is always optional. Every caller must work without it, because in
 * a field the fix can be refused, slow, or simply absent indoors, and none of
 * those is a reason to stop a scout recording what they saw.
 */

import type { Geopoint } from "@/api/client";

export interface Fix {
  point: Geopoint;
  /** Metres. Shown to the scout so a bad fix is visible rather than implied. */
  accuracy_m: number;
}

export type FixResult =
  | { ok: true; fix: Fix }
  | { ok: false; reason: "denied" | "unavailable" | "timeout" };

/** Long enough for a cold GPS start outdoors, short enough not to feel hung. */
const TIMEOUT_MS = 15_000;

export async function currentFix(): Promise<FixResult> {
  if (!("geolocation" in navigator)) return { ok: false, reason: "unavailable" };

  return new Promise<FixResult>((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({
          ok: true,
          fix: {
            point: { latitude: pos.coords.latitude, longitude: pos.coords.longitude },
            accuracy_m: Math.round(pos.coords.accuracy),
          },
        }),
      (err) =>
        resolve({
          ok: false,
          reason:
            err.code === err.PERMISSION_DENIED
              ? "denied"
              : err.code === err.TIMEOUT
                ? "timeout"
                : "unavailable",
        }),
      // `enableHighAccuracy` is what makes Android use GPS rather than the
      // network fix. A network fix in open farmland is often kilometres out,
      // which is worse than no position at all because it looks precise.
      { enableHighAccuracy: true, timeout: TIMEOUT_MS, maximumAge: 0 },
    );
  });
}
