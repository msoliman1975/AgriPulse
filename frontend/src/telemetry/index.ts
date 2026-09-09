import type { TelemetryEventName, TelemetryFeature, TelemetryFlow } from "./taxonomy.generated";
import { configureQueue, enqueue, flush, startTimer, stopTimer } from "./queue";
import { newEventId, touchSession } from "./session";
import type { TelemetryEvent } from "./types";

/**
 * Public telemetry API. Everything the app calls goes through `track()`.
 *
 * The kill switch is checked at module level, not per call: with
 * `VITE_TELEMETRY_ENABLED=false` the queue is never allocated, no listener is
 * registered, and `track()` returns on its first line. "Off" means off, not
 * "collected and discarded".
 */

export const TELEMETRY_ENABLED: boolean =
  String(import.meta.env.VITE_TELEMETRY_ENABLED ?? "true").toLowerCase() !== "false";

/** Injected by the vite `define` (declared globally in vite-env.d.ts).
 *  Attributes a behaviour change to a deploy. */
const APP_VERSION: string | undefined =
  typeof __APP_VERSION__ === "string" ? __APP_VERSION__ : undefined;

export type TrackFields = Omit<TelemetryEvent, "id" | "time" | "event_name">;

let started = false;

/**
 * Idempotent. Called once from the app shell after auth is settled.
 *
 * Emits `session_start` only when `touchSession` actually opened a session, so
 * a remount or a second call does not inflate the session count.
 */
export function initTelemetry(): void {
  if (!TELEMETRY_ENABLED || started) return;
  started = true;

  const { id, started: isNew } = touchSession();
  configureQueue({ sessionId: id, appVersion: APP_VERSION });
  startTimer();

  if (isNew) track("session_start");

  // Flush on hide, not on `beforeunload`. `visibilitychange -> hidden` is the
  // only event a mobile browser reliably fires when the tab is backgrounded or
  // the app is swiped away; `beforeunload` is not fired at all on iOS Safari.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void flush();
  });
  // `pagehide` covers the bfcache path, where `visibilitychange` may not fire.
  window.addEventListener("pagehide", () => void flush());
}

/** Test seam and a real teardown path for the kill switch. */
export function shutdownTelemetry(): void {
  started = false;
  stopTimer();
}

export function track(name: TelemetryEventName, fields: TrackFields = {}): void {
  if (!TELEMETRY_ENABLED) return;
  try {
    const { id } = touchSession();
    configureQueue({ sessionId: id, appVersion: APP_VERSION });
    enqueue({
      id: newEventId(),
      time: new Date().toISOString(),
      event_name: name,
      ...fields,
    });
  } catch {
    // A throw here would propagate into whatever UI callback called track().
    // Nothing telemetry does is worth a broken click handler.
  }
}

/**
 * The call the rest of the app uses.
 *
 * `feature` is a closed enum, so a typo is a compile error rather than a row
 * the server silently rejects.
 */
export function trackFeature(
  feature: TelemetryFeature,
  fields: Omit<TrackFields, "feature"> = {},
): void {
  track("feature_used", { ...fields, feature });
}

export function trackFlowStart(flow: TelemetryFlow, fields: TrackFields = {}): void {
  track("flow_start", { ...fields, flow });
}

export function trackFlowStep(flow: TelemetryFlow, step: string, fields: TrackFields = {}): void {
  track("flow_step", { ...fields, flow, step });
}

export function trackFlowComplete(flow: TelemetryFlow, fields: TrackFields = {}): void {
  track("flow_complete", { ...fields, flow, outcome: "ok" });
}

export { flush } from "./queue";
export { routeTemplate, ROUTE_MANIFEST } from "./routes";
export type { TelemetryEventName, TelemetryFeature, TelemetryFlow };
export type { TelemetryEvent } from "./types";
