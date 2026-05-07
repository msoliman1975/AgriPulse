# AgriPulse — UX handoff package

This folder is a self-contained handoff for a Claude Code session that will **build the AgriPulse front-end** and wire it to whatever backend APIs the team is building.

## What's in this folder

| File | Purpose | Read first? |
|---|---|---|
| `HANDOFF_README.md` | This file — orientation & how to use the package | ✅ start here |
| `UX_SPEC.md` | The UX specification: IA, screens, components, flows, design tokens, states | ✅ |
| `BUILD_PLAN.md` | Recommended stack, project structure, phased delivery, acceptance criteria | ✅ |
| `agripulse_app.html` | **Interactive mockup** — the visual source of truth. Insights + Plan, fully clickable. | ✅ open it |
| `agripulse_core_erd.html` | Mermaid ERD of the data model (organization, farms, land units, activities, alerts, etc.) | ✅ |
| `req.txt` | Original product notes — explains the `LAND_UNIT` modeling decision and the rule/override pattern | ⚪ context |
| `design_1_field_ops.html` | Earlier exploration — map-first concept (kept for future "Map" view) | ⚪ optional |
| `design_3_season_planner.html` | Earlier exploration — standalone planner (now folded into `agripulse_app.html`) | ⚪ optional |
| `index.html` | Landing page that compares the three explorations | ⚪ optional |

## How to use this package in a new Claude Code session

Paste this prompt at the start of your new session:

> I'm building the AgriPulse front-end. The full UX handoff is in this folder.
>
> 1. Read `HANDOFF_README.md` first.
> 2. Open `agripulse_app.html` in a browser — that is the **visual & interaction source of truth**. The static HTML is throwaway; what matters is the structure, components, and flows it demonstrates.
> 3. Read `UX_SPEC.md` end-to-end before writing any code. It covers the IA, every screen, every component, design tokens, and interaction patterns.
> 4. Read `BUILD_PLAN.md` for the recommended stack, project structure, and phased delivery. Confirm the stack with me before scaffolding.
> 5. Use `agripulse_core_erd.html` as the canonical data model. Build TypeScript types directly from those entities.
>
> **Out of scope for this session:** writing API contracts. The backend team owns those. Build the UI against a typed data layer (mock or real) and keep the API integration in a thin, swappable adapter.
>
> Start by confirming the stack and project structure from `BUILD_PLAN.md`, then begin Phase 1.

## Decisions already made (don't re-litigate)

These were validated by the product owner during the design exploration phase:

1. **Two primary destinations**: `Insights` (dashboard) is the home page. `Plan` (Gantt-style season planner) is a dedicated section. Both share the same shell.
2. **Single `LAND_UNIT` table** for blocks, pivots, and pivot sectors — see `req.txt` for the rationale. The UI must not branch on unit type for downstream features (alerts, charts, plans). Only shape rendering differs.
3. **Mango-first, multi-crop ready**. Design copy uses mango/Keitt examples, but no string or layout assumes a single crop.
4. **Conflict detection lives in the UI layer initially** — see the spray + drip pulse pin on B1 in the mockup. The rules are simple enough to start client-side; promote to server when complex.
5. **Activities are the unit of work in the planner** — `VEGETATION_PLAN` → `PLAN_ACTIVITY` (see `req.txt`). The Gantt bars are activities.

## Decisions deferred (the build session can ask)

- Whether to use Tailwind, CSS Modules, or vanilla CSS-with-tokens (`BUILD_PLAN.md` recommends one but is not prescriptive).
- Charting library (Recharts vs. visx vs. hand-rolled SVG — the mockup is hand-rolled and it's fine).
- Real-time transport for live alerts (SSE vs. WebSocket vs. polling) — UI just needs an event stream, doesn't care.
- i18n / RTL — Arabic support is a near-term requirement but not part of MVP. See `UX_SPEC.md` § Internationalization for hooks to leave in place.

## What the receiving session should produce

A working front-end that:
- Renders the Insights view and Plan view from typed data.
- Implements the four-step "New activity" flow.
- Implements lane selection, activity selection, filter chips, conflict pins, and growth-stage bands as shown in the mockup.
- Has a swappable data layer so the team can plug real APIs in later.
- Passes the acceptance criteria in `BUILD_PLAN.md`.

Not in scope:
- Authentication UI (assume the user is already logged in; consume a `currentUser` and `currentFarm` from context).
- Admin screens (rule overrides, imagery/weather config, users & roles) — placeholders only.
- The "Map" view — surfaced in side nav as "Land units" but can be a stub returning to Insights for MVP.
