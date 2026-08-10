import { describe, expect, it } from "vitest";

import type { CellLocation } from "@/api/actionCenter";
import {
  cellOrdinal,
  confidencePercent,
  formatCoords,
  mapsUrl,
} from "@/modules/actionCenter/lib/format";

const cell = (over: Partial<CellLocation> = {}): CellLocation => ({
  cell_id: "c1",
  row: 2,
  col: 3,
  ordinal: 3,
  total: 36,
  lat: 30.044211111,
  lon: 31.235781111,
  area_m2: "420.00",
  ...over,
});

describe("formatCoords", () => {
  it("renders 5 decimal places — roughly one metre, which is the point", () => {
    expect(formatCoords(cell())).toBe("30.04421, 31.23578");
  });

  it("pads short values so the column stays aligned", () => {
    expect(formatCoords(cell({ lat: 30.1, lon: 31.2 }))).toBe("30.10000, 31.20000");
  });

  it("handles the southern and western hemispheres", () => {
    expect(formatCoords(cell({ lat: -1.28333, lon: -36.81667 }))).toBe("-1.28333, -36.81667");
  });

  it("returns null rather than 'null, null' when the centroid is missing", () => {
    // A cell whose grid config was retired can come back without geometry.
    // Rendering the string "null, null" into a coordinate field would be
    // worse than showing nothing.
    expect(formatCoords(cell({ lat: null }))).toBeNull();
    expect(formatCoords(cell({ lon: null }))).toBeNull();
  });
});

describe("mapsUrl", () => {
  it("builds a link the phone's map app can open", () => {
    expect(mapsUrl(cell())).toContain("query=30.044211111,31.235781111");
  });

  it("is null when there is nothing to navigate to", () => {
    expect(mapsUrl(cell({ lat: null, lon: null }))).toBeNull();
  });
});

describe("cellOrdinal", () => {
  it("reads as 'n / total' so two rows on one block are distinguishable", () => {
    expect(cellOrdinal(cell())).toBe("3 / 36");
  });

  it("drops the total when the grid size is unknown", () => {
    expect(cellOrdinal(cell({ total: null }))).toBe("3");
  });

  it("is null when there is no ordinal at all", () => {
    expect(cellOrdinal(cell({ ordinal: null }))).toBeNull();
  });
});

describe("confidencePercent", () => {
  it("converts the API's decimal string to a whole percent", () => {
    expect(confidencePercent("0.82")).toBe(82);
  });

  it("rounds rather than truncating", () => {
    expect(confidencePercent("0.825")).toBe(83);
  });

  it("is null for an alert, which carries no probability", () => {
    expect(confidencePercent(null)).toBeNull();
  });

  it("is null for a value that is not a number", () => {
    expect(confidencePercent("n/a")).toBeNull();
  });
});
