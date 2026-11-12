import { describe, expect, it } from "vitest";

import {
  ESRI_IMAGERY_TILES,
  esriCaptureDateUrl,
  parseEsriCaptureDate,
  satelliteStyle,
} from "./esri";

describe("satelliteStyle", () => {
  it("is the Esri imagery base under the id overlays slot above", () => {
    const style = satelliteStyle();
    expect(style.layers).toEqual([{ id: "satellite", type: "raster", source: "satellite" }]);
    expect(style.sources.satellite).toMatchObject({ tiles: [ESRI_IMAGERY_TILES] });
    expect(style).not.toHaveProperty("glyphs");
  });
});

describe("esriCaptureDateUrl", () => {
  it("asks the metadata layers for the topmost capture under the centre", () => {
    const url = new URL(
      esriCaptureDateUrl({
        center: [32.6368, 30.0804],
        bounds: [32.62, 30.07, 32.65, 30.09],
        size: [800.4, 599.6],
      }),
    );
    expect(url.pathname).toMatch(/World_Imagery\/MapServer\/identify$/);
    expect(url.searchParams.get("geometry")).toBe("32.6368,30.0804");
    expect(url.searchParams.get("layers")).toMatch(/^top:5,/);
    expect(url.searchParams.get("imageDisplay")).toBe("800,600,96");
  });
});

describe("parseEsriCaptureDate", () => {
  it("reads SRC_DATE as an ISO day", () => {
    // Trimmed from the live answer for the reference farm.
    const body = {
      results: [
        { attributes: { SRC_DATE: "20200419", SRC_DATE2: "4/19/2020", NICE_DESC: "Vantor" } },
      ],
    };
    expect(parseEsriCaptureDate(body)).toBe("2020-04-19");
  });

  it("is null for an empty or odd answer", () => {
    expect(parseEsriCaptureDate({ results: [] })).toBeNull();
    expect(parseEsriCaptureDate({ error: { code: 400 } })).toBeNull();
    expect(parseEsriCaptureDate(null)).toBeNull();
    expect(parseEsriCaptureDate({ results: [{ attributes: { SRC_DATE: "Null" } }] })).toBeNull();
  });
});
