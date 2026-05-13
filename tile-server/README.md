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
