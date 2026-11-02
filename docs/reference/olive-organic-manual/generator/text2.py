"""Sections 7, 9, 10, 11 and 13 of the Organic Olive Manual (section 8 is in seedlings.py,
section 12 in weekly.py)."""
from text1 import B, h2, h3, p, note, facts, table

def gaps(items): B.append(("gaps", items))

# ============ 7
h2("s7", "7. إنشاء البستان", "7. Orchard Establishment")
h3("s7-1", "7.1 نظم الزراعة والمسافات", "7.1 Planting systems and spacing")
table(["النظام", "المسافة (م)", "شجرة/فدان", "النتيجة في مصر"], ["System", "Spacing (m)", "Trees/feddan", "Result in Egypt"], [
 (["مطري تقليدي", "—", "30–40 (70–100/هكتار)", "الكثافة السائدة في البساتين المطرية"], ["Traditional rainfed", "—", "30–40 (70–100/ha)", "Prevailing density in rainfed orchards"], ["ioc2012"], "H"),
 (["مروي تقليدي", "—", "140–170 (333–400/هكتار)", "الكثافة السائدة في البساتين المروية"], ["Traditional irrigated", "—", "140–170 (333–400/ha)", "Prevailing density in irrigated orchards"], ["ioc2012"], "H"),
 (["مكثف", "5×6", "نحو 140", "متوسط 1.87–2.37 طن/فدان في السنتين 5 و6؛ أعلى وزن ثمرة"], ["Intensive", "5×6", "About 140", "Mean 1.87–2.37 t/feddan in years 5 and 6; highest fruit weight"], ["ali2024"], "H"),
 (["فائق الكثافة", "1.5×4", "نحو 700", "متوسط 5.43–6.95 طن/فدان؛ نسبة زيت أقل قليلًا"], ["Super-high-density", "1.5×4", "About 700", "Mean 5.43–6.95 t/feddan; slightly lower oil percentage"], ["ali2024"], "H"),
])
facts([
 ("في الإسماعيلية أعطى الكرونايكي في النظام فائق الكثافة 7.27–8.93 طن ثمار و1.14–1.42 طن زيت/فدان؛ والمراقي أعلى نسبة زيت (نحو 19% وزن طازج) لكن أقل محصول.", "At Ismailia, Koroneiki in super-high-density gave 7.27–8.93 t fruit and 1.14–1.42 t oil per feddan; Maraki had the highest oil percentage (about 19% fresh weight) but the lowest yield.", ["ali2024"], "H"),
 ("نظم الزراعة: تقليدي 7–20 م (30–200 شجرة/هكتار)؛ مكثف 3–4 م داخل الصف × 6–8 م بين الصفوف (250–600)؛ فائق الكثافة 0.9–1.5 × 3–4 م (1655–2990)؛ الكثافات العالية تزيد الحشرات القشرية وعين الطاووس ومشاكل الضوء؛ الحصاد بالهزازات يحتاج 6–8 م بين الصفوف.", "Planting systems: traditional 7–20 m (30–200 trees/ha); intensive 3–4 m in the row × 6–8 m between rows (250–600); super-intensive 0.9–1.5 × 3–4 m (1,655–2,990); high densities raise scale insects, peacock spot and light problems; shaker harvesting needs 6–8 m between rows.", ["haifaguide"], "M"),
 ("أصناف النظام فائق الكثافة الأكثر استخدامًا: أربيكوينا، أربوسانا، كرونايكي.", "The cultivars most used in super-high-density orchards: Arbequina, Arbosana, Koroneiki.", ["ali2024"], "H"),
 ("يرى دليل ECOLIVE أن نحو 300 شجرة/هكتار هو الحد الشائع للبستان العضوي، لأن الكثافة العالية تتعارض مع مبادئ الوقاية من الأمراض بتجنب الظل الزائد.", "The ECOLIVE guide regards about 300 trees/ha as the common maximum for an organic grove, because high density conflicts with disease prevention by avoiding excessive shading.", ["ecolive"], "M"),
 ("الكثافة العالية وقلة التهوية وزيادة الرطوبة تشجع عين الطاووس، وتتطلب تصميمًا وتقليمًا وريًا مضبوطًا.", "High density, poor aeration and high humidity favour peacock spot, and require planting design, pruning and controlled irrigation.", ["buonaurio"], "H"),
])
h3("s7-2", "7.2 مادة الزراعة والإكثار", "7.2 Planting material and propagation")
facts([
 ("الشتلات المصابة نقلت الذبول الفيرتيسيليومي إلى البساتين عالميًا؛ يُنتج نظام EPPO PM 4/17 شتلات وأصولًا مختبرة خالية من الفيرتيسيليوم والزيليلا وفيروسات ArMV وCLRV وSLRSV.", "Infected nursery plants have spread Verticillium wilt to orchards worldwide; the EPPO PM 4/17 scheme produces tested trees and rootstocks free of Verticillium, Xylella and ArMV, CLRV and SLRSV viruses.", ["eppo"], "M"),
 ("الزيليلا فاستيديوسا غير موجودة في مصر، وأوقفت مصر مؤقتًا استيراد شتلات أشجار الفاكهة من الدول المصابة.", "Xylella fastidiosa is absent from Egypt, which temporarily suspended imports of fruit-tree seedlings from infected countries.", ["xylella"], "M"),
 ("العُقل الطرفية الورقية تحت الضباب أو بالتحكم في نقص ضغط البخار أو في الصناديق الخشبية، مع IBA بتركيز 4000 جزء في المليون (شمال سيناء).", "Leafy sub-terminal cuttings under mist, vapour-pressure-deficit control or in wooden boxes, with IBA at 4,000 ppm (North Sinai).", ["hegazi2010"], "H"),
 ("تحت الضباب ونقص ضغط البخار كان يونيو أفضل موعد (متوسط 38%) وديسمبر أسوأها (نحو 9%)؛ في الصناديق الخشبية كان مارس الأفضل، وأعلى نسبة 86% للتشيبرسينو في مارس.", "Under mist and VPD control June was the best date (mean 38%) and December the worst (about 9%); in wooden boxes March was best, with the highest rate 86% for Chiperssino in March.", ["hegazi2010"], "H"),
 ("الصناديق الخشبية أعطت أعلى نسبة تجذير بأقل استهلاك للماء مقارنة بالضباب ونقص ضغط البخار.", "Wooden boxes gave the highest rooting percentage, while intermittent mist used the most water.", ["hegazi2010"], "H"),
 ("في تجربة معهد بحوث البساتين (ضباب، IBA 5000 جزء في المليون لمدة 5 ثوانٍ) كان أبريل أفضل موعد ثم أكتوبر، ويناير أسوأها.", "In the Horticulture Research Institute trial (mist, IBA 5,000 ppm for 5 seconds), April was the best date, then October, with January the worst.", ["sawarsan"], "H"),
 ("هرمون IBA غير مدرج في الملحق الأول (مواد الوقاية) ولا الثاني (الأسمدة) من اللائحة 2021/1165؛ يجب التحقق من جهة الاعتماد قبل استخدامه في مشتل عضوي.", "IBA is not listed in Annex I (plant protection) or Annex II (fertilisers) of Regulation 2021/1165; check with the certifier before using it in an organic nursery.", ["eu1165"], "M"),
 ("الأصول التي تمنع تكاثر الفطر (مقاومة) مثل الفرانتويو أكثر فاعلية ضد الذبول من الأصول المتحملة عند تطعيم البيكوال عليها، لكن الطعم الحساس يزيد حساسية الأصل.", "Rootstocks that prevent fungal proliferation (resistant) such as Frantoio are more effective against wilt than tolerant rootstocks when Picual is grafted on them, but a susceptible scion increases the rootstock's susceptibility.", ["diaz"], "H"),
])
h3("s7-3", "7.3 تجهيز الموقع", "7.3 Site preparation")
facts([
 ("تقييم التربة حتى عمق متر على الأقل بفتح قطاعات وأخذ عينات؛ القيم المناسبة: عمق أكثر من 0.8 م، قوام طمي إلى طمي طيني، صرف جيد، pH من 5.5 إلى 8.5 (الأمثل 6.0–7.5)، P2O5 أكثر من 25 ملجم/كجم، K2O أكثر من 50 ملجم/كجم.", "Assess the soil to at least 1 m by opening profiles and sampling; favourable values: depth over 0.8 m, loam to clay-loam texture, good drainage, pH 5.5–8.5 (optimum 6.0–7.5), P2O5 over 25 mg/kg, K2O over 50 mg/kg.", ["ecolive"], "M"),
 ("تحريك التربة لعمق نحو متر دون قلب الطبقات (حرث تحت التربة ثم محراث حفار)، وتنظيف الأرض من الحشائش الصعبة قبل الزراعة.", "Loosen the soil to about 1 m without inverting the layers (ripping, then a chisel or tine cultivator), and clear hard-to-control weeds before planting.", ["ecolive"], "M"),
 ("الأجسام الحجرية لفطر الفيرتيسيليوم تبقى في التربة حتى 14 سنة؛ والدورة الزراعية غير كافية لاتساع عوائل الفطر؛ والتشميس والإضافات العضوية تساعد في الإدارة.", "Verticillium microsclerotia survive in soil for up to 14 years; crop rotation is not adequate because of the fungus's wide host range; soil solarisation and organic amendments help manage it.", ["diaz"], "H"),
 ("ينمو الزيتون في أي تربة جيدة الصرف والتهوية بـpH 6.5–8.5، ويكفيه قطاع تربة 1.0–1.5 م؛ تُتجنب المواقع ذات المياه الجوفية الأقرب من 1.2 م أو التي يتجمع فيها الماء؛ يتأثر الزيتون عند نسبة صوديوم متبادل 20–40.", "Olive grows on any well-drained, aerated soil with pH 6.5–8.5 and needs a 1.0–1.5 m soil profile; avoid sites with groundwater shallower than 1.2 m or standing water; olive is affected at an exchangeable sodium percentage of 20–40.", ["haifaguide"], "M"),
 ("تصحيح التربة قبل الزراعة: القلوية تُحمّض بالكبريت العنصري (450–900 كجم/هكتار للرملية، 1.8–2.25 طن للطينية) على دفعتين بفارق سنة؛ والصودية تُعالج بالجبس ثم غسيل الصوديوم بالري.", "Pre-planting soil correction: alkaline soil is acidified with elemental sulphur (450–900 kg/ha for sandy soil, 1.8–2.25 t for clay) in two applications a year apart; sodic soil is corrected with gypsum followed by leaching of the sodium.", ["haifaguide"], "M"),
 ("التشميس مذكور صراحة في لائحة الإنتاج العضوي ضمن طرق الوقاية.", "Solarisation is explicitly listed among preventive methods in the organic regulation.", ["eu848"], "H"),
])
h3("s7-4", "7.4 موعد الزراعة وتجهيز الجورة", "7.4 Planting time and hole preparation")
facts([
 ("الموعد الأنسب للزراعة في مصر من منتصف فبراير حتى منتصف مايو، وموعد ثانٍ من منتصف أغسطس حتى منتصف نوفمبر.", "The most suitable planting time in Egypt is from mid-February to mid-May, with a second window from mid-August to mid-November.", ["agriceg"], "L"),
 ("أفضل موعد مارس وأبريل ثم الخريف (سبتمبر وأكتوبر)، مع تجنب أشهر الحر (يونيو–أغسطس) والصقيع (ديسمبر ويناير).", "The best time is March and April, then autumn (September and October), avoiding the hot months (June–August) and frost (December and January).", ["elaard"], "L"),
 ("موعد الزراعة: على مدار السنة عدا يوليو–أغسطس ونوفمبر–يناير.", "Planting time: year round, except July–August and November–January.", ["haifaguide"], "M"),
 ("خلطة الجورة نحو 15 كجم كمبوست مع سوبر فوسفات وكبريت، وتُروى الجورة مرتين قبل الزراعة.", "Planting-hole mix of about 15 kg compost with superphosphate and sulphur; the hole is irrigated twice before planting.", ["elaard"], "L"),
 ("السوبر فوسفات غير مدرج في قائمة الأسمدة المسموح بها؛ البديل المدرج صخر الفوسفات الطري، والكبريت العنصري مدرج.", "Superphosphate is not on the list of permitted fertilisers; the listed alternative is soft ground rock phosphate, and elemental sulphur is listed.", ["eu1165"], "H"),
])

