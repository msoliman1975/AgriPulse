# Clip script — Create a farm

Recording script for the clip that sits on `guide-create-a-farm.html` and on
`process-map-the-farm.html`. Not published. This file is for whoever records.

- **Target length:** 4 minutes.
- **Recording account:** tenant `green-valley`, signed in as the tenant owner.
- **The farm must not exist yet.** The clip opens on the "No farms yet" empty
  state. Record this before you create any farm in that tenant.

---

## Before you press record

| Check | Why |
| --- | --- |
| Browser window at 1440 × 900, zoom 100% | Matches the screenshots in the guide. Text stays readable when the video is scaled down. |
| Bookmarks bar hidden, one tab only | Nothing personal on screen. |
| Notifications off on the machine | A pop-up in the middle of a take costs you the take. |
| Decide the boundary before recording | Know which four or five corners you will click. Hunting for the shape on camera looks slow. |
| Zoom the map to the farm first | A boundary drawn at low zoom is wrong, and the clip would teach the wrong habit. |
| Cursor size increased | The pointer is hard to follow at video scale. |

### Three known problems that show on camera

Fix these before recording, or accept them.

1. **`GET /api/v1/me` returns 500 on this tenant.** The tenant name does not
   appear in the top bar, so "Green Valley Farms" is never visible. If it is
   fixed before the shoot, the badge appears and the clip looks complete.
2. **The top bar reads "Moahmed ElSayed".** Misspelled, and not the name you
   would want on a published video. Change the display name in Keycloak.
3. **The sidebar lists "Farm management" twice**, one marked BETA. Viewers will
   ask about it. Either hide the beta entry for the recording account, or say
   one sentence about it and move on.

---

## Shot list

### 1 — The empty workspace (0:00 to 0:25)

**On screen:** the workspace on "No farms yet".

**Say:** "This is a new AgriPulse account. There are no farms yet, so almost
everything in the sidebar is greyed out. Insights, Plan, Signals and the rest
all need a farm to point at. So the first thing we do is create one."

**Do:** hover the greyed sidebar items briefly, then move to the button.

---

### 2 — Open the flow (0:25 to 0:40)

**On screen:** click **Create your first farm**. The map opens on satellite
imagery, panel reads "New farm — Step 1 of 2 · boundary".

**Say:** "Creating a farm takes two screens. First the boundary, then the
details. The map opens on satellite imagery so you can trace the real field
edges."

**Callout to add in editing:** box around "Step 1 of 2 · boundary".

---

### 3 — Why the boundary matters (0:40 to 1:00)

**On screen:** stay on step 1. Zoom in one or two levels on the farm.

**Say:** "Before drawing, zoom in. Everything AgriPulse computes for this farm
happens inside this line: every index, every block, every grid cell. A boundary
traced from too far out is wrong by tens of metres, and that error follows you
all season."

---

### 4 — Draw the boundary (1:00 to 1:50)

**On screen:** click **Draw boundary**. Click each corner. Double-click the last
corner to close the shape.

**Say:** "Click once at each corner of the farm. Double-click the last one to
close the shape. Draw the outer boundary only. The blocks come later, inside
it. And include the roads and buildings that sit inside the farm. We mark those
as land units afterwards, so they stop counting towards the crop numbers."

**Do:** draw slowly. Four or five corners is enough.

**Alternative to mention, not to demonstrate:** "If a surveyor already gave you
the boundary, use Upload file instead. It takes KML, GeoJSON, or a Shapefile in
a zip."

---

### 5 — Check the area (1:50 to 2:15)

**On screen:** the panel now reads step 2, with the area in the header, for
example "185.5 feddan".

**Say:** "As soon as the shape closes, the panel shows the area. Check it
against what you know the farm to be. If the number is far out, the shape is
wrong, not the calculation. Click Boundary and draw it again. It is much
cheaper to fix now than after the blocks are in."

**Callout:** circle the area figure.

---

### 6 — The two required fields (2:15 to 2:55)

**On screen:** type the Code, then the Name, then pick the Country.

**Say:** "Only two fields are required. Code is the short identifier your team
already uses. Name is the readable one. Watch the Create farm button: it stays
disabled until both are filled."

**Do:** show the button greyed, type the code, show it still greyed, type the
name, show it turn green. That contrast is the most useful three seconds in the
clip.

**Say:** "Country is optional, but set it. Decision trees can be written for a
region, and a farm with no country matches none of them."

---

### 7 — More details (2:55 to 3:25)

**On screen:** expand **More details**, scroll the panel.

**Say:** "Everything under More details is optional and you can add it later.
Description, location, farm type, ownership, water source, established date,
tags. If you know the water source now, set it. It gives context to anyone
reading a report about this farm later."

**Do:** do not fill them all on camera. Fill one, then collapse.

---

### 8 — Create it (3:25 to 3:50)

**On screen:** click **Create farm**. The farm appears in the picker, the
sidebar comes alive.

**Say:** "Create farm. The farm is now in the picker at the top, and the
workspace pages are no longer greyed out. Everything except the boundary can be
changed later in Farm settings."

---

### 9 — Close (3:50 to 4:00)

**Say:** "That is the farm shell. Next we cut it into blocks, set the grid cell
size, and mark the land units. That is the next clip."

**On screen:** end on the farm loaded in the workspace.

---

## After the recording

- Trim the sign-in. Start the clip already signed in.
- Add the three callouts named above.
- Captions in English. Arabic captions when the Arabic pages are written.
- Export at 1920 × 1080. The source is 1440 × 900, so it scales cleanly.
- Drop the file into the video slot on `guide-create-a-farm.html` and on step 1
  of `process-map-the-farm.html`.

## The next clips in this process

| Step | Clip | State |
| --- | --- | --- |
| 1 | Create the farm | script written, not recorded |
| 2 | Add the blocks | not written |
| 3 | Set the grid cell size | not written |
| 4 | Mark the land units | not written |
| 5 | Attach the people | not written |
