# AgriPulse Scout — Technical Specification

**Status:** draft for review · **Date:** 2026-08-08 · Part B of A/B/D
**Depends on:** [Capability catalogue](mobile-scouting-app-capabilities.md)

---

## 0. Correction carried from Part A

Part A claimed the observation→recommendation feedback loop was already closed.
That is true of the **mechanism** and false of the **content**.

`recommendations/service.py:296` loads a per-block signals snapshot into
`ConditionContext`, so any tree *can* read signals. But across all 18 seed trees
only four signal codes are referenced — `soil_salinity`, `petiole_no3n`,
`petiole_p`, `petiole_k` — every one a lab/soil sample value. **No tree consumes
a scouting-shaped observation.** There is also no signal seed catalogue; signal
definitions are authored per tenant at runtime.

Consequence: closing the loop is **scope**, specified in §7 and §8, not a freebie.
A v1 that ships without §8 still delivers dispatch → capture → human review,
which is the majority of the value, but nothing re-evaluates automatically.

---

## 1. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  TRIGGERS (live today)                                       │
│  RecommendationOpenedV1 (action_type='scout')                │
│  AlertOpenedV1 (severity ≥ threshold)                        │
│  routine scheduler (new)     supervisor ad-hoc (new)         │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
              ┌─────────────────────────────┐
              │  scouting dispatcher (new)  │
              │  resolves routing rule:     │
              │    triage → supervisor queue│
              │    auto   → assign + push   │
              └──────────────┬──────────────┘
                             ▼
                   ┌──────────────────┐        ┌──────────────────┐
                   │ scouting_visits  │◄──────►│  device_tokens   │
                   │      (new)       │        │      (new)       │
                   └────────┬─────────┘        └────────┬─────────┘
                            │                           │
                            │                    push channel (new)
                            │                    via notifications
                            ▼                           ▼
                   ┌──────────────────────────────────────────┐
                   │  Android app — Capacitor + React (new)   │
                   └────────────────────┬─────────────────────┘
                                        ▼
                   ┌──────────────────────────────────────────┐
                   │  signal_observations (LIVE, unchanged)   │
                   │  typed values · photo · GPS · notes      │
                   └────────────────────┬─────────────────────┘
                                        ▼
                   ┌──────────────────────────────────────────┐
                   │  signals snapshot → ConditionContext     │
                   │  LIVE mechanism · needs §8 trees         │
                   └──────────────────────────────────────────┘
