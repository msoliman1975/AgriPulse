"""Section 12: weekly work plans (weeks 1-52) for bearing trees, one plan per olive type.

Each rule below is a sourced task with the weeks and types it applies to. Weeks are
calendar weeks starting 1 January; when a source gives a month or growth stage, the
week numbers are mapped from it and the task confidence is not raised above the
source's own level.
"""
import datetime
from text1 import B, h2, h3, p, note, table

S, D, N = "S", "D", "N"
OIL, GREEN, BLACK = "oil", "green", "black"
ALL = (OIL, GREEN, BLACK)

MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
KC = [0.50, 0.50, 0.65, 0.60, 0.55, 0.50, 0.45, 0.45, 0.55, 0.60, 0.65, 0.50]  # FAO-56, Spain, 60% cover

def week_dates(w):
    start = datetime.date(2026, 1, 1) + datetime.timedelta(days=7 * (w - 1))
    end = datetime.date(2026, 12, 31) if w == 52 else start + datetime.timedelta(days=6)
    mid = start + datetime.timedelta(days=3)
    ar = f"{start.day} {MONTHS_AR[start.month-1]} – {end.day} {MONTHS_AR[end.month-1]}"
    en = f"{start.day} {MONTHS_EN[start.month-1]} – {end.day} {MONTHS_EN[end.month-1]}"
    return ar, en, mid.month

def rng(a, b): return set(range(a, b + 1))

# ---- phases per type: (first week, last week, phase index 0-8)
PHASE_NAMES = [
 ("1 · السكون والتقليم الشتوي", "1 · Rest and winter pruning"),
 ("2 · تفتح البراعم والنمو الزهري", "2 · Bud break and inflorescence growth"),
 ("3 · التزهير", "3 · Flowering"),
 ("4 · العقد والنمو الأول للثمرة", "4 · Fruit set and first fruit growth"),
 ("5 · تصلّب النواة", "5 · Pit hardening"),
 ("6 · نمو الثمرة وتراكم الزيت", "6 · Fruit growth and oil accumulation"),
 ("7 · النضج ومتابعة الحصاد", "7 · Maturation and harvest monitoring"),
 ("8 · الحصاد", "8 · Harvest"),
 ("9 · ما بعد الحصاد", "9 · Post-harvest"),
]
COMMON = [(1, 6, 0), (7, 11, 1), (12, 16, 2), (17, 24, 3), (25, 30, 4)]
PHASES = {
 OIL:   COMMON + [(31, 40, 5), (41, 43, 6), (44, 46, 7), (47, 52, 8)],
 GREEN: COMMON + [(31, 32, 5), (33, 35, 6), (36, 39, 7), (40, 52, 8)],
 BLACK: COMMON + [(31, 39, 5), (40, 41, 6), (42, 45, 7), (46, 52, 8)],
}
def phase_of(t, w):
    for a, b, ph in PHASES[t]:
        if a <= w <= b:
            return ph
HARVEST = {OIL: rng(44, 46), GREEN: rng(36, 39), BLACK: rng(42, 45)}
LAST_FRUIT_WEEK = {OIL: 46, GREEN: 39, BLACK: 45}
POST = {OIL: rng(47, 50), GREEN: rng(40, 43), BLACK: rng(46, 49)}

# ---- rules: (weeks, types, ar, en, refs, conf, freq_type, freq_ar, freq_en)
R = []
def rule(weeks, types, ar, en, refs, conf, ft, far, fen):
    R.append((set(weeks), set(types), ar, en, refs, conf, ft, far, fen))

# Irrigation (every week, Kc filled per month)
IRR = "IRR"
rule(rng(1, 52), ALL, IRR, IRR, ["fao56"], "M", D, "مرة أسبوعيًا", "Once a week")
rule(rng(5, 8), ALL, "الري الشتوي: انتظام الري وعدم الإفراط حتى لا يحدث تصمغ، وتنظيف النقاطات والفلاتر؛ الري مرتين أسبوعيًا للأشجار المروية بالتنقيط.",
     "Winter irrigation: keep it regular and avoid over-watering to prevent gummosis, and clean emitters and filters; irrigate drip-irrigated trees twice a week.", ["moafeb"], "L", S, "مرتان أسبوعيًا", "Twice a week")
