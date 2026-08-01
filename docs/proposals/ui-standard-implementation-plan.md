# UI Standard — Implementation Plan

**Date:** 2026-07-29
**Status:** awaiting green light. Nothing implemented.
**Inputs:** `docs/reports/ui-pattern-inventory-2026-07-29.html` (inventory) · `docs/proposals/ui-standard-mockups.html` (option mockups)

---

## 0. Decision record — locked

| # | Decision | Choice | Decided by |
|---|---|---|---|
| 1 | Row navigation | **C** — whole-row click *and* a real `<Link>` in the identity cell, plus a hover chevron | user |
| 2 | Filter idiom | **C** — status chips inline + counted filter popover + applied-filter chip row | user |
| 3 | Skeleton placement | **B** — inside the table; headers and toolbar render immediately | user |
| 4 | Detail composition | **C** — unified header (breadcrumb + `text-2xl` + inline status + actions, destructive last); tabs once a page exceeds 3 panels | user |
| 5 | Page width | **Wide** — `max-w-6xl` (1152px) is the default frame | user |
| 6 | Dark mode | **Light only** | user |
| 7 | `AsyncBoundary` shape | delegated → see §1.4 | me |

### Two questions the deck raised that are still open

Both were on the decision sheet but not in the reply. I am proceeding on these assumptions; say so if either is wrong.

| Question | Assumption I'm building on | Why |
|---|---|---|
| Client- or server-side filtering | **Server-side where the API supports it, client-side fallback otherwise.** `<Toolbar>` is agnostic; it emits a filter object and the page decides. | `DecisionTreeListPage` filters in a `useMemo` today and will break the moment a tenant passes one page of rows. Not worth adding API params in this workstream, so the fallback stays. |
| The 18 `useEffect` pages | **Convert to react-query as part of each page's own conversion**, not as a separate sweep. | Keeps each PR self-contained and testable. §1.4 is designed so a page can convert its layout *before* its data layer if a conversion turns out to be hairy. |

### Consequences of decisions 5 and 6 worth stating plainly

**Decision 5 (Wide) widens 14 pages.** Today ~14 pages sit at `max-w-5xl`, 4 at `max-w-6xl`, and the rest are uncapped. Wide-as-default means those 14 get 128px wider. That is unambiguously right for the dense tables (`/platform/integrations/health`, `/decision-trees`, `/platform/backfill` runs) and it is what `SettingsLayout` already does. It is less obviously right for the narrow ones — `/farms` has 5 columns and `/settings/users` has 4, and at 1152px they will read as a lot of whitespace with a table floating in it.

I am implementing your decision as stated: `<Page>` defaults to `wide`, every page gets it. `width="standard"` stays available in the API. **Flagging rather than deciding:** after PR DS-2 lands you will be able to see `/platform/tenants` at wide in the real app — if the narrow tables look thin there, tell me and I'll set those three or four pages to `standard`. One-line change per page, no rework.

**Decision 6 (Light only) removes work.** The CSS-variable migration of `ap.*` drops out of scope entirely. `tailwind.config.ts` keeps its literal hex values, and phase 5 shrinks to the type-scale and surface tokens. If dark mode is ever revisited, that migration comes back as its own piece of work — noted and accepted.

---

## 1. Phase 0 — the primitives

New files under `frontend/src/components/`. No page is touched in this phase, so it is additive and cannot regress anything.

### 1.1 `<Page>` — the frame

```tsx
type PageWidth = "wide" | "standard" | "full" | "bleed";

interface PageProps {
  width?: PageWidth;          // default "wide"
  children: ReactNode;
  className?: string;
}
```

| width | class | for |
|---|---|---|
| `wide` *(default)* | `mx-auto w-full max-w-6xl` | index, detail, settings, dashboards |
| `standard` | `mx-auto w-full max-w-5xl` | escape hatch for sparse tables |
| `full` | `w-full` | board, canvases |
| `bleed` | `w-full` + suppresses shell padding | map surfaces |

Always applies `flex flex-col gap-4`. **Never applies its own `px-*`/`py-*`** — `AppShell` owns that. `SettingsLayout` drops its `px-4 py-6` in the same PR, which is what fixes the triple-pad.

### 1.2 `<Toolbar>` + `<FilterPopover>` — decision 2

