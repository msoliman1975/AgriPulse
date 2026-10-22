"""Section 8: new plantings, from planting to the onset of fruiting."""
from text1 import B, h2, h3, p, note, facts

def timeline(items): B.append(("timeline", items))
S, D, N = "S", "D", "N"   # how-often source: stated / set by compiler from source timing / not given

h2("s8", "8. الشتلات المزروعة حديثًا: العمليات والخطة حتى بداية الإثمار", "8. Newly Planted Seedlings: Operations and Plan to the Onset of Fruiting")
h3("s8-1", "8.1 نطاق هذا القسم", "8.1 Scope of this section")
p("يغطي هذا القسم الشتلة من التحضير قبل الزراعة حتى بداية الإثمار. يُكثّر الزيتون في مصر أساسًا بالعُقل المجذّرة (القسم 7.2)، ولذلك يتناول القسم الشتلة المجذّرة أو المطعومة الجاهزة للزراعة. الأرقام مأخوذة من المصادر، وما لا يوجد له رقم منشور مذكور في القسم 13.",
  "This section covers the seedling from preparation before planting to the onset of fruiting. In Egypt olive is propagated mainly by rooted cuttings (Section 7.2), so the section deals with a rooted or grafted nursery plant ready for planting. Numbers are taken from the sources; where no published number exists this is listed in Section 13.")
