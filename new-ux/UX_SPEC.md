# AgriPulse — UX Specification

**Version:** 1.0 · MVP scope
**Visual reference:** `agripulse_app.html` (open in a browser; every component below is implemented there)
**Data model:** `agripulse_core_erd.html`

---

## 1. Product overview

AgriPulse is a multi-tenant SaaS for farm operators (initial vertical: mango orchards in Egypt). It pulls satellite imagery (Sentinel-2 default, PlanetScope upgrade), computes vegetation indices (NDVI, NDWI, GCI), and surfaces actionable insights — alerts, irrigation schedules, vegetation plans — over a familiar IA: **Insights** to triage, **Plan** to orchestrate the season.

**Primary jobs-to-be-done:**

1. *"What needs my attention right now across all my land units?"* → Insights view
2. *"What did the satellite say this week, and is it consistent with the ground?"* → Trend chart + alerts feed
3. *"What's the season look like, and are there scheduling conflicts?"* → Plan view
4. *"Schedule a new activity for one or more land units."* → New activity flow

---

## 2. Personas

| Persona | Goals | Where they live in the app |
|---|---|---|
| **Farm Manager (Mohamed)** | Daily triage, decide on irrigation/spray, send crew | Insights → Alerts → drill into Plan |
| **Agronomist (Layla)** | Validate the engine's recommendations, tune rules per variety | Insights → Trend chart + Land unit table → Rules & thresholds |
| **Owner / Org Admin (Hassan)** | Multi-farm visibility, season-level planning, ROI | Insights overview, multi-farm switcher, Reports |
| **Field Tech (Ahmed)** | Receive a task, confirm completion, log issues | Mobile / phone view of a single activity (post-MVP — leave hooks) |

**Roles in code:** `org_role` (admin/viewer) + `USER_FARM_ROLE.role` (manager/viewer). Org admin → all farms implicitly. Farm manager → only assigned farms. Viewer → read-only.

---

## 3. Information architecture

```
AgriPulse (org-scoped)
├─ [farm switcher in top bar — picks active FARM]
│
├─ Insights        ← home / default landing
│   ├─ KPI summary
│   ├─ Vegetation index trend
│   ├─ Land unit health table
│   ├─ Live alerts feed
│   ├─ Mini farm map
│   └─ This week's activities
│
├─ Land units      ← MVP stub (links to map view, deferred)
├─ Alerts          ← full alerts list (MVP: link only)
├─ Plan            ← the Gantt season planner
│   ├─ Filter chips (activity types, drafts)
│   ├─ Stage legend
│   ├─ Land units sidebar (lane selector)
│   ├─ Timeline (lanes × months)
│   │   ├─ Activity bars
│   │   ├─ Conflict pins
│   │   └─ Growth-stage bands
│   └─ Activity detail panel
│
├─ Reports         ← MVP stub
│
└─ Configuration   ← MVP stubs
    ├─ Rules & thresholds
    ├─ Imagery & weather
    └─ Users & roles
```

**Routing:**
```
/                            → /insights
/insights
/plan
/plan?lane=B1                → opens Plan with lane B1 highlighted
/plan?activity=b1-spray-...  → opens Plan with that activity selected
/land-units                  → MVP stub
/alerts                      → MVP stub
/reports                     → MVP stub
/config/rules                → MVP stub
/config/imagery              → MVP stub
/config/users                → MVP stub
```

URL is the source of truth for `lane` and `activity` selection. Deep-links from Insights ("Resolve" button on an alert) navigate to `/plan?activity=...&lane=...`.

---

## 4. Layout shell

The shell is shared across all routes.

```
┌────────────────────────────────────────────────────────────────────┐
│ Top bar (sticky, 60px)                                             │
│  • Brand · Crumbs (org > farm) · [view-specific toolbar] · Search  │
│  • Notifications · User avatar                                     │
├────────────┬───────────────────────────────────────────────────────┤
│            │                                                       │
│ Side nav   │                                                       │
│ (220px)    │  Active view (Insights | Plan | …)                    │
│  sticky    │                                                       │
│            │                                                       │
│            │                                                       │
└────────────┴───────────────────────────────────────────────────────┘
```

