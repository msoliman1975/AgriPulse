# AgriPulse Scout — Mobile App Capability Catalogue

**Status:** draft for review · **Date:** 2026-08-08 · **Target:** Android first

Part A of a three-part design set (A capabilities → B specs → D mockups).

---

## 1. Premise

The platform is already wired for this app and was left unbuilt. The scouting
loop exists on both ends; only the middle is missing.

```
index anomaly ──► scout_for_stress_v1 ──► recommendation
  (NDVI z-score)     (decision tree)        action_type: scout
                                            within_hours: 24 | 72
                                                    │
                                        ╔═══════════▼═══════════╗
                                        ║      THE GAP          ║
                                        ║  push · dispatch ·    ║
                                        ║  mobile capture       ║
                                        ╚═══════════┬═══════════╝
                                                    │
  decision trees ◄── signals snapshot ◄── signal_observations
  re-evaluate       (service.py:296)      (photos, GPS, typed values)
```

### What already exists

| Piece | Where | State |
|---|---|---|
| `Scout` farm role | `shared/auth/context.py:41` | live |
| `scouting.record` capability | `shared/rbac/capabilities.yaml:378` | **declared, `status: stub`, 0 endpoints** |
| Scout-triggering decision tree | `recommendations/seeds/scout_for_stress_v1.yaml` | live, bilingual, severity-graded |
| `RecommendationOpenedV1` carrying `action_type` | `recommendations/events.py` | live, already subscribed by notifications |
| Observation model (typed values, photo, GPS, notes) | `signals/models.py::SignalObservation` | live, TimescaleDB hypertable |
| Grouped observation forms | `signals/models.py::SignalTemplate` (+`position`, `is_required`) | live |
| GPS-inside-block enforcement | `location_mode='point_in_entity'`, DB `ST_Within` trigger | live |
| Observation → recommendation feedback | `recommendations/service.py:296` loads signals snapshot | live |
| Notification fan-out (`in_app`/`email`/`webhook`) | `notifications/subscribers.py` | live, per-user opt-in |
| Farm-scoped JWT for scoped-only users | PR #269/#270 | live since 2026-06-16 |

### What is genuinely new

1. `scouting_visits` — a thin dispatch/SLA entity.
2. A `push` channel + device-token registry + FCM sender.
3. Routing rules (supervisor-triage vs rule-based auto-assign, per farm).
4. The Android client itself.

---

## 2. Decisions locked

| # | Decision | Consequence |
|---|---|---|
| D1 | Scouts are **real Keycloak logins, farm-scoped** (`FarmRole.SCOUT`) | Reuses IAM + `recipient_user_id`; real audit trail; per-scout provisioning cost |
| D2 | **Online-only v1** | No local DB in v1. Payloads and UI states still shaped for a later queue (§7) |
| D3 | **Capacitor + React**, new mobile app in the monorepo | Reuses design tokens, EN/AR i18n catalogs, axios client, `oidc-client-ts`, maplibre-gl |
| D4 | **Thin `scouting_visits` table**; observations stay in `signals` | Feedback loop into decision trees works untouched |
| D5 | **Both** supervisor-triage and rule-based auto-assign, selectable per farm | Two dispatch paths; routing-rules model required |
| D6 | Visits have **multiple origins**, not just recommendations | `origin` discriminator drives copy, priority and SLA |
| D7 | **Phone is the Keycloak username**; email is synthesized on a domain we own | Field workers have no email, and `users.email` is `NOT NULL` + `UNIQUE`. Zero migration; see spec §11b |

---

## 3. Visit origins

A visit is the unit of work. Where it comes from changes almost nothing
structurally and almost everything about the copy and the SLA.

| Code | Origin | Trigger | Due-by source |
|---|---|---|---|
| `recommendation` | Decision tree emitted `action_type: scout` | `RecommendationOpenedV1` subscriber | tree's `parameters.within_hours` (24 / 72) |
| `alert` | An alert opened on a block, severity ≥ threshold | `AlertOpenedV1` subscriber | routing-rule default per severity |
| `routine` | Recurring scouting round | scheduled job | schedule cadence |
| `ad_hoc` | **Supervisor saw something on the map and wants eyes on it** | manual, from Farm Console | supervisor sets |
| `self_initiated` | Scout is in the field and logs what they found | mobile, unprompted | n/a — created already in progress |

`ad_hoc` is a first-class origin, not an afterthought: it is the only path that
carries a **human instruction** ("check the north edge, the NDVI looks patchy")
and optionally a **pinned map location + captured map view** rather than a
machine-generated reason.

---

## 4. Capabilities

Legend — **v1** ship first · **v1.5** fast follow · **v2** deferred.

### 4.1 Mobile — Scout (M)