```

---

## 2. Open questions from Part A — resolved

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | Declined / expired visit behaviour | Decline returns the visit to the queue **and** notifies the supervisor with the reason. Overdue does **not** auto-close: it stays open and escalates to the supervisor | A silently lapsed visit is indistinguishable from a farm nobody is watching |
| 2 | Partial submission | **Supported.** `outcome ∈ {resolved, inconclusive, blocked}` on completion | "I went, I photographed, I couldn't tell why" is the single most common real outcome and must not be forced into a false binary |
| 3 | `self_initiated` creates a visit? | **Yes** | Gives supervisors one uniform review surface and one audit trail; the row is cheap |
| 4 | Default templates | **Author them** — §7 | No catalogue exists |
| 5 | Supervisor mobile triage | **v1.5**; web only in v1 | Supervisors have desks; scouts do not |
| 6 | Push language | Per-user locale from `user_preferences`, falling back to tenant default | Templates are already keyed by locale |

---

## 3. Data model

All tenant-scoped (`tenant_<id>.*`) unless noted.

### 3.1 `scouting_visits`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid v7 PK | |
| `farm_id` | uuid NOT NULL | |
| `block_id` | uuid NOT NULL | FK blocks, CASCADE |
| `cell_id` | uuid NULL | sub-block grid cell; recs already carry it |
| `origin` | text NOT NULL | `recommendation` \| `alert` \| `routine` \| `ad_hoc` \| `self_initiated` |
| `recommendation_id` | uuid NULL | set when `origin='recommendation'` |
| `alert_id` | uuid NULL | set when `origin='alert'` |
| `schedule_id` | uuid NULL | set when `origin='routine'` |
| `title` | text NOT NULL | rendered at creation, bilingual-resolved |
| `instruction` | text NULL | **the supervisor's own words** — `ad_hoc` only |
| `reason_snapshot` | jsonb NULL | tree text, severity, index values at trigger time |
| `pin_point` | geometry(Point,4326) NULL | supervisor-dropped pin (`ad_hoc`) |
| `severity` | text NOT NULL | mirrors alert/rec severity; `info` for routine |
| `priority` | text NOT NULL | `high` \| `medium` \| `low` — from `parameters.priority` |
| `due_by` | timestamptz NULL | trigger time + `parameters.within_hours` |
| `status` | text NOT NULL | §4 state machine |
| `outcome` | text NULL | `resolved` \| `inconclusive` \| `blocked` |
| `assigned_to` | uuid NULL | `public.users` id |
| `assigned_by` | uuid NULL | NULL ⇒ assigned by rule, not a human |
| `assigned_at` | timestamptz NULL | |
| `accepted_at` | timestamptz NULL | |
| `started_at` | timestamptz NULL | |
| `completed_at` | timestamptz NULL | |
| `completed_by` | uuid NULL | |
| `decline_reason` | text NULL | |
| `template_id` | uuid NULL | which `signal_template` to present |
| `observation_group_id` | uuid NULL | lead `signal_observations.id` (§3.4) |
| `summary_note` | text NULL | scout's free text |
| `created_by` | uuid NULL | NULL ⇒ system-created |
| `idempotency_key` | text NULL | UNIQUE; client-generated, guards double-submit |
| `created_at` / `updated_at` | timestamptz | `TimestampedMixin` |

**Indexes**
- `(status, due_by)` — the overdue sweep and the board
- `(assigned_to, status)` — "My Visits"
- `(farm_id, status, due_by)` — supervisor board
- partial UNIQUE `(recommendation_id) WHERE recommendation_id IS NOT NULL AND status NOT IN ('cancelled','expired')` — one live visit per recommendation, the idempotency guard for a re-firing tree

> **Note.** The daily evaluator re-walks trees; without that partial unique index
> a persistent NDVI depression creates a new visit every single day.

### 3.2 `scouting_routing_rules`

Resolved most-specific-first: block → farm → tenant default.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid v7 PK | |
| `farm_id` | uuid NULL | NULL ⇒ tenant-wide default |
| `block_id` | uuid NULL | NULL ⇒ farm-wide |
| `origin` | text NULL | NULL ⇒ any origin |
| `min_severity` | text NULL | below this, no visit is created at all |
| `mode` | text NOT NULL | `triage` \| `auto` |
| `default_assignee` | uuid NULL | required when `mode='auto'` |
| `fallback_assignee` | uuid NULL | used when the default is inactive |
| `template_id` | uuid NULL | form to attach |
| `default_due_hours` | int NULL | when the origin carries no `within_hours` |
| `is_active` | bool | |

`mode='auto'` with no resolvable assignee **degrades to `triage`** rather than
dropping the visit. Silent loss is the worst failure here.

### 3.3 `device_tokens` (tenant-scoped)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid v7 PK | |
| `user_id` | uuid NOT NULL | |
| `token` | text NOT NULL | FCM registration token |
| `platform` | text NOT NULL | `android` (\| `ios` later) |
| `app_version` | text NULL | |
| `locale` | text NULL | device locale at registration |
| `last_seen_at` | timestamptz | refreshed on every app open |
| `revoked_at` | timestamptz NULL | set on logout or FCM `UNREGISTERED` |

UNIQUE on `(token)`. Multi-device per user is expected. A reaper revokes tokens
unseen for 90 days or rejected by FCM.

### 3.4 Link to observations — no new observation table

On submit, the app posts the whole form as one batch. The service writes N
`signal_observations` rows using the **existing** `template_observation_id`
grouping: the lead row stores its own id, siblings carry it. The visit's
`observation_group_id` stores that lead id.

`SignalObservation` needs **no schema change**. It already carries
`block_id`, `farm_id`, typed values, `attachment_s3_key`, `notes`,
`recorded_by`, `location_point`, `location_mode`, `time` (`observed_at`) vs
`inserted_at` (`recorded_at`).

---

## 4. Visit state machine

```
                    ┌──────────┐
   triage mode ────►│  queued  │  unassigned, awaiting supervisor
                    └────┬─────┘
                         │ assign
   auto mode ───────────►├──────────────┐
                         ▼              │
                   ┌──────────┐         │
                   │ assigned │         │ decline (reason)
                   └────┬─────┘         │  └──► back to queued
                        │ accept        │       + notify supervisor
                        ▼               │
                   ┌──────────┐         │
                   │ accepted │◄────────┘
                   └────┬─────┘
                        │ start (arrives / opens form)
                        ▼
                  ┌─────────────┐
                  │ in_progress │
                  └──────┬──────┘
                         │ submit
                         ▼
                  ┌─────────────┐
                  │  completed  │  + outcome: resolved | inconclusive | blocked
                  └─────────────┘

  Terminal side-paths from any pre-completed state:
    cancelled  — supervisor withdrew it
    expired    — past due_by AND swept; stays visible, escalates, never auto-closes