rule(rng(7, 24), ALL, "فترة حرجة للماء (من تمايز البراعم حتى التزهير والعقد، والطور الأول لنمو الثمرة): تجنّب العجز المائي.",
     "Water-critical period (bud differentiation to flowering and fruit set, and the first phase of fruit growth): avoid water deficit.", ["ecolive"], "M", N, "غير مذكور في المصادر", "Not given in sources")
rule(rng(25, 30), ALL, "تصلّب النواة أكثر الأطوار تحملًا للعجز المائي؛ في شمال سيناء أعطى الري بـ80% من البخر-نتح قيمًا وسطًا و60% أدناها، ووفّر الري الجزئي المتبادل للجذور 20% على الأقل من الماء.",
     "Pit hardening is the most deficit-tolerant stage; in North Sinai irrigation at 80% ETc gave intermediate values and 60% the lowest, and alternate partial root-zone irrigation saved at least 20% of water.", ["ecolive", "sinaiirr"], "M", N, "غير مذكور في المصادر", "Not given in sources")
rule(rng(31, 43), (OIL, BLACK), "الطور الثاني لنمو الثمرة وتراكم الزيت يحتاج الماء؛ الري بالتنقيط والري الناقص يقللان رطوبة البستان وعين الطاووس.",
     "The second phase of fruit growth and oil accumulation needs water; drip and deficit irrigation reduce orchard humidity and peacock spot.", ["ecolive", "buonaurio"], "M", N, "غير مذكور في المصادر", "Not given in sources")
rule(rng(31, 39), (GREEN,), "الطور الثاني لنمو الثمرة يحتاج الماء حتى الجني الأخضر.",
     "The second phase of fruit growth needs water until green harvest.", ["ecolive"], "M", N, "غير مذكور في المصادر", "Not given in sources")

# Records
rule(rng(1, 52), ALL, "السجلات العضوية: تسجيل كل مدخل وسبب استخدامه (إثبات الحاجة) والعمليات على كل قطعة.",
     "Organic records: record every input, the reason for its use (proof of need) and the operations on each parcel.", ["eu848", "law12"], "H", S, "مع كل عملية", "With every operation")

# Pruning and sanitation
rule(rng(2, 9), ALL, "التقليم الشتوي: تجنّب التقليم الجائر للأشجار القديمة؛ تقليم سنوي لتحسين الإضاءة والتهوية وتقليل الرطوبة داخل الشجرة.",
     "Winter pruning: avoid heavy pruning of old trees; prune annually to improve light and aeration and reduce humidity in the canopy.", ["moafeb", "buonaurio"], "L", N, "غير مذكور في المصادر", "Not given in sources")
rule(rng(2, 9), ALL, "نقل مخلفات التقليم والحشائش خارج المزرعة، وحرق الأفرع المصابة بخنافس القلف.",
     "Remove prunings and weeds from the farm, and burn branches infested with bark beetles.", ["moafeb"], "L", N, "غير مذكور في المصادر", "Not given in sources")
rule(rng(5, 9), ALL, "رش النحاس بعد تقليم الأشجار الكبيرة (ضمن حد 28 كجم نحاس/هكتار/7 سنوات).",
     "Spray copper after pruning large trees (within the 28 kg Cu/ha/7-year cap).", ["moafeb", "eu1165"], "L", D, "مرة بعد التقليم", "Once after pruning")
rule(rng(10, 13), ALL, "رشة نحاس ربيعية (مارس) ضد السل البكتيري وعين الطاووس؛ هيدروكسيد النحاس الأعلى كفاءة بأقل نحاس.",
     "Spring copper spray (March) against olive knot and peacock spot; copper hydroxide gives the best efficacy with the least copper.", ["uccost", "buonaurio"], "M", S, "مرة في مارس", "Once in March")
rule(rng(44, 48), ALL, "رشة نحاس خريفية (نوفمبر) ضد السل البكتيري وعين الطاووس.",
     "Autumn copper spray (November) against olive knot and peacock spot.", ["uccost", "buonaurio"], "M", S, "مرة في نوفمبر", "Once in November")
rule(rng(9, 17) | rng(42, 48), ALL, "رصد عين الطاووس: ظروف العدوى 15–21 °م مع بلل الأوراق؛ فحص الأوراق بعد فترات البلل.",
     "Peacock spot monitoring: infection conditions are 15–21 °C with leaf wetness; inspect leaves after wet periods.", ["buonaurio"], "H", N, "غير مذكور في المصادر", "Not given in sources")

