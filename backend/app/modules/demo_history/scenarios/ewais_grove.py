"""Ewais Grove: two seasons of a drip-irrigated mango farm near Ismailia.

The span is 2024-09-29 to 2026-09-28. The farm is 36 blocks, B01 in the
north-west to B36 in the south-east, 24 of Ewais and 12 of Keitt.

Each incident is something an Egyptian mango farm meets in a normal
year, placed where the calendar makes it matter, so each workflow screen
has a case to show:

1. Nitrogen shortfall in spring 2025, three Keitt blocks, found by the
   feeding tree and fixed with a feed.
2. A drip lateral break in the July 2025 heat, one block, most of it
   dry. The water tree's three readings agree and it raises an alert.
3. Lasiodiplodia dieback from November 2025 in one block, a slow canopy
   decline over three months, pruned out in February 2026 and slowly
   regrown.
4. A well pump failure in June 2026: the six northern blocks lose water
   for four days in a heat wave. One incident, six blocks, one morning.
5. A second, smaller lateral break in August 2026 on a Keitt block in its
   maturation window, so the pre-harvest deficit reads as overshot.

Weather-driven findings, such as mildew pressure at flowering, come from
the real weather and are not scripted here.
"""

from __future__ import annotations

from datetime import date

from app.modules.demo_history.incidents import Incident, Shift

FARM_CODE = "EWG-01"

INCIDENTS: tuple[Incident, ...] = (
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
            Shift("gndvi", -0.09),
            Shift("ndvi", -0.04),
        ),
    ),
    Incident(
        code="drip_lateral_break_2025",
        title="Drip lateral break in the July heat",
        blocks=("B14",),
        start=date(2025, 7, 8),
        full=date(2025, 7, 13),
        until=date(2025, 7, 24),
        gone=date(2025, 8, 4),
        cells="share:0.7",
        shifts=(
            Shift("ndmi", -0.14),
            Shift("smi", -0.45),
            Shift("cwsi", 0.45),
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
        code="well_pump_failure_2026",
        title="Well 1 pump failure in the June heat wave",
        blocks=("B01", "B02", "B03", "B04", "B05", "B06"),
        start=date(2026, 6, 14),
        full=date(2026, 6, 17),
        until=date(2026, 6, 20),
        gone=date(2026, 6, 30),
        shifts=(
            Shift("ndmi", -0.10),
            Shift("smi", -0.40),
            Shift("cwsi", 0.40),
        ),
    ),
    Incident(
        code="lateral_break_keitt_2026",
        title="Lateral break on a Keitt block before harvest",
        blocks=("B33",),
        start=date(2026, 8, 20),
        full=date(2026, 8, 24),
        until=date(2026, 9, 2),
        gone=date(2026, 9, 12),
        cells="share:0.8",
        shifts=(
            Shift("ndmi", -0.12),
            Shift("smi", -0.45),
            Shift("cwsi", 0.40),
        ),
    ),
)
