import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

import { track } from "./index";
import { flush } from "./queue";
import { matchRouteInfo } from "./routes";

/**
 * Page views and dwell. Mounted once, in the app shell.
 *
 * Dwell counts VISIBLE time only. Wall-clock between two route changes is not
 * "time spent" — it is "time the tab was open", and on a product people leave
 * open all day the two differ by an order of magnitude. Accumulating across
 * `visibilitychange` is what makes "which surface absorbs the most user time"
 * a real number instead of a measure of tab hygiene.
 */

/** A single page_leave above this is discarded rather than clamped. A laptop
 *  lid closed over a weekend produces one absurd row that would move a median. */
export const MAX_DWELL_MS = 30 * 60 * 1000;

export function useTelemetryRoute(): void {
  const location = useLocation();

  // Refs, not state: none of this may cause a render. A telemetry hook that
  // re-renders the shell on every visibility change would be a performance bug
  // introduced by the tool meant to find them.
  const accumulated = useRef(0);
  const visibleSince = useRef<number | null>(null);
  const template = useRef("unknown");
  const currentFarm = useRef<string | undefined>(undefined);

  useEffect(() => {
    const onVisibility = (): void => {
      if (document.visibilityState === "hidden") {
        if (visibleSince.current !== null) {
          accumulated.current += Date.now() - visibleSince.current;
          visibleSince.current = null;
        }
      } else if (visibleSince.current === null) {
        visibleSince.current = Date.now();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    const { template: next, farmId } = matchRouteInfo(location.pathname);
    template.current = next;
    currentFarm.current = farmId;
    accumulated.current = 0;
    visibleSince.current = document.visibilityState === "hidden" ? null : Date.now();

    track("page_view", { route: next, farm_id: farmId });
    // A route change is a flush point: the batch that carries the page_leave we
    // are about to emit should not sit in the queue for another 15 s.
    void flush();

    return () => {
      const visibleNow = visibleSince.current === null ? 0 : Date.now() - visibleSince.current;
      const total = accumulated.current + visibleNow;
      if (total <= MAX_DWELL_MS) {
        track("page_leave", {
          route: next,
          farm_id: farmId,
          duration_ms: Math.round(total),
        });
      }
    };
  }, [location.pathname]);

  // The unload path. The cleanup above runs on a route change but NOT when the
  // tab closes, so without this the last page of every session — often the one
  // the user got stuck on — reports no dwell at all.
  useEffect(() => {
    const emitLeave = (): void => {
      const visibleNow = visibleSince.current === null ? 0 : Date.now() - visibleSince.current;
      const total = accumulated.current + visibleNow;
      if (total > 0 && total <= MAX_DWELL_MS) {
        track("page_leave", {
          route: template.current,
          farm_id: currentFarm.current,
          duration_ms: Math.round(total),
        });
      }
      // Counted now; the route-change cleanup must not count it again.
      accumulated.current = 0;
      visibleSince.current = null;
      void flush();
    };
    // `pagehide` always means the page is going away. `visibilitychange` only
    // does when it settles on hidden — it also fires on the way back.
    const onVisibilityHide = (): void => {
      if (document.visibilityState === "hidden") emitLeave();
    };
    document.addEventListener("visibilitychange", onVisibilityHide);
    window.addEventListener("pagehide", emitLeave);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityHide);
      window.removeEventListener("pagehide", emitLeave);
    };
  }, []);
}
