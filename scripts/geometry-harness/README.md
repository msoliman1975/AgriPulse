# Geometry harness

Standalone, infra-free validation of the three farm-management spatial engines
against **real** field boundaries pulled from OpenStreetMap. It imports and runs
the actual production functions, then verifies the output independently with
shapely.

| Engine | Production function | Check |
|---|---|---|
| Auto-blocking | `app.modules.farms.auto_grid.auto_grid_candidates` | every block ⊆ AoI (no spill past boundary) |
| Sub-block grid | `app.modules.grid.geometry.generate_cells` | every cell ⊆ its block |
| Pivot | `app.modules.farms.pivot_geometry.{circle_polygon,equal_sectors}` | sectors ⊆ circle and tile it (coverage ≈ 1.0) |

## Run

```bash
# from repo root, using the backend venv
backend/.venv/Scripts/python.exe scripts/geometry-harness/fetch_aois.py   # once: pulls 3 AoIs to ./aois
backend/.venv/Scripts/python.exe scripts/geometry-harness/run_harness.py  # runs engines + writes ./out/*.html
```

`run_harness.py` exits non-zero if any AoI fails a containment check, so it
doubles as a CI-style smoke test. Open `out/index.html` (or serve the dir) to
inspect the Leaflet maps: white = AoI, cyan = auto-blocks, orange = sub-grid on
the largest block, purple = pivot + sectors.

## Caveats

- This exercises the **geometry engines only** — not the HTTP/auth/PostGIS
  persist path. On commit, PostGIS reprojects to UTM and recomputes the
  canonical `area_m2`; the harness approximates that with a local
  equirectangular projection about the AoI centroid (metrically equivalent at
  field scale).
- AoIs come from live Overpass queries, so the exact fields may differ run to
  run; the committed `aois/*.geojson` snapshot the set used for the current
  screenshots.
