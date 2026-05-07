# AgriPulse — Build Plan

This is the **implementation playbook** for the Claude Code session that will build the AgriPulse front-end from `UX_SPEC.md` and `agripulse_app.html`.

It assumes:
- The UX is settled (per `UX_SPEC.md`).
- API integration is **not** part of this session's scope. Build behind a typed data layer; mock data is fine; real APIs are wired later by swapping the adapter.

---

## 1. Recommended stack

| Concern | Choice | Why |
|---|---|---|
| Framework | **React 18 + TypeScript** | Component model fits the spec cleanly; large talent pool |
| Build tool | **Vite** | Fast dev loop, simple config, native TS |
| Routing | **React Router v6** | URL is the source of truth (per spec § 8) |
| Server state | **TanStack Query** | Fits the "swappable data layer" pattern; caches, retries, optimistic updates |
| Local state | **Zustand** for cross-tree UI state (selected lane/activity, modal draft); component state for everything else | Avoid Redux; keep stores small |
| Styling | **Vanilla CSS with custom properties** + co-located `.module.css` per component | Mirrors the mockup token approach; no build-step lock-in. Tailwind is fine if the team prefers — convert tokens to `theme.extend` |
| Charts | **Hand-rolled SVG** (per the mockup) for the trend chart and sparklines | Avoids 100KB chart deps for two simple visualizations. Recharts is acceptable if the team needs interactivity later |
| Dates | **date-fns** | Tree-shakeable, locale-aware |
| i18n | **react-intl** (FormatJS) | ICU MessageFormat for plurals/genders, ready for Arabic/RTL |
| Tests | **Vitest** + **React Testing Library** + **Playwright** for E2E | Industry standard, plays well with Vite |
| Lint/format | **ESLint + Prettier** with strict TS rules | Catch issues early |
| Package manager | **pnpm** | Faster, stricter |

**Don't add:**
- Redux/MobX (TanStack Query + Zustand is enough).
- Component library (MUI/AntD/Chakra) — design tokens are bespoke; a library would fight us.
- A CSS-in-JS runtime — keep CSS static for performance.
- Storybook in MVP — add post-MVP if component count grows.

---

## 2. Project structure

```
src/
├─ main.tsx                  # bootstrap
├─ App.tsx                   # router + providers
│
├─ shell/                    # layout shell (cross-cutting)
│  ├─ TopBar.tsx
│  ├─ SideNav.tsx
│  ├─ FarmSwitcher.tsx
│  └─ UserMenu.tsx
│
├─ views/
│  ├─ insights/
│  │  ├─ InsightsView.tsx
│  │  ├─ KPICards.tsx
│  │  ├─ TrendChart.tsx
│  │  ├─ LandUnitTable.tsx
│  │  ├─ AlertsFeed.tsx
│  │  ├─ MiniFarmMap.tsx
│  │  └─ ActivityListMini.tsx
│  │
│  ├─ plan/
│  │  ├─ PlanView.tsx
│  │  ├─ PlanToolbar.tsx
│  │  ├─ StageLegend.tsx
│  │  ├─ LaneSidebar.tsx
│  │  ├─ Timeline.tsx
│  │  ├─ Lane.tsx
│  │  ├─ ActivityBar.tsx
│  │  ├─ ConflictOverlay.tsx
│  │  ├─ StageBand.tsx
│  │  ├─ ActivityDetail.tsx
│  │  └─ NewActivityModal/
│  │     ├─ index.tsx
│  │     ├─ Step1Type.tsx
│  │     ├─ Step2Lanes.tsx
│  │     ├─ Step3Schedule.tsx
│  │     ├─ Step4Details.tsx
│  │     └─ Stepper.tsx
│  │
│  └─ stubs/                 # MVP placeholders for Land units, Alerts, Reports, Config/*
│
├─ components/               # reusable primitives
│  ├─ Button.tsx
│  ├─ IconButton.tsx
│  ├─ Pill.tsx
│  ├─ Badge.tsx
│  ├─ SegmentedControl.tsx
│  ├─ FilterChip.tsx
│  ├─ Card.tsx
│  ├─ Sparkline.tsx
│  ├─ KVList.tsx
│  ├─ Avatar.tsx
│  ├─ Tooltip.tsx
│  └─ Modal.tsx
│
├─ data/                     # the swappable data layer
│  ├─ types.ts               # all entity TS types — derived from agripulse_core_erd.html
│  ├─ adapter.ts             # interface every data source must implement
│  ├─ mock/
│  │  ├─ index.ts            # mock implementation of adapter
│  │  └─ fixtures/           # JSON fixtures matching the mockup's data
│  └─ http/                  # placeholder for real HTTP impl (do not implement in MVP)
│     └─ index.ts
│
├─ state/
│  ├─ session.ts             # currentUser, currentOrg, currentFarm
│  ├─ selection.ts           # selectedLane, selectedActivity (mirrors URL)
│  ├─ filters.ts             # plan view filters
│  └─ checklist.ts           # pre-flight checks per activity (local storage)
│
├─ hooks/
│  ├─ useUrlSelection.ts     # syncs ?lane / ?activity with state
│  ├─ useConflictDetection.ts
│  └─ useStageBand.ts        # derives band segments from CROP_VARIETY + GROWTH_STAGE_LOG
│
├─ rules/                    # domain logic, pure functions
│  ├─ conflicts.ts           # detectConflicts(activities, rules) → ConflictEdge[]
│  ├─ stages.ts              # current stage of a land unit, segment widths from variety
│  └─ formatting.ts          # area/date/NDVI formatters
│
├─ tokens/
│  └─ tokens.css             # design tokens from UX_SPEC § 9
│
├─ assets/icons/             # inline SVG components
│
└─ test/
   ├─ setup.ts
   └─ fixtures/
```