### 4.1 Top bar (`<TopBar>`)

| Region | Element | Behavior |
|---|---|---|
| Left | Brand mark + name | Click → `/insights` |
| | Breadcrumbs `Org › Farm` | Farm name is a button → opens **farm switcher** popover |
| Center (variable) | View-specific toolbar | Insights: date-range segment (Today / This week / Season / Custom). Plan: zoom segment (Day / Week / Month / Season) + Today button + `+ New activity` button |
| Right | Search icon-button | Global search palette (post-MVP — render disabled or hidden if not built) |
| | Notification bell | Unread count badge if any. Click → drawer with last 20 alerts |
| | Avatar | Click → menu (Profile · Org settings · Sign out) |

Sticky at `top:0`, `z-index: 10`. Must remain on top of modal backdrops? **No** — modals overlay everything (z-index 50).

### 4.2 Side nav (`<SideNav>`)

- Fixed 220px, sticky under top bar, scrollable independently.
- Two groups: **Workspace** (Insights, Land units, Alerts, Plan, Reports) and **Configuration** (Rules & thresholds, Imagery & weather, Users & roles).
- Active item: `--primary-soft` background, `--primary` text. Inactive hover: subtle warm-gray bg.
- Counts on the right: total count chip on Land units (14), severity-colored count on Alerts (3 critical → `--crit-soft` bg, `--crit` text).
- Click switches route. Browser back/forward must work.

---

## 5. Insights view

Route: `/insights`. The default landing page. Layout: 2-column inside the main area — `2fr | 1fr`.

### 5.1 Greeting + actions strip

```
Good morning, {firstName}.
{farmName} · {totalAreaFeddan} feddan · {dominantCropVariety} · Sentinel-2 imagery refreshed {relativeTime}
                                                          [Export] [+ New plan]
```

- Greeting reflects local time of the farm's timezone, not the user's.
- "New plan" jumps straight to `/plan` and opens the New activity modal pre-empty.
- "Export" opens a popover (CSV / PDF / link) — MVP can stub the menu and toast "Coming soon" on selection.

### 5.2 KPI cards (4-col grid)

Each card: title, value, mini sparkline, delta badge.

| Card | Source | Notes |
|---|---|---|
| **Healthy units** | Count of land units with NDVI deviation ≥ -5% / total units | Sparkline = trend of healthy count over last 8 weeks |
| **Active alerts** | Count of `ALERT` rows with `status='open'` | Color value red if > 0; sparkline = alert volume trend |
| **Avg NDVI** | Latest mean across units, weighted by area | Show deviation from 5-year baseline as delta |
| **Irrigation due** | Count of land units with `IRRIGATION_SCHEDULE.status='pending'` in next 7d | Total mm needed in hint. **Click → `/plan`** (entire card is clickable; cursor:pointer) |

Skeleton state: gray bars for value + sparkline.
Empty state (new farm, no data yet): "No imagery yet — first capture in {hours}h."
Error state: small inline retry link, value shows "—".

### 5.3 Vegetation index trend (`<TrendChart>`)

- Width: full width of left column. Height: 220px.
- Series: NDVI (solid), NDWI (dashed). Toggle via segmented control above chart (NDVI / NDWI / GCI / Compare).
- Background ribbon: 5-year baseline mean ± 1 SD.
- Y axis: 0.55–0.85 default (auto-scale to data).
- X axis: last 90 days, ticks per month.
- "Today" vertical guideline at right edge with circle marker on latest value, label `refresh · {date}`.
- Hover anywhere → tooltip with date + all visible series values.
- Empty state: "Not enough data yet — first 30 days of imagery still ingesting."

### 5.4 Land unit health table

Sortable table, default sort = `baseline_deviation ASC` (worst first).