```tsx
interface ToolbarProps {
  search?: { value: string; onChange: (v: string) => void; placeholder: string };
  chips?: ReactNode;            // inline, for the one high-traffic axis
  filters?: FilterAxis[];       // everything else → popover
  activeFilters?: AppliedFilter[];  // renders the removable chip row
  resultCount?: { shown: number; total: number };
  right?: ReactNode;
  onClearAll?: () => void;
}

interface FilterAxis { key: string; label: string; options: { value: string; label: string }[]; multi?: boolean }
interface AppliedFilter { key: string; value: string; label: string; onRemove: () => void }
```

The applied-filter chip row doubles as the result count — every index page is missing that today. Popover: click-outside close, Escape close, focus returns to the trigger, count badge on the button.

### 1.3 `<DataTable>` + `<RowList>` — decisions 1 and 3

```tsx
interface Column<T> {
  key: string;
  header: string;
  align?: "start" | "end";
  width?: string;
  cell: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Decision 1C: renders the identity cell as a <Link> AND makes the row clickable. */
  rowHref?: (row: T) => string;
  identityColumn?: string;      // defaults to columns[0].key
  onRowClick?: (row: T) => void;
}
```

Decision 1C is enforced by the component, not by each page: when `rowHref` is given, `<DataTable>` wraps the identity cell's content in a `<Link>`, adds `cursor-pointer` + hover to the `<tr>`, appends a chevron column, and navigates on row click. **In-row action buttons get `onClick={stopPropagation}` automatically** via a `<RowActions>` wrapper — this is the one real cost of 1C and it belongs in the primitive so no page can forget it.

`<RowList>` is the P2 equivalent: `leadingRail`, `title`, `subtitle`, `meta`, `actions` slots. It collapses `AlertsPage` and `RecommendationsPage`, which are currently near-duplicate 200-line files.

### 1.4 `<AsyncBoundary>` — my call (decision 7)

The shape question is: does it take a react-query result, or something neutral? **Neutral**, via a discriminated union plus an adapter.

```tsx
type AsyncState<T> =
  | { status: "loading" }
  | { status: "error"; error: unknown; retry?: () => void }
  | { status: "success"; data: T };

interface AsyncBoundaryProps<T> {
  state: AsyncState<T>;
  /** Decision 3B: "rows" keeps the table chrome mounted; "block" replaces it. */
  skeleton: "rows" | "block" | ReactNode;
  skeletonRows?: number;              // default 3
  isEmpty?: (data: T) => boolean;     // default: array length 0
  /** True when a filter or search is narrowing the result — picks noResults over empty. */
  filtered?: boolean;
  empty: ReactNode;                   // "nothing exists yet" + a CTA
  noResults?: ReactNode;              // "nothing matches" + Clear filters
  children: (data: T) => ReactNode;
}

// Adapters
function queryState<T>(q: UseQueryResult<T>): AsyncState<T>;
function useAsyncData<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T>;
```

Three reasons for neutral-plus-adapter over taking `UseQueryResult` directly:

1. **It unblocks phase 2.** A page can adopt the layout templates while still on `useEffect` (wrap with `useAsyncData`) and convert its data layer in the same PR or a later one. Taking `UseQueryResult` would make the react-query migration a hard prerequisite for all 18 pages.
2. **It is testable without a `QueryClientProvider`.** The primitive's own unit tests are then four plain cases.
3. **`filtered` cannot be derived from a query.** The empty-vs-no-results distinction — currently wrong on most pages, where a mistyped search reports that the system has no data — needs a signal only the page has.

The ladder, fixed in one place: `loading` → skeleton · `error` → `<ErrorState>` with a retry button · `success` + empty + `filtered` → `noResults` · `success` + empty → `empty` · else → `children(data)`.

`empty` is a **required** prop and `<EmptyState>` already requires an action slot — that is F-8 closed by type signature rather than by review.

### 1.5 The rest

| Component | Notes |
|---|---|
| `<Pagination>` | Extracted from `TenantListPage`. Props: `page`, `pageSize`, `total`, `onPageChange`. Renders nothing when `total <= pageSize`. |
| `<Field>` | `label`, `help`, `error`, `required`, `children`. Replaces 7 local copies. Generates `id`/`aria-describedby`/`aria-invalid` wiring. |
| `<FormFooter>` | Cancel-then-submit ordering, `busy` state, optional sticky. |
| `<LinkButton>` | `<Link>` with `<Button>`'s styling. **This is the reason `<Button>` has zero adopters** — half the "buttons" in the app are router links. |
| `<Card>` — extend | Add optional `title` and `footer` slots. Deletes the local `Card` in `TenantAdminDetailPage` and `BlockDefaultsPanel`. |
| `<StatusBanner>` | `kind: "info" \| "warn" \| "crit"`, `role="status"`. Extracted from `TenantAdminDetailPage`. |
| `<KPIRow>` | Grid wrapper over the existing `<KPICard>`; responsive 1/2/3-up. |
| `<PageHeader>` — extend | Add a `badge` slot for decision 4C's inline status pill. |

