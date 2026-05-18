import type { Polygon } from "geojson";

const EARTH_R = 6_378_137; // WGS-84 equatorial radius (m)

// Spherical-excess approximation. Accurate enough for human-scale block
// previews (sub-1% error up to ~50 km). Returns area in square metres.
// The first ring is exterior; subsequent rings are holes (subtracted).
export function approxPolygonAreaM2(poly: Polygon): number {
  let total = 0;
  for (let i = 0; i < poly.coordinates.length; i++) {
    const a = ringAreaM2(poly.coordinates[i]);
    total += i === 0 ? Math.abs(a) : -Math.abs(a);
  }
  return total;
}

export function ringAreaM2(ring: number[][]): number {
  if (ring.length < 3) return 0;
  let total = 0;
  for (let i = 0; i < ring.length; i++) {
    const [lon1, lat1] = ring[i];
    const [lon2, lat2] = ring[(i + 1) % ring.length];
    total +=
      (((lon2 - lon1) * Math.PI) / 180) *
      (2 + Math.sin((lat1 * Math.PI) / 180) + Math.sin((lat2 * Math.PI) / 180));
  }
  return (total * EARTH_R * EARTH_R) / 2;
}

export function haversineMeters(a: [number, number], b: [number, number]): number {
  const [lon1, lat1] = a;
  const [lon2, lat2] = b;
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const x = Math.sin(dphi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_R * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

// Sum of haversine distances between consecutive coords of the outer
// ring. Skips the trailing closing-point if the ring is closed (first ==
// last) so a 4-vertex square reports 4 edges, not 5.
export function polygonPerimeterM(poly: Polygon): number {
  const ring = poly.coordinates[0];
  if (!ring || ring.length < 2) return 0;
  const closed =
    ring.length > 2 &&
    ring[0][0] === ring[ring.length - 1][0] &&
    ring[0][1] === ring[ring.length - 1][1];
  const end = closed ? ring.length - 1 : ring.length;
  let total = 0;
  for (let i = 1; i < end; i++) {
    total += haversineMeters(ring[i - 1] as [number, number], ring[i] as [number, number]);
  }
  // For a closed ring, the implicit closing edge:
  if (closed) {
    total += haversineMeters(ring[end - 1] as [number, number], ring[0] as [number, number]);
  }
  return total;
}

// "ha" if ≥ 1 hectare (10 000 m²), "m²" otherwise. One decimal for ha,
// integer for m². No locale-specific separators — keeps the readout
// monospace-friendly during live updates.
export function formatArea(m2: number): string {
  if (!Number.isFinite(m2) || m2 <= 0) return "—";
  if (m2 >= 10_000) return `${(m2 / 10_000).toFixed(2)} ha`;
  return `${Math.round(m2)} m²`;
}

// "km" if ≥ 1000 m, "m" otherwise.
export function formatDistance(m: number): string {
  if (!Number.isFinite(m) || m <= 0) return "—";
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${Math.round(m)} m`;
}
