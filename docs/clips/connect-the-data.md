# Clip script — Connect the data

Recording script for `guide-turn-on-imagery-and-weather.html` and
`guide-check-what-arrived.html`. Not published.

A silent capture is already published on the first guide. This is for the
narrated version.

- **Target length:** 8 minutes for the subscription, 5 for the health check.
- **Record on a farm that is not yet subscribed.** The whole point of the clip
  is the moment the tick happens.

---

## Take 1 — nothing is measured until you subscribe (0:00 to 1:00)

**On screen:** the farm map, no data on it.

**Say:** "The farm is mapped and the blocks are drawn, and so far AgriPulse has
measured nothing at all. Nothing is computed until the farm is subscribed. Both
subscriptions live on the farm, not on the blocks."

## Take 2 — turn on Sentinel-2 (1:00 to 3:00)

**Do:** gear, Farm tab, scroll to Satellite imagery. Read the sentence under the
heading out loud. Tick **Sentinel-2 L2A**. Let the two fields appear.

**Say:** "Turning a product on subscribes the whole farm. There is no separate
step for blocks. Sentinel-2 is the optical stream: NDVI, NDRE, the moisture
indices, all of it comes from here."

**Say, on the two fields:** "Every, in hours, is how often we look for a new
pass. Max cloud is the most cloud you will accept in one."

**Callout, and say it plainly:** "Be careful with the cloud limit. It rejects
passes at the provider, so the ones it throws away never arrive and leave no
trace. If every pass you have reads exactly zero cloud, that is the limit
talking, not the sky."

## Take 3 — what farm-level fetching costs (3:00 to 4:30)

**Do:** point at "Fetched as one farm area" and the paragraph under it.

**Say:** "The panel is honest about the trade. Fetching the farm as one area
measures land outside your blocks too, and costs one larger request per pass
instead of one per block. That is why land units matter: ground inside the
boundary that is not crop still gets measured unless you mark it."

## Take 4 — thermal, and when not to bother (4:30 to 5:30)

**Say:** "Landsat surface temperature is a second satellite. Coarser pixel,
longer gap between passes, and no grid cells at all. It gives you land surface
temperature and crop water stress. On bare ground the numbers are real and
useless, because the water stress index pins at its maximum when there is no
canopy to cool. Turn it on when you have a canopy worth measuring."

**Do:** leave it off for this recording.

## Take 5 — weather (5:30 to 6:30)

**Do:** tick **Open-Meteo**.

**Say:** "Weather is fetched once for the farm's location and shared by every
block, so there is nothing to set per block. History and forecast come from the
same provider, and the daily job turns them into growing degree days, reference
evapotranspiration and cumulative rainfall."

## Take 6 — the account defaults (6:30 to 8:00)

**Do:** Settings, Integrations, Imagery tab, then Weather tab.

**Say:** "Set the account default once, and override only the farms that
differ. Imagery holds the cloud threshold. Weather holds the provider and the
polling cadence. Pick a farm under Farm overrides to see the resolved chain."

---

# Second clip — Check what arrived

## Take 1 — where to look (0:00 to 1:30)

**Do:** Settings, Integrations, Health.

**Say:** "This shows when weather and imagery last synced for each farm, and it
refreshes every thirty seconds. Six views. Start on Overview."

## Take 2 — Failing does not always mean broken (1:30 to 3:30)

**Do:** show the farm you just subscribed. It will read Failing, Never synced,
one overdue. Then open **Runs**.

**Say:** "This is the part worth learning. Overview says Failing. Runs says no
recent ingestion attempts at all. Nothing failed. Nothing has run yet. The
sync is overdue because it has never happened. On a farm that used to sync,
Failing is a real problem, and Runs will tell you what the last attempt did."

**Callout:** the two screens side by side.

## Take 3 — read it per farm (3:30 to 4:30)

**Say:** "A farm fetched as one area has no per-block jobs. So the Blocks view
of a farm-level subscription looks dead even when everything is fine. Use Farms
for farm-level subscriptions and Blocks only for farms that still fetch per
block."

## Take 4 — history (4:30 to 5:00)

**Say:** "A new subscription starts today. Baselines need history, and without a
baseline nothing can be called an anomaly. Backfill is run by whoever operates
the platform, and it re-reads imagery for every pass in the range, so ask for it
deliberately."

---

## State of the clips in Connect the data

| Step | Clip | State |
| --- | --- | --- |
| Turn on imagery and weather | script written, silent draft published |
| Check what arrived | script written, not recorded |