| # | Capability | Rel | Notes |
|---|---|---|---|
| M1 | Sign in with **phone number + 6-digit PIN**, Arabic by default | v1 | New public client `agripulse-mobile`, PKCE in a Custom Tab, **`offline_access`** for the ~90-day field session. Username is the E.164 phone; see spec §11b |
| M2 | Receive push, deep-link straight into the visit | v1 | FCM data message; cold-start deep link must work |
| M3 | **My Visits** — assigned / claimable / overdue, with SLA countdown | v1 | Sorted by due-by then severity |
| M4 | Visit detail: *why* — bilingual rec/alert text, severity, index anomaly sparkline, or the supervisor's instruction | v1 | Text comes free from the tree; sparkline reuses `indices` |
| M5 | Visit detail: *where* — block/cell geometry on maplibre, current position | v1 | Cell-scoped recs already carry `cell_id` |
| M6 | Navigate to the block/cell | v1 | **Two legs.** Drive → hand off to Google Maps via the universal `maps/dir/?api=1` HTTPS URL (deep-links to the app, degrades to browser, no Android 11 `<queries>` trap). Walk → in-app bearing + distance. Target ranks gate → supervisor pin → `pointOnFeature` of cell → of block. See spec §9b |
| M7 | Claim / accept / decline a visit | v1 | Decline needs a reason; returns it to the queue |
| M8 | Capture observations via the signal template form | v1 | Typed fields from `SignalDefinition` (`value_kind`, `categorical_values`, `value_min/max`, `unit`); `is_required` from the template junction |
| M9 | Photo capture + attach | v1 | Gated per definition by `attachment_allowed`; presign flow **already exists** (`init_attachment_upload`) |
| M10 | GPS-stamp **every observation row**, at the moment it is recorded | v1 | Per-row `location_point` + `time`; each photo is its own row carrying its own fix and shutter time. Fall back `point_in_entity` → `free_point` → `entity`. See spec §6.1 and §9 |
| M11 | Free-text note (+ Arabic voice-to-text) | v1 | Voice input matters more than it sounds for this persona |
| M12 | Submit → close visit, write observations, re-trigger evaluation | v1 | One transaction; idempotency key |
| M13 | Self-initiated visit ("I'm here, and I see something") | v1 | Pick block from map or resolve from GPS |
| M14 | Arabic / RTL throughout, low-literacy affordances | v1 | Icon-led, photo-first, large tap targets, minimal free text |
| M15 | My visit history | v1.5 | Last 30 days; no `analytics.read` on `Scout` today (§6) |
| M16 | Routine round mode — walk a sequence of blocks, tick each off | v1.5 | Batches `routine`-origin visits into one flow |
| M17 | In-app inbox mirror (`in_app_inbox` already exists) | v1.5 | Non-scouting notifications too |
| M18 | Offline queue | v2 | Deliberately deferred; API shaped for it now (§7) |
| M19 | Photo annotation (circle the lesion) | v2 | |
| M20 | On-device pest/disease hint from photo | v2 | Needs a model + labelled data the platform doesn't have yet |

### 4.2 Web — Supervisor / Agronomist (S)

| # | Capability | Rel | Notes |
|---|---|---|---|
| S1 | **Triage queue** — scout recommendations + alerts awaiting dispatch | v1 | Only path that exists when a farm is in `triage` mode |
| S2 | Assign / reassign / bulk-dispatch to scouts | v1 | |
| S3 | **Ad-hoc dispatch from the Farm Console map** — drop a pin, write an instruction, send | v1 | The "something looks fishy" path; the highest-value non-obvious feature |
| S4 | Routing rules per farm: `triage` vs `auto`, block→default-scout, severity thresholds | v1 | Implements D5 |
| S5 | Visit board — open / in-progress / overdue / done, SLA breach highlighting | v1 | |
| S6 | Review submitted observations: photos, values, resulting recommendations | v1 | |
| S7 | Routine scouting schedules (recurring rounds per block/farm) | v1.5 | Feeds M16 |
| S8 | Scout coverage + responsiveness reporting | v2 | Needs `analytics.read` grant |
| S9 | **Enrol a scout: name + phone + role, get a PIN on screen** | v1 | Extends the existing Workers screen. Creates user + membership + farm scope + linked `resources` row in one action (spec §11b.4) |
| S10 | Re-issue a PIN, and offboard across all five layers | v1 | Mirrors `:resend-invite`. Offboarding **must revoke offline tokens**, not just farm scopes |

### 4.3 Backend / platform (P)