import seedlings  # noqa: E402,F401  section 8

# ============ 9
h2("s9", "9. العمليات الزراعية للأشجار المثمرة", "9. Cultural Operations for Bearing Trees")
h3("s9-1", "9.1 التقليم", "9.1 Pruning")
facts([
 ("تجنّب التقليم الجائر للأشجار القديمة لأنه يضعف الإنتاج، ونقل مخلفات التقليم والحشائش خارج المزرعة، وحرق الأفرع المصابة بخنافس القلف (توصيات فبراير).", "Avoid heavy pruning of old trees because it weakens production; remove prunings and weeds from the farm, and burn branches infested with bark beetles (February recommendations).", ["moafeb"], "L"),
 ("رش النحاس بعد تقليم الأشجار الكبيرة (توصيات فبراير).", "Spray copper after pruning large trees (February recommendations).", ["moafeb"], "L"),
 ("التقليم السنوي يحسّن الإضاءة والتهوية ويقلل الرطوبة وفترات البلل داخل الشجرة، ويحسّن وصول الرش.", "Annual pruning improves light and aeration, reduces humidity and wetness periods inside the canopy, and improves spray penetration.", ["buonaurio"], "H"),
 ("في دراسة تكاليف كاليفورنيا يُقلَّم البستان في الربيع.", "In the California cost study the orchard is pruned in spring.", ["uccost"], "M"),
 ("الشكل الشائع في البساتين المكثفة هو الكأس: ساق 80–100 سم يتفرع إلى 2–4 أفرع رئيسية مائلة 45–50°.", "The common form in intensive orchards is the vase: a trunk of 80–100 cm branching into 2–4 main limbs inclined at 45–50°.", ["ecolive"], "M"),
])
h3("s9-2", "9.2 الري", "9.2 Irrigation")
table(["البند", "القيمة", "ملاحظة"], ["Item", "Value", "Note"], [
 (["معامل المحصول (فاو-56) لتغطية 40–60%", "بداية 0.65، منتصف 0.70، نهاية 0.70", "معامل القاعدة: 0.55 / 0.65 / 0.65"], ["Crop coefficient (FAO-56), 40–60% cover", "Initial 0.65, mid 0.70, end 0.70", "Basal: 0.55 / 0.65 / 0.65"], ["fao56"], "H"),
 (["معامل شهري (إسبانيا، تغطية 60%)", "يناير 0.50، فبراير 0.50، مارس 0.65، أبريل 0.60، مايو 0.55، يونيو 0.50، يوليو 0.45، أغسطس 0.45، سبتمبر 0.55، أكتوبر 0.60، نوفمبر 0.65، ديسمبر 0.50", "يُستخدم في الخطة الأسبوعية"], ["Monthly Kc (Spain, 60% cover)", "Jan 0.50, Feb 0.50, Mar 0.65, Apr 0.60, May 0.55, Jun 0.50, Jul 0.45, Aug 0.45, Sep 0.55, Oct 0.60, Nov 0.65, Dec 0.50", "Used in the weekly plan"], ["fao56"], "H"),
 (["تعديل التغطية", "مسافة 10 م وتغطية 20% تعطي معامل قاعدة منتصف الموسم ≈ 0.40", "يُحسب المعامل من التغطية الفعلية"], ["Cover adjustment", "10 m spacing and 20% cover give mid-season basal Kc ≈ 0.40", "Compute Kc from actual cover"], ["fao56"], "H"),
 (["عمق الجذور والاستنزاف المسموح", "1.2–1.7 م؛ p = 0.65", ""], ["Root depth and allowed depletion", "1.2–1.7 m; p = 0.65", ""], ["fao56"], "H"),
 (["الاستنزاف المسموح للجدولة بالتربة", "65% للزيتون", "يتفق مع قيمة فاو-56"], ["Allowable depletion for soil-based scheduling", "65% for olive", "Agrees with the FAO-56 value"], ["ucyoung"], "M"),
 (["معامل المحصول المقترح في كاليفورنيا", "0.65 لبساتين الزيت السياجية و0.75 لبساتين المائدة بشكل الكأس طوال الموسم", "التجارب الجارية تشير إلى قيم ربيعية أقل"], ["Crop coefficient suggested in California", "0.65 for hedgerow oil orchards and 0.75 for vase-shaped table orchards for the whole season", "Ongoing trials indicate lower spring values"], ["ucyoung"], "M"),
 (["تغطية أقل من 60%", "معامل التخفيض Kr = 2 × نسبة الأرض المظللة ظهرًا", ""], ["Cover below 60%", "Reduction coefficient Kr = 2 × fraction of ground shaded at midday", ""], ["ucyoung"], "M"),
 (["جهد ماء الساق (حجرة الضغط)", "غير مجهدة: −11 بار (يوم معتدل) إلى −15 بار (يوم حار جاف)؛ إجهاد خفيف تحت −15؛ متوسط −20 إلى −25 بار", "يُقاس على فرع به 1–3 أزواج أوراق لقصر عنق الورقة"], ["Stem water potential (pressure chamber)", "Non-stressed: −11 bar (mild day) to −15 bar (hot dry day); mild stress below −15; medium −20 to −25 bar", "Measured on a shoot with 1–3 leaf pairs because the olive petiole is short"], ["ucyoung"], "M"),
 (["التنقيط مقابل الغمر (الفيوم)", "447 مقابل 704 مم/سنة؛ نقص المحصول 23.7% بالغمر", ""], ["Drip vs flood (Fayoum)", "447 vs 704 mm/yr; 23.7% lower yield under flood", ""], ["fayoumdrip"], "M"),
 (["الري الجزئي المتبادل للجذور (شمال سيناء)", "وفّر 20% على الأقل من الماء؛ 60% من البخر-نتح أضعف القيم و80% وسط", "تجربة على الكالاماتا"], ["Alternate partial root-zone irrigation (North Sinai)", "Saved at least 20% water; 60% ETc gave the lowest values, 80% intermediate", "Kalamata trial"], ["sinaiirr"], "M"),
])
facts([
 ("الاحتياج المائي الموسمي تحت التنقيط: 600–800 مم/سنة للبساتين المكثفة و350–600 مم للتقليدية؛ وفي جدول هايفا للبساتين المثمرة (أكثر من 10 طن/هكتار) الإجمالي السنوي 7717 م³/هكتار لزيتون الزيت و4123 م³/هكتار لزيتون المائدة (الخطة الأسبوعية).", "Seasonal water requirement under drip: 600–800 mm/yr for intensive and 350–600 mm for traditional orchards; in the Haifa schedule for bearing orchards (over 10 t/ha) the annual total is 7,717 m³/ha for oil olives and 4,123 m³/ha for table olives (weekly plan).", ["haifaguide"], "M"),
 ("الفترات الأشد حساسية للعطش: لزيتون الزيت العقد وتراكم الزيت؛ ولزيتون المائدة العقد والطوران الأول والثالث لنمو الثمرة؛ تصلّب النواة أقلها تأثرًا.", "Most critical periods for water stress: for oil olives, fruit set and oil accumulation; for table olives, fruit set and fruit-growth stages 1 and 3; pit hardening has minimal impact on fruit size.", ["haifaguide"], "M"),
 ("التنقيط رفع إنتاج الزيت 30–50% ووفّر 30–45% من الماء مقارنة بالمطري والغمر؛ والتنقيط تحت السطحي أعطى 12.6 طن ثمار و2.4 طن زيت/هكتار مقابل 4.6 و1.1 في المطري.", "Drip raised oil yield by 30–50% and saved 30–45% of water compared with rainfed and flood irrigation; subsurface drip gave 12.6 t fruit and 2.4 t oil per ha against 4.6 and 1.1 rainfed.", ["haifaguide"], "M"),
 ("مواصفات الشبكة: نقاطات سطحية أول سنتين ثم تنقيط تحت سطحي على عمق 0.3 م؛ خطان لكل صف في البساتين التقليدية والمكثفة وخط واحد في فائقة الكثافة؛ مسافة النقاطات 0.50–0.75 م وتصرفها 1.0–1.6 لتر/ساعة حسب القوام.", "System specification: surface drippers for the first two years then subsurface drip at 0.3 m; two laterals per row in traditional and intensive orchards and one in super-intensive; emitter spacing 0.50–0.75 m and flow 1.0–1.6 L/h depending on soil texture.", ["haifaguide"], "M"),
 ("الزيتون حساس جدًا للإفراط في الري؛ التربة المشبعة تضعف الجذور وتزيد الإصابة بالفيتوفثورا والفيرتيسيليوم.", "Olive is very sensitive to over-irrigation; saturated soil damages roots and increases infection by Phytophthora and Verticillium.", ["haifaguide"], "M"),
 ("في فبراير: انتظام الري خلال الشتاء، وتنظيف النقاطات والفلاتر، وعدم الإفراط في المياه حتى لا يحدث تصمغ؛ والري مرتين أسبوعيًا للأشجار المروية بالتنقيط.", "In February: keep irrigation regular through winter, clean emitters and filters, and avoid over-watering to prevent gummosis; irrigate drip-irrigated trees twice a week.", ["moafeb"], "L"),
 ("الري بالتنقيط والري الناقص يقللان رطوبة البستان وبالتالي عين الطاووس.", "Drip and deficit irrigation reduce orchard humidity and thus peacock spot.", ["buonaurio"], "M"),
])
h3("s9-3", "9.3 التسميد العضوي", "9.3 Organic fertilisation")
table(["العنصر في الورقة", "ناقص", "مثالي", "سام"], ["Leaf nutrient", "Deficient", "Optimum", "Toxic"], [
 (["نيتروجين", "<1.4%", "1.5–2.0%", ">2.55%"], ["Nitrogen", "<1.4%", "1.5–2.0%", ">2.55%"], ["ecolive", "ucleaf"], "M"),
 (["فوسفور", "<0.05%", "0.1–0.3%", ">0.34%"], ["Phosphorus", "<0.05%", "0.1–0.3%", ">0.34%"], ["ecolive"], "M"),
 (["بوتاسيوم", "<0.4%", "0.8–1.0%", ">1.65%"], ["Potassium", "<0.4%", "0.8–1.0%", ">1.65%"], ["ecolive", "ucleaf"], "M"),
 (["كالسيوم", "<0.6%", "1.0–1.43%", ">3.15%"], ["Calcium", "<0.6%", "1.0–1.43%", ">3.15%"], ["ecolive"], "M"),
 (["مغنيسيوم", "<0.08%", "0.1–0.16%", ">0.69%"], ["Magnesium", "<0.08%", "0.1–0.16%", ">0.69%"], ["ecolive"], "M"),
 (["حديد", "<40 جزء في المليون", "90–124 جزء في المليون", ">460 جزء في المليون"], ["Iron", "<40 ppm", "90–124 ppm", ">460 ppm"], ["ecolive"], "M"),
])
facts([
 ("عينة الأوراق تؤخذ في يوليو من 100 ورقة على أفرع غير مثمرة.", "Leaf samples are taken in July: 100 leaves from non-bearing shoots.", ["ucleaf"], "M"),
 ("المعدلات الموصى بها للبستان المكثف المثمر: نيتروجين 150، فوسفور 35، بوتاسيوم 200 كجم/هكتار/سنة (من مصادر مسموحة في الإنتاج العضوي).", "Recommended rates for a mature intensive orchard: nitrogen 150, phosphorus 35, potassium 200 kg/ha/year (from permitted sources in organic production).", ["ucyoung", "eu1165"], "M"),
 ("النيتروجين السنوي نحو 0.5–1.5 كجم/شجرة (50–150 كجم/هكتار)، ويحتاجه أكثر وقت العقد (أواخر أبريل–منتصف مايو) والنمو الربيعي ونمو الثمرة، ويُضاف مع الري.", "Annual nitrogen about 0.5–1.5 kg/tree (50–150 kg/ha), needed most at fruit set (late April–mid-May), spring growth and fruit growth, applied with irrigation.", ["ecolive"], "M"),
 ("يُضاف البوتاسيوم بنسبة 2:1 مع النيتروجين، خاصة في السنة التالية لسنة حمل عالٍ.", "Potassium is applied at a 2:1 ratio to nitrogen, especially in the year after a high-yield year.", ["ecolive"], "M"),
 ("البورون: 100–150 جم بوراكس للشجرة الكبيرة كل 4 سنوات، وللصغيرة 10 جم × عدد سنوات الزراعة؛ البورون سام بتركيزات منخفضة.", "Boron: 100–150 g borax per mature tree every 4 years, and for young trees 10 g × years since planting; boron is toxic even at low concentrations.", ["ecolive"], "M"),
 ("توقيت النيتروجين: يكون في منطقة الجذور قبل النمو والتزهير (أوائل الربيع–أوائل الصيف)؛ الإجمالي للشجرة المثمرة 0.5–1.0 كجم؛ بالنثر يُقسم نصفين يناير وأكتوبر، ومع التسميد بالري يُعطى نحو 25% بعد العقد؛ والإفراط قبل العقد يصغّر الثمار ويزيد تبادل الحمل.", "Nitrogen timing: in the root zone before growth and bloom (early spring–early summer); bearing-tree total 0.5–1.0 kg; when broadcast split half in January and half in October, and with fertigation apply about 25% after fruit set; excess before fruit set gives small fruit and more alternate bearing.", ["haifaguide"], "M"),
 ("ما يزيله طن الثمار: 9.8 كجم نيتروجين، 25.9 كجم P2O5، 12.4 كجم K2O؛ وامتصاص الشجرة السنوي 276–578 جم نيتروجين و200–560 جم K2O في الدول المنتجة.", "Removal per tonne of fruit: 9.8 kg N, 25.9 kg P2O5, 12.4 kg K2O; annual tree uptake 276–578 g N and 200–560 g K2O in the producing countries.", ["haifaguide"], "M"),
 ("كثير من مزارعي البحر المتوسط يضيفون الأسمدة العضوية كل سنتين؛ التسميد العضوي السطحي (كمبوست، سماد مكمور) يحتاج حسابًا دقيقًا لتوازن العناصر؛ لا يوضع الكمبوست أو السماد ملاصقًا للساق؛ التسميد الخفيف المتكرر أثناء النمو أفضل.", "Many Mediterranean growers apply organic fertilisers every other year; top dressing with compost or composted manure needs careful balancing of nutrients; never place compost or fertiliser next to the trunk; feed lightly and often during the growing season.", ["haifaguide"], "M"),
 ("تحليل الأوراق أول مرة عند عمر سنتين ثم كل 1–2 سنة، في يوليو أو بعد 5–8 أسابيع من التزهير الكامل: 4 أوراق سليمة من وسط أفرع العام غير المثمرة من 20–25 شجرة لكل قطعة حتى 10 هكتارات؛ للبورون قد تكون عينة الثمار الناضجة أدق.", "First leaf analysis at two years of age, then every 1–2 years, in July or 5–8 weeks after full bloom: 4 healthy leaves from the middle of current-season non-bearing shoots from 20–25 trees per block of up to 10 ha; for boron, mature fruit samples may be more reliable.", ["haifaguide"], "M"),
 ("برنامج هايفا للبستان المثمر بالتسميد مع الري (إسبانيا، 500 شجرة/هكتار): نيتروجين 200–300، P2O5 200–240، K2O 395–480 كجم/هكتار؛ نحو ثلثيها من الربيع إلى أوائل الصيف والباقي بعد الحصاد؛ إنهاء التسميد قبل الحصاد بـ50 يومًا؛ الفوسفور حسب تحليل الأوراق. (الأسمدة المذكورة معدنية؛ في العضوي تؤخذ الكميات والتوقيت فقط من مصادر مسموحة.)", "Haifa programme for a fertigated bearing orchard (Spain, 500 trees/ha): N 200–300, P2O5 200–240, K2O 395–480 kg/ha; about two-thirds from spring to early summer and the rest after harvest; end fertigation 50 days before harvest; phosphorus by leaf analysis. (The fertilisers named are mineral; in organic production only the amounts and timing apply, from permitted sources.)", ["haifaprog", "eu848"], "M"),
 ("كمبوست مخلفات المعاصر (مياه الخضرة والجفت) أعطى محصولًا قريبًا من السماد العضوي المعدني التجاري في بستان عضوي لثلاث سنوات.", "Olive-mill waste compost (wastewater and pomace) gave yields close to a commercial organo-mineral fertiliser in an organic grove over three years.", ["pomace"], "M"),
 ("في البيكوال، الفلسبار مع سماد حيوي مذيب للبوتاسيوم رفع المحصول حتى 70%.", "In Picual, feldspar with a potassium-solubilising biofertiliser raised yield by up to 70%.", ["feldspar"], "L"),
 ("نقص البوتاسيوم والإفراط في النيتروجين يزيدان عين الطاووس.", "Potassium deficiency and excess nitrogen increase peacock spot.", ["buonaurio"], "H"),
 ("التسميد بالفوسفور والبوتاسيوم في يناير إن لم يُضف في ديسمبر.", "Phosphorus and potassium fertilisation in January if not applied in December.", ["maazrraty"], "L"),
])
h3("s9-4", "9.4 إدارة التربة والحشائش ومحاصيل التغطية", "9.4 Soil, weed and cover-crop management")
facts([
 ("تشترط اللائحة للمحاصيل المعمّرة الحفاظ على الخصوبة بمحاصيل سماد أخضر قصيرة وبقوليات وتنوع نباتي، وإضافة سماد الماشية أو المادة العضوية ويُفضّل مكمورًا.", "The regulation requires perennials to maintain fertility with short-term green manures, legumes and plant diversity, plus livestock manure or organic matter, preferably composted.", ["eu848"], "H"),
 ("تحميل الزيتون بالحمص أو العدس رفع المادة العضوية دون خفض محصول الزيتون (المغرب).", "Intercropping olive with chickpea or lentil raised soil organic matter without lowering olive yield (Morocco).", ["intercrop"], "M"),
 ("نمو الحشائش الزائد الذي يصل للأفرع السفلى يزيد عين الطاووس؛ الحرث أو الحش يقللها.", "Excessive weed growth reaching the lower canopy increases peacock spot; tillage or mowing reduces it.", ["buonaurio"], "H"),
 ("حرث سطحي بعمق نحو 10 سم في مارس لمكافحة الحشائش.", "Shallow tillage about 10 cm deep in March to control weeds.", ["maazrraty"], "L"),
])

