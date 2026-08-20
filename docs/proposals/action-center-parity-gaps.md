# Can Action Center replace Recommendations and Alerts?

Answer: not yet. The Action Center is a better queue, but it cannot close an
item. Every state change a user makes today happens on `/recommendations` or
`/alerts`. If those two rows leave the navigation now, several roles lose the
only control they have.

Checked on `origin/main` at `1d6229d0`, 2026-08-20.

## What the Action Center already covers

These are equal or better than the two single-kind pages:

| Feature | Recommendations | Alerts | Action Center |
| --- | --- | --- | --- |
| Both kinds in one list | no | no | yes, with a type filter |
| Status tabs with counts | tabs, no counts | tabs, no counts | tabs with counts |
| Severity shown | yes | yes | yes |
| Filter by block | no | no | yes |
| Filter by severity | no | no | yes |
| Filter by date raised | no | no | 1d/7d/30d/90d/all/custom |
| Filter by assignee | no | no | yes |
| Group by type, block or due date | no | no | yes |
| Select many rows and act once | no | no | yes |
| Assign to a person with a date and a note | no | no | yes, the dispatch dialog |
| Cell coordinates and a map link | zone code only | no | yes |
| Due date bucket, overdue marked | expiry text | no | yes |
| Repeat count and day streak | streak pill | no | yes, with first and last seen |
| Group of cells, with drill-down | count pill | no | yes, members list |
| Spreading or receding trend | no | no | yes |
| Open the linked board activity | yes | yes | yes, when an activity exists |

## The gaps

### G1. No way to close an item. Blocking.

`/recommendations` writes five state changes: apply, dismiss, defer 24 hours,
and the two the board uses. `/alerts` writes two: acknowledge and resolve.

The Action Center writes one thing: dispatch. Dispatch creates a board activity
or a scout visit. It does not change the row's own state.

Proof in the code:

- `frontend/src/api/actionCenter.ts` has three calls: list, members, dispatch.
- `frontend/src/modules/actionCenter/components/ItemRow.tsx:266-287` renders
  three buttons: open on board, why, dispatch.
- `backend/app/modules/action_center/service.py:524-565` creates the activity
  and returns. It never updates `recommendations.state` or `alerts.status`.
- `backend/app/modules/plans/service.py:345-400` creates the activity and does
  not touch the recommendation either.

Result: a recommendation dispatched from the Action Center stays `open`
forever. Its unified status shows `dispatched` only because the linked activity
has an assignee (`backend/app/modules/action_center/repository.py:56-65`).
Nobody can move it to `done` or `dismissed` from this screen.

### G2. Two roles cannot act at all in the Action Center. Blocking.

Dispatch needs both `plan.manage` and `recommendation.act`
(`backend/app/modules/action_center/router.py:180-183`).

From `backend/app/shared/rbac/role_capabilities.yaml`:

| Role | Can act on /alerts today | Can act on /recommendations today | Can dispatch |
| --- | --- | --- | --- |
| TenantOwner | yes | yes | yes |
| TenantAdmin | yes | yes | yes |
| FarmManager | yes | yes | yes |
| Agronomist | yes, ack and resolve | yes | no, has no `plan.manage` |
| FieldOperator | yes, ack only | no | no |

An Agronomist who loses the two menu rows gets a read-only Action Center.

### G3. The four-horizon guidance is not carried.

`/recommendations` shows the immediate, short term, long term and monitoring
action lists (`RecommendationsPage.tsx:246-267`).

The backend reads `recommendations.actions` in the Action Center query
(`repository.py:107`) but uses it only to pick a due bucket
(`service.py:103-106`). It is not in `ActionItem`, so no client can show it.

### G4. The decision path is cut to one line.

`/recommendations` shows every step of the tree walk: node id, matched or not
matched, and the values compared (`RecommendationsPage.tsx:269-307`).

The Action Center shows one sentence built from the last matching condition
(`service.py:125-166`). The rest of `tree_path` never leaves the server.

### G5. Four native states collapse into one tab.

`deferred`, `expired`, `snoozed` and `dismissed` all map to the `dismissed` tab
(`repository.py:42-52`). A user cannot list only deferred recommendations or
only snoozed alerts. The row shows its own state as a pill, so the information
is visible after the filter, not in it.

### G6. The native state pill is untranslated.

`ItemRow.tsx:143` prints `item.native_status` as raw text: `acknowledged`,
`deferred`, `snoozed`. There is no key for it in
`src/i18n/locales/*/actionCenter.json`. Arabic users see English words.

### G7. Two alert timestamps are missing.

`/alerts` shows when an alert was acknowledged and when it was resolved
(`AlertsPage.tsx:100-111`). Neither field is in the Action Center payload.

### G8. The board link disappears before dispatch.

`/alerts` always offers "Open in Plan", falling back to the block lane
(`AlertsPage.tsx:116-126`). The Action Center hides the link until an activity
exists (`ItemRow.tsx:270`).

## What to build before hiding the two rows

In order. G1 and G2 are the ones that block the change.

1. Add a close action to the Action Center. Two options:
   - Add `POST /v1/action-items:transition` that maps one unified verb to the
     right native call for each kind, or
   - Add per-kind buttons to `ItemRow` that call the existing
     `PATCH /v1/recommendations/{id}` and `PATCH /v1/alerts/{id}`.
   The second is smaller and reuses the capability checks already written.
2. Split the capability check. Reading and closing must not need
   `plan.manage`. Keep `plan.manage` for dispatch only.
3. Return `recommendations.actions` on `ActionItem` and render the four
   horizons in the "why" panel.
4. Return the full `tree_path` and render the step list in the "why" panel.
5. Add a native-state filter next to the status tabs.
6. Add translation keys for every native state, English and Arabic.
7. Add `acknowledged_at` and `resolved_at` to `ActionItem` and show them.
8. Fall back to the block lane in the board link when there is no activity.

## Note on the two routes

`/alerts/:farmId` and `/recommendations/:farmId` must stay routed even after
the menu rows go. Email and in-app notifications deep-link to them:

- `backend/app/modules/notifications/subscribers.py:294`
- `backend/app/modules/notifications/subscribers.py:1097`

Repoint those two links to `/action-center/:farmId` before deleting the pages.