Columns:
| Column | Content |
|---|---|
| Land unit | Bold name + sub-line `variety · area · irrigation_method` |
| Stage | Current `current_growth_stage` (humanized) |
| NDVI vs baseline | Pill with %, plus a thin progress bar (color-coded by health band) |
| Last irrigation | Relative date + mm |
| (action) | "Plan" button → `/plan?lane={id}` |

- Filter strip above: All / Blocks / Pivots (segments).
- Row hover: warm bg, action button revealed.
- Pagination: 10/page after MVP. MVP can show all units in one scrollable card.

### 5.5 Live alerts feed (right column)

Card title: "Live alerts · sorted by severity". Footer link "View all →" → `/alerts`.

Each item:
- Severity bar (4px wide, color-coded: crit/warn/info)
- Severity icon (32px circle, matching color)
- Title (`ALERT.diagnosis` short form)
- Description (`ALERT.prescription` summary, max 2 lines, truncate with ellipsis)
- Meta row: rule id · relative time · status hint
- Action button: contextual verb based on alert type
  - `crit` water-stress → **Resolve** → `/plan?activity={prescriptionId}` (auto-opens prescription)
  - `warn` emitter → **Inspect** → `/plan?lane={id}`
  - `warn` GDD-ahead → **Adjust** → `/plan?lane={id}`
  - `info` system → **Dismiss** (local state only)

If 0 alerts: friendly empty state "All clear — nothing needs your attention." (illustration optional)

### 5.6 Mini farm map

Card title: "Farm map" + link "Open full map →" (MVP stub).

- Static SVG of farm boundary with land-unit shapes colored by health band.
- Aspect ratio fixed (16:8 or similar), 200px tall.
- Click any shape: navigate to `/plan?lane={id}` (consistent with table).
- Fallback: gridded green background with text "Map preview unavailable for this farm".

### 5.7 This week's activities

Card title + link "Plan →".

- Up to 3–5 upcoming activities for the active farm in the next 7 days.
- Each row: date pill (day number + 3-letter day) · title · scope · type tag.
- Click row: navigate to `/plan?activity={id}`.

---

## 6. Plan view

Route: `/plan`. The dedicated planner. Layout: top toolbar + 3-column grid (lane sidebar | timeline | detail).

### 6.1 Plan toolbar

Sits below the global top bar. Contains:
- "Filter" label
- 5 type filter chips (Planting · Fertilizing · Spraying · Pruning · Harvesting), all active by default. Click toggles activity-bar visibility on the timeline.
- "Show drafts only" toggle chip — hides non-draft bars.
- **Stage legend** (vertical separator + 5 swatches: Flower / Fruit set / Fruit dev / Ripen / Harvest). Read-only; explains the band under each lane.
- Right side: stat mini-cards (`32 activities · 11 completed · 4 at risk · 17 upcoming`). Stats reflect *currently visible* (post-filter) bars.

### 6.2 Land units sidebar (`<LaneSidebar>`)

- Fixed 280px, scrollable.
- Grouped by farm section (header label + list). Group labels come from a `farm_section` field if present; otherwise from a stable ordering rule (north/south/east/west by centroid).
- Each row: type icon (square for blocks, circle for pivots) · name + sub-line (variety · area) · stage chip on the right.
- Click row: highlights the lane in the timeline, smooth-scrolls it into view, sets URL `?lane={id}`.

### 6.3 Timeline (`<Timeline>`)

The center pane. Horizontally scrollable (min-width 1200px).

**Header rows (sticky-top):**
- Month row: label cell ("Land unit") + 8 month columns.
- Week row: 8 cells with week ranges (e.g., "W18–22").

**Lanes:** one per land unit, in the same order as the sidebar. Each lane:

```
┌────────────────────┬──────────────────────────────────────────────┐
│ lhead (sticky-left)│ stripes (relative)                           │
│ Block B1           │  ┌─bar───┐ ┌─bar──┐                          │
│ Fruit · NDVI -18%⚠ │  └───────┘ └──────┘    ⋯                     │
│                    │  ▔▔▔▔▔▔▔ stage band ▔▔▔▔▔▔▔▔▔                │
└────────────────────┴──────────────────────────────────────────────┘
```