# ============ 10
h2("s10", "10. المكافحة العضوية للآفات والأمراض", "10. Organic Pest and Disease Management")
h3("s10-1", "10.1 ذبابة ثمار الزيتون (Bactrocera oleae)", "10.1 Olive fruit fly (Bactrocera oleae)")
facts([
 ("للذبابة 3 إلى 6 أجيال سنويًا؛ تبدأ الثمرة في التعرض للإصابة عند تصلّب النواة؛ يكتمل الجيل صيفًا في 30–35 يومًا؛ وتشتتي كيرقات في التربة أو في الثمار المتساقطة.", "The fly has 3 to 6 generations a year; fruit becomes susceptible at pit hardening; a generation can be completed in 30–35 days in summer; it overwinters as pupae in soil or in fallen fruit.", ["ecolive"], "M"),
 ("المصائد اللاصقة الصفراء اصطادت أكثر من مصائد ماكفيل؛ والبحيرة أكثر إصابة من الفيوم.", "Yellow sticky traps caught more flies than McPhail traps; El-Behera was more affected than El-Fayoum.", ["flybehera"], "M"),
 ("في مطروح ظهرت ذروتان لاصطياد البالغات في مصائد ماكفيل خلال فترة عدم نشاط الثمار: مارس ومايو.", "At Matrouh, McPhail traps showed two adult peaks during the fruit-free period: March and May.", ["flymatrouh"], "M"),
 ("نحو 50% من البيض يموت عند دورة 18–35 °م، ولا يفقس عند 18–37.8 °م (كاليفورنيا).", "About 50% of eggs die on an 18–35 °C cycle, and none hatch at 18–37.8 °C (California).", ["heatfly"], "M"),
 ("الكاولين (Super Nano) رشًا كل أسبوعين من 1 يونيو حتى الحصاد (12 رشة، 12–16 لتر/شجرة) بتركيز 3–5% خفّض الإصابة 69.3–83.4% في مطروح؛ 5% الأفضل، و3–4% أكثر اقتصادية.", "Kaolin (Super Nano) sprayed every 2 weeks from 1 June to harvest (12 sprays, 12–16 L per tree) at 3–5% reduced infestation by 69.3–83.4% at Matrouh; 5% was best and 3–4% more economical.", ["alikaolin"], "H"),
 ("هيدروكسيد النحاس خفّض الإصابة 55.9–59.9% وأوكسي كلوريد النحاس 48.0–58.5% (يُحسب ضمن حد النحاس).", "Copper hydroxide reduced infestation by 55.9–59.9% and copper oxychloride by 48.0–58.5% (counts against the copper cap).", ["alikaolin", "eu1165"], "H"),
 ("المصائد الغذائية أو الفرمونية للصيد الجماعي تُفحص أسبوعيًا صيفًا ويُجدد الطُعم بانتظام؛ خفضت الضرر 30–100% لكن نتائجها متغيرة ولا تكفي وحدها.", "Food or pheromone traps for mass trapping are checked weekly in summer with the bait renewed regularly; they cut damage by 30–100%, but results vary and they are not enough alone.", ["ecolive"], "M"),
 ("طُعم السبينوساد (GF-120) أسبوعيًا أو كل أسبوعين من أواخر يونيو حتى أواخر أكتوبر خفّض الإصابة إلى نحو 7% مقابل 42.5% في الكنترول (كاليفورنيا)؛ سُجلت مقاومة للسبينوساد هناك.", "Spinosad bait (GF-120) applied weekly or every two weeks from late June to late October cut infestation to about 7% against 42.5% in the control (California); spinosad resistance was recorded there.", ["gf120"], "M"),
 ("حدود اقتصادية (كورفو) بالإناث/مصيدة ماكفيل/أسبوع: سبتمبر 16 (حمل 25% من الأشجار) إلى 4 (حمل كامل)؛ أكتوبر 6 إلى 1.", "Economic injury levels (Corfu) in females/McPhail trap/week: September 16 (25% of trees bearing) down to 4 (all trees bearing); October 6 down to 1.", ["corfu"], "M"),
 ("تقليل الثمار المتساقطة التي تشتّي فيها الحشرة، ومنها رعي الأغنام قبل الحصاد وبعده؛ والحصاد المبكر يساعد؛ والعصر في أقصر وقت بعد الجني.", "Reduce fallen fruit in which the insect overwinters, including sheep grazing before and after harvest; early harvest helps; mill as soon as possible after picking.", ["ecolive"], "M"),
 ("فطر Metarhizium brunneum رشًا تحت الأشجار خريفًا خفّض المجتمع حتى 50% (إسبانيا).", "Metarhizium brunneum sprayed under the canopy in autumn reduced the population by up to 50% (Spain).", ["metarh"], "L"),
])
h3("s10-2", "10.2 فراشة الزيتون (Prays oleae)", "10.2 Olive moth (Prays oleae)")
facts([
 ("ثلاثة أجيال في البساتين شبه الجافة بمصر: طيران مارس–أبريل، مايو–يونيو، أغسطس–أكتوبر؛ وفي البساتين الجافة تداخل الطيرانان الأول والثاني ولم تُصطد ذكور في أغسطس–أكتوبر.", "Three generations in semi-arid Egyptian groves: flights in March–April, May–June and August–October; in arid groves the first two flights overlapped and no males were caught in August–October.", ["hegazi2011"], "M"),
 ("بكتيريا Bt كورستاكي: رشة قبل تفتح الأزهار مباشرة ضد جيل الأزهار، وبعد العقد مباشرة ضد جيل الثمار، وفي بداية نمو الأفرع ضد جيل الأوراق؛ التوقيت حسب رصد المجتمع.", "Bt kurstaki: spray just before flowers open against the flower generation, just after fruit set against the fruit generation, and at the start of shoot growth against the leaf generation; time by population monitoring.", ["ecolive"], "M"),
 ("Btk قتل 86.6% من يرقات فراشة الزيتون معمليًا.", "Btk killed 86.6% of olive moth larvae in the lab.", ["btk"], "M"),
])
h3("s10-3", "10.3 دودة الياسمين (Palpita unionalis)", "10.3 Jasmine moth (Palpita unionalis)")
facts([
 ("آفة أولية في المشاتل والزراعات الحديثة المروية؛ استُهدف بالتشويش الجنسي الطيران الأول (مايو–يونيو) والثاني (سبتمبر–نوفمبر) قرب القاهرة.", "A primary pest in nurseries and young irrigated plantings; mating disruption near Cairo targeted the first flight (May–June) and the second (September–November).", ["palpitamd"], "M"),
 ("التشويش الجنسي بفرمون ثنائي 80 جم مادة فعالة/هكتار أحدث نحو 90% تضليلًا للذكور؛ وأفضل نتيجة للتريكوجراما عدة إطلاقات 9000 دبور/شجرة كل أسبوعين.", "Mating disruption with a two-component pheromone at 80 g a.i./ha gave about 90% male disorientation; the best Trichogramma result was several releases of 9,000 wasps per tree at two-week intervals.", ["palpitamd"], "M"),
 ("أربعة أنواع من التريكوجراما وُجدت طبيعيًا في بساتين الزيتون المصرية؛ إطلاقات شهرية من T. evanescens متبوعة بمنتج النيم كانت فعالة.", "Four Trichogramma species occur naturally in Egyptian olive groves; monthly T. evanescens releases followed by a neem product were effective.", ["tricho"], "M"),
 ("يُعالج في المشاتل والزراعات الحديثة عند إصابة أكثر من 5% من الأشجار في الربيع.", "Treat nurseries and young plantings when more than 5% of trees are infested in spring.", ["palpitathr"], "L"),
 ("Btk قتل 80.9% من يرقات دودة الياسمين معمليًا.", "Btk killed 80.9% of jasmine moth larvae in the lab.", ["btk"], "M"),
])
h3("s10-4", "10.4 بسيلا الزيتون (الحشرة القطنية)", "10.4 Olive psyllid (cotton insect)")
facts([
 ("سُجّلت البسيلا في مصر عام 1988 آفة خطيرة في العريش ورفح، ثم في الفيوم بعد سنتين.", "The psyllid was recorded in Egypt in 1988 as a serious pest at Al-Arish and Rafah, and at Fayoum two years later.", ["psyllid"], "H"),
 ("في العريش (1997–1999): جيل واحد سنويًا؛ يبدأ وضع البيض في نوفمبر في براعم الأفرع؛ تظهر الحوريات من نوفمبر/ديسمبر وتستمر حتى يونيو–أغسطس؛ الذروة حول منتصف أبريل (نحو 60 حورية/فرع)؛ البالغات طوال السنة مع سكون تكاثري صيفًا وخريفًا.", "At Al-Arish (1997–1999): one generation a year; egg-laying starts in November in twig buds; nymphs appear from November/December and continue to June–August; peak around mid-April (about 60 nymphs per twig); adults all year with reproductive dormancy in summer and autumn.", ["psyllid"], "H"),
 ("الضرر: سقوط العناقيد وانخفاض عدد البراعم الزهرية وجفاف المتاع، والعسلة تسبب العفن الهبابي وتساقط الأزهار والثمار الصغيرة؛ في تونس سبّب 6–8 حشرات/عنقود خسارة 13% وأكثر من 30 حشرة خسارة تتجاوز 40% (Euphyllura olivina).", "Damage: raceme drop, fewer flower buds and pistil drying, with honeydew causing sooty mould and drop of blossoms and young fruit; in Tunisia 6–8 insects per raceme caused 13% loss and over 30 insects more than 40% (Euphyllura olivina).", ["psyllid"], "H"),
 ("نشاط الحوريات الأمثل عند حرارة صغرى 13.3–13.9 °م وعظمى 25.3–26.3 °م؛ والرطوبة النسبية (67.6–69.4%) كانت أعلى من المدى الأمثل.", "Nymphs were most active at minimum temperatures of 13.3–13.9 °C and maximums of 25.3–26.3 °C; relative humidity (67.6–69.4%) was above the optimum range.", ["psyllid"], "H"),
 ("في مسح على مستوى مصر بلغ مجتمع البسيلا أقصاه في مارس.", "In a nationwide survey the psyllid population peaked in March.", ["scales"], "M"),
 ("رش الزيوت المعدنية بمعدل 1.5% ضد حشرة الزيتون القطنية قبل تفتح البراعم وبداية التزهير (توصيات فبراير).", "Spray mineral oil at 1.5% against the olive cotton insect before bud break and the start of flowering (February recommendations).", ["moafeb"], "L"),
 ("الزيوت البارافينية مدرجة في المواد المسموح بها عضويًا.", "Paraffin oils are on the list of substances permitted in organic production.", ["eu1165"], "H"),
])
h3("s10-5", "10.5 الحشرات القشرية", "10.5 Scale insects")
facts([
 ("الحشرة القشرية السوداء: بلغت أقصاها في أكتوبر، ووصل تطفل Metaphycus lounsburyi إلى 34.2% و40.1% في أكتوبر.", "Black scale: peaked in October, with Metaphycus lounsburyi parasitism of 34.2% and 40.1% in October.", ["scales"], "M"),
 ("تحبّ الرطوبة؛ تهوية التاج بالتقليم والري المعتدل أول خطوتين؛ مكافحة النمل الذي يحميها من الطفيليات؛ وعند الإصابة الشديدة رش زيت بارافيني أواخر يوليو وعند الحاجة منتصف أغسطس.", "It thrives in humidity; canopy aeration by pruning and moderate irrigation are the first steps; control ants that protect it from parasitoids; for serious infestation spray paraffin oil in late July and, if needed, mid-August.", ["ecolive"], "M"),
 ("قشرية الزيتون (Parlatoria oleae): إطلاقات الطفيليات المحلية رفعت التطفل دون انخفاض واضح في المجتمع.", "Olive scale (Parlatoria oleae): releases of indigenous parasitoids raised parasitism without a visible fall in numbers.", ["parlatoria"], "M"),
])
h3("s10-6", "10.6 الحفارات: حفار ساق التفاح وخنفساء القلف", "10.6 Borers: leopard moth and bark beetle")
facts([
 ("حفار ساق التفاح (Zeuzera pyrina): يبدأ الطيران منتصف مايو ويستمر حتى أوائل نوفمبر (شمال مصر).", "Leopard moth (Zeuzera pyrina): flight starts in mid-May and lasts until early November (northern Egypt).", ["zeuzflight"], "M"),
 ("التشويش الجنسي في زراعات كثيفة مصابة بشدة قلل اصطياد المصائد والأنفاق النشطة ورفع المحصول.", "Mating disruption in heavily infested dense plantings reduced trap catches and active galleries and raised yield.", ["zeuzera"], "M"),
 ("خنفساء القلف: حرق الأفرع المصابة ونقل مخلفات التقليم خارج المزرعة (توصيات فبراير).", "Bark beetle: burn infested branches and remove prunings from the farm (February recommendations).", ["moafeb"], "L"),
])
h3("s10-7", "10.7 الأكاروسات والنيماتودا", "10.7 Mites and nematodes")
facts([
 ("حلم براعم الزيتون (Aceria oleae) مدمر للشجيرات والأشجار الصغيرة، ويتضاعف 16.7 مرة في جيل 13.5 يومًا عند 31 °م ورطوبة 80%؛ يفترسه Neoseiulus cydnodactylon وAgistemus olivi.", "Olive bud mite (Aceria oleae) is destructive on young trees, increasing 16.7-fold per 13.5-day generation at 31 °C and 80% RH; it is preyed on by Neoseiulus cydnodactylon and Agistemus olivi.", ["mites"], "M"),
 ("النيماتودا: في الحقل خفّض Nemastrol نيماتودا تعقد الجذور 82.4% ونيماتودا الموالح 75.6% بعد 6 أشهر؛ وحمض الهيوميك أعطى أفضل نمو؛ الأبامكتين خفّض النيماتودا 85.4% في الصوبة لكنه غير مدرج في المواد المسموح بها عضويًا.", "Nematodes: in the field Nemastrol cut root-knot nematode by 82.4% and citrus nematode by 75.6% after 6 months; humic acid gave the best growth; abamectin cut nematodes by 85.4% in the greenhouse but is not on the list of organic-permitted substances.", ["hammad", "eu1165"], "H"),
])
h3("s10-8", "10.8 عين الطاووس والسل البكتيري", "10.8 Peacock spot and olive knot")
facts([
 ("عين الطاووس: تتكون الجراثيم بين 5 و25 °م، وأفضل إنبات 16–21 °م، والعدوى المثلى نحو 20 °م مع بلل قصير أو 15 °م مع بلل طويل؛ والأوراق الصغيرة حساسة أيضًا.", "Peacock spot: spores form at 5–25 °C, germination is optimal at 16–21 °C, and infection is optimal at about 20 °C with short wetness or 15 °C with long wetness; young leaves are also susceptible.", ["buonaurio"], "H"),
 ("المعاملات تُعطى تجريبيًا في الخريف و/أو الربيع؛ وفي التجارب المقارنة (3–4 رشات خريفًا وربيعًا) كان هيدروكسيد النحاس الأعلى كفاءة بأقل نحاس معدني.", "Treatments are applied empirically in autumn and/or spring; in comparative trials (3–4 sprays in autumn and spring) copper hydroxide gave the best efficacy with the least metallic copper.", ["buonaurio"], "H"),
 ("مضادات حيوية فعالة حقليًا: Pseudomonas fluorescens وBacillus atrophaeus وBacillus amyloliquefaciens.", "Field-effective antagonists: Pseudomonas fluorescens, Bacillus atrophaeus and Bacillus amyloliquefaciens.", ["buonaurio"], "M"),
 ("السل البكتيري سُجّل لأول مرة في مصر بالفيوم 2008 وأحدث أورامًا على البيكوال والمنزانيللو والفرانتويو خلال 20–30 يومًا من العدوى.", "Olive knot was first recorded in Egypt in Fayoum in 2008 and produced knots on Picual, Manzanillo and Frantoio within 20–30 days of inoculation.", ["knot"], "M"),
 ("في دراسة تكاليف كاليفورنيا: رشة نحاس ضد السل في مارس في السنة الأولى، ومن السنة الثالثة رشة في مارس وأخرى في نوفمبر.", "In the California cost study: one copper spray against knot in March in the first year, and from year three one in March and one in November.", ["uccost"], "M"),
])
h3("s10-9", "10.9 الذبول الفيرتيسيليومي وأعفان الجذور", "10.9 Verticillium wilt and root rot")
facts([
 ("عُزلت 36 عزلة من 12 موقعًا في 8 مناطق بمصر وقُسمت إلى ثلاث مجموعات توافق خضري (VCG2 السائدة: 21 من 35 عزلة).", "36 isolates were taken from 12 sites in 8 regions of Egypt and fell into three vegetative compatibility groups (VCG2 dominant: 21 of 35 isolates).", ["mousa"], "H"),
 ("في البحر المتوسط تزيد الإصابة وشدة الأعراض من أواخر الخريف وأوائل الشتاء حتى الربيع ثم تقل بشدة صيفًا؛ وتظهر الأعراض الأولى في الأشجار المروية بعد 18–24 شهرًا من الزراعة في تربة ملوثة.", "In the Mediterranean, incidence and symptom severity rise from late autumn–early winter to spring and drop sharply in summer; first symptoms in irrigated trees appear 18–24 months after planting in infested soil.", ["calderon"], "M"),
 ("الإدارة: نظافة مادة الزراعة، إدارة الري، التشميس، الإضافات العضوية، المكافحة الحيوية؛ التبخير الكيماوي غير فعال أو غير مسموح.", "Management: clean planting material, irrigation management, solarisation, organic amendments, biological control; chemical fumigation is ineffective or not allowed.", ["diaz"], "H"),
 ("أعفان الجذور في المشاتل والبساتين الحديثة بالوادي الجديد: إصابة 60.8% وشدة 48.7% في الداخلة و52.1% و43.6% في الخارجة؛ Fusarium oxysporum الأكثر عزلًا.", "Root rot in nurseries and new orchards in New Valley: 60.8% incidence and 48.7% severity in Dakhla, 52.1% and 43.6% in Kharga; Fusarium oxysporum the most frequent.", ["elmorsi"], "H"),
 ("حمض الهيوميك 2.5 جم/لتر رشًا للتربة أعطى أعلى حماية، يليه Inicium وFulvital وBio-Health، وكانت أفضل من المبيد الكيماوي Rizolex-T.", "Humic acid at 2.5 g/L as a soil drench gave the best protection, followed by Inicium, Fulvital and Bio-Health, all better than the chemical Rizolex-T.", ["elmorsi"], "H"),
])
h3("s10-10", "10.10 الرصد بالأقمار الصناعية والطائرات المسيّرة", "10.10 Monitoring from satellite and drone imagery")
facts([
 ("بالطائرة المسيّرة الحرارية ارتفع فرق حرارة التاج عن الهواء نحو 2 كلفن عند الإصابة الخفيفة بالذبول، وارتبط مؤشر الإجهاد المائي CWSI بالتوصيل الثغري (R² = 0.83)؛ دقة الصور الحرارية 20 سم.", "With thermal drone imagery, crown-minus-air temperature rose about 2 K at low wilt severity, and the Crop Water Stress Index (CWSI) correlated with stomatal conductance (R² = 0.83); thermal resolution was 20 cm.", ["calderon"], "H"),
 ("المؤشرات الحرارية والنسب المرئية والفلورة كشفت الإصابة مبكرًا، بينما ارتبطت المؤشرات البنائية مثل NDVI بالضرر الظاهر.", "Thermal indicators, visible ratios and fluorescence detected infection early, while structural indices such as NDVI related to visible damage.", ["calderon"], "H"),
 ("دمج بيانات الطقس مع NDVI من Sentinel-2 أعاد إنتاج المحتوى المائي النسبي للتربة حتى متر (r² = 0.795)، بعد فصل غطاء الأشجار عن الحشائش؛ جذور الزيتون تصل 0.8–1.0 م.", "Combining weather data with Sentinel-2 NDVI reproduced relative soil water content to 1 m (r² = 0.795), after separating tree cover from grass; olive roots reach 0.8–1.0 m.", ["battista"], "H"),
])