**Conventions:**
- Component files: one component per file, named export.
- CSS modules co-located: `Foo.tsx` + `Foo.module.css`.
- Pure logic in `rules/` and `hooks/` — these are the targets for unit tests.
- No business logic in `views/` — they orchestrate, they don't compute.

---

## 3. Data layer (swappable adapter)

The single most important architectural rule.

```ts
// src/data/adapter.ts
export interface DataAdapter {
  // Session
  getCurrentSession(): Promise<Session>;
  switchFarm(farmId: string): Promise<void>;

  // Read
  listLandUnits(farmId: string): Promise<LandUnit[]>;
  listActivities(farmId: string, range: DateRange): Promise<PlanActivity[]>;
  listAlerts(farmId: string, status?: AlertStatus): Promise<Alert[]>;
  getIndexTimeseries(landUnitId: string, range: DateRange, indexType: IndexType): Promise<IndexPoint[]>;
  getCropVarieties(): Promise<CropVariety[]>;
  getGrowthStageLogs(landUnitId: string): Promise<GrowthStageLog[]>;

  // Write
  createActivity(input: CreateActivityInput): Promise<PlanActivity>;
  updateActivity(id: string, patch: UpdateActivityInput): Promise<PlanActivity>;
  resolveAlert(id: string): Promise<void>;
  toggleChecklistItem(activityId: string, item: string, done: boolean): Promise<void>;

  // Streams (optional — can be a no-op until backend supports it)
  subscribeAlerts?(farmId: string, onEvent: (a: Alert) => void): Unsubscribe;
}
```

**MVP must ship two implementations:**

1. `MockAdapter` (in `src/data/mock/`) — backed by JSON fixtures matching the mockup. The dev server runs against this by default.
2. `HttpAdapter` (in `src/data/http/`) — **stub only**. Throws `NotImplementedError` for every method. The backend team replaces methods one at a time.

`App.tsx` reads `import.meta.env.VITE_DATA_ADAPTER` (`mock` | `http`) and instantiates accordingly. **No view code imports an adapter directly** — they go through TanStack Query hooks like `useLandUnits()`, `useActivities()`, etc.

---

## 4. TypeScript types — derive from the ERD

Every entity in `agripulse_core_erd.html` becomes a TS type in `src/data/types.ts`. Stay close to the model:

```ts
export type UnitType = 'block' | 'pivot' | 'pivot_sector';
export type ActivityType = 'planting' | 'fertilizing' | 'spraying' | 'pruning' | 'harvesting';
export type ActivityStatus = 'draft' | 'scheduled' | 'completed' | 'skipped';
export type AlertSeverity = 'info' | 'warn' | 'critical';
export type AlertStatus = 'open' | 'acknowledged' | 'resolved' | 'dismissed';
export type IndexType = 'NDVI' | 'NDWI' | 'GCI';

export interface LandUnit {
  id: string;
  farmId: string;
  name: string;
  unitType: UnitType;
  boundary: GeoJsonPolygon;        // any consumer of geometry tolerates GeoJSON
  areaFeddans: number;
  cropVarietyId: string;
  plantingYear?: number;
  rootstock?: string;
  irrigationMethod: string;
  soilType?: string;
  currentGrowthStage: string;
  createdAt: string;               // ISO8601
}

export interface PlanActivity {
  id: string;
  planId: string;
  landUnitId: string;
  activityType: ActivityType;
  scheduledDate: string;           // ISO8601 — see open question §15.1 in UX_SPEC
  durationDays: number;            // see open question §15.2
  productName?: string;
  dosage?: string;
  notes?: string;
  status: ActivityStatus;
  completedAt?: string;
}

export interface Alert {
  id: string;
  landUnitId: string;
  ruleId: string;
  severity: AlertSeverity;
  status: AlertStatus;
  diagnosis: string;
  prescription: string;
  prescriptionActivityId?: string; // for "Resolve" deep links
  createdAt: string;
  resolvedAt?: string;
}

// ... and so on for Organization, Farm, User, CropVariety,
// IndexTimeseries, IrrigationSchedule, GrowthStageLog, ImageryConfig,
// WeatherConfig, RuleOverride
```

Convert ERD `snake_case` → TS `camelCase` at the adapter boundary.

---

## 5. Phased delivery

Six phases. Each phase is independently demoable. Don't move on until acceptance criteria pass.

### Phase 0 — Scaffold (½ day)

Set up the project. Nothing visible to a user.

- Vite + React + TS scaffold with `pnpm`.
- ESLint, Prettier, Vitest, Playwright wired.
- `tokens.css` imported globally.
- `MockAdapter` and `HttpAdapter` stubs in place.
- TanStack Query provider set up.
- React Router with placeholder routes for every URL in UX_SPEC § 3.
- A trivial home page proving the shell renders.

**Acceptance:**
- ✅ `pnpm dev` opens a blank-but-styled page using the design tokens.
- ✅ `pnpm test` runs and finds zero tests (passing).
- ✅ All routes render a stub.

### Phase 1 — Shell (1 day)

Build the persistent shell so subsequent views drop in.

- `<TopBar>` with brand, breadcrumbs, search/notifications/avatar buttons (non-functional).
- `<SideNav>` with all items, counts, active-state highlighting based on URL.
- View-specific toolbar slot on the top bar (renders different content for `/insights` vs `/plan`).
- Farm switcher popover (mock list of 2–3 farms).
- User menu (mock).
- Apply tokens; visually match the mockup pixel-near.

**Acceptance:**
- ✅ Side nav highlights the current section as you click between routes.
- ✅ Farm switcher swaps the breadcrumb name (state lives in `state/session.ts`).
- ✅ Visually matches `agripulse_app.html` shell at `≥1280px`.
- ✅ Keyboard navigation: tabbing through the top bar and side nav works; visible focus rings.

### Phase 2 — Insights view (2 days)

Implement the dashboard end-to-end against `MockAdapter`.

- `<KPICards>` — 4 cards, sparklines, deltas. "Irrigation due" deep-links to `/plan`.
- `<TrendChart>` — hand-rolled SVG, baseline ribbon, today guideline, segmented control to switch series.
- `<LandUnitTable>` — sort by deviation, pill+progress, "Plan" button deep-links to `/plan?lane=…`.
- `<AlertsFeed>` — severity-bar + ico-circle pattern, action buttons that deep-link with the right query params.
- `<MiniFarmMap>` — static SVG of farm boundary + colored land units, click → `/plan?lane=…`.
- `<ActivityListMini>` — top 3–5 upcoming activities, click → `/plan?activity=…`.

Build the data hooks: `useLandUnits()`, `useActivities()`, `useAlerts()`, `useIndexTimeseries()`. Wire to `MockAdapter`.

