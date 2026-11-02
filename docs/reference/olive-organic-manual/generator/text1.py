"""Sections 1-6 of the Organic Olive Manual.

Block helpers append to B. A fact row is (arabic, english, [source keys], confidence),
confidence in H (high), M (medium), L (low). No statement is added without a source.
"""
B = []
def h2(i, ar, en): B.append(("h2", i, ar, en))
def h3(i, ar, en): B.append(("h3", i, ar, en))
def p(ar, en): B.append(("p", ar, en))
def note(ar, en): B.append(("note", ar, en))
def facts(rows): B.append(("facts", rows))
def table(har, hen, rows): B.append(("table", har, hen, rows))

# ============ 1
h2("s1", "1. المقدمة والنطاق", "1. Introduction and Scope")
h3("s1-1", "1.1 الغرض من الدليل", "1.1 Purpose of the manual")
p("يقدّم هذا الدليل، في مرجع واحد، منهجية التشغيل ومراحل الموسم وأطواره وخطط عمل أسبوعية لإنتاج الزيتون إنتاجًا عضويًا في مصر، وخطة رعاية للشتلات المزروعة حديثًا حتى بداية الإثمار. كل معلومة مربوطة بمصدر منشور (قائمة مرقّمة في القسم 14 بروابط تشعبية) ومصحوبة بدرجة ثقة. لا يضيف الدليل توصيات من خارج المصادر؛ وحيث لا تقدّم المصادر قيمة محددة يُذكر ذلك صراحة في القسم 13 (الفجوات المعلوماتية).",
  "This manual brings together, in one reference, the operating method, season phases and stages, weekly work plans for organic olive production in Egypt, and a care plan for newly planted seedlings up to the onset of fruiting. Every statement is tied to a published source (numbered list with hyperlinks in Section 14) and carries a confidence level. The manual adds no recommendation that is not in the sources; where the sources give no value, this is stated in Section 13 (Information Gaps).")
h3("s1-2", "1.2 أنواع الزيتون المشمولة ولماذا ثلاث خطط", "1.2 Olive types covered and why there are three plans")
p("تُجمع الأصناف في ثلاثة أنواع حسب الغرض لأن مواعيد الحصاد وطريقة التصنيع العضوي تختلف بينها: (1) زيتون الزيت: كرونايكي، بيكوال، كوراتينا، شملالي، المراقي، أربيكوينا؛ (2) زيتون المائدة الأخضر: عجيزي شامي، عجيزي عقصي، تفاحي، منزانيللو، حامض؛ (3) زيتون المائدة الأسود: كالاماتا، منزانيللو، حامض. يعرّف المعيار الدولي الزيتون الأخضر بأنه يُجنى قبل تلوّن الثمرة بعد بلوغها الحجم الطبيعي، والأسود بأنه يُجنى عند النضج الكامل أو قبله بقليل. لذلك يحتوي القسم 12 على خطة أسبوعية مستقلة لكل نوع.",
  "Varieties are grouped into three types by end use, because harvest timing and organic processing differ between them: (1) oil olives: Koroneiki, Picual, Coratina, Chemlali, Maraki, Arbequina; (2) green table olives: Aggezi Shami, Aggezi Akse, Toffahi, Manzanillo, Hamed; (3) black table olives: Kalamata, Manzanillo, Hamed. The international standard defines green olives as harvested before colour change once they reach normal size, and black olives as harvested when fully ripe or slightly before. Section 12 therefore contains a separate weekly plan for each type.")
facts([
 ("الزيتون الأخضر: ثمار تُجنى خلال فترة النضج قبل التلوّن وبعد بلوغ الحجم الطبيعي. الزيتون المتلوّن: يُجنى عند تغيّر اللون. الزيتون الأسود: يُجنى عند النضج الكامل أو قبله بقليل.", "Green olives: harvested during the ripening period, before colouring and once normal size is reached. Olives turning colour: harvested at colour change. Black olives: harvested when fully ripe or slightly before.", ["iocot"], "H"),
 ("الصنف حامض يُستخدم للتخليل الأخضر والأسود، والعجيزي الشامي للتخليل الأخضر أو المحشو، والتفاحي للأخضر فقط لأنه يلين ويتخمر عند التخليل الأسود.", "Hamed is used for green and black pickling, Aggezi Shami for green or stuffed olives, and Toffahi for green only because it softens and ferments when black-pickled.", ["ioc2012"], "H"),
])

# ============ 2
h2("s2", "2. منهجية إعداد الدليل ومقياس درجة الثقة", "2. Methodology of this Manual and Confidence Scale")
h3("s2-1", "2.1 طريقة جمع المعلومات", "2.1 How the information was collected")
p("بُحث عن المصادر في: التشريع المصري (القانون 12 لسنة 2020) والتشريع الأوروبي ودستور الأغذية، ومطبوعات المجلس الدولي للزيتون والفاو، والدوريات المصرية المحكّمة على بنك المعرفة المصري (مركز البحوث الزراعية، مركز بحوث الصحراء، الجامعات المصرية)، ودراسات دولية محكّمة، ونشرات وزارة الزراعة كما نقلتها الصحف. قُرئ النص الكامل لـ26 مصدرًا زوّد بها المستخدم وفُحصت كل معلومة تستند إليها؛ المصادر التي لم يُتح منها إلا الملخص تحمل درجة ثقة أقل.",
  "Sources were searched in: Egyptian legislation (Law 12 of 2020), EU legislation and the Codex Alimentarius, International Olive Council and FAO publications, Egyptian peer-reviewed journals on the Egyptian Knowledge Bank (Agricultural Research Center, Desert Research Center, Egyptian universities), international peer-reviewed studies, and Ministry of Agriculture bulletins as reported in the press. The full texts of 26 documents supplied by the user were read and every statement citing them was checked; sources available only as abstracts carry a lower confidence level.")
