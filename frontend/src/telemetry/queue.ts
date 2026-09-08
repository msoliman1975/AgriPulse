import { getAccessToken } from "@/auth/token";

import { deviceKind, viewportWidth } from "./session";
import type { TelemetryBatch, TelemetryEvent } from "./types";

/**
 * The queue and the wire.
 *
 * Two rules govern every line here:
 *
 *  1. Telemetry never breaks the app. Every path swallows its own failure,
 *     nothing is retried, and the buffer is hard-capped so a broken flush
 *     cannot grow memory without bound.
 *  2. Losing events is acceptable; losing the user's work is not. When the two
 *     conflict, the events go.
 */

/** Ring-buffer cap. Overflow drops the OLDEST event and counts it: recent
 *  activity is what a support question is about. */
export const MAX_QUEUE = 200;
/** Flush at this many queued events. The server caps a batch at 50. */
export const FLUSH_AT_EVENTS = 10;
export const FLUSH_INTERVAL_MS = 15_000;
/** Server-side cap. Sending more just wastes the tail of the batch. */
const MAX_EVENTS_PER_BATCH = 50;

const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "/api";
const INGEST_URL = `${API_BASE}/v1/telemetry/events`;

let queue: TelemetryEvent[] = [];
let dropped = 0;
let timer: ReturnType<typeof setInterval> | null = null;
let sessionId = "";
let appVersion: string | undefined;

export function configureQueue(opts: { sessionId: string; appVersion?: string }): void {
  sessionId = opts.sessionId;
  appVersion = opts.appVersion;
}

export function enqueue(event: TelemetryEvent): void {
  queue.push(event);
  while (queue.length > MAX_QUEUE) {
    queue.shift();
    dropped += 1;
  }
  if (queue.length >= FLUSH_AT_EVENTS) void flush();
}

export function queueLength(): number {
  return queue.length;
}

export function droppedCount(): number {
  return dropped;
}

/** Test seam. */
export function resetQueue(): void {
  queue = [];
  dropped = 0;
  stopTimer();
}

export function startTimer(): void {
  if (timer !== null) return;
  timer = setInterval(() => void flush(), FLUSH_INTERVAL_MS);
}

export function stopTimer(): void {
  if (timer === null) return;
  clearInterval(timer);
  timer = null;
}

function takeBatch(): TelemetryBatch | null {
  if (queue.length === 0) return null;
  const events = queue.slice(0, MAX_EVENTS_PER_BATCH);
  // Taken off the queue BEFORE the request, and never put back. A retry on a
  // failed flush is how a telemetry client turns a backend blip into a request
  // storm against the backend that is already struggling.
  queue = queue.slice(events.length);
  const batch: TelemetryBatch = {
    session_id: sessionId,
    app_version: appVersion,
    device_kind: deviceKind(viewportWidth()),
    viewport_w: viewportWidth(),
    dropped,
    events,
  };
  dropped = 0;
  return batch;
}

/**
 * Send whatever is queued.
 *
 * `keepalive: true` — not `navigator.sendBeacon` — and the reason is the
 * bearer token. The ingest route is authenticated, because identity is stamped
 * from the JWT; `sendBeacon` cannot set an `Authorization` header, so a beacon
 * would arrive anonymous and be rejected 401. The alternative was a
 * short-lived token in the query string, which puts a credential in a URL that
 * lands in access logs. `keepalive` carries headers and survives unload in
 * every browser this app supports, so it is both the safer and the simpler
 * option. (Plan § 5.1, open question O3 — resolved in favour of keepalive.)
 *
 * `keepalive` bodies are capped at 64 KB by the fetch spec, which is the same
 * ceiling the server enforces. A 50-event batch is ~10 KB.
 */
export async function flush(): Promise<void> {
  // Token first, batch second. The other order looks equivalent and is not:
  // `takeBatch()` empties the queue, so flushing before a token exists — which
  // is exactly what happens on every hard refresh, while the OIDC user loads —
  // would throw the first events of every session away silently. Leaving them
  // queued means they go out on the next flush, and if the user never
  // authenticates the ring buffer caps the memory anyway.
  const token = getAccessToken();
  if (!token) return;
  const batch = takeBatch();
  if (batch === null) return;
  try {
    await fetch(INGEST_URL, {
      method: "POST",
      keepalive: true,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(batch),
    });
  } catch {
    // Network down, request blocked, page tearing down. Nothing to do and
    // nothing to say: the events are already gone by design.
  }
}
