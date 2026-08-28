import { describe, expect, it } from "vitest";

import { cellDateGap } from "./cellDateGap";

const SCENES = [
  { scene_date: "2026-08-25", computed_count: 36 },
  { scene_date: "2026-08-20", computed_count: 36 },
  { scene_date: "2025-07-23", computed_count: 36 },
];

describe("cellDateGap", () => {
  it("reports the gap when the drawn day is older than the selected day", () => {
    // The case Mohamed reported: the strip is on an August 2026 pass and every
    // cell still carries a July 2025 reading, because that is as far as the
    // cell backfill had reached.
    expect(
      cellDateGap({
        cellTimes: ["2025-07-23T08:41:47.247000+00:00", "2025-07-23T08:41:47.247000+00:00"],
        sceneDate: "2026-08-25",
        scenes: SCENES,
      }),
    ).toEqual({ drawn: "2025-07-23", wanted: "2026-08-25", dayCount: 1 });
  });

  it("stays silent when the cells are on the selected day", () => {
    expect(
      cellDateGap({
        cellTimes: ["2026-08-25T08:41:47.247000+00:00"],
        sceneDate: "2026-08-25",
        scenes: SCENES,
      }),
    ).toBeNull();
  });

  it("counts the days when blocks disagree, and names the newest", () => {
    const gap = cellDateGap({
      cellTimes: [
        "2025-07-23T08:41:47.247000+00:00",
        "2025-06-11T08:41:47.247000+00:00",
        "2025-07-23T08:41:47.247000+00:00",
      ],
      sceneDate: "2026-08-25",
      scenes: SCENES,
    });
    expect(gap).toEqual({ drawn: "2025-07-23", wanted: "2026-08-25", dayCount: 2 });
  });

  it("takes the UTC day of an instant, not the reader's local day", () => {
    // 00:30 UTC on the 24th is still the 23rd in every negative offset. Taking
    // the local day here is what put the whole scene strip a day out in #494.
    const gap = cellDateGap({
      cellTimes: ["2025-07-24T00:30:00+00:00"],
      sceneDate: "2026-08-25",
      scenes: SCENES,
    });
    expect(gap?.drawn).toBe("2025-07-24");
  });

  it("compares against the newest drawable day when no day is selected", () => {
    expect(
      cellDateGap({
        cellTimes: ["2025-07-23T08:41:47.247000+00:00"],
        sceneDate: null,
        scenes: SCENES,
      }),
    ).toEqual({ drawn: "2025-07-23", wanted: "2026-08-25", dayCount: 1 });
  });

  it("does not blame a day that draws nothing", () => {
    // The newest pass was lost to cloud, so it computed no raster. The map
    // never offered to draw it, and naming it as the day the reader wanted
    // would warn on every farm whose last pass was cloudy.
    expect(
      cellDateGap({
        cellTimes: ["2026-08-20T08:41:47.247000+00:00"],
        sceneDate: null,
        scenes: [
          { scene_date: "2026-08-25", computed_count: 0 },
          { scene_date: "2026-08-20", computed_count: 36 },
        ],
      }),
    ).toBeNull();
  });

  it("stays silent when no cell carries a reading", () => {
    // A farm whose backfill never ran at all. GridCellPopup already says that
    // in its own words; a day-gap notice would name a day nothing shows.
    expect(cellDateGap({ cellTimes: [], sceneDate: "2026-08-25", scenes: SCENES })).toBeNull();
    expect(
      cellDateGap({ cellTimes: [null, null], sceneDate: "2026-08-25", scenes: SCENES }),
    ).toBeNull();
  });

  it("stays silent when there is no timeline to disagree with", () => {
    expect(
      cellDateGap({
        cellTimes: ["2025-07-23T08:41:47.247000+00:00"],
        sceneDate: null,
        scenes: [],
      }),
    ).toBeNull();
  });
});
