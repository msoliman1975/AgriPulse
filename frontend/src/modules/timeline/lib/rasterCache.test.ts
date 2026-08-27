// The raster cache — the part of the replay that decides what the map is
// painting and what it is quietly loading.
//
// Tested against a fake map rather than MapLibre, for the same reason
// `rasterSource.test.ts` exists: jsdom has no WebGL, so a real map cannot
// be constructed, and the bug class this guards is a decision (which layer
// is at which opacity, which sources were kept) rather than a pixel.
//
// The fake records every source, layer and paint write in order, which is
// what lets "the outgoing pass was held until the incoming one loaded" be
// asserted at all. That sequencing was invisible to every test before
// this: the old code did the swap inside an effect and handed the result
// straight to MapLibre.

import type { Map as MlMap } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import { syncRasters, type RasterCache, type RasterFrame } from "./rasterCache";

/** A map stand-in that records what was added, removed and painted. */
function fakeMap(loaded: (id: string) => boolean = () => true) {
  const sources = new Set<string>();
  const layers = new Set<string>();
  const opacity = new Map<string, number>();
  const listeners = new Map<string, (() => void)[]>();
  const map = {
    getSource: (id: string) => (sources.has(id) ? {} : undefined),
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    addSource: (id: string) => sources.add(id),
    addLayer: (spec: { id: string }) => layers.add(spec.id),
    removeLayer: (id: string) => layers.delete(id),
    removeSource: (id: string) => sources.delete(id),
    isSourceLoaded: (id: string) => loaded(id),
    setPaintProperty: (id: string, prop: string, value: unknown) => {
      if (prop === "raster-opacity") opacity.set(id, value as number);
    },
    on: (event: string, fn: () => void) => {
      listeners.set(event, [...(listeners.get(event) ?? []), fn]);
    },
    off: (event: string, fn: () => void) => {
      listeners.set(
        event,
        (listeners.get(event) ?? []).filter((f) => f !== fn),
      );
    },
    emit: (event: string) => [...(listeners.get(event) ?? [])].forEach((fn) => fn()),
  };
  return { map, sources, layers, opacity, listeners };
}

function frame(key: string): RasterFrame {
  return { key, layers: [{ id: "__farm__", tileUrl: `https://t/${key}/{z}/{x}/{y}.png` }] };
}

/** The one layer id a single-layer frame owns, whatever the naming rule is. */
function only(cache: RasterCache, key: string): string {
  const ids = cache.get(key);
  expect(ids).toHaveLength(1);
  return ids![0];
}

function sync(
  map: ReturnType<typeof fakeMap>["map"],
  cache: RasterCache,
  genRef: { current: number },
  frames: RasterFrame[],
  activeKey: string | null,
): void {
  // The fake implements the handful of methods `syncRasters` calls, which
  // is a long way short of MapLibre's surface — hence the double cast.
  syncRasters(map as unknown as MlMap, {
    frames,
    activeKey,
    fadeMs: 200,
    cache: { current: cache },
    genRef,
  });
}

describe("syncRasters", () => {
  it("adds every frame it is given but paints only the active one", () => {
    const { map, opacity } = fakeMap();
    const cache: RasterCache = new Map();
    const genRef = { current: 0 };
    const frames = [frame("p1"), frame("p2"), frame("p3")];

    sync(map, cache, genRef, frames, "p1");

    // The preloads are ON the map. That is the whole point: a raster layer
    // at zero opacity still loads its tiles, so the pass the replay is
    // about to reach is already there when it reaches it.
    expect(cache.size).toBe(3);
    expect(opacity.get(only(cache, "p1"))).toBe(0.85);
    expect(opacity.get(only(cache, "p2"))).toBe(0);
    expect(opacity.get(only(cache, "p3"))).toBe(0);
  });

  it("swaps passes without re-adding either", () => {
    const { map, opacity, sources } = fakeMap();
    const cache: RasterCache = new Map();
    const genRef = { current: 0 };
    const frames = [frame("p1"), frame("p2")];

    sync(map, cache, genRef, frames, "p1");
    const added = new Set(sources);
    sync(map, cache, genRef, frames, "p2");

    // No source churn. The old code removed the outgoing pass and added
    // the incoming one on every swap, which threw away tiles that had just
    // been paid for and re-fetched them on a scrub backwards.
    expect(sources).toEqual(added);
    expect(opacity.get(only(cache, "p1"))).toBe(0);
    expect(opacity.get(only(cache, "p2"))).toBe(0.85);
  });

  it("holds the outgoing pass until the incoming one has its tiles", () => {
    let ready = false;
    const { map, opacity } = fakeMap((id) => (id.includes("p2") ? ready : true));
    const cache: RasterCache = new Map();
    const genRef = { current: 0 };
    const frames = [frame("p1"), frame("p2")];

    sync(map, cache, genRef, frames, "p1");
    sync(map, cache, genRef, frames, "p2");

    // Nothing painted yet: fading to a source with no tiles shows bare
    // satellite for the length of the fade, which is the gap this exists
    // to close.
    expect(opacity.get(only(cache, "p1"))).toBe(0.85);
    expect(opacity.get(only(cache, "p2"))).toBe(0);

    ready = true;
    map.emit("sourcedata");

    expect(opacity.get(only(cache, "p1"))).toBe(0);
    expect(opacity.get(only(cache, "p2"))).toBe(0.85);
  });

  it("does not paint a pass the reader has already scrubbed away from", () => {
    let ready = false;
    const { map, opacity } = fakeMap((id) => (id.includes("p2") ? ready : true));
    const cache: RasterCache = new Map();
    const genRef = { current: 0 };
    const frames = [frame("p1"), frame("p2"), frame("p3")];

    sync(map, cache, genRef, frames, "p2"); // waiting on p2's tiles
    sync(map, cache, genRef, frames, "p3"); // reader moved on

    ready = true;
    map.emit("sourcedata");

    // p2's held swap must not fire. This is the "map kept switching to
    // earlier dates after the run had ended" failure, in one assertion.
    expect(opacity.get(only(cache, "p2"))).toBe(0);
    expect(opacity.get(only(cache, "p3"))).toBe(0.85);
  });

  it("drops old frames past the cap but never the active one or a preload", () => {
    const { map } = fakeMap();
    const cache: RasterCache = new Map();
    const genRef = { current: 0 };

    // Walk a play head through twenty passes, three preloaded ahead.
    const all = Array.from({ length: 20 }, (_, i) => frame(`p${i}`));
    for (let i = 0; i < all.length; i += 1) {
      sync(map, cache, genRef, all.slice(i, i + 4), `p${i}`);
    }

    expect(cache.size).toBeLessThanOrEqual(12);
    expect(cache.has("p19")).toBe(true);
    // The oldest went first, which for a forward replay is the frames
    // furthest behind the play head.
    expect(cache.has("p0")).toBe(false);
  });

  it("paints nothing when the caller names no active frame", () => {
    const { map, opacity } = fakeMap();
    const cache: RasterCache = new Map();
    const genRef = { current: 0 };
    const frames = [frame("p1")];

    // What "pixels off" and "no pass yet" both look like from here. The
    // frame stays cached, so switching pixels back on is a paint write.
    sync(map, cache, genRef, frames, null);

    expect(cache.size).toBe(1);
    expect(opacity.get(only(cache, "p1"))).toBe(0);
  });
});
