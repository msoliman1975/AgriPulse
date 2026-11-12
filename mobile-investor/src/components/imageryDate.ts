/**
 * When Esri's high-resolution image under a point was captured, as YYYY-MM-DD.
 *
 * Esri refreshes its mosaic on its own schedule: over the reference farm east
 * of Cairo it was a capture from April 2020 when this was written. Saying so
 * beats letting an investor take a six-year-old picture for today's orchard.
 * Same lookup as the web app (frontend/src/lib/basemap/esri.ts).
 */
const IDENTIFY =
  "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/identify";

export function captureDateUrl(lon: number, lat: number): string {
  const d = 0.005;
  const params = new URLSearchParams({
    geometry: `${lon},${lat}`,
    geometryType: "esriGeometryPoint",
    sr: "4326",
    layers: "top:5,6,7,8,9,10,11,12,13,14,15,16",
    tolerance: "0",
    mapExtent: [lon - d, lat - d, lon + d, lat + d].join(","),
    imageDisplay: "800,800,96",
    returnGeometry: "false",
    f: "json",
  });
  return `${IDENTIFY}?${params.toString()}`;
}

export function parseCaptureDate(body: unknown): string | null {
  const results = (body as { results?: { attributes?: Record<string, unknown> }[] } | null)
    ?.results;
  const raw = results?.[0]?.attributes?.SRC_DATE;
  if (typeof raw !== "string" && typeof raw !== "number") return null;
  const m = /^(\d{4})(\d{2})(\d{2})$/.exec(String(raw));
  return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
}

export async function fetchCaptureDate(lon: number, lat: number): Promise<string | null> {
  try {
    const resp = await fetch(captureDateUrl(lon, lat));
    return resp.ok ? parseCaptureDate(await resp.json()) : null;
  } catch {
    return null;
  }
}
