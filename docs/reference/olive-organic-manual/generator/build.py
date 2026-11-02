"""Build the bilingual Organic Olive Manual.

Usage: python3 build.py OUTPUT.html
Reference numbers are assigned in order of first citation (Arabic and English share them).
"""
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sources import SOURCES  # noqa: E402
import text2  # noqa: E402,F401  (imports sections 7-13 into text1.B)
from text1 import B  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EDITION = "1.1"
DATE = {"ar": "نوفمبر 2026", "en": "November 2026"}

CSS = open(os.path.join(HERE, "style.css"), encoding="utf-8").read()
CSS = (CSS.replace("--palm:#2A6440", "--palm:#4F6B22").replace("--palm-soft:#E3EEE4", "--palm-soft:#E8EEDB")
          .replace("--date:#8A5526", "--date:#8A6A0E").replace("--date-soft:#F3E7D8", "--date-soft:#F5EDD3")
          .replace("--palm:#7DC393", "--palm:#A9C46E").replace("--palm-soft:#1F3226", "--palm-soft:#27311A")
          .replace("--date:#E0A868", "--date:#D9B54A").replace("--date-soft:#33271B", "--date-soft:#332B14"))
CSS += ("@media (max-width:640px){table.weeks{min-width:0}table.weeks thead{display:none}"
        "table.weeks,table.weeks tbody,table.weeks tr,table.weeks td{display:block;width:auto!important;min-width:0!important}"
        "table.weeks tr{border-bottom:2px solid var(--line);padding:8px 0}table.weeks td.wk,table.weeks td.dt{display:inline-block;padding-bottom:0}"
        "table.weeks tr[hidden]{display:none}}")
JS = open(os.path.join(HERE, "script.js"), encoding="utf-8").read().replace("medjool-lang", "olive-lang")

# ---- reference numbering by first citation
ORDER = []
def _note(keys):
    for k in keys:
        if k not in SOURCES:
            raise KeyError(f"unknown source key: {k}")
        if k not in ORDER:
            ORDER.append(k)
for b in B:
    if b[0] == "facts":
        for r in b[1]: _note(r[2])
    elif b[0] == "table":
        for r in b[3]: _note(r[2])
    elif b[0] == "timeline":
        for it in b[1]:
            for t in it[4]: _note(t[2])
    elif b[0] == "weeks":
        for w in b[3]:
            for t in w[4]: _note(t[2])
NUM = {k: i + 1 for i, k in enumerate(ORDER)}

e = lambda s: html.escape(s, quote=True)
L = {
 "ar": dict(conf={"H": "عالية", "M": "متوسطة", "L": "منخفضة"}, no="م", info="المعلومة", src="المصدر", cf="درجة الثقة",
            toc="جدول المحتويات", task="المهمة", how="عدد مرات التنفيذ:", source="المصدر",
            freq={"S": "مذكور في المصدر", "D": "حدده المعدّ من توقيت المصدر", "N": "غير مذكور في المصادر"},
            week="الأسبوع", dates="التواريخ التقريبية", phase="المرحلة", tasks="المهام (مع المصدر ودرجة الثقة)",
            allph="كل المراحل", filt="تصفية حسب المرحلة", refs_h="14. المراجع العلمية (مع الروابط التشعبية)", none="—"),
 "en": dict(conf={"H": "High", "M": "Medium", "L": "Low"}, no="No.", info="Information", src="Source", cf="Confidence",
            toc="Table of Contents", task="Task", how="How often:", source="Source",
            freq={"S": "stated in source", "D": "set by compiler from source timing", "N": "not given in sources"},
            week="Week", dates="Approx. dates", phase="Phase / stage", tasks="Tasks (with source and confidence)",
            allph="All phases", filt="Filter by phase", refs_h="14. Scientific References (with hyperlinks)", none="—"),
}

def badge(lang, c):
    return f'<span class="conf conf-{c}">{L[lang]["conf"][c]}</span>'

def cites(lang, keys):
    if not keys:
        return L[lang]["none"]
    return " ".join(f'<a class="cite" href="{e(SOURCES[k][1])}" target="_blank" rel="noopener" title="{e(SOURCES[k][0])}">[{NUM[k]}]</a>' for k in keys)