```

`self_initiated` visits are created directly in `in_progress` by the scout.

**`expired` is not a closure.** The sweep sets the flag, pushes an escalation to
the supervisor, and the visit remains actionable. Auto-closing overdue work would
make a neglected farm look identical to a healthy one.

---

## 5. Capabilities to add

Add to `shared/rbac/capabilities.yaml`, all `scope: farm`:

| Capability | Description | Granted to |
|---|---|---|
| `scouting.visit.read` | See visits on an assigned farm | Scout, FieldOperator, Agronomist, FarmManager, Viewer |
| `scouting.visit.claim` | Claim / accept / decline a visit assigned or offered to you | Scout, FieldOperator, Agronomist |
| `scouting.visit.complete` | Submit observations and close a visit | Scout, FieldOperator, Agronomist |
| `scouting.visit.assign` | Assign or reassign a visit to someone else | Agronomist, FarmManager |
| `scouting.dispatch` | Create an ad-hoc visit | Agronomist, FarmManager |
| `scouting.rule.manage` | Edit routing rules and routine schedules | FarmManager (+ tenant admin) |

Flip `scouting.record` from `status: stub` → `active` — it is the umbrella that
`scouting.visit.complete` implies; keep it as the write gate on the observation
batch so existing grants stay meaningful.

**Also grant `analytics.read` to `Scout`** if M15 (my history) ships in v1.5.

---

## 6. API surface

All under the existing `/api/v1` prefix, farm-scoped via `farm_id_param`
(the pattern PR #270 established for farm-scoped-only users).

### Mobile

| Method | Path | Capability | Notes |
|---|---|---|---|
| `GET` | `/scouting/visits` | `scouting.visit.read` | `?assigned_to=me&status=open`; also `claimable=true` |
| `GET` | `/scouting/visits/{id}` | `scouting.visit.read` | **Self-contained** — reason, block geometry, full template definition, thresholds |
| `POST` | `/scouting/visits/{id}:claim` | `scouting.visit.claim` | 409 if already claimed |
| `POST` | `/scouting/visits/{id}:accept` | `scouting.visit.claim` | |
| `POST` | `/scouting/visits/{id}:decline` | `scouting.visit.claim` | body: `{reason}` |
| `POST` | `/scouting/visits/{id}:start` | `scouting.visit.claim` | idempotent |
| `POST` | `/scouting/visits/{id}:submit` | `scouting.visit.complete` | **single batch**, §6.1 |
| `POST` | `/scouting/visits` | `scouting.visit.complete` | `self_initiated` only |
| `POST` | `/scouting/attachments:presign` | `scouting.record` | returns presigned R2 PUT + `attachment_s3_key` |
| `POST` | `/devices:register` | authenticated | FCM token upsert |
| `DELETE` | `/devices/{token}` | authenticated | logout |

### Supervisor / web

| Method | Path | Capability |
|---|---|---|
| `GET` | `/scouting/visits?status=queued` | `scouting.visit.read` |
| `POST` | `/scouting/visits/{id}:assign` | `scouting.visit.assign` |
| `POST` | `/scouting/visits:dispatch` | `scouting.dispatch` |
| `POST` | `/scouting/visits/{id}:cancel` | `scouting.visit.assign` |
| `GET`/`PUT` | `/scouting/routing-rules` | `scouting.rule.manage` |
| `GET`/`PUT` | `/scouting/schedules` | `scouting.rule.manage` |

### 6.1 Submit payload — one call, offline-shaped

Location and time are recorded **per observation row**, not once per visit. The
`ST_Within` trigger is `FOR EACH ROW`, and `signal_observations` carries its own
`location_point`, `location_mode`, `time` and `attachment_s3_key` on every row —
so the model already supports this and it would be a waste to collapse it.

`visit_location` is the fix taken when the scout tapped submit. It is the
**default** each observation inherits; any row may override it with the fix taken
at the moment that value was actually recorded.

```jsonc
POST /api/v1/scouting/visits/{id}:submit
{
  "idempotency_key": "0198f3...",        // client UUID v7, replay-safe
  "outcome": "inconclusive",
  "summary_note": "الأوراق صفراء في الركن الشمالي",

  "visit_location": {                    // default for rows that omit their own
    "mode": "point_in_entity",
    "lat": 29.9765, "lon": 32.5231, "accuracy_m": 8.2,
    "captured_at": "2026-08-08T07:38:04Z"
  },

  "observations": [
    { "definition_code": "canopy_vigour", "value_categorical": "poor" },

    // Each photo is its own row — scout_photo is value_kind:event — so it
    // carries the fix and the clock reading from the moment of the shutter.
    { "definition_code": "scout_photo", "value_event": "photo",
      "attachment_s3_key": "tenants/.../visits/.../a1.jpg",
      "observed_at": "2026-08-08T07:31:12Z",
      "location": { "mode": "point_in_entity",
                    "lat": 29.97661, "lon": 32.52288, "accuracy_m": 6.0,
                    "source": "gps_at_capture" } },

    { "definition_code": "scout_photo", "value_event": "photo",
      "attachment_s3_key": "tenants/.../visits/.../a2.jpg",
      "observed_at": "2026-08-08T07:33:47Z",
      "location": { "mode": "free_point",          // 14 m outside the boundary
                    "lat": 29.97702, "lon": 32.52401, "accuracy_m": 11.0,
                    "source": "gps_at_capture" } },

    { "definition_code": "stress_cause_observed", "value_categorical": "water" }
  ]
}
```

One transaction: insert N observations with a shared
`template_observation_id`, set the visit to `completed`, emit
`ScoutingVisitCompletedV1`.

**Why per-row matters.** A scout photographs a lesion at the north edge, walks
back along the row, and fills the form four minutes later thirty metres away.
Stamping every row with the submit-time fix would put the evidence in the wrong
place. The photo's coordinate is the only thing that makes it re-findable on a
later visit.

**Rules**
- The client takes a fresh GPS fix **at shutter time**, not at submit time.
- Do **not** rely on photo EXIF. If the camera lacks location permission the tag
  is simply absent, and it is absent silently. Read the fix from the Geolocation
  plugin and treat EXIF as advisory only.
- Strip EXIF server-side before storing — it carries device and, sometimes, a
  second conflicting location.
- `source` is recorded per row: `gps_at_capture` | `gps_at_submit` |
  `snapped_to_block` | `supervisor_pin` | `none`. Provenance beats precision when
  someone reviews this six months later.

---

## 7. Default scouting content (new — must be authored)

Ship as a **platform-curated seed catalogue**, mirroring
`recommendations/seeds/`. New directory `signals/seeds/`.

### 7.1 Signal definitions

| Code | `value_kind` | Values / range | Unit | `attachment_allowed` | Aggregation |
|---|---|---|---|---|---|
| `canopy_vigour` | categorical | `good`/`fair`/`poor`/`severe` | — | yes | `latest` |
| `stress_cause_observed` | categorical | `water`/`pest`/`disease`/`nutrition`/`salinity`/`mechanical`/`none`/`unknown` | — | yes | `latest` |
| `pest_incidence_pct` | numeric | 0–100 | % | yes | `mean`, 7d |
| `pest_species_observed` | categorical | crop-specific list | — | yes | `latest` |
| `disease_symptom` | categorical | `leaf_spot`/`powdery`/`anthracnose`/`wilt`/`chlorosis`/`necrosis`/`none` | — | yes | `latest` |
| `disease_severity` | categorical | `none`/`trace`/`moderate`/`severe` | — | yes | `max`, 7d |
| `soil_moisture_feel` | categorical | `dry`/`moist`/`wet`/`saturated` | — | no | `latest` |
| `irrigation_fault` | categorical | `none`/`emitter_blocked`/`line_leak`/`no_pressure`/`uneven` | — | yes | `latest` |
| `weed_pressure` | categorical | `none`/`light`/`moderate`/`heavy` | — | yes | `latest` |
| `growth_stage_observed` | categorical | crop phenology codes | — | yes | `latest` |
| `scout_photo` | event | — | — | yes | `count`, 7d |

Categorical, not free numeric, almost everywhere — deliberate. It survives an
illiterate or hurried operator, and it is what a decision tree can branch on.

### 7.2 Signal templates

| Template | Definitions | Used by |
|---|---|---|
| `scout_general_v1` | canopy_vigour*, stress_cause_observed*, soil_moisture_feel, scout_photo* | default for `recommendation`/`alert` origin |
| `scout_pest_disease_v1` | disease_symptom*, disease_severity*, pest_incidence_pct, pest_species_observed, scout_photo* | pest/disease-specific dispatch |
| `scout_irrigation_v1` | soil_moisture_feel*, irrigation_fault*, scout_photo* | irrigation-origin |
| `scout_routine_v1` | canopy_vigour*, weed_pressure, growth_stage_observed, scout_photo | routine rounds |
| `scout_quick_v1` | scout_photo*, (note only) | `self_initiated` walk-up |

`*` = `is_required`. **Every template must set `attachment_allowed` on at least
one definition** or the camera never appears (Part A friction #5).

---

## 8. Closing the loop (the part Part A got wrong)

Without this section, scouting data is inert. Three new trees, all consuming
`source: signals` with the codes from §7.1:

| Tree | Reads | Emits |
|---|---|---|
| `scout_confirmed_water_stress_v1` | `stress_cause_observed = water` + `soil_moisture_feel ∈ {dry}` + NDVI deviation | irrigation action, high confidence |
| `scout_confirmed_pest_pressure_v1` | `pest_incidence_pct` above threshold + `disease_severity` | treatment recommendation, crop-specific |
| `scout_found_nothing_v1` | `stress_cause_observed = none` + `canopy_vigour = good` | suppress/downgrade the originating alert; log a false positive |

`scout_found_nothing_v1` matters most and is easiest to forget. It is how the
platform learns its index thresholds are miscalibrated for a given block —
otherwise every false alarm silently re-fires forever.

**Sequencing:** §7 is a v1 blocker (no forms, no app). §8 can land in v1.5 —
but the spec should be honest that until it does, "closes the loop" is aspiration.

---

## 9. GPS handling — the top field-failure risk

`location_mode='point_in_entity'` is enforced by a DB `ST_Within` trigger. A GPS
fix 8 m outside a boundary is rejected **after** the scout has walked the block
and shot photos.

Verified in migration `0029_custom_signals_foundation.py`:

- `trg_signal_observation_check_point_in_entity` is `BEFORE INSERT OR UPDATE …
  FOR EACH ROW` — **each observation is validated independently**. One photo
  taken over the fence fails on its own row; it does not fail the batch.
- CHECK `ck_signal_observations_location_point_presence`:
  `entity` requires `location_point IS NULL`; `point_in_entity` and `free_point`
  both require it NOT NULL.
- The trigger returns early when `location_mode <> 'point_in_entity'`, so
  **`free_point` keeps the coordinate and skips the containment check**, and
  `block_id` may still be set.

### The fallback ladder — prefer `free_point`, not `entity`

An earlier draft of this spec said to fall back to `location_mode='entity'`.
That is the **lossy** option: the CHECK forces `location_point` to NULL, so the
coordinate is discarded outright. `free_point` keeps the coordinate *and* the
block attribution, and is strictly better everywhere the point is real but
outside the polygon.

| Situation | `location_mode` | Coordinate | `source` |
|---|---|---|---|
| Fix inside the block | `point_in_entity` | kept | `gps_at_capture` |
| Fix ≤ 25 m outside, scout accepts the snap | `point_in_entity` | snapped inside | `snapped_to_block` |
| Fix outside, or accuracy worse than the offset | `free_point` | **kept as-is** | `gps_at_capture` |
| No fix at all, or scout declines to share | `entity` | none | `none` |

Required client behaviour:

1. Fetch block geometry with the visit (already in the self-contained payload).
2. Run `turf.booleanPointInPolygon` **per row, before submit** — `@turf/turf` is
   already a frontend dependency.
3. Offer the snap only when the offset is within tolerance **and** exceeds the
   reported accuracy. Snapping a ±30 m fix that sits 8 m out is inventing precision.
4. Otherwise write `free_point` and keep the real reading.
5. Drop to `entity` only when there is genuinely no fix.
6. **Never block submission on GPS.** Losing an observation is far worse than
   losing its coordinate.

---

## 9b. Getting there — the two-leg problem

Navigation is two different problems and one app cannot do both.

**Leg 1 — drive to the field.** Roads, gates, 20 minutes. Hand off to Google Maps.
**Leg 2 — walk to the cell.** No roads, no addresses, 300 m across a block.
Google Maps is useless here; the in-app bearing + distance readout is the tool.

The app switches automatically: hand off while the scout is far away, switch to
the in-app compass once they are inside the farm boundary or under ~250 m.

### The hand-off

Use the **universal HTTPS URL**, not a `geo:` or `google.navigation:` intent:

```
https://www.google.com/maps/dir/?api=1
  &destination=<lat>,<lon>
  &travelmode=driving