**Acceptance:**
- ✅ Every card renders from mock data — no hardcoded JSX strings.
- ✅ Loading skeletons for each card while mock adapter "fetches".
- ✅ Empty states: stub a "new farm with no data" mock to verify each empty state renders.
- ✅ Every deep link from Insights lands on `/plan` with the right URL params.
- ✅ Trend chart shows correct points for the fixture data; tooltip on hover.
- ✅ All clickable elements keyboard-accessible.

### Phase 3 — Plan view, read-only (3 days)

Build the timeline and detail panel — view & navigate, no creation yet.

- `<PlanToolbar>` with filter chips, drafts toggle, stage legend, stat counters.
- `<LaneSidebar>` — grouped lanes, click selects.
- `<Timeline>` — month + week headers, today line, lanes rendered from data.
- `<Lane>` — head + stripes; renders `<ActivityBar>` per activity, `<StageBand>` from `CROP_VARIETY.phenology_model` + actual `GROWTH_STAGE_LOG` overrides, `<ConflictOverlay>` from `detectConflicts()` (rules from UX_SPEC § 6.5).
- `<ActivityDetail>` — populates on selection, shows all sections from UX_SPEC § 6.7. Pre-flight checklist toggles persist to localStorage.
- URL-driven selection via `useUrlSelection` — page reload restores exact state.

**Acceptance:**
- ✅ Timeline horizontally scrolls; sticky lane heads stay visible when scrolling right.
- ✅ Filter chips toggle bar visibility in real time. Stat counters reflect visible-set.
- ✅ Drafts-only toggle composes correctly with type filters.
- ✅ Stage band shows the right segment widths per variety (test with Keitt and Tommy Atkins fixtures).
- ✅ Current-stage segment has the inner outline.
- ✅ Conflict pin shows on B1 (spray + drip pulse fixture). Hover tooltip works.
- ✅ Activity selection updates `?activity=` and `?lane=`. Reload preserves it.
- ✅ Detail panel renders all sections; checklist toggles persist across reloads.
- ✅ Esc clears selection.
- ✅ Every Phase-2 deep link resolves correctly here.

### Phase 4 — New activity flow (2 days)

The 4-step modal.

- `<NewActivityModal>` with 4 steps and stepper.
- Step 1: type cards, single-select.
- Step 2: land unit chips, multi-select, grouped.
- Step 3: schedule inputs + live `<ConflictPreview>` using the same `detectConflicts()` function from Phase 3.
- Step 4: details inputs + `<SummaryBox>` + final conflict warning.
- On Create: optimistic insert into the timeline, auto-select first new activity, scroll lane into view.
- Failure path: keep modal open, error banner, flag failed entries.
- Keyboard: Esc closes (with confirm if dirty), Enter advances on valid step, arrow keys on type cards.
- Focus trap, return focus on close, ARIA dialog role.

**Acceptance:**
- ✅ Open from "+ New activity" button on Plan view AND from Insights "+ New plan" button.
- ✅ Validation: cannot advance from step 1 with no type, or step 2 with empty selection. Visual feedback (button flash).
- ✅ Step 3 conflict preview updates within 200ms of any input change.
- ✅ Step 4 summary reflects live state.
- ✅ Creating with a known conflict still succeeds but logs the conflict acknowledgement.
- ✅ Modal accessibility: focus trap, Esc closes, screen reader announces step changes.
- ✅ E2E test (Playwright): full "Spray → Block B1 → May 8 → Mancozeb → Create" flow ends with the new bar visible & selected.

### Phase 5 — Polish & non-functional (1.5 days)

Make it ship-ready.

