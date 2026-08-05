import { describe, expect, it } from "vitest";

import {
  customRange,
  isCustom,
  pastDays,
  presetRange,
  toDayRange,
  toIsoRange,
} from "./timeRange";

// The overview's graphs read different endpoints — some take ISO instants,
// some take calendar days, one takes a plain day count. One range has to
// translate into all three without drifting by a day at the edges.

const NOW = new Date("2026-06-30T12:00:00Z");

describe("presetRange", () => {
  it("resolves each preset to a first day, open at the top", () => {
    expect(presetRange("7d", NOW)).toEqual({ span: "7d", from: "2026-06-23", to: null });
    expect(presetRange("30d", NOW)).toEqual({ span: "30d", from: "2026-05-31", to: null });
    expect(presetRange("90d", NOW)).toEqual({ span: "90d", from: "2026-04-01", to: null });
  });

  it("treats season as the documented 180-day stopgap", () => {
    // Not a real season: the backend still exposes no season_start. Pinned so
    // that wiring real dates later is a visible, deliberate change.
    expect(presetRange("season", NOW).from).toBe("2026-01-01");
  });

  it("leaves all unbounded at both ends", () => {
    expect(presetRange("all", NOW)).toEqual({ span: "all", from: null, to: null });
  });
});

describe("custom ranges", () => {
  it("is distinguishable from a preset", () => {
    expect(isCustom(customRange("2026-01-01", "2026-02-01"))).toBe(true);
    expect(isCustom(presetRange("7d", NOW))).toBe(false);
  });
});

describe("toIsoRange", () => {
  it("widens calendar days to the instants that cover them", () => {
    // An `until` of the bare day would drop everything recorded that day.
    expect(toIsoRange(customRange("2026-01-01", "2026-02-01"))).toEqual({
      since: "2026-01-01T00:00:00Z",
      until: "2026-02-01T23:59:59Z",
    });
  });

  it("omits the ends that are open", () => {
    expect(toIsoRange({ span: "all", from: null, to: null })).toEqual({});
    expect(toIsoRange(presetRange("7d", NOW))).toEqual({ since: "2026-06-23T00:00:00Z" });
  });
});

describe("toDayRange", () => {
  it("closes an open top end at tomorrow so today is included", () => {
    // The weather timeseries takes an inclusive `to`; passing today would
    // race the last projection of the day.
    expect(toDayRange(presetRange("7d", NOW), NOW)).toEqual({
      from: "2026-06-23",
      to: "2026-07-01",
    });
  });

  it("keeps an explicit upper bound", () => {
    expect(toDayRange(customRange("2026-01-01", "2026-02-01"), NOW)).toEqual({
      from: "2026-01-01",
      to: "2026-02-01",
    });
  });

  it("omits from entirely for all", () => {
    expect(toDayRange({ span: "all", from: null, to: null }, NOW)).toEqual({ to: "2026-07-01" });
  });
});

describe("pastDays", () => {
  it("counts the days a bounded range covers", () => {
    expect(pastDays(presetRange("7d", NOW), 90, NOW)).toBe(7);
    expect(pastDays(customRange("2026-06-01", "2026-06-11"), 90, NOW)).toBe(10);
  });

  it("clamps, because a stitched chart cannot draw years of daily bars", () => {
    expect(pastDays(presetRange("season", NOW), 90, NOW)).toBe(90);
    expect(pastDays({ span: "all", from: null, to: null }, 90, NOW)).toBe(90);
  });

  it("never returns zero or negative days for a same-day or inverted range", () => {
    // A one-day window still has to ask for one day of history, or the
    // outlook renders an empty past slice beside a live forecast.
    expect(pastDays(customRange("2026-06-30", "2026-06-30"), 90, NOW)).toBe(1);
    expect(pastDays(customRange("2026-07-30", "2026-06-30"), 90, NOW)).toBe(1);
  });
});
