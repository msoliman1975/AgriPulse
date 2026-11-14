# Medjool organic plan templates: edition 1.3 to 1.7

Data: `backend/migrations/public/versions/data/0111_medjool_plan_templates_1_7.json`, seeded as drafts by public migration 0111. Every activity was checked against the English and Arabic editions of manual 1.7 (sections 12.2 and 8.8).

Counts: bearing 43 (17 kept, 14 changed, 12 new); new planting 21 (8 kept, 12 changed, 1 new). All 31 bearing and 20 new-planting activities from 1.3 carry on under their 1.3 codes. None were dropped.

## Conventions used

- **Note prefix.** Bearing `notes` and `notes_ar` have no "Week N." / "Weeks N-M." prefix. Add it when seeding, as `bearing_rows()` does. In 1.3, `notes_ar` in 0110 already had the Arabic prefix «الأسابيع N-M.», so add the Arabic prefix too. New-planting notes keep the 1.3 style: the period lead ("Weeks -8 to -4.", "Week 0." …) is written into the note.
- **offset_days / duration_days.** Bearing values come from 0099 `_weeks()`, with the stage being the one whose window holds `first_week`. New-planting values copy the 1.3 NEW_PLANTING list exactly: weeks -8 to -4 are stored as -56/28 (1.3 stored that row with 28 days, not 35, and I kept that); a year is 365 days; "Week 7 to month 12" is 49/316. For the year rows, `first_week`/`last_week` are offset÷7 and (offset+duration)÷7−1, so they are 52-155, 104-259 and 0-259 (RPW).
- **Note body.** Each note is the manual 1.7 12.2 / 8.8 task text verbatim, then any section-13 gap sentence, then the certifier sentence on input activities, then "How often: … (basis)", then "Source [n] · Level." The Arabic note is built the same way from the Arabic edition: task sentence, «الدليل، القسم 13، الفجوة n: …», the 0110 certifier sentence, «عدد مرات التنفيذ: …», «المصدر … · متوسطة». The builder checks that the source numbers and confidence in the English and Arabic texts match for every task.
- **1.3 "Source check" lines are dropped everywhere.** Edition 1.4 and later re-checked every citation against the full texts and corrected them (manual 2.1), and the corrected sources are now in the notes.
- **Repeated or split work.** Monthly or periodic tasks are one activity each: Trichogramma in weeks 11-23, RPW base prevention in weeks 5-52, dust mite scouting in weeks 14-34. Tasks that wrap the year end or fall in two separate windows are split, as winter irrigation was in 1.3: Khamedj spray at weeks 1-2 and week 42 (spraying-3/-4), and winter frond work at weeks 1-4 and 49-52 (pruning-2/-3). The three foliar K sprays stay three activities so their 1.3 codes are kept.
- **Codes.** 1.3 codes are rebuilt as in 0104 (`<type>-<n>` in sort order within each type). New codes continue each type's numbering.
- **Doses.** A structured dose is set only where 12.2 or 8.8 gives the dose for that task, and it matches the 0108 catalogue entry for that section. The autumn planting holes (soil_prep-2) have an input_code but no structured dose: 12.2 says only "same specification as spring", and the catalogue lists no dose for weeks 32-37.

### Bearing (43 activities)

