import { useCallback, useRef } from "react";

import { track } from "./index";
import type { TelemetryFlow } from "./taxonomy.generated";

/**
 * One tracked funnel, for the lifetime of the component that owns it.
 *
 * Written as a hook rather than bare `track()` calls because a funnel has one
 * rule that is easy to break by hand: `flow_start` must fire exactly once, and
 * every step must follow it. A page that emits `flow_step` with no preceding
 * `flow_start` produces a funnel with more people at step 2 than entered — a
 * chart that is not merely wrong but obviously wrong, and unfixable after the
 * fact.
 *
 * There is deliberately no `abandon()`. Abandonment is DERIVED server-side from
 * a start with no completion inside the flow's timeout. The client cannot
 * report the case that matters most — the user who closed the laptop — so
 * letting it report the easy cases would undercount exactly the hard ones.
 */
export interface FlowTracker {
  /** Idempotent. The second call in a component's life is ignored. */
  start: (entryPoint?: string) => void;
  /** Emits `flow_start` first if it has not fired yet, so a step is never
   *  orphaned by a code path that skipped the entry point. */
  step: (name: string) => void;
  complete: (durationMs?: number) => void;
  /** Lets the same component track a second attempt after a completion. */
  reset: () => void;
}

export function useFlow(flow: TelemetryFlow): FlowTracker {
  const started = useRef(false);
  const startedAt = useRef<number | null>(null);
  const stepCount = useRef(0);

  const start = useCallback(
    (entryPoint?: string) => {
      if (started.current) return;
      started.current = true;
      startedAt.current = Date.now();
      stepCount.current = 0;
      track("flow_start", {
        flow,
        props: entryPoint ? { entry_point: entryPoint.slice(0, 64) } : undefined,
      });
    },
    [flow],
  );

  const step = useCallback(
    (name: string) => {
      if (!started.current) start();
      stepCount.current += 1;
      track("flow_step", { flow, step: name, props: { attempt: stepCount.current } });
    },
    [flow, start],
  );

  const complete = useCallback(
    (durationMs?: number) => {
      if (!started.current) return;
      const elapsed =
        durationMs ?? (startedAt.current === null ? undefined : Date.now() - startedAt.current);
      track("flow_complete", {
        flow,
        outcome: "ok",
        duration_ms: elapsed,
        props: { steps_taken: stepCount.current },
      });
      started.current = false;
      startedAt.current = null;
    },
    [flow],
  );

  const reset = useCallback(() => {
    started.current = false;
    startedAt.current = null;
    stepCount.current = 0;
  }, []);

  return { start, step, complete, reset };
}
