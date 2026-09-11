# Held decision-tree rules

A rule lands here when it is finished and reviewed but **an input it depends on
is not yet trustworthy**. Publishing it would open cards from a number nobody
should act on. Dropping it would throw away the review.

This file used to be `backend/app/modules/recommendations/seeds/held/README.md`,
next to the YAML files. Both the seed files and `sync_from_disk` are gone:
public migration 0085 carried the platform trees into the database and the app
is now the only way to author one. So the mechanism has changed, and the
mechanism section below is the part that needed rewriting. The agronomy did
not change at all.

## How to publish a held rule now

There is no file to move. A platform admin authors the tree at
`/platform/decision-trees`, saves it as a draft, dry-runs it, and publishes it
when the release condition below is met. Say in the publish notes what changed
about the input.

A tree that is authored but not yet trusted can also be left as an unpublished
draft, which is the closest thing to the old `held/` directory: the evaluator
only walks published versions, so a draft opens no cards.

---

## `mango_irrigation_stress_cwsi_v1`

Not authored in the database. The YAML and its unit test were removed from the
repository before the seeds directory was deleted, so what survives is the
reasoning, which is the part worth keeping.

**Held because `cwsi` is pinned at its ceiling.** On production, 7225 of 7320
`cwsi` rows read exactly 1.0000 on one tenant and 792 of 792 on the other —
98.7 % and 100 %. The index carries no variation to threshold against, so an
absolute-threshold rule on it would have opened 72 cards on its first
evaluation from a saturated input rather than from real water stress.

The cause is stated in the code that produces it
(`app/modules/indices/computation.py`, `CWSI_DT_WET_C` / `CWSI_DT_DRY_C`): the
canopy-to-air temperature bounds are literature constants for a well-coupled
orchard canopy, -2 °C to +6 °C, and have not been calibrated for Egyptian
mango. An Egyptian summer LST near 49 °C over a sparse canopy on bright sand
puts the canopy-air difference well past +6 °C, so `np.clip` returns 1.0. That
comment already says the output must be read as a relative signal over time and
"must not drive" irrigation volumes — which is exactly what an absolute
threshold would make it do.

**Release when** the CWSI bounds are calibrated for Egyptian mango — a
non-water-stressed baseline against vapour-pressure deficit (Idso's regression)
rather than two constants — and production `cwsi` shows a spread rather than a
ceiling. The rule's own thresholds come from the mango index guide and need no
change; only the input does.
