# AgriPulse tile server

Wraps [TiTiler](https://developmentseed.org/titiler/) to serve XYZ/WMTS tiles
from AgriPulse's COG storage. ARCHITECTURE.md Â§ 9 commits this stack â€”
keep changes small and prefer upstream features over local forks.

## Running locally (production-like)

```bash
docker build -t agripulse/tile-server:dev .
docker run --rm -p 8000:8000 \
  -e AWS_S3_ENDPOINT_URL=http://host.docker.internal:9000 \
  -e AWS_ACCESS_KEY_ID=agripulse \
  -e AWS_SECRET_ACCESS_KEY=agripulse-dev \
  agripulse/tile-server:dev
```

Then `curl http://localhost:8000/healthz` for the readiness probe and
`http://localhost:8000/cog/info?url=...` for raster metadata. Full API
reference: <https://developmentseed.org/titiler/endpoints/cog/>.

In-cluster, the chart at [`infra/helm/tile-server/`](../infra/helm/tile-server/)
runs this image behind the NGINX ingress with TLS terminated by cert-manager.

## The `cutline` algorithm

`/cog/tiles/...` and `/cog/statistics` accept two extra parameters:

```
?algorithm=cutline&algorithm_params={"aoi":"<aoi_hash>"}
```

They cut what is rendered to a farm's own boundary. Everything outside it
comes back transparent.

The statistics take the parameter so one rule cuts both the picture and the
legend. Measured on a prod farm raster the counts do not move: statistics
are read at the raster's own resolution, where the stored mask already
applied this rule. It bites when a raster is larger than `max_size` and the
read is decimated.

The pipeline already cuts an index raster to the farm when it writes it,
but only on the raster's own pixel grid: a 10 m pixel whose centre is
inside the farm is stored whole, so up to 5 m of colour sits outside the
border, and up to 15 m on the 30 m thermal product. This cuts a second
time on the grid of the image being returned - screen pixels - so the
edge follows the boundary at any zoom, with no raster rewritten and no
backfill.

The boundary is read from `aoi/<aoi_hash>.geojson` in the imagery bucket,
in EPSG:4326. The backend writes it (`app/modules/imagery/boundary.py`)
on every farm-scene compute, and `imagery.publish_farm_boundaries` writes
it for farms that already have scenes. `aoi_hash` is a hash of the
polygon, so the object is content-addressed and cached for the life of
the process.

A farm with no boundary object renders uncut, exactly as it did before
this existed. Nothing 404s and no map goes empty.

Cost, measured in the running image on a 512-pixel tile: about 0.1 ms for
a tile wholly inside the farm, and about 10 ms for one the border crosses,
against roughly 120 ms for the tile itself. See `_inside_mask` for why it
is not a single call to `rasterio.features.geometry_mask`.

Tests are in `tests/`, and run in CI without the image:

```bash
pip install "titiler.core==0.21.1" "rio-tiler==7.4.0" pytest
python -m pytest tests -q
```

`tests/verify_in_pod.py` and `tests/check_tile_in_pod.py` are the same
checks for a shell inside the running container, where there is no pytest;
the second renders one real tile twice and compares.