| Code | Type | Weeks | Change | What changed | Manual |
|---|---|---|---|---|---|
| irrigation-1 | irrigation | 1 to 8 | kept | Same regime, frequency and sources in 1.7 12.2 weeks 1-8; wording now says the FAO figure is for Tunisia. | 12.2 weeks 1-8 |
| trap_service-1 | trap_service | 1 to 52 | changed | 1.7 12.2 weeks 1-52: every 7-15 days (was 7-14), 1-4 traps/ha (was 0.5-1), traps on the ground, shaded, near edges; sources [8] [36] [44] [55] [51] (was [8]). | 12.2 weeks 1-52 |
| observation-1 | observation | 1 to 52 | changed | 1.7 12.2 weeks 1-52: detailed symptom list, lowest metre of trunk, male/seedling palms, burn and bury; survey 1x/month cold months, 2x/month warm season, whole farm at least every 2 months; sources [8] [9] [44] [69] [62] [53]. Gaps 12 and 13 (section 13) added. | 12.2 weeks 1-52 |
| spraying-3 | spraying | 1 to 2 | new | New in 1.7 12.2 weeks 1-2 and 42 (2 sprays a year: after harvest and about a month before spathe emergence). This is the pre-emergence spray; spraying-4 is the post-harvest one. | 12.2 weeks 1-2 |
| pruning-2 | pruning | 1 to 4 | new | New in 1.7 12.2 weeks 1-4 and 49-52 (once per palm per winter). Split at the year end like the winter irrigation; pruning-3 is weeks 49-52. | 12.2 weeks 1-4 |
| soil_prep-1 | soil_prep | 2 to 9 | kept | Unchanged in 1.7 12.2 weeks 2-9 (source [3], Medium). | 12.2 weeks 2-9 |
| pruning-1 | pruning | 3 to 5 | changed | 1.7 12.2 weeks 3-5: spines from about 20-25 outer leaves, no green fronds cut, treat every cut; sources [6] [42] [29] · Medium (was [29] · Low). | 12.2 weeks 3-5 |
| pollination-1 | pollination | 5 to 13 | kept | Unchanged in 1.7 12.2 weeks 5-13 (sources [12] [13], Medium). | 12.2 weeks 5-13 |
| hilling-1 | hilling | 5 to 52 | new | New in 1.7 12.2 (weeks 5, 9, 13 ... 52, monthly with the farm inspection): cover exposed aerial roots with soil, control rats and mice. Source [62]. One activity spanning weeks 5-52. | 12.2 weeks 5-52 |
| observation-5 | observation | 5 to 13 | new | New in 1.7 12.2 weeks 5-13. Source [66], Medium. | 12.2 weeks 5-13 |
| observation-2 | observation | 6 to 13 | kept | Same task, frequency and source ([11], High) in 1.7 12.2 weeks 6-13. The 1.3 'Source check' line is dropped: 1.7 re-checked every citation against the full texts (section 2.1). | 12.2 weeks 6-13 |
| pollination-2 | pollination | 6 to 13 | changed | 1.7 12.2 weeks 6-13: fresh male strands between the female strands or 10% pollen with talc; second pass 2-4 days later and again after rain within 2-3 days; 10:00-15:00 at >=18 °C; source [39] added. | 12.2 weeks 6-13 |
| bagging-1 | bagging | 6 to 13 | changed | 1.7 12.2 weeks 6-13: a paper bag (1.3: kraft paper), removed after 8-10 days to 2-3 weeks; sources [5] [6] (was [5]). | 12.2 weeks 6-13 |
| spraying-1 | spraying | 6 to 13 | kept | Unchanged in 1.7 12.2 weeks 6-13 (source [20], Medium); 1.3 'Source check' line dropped. | 12.2 weeks 6-13 |
| thinning-3 | thinning | 6 to 13 | new | New in 1.7 12.2 weeks 6-13 (first thinning at pollination). Source [6], Medium. | 12.2 weeks 6-13 |
| observation-6 | observation | 6 to 13 | new | New in 1.7 12.2 weeks 6-13: inspect spathes, burn infected ones, no pollen from affected males. Source [44], Medium. | 12.2 weeks 6-13 |
| irrigation-3 | irrigation | 9 to 15 | kept | Same window, 1-2x/week, source [5] Low in 1.7 12.2 weeks 9-15; 1.7 adds the Negev sentence on autumn-winter irrigation. Gap 11 named. | 12.2 weeks 9-15 |
| irrigation-4 | irrigation | 10 to 52 | kept | Unchanged in 1.7 12.2 weeks 10-52 (sources [2] [4] [39], Medium); 1.3 'Source check' line dropped. | 12.2 weeks 10-52 |
| planting-1 | planting | 10 to 17 | changed | 1.7 12.2 weeks 10-17: offshoots 3-5 years and 10-25 kg (was 3-4 years, 12-20 kg), base 20-35 cm, free of pests; treat and cover every cut on the mother palm (RPW); sources [2] [44] (was [2] [3]). | 12.2 weeks 10-17 |
| spraying-5 | spraying | 11 to 23 | new | New in 1.7 12.2 weeks 11, 15, 19, 23 (monthly from mid-March, 3-4 releases a season). One activity spanning weeks 11-23. Source [33], Medium. | 12.2 weeks 11-23 |
| spraying-2 | spraying | 13 | kept | Unchanged in 1.7 12.2 week 13 (source [20], Medium); 1.3 'Source check' line dropped. | 12.2 week 13 |
| thinning-1 | thinning | 14 to 15 | changed | 1.7 12.2 weeks 14-15: FAO methods (cut strand tips, remove centre strands, 50-60% of fruits), US guides by pea size; source [39] added; 1.3 'one quarter' wording removed. | 12.2 weeks 14-15 |
| thinning-2 | thinning | 14 to 15 | changed | 1.7 12.2 weeks 14-15: 10-12 bunches per mature palm, 8-10 leaves per bunch (was 8-9 leaves, <=15 bunches, Deglet Noor); remove weak/late bunches; sources [5] [6] [35] [39] [42] (was [7]). The 1.3 'Medjool ratio not found' gap note is removed. | 12.2 weeks 14-15 |
| observation-3 | observation | 14 to 34 | changed | 1.7 12.2 weeks 14-34 (every 2 weeks from fruit set; was weeks 20-34): silk webbing sign, infestation from the first to third week of July; sources [21] [20] [44] [63] · Medium (was [20] [21] · Low). Gap 4 named. | 12.2 weeks 14-34 |
| irrigation-5 | irrigation | 16 to 26 | changed | 1.7 12.2 weeks 16-26: source [18] only; the 3 m³/tree/week drip figure and reference [43] are no longer in this task. Frequency 1-2x/week (Low) unchanged. Gap 11 named. | 12.2 weeks 16-26 |
| bending-1 | bending | 16 to 22 | changed | 1.7 12.2 weeks 16-22: usually 1-1.5 months after pollination; Medjool stalks brittle, two ropes to an upper and a lower leaf; sources [5] [6] [39] [42] · Medium (was [5] · Low). | 12.2 weeks 16-22 |
| fertilizing-2 | fertilizing | 19 | kept | Unchanged in 1.7 12.2 week 19 (source [19], Low); 1.3 'Source check' line dropped. | 12.2 week 19 |
| fertilizing-3 | fertilizing | 23 | kept | Unchanged in 1.7 12.2 week 23 (source [19], Low). | 12.2 week 23 |
| irrigation-6 | irrigation | 27 to 39 | kept | Unchanged in 1.7 12.2 weeks 27-39 (2x/week; sources [4] [10] [28] [42] [18], Medium); 1.3 'Source check' line dropped. | 12.2 weeks 27-39 |
| fertilizing-4 | fertilizing | 27 | kept | Unchanged in 1.7 12.2 week 27 (source [19], Low). | 12.2 week 27 |
| bagging-2 | bagging | 27 to 28 | changed | 1.7 12.2 weeks 27-28: bag as fruit passes Kimri to Khalal, finish before Rutab; open-ended or porous bags; white 2 mm net bags in July best in the Egyptian oases, May-June bagging raised moth damage; brown paper / bird-net text no longer here; sources [16] [6] [33] [45] [39] (was [16] [18] [29]). | 12.2 weeks 27-28 |
| spraying-6 | spraying | 27 | new | New in 1.7 12.2 week 27 (early July, 100-150 g per palm). Source [44], Medium. Gap 4 named. | 12.2 week 27 |
| thinning-4 | thinning | 27 to 34 | new | New in 1.7 12.2 weeks 27-34: wire rings and removing a few centre strands, avoid excess soil moisture, weed-free basin during Khalal. Source [44], Medium. | 12.2 weeks 27-34 |
| observation-4 | observation | 29 to 36 | kept | Unchanged in 1.7 12.2 weeks 29-36 (sources [15] [18], Medium). Gaps 14 and 15 (heat units) added. | 12.2 weeks 29-36 |
| soil_prep-2 | soil_prep | 32 to 37 | kept | Unchanged in 1.7 12.2 weeks 32-37 (source [3], Medium). | 12.2 weeks 32-37 |
| harvesting-1 | harvesting | 37 to 41 | changed | 1.7 12.2 weeks 37-41: harvest at Rutab, handle gently, collect fallen dates (Ephestia about 4x higher); sources [17] [24] [39] [30] [33] [45] (was [17] [24]). Gaps 14 and 15 added. | 12.2 weeks 37-41 |
| observation-7 | observation | 37 to 41 | new | New in 1.7 12.2 weeks 37-41 (weekly during harvest, set by compiler). Sources [33] [44], Medium. | 12.2 weeks 37-41 |
| irrigation-7 | irrigation | 40 to 48 | kept | Unchanged in 1.7 12.2 weeks 40-48 (1-2x/week, source [5], Low). Gap 11 named. | 12.2 weeks 40-48 |
| planting-2 | planting | 40 to 44 | kept | Unchanged in 1.7 12.2 weeks 40-44 (source [3], Medium). | 12.2 weeks 40-44 |
| spraying-4 | spraying | 42 | new | New in 1.7 12.2 week 42 (the after-harvest spray of the two a year). Source [44], Medium. | 12.2 week 42 |
| fertilizing-1 | fertilizing | 44 to 52 | changed | 1.7 12.2 weeks 44-52, once a year (1.3: weeks 1-4, every 2 years, 20-50 kg); at least 5 kg per year of palm age up to about 50 kg (UAE calendar, end of October-December); Morocco 50 kg compost; Dakhla filter mud + poultry manure; sources [42] [31] [10] · Medium (was [3] [10] · Low). Gap 2 named. | 12.2 weeks 44-52 |
| irrigation-2 | irrigation | 49 to 52 | kept | Same regime in 1.7 12.2 weeks 49-52; note now carries the full 12.2 text (as weeks 1-8). | 12.2 weeks 49-52 |
| pruning-3 | pruning | 49 to 52 | new | New in 1.7 12.2 weeks 49-52 (continues into weeks 1-4 as pruning-2; once per palm per winter across both). | 12.2 weeks 49-52 |

