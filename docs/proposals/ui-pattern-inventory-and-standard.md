# UI Pattern Inventory & Standard Page Pattern

**Date:** 2026-07-29
**Scope:** `frontend/src` — every routed page in the tenant workspace and the Platform Management Portal.
**Goal:** unify look-and-feel for pages that share a *shape* (not a function), and name the pages that are genuinely one-of-a-kind so they are explicitly exempt.

Builds on `docs/reports/ux-consistency-assessment-2026-06-08.html` (findings F-1..F-11). That
assessment diagnosed the problem; the `src/components/` primitives were the prescribed cure.
This document measures whether the cure was taken, inventories the surfaces by pattern, and
proposes the contract that makes the drift non-recurring.

---

## 1. Pattern taxonomy

Eight shapes cover all 45 routed pages.

| # | Pattern | Shape | Count |
|---|---------|-------|-------|
| **P1** | **Index (table)** | Header + toolbar (search/filter) + table + optional pagination; row click → detail | 9 |
| **P2** | **Index (card/row list)** | Same skeleton, but rows are multi-line cards with inline actions; no detail page | 4 |
| **P3** | **Index (expandable / editable in place)** | Table or row-list where the row *is* the editor — expand/inline-save, no separate detail route | 5 |
| **P4** | **Entity detail** | Back link/breadcrumb + identity header + status + KPI/summary + tabbed or stacked panels + destructive actions | 5 |
| **P5** | **Entity form** | Header + single-column field stack + submit/cancel footer | 5 |
| **P6** | **Settings / config surface** | Section stack of labelled panels with save-per-section | 7 |
| **P7** | **Tabbed dashboard** | Header + segmented tabs, each tab an independent data view | 3 |
| **P8** | **Bespoke canvas** | Full-bleed or app-inside-a-page; owns its own layout & scrolling | 7 |

P1+P2+P3 = **18 index pages**. P4 = **5 detail pages**. That is the mass the user is pointing at.

---

## 2. Inventory

### P1 — Index (table) → detail

| Route | Component | Detail target | Drift from the best-in-class version |
|---|---|---|---|
| `/platform/tenants` | `TenantListPage` | `/platform/tenants/:id` | **Reference implementation.** `<PageHeader>`+`<Table>`+`<FilterChip>`+`<ErrorState>`+pagination. Wrapper `section.mx-auto.max-w-5xl` |
| `/farms` | `FarmListPage` | `/farms/:id` | Also uses primitives, but wrapper is `div.space-y-4` (no max-width), filter is a bare checkbox in a `<Card>`, empty state is `<EmptyState>` (vs in-table row), navigation is a link in cell 1 (vs `<Tr interactive>`), no pagination |
| `/decision-trees` | `DecisionTreeListPage` | `/decision-trees/:code` | `max-w-6xl`, raw `<h1>`, raw `<table>`, 4× `<select>` filters (not chips), 4-branch loading/error/empty/no-results ladder, `px-4 py-2` cells vs `px-3 py-2` |
| `/platform/plan-templates` | `PlatformPlanTemplatesPage` | `/platform/plan-templates/:id` | `max-w-5xl p-6` (double padding), raw `<h1>`, raw `<table>`, **hand-rolled pill filters** (3rd filter idiom), `px-4 py-3` cells, own `thead` border treatment |
| `/platform/admins` | `PlatformAdminsPage` | — (modal) | `max-w-5xl p-6`, raw `<h1>`, raw `<table>`, no toolbar, invite via `<Modal>` |
| `/platform/integrations/health` | `PlatformHealthPage` | `…/tenants/:id` | `max-w-6xl p-6`, raw `<h1>`, raw `<table>`, no toolbar, empty state is a bare `<p>` |
| `/settings/users` | `UsersConfigPage` | — (inline) | `max-w-5xl` (no `p-6`), raw `<h1>`, raw `<table>` |
| `/tenants/:tenantId` | `TenantDetailPage` | `/farms/:id` | `div.space-y-6`, legacy `.card` class, **borderless** raw `<table>` with `border-t` rows — a 4th table look |
| `/platform/backfill` | `PlatformBackfillPage` (Runs tab) | — | `p-4` wrapper, `text-lg` `<h1>` (only page at that scale), raw `<table>` with `p-2` cells, `min-w-[720px]` |