h3("s2-2", "2.2 مقياس درجة الثقة", "2.2 Confidence scale")
table(["المستوى", "التعريف المستخدم في هذا الدليل"], ["Level", "Definition used in this manual"], [
 (["@H", "دراسة محكّمة أو مصدر رسمي يتناول الزيتون في مصر مباشرة، أو نص تشريعي أو معيار دولي، وقُرئت القيمة من النص الكامل."], ["@H", "Peer-reviewed study or official source on olive in Egypt, or a legal text or international standard, with the value read from the full text."], [], None),
 (["@M", "مصدر محكّم أو دليل إرشادي من بلد آخر أو لصنف آخر، أو دراسة مصرية قُرئ ملخصها فقط."], ["@M", "Peer-reviewed source or extension guide from another country or for another variety, or an Egyptian study read from its abstract only."], [], None),
 (["@L", "مصدر ثانوي أو صحفي أو موقع إرشادي غير رسمي، أو رقم أسبوع حُدد بتطبيق توقيت المصدر (شهر أو طور نمو) على التقويم الأسبوعي."], ["@L", "Secondary, press or unofficial extension source, or a week number obtained by mapping a source's timing (month or growth stage) onto the weekly calendar."], [], None),
])
h3("s2-3", "2.3 سطر «عدد مرات التنفيذ»", "2.3 The 'How often' line")
p("لكل مهمة في الخطط سطر يبيّن عدد مرات التنفيذ، وبين القوسين مصدر الرقم: «مذكور في المصدر» إذا أُخذ الرقم من المرجع؛ «حدده المعدّ من توقيت المصدر» إذا ذكر المصدر التوقيت فقط (مثل: من 1 يونيو حتى الحصاد) فحُوّل إلى عدد؛ «غير مذكور في المصادر» إذا لم يوجد رقم منشور ويجب تحديده في الحقل.",
  "Every task in the plans has a 'How often' line; the note in brackets says where the number comes from: 'stated in source' when the number is taken from the reference; 'set by compiler from source timing' when the source gives only the timing (for example, from 1 June to harvest) and this was turned into a count; 'not given in sources' when no published number exists and it must be set in the field.")

