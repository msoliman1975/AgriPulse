"""Fetch 3 real farmland AoIs from OpenStreetMap (Overpass API).

We pull closed `landuse=farmland` ways in known agricultural bboxes, then
pick three with *diverse* shapes (a compact/convex one, an irregular/concave
one, and a mid-complexity one) so the clipping algorithm is exercised on
real, non-synthetic field boundaries.

Saves each as GeoJSON under ./aois/. Run once; the harness reads the files.
"""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import Polygon

HERE = Path(__file__).parent
AOI_DIR = HERE / "aois"

OVERPASS = "https://overpass-api.de/api/interpreter"

# Agricultural areas with clearly-mapped fields in OSM. Small bboxes keep the
# response light. (south, west, north, east)
BBOXES = {
    "nile_delta": (30.95, 31.10, 31.00, 31.18),   # Nile Delta smallholdings
    "fayoum": (29.30, 30.70, 29.36, 30.82),        # Fayoum irrigated fields
    "reclaimed_desert": (30.40, 30.20, 30.48, 30.35),  # West-Delta reclamation
}


def _overpass_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    return (
        "[out:json][timeout:90];"
        f'(way["landuse"="farmland"]({s},{w},{n},{e});'
        f'way["landuse"="orchard"]({s},{w},{n},{e}););'
        "out geom;"
    )


def _fetch(bbox: tuple[float, float, float, float]) -> list[dict]:
    query = _overpass_query(bbox)
    body = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        OVERPASS,
        data=body,
        headers={"User-Agent": "agripulse-geometry-harness/1.0"},
    )
    # Public map data; tolerate corporate TLS-MITM (Netskope) with an
    # unverified context — this is a throwaway test fetch, not app traffic.
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
        payload = json.loads(resp.read().decode())
    return payload.get("elements", [])


def _way_to_polygon(el: dict) -> Polygon | None:
    geom = el.get("geometry")
    if not geom or len(geom) < 4:
        return None
    ring = [(p["lon"], p["lat"]) for p in geom]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    try:
        poly = Polygon(ring)
    except Exception:
        return None
    if not poly.is_valid or poly.is_empty:
        return None
    return poly


def _approx_area_m2(poly: Polygon) -> float:
    # Rough metric area for filtering (equirectangular about centroid).
    import math

    lat0 = poly.centroid.y
    m_lat = 110_540.0
    m_lon = 111_320.0 * math.cos(math.radians(lat0))
    minx, miny, _, _ = poly.bounds
    metric = Polygon([((x - minx) * m_lon, (y - miny) * m_lat) for x, y in poly.exterior.coords])
    return metric.area


def main() -> None:
    candidates: list[tuple[float, Polygon]] = []
    for name, bbox in BBOXES.items():
        try:
            els = _fetch(bbox)
        except Exception as exc:  # pragma: no cover - network
            print(f"[{name}] fetch failed: {exc}")
            continue
        for el in els:
            poly = _way_to_polygon(el)
            if poly is None:
                continue
            area = _approx_area_m2(poly)
            # Keep fields between 1.5 ha and 60 ha — big enough for a few
            # auto-blocks, small enough to render cleanly.
            if 15_000 <= area <= 600_000:
                candidates.append((area, poly))
        print(f"[{name}] usable fields: {sum(1 for a, _ in candidates)}")

    if not candidates:
        raise SystemExit("No AoIs fetched — check network / Overpass availability.")

    # Diversity by convexity ratio (area / convex-hull area): low = concave.
    scored = []
    for area, poly in candidates:
        convexity = poly.area / poly.convex_hull.area if poly.convex_hull.area else 1.0
        verts = len(poly.exterior.coords) - 1
        scored.append((convexity, verts, area, poly))

    # Pick: most concave, most vertices, and a mid/compact one.
    scored.sort(key=lambda t: t[0])           # by convexity asc
    most_concave = scored[0]
    scored.sort(key=lambda t: t[1], reverse=True)  # by vertex count desc
    most_complex = next((s for s in scored if s[3] is not most_concave[3]), scored[0])
    scored.sort(key=lambda t: abs(t[0] - 0.95))    # near-convex/compact
    compact = next(
        (s for s in scored if s[3] not in (most_concave[3], most_complex[3])), scored[0]
    )

    chosen = {
        "aoi_concave": most_concave[3],
        "aoi_complex": most_complex[3],
        "aoi_compact": compact[3],
    }
    for fname, poly in chosen.items():
        fc = {
            "type": "Feature",
            "properties": {
                "source": "OpenStreetMap landuse=farmland/orchard",
                "vertices": len(poly.exterior.coords) - 1,
                "approx_area_m2": round(_approx_area_m2(poly)),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[list(c) for c in poly.exterior.coords]],
            },
        }
        out = AOI_DIR / f"{fname}.geojson"
        out.write_text(json.dumps(fc, indent=2))
        print(f"wrote {out}  ({fc['properties']['vertices']} verts, "
              f"{fc['properties']['approx_area_m2']/10_000:.1f} ha)")


if __name__ == "__main__":
    main()