# Fertilisation
rule(rng(1, 4), ALL, "تسميد فوسفاتي وبوتاسي إن لم يُضف في ديسمبر، من المصادر المسموح بها (صخر الفوسفات الطري، كبريتات البوتاسيوم الطبيعية).",
     "Phosphorus and potassium fertilisation if not applied in December, from permitted sources (soft ground rock phosphate, natural potassium sulphate).", ["maazrraty", "eu1165"], "L", S, "مرة واحدة", "Once")
rule(rng(49, 52), ALL, "تسميد فوسفاتي وبوتاسي (ديسمبر) من المصادر المسموح بها؛ البوتاسيوم بنسبة 2:1 مع النيتروجين بعد سنة الحمل العالي.",
     "Phosphorus and potassium fertilisation (December) from permitted sources; potassium at 2:1 to nitrogen after a high-yield year.", ["maazrraty", "ecolive", "eu1165"], "L", S, "مرة واحدة", "Once")
rule(rng(7, 22), ALL, "التسميد النيتروجيني مع الري من مصادر عضوية مسموحة (يُحظر النيتروجين المعدني): النمو الربيعي والعقد (أواخر أبريل–منتصف مايو) أكثر فترات الاحتياج؛ الإجمالي السنوي 0.5–1.5 كجم نيتروجين/شجرة.",
     "Nitrogen with irrigation from permitted organic sources (mineral N banned): spring growth and fruit set (late April–mid-May) are the peak need; annual total 0.5–1.5 kg N per tree.", ["ecolive", "eu848"], "M", N, "عدد الدفعات غير مذكور في المصادر", "Number of splits not given in sources")
rule(rng(27, 28), ALL, "تحليل الأوراق: 100 ورقة من أفرع غير مثمرة ومقارنتها بالحدود المثلى (نيتروجين 1.5–2.0%، بوتاسيوم 0.8–1.0%).",
     "Leaf analysis: 100 leaves from non-bearing shoots compared with optimum ranges (N 1.5–2.0%, K 0.8–1.0%).", ["ucleaf", "ecolive"], "M", S, "مرة في يوليو", "Once in July")

# Soil and weeds
rule(rng(9, 13), ALL, "مكافحة الحشائش: حرث سطحي بعمق نحو 10 سم أو حش؛ الحشائش التي تصل الأفرع السفلى تزيد عين الطاووس.",
     "Weed control: shallow tillage about 10 cm deep or mowing; weeds reaching the lower canopy increase peacock spot.", ["maazrraty", "buonaurio"], "L", S, "مرة في مارس", "Once in March")

# Olive fruit fly
rule(rng(9, 22), ALL, "ذبابة الزيتون: رصد المصائد في الربيع (ذروتان في مارس ومايو بمطروح)؛ المصائد اللاصقة الصفراء تصطاد أكثر من ماكفيل.",
     "Olive fly: spring trap monitoring (two peaks in March and May at Matrouh); yellow sticky traps catch more than McPhail traps.", ["flymatrouh", "flybehera"], "M", D, "قراءة أسبوعية", "Weekly reading")
FLY_MON = "FLYMON"
rule(rng(23, 46), ALL, FLY_MON, FLY_MON, ["ecolive", "flybehera"], "M", S, "فحص أسبوعي", "Weekly check")
KAOLIN = "KAOLIN"
rule(set(range(22, 47, 2)), ALL, KAOLIN, KAOLIN, ["alikaolin"], "H", S, "كل أسبوعين (12 رشة في التجربة)", "Every two weeks (12 sprays in the trial)")
SPINOSAD = "SPINOSAD"
rule(rng(26, 43), ALL, "طُعم السبينوساد (GF-120) أسبوعيًا أو كل أسبوعين عند ارتفاع الاصطياد؛ بالتبادل مع الكاولين والمصائد بسبب المقاومة.",
     "Spinosad bait (GF-120) weekly or every two weeks when catches rise; alternate with kaolin and traps because of resistance.", ["gf120"], "M", S, "أسبوعيًا أو كل أسبوعين", "Weekly or every two weeks")
rule(rng(27, 35), ALL, "الحرارة العالية تحدّ من الذبابة (نحو 50% موت للبيض عند 18–35 °م ولا فقس عند 18–37.8 °م)؛ تسجيل درجات الحرارة القصوى مع قراءة المصائد.",
     "High heat limits the fly (about 50% egg mortality at 18–35 °C and no hatch at 18–37.8 °C); record maximum temperatures with trap readings.", ["heatfly"], "M", D, "أسبوعيًا", "Weekly")