### New planting (21 activities)

| Code | Type | Weeks | Change | What changed | Manual |
|---|---|---|---|---|---|
| soil_prep-1 | soil_prep | -8 to -4 | changed | 1.7 8.8 W-8 to W-4 Task 1: sources [2] [37] (was [3]); text unchanged. | 8.8 W-8 to W-4 Task 1 |
| irrigation-1 | irrigation | -8 to -4 | kept | Unchanged in 1.7 8.8 W-8 to W-4 Task 2 (source [3], Medium). | 8.8 W-8 to W-4 Task 2 |
| observation-1 | observation | -8 to -4 | changed | 1.7 8.8 W-8 to W-4 Task 3: sources [2] [3] (was [3] [37]); 1.3 'Source check' line dropped. | 8.8 W-8 to W-4 Task 3 |
| planting-1 | planting | -8 to -4 | changed | 1.7 8.8 W-8 to W-4 Task 4: offshoots removed at 3-5 years, 10-25 kg, base 20-35 cm (was 3-4 years, 12-20 kg); Medjool offshoots harder to establish. | 8.8 W-8 to W-4 Task 4 |
| planting-2 | planting | 0 | changed | 1.7 8.8 W0 Task 1: sources [2] [3]; tying the leaves is now its own task (Task 3, source [39]) and moves to planting-5. | 8.8 W0 Task 1 |
| irrigation-2 | irrigation | 0 | kept | Unchanged in 1.7 8.8 W0 Task 2 (sources [2] [3] [4], Medium); How often line added. | 8.8 W0 Task 2 |
| planting-5 | planting | 0 | new | Split from 1.3 planting-2: 1.7 8.8 W0 Task 3 is a separate task (source [39], Medium). | 8.8 W0 Task 3 |
| planting-3 | planting | 0 | changed | 1.7 8.8 W0 Task 4: sources [2] [3] (was [37]); 1.3 'Source check' line dropped. | 8.8 W0 Task 4 |
| soil_prep-2 | soil_prep | 0 | changed | 1.7 8.8 W0 Task 5: source [2] (was [2] [39]). | 8.8 W0 Task 5 |
| trap_service-1 | trap_service | 0 to 259 | changed | 1.7 8.8 W0 Task 6, W7-month 12 Task 4, years 2-3 Task 4, years 3-5 Task 5: every 7-15 days (was 7-14), as for mature palms; trap density as for mature palms (12.2: 1-4 traps/ha, was 0.5-1). Gap 12 added. | 8.8 W0 Task 6; W7-month 12 Task 4; years 2-3 Task 4; years 3-5 Task 5 |
| irrigation-3 | irrigation | 1 to 6 | changed | 1.7 8.8 W1-W6 Task 1: sources [2] [3] (was [2] [4] [39]). | 8.8 W1-W6 Task 1 |
| observation-2 | observation | 1 to 6 | changed | 1.7 8.8 W1-W6 Task 2: source [2] (was [2] [37]). | 8.8 W1-W6 Task 2 |
| observation-3 | observation | 6 | kept | Unchanged in 1.7 8.8 W6 Task 3 (sources [2] [39], Medium). | 8.8 W6 Task 3 |
| irrigation-4 | irrigation | 7 to 51 | changed | 1.7 8.8 W7-month 12 Task 1: sources [2] [3] [37] (was [4] [37]); the no-winter-number statement is now in the How often line. | 8.8 W7-month 12 Task 1 |
| observation-4 | observation | 7 to 51 | changed | 1.7 8.8 W7-month 12 Tasks 2 and 3: sources [2] [3] (was [37]); 'annual fertilisation schedule'. Gap 7 kept. | 8.8 W7-month 12 Tasks 2-3 |
| irrigation-5 | irrigation | 52 to 155 | kept | Same frequencies and sources ([4] [10], Low) in 1.7 8.8 years 2-3 Task 1; 1.7 explains the frequencies combine the first-summer soil schedule and the bearing winter regime. | 8.8 years 2-3 Task 1 |
| fertilizing-1 | fertilizing | 52 to 155 | changed | 1.7 8.8 years 2-3 Task 2: source [3] (was [37]); protection duration given only as first summer and following winter. Gap 7 kept. | 8.8 years 2-3 Task 2 |
| observation-5 | observation | 52 to 155 | kept | Unchanged in 1.7 8.8 years 2-3 Task 3 (source [38], Medium). Gap 8 kept. | 8.8 years 2-3 Task 3 |
| irrigation-6 | irrigation | 104 to 259 | kept | Unchanged in 1.7 8.8 years 3-5 Task 1 (source [10], Medium). | 8.8 years 3-5 Task 1 |
| observation-6 | observation | 104 to 259 | kept | Same content in 1.7 8.8 years 3-5 Tasks 2 and 3 ([41] Low; [38] Medium); 1.7 lists the bearing operations to switch to. | 8.8 years 3-5 Tasks 2-3 |
| planting-4 | planting | 104 to 259 | kept | Unchanged in 1.7 8.8 years 3-5 Task 4 (source [2], Medium). | 8.8 years 3-5 Task 4 |
## Change table: where each item went