# ============ 11
h2("s11", "11. الحصاد والتصنيع", "11. Harvest and Processing")
h3("s11-1", "11.1 مؤشر النضج ومواعيد الحصاد", "11.1 Maturity index and harvest dates")
table(["الصنف", "أفضل موعد (شمال سيناء 2021–2023)", "مؤشر النضج"], ["Variety", "Best date (North Sinai 2021–2023)", "Maturity index"], [
 (["منزانيللو", "19 أكتوبر؛ يمكن أن يكون قبله بأسبوعين في المواسم الحارة", "4.69 (2021)، 4.90 (2022)؛ 4.34 في 5 أكتوبر 2023"], ["Manzanillo", "19 October; can be two weeks earlier in hot seasons", "4.69 (2021), 4.90 (2022); 4.34 on 5 October 2023"], ["nagaty"], "H"),
 (["بيكوال", "2 نوفمبر", "3.43، 3.20، 5.74"], ["Picual", "2 November", "3.43, 3.20, 5.74"], ["nagaty"], "H"),
 (["شملالي", "2 نوفمبر", "3.42، 3.32، 3.55"], ["Chemlali", "2 November", "3.42, 3.32, 3.55"], ["nagaty"], "H"),
 (["كرونايكي", "2–16 نوفمبر", "2.58–3.03"], ["Koroneiki", "2–16 November", "2.58–3.03"], ["nagaty"], "H"),
 (["طريق القاهرة–الإسكندرية (2013–2014): منزانيللو", "15 سبتمبر–15 أكتوبر (166–170 يومًا بعد التزهير الكامل)", "بدء الجني عند 2.5"], ["Cairo–Alexandria road (2013–2014): Manzanillo", "15 September–15 October (166–170 days after full bloom)", "Picking started at 2.5"], ["harvestdays"], "H"),
 (["طريق القاهرة–الإسكندرية: بيكوال، كوراتينا، كرونايكي", "15 أكتوبر–15 نوفمبر (بيكوال 184–192، كوراتينا 193–199، كرونايكي 216–224 يومًا)", "بدء الجني عند 2.5"], ["Cairo–Alexandria road: Picual, Coratina, Koroneiki", "15 October–15 November (Picual 184–192, Coratina 193–199, Koroneiki 216–224 days)", "Picking started at 2.5"], ["harvestdays"], "H"),
 (["طريق القاهرة–الإسكندرية: أربيكوينا", "1–15 نوفمبر (213–217 يومًا)", "بدء الجني عند 2.5"], ["Cairo–Alexandria road: Arbequina", "1–15 November (213–217 days)", "Picking started at 2.5"], ["harvestdays"], "H"),
])
facts([
 ("مع تأخير الجني زاد طول الثمرة وعرضها ووزنها ونسبة الزيت، وانخفضت الفينولات الكلية في الزيت (طريق القاهرة–الإسكندرية).", "Delaying picking increased fruit length, width, weight and oil content, while total polyphenols in the oil decreased (Cairo–Alexandria road).", ["harvestdays"], "H"),
 ("زيت بكر ممتاز: ثمار طازجة لا يزيد الوقت من الجني إلى المعصرة على 24–48 ساعة؛ إيقاف الري في الأسابيع السابقة للحصاد (الرطوبة المثلى نحو 50%)؛ ضرب الأشجار بالعصي غير موصى به.", "Extra virgin oil: fresh fruit with no more than 24–48 hours from picking to the mill; stop irrigation in the weeks before harvest (optimum moisture about 50%); beating the trees is not recommended.", ["haifaguide"], "M"),
 ("يُحسب مؤشر النضج من 100 ثمرة سليمة مأخوذة عشوائيًا من محيط الشجرة.", "The maturity index is determined on 100 healthy fruits taken at random around the tree.", ["nagaty"], "H"),
 ("الحموضة الحرة كانت 0.19–0.35% في جني 5 أكتوبر وارتفعت في 16 نوفمبر إلى 1.06–1.41% (بيكوال) و0.82–1.87% (كرونايكي) وحتى 1.87% (منزانيللو)؛ وتنخفض الفينولات والكلوروفيل مع النضج.", "Free acidity was 0.19–0.35% at the 5 October picking and rose by 16 November to 1.06–1.41% (Picual), 0.82–1.87% (Koroneiki) and up to 1.87% (Manzanillo); phenols and chlorophyll fall with ripening.", ["nagaty"], "H"),
 ("الثمار المصابة بالذبابة أكثر عرضة للتلف التأكسدي والميكروبي، فيُقصّر الوقت بين الجني والعصر قدر الإمكان.", "Fly-damaged fruit is more sensitive to oxidative and microbial breakdown, so keep the time from picking to milling as short as possible.", ["ecolive"], "M"),
])
h3("s11-2", "11.2 زيت الزيتون العضوي", "11.2 Organic olive oil")
facts([
 ("في مصر غالبًا أكثر من 70% من الزيت بكر ممتاز لأن الجني يدوي وطاقة المعاصر أكبر من كمية الثمار؛ 65% بكر ممتاز و15% بكر (2008/09).", "In Egypt more than 70% of oil is often extra virgin because picking is by hand and mill capacity exceeds the olive supply; 65% extra virgin and 15% virgin (2008/09).", ["ioc2012"], "H"),
 ("زيتون الزيت المروي يعطي 14–18% زيتًا في المعصرة، والمطري حتى 22%.", "Irrigated oil olives give 14–18% oil at the mill, rainfed up to 22%.", ["ioc2012"], "H"),
 ("مشكلة معروفة: محتوى Δ-7-ستيجماستينول وحمض اللينولينيك في بعض الزيوت المصرية.", "A known problem: Δ-7-stigmastenol and linolenic acid content in some Egyptian oils.", ["ioc2012"], "H"),
 ("حد الزيت البكر الممتاز 0.8% حموضة، والبكر حتى 2%.", "Extra virgin limit 0.8% acidity; virgin up to 2%.", ["ioc2012"], "H"),
])
h3("s11-3", "11.3 زيتون المائدة العضوي (أخضر وأسود)", "11.3 Organic table olives (green and black)")
facts([
 ("لا يُسمح بالصودا الكاوية للزيتون في التصنيع العضوي (مسموحة فقط للسكر وزيوت نباتية غير زيت الزيتون)، لذلك يكون زيتون المائدة العضوي من النوع «الطبيعي».", "Sodium hydroxide is not permitted for olives in organic processing (only for sugar and plant oils other than olive oil), so organic table olives are the 'natural' type.", ["eu1165", "codex"], "H"),
 ("الزيتون الطبيعي يوضع مباشرة في محلول ملحي يتخمر فيه كليًا أو جزئيًا؛ الحد الأدنى للملح 6%، والحد الأقصى للـpH 4.3، والحد الأدنى لحموضة اللاكتيك 0.3%.", "Natural olives are placed directly in brine where they ferment fully or partly; minimum salt 6%, maximum pH 4.3, minimum lactic acidity 0.3%.", ["iocot"], "H"),
 ("المعاملة الحرارية: بسترة لا تقل عن 15 وحدة بسترة للزيتون الطبيعي.", "Heat treatment: pasteurisation of at least 15 pasteurisation units for natural olives.", ["iocot"], "H"),
 ("الفئات التجارية ممتاز وأولى وثانية؛ مثلًا الثمار المعيبة في الزيتون الأخضر 4% و6% و10%، وتُقدّر العيوب في عينة لا تقل عن 200 ثمرة.", "Trade categories Extra, First and Second; for example blemished green olives 4%, 6% and 10%; defects assessed on a sample of at least 200 fruits.", ["iocot"], "H"),
 ("الإضافات المسموح بها في المعيار الدولي مثل البنزوات والسوربات وجلوكونات الحديدوز (لتثبيت لون الزيتون الأسود المؤكسد) غير مدرجة للمنتج العضوي.", "Additives allowed by the international standard such as benzoate, sorbate and ferrous gluconate (to fix the colour of oxidised black olives) are not listed for organic products.", ["iocot", "eu1165"], "H"),
 ("الأحماض المسموح بها عضويًا: اللاكتيك والستريك والطرطريك والماليك والأسكوربيك.", "Acids permitted in organic processing: lactic, citric, tartaric, malic and ascorbic.", ["eu1165"], "H"),
])

