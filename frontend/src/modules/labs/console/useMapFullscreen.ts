// Full-screen for the map pane.
//
// MapLibre is created with `trackResize`, which listens for a WINDOW resize —
// and entering full-screen on a child element does not reliably emit one. The
// canvas then keeps its old dimensions and renders letterboxed inside a
// full-screen container, which looks like a rendering bug. Nudging the window
// after the transition settles is enough for MapLibre to pick up the new size,
// and avoids threading a map instance out of MapCanvas just for this.
import { useCallback, useEffect, useRef, useState } from "react";

export function useMapFullscreen<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const onChange = (): void => {
      const active = document.fullscreenElement === ref.current;
      setIsFullscreen(active);
      // rAF so the browser has laid the element out at its new size first.
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const toggle = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    if (document.fullscreenElement === el) {
      void document.exitFullscreen().catch(() => {
        /* the user can always press Escape */
      });
      return;
    }
    void el.requestFullscreen().catch(() => {
      /* blocked by permissions policy or an unsupported browser */
    });
  }, []);

  return { ref, isFullscreen, toggle };
}
