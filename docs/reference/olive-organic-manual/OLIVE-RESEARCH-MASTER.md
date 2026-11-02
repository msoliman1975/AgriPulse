# Organic Olive Production in Egypt: Master Research File

**One location for all Task 1 research.** Updated 2026-10-22 after review of the second batch of uploaded files.
**Used by:** the Organic Olive Manual (bilingual HTML), built on the structure of the Organic Medjool Manual.

| Part | Content |
|---|---|
| **0** | **Read first:** consolidated findings, corrections, review of the second upload batch, status of all downloads, and the manual blueprint |
| 1 | Research dossier: sector, law, irrigation, fertility, IPM overview, harvest, remote sensing, FAO sources, first-batch file reviews |
| 2 | Pests and diseases |
| 3 | Varieties of Egypt and the Middle East |
| 4 | Orchard establishment, planting systems and propagation |

Confidence key used throughout: **H** = several consistent sources, or regulation or Egyptian data read in full. **M** = one study or a reliable guide. **L** = abstract only or extrapolated. **I** = expert inference.

---

# PART 0: Read first

## 0.1 Consolidated findings (all research to date)

1. **Sector.**
   - Egypt is a table-olive country: about 750 kt of table olives and about 52 kt of oil in 2023/24 (IOC). Ministry of Agriculture (MALR) figures: 1.13 Mt of fruit from 269,000 feddan in 2021/22, but yield per feddan fell 16 % between 2018 and 2022 (heat).
   - Aggezi Shami covers about **80 % of olive area in Fayoum, 40 % in Ismailia and 30 % in Nubaria** (IOC catalogue).
   - Organic olives covered only about 1,335 ha in 2009, yielding about 28 % less than conventional for an 8–10 % price premium.
   - FAO and Egypt signed an olive value-chain agreement on 10 Sep 2026.
2. **Law.**
   - Egyptian Law 12/2020 (20 articles): the General Administration of Organic Agriculture oversees production up to harvest and the National Food Safety Authority oversees post-harvest. It creates a national logo and requires an export certificate (Art. 8).
   - EU 2018/848 and Codex CXG 32 both require **3 years of conversion before the first organic harvest** of a perennial crop. Under Codex the authority may shorten this, but never below 12 months. Conversion starts only once the farm is **under inspection**.
   - Livestock manure is capped at 170 kg N/ha/yr and must not come from factory farming. Copper is capped at 28 kg Cu/ha over 7 years.
   - **No NaOH (lye) for olives**, so organic table olives must be naturally fermented.
3. **Varieties.**
   - Koroneiki is the best fit for organic production: high oil, early bearing, heat-tolerant, **low peacock-spot susceptibility in 100 % of studies**, and fairly Verticillium-resistant.
   - Picual and Coratina give the highest yields but carry disease risk: Picual is highly Verticillium-susceptible and Coratina is moderately susceptible to leaf spot.
   - Aggezi Shami, Toffahi and Hamed are the table-olive base. Maraki has the highest oil content of the Egyptian varieties.
   - ARC breeding (since 1994) has produced many named selections (Part 0.3).
4. **Establishment.**
   - Intensive planting (5 × 6 to 6 × 4 m, 140–175 trees/feddan) is the default organic system.
   - SHD (4 × 1.5 m, about 700 trees/feddan) **tripled yield** in Ismailia (5.4–7.0 against 1.9–2.4 t/feddan in years 5–6) at a slightly lower oil %.
   - Use certified clean nursery stock (EPPO PM 4/17).
   - Rooting depends on cultivar and season: April or June for mist, March for wooden boxes. ARC line 48 is hard to root, so graft it.
5. **Water.** FAO-56 olive Kc is 0.65 / 0.70 / 0.70 (Kcb 0.55 / 0.65 / 0.65) at 40–60 % ground cover, and must be **reduced for sparse cover** (Kcb about 0.40 at 20 % cover). Monthly Kc for olives in Spain is 0.45–0.65. Egyptian trials favour drip at 60–80 % ETc.
6. **Pests and diseases.**
   - **Olive fly** is the key pest; Egyptian infestation can reach 99 %. **Kaolin** sprayed every 2 weeks from June to harvest cut infestation by 69–83 % at Matrouh.
   - **Verticillium** is present across Egypt, from Siwa and the North Coast to Fayoum, Ismailia and North Sinai, in 3 compatibility groups. There is no cure; prevention and drone thermal detection are the tools. Rootstocks only help if they are *resistant* (avoidant), and even then not fully.
   - **Peacock spot:** copper hydroxide is the most efficient copper; *Bacillus amyloliquefaciens* and *Pseudomonas fluorescens* worked in the field; avoid excess nitrogen and potassium deficiency.
   - **Nursery root rot:** humic acid was best.
   - **Nematodes:** humic acid, *Bacillus subtilis* and botanical products work, but abamectin and oxamyl are **not organic**.
7. **Remote sensing.**
   - Sentinel-2 NDVI combined with a weather water balance reproduces root-zone water status (r² 0.80).
   - UAV thermal CWSI detects Verticillium early (R² 0.83 with stomatal conductance).
   - NDVI responds only late, and bare sand between rows biases it, so use per-tree segmentation.

## 0.2 Corrections made by the second batch (full texts)

| Item | Before | After | Source |
|---|---|---|---|
| Aggezi Shami pollination | Self-compatible (IOC 2012) | **Conflicting.** The IOC catalogue says self-*in*compatible with high pistil abortion; El-Soda 2017 found it self-compatible on the Cairo–Alex road. Best pollinizer is **Maraki** (and the reverse) | IOC catalogue sheet; El-Soda et al. 2017 |
| Maraki pollination | Not covered | Self-compatible (El-Soda 2017), but self-incompatible in Elsayed 2014. Treat as **needs a pollinizer** | Both |
| Koroneiki pollination | "Reports conflict" | **Self-compatible** in Egyptian trial; a good pollinizer for Dolce, Manzanillo and Picual | El-Soda 2017 |
| Kalamata and Manzanillo | Kalamata self-incompatible | Both **highly self-incompatible**. **Dolce** is a good pollinizer for Kalamata, Coratina and Koroneiki | El-Soda 2017 |
| Bloom order (Cairo–Alex road) | Not covered | Aggezi earliest, Kalamata latest; bloom lasts 14–20 days with overlap | El-Soda 2017 |
| SHD vs intensive, Ismailia | 7.3–8.9 t/feddan (Koroneiki SHD) | Full data: intensive 5 × 6 m (140 trees/feddan) vs SHD 1.5 × 4 m (700/feddan). **Means: intensive 1.9–2.4, SHD 5.4–7.0 t/feddan** in years 5–6. Koroneiki SHD gave 7.27–8.93 t and 1.14–1.42 t oil. **Oil % lower in SHD** (Koroneiki 15.7–15.9 % FW vs 16.8–17.6 %). Maraki had the highest oil % (about 19 %) but the lowest yield. Fruit weight higher in intensive | Ali et al. 2024 |
| Best month for cuttings | June (mist) | Season depends on system. **Mist/VPD: June** (about 38 %); **wooden boxes: March** (best overall, up to 86 % in Chiperssino); December worst (about 9 %). ARC 2022–23 trial (mist, IBA 5,000 ppm): **April best, then October; January worst** | Hegazi et al. 2010; Sawarsan et al. 2024 |
| ARC lines rooting | Not covered | **Easy:** 102, 66. **Moderate:** 97, 91, 69, 32, 138. **Difficult:** 92, 99, **48**, 52. The salt-tolerant line 48 should therefore be **grafted** | Sawarsan et al. 2024 |
| Verticillium distribution in Egypt | "No incidence survey" | Still no incidence survey, but isolates came from **12 sites in 8 regions**: Matrouh (Siwa, Barrani, El-Dabaa), Alexandria (Ameria), Menoufia, Fayoum (Sennoris), Ismailia, North Sinai (Arish). Three VCGs; VCG2 dominant (21 of 35 isolates) | Mousa et al. |
| Rootstocks against Verticillium | "Delay but don't prevent" | Refined: **avoidant/resistant** rootstocks (Frantoio, wild AMK27, GUA3, AMK21) beat *tolerant* ones. A susceptible scion (Picual) *raises* the rootstock's susceptibility. Microsclerotia survive **up to 14 years** | Díaz-Rueda et al. 2022 |
| Kaolin programme | 3–4 % from pit hardening | Matrouh protocol: **12 sprays every 2 weeks from 1 June to harvest**, 12–16 L per tree. 3–5 % kaolin gave 69–83 %. Bentonite 4–5 % gave 47–72 %, but **bentonite is not an EU-listed plant-protection substance**. Copper hydroxide (55.9–59.9 %) beat oxychloride (48.0–58.5 %) | Ali 2016 |
| Peacock spot cultivar susceptibility | Not covered | Share of studies reporting **low** susceptibility: **Koroneiki 100 % (5 studies)**, Leccino 90 %, Haouzia 50 %, Arbosana 50 %, Coratina 36 %, Kalamata 33 %, Frantoio 12 %, Arbequina 5 % | Buonaurio et al. 2023 |
| Peacock spot epidemiology | Mild and wet | Spores form at 5–25 °C; germination is optimal at 16–21 °C; infection is optimal about 20 °C (short wetness) or about 15 °C (long wetness). Young leaves are also susceptible. Excess N and **K deficiency** raise risk; drip and deficit irrigation lower it | Buonaurio et al. 2023 |
| Peacock spot organic tools | Copper and pruning | Plus: **copper hydroxide** (most efficient), low-copper gluconate complexes, **antagonists** *B. amyloliquefaciens* FZB24, *B. atrophaeus*, *P. fluorescens* (field-effective), resistance inducers (chitosan is an EU basic substance) | Buonaurio et al. 2023 |
| Nematode products | Results unknown | Greenhouse: abamectin cut *M. incognita* by 85.4 %. Field, after 6 months: Nemastrol cut root-knot nematode by 82.4 % and citrus nematode by 75.6 %. Humic acid gave the best plant growth. **Organic status:** humic acid and *B. subtilis* (Clean Root) are OK; Nemastrol (botanical mix) needs a certifier check; **abamectin and oxamyl are not allowed** | Hammad et al. 2021 |
| Root rot, New Valley | Organic compounds best | Incidence and severity **60.8 % / 48.7 % in Dakhla**, 52.1 % / 43.6 % in Kharga. **Humic acid (2.5 g/L drench)** significantly best; Inicium, Fulvital, Bio-Health and Alga Grow good; EM1 weakest. Rizolex-T (chemical) was *less* effective than the organics | El-Morsi & Mahdy 2013 |
| FAO-56 olive Kc | Secondary citations | Read in full: **Kc ini 0.65, mid 0.70, end 0.70; Kcb 0.55 / 0.65 / 0.65** (40–60 % cover); max height 3–5 m; root depth 1.2–1.7 m; p = 0.65. Spain, 60 % cover, Jan–Dec: **0.50, 0.50, 0.65, 0.60, 0.55, 0.50, 0.45, 0.45, 0.55, 0.60, 0.65, 0.50**. Example 43: 10 m spacing, 20 % cover gives Kcb mid ≈ **0.40**. Olives have strong stomatal control (Fr ≈ 0.67) | FAO-56 |
| Codex organic guidelines | Not read | CXG 32: perennials need **≥3 years before the first harvest**; authority may vary this but **≥12 months**; conversion starts only under inspection; factory-farm manure banned; copper only where need is recognised; NaOH not permitted except for sugar pH; labelling thresholds 95 % / 70 % | Codex CXG 32-1999 |
| Salt-tolerant ARC genotypes | Protocol only | Coratina × Frantoio and reciprocal crosses on **5,648 ppm (about 8.8 dS/m) water**, 3 × 6 m, sandy loam. **G16** gave the most oil under salinity. **G26** has the lowest oil and is a candidate **salt-tolerant rootstock**. **G25** is dual purpose (moderate oil, top yield, Ca and chlorophyll) | El-Husseiny et al. 2025 |

## 0.3 Review of the second upload batch (17 distinct files)

| # | File | Type | What it adds | Used in |
|---|---|---|---|---|
| 1 | **FAO-56**, *Crop Evapotranspiration* (full text) | FAO guideline | Olive Kc, Kcb, root depth, p factor, Spanish monthly Kc, ground-cover adjustment (Example 43) | Irrigation chapter; AgriPulse ET model |
| 2 | **El-Husseiny et al. 2025**, HRJ 3(5): genotypes under saline stress | ARC field trial | G16 (oil), G26 (rootstock), G25 (dual) at 5,648 ppm | Varieties; rootstocks; salinity |
| 3 | **Díaz-Rueda et al. 2022**, Front. Plant Sci. 13:1032489 | Peer-reviewed | Resistant vs tolerant rootstocks for Picual; 14-year microsclerotia survival | Verticillium; rootstocks |
| 4 | **Hegazi et al. 2010**, Bull. Fac. Agric. Cairo 61 | Field trial, North Sinai | 5 cultivars × 3 propagation systems × 4 dates; **wooden boxes cheapest and best** | Nursery and propagation |
| 5 | **Sawarsan et al. 2024**, HRJ 2(4) | ARC trial | Rooting classes of 11 ARC lines; April best | Propagation; ARC lines |
| 6 | **Ali et al. 2024**, HRJ 2(3) | ARC trial, Ismailia | Intensive vs SHD, 3 cultivars, full yield and oil tables | Planting systems |
| 7 | **IOC World Catalogue: Aggezi Shami** | Catalogue sheet | Area share by region, morphology, SSR profile, self-incompatible, fly-susceptible | Variety card |
| 8 | **El-Soda et al. 2017**, Bull. Fac. Agric. Cairo 68 | Field trial, Cairo–Alex road | Self-incompatibility of 8 cultivars, bloom order, **pollinizer pairs** | Pollination section |
| 9 | **Elsayed 2014**, M.Sc. thesis (Cairo Univ.) | Thesis (front matter and abstract only) | Maraki, Sewia and E52 vs Coratina and Koroneiki. **The full results chapters are not in the upload** | Varieties (abstract level) |
| 10 | **Mikhail 2015**, Ann. Agric. Sci. Moshtohor 53 | ARC breeding | Hamed crosses. Table selections 73, 91, 100; oil 42, 47, 71, 89, 98; dual 57, 59 | ARC selections table |
| 11 | **Osman 2015**, Ann. Agric. Sci. Moshtohor 53 | ARC breeding | Toffahi crosses. Table selections 51, 62, 63; oil 36, 49, 109, 121; dual 34, 35, 108, 110, 111 | ARC selections table |
| 12 | **Codex CXG 32-1999** (rev. 2007, amended 2009) | International standard | Conversion, inputs (Annex 2), processing aids, labelling | Regulatory chapter |
| 13 | **Buonaurio et al. 2023**, Front. Plant Sci. 13:1061136 | Review | Peacock spot epidemiology, cultivar table, copper, biocontrol | Disease chapter |
| 14 | **Hammad et al. 2021**, Egypt. J. Phytopathol. 49(2) | Greenhouse and field | Nematode bio-products on olive | Nematodes |
| 15 | **El-Morsi & Mahdy 2013**, Egypt. J. Agric. Res. 91(2) | Survey and greenhouse | New Valley root rot incidence; humic acid | Nursery diseases |
| 16 | **Mousa et al.**, J. Plant Prod. 34(7) | Lab | Verticillium VCGs from 8 Egyptian regions | Verticillium |
| 17 | **Ali 2016**, J. Plant Prot. Path. 7(7) | Field, Matrouh | Kaolin, bentonite and copper against olive fly | Olive fly |

**Duplicates received (no new content):** the Frontiers rootstock paper (2 copies), Battista et al. 2023 (3 copies in total), and the ECOLIVE .docx (2 copies, both incomplete; the original PDF is still needed).

## 0.4 Status of all downloads