rule(rng(36, 39), (OIL, BLACK), "حد التدخل لذبابة الزيتون في سبتمبر: 4 (حمل كامل) إلى 16 (حمل 25%) أنثى/مصيدة ماكفيل/أسبوع.",
     "Olive fly action level in September: 4 (full crop) to 16 (25% of trees bearing) females/McPhail trap/week.", ["corfu"], "M", S, "أسبوعيًا", "Weekly")
rule(rng(40, 43), (OIL, BLACK), "حد التدخل لذبابة الزيتون في أكتوبر: 1 (حمل كامل) إلى 6 (حمل 25%) أنثى/مصيدة ماكفيل/أسبوع.",
     "Olive fly action level in October: 1 (full crop) to 6 (25% of trees bearing) females/McPhail trap/week.", ["corfu"], "M", S, "أسبوعيًا", "Weekly")
SANIT = "SANIT"
rule(set(), ALL, SANIT, SANIT, ["ecolive"], "M", N, "غير مذكور في المصادر", "Not given in sources")

# Olive moth
rule(rng(9, 17), ALL, "فراشة الزيتون: مصائد فرمونية لرصد الطيران الأول (مارس–أبريل، جيل الأزهار).",
     "Olive moth: pheromone traps to monitor the first flight (March–April, flower generation).", ["hegazi2011"], "M", D, "قراءة أسبوعية", "Weekly reading")
rule(rng(12, 13), ALL, "رش Bt كورستاكي قبل تفتح الأزهار مباشرة ضد جيل الأزهار، حسب نتائج الرصد.",
     "Spray Bt kurstaki just before flowers open against the flower generation, according to monitoring.", ["ecolive", "btk"], "M", D, "مرة واحدة", "Once")
rule(rng(17, 19), ALL, "رش Bt كورستاكي بعد العقد مباشرة ضد جيل الثمار، حسب نتائج الرصد.",
     "Spray Bt kurstaki just after fruit set against the fruit generation, according to monitoring.", ["ecolive", "btk"], "M", D, "مرة واحدة", "Once")
rule(rng(18, 26), ALL, "فراشة الزيتون: رصد الطيران الثاني (مايو–يونيو، جيل الثمار).", "Olive moth: monitor the second flight (May–June, fruit generation).", ["hegazi2011"], "M", D, "قراءة أسبوعية", "Weekly reading")
rule(rng(31, 43), ALL, "فراشة الزيتون: رصد الطيران الثالث (أغسطس–أكتوبر، جيل الأوراق) في البساتين شبه الجافة؛ لا يُسجل عادة في البساتين الجافة.",
     "Olive moth: monitor the third flight (August–October, leaf generation) in semi-arid groves; usually not recorded in arid groves.", ["hegazi2011"], "M", D, "قراءة أسبوعية", "Weekly reading")

# Jasmine moth
rule(rng(18, 26) | rng(36, 48), ALL, "دودة الياسمين: فترة الطيران (مايو–يونيو وسبتمبر–نوفمبر)؛ تشويش جنسي بفرمون 80 جم/هكتار أو إطلاق تريكوجراما 9000/شجرة كل أسبوعين، خاصة على النموات الحديثة.",
     "Jasmine moth: flight period (May–June and September–November); mating disruption with pheromone at 80 g/ha, or Trichogramma releases of 9,000 per tree every two weeks, especially on young growth.", ["palpitamd", "tricho"], "M", S, "إطلاق كل أسبوعين", "Release every two weeks")

# Psyllid
rule(rng(1, 24) | rng(46, 52), ALL, "بسيلا الزيتون: فحص الحوريات على النموات والعناقيد (من نوفمبر/ديسمبر حتى يونيو، الذروة مارس–أبريل).",
     "Olive psyllid: inspect for nymphs on shoots and inflorescences (November/December to June, peak March–April).", ["psyllid", "scales"], "M", N, "غير مذكور في المصادر", "Not given in sources")
rule(rng(6, 10), ALL, "رش زيت معدني (بارافيني) 1.5% ضد بسيلا الزيتون قبل تفتح البراعم وبداية التزهير.",
     "Spray mineral (paraffin) oil at 1.5% against the olive psyllid before bud break and the start of flowering.", ["moafeb", "eu1165"], "L", D, "مرة واحدة", "Once")