# ============ 3
h2("s3", "3. أصناف الزيتون في مصر والشرق الأوسط", "3. Olive Varieties of Egypt and the Middle East")
h3("s3-1", "3.1 الأصناف المحلية المصرية", "3.1 Egyptian local varieties")
table(["الصنف", "الأصل", "الاستخدام", "الخصائص"], ["Variety", "Origin", "Use", "Traits"], [
 (["عجيزي شامي", "الفيوم", "مائدة (أخضر، محشو)", "نحو 20% من مساحة الزيتون في مصر، ونحو 80% في الفيوم و40% في الإسماعيلية و30% في النوبارية؛ متحمل جدًا للإشعاع والجفاف؛ ثمرة كبيرة سهلة فصل النواة؛ زيت 7–9%؛ حساس لذبابة الزيتون"],
  ["Aggezi Shami", "Fayoum", "Table (green, stuffed)", "About 20% of Egypt's olive area, and about 80% in Fayoum, 40% in Ismailia and 30% in Nubaria; very hardy to radiation and drought; large freestone fruit; oil 7–9%; susceptible to olive fly"], ["ioc2012", "iocaggezi"], "H"),
 (["عجيزي عقصي", "الفيوم", "مائدة (أخضر)", "قدرة تجذير وإنتاجية عالية؛ ثمرة ثقيلة جدًا؛ انتشر بعد أن كان محدودًا"],
  ["Aggezi Akse", "Fayoum", "Table (green)", "High rooting ability and productivity; very heavy fruit; now widely distributed"], ["ioc2012"], "H"),
 (["تفاحي", "الفيوم، الجيزة، بني سويف", "مائدة (أخضر)", "مبكر الحمل والتزهير والحصاد؛ نسبة لحم/نواة عالية جدًا؛ زيت 5–7%؛ لا يصلح للتخليل الأسود؛ نحو 6% من المساحة"],
  ["Toffahi", "Fayoum, Giza, Beni Suef", "Table (green)", "Early bearing, flowering and harvest; very high flesh-to-stone ratio; oil 5–7%; unsuitable for black pickling; about 6% of area"], ["ioc2012", "toffahi"], "H"),
 (["حامض", "سيوة، شمال سيناء", "مائدة (أخضر وأسود)", "متحمل للجفاف والملوحة؛ إنتاج عالٍ ومنتظم؛ ثمرة كبيرة حساسة للنقل؛ نحو 6% من المساحة"],
  ["Hamed", "Siwa, North Sinai", "Table (green and black)", "Drought- and salt-resistant; high, constant productivity; large fruit sensitive to handling; about 6% of area"], ["ioc2012"], "H"),
 (["وطيقن", "سيوة", "ثنائي، أساسًا زيت", "زيت عالي الأوليك قليل المرارة؛ الحصاد أكتوبر–ديسمبر؛ نحو 5% من المساحة؛ ينخفض محصوله مع ملوحة مياه الآبار أكثر من حامض"],
  ["Wateken (Wetteken)", "Siwa", "Dual, mainly oil", "High-oleic, low-bitterness oil; harvest October–December; about 5% of area; yield falls with well-water salinity more than Hamed"], ["ioc2012", "siwa"], "H"),
 (["المراقي", "سيوة", "زيت", "عالي الأوليك؛ إنتاجية عالية جدًا؛ قدرة تجذير منخفضة؛ الحصاد نوفمبر–ديسمبر؛ أعلى نسبة زيت بين التراكيب المصرية المدروسة؛ نحو 2% من المساحة"],
  ["Maraki", "Siwa", "Oil", "High-oleic; very high crop intensity; low rooting ability; harvest November–December; highest oil content among the Egyptian genotypes studied; about 2% of area"], ["ioc2012", "elsayed"], "H"),
 (["سيوي (Sewia)", "سيوة", "ثنائي", "أثقل ثمرة ونواة بين التراكيب المدروسة؛ زيت أقل من المراقي"],
  ["Siwi (Sewia)", "Siwa", "Dual", "Heaviest fruit and stone among the genotypes studied; less oil than Maraki"], ["elsayed"], "M"),
])
h3("s3-2", "3.2 الأصناف المستوردة المزروعة في مصر", "3.2 Imported varieties grown in Egypt")
table(["الصنف", "الاستخدام", "النتائج في مصر"], ["Variety", "Use", "Results in Egypt"], [
 (["كرونايكي", "زيت", "أعلى محصول (44.2 كجم/شجرة) وأعلى زيت (49.9% وزن جاف) في الأراضي المستصلحة؛ أفضل محصول في النظام فائق الكثافة بالإسماعيلية (7.27–8.93 طن/فدان)؛ تحمل للحرارة في شمال سيناء؛ أفضل حصاد 2–16 نوفمبر"],
  ["Koroneiki", "Oil", "Highest yield (44.2 kg/tree) and oil (49.9% dry weight) on reclaimed land; best yield in super-high-density planting at Ismailia (7.27–8.93 t/feddan); heat-tolerant in North Sinai; best harvest 2–16 November"], ["samra", "ali2024", "nagaty"], "H"),
 (["بيكوال", "زيت / ثنائي", "36.2 كجم/شجرة وزيت 40.4% وزن جاف في الأراضي المستصلحة؛ أفضل حصاد نحو 2 نوفمبر بشمال سيناء"],
  ["Picual", "Oil / dual", "36.2 kg/tree and 40.4% oil (dry weight) on reclaimed land; best harvest about 2 November in North Sinai"], ["samra", "nagaty"], "H"),
 (["كوراتينا", "زيت", "أعلى محصول على طريق القاهرة–الإسكندرية الصحراوي؛ من أنسب الأصناف تحت الملوحة"],
  ["Coratina", "Oil", "Highest yield on the Cairo–Alexandria desert road; among the most suitable under salinity"], ["elsayed", "assiut"], "M"),
 (["شملالي", "زيت", "أعلى نسبة زيت في شمال سيناء؛ متحمل للحرارة؛ أفضل حصاد 2 نوفمبر"],
  ["Chemlali", "Oil", "Highest oil content in North Sinai; heat-tolerant; best harvest 2 November"], ["nagaty"], "H"),
 (["منزانيللو", "مائدة / ثنائي", "ينضج قبل الأصناف الأخرى بـ15–30 يومًا؛ أفضل حصاد نحو 19 أكتوبر بشمال سيناء؛ عالي عدم التوافق الذاتي"],
  ["Manzanillo", "Table / dual", "Ripens 15–30 days before other cultivars; best harvest about 19 October in North Sinai; highly self-incompatible"], ["nagaty", "elsoda"], "H"),
 (["كالاماتا", "مائدة (أسود)", "آخر الأصناف تزهيرًا؛ عالي عدم التوافق الذاتي"],
  ["Kalamata", "Table (black)", "Latest variety to bloom; highly self-incompatible"], ["elsoda"], "H"),
 (["دولتشي", "زيت / مائدة", "أعلى نسبة أزهار كاملة مع الكوراتينا؛ متوافق ذاتيًا؛ ملقّح جيد للكالاماتا والكوراتينا والكرونايكي"],
  ["Dolce", "Oil / table", "Highest perfect-flower percentage with Coratina; self-compatible; good pollinizer for Kalamata, Coratina and Koroneiki"], ["elsoda"], "H"),
 (["أربيكوينا", "زيت", "أقل محصول للشجرة في الأراضي المستصلحة المالحة؛ احتياج برودة منخفض"],
  ["Arbequina", "Oil", "Lowest yield per tree on saline reclaimed land; low chilling requirement"], ["assiut", "chill"], "M"),
 (["تشيبرسينو، تانشي، جباع، كونسرفوليا، إيترانا", "أصناف مُدخلة حديثًا", "تفوقت في الزيت والمحصول ووزن الثمرة في شمال سيناء؛ تشيبرسينو الأعلى تجذيرًا وإيترانا الأقل"],
  ["Chiperssino, Tanche, Jabaa, Conservolia, Itrana", "Recently introduced", "Superior in oil, yield and fruit weight in North Sinai; Chiperssino roots best, Itrana worst"], ["hegazi2010"], "H"),
 (["جيزة 48، جيزة 32 (تراكيب مصرية)", "—", "جيزة 48 الأعلى تحملًا للملوحة وجيزة 32 الأكثر حساسية؛ سيراسولا قريب من جيزة 48"],
  ["Giza 48, Giza 32 (Egyptian genotypes)", "—", "Giza 48 the most salt-tolerant and Giza 32 the most sensitive; Cerasuola comparable to Giza 48"], ["giza48"], "M"),
])
h3("s3-3", "3.3 سلالات برنامج التربية المصري", "3.3 Selections from the Egyptian breeding programme")
facts([
 ("بدأ برنامج تربية الزيتون بمعهد بحوث البساتين عام 1994 بالتهجين بين أصناف محلية وأجنبية لإنتاج أصناف للمائدة أو للزيت أو ثنائية الغرض.", "The Horticulture Research Institute olive breeding programme began in 1994, crossing local and foreign cultivars to obtain table, oil or dual-purpose varieties.", ["mikhail", "osman"], "H"),
 ("من هجن كرونايكي ومنزانيللو وبيكوال وأربيكوينا مع حامض (تقييم 2011–2013): السلالات 73 و91 و100 للمائدة؛ 42 و47 و71 و89 و98 للزيت؛ 57 و59 ثنائية الغرض.", "From crosses of Koroneiki, Manzanillo, Picual and Arbequina with Hamed (evaluated 2011–2013): selections 73, 91 and 100 for table; 42, 47, 71, 89 and 98 for oil; 57 and 59 dual-purpose.", ["mikhail"], "H"),
 ("من هجن ليتشينو وكوراتينا وأربيكوينا مع تفاحي (2011–2013): السلالات 51 و62 و63 للمائدة؛ 36 و49 و109 و121 للزيت؛ 34 و35 و108 و110 و111 ثنائية الغرض.", "From crosses of Leccino, Coratina and Arbequina with Toffahi (2011–2013): selections 51, 62 and 63 for table; 36, 49, 109 and 121 for oil; 34, 35, 108, 110 and 111 dual-purpose.", ["osman"], "H"),
 ("من هجن كوراتينا × فرانتويو والعكس تحت ري بمياه 5648 جزء في المليون: G16 الأفضل لاستخلاص الزيت؛ G26 أقل زيتًا ويمكن أن يكون أصلًا متحملًا للملوحة بعد دراسة التوافق؛ G25 ثنائي الغرض بأعلى محصول.", "From Coratina × Frantoio and reciprocal crosses irrigated with 5,648 ppm water: G16 is best for oil extraction; G26 has the least oil and can serve as a salt-tolerant rootstock after compatibility studies; G25 is dual-purpose with the highest yield.", ["elhusseiny"], "H"),
 ("قابلية تجذير 11 تركيبًا وراثيًا من البرنامج: سهلة 102 و66؛ متوسطة 97 و91 و69 و32 و138؛ صعبة 92 و99 و48 و52.", "Rooting ability of 11 genotypes from the programme: easy 102 and 66; moderate 97, 91, 69, 32 and 138; difficult 92, 99, 48 and 52.", ["sawarsan"], "H"),
])
h3("s3-4", "3.4 أصناف الشرق الأوسط وشمال أفريقيا", "3.4 Varieties of the Middle East and North Africa")
table(["البلد", "الأصناف", "الخصائص"], ["Country", "Varieties", "Traits"], [
 (["سوريا", "زيتي، صوراني، خضيري، دعيبلي، قيسي، قرماني", "الخمسة الأولى نحو 90% من أشجار سوريا؛ حمض الأوليك نحو 70% في معظمها، والقرماني أقل؛ Δ-7-ستيجماستينول تجاوز 0.5% في الخضيري والدعيبلي وقارب الحد في الصوراني والإنساسي"],
  ["Syria", "Zaity, Sorani, Khodeiri, Doebli, Kaissy, Karamani", "The first five make up about 90% of Syrian trees; oleic acid about 70% in most, lower in Karamani; Δ-7-stigmastenol above 0.5% in Khodeiri and Doebli and close to the limit in Sorani and Insassy"], ["syria"], "M"),
 (["لبنان", "صوري (صوراني)، بلدي", "الصوري ثنائي الغرض، زيت 28–35% وزن طازج، الحصاد منتصف سبتمبر–أواخر أكتوبر؛ Δ-7-ستيجماستينول يتجاوز أحيانًا 0.5%"],
  ["Lebanon", "Soury (Sorani), Baladi", "Soury is dual-purpose, oil 28–35% fresh weight, harvest mid-September to late October; Δ-7-stigmastenol sometimes above 0.5%"], ["soury"], "M"),
 (["فلسطين والأردن", "نبالي بلدي، نبالي محسّن (الرصيعي)، سوري", "الأصناف السائدة في فلسطين، كلها ثنائية الغرض وتتأثر بتبادل الحمل؛ النبالي البلدي حساس للظروف الجوية أثناء التزهير؛ السوري أصله من صور بلبنان. الزيت (وزن جاف): نبالي بلدي 55.6%، نبالي محسّن 46.8%، سوري 40.3%؛ الأوليك 66.2% و56.4% و70.1%؛ الفينولات 380 و128 و217 ملجم/كجم؛ Δ-7-ستيجماستينول زائد في النبالي البلدي فقط"],
  ["Palestine and Jordan", "Nabali Baladi, Nabali Mohassan (Rasi'i), Souri", "The dominant Palestinian cultivars, all dual-purpose and affected by alternate bearing; Nabali Baladi is sensitive to adverse weather at flowering; Souri originated in Sour, Lebanon. Oil (dry weight): Nabali Baladi 55.6%, Nabali Mohassan 46.8%, Souri 40.3%; oleic 66.2%, 56.4% and 70.1%; polyphenols 380, 128 and 217 mg/kg; Δ-7-stigmastenol excessive only in Nabali Baladi"], ["palestine", "rasii"], "M"),
 (["إسرائيل", "برنيا، سوري، كادش، كادشون", "برنيا (K-18 سابقًا) أكثر الأصناف انتشارًا في البساتين المكثفة (25%)؛ تحت ري بمياه 4.5 ديسيسيمنز/م: برنيا 15 طن/هكتار وزيت 18%، سوري 10 طن/هكتار وزيت 17%؛ كادشون من التلقيح الذاتي لكادش لمقاومة عين الطاووس"],
  ["Israel", "Barnea, Souri, Kadesh, Kadeshon", "Barnea (formerly K-18) is the most widespread cultivar in intensive orchards (25%); under 4.5 dS/m irrigation: Barnea 15 t/ha and 18% oil, Souri 10 t/ha and 17% oil; Kadeshon from self-pollination of Kadesh, selected for peacock-spot resistance"], ["barneaioc", "halutza", "barnea", "kadesh"], "M"),
 (["تركيا", "جيملك، ممجك، أيفاليك، أوسلو، دومات، كيليس يغليك، نيزيب يغليك", "ممجك نحو 19% من أشجار تركيا؛ أيفاليك نحو 25% من مساحة الزيتون (2012)"],
  ["Turkey", "Gemlik, Memecik, Ayvalık, Uslu, Domat, Kilis Yağlık, Nizip Yağlık", "Memecik about 19% of Turkish trees; Ayvalık about 25% of olive acreage (2012)"], ["memecik", "turkey"], "M"),
 (["تونس", "شملالي، شتوي، زلماطي", "الشملالي (الوسط) والزلماطي (الجنوب) الرئيسيان؛ الشملالي أكثر تحملًا للعجز المائي من الشتوي"],
  ["Tunisia", "Chemlali, Chetoui, Zalmati", "Chemlali (centre) and Zalmati (south) are the main cultivars; Chemlali tolerates water stress better than Chetoui"], ["chemlali", "tunisia"], "M"),
 (["المغرب", "بيشولين مغربي، حوزية، منارة", "البيشولين المغربي نحو 90% من الأشجار؛ الحوزية والمنارة انتخابان نسيليان منه؛ المنارة عالية الإنتاج جيدة التجذير"],
  ["Morocco", "Picholine marocaine, Haouzia, Menara", "Picholine marocaine about 90% of trees; Haouzia and Menara are clonal selections from it; Menara is high-yielding with good rooting"], ["morocco", "menara"], "M"),
 (["إيران", "زرد، روغني، ماري", "زرد أكثر الأصناف انتشارًا في إيران"],
  ["Iran", "Zard, Rowghani, Mari", "Zard is the most widespread cultivar in Iran"], ["iran"], "M"),
 (["العراق", "الخستاوي، الأشرسي، الدهكان", "الأصناف المحلية؛ الموصل وأربيل والسليمانية وكركوك عالية الملاءمة مناخيًا، والرطبة متوسطة، والبصرة والناصرية والعمارة وبغداد والديوانية والحي غير ملائمة"],
  ["Iraq", "Khastawi, Ashrasi, Dahkan", "Local varieties; Mosul, Erbil, Sulaymaniyah and Kirkuk are highly suitable climatically, Al-Rutba moderate, and Basra, Nasiriyah, Amarah, Baghdad, Diwaniyah and Al-Hay unsuitable"], ["iraq"], "M"),
 (["السعودية", "بيكوال، منزانيللو وأصناف مستوردة", "البيكوال في الجوف وتبوك وحائل بزيت 15–22%، يتحمل الملوحة والصقيع وحساس للذبول الفيرتيسيليومي؛ المنزانيللو منتشر في الجوف"],
  ["Saudi Arabia", "Picual, Manzanillo and imported varieties", "Picual in al-Jawf, Tabuk and Hail with 15–22% oil, tolerant of salinity and frost but susceptible to Verticillium wilt; Manzanillo widespread in al-Jawf"], ["saudi"], "L"),
])
h3("s3-5", "3.5 التلقيح والملقّحات", "3.5 Pollination and pollinizers")
facts([
 ("في تجربة على طريق القاهرة–الإسكندرية (8 أصناف، 2014–2015): العجيزي والدولتشي والمراقي والكرونايكي متوافقة ذاتيًا؛ البيكوال والكوراتينا جزئيًا؛ الكالاماتا والمنزانيللو عالية عدم التوافق. التلقيح الخلطي أعطى أفضل عقد ووزن ثمرة ونسبة زيت في معظم الأصناف.", "In a Cairo–Alexandria road trial (8 cultivars, 2014–2015): Aggezi, Dolce, Maraki and Koroneiki were self-compatible; Picual and Coratina partially self-incompatible; Kalamata and Manzanillo highly self-incompatible. Cross-pollination gave the best fruit set, fruit weight and oil content in most cultivars.", ["elsoda"], "H"),
 ("الملقّحات الموصى بها: المراقي والعجيزي لبعضهما؛ الكرونايكي للدولتشي والمنزانيللو والبيكوال؛ الدولتشي للكالاماتا والكوراتينا والكرونايكي.", "Recommended pollinizers: Maraki and Aggezi for each other; Koroneiki for Dolce, Manzanillo and Picual; Dolce for Kalamata, Coratina and Koroneiki.", ["elsoda"], "H"),
 ("العجيزي أبكر الأصناف تزهيرًا والكالاماتا آخرها؛ مدة التزهير 15–20 يومًا (2014) و14–18 يومًا (2015) مع تداخل بين الأصناف.", "Aggezi blooms earliest and Kalamata latest; bloom lasted 15–20 days (2014) and 14–18 days (2015) with overlap between cultivars.", ["elsoda"], "H"),
 ("كتالوج المجلس الدولي يصف العجيزي الشامي بأنه غير متوافق ذاتيًا مع نسبة إجهاض متاع عالية ومشاكل توافق مع بعض الملقّحات.", "The IOC catalogue describes Aggezi Shami as self-incompatible with a high pistil-abortion rate and compatibility problems with some pollinizers.", ["iocaggezi"], "M"),
 ("وجدت دراسة 2014 أن كل التراكيب المدروسة (سيوي، المراقي، E52، كوراتينا، كرونايكي) غير متوافقة ذاتيًا، وأن الكوراتينا أعطى أعلى محصول تحت التلقيح المفتوح.", "A 2014 study found all genotypes studied (Sewia, Maraki, E52, Coratina, Koroneiki) self-incompatible, with Coratina giving the highest yield under open pollination.", ["elsayed"], "M"),
])
h3("s3-6", "3.6 صفات تهم الإنتاج العضوي", "3.6 Traits that matter for organic production")
facts([
 ("نسبة الدراسات التي وصفت الصنف بأنه منخفض القابلية لعين الطاووس: كرونايكي 100% (5 دراسات)، ليتشينو 90%، حوزية 50%، أربوسانا 50%، كوراتينا 36%، كالاماتا 33%، فرانتويو 12%، أربيكوينا 5%.", "Share of studies reporting low susceptibility to peacock spot: Koroneiki 100% (5 studies), Leccino 90%, Haouzia 50%, Arbosana 50%, Coratina 36%, Kalamata 33%, Frantoio 12%, Arbequina 5%.", ["buonaurio"], "H"),
 ("الذبول الفيرتيسيليومي: الفرانتويو أكثر الأصناف مقاومة والبيكوال أكثرها حساسية والأربيكوينا وسط.", "Verticillium wilt: Frantoio is the most resistant cultivar, Picual the most susceptible and Arbequina intermediate.", ["vwcult"], "M"),
 ("الأصناف المبكرة مثل الأربيكوينا والكرونايكي احتياجها للبرودة أقل، بينما يحتاج البيكوال برودة أكثر.", "Early cultivars such as Arbequina and Koroneiki have lower chilling requirements, while Picual needs more chilling.", ["chill"], "M"),
 ("العجيزي الشامي حساس لذبابة الزيتون، والتفاحي متوسط الحساسية لها.", "Aggezi Shami is susceptible to olive fly, and Toffahi moderately susceptible.", ["iocaggezi", "ioc2012"], "H"),
])