| # | Item | Placed as |
|---|---|---|
| 1 | Khamedj prevention spray | spraying-3 (wk 1-2), spraying-4 (wk 42) |
| 2 | Winter frond work | pruning-2 (wk 1-4), pruning-3 (wk 49-52) |
| 3 | RPW prevention at palm base, monthly | hilling-1 (wk 5-52) |
| 4 | Khamedj risk (3 tasks) | observation-5 (rain record), observation-6 (spathe inspection), thinning-3 (top third) |
| 5 | Trichogramma | spraying-5 (wk 11-23), 1 card/palm |
| 6 | Sulphur dusting | spraying-6 (wk 27), 100-150 g/plant |
| 7 | Fruit rot ventilation; field sanitation | thinning-4 (wk 27-34); observation-7 (wk 37-41) |
| 8 | Organic fertilisation wk 44-52, yearly | fertilizing-1 moved; 5 kg/plant/year_of_age |
| 9 | Trap service 7-15 days, 1-4 traps/ha; symptom list | trap_service-1 and observation-1 (bearing); trap_service-1 (new planting) |
| 10 | 10-12 bunches, 8-10 leaves; dust mite scouting from wk 14 | thinning-2; observation-3 |
| 11 | 8.8 re-check | All 20 rows re-checked; 12 changed (mostly sources; offshoot age/weight; RPW 7-15 days); tie-leaves split out as planting-5 |
| 12 | Gaps 12-15 | Gap 12: bearing observation-1 and new-planting trap_service-1. Gap 13: bearing observation-1. Gaps 14 and 15: observation-4 (ripening) and harvesting-1 |

