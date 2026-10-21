"""End-to-end geometry harness for the farm-management spatial engines.

For each real AoI in ./aois/*.geojson this runs the *actual production
functions* and verifies the output with shapely (an independent check, not
the same code path):

  1. AUTO-BLOCKING   app.modules.farms.auto_grid.auto_grid_candidates
        → assert every block candidate is contained in the AoI (no spill).
  2. SUB-BLOCK GRID  app.modules.grid.geometry.generate_cells
        → on the largest block, assert every grid cell is contained in it.
  3. PIVOT           app.modules.farms.pivot_geometry.{circle_polygon,equal_sectors}
        → assert every sector is contained in the circle and the sectors
          tile it (union area ≈ circle area).

The sub-block grid runs in a projected metric CRS (it uses shapely on UTM in
prod); here we substitute a local equirectangular metric projection about the
AoI centroid — visually and metrically equivalent at field scale. Results are
written as a self-contained Leaflet map per AoI under ./out/.
"""

from __future__ import annotations

import json
import math
import sys
from decimal import Decimal
from pathlib import Path

from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

HERE = Path(__file__).parent
sys.path.insert(0, str((HERE / ".." / ".." / "backend").resolve()))

from app.modules.farms import pivot_geometry  # noqa: E402
from app.modules.farms.auto_grid import auto_grid_candidates  # noqa: E402
from app.modules.grid.geometry import generate_cells  # noqa: E402

AOI_DIR = HERE / "aois"
OUT_DIR = HERE / "out"

# Tunables for the demo run.
AUTO_BLOCK_CELL_M = 200
SUBGRID_CELL_M = 40
PIVOT_SECTORS = 6

_M_PER_DEG_LAT = 110_540.0


