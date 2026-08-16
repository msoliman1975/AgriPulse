# Audit: what still reads block-level config after the farm-level move

Migrations 0074 / 0076 / 0077 moved imagery and weather configuration from
per-block rows to per-farm rows, with the block rows kept as a fallback for
farms that have not cut over. The gate is `fetch_farm_aoi`, never "does a
farm subscription exist" — 0074 created one for **every** farm, so the
existence predicate would match everywhere.

Thermal (`landsat_c2_l2_st`) is the sharp edge: it is **farm-AOI only** and
has no block rows at all, by construction. Anything gated on block rows
cannot see it, however hard it is failing.

This audit swept every reader of `imagery_aoi_subscriptions` and
`weather_subscriptions` outside their owning repositories.

## Clear

| Area | Why it is fine |
|---|---|
| **Decision trees / recommendations** | Read `block_index_aggregates`, the *output* table. The farm path writes it via `_write_block_aggregates_from_farm`, so per-block numbers exist either way. No subscription read anywhere in `recommendations/` or `shared/conditions/`. Verified in production: all 36 blocks of the cut-over farm carry data for both products. |
| **Backfill** | Fixed by #468 (dispatch), #481 (farm-path index recompute) and #483 (per-product sources). |
| **Purge registry** | Already lists all four farm tables — the "no orphans" CI guard did its job. |
| **`farms/cascade.py`** | Counts block subscriptions it deactivates when a block is archived. Block-scoped by design: archiving a block should not touch a farm row. |
| **`farms/repository.py`** | Uses the block tables as a has-any-data dependency check for block operations. Correct at that scope. |
| **`shared/settings/resolver.py`** | Has its own farm tier (`farm_imagery_overrides`, migration 0020). Different mechanism from subscriptions. |

## Fixed

**Integration health omitted farm-only providers.**
`integrations_health/providers_service.py` gated the provider list on
`EXISTS (block subscriptions)`. Confirmed in production before the fix: the
tenant fetching thermal daily listed `sentinel_hub` and `open_meteo`, and
**not `landsat_pc`** — on the page whose entire job is to say whether a
provider is healthy. A fully cut-over tenant would lose weather from the
page too. Now checks both shapes.

**The simulation clone dropped farm-level configuration.**
`simulation/snapshot.py` listed the two block subscription tables and zero
farm ones, so a cloned tenant arrived with no configuration for any
cut-over farm, and none for thermal at all. The clone *looked* configured —
block rows present — while describing a farm that fetches nothing. Both
farm tables are now carried, with `is_active` forced FALSE like the block
rows, so loading a snapshot still cannot start a real provider fetching.

## Open — needs a product decision, not a patch

### 1. Block-tier cloud-cover is a silent no-op on a cut-over farm

`integrations/service.py` writes `cloud_cover_max_pct` to
`imagery_aoi_subscriptions` for the LandUnit tier. On a cut-over farm the
fetch reads the **farm** subscription's cap, so the block-tier edit saves
successfully and changes nothing. "Reset every per-block override" has the
same problem.

Three options, none obviously right:

- **Write through to the farm subscription.** Honest about what drives the
  fetch, but one block's edit silently changes the whole farm — a surprising
  blast radius from a control labelled per-block.
- **Disable the control** once the farm has cut over, pointing at the
  farm-level setting. No no-op and no surprise, but it removes a capability
  operators may still expect.
- **Leave it**, and accept that the block tier is dead for cut-over farms.
  Cheapest, and the worst for anyone who trusts the UI.

Worth noting alongside: the thermal subscription deliberately carries a
loose cap (80). Scene-level cloud is a weak filter for thermal in both
directions — measured over the reference farm, 4 of 22 scenes with >10%
scene cloud were ≥90% clear over the AOI, and two with modest scene cloud
were 0% clear. Per-pixel `qa_pixel` is the real filter.

### 2. Grid configuration derives its product from block subscriptions

`grid/repository.py` LEFT JOINs `imagery_aoi_subscriptions` to get each
block's product and native pixel size. Once block subscriptions are
deactivated, `product_code` and `native_pixel_m` come back NULL and the
`grid_configs` join (keyed on `s.product_id`) stops matching.

Thermal never appearing here is arguably **correct** — a sub-block grid on a
100 m thermal pixel would be meaningless, and the UI already labels thermal
as a farm-scale signal. The genuine bug is narrower: a farm whose block
subscriptions were deactivated after cutting over loses its grid
configuration display for Sentinel-2 as well.

## The pattern worth remembering

Every one of these failed the same way: **silently, and in the direction of
looking healthy.** A provider vanishes from a health page rather than
showing red. A clone reports configured rather than empty. A setting saves
rather than erroring. A backfill reports success having recomputed the wrong
scenes.

When a predicate keyed on block rows stops describing reality, the result is
almost never an exception — it is an empty set that reads as "nothing to
report".