# Scales
rule({30}, ALL, "الحشرة القشرية السوداء: عند الإصابة الشديدة رش زيت بارافيني (أواخر يوليو).",
     "Black scale: for serious infestation spray paraffin oil (late July).", ["ecolive"], "M", S, "مرة (أواخر يوليو)", "Once (late July)")
rule({33}, ALL, "الحشرة القشرية السوداء: رشة زيت ثانية عند الحاجة (منتصف أغسطس).",
     "Black scale: second oil spray if needed (mid-August).", ["ecolive"], "M", S, "مرة عند الحاجة", "Once if needed")
rule(rng(40, 44), ALL, "الحشرة القشرية السوداء في ذروتها (أكتوبر) مع ذروة تطفل Metaphycus؛ حماية الطفيليات ومكافحة النمل.",
     "Black scale at its peak (October) together with peak Metaphycus parasitism; conserve parasitoids and control ants.", ["scales", "ecolive"], "M", N, "غير مذكور في المصادر", "Not given in sources")

# Leopard moth
rule({20}, ALL, "حفار ساق التفاح: تعليق موزعات التشويش الجنسي ومصائد الصيد الجماعي مع بداية الطيران (منتصف مايو).",
     "Leopard moth: hang mating-disruption dispensers and mass-trapping traps at the start of flight (mid-May).", ["zeuzflight", "zeuzera"], "M", D, "مرة واحدة", "Once")
rule(rng(21, 44), ALL, "حفار ساق التفاح: فترة الطيران حتى أوائل نوفمبر؛ فحص المصائد والأنفاق النشطة.",
     "Leopard moth: flight until early November; check traps and active galleries.", ["zeuzflight", "zeuzera"], "M", N, "غير مذكور في المصادر", "Not given in sources")

# Verticillium
rule(rng(24, 30), ALL, "الذبول الفيرتيسيليومي: مسح حراري بالطائرة المسيّرة صيفًا (دقة 20 سم) لكشف الأشجار المصابة مبكرًا عبر ارتفاع حرارة التاج ومؤشر CWSI.",
     "Verticillium wilt: summer thermal drone survey (20 cm resolution) to detect early infected trees from raised crown temperature and CWSI.", ["calderon"], "H", N, "غير مذكور في المصادر", "Not given in sources")
rule(rng(1, 14) | rng(46, 52), ALL, "الذبول الفيرتيسيليومي: فترة زيادة الأعراض (أواخر الخريف حتى الربيع)؛ فحص الأشجار وإزالة الميتة مع جذورها.",
     "Verticillium wilt: period of rising symptoms (late autumn to spring); inspect trees and remove dead ones with their roots.", ["calderon", "diaz"], "M", N, "غير مذكور في المصادر", "Not given in sources")

# Harvest - oil
rule(set(range(40, 47, 2)), (OIL,), "مؤشر النضج على 100 ثمرة سليمة من محيط الشجرة، مع نسبة الزيت والفينولات، لتحديد موعد الجني.",
     "Maturity index on 100 healthy fruits from around the tree, with oil and phenol content, to set the picking date.", ["nagaty"], "H", S, "كل أسبوعين", "Every two weeks")
rule({44}, (OIL,), "جني البيكوال والشملالي (أفضل موعد 2 نوفمبر)؛ وفي المواسم الحارة يُفضل الجني المبكر عند مؤشر نضج أقل.",
     "Pick Picual and Chemlali (best date 2 November); in hot seasons pick earlier at a lower maturity index.", ["nagaty"], "H", S, "مرة", "Once")
rule(rng(44, 46), (OIL,), "جني الكرونايكي (2–16 نوفمبر)؛ التأخير يرفع الحموضة فوق 0.8% ويخفض الفينولات.",
     "Pick Koroneiki (2–16 November); delay raises acidity above 0.8% and lowers phenols.", ["nagaty"], "H", S, "خلال الفترة", "Within the window")
rule(rng(44, 46), (OIL,), "العصر في أقصر وقت بعد الجني، خاصة للثمار المصابة بالذبابة؛ تسجيل كمية الحصاد لكل قطعة.",
     "Mill as soon as possible after picking, especially fly-damaged fruit; record the harvest quantity for each parcel.", ["ecolive", "eu848"], "M", D, "مع كل دفعة", "With every batch")

