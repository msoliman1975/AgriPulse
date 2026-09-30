"""Ewais Grove: two seasons of a drip-irrigated mango farm near Ismailia.

The span is 2024-09-29 to 2026-09-28. The farm is 36 blocks, B01 in the
north-west to B36 in the south-east: Ewais on B01-B24, Keitt on B25-B36.
All trees are small (NDVI 0.12 to 0.26 over the whole span) and bearing.

The values are set against this farm's own readings and the tenant's
tree parameter overrides:

* water tree, small trees: leaf water floor NDMI -0.15 (the farm runs
  -0.12 to -0.04); soil moisture floor SMI 0.02 and deficit floor 0.01
  (the farm's SMI is noisy, 5th percentile 0.015, median 0.21); CWSI is
  switched off, because it sits at 0.97 to 0.995 on this desert site.
* feeding tree: NDRE floor 0.05 (farm 0.06 to 0.16), GNDVI floor 0.24
  (farm 0.27 to 0.40).
* canopy tree: MSAVI floor 0.10 (farm 0.11 to 0.21).

In the maturation window a bearing block's water walk asks one question
only: did the pre-harvest irrigation cut happen? So the cut itself is
part of the scenario, and it is a `set` shift, because the tree tests a
band (0.01 <= SMI < 0.02) that a noisy reading would never stay in.
Ewais matures 1 July to 15 September; Keitt 16 August to 31 October.

What each incident is for:

1. The pre-harvest cut, done on plan on every block but one, so the
   water tree reads "cut on plan" through each harvest.
2. B18 forgets the cut in 2025, so the tree reads "cut missing".
3. A drip lateral breaks on B14 in July 2025, in the middle of the cut,
   so the cut goes too deep and the tree reads "overshot", critical.
4. A nitrogen shortfall on three Keitt blocks in spring 2025, found by
   the feeding tree and fixed with a feed.
5. Lasiodiplodia dieback on B21 from November 2025, pruned in February
   2026 and slowly regrown, found by the canopy tree.
6. A lateral break on B33 during fruit set in April 2026: leaf and soil
   both dry, an irrigation alert.
7. The well 1 pump fails in the June 2026 heat: the six northern blocks
   dry out together for four days. One alert per block, one morning.

Weather-driven findings, such as mildew pressure at flowering, come from
the real weather and are not scripted here.
"""

from __future__ import annotations

from datetime import date

from app.modules.demo_history.incidents import Incident, Shift

FARM_CODE = "EWG-01"

_EWAIS = tuple(f"B{n:02d}" for n in range(1, 25))
_KEITT = tuple(f"B{n:02d}" for n in range(25, 37))

# The band the water tree reads as "cut on plan": 0.01 <= SMI < 0.02.
_CUT = (Shift("smi", 0.015, mode="set"),)


def _cut(code: str, blocks: tuple[str, ...], start: date, until: date) -> Incident:
    """The pre-harvest cut: a week to bring soil moisture down, then held."""
    full = min(date.fromordinal(start.toordinal() + 7), until)
    return Incident(
        code=code,
        title="Pre-harvest irrigation cut",
        blocks=blocks,
        start=start,
        full=full,
        until=until,
        gone=date.fromordinal(until.toordinal() + 1),
        shifts=_CUT,
    )


INCIDENTS: tuple[Incident, ...] = (
    # --- the cut, every harvest in the span ---------------------------
    _cut("cut_keitt_2024", _KEITT, date(2024, 9, 29), date(2024, 10, 31)),
    _cut(
        "cut_ewais_2025",
        tuple(b for b in _EWAIS if b != "B18"),
        date(2025, 7, 1),
        date(2025, 9, 15),
    ),
    _cut("cut_keitt_2025", _KEITT, date(2025, 8, 16), date(2025, 10, 31)),
    _cut("cut_ewais_2026", _EWAIS, date(2026, 7, 1), date(2026, 9, 15)),
    _cut("cut_keitt_2026", _KEITT, date(2026, 8, 16), date(2026, 9, 27)),
    # --- problems ------------------------------------------------------
    Incident(
        code="nitrogen_shortfall_2025",
        title="Nitrogen shortfall on three Keitt blocks",
        blocks=("B28", "B29", "B30"),
        start=date(2025, 3, 10),
        full=date(2025, 4, 5),
        until=date(2025, 4, 25),
        gone=date(2025, 5, 20),
        shifts=(
            Shift("ndre", -0.08),
            Shift("gndvi", -0.13),
            Shift("ndvi", -0.04),
        ),
    ),
    Incident(
        # Applied after the Ewais cut, so it pulls the cut's 0.015 down
        # below the 0.01 deficit floor on most of the block.
        code="drip_break_during_cut_2025",
        title="Drip lateral break during the pre-harvest cut",
        blocks=("B14",),
        start=date(2025, 7, 14),
        full=date(2025, 7, 17),
        until=date(2025, 7, 26),
        gone=date(2025, 8, 3),
        cells="share:0.7",
        shifts=(
            Shift("smi", 0.0, mode="set"),
            Shift("ndmi", -0.14),
            Shift("ndvi", -0.05),
        ),
    ),
    Incident(
        code="dieback_2025",
        title="Lasiodiplodia dieback, pruned in February",
        blocks=("B21",),
        start=date(2025, 11, 1),
        full=date(2026, 1, 20),
        until=date(2026, 2, 10),
        gone=date(2026, 4, 30),
        cells="share:0.5",
        shifts=(
            Shift("ndvi", -0.12),
            Shift("msavi", -0.10),
            Shift("savi", -0.10),
            Shift("ndre", -0.06),
            Shift("bsi", 0.06),
        ),
    ),
    Incident(
        code="lateral_break_fruit_set_2026",
        title="Lateral break during fruit set",
        blocks=("B33",),
        start=date(2026, 4, 6),
        full=date(2026, 4, 9),
        until=date(2026, 4, 18),
        gone=date(2026, 4, 26),
        cells="share:0.8",
        shifts=(
            Shift("ndmi", -0.12),
            Shift("smi", -0.45),
        ),
    ),
    Incident(
        code="well_pump_failure_2026",
        title="Well 1 pump failure in the June heat wave",
        blocks=("B01", "B02", "B03", "B04", "B05", "B06"),
        start=date(2026, 6, 14),
        full=date(2026, 6, 17),
        until=date(2026, 6, 20),
        gone=date(2026, 6, 30),
        shifts=(
            Shift("ndmi", -0.11),
            Shift("smi", -0.45),
        ),
    ),
)
