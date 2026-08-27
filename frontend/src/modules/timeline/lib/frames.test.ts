import { describe, expect, it } from "vitest";

import type { FarmScene } from "@/api/imagery";
import type { TimelineEvent } from "@/api/timeline";
import {
  buildFrames,
  daysBetween,
  drawablePasses,
  eventOpacity,
  FADE_DAYS,
  frameIndexOf,
  passForFrames,
  passSequence,
  visibleEvents,
} from "./frames";

function scene(over: Partial<FarmScene>): FarmScene {
  return {
    scene_date: "2026-06-01",
    at: "2026-06-01T08:30:00Z",
    block_count: 3,
    succeeded_count: 3,
    skipped_cloud_count: 0,
    computed_count: 3,
    cloud_cover_pct: "1.0",
    ...over,
  };
}

function event(day: string, over: Partial<TimelineEvent> = {}): TimelineEvent {
  return {
    kind: "flag",
    id: `e-${day}`,
    at: `${day}T09:00:00Z`,
    day,
    block_id: "b1",
    block_name: "Block 1",
    block_name_ar: null,
    block_code: "B1",
    code: null,
    title_en: "note",
    title_ar: null,
    detail: null,
    severity: "warning",
    point: null,
    ...over,
  };
}

describe("buildFrames", () => {
  it("includes both ends", () => {
    expect(buildFrames("2026-06-01", "2026-06-04")).toEqual([
      "2026-06-01",
      "2026-06-02",
      "2026-06-03",
      "2026-06-04",
    ]);
  });

  it("is one frame for a single day", () => {
    expect(buildFrames("2026-06-01", "2026-06-01")).toEqual(["2026-06-01"]);
  });

  it("crosses a month boundary without repeating or skipping a day", () => {
    const frames = buildFrames("2026-05-30", "2026-06-02");
    expect(frames).toEqual(["2026-05-30", "2026-05-31", "2026-06-01", "2026-06-02"]);
  });

  it("crosses a DST change in the viewer's zone without dropping a day", () => {
    // Every day key here is a UTC midnight, so a local clock shifting by an
    // hour cannot land two frames on one date — which is what a local-time
    // Date walk does on the last Sunday in March.
    const frames = buildFrames("2026-03-27", "2026-03-31");
    expect(frames).toEqual(["2026-03-27", "2026-03-28", "2026-03-29", "2026-03-30", "2026-03-31"]);
  });

  it("is empty when the window is reversed", () => {
    expect(buildFrames("2026-06-04", "2026-06-01")).toEqual([]);
  });
});

describe("daysBetween", () => {
  it("counts forward and backward", () => {
    expect(daysBetween("2026-06-01", "2026-06-04")).toBe(3);
    expect(daysBetween("2026-06-04", "2026-06-01")).toBe(-3);
    expect(daysBetween("2026-06-01", "2026-06-01")).toBe(0);
  });
});

describe("drawablePasses", () => {
  it("drops a pass whose indices never ran", () => {
    // A day that is entirely "succeeded" but has no computed rasters draws
    // nothing. Carrying it forward would blank the map under a scrubber
    // saying a pass happened.
    const passes = drawablePasses([
      scene({ scene_date: "2026-06-01", computed_count: 3 }),
      scene({ scene_date: "2026-06-06", computed_count: 0 }),
      scene({ scene_date: "2026-06-11", computed_count: 2 }),
    ]);
    expect(passes.map((p) => p.day)).toEqual(["2026-06-01", "2026-06-11"]);
  });

  it("sorts oldest first whatever order the api answered in", () => {
    const passes = drawablePasses([
      scene({ scene_date: "2026-06-11" }),
      scene({ scene_date: "2026-06-01" }),
    ]);
    expect(passes.map((p) => p.day)).toEqual(["2026-06-01", "2026-06-11"]);
  });
});

describe("passForFrames", () => {
  const frames = buildFrames("2026-06-01", "2026-06-08");
  const passes = [
    { day: "2026-06-03", at: "2026-06-03T08:00:00Z" },
    { day: "2026-06-07", at: "2026-06-07T08:10:00Z" },
  ];

  it("carries the last pass forward until the next one", () => {
    const map = passForFrames(frames, passes);
    expect(map.get("2026-06-03")?.day).toBe("2026-06-03");
    expect(map.get("2026-06-04")?.day).toBe("2026-06-03");
    expect(map.get("2026-06-06")?.day).toBe("2026-06-03");
    expect(map.get("2026-06-07")?.day).toBe("2026-06-07");
    expect(map.get("2026-06-08")?.day).toBe("2026-06-07");
  });

  it("draws nothing before the first pass", () => {
    // Reaching backwards for the first pass would show a reader ground
    // that had not been sensed on the date they are looking at.
    const map = passForFrames(frames, passes);
    expect(map.get("2026-06-01")).toBeNull();
    expect(map.get("2026-06-02")).toBeNull();
  });

  it("answers null for every frame when there are no passes", () => {
    const map = passForFrames(frames, []);
    expect([...map.values()].every((v) => v === null)).toBe(true);
  });
});

