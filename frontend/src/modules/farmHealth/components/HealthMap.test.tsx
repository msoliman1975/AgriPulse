// What the map does to MapLibre, driven against a fake one.
//
// jsdom has no WebGL, so a real map cannot mount here. That gap let two
// defects reach production: the data effects were gated on a ref and so
// never re-ran once the map finished loading, and a block with no cell
// verdicts collapsed the image source to four identical corners, which
// killed the page with "x=Infinity, y=Infinity, z=Infinity outside of
// bounds".
//
// This fake records the calls. It cannot prove the map looks right, but it
// proves the two things that were wrong: that the layers are fed at all,
// and that a zero-area image is never handed over.

import { render, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { StatusCode } from "@/api/farmHealth";
import { HealthMap, type MapBlock, type MapCell } from "./HealthMap";

interface FakeSource {
  setData: ReturnType<typeof vi.fn>;
  setCoordinates: ReturnType<typeof vi.fn>;
  updateImage: ReturnType<typeof vi.fn>;
}

const fake = vi.hoisted(() => {
  const state = {
    loadHandler: null as (() => void) | null,
    sources: new Map<string, FakeSource>(),
    layout: [] as { layer: string; prop: string; value: unknown }[],
    fitBounds: vi.fn(),
    layers: [] as Record<string, unknown>[],
  };
  return state;
});

vi.mock("maplibre-gl", () => {
  class FakeMap {
    constructor() {
      fake.sources.clear();
      fake.layout.length = 0;
      fake.layers.length = 0;
    }
    on(event: string, a: unknown, b?: unknown) {
      if (event === "load" && typeof a === "function") fake.loadHandler = a as () => void;
      void b;
    }
    addControl() {}
    addSource(id: string) {
      fake.sources.set(id, {
        setData: vi.fn(),
        setCoordinates: vi.fn(),
        updateImage: vi.fn(),
      });
    }
    addLayer(layer: Record<string, unknown>) {
      fake.layers.push(layer);
    }
    getSource(id: string) {
      return fake.sources.get(id);
    }
    setLayoutProperty(layer: string, prop: string, value: unknown) {
      fake.layout.push({ layer, prop, value });
    }
    fitBounds(...args: unknown[]) {
      fake.fitBounds(...args);
    }
    getCanvas() {
      return { style: {} };
    }
    resize() {}
    remove() {}
  }
  return {
    default: {
      Map: FakeMap,
      NavigationControl: class {},
      AttributionControl: class {},
    },
  };
});

function block(id: string, selected: boolean): MapBlock {
  return {
    blockId: id,
    code: id,
    selected,
    boundary: {
      type: "Polygon",
      coordinates: [
        [
          [31, 30],
          [31.01, 30],
          [31.01, 30.01],
          [31, 30.01],
          [31, 30],
        ],
      ],
    },
  };
}

function cell(row: number, col: number, status: StatusCode = "good"): MapCell {
  const size = 0.001;
  const west = 31 + col * size;
  const south = 30 - row * size;
  return {
    cellId: `${row}:${col}`,
    row,
    col,
    status,
    ring: [
      [west, south],
      [west + size, south],
      [west + size, south + size],
      [west, south + size],
      [west, south],
    ],
  };
}

const colorOf = () => "#6FBF4B";

beforeAll(() => {
  // jsdom's canvas has no 2D context, so the paint step would bail before
  // it ever reached setCoordinates. The drawing itself is covered by
  // cellRaster.test.ts; this file only needs the paint to complete so the
  // coordinates handed to MapLibre can be asserted.
  const ctx = {
    canvas: { width: 512, height: 512 },
    filter: "none",
    fillStyle: "",
    clearRect: () => {},
    beginPath: () => {},
    moveTo: () => {},
    lineTo: () => {},
    closePath: () => {},
    fill: () => {},
  } as unknown as CanvasRenderingContext2D;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- getContext is
  // an overload set; matching it exactly here would be noise, and the stub is
  // only ever asked for a 2d context.
  HTMLCanvasElement.prototype.getContext = ((): any => ctx) as HTMLCanvasElement["getContext"];
  HTMLCanvasElement.prototype.toDataURL = () => "data:image/png;base64,AA==";
});

function draw(props: Partial<Parameters<typeof HealthMap>[0]> = {}) {
  return render(
    <HealthMap
      blocks={[block("b1", true)]}
      cells={[]}
      highlighted={new Set()}
      colorOf={colorOf}
      onSelectBlock={() => {}}
      onSelectCell={() => {}}
      fitMode="block"
      fitKey="b1"
      {...props}
    />,
  );
}

describe("HealthMap", () => {
  beforeEach(() => {
    fake.loadHandler = null;
    fake.fitBounds.mockReset();
  });

  it("feeds the layers once the map has loaded, not only before", async () => {
    // The defect: the data effects were gated on a ref, so when the queries
    // resolved before the map's load event they ran once against an unready
    // map and never again. Nothing was ever drawn.
    draw();
    // Nothing exists yet: the sources are added in the map's load handler.
    expect(fake.sources.get("fh-blocks")).toBeUndefined();

    fake.loadHandler?.();

    await waitFor(() => {
      expect(fake.sources.get("fh-blocks")?.setData).toHaveBeenCalled();
    });
    const arg = fake.sources.get("fh-blocks")?.setData.mock.calls[0][0] as {
      features: unknown[];
    };
    expect(arg.features).toHaveLength(1);
  });

  it("frames the selected block once loaded", async () => {
    draw();
    fake.loadHandler?.();

    await waitFor(() => {
      expect(fake.fitBounds).toHaveBeenCalled();
    });
    const [bounds] = fake.fitBounds.mock.calls[0] as [number[][]];
    // South-west corner first, and every number finite.
    expect(bounds[0][0]).toBeLessThan(bounds[1][0]);
    expect(bounds.flat().every((n) => Number.isFinite(n))).toBe(true);
  });

  it("hides the cell image when the block has no cell verdicts", async () => {
    // Every verdict on the reference farm is block-scoped, so this is the
    // normal path. Collapsing the image's corners instead of hiding it gave
    // MapLibre a zero-area quad and killed the page.
    draw({ cells: [] });
    fake.loadHandler?.();

    await waitFor(() => {
      expect(fake.layout).toContainEqual({
        layer: "fh-cell-image",
        prop: "visibility",
        value: "none",
      });
    });
    expect(fake.sources.get("fh-cell-image")?.setCoordinates).not.toHaveBeenCalled();
  });

  it("never hands MapLibre a zero-area image footprint", async () => {
    draw({ cells: [cell(0, 0), cell(0, 1)] });
    fake.loadHandler?.();

    await waitFor(() => {
      expect(fake.sources.get("fh-cell-image")?.setCoordinates).toHaveBeenCalled();
    });
    const corners = fake.sources.get("fh-cell-image")?.setCoordinates.mock
      .calls[0][0] as [number, number][];
    const lons = corners.map((c) => c[0]);
    const lats = corners.map((c) => c[1]);
    expect(Math.max(...lons)).toBeGreaterThan(Math.min(...lons));
    expect(Math.max(...lats)).toBeGreaterThan(Math.min(...lats));
    expect(corners.flat().every((n) => Number.isFinite(n))).toBe(true);
  });

  it("starts with the cell image hidden", () => {
    draw();
    fake.loadHandler?.();
    const layer = fake.layers.find((l) => l.id === "fh-cell-image");
    // The placeholder is 1x1 over a zero-area footprint and must never draw.
    expect(layer?.layout).toEqual({ visibility: "none" });
  });
});
