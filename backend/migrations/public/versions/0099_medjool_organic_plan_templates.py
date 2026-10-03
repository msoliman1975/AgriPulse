"""Two organic Medjool plan templates from the Organic Medjool Manual.

* ``medjool-organic-bearing-eg``: section 12, the 52-week plan for bearing
  palms. Each of the 28 activities is anchored to one of the nine Medjool
  stages from 0097, and its offset is the manual's week number counted from
  the week that stage starts.
* ``medjool-organic-new-planting-eg``: section 8.8, from 8 weeks before
  planting to year 5. Anchored on the block's start date, which is the field
  planting week (W0).

Rules followed:

* Nothing outside the manual. Product names and doses are the manual's.
  Where the manual says a value was not found (section 13), the note says so.
* Repeated work ("every 7-14 days", "daily") is one activity spanning its
  window, with the frequency in the note. Plans have no recurrence.
* Each note ends with the manual's source numbers and confidence level, and,
  where the cited source was checked on 3 Oct 2026 and differed, a
  "Source check" line saying how.
* Inputs: the manual's section 5 note is repeated on every input activity:
  check it against the certifying body's list of permitted inputs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0099"
down_revision: str | Sequence[str] | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PATH = "date_palm.medjool"
_CERTIFIER = "Check the input against the certifying body's list of permitted inputs (manual 5.1)."

# Week each stage starts, from 0097 (week 1 starts 1 January).
_STAGE_START_WEEK = {
    "dormancy": 1,
    "pollination": 6,
    "fruit_set": 11,
    "kimri": 16,
    "khalal": 27,
    "rutab": 31,
    "tamar": 35,
    "harvest": 37,
    "post_harvest": 42,
}


def _weeks(stage: str, first: int, last: int) -> tuple[int, int]:
    """(offset_days, duration_days) for manual weeks first..last from a stage start.

    The manual's week 52 runs 24-31 December, 8 days, so a window ending in
    week 52 gets one more day and reaches 31 December.
    """
    duration = 7 * (last - first + 1) + (1 if last == 52 else 0)
    return 7 * (first - _STAGE_START_WEEK[stage]), duration


# (activity_type, stage, first_week, last_week, product, dosage, notes)
BEARING: list[tuple] = [
    (
        "irrigation",
        "dormancy",
        1,
        8,
        None,
        None,
        "Winter regime (December-February): reduce irrigation, do not stop it. FAO reference "
        "about 4,372 m³/ha for December-February; Medjool in Dakhla was irrigated once a week "
        "in winter; a UAE calendar gives every 6-7 days. How often: 1x per week. "
        "Source [4] [10] [42] · Medium.",
    ),
    (
        "irrigation",
        "post_harvest",
        49,
        52,
        None,
        None,
        "Winter regime (December-February): reduce irrigation, do not stop it. Medjool in "
        "Dakhla was irrigated once a week in winter. How often: 1x per week. "
        "Source [4] [10] [42] · Medium.",
    ),
    (
        "trap_service",
        "dormancy",
        1,
        52,
        "Pheromone traps (food bait and water)",
        "0.5-1 trap per ha",
        "Red palm weevil: service pheromone traps - change food bait and water - and record "
        "the catch per trap. Runs all year. How often: 1x every 7-14 days. "
        "Source [8] · Medium. Source check: the FAO guideline [8] could not be opened.",
    ),
    (
        "observation",
        "dormancy",
        1,
        52,
        None,
        None,
        "Red palm weevil: visual inspection of palms for symptoms and stages; heavily "
        "infested palms are removed and disposed of. Runs all year. How often: regular "
        "inspection; the sources give no number per week. Source [8] [9] · Medium.",
    ),
    (
        "fertilizing",
        "dormancy",
        1,
        4,
        "Well-matured manure, or filter mud + poultry manure",
        "20-50 kg manure per palm every 2 years; Dakhla trial best: filter mud 25 kg + poultry manure 25 kg per palm",
        "Organic fertilisation of mature palms, every 2 years. The sources do not state the "
        "month of application; weeks 1-4 are a placement only (manual section 13). "
        + _CERTIFIER
        + " How often: 1 application every 2 years. Source [3] [10] · Low. Source check: "
        "the 20-50 kg figure was not found on the cited FAO page [3]; the Dakhla trial [10] matches.",
    ),
    (
        "soil_prep",
        "dormancy",
        2,
        9,
        "Topsoil + well-matured manure",
        "10-15 kg manure per hole",
        "Prepare planting holes 1-2 months before spring planting: topsoil + 10-15 kg "
        "well-matured manure, with at least 15-20 cm of soil between manure and roots. "
        + _CERTIFIER
        + " How often: once per planting hole. Source [3] · Medium.",
    ),
    (
        "pruning",
        "dormancy",
        3,
        5,
        None,
        None,
        "Dethorning and removal of dead fronds at the end of the dormant period, to give "
        "access to emerging spathes before pollination. How often: once per palm per season. "
        "Source [29] · Low.",
    ),
    (
        "pollination",
        "dormancy",
        5,
        13,
        None,
        None,
        "Pollen: collect male spathes as they open; dry the pollen and store it dry in "
        "tightly closed bottles. Viable about 4 weeks at cold or room temperature; -30 °C "
        "gives the best longer storage. How often: as each male spathe opens; the sources "
        "give no fixed number. Source [12] [13] · Medium.",
    ),
    (
        "observation",
        "pollination",
        6,
        13,
        None,
        None,
        "Inspect female palms for spathe cracking every day: Medjool receptivity is only "
        "about 3 days. How often: daily (7x per week). Source [11] · High. Source check: "
        "the cited article [11] is about the cultivar Assiane and gives no Medjool "
        "receptivity figure; it says pollination should not be delayed more than 3-4 days.",
    ),
    (
        "pollination",
        "pollination",
        6,
        13,
        None,
        None,
        "Pollinate each opened female spathe within 2-4 days of opening (traditional: "
        "insert 2-3 male strands into the female cluster); repeat a second pass 3-4 days "
        "later. Record the pollination date per bunch. How often: 2 passes per spathe. "
        "Source [5] [6] [11] · Medium. Source check: the 2-4 day and 3-4 day timing matches "
        "[5]; the 2-3 male strands method was not found on [6].",
    ),
    (
        "bagging",
        "pollination",
        6,
        13,
        "Kraft paper bag",
        "1 bag per pollinated inflorescence",
        "If low temperatures are expected, cover each pollinated inflorescence with a kraft "
        "paper bag. The manual gives no temperature. "
        + _CERTIFIER
        + " How often: once per pollinated inflorescence, only when cold is expected. "
        "Source [5] · Medium. Source check: [5] says paper bags for low temperature; it "
        "names kraft paper for the ripening season.",
    ),
    (
        "spraying",
        "pollination",
        6,
        13,
        "Bacillus thuringiensis (Bt) dust",
        None,
        "Lesser date moth: Bt dust applied at pollination (practice reported from Iraq). "
        + _CERTIFIER
        + " How often: once, at pollination. Source [20] · Medium. Source check: [20] reports "
        "Bt treatments in Iraq but gives no timing.",
    ),
    (
        "irrigation",
        "pollination",
        9,
        15,
        None,
        None,
        "Flowering, pollination and fruit set (March to mid-April): irrigation is important "
        "after spathe emergence and at regular intervals after fruit set. How often: 1-2x per "
        "week; the sources give no number for this period (manual section 13). "
        "Source [5] · Low.",
    ),
    (
        "irrigation",
        "pollination",
        10,
        52,
        None,
        None,
        "New plantings of this season (offshoots or tissue-culture plants): irrigate them on "
        "their own schedule (the new-planting template) - light, frequent irrigation, water "
        "kept away from the heart. How often: first summer: sandy soil daily, most soils every "
        "2-3 days, heavy soil 1x per week; outside the first summer the sources give no "
        "number. Source [2] [4] [39] · Medium. Source check: the soil-type frequencies are on "
        "FAO page [3], not [4].",
    ),
    (
        "planting",
        "pollination",
        10,
        17,
        None,
        None,
        "Offshoot removal and spring planting window (March/April): offshoots 3-4 years old "
        "and 12-20 kg; keep a 5-8 cm soil ball on the roots; root in a nursery 1-2 years "
        "before field planting. How often: once per offshoot. Source [2] [3] · Medium. "
        "Source check: [2] says offshoots of at least 3-5 years and 10-25 kg; the soil ball "
        "and nursery period match.",
    ),
    (
        "spraying",
        "fruit_set",
        13,
        13,
        "Bacillus thuringiensis (Bt) spray",
        None,
        "Lesser date moth: Bt spray two weeks after the reference pollination (fruit set). "
        + _CERTIFIER
        + " How often: once, 2 weeks after pollination. Source [20] · Medium. Source check: "
        "[20] gives no timing for Bt.",
    ),
    (
        "thinning",
        "fruit_set",
        14,
        15,
        None,
        None,
        "Hand thinning 3-4 weeks after pollination: reduce to about 30 strands per bunch and "
        "10 fruits per strand (Medjool, Israel). Methods: cut back strand tips (about one "
        "quarter) and remove inner strands. Alternative reported in Arizona: 15-20 fruits per "
        "strand, about 35 strands per bunch. How often: once per bunch, 3-4 weeks after its "
        "pollination. Source [5] [30] · High. Source check: [5] says cut the lower one third "
        "of the strands, not one quarter.",
    ),
    (
        "thinning",
        "fruit_set",
        14,
        15,
        None,
        None,
        "Adjust bunch number to leaf area: reference ratio 8-9 leaves per bunch with no more "
        "than 15 bunches. This is a Deglet Noor reference; a Medjool ratio was not found "
        "(manual section 13). How often: once per palm per season. Source [7] · Medium.",
    ),
    (
        "irrigation",
        "kimri",
        16,
        26,
        None,
        None,
        "Kimri (mid-April to June): keep soil moisture steady with drip and avoid abrupt "
        "wet-dry cycles, a main cause of fruit cracking. A Medjool drip study supplied about "
        "3 m³ per tree per week from mid-April to the end of July. How often: 1-2x per week; "
        "the sources give no number for this period. Source [18] [43] · Low. Source check: "
        "[43] could not be opened.",
    ),
    (
        "bending",
        "kimri",
        16,
        22,
        "Twisted leaflets, rope or twine",
        None,
        "Check fruit stalks weekly; bend and tie each bunch once its stalk is fully extended "
        "but still flexible. How often: check 1x per week; bend and tie once per bunch. "
        "Source [5] · Low. Source check: [5] says the bunch is tied when the fruit stalk is "
        "fully extended but still flexible.",
    ),
    (
        "fertilizing",
        "kimri",
        19,
        19,
        "Foliar potassium",
        "800 mg/L K",
        "Optional foliar potassium, spray 1 of 3 (May). Medjool study: 800 mg/L K in May, "
        "June and July; +31% yield. Use only if the K source is permitted by the certifier. "
        + _CERTIFIER
        + " Source [19] · Low. Source check: [19] could not be opened.",
    ),
    (
        "fertilizing",
        "kimri",
        23,
        23,
        "Foliar potassium",
        "800 mg/L K",
        "Optional foliar potassium, spray 2 of 3 (June). Use only if the K source is "
        "permitted by the certifier. " + _CERTIFIER + " Source [19] · Low.",
    ),
    (
        "fertilizing",
        "khalal",
        27,
        27,
        "Foliar potassium",
        "800 mg/L K",
        "Optional foliar potassium, spray 3 of 3 (July). Use only if the K source is "
        "permitted by the certifier. " + _CERTIFIER + " Source [19] · Low.",
    ),
    (
        "observation",
        "kimri",
        20,
        34,
        "Stethorus gilvifrons (predator release)",
        None,
        "Dust mite: scout bunches (the mite is recorded in the New Valley); biological "
        "option: release the predator Stethorus gilvifrons. Timing and thresholds were not "
        "found (manual section 13). " + _CERTIFIER + " How often: the sources give no "
        "frequency; every 2 weeks is a placement only. Source [20] [21] · Low.",
    ),
    (
        "irrigation",
        "khalal",
        27,
        39,
        None,
        None,
        "Summer regime (July-September): FAO reference about 7,154 m³/ha; 87-297 L per palm "
        "per day (Saudi lysimeter); Medjool in Dakhla was irrigated twice a week in summer; "
        "a UAE calendar gives every 3-5 days. Keep moisture steady through Khalal, Rutab and "
        "Tamar to limit cracking. How often: 2x per week. Source [4] [10] [28] [42] [18] · "
        "Medium. Source check: the FAO figures in [4] are for mature Deglet Nour in Tunisia; "
        "the Dakhla schedule [10] matches.",
    ),
    (
        "bagging",
        "khalal",
        27,
        28,
        "Open-ended bags; brown wrapping paper; net bags",
        None,
        "Bag bunches at the start of Khalal with open-ended bags, left on until harvest "
        "(Medjool: less sunburn, better ripening). Brown wrapping paper was reported to "
        "inhibit black nose; net bags protect against birds. "
        + _CERTIFIER
        + " How often: once per bunch; bags stay on until harvest. Source [16] [18] [29] · High.",
    ),
    (
        "observation",
        "khalal",
        29,
        36,
        None,
        None,
        "Monitor ripening progress inside the bags (Khalal, Rutab, Tamar) and fruit "
        "cracking; keep irrigation steady. How often: the sources give no frequency. "
        "Source [15] [18] · Medium.",
    ),
    (
        "soil_prep",
        "rutab",
        32,
        37,
        "Topsoil + well-matured manure",
        "10-15 kg manure per hole",
        "Prepare planting holes 1-2 months before autumn planting (same specification as "
        "spring). " + _CERTIFIER + " How often: once per planting hole. Source [3] · Medium.",
    ),
    (
        "harvesting",
        "harvest",
        37,
        41,
        None,
        None,
        "Harvest Medjool by picking individual soft dates in 2-3 passes, 1-2 weeks apart; "
        "shake each bag over a collection tub so only ripe dates fall. Egyptian harvest "
        "starts around mid-September. How often: 1 pick per bunch every 1-2 weeks; 2-3 picks "
        "in total. Source [17] [24] · Medium. Source check: [17] could not be opened; the "
        "same text is in the Arizona guide [30].",
    ),
    (
        "irrigation",
        "harvest",
        40,
        48,
        None,
        None,
        "Autumn, after harvest (October-November): continue irrigating; lack of irrigation "
        "during autumn and winter delayed the next flowering and reduced fruit set (Negev). "
        "How often: 1-2x per week; the sources give no number for this period (manual "
        "section 13). Source [5] · Low.",
    ),
    (
        "planting",
        "harvest",
        40,
        44,
        None,
        None,
        "Autumn planting window for tissue-culture plants or offshoots (spring and autumn "
        "are the preferred planting seasons in the Northern Hemisphere). How often: once per "
        "plant. Source [3] · Medium.",
    ),
]

# (activity_type, offset_days, duration_days, product, dosage, notes) - anchor: start (= W0).
_YEAR = 365
NEW_PLANTING: list[tuple] = [
    (
        "soil_prep",
        -56,
        28,
        "Topsoil + well-matured manure",
        "10-15 kg manure per hole",
        "Weeks -8 to -4. Dig and prepare planting holes; fill with topsoil + 10-15 kg "
        "well-matured manure, keeping at least 15-20 cm of soil between manure and future "
        "roots; irrigate the holes. " + _CERTIFIER + " How often: once per planting hole. "
        "Source [3] · Medium.",
    ),
    (
        "irrigation",
        -56,
        28,
        None,
        None,
        "Weeks -8 to -4. Irrigate the prepared holes shortly before planting. How often: "
        "once, shortly before planting. Source [3] · Medium.",
    ),
    (
        "observation",
        -56,
        28,
        None,
        None,
        "Weeks -8 to -4. Tissue-culture plants: continue hardening (high to low humidity, "
        "low to high light) until they have at least 4 pinnate leaves. How often: gradual "
        "and continuous; the sources give no number. Source [3] [37] · Medium. Source check: "
        "the 4-leaf stage matches [3]; the humidity and light wording was not found on [3] "
        "or [37].",
    ),
    (
        "planting",
        -56,
        28,
        None,
        None,
        "Weeks -8 to -4. Offshoots: use nursery-rooted offshoots (1-2 years in nursery); "
        "offshoots removed at 3-4 years and 12-20 kg with a 5-8 cm soil ball on the roots. "
        "How often: once per offshoot. Source [2] · Medium. Source check: [2] says at least "
        "3-5 years and 10-25 kg.",
    ),
    (
        "planting",
        0,
        7,
        None,
        None,
        "Week 0. Plant to the depth of the greatest diameter; leaf base clearly above soil; "
        "keep irrigation water away from the heart. Tie the offshoot's leaves together at the "
        "top until new growth appears. How often: once per plant. Source [2] [3] [39] · Medium.",
    ),
    (
        "irrigation",
        0,
        7,
        None,
        None,
        "Week 0. First irrigation at planting, then the soil-type schedule: sandy soil daily, "
        "most soils every 2-3 days, heavy soil weekly; keep water away from the heart. "
        "Source [2] [3] [4] · Medium.",
    ),
    (
        "planting",
        0,
        7,
        "Hessian wrapping, shade net or a tent of date leaves",
        None,
        "Week 0. Fit protection against sun, wind and animals; keep it on through the first "
        "summer and the following winter. How often: once at planting. Source [37] · Medium. "
        "Source check: this text is on FAO page [3], not [37].",
    ),
    (
        "soil_prep",
        0,
        7,
        "Hay or straw mulch",
        None,
        "Week 0. Spread a hay or straw mulch in the basin. "
        + _CERTIFIER
        + " How often: once at planting. Source [2] [39] · Medium.",
    ),
    (
        "trap_service",
        0,
        5 * _YEAR,
        "Pheromone traps (food bait and water)",
        "0.5-1 trap per ha",
        "From planting onwards, all year: red palm weevil visual inspection and trap "
        "servicing, as for mature palms. How often: 1x every 7-14 days. Source [8] [9] · Medium.",
    ),
    (
        "irrigation",
        7,
        42,
        None,
        None,
        "Weeks 1-6. Light, frequent irrigation to keep the soil moist at all times (first "
        "summer: daily on very sandy soil, every 2-3 days on most soils, weekly on heavy "
        "soil). Source [2] [4] [39] · Medium.",
    ),
    (
        "observation",
        7,
        42,
        None,
        None,
        "Weeks 1-6. Inspect every plant: the surface soil must not dry out and shrink away "
        "from the plant; check that water does not reach the heart. How often: during the "
        "first 6 weeks; the sources give no number per week. Source [2] [37] · Medium.",
    ),
    (
        "observation",
        42,
        7,
        None,
        None,
        "Week 6. Record plants showing new growth; the tied fronds may dry, and new leaves "
        "should appear by autumn. How often: once, at week 6. Source [2] [39] · Medium.",
    ),
    (
        "irrigation",
        49,
        _YEAR - 49,
        None,
        None,
        "Week 7 to month 12. Irrigation by soil type as above; sandy soils need more "
        "irrigation and fertilisation because of leaching. The sources give no winter number "
        "for young plants (manual section 13). Source [4] [37] · Medium.",
    ),
    (
        "observation",
        49,
        _YEAR - 49,
        None,
        None,
        "Week 7 to month 12. Keep protection on through the first summer (sun, wind) and the "
        "following winter (cold). Close follow-up for at least 10-12 months: fertilisation, "
        "weeding and mulching; detect and correct problems. Organic fertiliser rates for young "
        "Medjool were not found (manual section 13). How often: the sources give no frequency. "
        "Source [37] · Medium. Source check: this text is on FAO page [3], not [37].",
    ),
    (
        "irrigation",
        _YEAR,
        2 * _YEAR,
        None,
        None,
        "Years 2-3, vegetative growth. Continue light, regular irrigation, keeping water off "
        "the heart. Summer: per soil type (sandy daily, most soils 2-3x per week, heavy 1x per "
        "week); winter: 1x per week. The sources give no number for years 2-3. "
        "Source [4] [10] · Low.",
    ),
    (
        "fertilizing",
        _YEAR,
        2 * _YEAR,
        None,
        None,
        "Years 2-3. Continue organic fertilisation, weeding and mulching; remove protection "
        "once the plant is established. Organic fertiliser rates for young Medjool were not "
        "found (manual section 13). " + _CERTIFIER + " How often: the sources give no "
        "frequency for years 2-3. Source [37] · Medium.",
    ),
    (
        "observation",
        _YEAR,
        2 * _YEAR,
        None,
        None,
        "Years 2-3. Expect the juvenile phase to be sterile: early inflorescence buds abort. "
        "Axillary buds develop into offshoots in this phase. Whether early inflorescences "
        "should be removed was not found (manual section 13). Observation only. "
        "Source [38] · Medium.",
    ),
    (
        "irrigation",
        2 * _YEAR,
        3 * _YEAR,
        None,
        None,
        "Years 3-5, onset of fruiting. Move to the bearing-palm regime: winter 1x per week and "
        "summer 2x per week (Medjool, Dakhla); spring and autumn 1-2x per week (not stated in "
        "sources). Source [10] · Medium.",
    ),
    (
        "observation",
        2 * _YEAR,
        3 * _YEAR,
        None,
        None,
        "Years 3-5. Onset of harvestable fruit is reported at 3-5 years for offshoot-grown "
        "palms and about 4 years for tissue-culture plants. When the palm enters the "
        "generative phase (inflorescences form, offshoot production stops), set its palm phase "
        "to Bearing and switch to the bearing-palm template. Source [41] · Low (years to "
        "fruit); [38] · Medium (generative phase).",
    ),
    (
        "planting",
        2 * _YEAR,
        3 * _YEAR,
        None,
        None,
        "Years 3-5. Offshoots on the young palm become ready for removal after 3-5 years "
        "attached, depending on variety. How often: once per offshoot. Source [2] · Medium.",
    ),
]

TEMPLATES = {
    "medjool-organic-bearing-eg": {
        "name": "Organic Medjool - bearing palms (Western Desert, Egypt)",
        "name_ar": "المجدول العضوي - النخيل المثمر (الصحراء الغربية، مصر)",
        "description": (
            "52-week plan from the Organic Medjool Manual (Edition 1.3, Sept 2026), section 12. "
            "Activities follow the nine Medjool stages. Repeated work is one activity per "
            "window with the frequency in its notes."
        ),
        "description_ar": (
            "خطة 52 أسبوعًا من دليل المجدول العضوي (الإصدار 1.3، سبتمبر 2026)، القسم 12. "
            "تتبع الأنشطة مراحل المجدول التسع."
        ),
    },
    "medjool-organic-new-planting-eg": {
        "name": "Organic Medjool - new planting to first fruit (Western Desert, Egypt)",
        "name_ar": "المجدول العضوي - من الزراعة حتى بداية الإثمار (الصحراء الغربية، مصر)",
        "description": (
            "From 8 weeks before planting to year 5, from the Organic Medjool Manual "
            "(Edition 1.3, Sept 2026), section 8.8. Set the plan start date to the field "
            "planting week."
        ),
        "description_ar": (
            "من 8 أسابيع قبل الزراعة حتى السنة الخامسة، من دليل المجدول العضوي، القسم 8.8. "
            "اجعل تاريخ بدء الخطة أسبوع الزراعة في الحقل."
        ),
    },
}


def bearing_rows() -> list[dict]:
    rows = []
    for sort, (atype, stage, first, last, product, dosage, notes) in enumerate(BEARING, 1):
        offset, duration = _weeks(stage, first, last)
        rows.append(
            {
                "activity_type": atype,
                "anchor": "stage",
                "stage_code": stage,
                "offset_days": offset,
                "duration_days": duration,
                "product_name": product,
                "dosage": dosage,
                "notes": (
                    f"Weeks {first}-{last}. {notes}" if first != last else f"Week {first}. {notes}"
                ),
                "sort_order": sort,
            }
        )
    return rows


def new_planting_rows() -> list[dict]:
    return [
        {
            "activity_type": atype,
            "anchor": "start",
            "stage_code": None,
            "offset_days": offset,
            "duration_days": duration,
            "product_name": product,
            "dosage": dosage,
            "notes": notes,
            "sort_order": sort,
        }
        for sort, (atype, offset, duration, product, dosage, notes) in enumerate(NEW_PLANTING, 1)
    ]


def upgrade() -> None:
    conn = op.get_bind()
    crop_id = conn.execute(
        sa.text("SELECT id FROM public.crops WHERE code = 'date_palm' AND deleted_at IS NULL")
    ).scalar()
    if crop_id is None:
        return
    for code, rows in (
        ("medjool-organic-bearing-eg", bearing_rows()),
        ("medjool-organic-new-planting-eg", new_planting_rows()),
    ):
        exists = conn.execute(
            sa.text("SELECT 1 FROM public.plan_templates WHERE code = :c AND deleted_at IS NULL"),
            {"c": code},
        ).first()
        if exists is not None:
            continue
        meta = TEMPLATES[code]
        template_id = conn.execute(
            sa.text(
                "INSERT INTO public.plan_templates "
                "(code, name, name_ar, crop_path, crop_id, country, region, description, "
                " description_ar, status) "
                "VALUES (:code, :name, :name_ar, :path, :crop_id, 'EG', NULL, :description, "
                " :description_ar, 'published') RETURNING id"
            ),
            {"code": code, "path": _PATH, "crop_id": crop_id, **meta},
        ).scalar_one()
        for row in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO public.plan_template_activities "
                    "(template_id, activity_type, anchor, milestone_id, stage_code, offset_days, "
                    " duration_days, product_name, dosage, notes, sort_order) "
                    "VALUES (:tid, :activity_type, :anchor, NULL, :stage_code, :offset_days, "
                    " :duration_days, :product_name, :dosage, :notes, :sort_order)"
                ),
                {"tid": template_id, **row},
            )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM public.plan_templates WHERE code = ANY(:codes)").bindparams(
            sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))
        ),
        {"codes": list(TEMPLATES)},
    )