```

- It deep-links straight into the Maps app when installed, and falls back to the
  browser when it is not — no dead button on a handset without Maps.
- It avoids the Android 11+ package-visibility `<queries>` declaration that a raw
  intent needs, and the silent failure when that declaration is forgotten.
- Opened via `@capacitor/browser`'s external mode (or `window.open(url,'_system')`)
  so it leaves the WebView rather than loading Maps inside the app.

Offer the same coordinate as a **copyable `lat,lon` string** and a `geo:` share —
WhatsApp is how a scout actually tells a colleague where to meet.

### Which coordinate do we send?

This is the part that decides whether the feature is useful, and the obvious
answer is wrong.

| Rank | Target | Why |
|---|---|---|
| 1 | The farm's **access gate**, if recorded | The only point a vehicle can actually reach. Driving directions to the middle of a field send people down an irrigation bund |
| 2 | The supervisor's **`pin_point`** (`ad_hoc` visits) | They picked it deliberately |
| 3 | `turf.pointOnFeature` of the target **cell** | Guaranteed *inside* the polygon |
| 4 | `turf.pointOnFeature` of the **block** | Same guarantee, coarser |

> Use `pointOnFeature`, **never `centroid`**. A block bent around a road or a
> pivot is concave, and its centroid can sit outside the block entirely — the
> same class of geometry bug already recorded for the map dots.

**Gap:** there is no gate/access-point field on `farms` or `blocks` today. Until
one exists the app ranks from 2 downward. Worth adding as a nullable
`access_point geometry(Point,4326)` on `farms` — it is the single highest-value
field for this feature and costs one column.

### Leg 2 — in-app

Bearing, distance and accuracy, updated live, against the target cell:
`340 m · bearing 019° · ±6 m`. No route line — there is no route. A heading and a
shrinking number is what people actually navigate a field with.

1. App registers the FCM token at login and on every refresh → `POST /devices:register`.
2. `push` joins `_PER_USER_CHANNELS` and `_KNOWN_CHANNELS` in
   `notifications/subscribers.py`; it respects the existing per-user
   `notification_channels` opt-in and the tenant `alert_notification_channels`.
3. New sender `notifications/push.py` alongside `smtp.py` / `webhook.py`.
4. Templates in `public.notification_templates` keyed `(template_code, locale,
   channel='push', version)` — one per origin, EN + AR.
5. Idempotency: the existing partial UNIQUE on
   `(alert_id, channel, recipient_user_id) WHERE status IN ('pending','sent')`
   extends to visits — add `visit_id` to `notification_dispatches`.
6. Payload is a **data message** (not notification-only) so the app controls
   presentation and cold-start deep-linking:

```jsonc
{ "type": "scouting_visit", "visit_id": "...", "farm_id": "...",
  "block_id": "...", "severity": "critical", "due_by": "...",
  "deep_link": "agripulse://scout/visits/{id}" }