# Harvest - green table
rule(rng(33, 39), (GREEN,), "متابعة حجم الثمرة ولونها: الزيتون الأخضر يُجنى بعد بلوغ الحجم الطبيعي وقبل التلوّن؛ بلغ مؤشر نضج المنزانيللو 3.5–3.9 في 5 أكتوبر بشمال سيناء؛ التفاحي مبكر الحصاد.",
     "Monitor fruit size and colour: green olives are picked at normal size and before colour change; Manzanillo reached a maturity index of 3.5–3.9 by 5 October in North Sinai; Toffahi is early.", ["iocot", "nagaty", "toffahi"], "L", D, "أسبوعيًا", "Weekly")
rule(rng(36, 39), (GREEN,), "الجني الأخضر (العجيزي، التفاحي، المنزانيللو، الحامض) قبل التلوّن، ثم التخمير الطبيعي في محلول ملحي (ملح ≥6%، pH ≤4.3، لاكتيك ≥0.3%) بدون صودا كاوية.",
     "Green harvest (Aggezi, Toffahi, Manzanillo, Hamed) before colour change, then natural brine fermentation (salt ≥6%, pH ≤4.3, lactic ≥0.3%) without lye.", ["iocot", "eu1165"], "L", N, "غير مذكور في المصادر", "Not given in sources")

# Harvest - black table
rule(rng(40, 45), (BLACK,), "مؤشر النضج على 100 ثمرة: الزيتون الأسود يُجنى عند النضج الكامل أو قبله بقليل؛ مؤشر المنزانيللو 4.3–4.9 في 19 أكتوبر و5.4–5.7 في 2 نوفمبر.",
     "Maturity index on 100 fruits: black olives are picked fully ripe or slightly before; Manzanillo index 4.3–4.9 on 19 October and 5.4–5.7 on 2 November.", ["iocot", "nagaty"], "M", S, "كل أسبوعين", "Every two weeks")
rule(rng(42, 45), (BLACK,), "الجني الأسود (الكالاماتا، المنزانيللو، الحامض) ثم التخمير الطبيعي في محلول ملحي بدون صودا كاوية وبدون جلوكونات الحديدوز.",
     "Black harvest (Kalamata, Manzanillo, Hamed), then natural brine fermentation without lye and without ferrous gluconate.", ["iocot", "eu1165"], "L", N, "غير مذكور في المصادر", "Not given in sources")

# Post-harvest (all types)
rule(set(), ALL, "POSTMET", "POSTMET", ["metarh"], "L", D, "مرة واحدة", "Once")

def text_for(rule_ar, rule_en, t, w, month):
    if rule_ar == IRR:
        k = KC[month - 1]
        return (f"الري: حساب احتياج الأسبوع = معامل المحصول × البخر-نتح المرجعي؛ معامل الشهر للزيتون (تغطية 60%) = {k:.2f}، ويُخفض حسب التغطية الفعلية (تغطية 20% → معامل قاعدة ≈ 0.40).",
                f"Irrigation: weekly need = crop coefficient × reference evapotranspiration; this month's olive Kc (60% cover) = {k:.2f}, reduced for actual cover (20% cover → basal Kc ≈ 0.40).")
    if rule_ar == FLY_MON:
        return ("ذبابة الزيتون: فحص المصائد (لاصقة صفراء وماكفيل) أسبوعيًا مع تجديد الطُعم؛ الثمار قابلة للإصابة منذ تصلّب النواة.",
                "Olive fly: check traps (yellow sticky and McPhail) weekly and renew the bait; fruit is susceptible from pit hardening.")
    if rule_ar == KAOLIN:
        return ("رش الكاولين 3–4% (5% في الإصابة العالية) كل أسبوعين من 1 يونيو حتى الحصاد، 12–16 لتر/شجرة؛ خفّض الإصابة 69–83% في مطروح.",
                "Spray kaolin at 3–4% (5% under high pressure) every two weeks from 1 June to harvest, 12–16 L per tree; it cut infestation by 69–83% at Matrouh.")
    return rule_ar, rule_en

