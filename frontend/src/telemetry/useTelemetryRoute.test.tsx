import { act, render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as sdk from "./index";
import { useTelemetryRoute } from "./useTelemetryRoute";

/**
 * The dwell rules, which are the part of this that is easy to get subtly wrong
 * and impossible to notice: a wrong number still renders a chart.
 */

function Probe(): null {
  useTelemetryRoute();
  return null;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/board/:farmId" element={<Probe />} />
        <Route path="/farms" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );
}

function setVisibility(state: "visible" | "hidden"): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

const FARM = "8f3a1b2c-0000-4000-8000-000000000000";

describe("useTelemetryRoute", () => {
  let track: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    track = vi.spyOn(sdk, "track").mockImplementation(() => undefined);
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("emits page_view with the template and the farm id", () => {
    renderAt(`/board/${FARM}`);
    expect(track).toHaveBeenCalledWith("page_view", {
      route: "/board/:farmId",
      farm_id: FARM,
    });
  });

  it("emits page_leave with the visible dwell on unmount", () => {
    const view = renderAt("/farms");
    act(() => {
      vi.advanceTimersByTime(4_000);
    });
    view.unmount();
    const leave = track.mock.calls.find((c) => c[0] === "page_leave");
    expect(leave?.[1]).toMatchObject({ route: "/farms" });
    expect((leave?.[1] as { duration_ms: number }).duration_ms).toBeGreaterThanOrEqual(3_900);
  });

  it("excludes time the tab was hidden", () => {
    renderAt("/farms");
    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    // Hiding emits its own page_leave for the 2s that were visible...
    setVisibility("hidden");
    const first = track.mock.calls.find((c) => c[0] === "page_leave");
    expect((first?.[1] as { duration_ms: number }).duration_ms).toBeGreaterThanOrEqual(1_900);
    expect((first?.[1] as { duration_ms: number }).duration_ms).toBeLessThan(3_000);

    // ...and the hour spent backgrounded is not counted anywhere.
    act(() => {
      vi.advanceTimersByTime(60 * 60 * 1000);
    });
    setVisibility("visible");
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    setVisibility("hidden");
    const leaves = track.mock.calls.filter((c) => c[0] === "page_leave");
    expect(leaves).toHaveLength(2);
    expect((leaves[1][1] as { duration_ms: number }).duration_ms).toBeLessThan(3_000);
  });

  it("discards an absurd dwell rather than storing it", () => {
    const view = renderAt("/farms");
    act(() => {
      // A laptop lid closed over a weekend, with the tab never marked hidden.
      vi.advanceTimersByTime(48 * 60 * 60 * 1000);
    });
    view.unmount();
    expect(track.mock.calls.filter((c) => c[0] === "page_leave")).toHaveLength(0);
  });
});
