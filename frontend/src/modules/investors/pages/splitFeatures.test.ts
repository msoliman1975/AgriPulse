import type { Feature, MultiPolygon, Polygon } from "geojson";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/modules/farms/components/MapDraw", () => ({ MapDraw: () => null }));
vi.mock("../components/FarmHoldingsMap", () => ({ FarmHoldingsMap: () => null }));

import { splitFeatures } from "./HoldingNewPage";

const square = (x: number): number[][] => [
  [x, 0],
  [x + 1, 0],
  [x + 1, 1],
  [x, 1],
  [x, 0],
];

describe("splitFeatures", () => {
  it("makes one holding per polygon and keeps the file's names", () => {
    const named: Feature<Polygon> = {
      type: "Feature",
      properties: { Name: "North strip" },
      geometry: { type: "Polygon", coordinates: [square(0)] },
    };
    const multi: Feature<MultiPolygon> = {
      type: "Feature",
      properties: {},
      geometry: { type: "MultiPolygon", coordinates: [[square(2)], [square(4)]] },
    };
    const rows = splitFeatures([named, multi], (n) => `Holding ${n}`);
    expect(rows.map((r) => r.name)).toEqual(["North strip", "Holding 2", "Holding 3"]);
    expect(rows.every((r) => r.polygon.type === "Polygon")).toBe(true);
    expect(rows.every((r) => r.status === "draft" && r.check === null)).toBe(true);
  });
});