### 1.6 i18n

New shared keys under the `common` namespace, in **both** `en` and `ar`: `toolbar.search`, `toolbar.filters`, `toolbar.clearAll`, `toolbar.showing`, `state.loadFailed`, `state.retry`, `state.noResults`, `pagination.*`, `table.openRow`.

> **Gotcha:** `src/i18n/locales/*/common.json` currently begins with a UTF-8 BOM. Preserve it — rewriting these files without it has burned this repo before on ASCII-sensitive tooling. Edit in place rather than regenerating.

---

## 2. Enforcement

The repo already has exactly the right mechanism: `no-restricted-syntax` in `frontend/eslint.config.js`, currently holding the palette guard, promoted to `error` once usage hit zero. Same pattern, new selectors — appended to the existing array, not a new config block.

```js
// added to the existing no-restricted-syntax array
{ selector: "JSXOpeningElement[name.name='table']",
  message: "Use <DataTable> (or <Table> for a bespoke table) from @/components." },
{ selector: "JSXOpeningElement[name.name='h1']",
  message: "Page titles go through <PageHeader> so the type scale stays single-valued." },
{ selector: "Literal[value=/^(?:.*\\s)?btn(?:\\s|-|$)/]",
  message: ".btn is the retired legacy layer — use <Button> or <LinkButton>." },
{ selector: "Literal[value=/(?:^|\\s)card(?:\\s|$)/]",
  message: ".card is the retired legacy layer — use <Card>." },
{ selector: "Literal[value=/rounded-(?:xl|lg)\\s+border\\s+border-ap-line\\s+bg-ap-panel/]",
  message: "This is <Card>. Inlining it is how we ended up with three card styles." },
// page modules must not re-declare a shared primitive
{ selector: "FunctionDeclaration[id.name=/^(Card|Field|FieldRow|Row|Pagination|Toolbar)$/]",
  message: "Import the primitive from @/components instead of shadowing it locally." },
```

Scoping, mirroring how the palette guard is already handled:
- `src/components/**` exempt — the primitives legitimately contain the raw markup.
- `src/modules/labs/map/**` already has `no-restricted-syntax: "off"`; leave it.
- `**/*.test.tsx` exempt for the `h1`/`table` selectors.
- The last selector (shadowing) applies to `src/modules/**/pages/**` and `src/pages/**` only — `Row` is a reasonable local name inside a component file.

**Warnings in DS-2, errors in DS-8.** Landing them as errors up front would fail CI on 40 unconverted pages.

### Pattern gallery

There is no Storybook in this repo and adding one is a disproportionate amount of new tooling for this. Instead: a `/labs/patterns` route (the repo already uses `labs/` for exactly this kind of internal surface), rendering each template with live loading / error / empty / no-results / populated states. It is the thing to point at in code review, and unlike Storybook it exercises the real router, i18n, and RTL.

---

## 3. Per-page conversion map

**Effort:** S = mechanical, under an hour · M = some restructuring · L = needs its own PR and thought.
**Test:** ✎ = an existing `.test.tsx` will need updating.

### Index pages → `<IndexPage>` composition (18)

| Page | Template | Width | Effort | Test |
|---|---|---|---|---|
| `TenantListPage` | DataTable | wide | S | ✎ |
| `FarmListPage` | DataTable | wide | S | ✎ |
| `UsersConfigPage` | DataTable | wide | S | |
| `PlatformHealthPage` | DataTable | wide | S | |
| `PlatformPlanTemplatesPage` | DataTable | wide | S | |
| `PlatformAdminsPage` | DataTable | wide | M | |
| `DecisionTreeListPage` | DataTable + FilterPopover | wide | M | |
| `TenantDetailPage` | DataTable | wide | M | |
| `PlatformBackfillPage` (runs) | DataTable | wide | M | ✎ |
| `AlertsPage` | RowList | wide | M | |
| `RecommendationsPage` | RowList | wide | M | |
| `PlatformCropsPage` | RowList (nested) | wide | L | |
| `SignalsLogPage` | RowList + split | wide | L | |
| `ResourcesWorkersPage` | DataTable (editable) | wide | M | |
| `ResourcesEquipmentPage` | DataTable (editable) | wide | M | |
| `PlatformDefaultsPage` | RowList (editable) | wide | M | |
| `RulesConfigPage` | RowList + tabs | wide | L | |
| `SignalsConfigPage` | RowList + editor | wide | L | |