Every item in the change table was placed.

## Judgement calls (open questions)

1. **Activity types with no exact fit.** Trichogramma release is `spraying`, following 1.3, which filed the Bt dust as spraying; there is no biocontrol type. RPW base prevention (covering roots and controlling rodents) is `hilling`. Bunch ventilation (wire rings, removing centre strands) is `thinning`. Field sanitation is `observation`, the 1.3 catch-all.
2. **New-planting trap density.** 8.8 says only "as for mature palms". The 1-4 traps/ha figure, both as text and as a structured dose, comes from 12.2, following change-table item 9 ("BOTH templates"). If the dose must be stated in 8.8 itself, drop the structured dose.
3. **Combined new-planting rows kept as in 1.3.** observation-4 (8.8 W7 to month 12, Tasks 2 and 3) and observation-6 (years 3-5, Tasks 2 and 3) each combine two manual tasks. observation-6 mixes [41] Low and [38] Medium. Its `confidence` is set to `low`, the lower of the two, and the note keeps both levels.
4. **Seed-added sentence.** observation-6 keeps the 1.3 seed's app instruction ("Set the palm phase to Bearing and switch to the bearing-palm template"), with its Arabic from 0110. It is not manual text.
5. **source_tree_code** is set on 32 activities and left null where no tree clearly covers the same work (pollen, cold bags, top-third removal, offshoot removal, bunch number, foliar K, holes, autumn irrigation and planting, fertilisation, ventilation, sanitation).

