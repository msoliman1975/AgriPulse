# CD-4 — ServiceMonitors for workers, tile-server, frontend

[Shared preamble — see README.md]

## Goal
Today only `infra/helm/api/templates/servicemonitor.yaml` exists. Workers, tile-server, and frontend have no Prometheus scrape config — they're observability blind spots. This PR adds equivalents.

## Files to change
- `infra/helm/workers/templates/servicemonitor.yaml` — new (PodMonitor actually, since workers have no Service).
- `infra/helm/tile-server/templates/servicemonitor.yaml` — new.
- `infra/helm/frontend/templates/servicemonitor.yaml` — new.
- `infra/helm/workers/values.yaml` — enable celery prometheus exporter sidecar (image: `ovalmoney/celery-exporter:latest` or pinned digest).
- `infra/helm/frontend/templates/configmap.yaml` (extend existing nginx config) — enable `stub_status` on `/nginx_status` accessible only from localhost; the SM scrapes via an annotation port.
- `infra/helm/tile-server/values.yaml` — TiTiler exposes `/metrics` by default; confirm and document.
- `infra/helm/workers/templates/deployments.yaml` — add the exporter sidecar container.

## Tasks
1. Workers: add a `celery-exporter` sidecar container scraping the Redis broker for queue stats. Expose port 9540. Add a PodMonitor (not ServiceMonitor — workers have no Service) selecting on the workers' pod labels, scraping `:9540/metrics`.
2. Tile-server: confirm TiTiler exposes `/metrics` (it does via Prometheus middleware). Add a ServiceMonitor scraping `:8000/metrics`. If `/metrics` is disabled, enable it via env var first.
3. Frontend: extend the existing nginx configmap to expose `stub_status` on a separate `:8081/nginx_status` listener bound to `127.0.0.1`. Add an `nginx-prometheus-exporter` sidecar (`nginx/nginx-prometheus-exporter:latest` or pinned) on port 9113. ServiceMonitor scrapes `:9113/metrics`.
4. All three SMs/PMs go in the `monitoring` namespace selector (per kube-prometheus-stack defaults) — use `metadata.labels.release: kube-prometheus-stack` so the operator picks them up.
5. Wrap each in `{{- if .Values.serviceMonitor.enabled }}` defaulting to true.

## Out of scope
- Don't change the api chart's ServiceMonitor.
- Don't add Grafana dashboards in this PR — that's a follow-up.
- Don't add alerting rules — also follow-up.

## Definition of done
- `helm template` for each chart renders the SM/PM.
- After deploy, `kubectl get servicemonitor,podmonitor -A` shows the new resources.
- `up{job="missionagre-workers"}` and similar return 1 in Prometheus.
- PR description includes the queries to check post-deploy.