### P2 — Index (card/row list), inline actions

| Route | Component | Notes |
|---|---|---|
| `/alerts/:farmId` | `AlertsPage` | `<SegmentedControl>` in header as the status filter; `ul.divide-y` inside inline card surface; severity rail; local `Row` |
| `/recommendations/:farmId` | `RecommendationsPage` | Structurally a **near-clone** of AlertsPage (same wrapper, same 4-branch ladder, same `ul.divide-y`), diverges only in row content and an extra header link |
| `/signals/:farmId` | `SignalsLogPage` | Same wrapper, but body is a `grid lg:grid-cols-[18rem_1fr]` master–detail split — the only index page with that layout |
| `/platform/crops` | `PlatformCropsPage` | Expandable crop → variety → strain tree in a `divide-y` panel; legacy `.btn btn-primary` |

### P3 — Index with in-place editing

| Route | Component | Notes |
|---|---|---|
| `/settings/workers` | `ResourcesWorkersPage` | `<PageHeader>` ✓, but `flex-col gap-6` wrapper and raw `<table>` with `border-b p-3` card header |
| `/settings/equipment` | `ResourcesEquipmentPage` | Sibling of the above; same shape, independently written |
| `/platform/defaults` | `PlatformDefaultsPage` | Grouped `<section>` panels of `DefaultRow` editors; raw `<h1>`; per-row save |
| `/settings/rules` | `RulesConfigPage` | Tabs + list + inline rule editing |
| `/config/signals/:farmId` | `SignalsConfigPage` | 1030 lines; template list + per-template field editor; local `Field` |

### P4 — Entity detail

| Route | Component | Wayfinding | Header | Panels | Notes |
|---|---|---|---|---|---|
| `/platform/tenants/:id` | `TenantAdminDetailPage` | `←`/`→` text link | `text-lg` + slug + status badge, `border-b` | `<SegmentedControl>` tabs → `<KPICard>` row + panels | **Defines a local `Card`** (`rounded-lg … shadow-card`) that shadows the shared `Card` (`rounded-xl`, no shadow) |
| `/farms/:farmId` | `FarmDetailPage` | `<Breadcrumb>` | `<PageHeader>` `text-2xl` | Stacked `<Card>`s, no tabs | Actions use legacy `.btn btn-ghost`; blocks list is a bare `<ul>` |
| `/farms/:farmId/blocks/:blockId` | `BlockDetailPage` | `<Breadcrumb>` | `<PageHeader>` | Stacked, legacy `.card` div | Sibling of FarmDetailPage; mixes `<Card>` and `.card` |
| `/platform/plan-templates/:id` | `PlanTemplateEditorPage` | `←` link | raw `<h1>` `text-xl` | Editor panels | `max-w-5xl p-6` |
| `…/health/tenants/:tenantId` | `PlatformHealthTenantDrillPage` | `←` link | *(delegated)* | Wraps `IntegrationsHealthPage` | Adds a 3rd back-link idiom |

**Three wayfinding idioms for one concept** (breadcrumb / arrow-link / none) — F-7, still open.

### P5 — Entity form

`FarmEditPage`, `BlockEditPage`, `BlockCreatePage`, `DecisionTreeCreatePage`, `/platform/tenants/new` (`TenantCreatePage`).
`div.space-y-4` + raw `<h1>` for the farms trio; `section.mx-auto.max-w-2xl` multi-step for TenantCreatePage.
Four independent local `Field` components (`TenantCreatePage`, `DecisionTreeCreatePage`, `PlanTemplateEditorPage`, `SignalsConfigPage`) plus three more in non-page files.

