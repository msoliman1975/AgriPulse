// Pure helpers for building TiTiler tile-URL templates.
//
// The backend keeps assets in S3 at the deterministic key
//   {provider}/{product}/{scene}/{aoi}/{role}.tif
// (PR-B's `app.modules.imagery.storage.build_asset_key`).
//
// TiTiler's raw-COG mode serves tiles via:
//   {tileServerBaseUrl}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?
//     url=<asset_uri>&rescale=<min,max>&colormap_name=<name>
//
// The frontend never hard-codes the tile-server origin or the bucket
// name — both come from /api/v1/config (Q1 in the PR-D plan). For
// MapLibre / deck.gl XYZ consumption, we leave `{z}/{x}/{y}` as
// placeholders for the rendering library to interpolate.

import type { AnyIndexCode, IndexCode } from "@/api/indices";

interface BuildTileUrlInput {
  tileServerBaseUrl: string;
  s3Bucket: string;
  /** Asset-key path under the bucket (no leading slash, no `s3://`). */
  assetKey: string;
  /** Visualisation rescale window. */
  rescaleMin: number;
  rescaleMax: number;
  /** TiTiler colormap name. NDVI/EVI use a green ramp; NDWI uses blue. */
  colormap: string;
}

/**
 * Build the tile-URL template for one COG asset. The placeholders
 * `{z}`, `{x}`, `{y}` are intentionally left intact so the consumer
 * (MapLibre raster source, deck.gl TileLayer) interpolates them.
 */
export function buildTileUrlTemplate(input: BuildTileUrlInput): string {
  const base = trimTrailingSlash(input.tileServerBaseUrl);
  const assetUri = `s3://${input.s3Bucket}/${input.assetKey}`;
  const params = new URLSearchParams({
    url: assetUri,
    rescale: `${input.rescaleMin},${input.rescaleMax}`,
    colormap_name: input.colormap,
  });
  return `${base}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?${params.toString()}`;
}

/**
 * Pick a sensible (rescale, colormap) for one of the standard indices.
 * Bounds are not from `indices_catalog.value_min/value_max` directly —
 * those are the theoretical full range, but a green ramp over [-1, 1]
 * looks washed out. We tighten the window to the meaningful agronomic
 * range for each index.
 *
 * The switch is deliberately exhaustive with no `default`, so adding a
 * code to `IndexCode` fails the build here rather than silently rendering
 * a new index with NDVI's window.
 */
export function visualizationDefaults(indexCode: AnyIndexCode): {
  rescaleMin: number;
  rescaleMax: number;
  colormap: string;
} {
  switch (indexCode) {
    case "ndvi":
      return { rescaleMin: -0.2, rescaleMax: 0.9, colormap: "greens" };
    case "ndwi":
      return { rescaleMin: -0.5, rescaleMax: 0.5, colormap: "blues" };
    case "evi":
      return { rescaleMin: -0.2, rescaleMax: 0.9, colormap: "greens" };
    case "savi":
      return { rescaleMin: -0.2, rescaleMax: 0.9, colormap: "greens" };
    case "msavi":
      // Same window as savi. MSAVI2 only replaces savi's fixed soil factor
      // with a per-pixel one, so the two occupy the same range and reading
      // them on different windows would make the pair incomparable.
      return { rescaleMin: -0.2, rescaleMax: 0.9, colormap: "greens" };
    case "ndre":
      return { rescaleMin: -0.2, rescaleMax: 0.7, colormap: "greens" };
    case "gndvi":
      return { rescaleMin: -0.2, rescaleMax: 0.8, colormap: "greens" };
    case "ndmi":
      // Moisture index (NIR/SWIR), ~[-1,1]; blues like ndwi.
      return { rescaleMin: -0.5, rescaleMax: 0.5, colormap: "blues" };
    case "bsi":
      // Bare soil. Normalized difference, so [-1,1] — but the agronomic
      // action happens either side of zero (canopy vs exposed ground), so a
      // divergent brown ramp centred on 0 reads better than a sequential one.
      return { rescaleMin: -0.5, rescaleMax: 0.5, colormap: "brbg_r" };
    case "msi":
      // ⚠️ Two deviations from every case above, both deliberate:
      //   1. Range is a RATIO (~0.2 well-watered → 2.0 severely stressed),
      //      not [-1, 1]. Reusing a normalized-difference window here would
      //      clamp every real pixel to one end of the ramp.
      //   2. `_r` reverses the ramp, because high MSI is BAD. Without the
      //      reversal a parched block renders in the same colour a healthy
      //      one does under NDVI.
      return { rescaleMin: 0.2, rescaleMax: 2.0, colormap: "rdylgn_r" };

    // --- Thermal (`landsat_c2_l2_st`) -------------------------------
    // Ranges are the catalog's own `value_min`/`value_max`, not the
    // [-1, 1] the normalized differences share. Omitting these returned
    // `undefined` here, and the caller read `.rescaleMin` off it — which
    // took down the whole scene page the moment a thermal scene became
    // openable and its own index was selected.
    case "lst":
      // Degrees Celsius, 0-60 — the only index in either set with a UNIT.
      // Hot is bad, so the ramp runs green (cool) -> red (hot).
      return { rescaleMin: 0, rescaleMax: 60, colormap: "rdylgn_r" };
    case "cwsi":
      // 0 = freely transpiring, 1 = fully stressed. High is bad.
      return { rescaleMin: 0, rescaleMax: 1, colormap: "rdylgn_r" };
    case "smi":
      // 0 = dry edge, 1 = wet edge. Wetter reads blue, like ndwi/ndmi.
      return { rescaleMin: 0, rescaleMax: 1, colormap: "blues" };
  }
}

/**
 * Build the asset-key for an index COG that the imagery pipeline
 * already wrote — mirrors `app.modules.imagery.storage.build_asset_key`.
 */
export function indexAssetKey(input: {
  providerCode: string;
  productCode: string;
  sceneId: string;
  aoiHash: string;
  indexCode: IndexCode;
}): string {
  return `${input.providerCode}/${input.productCode}/${input.sceneId}/${input.aoiHash}/${input.indexCode}.tif`;
}

function trimTrailingSlash(s: string): string {
  return s.endsWith("/") ? s.slice(0, -1) : s;
}
