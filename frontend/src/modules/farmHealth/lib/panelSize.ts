// A panel size that survives a reload.
//
// Whoever moved the rail to 420px did it because their block names are long,
// and that is still true on their next visit. Storing it is what makes the
// handle worth dragging once rather than every time.
//
// `localStorage` throws outright in some contexts — a browser set to block
// site data, a privacy window, an embedded preview — so every read and write
// is guarded and a failure means the default size, never a broken screen.

import { useCallback, useState } from "react";

const PREFIX = "farmHealth.panel.";

export function readSize(key: string, fallback: number): number {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw === null) return fallback;
    const parsed = Number.parseFloat(raw);
    // A stored NaN or a stored zero is a corrupt value, not a request for a
    // panel with no width.
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  } catch {
    return fallback;
  }
}

/**
 * One panel's size, remembered per browser.
 *
 * Returns the same pair `useState` does, so a caller hands the setter
 * straight to a `Resizer`.
 */
export function usePanelSize(key: string, fallback: number): [number, (next: number) => void] {
  const [size, setSize] = useState(() => readSize(key, fallback));
  const store = useCallback(
    (next: number) => {
      setSize(next);
      try {
        window.localStorage.setItem(PREFIX + key, String(Math.round(next)));
      } catch {
        // A size that cannot be stored is still a size that works for this
        // visit. There is nothing to tell the reader.
      }
    },
    [key],
  );
  return [size, store];
}
