"""Medjool Oasis: two seasons of a Medjool date palm demo farm.

The farm is MDJ-DEMO in the palm-medjool demo tenant: the boundary and the
13 M blocks of Al Ashraf (farm Al001), whose history is copied rather than
backfilled again (`copy_history`). The span is 15 October 2024 to
15 October 2026: two full seasons, each with winter cold, flower emergence
and pollination (February to April), summer heat, and ripening and
harvest (August to October).

Four blocks carry the story, chosen from their real readings:

* M28, the healthy reference: bearing, large palms, steady NDVI. Only
  events from outside touch it (cold, rain, a pump failure).
* M2, the typical bearing block: the operational incidents.
* M5, large and patchy, reaching bearing in March 2026: a recurring
  nitrogen zone.
* M31, tissue-culture plantings from March 2024, on slightly saline sand,
  with the steepest real decline: the young-block story.

The other nine blocks carry their real history and no incident.

The trees this is written for:

* Tree crops - canopy vigour and stand, and Tree crops - feeding, per cell.
  They read the index rows the incidents below move.
* Date palm Medjool - cold injury, from a steered cold snap.
* Rain at pollination and ripening, heat units, and the seasonal
  operations calendar, from the real weather and growth stages. Rain fell
  in March 2025, March 2026 and on 26-27 September 2026.

Readings on this farm are low because a 10 m pixel over palms at 8 x 8 m
on sand is mostly soil: NDVI 0.074 to 0.110 (block means, 5th to 95th
percentile), MSAVI 0.073 to 0.104, BSI 0.185 to 0.223, NDMI -0.138 to
-0.092, NDRE 0.016 to 0.055, GNDVI 0.233 to 0.290. The shifts below are
sized against that spread, so an incident moves a cell well past the
tenant's history-derived floors (about the 10th percentile) and its
z-score past -2, and a chart shows it plainly without leaving the range
the farm can produce.

Cells are given by their grid position. The grid is 40 m, and the row and
column numbers are absolute UTM grid positions:

* M2: columns 9712-9716, rows 81100-81112 (63 cells).
* M5: columns 9716-9721, rows 81095-81109 (81 cells).
* M28: columns 9712-9716, rows 81134-81135 (10 cells).
* M31: columns 9711-9716, rows 81139-81145 (26 cells).
"""

from __future__ import annotations

from datetime import date

from app.modules.demo_history.copy_history import CopySource
from app.modules.demo_history.incidents import Incident, Shift, WeatherIncident
from app.modules.demo_history.people import AttributeChange, TeamPolicy

FARM_CODE = "MDJ-DEMO"

SPAN = (date(2024, 10, 15), date(2026, 10, 15))

COPY_SOURCE = CopySource(
    schema="tenant_01a1e2bf2d617d20aff8e268bda2db0b",
    farm_code="Al001",
    block_prefix="M",
)

