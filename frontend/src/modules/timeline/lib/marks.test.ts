import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { Polygon } from "geojson";

import type { TimelineEvent } from "@/api/timeline";
import { registerMarkerImages } from "@/modules/labs/map/markerIcons";
import type { FadedEvent } from "./frames";
import { buildBlockAnchors, buildBlockHighlights, buildMarks, markerIconFor } from "./marks";

const SQUARE: Polygon = {
  type: "Polygon",
  coordinates: [
    [
      [31.6, 30.6],
      [31.61, 30.6],
      [31.61, 30.61],
      [31.6, 30.61],
      [31.6, 30.6],
    ],
  ],
};

function event(over: Partial<TimelineEvent>): TimelineEvent {
  return {
    kind: "flag",
    id: "e1",
    at: "2026-06-03T09:00:00Z",
    day: "2026-06-03",
    block_id: "b1",
    block_name: "Block 1",
    block_code: "B1",
    code: null,
    title_en: "",
    title_ar: null,
    detail: null,
    severity: "warning",
    point: null,
    ...over,
  };
}

function faded(e: TimelineEvent, opacity = 1): FadedEvent {
  return { event: e, opacity };
}

// jsdom has no 2D canvas, and `registerMarkerImages` draws every marker on
// one. Without a stub `canvas2d` returns null, the registration loop skips
// silently, and the test below would pass against an empty registry — which
// is the exact silence it exists to catch. The stub records nothing and draws
// nothing; only the ids matter here.
let realGetContext: typeof HTMLCanvasElement.prototype.getContext;
let realPath2D: unknown;

function stubContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const noop = (): void => undefined;
  return new Proxy(
    {},
    {
      get(_target, prop) {
        if (prop === "canvas") return canvas;
        if (prop === "getImageData") {
          return () => ({
            width: canvas.width,
            height: canvas.height,
            data: new Uint8ClampedArray(canvas.width * canvas.height * 4),
          });
        }
        return noop;
      },
      set: () => true,
    },
  ) as CanvasRenderingContext2D;
}

beforeAll(() => {
  // `strokeGlyph` builds a `Path2D` per glyph, which jsdom also lacks. A
  // constructor that records its argument and nothing else is enough: the
  // stub context ignores what it is handed.
  const g = globalThis as unknown as Record<string, unknown>;
  realPath2D = g.Path2D;
  g.Path2D = class {
    constructor(readonly d?: string) {}
  };
  realGetContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function getContext(this: HTMLCanvasElement) {
    return stubContext(this);
    // Through `unknown`: the real signature is an overload set covering
    // webgl and bitmaprenderer too, and a 2D-only stub does not overlap it.
  } as unknown as typeof HTMLCanvasElement.prototype.getContext;
});

afterAll(() => {
  HTMLCanvasElement.prototype.getContext = realGetContext;
  (globalThis as unknown as Record<string, unknown>).Path2D = realPath2D;
});

describe("markerIconFor", () => {
  it("gives the three located kinds a shape and the block-scoped kinds none", () => {
    expect(markerIconFor(event({ kind: "alert", code: "irrigate" }))).toBeTruthy();
    expect(markerIconFor(event({ kind: "flag" }))).toBeTruthy();
    expect(markerIconFor(event({ kind: "signal" }))).toBeTruthy();
    expect(markerIconFor(event({ kind: "visit" }))).toBeTruthy();
    // A stage, an activity and a recommendation are properties of a BLOCK,
    // not of a spot in it. A pin would invent precision nobody recorded.
    expect(markerIconFor(event({ kind: "stage" }))).toBeNull();
    expect(markerIconFor(event({ kind: "activity" }))).toBeNull();
    expect(markerIconFor(event({ kind: "recommendation" }))).toBeNull();
  });

  it("only ever names images that are actually registered", () => {
    // The failure this guards is silent: MapLibre draws NOTHING for an
    // `icon-image` it cannot resolve, with no error. Collect what the
    // registration loop creates and check every id this module can emit is
    // in that set.
    const registered = new Set<string>();
    const fakeMap = {
      hasImage: () => false,
      addImage: (id: string) => registered.add(id),
      loadImage: () => undefined,
    };
    registerMarkerImages(fakeMap as never);

    const emitted = [
      markerIconFor(event({ kind: "alert", code: "irrigate", severity: "critical" })),
      markerIconFor(event({ kind: "alert", code: "not_a_verb", severity: "info" })),
      markerIconFor(event({ kind: "alert", code: null, severity: null })),
      markerIconFor(event({ kind: "flag", severity: "warning" })),
      markerIconFor(event({ kind: "flag", severity: "critical" })),
      markerIconFor(event({ kind: "signal" })),
      markerIconFor(event({ kind: "visit" })),
    ].filter((id): id is string => id !== null);

    expect(emitted.length).toBe(7);
    for (const id of emitted) expect(registered).toContain(id);
  });
});