```

7. FCM delivery is best-effort. The visit list is the source of truth; the app
   always reconciles on open. A dropped push must never mean lost work.

---

## 11. Mobile app architecture

```
mobile/                        # new workspace in the monorepo
  src/
    app/          routing, auth bootstrap, push registration
    features/
      visits/     list, detail, claim/decline
      capture/    dynamic template form, camera, GPS
      map/        maplibre block view + position
      history/
    shared/       ← imports design tokens, i18n catalogs, api client
  android/                     # Capacitor native shell
  capacitor.config.ts
```

**Reused from `frontend/`:** design tokens, the full EN/AR i18next catalogues,
the axios client + interceptors, `oidc-client-ts` config, `@turf/turf`,
`maplibre-gl`. These are the expensive parts and none are rebuilt.

**Capacitor plugins:** `@capacitor/push-notifications` (FCM),
`@capacitor/camera`, `@capacitor/geolocation`, `@capacitor/preferences`,
`@capacitor/network` (for the v2 queue), `@capacitor/app` (deep links).

**Auth.** OIDC PKCE in a Custom Tab against Keycloak; refresh token in
`@capacitor/preferences` backed by Android Keystore. Long-lived refresh
(~90 days) — a scout must not re-authenticate in a field with no signal.

**Form rendering.** The capture form is **fully driven by the template
definition** returned with the visit. Adding a signal definition changes the app
with no release. This is why `value_kind` / `categorical_values` /
`value_min|max` / `unit` / `is_required` must all ride on the visit payload.

**Build.** Vite build → `npx cap sync android` → Gradle. Signed AAB. Play
internal-testing track for pilot; the pilot farm is small enough that internal
testing beats a public listing.

---

## 11b. Identity, authentication and access

### 11b.1 Three layers that already exist

Identity unification (U-2/U-3, live since 2026-06-15) already built the model
this app needs. Nothing new is invented here; the U-3 link is simply used for
the first time.

| Layer | Table | Carries | Login? |
|---|---|---|---|
| **User** | `public.users` | `keycloak_subject`, `email`, **`phone`**, `full_name` | the login itself |
| **Member** | `public.tenant_memberships` (+ `farm_scopes`) | which tenant, which farms, which role | authorises |
| **Worker** | `tenant_<id>.resources` `kind='worker'` | `role`, **`phone`**, assignable to activities | no |

**Every mobile user is all three**: a `users` row to authenticate, a
`tenant_membership` + `farm_scopes` to authorise, and a `resources` worker row
linked through **`resources.membership_id`** so the same person can be assigned
work on the board.

A worker row **without** `membership_id` is unlinked labour: it can be scheduled,
but it cannot log in and cannot be pushed to. That is the correct model — not
every field hand needs an account.

### 11b.2 Roles

Farm-scope roles only. **No tenant role is required** — farm-scoped-only users
have worked since PR #269/#270.

| Role | App | Notes |
|---|---|---|
| `Scout` | mobile | Read the field, log observations. No `alert.acknowledge`, no `plan_activity.complete`, no `analytics.read` |
| `FieldOperator` | mobile | Superset of Scout; also completes plan activities and acknowledges alerts |
| `Agronomist` | web + mobile | Triage, dispatch, review |
| `FarmManager` | web | Also routing rules and schedules |

> **`FieldWorker` cannot use the app.** U-2 added it to the `resources.role`
> vocabulary as a worker-only value with **no capabilities at all**. Existing
> worker rows recorded as `FieldWorker` must be re-roled to `Scout` before they
> can be given an account. **Audit the worker table before the pilot.**

### 11b.3 The email problem, and the decision

**The blocker.** `public.users.email` is `CITEXT NOT NULL` with `uq_users_email`
(`migrations/public/versions/0003_iam_tables.py:74`), and
`KeycloakAdminClient` sets `"username": email, "email": email`. Field workers do
not have email addresses, so today they **cannot be provisioned at all**.

**Decision (D7): phone as the Keycloak username, with a synthesized email.**
No migration to the identity core; the debt is confined to one synthetic column
value.

```
public.users
  phone           = +201001234567                              ← real, the identity
  email           = +201001234567@scouts.agripulse.cloud       ← synthetic, satisfies NOT NULL + UNIQUE
  full_name       = "Youssef Barakat"