def task_li(lang, j, ar, en, refs, c, ft, far, fen):
    T = L[lang]
    return (f'<li><b class="tk">{T["task"]} {j}:</b> {e(ar if lang == "ar" else en)} '
            f'<span class="meta">{T["source"]} {cites(lang, refs)} · {badge(lang, c)}</span>'
            f'<span class="freq freq-{ft}"><b>{T["how"]}</b> {e(far if lang == "ar" else fen)} <i>({T["freq"][ft]})</i></span></li>')

def render(lang):
    T = L[lang]; idx = 0 if lang == "ar" else 1
    toc, body, open_sec = [], [], False
    for b in B:
        k = b[0]
        if k == "h2":
            if open_sec: body.append("</section>")
            body.append(f'<section><h2 id="{lang}-{b[1]}">{e(b[2 + idx])}</h2>'); open_sec = True
            toc.append(f'<li class="l1"><a href="#{lang}-{b[1]}">{e(b[2 + idx])}</a></li>')
        elif k == "h3":
            body.append(f'<h3 id="{lang}-{b[1]}">{e(b[2 + idx])}</h3>')
            toc.append(f'<li class="l2"><a href="#{lang}-{b[1]}">{e(b[2 + idx])}</a></li>')
        elif k == "p":
            body.append(f"<p>{e(b[1 + idx])}</p>")
        elif k == "note":
            body.append(f'<p class="note">{e(b[1 + idx])}</p>')
        elif k == "facts":
            rows = "".join(f'<tr><td class="n">{i}</td><td>{e(r[idx])}</td><td class="c">{cites(lang, r[2])}</td><td class="c">{badge(lang, r[3])}</td></tr>'
                           for i, r in enumerate(b[1], 1))
            body.append(f'<div class="tw"><table class="facts"><thead><tr><th class="n">{T["no"]}</th><th>{T["info"]}</th><th>{T["src"]}</th><th>{T["cf"]}</th></tr></thead><tbody>{rows}</tbody></table></div>')
        elif k == "table":
            hdr, rows = b[1 + idx], b[3]
            has_src = any(r[2] for r in rows)
            th = "".join(f"<th>{e(h)}</th>" for h in hdr) + (f'<th>{T["src"]}</th><th>{T["cf"]}</th>' if has_src else "")
            trs = []
            for car, cen, refs, c in rows:
                cells = "".join(f'<td class="c">{badge(lang, v[1])}</td>' if v.startswith("@") and len(v) == 2 else f"<td>{e(v)}</td>"
                                for v in (car if lang == "ar" else cen))
                if has_src:
                    cells += f'<td class="c">{cites(lang, refs)}</td><td class="c">{badge(lang, c) if c else T["none"]}</td>'
                trs.append(f"<tr>{cells}</tr>")
            body.append(f'<div class="tw"><table class="grid"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>')
        elif k == "timeline":
            lis = []
            for when_ar, when_en, ph_ar, ph_en, tasks in b[1]:
                items = "".join(task_li(lang, j, *t) for j, t in enumerate(tasks, 1))
                lis.append(f'<li><div class="when"><span class="w">{e(when_ar if lang == "ar" else when_en)}</span><span class="ph">{e(ph_ar if lang == "ar" else ph_en)}</span></div><ul class="tasks">{items}</ul></li>')
            body.append(f'<ol class="timeline">{"".join(lis)}</ol>')
        elif k == "weeks":
            _, t, names, weeks = b
            btns = f'<button type="button" class="pf on" data-p="all">{T["allph"]}</button>' + "".join(
                f'<button type="button" class="pf" data-p="{i}">{e(n[idx])}</button>' for i, n in enumerate(names))
            rows = []
            for w, ar_d, en_d, ph, tasks in weeks:
                items = "".join(task_li(lang, j, *tk) for j, tk in enumerate(tasks, 1))
                rows.append(f'<tr data-p="{ph}" id="{lang}-{t}-w{w}"><td class="wk">{T["week"]} {w}</td><td class="dt">{e(ar_d if lang == "ar" else en_d)}</td>'
                            f'<td><span class="phase p{ph}">{e(names[ph][idx])}</span></td><td><ul class="tasks">{items}</ul></td></tr>')
            body.append(f'<div class="filters" role="group" aria-label="{T["filt"]}">{btns}</div>'
                        f'<div class="tw"><table class="weeks"><thead><tr><th>{T["week"]}</th><th>{T["dates"]}</th><th>{T["phase"]}</th><th>{T["tasks"]}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
        elif k == "gaps":
            body.append('<ol class="gaps">' + "".join(f"<li>{e(g[idx])}</li>" for g in b[1]) + "</ol>")
    if open_sec: body.append("</section>")
    toc.append(f'<li class="l1"><a href="#{lang}-s14">{T["refs_h"]}</a></li>')
    refs = "".join(f'<li id="{lang}-ref{NUM[k]}"><span class="rn">[{NUM[k]}]</span><span>{e(SOURCES[k][0])}<br><a href="{e(SOURCES[k][1])}" target="_blank" rel="noopener">{e(SOURCES[k][1])}</a></span></li>' for k in ORDER)
    body.append(f'<section><h2 id="{lang}-s14">{T["refs_h"]}</h2><ol class="refs" dir="ltr">{refs}</ol></section>')
    return toc, body

HERO = {
 "ar": (f"دليل تشغيلي · الإصدار {EDITION} · {DATE['ar']}", "دليل الإنتاج العضوي للزيتون في مصر",
        "منهجية التشغيل ومراحل الموسم وأطواره، أصناف مصر والشرق الأوسط، خطط عمل أسبوعية لكل نوع، ورعاية الشتلات حتى الإثمار",
        [("الموقع", "مصر — الساحل الشمالي، سيناء، غرب الدلتا، الفيوم، الواحات"), ("الأنواع", "زيتون زيت · مائدة أخضر · مائدة أسود"),
         ("النظام", "إنتاج عضوي — القانون 12 لسنة 2020"), ("المصادر", f"{len(ORDER)} مرجعًا مع روابط")], "درجة الثقة:", "تعريف المستويات"),
 "en": (f"Operating manual · Edition {EDITION} · {DATE['en']}", "Organic Olive Production Manual for Egypt",
        "Operating method, season phases and stages, varieties of Egypt and the Middle East, weekly work plans per type, and seedling care to fruiting",
        [("Location", "Egypt — North Coast, Sinai, West Delta, Fayoum, oases"), ("Types", "Oil · green table · black table"),
         ("System", "Organic — Egyptian Law 12/2020"), ("Sources", f"{len(ORDER)} linked references")], "Confidence:", "What the levels mean"),
}

def main(out):
    parts = []
    for lang in ("ar", "en"):
        eyebrow, h1, sub, fr, leg, legl = HERO[lang]
        toc, body = render(lang)
        facts_row = "".join(f"<div><dt>{e(a)}</dt><dd>{e(b)}</dd></div>" for a, b in fr)
        legend = " ".join(badge(lang, c) for c in "HML")
        attrs = 'lang="ar" dir="rtl" data-lang="ar"' if lang == "ar" else 'lang="en" dir="ltr" data-lang="en" hidden'
        parts.append(f'<div class="lang" {attrs}><header class="hero"><p class="eyebrow">{e(eyebrow)}</p><h1>{e(h1)}</h1><p class="sub">{e(sub)}</p>'
                     f'<dl class="facts-row">{facts_row}</dl><p class="legend">{leg} {legend} <a href="#{lang}-s2-2">{legl}</a></p></header>'
                     f'<div class="layout"><nav class="toc" aria-label="{L[lang]["toc"]}"><details open><summary>{L[lang]["toc"]}</summary><ol>{"".join(toc)}</ol></details></nav>'
                     f'<main>{"".join(body)}</main></div></div>')
    page = ('<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Organic Olive Manual</title>'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600&family=Readex+Pro:wght@500;600;700&display=swap">'
            f'<style>{CSS}</style></head><body>'
            '<div class="bar"><span class="brand">دليل الزيتون العضوي · Organic Olive Manual</span><div class="switch" role="group" aria-label="Language / اللغة">'
            '<button type="button" id="btn-ar" data-l="ar" aria-pressed="true">العربية</button><button type="button" id="btn-en" data-l="en" aria-pressed="false">English</button></div></div>'
            + "".join(parts) + f"<script>{JS}</script></body></html>")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    unused = sorted(set(SOURCES) - set(ORDER))
    print(f"written {out}: {len(page)} bytes, {len(ORDER)} references cited; unused sources: {unused}")

if __name__ == "__main__":
    main(sys.argv[1])
