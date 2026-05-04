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

import type { IndexCode } from "@/api/indices";

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
 * Pick a sensible (rescale, colormap) for one of the six standard
 * indices. Bounds are not from `indices_catalog.value_min/value_max`
 * directly — those are the theoretical full range, but a green ramp
 * over [-1, 1] looks washed out. We tighten the window to the
 * meaningful agronomic range for each index.
 */
export function visualizationDefaults(indexCode: IndexCode): {
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
    case "ndre":
      return { rescaleMin: -0.2, rescaleMax: 0.7, colormap: "greens" };
    case "gndvi":
      return { rescaleMin: -0.2, rescaleMax: 0.8, colormap: "greens" };
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