Keycloak
  username        = +201001234567
  email           = +201001234567@scouts.agripulse.cloud
  emailVerified   = false
  credential      = 6-digit PIN, temporary = false
```

**Rules**

1. **Normalise to E.164 on write.** Supervisors will type `01001234567`;
   store `+201001234567`. Normalise before the uniqueness check, or the same
   person gets two accounts.
2. **Never synthesize onto `.local`.** Keycloak 26 strips `.local` addresses on
   user-profile write — a known, already-recorded failure. Use a real domain we
   control (`scouts.agripulse.cloud`), with **no MX record**, so nothing can ever
   be delivered there.
3. **`emailVerified` stays false** and the synthetic address is never used for
   delivery.
4. **`notification_channels` must default to `['in_app','push']`** for these
   users. The system default is `['in_app','email']`, which would fire mail at a
   non-existent address forever.
5. **The Keycloak username is phone, permanently.** If a scout later gains a real
   email, update `users.email` and leave the username alone — changing it
   silently breaks their login.
6. Flag synthetic addresses so reporting and the Team screen can hide them.
   A nullable `users.email_is_synthetic boolean` is the cheap version; deriving
   from the domain suffix is the zero-migration version.

**Credential.** `_issue_credential` already tolerates a dead SMTP by falling back
to `_set_temporary_password`. That path sets `temporary: true`, forcing an
`UPDATE_PASSWORD` on first login — **wrong for this persona**, who cannot
complete a password-change form in a browser. Scout enrolment needs a sibling
method that sets `temporary: false` with a supervisor-chosen 6-digit PIN.

### 11b.4 Enrolment flow

```
Supervisor (web)                    Backend                     Keycloak
─────────────────────────────────────────────────────────────────────────
Add worker
  name + phone + role=Scout  ──►  normalise to E.164
  ☑ "give them app access"        synthesize email
                                  create users row      ──►  create user
                                                              username=phone
                                  membership + farm_scope     set 6-digit PIN
                                  resources row               temporary=false
                                    membership_id=… ◄──────── set farm_scopes attr
                                  channels=[in_app,push]
  ◄── show PIN once, on screen ──