def tasks_for(t, w):
    ar_d, en_d, month = week_dates(w)
    out = []
    for weeks, types, ar, en, refs, conf, ft, far, fen in R:
        if t not in types:
            continue
        active = w in weeks
        if (ar in (FLY_MON, KAOLIN) or "GF-120" in en) and w > LAST_FRUIT_WEEK[t]:
            active = False
        if ar == SANIT:
            active = w in POST[t]
            if active:
                ar, en = ("ذبابة الزيتون بعد الحصاد: جمع الثمار المتساقطة والمتبقية التي تشتّي فيها الحشرة، ورعي الأغنام بعد الحصاد.",
                          "Olive fly after harvest: collect fallen and leftover fruit in which the insect overwinters, and graze sheep after harvest.")
        if ar == "POSTMET":
            active = w == min(POST[t])
            if active:
                ar, en = ("رش فطر Metarhizium brunneum على التربة تحت الأشجار في الخريف ضد عذارى ذبابة الزيتون (خفض حتى 50% في إسبانيا).",
                          "Spray Metarhizium brunneum on the soil under the trees in autumn against olive fly pupae (up to 50% reduction in Spain).")
        if not active:
            continue
        ar2, en2 = text_for(ar, en, t, w, month)
        out.append((ar2, en2, refs, conf, ft, far, fen))
    return out

TYPES = [
 (OIL, "12.2", "خطة زيتون الزيت (كرونايكي، بيكوال، كوراتينا، شملالي، المراقي، أربيكوينا)", "Plan for oil olives (Koroneiki, Picual, Coratina, Chemlali, Maraki, Arbequina)"),
 (GREEN, "12.3", "خطة زيتون المائدة الأخضر (عجيزي شامي، عجيزي عقصي، تفاحي، منزانيللو، حامض)", "Plan for green table olives (Aggezi Shami, Aggezi Akse, Toffahi, Manzanillo, Hamed)"),
 (BLACK, "12.4", "خطة زيتون المائدة الأسود (كالاماتا، منزانيللو، حامض)", "Plan for black table olives (Kalamata, Manzanillo, Hamed)"),
]

h2("s12", "12. خطة العمل الزراعية الأسبوعية للأشجار المثمرة", "12. Weekly Agricultural Work Plan for Bearing Trees")
h3("s12-1", "12.1 كيفية قراءة الخطط ومرجعها الزمني", "12.1 How to read the plans and their time reference")
p("الأسبوع 1 يبدأ في 1 يناير. لكل نوع زيتون خطة مستقلة لأن مراحل نمو الثمرة والحصاد والتصنيع تختلف (القسم 6.2)؛ الأسابيع 1–30 متشابهة بين الأنواع، والأسابيع 31–52 تختلف. لكل أسبوع المرحلة التشغيلية وقائمة مرقّمة بالمهام، ولكل مهمة المصدر ودرجة الثقة وعدد مرات التنفيذ. يمكن تصفية الجدول حسب المرحلة. المواعيد مرتبطة بشمال مصر (الساحل الشمالي، شمال سيناء، غرب الدلتا) حيث أُجريت أغلب الدراسات المذكورة.",
  "Week 1 starts on 1 January. Each olive type has its own plan because fruit development, harvest and processing differ (Section 6.2); weeks 1–30 are similar between types and weeks 31–52 differ. Each week shows its operating phase and a numbered task list, each task with its source, confidence level and how often it is done. The table can be filtered by phase. Timing refers to northern Egypt (North Coast, North Sinai, West Delta), where most of the cited studies were done.")
table(["المرحلة", "زيتون الزيت", "مائدة أخضر", "مائدة أسود"], ["Phase", "Oil olives", "Green table", "Black table"], [
 ([PHASE_NAMES[i][0]] + [", ".join(f"{a}–{b}" for a, b, ph in PHASES[t] if ph == i) for t in (OIL, GREEN, BLACK)],
  [PHASE_NAMES[i][1]] + [", ".join(f"{a}–{b}" for a, b, ph in PHASES[t] if ph == i) for t in (OIL, GREEN, BLACK)],
  ["nagaty", "iocot", "ecolive"], "L") for i in range(9)
])
for t, num, ar, en in TYPES:
    h3(f"s12-{t}", f"{num} {ar}", f"{num} {en}")
    weeks = []
    for w in range(1, 53):
        ar_d, en_d, _ = week_dates(w)
        weeks.append((w, ar_d, en_d, phase_of(t, w), tasks_for(t, w)))
    B.append(("weeks", t, PHASE_NAMES, weeks))
