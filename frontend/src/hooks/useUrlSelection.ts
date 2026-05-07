import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

import { usePlanSelection } from "@/state/planSelection";

/**
 * Bidirectional sync between `?lane=` / `?activity=` URL params and the
 * Zustand selection store. The URL is the single source of truth — the
 * store mirrors it so deep components don't all need to subscribe to
 * `useSearchParams`. Reload-stable.
 */
export function useUrlSelection(): void {
  const [params, setParams] = useSearchParams();
  const { laneId, activityId, setBoth } = usePlanSelection();

  // URL → store (initial mount + back/forward).
  useEffect(() => {
    const lane = params.get("lane");
    const activity = params.get("activity");
    if (lane !== laneId || activity !== activityId) {
      setBoth(lane, activity);
    }
    // Intentionally don't depend on store values — we only react to the
    // URL changing externally. Internal store mutations are pushed back
    // to the URL via the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  // Store → URL.
  useEffect(() => {
    const next = new URLSearchParams(params);
    if (laneId) next.set("lane", laneId);
    else next.delete("lane");
    if (activityId) next.set("activity", activityId);
    else next.delete("activity");
    if (next.toString() !== params.toString()) {
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [laneId, activityId]);
}