Reads the PIN to the scout
```

The PIN is shown **once**, on screen, and never stored in readable form —
the same one-time-reveal contract `invite_user` already returns for
`temporary_password`. Re-issuing is a supervisor action, mirroring
`:resend-invite`.

### 11b.5 Keycloak client and session

New **public** client `agripulse-mobile`:

- Authorization Code + **PKCE**, in an Android Custom Tab — never an embedded WebView.
- Redirect `agripulse://auth/callback`; the same scheme carries push deep links.
- **`offline_access` scope** — this is the right mechanism for a ~90-day field
  session. Do **not** stretch SSO Session Idle/Max on the realm; that would weaken
  the web app for everyone.
- Refresh token in `@capacitor/preferences`, backed by Android Keystore.
- `farm_scopes` mapper as-is — the middleware already parses JSON-string items.

The existing `agripulse-api` direct-grant client stays for scripts and tests. A
phone+PIN direct-grant login is the fallback if PKCE-in-Custom-Tab proves
awkward for this persona, but PKCE is the default.

### 11b.6 Authorization at request time

Unchanged from the web app, which is the point:

- The JWT carries `tenant_id`, `tenant_role` (absent for scouts) and `farm_scopes`.
- Every scouting endpoint gates on a farm-scoped capability via `farm_id_param`,
  the pattern PR #270 established.