- Loading skeletons standardized across all cards (one shared `<Skeleton>` component).
- Error boundaries around each view.
- Toast system for transient errors and post-action confirmations.
- Performance pass:
  - Virtualize the lane list if `landUnits.length > 30` (use `@tanstack/react-virtual`).
  - Memoize bar position calculations.
  - Lazy-load the New activity modal (it's only opened on demand).
- i18n hooks: extract every visible string to a `messages/en.json` (no Arabic translation in this scope, but the structure is in place).
- Accessibility audit: axe-core via Vitest + Playwright; fix every violation.
- Print stylesheet for the Insights view (export-as-PDF-friendly).
- README for the codebase: how to run, where to find what, how to swap adapters.

**Acceptance:**
- ✅ Lighthouse: Performance ≥ 90, Accessibility ≥ 95, Best Practices ≥ 95 on `/insights` and `/plan` (mock data).
- ✅ Zero axe-core violations on either view.
- ✅ Bundle size < 300KB gzipped (split modal lazy chunk excluded).
- ✅ E2E suite passes locally and in CI.

### Phase 6 — Real API integration (out of scope for THIS session)

Listed for completeness — done by the backend team or a follow-up session.

- Implement `HttpAdapter` method by method against the actual API.
- Switch the env var; the views don't change.
- Add real-time alert subscription if the backend supports it.

---

## 6. Testing strategy

| Level | Tool | What to cover |
|---|---|---|
| **Unit** | Vitest | Pure logic in `rules/` and `hooks/`. Especially: `detectConflicts`, stage segment calculation, date/area formatters, URL param sync. |
| **Component** | RTL | Each component in `components/` and `views/*/` rendered with mock data + interactions. Selection state, filter toggles, modal step transitions. |
| **E2E** | Playwright | Three core flows: (1) Insights → alert "Resolve" → Plan with prescription auto-selected. (2) Plan filter chips + lane selection + activity selection survive reload. (3) Full New activity create flow including conflict preview. |
| **Visual regression** | (post-MVP) Playwright screenshot diffs against a baseline | Catch unintended UI shifts |

Test data lives in `src/data/mock/fixtures/` — same fixtures power dev mode and tests. **No magic strings in tests** — import from fixtures.

---

## 7. Quality gates before shipping

Run before declaring Phase 5 complete:

```bash
pnpm typecheck           # zero TS errors
pnpm lint                # zero ESLint errors
pnpm test                # all unit + component tests pass
pnpm test:e2e            # all Playwright tests pass
pnpm build               # bundle builds, < size budget
pnpm preview             # smoke test the prod build
```

Manual checks:
- Open `/insights`, click every interactive element, verify nothing throws.
- Open `/plan`, scroll through all lanes, hover all conflict pins, hover all stage segments.
- Run through the New activity modal three times with different combinations.
- Resize from 1440 → 1024 → 640px; verify the responsive rules in UX_SPEC § 11.
- Tab through both views with no mouse; verify every interaction is reachable.

---

## 8. Estimated effort

For a single experienced front-end engineer, working full-time:

| Phase | Estimate |
|---|---|
| Phase 0 — Scaffold | 0.5 day |
| Phase 1 — Shell | 1 day |
| Phase 2 — Insights | 2 days |
| Phase 3 — Plan (read-only) | 3 days |
| Phase 4 — New activity flow | 2 days |
| Phase 5 — Polish & non-functional | 1.5 days |
| **Total** | **~10 working days** |

Add 30% buffer for review cycles, design tweaks, and platform-team API alignment.

---

## 9. What success looks like

When this session is done:
1. `pnpm dev` launches a UI that **looks and behaves like `agripulse_app.html`** — but built on real components, real data flow, real types.
2. Switching `VITE_DATA_ADAPTER=http` would crash with `NotImplementedError` — proving the views never reached around the adapter.
3. The codebase is **legible to the backend team** so they can fill in `HttpAdapter` without front-end help.
4. Every flow from `UX_SPEC.md` works without a single console warning.
5. Lighthouse, axe, and the test suite all pass.

---

## 10. Notes for the implementer

- **Don't redesign as you build.** If the spec is ambiguous, prefer faithful-to-mockup. If the mockup is ambiguous, prefer simpler. Raise the question rather than invent.
- **Don't add features.** Anything not in `UX_SPEC.md` waits.
- **Keep components dumb.** A `<KPICard>` should not know how to fetch data. Pages compose; components present.
- **Style with tokens, never hex literals.** If you reach for a new color, propose adding it to tokens first.
- **Test the conflict logic carefully.** It's the part most likely to silently regress.
- **The mockup is throwaway.** Once components are built, the mockup HTML can be archived. Do not import from it.