def _m_per_deg_lon(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


class LocalProj:
    """Equirectangular WGS84 <-> local metres about a reference point."""

    def __init__(self, lon0: float, lat0: float) -> None:
        self.lon0 = lon0
        self.lat0 = lat0
        self.mlon = _m_per_deg_lon(lat0)

    def to_m(self, lon: float, lat: float) -> tuple[float, float]:
        return ((lon - self.lon0) * self.mlon, (lat - self.lat0) * _M_PER_DEG_LAT)

    def from_m(self, x: float, y: float) -> tuple[float, float]:
        return (self.lon0 + x / self.mlon, self.lat0 + y / _M_PER_DEG_LAT)

    def poly_to_m(self, poly: Polygon) -> Polygon:
        return Polygon([self.to_m(x, y) for x, y in poly.exterior.coords])

    def poly_from_m(self, poly: Polygon) -> Polygon:
        return Polygon([self.from_m(x, y) for x, y in poly.exterior.coords])


def _load_aoi(path: Path) -> tuple[dict, Polygon]:
    fc = json.loads(path.read_text())
    geom = fc["geometry"]
    return geom, shape(geom)


def run_aoi(path: Path) -> dict:
    name = path.stem
    geom, aoi = _load_aoi(path)
    c = aoi.centroid
    proj = LocalProj(c.x, c.y)
    aoi_m = proj.poly_to_m(aoi)
    aoi_area_ha = aoi_m.area / 10_000

    report: dict = {"name": name, "aoi_area_ha": round(aoi_area_ha, 2)}

    # ---- 1. AUTO-BLOCKING -------------------------------------------------
    blocks = auto_grid_candidates(geom, cell_size_m=AUTO_BLOCK_CELL_M)
    block_polys = [shape(b["geometry"]) for b in blocks]
    # Spill = area of any block lying outside the AoI (allow a tiny epsilon
    # for the equirectangular round-off between the two projections).
    tol = aoi_m.buffer(0.01)  # 1 cm buffer in metres
    spill_total = 0.0
    worst_spill = 0.0
    for bp in block_polys:
        bp_m = proj.poly_to_m(bp)
        outside = bp_m.difference(tol)
        if not outside.is_empty:
            spill_total += outside.area
            worst_spill = max(worst_spill, outside.area)
    report["auto_block"] = {
        "count": len(blocks),
        "cell_m": AUTO_BLOCK_CELL_M,
        "spill_total_m2": round(spill_total, 3),
        "worst_block_spill_m2": round(worst_spill, 3),
        "pass": spill_total < 1.0,  # < 1 m² total spill across all blocks
    }

    # ---- 2. SUB-BLOCK GRID (on the largest block) -------------------------
    largest = max(block_polys, key=lambda p: proj.poly_to_m(p).area)
    block_m = proj.poly_to_m(largest)
    cells = list(generate_cells(boundary_utm_wkt=block_m.wkt, cell_size_m=Decimal(SUBGRID_CELL_M)))
    cell_polys_m = [shape({"type": "Polygon", "coordinates": _wkt_coords(c.geom_wkt)}) for c in cells]
    block_tol = block_m.buffer(0.01)
    grid_spill = sum(
        cp.difference(block_tol).area for cp in cell_polys_m if not cp.difference(block_tol).is_empty
    )
    report["sub_grid"] = {
        "count": len(cells),
        "cell_m": SUBGRID_CELL_M,
        "spill_total_m2": round(grid_spill, 3),
        "pass": grid_spill < 1.0,
    }
    cell_polys_wgs = [proj.poly_from_m(cp) for cp in cell_polys_m]

    # ---- 3. PIVOT ---------------------------------------------------------
    # Radius that comfortably fits inside the AoI bbox.
    minx, miny, maxx, maxy = aoi_m.bounds
    radius = min(maxx - minx, maxy - miny) * 0.30
    radius = max(60.0, min(radius, 400.0))
    circle = pivot_geometry.circle_polygon(lat=c.y, lon=c.x, radius_m=radius)
    sectors = pivot_geometry.equal_sectors(
        lat=c.y, lon=c.x, radius_m=radius, sector_count=PIVOT_SECTORS
    )
    circle_poly = shape(circle)
    sector_polys = [shape(s) for s in sectors]
    circle_m = proj.poly_to_m(circle_poly)
    union_m = unary_union([proj.poly_to_m(sp) for sp in sector_polys])
    sector_spill = sum(
        proj.poly_to_m(sp).difference(circle_m.buffer(0.5)).area for sp in sector_polys
    )
    coverage = union_m.area / circle_m.area if circle_m.area else 0.0
    report["pivot"] = {
        "sectors": PIVOT_SECTORS,
        "radius_m": round(radius, 1),
        "sector_spill_m2": round(sector_spill, 3),
        "coverage_ratio": round(coverage, 4),
        "pass": sector_spill < 5.0 and 0.98 <= coverage <= 1.02,
    }

    # ---- Render -----------------------------------------------------------
    _render_html(
        name=name,
        aoi=geom,
        blocks=[mapping(p) for p in block_polys],
        grid_block=mapping(largest),
        grid_cells=[mapping(p) for p in cell_polys_wgs],
        pivot_circle=circle,
        pivot_sectors=sectors,
        report=report,
    )
    return report


def _wkt_coords(wkt: str) -> list:
    # generate_cells emits "POLYGON ((x y, x y, ...))"; reuse shapely to parse.
    from shapely import wkt as _w

    poly = _w.loads(wkt)
    return [list(map(list, poly.exterior.coords))]


def _render_html(*, name, aoi, blocks, grid_block, grid_cells, pivot_circle, pivot_sectors, report):
    ab = report["auto_block"]
    sg = report["sub_grid"]
    pv = report["pivot"]

    def badge(ok: bool) -> str:
        return (
            '<span style="color:#fff;background:#16a34a;padding:1px 6px;border-radius:4px">PASS</span>'
            if ok
            else '<span style="color:#fff;background:#dc2626;padding:1px 6px;border-radius:4px">FAIL</span>'
        )

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Geometry harness — {name}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body{{margin:0;font-family:system-ui,sans-serif}}
  #map{{height:78vh}}
  .panel{{padding:8px 14px;font-size:13px;line-height:1.5;background:#0f172a;color:#e2e8f0}}
  .panel b{{color:#fff}} .sw{{display:inline-block;width:12px;height:12px;margin-right:4px;vertical-align:-1px;border:1px solid #333}}
</style></head><body>
<div class="panel">
  <b>{name}</b> &nbsp;|&nbsp; AoI {report['aoi_area_ha']} ha &nbsp;|&nbsp;
  <span class="sw" style="background:#22d3ee55;border-color:#22d3ee"></span>Auto-blocks: {ab['count']} @ {ab['cell_m']}m, spill {ab['spill_total_m2']} m² {badge(ab['pass'])} &nbsp;|&nbsp;
  <span class="sw" style="background:#f59e0b55;border-color:#f59e0b"></span>Sub-grid: {sg['count']} @ {sg['cell_m']}m, spill {sg['spill_total_m2']} m² {badge(sg['pass'])} &nbsp;|&nbsp;
  <span class="sw" style="background:#a78bfa55;border-color:#a78bfa"></span>Pivot: {pv['sectors']} sectors, r={pv['radius_m']}m, coverage {pv['coverage_ratio']} {badge(pv['pass'])}
</div>
<div id="map"></div>
<script>
const aoi={json.dumps(aoi)};
const blocks={json.dumps({"type":"GeometryCollection","geometries":blocks})};
const gridBlock={json.dumps(grid_block)};
const gridCells={json.dumps({"type":"GeometryCollection","geometries":grid_cells})};
const circle={json.dumps(pivot_circle)};
const sectors={json.dumps({"type":"GeometryCollection","geometries":pivot_sectors})};

const map=L.map('map');
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{maxZoom:21,attribution:'Esri World Imagery'}}).addTo(map);

const aoiLayer=L.geoJSON(aoi,{{style:{{color:'#ffffff',weight:3,fill:false}}}}).addTo(map);
L.geoJSON(blocks,{{style:{{color:'#22d3ee',weight:1,fillColor:'#22d3ee',fillOpacity:0.30}}}}).addTo(map);
L.geoJSON(gridBlock,{{style:{{color:'#f59e0b',weight:2,fill:false,dashArray:'4 3'}}}}).addTo(map);
L.geoJSON(gridCells,{{style:{{color:'#f59e0b',weight:0.7,fillColor:'#f59e0b',fillOpacity:0.25}}}}).addTo(map);
L.geoJSON(circle,{{style:{{color:'#a78bfa',weight:2,fill:false}}}}).addTo(map);
L.geoJSON(sectors,{{style:{{color:'#a78bfa',weight:1,fillColor:'#a78bfa',fillOpacity:0.18}}}}).addTo(map);

map.fitBounds(aoiLayer.getBounds(),{{padding:[30,30]}});
</script></body></html>"""
    out = OUT_DIR / f"{name}.html"
    out.write_text(html, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    aois = sorted(AOI_DIR.glob("*.geojson"))
    if not aois:
        raise SystemExit("No AoIs — run fetch_aois.py first.")
    reports = [run_aoi(p) for p in aois]

    # Console summary.
    print("\n=== GEOMETRY HARNESS SUMMARY ===")
    all_pass = True
    for r in reports:
        ab, sg, pv = r["auto_block"], r["sub_grid"], r["pivot"]
        ok = ab["pass"] and sg["pass"] and pv["pass"]
        all_pass &= ok
        print(f"\n{r['name']}  ({r['aoi_area_ha']} ha)  {'PASS' if ok else 'FAIL'}")
        print(f"  auto-block : {ab['count']:>3} blocks  spill={ab['spill_total_m2']} m²  "
              f"(worst {ab['worst_block_spill_m2']} m²)  {'ok' if ab['pass'] else 'FAIL'}")
        print(f"  sub-grid   : {sg['count']:>3} cells   spill={sg['spill_total_m2']} m²  "
              f"{'ok' if sg['pass'] else 'FAIL'}")
        print(f"  pivot      : {pv['sectors']} sectors  coverage={pv['coverage_ratio']}  "
              f"spill={pv['sector_spill_m2']} m²  {'ok' if pv['pass'] else 'FAIL'}")

    # index.html
    links = "".join(f'<li><a href="{r["name"]}.html">{r["name"]}</a></li>' for r in reports)
    (OUT_DIR / "index.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>Geometry harness</title>"
        f"<h2>Geometry harness output</h2><ul>{links}</ul>",
        encoding="utf-8",
    )
    print(f"\nMaps written to {OUT_DIR}")
    print("OVERALL:", "ALL PASS" if all_pass else "SOME FAILED")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