**Lane head** (`.lhead`, 200px sticky-left):
- Name (bold)
- Sub-line: stage · NDVI deviation. Tint sub-line in `--crit` if deviation < -15%, `--warn` if < -5%.
- Click: same as sidebar row (selects lane).

**Stripes** (60px tall):
- Subtle vertical grid (1 line per week-cell) using a repeating-linear-gradient.
- Activity bars (see 6.4)
- Conflict overlay SVG + pin (see 6.5)
- Growth-stage band at bottom (see 6.6)

**Today line:** vertical 2px line at `today_pct = (daysSinceMar1 / totalSeasonDays)`. Top label "Today · {date}" badge in `--accent`. Spans the entire timeline (z-index above lanes, below modal).

**Lane selection state:** `lane.selected` adds a soft warm tint to the entire row (see mockup `.lane.selected`). Persists across activity selections.

### 6.4 Activity bar (`<ActivityBar>`)

| Attribute | Source field | UI |
|---|---|---|
| Lane | `PLAN_ACTIVITY.land_unit_id` | which row |
| Type | `PLAN_ACTIVITY.activity_type` | color via type token (plant/fert/spray/prune/harv) |
| Time | `PLAN_ACTIVITY.scheduled_date` + `duration` | left/width as % of season |
| Status | `PLAN_ACTIVITY.status` | `draft` → 55% opacity + dashed inset border. `completed` → solid + checkmark glyph (post-MVP). `scheduled`/default → solid |
| Label | `PLAN_ACTIVITY.product_name` (or activity_type if none) | truncate with ellipsis; full label in tooltip |
| Suffix | optional `· {note}` | smaller, fainter |

**Sizing:**
- `left% = ((scheduled_date - season_start) / season_length) * 100`
- `width% = (duration_days / season_length) * 100` — clamp to a minimum visible width (~3%).

**States:**
- Hover: lift 1px, deeper shadow.
- Selected (`is-selected`): 2px outline in `--ink`, +2px outline-offset.
- Hidden by filter (`hidden-type`): `display:none`.

**Click:** select the activity → highlight bar, select its lane, populate the detail panel, set URL `?activity={id}&lane={id}`.

### 6.5 Conflict overlay & pin (`<ConflictPin>`)

Conflicts are pairs of activities on the **same lane** within an overlapping time window that violate a known rule. MVP rules:

| Rule id | Trigger | Message |
|---|---|---|
| `CFL-SPRAY-WASH` | `spray` and `irrigation/fert pulse` within 3 days | "Run irrigation AFTER spray dries (~14:00) to avoid washing product." |
| `CFL-PHI` | `spray` within `pre_harvest_interval_days` of a `harvest` window | "PHI conflict: product cannot be applied less than {n} days before harvest." |
| `CFL-PRUNE-FLOWER` | `prune` during `flowering` stage segment | "Pruning during flowering reduces yield — confirm intent." |

**Visual:**
- Dashed amber arc (SVG path) connecting the two bars' top edges, peaking above them.
- A 20px circle pin in `--warn` at the arc's peak, with a "!" glyph and a `title` tooltip showing the rule message.
- `position: absolute` inside the lane stripes; `pointer-events: auto` on pin only (arc is decorative).

**On click of pin (post-MVP):** scroll/highlight both conflicting bars and open a side popover. MVP: hover tooltip is enough.

Conflict detection runs **client-side** initially (`detectConflicts(activities, rules) → ConflictEdge[]`).

### 6.6 Growth-stage band (`<StageBand>`)

A 5px-tall horizontal strip at the bottom of each lane's stripes div. Made of segments whose widths are percentages of the season:

| Segment | Color | Default width (Keitt mango) | Default width (Tommy Atkins) |
|---|---|---|---|
| Flower | `#f0c75b` | 15% | 10% |
| Fruit set | `#b8d4a3` | 10% | 10% |
| Fruit dev | `#84b078` | 40% | 30% |
| Ripen | `#d6a546` | 15% | 15% |
| Harvest | `#c46b50` | 15% | 15% |
| Post-harvest | `#cfd1ca` | 5% | 20% |

