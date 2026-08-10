# Web app additions required by AgriPulse Scout

**Status:** draft for review · **Date:** 2026-08-08
**Companion to:** [capabilities](mobile-scouting-app-capabilities.md) · [spec](mobile-scouting-app-spec.md) · [mockups](mobile-scouting-app-mockups.html)

The phone is only half the product. Every visit is dispatched, assigned and
reviewed from the web app, and scouts are enrolled there. This is the web-side
work, checked against the live route table in `frontend/src/App.tsx`.

Legend — 🆕 new surface · ➕ extends an existing one · ⚠️ decision needed first.

---

## 1. Scouting — entirely new 🆕

No `/scouting` route exists today.

| # | Surface | Route | Notes |
|---|---|---|---|
| W1 | **Triage queue** — machine-created visits awaiting a human | `/scouting/:farmId` | The only path when a farm's routing rule is `mode='triage'`. Mocked in stage 08 |
| W2 | **Visit board** — open / in progress / overdue / done | same page, tabs | Overdue must sort first and never auto-clear |
| W3 | **Assign / reassign / bulk dispatch** | action on W1 | `scouting.visit.assign` |
| W4 | **Ad-hoc dispatch from the map** | action on `/labs/map` | ➕ Farm Console. Drop a pin, write the instruction, pick a scout. Mocked in stage 07 |
| W5 | **Visit detail + observation review** | `/scouting/:farmId/visits/:id` | Photos, typed values, outcome, and **each photo plotted at its own capture coordinate** (spec §6.1) |
| W6 | **Routing rules** — `triage` vs `auto`, default assignee, severity floor | `/config/scouting/:farmId` | Mirrors the existing `/config/rules/:farmId` pattern |
| W7 | **Routine scouting schedules** | same page | v1.5 — feeds the mobile "round" mode |
| W8 | Scout coverage + responsiveness | `/reports/:farmId` ➕ | v2; needs `analytics.read` on `Scout` |

**W4 is the highest-value item here** and the easiest to under-scope. It is the
only origin that carries a human instruction, and the supervisor is already
looking at the imagery when the hunch forms — so it must be an action *on the
Farm Console*, not a separate page they have to navigate to.

---

## 2. Identity and enrolment ➕

Everything hangs off this; see spec §11b.

| # | Surface | Where | Notes |
|---|---|---|---|
| W9 | **Enrol a scout**: name + phone + role + "give app access" → **PIN shown once** | `/settings/workers` ➕ | One action creates `users` + `tenant_membership` + `farm_scope` + linked `resources` row |
| W10 | **Re-issue PIN** | same | Mirrors the existing `:resend-invite` |
| W11 | **Offboard across all five layers** | same | Scopes, membership, worker archive, device tokens, **and the Keycloak offline token** |
| W12 | **Registered devices** per user — model, last seen, revoke | `/settings/users` ➕ | Without this, a lost phone keeps receiving farm data |
| W13 | **Hide or flag synthetic emails** | `/settings/users` ➕ | `<phone>@scouts.agripulse.cloud` must not read as a real contact |
| W14 | **`FieldWorker` audit + bulk re-role to `Scout`** | `/settings/workers` ➕ | ⚠️ `FieldWorker` has **zero** capabilities — those people cannot log in. Run before pilot |
| W15 | Phone number as a first-class, validated field (E.164) | `/settings/workers` ➕ | It becomes the login. Normalise on write or one person gets two accounts |

---

## 3. Notifications ➕

`/settings/notifications` already exists.

| # | Surface | Notes |
|---|---|---|
| W16 | **`push` as a fourth channel** in preferences | Alongside `in_app` / `email` / `webhook` |
| W17 | **Scout defaults must be `['in_app','push']`** | The system default `['in_app','email']` would fire mail at a synthetic address forever |
| W18 | Per-origin notification control | Let a supervisor mute `routine` without muting `alert` |

---

## 4. Scouting forms — a platform tier that does not exist ⚠️ 🆕

The scouting signal definitions and templates (spec §7) are the S0 blocker: no
forms, no app.

**The problem.** `SignalDefinition` and `SignalTemplate` are **tenant-scoped**
(`tenant_<id>.signal_definitions`) and authored per tenant at
`/config/signals/:farmId`. There is **no `public.signal_definitions`** and no
platform signals catalogue — unlike decision trees and crops, signals have no
platform tier at all. So there is nowhere to publish a curated scouting form set
once for everybody.