`AlertsPage` + `RecommendationsPage` and `ResourcesWorkersPage` + `ResourcesEquipmentPage` are the two duplicate pairs — convert each pair in one PR so the shared shape is obvious in the diff.

### Detail pages → `<DetailPage>` (5)

| Page | Panels | Tabs? (4C rule: >3) | Effort | Test |
|---|---|---|---|---|
| `TenantAdminDetailPage` | 5 | yes — keeps tabs | M | ✎ |
| `FarmDetailPage` | 4 | yes — **gains** tabs | M | ✎ |
| `BlockDetailPage` | 4 | yes — **gains** tabs | M | ✎ |
| `PlanTemplateEditorPage` | editor | no | M | |
| `PlatformHealthTenantDrillPage` | delegates | no | S | |

All five get the unified header. `TenantAdminDetailPage` loses its local `Card` and its `text-lg` title. Farm and Block detail gaining tabs is the most visible user-facing change in the whole programme — worth a look in the browser before merging.

### Form pages → `<FormPage>` (5)

`FarmEditPage` ✎, `BlockEditPage` ✎, `BlockCreatePage` ✎, `DecisionTreeCreatePage`, `TenantCreatePage` ✎ (L — multi-step). All S/M except the last. Page frame is `wide` per decision 5, with the form card itself capped at `max-w-3xl` inside it — a 1152px-wide single-column form has unreadable label/field distances. Flagging as a detail of 5, not a departure from it.

### Settings / dashboards (10)

`IntegrationsWeatherPage`, `IntegrationsImageryPage`, `IntegrationsTenantOnlyPage`, `ImageryWeatherConfigPage`, `FarmMembersPage` ✎, `SettingsIndexPage`, `SettingsPlaceholderPage`, `IntegrationsHealthPage`, `InsightsPage`, `PlatformBackfillPage` (form tabs). Mostly S — `<Page>` + `<PageHeader>` + delete local padding. `PlatformBackfillPage`'s hand-rolled `role="tablist"` becomes `<SegmentedControl>`.

### Exempt canvases (7)

`FarmConsolePage`, `MapExperiencePage`, `BoardPage`, `DecisionTreeViewerPage`, `ReportsPage`, `HomePage`, `LoginPage`. **Frame and header only** — `<Page width="full">` or `"bleed"`, `<PageHeader>`, `<Button>`. Bodies untouched. `HomePage` also drops its legacy `.card`.

### Deletions

`FarmCreatePage.tsx` + `FarmCreatePage.test.tsx` — unrouted dead code.

---

## 4. PR slicing

Each row is one PR against `origin/main`. Sequential unless marked parallel.

| PR | Contents | Gate |
|---|---|---|
| **DS-1** | All phase-0 primitives + unit tests + i18n keys + `/labs/patterns`. No page touched. | tests green; gallery renders in EN and AR |
| **DS-2** | `<Page>` adopted app-wide (frame only, no other change) + `SettingsLayout` padding fix + lint rules as **warnings**. This is the PR where the wide default becomes visible. | visual check of 6 representative pages |
| **DS-3** | Reference conversions: `TenantListPage` (index), `TenantAdminDetailPage` (detail), `FarmEditPage` (form). | the three templates proven end-to-end |
| **DS-4** | Index sweep A — the 5 mechanical DataTable pages | parallel with DS-5 |
| **DS-5** | Index sweep B — the two duplicate pairs (`Alerts`/`Recommendations`, `Workers`/`Equipment`) via `<RowList>` | parallel with DS-4 |
| **DS-6** | Index sweep C — the 4 L-effort pages (`PlatformCrops`, `SignalsLog`, `RulesConfig`, `SignalsConfig`) | own PR each if diffs get large |
| **DS-7** | Detail + form pages; delete local `Card`/`Field`; single wayfinding idiom | browser check on Farm/Block detail gaining tabs |
| **DS-8** | Retire `.btn`/`.card`/`.input`/`.label` from `index.css`; delete `brand-*` and `sand-*` from `tailwind.config.ts`; lint warnings → **errors**; delete `FarmCreatePage`. | `pnpm lint` clean with rules at error |
| **DS-9** | Type-scale + surface tokens; exempt canvases adopt frame + header. | final visual pass |