# ============ 4
h2("s4", "4. بيئة الإنتاج في مصر", "4. Production Environment in Egypt")
h3("s4-1", "4.1 القطاع والمساحة", "4.1 Sector and area")
facts([
 ("مصر بلد زيتون مائدة: نحو 80% من الإنتاج للمائدة. زادت المساحة من نحو 3700 هكتار (1980) إلى 65303 هكتار (2009) منها 56330 هكتارًا مثمرة.", "Egypt is a table-olive country: about 80% of output is table olives. Area grew from about 3,700 ha (1980) to 65,303 ha (2009), of which 56,330 ha were bearing.", ["ioc2012"], "H"),
 ("ميزان المجلس الدولي للزيتون 2023/24: إنتاج زيتون المائدة في مصر نحو 750 ألف طن، والاستهلاك 560 ألف طن، والتصدير 181 ألف طن.", "IOC balance 2023/24: Egyptian table-olive production about 750,000 t, consumption 560,000 t, exports 181,000 t.", ["iocbal"], "M"),
 ("وزارة الزراعة: 1.13 مليون طن من 269 ألف فدان في 2021/22، وتراجعت الإنتاجية من 5.03 إلى 4.19 طن/فدان (2018–2022) مع موجات الحر.", "Ministry of Agriculture: 1.13 million t from 269,000 feddan in 2021/22, with productivity falling from 5.03 to 4.19 t/feddan (2018–2022) alongside heat waves.", ["nagaty"], "H"),
 ("في 2009: 445 هكتارًا عضوية للزيت و890 هكتارًا للمائدة؛ إنتاجية المائدة العضوية 7.3 طن/هكتار مقابل 10.2 للتقليدية؛ سعر المائدة الخضراء العضوية 0.54 يورو/كجم مقابل 0.49.", "In 2009: 445 ha organic for oil and 890 ha for table olives; organic table yield 7.3 t/ha against 10.2 conventional; organic green table olives €0.54/kg against €0.49.", ["ioc2012"], "H"),
 ("الكثافة: 70–100 شجرة/هكتار في البساتين المطرية و333–400 شجرة/هكتار في المروية.", "Density: 70–100 trees/ha in rainfed orchards and 333–400 trees/ha in irrigated orchards.", ["ioc2012"], "H"),
 ("وقّعت مصر والفاو في 10 سبتمبر 2026 إطارًا لتطوير سلسلة قيمة الزيتون.", "Egypt and FAO signed a framework on 10 September 2026 to develop the olive value chain.", ["faomou"], "M"),
])
h3("s4-2", "4.2 المناطق والمناخ والمياه", "4.2 Zones, climate and water")
facts([
 ("الساحل الشمالي الغربي بين الإسكندرية والسلوم (شريط 20–30 كم): مناخ جاف بشتاء معتدل؛ متوسط أبرد الشهور 7–18 °م؛ مطر 100–150 مم خلال 3–4 أسابيع في الخريف والشتاء؛ رياح شمالية غربية قوية.", "North-west coast between Alexandria and Sollum (20–30 km band): arid with mild winters; coldest-month mean 7–18 °C; 100–150 mm of rain over 3–4 weeks in autumn and winter; strong north-westerly winds.", ["ioc2012"], "H"),
 ("زُرعت بساتين مكثفة في سيناء وبين الإسكندرية والقاهرة على أراضٍ صحراوية، مع ري بمياه جوفية تصل ملوحتها إلى 11.7 ديسيسيمنز/م.", "Intensive orchards were planted in Sinai and between Alexandria and Cairo on desert land, irrigated with aquifer water of up to 11.7 dS/m.", ["ioc2012"], "H"),
 ("شمال سيناء (العريش): تربة رملية طميية، مياه بئر ملوحتها 6.6 ديسيسيمنز/م؛ موجات حر بلغت 40.4 °م (2021) و43.9 °م (2022) خلال تراكم الزيت.", "North Sinai (Arish): sandy loam, well water of 6.6 dS/m; heat waves reached 40.4 °C (2021) and 43.9 °C (2022) during oil accumulation.", ["nagaty"], "H"),
 ("سيوة: ارتفاع ملوحة مياه الري خفّض المحصول ونسبة الزيت وحجم الثمرة في الصنفين المدروسين.", "Siwa: higher irrigation-water salinity lowered yield, oil content and fruit size in both cultivars studied.", ["siwa"], "M"),
 ("تصنّف الفاو الزيتون متوسط التحمل للملوحة بحد ملوحة لمستخلص التربة 3–6 ديسيسيمنز/م؛ وفي الحقل كان الحد 4 ديسيسيمنز/م مع انخفاض 12% لكل وحدة زيادة.", "FAO classes olive as moderately salt-tolerant with a soil-extract threshold of 3–6 dS/m; in the field the threshold was 4 dS/m with a 12% decline per unit above it.", ["aragues"], "M"),
 ("عندما يتجاوز متوسط الحرارة 25 °م أو تتجاوز موجات الحر 40 °م عدة أيام خلال تراكم الزيت، يتضرر وزن الثمرة وكمية الزيت وجودته؛ ويمكن تفادي ذلك بالحصاد المبكر عند مؤشر نضج أقل.", "When mean temperature exceeds 25 °C or heat waves above 40 °C last several days during oil accumulation, fruit weight and oil quantity and quality suffer; this can be avoided by harvesting earlier at a lower maturity index.", ["nagaty"], "H"),
])
h3("s4-3", "4.3 الآفات والأمراض الرئيسية المسجلة في مصر", "4.3 Main pests and diseases recorded in Egypt")
facts([
 ("ذبابة ثمار الزيتون هي الآفة الرئيسية في بساتين الزيتون بمصر؛ قد تصل الإصابة إلى 99% والخسارة إلى 30% أو أكثر.", "Olive fruit fly is the key pest of olive orchards in Egypt; infestation can reach 99% and losses 30% or more.", ["alikaolin"], "H"),
 ("الذبول الفيرتيسيليومي أخطر أمراض الزيتون في مصر، وعُزل من مطروح (سيوة، براني، الضبعة) والإسكندرية والمنوفية والفيوم والإسماعيلية وشمال سيناء.", "Verticillium wilt is the most serious olive disease in Egypt, isolated from Matrouh (Siwa, Barrani, El-Dabaa), Alexandria, Menoufia, Fayoum, Ismailia and North Sinai.", ["mousa"], "H"),
 ("آفات أخرى مسجلة: فراشة الزيتون، دودة الياسمين، بسيلا الزيتون، الحشرة القشرية السوداء، قشرية الزيتون، حفار ساق التفاح، حلم براعم الزيتون، نيماتودا تعقد الجذور؛ وأمراض: عين الطاووس، السل البكتيري، أعفان الجذور (القسم 10).", "Other recorded problems: olive moth, jasmine moth, olive psyllid, black scale, olive scale, leopard moth, olive bud mite, root-knot nematode; and diseases: peacock spot, olive knot, root rot (Section 10).", ["hegazi2011", "psyllid", "scales", "zeuzera", "mites", "hammad", "buonaurio", "knot", "elmorsi"], "H"),
])

