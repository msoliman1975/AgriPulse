// The high-resolution satellite base every map draws on, and how old it is.
//
// Esri World Imagery is a mosaic Esri refreshes on its own schedule. Measured
// in November 2026, the reference farm east of Cairo was a Vantor capture
// from 19 April 2020, while the Delta and Wadi El Natrun were mid-2025. We
// cannot make it newer, so every map says how old it is, and lays our own
// latest Sentinel-2 pass over the farm (see latestPhoto.ts).
//
// Its capture date comes from the same service's metadata layers: an
// `identify` on the view returns the topmost capture under it, with
// SRC_DATE as YYYYMMDD. The service sends `Access-Control-Allow-Origin: *`.
import type { RasterSourceSpecification, StyleSpecification } from "maplibre-gl";

export const ESRI_IMAGERY_TILES =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

const ESRI_IDENTIFY =
  "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/identify";

/** The resolution metadata layers, 1.9 cm through 38 m; 0-4 are not metadata. */
const METADATA_LAYERS = "top:5,6,7,8,9,10,11,12,13,14,15,16";

/** Source and layer id of the base, so overlays can be slotted just above it. */
export const SATELLITE_SOURCE_ID = "satellite";
export const SATELLITE_LAYER_ID = "satellite";

export function satelliteSource(): RasterSourceSpecification {
  return {
    type: "raster",
    tiles: [ESRI_IMAGERY_TILES],
    tileSize: 256,
    maxzoom: 19,
    attribution: "Esri, Vantor, Earthstar Geographics",
  };
}

/** A style holding only the satellite base. Callers add their own layers on load. */
export function satelliteStyle(opts: { glyphs?: string } = {}): StyleSpecification {
  return {
    version: 8,
    ...(opts.glyphs ? { glyphs: opts.glyphs } : {}),
    sources: { [SATELLITE_SOURCE_ID]: satelliteSource() },
    layers: [{ id: SATELLITE_LAYER_ID, type: "raster", source: SATELLITE_SOURCE_ID }],
  };
}

/** Below this zoom the view spans many captures and one date would mislead. */
export const CAPTURE_DATE_MIN_ZOOM = 11;

export function esriCaptureDateUrl(input: {
  center: [number, number];
  bounds: [number, number, number, number];
  size: [number, number];
}): string {
  const [x, y] = input.center;
  const params = new URLSearchParams({
    geometry: `${x},${y}`,
    geometryType: "esriGeometryPoint",
    sr: "4326",
    layers: METADATA_LAYERS,
    tolerance: "0",
    mapExtent: input.bounds.join(","),
    imageDisplay: `${Math.round(input.size[0])},${Math.round(input.size[1])},96`,
    returnGeometry: "false",
    f: "json",
  });
  return `${ESRI_IDENTIFY}?${params.toString()}`;
}

/** The capture date as `YYYY-MM-DD`, or null when the answer carries none. */
export function parseEsriCaptureDate(body: unknown): string | null {
  const results = (body as { results?: { attributes?: Record<string, unknown> }[] } | null)
    ?.results;
  const raw = results?.[0]?.attributes?.SRC_DATE;
  if (typeof raw !== "string" && typeof raw !== "number") return null;
  const m = /^(\d{4})(\d{2})(\d{2})$/.exec(String(raw));
  return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
}
