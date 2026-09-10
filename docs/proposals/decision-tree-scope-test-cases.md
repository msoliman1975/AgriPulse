# Decision tree authoring — user test cases

For the two authoring scopes added in #673: a platform admin editing the
platform catalogue, and a tenant admin working with the same trees.

Users:

| Scope | Login | Password | What the token carries |
| --- | --- | --- | --- |
| Platform | `dev@agripulse.local` | `dev` | `platform_role=PlatformAdmin`, `tenant_id` empty |
| Tenant | `msoliman_75@hotmail.com` | `Egypt@2011` | `tenant_role=TenantOwner`, `tenant_id` set |

Positive cases say what must happen. Negative cases say what must **not**
happen, and most of them are about the page telling the truth when a thing is
not allowed. A page that goes blank or states a false reason fails the case
even though nothing crashed.

## Platform scope

### P-1 (positive) — The catalogue lists and every tree is editable

1. Sign in as the platform admin.
2. Open `/platform/decision-trees`.

Expected: the table lists the platform trees and the count reads "Showing 41
of 41". Every row has an Archive button.

### P-2 (positive) — Country names read as names

Expected on the same page: the Locations column shows country names, not the
two-letter codes. The Filters control offers those names.

Why this case exists: `/v1/countries` needs a tenant, so a platform admin used
to get 403 and the column fell back to raw codes.

### P-3 (positive) — The crop picker can add a crop

1. Open any tree, for example `/platform/decision-trees/t_ndvi_canopy_vigour`.
2. Open the Crop select in Tree details.

Expected: the select lists real crops, not only "All crops". Choosing one
enables the Add button, and pressing Add puts a chip under the select.

### P-4 (positive) — Edit, save, publish

1. Change the Description (EN) field.
2. Press "Save as new draft".
3. Read the version history.

Expected: a new version appears marked as a draft, and the current version
does not move. Pressing "Publish v<n>" then makes it current.

### P-5 (positive) — Publishing an earlier version restores it

1. On a tree with more than one version, press Publish on an earlier version.

Expected: that version becomes current, and the name and description on the
page return to what that version carried.

### P-6 (positive) — Execution scope survives a save

1. Note the Execution scope radio on a tree.
2. Change nothing about it. Edit the description and save.

Expected: the radio still shows the same value, and the tree row still holds
the same scope. A tree authored per block must not become per grid cell.

### P-7 (negative) — No tenant-only panel is shown

Expected on the platform viewer: there is no "Dry-run on a block" panel, no
"Run on a farm" panel, no "Your overrides" panel, and no "How your farms run
this" panel.

Why this case exists: those four read tenant data. Left on the page they did
not fail quietly. Two of them printed "No blocks match this tree's crop /
country / soil targeting", which is a statement about the tree and was untrue —
the real reason was that a platform admin has no farms.

### P-8 (negative) — No console error while the page is idle

Expected: opening the list and the viewer produces no 403 in the browser
console.

## Tenant scope

### T-1 (positive) — The catalogue lists platform trees and own trees

1. Sign in as the tenant admin.
2. Open `/decision-trees`.

Expected: the list shows the platform trees. Any tree the tenant authored also
appears.

### T-2 (negative) — A platform tree cannot be edited, and the page says why

1. Open a platform tree from that list.

Expected: no "Save as new draft" button and no Publish button. The page shows
the sentence naming who owns the tree and what to do instead. The page must
not offer a Save that the server refuses.

### T-3 (positive) — The rollout panel reports the farms

Expected: the "How your farms run this" panel shows "Running on N of N farms"
with the tenant's real farm count.

### T-4 (positive) — Turn off across every farm, then back on

1. Press "Turn off everywhere".
2. Read the count.
3. Press "Turn on everywhere".

Expected: the count goes to 0 of N and the button changes to "Turn on
everywhere". Turning it back on returns the count to N of N.

### T-5 (positive) — The new-farm consequence is stated

Expected: while the tree is off everywhere, the panel shows the sentence
saying a farm added later will still run the tree.

Why this case exists: enable and disable are stored as one row per farm, and a
farm that does not exist yet has no row. Without this sentence, cards appear
from a tree the tenant turned off and nothing explains it.

### T-6 (positive) — Pin a version, then follow the current version again

1. Choose a version in "Version to hold" and press Apply.
2. Read the line above the select.
3. Choose "Follow the current version" and press Apply.

Expected: after step 1 the line reads "Held at version N". After step 3 it
returns to "Following the current version". The pin row must be gone from the
database, not only from the page.

### T-7 (negative) — A draft version cannot be pinned

Expected: the "Version to hold" select lists only published versions. A draft
must not appear.

Why this case exists: the sweep resolves a pinned version only when it is
published. Pinning a draft would remove the tree from the sweep with no
message, which is turning a tree off by accident.

### T-8 (positive) — Copy a platform tree

1. Press "Copy to my tenant".
2. Read the dialog.
3. Press Copy.

Expected: the dialog states the code rule, has "Turn the original off on my
farms" ticked, and states two things — open recommendations stay under the
original code, and the copy does not move when the platform publishes. After
Copy, the page opens the new tree and its code is the original code plus the
tenant name.

### T-9 (positive) — The copy is editable and the original is off

Expected: the copy has Save and Publish. The original then reads "Running on 0
of N farms".

### T-10 (negative) — A copy cannot take an existing code

1. Copy a tree and type the original's own code in the dialog.

Expected: the copy is refused with a message naming the code. Two trees must
not share one code, because a lookup by code would match both.