- A `Scout` who requests a visit on a farm outside their scope gets 403 from the
  same middleware that guards the web app. **No mobile-specific authorization
  path exists, and none should.**

### 11b.7 Offboarding

A scout who leaves must lose access on all three layers, and the token TTL is the
lag:

1. Revoke `farm_scopes` → `set_farm_scopes()` syncs Keycloak.
2. Set the membership to inactive.
3. Archive the `resources` row (`archived_at`) — history is preserved.
4. **Revoke device tokens** (`device_tokens.revoked_at`) or a deregistered phone
   keeps buzzing.
5. **Revoke offline tokens in Keycloak.** An `offline_access` token outlives an
   access-token TTL by design; scope revocation alone does not kill it.

> Step 5 is the one that gets forgotten. With a 90-day offline token, "we removed
> their access" is false until it is done.

### 11b.8 Risks specific to this model

| Risk | Severity | Mitigation |
|---|---|---|
| **Recycled phone numbers.** Egyptian numbers are reassigned; username = phone means the new holder inherits an identity | **High** | Never add SMS-based password reset on top of this model without re-verification. Offboarding must archive the user, not just the membership |
| **6-digit PIN is weak** | Medium | Keycloak brute-force detection **must** be enabled on the realm. Blast radius is bounded: a Scout can read one farm and write observations, nothing more |
| Synthetic emails pollute reporting and the Team screen | Medium | Flag and filter (§11b.3 rule 6) |
| Supervisor becomes the password-reset helpdesk | Medium | Accepted cost of no SMS. Measure at pilot; SMS OTP is the upgrade path |
| Provisioning burden per scout | Medium | Bulk enrolment from the existing worker list — most already exist as `resources` rows with a `phone` |
| PIN read aloud in front of others | Low | Prompt a change on first login **inside the app**, not via Keycloak's browser form |

## 12. Delivery sequence

| Phase | Contents | Gate |
|---|---|---|
| **S-1** | **Identity first** — phone-as-username enrolment, PIN issuance (`temporary:false`), `agripulse-mobile` KC client, worker-table `FieldWorker` audit (§11b) | A scout with no email can log in |
| **S0** | §7 signal definitions + templates as seeds; capabilities + role grants (§5) | Forms exist and are authored |
| **S1** | `scouting_visits`, routing rules, service, mobile+web API (§3, §6) | API testable with curl |
| **S2** | `push` channel, `device_tokens`, FCM sender, templates (§10) | A phone rings |
| **S3** | Android app: auth, visit list, detail, capture, submit (§11) | End-to-end on a real handset |
| **S4** | Web: triage queue, ad-hoc map dispatch, board (S1–S6) | Supervisor loop closed |
| **S5** | §8 trees, overdue sweep, routine schedules | Automation loop closed |

S0 and S2 are independent of S1 and can run in parallel. S3 is the long pole.

---

## 13. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Online-only v1 fails first field trial (D2) | **High** | §7 offline-shaped payloads mean the fix is additive, not a rewrite. Pilot on a block with known coverage |
| GPS `ST_Within` rejections lose work | **High** | §9 client pre-validation, never block submit |
| Daily evaluator floods scouts with repeat visits | **High** | Partial UNIQUE on `recommendation_id` (§3.1) |
| Scouting data recorded but inert | Medium | §8 — be explicit about which release closes it |
| Push undelivered on Chinese OEM Android builds | Medium | List is source of truth; badge on app open; consider SMS fallback for `critical` |
| Per-scout Keycloak provisioning burden (D1) | Medium | Bulk-invite flow; measure at pilot. Full identity risk table in §11b.8 |
| **Field workers have no email — cannot be provisioned at all today** | **High** | D7: phone-as-username + synthetic email (§11b.3). Blocks everything, hence phase S-1 |
| Offline token survives offboarding | **High** | §11b.7 step 5 — revoke offline tokens in Keycloak, not just farm scopes |
| Capacitor perf on low-end handsets | Low | Keep maplibre to one screen; test on a ~$100 device early |
```