| # | Capability | Rel | Notes |
|---|---|---|---|
| P1 | `scouting_visits` table + service + router; implement the stub `scouting.record` | v1 | |
| P2 | `push` as a 4th channel + `device_tokens` table (multi-device) + FCM sender | v1 | Add to `_PER_USER_CHANNELS` / `_KNOWN_CHANNELS` in `subscribers.py` |
| P3 | Subscriber: `RecommendationOpenedV1` where `action_type == 'scout'` → create visit per routing rule | v1 | Hook point already fires |
| P4 | Subscriber: `AlertOpenedV1` above a severity threshold → create visit | v1 | |
| P5 | Routing-rules model + resolver | v1 | |
| P6 | Visit ↔ signal-observation-group linkage (reuse `template_observation_id` lead row) | v1 | |
| P7 | New capabilities + role grants (§6) | v1 | |
| P8 | Push notification templates, EN + AR, per origin | v1 | `public.notification_templates` is already keyed by `(code, locale, channel, version)` |
| P9 | ~~Presigned attachment upload~~ | — | **Already built** — `signals/service.py::init_attachment_upload` does presign → PUT → INSERT. Reuse as-is |
| P12 | `farms.access_point geometry(Point,4326)` — the gate a vehicle can reach | v1.5 | One nullable column; without it, driving directions aim at the middle of a field. See spec §9b |
| P13 | **Phone-based enrolment**: E.164 normalisation, synthetic-email minting, PIN issuance with `temporary:false` | v1 | Sibling to `_set_temporary_password`, which forces a browser password change this persona cannot complete |
| P14 | `agripulse-mobile` Keycloak client + `offline_access`, and offline-token revocation on offboard | v1 | Realm change. Do **not** stretch realm SSO lifetimes — that weakens the web app |
| P15 | Audit `resources.role='FieldWorker'` rows before pilot | v1 | `FieldWorker` has **zero** capabilities; those people cannot log in until re-roled to `Scout` |
| P10 | Overdue/SLA sweep job → escalation push to supervisor | v1.5 | |
| P11 | Routine-schedule generator job | v1.5 | |

---

## 5. Personas & role mapping

| Persona | Farm role | Surface |
|---|---|---|
| Scout | `Scout` | Mobile only |
| Field operator | `FieldOperator` | Mobile; superset — also holds `alert.acknowledge`, `plan_activity.complete` |
| Agronomist | `Agronomist` | Web triage + mobile (can also scout) |
| Farm manager | `FarmManager` | Web triage, rules, board |

---

## 6. Friction found in the current model

These are real and need decisions before specs are final.

1. **`Scout` cannot close anything.** No `alert.acknowledge`, no
   `plan_activity.complete`. Fine under D4 (visits are their own entity), but
   the new visit capabilities must be granted explicitly.
2. **`Scout` has no `analytics.read`** — blocks M15/S8 without a grant change.
3. **New capabilities required:** `scouting.visit.read`, `scouting.visit.claim`,
   `scouting.visit.complete`, `scouting.visit.assign`, `scouting.dispatch`,
   `scouting.rule.manage`. Only the first three go to `Scout`.
4. **GPS drift at block edges will trip the `ST_Within` trigger.** A scout
   standing on the boundary gets a hard DB rejection after they have already
   walked the block and taken photos. The client must validate against the block
   polygon *before* submit and offer "snap to block" or fall back to
   `location_mode='entity'`. This is the single most likely field-failure mode.
5. **Photos are gated per signal definition** (`attachment_allowed`). Scouting
   templates must set it, or the camera silently won't be offered.
6. **Notification recipients are loaded per farm from user preferences.** Push
   needs a per-user, multi-device token registry and a stale-token reaper.
7. **Unlinked labour cannot be targeted.** `resources` rows with
   `membership_id IS NULL` have no login, so they cannot receive push. Under D1
   every scout needs provisioning — budget for it.

---

## 7. Keeping the offline door open (D2)

v1 is online-only, but these cost nothing now and prevent a data-layer rewrite:

- Every mutation takes a **client-generated idempotency key** (UUID v7).
- Observation submit is a **single batch endpoint**, never a chatter of per-field calls.
- The visit payload is **self-contained** — reason text, thresholds, block
  geometry, and the full template definition ride along, so a cached visit is
  renderable with no follow-up fetch.
- Client records `observed_at` separately from `recorded_at` — the model already
  distinguishes `time` from `inserted_at`.
- UI carries a **sync-state slot** from day one (synced / pending / failed), even
  though v1 only ever shows "synced".

---

## 8. Open questions for the specs round

1. Does a declined or expired visit auto-escalate to the supervisor, or silently lapse?
2. Can a scout submit a **partial** visit (arrived, photographed, could not complete)?
3. Should `self_initiated` observations create a visit record at all, or write bare signal observations?
4. Which signal templates ship as scouting defaults — is there an existing seed catalogue to reuse?
5. Do supervisors need mobile triage in v1, or is web sufficient?
6. Push language: per-user locale from `user_preferences`, or farm default?
