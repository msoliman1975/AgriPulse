import type { Polygon } from "geojson";
import { describe, expect, it } from "vitest";

import {
  classifyRows,
  deriveRowsFromFiles,
  filenameToCode,
  type BulkRow,
  type ExistingBlock,
} from "./bulk";

function square(lon: number, lat: number, side = 0.01): Polygon {
  return {
    type: "Polygon",
    coordinates: [
      [
        [lon, lat],
        [lon + side, lat],
        [lon + side, lat + side],
        [lon, lat + side],
        [lon, lat],
      ],
    ],
  };
}

function makeGeojsonFile(name: string, ...polys: Polygon[]): File {
  const content = JSON.stringify({
    type: "FeatureCollection",
    features: polys.map((geometry) => ({ type: "Feature", properties: {}, geometry })),
  });
  return new File([content], name, { type: "application/geo+json" });
}

function row(code: string, geometry: Polygon | null, clientError: string | null = null): BulkRow {
  return { id: code, fileName: `${code}.geojson`, code, name: "", geometry, clientError };
}

describe("filenameToCode", () => {
  it("strips the extension and path", () => {
    expect(filenameToCode("North-7.geojson")).toBe("North-7");
    expect(filenameToCode("/data/farm/Block_3.zip")).toBe("Block_3");
  });

  it("sanitizes disallowed characters to single dashes", () => {
    expect(filenameToCode("north field #2.kml")).toBe("north-field-2");
  });

  it("trims leading underscores/dashes", () => {
    expect(filenameToCode("_hidden.geojson")).toBe("hidden");
  });

  it("falls back to BLOCK when nothing usable remains", () => {
    expect(filenameToCode("###.kml")).toBe("BLOCK");
  });

  it("clamps to 32 characters", () => {
    expect(filenameToCode("a".repeat(50) + ".geojson").length).toBe(32);
  });
});

describe("deriveRowsFromFiles", () => {
  it("makes one row per single-polygon file", async () => {
    const rows = await deriveRowsFromFiles([makeGeojsonFile("North-1.geojson", square(31.2, 30.1))]);
    expect(rows).toHaveLength(1);
    expect(rows[0].code).toBe("North-1");
    expect(rows[0].geometry).not.toBeNull();
    expect(rows[0].clientError).toBeNull();
  });

  it("expands a multi-polygon file into suffixed rows", async () => {
    const rows = await deriveRowsFromFiles([
      makeGeojsonFile("Grid.geojson", square(31.2, 30.1), square(31.3, 30.1)),
    ]);
    expect(rows.map((r) => r.code)).toEqual(["Grid-1", "Grid-2"]);
  });

  it("emits an error row for an unparseable file", async () => {
    const bad = new File(["not json"], "broken.geojson", { type: "application/geo+json" });
    const rows = await deriveRowsFromFiles([bad]);
    expect(rows).toHaveLength(1);
    expect(rows[0].geometry).toBeNull();
    expect(rows[0].clientError).toBe("invalid");
  });
});

describe("classifyRows", () => {
  const geomA = square(31.2, 30.1);
  const geomB = square(31.5, 30.1);
  const existing: ExistingBlock[] = [{ code: "EXIST", geometry: geomA }];

  it("marks an unknown code as new", () => {
    const [r] = classifyRows([row("FRESH", geomB)], existing);
    expect(r.status).toBe("new");
  });

  it("marks a code match with identical geometry as reuse", () => {
    const [r] = classifyRows([row("EXIST", square(31.2, 30.1))], existing);
    expect(r.status).toBe("reuse");
    expect(r.existingCode).toBe("EXIST");
  });

  it("marks a code match with changed geometry as replace", () => {
    const [r] = classifyRows([row("EXIST", geomB)], existing);
    expect(r.status).toBe("replace");
  });

  it("flags a duplicate code within the batch as error", () => {
    const rows = classifyRows([row("DUP", geomA), row("DUP", geomB)], existing);
    expect(rows[0].status).toBe("new");
    expect(rows[1].status).toBe("error");
    expect(rows[1].clientError).toBe("duplicate");
  });

  it("keeps a parse-error row as error", () => {
    const [r] = classifyRows([row("BROKEN", null, "invalid")], existing);
    expect(r.status).toBe("error");
  });
});
