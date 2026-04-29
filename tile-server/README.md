# MissionAgre tile server

Wraps [TiTiler](https://developmentseed.org/titiler/) to serve XYZ/WMTS tiles
from MissionAgre's COG storage. ARCHITECTURE.md § 9 commits this stack —
keep changes small and prefer upstream features over local forks.

## Running locally (production-like)

```bash
docker build -t missionagre/tile-server:dev .
docker run --rm -p 8000:8000 \
  -e AWS_S3_ENDPOINT_URL=http://host.docker.internal:9000 \
  -e AWS_ACCESS_KEY_ID=missionagre \
  -e AWS_SECRET_ACCESS_KEY=missionagre-dev \
  missionagre/tile-server:dev
```

Then `curl http://localhost:8000/healthz` for the readiness probe and
`http://localhost:8000/cog/info?url=...` for raster metadata. Full API
reference: <https://developmentseed.org/titiler/endpoints/cog/>.

In-cluster, the chart at [`infra/helm/tile-server/`](../infra/helm/tile-server/)
runs this image behind the NGINX ingress with TLS terminated by cert-manager.
