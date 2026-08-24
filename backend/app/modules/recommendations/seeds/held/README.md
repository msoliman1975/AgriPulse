# Held seeds — written, tested, not published

`sync_from_disk` reads `seeds/*.yaml` with a non-recursive glob, so nothing in
this directory is inserted into `public.decision_trees` or evaluated against a
block. A tree lands here when the rule itself is finished and reviewed but an
**input it depends on is not yet trustworthy**. Deleting it would throw away
the review; publishing it would open cards from a number nobody should act on.

To publish one, move the file up to `seeds/` and let startup sync pick it up.
Say in the commit what changed about the input.

Each held tree must be listed below with the specific condition that releases it.

---

## `mango_irrigation_stress_cwsi_v1`

**Held because `cwsi` is pinned at its ceiling.** On prod, 7225 of 7320
`cwsi` rows read exactly 1.0000 on one tenant and 792 of 792 on the other —
98.7 % and 100 %. The index carries no variation to threshold against, so an
absolute-threshold rule on it would have opened 72 cards on its first
evaluation from a saturated input rather than from real water stress.

The cause is stated in the code that produces it
(`app/modules/indices/computation.py`, `CWSI_DT_WET_C` / `CWSI_DT_DRY_C`):
the canopy-to-air temperature bounds are literature constants for a
well-coupled orchard canopy, -2 °C to +6 °C, and have not been calibrated for
Egyptian mango. An Egyptian summer LST near 49 °C over a sparse canopy on
bright sand puts the canopy-air difference well past +6 °C, so `np.clip`
returns 1.0. That comment already says the output must be read as a relative
signal over time and "must not drive" irrigation volumes — which is exactly
what an absolute threshold would make it do.

**Release when** the CWSI bounds are calibrated for Egyptian mango — a
non-water-stressed baseline against vapour-pressure deficit (Idso's
regression) rather than two constants — and prod `cwsi` shows a spread rather
than a ceiling. The tree's own thresholds come from the mango index guide and
need no change; only the input does.

The rule is exercised by
`backend/tests/unit/recommendations/test_mango_index_guide_trees_held.py`, so
it cannot rot while it waits.
