// Guards for the two defects that made the screen awkward to use on first
// open. Both are layout and imperative-map bugs, which jsdom cannot
// measure — it reports every height as 0 and has no WebGL — so neither is
// provable by rendering. These pin the two facts that ARE checkable and
// that were false when the bugs shipped.
//
// Being explicit about the limit: a green run here does not prove the rail
// scrolls or the map frames the farm. It proves the flex chain is declared
// unbroken and that the bounds helper answers correctly. The behaviour
// itself was verified on prod, and that verification is the real evidence.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";

import { setupTestI18n } from "@/i18n/testing";
import { boundsOf } from "../lib/mapBounds";
import type { BlockFeatureProps } from "./TimelineMap";
import { EventRail } from "./EventRail";
import type { FadedEvent } from "../lib/frames";
import type { TimelineEvent } from "@/api/timeline";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: "" } }) }));

// ---------------------------------------------------------------------------
// The rail's scroll chain
// ---------------------------------------------------------------------------

function event(i: number): TimelineEvent {
  return {
    kind: "alert",
    id: `a${i}`,
    at: "2026-08-05T09:00:00Z",
    day: "2026-08-05",
    block_id: "b1",
    block_name: "North ridge",
    block_code: "B-01",
    code: "inspect",
    title_en: `Alert number ${i}`,
    title_ar: null,
    detail: "grid:ndvi_spatial_anomaly",
    severity: "critical",
    point: null,
  };
}

const BUSY: FadedEvent[] = Array.from({ length: 108 }, (_, i) => ({
  event: event(i),
  opacity: 1,
}));

describe("event rail scroll chain", () => {
  it("puts every row behind ONE scroll container, not on the page", async () => {
    // 108 is not arbitrary: it is what this farm actually recorded on
    // 5 August 2026, and it is the day the bug was reported on. With the
    // chain broken the rail rendered all 108 at full height and pushed the
    // scrubber below the fold.
    await setupTestI18n("en");
    const { container } = render(
      <EventRail
        frameDay="2026-08-05"
        visible={BUSY}
        omittedKinds={[]}
        truncated={false}
        focusedEventId={null}
        onFocusEvent={() => undefined}
        formatDay={(d) => d}
        formatTime={(t) => t}
      />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(108);

    const scroller = container.querySelector(".overflow-y-auto");
    expect(scroller, "the rail has no scroll container at all").toBeTruthy();

    // Every row must live inside that scroller. A row outside it is a row
    // that grows the page.
    for (const li of screen.getAllByRole("listitem")) {
      expect(scroller!.contains(li)).toBe(true);
    }

    // The scroller declares `flex-1 min-h-0`, and `flex-1` is meaningless
    // unless its PARENT is a flex container. That parent is the element
    // that was wrong: a Card with a title wraps its children in a plain
    // <div>, so the scroller's `flex-1` resolved against a block box, its
    // height became content height, and `overflow-y-auto` never engaged.
    //
    // Asserting on the parent specifically, not on "some ancestor has
    // flex-1" — the first version of this test did the latter, filtered
    // the offending <div> out because it had no flex-1 of its own, and
    // passed on the broken code.
    expect(scroller!.className).toContain("flex-1");
    expect(scroller!.className).toContain("min-h-0");

    const parent = scroller!.parentElement!;
    expect(
      parent.className.split(/\s+/),
      `the scroller's parent is not a flex container, so its flex-1 does ` +
        `nothing: "${parent.className}"`,
    ).toContain("flex");
    expect(
      parent.className,
      `the scroller's parent must shrink below its content: "${parent.className}"`,
    ).toContain("min-h-0");
  });
});

// ---------------------------------------------------------------------------
// The bounds the map frames on
// ---------------------------------------------------------------------------

function blocks(...polys: Polygon[]): FeatureCollection<Polygon, BlockFeatureProps> {
  return {
    type: "FeatureCollection",
    features: polys.map((geometry, i) => ({
      type: "Feature",
      geometry,
      properties: { block_id: `b${i}`, block_name: `B${i}`, highlight: 0 },
    })),
  };
}

const SQUARE: Polygon = {
  type: "Polygon",
  coordinates: [
    [
      [31.6, 30.6],
      [31.62, 30.6],
      [31.62, 30.62],
      [31.6, 30.62],
      [31.6, 30.6],
    ],
  ],
};

describe("boundsOf", () => {
  it("is null before any block has loaded", () => {
    // This is the state the map mounts in on a cold load, and the reason
    // the constructor's `bounds` option cannot frame the farm on its own.
    expect(boundsOf(blocks(), null)).toBeNull();
  });

  it("frames the blocks once they arrive", () => {
    expect(boundsOf(blocks(SQUARE), null)).toEqual([
      [31.6, 30.6],
      [31.62, 30.62],
    ]);
  });

  it("includes the farm boundary, so a farm wider than its blocks still fits", () => {
    const aoi: MultiPolygon = {
      type: "MultiPolygon",
      coordinates: [
        [
          [
            [31.5, 30.5],
            [31.7, 30.5],
            [31.7, 30.7],
            [31.5, 30.7],
            [31.5, 30.5],
          ],
        ],
      ],
    };
    expect(boundsOf(blocks(SQUARE), aoi)).toEqual([
      [31.5, 30.5],
      [31.7, 30.7],
    ]);
  });

  it("frames from the AOI alone when a farm has no blocks yet", () => {
    const aoi: MultiPolygon = {
      type: "MultiPolygon",
      coordinates: [
        [
          [
            [31.5, 30.5],
            [31.7, 30.5],
            [31.7, 30.7],
            [31.5, 30.7],
            [31.5, 30.5],
          ],
        ],
      ],
    };
    expect(boundsOf(blocks(), aoi)).toEqual([
      [31.5, 30.5],
      [31.7, 30.7],
    ]);
  });
});
