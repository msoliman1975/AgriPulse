# Investor app v2: build plan

Status: **approved scope**. Owner approved D1–D6 as proposed on 2026-11-16. This file is the
source of truth for the build loop: each PR updates the **Status** table at
the end.

Design: `docs/proposals/investor-app-v2-mockup.html` (open it in a browser;
EN/AR toggle top right). Items marked "NEW" in the mockup are not built yet.

## 1. What we are building

The investor Android app (`mobile-investor/`) today has a holdings list and a
holding screen with two tabs, Map and Details. v2 adds:

1. A redesigned holdings list: portfolio stats, a **crop image** on each
   holding card, and a stage pill coloured by growth stage.
2. Holding screen with four tabs:
   - **Map**: pinch / scroll zoom and drag pan (app-only work).
   - **Details**: on-site photo, stage ribbon, more holding facts.
   - **Activities** (new): the season's field activities for the holding's
     block, with status and field photos.
   - **Harvest** (new): picks with weight, price and revenue; totals; a chart.
3. A **crop image** on the crop catalog, used as the crop's icon in the
   investor app and reused on web (block cards, plan board, crop catalog).

What already exists and is reused unchanged: `GET /api/v1/investor/me`,
`/investor/holdings`, `/investor/holdings/{id}`,
`/investor/holdings/{id}/latest-photo` (satellite), `/investor/app-version`,
and the response allowlists pinned by `tests/unit/modules/investors`.

## 2. Decisions (owner answers)

Each decision lists the answer the owner approved. A decision added later
starts as **open**; a PR it blocks does not start, and the loop stops and asks.

| ID | Decision | Answer | State | Blocks |
|---|---|---|---|---|
| D1 | How a block's harvest is split across the holdings in it | By tree count when both the holding and block have one, otherwise by area | approved 2026-11-16 | 6, 9 |
| D2 | Do investors see revenue, or weight only | Gross revenue (weight x price), no costs | approved 2026-11-16 | 6, 9 |
| D3 | Do investors see `acquired_by` and `contract_ref` | `acquired_by` yes, `contract_ref` yes (it is their own contract) | approved 2026-11-16 | 2b |
| D4 | Activity fields visible to investors; skipped activities | Title and type, date, status, photos. No product, dosage or notes. Skipped hidden | approved 2026-11-16 | 4 |
| D5 | Photos to investors: automatic or staff-approved | Automatic, with a per-photo "hide from investors" switch for staff | approved 2026-11-16 | 3, 4 |
| D6 | The third portfolio stat tile | "Activities completed this season" across current holdings | approved 2026-11-16 | 7 |

Settled by design (not owner decisions):

- Currency comes from the tenant's `default_currency`, never hard-coded.
- Tree age is computed in the app from `planting_date`.
- The crop image lives on the crop, with an optional per-variety override.
- Every new investor endpoint: ownership checked first, a holding the
  investor does not own answers 404, the response is an explicit allowlist,
  and a unit test pins its field set.

## 3. Design

### 3.1 Crop image (PR 1)

- Public migration: `crops.image_s3_key text null`,
  `crop_varieties.image_s3_key text null` (override).
- Platform-admin upload in the crop catalog editor: presigned PUT, the same
  flow as `crop_documents` (`backend/app/modules/crop_documents/`).
  PNG / JPEG / WebP, max 5 MB.
- A worker task makes square WebP renditions at 64, 128 and 256 px next to
  the original (`.../crop-images/{crop_id}/{size}.webp`).
- Not sensitive: served from a cacheable URL (long cache, key changes on
  re-upload). APIs return `crop_image_url` (256 px) and `crop_icon_url`
  (64 px), resolved variety override first, then crop.
- Added to: investor holding responses, block / block-crop reads, plan board
  rows, crop catalog list.
