# MASTER PROMPT — Thermal source integration: close the LST / CWSI / SMI gap

You are implementing a single-initiative build in the AgriPulse repo (`C:\Users\mosoliman\projects\MissionAgre`).
Goal: **add a thermal imagery source and ship the three indices that depend on it — LST, CWSI, SMI** — implemented, tested, deployed and prod-verified.

The investigation is **already done**. Do not redo it. Everything in "Locked findings" below was verified against live endpoints from the production node and from inside the running API pod on **14 Aug 2026**. Re-deriving it wastes a session; re-checking one fact when something contradicts it is fine.

---

## Read first (authoritative)

1. **`docs/guide/thermal-integration-study.html`** — the full study: routes priced, two corrections to the gap
   analysis, the resolution problem, and the build shape. **Source of truth for this work.**
   Also published at `https://claude.ai/code/artifact/aa086423-d201-4aa8-a9c4-d19b14ad5f68`.
   (Uncommitted as of writing — it is a working-tree file, not on `origin/main`.)
2. **`docs/guide/agri-indices-gap-analysis.html` § 04** — the document this study answers. Note that its
   recommendation is **wrong for our account** — see Locked finding L1.
3. Code you will touch, read before editing:
   `backend/app/modules/imagery/providers/protocol.py` (the contract — do not change it),
   `backend/app/modules/imagery/providers/sentinel_hub.py` (the adapter to mirror),
   `backend/app/modules/imagery/tasks.py` (the one hardcoded seam, see L5),
   `backend/app/modules/indices/computation.py` (pure-numpy formulas, `CALC_VERSION`, `MASK_RULESET`).
4. Memory files already in context: `project_indices_gap_audit_build`, `project_farm_level_subscriptions`,
   `feedback_frontend_backend_constant_drift`, `feedback_read_the_vocabulary_dont_infer_it`,
   `feedback_cast_plus_string_bind_family`, `feedback_ci_concurrency_cancels_merge_builds`,
   `feedback_overlay_bump_after_merge`, `feedback_windows_dev_env`, `feedback_browser_body_can_lie`.

---

## Locked findings (verified — do not re-litigate)

**L1 — Our CDSE account does NOT serve the product the gap analysis recommended.**
Production runs on the **CDSE free tier** (`sh.dataspace.copernicus.eu`), not commercial Sentinel Hub — the
commercial trial expired. Enumerated with the live prod credentials, our account serves exactly 10 collections:
`landsat-ot-l1`, `sentinel-1-grd`, `sentinel-2-l1c`, `sentinel-2-l2a`, `sentinel-3-olci`, `sentinel-3-olci-l2`,
`sentinel-3-slstr`, `sentinel-3-slstr-l2`, `sentinel-3-synergy-l2`, `sentinel-5p-l2`.
Landsat is **Level-1 (TOA radiance)**, not Collection-2 Level-2 Surface Temperature. Taking it means writing the
retrieval chain ourselves. **Do not.**

**L2 — Sentinel-3 SLSTR is ruled out on geometry, not cost.**
It works with our credentials (verified: HTTP 200, real LST 297.6–308.4 K, **0.0067 PU** per request). But
Bashier Elkhier's entire extent is **786 m × 1085 m** and one SLSTR pixel is 1 km — *larger than the whole farm*,
blending canopy with desert. Not a "farm-level baseline". Do not use it for this.

**L3 — USGS LandsatLook asset URLs are gated. The 200 is a lie.**
The STAC catalog is public, but a ranged GET on the `ST_B10` href 302s to `ers.cr.usgs.gov` and returns
**33 KB of HTML login page under a `200`** (magic bytes `3c21 444f` = `<!DOCTYP`). Classic
`feedback_browser_body_can_lie`. Do not build against `landsatlook.usgs.gov/data/`.

**L4 — THE CHOSEN ROUTE: Landsat C2 L2 ST via Microsoft Planetary Computer. Free, anonymous.**
Verified end to end from the prod node and inside the API pod:

| What | Verified value |
|---|---|
| STAC search | `https://planetarycomputer.microsoft.com/api/stac/v1/search`, collection `landsat-c2-l2`, **no auth**, HTTP 200 |
| Anonymous SAS token | `https://planetarycomputer.microsoft.com/api/sas/v1/token/landsat-c2-l2` → HTTP 200, expires ~1 h, **no account** |
| Asset host | `landsateuwest.blob.core.windows.net` (West Europe — short hop from Hetzner) |
| Ranged GET | HTTP **206**, magic `4949 2a00` (`II*\0` = real TIFF), 0.159 s |
| CRS | **`EPSG:32636`** — already our storage CRS for Egypt. **No reprojection step.** |
| Raster | 7791 × 7641, `uint16`, nodata `0.0`, res 30 m, overviews `[2,4,8,16,32,64]` |
| Perf (in pod) | open **0.34 s**, 34×34 window read **0.05 s**. rasterio 1.5.0 / GDAL 3.12.1 |
| Sanity values | LST 27.21 / 27.42 / 27.60 °C over irrigated ground near Suez, 08:17 UTC, Aug |
| Scaling | **`K = DN × 0.00341802 + 149.0`**, `°C = K − 273.15` |
| Same-item assets | `lwir11` (gsd **100**), `red`, `nir08`, `qa_pixel` — all on the identical item |
| Cadence (real farm bbox, 12 mo) | **86 scenes**, L8 43 + L9 43, median gap **7 d**, mean 4.2 d, max 8 d |
| Scene cloud ≤10% | 58 / 86 (67%) — a **floor**, `eo:cloud_cover` describes a 185 km scene, not our 85 ha farm |
| Overpass | 08:16–08:24 UTC ≈ 10:20 local winter / 11:20 summer |

Fallback if PC ever withdraws: the **byte-identical** files are in AWS `s3://usgs-landsat/` (requester-pays).
That is a credentials change in the adapter, not a rewrite. PC has **no ECOSTRESS** (checked all 136 collections),
so ECOSTRESS stays phase 2 against NASA Earthdata.

**L5 — There is exactly ONE hardcoded seam in the pipeline.**
`_make_provider()` in `backend/app/modules/imagery/tasks.py` (~line 104) unconditionally returns
`SentinelHubProvider()`. Everything downstream is already product-code-parameterised: storage keys
(`storage.py`), pgstac collection ids (`pgstac.py`), band order (from `product["bands"]`), aggregates.
`_lookup_product()` already selects `provider_code`. Dispatch on it. A `set_provider_factory` test seam exists.

**L6 — Resolution is the real constraint, and it is a product decision.**
Thermal is **100 m native** resampled to a 30 m grid. Block stats from prod: min **0.53 ha**, avg **3.10 ha**
(~158 m side), max **25.07 ha**. So: farm = ~8 × 11 independent samples (honest); a 25 ha block ≈ 5 × 5 (real
signal); a 0.53 ha block is a fraction of one pixel (must inherit the farm value, not fake precision).
84 blocks across 3 tenants (80 / 0 / 4).

**L7 — SMI's NDVI must come from the Landsat scene, not our Sentinel-2 stack.**
The LST–NDVI triangle is only valid if both surfaces are the same ground at the same moment. `red` and `nir08`
ride in the same item. Keep the 10 m S2 NDVI as the one we chart; use Landsat NDVI inside SMI.

**L8 — CWSI ships simplified first.**
Air temperature already arrives hourly from Open-Meteo; interpolate to the overpass minute. A rigorous CWSI
needs a crop- and site-specific non-water-stressed baseline. Ship the temperature-difference form and carry
the Egyptian-mango calibration as known debt — same species of debt the guide flags for LAI. Say so in the UI.

---

## Build order

Each step is a PR unless noted. Migrations are created **LAST** within each PR, chained off the then-current head.

1. **Open the provider seam.** Make `_make_provider()` dispatch on provider code from `_lookup_product()`.
   No behaviour change for `sentinel_hub`. Ships alone, green, first.
2. **Add `backend/app/modules/imagery/providers/landsat_pc.py`.** Satisfies the existing `ImageryProvider`
   protocol unchanged. `discover()` → PC STAC search. `fetch()` → windowed rasterio read over `/vsicurl`.
   Cache the anonymous SAS token in-process exactly like the SH OAuth token (same shape, ~1 h expiry, refresh
   with a lead). Set `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`.
3. **Seed the catalog.** Public migration: provider row + `landsat_c2_l2_st` product row (bands incl. `lwir11`,
   `red`, `nir08`, `qa_pixel`) + three `indices_catalog` rows (`lst`, `cwsi`, `smi`).
   Live spectral catalog today is 9: `bsi, evi, gndvi, msi, ndmi, ndre, ndvi, ndwi, savi`.
4. **Formulas + a second mask ruleset.** Three functions in `indices/computation.py`. Landsat `qa_pixel` is a
   **different encoding** from S2 `SCL` — the existing `s2_scl_v1` class list does **not** transfer; add a
   `landsat_qa_pixel_v1` ruleset. **Bump `CALC_VERSION`.**
5. **Teach the stack that an index can have a unit.** The one genuinely new concept: every index today is a
   dimensionless ratio bounded near −1..1; LST is °C. Touches `value_min`/`value_max` semantics, chart axes,
   tooltips, baselines, and en+ar formatting. Small but wide.
6. **Mirror constants to the frontend with a lock-step test.** Drift here degrades the UI silently
   (`feedback_frontend_backend_constant_drift`). en + ar locale entries. Do not invent TS unions —
   read the vocabulary (`feedback_read_the_vocabulary_dont_infer_it`).