**Source:** `CROP_VARIETY.phenology_model` defines per-variety segment widths and `GROWTH_STAGE_LOG` provides actual transitions to override defaults.

The segment matching the unit's **current** stage gets an inner outline (`box-shadow: inset 0 0 0 2px rgba(0,0,0,.35)`) to mark "you are here".

Each segment carries a `title` tooltip with the stage name + month range.

### 6.7 Activity detail panel (`<ActivityDetail>`)

Right column, 340px, scrollable. Three states:

**Empty state** (no activity selected):
> "Select an activity bar to see details, conflicts & actions."

**Activity selected** — sections (top to bottom):

1. **Header**
   - Type badge (color-coded) + status badge (Scheduled / Completed / Draft / Skipped)
   - Title: `{product_name} — {land_unit_name}` (or `{activity_type} — …` if no product)
   - Sub: human date+time + crew

2. **Activity** (key/value list)
   - Type · Product · Dosage · Total (per-area calc) · Re-entry · PHI

3. **Why this is scheduled**
   - One short paragraph explaining the rule trigger (`{rule_id}: {short reason}`) or "Manually scheduled by user"

4. **Pre-flight checklist** (if applicable)
   - Click-to-toggle items. State persists locally per activity.
   - Examples per type:
     - Spray: wind < 15 km/h confirmed · no rain forecast 6h · equipment calibrated · PPE check · notify neighboring units
     - Irrigation: pump capacity · emitter inspection cleared
     - Pruning: equipment sanitised · disposal pile location

5. **Conflicts & suggestions** (only if conflicts present)
   - Inline `--warn` callout with the conflict message + suggested mitigation

6. **Action buttons** (sticky at bottom of panel)
   - Primary: "Mark complete" (or "View log" if already completed)
   - Secondary: "Reschedule" · "Skip"

### 6.8 New activity flow (`<NewActivityModal>`)

Modal overlay (`z-index: 50`), centered, 600px wide. 4 steps with a stepper at the top.

**Step 1 — Type**
- 5 cards (Planting · Fertilizing · Spraying · Pruning · Harvesting), grid 5×1.
- Each card: color swatch · name · 1-line description.
- Single-select. Validation: must pick one to continue.

**Step 2 — Land units**
- Multi-select chips, grouped by farm section.
- Empty selection blocks "Next" with shake/red-flash on the button.

**Step 3 — Schedule**
- Inputs (2-column grid): Date · Start time · Duration (select) · Recurrence (select).
- Default date: today + 2 days. Default time: 06:00. Default duration: 4h.
- **Live conflict preview** below the inputs:
  - Green callout if no conflicts: "✓ No scheduling conflicts detected for the selected window."
  - Amber callout listing each conflict with bolded land unit name. Conflict detection runs the same `detectConflicts` function used on the timeline, against a synthetic activity built from current state.

**Step 4 — Details & review**
- Inputs: Product/description · Dosage/rate · Crew · Notes.
- **Summary box** (read-only) showing what will be created.
- Final conflict warning if conflicts remain (does not block submission — user can override).

**Stepper:**
- 4 pills with numbers, separator bars between them.
- Past steps marked `done` (green check), current marked `active` (dark filled), future faded.

**Footer:**
- Left: "Cancel" (closes without saving)
- Right: "Back" (disabled on step 1) · "Next" (becomes "Create activity" on step 4)

**On Create:**
- For each selected land unit, post one `PLAN_ACTIVITY` row.
- Insert the resulting bars into the corresponding lanes (optimistic UI is fine — reconcile on success).
- Close modal, auto-select the first newly-created activity, scroll its lane into view.
- If any post fails, keep modal open with an error banner and the failed entries flagged.

**Keyboard:**
- `Esc` closes modal (with confirm if any field touched).
- `Enter` advances on steps 1 & 3 if valid.
- Arrow keys navigate type cards in step 1.

---

## 7. Component inventory

The receiving session should build these as composable, typed components.