Three options:

| Option | What it means | Cost |
|---|---|---|
| **A. Seed per tenant at provisioning** | A `signals/seeds/` catalogue applied into each tenant schema on creation, plus a backfill for existing tenants | Low. But every tenant then owns a private copy that drifts, and improving a form never reaches anyone |
| **B. Add a platform tier** (recommended) | `public.signal_definitions` + `signal_templates` with nullable `tenant_id`, exactly the `decision_trees` pattern; a `/platform/signals` catalogue page | Medium. Migration + resolver + UI, but it matches a pattern the codebase already uses twice |
| **C. Tenant-authored only** | Document the forms; each tenant builds their own | Near-zero build, near-zero chance the pilot succeeds |

I recommend **B**. Scouting forms are exactly the kind of thing that should
improve centrally — and the two-tier read (`WHERE tenant_id IS NULL OR
tenant_id = :tid`) is already written twice in this codebase.

---

## 5. Platform decision-tree authoring ⚠️ 🆕

Answering the question directly: **there is no platform decision-tree page and
there never was one.** Global trees (`public.decision_trees.tenant_id IS NULL`)
are authored **only** as YAML in `recommendations/seeds/` and upserted by
`loader.sync_from_disk()` at **API startup** (`app/core/app_factory.py:49-54`).
Deploying the API is what publishes a tree. The API cannot create one:
`decision_tree.manage` is `scope: tenant`, and the authoring routes assert
`context.tenant_id is not None` (`recommendations/router.py:447`) and always set
`tenant_id=context.tenant_id` (`:378`).

Tenants *can already see* platform trees — the list query is
`WHERE t.tenant_id IS NULL OR t.tenant_id = :tid` (`:346`). What is missing is a
place to manage the **global catalogue** without standing inside a tenant.

| Option | What it means | Trade-off |
|---|---|---|
| **C1. Read-only platform catalogue** (recommended first) | `/platform/decision-trees` — list all 18 seeded trees, view the graph, evidence, citations, which tenants override them | Cheap, no source-of-truth conflict. Probably solves the actual complaint |
| **C2. Author in the UI, emit a PR** | Editing opens a GitHub PR against `seeds/*.yaml` | Keeps code review and scientific provenance. Needs a GitHub integration |
| **C3. DB becomes source of truth** | `sync_from_disk` degrades to insert-if-missing and never overwrites | Full authoring freedom, but repo YAML silently drifts from live and the `evidence`/DOI blocks lose review |

**Do not do C3 and keep the seeder as-is.** They fight: the UI writes a row, the
next deploy's hash comparison overwrites it. That is a genuine footgun and the
main reason the current YAML-only design is defensible.

> Worth stating plainly: the YAML approach is *good* here. Trees carry `evidence`
> blocks with DOIs, citations and `transferability` ratings — scientific claims
> that benefit from diffs and review. A UI is a convenience; provenance is the product.

---

## 6. Smaller items

| # | Item | Where |
|---|---|---|
| W19 | **`farms.access_point`** — drop the gate pin a vehicle can actually reach | `/farms/:farmId/edit` or Farm Console ➕. Without it, driving directions aim at the middle of a field (spec §9b) |
| W20 | Link from a block/alert straight to "send a scout" | `/alerts/:farmId`, Farm Console ➕ |
| W21 | Show scouting observations on the block timeline | `/labs/map` inspector ➕ |
| W22 | Arabic strings for every surface above | `en/ar` catalogues — the app is Arabic-first and the web side must match |

---

## 7. Suggested order

1. **W14** — the `FieldWorker` audit. It is free, and it tells you how many people actually need accounts.
2. **W9–W11, W15** — enrolment. Nothing can be tested without a scout who can log in.
3. **§4 option B** — the signals platform tier, then author the forms.
4. **W1–W3, W5** — triage queue and review, so dispatched work can be closed.
5. **W16–W17** — push channel.
6. **W4** — ad-hoc dispatch. The highest-value feature, but it needs the rest to exist first.
7. **W6** — routing rules. Until then, hard-code `mode='triage'`.
8. **C1** — the platform tree catalogue, independent of everything above.