describe("eventOpacity", () => {
  it("is full on the event's own day", () => {
    expect(eventOpacity("2026-06-03", "2026-06-03")).toBe(1);
  });

  it("is zero for a day that has not happened yet on this frame", () => {
    expect(eventOpacity("2026-06-05", "2026-06-03")).toBe(0);
  });

  it("is zero once the event is past the fade window", () => {
    expect(eventOpacity("2026-06-03", `2026-06-0${3 + FADE_DAYS + 1}`)).toBe(0);
  });

  it("decreases with age but never reaches an invisible floor", () => {
    const one = eventOpacity("2026-06-03", "2026-06-04");
    const three = eventOpacity("2026-06-03", "2026-06-06");
    expect(one).toBeGreaterThan(three);
    // A mark at ~0 opacity is unreadable but still holds a collision slot,
    // so it would hide the mark behind it while showing nothing itself.
    expect(three).toBeGreaterThan(0.2);
  });
});

describe("visibleEvents", () => {
  const events = [
    event("2026-06-01"),
    event("2026-06-03"),
    event("2026-06-06"),
    event("2026-06-08"),
  ];

  it("keeps the day itself and the fade window, and drops the rest", () => {
    const visible = visibleEvents(events, "2026-06-06");
    expect(visible.map((v) => v.event.day)).toContain("2026-06-06");
    expect(visible.map((v) => v.event.day)).toContain("2026-06-03");
    // Five days back is outside the window; the future one is not yet.
    expect(visible.map((v) => v.event.day)).not.toContain("2026-06-01");
    expect(visible.map((v) => v.event.day)).not.toContain("2026-06-08");
  });

  it("puts the freshest last, so it is drawn on top", () => {
    const visible = visibleEvents(events, "2026-06-06");
    expect(visible[visible.length - 1].event.day).toBe("2026-06-06");
  });
});

describe("frameIndexOf", () => {
  const frames = buildFrames("2026-06-01", "2026-06-05");

  it("finds a day that survived a window change", () => {
    expect(frameIndexOf(frames, "2026-06-03")).toBe(2);
  });

  it("reports -1 for a day the new window does not hold", () => {
    expect(frameIndexOf(frames, "2026-07-03")).toBe(-1);
    expect(frameIndexOf(frames, null)).toBe(-1);
  });
});

describe("passSequence", () => {
  it("names each pass once, in the order the replay reaches it", () => {
    const frames = buildFrames("2026-06-01", "2026-06-10");
    const passes = drawablePasses([
      scene({ scene_date: "2026-06-03", at: "2026-06-03T08:30:00Z" }),
      scene({ scene_date: "2026-06-08", at: "2026-06-08T08:30:00Z" }),
    ]);
    const byFrame = passForFrames(frames, passes);

    // Ten frames, two passes. Carry-forward means five consecutive frames
    // resolve to one pass, and what the prefetch and the preload window
    // both want is "what will be drawn next", not "what is drawn tomorrow".
    expect(passSequence(frames, byFrame).map((p) => p.day)).toEqual(["2026-06-03", "2026-06-08"]);
  });

  it("leaves out a pass the window never reaches", () => {
    const frames = buildFrames("2026-06-01", "2026-06-05");
    const passes = drawablePasses([
      scene({ scene_date: "2026-06-02", at: "2026-06-02T08:30:00Z" }),
      scene({ scene_date: "2026-06-20", at: "2026-06-20T08:30:00Z" }),
    ]);

    // Prefetching a pass outside the window would spend a request on a
    // frame that cannot be scrubbed to.
    expect(passSequence(frames, passForFrames(frames, passes)).map((p) => p.day)).toEqual([
      "2026-06-02",
    ]);
  });

  it("is empty when no frame has an image", () => {
    const frames = buildFrames("2026-06-01", "2026-06-05");
    expect(passSequence(frames, passForFrames(frames, []))).toEqual([]);
  });
});
