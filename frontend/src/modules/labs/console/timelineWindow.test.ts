import { describe, expect, it } from "vitest";

import type { FarmScene } from "@/api/imagery";

import { asOfInstant, scenesWithin, TIMELINE_DEFAULT_DAYS } from "./timelineWindow";

function scene(scene_date: string): FarmScene {
  return {
    scene_date,
    at: `${scene_date}T08:30:00Z`,
    succeeded_count: 36,
    skipped_cloud_count: 0,
    computed_count: 36,
    cloud_cover_pct: null,
    no_reading_pct: null,
  } as unknown as FarmScene;
}

describe("scenesWithin", () => {
  it("defaults to thirty days", () => {
    expect(TIMELINE_DEFAULT_DAYS).toBe(30);
  });

  it("keeps only the passes inside the window", () => {
    const scenes = [scene("2026-08-20"), scene("2026-08-10"), scene("2026-06-01")];
    const out = scenesWithin(scenes, 30, null).map((s) => s.scene_date);
    expect(out).toEqual(["2026-08-20", "2026-08-10"]);
  });

  it("anchors on the newest pass, not on today", () => {
    // Every pass is months old. Anchored on the clock this returns nothing and
    // the console opens on an empty date bar; anchored on the newest pass it
    // returns the passes around it, which is the point.
    const scenes = [scene("2025-03-20"), scene("2025-03-10"), scene("2024-01-01")];
    const out = scenesWithin(scenes, 30, null).map((s) => s.scene_date);
    expect(out).toEqual(["2025-03-20", "2025-03-10"]);
  });

  it("keeps a selected pass that falls outside the window", () => {
    // Narrowing the window must not hide the scene the map is drawing.
    const scenes = [scene("2026-08-20"), scene("2026-08-10"), scene("2026-06-01")];
    const out = scenesWithin(scenes, 30, "2026-06-01").map((s) => s.scene_date);
    expect(out).toEqual(["2026-08-20", "2026-08-10", "2026-06-01"]);
  });

  it("returns everything for a null window", () => {
    const scenes = [scene("2026-08-20"), scene("2024-01-01")];
    expect(scenesWithin(scenes, null, null)).toHaveLength(2);
  });

  it("survives an empty list", () => {
    expect(scenesWithin([], 30, null)).toEqual([]);
  });

  it("crosses a month boundary by days, not by calendar month", () => {
    const scenes = [scene("2026-03-05"), scene("2026-02-10"), scene("2026-02-01")];
    // 30 days back from 5 March 2026 is 3 February.
    const out = scenesWithin(scenes, 30, null).map((s) => s.scene_date);
    expect(out).toEqual(["2026-03-05", "2026-02-10"]);
  });
});

describe("asOfInstant", () => {
  it("is null while the bar is on latest", () => {
    expect(asOfInstant(null)).toBeNull();
  });

  it("cuts at the END of the selected day", () => {
    // Not the overpass instant: the satellite passes in the morning, and
    // cutting there would hide everything a scout recorded that afternoon.
    expect(asOfInstant("2026-08-12")).toBe("2026-08-12T23:59:59.999Z");
  });
});