> `FarmCreatePage.tsx` is **dead code** — `/farms/new` redirects to `/labs/map?create=farm`; nothing but its own test imports it.

### P6 — Settings / config surfaces

`SettingsIndexPage`, `SettingsPlaceholderPage`, `IntegrationsWeatherPage`, `IntegrationsImageryPage`, `IntegrationsTenantOnlyPage`, `ImageryWeatherConfigPage`, `FarmMembersPage`.
The three `Integrations*` pages are the most internally consistent group in the codebase (`flex-col gap-6` + `<PageHeader>` + `<EmptyState>`), and they are also the group that **triple-pads**: `AppShell` `px-4 py-6` → `SettingsLayout` `px-4 py-6` → page content.

### P7 — Tabbed dashboard

`IntegrationsHealthPage` (+ `OverviewTab`/`RunsTab`/`QueueTab`/`ProvidersTab`), `InsightsPage`, `PlatformBackfillPage`.
`IntegrationsHealthPage` and `InsightsPage` use `<SegmentedControl>`; `PlatformBackfillPage` hand-rolls `role="tablist"` + `TabButton`.

### P8 — Bespoke canvas (**genuinely unique — exempt from the index/detail standard**)

| Route | Component | Why it's unique |
|---|---|---|
| `/labs/map` | `FarmConsolePage` | Full-bleed map, progressive disclosure, owns scrolling; `AppShell` special-cases it |
| `/labs/map-legacy` | `MapExperiencePage` | Legacy full-bleed map (1720 lines) |
| `/board/:farmId` | `BoardPage` | Season/week/month activity grid; `max-w-[none]`, `px-4 py-6` |
| `/decision-trees/:code` | `DecisionTreeViewerPage` | Visual node canvas + YAML toggle; `max-w-[120rem]` — widest page in the app |
| `/reports/:farmId` | `ReportsPage` | Registry + print-to-PDF (`.report-print-area`) |
| `/` | `HomePage` | Redirect-or-empty-state card; legacy `.card` |
| `/login` | `LoginPage` | Unauthenticated split layout, `bg-sand-50` — the only surviving `sand-*` use |

---

## 3. Why they look different — the measured drift

The design system exists and is **almost entirely unused**. Census over `frontend/src` (excluding tests):

| Primitive | Files importing it | Competing hand-rolled instances |
|---|---|---|
| `<Button>` | **0** | 64 `bg-ap-primary px-…` + 34 legacy `.btn` |
| `<Card>` | 3 | 79 inline `rounded-xl border border-ap-line bg-ap-panel` + 16 `rounded-lg` variants + 23 legacy `.card` |
| `<Table>` | 2 | 28 raw `<table>` |
| `<PageHeader>` | 10 | 37 raw `<h1>` at `text-2xl` / `text-xl` / `text-lg` / `text-base` / `text-sm` |
| `<EmptyState>` | 4 | 28 hand-rolled `p-12 / py-10 / py-12 text-center` |
| `<ErrorState>` | 5 | 145 inline `text-{sm,xs} text-ap-crit` |
| `<FilterChip>` | 1 | pill-buttons, `<select>`s, checkboxes |
| `<Breadcrumb>` | 2 | 3 arrow-link back-idioms |
| `<Skeleton>` | 56 | — (the one success) |
| `<Pill>` | 26 | — (mostly adopted) |

Four structural axes account for nearly all the visual difference:

1. **Page frame.** Nine variants in use: `space-y-4`, `space-y-6`, `space-y-5 p-4`, `flex-col gap-4`, `flex-col gap-6`, `mx-auto max-w-4xl`, `max-w-5xl`, `max-w-5xl p-6`, `max-w-6xl p-6`. `AppShell` already supplies `px-4 py-6`, so every `p-4`/`p-6` page is double-padded and every `/settings/*` page is triple-padded.
2. **Header.** `<PageHeader>` (10) vs raw `<h1>` at 5 different type scales (37).
3. **Async ladder.** Every list page re-implements loading→error→empty→no-results, with the skeleton sometimes replacing the whole table (`FarmListPage`, `PlatformHealthPage`) and sometimes living inside it (`TenantListPage`).
4. **Data layer.** 29 pages on react-query, 18 on `useEffect`+`useState`+`isApiError` — which is *why* the error/empty rendering can't converge: the two idioms don't produce the same state object.