# ============ 5
h2("s5", "5. الإطار التنظيمي للزراعة العضوية", "5. Organic Regulatory Framework")
h3("s5-1", "5.1 القانون المصري رقم 12 لسنة 2020", "5.1 Egyptian Law No. 12 of 2020")
facts([
 ("يتكون القانون من 20 مادة. تختص الإدارة العامة للزراعة العضوية بالإنتاج الأولي حتى الحصاد، والهيئة القومية لسلامة الغذاء بمرحلة ما بعد الحصاد (المادة 3).", "The law has 20 articles. The General Administration of Organic Agriculture oversees primary production up to harvest; the National Food Safety Authority oversees the post-harvest stage (Art. 3).", ["law12"], "H"),
 ("تسجّل جهة المطابقة لدى الجهتين وتضع رقم تسجيلها على كل شهادة (المادة 4).", "Every conformity body must register with both authorities and print its registration number on every certificate (Art. 4).", ["law12"], "H"),
 ("شعار عضوي وطني برقم كودي إلزامي على المنتجات المحلية، وشعار خاص للمدخلات المحلية المسموح بها (المواد 5–7).", "A national organic logo with a code number is mandatory on products for the local market, with a separate logo for permitted local inputs (Arts. 5–7).", ["law12"], "H"),
 ("يلزم كل مُصدّر بشهادة تثبت تسجيله لدى جهة مطابقة مرخصة، وهي من مستندات التصدير (المادة 8).", "Every exporter needs a certificate proving registration with a licensed conformity body; it is part of the export file (Art. 8).", ["law12"], "H"),
 ("يحتفظ المنتج والتاجر بسجلات الإنتاج العضوي والمبيعات ويخطران جهة المطابقة ببرنامج النشاط (المادة 12).", "Producers and traders keep organic production and sales records and notify the conformity body of their activity programme (Art. 12).", ["law12"], "H"),
 ("تحدد اللائحة التنفيذية المعايير وقوائم الإنتاج العضوي والتسجيل والرقابة، وضوابط عناصر المكافحة الحيوية (المادة 13).", "The executive regulations set the standards, organic production lists, registration and control, and rules for biological-control agents (Art. 13).", ["law12"], "H"),
])
h3("s5-2", "5.2 فترة التحول وقواعد الإنتاج (الاتحاد الأوروبي ودستور الأغذية)", "5.2 Conversion period and production rules (EU and Codex)")
facts([
 ("المحاصيل المعمّرة تحتاج فترة تحول لا تقل عن 3 سنوات قبل أول حصاد عضوي، وتبدأ فقط بعد وضع المزرعة تحت نظام التفتيش.", "Perennial crops need a conversion period of at least 3 years before the first organic harvest, starting only once the farm is placed under inspection.", ["eu848", "codex"], "H"),
 ("يجيز دستور الأغذية للجهة المختصة تعديل الفترة حسب تاريخ الأرض على ألا تقل عن 12 شهرًا.", "Codex allows the authority to vary the period according to the land's history, but never below 12 months.", ["codex"], "H"),
 ("يمكن بيع منتج نباتي وحيد المكوّن بوصف «في مرحلة التحول» إذا حُصد بعد 12 شهرًا على الأقل من بدء التحول.", "A single-ingredient plant product may be sold as 'in-conversion' if harvested at least 12 months after conversion began.", ["eu848"], "H"),
 ("يجب استخدام مادة إكثار عضوية؛ وفي الدول الثالثة يجوز لجهة الرقابة الإذن بمادة غير عضوية قبل الزراعة إذا لم تتوفر العضوية.", "Organic planting material must be used; in third countries the control body may authorise non-organic material before planting when organic material is unavailable.", ["eu848"], "H"),
 ("الإنتاج الموازي لنفس الصنف مسموح للمعمّرات فقط ضمن خطة تحول تكتمل خلال 5 سنوات، مع إخطار بالحصاد قبل 48 ساعة.", "Parallel production of the same variety is allowed for perennials only within a conversion plan completed in 5 years, with harvest notified 48 h in advance.", ["eu848"], "H"),
 ("يُحظر السماد النيتروجيني المعدني؛ وسماد الماشية محدود بـ170 كجم نيتروجين/هكتار/سنة ويُمنع إن كان من مزارع صناعية.", "Mineral nitrogen fertiliser is banned; livestock manure is capped at 170 kg N/ha/yr and not allowed from factory farming.", ["eu848", "eu1165", "codex"], "H"),
 ("الوقاية أولًا: الأعداء الطبيعيون، اختيار الصنف، الطرق الميكانيكية، التشميس. المنتجات المسموح بها تُستخدم عند الضرورة فقط مع سجلات تثبت الحاجة.", "Prevention first: natural enemies, variety choice, mechanical methods, solarisation. Permitted products are used only when necessary, with records proving the need.", ["eu848"], "H"),
 ("يحتفظ المزارع بسجلات القطع وكمية الحصاد.", "Farmers keep records of parcels and harvest quantities.", ["eu848"], "H"),
 ("المنتج المصنّع يوصف عضويًا إذا كانت 95% على الأقل من مكوّناته الزراعية عضوية.", "A processed product may be labelled organic only if at least 95% of its agricultural ingredients are organic.", ["eu848", "codex"], "H"),
])
h3("s5-3", "5.3 المدخلات المسموح بها لبستان الزيتون", "5.3 Permitted inputs for an olive grove")
table(["الفئة", "المدخلات المسموح بها", "الشروط"], ["Category", "Permitted inputs", "Conditions"], [
 (["وقاية النبات", "الكاولين؛ السبينوساد؛ الكائنات الدقيقة المعتمدة (ومنها Bt)؛ الأزاديراختين (النيم)؛ البيرثرينات؛ الزيوت البارافينية؛ الكبريت؛ بيكربونات البوتاسيوم والصوديوم؛ الأحماض الدهنية؛ الفيرومونات؛ التربة الدياتومية؛ مواد أساسية مثل الخل والكيتوزان", "الفيرومونات في المصائد والموزعات فقط"], ["Plant protection", "Kaolin; spinosad; approved micro-organisms (including Bt); azadirachtin (neem); pyrethrins; paraffin oils; sulphur; potassium and sodium hydrogen carbonate; fatty acids; pheromones; diatomaceous earth; basic substances such as vinegar and chitosan", "Pheromones only in traps and dispensers"], ["eu1165"], "H"),
 (["النحاس", "هيدروكسيد، أوكسي كلوريد، أكسيد النحاس، مزيج بوردو، كبريتات النحاس الثلاثية", "حد أقصى 28 كجم نحاس/هكتار خلال 7 سنوات"], ["Copper", "Copper hydroxide, oxychloride, oxide, Bordeaux mixture, tribasic copper sulphate", "Maximum 28 kg Cu/ha over 7 years"], ["eu1165"], "H"),
 (["مبيدات داخل المصائد", "دلتامثرين، لامبدا سيهالوثرين", "فقط داخل مصائد بجاذب خاص ضد ذبابة الزيتون وذبابة الفاكهة"], ["Insecticides in traps", "Deltamethrin, lambda-cyhalothrin", "Only inside traps with specific attractants against olive fly and medfly"], ["eu1165"], "H"),
 (["الأسمدة ومحسنات التربة", "سماد المزرعة والكمبوست، كمبوست المخلفات النباتية، الفيرمي كمبوست، صخر الفوسفات الطري، كبريتات البوتاسيوم الطبيعية، الجبس، كربونات الكالسيوم والمغنيسيوم الطبيعية، الليوناردايت والأحماض الدبالية، مسحوق الصخور، مستحضرات الكائنات الدقيقة", "منع مصدر المزارع الصناعية؛ حدود للمعادن الثقيلة في الكمبوست؛ الأحماض الدبالية بشروط الاستخلاص"], ["Fertilisers and soil conditioners", "Farmyard manure and compost, plant-waste compost, vermicompost, soft ground rock phosphate, natural potassium sulphate, gypsum, natural calcium and magnesium carbonate, leonardite and humic acids, stone meal, micro-organism preparations", "No factory-farm origin; heavy-metal limits for compost; humic acids under extraction conditions"], ["eu1165"], "H"),
 (["التصنيع", "أحماض اللاكتيك والستريك والطرطريك والماليك والأسكوربيك؛ سترات الكالسيوم", "لا تُسمح الصودا الكاوية للزيتون، ولا البنزوات أو السوربات أو جلوكونات الحديدوز"], ["Processing", "Lactic, citric, tartaric, malic and ascorbic acids; calcium citrates", "No sodium hydroxide for olives; no benzoate, sorbate or ferrous gluconate"], ["eu1165", "codex"], "H"),
])
note("قائمة المدخلات المصرية وفق القانون 12/2020 لم تُتح؛ يجب التأكد من تسجيل كل مدخل لدى لجنة مبيدات الآفات الزراعية وموافقة جهة الاعتماد قبل استخدامه (القسم 13).",
     "The Egyptian input list under Law 12/2020 was not available; each input must be confirmed as registered with the Agricultural Pesticide Committee and accepted by the certifier before use (Section 13).")

