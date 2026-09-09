import type { TelemetryBatch } from "./types";

/**
 * Session identity and device context.
 *
 * A session is a browser-tab visit, not a login. It ends after
 * `IDLE_TIMEOUT_MS` of no tracked activity, which is what makes "median session
 * length" mean time-in-product rather than time-with-tab-open.
 *
 * The id is held in `sessionStorage`, not `localStorage`: a second tab is a
 * second session, and a closed tab must not resume yesterday's.
 */

const STORAGE_KEY = "agripulse.telemetry.session";
export const IDLE_TIMEOUT_MS = 30 * 60 * 1000;

interface StoredSession {
  id: string;
  lastSeen: number;
  startedAt: number;
}

function randomId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  // Test environments and very old browsers. Uniqueness matters, entropy
  // quality does not — this id names a tab visit, nothing security-bearing.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
    const r = Math.floor(Math.random() * 16);
    const v = ch === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function newEventId(): string {
  return randomId();
}

function read(): StoredSession | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as StoredSession).id === "string"
    ) {
      return parsed as StoredSession;
    }
  } catch {
    // Private mode, disabled storage, corrupt JSON. A fresh session is the
    // correct answer to all three, and telemetry must never throw.
  }
  return null;
}

function write(s: StoredSession): void {
  try {
    globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // Storage full or blocked. The in-memory id still holds for this page
    // load, which is the common case; only a reload loses continuity.
  }
}

let current: StoredSession | null = null;

/** Returns the session id and whether this call started a new session. */
export function touchSession(now: number = Date.now()): {
  id: string;
  started: boolean;
} {
  if (current === null) current = read();
  if (current === null || now - current.lastSeen > IDLE_TIMEOUT_MS) {
    current = { id: randomId(), lastSeen: now, startedAt: now };
    write(current);
    return { id: current.id, started: true };
  }
  current.lastSeen = now;
  write(current);
  return { id: current.id, started: false };
}

export function sessionStartedAt(): number {
  return current?.startedAt ?? Date.now();
}

/** Test seam. Clears both the module cache and the stored session. */
export function resetSession(): void {
  current = null;
  try {
    globalThis.sessionStorage?.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Coarse device class. Deliberately derived from viewport width, not from the
 * user-agent string: the UA is a fingerprint we decided not to collect, and the
 * only product question here is "is anyone using this on a phone in the field?"
 */
export function deviceKind(width: number): NonNullable<TelemetryBatch["device_kind"]> {
  if (width < 640) return "mobile";
  if (width < 1024) return "tablet";
  return "desktop";
}

export function viewportWidth(): number {
  return Math.min(globalThis.innerWidth || 0, 32767);
}
