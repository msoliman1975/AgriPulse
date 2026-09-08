import { describe, expect, it } from "vitest";

import type { StatusCode } from "@/api/farmHealth";
import {
  bboxToImageCoordinates,
  blurRadius,
  canvasSize,
  cellsBbox,
  outlineSegments,
  paintCells,
  type PaintCell,
  type PaintContext,
} from "./cellRaster";

/** A unit square cell at grid position (row, col), one thousandth wide. */
function cell(row: number, col: number, status: StatusCode = "good"): PaintCell & {
  row: number;
  col: number;
} {
  const size = 0.001;
  const west = 30 + col * size;
  const south = 20 - row * size;
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

/** Records what was drawn, so the maths can be checked without a canvas. */
function fakeContext(width = 100, height = 100): PaintContext & {
  ops: string[];
  points: [number, number][];
  fills: string[];
  filters: string[];
} {
  const ops: string[] = [];
  const points: [number, number][] = [];
  const fills: string[] = [];
  const filters: string[] = [];
  return {
    canvas: { width, height },
    ops,
    points,
    fills,
    filters,
    set filter(value: string) {
      filters.push(value);
    },
    get filter() {
      return filters[filters.length - 1] ?? "none";
    },
    set fillStyle(value: string) {
      fills.push(value);
    },
    get fillStyle() {
      return fills[fills.length - 1] ?? "";
    },
    clearRect: () => ops.push("clear"),
    beginPath: () => ops.push("begin"),
    moveTo: (x, y) => {
      ops.push("move");
      points.push([x, y]);
    },
    lineTo: (x, y) => {
      ops.push("line");
      points.push([x, y]);
    },
    closePath: () => ops.push("close"),
    fill: () => ops.push("fill"),
  };
}

describe("cellsBbox", () => {
  it("covers every cell and leaves room for the blur to spread", () => {
    const box = cellsBbox([cell(0, 0), cell(1, 1)], 0.1);

    expect(box).not.toBeNull();
    // The cells span 30.000–30.002 and 19.999–20.001. A tight box would clip
    // the blur into a hard straight edge, which is the artefact it exists to
    // remove, so the box is wider than the cells on every side.
    expect(box!.west).toBeLessThan(30);
    expect(box!.east).toBeGreaterThan(30.002);
    expect(box!.south).toBeLessThan(19.999);
    expect(box!.north).toBeGreaterThan(20.001);
  });

  it("is null with no cells, so the caller can drop the layer", () => {
    expect(cellsBbox([])).toBeNull();
  });
});

describe("bboxToImageCoordinates", () => {
  it("orders the corners the way an image source reads them", () => {
    const coords = bboxToImageCoordinates({ west: 1, south: 2, east: 3, north: 4 });

    // Clockwise from the top left. Any other order flips or mirrors the map.
    expect(coords).toEqual([
      [1, 4],
      [3, 4],
      [3, 2],
      [1, 2],
    ]);
  });
});

describe("canvasSize", () => {
  it("keeps the pixels square, so the cells stay square", () => {
    const size = canvasSize({ west: 0, south: 0, east: 2, north: 1 }, 1000);

    expect(size.width).toBe(1000);
    expect(size.height).toBe(500);
  });
});

describe("blurRadius", () => {
  it("scales with the cell, so few cells and many look equally smooth", () => {
    const size = { width: 1024, height: 1024 };
    const coarse = blurRadius(64, size);
    const fine = blurRadius(400, size);

    // More cells means smaller cells means a smaller radius. A fixed radius
    // would wash a dense grid into one colour.
    expect(fine).toBeLessThan(coarse);
    expect(fine).toBeGreaterThanOrEqual(2);
  });
});

describe("paintCells", () => {
  const colorOf = (status: StatusCode) => (status === "alert" ? "#D64545" : "#6FBF4B");

  it("puts a cell where its coordinates say, with north at the top", () => {
    const box = { west: 0, south: 0, east: 1, north: 1 };
    const ctx = fakeContext(100, 100);
    const one: PaintCell = {
      cellId: "a",
      status: "good",
      ring: [
        [0, 1],
        [1, 1],
        [1, 0],
        [0, 0],
        [0, 1],
      ],
    };

    paintCells(ctx, [one], box, colorOf, 4);

    // Latitude grows north and canvas y grows down, so the north-west corner
    // is (0, 0) on the canvas. Getting this backwards flips the map
    // vertically, which looks plausible and is wrong.
    expect(ctx.points[0]).toEqual([0, 0]);
    expect(ctx.points).toContainEqual([100, 100]);
  });

  it("blurs once for the whole grid, not per cell", () => {
    const box = { west: 0, south: 0, east: 1, north: 1 };
    const ctx = fakeContext();

    paintCells(ctx, [cell(0, 0, "good"), cell(0, 1, "alert")], box, colorOf, 6);

    const blurs = ctx.filters.filter((f) => f.startsWith("blur("));
    // Blurring each cell on its own leaves a seam where two cells of the
    // same colour meet, which reads worse than the grid it replaced.
    expect(blurs).toEqual(["blur(6px)"]);
  });

  it("leaves the filter off when it is done", () => {
    const ctx = fakeContext();
    paintCells(ctx, [cell(0, 0)], { west: 0, south: 0, east: 1, north: 1 }, colorOf, 3);

    expect(ctx.filters[ctx.filters.length - 1]).toBe("none");
  });

  it("paints each cell in its own status colour", () => {
    const ctx = fakeContext();
    paintCells(
      ctx,
      [cell(0, 0, "alert"), cell(0, 1, "good")],
      { west: 0, south: 0, east: 1, north: 1 },
      colorOf,
      2,
    );

    expect(ctx.fills).toEqual(["#D64545", "#6FBF4B"]);
  });

  it("skips a ring that cannot be a polygon", () => {
    const ctx = fakeContext();
    paintCells(
      ctx,
      [{ cellId: "bad", status: "good", ring: [[0, 0]] }],
      { west: 0, south: 0, east: 1, north: 1 },
      colorOf,
      2,
    );

    expect(ctx.ops).not.toContain("fill");
  });
});

describe("outlineSegments", () => {
  it("traces the shape, not the grid inside it", () => {
    // Four cells in a square. The outline is 8 edges; the 8 internal ones
    // would put the grid back on top of the image the blur removed.
    const square = [cell(0, 0), cell(0, 1), cell(1, 0), cell(1, 1)];

    expect(outlineSegments(square)).toHaveLength(8);
  });

  it("gives a lone cell all four of its edges", () => {
    expect(outlineSegments([cell(0, 0)])).toHaveLength(4);
  });

  it("keeps two separate patches apart", () => {
    // Not neighbours: column 0 and column 5. Eight edges, not six.
    expect(outlineSegments([cell(0, 0), cell(0, 5)])).toHaveLength(8);
  });

  it("decides neighbours by row and column, not by geometry", () => {
    // Two cells that are neighbours by index but do not quite touch, which
    // is what a rezone leaves behind. A geometric test would open the
    // outline along the hairline between them.
    const a = cell(0, 0);
    const shifted: [number, number][] = cell(0, 1).ring.map(([lon, lat]) => [lon + 0.0002, lat]);
    const b = { ...cell(0, 1), ring: shifted };

    expect(outlineSegments([a, b])).toHaveLength(6);
  });
});
