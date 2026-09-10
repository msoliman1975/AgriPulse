// A panel size that survives a reload.
//
// Whoever moved the rail to 420px did it because their block names are long,
// and that is still true on their next visit. Storing it is what makes the
// handle worth dragging once rather than every time.
//
// `localStorage` throws outright in some contexts — a browser set to block
// site data, a privacy window, an embedded preview — so every read and write
// is guarded and a failure means the default size, never a broken screen.

import { useCallback, useEffect, useRef, useState } from "react";

const PREFIX = "farmHealth.panel.";

export function readSize(key: string, fallback: number, min: number, max: number): number {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw === null) return fallback;
    const parsed = Number.parseFloat(raw);
    // A stored NaN or a stored zero is a corrupt value, not a request for a
    // panel with no width.
    if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
    // Clamped against the CALLER's range, not just sanity-checked. A size
    // stored before the range changed would otherwise be applied whole, and
    // the handle would report an `aria-valuenow` outside its own min and max
    // until the first drag.
    return Math.min(max, Math.max(min, parsed));
  } catch {
    return fallback;
  }
}

/** How long after the last move the size is written. One drag, one write. */
const SETTLE_MS = 300;

/**
 * One panel's size, remembered per browser.
 *
 * Returns the same pair `useState` does, so a caller hands the setter
 * straight to a `Resizer`.
 *
 * The state moves with the pointer; the WRITE waits for it to settle. A
 * pointer fires 60 to 120 moves a second, and storing on each one meant that
 * many synchronous `localStorage` writes per second of drag.
 */
export function usePanelSize(
  key: string,
  fallback: number,
  min: number,
  max: number,
): [number, (next: number) => void] {
  const [size, setSize] = useState(() => readSize(key, fallback, min, max));
  const timer = useRef<number | null>(null);

  // A drag that ends by unmounting the screen — a route change mid-drag —
  // still stores the size the reader left it at.
  const pending = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
      if (pending.current === null) return;
      try {
        window.localStorage.setItem(PREFIX + key, String(Math.round(pending.current)));
      } catch {
        // Nothing to tell the reader; see below.
      }
    },
    [key],
  );

  const store = useCallback(
    (next: number) => {
      setSize(next);
      pending.current = next;
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        pending.current = null;
        try {
          window.localStorage.setItem(PREFIX + key, String(Math.round(next)));
        } catch {
          // A size that cannot be stored is still a size that works for this
          // visit. There is nothing to tell the reader.
        }
      }, SETTLE_MS);
    },
    [key],
  );
  return [size, store];
}