---

## 4. Proposed standard

### 4.1 One page frame, owned by the shell

Delete every per-page `mx-auto max-w-*` / `p-*` and move width into a shell-level contract:

```tsx
<Page width="standard">   // max-w-5xl  — index, form, detail  (default)
<Page width="wide">       // max-w-6xl  — dense tables, dashboards
<Page width="full">       // no cap     — board, canvases
<Page width="bleed">      // no padding — map surfaces
```

`AppShell` keeps `px-4 py-6`; `<Page>` owns `mx-auto`, the max-width, and vertical rhythm
(`flex flex-col gap-4`). `SettingsLayout` drops its own `px-4 py-6`.

### 4.2 Three page templates

**`<IndexPage>`** — for all 18 P1/P2/P3 surfaces:

```
<Page>
  <PageHeader title subtitle actions>        // one type scale, always
  <Toolbar search filters                    // FilterChip only; no bare <select>
           right={viewToggle}>
  <AsyncBoundary                             // one component owns the ladder
     query={q}
     empty={<EmptyState message action/>}    // action is required, not optional (F-8)
     skeleton="table" | "rows">
    <DataTable columns rows onRowClick/>     // or <RowList> for P2
  </AsyncBoundary>
  <Pagination/>                              // rendered iff total > pageSize
</Page>
```

Row navigation standardizes on `<Tr interactive onClick>` **plus** a real `<Link>` in the identity
column (keyboard + middle-click survive; whole row stays clickable).

**`<DetailPage>`** — for all 5 P4 surfaces:

```
<Page>
  <PageHeader above={<Breadcrumb/>}          // breadcrumb is the ONE wayfinding idiom
              title subtitle badge
              actions={[edit, …, destructive-last]}/>
  <StatusBanner/>                            // optional, role="status"
  <KPIRow/>                                  // optional
  <Tabs/>  →  <Card> panels                  // SegmentedControl always; never hand-rolled
</Page>
```

**`<FormPage>`** — for all 5 P5 surfaces: `<Page width="standard">` + `<Breadcrumb>` + one shared
`<Field>` (label / help / error / required) replacing the seven local copies + a sticky
`<FormFooter>` with cancel-then-submit ordering.

### 4.3 Primitives to add / fix

| Action | Component | Replaces |
|---|---|---|
| **add** | `<Page>` | 9 wrapper variants |
| **add** | `<AsyncBoundary>` | ~18 hand-written loading/error/empty ladders + 145 inline error strings |
| **add** | `<DataTable>` (thin, on `<Table>`) | 28 raw `<table>` |
| **add** | `<Toolbar>` | 4 filter idioms |
| **add** | `<Field>` | 7 local `Field` copies |
| **add** | `<Pagination>` | the one copy in `TenantListPage` |
| **add** | `<BackLink>` or enforce `<Breadcrumb>` | 3 back-link idioms |
| **fix** | `<Card>` — add optional `title`/`footer` slots | local `Card` in `TenantAdminDetailPage` + `BlockDefaultsPanel`; 79 inline surfaces |
| **enforce** | `<Button>` | 64 hand-rolled + 34 `.btn`; add a `Button`-styled `<LinkButton>` so `<Link className="btn…">` disappears |
| **retire** | `.btn` / `.card` / `.input` / `.label` in `index.css` | 57 call sites |

### 4.4 Theme

The token layer is sound — `ap.*` in `tailwind.config.ts` is coherent and RTL is handled via
`tailwindcss-rtl` + logical utilities. It needs three additions, not a redesign:

1. **Type scale as tokens.** `text-page-title` / `text-section-title` / `text-body` / `text-meta`
   so `text-2xl|xl|lg|base|sm` for an `<h1>` becomes unspellable.
2. **Surface tokens.** One radius (`rounded-xl`), one border, one elevation. Today
   `rounded-xl`-no-shadow and `rounded-lg`-`shadow-card` both claim to be "the card".
3. **Kill the dead palettes.** `brand-*` is down to 2 uses and `sand-*` to `LoginPage`. Fold both
   into `ap.*` and delete the scales, or the next page re-seeds the drift.

Dark mode is **not** in scope and nothing currently anticipates it; if it's wanted, the `ap.*`
tokens should move to CSS variables in the same pass rather than later.

### 4.5 Enforcement (otherwise this regresses — it already did once)

The primitives were written in June with explicit "new code should use this" comments and got
0–10 adopters. Convention alone has been tested and failed. Add:

- ESLint `no-restricted-syntax`: ban raw `<table>`, raw `<h1>`, `className="btn*"`, `className="card"`, and the literal `rounded-xl border border-ap-line bg-ap-panel` outside `src/components/`.
- `lint-imports`-style guard: page modules may not define a component named `Card` / `Field` / `Row`.
- A Storybook-or-equivalent page-template gallery so "what does an index page look like" has one answer to point at.

---

## 5. Suggested sequencing

| Phase | Content | Blast radius |
|---|---|---|
| **0** | Add `<Page>`, `<AsyncBoundary>`, `<DataTable>`, `<Toolbar>`, `<Field>`, `<Pagination>`; extend `<Card>`; add `<LinkButton>`. No page edits. | additive, zero risk |
| **1** | Land the lint rules as **warnings**. Convert `TenantListPage` (P1), `TenantAdminDetailPage` (P4), `FarmEditPage` (P5) as the three reference conversions. | 3 pages |
| **2** | Convert the remaining 17 index pages. Highest payoff: `AlertsPage`/`RecommendationsPage` (near-duplicates → one `<RowList>`), `ResourcesWorkersPage`/`ResourcesEquipmentPage` (siblings), the 4 raw-table platform pages. | 17 pages |
| **3** | Detail + form pages; delete local `Card`/`Field`; single wayfinding idiom. | 10 pages |
| **4** | Retire `.btn`/`.card`/`.input`/`.label`; delete `brand-*`/`sand-*`; lint rules → errors. Delete dead `FarmCreatePage`. | cleanup |
| **5** | Type-scale + surface tokens; P8 canvases adopt `<Page width="full|bleed">` and `<PageHeader>` only (they keep their bespoke bodies). | tokens |

Phases 2 and 3 are mechanical and parallelizable per module. Phase 4 is the one that must not be
skipped — every prior cleanup stalled before it, which is why three generations of button styling
coexist today.

---

## 6. Open decisions

1. **Row navigation** — whole-row click (Platform convention) or link-in-first-cell (Farms convention)? Recommend both, as in §4.2.
2. **Filter idiom** — chips (`TenantListPage`) or dropdowns (`DecisionTreeListPage`)? Chips read better but don't scale past ~6 values; `DecisionTreeListPage` has 4 axes. Recommend chips for ≤2 axes / ≤6 values, a filter popover beyond that.
3. **Client vs server filtering** — `DecisionTreeListPage` filters in `useMemo`, `TenantListPage` filters server-side. The standard toolbar has to pick one default.
4. **Data layer** — is converting the 18 `useEffect` pages to react-query in scope? Without it, `<AsyncBoundary>` needs two shapes. Recommend yes, folded into each page's conversion.
5. **Dark mode** — in or out? Decide before §4.4, not after.
6. **Storybook** — worth adding as the pattern reference, or is a `/labs/patterns` route inside the app enough?
7. **Arabic/RTL** — the open `project_arabic_i18n_hardening` PR-2/PR-3 work touches hardcoded JSX strings in these same components. Sequence the two so they don't collide.