7. **UI resolution labelling** per L6. Farm-scale default; qualify block values by block size; label the
   100 m resolution wherever a thermal number appears. Thermal must **not** drive per-block irrigation volumes yet.

No change needed to storage keys, pgstac collections, aggregate tables or the tile server.

---

## Migration numbers

At the time of writing, `origin/main` heads are **public `0065`**, **tenant `0077`**.
**Re-check immediately before every push** — this repo has lost the migration-number race twice
(`project_indices_gap_audit_build`). `alembic.ini` and migration files must be **ASCII** (cp1252 locale).
Provide **data-safe downgrades** (CI runs the roundtrip up *and* down on a shared DB).
asyncpg raw SQL on nullable text needs `CAST`; postfix `:x::text` dies inside `text()`
(`feedback_cast_plus_string_bind_family`).

---

## Standard workflow per PR

1. **Branch off fresh `origin/main` explicitly** — ~16 worktrees exist and other sessions hold `main` checked
   out (`feedback_verify_base_branch_before_branching`). Never commit to `main`.
2. Implement the slice; match surrounding style.
3. **Local verify:** backend → `./scripts/dev-stack.ps1 -Phase api` (uvicorn runs **without** `--reload`; a stale
   process serves old routes). Run the module's pytest. Frontend → `tsc -b` (CI runs `tsc -b`, not `tsc`) + eslint;
   use `node node_modules/typescript/bin/tsc` if `.bin` shims are missing. Do **not** `prettier --write` a broad
   glob here. Local pre-commit `--all-files` lies on Windows — trust the CI job log.
4. **Commit** with git email `msoliman_75@hotmail.com` (`--reset-author` if the work email auto-attaches).
   Push, open PR with `gh` (`GH_TOKEN=…` prefix; do not touch the `gh` keyring login; PAT expires 2026-09-05).
5. CI green → squash-merge. **A "cancelled" run may still have pushed its images — read the job log, never the
   run conclusion** (`feedback_ci_concurrency_cancels_merge_builds`).
6. **Deploy:** bump the hetzner overlay image tags (`infra/argocd/overlays/hetzner/values.yaml`) to the
   **merge-commit SHA**. Backend/migration PRs bump **api + workers together**; frontend bumps frontend.
   **Wait for the containers job to publish images first**, else ImagePullBackOff
   (`feedback_overlay_bump_after_merge`). GHCR tags are 7 chars, git prints 8. Prod promotes are manual.
7. **Prod-verify** — a frontend roll proves nothing about the api; each chart is its own ArgoCD app.
   `app.agripulse.cloud/api/*` returns the SPA, so **a 200 there is a lie**. 401-vs-404 probing is worthless
   (auth middleware rejects pre-routing) — **introspect `app.routes` inside the pod**.
   - SSH: `ssh root@167.233.98.216` (key `~/.ssh/id_ed25519`) — **verified working this session**.
   - DB: `kubectl -n agripulse exec -c postgres agripulse-pg-1 -- psql -U postgres -d agripulse -c "…"`
   - Tenant schema = `tenant_` + tenant_id without dashes. agrosina-suez tenant
     `019eafdc-242c-7320-948e-13490efc67dd`. Bashier Elkhier farm bbox
     `32.633694,30.072694,32.641861,30.082472`.
   - Token via **direct-grant** (`project_farm_mgmt_ux_and_prod_test`); Netskope → `--ssl-no-revoke` on curl.
8. Record progress in memory (`project_thermal_indices_build`) after each PR merges: SHA + deploy state.

---

## Open questions to close during the build

- **Per-pixel cloud from `qa_pixel` was never measured** over the farm. The 67% usable-cadence figure is a
  floor derived from scene-level cloud. Measure it in step 4 and correct the study doc.
- **Planetary Computer's terms of use for sustained production polling were not read.** Read them before this
  becomes a scheduled Celery beat task, not after. Volume is trivial; the terms still govern.
- **Does the farm-level subscription gate apply?** Imagery is gated on `fetch_farm_aoi`, **not** on a farm sub
  existing (`project_farm_level_subscriptions`). Confirm how a second product enters that gate before wiring
  scheduling, or thermal silently never fetches.

---

## Do not

- Do not use `landsat-ot-l1` from CDSE (L1) — see L1.
- Do not use Sentinel-3 SLSTR for this — see L2.
- Do not build against `landsatlook.usgs.gov/data/` — see L3.
- Do not change `ImageryProvider` in `protocol.py` — the new adapter fits it as-is.
- Do not pair Sentinel-2 NDVI with Landsat LST inside SMI — see L7.
- Do not present block-level thermal at the same visual confidence as 10 m optical indices — see L6.