**Received and read in full (26 distinct documents):**
- Law 12/2020 excerpt (#1)
- EU 2018/848 (#4)
- EU 2021/1165 (#5)
- IOC table-olive standard (#9)
- IOC Egypt policy (#12)
- ECOLIVE (#17, **incomplete**)
- Nagaty & Awad 2024 (#30)
- Battista 2023 (#62)
- Calderón 2013 (#63)
- Codex CXG 32 (#66)
- FAO-56 (#69)
- Ali et al. 2024 (E1)
- Sawarsan 2024 (E4)
- Hegazi 2010 (E5)
- Díaz-Rueda 2022 (E8)
- El-Husseiny 2025 (E9)
- IOC Aggezi sheet (V1)
- Osman 2015 (V5)
- Mikhail 2015 (V6)
- Elsayed thesis (V7, **abstract only**)
- El-Soda 2017 (V12)
- Ali 2016 (PD1)
- Mousa (PD6)
- El-Morsi & Mahdy 2013 (PD8/PD9)
- Hammad 2021 (PD10)
- Buonaurio 2023 (PD17)

**Still needed (highest value first):**
1. **ECOLIVE original PDF** (#17): https://orgprints.dk/id/eprint/33891/1/ECOLIVE%20GUIDEBOOK-EN.pdf
2. **ARC olive bulletin and HRI variety map, plus the 13 registered selections** (not online; HRI Olive Dept.)
3. **Egyptian pesticide committee (APC) list of registered bio-products for olive** (not online)
4. **Executive regulations of Law 12/2020** (Official Gazette)
5. EU 2021/1378, consolidated (#6): approved control bodies for Egypt
6. Psyllid study, Al-Arish (PD2): https://ejar.journals.ekb.eg/article_397361.html
7. Prays and Palpita phenology in Egypt (PD3, PD4, PD5)
8. Saline reclaimed-soil cultivar trial (V3): https://ajas.journals.ekb.eg/article_263933.html
9. FAO Paper 66, fruit-trees chapter (#70): https://www.fao.org/3/i2800e/i2800e00.htm
10. IOC olive-oil trade standard, Rev. 21 (#8)
11. Elsayed 2014 thesis, **results chapters** (V7)

## 0.5 Manual blueprint (from the structure of the Organic Medjool Manual)

The olive manual reuses the Medjool manual's format, a **single bilingual HTML file (Arabic RTL default / English)**:
- **Page:** sticky top bar with a language switch; hero with edition, date and fact strip (location, variety, system, number of sources); confidence legend; collapsible table of contents; numbered sections with stable anchors (`ar-s1…`, `en-s1…`).
- **Tasks:** every task line carries numbered **hyperlinked citations**, a **confidence badge** (High, Medium, Low, Expert inference), and a **"How often" line** stating whether the number is *stated in source*, *set by the compiler from source timing* or *not given in sources*.
- **Plans:** a **phase-filtered 52-week work plan**, plus a **timeline plan for new plantings**.
- **Closing sections:** an **information-gaps** section listing what the sources did not give; a numbered **reference list** with URLs.
- **Annexes:** organism cards, a weather and spectral-index relation table, a detection-method comparison, and an **"Expert interpretation for AgriPulse"** table.

Olive chapter map (Medjool equivalent in brackets):
1. Introduction and scope
2. Methodology and confidence scale
3. Variety profiles: Koroneiki, Picual, Coratina, Aggezi Shami, Manzanillo, Kalamata, Toffahi, Maraki, Arbequina, plus ARC lines (was: single variety card)
4. Production environments of Egypt: 8 zones
5. Organic regulatory framework: Law 12/2020, EU 2018/848, Codex
6. Operating methodology: olive phenology (BBCH) and the operating phases of the plan
7. Orchard establishment: systems, spacing, stock, site preparation
8. New plantings, years 0–4, with a timeline plan
9. Cultural operations: pollination and pollinizers, pruning and training, irrigation, organic fertilisation, soil and cover crops
10. Organic pest and disease management: fly, moths, psyllid, scales, borers, mites, nematodes; peacock spot, knot, Verticillium, root rot; remote-sensing monitoring
11. Harvest and processing: maturity index, harvest dates, organic oil and natural table olives
12. Weekly work plan, weeks 1–52, filtered by phase
13. Information gaps
14. References

Annexes:
- **Annex A:** olive fruit fly (indices, weather and detection)
- **Annex B:** olive pests and diseases matrix, with expert interpretation for AgriPulse

---

# PART 1: Research dossier

## Organic Olive Manual for Egypt — Task 1: Research Dossier

**Status:** Research phase (Task 1). This file collects the evidence for the manual, analyzes it, flags gaps, and lists source files to download.
**Update (review of uploaded files):** I read 9 files in full. **Section 6** reviews each one. Where a full text contradicted an earlier search-based figure, the figure is corrected in place and marked *(corrected from full text)*.
**Date:** 2026-10-21
**Target output (next tasks):** An Arabic organic olive production manual (دليل الإنتاج العضوي للزيتون في مصر), Word format, with an AgriTech / remote-sensing chapter that ties into AgriPulse.

> **How this research was done.** The research container's network policy blocked direct downloads and page fetches from every source host (IOC, EUR-Lex, EKB journals, orgprints, CSIC, KCOA). Because of that, the findings below come from search-engine extracts of each source, not from reading the full PDFs. Each number names its source. Before a number goes into the manual, check it against the full text in **Section 4 (files to download)**. When you upload those files, I will read them in full and correct this dossier.

---

### 1. Executive summary

1. **Egypt is a table-olive country moving toward oil.** IOC balances show Egypt produced about **750 kt of table olives** and **52 kt of olive oil** in 2023/24 (final). Provisional 2024/25 figures are 600 kt of table olives and 80 kt of exports. Egypt ranks around **3rd worldwide among table-olive exporters**. National policy targets expansion and oil cultivars (Koroneiki, Coratina). For an organic manual, both product lines need chapters: table olives and oil.
2. **The legal base exists: Law No. 12 of 2020 on Organic Agriculture**, which has 20 articles and executive regulations. Two bodies share oversight *(corrected from full text)*. The **General Administration of Organic Agriculture** (Ministry of Agriculture) covers primary production up to harvest. The **National Food Safety Authority (NFSA)** covers the post-harvest stage. The Central Laboratory of Organic Agriculture provides technical support. The decree number and date of the executive regulations still need confirmation from the Official Gazette (الوقائع المصرية). For export, the EU standard (Reg. 2018/848) applies in practice, with imports certified by control bodies listed in **Annex II of Implementing Reg. 2021/1378**. Egyptian certifiers have had recognition problems: COAE was withdrawn in 2014 and ECOA was suspended in 2017. Exporters therefore usually rely on international control bodies.
3. **Main agronomic constraints in Egypt:** sandy or calcareous desert soils, saline groundwater (Siwa, the North Coast, Sinai), high evaporative demand, and **warm winters that cut chilling**, which leads to poor or irregular flowering. Cultivar choice per region is the first organic "input decision".
4. **Pest pressure is manageable organically.** The key pests are the olive fruit fly (*Bactrocera oleae*), olive moth (*Prays oleae*), jasmine moth (*Palpita unionalis*), black scale (*Saissetia oleae*), leopard moth (*Zeuzera pyrina*), and olive psyllid (*Euphyllura*). The key diseases are peacock spot (*Spilocaea oleagina*) and Verticillium wilt. Egyptian studies already cover native **Trichogramma** species, black-scale parasitoids (*Metaphycus*), pheromone mating disruption against leopard moth, entomopathogenic nematodes, and fly trapping. Mediterranean organic trials support **kaolin**, **spinosad bait**, **Bt (Btk)** and copper within the EU cap of **28 kg Cu/ha over 7 years**.
5. **Water is the binding resource.** Egyptian trials favour drip, partial root-zone drying, or subsurface drip at **60–80 % ETc**. Farmer practice can use about **31.5 m³/tree/yr** against **10–18 m³** in scheduled treatments. Mediterranean data show the FAO-56 default olive Kc of about 0.70 **overestimates** use in sparse groves, where measured mid-season Kcb is about 0.40–0.45. Kc must come from canopy cover, which is exactly what remote sensing measures.
6. **Organic fertility can be closed on-farm.** Olive-mill pomace and wastewater compost gave yields close to commercial organic-mineral fertilizer in a 3-year organic trial. Egyptian Picual trials with **feldspar plus K-solubilizing biofertilizer** raised yield up to 70 %. The nutrient budget is about **3–4 kg N per tonne of fruit**, and harvest plus pruning remove about 54 kg N/ha/yr. Leaf analysis targets: **N 1.5–2.0 %, K 0.8–1.0 %**, sampled in July from non-bearing shoots.
7. **Remote sensing has a strong evidence base for olives.** Sentinel-2 NDVI combined with weather reproduces root-zone water status (r² ≈ 0.80, Battista et al. 2023). UAV thermal and hyperspectral imaging detects **Verticillium** before visible symptoms (Calderón et al. 2013). S1 and S2 time series map grove decline (Morocco, OA 0.93). Yield prediction from satellite data is still research-grade. The manual should present it as advisory, not certified.

---

### 2. Analysis by manual chapter

Confidence key: **H** = several consistent sources or established regulation. **M** = one solid study. **L** = abstract or secondary only, or a gap.

#### 2.1 Egyptian olive sector and agro-ecological zones (M)
- Area grew from about 3,700 ha (1980) to about 65,300 ha (2009) (IOC Egypt policy 2012). More recent area figures need FAOSTAT or MALR statistics. The North Sinai study reports 2005–2023 averages of **715.5 kt fruit / 54.3 kt oil** in feddan units.
- Regional shares (Tridge, secondary): Nubaria ≈28 %, Ismailia ≈14 %, Fayoum ≈13 %. Other major zones: North Sinai (Arish), Matrouh/North Coast (rainfed and supplementary irrigation), Siwa (saline, traditional), and new lands west of the Delta (Wadi El-Natrun, Sadat, Cairo–Alex desert road), plus Minya, Ras Sudr and East Owainat.
- Policy: ARC Horticulture Research Institute plans expansion to about 50 k feddan and 100 M trees, a variety map per region, and certified seedlings via an olive producers and exporters council.

#### 2.2 Cultivars (M)
| Cultivar | Use | Egyptian evidence |
|---|---|---|
| Picual | Oil, dual | Widely planted; good across Minya, Nubaria and Sinai. Best harvest in N. Sinai is about **2 November** (MI 3.2–3.4 in normal years) *(corrected from full text; was "2nd half of Nov")* |
| Koroneiki | Oil | Highest yield (44 kg/tree) and oil (≈50 % DW) on reclaimed land; best under super-high-density in Ismailia; top salinity and drought tolerance in one pot study. Poor in Minya |
| Coratina | Oil | Recommended oil cultivar by ARC; salinity-tolerant |
| Aggezi Shami / Aggezi Akse (عجيزي) | Table | Local; best in Minya; highest yield in a salinity trial |
| Toffahi (تفاحي) | Table | Largest fruit; low oil (≈20 % DW) |
| Manzanillo | Table | Matures 15–30 days before others (N. Sinai) |
| Kalamata | Table | Sinai irrigation and fertilizer trials |
| Arbequina, Arbosana, Koroneiki | SHD hedgerow | 4 × 1.5 m systems trialled in Egypt |
| Hamid, Wetteken (Siwa) | Local | Yield falls with salinity, Wetteken more so |

**Analysis:** Organic production favours cultivars with low input needs and tolerance of local stresses. That means Koroneiki or Coratina for oil in saline or desert sites, and Picual for broad adaptation. Aggezi suits table olives in Middle Egypt. Chilling must also be weighed. Warm-winter flowering failure is documented internationally (Engelen et al. 2023), but Egyptian chilling data are a **gap**. Local North African cultivars reportedly tolerate heat better.

#### 2.3 Legal and certification framework (H for EU, M for Egypt)
- **Egypt:** Law 12/2020 (issued by presidential ratification and published in the Official Gazette). The executive regulations cover standards, permitted input lists for plant, animal and aquatic production, registration and renewal of organic units, and control procedures. Fines of EGP 5,000–500,000. The law creates a national organic logo and import and export controls. **Still to confirm:** the regulation decree number and date, the conversion period, and the national input list.
- **EU (export market):** Reg. (EU) **2018/848** is the basic act. Annex II Part I sets a **conversion period of 3 years before harvest for perennial crops**. Reg. (EU) **2021/1165** lists authorised inputs (fertilizers in Annex II, plant protection substances in Annex I). Copper is capped at **28 kg/ha over 7 years** under Reg. 2018/1981; the approval was extended to 30 June 2029 by Reg. 2025/1489. Imports must come through control bodies in **Reg. 2021/1378 Annex II**, last amended by 2024/2140 and 2026/1398.
- **Certifier history:** COAE was delisted by the EU in 2014 and suspended by USDA in 2013. ECOA's EU equivalence was suspended in 2017. Icert is listed by IFOAM as EU-approved (undated). **Action:** check the current Annex II for Egyptian-operating bodies before the manual names any.
- **Plant health:** *Xylella fastidiosa* is a quarantine pest absent from Egypt. Egypt suspended imports of fruit-tree seedlings from infected countries (WTO notification, 2017). The manual needs a "certified clean nursery stock only" rule.

#### 2.4 Site, soil and orchard establishment (M)
- Salinity: FAO classes olive as moderately tolerant, with ECe threshold **3–6 dS/m**. A field threshold of **4 dS/m** was found for Arbequina (−12 % per dS/m). Irrigation water at 4.2 dS/m caused little loss in the Negev. Keep the root zone below 6 dS/m. Waterlogging combined with salinity is the worst case, as in Siwa.
- Planting systems: traditional (7×7 or 6×6 m), intensive, and super-high-density (SHD) at 4 × 1.5 m on a central leader with trellis. SHD gave higher yield per area for Koroneiki in Ismailia. Intensive planting gave larger fruit.

#### 2.5 Irrigation (M–H)
- Drip versus flood in Fayoum: about 447 versus 704 mm/yr, and flood irrigation lost about 24 % yield.
- Kalamata in N. Sinai: alternate partial root-zone irrigation saved ≥20 % water. 60 % ETc reduced performance and 80 % ETc was intermediate.
- Coratina in the W. Delta: about 9.9–17.9 m³/tree/yr in scheduled treatments versus 31.5 for farmer practice.
- Subsurface inclined drip in Benha: 17.9–21.9 t/ha, with water productivity of 2.8 kg/m³.
- **Kc:** use Kcb from ground cover (Allen & Pereira). Mid-season Kcb is about 0.40–0.45 for sparse groves, against the FAO-56 default of about 0.70. This is a direct use for satellite-derived canopy cover in AgriPulse.
- Severe deficit should be avoided at flowering and fruit set, and applied during pit hardening (summer) when evaporative demand is high (standard RDI practice).

#### 2.6 Organic fertility management (M)
- Nutrient demand is about 3–4 kg N per tonne of fruit (UC: 6–8 lb/ton). Harvest plus pruning remove about 54 kg N, 46 kg K and 58 kg Ca per ha per year. P and Mg removal is below 7 kg/ha.
- Leaf standards: N optimum 1.5–2.0 % (deficient below 1.4 %); K optimum 0.8–1.0 % (deficient below 0.4 %). Sample in July from 100 leaves on non-bearing shoots.
- On-farm options supported by evidence: olive-mill pomace and wastewater compost (≈ commercial fertilizer yield over 3 yrs), shredded pruning-wood compost, farmyard manure or poultry compost (check certifier rules on factory-farm manure), legume green manure such as faba bean (lower yield in the Italian trial), feldspar plus K-solubilizing bacteria (Picual +70 %), humic acid, and EM.
- **Gap:** Egyptian kg-per-tree compost recommendations by tree age. ARC bulletins should hold these and need to be uploaded.

#### 2.7 Pest management: organic IPM (M)
| Pest | Egyptian data | Organic tools with evidence |
|---|---|---|
| Olive fruit fly *Bactrocera oleae* | Higher pressure in Behera than Fayoum; yellow sticky traps beat McPhail; Matrouh spring peaks in Mar and May; 8 parasitoids active Jul–Nov | Kaolin (consistent reduction, Sicily and Catalonia); spinosad, including GF-120 bait; mass trapping as a supplement (30–100 % damage reduction, variable). EU organic rules also allow **deltamethrin or lambda-cyhalothrin, but only inside attract-and-kill traps against *B. oleae*** (Reg. 2021/1165 Annex I). Destroy or graze fallen fruit; harvest early; mill quickly |
| Olive moth *Prays oleae* | 3 generations: Mar–Apr, May–Jun, Aug–Oct | Btk at the flower generation (86.6 % lab mortality); Trichogramma releases |
| Jasmine moth *Palpita unionalis* | Pheromone-monitored in arid and semi-arid groves | Btk (80.9 % lab); 4 native *Trichogramma* spp.; monthly *T. evanescens* releases plus neem |
| Black scale *Saissetia oleae* | Peak in October; *Metaphycus lounsburyi* parasitism 34–40 % | Conserve parasitoids; summer mineral oil (paraffin) if allowed; open canopy pruning |
| Leopard moth *Zeuzera pyrina* | Serious in dense plantings | Pheromone mating disruption (Egypt field trial); entomopathogenic nematodes injected into galleries; UV-pheromone traps |
| Olive psyllid *Euphyllura* | **Gap** in Egyptian data | Kaolin and soap at flowering (to verify) |

#### 2.8 Diseases (L–M)
- Peacock spot (*Spilocaea oleagina*) was confirmed in Ismailia and Behera and reduces pigments and carbohydrates. Copper is effective (3 sprays at 15-day intervals in trials). In organic production, copper counts against the 28 kg/7-yr cap, so the manual will pair it with pruning for airflow.
- Verticillium wilt is the most serious soil-borne threat worldwide. **No Egyptian survey was found (gap).** Prevention: clean stock, avoid previous solanaceous or cotton sites, solarisation, organic amendments. Early detection by UAV thermal imaging.
- Olive knot (*Pseudomonas savastanoi*) and root rots: not researched yet. Copper after pruning or hail wounds.

#### 2.9 Harvest, post-harvest and processing (M)
- Jaén maturity index: 100 fruits are scored 0–7. Picual's optimum is MI 3–4. Recommended harvest dates for N. Sinai, from the full text of Nagaty & Awad 2024: **Manzanillo 19 Oct** (up to 2 weeks earlier in hot years), **Picual and Chemlali 2 Nov**, **Koroneiki 2–16 Nov**. Free acidity rose from about 0.2–0.35 % (5 Oct) to 1.1–1.9 % (16 Nov). Late fruit therefore risks losing the extra-virgin grade (≤0.8 %).
- Oil quality: EU and IOC extra virgin limit is ≤0.8 % free acidity. The IOC trade standard is COI/T.15/NC No 3, now Rev. 21/22 (2025).
- Table olives: IOC standard COI/OT/NC No 1 (2004). Natural fermentation is lactic. *(Corrected from full text)* For natural olives the IOC sets a **minimum** of 6 % NaCl, a **maximum** pH of 4.3 and a minimum of 0.3 % lactic acid. For treated (lye) olives the figures are a minimum of 5 % NaCl, a maximum pH of 4.0 and a minimum of 0.5 % lactic acid. The earlier "≤6 %" figure came from a secondary FSSAI source and was wrong.
- **Organic table olives must be natural-style (no lye).** Reg. 2021/1165 Annex V allows sodium hydroxide only for sugar, plant protein extracts and "oil from plant origin **excluding olive oil**", and for Laugengebäck, but not for olives. The IOC preservatives (benzoic and sorbic acid), the colour stabilisers (ferrous gluconate and lactate), calcium chloride as a firming agent, and MSG are not authorised for this use in organic food. Allowed acidifiers and antioxidants: lactic (E270), citric (E330), tartaric (E334), malic (E296) and ascorbic acid (E300), plus calcium citrates (E333). Confirm against the consolidated Annex V before printing, since it is amended regularly.
- By-products: pomace and wastewater go back to compost (closes the loop, see 2.6).

#### 2.10 AgriTech and remote sensing chapter (M–H)
| Application | Evidence | Sensor | Relevance to AgriPulse |
|---|---|---|---|
| Root-zone water status | Battista et al. 2023: NDVI plus weather gives r² 0.795 vs soil RSWC | Sentinel-2 | Irrigation advisory per block |
| Kc from canopy cover | Allen & Pereira Kcb from ground cover | S2 (fCover), UAV | ET-based scheduling |
| GPP and productivity | Chiesi et al. 2022, light-use efficiency | S2 | Productivity zoning |
| Grove mapping and decline | Tadla, Morocco: S1+S2 SVM, OA 0.927 | S1, S2 | Detect abandoned or declining blocks |
| Yield estimation | NDVI DTW plus ML (EGU 2024, abstract only) | S2 | Research-grade only |
| Verticillium and water-stress detection | Calderón et al. 2013 (full text): Tc−Ta rises about 2 K at low severity; **CWSI** vs stomatal conductance R² = 0.83; Tc−Ta vs G R² = 0.76. Visible B/BG/BR ratios and fluorescence give early detection; NDVI only shows later structural damage | UAV thermal (20 cm), 6-band multispectral (20 cm), hyperspectral (40 cm) | Scouting and targeted ground checks |
| Xylella and Verticillium diagnosis | ITER drone project | UAV | Future |

Olive groves have two layers (tree plus understory or bare soil). Tree response lags grass response, so indices must be canopy-masked or measured at high resolution. Bare desert soil between trees strongly biases NDVI in Egypt. Use SAVI or MSAVI, or per-tree segmentation.

---

### 3. Gaps that need your uploads or local sources
1. Official ARC / Horticulture Research Institute olive bulletin (نشرة الزيتون), with fertilizer and compost doses by tree age and the service calendar.
2. The executive regulations of Law 12/2020 (decree number and full text) and the national permitted-input lists.
3. The current EU list of control bodies for Egypt (Reg. 2021/1378 Annex II, consolidated).
4. Egyptian chilling and flowering data for Picual, Koroneiki and Aggezi.
5. An Egyptian Verticillium and olive-psyllid survey.
6. MALR or CAPMAS current olive area by governorate.
7. ~~Organic table-olive processing (lye)~~. **Answered:** lye is not permitted for olives under EU organic rules (see 2.9). Still open: whether the Egyptian national list differs.
8. **New:** the ECOLIVE file uploaded is incomplete. About pp. 24–69 are missing: soil management, organic fertilisation doses, fertigation, oil extraction and malaxation, and the disease chapters up to Xylella. Please upload the original PDF (link #17).
9. **New:** the 2018/848 text uploaded is the original 2018 version. Articles 45–57 on imports and the transition for control bodies have since been amended. Please upload the consolidated version, and Reg. 2021/1378 (link #6), to confirm current import rules for Egypt.

---

### 4. Files to download and upload (direct links)

The container could not download any of these because of network policy. Download them and upload them into this chat, or commit them to `docs/reference/olive-organic-manual/sources/`. Priority **A** = essential for the manual.

#### A. Regulation and standards
| # | P | Document | Link |
|---|---|---|---|
| 1 | A | Egypt Organic Law 12/2020, English excerpt (KCOA) | https://kcoa-africa.org/wp-content/uploads/2025/10/KHNA-EG-20-Egyptian-National-Law-on-Organic-Agriculture_excerpt-transalted-to-English-2.pdf |
| 2 | A | COAE — standards and laws page (Arabic/English law texts) | https://www.coae-egypt.com/?portfolio=fresh-vegetables |
| 3 | A | COAE — Organic Law registration notice | https://www.coae-egypt.com/?p=9138 |
| 4 | A | EU Reg. 2018/848 (organic basic act) | https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32018R0848 |
| 5 | A | EU Reg. 2021/1165 (authorised inputs) | https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32021R1165 |
| 6 | A | EU Reg. 2021/1378 (recognised control bodies, check consolidated version) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02021R1378-20260101 (if the date suffix fails, open https://eur-lex.europa.eu/eli/reg_impl/2021/1378 and choose "Current consolidated version") |
| 7 | B | EU Reg. 2018/1981 (copper 28 kg/7 yr) | https://eur-lex.europa.eu/eli/reg_impl/2018/1981/oj/eng |
| 8 | A | IOC trade standard olive oils COI/T.15/NC3 Rev.21 | https://data.consilium.europa.eu/doc/document/ST-7949-2025-ADD-2/en/pdf |
| 9 | A | IOC trade standard table olives COI/OT/NC1 | https://www.internationaloliveoil.org/wp-content/uploads/2019/11/COI-OT-NC1-2004-Eng.pdf |
| 10 | B | USDA GAIN Egypt food import regulations 2020 | https://apps.fas.usda.gov/newgainapi/api/Report/DownloadReportByFileName?fileName=Food+and+Agricultural+Import+Regulations+and+Standards+Country+Report_Cairo_Egypt_12-31-2020 |
| 11 | B | Organic Egypt newsletter (law context) | https://organicegypt.org/newsletter-volume-5-march-to-june-2020/ |

#### B. Sector and statistics
| # | P | Document | Link |
|---|---|---|---|
| 12 | A | IOC Egypt olive policy 2012 | https://www.internationaloliveoil.org/wp-content/uploads/2019/11/ENGLISH_POLICY_-EGYPT-2012_OK.pdf |
| 13 | A | IOC table olive balance Dec 2025 | https://www.internationaloliveoil.org/wp-content/uploads/2025/12/122-OT-2025.pdf |
| 14 | A | IOC olive oil balance Dec 2025 | https://www.internationaloliveoil.org/wp-content/uploads/2025/12/122-HO-2025.pdf |
| 15 | B | Egypt olive production and economics (N. Sinai, 2005–2023) | https://sinjas.journals.ekb.eg/article_414567_521a472c1e6656043372a40ec69e8ba0.pdf |
| 16 | B | Agricultural and food policies in Egypt 2014–2021 (ARI) | https://s3.eu-central-1.amazonaws.com/storage.arab-reform.net/ari/2023/01/05152104/2023-01-05-EN-Agricultural-and-Food-Policies-in-Egypt-between-2014-and-2021-What-Changed-and-What-didnt.pdf |

#### C. Organic olive manuals (templates)
| # | P | Document | Link |
|---|---|---|---|
| 17 | A | ECOLIVE organic olive oil training guidebook (Erasmus+) | https://orgprints.dk/id/eprint/33891/1/ECOLIVE%20GUIDEBOOK-EN.pdf |
| 18 | A | UC ANR Organic Olive Production Manual (Vossen, pub. 3505; paid, ISBN 9781601074409) | https://anrcatalog.ucanr.edu (search "Organic Olive Production Manual") |
| 19 | B | UC olive fertilization notes | https://ucanr.edu/node/107355 |
| 20 | B | UC leaf-analysis standards PDF | https://class.ucanr.edu/sites/default/files/2011-05/90442.pdf |

#### D. Egyptian agronomy studies (EKB)
| # | P | Topic | Link |
|---|---|---|---|
| 21 | A | Cultivar evaluation under Egyptian conditions | https://journals.ekb.eg/article_118657.html |
| 22 | B | Cultivars in Minya | https://journals.ekb.eg/article_41901.html |
| 23 | B | Cultivars (AJAS, Arabic) | https://ajas.journals.ekb.eg/article_263933_106e61a98382bc268396b22a3e4d27d3.pdf?lang=ar |
| 24 | A | Irrigation of Kalamata, N. Sinai (PRD/RDI) | https://journals.ekb.eg/article_40874.html |
| 25 | A | Subsurface drip, Benha | https://fjard.journals.ekb.eg/article_197024_68bb6e6a629948c9202d9ba7389b43c8.pdf |
| 26 | B | Emitter types, Beheira | https://mjae.journals.ekb.eg/article_456899_2597a184a6818f54d49684b49d263529.pdf |
| 27 | B | Irrigation study (MJAE) | https://mjae.journals.ekb.eg/article_96079_1b7264318f3cc5e84e0e109ce44a2016.pdf?lang=ar |
| 28 | A | Irrigation regime plus organic/bio fertilizer | https://ejss.journals.ekb.eg/article_29031_1e98257e722bb6e96c626fd18dc43581.pdf |
| 29 | B | Drip vs flood, Fayoum | https://journals.ekb.eg/article_39619.html |
| 30 | A | Harvest date and maturity, N. Sinai (Picual) | https://sinjas.journals.ekb.eg/article_358816_9e1f8cf2590f37fa5d364d377425b4ab.pdf |
| 31 | A | Intensive vs SHD, Ismailia | https://hrj.journals.ekb.eg/article_389568_982f1291333d59ef2aeca6a8ba9f954d.pdf |
| 32 | B | High-density oil quality (EJCHEM) | https://ejchem.journals.ekb.eg/article_233788_d41d8cd98f00b204e9800998ecf8427e.pdf |
| 33 | A | Salinity: cultivars (SJAS) | https://sjas.journals.ekb.eg/article_459730_813418d114671e4da84d2e3f602bf3f3.pdf |
| 34 | B | Siwa cultivars vs well-water quality | https://jpp.journals.ekb.eg/article_258944.html |
| 35 | B | Aggezi and Koroneiki with organic/bio-fertilizers (AGRIS) | https://agris.fao.org/search/en/records/67598a42c7a957febdfb7aea |
| 36 | B | Picual feldspar plus K-biofertilizer | https://www.bio-conferences.org/articles/bioconf/abs/2024/01/bioconf_msnbas2024_02012/bioconf_msnbas2024_02012.html |
| 37 | B | Organic vs inorganic fertilizer, South Sinai | https://journals.ekb.eg/article_36607.html |

#### E. Pests and diseases
| # | P | Topic | Link |
|---|---|---|---|
| 38 | A | Olive fly spring catches (Egypt) | https://ejdr.journals.ekb.eg/article_5805_6af064194148611ada924e2f551771ab.pdf |
| 39 | A | Olive fly population, Behera vs Fayoum | https://doaj.org/article/0a7b07ebb89248929ebc81fed33dab6f |
| 40 | A | Kaolin plus spinosad in an organic grove | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10056781/ |
| 41 | B | Eco-trap mass trapping, organic | https://orgprints.org/id/eprint/7976/1/Caleca_et_alIOBC.pdf |
| 42 | B | Catalonia organic olive fly alternatives | https://ruralcat.gencat.cat/documents/20181/8633778/grups_operatius_en_119/9f4c249c-7605-4707-9b5e-3894893b6872 |
| 43 | A | Black scale parasitoids, Egypt | https://ojs.uniba.it/index.php/entomol/article/download/828/660 |
| 44 | A | Scale insects and psyllids survey, Egypt | https://journals.ekb.eg/article_15172.html |
| 45 | A | Prays and Palpita phenology (Insect Science 2011) | https://wiki.pestinfo.org/wiki/Insect_Science_(2011)_18,_565-574 |
| 46 | A | Trichogramma in Egyptian olive groves | https://asejaiqjsae.journals.ekb.eg/article_6815_aef398d95eebcc2926b6ebe34843578e.pdf |
| 47 | B | Bt strains vs Prays and Palpita (Insect Science 2005) | https://wiki.pestinfo.org/wiki/Insect_Science_(2005)_12,_185-192 |
| 48 | B | Organic Prays control, Portugal (IPB) | https://bibliotecadigital.ipb.pt/bitstreams/c128fd76-c359-4bed-8bcd-dee02ab6753d/download |
| 49 | B | Bulletin of Insectology 2023 (olive pests) | https://archive.bulletinofinsectology.org/pdfarticles/vol76-2023-271-281ksentini.pdf |
| 50 | A | Leopard moth mating disruption, Egypt | https://academic.oup.com/aesa/article/102/5/809/89654 |
| 51 | B | Leopard moth, nematodes and imidacloprid | https://journals.ekb.eg/article_17040.html |
| 52 | B | Leopard moth pheromone trapping (Tropentag) | https://www.tropentag.de/2013/abstracts/links/Hegazi_iZPgtq3i.pdf |
| 53 | B | Peacock spot, Egypt (Benha Univ.) | https://bu.edu.eg/staff/hassanemara7-publications/29001 |
| 54 | B | Xylella and Egyptian quarantine (CIHEAM) | https://ressources.ciheam.org/ressources/om/pdf/a121/00007227.pdf |

#### F. Water, compost and climate
| # | P | Topic | Link |
|---|---|---|---|
| 55 | A | Olive Kcb and transpiration (Water MDPI 2021) | https://iris.unipa.it/retrieve/e3ad8927-5d7d-da0e-e053-3705fe0a2b96/117%202021%20Sirera%20Transpiration%20and%20water%20uses%20-%20Water%20MDPI-13-02466-v2.pdf |
| 56 | B | Dual Kc olive (Évora) | https://dspace.uevora.pt/rdpc/bitstream/10174/19187/1/FLSantos_SDualWater%20use.pdf |
| 57 | A | Olive-mill by-products in an organic orchard (JAST 2016) | https://jast.modares.ac.ir/article_15982.html |
| 58 | B | Pomace as amendment (Casacchia 2012) | https://iris.unibas.it/retrieve/dd9e0b50-fd5c-1e84-e053-3a05fe0aa940/2012%20-%20Casacchia%20et%20al%20-%20IJA.pdf |
| 59 | B | Chilling and olive flowering (Plants 2023) | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10143890/ |
| 60 | B | Saline irrigation of olive (HortScience) | https://journals.ashs.org/view/journals/hortsci/43/2/article-p320.xml |
| 61 | B | Arbequina salinity field threshold | https://citarea.cita-aragon.es/bitstream/10532/2572/1/Aragues_vegetative.pdf |

#### G. Remote sensing
| # | P | Topic | Link |
|---|---|---|---|
| 62 | A | Sentinel-2 plus meteo, olive water shortage | https://flore.unifi.it/bitstream/2158/1423285/1/Estimating%20the%20effect%20of%20water%20shortage%20on%20olive%20trees%20by%20the%20combination%20of%20meteorological%20and%20Sentinel-2%20data.pdf |
| 63 | A | UAV thermal and hyperspectral Verticillium detection | https://quantalab.ias.csic.es/pdf/paper_verticillium_calderon_RSE_2013.pdf |
| 64 | B | Olive classification and yield, S2 (EGU24) | https://meetingorganizer.copernicus.org/EGU24/EGU24-13375.html |
| 65 | B | S1+S2 olive decline mapping (2026) | https://www.bio-conferences.org/articles/bioconf/pdf/2026/04/bioconf_icwes2025_01006.pdf |

#### H. Arabic sources to request locally (no direct link found)
- ARC Horticulture Research Institute, Olive Research Dept.: "زراعة وإنتاج الزيتون" technical bulletin, and the annual service calendar (التقويم الزراعي للزيتون). Available from the ARC Agricultural Extension (الإدارة المركزية للإرشاد الزراعي) or https://www.arc.sci.eg.
- Central Laboratory of Organic Agriculture (المعمل المركزي للزراعة العضوية): national standard and permitted-input lists.
- Desert Research Center (مركز بحوث الصحراء): olive bulletins for Matrouh and Sinai.
- Official Gazette text of the Law 12/2020 executive regulations.

---

### 5. Proposed manual outline (for Task 2, in Arabic)
1. مقدمة: قطاع الزيتون في مصر والفرص التصديرية العضوية
2. الإطار التشريعي والاعتماد (قانون 12/2020، اللائحة الأوروبية 2018/848، فترة التحول، السجلات)
3. اختيار الموقع والمناطق الزراعية البيئية في مصر (التربة، المياه، الملوحة، البرودة)
4. الأصناف الموصى بها لكل منطقة (زيت / مائدة / ثنائي الغرض)
5. إنشاء البستان العضوي: الشتلات المعتمدة، المسافات، أنظمة الزراعة
6. إدارة التربة والتغطية النباتية والكمبوست (تدوير مخلفات المعاصر والتقليم)
7. التسميد العضوي وبرنامج التحليل الورقي
8. الري وجدولته (ETc، Kc، الري الناقص المنظم، إدارة الملوحة)
9. التقليم والتربية
10. المكافحة المتكاملة العضوية للآفات (تقويم شهري للآفات والمكافحة)
11. الأمراض وإدارتها
12. الحصاد ومؤشر النضج
13. التصنيع العضوي: زيت الزيتون وزيتون المائدة
14. الزراعة الرقمية والاستشعار عن بعد (Sentinel-2، الطائرات المسيرة، منصة AgriPulse)
15. السجلات والتتبع ونماذج المراقبة
16. التقويم السنوي لعمليات الخدمة
ملاحق: قوائم المدخلات المسموح بها، نماذج السجلات، المراجع

---

### 6. Review of uploaded files (full-text reading)

**Received:** links #1, #4, #5, #9, #12, #17 (incomplete), #30, #62, #63. Everything else in Section 4 is still outstanding.

#### 6.1 Egypt Organic Agriculture Law 12/2020, English excerpt (KCOA/GIZ, 2021)
**What it is:** a 7-page summary of the law plus a sector overview. It is not the official text.
**Key content:**
- Parliament approved the law on 26 Jan 2020. It has 20 articles.
- **Art. 3** splits the competent authorities. The **General Administration of Organic Agriculture** handles primary production up to harvest. The **National Food Safety Authority** handles the post-harvest stage. Both set input and product standards, testing, labels and import/export conditions.
- **Art. 4:** every conformity (certification) body must register with them and print its registration number on every certificate.
- **Art. 5–7:** there is a national organic logo carrying a code number (product, conformity body, commodity, production date), which is mandatory on products sold locally. A separate logo marks permitted local inputs. False use of either logo is banned.
- **Art. 8:** every exporter needs a certificate from the Administration or the Authority showing registration with a licensed conformity body. This certificate is part of the export file.
- **Art. 11:** conformity bodies must report certificates and audit results within 30 days.
- **Art. 12:** producers and traders must keep records and notify their organic programme.
- **Art. 13:** the executive regulations define the standards and input lists, registration and renewal, import controls, sanctions, and rules for **biological-control agents** (beneficial insects, microorganisms).

**Sector data (2016, FiBL/IFOAM):**
- 105,908 ha certified organic, about 970 farms. Egypt has the highest organic share of farmland in Africa (2.8 %). About half the farms are in Middle Egypt, especially Fayoum.
- 40–50 % of organic output is exported, mainly to the EU and USA.
- Growth zones: East Delta (Qalyubia, Sharkia, Ismailia), North Sinai, Upper Egypt.
- Sector bodies: UGEOBA, FAODAS, EAGA organic council, and the Ministry of Trade organic committee.

**For the manual:** the law's structure gives the outline of the "Legal framework" chapter. It also adds a mandatory **export certificate (Art. 8)** step to the export flowchart.
**Caveats:**
- It still does not give the **number or date of the executive-regulations decree** or the **conversion period**.
- It describes COAE as EU-recognised, but that information predates the 2014 delisting, so it is outdated.

#### 6.2 IOC, "Policies – Egypt" (2012)
**Key content:**
- Table olives are about 80 % of olive output.
- Area: 65,303 ha in 2009, of which 56,330 ha bearing. Olives cover about 4 % of crop area.
- Egypt pioneered micro-irrigation of olives on desert sand with less than 80 mm of rain. It irrigates with aquifer water up to **EC 11.7 dS/m**.
- **Organic in 2009:** 445 ha for oil and 890 ha for table olives (400 and 650 ha in production). Organic table-olive yield was **7.30 t/ha against 10.20 t/ha** conventional. The oil-orchard yields are printed as "10.35 vs 7.38 kg/ha", which is clearly a unit error for t/ha.
- Price premium was small: organic oil-olives €0.44/kg against €0.40/kg; organic green table olives €0.54/kg against €0.49/kg (2009/10).
- Varieties, with share of olive area:

  | Variety | Use | Notes | Share |
  |---|---|---|---|
  | Aggezi Shami | Table | Oil 7–9 %; moderately susceptible to fly | 20 % |
  | Hamed (Siwa) | Table | Drought- and salt-resistant | 6 % |
  | Toffahi | Table | Oil 5–7 %; unsuitable for black pickling | 6 % |
  | Wateken (Siwa) | Oil | High oleic | 5 % |
  | Maraki (Siwa) | Oil | Expected to become the main oil cultivar | 2 % |
  | Aggizi Akse | Table | Green pickling | — |

- Some trees were uprooted in 2009–10 because of **climate change**. Density is 70–100 trees/ha rainfed and 333–400 trees/ha irrigated.
- Irrigated oil-olives give **14–18 % mill yield** (dry-farmed up to 22 %). 45–70 % of oil is extra virgin.
- Planned actions include reusing pomace and wastewater as fertiliser, a satellite census of orchards, and fixing Δ-7-stigmastenol and linolenic acid compliance.

**For the manual:** this is baseline evidence that organic olives in Egypt yield about 28 % less with only an 8–10 % price premium. The economics chapter must address this gap through export premiums, input savings and group certification. Maraki, Hamed and Wateken should be added to the variety table.
**Caveat:** the data are from 2009. Use the newer MALR figures in 6.3.

#### 6.3 Nagaty & Awad (2024), harvest time × cultivar, North Sinai (SINJAS 13(1):29–46)
**Design:** 30-year-old Picual, Manzanillo, Koroneiki and Chemlali trees at 5 × 5 m on sandy loam (soil EC 1.31), drip-irrigated with **well water at EC 6.6 dS/m, SAR 10**. Harvested 5 Oct, 19 Oct, 2 Nov and 16 Nov over 2021–2023.
**Findings:**
- Recommended harvest: Manzanillo **19 Oct** (up to 2 weeks earlier in hot years), Picual and Chemlali **2 Nov**, Koroneiki **2–16 Nov**.
- Oil content follows Chemlali > Koroneiki > Picual > Manzanillo. Phenols, chlorophyll and carotenoids fall with ripening; acidity, peroxide value, K232 and K270 rise.
- Free acidity at 16 Nov was Picual 1.06–1.41 %, Koroneiki 0.82–1.87 % and Manzanillo up to 1.87 %. All exceed the 0.8 % extra-virgin limit.
- **Heat:** when the average temperature during oil accumulation (Aug–Oct) exceeds **25 °C**, or heat waves above **40 °C** last several days, fruit weight, oil content and oil quality fall. Peaks reached 43.9 °C in 2022.
- National context (MALR 2023): **1.13 Mt of olives from 269,000 feddan (2021/22)**. Productivity fell from 5.03 to 4.19 t/feddan (2018–2022, −16 %), and oil output from 40 kt (2018) to 34 kt (2021).

**For the manual:** this is the Egyptian evidence base for the harvest calendar and for a heat-wave rule (bring harvest forward). It also shows olives producing on EC 6.6 water.
**Caveats:** single site, and the yield per tree was not reported.

#### 6.4 IOC Trade Standard for Table Olives, COI/OT/NC No 1 (Dec 2004)
**Key content:**
- **Types:** green, turning colour, black.
- **Trade preparations:** treated (lye), **natural** (brine only), dehydrated/shrivelled, darkened by oxidation, specialities.
- **Sizes:** fruits per kg, 60/70 to 381/410.
- **Categories:** Extra, First and Second, with defect tolerances. Examples for green olives: blemished fruit 4 % / 6 % / 10 %; pits in pitted olives 1 %. Sample of 200 fruits at AQL 6.5.
- **Brine:** natural olives need ≥6 % NaCl, pH ≤4.3 and ≥0.3 % lactic acid. Treated olives need ≥5 % NaCl, pH ≤4.0 and ≥0.5 % lactic acid. Dehydrated olives need ≥10 % NaCl.
- **Pasteurisation:** ≥15 PU at 62.5 °C. Black olives darkened by oxidation need sterilisation at F0 ≥15.
- **Additives:** benzoic acid (1 g/kg), sorbic acid (0.5 g/kg), lactic, citric and tartaric acids (15 g/kg each), ferrous gluconate (0.15 g/kg Fe), CaCl₂, and MSG (5 g/kg).

**For the manual:** this sets the quality and grading chapter for table olives. Section 2.9 lists the subset of additives allowed in organic production; the organic product will be **natural-style** fermented olives.
**Caveat:** this is the 2004 edition. Check the IOC site for any later revision.

#### 6.5 EU Regulation 2018/848 (organic production, original 2018 text)
**Clauses that matter for olives:**
- **Annex II Part I 1.7.1:** perennial crops need a **conversion period of at least 3 years before the first organic harvest**.
- **Art. 10(3):** earlier periods can be recognised retroactively only with proof that the land had no non-permitted inputs for at least 3 years. Abandoned or desert land qualifies.
- **Art. 10(4):** products from the conversion period cannot be sold as organic or in-conversion. The exception is a single-ingredient plant product harvested at least **12 months** into conversion, which may be labelled "in-conversion". This covers olive oil from the 2nd and 3rd harvests.
- **Art. 9(8):** **parallel production** of the same variety is allowed for perennials only under a conversion plan finishing within **5 years**. The farmer must notify each harvest 48 h in advance and report quantities.
- **1.8:** use organic planting material. Non-organic seedlings need an authorisation (third countries: by the control body, 1.8.5.2).
- **1.9:**
  - maintain soil organic matter;
  - perennials need short-term green manures, legumes and plant diversity;
  - manure or compost, preferably from organic sources;
  - livestock manure capped at **170 kg N/ha/yr**;
  - **no mineral N fertiliser**;
  - microbial preparations and biodynamic preparations are allowed.
- **1.10:** prevention comes first (natural enemies, varieties, mechanical methods, **solarisation**). Products are allowed only "to the extent necessary", **with records proving the need**. Traps must prevent contact with the crop and be removed after use.
- **1.12:** keep parcel and harvest records.
- **Art. 30:** a product can be labelled organic only if at least 95 % of its agricultural ingredients are organic.
- **Art. 36:** **group certification** is open to members with holdings of at most 5 ha (or organic turnover of at most €25,000). It requires legal personality, joint marketing and an internal control system. This suits Egyptian smallholders.
- **Art. 45–46:** imports go through control bodies recognised for third countries.

**Caveat:** this is the original text. Art. 57 (old-regime control bodies expiring 31 Dec 2023) and other articles have since been amended. Use the consolidated version.

#### 6.6 EU Implementing Regulation 2021/1165 (authorised inputs and products)
**Plant protection (Annex I), olive-relevant entries:**
- Kaolin.
- **Spinosad**.
- Bt and other approved micro-organisms (all non-GMO approved micro-organisms are allowed, including *Beauveria* and *Trichoderma*).
- Azadirachtin (neem).
- Pyrethrins.
- Paraffin oils.
- Sulphur and lime sulphur.
- Potassium and sodium hydrogen carbonate.
- Fatty acids (soap).
- Pheromones (traps and dispensers only).
- Diammonium phosphate (traps only).
- Ferric phosphate.
- Laminarin.
- Plant oils.
- Diatomaceous earth.
- **Copper compounds** (hydroxide, oxychloride, oxide, Bordeaux mixture, tribasic sulphate) capped at **28 kg Cu/ha over 7 years**.
- **Deltamethrin and lambda-cyhalothrin only in traps with attractants against *Bactrocera oleae*** and *Ceratitis*.
- Basic substances: vinegar, whey, Equisetum, calcium hydroxide, sodium chloride, onion oil and others.

**Fertilisers (Annex II):**
- Allowed: farmyard manure and composted animal excrements (**not of factory-farming origin**), plant-matter compost (with heavy-metal caps), vermicompost, guano, plant by-products such as oilseed cake, wood ash (untreated wood), soft rock phosphate, crude potassium salt, potassium sulphate of natural origin, natural lime and dolomite, gypsum, kieserite, **leonardite and humic acids** (with conditions), stone meal and clays, and micro-organism preparations.
- Mineral micronutrients are allowed only where a need is documented.

**Processing (Annex V):** see 2.9. **No NaOH for olives**, and no benzoate, sorbate or ferrous gluconate.

**Analysis for Egypt:**
- Most Egyptian "organic" inputs on the market (compost, humic acid, feldspar, biofertilisers) fit Annex II, but certifiers need the **manufacturer's certificate of origin** for each.
- Poultry manure from Egyptian battery farms counts as **factory farming** and is **not permitted**.
- Feldspar and potassium-solubilising bacteria fit under "stone meal" and "micro-organism preparations"; confirm with the certifier.

#### 6.7 ECOLIVE: Training for the production of organic olive oil (Scollo et al., 2018, Erasmus+)
**Problem:** the uploaded .docx is a lossy conversion. The text jumps from the soil-analysis table (≈p. 24) straight into the Xylella section (≈p. 69). The missing pages cover soil preparation, **organic fertilisation doses**, fertigation, foliar feeding, harvest and transport, **malaxation and extraction**, and the bacterial-canker, peacock-spot, Phytophthora and Verticillium chapters. **Please upload the original PDF.**

**Usable content from what was received:**
- **Thermal thresholds by stage:** 10 °C to bud burst, 15 °C to flowering, 18 °C to fruit set, 20 °C to veraison. Frost damage starts below −5 °C.
- **Critical water periods:** bud differentiation through fruit set, and the first phase of fruit growth. Pit hardening is the most deficit-tolerant stage, which supports RDI timing.
- Organic groves: a maximum of about **300 trees/ha** is "commonly accepted". This is the guide's recommendation, not a legal rule.
- **Soil favourable values:** depth over 0.8 m, pH 5.5–8.5 (optimum 6.0–7.5), P₂O₅ over 25 mg/kg, K₂O over 50 mg/kg.
- **Olive fly:** biology (3–6 generations; fruit susceptible from pit hardening); controls are mass trapping (30–100 % damage reduction), GF-120, kaolin, pyrethrin bait sprays, sheep grazing of fallen fruit, and early harvest with quick milling.
- **Olive moth:** **Btk timing** is just before bloom for the flower generation, just after fruit set for the fruit generation, and at the start of shoot growth for the leaf generation. Base timing on trap monitoring.
- **Black scale:** prune for airflow and avoid over-irrigation; protect parasitoids by controlling ants; use paraffin oil in **late July and, if needed, mid-August**.
- **Leaf standards:**

  | Nutrient | Deficient | Optimum |
  |---|---|---|
  | N | <1.4 % | 1.5–2.0 % |
  | P | <0.05 % | 0.1–0.3 % |
  | K | <0.4 % | 0.8–1.0 % |
  | Ca | <0.6 % | 1.0–1.43 % |
  | Mg | <0.08 % | 0.1–0.16 % |
  | Fe | <40 ppm | 90–124 ppm |

- **N input** 0.5–1.5 kg/tree/yr (50–150 kg/ha). K should be fertilised "in a 2:1 ratio" to N, especially after an on-year; check the wording in the original PDF.
- **Boron:** 100–150 g borax per mature tree every 4 years, or young trees 10 g × tree age. Boron is toxic in excess.
- **Calcium:** calcium amendment at 5–10 kg/tree only where soil analysis shows a need.

**For the manual:** this gives the structure of the IPM and nutrition chapters. Its Mediterranean timings need shifting earlier for Egypt (earlier bloom, a longer fly season).

#### 6.8 Calderón et al. (2013), UAV detection of Verticillium wilt (Remote Sensing of Environment 139:231–245)
**Design:**
- Two Spanish orchards: a 7 ha Picual orchard at 6 × 4 m, and a 10 ha Arbequina orchard.
- Flights over 2009–2011.
- Sensors: UAV thermal camera (8–12 µm, 20 cm pixels), 6-band multispectral camera (450–800 nm, 20 cm), and a Micro-Hyperspec VNIR imager (260 bands, 40 cm).
- Severity scored on a 0–4 scale.

**Findings:**
- Tc−Ta rises by about **2 K already at low severity**.
- Airborne **CWSI** correlates with stomatal conductance at **R² = 0.83**; Tc−Ta with conductance at R² = 0.76; and with PRI570 at R² = 0.51.
- Visible ratios (B/BG/BR) and chlorophyll fluorescence also detect early infection.
- **NDVI and other structural indices respond only once damage is visible.**
- Symptoms appear 18–24 months after planting in infested soil. Disease builds from late autumn to spring and stalls in summer.

**For the manual and AgriPulse:**
- Sentinel-2 NDVI cannot catch Verticillium early. Early detection needs **thermal or high-resolution drone data at crown level**, flown around midday in summer.
- Recommended practice: a yearly thermal UAV flight on high-value blocks, with ground checks on hot-crown trees.
- The same CWSI approach doubles as an irrigation-stress map.

**Correction:** earlier search notes said the study "did not compute CWSI". It did.

#### 6.9 Battista et al. (2023), Sentinel-2 + weather for olive water stress (European Journal of Remote Sensing 56:2194553)
**Design:**
- Rainfed olive grove near Florence (5 × 5 m, grass understorey), May 2021 – Oct 2022.
- Model: relative soil water content (RSWC) from weather data (DAYMET 200 m grid) plus Sentinel-2 NDVI.
- NDVI is split into **tree and grass cover fractions**, using very-high-resolution images to estimate tree canopy cover.
- Water balance is computed over **60 days for trees** (roots 0.8–1.0 m) and 30 days for grass.

**Result:** tree RSWC matched 1 m soil observations at r² = 0.795, RMSE 0.15, MBE −0.09.

**For AgriPulse:**
- The method transfers to Egypt only with changes. Egyptian groves are **drip-irrigated with bare sand between rows**, so irrigation volumes must be added to the water balance.
- The grass layer becomes a bare-soil layer. NDVI is strongly biased by bright sand, so the tree cover fraction must come from per-tree segmentation (see 2.10).
- Its useful outputs: tree canopy cover over time, which feeds Kcb (2.5), and a water-stress coefficient (Ks) per block.

---

### 7. Changes made in this review
| Item | Before | After (source) |
|---|---|---|
| Picual harvest, N. Sinai | 2nd half of Nov | about 2 Nov (6.3) |
| Natural table-olive brine | ≤6 % NaCl | **≥6 %** NaCl, pH ≤4.3, ≥0.3 % lactic (6.4) |
| Lye in organic olives | unverified | **not permitted** (6.6) |
| Organic table-olive additives | not covered | allowed and banned lists (2.9, 6.6) |
| Competent authorities in Law 12/2020 | CLOA plus NFSA | General Admin. of Organic Agriculture (pre-harvest) plus NFSA (post-harvest) (6.1) |
| Calderón 2013 and CWSI | "did not compute CWSI" | computed, R² = 0.83 (6.8) |
| Olive fly trap insecticides | not covered | deltamethrin or λ-cyhalothrin allowed in traps only (6.6) |
| National production | IOC balance only | MALR 2021/22: 1.13 Mt from 269 k feddan; yield −16 % 2018–22 (6.3) |
| Organic vs conventional yield | not covered | 7.3 vs 10.2 t/ha table olives, 2009 (6.2) |

---

### 8. FAO sources (dedicated search)

**Bottom line:** FAO has **no current organic olive manual**. What it has falls into four groups:
- the FAO/WHO **Codex standards** for organic food, table olives and olive oil;
- the FAO **irrigation papers**;
- one old **regional olive-pest publication** (1992);
- a **new FAO–Egypt olive value-chain agreement** (10 Sep 2026), whose outputs are not yet published.

The download table uses the same priority scale as Section 4 (A = essential). I fetched none of these files; please download and upload them.

| # | P | FAO document | Why it matters | Link |
|---|---|---|---|---|
| 66 | A | **Codex CXG 32-1999**, Guidelines for organically produced foods (rev. 2007, amended 2008–2009) | The international organic baseline that national laws, Egypt's included, are built on. Covers conversion, input lists (Annex 2) and inspection | https://www.fao.org/fileadmin/user_upload/livestockgov/documents/cxg_032e.pdf |
| 67 | A | **Codex CXS 66-1981**, Standard for table olives (2024 version) | The Codex counterpart of the IOC standard, used for export compliance | https://www.fao.org/fao-who-codexalimentarius/codex-texts/list-standards/en/ (search "66-1981"; the French PDF is at https://www.fao.org/input/download/standards/243/CXS_066f.pdf) |
| 68 | A | **Codex CXS 33-1981**, Standard for olive oils and olive-pomace oils (2024 version) | Quality grades and limits for olive oil | Same list page (search "33-1981"); English copy rev. 2017/2021: https://bsti.portal.gov.bd/sites/default/files/files/bsti.portal.gov.bd/notices/cea2a2df_9c32_4ddc_bb3b_f10024e7f0ac/2023-01-19-08-36-1f0f3cdd942461b6a91c362dada016cf.pdf |
| 69 | A | **FAO I&D Paper 56**, Crop evapotranspiration (1998) | Olive Kc table and the method for adjusting it to ground cover (see 2.5) | https://www.fao.org/4/x0490e/x0490e00.htm |
| 70 | A | **FAO I&D Paper 66**, Crop yield response to water (2012). Chapter "Fruit trees and vines" by Fereres, Goldhamer and Sadras, pp. 246–295 | Deficit-irrigation response of olive; main reference for RDI | https://www.fao.org/3/i2800e/i2800e00.htm |
| 71 | B | **FAO I&D Paper 29**, Water quality for agriculture | Salinity and SAR limits for well water such as N. Sinai's EC 6.6 dS/m, SAR 10 (see 6.3) | https://www.fao.org/4/t0234e/t0234e00.htm |
| 72 | B | **FAO Plant Production & Protection Paper 115**, *Olive pests and their control in the Near East* (1992, about 180 pp.) | The only FAO olive-IPM book for the region. Old, but describes the regional pest complex | No online PDF found. Try FAO Open Knowledge (https://openknowledge.fao.org, search "Olive pests Near East"), the ARC library or a university library |
| 73 | B | FAO Regional Symposium on Fruit Flies in the Near East (Hammamet, 2012), proceedings | Surveillance, semiochemicals, sanitation and SIT; *B. oleae* listed among the main regional fruit flies | https://www.fao.org/fileadmin/templates/agphome/documents/Pests_Pesticides/fruitflies/fruitflies.pdf |
| 74 | B | FAO, *Fats, Oils and Related Products* (Codex volume) | Older consolidated text of the olive-oil standard | https://www.fao.org/4/y2774e/y2774e00.htm |
| 75 | B | FAOSTAT crop data: Egypt, olives (area harvested and production) | Official area and yield series to cross-check MALR | https://www.fao.org/faostat/en/#data/QCL |
| 76 | — | FAO–Egypt olive value-chain framework (MoU signed 10 Sep 2026) | Will produce a national olive strategy covering production through marketing, with a push for oil varieties. Nothing is published yet; watch FAO Egypt | News: https://english.ahram.org.eg/News/576406.aspx |

**FAO AGRIS records worth pulling** (abstracts on AGRIS; full texts with the publishers):
- Olive-mill-by-product compost in olive groves: https://agris.fao.org/search/en/records/65df31a863b8185d9cab9822
- Compost and irrigation strategy in olive groves: https://agris.fao.org/search/ru/records/6765396550e69ae818388dff
- Pomace compost and soil fauna: https://agris.fao.org/search/en/records/6765396e50e69ae818388fce
- Aggezi and Koroneiki with organic and bio-fertilisers, Egypt (#35): https://agris.fao.org/search/en/records/67598a42c7a957febdfb7aea

**Non-FAO but close in kind:** an Arabic national olive guide from Jordan's NARC (2nd ed., 2024) has the same chapter structure our manual needs. It is a good template for Arabic terminology: https://www.narc.gov.jo/ebv4.0/root_storage/ar/eb_list_page/olive.pdf

**Evidence from the AGRIS compost records:** pomace (alperujo) compost consistently raises soil carbon, available P and K, and soil fauna. Its yield effect is inconsistent: no change in rainfed groves over 3 years, but +30–41 % in an irrigated hedgerow system. The manual should present compost as a **soil-building practice** rather than a guaranteed yield booster.


---

# PART 2: Pests and diseases

## Organic Olive Manual for Egypt: Pests and Diseases Research

**Date:** 2026-10-21. A companion to Part 1 (Sections 2.7, 2.8 and 6.6–6.8).
**Method:** targeted literature search for Egyptian records, plus the Mediterranean organic-control evidence. Organic status was checked against the full text of **EU Reg. 2021/1165 Annex I** (uploaded and read).
**Confidence:** **H** = several consistent sources, Egyptian data or regulation. **M** = one solid study, or non-Egyptian data likely to transfer. **L** = abstract only, or extrapolated.

> Most Egyptian findings below come from abstracts and search extracts. The download list in Section 6 marks the full texts needed before the manual quotes their numbers.

---

### 1. Key findings

1. **Egypt's olive pest complex is well documented** for the olive fruit fly, olive moth, jasmine moth, psyllid, scale insects, leopard moth, bark beetle and eriophyid mites. Five pests are **severe** in the risk table (Section 4): the olive fruit fly, jasmine moth (young trees and nurseries), olive psyllid, leopard moth and olive bud mite (young trees). The olive moth, black scale, olive scale and bark beetle are rated **moderate**. Egyptian data on Mediterranean fruit fly damage to olives, on *Euzophera* trunk borers and on olive thrips are thin or missing.
2. **Diseases recorded in Egypt:**
   - **Peacock spot** (Ismailia, Behera).
   - **Olive knot**: first Egyptian record was Fayoum in 2008.
   - **Verticillium wilt**: called "the most serious olive disease in Egypt"; 35 pathogenic isolates from 8 regions fall into 3 compatibility groups.
   - **Root rot and wilt complex** in nurseries and orchards (New Valley): *Fusarium* spp., *Rhizoctonia*, *Macrophomina*.
   - **Root-knot nematodes**: densities on olive are among the highest of any host in NE Egypt.
   - **No Egyptian records were found** for anthracnose (*Colletotrichum*) or Cercospora leaf spot.
3. **Egypt's hot summers work in growers' favour against the fly.** Eggs die at around 35 °C and do not hatch at 37.8 °C, and adult activity stops around 35 °C. In much of Egypt the **summer fly generation collapses**. The damaging period is **autumn (Sept–Nov)**, which is also harvest time. The North Coast and Sinai are cooler, so pressure there is higher; Behera ranks above Fayoum.
4. **An organic toolbox exists for every key pest**, and several tools have Egyptian field evidence:
   - kaolin against the fly: **69–83 % reduction in a field trial at Matrouh**;
   - native *Trichogramma* and pheromone mating disruption against jasmine moth near Cairo (about 90 % male disorientation);
   - mating disruption against leopard moth;
   - predatory mites against eriophyids;
   - parasitoids of black scale (*Metaphycus* up to 40 %);
   - humic and fulvic products and PGPR against root rot in nurseries.
5. **The weak points for organic production** are four:
   - **Verticillium and root rot**: there is no curative product, so the defence is clean planting stock, site history and solarisation.
   - **Leopard moth and bark beetle**: borers are hard to reach.
   - **Copper dependence** for peacock spot and knot, capped at 28 kg Cu/ha over 7 years. Dodine, the main copper substitute, is **not** organic.
   - **Spinosad resistance** has been documented in olive fly in California, so baits must be rotated with kaolin and trapping.

---

### 2. Pest profiles

#### 2.1 Olive fruit fly, *Bactrocera oleae* (ذبابة ثمار الزيتون). Key pest, H
- **Egypt:**
  - Behera is more affected than Fayoum. Yellow sticky traps outcatch McPhail traps.
  - Matrouh: two spring peaks in McPhail traps (March, May), with more females caught.
  - 8 parasitoid species, active July–Nov.
  - Kaolin trial at Matrouh (2013–14): 3–5 % kaolin gave **69–83 % reduction**; 3–4 % was the most economic rate.
- **Biology:**
  - 3–6 generations a year.
  - Fruit becomes susceptible **from pit hardening** (around July).
  - Heat limits the fly: about 50 % egg mortality on a 18–35 °C daily cycle and no hatch on 18–37.8 °C (California). Pupae tolerate up to about 40 °C.
  - Fallen and unharvested fruit carry the population through winter.
- **Damage:**
  - Oil: acidity rises and up to 80 % of oil value can be lost.
  - Table olives: near-zero tolerance, since any sting downgrades the fruit.
- **Monitoring:**
  - McPhail traps with ammonium bait and/or yellow sticky pheromone traps, from June to harvest, read weekly.
  - Sample 100 fruits a week for stings.
- **Action thresholds (calibrate locally, M):**
  - Corfu economic injury level: Sept 4–16 females/McPhail/week (lower in full-crop years); Oct 1–6.
  - California practice: more than 4 flies/trap/week means act; about 10 or more means high pressure.
  - Table olives: act at first stings.
- **Organic control (all EU-permitted unless noted):**
  1. **Sanitation:** collect fallen and leftover fruit, graze sheep after harvest, harvest early and mill within 24 h.
  2. **Kaolin** particle film. Egyptian evidence is the Matrouh trial above. Spray 3–4 % from pit hardening, and repeat after rain or heavy dew.
  3. **Spinosad bait (GF-120)**, spot-sprayed weekly on part of the canopy. In California, infestation was 7 % against 42 % untreated. Rotate it because of resistance.
  4. **Mass trapping** (30–100 % damage reduction, variable) as a supplement. EU rules also allow **deltamethrin or λ-cyhalothrin only inside attract-and-kill traps**.
  5. ***Metarhizium brunneum*** sprayed on soil under the canopy in autumn, against pupating larvae: up to 50 % population reduction in Spain. Experimental; it persists only about 4 months.
  6. **Copper** sprays also reduce fly attack (Sicily, Matrouh). Count them against the copper cap.

#### 2.2 Olive moth, *Prays oleae* (فراشة الزيتون / ثاقبة البراعم). Moderate, H
- **Egypt** (pheromone traps, 3 years):
  - In semi-arid groves there are 3 flights: **Mar–Apr** (flower generation), **May–Jun** (fruit generation) and **Aug–Oct** (leaf generation).
  - In arid groves the first two flights overlap and there is no autumn flight.
  - Populations are lower in off-years.
- **Damage:** the flower generation destroys inflorescences; the fruit generation causes fruit drop in June and September. The leaf generation does little harm.
- **Organic control:**
  - **Btk** (*Bacillus thuringiensis kurstaki*): 86.6 % larval mortality in the lab.
  - Spray Btk just before bloom against the flower generation, and just after fruit set against the fruit generation, timed from trap peaks.
  - Native *Trichogramma*.
  - Avoid broad sprays that kill parasitoids.

#### 2.3 Jasmine moth, *Palpita unionalis* (= *P. vitrealis*) (دودة الياسمين). Severe on young trees, H
- **Egypt:**
  - A primary pest of **nurseries and irrigated young plantings**.
  - Flights in **May–Jun** and **Sep–Nov**.
  - **Mating disruption** near Cairo (2002–04): a 2-component pheromone at 80 g a.i./ha gave about 90 % male disorientation, but some mated females remained, so it works best in isolated, dense blocks.
  - **Native *Trichogramma*:** 4 species occur naturally in Egyptian groves. The best result came from several releases of 9,000 wasps/tree at 2-week intervals. Monthly *T. evanescens* releases followed by neem were also effective.
- **Threshold:** treat nurseries and young plantings when more than 5 % of trees are infested in spring (non-Egyptian guide, M).
- **Organic control:**
  - Btk (80.9 % in the lab).
  - Spinosad (Egyptian field trial; details unconfirmed).
  - Remove water sprouts and suckers.
  - Mating disruption and *Trichogramma* as above.

#### 2.4 Olive psyllid, *Euphyllura straminea* (and *E. olivina*) (بسيلا الزيتون). Severe in Sinai and North Coast, H
- **Egypt:**
  - The species is *E. straminea*. Recorded at El-Arish and Rafah, then Fayoum, then Burg El-Arab (1997).
  - Nymphs present from Nov/Dec to June; **peak in March–April** (national survey: maximum in March).
- **Damage:** waxy secretions on flower clusters during **bloom and fruit set** cause flower and fruit drop. Yield losses of 30–60 % are reported for heavy attack (general database, M).
- **Organic control:**
  - Prune to open the canopy.
  - Before bloom when nymphs are dense: **fatty-acid soap**, **paraffin oil** (pre-bloom only) or **kaolin**. Azadirachtin is permitted.
  - Conserve predators (anthocorids, coccinellids).
- **Gap:** no Egyptian trial of organic products against the psyllid. Confidence for control is M.

#### 2.5 Scale insects (Moderate, H)
- **Black scale, *Saissetia oleae*** (الحشرة القشرية السوداء):
  - Peaks in **October**.
  - *Metaphycus lounsburyi* parasitism reached 34–40 % in October. Five encyrtids plus a pteromalid are recorded in Egypt.
  - Honeydew leads to sooty mould.
  - **Organic control:** canopy opening, moderate irrigation, ant control to protect parasitoids, and **paraffin oil on crawlers in late July or mid-August**.
- **Olive scale, *Parlatoria oleae***:
  - Three peaks a year (Jan, Apr, Aug; Sharkia).
  - Native *Aphytis* species (*A. maculicornis*, *A. diaspidis*) occur from the North Coast to Giza.
  - **Augmentative *Aphytis/Encarsia* releases raised parasitism but did not reduce scale numbers** in Egypt. Rely on conservation, plus paraffin oil where needed.
- **Oleander scale, *Aspidiotus nerii***: no Egyptian data on natural enemies. In Greece: *Aphytis melinus*, *Rhyzobius lophanthae*, *Chilocorus bipustulatus*.

#### 2.6 Leopard moth, *Zeuzera pyrina* (حفار ساق التفاح / حفار الساق). Severe in dense plantings, H
- **Egypt:** serious in high-density olives. Chemical and biological control have historically scored poorly.
- **Organic control with Egyptian evidence:**
  - **Mating disruption** in heavily infested dense plots: fewer trap catches and active galleries, higher yield.
  - **UV-light plus pheromone sticky traps** for mass trapping.
  - **Entomopathogenic nematodes** (Egyptian strains) injected or sprayed into galleries. An EGB20 strain mixed with a half dose of diazinon killed 100 %, but the diazinon is **not organic**. Nematodes alone are permitted.
  - Prune out and burn infested branches, and probe galleries with wire.

#### 2.7 Olive bark beetle, *Phloeotribus scarabaeoides* (خنفساء قلف الزيتون). Moderate, M
- **Egypt:**
  - Fayoum study (2008): chemical trials only (Cidial, Basudin), which are **not organic**.
  - Named in the 2026 North Sinai extension campaign.
- **Biology:** 2–4 generations. Beetles breed in **pruning wood and firewood** and attack weakened trees.
- **Organic control (all cultural):**
  - Remove or chip pruning wood within weeks.
  - Leave "trap logs" of prunings in late winter, then destroy them once colonised.
  - Keep trees vigorous. A 2021 study found no evidence that the beetle spreads Verticillium.

#### 2.8 Olive bud mite and rust mite, *Aceria oleae* and *Tegolophus hassani* (eriophyids). Severe on young trees, H
- **Egypt:**
  - The bud mite is "disastrous on shrub and young olive trees", multiplying 16.7× per 13.5-day generation at 31 °C and 80 % RH.
  - Native predators: *Neoseiulus cydnodactylon* and *Agistemus olivi*. **Releases of *Neoseiulus barkeri*** suppressed both eriophyids on seedlings (2021).
  - *A. olivi* is recorded only from Egypt.
- **Organic control:** sulphur (wettable, avoid heat above 32 °C), predatory-mite releases in nurseries, and no broad-spectrum sprays.

#### 2.9 Other or uncertain pests
- **Mediterranean fruit fly, *Ceratitis capitata*:** widespread in Egypt but **not recorded as an olive pest** in Egyptian reports. Expect it only next to citrus, guava or peach.
- ***Euzophera pinguis*** (bark pyralid): no Egyptian records found. It attacks via wounds and knot galls. *Beauveria* wound dressing worked in Spain. Watch for it.
- **Olive thrips, *Liothrips oleae*:** no Egyptian data found.
- **Root-knot nematodes, *Meloidogyne* spp.:**
  - The highest densities in NE Egypt were on olive, at 800 J2 per 250 g soil.
  - An Egyptian trial tested humic acid and three bioagents against oxamyl; results still to be read.
  - *Dactylaria brochopaga* (a trapping fungus) has been tested in Egypt.
  - Nursery soil solarisation worked in Spain.

---

### 3. Disease profiles

#### 3.1 Peacock spot (olive leaf spot), *Venturia oleaginea* / *Spilocaea oleagina* (عين الطاووس). Moderate, M
- **Egypt:** confirmed in Ismailia and Behera. It reduces leaf pigments and carbohydrates. In trials, sprays started in October and were repeated every 15 days. **No incidence survey by governorate exists.**
- **Epidemiology:** favoured by leaf wetness at mild temperatures. In the Levant, infection rises in **Mar–Apr and Oct–Nov** and is worse on the north side of trees. In Egypt, the **North Coast, Delta and irrigated dense plantings** are most at risk; desert inland sites are low risk.
- **Organic control:**
  - Prune for airflow; avoid overhead irrigation and over-fertilising with nitrogen.
  - **Copper** (hydroxide, oxychloride or Bordeaux) **before autumn rains or after harvest**, plus a spring spray if wet.
  - Stay within **28 kg Cu/ha over 7 years**, which in practice means about 4 kg Cu/ha/yr.
  - Dodine is an effective copper substitute but is **not organic**.
  - Biostimulants and endophytes are promising (2023 review) but have no field-proven organic product yet.

#### 3.2 Olive knot, *Pseudomonas savastanoi* pv. *savastanoi* (السل البكتيري / تدرن الزيتون). Low–moderate, H
- **Egypt:** first record was Fayoum in 2008, on local cultivars. Isolates induced knots on **Picual, Manzanillo and Frantoio** within 20–30 days.
- **Spread:** enters through wounds (pruning, hail, frost, harvest by beating).
- **Organic control:**
  - Prune in dry weather and do the infected trees last.
  - Disinfect tools.
  - Cut out knots.
  - Apply copper after pruning, hail or harvest.
  - Avoid beating the trees at harvest.

#### 3.3 Verticillium wilt, *Verticillium dahliae* (الذبول الفيرتيسيليومي). Severe, no cure, H
- **Egypt:** described as the most serious olive disease in Egypt. The pathogen has been present in Egypt since at least 1986 (EPPO). There is **no incidence survey**.
- **Behaviour:** soil-borne microsclerotia survive for years. Symptoms appear **18–24 months after planting** in infested soil. Disease rises from autumn to spring and stalls in summer.
- **Organic management (all preventive):**
  1. Choose a site with **no history of cotton, solanaceous crops or cucurbits**; test the soil for microsclerotia.
  2. Use **certified pathogen-free nursery plants**.
  3. **Solarise** before planting (EU 2018/848 explicitly lists solarisation).
  4. Use organic amendments and compost (suppressive soils) and avoid excess nitrogen and over-irrigation.
  5. Remove dead trees and their roots and do not chip them in the grove.
  6. Prefer tolerant cultivars. Picual is susceptible in Spain; Egyptian cultivar data is a gap.
- **Detection:** UAV thermal and CWSI imaging catches early infection (Calderón 2013, see dossier 6.8). This is the strongest AgriTech use case in the manual.

#### 3.4 Root rot and wilt complex: *Fusarium oxysporum*, *F. solani*, *Rhizoctonia solani*, *Macrophomina* (أعفان الجذور). Moderate in nurseries and young trees, H
- **Egypt (New Valley):** *F. oxysporum*, *F. solani* and *R. solani* were the most frequent and most aggressive; *Macrophomina* was the least common. All the fungi were pathogenic to transplants.
- **Organic control with Egyptian greenhouse evidence:**
  - **Humic acid, Fulvital, Bio-Health** and other organic compounds gave the highest protection.
  - A **mix of PGPR** (plant-growth-promoting bacteria) gave the best protection in a second study.
  - Add *Trichoderma* (EU-permitted micro-organism; no Egyptian olive trial).
  - Use well-drained, solarised nursery media.

#### 3.5 Diseases not recorded in Egypt (watch list)
- **Anthracnose, *Colletotrichum* spp.:** no Egyptian olive record found. It is a risk in humid coastal zones at harvest.
- **Cercospora leaf spot, *Pseudocercospora cladosporioides*:** no Egyptian record. Its symptoms are confused with peacock spot. Copper controls it.
- ***Xylella fastidiosa*:** a quarantine pest **absent** from Egypt. Imports of fruit-tree seedlings from infected countries were suspended (2017).

#### 3.6 Physiological disorders (often mistaken for disease)
- **Salinity:** leaf-tip and margin burn, defoliation, smaller fruit. Egyptian genotype Giza 48 was the most tolerant and Giza 32 the most sensitive (HRI 2023–24). Picual under 9,000 ppm irrigation was helped by potassium silicate and humic substances (Benha).
- **Boron:** deficiency appears as top-leaf yellowing and fruit drop. Toxicity appears where irrigation water carries more than **1–2 mg/L B** (IOC). Check well water before applying borax.
- **Heat:** above 40 °C during oil accumulation causes early colouring, small fruit and low oil (N. Sinai 2021–23, see dossier 6.3).

---

### 4. Risk ranking for Egyptian organic groves

| Rank | Problem | Main zones | Organic control strength |
|---|---|---|---|
| 1 | Olive fruit fly (autumn) | North Coast, Behera, Sinai, Delta | **Good:** kaolin, bait, traps, sanitation |
| 2 | Verticillium and root rot | Ex-cotton or vegetable land, Delta, new lands with poor nursery stock | **Weak:** prevention only |
| 3 | Jasmine moth (young trees and nurseries) | New plantings everywhere | **Good:** Btk, *Trichogramma*, mating disruption |
| 4 | Olive psyllid | N. Sinai, North Coast, Fayoum | **Medium:** soap, oil and kaolin pre-bloom |
| 5 | Leopard moth | Dense and SHD plantings | **Medium:** mating disruption, nematodes |
| 6 | Peacock spot and knot | Coastal, Delta, dense plantings | **Medium:** copper within the cap, pruning |
| 7 | Scales, mites, bark beetle | Widespread | **Good:** conservation, oil, sulphur, wood hygiene |
| 8 | Nematodes | Sandy nurseries | **Medium:** solarisation, clean stock, bioagents |

---

### 5. Draft organic protection calendar for Egypt (synthesis; verify with ARC before publishing)

Timings combine the Egyptian phenology data above with the ECOLIVE and EU guidance. Shift them about 2 weeks earlier for Upper Egypt and inland desert sites, and later for the North Coast.

| Month | Stage | Action |
|---|---|---|
| Dec–Jan | Dormancy, post-harvest | **Sanitation:** collect fallen fruit, graze sheep. Prune (dry days) and remove or chip the wood. **Copper** after pruning, against knot and peacock spot. Parlatoria peak in Jan: oil only if heavy. Solarise new sites in summer, not now |
| Feb–Mar | Bud burst, inflorescence growth | Psyllid nymphs building: **soap or kaolin** if dense. Hang **Prays pheromone traps**. Fly McPhail traps on the North Coast (spring peak in March). Leaf analysis is not due yet |
| Mar–Apr | Flowering | **Btk just before bloom** if Prays flower-generation catches are high. Psyllid peak: pre-bloom treatment only, **no oil during bloom**. Peacock spot copper if the spring is wet |
| May–Jun | Fruit set | **Btk after fruit set** (Prays fruit generation). Jasmine moth first flight: **mating-disruption dispensers or *Trichogramma*** in young blocks. Install **fly monitoring traps** |
| Jul–Aug | Pit hardening | Fruit becomes fly-susceptible: **kaolin 3–4 %** cover. Black-scale crawlers: **paraffin oil in late July or mid-Aug**. Leaf sampling in July. Heat above 35 °C suppresses the fly, so monitor rather than spray |
| Sep–Nov | Oil accumulation, harvest | **Peak fly risk:** weekly trap reading, **spinosad bait** spot-sprays at threshold, kaolin top-ups, mass traps. Jasmine moth second flight. **Harvest on time:** Manzanillo mid-Oct, Picual and Chemlali early Nov, Koroneiki early to mid-Nov. Mill within 24 h. Black-scale peak in October: conserve *Metaphycus*. Peacock spot copper **before the first rains or right after harvest** |
| Any time | — | Leopard moth: probe galleries, inject nematodes, remove infested limbs. Bark beetle: remove pruning wood. Thermal UAV survey in summer for Verticillium and stress |

---

### 6. Full texts to download (pests and diseases)

| # | P | Topic | Link |
|---|---|---|---|
| PD1 | A | Kaolin and copper against olive fly, Matrouh (Egypt) | https://journals.ekb.eg/article_51095.html |
| PD2 | A | Psyllid *E. straminea* seasonal abundance, Al-Arish | https://ejar.journals.ekb.eg/article_397361.html |
| PD3 | A | Prays and Palpita phenology in Egypt (Hegazi et al. 2011) | https://wiki.pestinfo.org/wiki/Insect_Science_(2011)_18,_565-574 |
| PD4 | A | *Palpita* population trend in Egyptian varieties | https://www.openagrar.de/receive/openagrar_mods_00011604 |
| PD5 | A | *Palpita* mating disruption and Trichogramma near Cairo | https://www.openagrar.de/receive/openagrar_mods_00052716 |
| PD6 | A | Verticillium isolates from olive in Egypt (VCGs) | https://jpp.journals.ekb.eg/article_118786_4114edf64dd2968c60882e4e01eb0005.pdf |
| PD7 | A | Olive knot, first record in Egypt (J. Plant Pathol. 2009) | https://wiki.pestinfo.org/wiki/Journal_of_Plant_Pathology_(2009)_91,_p._235_(Ahmad_et_al.) |
| PD8 | A | Root rot and wilt of olive, New Valley: survey and control | https://ejar.journals.ekb.eg/article_162111_a9a9470ee5b68395753b0cbcb86f3808.pdf |
| PD9 | A | Root rot and wilt control with PGPR / organic compounds | https://ajas.journals.ekb.eg/article_268648.html |
| PD10 | A | Nematodes on olive: humic acid and bioagents vs oxamyl (Egypt 2021) | https://ejp.journals.ekb.eg/article_211750_5f466ca900afcab52467ac44fa7fcdeb.pdf |
| PD11 | B | Nematodes in NE Egypt fruit trees | https://ejaj.journals.ekb.eg/article_267637.html |
| PD12 | A | Eriophyid mites and predators in an Egyptian olive nursery | https://independent.academia.edu/BadawiAwad |
| PD13 | B | Parlatoria augmentative releases, Egypt (Abd-Rabou) | https://riviste.unimi.it/index.php/bzab/article/download/27644/23082/77590 |
| PD14 | B | Aphytis checklist for Egypt | https://ojs.uniba.it/index.php/entomol/article/download/829/661 |
| PD15 | B | Bark beetle chemical trial, Fayoum | https://fjard.journals.ekb.eg/article_197505.html |
| PD16 | B | Peacock spot copper alternatives (dodine), 2024 | https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2024.1369048/pdf |
| PD17 | A | Olive leaf spot review (2023, organic options) | https://www.frontiersin.org/articles/10.3389/fpls.2022.1061136 |
| PD18 | B | Metarhizium soil treatment against olive fly (Frontiers 2018) | https://www.doi.org/10.3389/FPLS.2018.00001 |
| PD19 | B | Heat limits on olive fly (Environ. Entomol. 2009) | https://academic.oup.com/ee/article/38/5/1496/410338 |
| PD20 | B | Olive fly economic injury levels (Corfu) | https://ejournals.epublishing.ekt.gr/index.php/entsoc/article/download/13892/12631 |
| PD21 | B | GF-120 field efficacy and resistance (UC) | https://ccfruitandnuts.ucanr.edu/sites/default/files/2010-08/44747.pdf |
| PD22 | B | Euzophera: Beauveria wound dressing | https://complete.bioone.org/journals/journal-of-economic-entomology/volume-106/issue-4/EC13203/Beauveria-bassiana-Ascomycota--Hypocreales-Wound-Dressing-for-the-Control/10.1603/EC13203.full |
| PD23 | B | Salinity tolerance of Egyptian olive genotypes (HRI) | https://www.plantarchives.org/20-1/3123-3129%20(6280).pdf |
| PD24 | A | FAO paper 115, *Olive pests and their control in the Near East* (1992) | No PDF online. Request from the ARC or Plant Protection Research Institute library |
| PD25 | A | **Egyptian Ministry of Agriculture: APC recommendations for olive (official pesticide and bio-product list)** | Not online. Obtain from the Agricultural Pesticide Committee (لجنة مبيدات الآفات الزراعية) or the governorate agriculture directorate. Needed to confirm which bio-products are **registered in Egypt** |

Previously listed and still relevant: dossier #38–#53 (olive fly spring catches, Behera/Fayoum, kaolin and spinosad, Eco-trap, black-scale parasitoids, leopard moth mating disruption, peacock spot in Egypt).

---

### 7. Remaining gaps
1. Egyptian **cultivar susceptibility** to olive fly, Verticillium and peacock spot (Picual, Koroneiki, Aggezi, Toffahi, Manzanillo).
2. Organic control trials against the **psyllid** and **bark beetle** in Egypt.
3. A national **Verticillium incidence** survey.
4. The **list of bio-pesticides registered in Egypt** (Btk, spinosad, kaolin, Beauveria, Metarhizium, Trichoderma, pheromones). An input that is EU-permitted but not registered in Egypt cannot legally be used.
5. A regional calibration of olive fly action thresholds (flies per trap) for Egypt.


---

# PART 3: Varieties of Egypt and the Middle East

## Organic Olive Manual for Egypt: Olive Varieties of Egypt and the Middle East

**Date:** 2026-10-21. A companion to Part 1 (Sections 2.2, 6.2, 6.3) and Part 2.
**Method:** literature search on Egyptian, Levantine, North African, Israeli and Gulf cultivar studies, the IOC World Olive Catalogue, and the full text of the IOC Egypt policy report (2012) and Nagaty & Awad (2024), both uploaded and read.
**Confidence:** **H** = several consistent sources or full-text read. **M** = one study or a reliable catalogue. **L** = abstract, commercial or extrapolated.

---

### 1. Key findings

1. **Egypt grows two groups of cultivars.**
   - **Local table cultivars:** Aggezi Shami, Toffahi, Aggezi Akse, Hamed. These have low oil (5–9 %), large fruit and are grown mainly in Fayoum, Giza and Siwa.
   - **Imported oil and dual-purpose cultivars:** Picual, Koroneiki, Coratina, Manzanillo, Kalamata, Arbequina. These dominate the new desert lands.
   - The **Siwa oil cultivars** (Maraki, Wateken) and the **ARC breeding lines** are under-used.
2. **ARC has an official variety map and 13 registered selections.** The map (خريطة صنفية) assigns cultivars by region. The selections include lines **48, 66 and 69**, noted for **stable yields in the Egyptian climate**, and **123 and 138**, noted for **high yields in hot areas**. Line 48 also tops a salinity screen as "Giza 48". **The map's content is not published online; it must be obtained from HRI.**
3. **Egyptian desert trials** give these rankings:

   | Trait | Ranking |
   |---|---|
   | Yield | Coratina and Picual lead (Wadi El-Natrun; Cairo–Alex road) |
   | Oil content and early bearing | Koroneiki leads; best yield per tree on sandy soil in one trial |
   | Overall in Minya | Aggezi Shami, Aggezi Akse, Picual |
   | Salinity | Coratina, Koroneiki, Picual, Aggezi Shami most suitable |
   | Weakest | Arbequina had the lowest yield on saline reclaimed soil |

4. **The Middle East offers heat- and drought-adapted germplasm:**
   - **Tunisia:** Chemlali, very drought- and heat-tolerant.
   - **Israel:** Barnea, salt-tolerant (15 t/ha at EC 4.5 dS/m in the Negev).
   - **Levant:** Souri/Soury and Nabali.
   - **Syria:** Sorani, Zaity, Khodeiri, Doebli, together about 90 % of Syrian trees.
   - **Morocco:** Picholine marocaine and its clones Haouzia and Menara.
   - **Common oil-chemistry flag:** several Levantine cultivars (Nabali Baladi, Souri, Khodeiri, Doebli, Sorani) have **Δ-7-stigmastenol at or above the IOC 0.5 % limit**. Egypt's Picual-type oils share the same problem (IOC 2012). Cultivar choice therefore affects whether the oil can be graded extra virgin.
5. **What matters most for organic production:**
   - **Verticillium:** Picual is highly susceptible, Frantoio the most resistant, Koroneiki close to Frantoio, Arbequina intermediate.
   - **Olive fly:** large, round, green, hard fruit is attacked more. Table cultivars are the most exposed; small-fruited oil cultivars are less so.
   - **Chilling:** Arbequina and Koroneiki need little chilling and flower well after warm winters; Picual needs more and is "more vulnerable to climate change".
   - **Pollination:** most cultivars set better with a compatible pollinizer. Manzanillo needs one in warm climates; Kalamata is self-incompatible and incompatible with Picual and Arbequina.

---

### 2. Egyptian local cultivars

| Cultivar (Arabic) | Origin | Use | Key traits | Share of area (2009) | Conf. |
|---|---|---|---|---|---|
| **Aggezi Shami** (عجيزي شامي) | Fayoum | Table (green, stuffed) | Very hardy (sun, drought); fruit large, freestone, firm; **oil 7–9 %**; self-compatible but has pollinizer compatibility problems; medium productivity; **moderately susceptible to fly**. Best yield in a salinity trial; best overall in Minya | **20 %**, the most widespread | H |
| **Aggezi Akse** (عجيزي عقصي) | Fayoum | Table (green) | High rooting and productivity; very heavy fruit. Now widespread | — | M |
| **Toffahi** (تفاحي) | Fayoum, Giza, Beni Suef | Table (green only) | Early bearing and harvest; very high flesh-to-stone ratio; **oil 5–7 %** (20 % DW); **too soft for black pickling**; moderately susceptible to fly | 6 % | H |
| **Hamed / Hamid** (حامض) | Siwa, N. Sinai | Table (green and black) | Very hardy; **drought- and salt-resistant**; high and constant yield; large fruit, bruises easily | 6 % | H |
| **Wateken / Wetteken** (وطيقن) | Siwa | Dual, mainly oil | High oleic, low bitterness; harvest Oct–Dec. In Siwa, yield falls with salinity more than in Hamed | 5 % | M |
| **Maraki** (مراقي) | Siwa | Oil | Very high oleic; **very high crop intensity**; low rooting ability; harvest Nov–Dec. **Highest oil content among Egyptian genotypes** (Cairo Univ. thesis). Tipped by the IOC as "Egypt's future main oil cultivar" | 2 % | M |
| **Siwi / Sewia** (سيوي) | Siwa | Dual | Heaviest fruit and stone among the genotypes tested; lower oil than Maraki | — | L |
| **ARC selections** 48, 66, 69, 123, 138 and others (13 registered) | HRI breeding since 1994 (crosses of local × Koroneiki, Chemlali, Kalamata, Coratina, Leccino) | Oil, table and dual | 48, 66, 69: stable yields. 123, 138: high yield in hot areas. 48 ("Giza 48") the most salt-tolerant and Giza 32 the most sensitive in a 2023–24 screen. Oils graded extra virgin at El-Khatatba | — | L–M |

Farmers know Aggezi, Toffahi and Manzanillo well but **often do not know Picual, Koroneiki or Maraki** (field survey). The manual should fill this gap.

---

### 3. Imported cultivars widely grown in Egypt

| Cultivar | Use | Egyptian evidence | Verticillium | Chilling | Other | Conf. |
|---|---|---|---|---|---|---|
| **Picual** (بيكوال) | Oil, dual | Highest yield and oil % at Wadi El-Natrun; good in Minya and Nubaria. Harvest about 2 Nov in N. Sinai; free acidity rises fast after that. Oil content 40 % DW (Samra 2009) | **Highly susceptible** (killed in 2 years in infested Spanish soil) | **Higher** | Tolerates salinity and wet soil; widespread in Saudi Al-Jouf, Tabuk and Hail too | H |
| **Koroneiki** (كرونايكي) | Oil | Highest oil (≈50 % DW), 44 kg/tree on reclaimed land; best on sandy soil; best yield and oil under super-high density in Ismailia. Poor in Minya. Harvest 2–16 Nov. **Heat-tolerant** in N. Sinai (lowest moisture loss). Lowest alternate bearing (Iran). Small fruit, 1–1.7 g | **Fairly resistant** (close to Frantoio) | **Low** | Most salt- and drought-tolerant in one pot study. Self-compatibility reports conflict | H |
| **Coratina** (كوراتينا) | Oil | Highest yield on the Cairo–Alex road; among the most suitable under salinity; high oil %. Recommended oil cultivar by ARC | No Egyptian data (moderate in Italy) | Medium | High-phenol, bitter oil | M |
| **Manzanillo** (منزانيللو) | Table, dual | Matures 15–30 days earlier than other cultivars; harvest about 19 Oct (earlier in hot years). Highest peroxide value and lowest phenols of the 4 tested. Most salt-sensitive of 3 cultivars in a Negev trial | No data in these sources | Low–medium | **Needs a pollinizer in warm climates** (Sevillano good; Mission incompatible). Large fruit attracts fly | H |
| **Kalamata** (كالاماتا) | Table (black) | Grown in N. Sinai and S. Sinai; best productivity on Picholine rootstock | — | — | **Strongly self-incompatible.** Compatible with Barnea; incompatible with Picual and Arbequina | M |
| **Arbequina** (أربيكوينا) | Oil (SHD hedgerow) | **Lowest yield** per tree on saline reclaimed soil; late harvest (213–217 days after bloom) | Intermediate | **Low** | Small fruit; suits super-high-density planting | M |
| **Chemlali** (شملالي) | Oil | Highest oil in N. Sinai (up to 49 % DW); heat-tolerant; harvest about 2 Nov | — | Low (Tunisian model) | Very small fruit; high phenols | H |
| **Frantoio** | Oil | Little Egyptian data | **Most resistant** reference cultivar | — | Candidate for Verticillium-infested sites | M |

---

### 4. Middle East and North Africa cultivars (candidate germplasm)

| Country | Cultivars | Traits relevant to Egypt | Conf. |
|---|---|---|---|
| **Tunisia** | **Chemlali** (central and south), **Chetoui** (north), Oueslati, Zalmati | Chemlali is more drought-tolerant than Chetoui (thicker palisade, more stomata, better antioxidant protection); "very drought resistant, salt tolerant". Chetoui's photosynthesis drops sharply after 30 days without water | H |
| **Israel** | **Barnea**, **Souri**, Picual, Manzanillo | **Barnea:** salt-tolerant (more fine roots at 7.5 dS/m); best balance at **4.2 dS/m**; 15 t/ha, 18 % oil at EC 4.5 (Halutza). Souri: 10 t/ha, 17 % oil; Verticillium incidence doubled under saline irrigation. Picual: 10 t/ha, 12 % oil | H |
| **Lebanon / Palestine / Jordan** | **Souri/Soury**, **Nabali Baladi**, Nabali Mohassan, Rasi'i, Baladi | Soury: dual-purpose, oil 28–35 % FW, harvest mid-Sept to late Oct; Δ-7-stigmastenol sometimes above 0.5 %. Nabali Baladi: oleic about 60 % or more, but high Δ-7-stigmastenol. Nabali Mohassan: lower oleic. Drought ratings vary by source | M |
| **Syria** | **Zaity**, **Sorani**, **Khodeiri**, **Doebli**, Kaissy, Karamani | These 5 make up about 90 % of Syrian trees. Oleic about 70 %. Zaity, Sorani and Doebli have high oil. **Δ-7-stigmastenol above 0.5 % in Khodeiri and Doebli** and near it in Sorani. Karamani has low oleic | M |
| **Morocco** | **Picholine marocaine** (90 % of trees), clones **Haouzia** and **Menara** | Picholine marocaine is well adapted but alternate-bearing and **highly susceptible to peacock spot**; Haouzia and Menara are medium. Dual-purpose | M |
| **Saudi Arabia** | Picual, Manzanillo, Barnea, Kaissy, Arbequina, Koroneiki and about 30 more at the Al-Jouf research unit | Desert, frost-prone north. Picual tolerates salinity and frost but is Verticillium-susceptible. Performance papers exist for 8 cultivars (2024) | L |
| **Turkey** | Gemlik, Ayvalık, Memecik | Memecik: the most phenols and heavy fruit. Gemlik: high oil and constant yield. Ayvalık: weak graft union on Gemlik rootstock. No desert-condition data | L |

**Import caution:** *Xylella fastidiosa* is absent from Egypt, and Egypt suspended seedling imports from infected countries (2017). Any foreign material must come as **certified, Xylella-tested stock** through the Plant Quarantine Administration. In practice, use cultivars already in Egyptian nurseries or the ARC gene bank.

---

### 5. Choosing cultivars for an organic grove: a decision guide (synthesis; check against the ARC variety map)

#### 5.1 Organic selection criteria (in order)
1. **Soil-borne disease risk.** On land with cotton, solanaceous or vegetable history, or poor nursery records, **avoid Picual** and prefer Koroneiki, Frantoio or Coratina. Solarise and test the soil.
2. **Water salinity.**
   - Above **4 dS/m:** Koroneiki, Coratina, Picual, Aggezi Shami, Hamed, Barnea-type cultivars, ARC line 48.
   - Avoid Manzanillo and Arbequina.
3. **Winter chill.** Warm winters (Upper Egypt, inland desert, the south of the new lands) favour low-chill cultivars (Koroneiki, Arbequina, Chemlali, Manzanillo). Picual is riskier.
4. **Olive fly exposure.** Table olives (large green fruit) need the full fly programme. Small-fruited oil cultivars (Koroneiki, Chemlali, Arbequina) are less attractive and are **easier to keep organic**.
5. **Heat during oil accumulation.** Koroneiki and Chemlali held oil and quality best under 40 °C or hotter heat waves (N. Sinai). Manzanillo and Picual lost more.
6. **Pollination.** Plant at least 2 cultivars with **overlapping bloom**, about 10 % pollinizer trees. Never plant Kalamata without Barnea or another compatible pollinizer.
7. **Market.** Organic EVOO for export suits Koroneiki, Coratina, Picual or Chemlali, picked early for phenols. Watch **Δ-7-stigmastenol** in Picual and Levantine cultivars. Organic natural-style table olives suit Aggezi Shami and Kalamata; Toffahi is green only.

#### 5.2 Proposed zone recommendations (provisional, pending the HRI map)
| Zone | Conditions | Oil | Table / dual | Notes |
|---|---|---|---|---|
| North Coast and Matrouh (rainfed or supplementary) | Mild winters, 100–150 mm rain, strong NW winds, high fly and peacock-spot pressure | Koroneiki, Coratina, Chemlali | Aggezi Shami, Hamed | Fly and leaf spot are the main organic challenges; windbreaks |
| North Sinai (Arish) | Sandy loam, saline wells (EC up to about 6.6), heat waves | Koroneiki, Chemlali, Picual (harvest 2 Nov) | Manzanillo (harvest 19 Oct), Kalamata + pollinizer | Psyllid hotspot; heat-tolerant oil cultivars preferred |
| West Delta new lands (Nubaria, Wadi El-Natrun, Sadat, Cairo–Alex road) | Sandy, drip, groundwater | Picual, Coratina, Koroneiki (SHD) | Manzanillo, Aggezi | Highest yields in trials; Verticillium screening on ex-vegetable land |
| Ismailia, Sharkia, East Delta | Sandy to loamy, near export ports | Koroneiki (SHD), Coratina | Aggezi Shami, Picual | Strong organic-export cluster |
| Fayoum, Beni Suef, Giza | Old lands, origin of local cultivars, olive knot recorded | Picual, Koroneiki | **Aggezi Shami, Aggezi Akse, Toffahi** | Fayoum is Egypt's organic hub (about half of organic farms) |
| Minya and Middle Egypt | Hotter, warmer winters | Picual; ARC heat lines 123 and 138 | **Aggezi Shami, Aggezi Akse** | Koroneiki grew poorly in one Minya trial |
| Siwa and the oases | Saline water, waterlogging | **Maraki, Wateken** | **Hamed, Siwi** | Drainage first; local cultivars are best adapted |
| Upper Egypt, East Owainat, Toshka | Very hot, low chill | Koroneiki, Chemlali, ARC 123 and 138 | Manzanillo | Chilling is the main risk; trial before scaling |

---

### 6. Gaps
1. **The HRI variety map** and the descriptions of the **13 registered ARC selections** (yield, oil, chilling, salinity, disease).
2. Egyptian **chilling-hour data** by cultivar.
3. Egyptian **cultivar susceptibility** to fly, Verticillium and peacock spot (Aggezi, Toffahi, Koroneiki, Coratina).
4. **Oil chemistry** (Δ-7-stigmastenol, linolenic acid) by cultivar and region in Egypt, which decides EVOO compliance.
5. Pollinizer compatibility tested under Egyptian conditions.

### 7. Files to download

| # | P | Document | Link |
|---|---|---|---|
| V1 | A | IOC World Olive Catalogue: Egypt (Aggezi Shami and others) | https://worldolivecatalogue.internationaloliveoil.org/en/variety/egypt/aggezi-shami |
| V2 | A | Samra et al. 2009, Toffahi, Koroneiki, Picual on reclaimed land | https://journals.ekb.eg/article_118657.html |
| V3 | A | Cultivars under saline stress in reclaimed soils (Assiut 2022) | https://ajas.journals.ekb.eg/article_263933.html |
| V4 | A | HRI breeding: evaluation of hybrids | https://jpp.journals.ekb.eg/article_118795.html |
| V5 | A | HRI breeding: agronomic and qualitative evaluation of selections | https://journals.ekb.eg/article_109799.html |
| V6 | A | HRI accessions from the improvement programme | https://journals.ekb.eg/article_109795.html |
| V7 | A | Local oil clones vs world cultivars (Ain Shams; Maraki, Sewia) | https://research.asu.edu.eg/bitstream/12345678/25416/1/V2485.pdf |
| V8 | B | Egyptian cultivars: molecular ID and leaf oil (Maraki, Aggezi, Toffahi) | https://journals.ekb.eg/article_151618.html |
| V9 | B | Four cultivars in sandy soil, yield and quality | https://journals.ekb.eg/article_15329.html |
| V10 | B | Optimum harvest date, 5 cultivars, Cairo–Alex road | https://journals.ekb.eg/article_1333.html |
| V11 | B | Cultivars at Wadi El-Natrun | https://journals.ekb.eg/article_45383.html |
| V12 | A | Cross-pollination in Egyptian cultivars | https://ejarc.journals.ekb.eg/article_212880_96bb88389baa859f29b9223fd532240e.pdf |
| V13 | B | Salinity tolerance of Egyptian genotypes (Giza 48 / Giza 32) | https://www.plantarchives.org/20-1/3123-3129%20(6280).pdf |
| V14 | B | Verticillium resistance of cultivars (Frantoio, Picual, Arbequina, Koroneiki) | https://helvia.uco.es/handle/10396/12064 |
| V15 | B | Barnea under saline irrigation, Negev | https://cris.bgu.ac.il/en/publications/optimization-of-saline-water-level-for-sustainable-barnea-olive-a-2/ |
| V16 | B | Halutza commercial cultivars with saline water (ISHS 791_40) | https://www.ishs.org/ishs-article/791_40 |
| V17 | B | Syrian cultivars: oil quality (CIHEAM) | https://ressources.ciheam.org/ressources/om/pdf/a73/00800340.pdf |
| V18 | B | Palestinian cultivars: morphology and oil (Jordan J. Agric. Sci.) | https://archives.ju.edu.jo/index.php/jjas/article/download/6064/3652/14433 |
| V19 | B | Chemlali vs Chetoui drought anatomy | https://www.ps.ueb.cas.cz/pdfs/phs/2009/03/04.pdf |
| V20 | B | Chilling: Arbequina and Koroneiki low vs Picual | https://www.ojs.uel.br/revistas/uel/index.php/semagrarias/article/view/52010 |
| V21 | B | Kalamata pollen compatibility | https://sjar.revistas.csic.es/index.php/sjar/article/view/2223 |
| V22 | B | Fly susceptibility vs fruit traits (Sicily) | https://iris.unipa.it/retrieve/e3ad8915-fa37-da0e-e053-3705fe0a2b96/07_Rizzo%26CalecaIOBC07.pdf |
| V23 | B | Al-Jouf (Saudi) 8 cultivars | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11199486/ |
| V24 | A | **HRI variety map and the 13 registered selections**: not online | Request from HRI Olive Research Dept. (قسم بحوث الزيتون، معهد بحوث البساتين) |


---

# PART 4: Orchard establishment, planting systems and propagation

## Organic Olive Manual for Egypt: Establishing New Olive Orchards (Planting Systems, Propagation and Methods)

**Date:** 2026-10-21. A companion to Parts 1–3.
**Method:** literature search (Egyptian, Mediterranean and US sources). Organic rules were checked against the full text of EU Reg. 2018/848 and 2021/1165 (uploaded and read).
**Confidence:** **H** = several sources, or the regulation itself. **M** = one study or extension guide. **L** = general practice not yet backed by an Egyptian source. Mark L items for ARC confirmation.

> **Unit:** 1 feddan = 4,200 m² = 0.42 ha. Trees per feddan = 4,200 ÷ (row spacing × tree spacing).

---

### 1. Key findings
1. **Organic rules start at planting.**
   - Use **organic planting material**; non-organic nursery trees need a **prior written authorisation** from the control body (Reg. 2018/848, Annex II I-1.8.1 and 1.8.5.2).
   - The **3-year conversion clock** starts only when the farm is **notified to a control body**, so register before or at planting. The trees then reach their first organic harvest at about year 3–4, which is roughly when they start bearing anyway.
   - Synthetic **hydrogels** (polyacrylamide) are **not** in the EU organic fertiliser and soil-conditioner list. Leonardite humic acid is permitted with conditions.
2. **Planting system decides the organic strategy.**
   - **Traditional:** 70–100 trees/ha rainfed (about 30–40 per feddan).
   - **Intensive:** 200–400 trees/ha; Egyptian irrigated groves are 333–400/ha, about 140–170 per feddan.
   - **High-density:** 400–700/ha.
   - **Super-high-density (SHD) hedgerow:** above 1,500/ha, about 700 per feddan at 4 × 1.5 m.
   - Organic guidance (ECOLIVE) suggests **about 300 trees/ha as a common maximum for organic** because of shading, disease and input pressure. Egyptian research nevertheless found **SHD Koroneiki gave the highest yields** (7.3–8.9 t fruit/feddan and 1.1–1.4 t oil/feddan, Ismailia).
   - **Recommendation:** use **intensive (6 × 4 to 7 × 5 m)** as the default organic system. Reserve SHD for experienced, well-capitalised growers with Koroneiki or Arbequina, a strong canopy-disease programme and access to mechanical harvesting.
3. **Propagation in Egypt is mostly by rooted semi-hardwood cuttings under mist.**
   - IBA dips at **4,000–6,000 ppm**.
   - **June** is the best collection month in several Egyptian trials (North Sinai, Cairo).
   - Rooting varies strongly by cultivar.
   - Grafting is used for hard-to-root cultivars, for rootstock benefits (Kalamata on Picholine gave the best productivity) and for **top-working** old groves to a new cultivar (best success **Aug–Oct**).
   - Micropropagation is at research stage in Egypt (Picual, Sourani, Dolce).
4. **Clean planting stock is the single most important organic decision.** Infected nursery plants are "the vehicle" of Verticillium worldwide. Use stock produced under the **EPPO PM 4/17 certification scheme**: nuclear stock tested free of *V. dahliae*, *Xylella* and the main viruses. Egypt bans seedling imports from *Xylella*-infected countries.
5. **Rootstocks:** resistant rootstocks such as Frantoio **delay but do not prevent** Verticillium in Picual; after 4 years the Picual combinations were still heavily colonised. Egyptian HRI is testing **salt-tolerant Coratina and Frantoio genotypes as rootstocks**. This is not yet a commercial recommendation.
6. **On desert land, establishment rests on three things:**
   - **water quality** (EC, SAR, boron) and drip in place **before** planting;
   - **windbreaks** (casuarina is the traditional Egyptian shelterbelt tree; aim for a semi-permeable belt);
   - **organic matter in the root zone**, from compost and pomace compost.
7. **Cover crops and intercrops build organic soil fertility** (required for perennials by 2018/848 I-1.9.2(b)). Faba bean raised soil organic matter in Tunisia. Olive with chickpea or lentil raised soil organic matter without cutting olive yield in Morocco. Self-reseeding legumes need no reseeding. Under drip on sand, cover crops compete for water, so irrigate them separately or grow them only in winter.

---

### 2. Planting systems

| System | Spacing (m) | Trees/ha | Trees/feddan | Bearing | Harvest | Fit for organic in Egypt | Conf. |
|---|---|---|---|---|---|---|---|
| Traditional rainfed (North Coast) | 10 × 10 to 12 × 12 | 70–100 | 30–40 | Late (6–8 yr) | Hand, beating | Good (low disease pressure) but low yield; mainly Matrouh | H |
| Traditional irrigated | 7 × 7 | 204 | 86 | 4–5 yr | Hand or shakers | Good | H |
| **Intensive** (recommended default) | 6 × 6 / 6 × 5 / 6 × 4 / 7 × 5 | 277–416 | 117–175 | 3–4 yr | Hand, rakes, trunk shakers | **Very good**: airflow, room for cover crops, vase training | H |
| High-density | 5 × 3 to 6 × 3 | 555–667 | 233–280 | 2–3 yr | Canopy shakers | Moderate: more disease and pruning | M |
| Super-high-density hedgerow | **4 × 1.5** (3.5–4 × 1.35–1.5) | 1,650–2,000 | about 700–830 | Year 2–3 | Over-row straddle harvester | **Difficult**: dense canopy, peacock spot and scale pressure, heavy compost need, only low-vigour cultivars (Arbequina, Arbosana, Koroneiki, Sikitita, Oliana, Lecciana), trellis and wires, high capital | H |

**Notes**
- **Row orientation:** run rows **north–south** for even light. On the North Coast, put rows **across the prevailing NW wind** or protect them with windbreaks (L).
- **Within-row spacing:** use wider spacing for vigorous cultivars (Picual, Coratina, Aggezi) and closer spacing for Koroneiki and Arbequina (M).
- **Pollinizers:** add 8–10 % pollinizer trees with overlapping bloom. Kalamata always needs a compatible pollinizer such as Barnea (see Part 3).

---

### 3. Propagation methods

| Method | How | Egyptian evidence | Use | Conf. |
|---|---|---|---|---|
| **Semi-hardwood leafy cuttings under mist** (main method) | 12–15 cm cuttings with 2–4 leaf pairs; basal dip in IBA; bottom heat; intermittent mist or fog; perlite/peat; 60–90 days to root; harden off; pot up | IBA **4,000–6,000 ppm**; **June** collection best (Cairo, N. Sinai). Manzanillo and Picual: IBA 6,000 ppm for 5 s was best. Strong cultivar differences (e.g. Cheperssino high, Itrana low). HRI breeding lines rooted at IBA 5,000 ppm. Beni Suef: best survival after transplanting for cuttings planted in Aug and Nov | Own-rooted plants for all easy-rooting cultivars (Koroneiki, Arbequina, Picual, Manzanillo) | H |
| **Grafting onto seedling or clonal rootstocks** | Seedlings from olive seed (often wild or Chemlali-type), then whip, cleft, bark or chip grafting | Kalamata on **Picholine** rootstock was the most productive (Cairo–Alex road) | Hard-to-root cultivars (Kalamata, some table types); rootstock benefits | M |
| **Top-working (re-grafting adult trees)** | Cut back scaffolds; bark or cleft graft 2–4 scions per limb; never top-work a whole large tree in one year | Iran: best in **mid to late October**. Pakistan: 100 % success **Aug to mid-Sept** (bark graft and T-bud). Egypt: no data (IOC 2012 lists grafting as policy to switch non-adapted cultivars) | Converting Toffahi or Aggezi blocks to oil cultivars; fixing pollination | M |
| **Micropropagation** | Axillary bud culture; ex-vitro rooting | Cairo Univ. and NRC research on Picual, Sourani, Dolce. Not commercial in Egypt | Future clean-stock source; costly | M |
| **Suckers and ovuli** (traditional) | Basal suckers or knobs dug from old trees | Traditional in Siwa and Fayoum | **Avoid** in organic: risk of carrying Verticillium, nematodes and knot | L |

**Organic nursery rules** (2018/848, I-1.8):
- For **organic plant reproductive material**, mother plants must be organic for at least one generation (perennials: two growing seasons).
- **Media:** peat is allowed only in horticulture; compost and coir are fine.
- **Rooting hormone:** IBA is a synthetic growth regulator and is **not** in the EU organic plant-protection or fertiliser lists. Organic nurseries use willow-bark extract (*Salix* cortex is an EU basic substance) and aloe or other natural rooting aids, or they buy conventional stock under derogation. **Confirm with the certifier.** This is a real constraint, and buying conventional stock under derogation is the usual Egyptian practice (M).

---

### 4. Nursery stock quality checklist (for the manual)

| Criterion | Standard |
|---|---|
| Health certification | Produced under the **EPPO PM 4/17** scheme or equivalent national certification: free of *V. dahliae*, *Xylella fastidiosa*, ArMV, CLRV, SLRSV. Phytosanitary certificate from the Plant Quarantine Administration |
| Trueness to type | Cultivar label and nursery register; DNA (SSR) check for large orders |
| Age and size | About 12–18 months, **60–100 cm**, single straight stem with no forks below 50–60 cm |
| Roots | Well developed, **not circling or kinked**; container about 2–3 L; no root rot (*Fusarium*, *Rhizoctonia*) |
| Pests | Free of root-knot nematodes (ask for a lab test of nursery soil), eriophyid mites, scale and jasmine-moth larvae |
| Organic status | Organic stock, or a written **derogation** from the control body **before** purchase; keep invoices |

Sources: EPPO PM 4/17; IOC germplasm-network and certification harmonisation; Egyptian nursery surveys of root rot and nematodes (see Part 2).

---

### 5. Site preparation (desert and new lands)

| Step | Practice | Conf. |
|---|---|---|
| 1. Soil survey | Open profiles to **≥1 m**. Favourable: depth >0.8 m, pH 6–8 (tolerates up to 8.5), good drainage, no hardpan; check CaCO₃ and active lime (Fe chlorosis risk) | H (ECOLIVE) |
| 2. Water analysis | EC, SAR, Cl, Na, **boron** (olive tolerates about 1–2 mg/L B). Aim for root-zone ECe <4–6 dS/m. Plan a leaching fraction | H |
| 3. Site history | Avoid fields with cotton, solanaceous or cucurbit history (Verticillium); test for microsclerotia and nematodes | H |
| 4. Deep ripping | Rip about 1 m deep along the planting rows, without inverting the layers | H (ECOLIVE) |
| 5. Solarisation (if risky) | Moist soil under clear plastic for 6–8 weeks in **June–August**. Explicitly listed in EU organic rules (I-1.10.1) | H |
| 6. Windbreaks | Casuarina (or native species) on the windward side, **1–2 years before planting**, aiming for a semi-permeable belt. A wind speed below about 3 m/s stops sand movement (citrus on sand study) | M |
| 7. Irrigation | Drip laterals and emitters installed and tested **before** planting. Young trees: 2 emitters per tree, adding more as the canopy grows (see Part 1, 2.5) | M |
| 8. Organic matter | Compost or pomace compost along the rows. Manure must not be of factory-farming origin; livestock manure is capped at 170 kg N/ha/yr | H (regulation) |
| 9. Mineral correction | Only from the EU Annex II list: rock phosphate, natural potassium sulphate, gypsum on sodic soils, elemental sulphur on high-pH soils | H |

---

### 6. Planting operation

| Item | Recommendation | Conf. |
|---|---|---|
| **Timing (Egypt)** | **Late winter to spring (Feb–April)**, after the cold and before the heat, is the main window. A secondary window is **autumn (Oct–Nov)**. Avoid **May–Sept**: transplant shock and sand heat. Spring is preferred on the North Coast and in Sinai; autumn in Upper Egypt | L: general guidance and the Beni Suef cutting data. **Confirm with ARC** |
| Pit size | **About 60 × 60 × 60 cm** on ripped sand; **up to 1 × 1 × 1 m** on unripped or compacted soil or for large trees | M |
| Pit fill | Original soil mixed with **well-made compost** (rate per the ARC bulletin; gap). Keep raw manure off the roots | L |
| Planting depth | Same depth as in the nursery pot, with the root collar at soil level. Never bury the graft union | H |
| Irrigation at planting | Water the pots the day before. Irrigate immediately after planting, then keep the root ball moist with frequent short drip cycles in the first 2–3 months | M |
| Stake and protection | Bamboo or metal stake on the windward side, soft ties. **Trunk guards** against rabbits and sun scald. SHD needs a trellis with 2–3 wires | M |
| Mulch | Organic mulch (pruning chips, straw) around the tree to cut evaporation and weeds; keep it away from the trunk | M |
| Records (organic) | Planting date, nursery invoice and certificate, derogation, map of cultivars and pollinizers. Required under 2018/848 I-1.12 | H |

---

### 7. Care of young trees (years 0–4)

| Topic | Practice | Conf. |
|---|---|---|
| **Training (intensive)** | **Vase (goblet)**: head the stem at **60–70 cm** (80–100 cm if mechanical shakers will be used); keep **3–4 (up to 5) scaffolds** at staggered heights about 45° apart. Minimal pruning in years 1–2; remove suckers and competing low shoots. Light cuts in **Feb–April** | H |
| **Training (SHD)** | **Single central leader** on the stake and wire, about 2–2.5 m with a flexible top. Shorten laterals towards the top. No heading | H |
| Irrigation | Frequent, small applications; increase emitters and volume with canopy size. Use Kc × canopy-cover methods (Part 1, 2.5) | M |
| Nutrition | Compost bands each autumn or winter; liquid organic fertilisers through drip (allowed products only). Leaf analysis from year 3 | M |
| Pests to watch | **Jasmine moth** (Btk or Trichogramma; act above 5 % infested shoots), **olive bud mite** (sulphur, predatory mites), psyllid on early flowers, leopard moth in dense blocks (see Part 2) | H |
| Weeds | Mow or hand-weed within rows, mulch, sheep grazing in older blocks. **No herbicides** in organic | H |
| Cover crops | Winter legumes such as faba bean, vetch or berseem, or chickpea and lentil as intercrops, in the inter-row. Mow or incorporate before the summer water peak. Under drip on sand, give them separate irrigation or sow only in winter | M |
| First crop | Remove flowers or fruit in year 2 on weak trees, to build the frame | L |

---

### 8. Economics (indicative)

| Item | Value | Source |
|---|---|---|
| Conventional traditional orchard, North Sinai (2018) | Costs about **11,500 LE/feddan**, revenue about **38,500 LE/feddan** | SINJAS (economic study) |
| SHD Koroneiki, Ismailia (research station) | **7.27–8.93 t fruit/feddan, 1.14–1.42 t oil/feddan** | HRJ 2024 |
| Organic yield gap (2009) | Organic table olives yielded 7.3 t/ha against 10.2 t/ha conventional; price premium only about 10 % | IOC 2012 (Part 1, 6.2) |
| SHD establishment cost | **No Egyptian budget found.** UC sample-cost studies (Arbequina trellis) can be rebuilt with Egyptian prices | UC ANR |

---

### 9. Gaps
1. ARC/HRI **planting calendar** and **pit and compost rates** for Egyptian desert soils.
2. An Egyptian **SHD establishment budget** (trees, trellis, drip, labour, break-even year).
3. Availability of **certified (EPPO-type) olive nurseries in Egypt**, and whether any **organic olive nursery** exists.
4. Natural rooting aids acceptable to certifiers, with rooting results for Egyptian cultivars.
5. Egyptian data on salt- or Verticillium-tolerant **rootstocks** (HRI 2022–23 trial results).
6. Data on the survival of young trees under different windbreak or shade-net designs in Egyptian deserts.

### 10. Files to download

| # | P | Document | Link |
|---|---|---|---|
| E1 | A | Intensive vs SHD (Coratina, Koroneiki, Maraki), Ismailia | https://hrj.journals.ekb.eg/article_389568_982f1291333d59ef2aeca6a8ba9f954d.pdf |
| E2 | A | Planting-system comparison: design, costs, oil (ISHS) | https://ishs.org/ishs-article/1057_27/ |
| E3 | B | Density effects on yield and quality, Sicily (Horticulturae 2022) | https://iris.unipa.it/retrieve/929db56a-e632-49d3-b84b-f6f8186e31e1/horticulturae-08-00817-v2.pdf |
| E4 | A | Rooting cuttings of Egyptian breeding genotypes (HRJ 2024) | https://hrj.journals.ekb.eg/article_394477_6ca1f05e3ac01edf89910a54432ac5b4.pdf |
| E5 | A | Rooting of 5 introduced cultivars, mist/VPD (Egypt) | https://ejarc.journals.ekb.eg/article_215387_a74195409d8a9e319107c494c0e2a8f5.pdf |
| E6 | B | Cuttings: Khoderi, Maraki, Manzanillo, Moluki (Benha thesis abstract) | https://www.bu.edu.eg/portal/uploads/discussed_thesis/finalabsrtract/11704814.pdf |
| E7 | B | Cutting survival by planting month, Beni Suef | https://asejaiqjsae.journals.ekb.eg/article_2324_31ab96a13aaf86ba329846a212335f63.pdf?lang=ar |
| E8 | A | Rootstocks against Verticillium (Frontiers 2022) | https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2022.1032489/pdf |
| E9 | A | Salt-tolerant genotypes as rootstocks (HRI Egypt) | https://hrj.journals.ekb.eg/article_452475_c1e33abb0d88bf4241de6860974fcc7b.pdf |
| E10 | A | **EPPO PM 4/17**: certification scheme for olive | https://gd.eppo.int (search "PM 4/17 olive") |
| E11 | B | Hydrogel and K-humate on olive, Matrouh | https://ejdr.journals.ekb.eg/article_5849_83bc574b4ea3f778f35e0c6c8f39dd65.pdf |
| E12 | B | Organic vs mineral fertiliser on sandy soil, South Sinai | https://ejss.journals.ekb.eg/article_194.html |
| E13 | B | Intercropping in Moroccan olive agroforestry | https://www.vegetosindia.org/article/the-effect-of-intercropping-crop-type-on-soil-fertility-olive-trees-productivity-and-quality-in-moroccan-agroforestry-systems |
| E14 | B | Tunisian olive groves with legume and cereal covers | https://www1.montpellier.inra.fr/wp-inra/biodiversify/tunisia-olive-groves-with-cover-crops-and-grazing |
| E15 | B | Self-reseeding legumes in olive groves (IPB) | https://bibliotecadigital.ipb.pt/bitstreams/701aa7ef-f922-42c6-9bfb-4afe9ac4a895/download |
| E16 | B | Economics of olive, North Sinai | https://sinjas.journals.ekb.eg/article_210151_cf87f820483c8efc2e3db7dc6cf059e1.pdf |
| E17 | B | UC sample costs: SHD olive for oil | https://ucanr.edu/media/304274 |
| E18 | B | Micropropagation review (2025) | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12038445/ |
| E19 | B | Top-working timing for olive (Iran) | https://spj.areeo.ac.ir/article_129289.html |
| E20 | A | **ARC olive bulletin** (planting dates, pit and compost rates): not online | Request from HRI or the Central Administration for Agricultural Extension |


---

---

# PART 5: Third upload batch (reviewed 2026-11-02)

| File | Content | Effect on the manual (Edition 1.1) |
|---|---|---|
| Ebiad & Abu-Qaoud (2014), Jordan J. Agric. Sci. 10(1) | Nabali Baladi, Nabali Mohassan and Souri in Palestine (full text) | Variety row expanded:<br>• oil (dry weight) 55.6 / 46.8 / 40.3 %<br>• oleic 66.2 / 56.4 / 70.1 %<br>• polyphenols 380 / 128 / 217 mg/kg<br>• all three alternate-bearing and dual-purpose<br>• Souri originated in Sour (Lebanon)<br>• Δ-7-stigmastenol excessive only in Nabali Baladi<br>Palestinian phenology added to section 6.1: growth from early Feb, full bloom late Apr–early May, pit hardening mid-Jun–early Jul, colour change mid-Oct–early Nov |
| Abdullah & Khaleel (2023), Dirasat Hum. Soc. Sci. 50(6) | Climate suitability for olive in Iraq (full text) | Iraq row now cites the correct paper title:<br>• local varieties Khastawi, Ashrasi, Dahkan<br>• Mosul, Erbil, Sulaymaniyah and Kirkuk highly suitable; Al-Rutba moderate; the south unsuitable<br>Added to section 6.1: olive needs a frost-free period of at least 150 days |
| UC Cooperative Extension (2024), *Irrigation and Nutrient Management of Young Orchards*, Ch. 6 (young olive) | Full text | **Correction:** "N can be reduced or omitted in the first two seasons on fertile soils" is from the **walnut** chapter, so it was removed from the seedling plan.<br>Added from the olive chapter:<br>• very frequent fertilisation (weekly to every two weeks) and irrigation (several times a week) in year 1<br>• avoid over-irrigation and N over-fertilisation<br>• Kr = 2 × cover fraction for cover below 60 %<br>• California Kc 0.65 (hedgerow oil) and 0.75 (vase table)<br>• stem-water-potential baselines and stress thresholds (mild below −15 bar, medium −20 to −25 bar)<br>• allowable depletion 65 %<br>• mature intensive rates N 150, P 35, K 200 kg/ha/yr<br>The guide's urea and ammonium-nitrate doses are mineral and are not permitted in organic production; only their frequency is used |