### Shell

- `<TopBar />`
- `<SideNav />` with `<SideNavItem />`
- `<FarmSwitcher />` (popover)
- `<UserMenu />`

### Primitives

- `<Button variant="primary|default|ghost|icon" />`
- `<IconButton />`
- `<Pill kind="ok|warn|crit|neutral" />`
- `<Badge kind="...|type-spray|type-fert|..." />`
- `<SegmentedControl items={...} value={...} onChange={...} />`
- `<FilterChip active={...} onToggle={...} />`
- `<Card title? hint? actions? children />`
- `<Sparkline points={[]} stroke="..." />` — viewBox-based SVG, accepts color
- `<KVList items={[[k,v],...]} />`
- `<Avatar initials={...} />`
- `<Tooltip content={...} children />` — wraps any element

### Insights-specific

- `<KPICard title value sparkline delta clickable? onClick? />`
- `<TrendChart series=[{name,points,style}] baseline? today? />`
- `<LandUnitTable rows filter sort onPlanClick />`
- `<AlertsFeed items onAction />` with `<AlertRow />`
- `<MiniFarmMap landUnits onUnitClick />`
- `<ActivityListMini items onClick />`

### Plan-specific

- `<PlanToolbar filters statsCounts onFilterChange />`
- `<StageLegend />`
- `<LaneSidebar groups onSelect selectedLane />`
- `<Timeline lanes activities conflicts seasonStart seasonEnd today />`
  - `<TimelineHeader />` (months + weeks)
  - `<TimelineToday position={pct} label />`
  - `<Lane laneData activities conflicts onSelectActivity />`
    - `<LaneHead />`
    - `<ActivityBar />`
    - `<ConflictOverlay edges />` with `<ConflictPin />`
    - `<StageBand segments currentStage />`
- `<ActivityDetail activity onComplete onReschedule onSkip />`
- `<NewActivityModal open onClose onSubmit existingActivities />` with `<TypeCard />`, `<LandUnitChip />`, `<ConflictPreview />`, `<SummaryBox />`, `<ModalStepper />`

---

## 8. Selection & state model

Three pieces of selection state, ordered by scope:

```
URL  ← single source of truth
  ├─ route                e.g. /plan
  ├─ ?lane=B1             selected lane
  └─ ?activity=b1-spray-…  selected activity (implies lane)

Local UI state
  ├─ filter chips active set
  ├─ "drafts only" toggle
  ├─ KPI segment / chart series toggles
  ├─ checklist item toggles per activity (persisted to local storage with TTL)
  └─ modal open + draft state

Server state (typed data layer)
  ├─ currentUser, currentOrg, currentFarm
  ├─ landUnits[]
  ├─ activities[]    (current vegetation plan)
  ├─ alerts[]        (open + recently resolved)
  ├─ indexTimeseries (last 90d for trend chart)
  └─ growthStageLogs (for current stage detection)
```

**Rules:**
- Changing `?lane` or `?activity` is debounced into the URL (replace, not push, on rapid clicks).
- Reloading the page on any URL must restore the exact same view.
- Selecting an activity sets both `?activity=` AND `?lane=` (lane is implied).

---

## 9. Design tokens

