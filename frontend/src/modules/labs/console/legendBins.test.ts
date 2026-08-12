import { describe, expect, it } from "vitest";

import type { GridCellWithValue } from "@/api/grid";
import { computeLegend, formatRange, type LegendGroup } from "./legendBins";

/** Only the fields computeLegend reads actually matter; the rest is ballast. */
function cell(
  mean: string | null,
  areaM2: string,
  id = Math.random().toString(36),
): GridCellWithValue {
  return {
    cell_id: id,
    row_idx: 0,
    col_idx: 0,
    area_m2: areaM2,
    centroid_lon: 32.6,
    centroid_lat: 30.0,
    geometry: { type: "Polygon", coordinates: [] },
    mean,
    valid_pixel_pct: "100",
    time: "2026-07-01T00:00:00Z",
  };
}

function group(blockId: string, cells: GridCellWithValue[]): LegendGroup {
  return { blockId, cells };
}

const fmt2 = (n: number): string => n.toFixed(2);

describe("computeLegend", () => {
  it("returns one row per band, highest band first", () => {
    const res = computeLegend([], "ndvi", null);
    // ndvi: bare, verySparse, sparse, developing, dense, veryDense
    expect(res.rows).toHaveLength(6);
    expect(res.rows[0].key).toBe("veryDense");
    expect(res.rows[res.rows.length - 1].key).toBe("bare");
  });

  it("sums cell area into the band whose inclusive max the value fits under", () => {
    const res = computeLegend(
      [group("b1", [cell("0.25", "1000"), cell("0.35", "2000"), cell("0.15", "500")])],
      "ndvi",
      null,
    );
    const byKey = Object.fromEntries(res.rows.map((r) => [r.key, r.areaM2]));
    // 0.25 and 0.35 are both <= 0.4 -> "sparse"; 0.15 <= 0.2 -> "verySparse".
    expect(byKey.sparse).toBe(3000);
    expect(byKey.verySparse).toBe(500);
    expect(res.coveredM2).toBe(3500);
  });

  it("treats the band max as inclusive", () => {
    // Exactly 0.2 must land in verySparse (max: 0.2), not sparse.
    const res = computeLegend([group("b1", [cell("0.2", "100")])], "ndvi", null);
    const byKey = Object.fromEntries(res.rows.map((r) => [r.key, r.areaM2]));
    expect(byKey.verySparse).toBe(100);
    expect(byKey.sparse).toBe(0);
  });

  it("puts a null mean in noData rather than a band", () => {
    const res = computeLegend([group("b1", [cell(null, "700"), cell("0.5", "300")])], "ndvi", null);
    expect(res.noDataM2).toBe(700);
    expect(res.noDataCells).toBe(1);
    expect(res.coveredM2).toBe(300);
    expect(res.totalCells).toBe(2);
  });

  it("skips rows with a non-finite or non-positive area instead of distorting a total", () => {
    const res = computeLegend(
      [group("b1", [cell("0.5", "not-a-number"), cell("0.5", "0"), cell("0.5", "250")])],
      "ndvi",
      null,
    );
    expect(res.coveredM2).toBe(250);
    expect(res.totalCells).toBe(1);
  });

  it("scopes to a single block when asked", () => {
    const groups = [group("b1", [cell("0.5", "100")]), group("b2", [cell("0.5", "900")])];
    expect(computeLegend(groups, "ndvi", null).coveredM2).toBe(1000);
    expect(computeLegend(groups, "ndvi", "b2").coveredM2).toBe(900);
    expect(computeLegend(groups, "ndvi", "b1").coveredM2).toBe(100);
  });

  it("handles the unbounded top band", () => {
    const res = computeLegend([group("b1", [cell("0.95", "400")])], "ndvi", null);
    const top = res.rows[0];
    expect(top.key).toBe("veryDense");
    expect(top.hi).toBeNull();
    expect(top.areaM2).toBe(400);
  });

  it("bins NDWI's negative bands, which run the opposite way to the canopy indices", () => {
    // ndwi: <=-0.4 denseCanopy, <=-0.15 vegetated, <=0 bareOrDamp,
    //       <=0.2 standingWater, > 0.2 openWater
    const res = computeLegend(
      [group("b1", [cell("-0.5", "100"), cell("-0.2", "200"), cell("0.3", "300")])],
      "ndwi",
      null,
    );
    const byKey = Object.fromEntries(res.rows.map((r) => [r.key, r.areaM2]));
    expect(byKey.denseCanopy).toBe(100);
    expect(byKey.vegetated).toBe(200);
    expect(byKey.openWater).toBe(300);
  });

  it("gives the lowest band no lower bound", () => {
    const res = computeLegend([], "ndmi", null);
    const lowest = res.rows[res.rows.length - 1];
    expect(lowest.key).toBe("bare");
    expect(lowest.lo).toBeNull();
    expect(lowest.hi).toBe(-0.2);
  });

  it("assigns every row a colour from the map's ramp", () => {
    const res = computeLegend([], "ndvi", null);
    for (const row of res.rows) expect(row.color).toMatch(/^#[0-9a-f]{6}$/);
  });

  it("copes with undefined groups (grid query disabled)", () => {
    const res = computeLegend(undefined, "ndvi", null);
    expect(res.coveredM2).toBe(0);
    expect(res.totalCells).toBe(0);
    expect(res.rows).toHaveLength(6);
  });
});

describe("formatRange", () => {
  const base = { key: "k", tone: "healthy" as const, color: "#000", areaM2: 0, cellCount: 0 };

  it("renders the lowest band as an upper bound only", () => {
    expect(formatRange({ ...base, lo: null, hi: 0.1 }, fmt2)).toBe("≤ 0.10");
  });

  it("renders the highest band as a lower bound only", () => {
    expect(formatRange({ ...base, lo: 0.8, hi: null }, fmt2)).toBe("> 0.80");
  });

  it("renders a middle band as a closed range", () => {
    expect(formatRange({ ...base, lo: 0.2, hi: 0.4 }, fmt2)).toBe("0.20 – 0.40");
  });
});