import weekly  # noqa: E402,F401  section 12

# ============ 13
h2("s13", "13. الفجوات المعلوماتية (ما لم تقدمه المصادر)", "13. Information Gaps (what the sources did not provide)")
p("لم يُعثر لهذه البنود على قيمة منشورة موثوقة؛ تُستكمل بالقياس الحقلي أو بالرجوع إلى معهد بحوث البساتين أو مركز بحوث الصحراء أو جهة الاعتماد.",
  "No reliable published value was found for these items; complete them with field measurements or by consulting the Horticulture Research Institute, the Desert Research Center or the certification body.")
gaps([
 ("موعد حصاد زيتون المائدة الأخضر بالأسبوع لكل صنف في مصر (العجيزي، التفاحي، المنزانيللو الأخضر)؛ المتاح هو التعريف الدولي للمرحلة وأن التفاحي مبكر.", "Green table-olive harvest week for each variety in Egypt (Aggezi, Toffahi, green Manzanillo); only the international definition of the stage and Toffahi's early harvest are available."),
 ("موعد حصاد الكالاماتا الأسود في مصر.", "Black Kalamata harvest date in Egypt."),
 ("كميات مياه الري المقاسة في الأراضي الصحراوية المصرية لكل مرحلة؛ المتاح جداول هايفا لمناخ البحر المتوسط ومعاملات الفاو وتوصية فبراير (مرتان أسبوعيًا).", "Irrigation volumes measured on Egyptian desert land for each phase; available are the Haifa Mediterranean schedules, FAO coefficients and the February recommendation (twice a week)."),
 ("موعد إضافة الكمبوست العضوي ومعدله (كجم/شجرة) للأشجار المثمرة في مصر.", "Timing and rate (kg/tree) of compost for bearing trees in Egypt."),
 ("أبعاد الجورة ومعدلات الري للشتلات المزروعة حديثًا في مصر.", "Planting-hole dimensions and irrigation rates for newly planted seedlings in Egypt."),
 ("قائمة المدخلات العضوية المسموح بها وفق القانون 12/2020 والمنتجات الحيوية المسجلة لدى لجنة مبيدات الآفات الزراعية.", "The list of organic inputs permitted under Law 12/2020 and the bio-products registered with the Agricultural Pesticide Committee."),
 ("الخريطة الصنفية لمعهد بحوث البساتين وتوصيف السلالات المسجلة.", "The Horticulture Research Institute variety map and descriptions of the registered selections."),
 ("احتياجات البرودة للأصناف المصرية وتواريخ التزهير لكل منطقة.", "Chilling requirements of Egyptian varieties and flowering dates for each region."),
 ("حدود اقتصادية لذبابة الزيتون معايرة لمصر، وحد للتدخل ضد البسيلا وفراشة الزيتون.", "Olive fly action thresholds calibrated for Egypt, and thresholds for the psyllid and olive moth."),
 ("تجارب عضوية مصرية ضد البسيلا وخنفساء القلف وعين الطاووس.", "Egyptian organic trials against the psyllid, bark beetle and peacock spot."),
 ("سنة بداية الإثمار لكل صنف في الأراضي المصرية؛ المتاح أن الأشجار الناتجة من العقل تثمر بعد نحو 4 سنوات بشكل عام.", "Year of first fruiting for each variety on Egyptian land; available only is that cutting-grown trees bear fruit in about four years in general."),
 ("صفحات دليل ECOLIVE 24–69 (التسميد العضوي، استخلاص الزيت، الأمراض) لم تصل في الملف المرفوع.", "Pages 24–69 of the ECOLIVE guide (organic fertilisation, oil extraction, diseases) were missing from the uploaded file."),
])