- Web: shared `CropAvatar` component with fallback (coloured circle with the
  crop's first letter); used in crop catalog, block cards and plan board.

### 3.2 Investor API additions (PR 2, 2b)

`InvestorAppMeResponse` gains `status`, `investor_type`, `email`, `phone`.

`InvestorAppHoldingResponse` gains:

- `stage_code`
- `stages`: the variety's ordered stage list,
  `[{code, name_en, name_ar, expected_start, expected_end}]` for the current
  season, from the same resolution `stage_dates.py` uses. The app derives
  ribbon widths from the dates; null dates fall back to equal widths.
- `expected_harvest_on`: expected start of the harvest / maturation stage.
- `crop_image_url`, `crop_icon_url` (from PR 1).
- PR 2b, only if D3 is approved: `acquired_by`, `contract_ref`.

### 3.3 Activity photos (PR 3)

- Tenant migration: `plan_activity_photos (id, activity_id, s3_key,
  taken_at, created_by, created_at, hidden_from_investors bool default false,
  deleted_at)`.
- `POST /plan-activities/{id}/photos/init` (presigned PUT, mirrors
  `field_flags.init_photo_upload`), attach keys on complete
  (`complete` accepts `attachment_s3_keys`), list photos on activity reads.
- Scout (`mobile/`): optional photo step in `WorkDetailScreen` before
  Complete.
- Web: photos on the activity drawer; staff toggle "hide from investors".

### 3.4 Investor activities and site photo (PR 4)

- `GET /investor/holdings/{id}/activities`: plan activities on the holding's
  block, in the current season and inside the ownership period. Fields per D4:
  `id, activity_type, title, title_ar, scheduled_date, status, completed_at,
  photos: [{thumb_url, url, taken_at}]` (presigned GET, short TTL; hidden
  photos excluded). Status `scheduled` shows as upcoming.
- `GET /investor/holdings/{id}/site-photo`: newest of (block attachments of
  kind `photo`, visible activity photos) on the block; `{url, taken_at}` or
  null.

### 3.5 Harvest records (PR 5)

- Tenant migration: `harvest_lots (id, farm_id, block_id, block_crop_id,
  season_label, pick_no, label, label_ar, harvested_on, weight_kg numeric,
  price_per_kg numeric null, currency, notes_internal, created_by,
  updated_by, timestamps, deleted_at)`.
- Staff API: CRUD under the block, capability `harvest.read` / `harvest.manage`
  (RBAC yaml + frontend `capabilities.ts`); audit events.
- Web: Harvest section on the block page: list, add, edit.

### 3.6 Investor harvest (PR 6)

- `GET /investor/holdings/{id}/harvest?season=`: lots on the block inside the
  ownership period, each scaled to the holding per D1; totals (weight,
  revenue per D2, average price) computed on the server. Never returns the
  block's total or the holding's share.
- Previous holdings: up to the ownership end date. Future holdings: empty.

### 3.7 App screens (PR 7–9)

`mobile-investor/`: list redesign with crop avatars and stats (PR 7), map
zoom and pan, Details tab with site photo and ribbon (PR 7), Activities tab
(PR 8), Harvest tab (PR 9). New calls cached in Preferences like `/me` and
`/holdings`, with the "data from ..." offline note. EN and AR strings in
`src/i18n/locales/`.

## 4. Delivery: PRs

"Deploy" means the promotion procedure in `CLAUDE.md`.

| # | PR | Main contents | Tests | Deploy |
|---|---|---|---|---|
| 0 | Build plan | This file and the mockup | n/a | n/a |
| 1 | Crop image | 3.1 end to end | unit: URL resolution (variety override); integration: upload init / finalize, renditions task; vitest: `CropAvatar` fallback | api + workers + frontend |
| 2 | Investor API additions | 3.2 without D3 fields | unit: pinned allowlists updated; stage list and expected harvest dates | api |
| 2b | Ownership facts | `acquired_by`, `contract_ref` (D3) | unit: allowlist | api |
| 3 | Activity photos | 3.3 | integration: init, attach on complete, hide toggle; Scout + web vitest | api + frontend |
| 4 | Investor activities + site photo | 3.4 | unit: allowlist; integration: ownership window, other investor's holding 404, hidden photos excluded | api |
| 5 | Harvest records | 3.5 | integration: CRUD, caps enforced, audit; vitest | api + frontend |
| 6 | Investor harvest | 3.6 | unit: split per D1; integration: ownership window, no block totals in response | api |
| 7 | App: list, map, details | 3.7 | vitest (`mobile-investor`) incl. RTL | APK (not deployed by ArgoCD) |
| 8 | App: Activities tab | 3.7 | vitest | APK |
| 9 | App: Harvest tab | 3.7 | vitest | APK |
| 10 | Release | Version bump in its three places, `INVESTOR_APP_MIN_VERSION` / `LATEST_VERSION` on the api, APK build notes in `mobile-investor/README.md` | n/a | api |

Order: PR 1 first (no open decisions). Then PR 2, 3, 5 can go in any order;
4 after 3; 6 after 5; app PRs after their backend PRs are deployed.

## 5. How the build loop works

The loop is self-paced. Each iteration:

1. Read this file's **Status** table. Pick the earliest PR that is not
   `deployed` and whose blocking decisions in section 2 are answered.
   If every remaining PR is blocked, stop and list the open decisions.
2. Do the next action for it: build → test locally (backend unit;
   integration with Docker; frontend / mobile lint, typecheck, vitest, build)
   → push → open PR → subscribe to PR activity → fix CI → merge when required
   CI is green (read `backend-integration`'s pytest summary, not its
   conclusion) → wait for `ci` on the merge commit → promotion PR in
   `infra/argocd/overlays/hetzner/values.yaml` with notes and rollback tags →
   merge → verify (`verify-prod-frontend.sh` when the frontend tag changed,
   `check-prod-beta-designer.cjs` in token mode, plus an API smoke of new
   endpoints with the `claude-automation` client).
3. Update the Status table in the PR that finishes each step.
4. While waiting on CI the PR subscription wakes the session; the loop
   fallback wake is 20–30 minutes.

### Stop and ask the owner when

- the next PR is blocked by an open decision in section 2;
- an action is on the `CLAUDE.md` "may not" list (force-push or rewrite
  `main`, disable or skip tests, switch the decision engine, publish decision
  trees, hard-delete data);
- a migration would do more than the additive changes above;
- prod verification fails and one fix-forward does not clear it (roll back
  to the noted tag first, then ask);
- the session needs network access to `app.` / `api.agripulse.cloud`.

## 6. Status

| # | PR | State | Link | Deployed |
|---|---|---|---|---|
| 0 | Build plan | merged | [#882](https://github.com/msoliman1975/AgriPulse/pull/882) | n/a (docs) |
| 1 | Crop image | deployed | [#883](https://github.com/msoliman1975/AgriPulse/pull/883), merged `8bfe412` | api, workers, frontend `8bfe412` (rollback `09e94e2`); public 0114; ADR 0004 |
| 2 | Investor API additions | deployed | [#885](https://github.com/msoliman1975/AgriPulse/pull/885), merged `73f147f` | api `73f147f` (rollback `8bfe412`); workers and frontend unchanged at `8bfe412` |
| 2b | Ownership facts | deployed | [#887](https://github.com/msoliman1975/AgriPulse/pull/887), merged `69a3f30` | api `69a3f30` (rollback `73f147f`) |
| 3 | Activity photos | deployed | [#889](https://github.com/msoliman1975/AgriPulse/pull/889), merged `a19ce55` | api and frontend `a19ce55` (rollback api `69a3f30`, frontend `8bfe412`); tenant 0110; Scout photo step ships with the next Scout APK; route is `/activities/{id}/photos/init` |
| 4 | Investor activities + site photo | deployed | [#891](https://github.com/msoliman1975/AgriPulse/pull/891), merged `d61349b` | api `d61349b` (rollback `a19ce55`); season = active plan's calendar year; `thumb_url` = full image until activity photos get renditions |
| 5 | Harvest records | deployed | [#893](https://github.com/msoliman1975/AgriPulse/pull/893), merged `2f3fb84` | api and frontend `2f3fb84` (rollback api `d61349b`, frontend `a19ce55`); tenant 0111; harvest.manage: TenantOwner, TenantAdmin, FarmManager; harvest.read adds PlatformSupport, InvestmentManager, Agronomist, Viewer (owner to confirm) |
| 6 | Investor harvest | deployed | [#895](https://github.com/msoliman1975/AgriPulse/pull/895), merged `d8f0143` | api `d8f0143` (rollback `2f3fb84`); D1 uses the block's `plant_count` from its planting layout |
| 7 | App: list, map, details | deployed | [#897](https://github.com/msoliman1975/AgriPulse/pull/897), merged `9bfc0e0` | App PR: tests, typecheck and build run locally (CI had no `mobile-investor` job until PR 10; the `mobile` job is Scout). Map already zoomed and panned (MapLibre): rotation and tilt now off, "Back to my holding" button. D6 counts each block activity once across holdings |
| 8 | App: Activities tab | deployed | [#899](https://github.com/msoliman1975/AgriPulse/pull/899), merged `f4500ee` | App PR, verified locally as PR 7. Shares the activities cache with the list's D6 stat. Android back with a photo open now closes the photo first (follow-up fix) |
| 9 | App: Harvest tab | deployed | [#900](https://github.com/msoliman1975/AgriPulse/pull/900), merged `cf22fc5` | App PR, verified locally as PR 7. Money in the response currency (code in English, symbol in Arabic) |
| 10 | Release | deployed | [#901](https://github.com/msoliman1975/AgriPulse/pull/901), merged `ab9f5ba` | api `ab9f5ba` (rollback `d8f0143`): `INVESTOR_APP_LATEST_VERSION` 0.2.0, minimum stays 0.1.0 until `INVESTOR_APP_DOWNLOAD_URL` is set. App 0.2.0 (versionCode 2) APK built by the new CI `mobile-investor` job (artifact `investor-debug-apk`) |
