# AgriPulse — Implementation plan (this codebase)

**Status:** locked 2026-05-06. **Amended 2026-05-07** — see "Amendments" below. Companion to `UX_SPEC.md` (UX truth) and `BUILD_PLAN.md` (handoff team's recommended approach). Where the three disagree, this document wins for **MissionAgre / AgriPulse** specifically — it reconciles the spec with our existing backend, frontend stack, and the FarmDM/Slice-4 decisions already locked in memory.

The receiving session should read **this file first**, then `UX_SPEC.md` for visual/interaction truth, then dip into `BUILD_PLAN.md` only for stack rationale we explicitly endorse.

---

## 0. Amendments (2026-05-07)

The original plan was written 2026-05-06, before the FarmDM rollout finished. Three corrections apply:

1. **Stub regions removed.** Locked decision #4 deferred FarmDM PR-3 (`growth_stage_logs`) and PR-4 (`block_index_baselines` + `baseline_deviation`). Both shipped on 2026-05-07. The five `<DataPendingChip>` surfaces in the original §6 are no longer needed; that section now documents which fields back each surface for real.
2. **`alerts.prescription_activity_id` is a new backend PR, not a verification.** The original plan flagged this as "verify exposed". Reality: the `Alert` model has no such column. Added to §5 as a mandatory backend change so the alerts feed's "Resolve" button can deep-link to a specific activity bar instead of just a lane.
3. **Irrigation surface decision.** PR-7 of FarmDM shipped a full irrigation engine (daily recommendations per block via Beat sweep). UX_SPEC.md does not address it. Decision: project `irrigation_schedules` rows into the Plan view as a sixth activity type (`irrigation`), reusing the existing bar/lane/conflict machinery. The Insights "Irrigation due" KPI reads from the same table. Captured in §5.3 and PR-5 below.

---

## 1. Decisions locked for this build

These four answers from the product owner gate everything else:

| # | Decision | Implication |
|---|---|---|
| 1 | **Replace primary nav with farm-scoped shell.** Insights/Plan/Land units/Alerts/Reports/Configuration is the new IA. Existing `TenantTree` becomes an org-admin drawer. | Largest UX shift. Existing `/farms` and `/farms/:id/blocks/:id` routes survive but are reached through "Land units" inside the active-farm context, not as the primary entry. |
| 2 | **No MockAdapter.** Real APIs through `src/api/*.ts`, wrapped in TanStack Query hooks. | Drops the swappable-adapter abstraction in `BUILD_PLAN.md` §3. The API client modules already exist for plans, alerts, indices, weather, imagery; we extend them, we don't replace them. |
| 3 | **Add `duration_days INT` + `start_time TIME` to `plan_activities`.** One-shot migration, this slice. | Plan view's Gantt bars are data-driven on width AND time-of-day labels are real, not cosmetic. Touches plans module + schemas + service + tests. |
| 4 | ~~Defer FarmDM PR-3, PR-4, and the alerts-prescription verification.~~ **Superseded 2026-05-07.** PR-3 and PR-4 shipped; `prescription_activity_id` is now an additive backend column (§5.2). No surfaces stub — see §6. | All Insights and Plan surfaces use real data. The original three deferred regions are wired to `block_index_baselines`, `growth_stage_logs`, and the new `alerts.prescription_activity_id` column. |
| 5 | **Project irrigation_schedules into Plan view as activity type `irrigation`.** Same bar/lane/conflict treatment as the other five types; no new swimlane. Insights "Irrigation due" KPI reads from `irrigation_schedules.status='pending'`. | Reuses existing `<ActivityBar>`, `<ConflictOverlay>`, `<ActivityDetail>` machinery. Conflict rule `CFL-SPRAY-WASH` (UX_SPEC §6.5) already pairs `spray` with `irrigation/fert pulse` — works out of the box once irrigation rows project as activities. |

---

## 2. Stack — what we adopt, what we already have, what we reject

| Concern | Decision | Source |
|---|---|---|
| Framework | React 18 + TypeScript | already in repo |
| Build | Vite | already in repo |
| Routing | React Router v6 | already in repo |
| **Server state** | **Adopt TanStack Query.** Wrap the existing `src/api/*.ts` clients in `useXxx` hooks under `src/queries/`. | `BUILD_PLAN.md` §1 endorses this; we lacked it. |
| **Cross-tree UI state** | **Adopt Zustand**, scope is small: `selectedLane`, `selectedActivity`, plan filter chips, drafts toggle, modal open + draft. Everything else is component state or URL. | `BUILD_PLAN.md` §1 |
| **URL is selection truth** | `?lane=` and `?activity=` on `/plan`, plus the date-range segment on `/insights`, sync via a `useUrlSelection` hook. Replace-not-push for rapid clicks. | `UX_SPEC.md` §8 |
| Styling | **Tailwind v3 + tailwindcss-rtl** (already wired). Map all `UX_SPEC.md` §9 design tokens into `tailwind.config.ts` `theme.extend.colors / spacing / borderRadius / boxShadow`. No second styling system, no vanilla-CSS-modules. | conflict with `BUILD_PLAN.md` §1; we win |
| Charts | **Recharts** for the 90-day trend chart (already used in `IndexTrendChart`). **Hand-rolled SVG** for KPI sparklines and the Gantt timeline. | `BUILD_PLAN.md` §1 allows; we extend |
| Dates | `date-fns` (already in repo). Use `date-fns-tz` if/when the timezone open question forces it. | already in repo |
| **i18n** | **Stay on `react-i18next`** with the existing `en/`/`ar/` namespaces. Reject the `react-intl` recommendation outright. | conflict with `BUILD_PLAN.md` §1; we win |
| Auth | Keycloak via `react-oidc-context` + `ProtectedRoute` + `AuthSync` (already wired). | already in repo |
| Testing | Vitest + RTL + Playwright. Vitest already in repo; Playwright **adopt** in this slice. | `BUILD_PLAN.md` §6 |
| Data adapter | **Reject** the `DataAdapter` interface, `MockAdapter`, `HttpAdapter`, env-var swap, and `data/fixtures/` tree. | conflict with `BUILD_PLAN.md` §3; we win |
| Component library | None — bespoke. Don't introduce MUI/AntD/Chakra. | `BUILD_PLAN.md` §1 |
| Map | **MapLibre static config (no deck.gl)** for the mini farm map on Insights. The full deck.gl stack stays available for the existing block detail. | tradeoff — keeps dashboard light |

**Don't add** in this slice: Storybook, Redux/MobX, CSS-in-JS, react-intl, react-virtual (until lanes > 30 measured), a DataAdapter abstraction.

---

## 3. Information architecture — reconciled

`UX_SPEC.md` §3's IA is correct *inside an active farm context*. We layer that under the existing tenant/auth shell.

```
AgriPulse (org-scoped via tenant_schema in JWT)
│
├─ [top bar]
│   • Brand → /insights
│   • Breadcrumbs:  Org name › Farm name (button → farm switcher popover)
│   • View-specific toolbar slot
│   • [bell] [avatar] [tenant tree drawer toggle ⚙ — org admins only]
│
├─ [side nav, farm-scoped]
│   ├─ Workspace
│   │   ├─ Insights        /insights                      ← default landing
│   │   ├─ Land units      /farms/:farmId                 ← reuses existing FarmDetailPage
│   │   ├─ Alerts          /alerts                        ← new (calls existing /api/v1/alerts)
│   │   ├─ Plan            /plan                          ← new
│   │   └─ Reports         /reports                       ← stub (link only)
│   └─ Configuration
│       ├─ Rules & thresholds   /config/rules
│       ├─ Imagery & weather    /config/imagery
│       └─ Users & roles        /config/users
│
└─ [tenant tree drawer] (org-admin only)
    └─ org → list of farms → switch active farm
```

**Key reconciliations:**

- The active farm lives in URL via `farm_id` path params for all routes that need it (`/insights/:farmId?` form below) OR in Zustand session state with persisted `localStorage` (deciding: **path-param**, since it's the source of truth and works across tabs). Final routes:
  ```
  /                                 → /insights/{currentFarmId}
  /insights/:farmId
  /plan/:farmId
  /alerts/:farmId
  /reports/:farmId
  /config/rules/:farmId
  /config/imagery/:farmId
  /config/users/:farmId
  /farms                            → existing FarmListPage (admin overview)
  /farms/:farmId                    → existing FarmDetailPage (= Land units view)
  /farms/:farmId/blocks/...         → existing block CRUD
  /tenants/:tenantId                → existing TenantDetailPage
  ```
- The `?lane=` and `?activity=` query params on `/plan/:farmId` follow `UX_SPEC.md` §8 verbatim.
- The "farm switcher" popover on the breadcrumb lists farms the user has scopes on (from the existing `/api/v1/me` capabilities). Switching navigates the current route's `:farmId` segment.
- Side-nav items resolve their `:farmId` from the current route. If the user is on `/farms` (no active farm), the side-nav shows Workspace items as disabled with a tooltip "Pick a farm to continue."

---

## 4. Naming translation table

The spec uses different vocabulary; we keep our names internally and translate at the view layer per the FarmDM locked decision.

| Spec term | Our term | Notes |
|---|---|---|
| ORGANIZATION | tenant | UI copy can say "Organization" |
| LAND_UNIT | block | UI copy says "Land unit"; `unit_type` already on `blocks` |
| USER_FARM_ROLE | farm_scopes | internal name unchanged |
| `area_feddans` | `area_m2` (DB) → feddan or hectare per `user_preferences.unit_system` | `AreaDisplay` component already does this |
| `prescription_activity_id` (Alert) | TBD on `alerts` model | see §6 gap list |
| `current_growth_stage` | `block_crops.growth_stage` | latest active assignment |

The receiving session must **never** ask the user to reconcile these — translate silently.

---

## 5. Backend touches required for this slice

Most of what the UX needs is already shipped. Two mandatory backend changes remain: the `plan_activities` schema bump (original) and the `alerts.prescription_activity_id` column (new — added by amendment, supersedes the "verify" item).

### 5.1 plan_activities migration (mandatory)

```sql
ALTER TABLE plan_activities
  ADD COLUMN duration_days INT NOT NULL DEFAULT 1
    CHECK (duration_days >= 1 AND duration_days <= 60),
  ADD COLUMN start_time TIME NULL;
```

- `duration_days` defaults to 1 for backfill; the FE uses this to size bars.
- `start_time` is nullable; null means "all-day". UI label falls back to "—" or hides the time.

Files to change:
- `backend/app/modules/plans/models.py` — add the columns to `PlanActivity`.
- `backend/app/modules/plans/schemas.py` — add to `ActivityCreateRequest`, `ActivityUpdateRequest`, `ActivityResponse`. Validation: `duration_days` 1..60; `start_time` HH:MM.
- `backend/app/modules/plans/repository.py`, `service.py` — pass through.
- New Alembic migration.
- Tests: `backend/tests/integration/.../plans/...` — extend create/list/calendar/update test cases.

### 5.2 alerts.prescription_activity_id (mandatory — added 2026-05-07)

```sql
ALTER TABLE alerts
  ADD COLUMN prescription_activity_id UUID NULL
    REFERENCES plan_activities(id) ON DELETE SET NULL;
```

- Nullable: not every alert has a prescribed activity (info alerts don't, system alerts don't).
- ON DELETE SET NULL: deleting the activity drops the link; the alert's prescription text remains intact.
- Set by the alerts engine when a rule's `actions` block contains a `create_activity` directive (or by a future operator-driven prescription flow). For MVP, the engine writes `NULL`; the column exists so the FE deep-link contract is stable and the value can be backfilled by a follow-up sweep.

Files to change:
- `backend/app/modules/alerts/models.py` — add the column to `Alert`.
- `backend/app/modules/alerts/schemas.py` — add to `AlertResponse`.
- `backend/app/modules/alerts/repository.py` — `SELECT` and `UPDATE` paths pass it through.
- `backend/app/modules/alerts/engine.py` — recognise an optional `create_activity` action in `default_rules.actions`; emit a `prescription_activity_id` on the new alert if present (for now, leave the activity itself uncreated — out-of-scope wiring).
- New Alembic tenant migration (`0010_alerts_prescription_activity_id.py` or next free number).
- Tests: extend `tests/integration/.../alerts/...` to confirm the column round-trips and that `NULL` is the default.

### 5.3 Irrigation projection into the Plan view (frontend)

No backend change. The FE reads `irrigation_schedules` (existing `GET /api/v1/irrigation/schedules?farm_id=&from=&to=`) and projects each pending row as a synthetic `PlanActivity` with `activity_type='irrigation'`, `scheduled_date=irrigation_schedules.scheduled_for`, `duration_days=1`, `product_name=null`, `notes=` recommendation summary, `status` mapped from irrigation status (`pending → scheduled`, `applied → completed`, `skipped → skipped`).

A `useIrrigationActivities(farmId, range)` hook in `src/queries/irrigation.ts` returns these, and `<Lane>` merges them with real `PlanActivity` rows before passing to `<ActivityBar>` and `detectConflicts()`. Apply/skip actions on an irrigation bar route to `PATCH /api/v1/irrigation/schedules/{id}` instead of the activity endpoint — the `ActivityBar`'s click handler dispatches based on a synthetic flag.

### 5.4 Endpoints already shipped that we just consume

| UX surface | Endpoint(s) we call |
|---|---|
| Insights — Live alerts feed | `GET /api/v1/alerts?status=open&limit=20` (with optional `severity`) |
| Insights — Land unit health table | `GET /api/v1/farms/{farmId}/blocks` (existing) + per-block latest aggregate (existing) |
| Insights — Trend chart | `GET /api/v1/blocks/{blockId}/index-timeseries` (existing) — we'll need a farm-rollup variant; see §6 |
| Insights — This week's activities | `GET /api/v1/farms/{farmId}/plans/calendar?from=&to=` |
| Insights — Mini farm map | `GET /api/v1/farms/{farmId}` + blocks list + their boundaries |
| Plan — lanes | farm's blocks list |
| Plan — bars | `GET /api/v1/farms/{farmId}/plans` then `GET /api/v1/plans/{planId}/activities` (or the calendar endpoint with a season window) |
| Plan — new activity | `POST /api/v1/plans/{planId}/activities` |
| Plan — reschedule/skip/complete | `PATCH /api/v1/activities/{activityId}` (existing) |
| Plan — irrigation bars | `GET /api/v1/irrigation/schedules?farm_id=&from=&to=` then `PATCH /api/v1/irrigation/schedules/{id}` for apply/skip (existing — FarmDM PR-7) |
| Insights — Irrigation due KPI | `GET /api/v1/irrigation/schedules?farm_id=&status=pending&from=today&to=today+7d` |
| Alerts page | `GET /api/v1/alerts` + `PATCH /api/v1/alerts/{id}` |
| Configuration → Rules | `GET /api/v1/rules/defaults`, `GET /api/v1/rules/overrides`, `PUT /api/v1/rules/overrides/{ruleCode}` |
| Configuration → Imagery & weather | existing per-block subscription endpoints (Slice-2 / Slice-4 PR-A) |
| Configuration → Users & roles | existing `farm_scopes` admin endpoints |

### 5.5 Endpoints we may add as small extensions (not blockers)

- A farm-rollup `GET /api/v1/farms/{farmId}/index-timeseries` that returns area-weighted means across blocks. If absent, the FE computes the rollup client-side from per-block calls — slower but works.
- A `GET /api/v1/farms/{farmId}/insights-summary` that pre-computes the four KPI numbers in one round-trip. Without it the dashboard does ~4 calls; acceptable.

---

## 6. Surface ↔ data field map (no stubs needed as of 2026-05-07)

The original plan listed five `<DataPendingChip>` stubs gated on FarmDM PR-3/PR-4 and an `alerts.prescription_activity_id` verification. With PR-3 and PR-4 shipped 2026-05-07 and §5.2 adding `prescription_activity_id`, every surface is data-backed. This section now serves as the surface→field mapping reference.

| Surface | Backing field |
|---|---|
| KPI card "Avg NDVI" delta vs baseline | `block_index_aggregates.baseline_deviation` (PR-4 ✅) — area-weighted mean across blocks |
| Trend chart 5-year baseline ribbon | `block_index_baselines` (PR-4 ✅) — DOY-bucketed mean ± SD, cyclic distance |
| Land unit health table — "NDVI vs baseline" pill + default sort | `block_index_aggregates.baseline_deviation` (PR-4 ✅) — sort `ASC` (worst first) |
| Stage band — "current stage" inner outline | `growth_stage_logs` (PR-3 ✅) — latest non-skipped log row drives the highlight; default segment widths from `crop_varieties.phenology_stages_override` ?? `default_phenology_model` |
| Alerts — "Resolve" deep link to a prescription activity | `alerts.prescription_activity_id` (PR-1b §5.2) — when present, link to `/plan/:farmId?activity={prescription_activity_id}&lane={block_id}`; when null, fall back to lane-only |

**`<DataPendingChip>` is still introduced as a primitive in PR-2** — keeps the door open for future deferrals without rework, and the `alerts.prescription_activity_id` column will mostly be `NULL` until the engine starts emitting it.

---

## 7. Gaps recap (no-action / FE-only / explicit-deferral)

| Gap | Where | Plan |
|---|---|---|
| `duration_days` / `start_time` on `plan_activities` | backend | **fix this slice** (§5.1) |
| `prescription_activity_id` on `alerts` | backend | **fix this slice** (§5.2 — added 2026-05-07) |
| `block_index_baselines` table + `baseline_deviation` column | backend | ✅ **shipped 2026-05-07** (FarmDM PR-4) |
| `growth_stage_logs` table | backend | ✅ **shipped 2026-05-07** (FarmDM PR-3) |
| `irrigation_schedules` projection into Plan view | frontend | **this slice** (§5.3) — synthetic activities of type `irrigation` |
| Frontend API clients for alerts / plans / irrigation | frontend | **this slice** — new files in `src/api/` (PR-2) |
| Conflict rules `CFL-SPRAY-WASH` / `CFL-PHI` / `CFL-PRUNE-FLOWER` | frontend | **client-side this slice** in `src/rules/conflicts.ts`. Promote to server later. |
| `useChecklist` per-activity state | frontend | localStorage only; persist on backend post-MVP (no PLAN_ACTIVITY column added now). |
| Farm-rollup index timeseries | backend, optional | client-side rollup OK for MVP |
| Farm switcher (top-bar) | frontend | new component in shell (§8) |
| URL-driven selection sync | frontend | new `useUrlSelection` hook |
| Skeleton primitive, Stepper, Modal, Tooltip primitives | frontend | new in `src/components/` |
| `DataPendingChip` | frontend | new in `src/components/` (still useful — see §6 closing note) |
| TanStack Query provider + Zustand | frontend | new dependencies in `App.tsx` |

---

## 8. Project structure additions

We extend the existing tree; we do **not** create the `src/data/`, `src/data/mock/`, or `src/data/http/` folders from `BUILD_PLAN.md` §2.

```
frontend/src/
├─ App.tsx                              # ADD QueryClientProvider; new routes
├─ shell/
│  ├─ AppShell.tsx                      # MODIFY: replace TenantTree with SideNav (farm-scoped); keep tenant drawer for admins
│  ├─ Header.tsx                        # MODIFY: add breadcrumbs + farm switcher + view-specific toolbar slot + bell
│  ├─ SideNav.tsx                       # NEW (farm-scoped Workspace + Configuration groups)
│  ├─ FarmSwitcher.tsx                  # NEW (popover on breadcrumb)
│  ├─ TenantTree.tsx                    # KEEP, demote to org-admin drawer trigger
│  └─ icons.tsx                         # extend with the 10–12 stroke icons the new IA needs
│
├─ modules/
│  ├─ insights/                         # NEW
│  │   ├─ pages/InsightsPage.tsx
│  │   ├─ components/KPICards.tsx
│  │   ├─ components/TrendChartCard.tsx          # wraps existing IndexTrendChart
│  │   ├─ components/LandUnitHealthTable.tsx
│  │   ├─ components/AlertsFeedCard.tsx
│  │   ├─ components/MiniFarmMap.tsx
│  │   └─ components/UpcomingActivitiesCard.tsx
│  ├─ plan/                              # NEW
│  │   ├─ pages/PlanPage.tsx
│  │   ├─ components/PlanToolbar.tsx
│  │   ├─ components/StageLegend.tsx
│  │   ├─ components/LaneSidebar.tsx
│  │   ├─ components/Timeline.tsx
│  │   ├─ components/Lane.tsx
│  │   ├─ components/ActivityBar.tsx
│  │   ├─ components/ConflictOverlay.tsx
│  │   ├─ components/StageBand.tsx
│  │   ├─ components/ActivityDetail.tsx
│  │   └─ components/NewActivityModal/
│  │       ├─ index.tsx
│  │       ├─ Step1Type.tsx
│  │       ├─ Step2Lanes.tsx
│  │       ├─ Step3Schedule.tsx
│  │       ├─ Step4Details.tsx
│  │       └─ Stepper.tsx
│  ├─ alerts/                            # NEW (full /alerts list page)
│  │   └─ pages/AlertsPage.tsx
│  ├─ reports/                           # NEW (stub page)
│  ├─ config/                            # NEW (3 stub pages, wrap existing screens)
│  ├─ farms/                             # KEEP — reachable as /farms/:farmId (= Land units view)
│  ├─ imagery/                           # KEEP
│  ├─ indices/                           # KEEP
│  └─ weather/                           # KEEP
│
├─ queries/                              # NEW — TanStack Query hooks, 1:1 with src/api/*.ts
│  ├─ alerts.ts                          # useAlerts, useTransitionAlert
│  ├─ plans.ts                           # usePlans, useActivities, useCalendar, useCreateActivity, useUpdateActivity
│  ├─ blocks.ts                          # useBlocks, useBlock
│  ├─ indices.ts                         # useIndexTimeseries, useFarmIndexTimeseries
│  ├─ weather.ts                         # useWeatherDaily
│  ├─ imagery.ts                         # passthrough
│  └─ session.ts                         # useMe, useFarmsForUser
│
├─ state/                                # NEW (Zustand stores; small)
│  ├─ selection.ts                       # selectedLane, selectedActivity (URL-mirrored)
│  ├─ planFilters.ts                     # activity-type chips, drafts toggle
│  └─ checklist.ts                       # per-activity preflight checks (localStorage-backed)
│
├─ rules/                                # NEW (pure functions)
│  ├─ conflicts.ts                       # detectConflicts(activities, rules) → ConflictEdge[]
│  ├─ stages.ts                          # segment widths from CROP_VARIETY phenology + stage detection
│  └─ formatting.ts                      # extends existing formatters
│
├─ hooks/                                # NEW
│  ├─ useUrlSelection.ts
│  ├─ useActiveFarm.ts                   # resolves :farmId from URL or session, validates membership
│  └─ useConflictDetection.ts
│
├─ components/                           # NEW primitives
│  ├─ Skeleton.tsx
│  ├─ Tooltip.tsx
│  ├─ Modal.tsx                          # focus trap, role=dialog
│  ├─ DataPendingChip.tsx
│  ├─ KPICard.tsx
│  ├─ Sparkline.tsx
│  ├─ FilterChip.tsx
│  ├─ Pill.tsx
│  ├─ Badge.tsx
│  └─ SegmentedControl.tsx
│
├─ tokens/                               # NEW — token bridge to Tailwind
│  └─ tokens.css                         # CSS custom properties from UX_SPEC §9; tailwind.config.ts maps them
│
└─ i18n/                                 # KEEP — extend en/ar JSON with insights.* and plan.* namespaces
```

---

## 9. Phased delivery (this slice)

Six PRs, each independently reviewable and demoable. Estimates assume one full-time engineer plus async backend collaboration.

### PR-1 — Backend: plan_activities duration & start_time *(0.5 day)*
- Migration + model + schemas + repository + service.
- Tests updated.
- **Acceptance:** create/update/list/calendar all round-trip both fields. Existing rows backfill `duration_days=1`, `start_time=NULL`.

### PR-1b — Backend: alerts.prescription_activity_id *(0.5 day, added 2026-05-07)*
- Tenant migration adding the nullable UUID FK.
- `Alert` model + `AlertResponse` schema + repository read/write paths.
- `engine.py` recognises an optional `create_activity` directive in `default_rules.actions`; for MVP it records `prescription_activity_id=NULL` (the activity-creation wiring is a follow-up).
- **Acceptance:** column round-trips through create/list/PATCH; default value is `NULL`; FE deep-link contract works for both populated and null cases.

### PR-2 — Frontend foundation *(1 day)*
- Add `@tanstack/react-query` and `zustand` to `frontend/package.json`.
- TanStack Query provider mounted in `App.tsx` (inside `ProtectedRoute`).
- New `frontend/src/api/{alerts,plans,irrigation}.ts` clients — typed wrappers over the existing endpoints.
- Tokens bridged from UX_SPEC §9 into `tailwind.config.ts`.
- New `Skeleton`, `Tooltip`, `Modal`, `DataPendingChip`, `Pill`, `Badge`, `FilterChip`, `SegmentedControl`, `KPICard`, `Sparkline` primitives — minimal viable, story-style usage examples in adjacent `*.test.tsx`.
- New empty pages registered for every route in §3, each rendering a "Coming soon" placeholder.
- **Acceptance:** every URL in §3 renders without crashing; tabbing through new pages is keyboard-accessible; `pnpm test` green.

### PR-3 — Shell rework *(1.5 days)*
- New `<SideNav>` with the two groups. Active highlight from URL.
- `<Header>` rebuilt: brand + breadcrumbs + farm switcher + view-specific toolbar slot + bell + avatar + tenant-tree drawer toggle for admins.
- `<FarmSwitcher>` popover lists user-accessible farms (from `me` + `farms`).
- `<TenantTree>` demoted to a drawer behind a settings/admin gear; only org admins see the toggle.
- `useActiveFarm()` hook validates membership and throws to a route boundary on mismatch.
- **Acceptance:** existing flows (farm CRUD, block CRUD) all still work, now accessed via Land units. New Insights/Plan pages pick up the active farm correctly. Switching farms updates URL and view.

### PR-4 — Insights view *(3 days)*
- All cards in UX_SPEC §5, wired to real APIs through `src/queries/`.
- Stubs per §6 for baselines/deviation surfaces; `<DataPendingChip>` consistently used.
- Mini map: MapLibre static, no deck.gl, click → `/plan/:farmId?lane=:blockId`.
- Trend chart: extend existing `IndexTrendChart` with the segmented control (NDVI/NDWI/GCI/Compare) + today-line marker.
- Empty / loading / error states for every card per UX_SPEC §10.
- **Acceptance:** every deep link from Insights lands on the correct `/plan/:farmId?...` URL. All cards render from real fixtures (or stubs only where §6 allows). Lighthouse ≥ 90 perf, ≥ 95 a11y on /insights.

### PR-5 — Plan view (read-only) *(3 days)*
- `<PlanToolbar>` with filter chips (6 types — the original 5 plus `irrigation`), drafts toggle, stage legend, stat counters.
- `<LaneSidebar>` grouped by `farm_section` if present, else by centroid ordering.
- `<Timeline>` with month + week headers, today line, lanes from data.
- `<Lane>` rendering bars (`duration_days` + `start_time` driven), stage band from `growth_stage_logs` (PR-3 ✅) over variety phenology defaults, conflict overlay from client-side `detectConflicts()`.
- **Irrigation projection** (§5.3): `irrigation_schedules` rows render as bars with `activity_type='irrigation'` alongside real `plan_activities`. Apply/skip routes to the irrigation endpoint, not the activity endpoint, via a `source: 'irrigation' | 'plan'` discriminator on the merged list.
- Conflict pin renders for the `CFL-SPRAY-WASH` rule between a real spray and a projected irrigation bar (the deterministic-fixture target for E2E).
- `<ActivityDetail>` panel with all sections, checklist toggles persisted in localStorage; for irrigation bars, the panel shows the recommendation breakdown (Kc, ET₀, recent precip, recommended_mm) instead of a product/dosage block.
- URL-driven selection via `useUrlSelection`.
- **Acceptance:** `?lane=` and `?activity=` reload-stable; activity IDs from both sources resolve. Filter chips update the bar set in real time. Spray + irrigation conflict pin renders on the seeded fixture. Esc clears selection.

### PR-6 — New activity flow + Alerts page + polish *(3 days)*
- `<NewActivityModal>` 4 steps with stepper, validation, live conflict preview reusing `detectConflicts()`, optimistic insert, focus trap, Esc/Enter behaviors.
- Full `/alerts/:farmId` page: list, filters, severity bars, transitions (acknowledge/resolve/snooze) wired to `PATCH /alerts/{id}`.
- Configuration stubs that wrap existing screens (rules, imagery, users) — clean redirect rather than a new screen.
- i18n: extract every visible string in new files into `en/insights.json`, `en/plan.json`, `en/alerts.json` (Arabic shells with English fallback in this slice).
- a11y audit: axe-core in Playwright; fix violations.
- Performance: lazy-load `NewActivityModal`; memoize bar position calculations.
- **Acceptance:** Playwright E2E covers (a) Insights → alert "Resolve" → Plan with lane selected; (b) full new-activity create flow with conflict preview; (c) reload preserves `?lane=&activity=`. Bundle < 300 KB gzipped excluding the lazy modal chunk. Zero axe violations on Insights/Plan/Alerts.

**Total: ~12.5 working days plus the two half-day backend PRs (PR-1 and PR-1b).** Add 30% buffer for review cycles.

---

## 10. Testing strategy

| Level | Tool | Targets |
|---|---|---|
| Unit | Vitest | `rules/conflicts.ts` (every rule × hit / miss / boundary), `rules/stages.ts` segment-width math, `useUrlSelection` round-trip, `useActiveFarm` validation. |
| Component | Vitest + RTL | Each component in `components/` and the Insights/Plan card components rendered with fixture data. Selection, filter toggles, modal step transitions, checklist persistence. |
| Integration (backend) | existing pytest harness | `plan_activities` with `duration_days` + `start_time` round-trips; backfill default for existing rows. |
| E2E | Playwright | The three flows in §9 PR-6 acceptance. |

**No magic strings in tests** — fixtures live in `frontend/src/test/fixtures/` and are imported by both dev mode helpers (when needed) and tests.

---

## 11. RBAC mapping

Every new view consults the existing `useCapability` hook against the existing capability strings. No new capabilities introduced.

| Surface | Capability |
|---|---|
| Insights view | `block.read` (any block in farm) |
| Plan view (read) | `plan.read` |
| Plan view (create activity) | `plan.manage` |
| Plan view (mark complete / skip) | `plan_activity.complete` |
| Alerts view (read) | `alert.read` |
| Alert acknowledge / resolve / snooze | `alert.acknowledge` / `alert.resolve` / `alert.snooze` |
| Rule overrides (Configuration) | `alert_rule.read` / `alert_rule.manage` |
| Imagery & weather configuration | existing imagery/weather capabilities |
| Users & roles | existing `farm_scopes.manage` |

The side-nav greys out items the current user can't access; clicking shows a small explanation rather than a 403.

---

## 12. Internationalization & RTL

- All new strings in `frontend/src/i18n/locales/{en,ar}/{insights,plan,alerts,common}.json`. The Arabic file ships with English fallback for now and is filled in a follow-up.
- Use logical CSS properties (`ms-*`, `me-*`, `start-*`, `end-*`) — already the convention in the repo.
- Number/date formatting via `Intl.*` and the existing `user_preferences` (lang, unit_system, timezone, date_format).
- `AreaDisplay` reused for any area number — never hardcode "feddan" / "ha".

---

## 13. Out of scope (explicit)

Echoing UX_SPEC §14 plus our own deferrals:

- Any FarmDM PR not listed in §5 of this plan.
- A real-time (SSE/WebSocket) alerts subscription — alerts are fetched on a 60s interval via TanStack Query refetch.
- Drag-to-reschedule on the timeline.
- Multi-select activity bars.
- The full Map view (`design_1_field_ops.html`) — Land units points at the existing FarmDetailPage instead.
- A fully translated Arabic shipment — keys exist, translations follow.
- A unified Reports view.
- Mobile field-tech view.

---

## 14. Open questions parked (not blockers)

These do not gate this slice but should be answered before the *next* slice that depends on them.

1. **Time zone storage.** ⚠️ **Promoted from "parked" to "decide before PR-1" by 2026-05-07 amendment.** `scheduled_date` is `Date` and `start_time` (added in PR-1) is `TIME` — neither carries a timezone. The UI assumes the farm's local timezone (already on `farms` per Slice-2). The migration must include a comment locking this convention; otherwise reschedule semantics drift across DST boundaries. (UX_SPEC §15.1)
2. **Conflict rules promotion to server.** When user count grows or rules become complex (off-label combinations, registry interactions), promote `detectConflicts` from `src/rules/conflicts.ts` to a backend evaluator hanging off the alerts engine. (UX_SPEC §15.3)
3. **Imagery cadence pill.** The header's "Sentinel-2 · 5d cadence" line — per-farm config or per-block? Currently per-block by FarmDM decision; the header would need to summarise (e.g., "mixed cadence" if blocks differ). (UX_SPEC §15.4)
4. **Pre-flight checklist persistence post-MVP.** Likely a JSON column on `plan_activities` — confirm before adding. (UX_SPEC §15.5)
5. **Farm-rollup index timeseries endpoint.** Server-side aggregate vs client-side rollup — measure the trend chart's first-paint after MVP and decide.

---

## 15. Success criteria for this slice

When this slice is merged:

1. Visiting `/` lands on `/insights/{currentFarmId}` and shows real KPIs, real alerts, real upcoming activities for the user's default farm.
2. The side-nav reflects the new IA. Existing flows (farm CRUD, block CRUD, attachments, members, imagery panel) are reachable via Land units and visibly unchanged.
3. The Plan view loads existing `plan_activities` for the active farm, sized correctly using the new `duration_days`. The conflict pin renders for any deliberately-overlapping spray + irrigation pair.
4. The four-step new activity modal creates real `plan_activities` rows via the existing API.
5. Reloading any URL preserves the exact view, including `?lane=` and `?activity=`.
6. Avg-NDVI delta, baseline ribbon, and health-table deviation sort all render real values from `block_index_baselines` / `block_index_aggregates.baseline_deviation`. The stage band's "you are here" outline reflects the latest `growth_stage_logs` entry. Alerts with a populated `prescription_activity_id` deep-link to the activity bar; null values fall back to lane-only.
7. Today's `irrigation_schedules.status='pending'` rows appear as `irrigation` bars on the Plan view; applying/skipping one updates the row via the irrigation endpoint and the bar's status flips without a full refetch.
8. Lighthouse, axe-core, and the test suite all green on /insights, /plan, /alerts.
9. Switching `useCapability` to a viewer role hides write controls everywhere; no 403s leak to the UI.

---

## 16. Cross-references

- **`new-ux/UX_SPEC.md`** — the visual & interaction spec. Truth for layout, copy patterns, tokens, states, accessibility.
- **`new-ux/BUILD_PLAN.md`** — the handoff team's recommended approach. Use only the parts §2 of this plan adopts.
- **`new-ux/agripulse_app.html`** — the clickable mockup. Source of truth for visual fidelity at `≥1280px`.
- **`new-ux/agripulse_core_erd.html`** — proposal ERD. Translate to our names per §4 of this plan; do **not** import literally.
- **`FarmDM/req.txt`** — original product notes (LAND_UNIT rationale).
- **memory `project_farmdm_proposal_decisions.md`** — locked PR rollout order; this slice defers PR-3 / PR-4 / PR-5-prescription-verify.
- **memory `project_slice4_weather_decisions.md`** — weather slice decisions; nothing in this UX slice contradicts them.
- **`backend/app/modules/plans/`**, **`backend/app/modules/alerts/`**, **`backend/app/modules/indices/`**, **`backend/app/modules/weather/`** — backend modules already in place that this slice consumes.