## Where the manual disagrees with itself, or with the 1.3 seed

- **English vs Arabic, 12.2 weeks 44-52 (fertilizing-1).** EN: "up to about 50 kg per palm over 10 years". AR: «حتى نحو 50 كجم للنخلة الأكبر من 10 سنوات», which means up to about 50 kg for palms older than 10 years. Each language's note follows its own edition.
- **English vs Arabic, 8.8 years 2-3 Task 3.** EN "Expect the juvenile phase to be sterile". AR «الطور اليافع عقيم عادةً» ("is usually sterile"). This is a small difference in nuance.
- No numeric disagreement: an automatic comparison of every number in all 38 12.2 tasks and 36 8.8 tasks found differences only where one edition writes a number as a word ("1×" vs «مرة», "two" vs «أسبوعين»).
- **Inside both editions, 12.2 weeks 6-13 pollination (pollination-2).** The task says "repeat a second pass 2–4 days later", but its How-often line says "then again 3–4 days later". Both are kept verbatim.
- **Arabic terms that differ from the 1.3 seed (0100/0104/0110):** 1.7 uses المجدول (0110 notes used المجهول), عنكبوت الغبار (0104 title: حلم الغبار), طين المرشحات (0110: طينة المرشحات), غطاء من الدريس أو القش (0110: فرشة من القش أو التبن), «وفق المسطح الورقي» (0104: «حسب المساحة الورقية»), and «إزالة الأشواك» (0104: «إزالة الشوك»). The 1.7 Arabic edition's wording is used throughout, and several title_ar values were updated to match.
