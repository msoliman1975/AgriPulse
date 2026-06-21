"""Break down a compare_indices.py report JSON: per-index error split by clean vs
cloudy scenes, the cloud-mask (Mode B) shift, pixel-count ratios, and a per
(block,date) NDVI table. Usage: python analyze_report.py [report.json]"""

import json
import math
import sys

doc = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "agrosina-report.json"))
cmps = doc["comparisons"]
IDX = ["ndvi", "ndwi", "evi", "savi", "ndre", "gndvi", "ndmi"]

CLOUDY_THRESH = 10.0  # cloud_cover_pct above this = "cloudy" scene


def agg(xs):
    if not xs:
        return None
    n = len(xs)
    return dict(
        n=n,
        bias=sum(xs) / n,
        mae=sum(abs(x) for x in xs) / n,
        rmse=math.sqrt(sum(x * x for x in xs) / n),
        maxabs=max(abs(x) for x in xs),
    )


# Split Mode A mean error by clean vs cloudy
clean = {i: [] for i in IDX}
cloudy = {i: [] for i in IDX}
modeb = {i: [] for i in IDX}  # cloudmask shift = ref_b - ref_a (all)
modeb_cloudy = {i: [] for i in IDX}
pix = []
for c in cmps:
    ra, rb = c["ref_replicate"], c["ref_cloudmask"]
    cc = c.get("cloud_cover_pct") or 0.0
    if not ra:
        continue
    bucket = cloudy if cc > CLOUDY_THRESH else clean
    for i in IDX:
        om = c["ours"].get(i, {}).get("mean")
        am = ra.get(i, {}).get("mean")
        if om is not None and am is not None:
            bucket[i].append(om - am)
        if rb and rb.get(i, {}).get("mean") is not None and am is not None:
            modeb[i].append(rb[i]["mean"] - am)
            if cc > CLOUDY_THRESH:
                modeb_cloudy[i].append(rb[i]["mean"] - am)
    oc = c["ours"].get("ndvi", {}).get("count")
    ac = ra.get("ndvi", {}).get("count")
    if oc and ac:
        pix.append((c["block"], c["date"], cc, oc, ac, oc / ac))

print("== Mode A (replicate, no cloud mask): OUR mean - CDSE native-10m mean ==")
print(f"{'index':6} | {'CLEAN (cc<=10%)':>34} | {'CLOUDY (cc>10%)':>34}")
print(f"{'':6} | {'n':>3} {'bias':>8} {'mae':>8} {'rmse':>8} | {'n':>3} {'bias':>8} {'mae':>8} {'rmse':>8}")
for i in IDX:
    a, b = agg(clean[i]), agg(cloudy[i])
    la = f"{a['n']:>3} {a['bias']:>+8.4f} {a['mae']:>8.4f} {a['rmse']:>8.4f}" if a else " " * 30
    lb = f"{b['n']:>3} {b['bias']:>+8.4f} {b['mae']:>8.4f} {b['rmse']:>8.4f}" if b else " " * 30
    print(f"{i:6} | {la} | {lb}")

print("\n== Mode B impact: CDSE cloud-masked - CDSE unmasked (how much clouds bias the mean) ==")
print(f"{'index':6} | {'ALL dates':>26} | {'CLOUDY only':>26}")
for i in IDX:
    a, b = agg(modeb[i]), agg(modeb_cloudy[i])
    la = f"n={a['n']:>2} bias={a['bias']:>+7.4f} max={a['maxabs']:.4f}" if a else ""
    lb = f"n={b['n']:>2} bias={b['bias']:>+7.4f} max={b['maxabs']:.4f}" if b else ""
    print(f"{i:6} | {la:>26} | {lb:>26}")

print("\n== Pixel-count: our valid_pixel_count vs CDSE native-10m sampleCount ==")
print(f"{'block':11} {'date':11} {'cc%':>6} {'ours':>8} {'native':>7} {'ratio':>7}")
for blk, d, cc, oc, ac, r in sorted(pix, key=lambda x: (x[0], x[1])):
    print(f"{blk:11} {d:11} {cc:>6.1f} {oc:>8d} {ac:>7d} {r:>6.1f}x")

# NDVI per-date detail (worst + best)
print("\n== NDVI per (block,date): ours vs CDSE-native (Mode A) ==")
rows = []
for c in cmps:
    ra = c["ref_replicate"]
    if not ra:
        continue
    om = c["ours"]["ndvi"]["mean"]
    am = ra["ndvi"]["mean"]
    rows.append((c["block"], c["date"], c.get("cloud_cover_pct") or 0, om, am, om - am))
print(f"{'block':11} {'date':11} {'cc%':>6} {'ours':>8} {'cdse':>8} {'delta':>8}")
for blk, d, cc, om, am, dl in sorted(rows, key=lambda x: -abs(x[5])):
    print(f"{blk:11} {d:11} {cc:>6.1f} {om:>8.4f} {am:>8.4f} {dl:>+8.4f}")