**DS-8 is the one that must not be skipped.** Every prior cleanup in this repo stalled before its equivalent step, which is why three generations of button styling coexist today. If the sweep runs out of steam, DS-8 is still worth landing on whatever has converted — the lint rules are what stop the drift re-accumulating.

---

## 5. Testing

**38 test files exist; 14 touch pages in scope.** Most assert on roles and text (`getByRole`, `getByText`) rather than class names, so breakage should be modest — but `FarmListPage.test.tsx` and friends were written against the current DOM shape and will need updating where the wrapper nesting changes.

- **Unit:** every new primitive gets a test file. `AsyncBoundary` gets five (loading, error+retry, empty, no-results, success) — it is the highest-leverage component in the set.
- **Existing page tests:** update in the same PR as the page. Do not convert a page and defer its test.
- **e2e:** `e2e/specs/` has `smoke.spec.ts`, `alerts.spec.ts`, `grid.spec.ts`. `smoke.spec.ts` is the real regression net for DS-2 (the frame change). Extend it with an assertion per template — one index, one detail, one form — before DS-3.
- **RTL:** the gallery must be checked with `dir="rtl"`. `<Toolbar>`'s popover and `<DataTable>`'s chevron are the two new things with a direction, and the chevron must mirror.
- **a11y:** `eslint-plugin-jsx-a11y` is already on and will catch the row-click pattern if `<DataTable>` gets it wrong — which is a feature, since decision 1C exists precisely to keep the row keyboard-reachable.

Local verification, from prior sessions in this repo:
- Frontend has no `--reload` coupling, but if a new component won't render, **kill port 5173** — stale Vite is the usual cause.
- Playwright MCP OIDC automation is broken (PKCE double-mount); use a Keycloak direct-grant token.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| **DS-2 changes every page's width at once.** | `<Page>` ships in DS-1 unused. DS-2 adopts it with each page's *current* width preserved except where wide is intended; anything questionable gets `standard` and is revisited. Rollback is one prop. |
| **Farm/Block detail gaining tabs is a real UX change**, not a restyle. | Browser check before merging DS-7. If tabs feel wrong there, the 4C rule becomes ">4 panels" and both stay stacked — the header unification is the part that matters. |
| **Concurrent worktrees.** This repo runs ~16 and other sessions flip the shared checkout mid-task. | Cut every DS branch from `origin/main` explicitly. Keep PRs module-scoped so two sweeps don't collide. Rebase before each push. |
| **Merge CI cancellation.** Bumping overlay tags immediately after a squash-merge cancels the merge CI and lands `ImagePullBackOff`. | This is frontend-only, but DS PRs will trigger deploys. Wait for the containers job before any tag bump. |
| **Locale file encoding.** `common.json` carries a BOM. | Edit in place; never regenerate. Check `git diff` for a whole-file rewrite before committing. |
| **Sweep fatigue.** 40 pages is a lot of mechanical work. | DS-4/5/6 are independent and parallelizable. The lint rules (DS-8) mean an incomplete sweep still converges rather than decaying. |

---

## 7. Definition of done

- Every routed page renders inside `<Page>`; no page declares its own `mx-auto max-w-*` or `p-*`.
- `pnpm lint` passes with the design-system rules at `error`.
- Zero raw `<table>`, zero raw `<h1>`, zero `.btn`/`.card` outside `src/components/`.
- `<Button>` / `<LinkButton>` importer count > 0 and inline `bg-ap-primary px-` count == 0.
- One wayfinding idiom (breadcrumb) on all detail and form pages.
- `/labs/patterns` renders all templates in all states, in EN and AR.
- `brand-*` and `sand-*` gone from `tailwind.config.ts`.
- `pnpm test` and `pnpm test:e2e` green.

---

## 8. Before I start

Nothing blocks DS-1 — it is purely additive and none of the open questions touch it. If you want to green-light incrementally, **DS-1 is safe to start on its own** and the two open questions in §0 only become live at DS-3.

What I'd want confirmed before DS-3:
1. The two §0 assumptions (server-side filtering; convert `useEffect` pages page-by-page) — or a veto on either.
2. Whether Farm/Block detail *should* gain tabs, or whether you'd rather see that in the browser first and decide then.
