import { describe, expect, it } from "vitest";

import { buildTileUrlTemplate, indexAssetKey, visualizationDefaults } from "./tileUrl";

const TILE_URL = "http://localhost:8001";
const BUCKET = "agripulse-uploads";

describe("buildTileUrlTemplate", () => {
  it("emits TiTiler XYZ template with placeholders intact", () => {
    const url = buildTileUrlTemplate({
      tileServerBaseUrl: TILE_URL,
      s3Bucket: BUCKET,
      assetKey: "sentinel_hub/s2_l2a/SCENE/AOI/ndvi.tif",
      rescaleMin: -0.2,
      rescaleMax: 0.9,
      colormap: "greens",
    });
    expect(url).toContain("/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?");
    expect(url).toContain("colormap_name=greens");
    expect(url).toContain("rescale=-0.2%2C0.9"); // urlencoded comma
    expect(url).toContain("url=s3");
    expect(url).toContain(`${BUCKET}%2Fsentinel_hub%2Fs2_l2a%2FSCENE%2FAOI%2Fndvi.tif`);
  });

  it("strips trailing slash from tile-server URL", () => {
    const url = buildTileUrlTemplate({
      tileServerBaseUrl: "http://localhost:8001/",
      s3Bucket: BUCKET,
      assetKey: "x.tif",
      rescaleMin: 0,
      rescaleMax: 1,
      colormap: "greens",
    });
    expect(url.startsWith("http://localhost:8001/cog/tiles/")).toBe(true);
    // No double-slash between origin and path.
    expect(url).not.toContain("8001//cog");
  });
});

describe("visualizationDefaults", () => {
  it("uses the green ramp for vegetation indices", () => {
    expect(visualizationDefaults("ndvi").colormap).toBe("greens");
    expect(visualizationDefaults("evi").colormap).toBe("greens");
    expect(visualizationDefaults("savi").colormap).toBe("greens");
    expect(visualizationDefaults("ndre").colormap).toBe("greens");
    expect(visualizationDefaults("gndvi").colormap).toBe("greens");
  });

  it("uses the blue ramp for water indices", () => {
    expect(visualizationDefaults("ndwi").colormap).toBe("blues");
  });

  it("returns deterministic rescale windows", () => {
    expect(visualizationDefaults("ndvi")).toEqual({
      rescaleMin: -0.2,
      rescaleMax: 0.9,
      colormap: "greens",
    });
  });
});

describe("indexAssetKey", () => {
  it("produces the canonical layout the backend writes", () => {
    expect(
      indexAssetKey({
        providerCode: "sentinel_hub",
        productCode: "s2_l2a",
        sceneId: "S2A_TEST",
        aoiHash: "deadbeef",
        indexCode: "ndvi",
      }),
    ).toBe("sentinel_hub/s2_l2a/S2A_TEST/deadbeef/ndvi.tif");
  });
});