INCIDENTS: tuple[Incident, ...] = (
    # 1. Establishment gaps: a corner of the March 2024 tissue-culture
    #    planting fails on saline sand. Bare soil rises where palms died.
    #    Replanted mid-January; the patch closes by spring.
    Incident(
        code="mdj-01-m31-establishment-gaps",
        title="M31 establishment gaps in the young planting",
        blocks=("M31",),
        cells="rows:81139-81141",
        start=date(2024, 11, 5),
        full=date(2024, 11, 25),
        until=date(2025, 1, 15),
        gone=date(2025, 3, 31),
        shifts=(
            Shift("msavi", -0.035),
            Shift("savi", -0.035),
            Shift("ndvi", -0.035),
            Shift("bsi", 0.06),
        ),
    ),
    # 4. Nitrogen shortfall at fruit set on the north rows of M5. The
    #    feed goes on in April and the zone recovers in May.
    Incident(
        code="mdj-04-m5-nitrogen-2025",
        title="M5 nitrogen shortfall at fruit set",
        blocks=("M5",),
        cells="rows:81095-81099",
        start=date(2025, 3, 5),
        full=date(2025, 3, 20),
        until=date(2025, 4, 10),
        gone=date(2025, 5, 5),
        shifts=(Shift("ndre", -0.035), Shift("gndvi", -0.015)),
    ),
    # 5. A drip lateral breaks along one column of M2 in the June heat:
    #    a dry stripe, then a weaker canopy along it. Repaired late June.
    Incident(
        code="mdj-05-m2-lateral-break",
        title="M2 drip lateral break, dry stripe",
        blocks=("M2",),
        cells="cols:9714-9714",
        start=date(2025, 6, 8),
        full=date(2025, 6, 12),
        until=date(2025, 6, 26),
        gone=date(2025, 7, 15),
        shifts=(
            Shift("ndmi", -0.08),
            Shift("savi", -0.025),
            Shift("ndvi", -0.025),
            Shift("msavi", -0.025),
        ),
    ),
    # 7. Iron chlorosis on the calcareous west side of M2 (pH 8.3): the
    #    leaves pale (GNDVI) while red-edge nitrogen stays normal, which is
    #    what sends the feeding tree down its chlorophyll branch.
    Incident(
        code="mdj-07-m2-iron-chlorosis",
        title="M2 iron chlorosis on the calcareous west side",
        blocks=("M2",),
        cells="cols:9712-9713",
        start=date(2026, 2, 1),
        full=date(2026, 2, 20),
        until=date(2026, 3, 10),
        gone=date(2026, 4, 10),
        shifts=(Shift("gndvi", -0.05),),
    ),
    # 9. The same M5 rows run short of nitrogen again in spring 2026: a
    #    recurring zone, which is what leads to the soil test and a
    #    variable-rate feed.
    Incident(
        code="mdj-09-m5-nitrogen-2026",
        title="M5 nitrogen shortfall again in the same zone",
        blocks=("M5",),
        cells="rows:81095-81099",
        start=date(2026, 4, 1),
        full=date(2026, 4, 15),
        until=date(2026, 5, 5),
        gone=date(2026, 5, 30),
        shifts=(Shift("ndre", -0.04), Shift("gndvi", -0.015)),
    ),
    # 10. First full summer for the young palms on sand: leaf water drops
    #     across M31 until the irrigation regime is raised.
    Incident(
        code="mdj-10-m31-first-summer-heat",
        title="M31 first-summer heat stress on sand",
        blocks=("M31",),
        start=date(2026, 6, 5),
        full=date(2026, 6, 20),
        until=date(2026, 7, 15),
        gone=date(2026, 8, 5),
        shifts=(
            Shift("ndmi", -0.07),
            Shift("msavi", -0.025),
            Shift("savi", -0.025),
            Shift("ndvi", -0.02),
        ),
    ),
    # 11. The well pump serving M28 and M2 fails in the July heat. Both
    #     blocks go dry together for four days, then recover once it is
    #     repaired.
    Incident(
        code="mdj-11-pump-failure",
        title="Well pump failure on M28 and M2",
        blocks=("M28", "M2"),
        start=date(2026, 7, 8),
        full=date(2026, 7, 9),
        until=date(2026, 7, 11),
        gone=date(2026, 7, 16),
        shifts=(Shift("ndmi", -0.09),),
    ),
)

WEATHER_INCIDENTS: tuple[WeatherIncident, ...] = (
    # 2. A cold outbreak on top of the real cool spell of late February
    #    2025 (real minimums 4.7 to 5.5 C). Nights reach -6.5 C, past the
    #    cold tree's -5 C irrigate-ahead line and its -6 C leaflet line.
    WeatherIncident(
        code="mdj-02-cold-snap-2025",
        title="Cold snap, nights to -6.5 C",
        start=date(2025, 2, 23),
        full=date(2025, 2, 24),
        until=date(2025, 2, 26),
        gone=date(2025, 2, 28),
        min_temp_c=-6.5,
    ),
)

# Dated changes to the crop records, made by the agronomist.
ATTRIBUTE_CHANGES: tuple[AttributeChange, ...] = (
    AttributeChange(on=date(2026, 3, 1), block="M5", attributes={"palm_phase": "bearing"}),
    AttributeChange(on=date(2026, 4, 1), block="M31", attributes={"palm_phase": "juvenile"}),
)

TEAM_POLICY = TeamPolicy(
    product_for_activity={
        "irrigation": (None, "Add 1.5 h to each drip cycle for 7 days, check emitters"),
        "fertilizing": (
            "Ammonium sulphate 20.6% N",
            "2 kg per palm through the drip, split in two",
        ),
        "spraying": ("Fe-EDDHA 6% chelate", "50 g per palm in the drip, repeat after 3 weeks"),
        "pruning": (None, "Remove dry fronds and old frond bases, burn the cuttings"),
        "harvesting": (None, "Pick at rutab to tamar, bunch by bunch, into lined crates"),
        "observation": (None, "Walk the block, check emitters and 10 palms per row"),
    },
    dismiss_reasons=(
        "Checked on the ground. Emitters run and the palms look normal.",
        "Already in this week's program.",
        "Dust on the image after the khamaseen. The block was fine in the field.",
        "Seen by the agronomist. We will check again at the next pass.",
    ),
    defer_note="Waiting for the next image before acting.",
    skip_note="Crew moved to pollination on another block. Rescheduled on the board.",
    irrigation_skip_note="Well maintenance this evening. Next cycle tomorrow.",
)