describe("buildBlockAnchors", () => {
  it("places the anchor inside the block", () => {
    const anchors = buildBlockAnchors([{ id: "b1", boundary: SQUARE }]);
    const [lon, lat] = anchors.get("b1")!;
    expect(lon).toBeGreaterThanOrEqual(31.6);
    expect(lon).toBeLessThanOrEqual(31.61);
    expect(lat).toBeGreaterThanOrEqual(30.6);
    expect(lat).toBeLessThanOrEqual(30.61);
  });

  it("skips a block with no boundary rather than inventing one", () => {
    expect(buildBlockAnchors([{ id: "b1", boundary: null }]).size).toBe(0);
  });
});

describe("buildMarks", () => {
  const anchors = buildBlockAnchors([{ id: "b1", boundary: SQUARE }]);

  it("uses the event's own coordinate when it has one", () => {
    const e = event({
      kind: "flag",
      point: { type: "Point", coordinates: [31.605, 30.605] },
    });
    const fc = buildMarks([faded(e)], anchors);
    expect(fc.features[0].geometry.coordinates).toEqual([31.605, 30.605]);
  });

  it("borrows the block anchor when the row records no coordinate", () => {
    const fc = buildMarks([faded(event({ point: null }))], anchors);
    expect(fc.features).toHaveLength(1);
    expect(fc.features[0].geometry.coordinates).toEqual(anchors.get("b1"));
  });

  it("drops an event with neither a point nor a known block", () => {
    // There is nowhere honest to put it, and a mark at [0,0] would land in
    // the Gulf of Guinea.
    const fc = buildMarks([faded(event({ point: null, block_id: "gone" }))], anchors);
    expect(fc.features).toHaveLength(0);
  });

  it("carries the fade opacity onto the feature", () => {
    const fc = buildMarks([faded(event({}), 0.4)], anchors);
    expect(fc.features[0].properties.opacity).toBe(0.4);
  });

  it("sorts a fresh critical mark ahead of a stale one", () => {
    const fresh = buildMarks([faded(event({ severity: "critical" }), 1)], anchors);
    const stale = buildMarks([faded(event({ severity: "critical" }), 0.4)], anchors);
    expect(fresh.features[0].properties.sort_key).toBeLessThan(
      stale.features[0].properties.sort_key,
    );
  });
});

describe("buildBlockHighlights", () => {
  it("lights a block for a stage, an activity or a recommendation", () => {
    const h = buildBlockHighlights([
      faded(event({ kind: "activity", block_id: "b1" }), 0.6),
      faded(event({ kind: "stage", block_id: "b2" }), 1),
    ]);
    expect(h.get("b1")).toBe(0.6);
    expect(h.get("b2")).toBe(1);
  });

  it("ignores the kinds that draw their own mark", () => {
    const h = buildBlockHighlights([faded(event({ kind: "alert", block_id: "b1" }))]);
    expect(h.size).toBe(0);
  });

  it("keeps the freshest when a block carries several", () => {
    const h = buildBlockHighlights([
      faded(event({ kind: "activity", id: "a", block_id: "b1" }), 0.4),
      faded(event({ kind: "stage", id: "b", block_id: "b1" }), 1),
    ]);
    expect(h.get("b1")).toBe(1);
  });
});
