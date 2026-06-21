# Index accuracy check

Validates our stored Sentinel-2 index aggregates (`block_index_aggregates`)
against **CDSE's own server-side computation** — the Sentinel Hub **Statistical
API** — over the *same* imagery we ingest. Because the source pixels are
identical, any discrepancy isolates a defect in *our* pipeline (band scaling,
AOI masking, cloud masking, raster sizing, aggregation) rather than mixing in
atmospheric-correction differences between providers.

Two reference modes per (block, scene):

- **Mode A – replicate** — same band math, no cloud mask. Apples-to-apples check
  of our computation; should match our stored means to sub-percent.
- **Mode B – cloud-mask** — same band math, SCL clouds/shadows/cirrus/snow
  excluded. The Mode B − Mode A gap quantifies the impact of our *missing* cloud
  mask.

## Run

It must run **inside the API pod** (it has `SENTINEL_HUB_*` creds, egress to
CDSE, DB access via psycopg, and app settings). CDSE trial accounts are
rate-limited, hence the `--sleep` pacing + 429 backoff.

```bash
NODE=167.233.98.216
API=$(ssh root@$NODE "kubectl -n agripulse get po -l app.kubernetes.io/name=agripulse-api -o name | head -1")
API=${API#pod/}

ssh root@$NODE "kubectl -n agripulse exec -i $API -- python - --auto-low 4 --auto-high 2 --sleep 4" \
    < compare_indices.py > agrosina-report.json 2> run.log

python analyze_report.py agrosina-report.json
```

Key args: `--tenant-slug` (default `agrosina`), `--dates` (CSV `YYYY-MM-DD`, else
auto-pick `--auto-low` lowest-cloud + `--auto-high` highest-cloud dates),
`--blocks` (CSV names), `--no-mode-b`, `--sleep` (inter-call seconds).

The JSON (`{meta, summary, comparisons[]}`) goes to **stdout**; a human summary
to **stderr**. Re-run periodically as a regression check after any change to the
imagery fetch / index computation path.

## Latest finding

See [`docs/reports/index-accuracy-agrosina-2026-06-20.md`](../../docs/reports/index-accuracy-agrosina-2026-06-20.md).
Headline: formulas/scaling are **correct** (well-sampled blocks match CDSE to
<0.001 on all 7 indices), but our Process-API fetch omits output resolution, so
AOIs are resampled onto a fixed 256×256 grid instead of native 10 m — which
inflates pixel counts 26–56× and injects a systematic per-block bias up to
~0.03 NDVI on smaller/non-square blocks.
