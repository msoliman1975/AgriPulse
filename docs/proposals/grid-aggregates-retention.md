# Sub-block grid observation retention & cost (V2-3)

**Status:** decided — *compress-only, no hard retention* (2026-06-06).
**Scope:** `tenant_<id>.block_grid_aggregates` (per-cell index aggregates,
the highest-volume table the grid feature produces).

## TL;DR

- Compression is **on** (`compress_after = 30 days`, segment by
  `block_id, index_code`) from migration `0034`. It keeps stored volume
  for the kept window small (~90% on these numeric series).
- **No retention policy** is applied by default — we keep all history.
- A disabled scaffold exists so retention is a one-liner when storage
  becomes a concern: set `GRID_AGGREGATES_RETENTION_DAYS` and run
  `python -m scripts.apply_grid_retention`.

## Why compress-only (not a hard retention cap)

Per-cell history has real analytical value (season-over-season comparison
of a specific patch), and at current scale compression makes keeping it
cheap. We'd rather not drop data we can't get back until there's evidence
storage is actually a problem. The lever is wired and documented, so
enabling retention later is trivial and non-breaking.

## Cost model

Assumptions (design-doc scale):

| Parameter | Value |
|---|---|
| Cell size | 20 m (Sentinel-2) |
| Block size | ~10 ha → ~250 cells/block |
| Indices stored per cell | up to 6 |
| Usable scenes/yr (after cloud filtering) | ~50 |
| Blocks/tenant | ~50 |

Rows/tenant/yr ≈ 250 × 6 × 50 × 50 ≈ **~10M rows/yr**.

Row width is ~12 small columns (timestamptz, 4× uuid, text index code,
4× numeric, 2× int). Budget **~120 B/row uncompressed**:

- Uncompressed: ~10M × 120 B ≈ **~1.2 GB/tenant/yr**.
- Compressed (columnar, ~90% on these series): **~120–200 MB/tenant/yr**.

So the *kept* window is cheap; the only risk is **unbounded linear
growth** over many years. Compress-only is fine for the foreseeable
horizon; retention becomes worthwhile once a tenant accumulates several
years and the older tail is no longer queried.

## Enabling retention later

1. Choose a window (recommended **730 days ≈ 24 months** = ~2 seasons).
2. Set the knob and apply it across tenants:

   ```bash
   GRID_AGGREGATES_RETENTION_DAYS=730 python -m scripts.apply_grid_retention
   # dry run first:
   python -m scripts.apply_grid_retention --dry-run
   ```

   The applier adds a TimescaleDB `add_retention_policy(...)` per tenant
   (`if_not_exists`, idempotent). Running it with the knob **unset**
   removes the policy again (compress-only). **Retention is
   irreversible** for chunks already dropped past the window.

3. Keep `block_index_aggregates` (block-level) retention longer or
   indefinite — it's far smaller and feeds baselines.

## Partitioning note (future tuning, not urgent)

`block_grid_aggregates` uses `chunk_time_interval = 7 days` + a 4-way
`block_id` space partition (mirrors `block_index_aggregates` so chunks
align for joins). At ~5-day revisit a 7-day chunk holds roughly one
scene's cells; over years this is many small chunks. If chunk count ever
hurts planning time, raise the interval (e.g. 30 days, matching
`compress_after`) via `set_chunk_time_interval` — this affects only *new*
chunks and is safe to do live. Not changed here; flagged for when volume
warrants it.
