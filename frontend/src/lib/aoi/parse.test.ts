import { describe, expect, it } from "vitest";
import { AoiParseError, MAX_FILE_BYTES, parseAoiFile, pickPolygonalFeatures } from "./parse";

function makeFile(name: string, content: string, type = "application/json"): File {
  return new File([content], name, { type });
}

const cairoGeojson = JSON.stringify({
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: {},
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [31.2, 30.0],
            [31.21, 30.0],
            [31.21, 30.01],
            [31.2, 30.01],
            [31.2, 30.0],
          ],
        ],
      },
    },
  ],
});

describe("parseAoiFile", () => {
  it("parses a small .geojson FeatureCollection", async () => {
    const file = makeFile("farm.geojson", cairoGeojson, "application/geo+json");
    const result = await parseAoiFile(file);
    expect(result.format).toBe("geojson");
    expect(result.collection.features).toHaveLength(1);
  });

  it("upgrades a bare Feature into a collection", async () => {
    const feature = JSON.stringify({
      type: "Feature",
      properties: {},
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [31.2, 30.0],
            [31.21, 30.0],
            [31.21, 30.01],
            [31.2, 30.01],
            [31.2, 30.0],
          ],
        ],
      },
    });
    const file = makeFile("farm.json", feature);
    const result = await parseAoiFile(file);
    expect(result.collection.features).toHaveLength(1);
  });

  it("rejects oversize files", async () => {
    const huge = new File(["x"], "huge.geojson", { type: "application/geo+json" });
    Object.defineProperty(huge, "size", { value: MAX_FILE_BYTES + 1 });
    await expect(parseAoiFile(huge)).rejects.toMatchObject({ code: "too_large" });
  });

  it("rejects unsupported extensions", async () => {
    const file = new File(["data"], "farm.txt", { type: "text/plain" });
    await expect(parseAoiFile(file)).rejects.toBeInstanceOf(AoiParseError);
  });

  it("rejects empty FeatureCollections", async () => {
    const empty = JSON.stringify({ type: "FeatureCollection", features: [] });
    const file = makeFile("empty.geojson", empty);
    await expect(parseAoiFile(file)).rejects.toMatchObject({ code: "empty" });
  });

  it("rejects malformed JSON", async () => {
    const file = makeFile("bad.geojson", "not json");
    await expect(parseAoiFile(file)).rejects.toMatchObject({ code: "invalid_content" });
  });
});

describe("pickPolygonalFeatures", () => {
  it("filters out non-polygonal features", () => {
    const collection = {
      type: "FeatureCollection" as const,
      features: [
        {
          type: "Feature" as const,
          properties: {},
          geometry: { type: "Point" as const, coordinates: [31, 30] },
        },
        {
          type: "Feature" as const,
          properties: {},
          geometry: {
            type: "Polygon" as const,
            coordinates: [
              [
                [31.2, 30.0],
                [31.21, 30.0],
                [31.21, 30.01],
                [31.2, 30.01],
                [31.2, 30.0],
              ],
            ],
          },
        },
      ],
    };
    expect(pickPolygonalFeatures(collection)).toHaveLength(1);
  });
});
