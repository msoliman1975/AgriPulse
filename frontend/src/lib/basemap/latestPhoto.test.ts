import { describe, expect, it, vi } from "vitest";
import type { Map as MapLibreMap } from "maplibre-gl";

import { applyLatestPhoto, PHOTO_LAYER_ID, PHOTO_SOURCE_ID } from "./latestPhoto";

/** Just enough of a MapLibre map to watch layers come and go. */
function fakeMap(layerIds: string[]) {
  const layers = layerIds.map((id) => ({ id }));
  const sources = new Map<string, { tiles?: string[] }>();
  const visibility = new Map<string, string>();
  const map = {
    style: { _loaded: true },
    once: vi.fn(),
    getStyle: () => ({ layers }),
    getSource: (id: string) => sources.get(id),
    addSource: (id: string, spec: { tiles?: string[] }) => sources.set(id, spec),
    removeSource: (id: string) => sources.delete(id),
    getLayer: (id: string) => layers.find((l) => l.id === id),
    addLayer: (layer: { id: string }, before?: string) => {
      const at = before ? layers.findIndex((l) => l.id === before) : -1;
      if (at < 0) layers.push(layer);
      else layers.splice(at, 0, layer);
    },
    removeLayer: (id: string) =>
      layers.splice(
        layers.findIndex((l) => l.id === id),
        1,
      ),
    setLayoutProperty: (id: string, _k: string, v: string) => visibility.set(id, v),
  };
  return { map: map as unknown as MapLibreMap, layers, sources, visibility };
}

describe("applyLatestPhoto", () => {
  it("slots the photo directly above the satellite base, under the page's layers", () => {
    const f = fakeMap(["background", "satellite", "blocks-fill", "blocks-line"]);
    applyLatestPhoto(f.map, "https://tiles/a/{z}/{x}/{y}.png", true);
    expect(f.layers.map((l) => l.id)).toEqual([
      "background",
      "satellite",
      PHOTO_LAYER_ID,
      "blocks-fill",
      "blocks-line",
    ]);
    expect(f.sources.get(PHOTO_SOURCE_ID)).toMatchObject({ tileSize: 512 });
    expect(f.visibility.get(PHOTO_LAYER_ID)).toBe("visible");
  });

  it("hides rather than removes when the high-res base is picked", () => {
    const f = fakeMap(["satellite"]);
    applyLatestPhoto(f.map, "u1", true);
    applyLatestPhoto(f.map, "u1", false);
    expect(f.layers.map((l) => l.id)).toEqual(["satellite", PHOTO_LAYER_ID]);
    expect(f.visibility.get(PHOTO_LAYER_ID)).toBe("none");
  });

  it("swaps the source for a newer pass and removes it when there is none", () => {
    const f = fakeMap(["satellite", "outline"]);
    applyLatestPhoto(f.map, "u1", true);
    applyLatestPhoto(f.map, "u2", true);
    expect(f.sources.get(PHOTO_SOURCE_ID)?.tiles).toEqual(["u2"]);
    expect(f.layers.map((l) => l.id)).toEqual(["satellite", PHOTO_LAYER_ID, "outline"]);
    applyLatestPhoto(f.map, null, true);
    expect(f.sources.has(PHOTO_SOURCE_ID)).toBe(false);
    expect(f.layers.map((l) => l.id)).toEqual(["satellite", "outline"]);
  });

  it("limits the photo to the farm's box when given one", () => {
    const f = fakeMap(["satellite"]);
    applyLatestPhoto(f.map, "u1", true, [32.63, 30.07, 32.64, 30.08]);
    expect(f.sources.get(PHOTO_SOURCE_ID)).toMatchObject({ bounds: [32.63, 30.07, 32.64, 30.08] });
  });

  it("waits for a style that is still loading", () => {
    const f = fakeMap(["satellite"]);
    // Tiles in flight do not matter, only whether the style document loaded.
    (f.map as unknown as { style: { _loaded: boolean } }).style._loaded = false;
    applyLatestPhoto(f.map, "u1", true);
    expect(f.map.once).toHaveBeenCalledWith("load", expect.any(Function));
    expect(f.sources.size).toBe(0);
  });
});
