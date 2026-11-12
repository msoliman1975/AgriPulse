// Our own newest clear Sentinel-2 pass, drawn over the farm in true colour.
//
// The api picks the pass (newest one clear over THIS farm) and builds the tile
// URL, so the web maps and the Android investor app draw the same picture.
// Here we only slot it into a MapLibre map: directly above the satellite base
// and below every outline, marker and index layer a page adds.
import type { Map as MapLibreMap, RasterSourceSpecification } from "maplibre-gl";

import { SATELLITE_LAYER_ID } from "./esri";

export const PHOTO_SOURCE_ID = "latest-photo";
export const PHOTO_LAYER_ID = "latest-photo";

export function photoSourceSpec(tileUrl: string): RasterSourceSpecification {
  return {
    type: "raster",
    tiles: [tileUrl],
    // The api asks the tile server for scale=2, i.e. 512 px tiles.
    tileSize: 512,
    attribution: "Contains modified Copernicus Sentinel data",
  };
}

/** The layer just above the satellite base, or undefined to append on top. */
function layerAboveBase(map: MapLibreMap): string | undefined {
  const ids = map.getStyle().layers.map((l) => l.id);
  const at = ids.indexOf(SATELLITE_LAYER_ID);
  if (at < 0) return ids[0];
  return ids.slice(at + 1).find((id) => id !== PHOTO_LAYER_ID);
}

/**
 * Show, hide, swap or remove the photo layer. Idempotent, so an effect can
 * call it on every change. A map whose style is still loading is retried once
 * it settles.
 */
export function applyLatestPhoto(map: MapLibreMap, tileUrl: string | null, visible: boolean): void {
  if (!map.isStyleLoaded()) {
    map.once("idle", () => applyLatestPhoto(map, tileUrl, visible));
    return;
  }
  const source = map.getSource(PHOTO_SOURCE_ID) as { tiles?: string[] } | undefined;
  if (source && (!tileUrl || source.tiles?.[0] !== tileUrl)) {
    if (map.getLayer(PHOTO_LAYER_ID)) map.removeLayer(PHOTO_LAYER_ID);
    map.removeSource(PHOTO_SOURCE_ID);
  }
  if (!tileUrl) return;
  if (!map.getSource(PHOTO_SOURCE_ID)) map.addSource(PHOTO_SOURCE_ID, photoSourceSpec(tileUrl));
  if (!map.getLayer(PHOTO_LAYER_ID)) {
    map.addLayer(
      { id: PHOTO_LAYER_ID, type: "raster", source: PHOTO_SOURCE_ID },
      layerAboveBase(map),
    );
  }
  map.setLayoutProperty(PHOTO_LAYER_ID, "visibility", visible ? "visible" : "none");
}