# ============ 6
h2("s6", "6. منهجية التشغيل: مراحل الموسم وأطواره", "6. Operating Methodology: Phases and Stages of the Season")
h3("s6-1", "6.1 الاحتياجات الحرارية وأطوار النمو", "6.1 Thermal needs and growth stages")
table(["الطور", "الحرارة المطلوبة"], ["Stage", "Temperature needed"], [
 (["من استئناف النمو حتى البراعم الزهرية", "10 °م"], ["Growth resumption to flower buds", "10 °C"], ["ecolive"], "M"),
 (["من البراعم الزهرية حتى التزهير", "15 °م"], ["Flower buds to flowering", "15 °C"], ["ecolive"], "M"),
 (["من التزهير حتى العقد", "18 °م"], ["Flowering to fruit set", "18 °C"], ["ecolive"], "M"),
 (["من العقد حتى التلوّن", "20 °م"], ["Fruit set to veraison", "20 °C"], ["ecolive"], "M"),
 (["من التلوّن حتى النضج", "15 °م"], ["Veraison to ripening", "15 °C"], ["ecolive"], "M"),
 (["من النضج حتى السكون الشتوي", "5 °م"], ["Ripening to winter rest", "5 °C"], ["ecolive"], "M"),
])
facts([
 ("يحتاج الزيتون فترة خالية من الصقيع لا تقل عن 150 يومًا لإكمال أطوار نموه.", "Olive needs a frost-free period of at least 150 days to complete its growth stages.", ["iraq"], "M"),
 ("في فلسطين (مناخ متوسطي شبه ساحلي، 2010): بدء النمو الخضري أوائل فبراير؛ التزهير الكامل أواخر أبريل–أوائل مايو؛ تصلّب النواة منتصف يونيو–أوائل يوليو؛ بدء التلوّن منتصف أكتوبر (سوري) حتى أوائل نوفمبر (نبالي محسّن).", "In Palestine (semi-coastal Mediterranean climate, 2010): vegetative growth started in early February; full bloom late April–early May; pit hardening mid-June–early July; colour change from mid-October (Souri) to early November (Nabali Mohassan).", ["palestine"], "M"),
 ("الفترات الحرجة للماء: من تمايز البراعم حتى التزهير والعقد، والطور الأول لنمو الثمرة، والطور الثاني لنمو الثمرة. تصلّب النواة أكثر الأطوار تحملًا للعجز المائي. المطر أثناء التزهير قد يقلل العقد.", "Water-critical periods: bud differentiation to flowering and fruit set, the first phase of fruit growth, and the second phase of fruit growth. Pit hardening is the most deficit-tolerant stage. Rain at flowering can reduce fruit set.", ["ecolive"], "M"),
 ("تبدأ قابلية الثمرة للإصابة بذبابة الزيتون عند تصلّب النواة (يوليو أو قبله حسب المناخ).", "Fruit becomes susceptible to olive fly at pit hardening (July or earlier depending on climate).", ["ecolive"], "M"),
 ("يبدأ تراكم الزيت في أواخر الصيف ويزداد من منتصف سبتمبر إلى منتصف أكتوبر ثم يتباطأ في المراحل الأخيرة؛ وفي شمال سيناء تمتد فترة تراكم الزيت من أغسطس إلى أواخر أكتوبر.", "Oil accumulation starts in late summer, increases from mid-September to mid-October and slows in the final stages; in North Sinai the oil-accumulation period runs from August to late October.", ["nagaty"], "H"),
 ("يتلوّن المنزانيللو ويصل للنضج قبل البيكوال والكرونايكي والشملالي بنحو 15–30 يومًا لأنه يزهر ويعقد قبلها بنحو أسبوعين.", "Manzanillo colours and matures about 15–30 days before Picual, Koroneiki and Chemlali because it flowers and sets fruit about two weeks earlier.", ["nagaty"], "H"),
 ("الحصاد الأمثل يكون بعد التزهير الكامل بنحو 166–170 يومًا للمنزانيللو، وبعد 213–217 يومًا للأربيكوينا و216–224 يومًا للكرونايكي (طريق القاهرة–الإسكندرية).", "Optimum harvest came about 166–170 days after full bloom for Manzanillo, 213–217 days for Arbequina and 216–224 days for Koroneiki (Cairo–Alexandria road).", ["harvestdays"], "M"),
])
h3("s6-2", "6.2 الفروق التشغيلية بين أنواع الزيتون الثلاثة", "6.2 Operating differences between the three olive types")
table(["البند", "زيتون الزيت", "زيتون المائدة الأخضر", "زيتون المائدة الأسود"], ["Item", "Oil olives", "Green table olives", "Black table olives"], [
 (["مرحلة الجني", "حسب مؤشر النضج والزيت والفينولات", "قبل التلوّن بعد بلوغ الحجم الطبيعي", "عند النضج الكامل أو قبله بقليل"], ["Picking stage", "By maturity index, oil and phenols", "Before colour change, at normal size", "Fully ripe or slightly before"], ["nagaty", "iocot"], "H"),
 (["أفضل موعد مسجل في مصر", "بيكوال وشملالي 2 نوفمبر؛ كرونايكي 2–16 نوفمبر", "غير مذكور بالأسبوع؛ التفاحي مبكر الحصاد", "منزانيللو: مؤشر نضج 4.3–4.9 عند 19 أكتوبر"], ["Best recorded date in Egypt", "Picual and Chemlali 2 November; Koroneiki 2–16 November", "Not given by week; Toffahi is early", "Manzanillo: maturity index 4.3–4.9 at 19 October"], ["nagaty", "toffahi"], "H"),
 (["التصنيع العضوي", "عصر سريع بعد الجني", "تخمير طبيعي في محلول ملحي (بدون صودا كاوية)", "تخمير طبيعي في محلول ملحي (بدون صودا كاوية وبدون أكسدة بجلوكونات الحديدوز)"], ["Organic processing", "Quick milling after picking", "Natural brine fermentation (no lye)", "Natural brine fermentation (no lye, no ferrous-gluconate oxidation)"], ["eu1165", "iocot", "ecolive"], "H"),
 (["ذبابة الزيتون", "الإصابة ترفع الحموضة وتخفض جودة الزيت", "الثمار المصابة تُخفّض الفئة التجارية", "فترة تعرض أطول على الشجرة"], ["Olive fly", "Infestation raises acidity and lowers oil quality", "Damaged fruit lowers the trade category", "Longer exposure on the tree"], ["ecolive", "iocot"], "M"),
])
h3("s6-3", "6.3 المراحل التشغيلية المعتمدة في الخطط", "6.3 Operating phases used in the plans")
p("تنظَّم السنة في تسع مراحل تشغيلية تتبع الأطوار السابقة: (1) السكون والتقليم الشتوي؛ (2) تفتح البراعم والنمو الزهري؛ (3) التزهير؛ (4) العقد والنمو الأول للثمرة؛ (5) تصلّب النواة؛ (6) نمو الثمرة وتراكم الزيت؛ (7) النضج ومتابعة الحصاد؛ (8) الحصاد؛ (9) ما بعد الحصاد. تُربط أسابيع الخطط بهذه المراحل حسب التوقيت الشهري في المصادر، لذلك تحمل أرقام الأسابيع درجة ثقة منخفضة ما لم يذكر المصدر التاريخ نفسه. تختلف المراحل 6–9 بين الأنواع الثلاثة.",
  "The year is organised into nine operating phases that follow the stages above: (1) Rest and winter pruning; (2) Bud break and inflorescence growth; (3) Flowering; (4) Fruit set and first fruit growth; (5) Pit hardening; (6) Fruit growth and oil accumulation; (7) Maturation and harvest monitoring; (8) Harvest; (9) Post-harvest. Plan weeks are assigned to these phases from the monthly timing in the sources, so week numbers carry Low confidence unless the source gives the date itself. Phases 6–9 differ between the three types.")