h3("s8-2", "8.2 الشتلة الجاهزة للزراعة", "8.2 Planting material ready for the field")
facts([
 ("تُستخدم مادة إكثار عضوية؛ والشتلات غير العضوية تحتاج إذنًا من جهة الرقابة قبل الزراعة، لموسم واحد، ولا تُعامل بمبيدات غير مسموحة.", "Organic planting material is used; non-organic plants need authorisation from the control body before planting, for one season at a time, and must not be treated with non-permitted products.", ["eu848"], "H"),
 ("تُفضّل شتلات منتَجة وفق نظام EPPO PM 4/17 المختبرة من الفيرتيسيليوم والزيليلا والفيروسات.", "Prefer plants produced under the EPPO PM 4/17 scheme, tested for Verticillium, Xylella and viruses.", ["eppo"], "M"),
 ("بداية الحمل: التفاحي مبكر، والعجيزي الشامي والحامض وسط.", "Start of bearing: Toffahi is early; Aggezi Shami and Hamed are intermediate.", ["ioc2012", "iocaggezi"], "H"),
])
h3("s8-3", "8.3 الري والتسميد للشتلة الصغيرة", "8.3 Irrigation and nutrition of the young tree")
facts([
 ("يُروى بالماء فقط في أول أسبوع أو أسبوعين، ثم يُضاف السماد مع كل رية بنسبة نيتروجين:بوتاسيوم 1:1 بعد ظهور علامات تأسيس الشتلة.", "Irrigate with water only for the first one or two weeks, then apply fertiliser with every irrigation at an N:K ratio of 1:1 once the trees show signs of establishment.", ["haifaprog"], "M"),
 ("معدل النيتروجين للبساتين الحديثة: 1 جم نيتروجين للشجرة يوميًا لكل سنة من عمرها.", "Nitrogen rate for young orchards: 1 g N per tree per day for every year of age.", ["haifaprog"], "M"),
 ("في الإنتاج العضوي يُحظر السماد النيتروجيني المعدني، فيُعطى النيتروجين من المصادر المسموح بها فقط.", "In organic production mineral nitrogen fertiliser is banned, so nitrogen comes only from permitted sources.", ["eu848", "eu1165"], "H"),
 ("يمكن تقليل تسميد النيتروجين أو حذفه في أول موسمين في الأراضي الخصبة.", "Nitrogen fertilisation can be reduced or omitted in the first two seasons on fertile soils.", ["ucyoung"], "M"),
 ("نظام الري الموصى به في أول سنتين: نقاطات سطحية.", "Recommended irrigation in the first two years: surface drippers.", ["haifaguide"], "M"),
 ("معامل المحصول يُعدّل حسب نسبة تغطية الأشجار للأرض؛ عند تغطية 20% ينخفض معامل القاعدة إلى نحو 0.40.", "The crop coefficient is adjusted for the trees' ground cover; at 20% cover the basal coefficient falls to about 0.40.", ["fao56"], "H"),
 ("البورون للأشجار الصغيرة: 10 جم بوراكس × عدد سنوات الزراعة، مع الحذر لسميته.", "Boron for young trees: 10 g borax × years since planting, with care because it is toxic.", ["ecolive"], "M"),
])
h3("s8-4", "8.4 حماية الشتلة الصغيرة", "8.4 Protection of the young tree")
facts([
 ("دودة الياسمين آفة أولية في المشاتل والزراعات الحديثة المروية؛ تُعالج عند إصابة أكثر من 5% من الأشجار في الربيع.", "Jasmine moth is a primary pest of nurseries and young irrigated plantings; treat when more than 5% of trees are infested in spring.", ["palpitamd", "palpitathr"], "M"),
 ("حلم براعم الزيتون مدمر للشجيرات والأشجار الصغيرة؛ تُستخدم إطلاقات المفترس Neoseiulus barkeri ضد الأكاروسات الدودية على الشتلات.", "Olive bud mite is destructive on shrubs and young trees; releases of the predator Neoseiulus barkeri are used against eriophyid mites on seedlings.", ["mites"], "M"),
 ("أعفان الجذور والذبول في الشتلات والبساتين الحديثة: حمض الهيوميك 2.5 جم/لتر رشًا للتربة أعطى أعلى حماية وزاد ارتفاع النبات وعدد الأوراق والوزن.", "Root rot and wilt in transplants and new orchards: humic acid at 2.5 g/L as a soil drench gave the best protection and increased plant height, leaf number and weight.", ["elmorsi"], "H"),
 ("النيماتودا على الشتلات: حمض الهيوميك أعطى أعلى وزن طازج للنبات (403.8%) في الصوبة.", "Nematodes on seedlings: humic acid gave the highest plant fresh weight (403.8%) in the greenhouse.", ["hammad"], "H"),
])
h3("s8-plan", "8.5 الخطة الزمنية من التحضير حتى بداية الإثمار", "8.5 Time plan from preparation to the onset of fruiting")
note("لكل مهمة سطر «عدد مرات التنفيذ» يبيّن مصدر الرقم (القسم 2.3).", "Each task has a 'How often' line stating where the number comes from (Section 2.3).")
timeline([
 ("قبل الزراعة بسنة أو أكثر", "One year or more before planting", "التسجيل والتحليل", "Registration and analysis", [
   ("إخطار جهة الرقابة ووضع المزرعة تحت التفتيش؛ تبدأ فترة التحول (3 سنوات للمعمّرات) من هذا التاريخ.", "Notify the control body and place the farm under inspection; the conversion period (3 years for perennials) starts from this date.", ["eu848", "codex", "law12"], "H", S, "مرة واحدة", "Once"),
   ("تقييم التربة حتى عمق متر بقطاعات وعينات: العمق، القوام، الصرف، pH، P2O5، K2O.", "Assess the soil to 1 m with profiles and samples: depth, texture, drainage, pH, P2O5, K2O.", ["ecolive"], "M", D, "مرة واحدة لكل قطعة", "Once per parcel"),
   ("مراجعة تاريخ الأرض: الأجسام الحجرية للفيرتيسيليوم تبقى حتى 14 سنة والدورة الزراعية غير كافية.", "Review the land's history: Verticillium microsclerotia survive up to 14 years and rotation is not adequate.", ["diaz"], "H", D, "مرة واحدة", "Once"),
   ("تحليل ملوحة مياه الري مقارنة بحد تحمل الزيتون (ملوحة مستخلص التربة 3–6 ديسيسيمنز/م).", "Analyse irrigation-water salinity against the olive tolerance threshold (soil-extract salinity 3–6 dS/m).", ["aragues"], "M", D, "مرة واحدة", "Once"),
 ]),
 ("صيف ما قبل الزراعة", "The summer before planting", "التشميس", "Solarisation", [
   ("تشميس التربة في الأراضي المعرضة للفيرتيسيليوم.", "Solarise the soil on land at risk of Verticillium.", ["eu848", "diaz"], "H", N, "غير مذكور في المصادر", "Not given in sources"),
 ]),
 ("قبل الزراعة بأسابيع", "Weeks before planting", "تجهيز الأرض والجور", "Land and holes", [
   ("تحريك التربة لعمق نحو متر دون قلب الطبقات، وتنظيف الحشائش الصعبة.", "Loosen the soil to about 1 m without inverting layers, and clear hard-to-control weeds.", ["ecolive"], "M", D, "مرة واحدة", "Once"),
   ("تركيب شبكة نقاطات سطحية للسنتين الأوليين.", "Install a surface-dripper network for the first two years.", ["haifaguide"], "M", D, "مرة واحدة", "Once"),
   ("تجهيز الجورة بنحو 15 كجم كمبوست مع الكبريت؛ ويُستبدل السوبر فوسفات (غير مسموح) بصخر الفوسفات الطري المسموح.", "Prepare the hole with about 15 kg compost and sulphur; replace superphosphate (not permitted) with permitted soft ground rock phosphate.", ["elaard", "eu1165"], "L", S, "مرة واحدة لكل جورة", "Once per hole"),
   ("ري الجورة مرتين قبل الزراعة.", "Irrigate the hole twice before planting.", ["elaard"], "L", S, "مرتان", "Twice"),
   ("اختيار الملقّحات حسب الصنف الرئيسي: المراقي والعجيزي لبعضهما؛ الكرونايكي للمنزانيللو والبيكوال؛ الدولتشي للكالاماتا والكوراتينا والكرونايكي.", "Choose pollinizers for the main variety: Maraki and Aggezi for each other; Koroneiki for Manzanillo and Picual; Dolce for Kalamata, Coratina and Koroneiki.", ["elsoda"], "H", D, "مرة واحدة", "Once"),
 ]),
 ("موعد الزراعة: منتصف فبراير–منتصف مايو أو منتصف أغسطس–منتصف نوفمبر", "Planting time: mid-February to mid-May, or mid-August to mid-November", "الزراعة", "Planting", [
   ("الزراعة في الموعد الأنسب (منتصف فبراير–منتصف مايو) أو الموعد الثاني (منتصف أغسطس–منتصف نوفمبر)، وتجنب يونيو–أغسطس وديسمبر–يناير.", "Plant in the best window (mid-February to mid-May) or the second window (mid-August to mid-November), avoiding June–August and December–January.", ["agriceg", "elaard"], "L", S, "مرة واحدة", "Once"),
   ("حفظ سجل الزراعة: تاريخ الزراعة، مصدر الشتلات، شهادتها، الإذن إن كانت غير عضوية.", "Keep a planting record: date, nursery source, certificate, and the authorisation if non-organic.", ["eu848", "law12"], "H", S, "مرة واحدة", "Once"),
 ]),
 ("الأسبوعان 1–2 بعد الزراعة", "Weeks 1–2 after planting", "التأسيس", "Establishment", [
   ("ري بالماء فقط دون تسميد.", "Irrigate with water only, without fertiliser.", ["haifaprog"], "M", S, "مع كل رية", "With every irrigation"),
 ]),
 ("الأسبوع 3 حتى نهاية السنة الأولى", "Week 3 to the end of year 1", "النمو الأول", "First growth", [
   ("بعد ظهور علامات التأسيس: سماد مسموح مع كل رية بنسبة نيتروجين:بوتاسيوم 1:1، بمعدل 1 جم نيتروجين/شجرة/يوم.", "Once establishment is visible: permitted fertiliser with every irrigation at N:K 1:1, at 1 g N/tree/day.", ["haifaprog", "eu848"], "M", S, "مع كل رية", "With every irrigation"),
   ("حساب الري من معامل المحصول المعدّل لتغطية الشتلة الصغيرة.", "Calculate irrigation from the crop coefficient adjusted for the young tree's ground cover.", ["fao56"], "H", D, "أسبوعيًا", "Weekly"),
   ("فحص دودة الياسمين خلال طيرانها (مايو–يونيو وسبتمبر–نوفمبر)؛ المعالجة عند تجاوز 5% من الأشجار المصابة في الربيع ببكتيريا Bt أو إطلاق التريكوجراما 9000/شجرة كل أسبوعين.", "Inspect for jasmine moth during its flights (May–June and September–November); treat when more than 5% of trees are infested in spring with Bt, or release Trichogramma at 9,000 per tree every two weeks.", ["palpitamd", "palpitathr", "btk"], "M", S, "إطلاقات كل أسبوعين", "Releases every two weeks"),
   ("فحص حلم البراعم على الشتلات وإطلاق المفترس Neoseiulus barkeri عند الإصابة.", "Inspect seedlings for bud mite and release the predator Neoseiulus barkeri when infested.", ["mites"], "M", N, "غير مذكور في المصادر", "Not given in sources"),
   ("عند ظهور أعفان الجذور أو الذبول: رش التربة بحمض الهيوميك 2.5 جم/لتر.", "If root rot or wilt appears: drench the soil with humic acid at 2.5 g/L.", ["elmorsi"], "H", N, "غير مذكور في المصادر", "Not given in sources"),
   ("إزالة الأفرع المصابة بخنافس القلف ونقل المخلفات خارج المزرعة.", "Remove branches infested with bark beetles and take residues off the farm.", ["moafeb"], "L", N, "غير مذكور في المصادر", "Not given in sources"),
   ("رشة نحاس ضد السل البكتيري في مارس في السنة الأولى.", "One copper spray against olive knot in March of the first year.", ["uccost"], "M", S, "مرة في مارس", "Once in March"),
 ]),
 ("السنة الثانية", "Year 2", "تكوين الهيكل", "Frame building", [
   ("سماد مسموح مع كل رية بمعدل 2 جم نيتروجين/شجرة/يوم (1 جم × عمر الشجرة)؛ ويمكن تقليله أو حذفه في الأراضي الخصبة.", "Permitted fertiliser with every irrigation at 2 g N/tree/day (1 g × tree age); it can be reduced or omitted on fertile soils.", ["haifaprog", "ucyoung"], "M", S, "مع كل رية", "With every irrigation"),
   ("بوراكس 10 جم × سنتين = 20 جم للشجرة عند الحاجة.", "Borax 10 g × 2 years = 20 g per tree when needed.", ["ecolive"], "M", S, "مرة واحدة", "Once"),
   ("تكوين شكل الكأس للبستان المكثف: ساق 80–100 سم وفروع رئيسية 2–4 مائلة 45–50°.", "Build the vase form for intensive orchards: trunk 80–100 cm and 2–4 main limbs inclined at 45–50°.", ["ecolive"], "M", N, "غير مذكور في المصادر", "Not given in sources"),
   ("استمرار برنامج حماية السنة الأولى (دودة الياسمين، حلم البراعم، أعفان الجذور).", "Continue the year-1 protection programme (jasmine moth, bud mite, root rot).", ["palpitamd", "mites", "elmorsi"], "M", D, "حسب الرصد", "According to monitoring"),
   ("نهاية الشهر الثاني عشر من بدء التحول: يجوز بيع المنتج وحيد المكوّن بوصف «في مرحلة التحول».", "From month 12 of conversion: a single-ingredient product may be sold as 'in-conversion'.", ["eu848"], "H", S, "مرة واحدة", "Once"),
 ]),
 ("السنة الثالثة", "Year 3", "الانتقال للحمل", "Transition to bearing", [
   ("سماد مسموح مع كل رية بمعدل 3 جم نيتروجين/شجرة/يوم.", "Permitted fertiliser with every irrigation at 3 g N/tree/day.", ["haifaprog"], "M", S, "مع كل رية", "With every irrigation"),
   ("التحول من النقاطات السطحية إلى الري تحت السطحي.", "Switch from surface drippers to subsurface drip.", ["haifaguide"], "M", S, "مرة واحدة", "Once"),
   ("أول تحليل أوراق في يوليو (100 ورقة من أفرع غير مثمرة) ومقارنته بالحدود المثلى (القسم 9.3).", "First leaf analysis in July (100 leaves from non-bearing shoots), compared with the optimum ranges (Section 9.3).", ["ucleaf", "ecolive"], "M", S, "مرة في السنة", "Once a year"),
   ("رشتا نحاس ضد السل البكتيري: مارس ونوفمبر.", "Two copper sprays against olive knot: March and November.", ["uccost"], "M", S, "مرتان في السنة", "Twice a year"),
   ("بدء برنامج ذبابة الزيتون مع ظهور الثمار (كاولين كل أسبوعين من 1 يونيو حتى الحصاد).", "Start the olive fly programme once fruit appears (kaolin every two weeks from 1 June to harvest).", ["alikaolin"], "H", S, "كل أسبوعين", "Every two weeks"),
 ]),
 ("بعد 3 سنوات من بدء التحول", "Three years after conversion started", "بداية الإثمار العضوي", "Onset of organic fruiting", [
   ("أول حصاد يمكن بيعه عضويًا بعد اكتمال 3 سنوات من بدء التحول؛ والانتقال إلى الخطة الأسبوعية للأشجار المثمرة (القسم 12).", "The first harvest that can be sold as organic comes after 3 full years of conversion; move to the weekly plan for bearing trees (Section 12).", ["eu848", "codex"], "H", S, "مرة واحدة", "Once"),
   ("في تجربة الإسماعيلية سُجّل محصول الكرونايكي والكوراتينا والمراقي في السنتين الخامسة والسادسة بعد الزراعة: 1.87–2.37 طن/فدان (مكثف) و5.43–6.95 (فائق الكثافة).", "In the Ismailia trial, Koroneiki, Coratina and Maraki yields were recorded in the fifth and sixth years after planting: 1.87–2.37 t/feddan (intensive) and 5.43–6.95 (super-high-density).", ["ali2024"], "H", S, "—", "—"),
 ]),
])