Use CSS custom properties (or Tailwind's `theme.extend`) — values mirror the mockup.

```css
:root {
  /* Surface */
  --bg:        #f7f6f1;
  --panel:    #ffffff;
  --line:     #e8e5db;

  /* Ink */
  --ink:      #1f2420;
  --muted:    #6c7268;

  /* Brand */
  --primary:       #356b30;
  --primary-soft:  #dceadb;

  /* Semantic */
  --good:     #4f8e4a;
  --accent:   #1f6f9a;   /* informational, "today" line */
  --warn:     #c98a18;
  --warn-soft:#f7e7c2;
  --crit:     #b24430;
  --crit-soft:#f3d2c9;

  /* Activity types */
  --plant:    #4f8e4a;
  --fert:     #1f6f9a;
  --spray:    #8d4ab0;
  --prune:    #c98a18;
  --harv:     #b24430;

  /* Stages */
  --stage-flow:   #f0c75b;
  --stage-frset:  #b8d4a3;
  --stage-frdev:  #84b078;
  --stage-ripen:  #d6a546;
  --stage-harv:   #c46b50;
  --stage-post:   #cfd1ca;

  /* Effects */
  --shadow:  0 1px 2px rgba(0,0,0,.04), 0 6px 18px rgba(20,40,15,.06);
  --shadow-lg: 0 30px 60px rgba(0,0,0,.25);
}
```

**Spacing scale:** 4 / 8 / 12 / 14 / 16 / 18 / 20 / 22 / 24 / 32 / 40 px. Stick to these.

**Radii:** 4 (chip swatch) · 8 (buttons, inputs) · 10 (cards, mini-cards) · 12 (mini-map) · 14 (large cards, modal) · 999 (pills, chips).

**Typography:**
- Family: `-apple-system, "Segoe UI", Inter, Roboto, system-ui, sans-serif`
- Sizes: 11 (legend/uppercase), 12 (hint/meta), 13 (body), 14 (default), 16 (h3 modal/panel), 18 (h2), 22 (h1 greeting), 28 (KPI value).
- Weights: 400 / 500 / 600 / 700.
- Letter-spacing on uppercase eyebrow labels: `0.04em–0.06em`.

**Iconography:** stroke-based, 18–20px, `stroke-width: 2`. Embed as inline SVG — no icon font.

---

## 10. Interaction patterns

### Selection
- **Lane selection** is a UI-only state — no server effect. Visual: warm tint on the lane row + sidebar item.
- **Activity selection** is mutually exclusive — exactly one at a time. Visual: 2px outline-offset around the bar.
- Clicking an empty area of the timeline does **not** clear selection (keep it sticky to avoid accidental loss). Press `Esc` to clear.

### Deep links
- All entry points to `/plan` accept either or both `?lane=` and `?activity=`. The Plan view resolves them on mount and on back/forward navigation.
- "Resolve" / "Inspect" / "Adjust" buttons in the alerts feed compute the correct deep link based on alert metadata (`prescription_id` if present, else just `lane`).

### Filter chips
- Chips are independent toggles. State is **OR within type, AND across constraint groups**. So:
  - 5 type chips active = show all 5 types (OR)
  - "Drafts only" = AND constraint across whatever types are active
- Changing filters never hides selected activity — if the selected one no longer matches, keep it visible with a subtle "filtered" badge (post-MVP) or just leave it.

### Conflict pin
- Hover anywhere on the pin shows the rule message tooltip.
- Click (post-MVP): scrolls/highlights both conflicting bars and opens a side popover with the rule details.

### Growth-stage band
- Hover any segment → tooltip with stage name + month range.
- Current segment is visually marked. No click action in MVP.

### Empty / loading / error states (defaults)
- **Loading**: skeleton cards (shimmering bars in the same shape as the final content). Avoid spinners except for the trend chart which can show a centered subtle spinner.
- **Empty**: short, non-apologetic message + optional illustration. Examples in §5.
- **Error**: small inline retry link, never a full-page error in the dashboard. Toast for transient errors.

---

## 11. Responsive

MVP target: desktop ≥ 1280px wide.

| Breakpoint | Behavior |
|---|---|
| `≥ 1440` | 4-column KPIs, 2:1 main grid, 280px lane sidebar |
| `≥ 1280` | Same as above, mini map shrinks to 180px tall |
| `≥ 1024` | 4-col KPIs become 2×2, alerts feed moves below main column |
| `< 1024` | 1-column stack. Plan view: lane sidebar collapses to a top dropdown ("Choose land unit"); detail panel becomes a bottom drawer when an activity is selected. |
| `< 640` | Phone view — Insights only. Plan view shows a "Use desktop for season planning" stub and a read-only list of upcoming activities. |

---

## 12. Internationalization

Mango orchards are in Egypt, so Arabic + RTL is a near-term need. Even though MVP is English-only, leave hooks:

- All copy in a single locale file. No string concatenation in JSX (use ICU MessageFormat or t-tagged templates).
- Use logical CSS properties (`margin-inline-start`, `padding-inline-end`) instead of `left/right` where possible.
- Time/date formatting via the user's `language_pref` from `USER` table (fall back to org default).
- Number formatting: `0.71` NDVI uses `Intl.NumberFormat`. Area uses feddan in Egypt, hectare in MENA-broader — surface as `area_unit` org setting.
- Direction-aware icons (chevrons in stepper) — use `inline-start`/`inline-end` aware components.

---

## 13. Accessibility

- All interactive elements reachable via Tab. Visible focus ring (use `:focus-visible`, default browser ring is acceptable but ensure contrast on warm backgrounds).
- Color is never the only signal:
  - Health pills include a sign (`+6%` / `-18%`)
  - Alert severity also has an icon glyph
  - Activity types include a label, not just a color
- Charts: provide a tabular alternative (`<table>` rendered visually hidden) for screen readers.
- Modal: `role="dialog"`, focus trap, return focus on close, `aria-labelledby`.
- Color contrast: all text on warm bg passes WCAG AA (verified for `--ink` on `--bg` and `--muted` on `--panel`).
- Tooltip content (e.g., conflict message, stage segment) must also be reachable via keyboard — pattern: focusable element + `aria-describedby` to a live region or the tooltip body.

---

## 14. Out of scope (MVP)

- Map view (Field Ops design) — defer.
- Reports view — link only.
- Configuration screens (rules, imagery, users) — link only.
- Mobile-optimized field tech view.
- Multi-farm dashboard (org-level KPIs across all farms). The current design is single-farm.
- Real-time WebSocket alerts. MVP can poll every 60s.
- Bulk activity actions (multi-select bars).
- Activity drag-to-reschedule on the timeline. Use the detail panel's "Reschedule" button.
- Comments / @mentions on activities.

---

## 15. Open questions for the build session

These are decisions the implementer should raise with the product owner if not already resolved:

1. **Time zone handling.** All `scheduled_date` values — are they stored in UTC or in the farm's local timezone? UI must be consistent (we're showing labels like "Wed, May 7 · 06:00").
2. **Activity duration model.** The data model has `scheduled_date` only — is `duration` a separate field, or is it implied by `activity_type` + a default? UI assumes a `duration` exists.
3. **Conflict rules location.** Start client-side (per §6.5) — confirm with backend team whether to migrate to a server-side decision engine before scale.
4. **Imagery cadence display.** Live pill on top bar shows "Sentinel-2 · 5d cadence" — is this per-farm config? If yes, where does it surface in `IMAGERY_CONFIG`?
5. **Pre-flight checklist persistence.** Local storage is fine for MVP. Post-MVP: persist on `PLAN_ACTIVITY` as a JSON column?

---

## 16. Visual reference index

Every section above maps to a region of `agripulse_app.html`. Quick navigation:

| Section | Where in mockup |
|---|---|
| § 4 Shell | All views — top bar + side nav |
| § 5 Insights | `id="view-insights"` |
| § 5.2 KPI cards | `.row.cards4` first row of insights |
| § 5.3 Trend chart | First card in left column of insights |
| § 5.4 Land unit health | Second card in left column of insights |
| § 5.5 Alerts feed | `.card.alerts` in right column |
| § 5.6 Mini map | `.mini-map` card |
| § 5.7 This week's activities | `.card.act` |
| § 6 Plan view | `id="view-plan"` |
| § 6.1 Toolbar | `.plan-toolbar` |
| § 6.2 Lane sidebar | `.plan-side` |
| § 6.3 Timeline | `.tl-wrap` |
| § 6.4 Activity bar | `.bar` (any) |
| § 6.5 Conflict pin | `.conflict-pin` (B1 lane) |
| § 6.6 Stage band | `.stage-band` (every lane) |
| § 6.7 Detail panel | `.plan-detail` |
| § 6.8 New activity modal | `#newActivityModal` |
