"""Validate our stored Sentinel-2 index aggregates against CDSE's own server-side
computation (Sentinel Hub **Statistical API**) over the *same* imagery.

Because the source pixels are identical, any discrepancy isolates a bug or a
methodology gap in *our* pipeline (band scaling, AOI masking, cloud masking,
aggregation) rather than mixing in atmospheric-correction differences. This is
the highest-signal accuracy check we can run without standing up a second,
fully independent provider (e.g. Google Earth Engine).

Two reference modes are computed per (block, scene):
  * MODE A "replicate"  — same band math, NO cloud mask (dataMask only). This is
    an apples-to-apples check of OUR computation: it should match our stored
    means to within sub-percent. A large delta here = a real bug.
  * MODE B "cloud-mask" — same band math, but SCL clouds/shadows/cirrus/snow are
    excluded (best practice). The gap between our (unmasked) value and Mode B
    quantifies the impact of our missing cloud mask, especially on cloudy dates.

WHERE TO RUN: inside the API pod on the cluster (it has the SENTINEL_HUB_* creds,
egress to CDSE, DB access via psycopg, and the app settings). From a dev box:

  API=$(ssh root@<node> "kubectl -n agripulse get po -l app.kubernetes.io/name=agripulse-api -o name | head -1")
  ssh root@<node> "kubectl -n agripulse exec -i ${API#pod/} -- python - --auto-low 4 --auto-high 2" \
      < scripts/index-accuracy/compare_indices.py > report.json

Args (all optional; sane agrosina defaults):
  --tenant-slug   public.tenants.slug to resolve the schema (default: agrosina)
  --dates         comma YYYY-MM-DD to compare (overrides auto-pick)
  --auto-low N    auto-pick N lowest-cloud scene dates (default 4)
  --auto-high M    auto-pick M highest-cloud scene dates (default 2)
  --blocks        comma block names (default: all blocks with aggregates)
  --no-mode-b     skip the cloud-masked reference (Mode A only, half the calls)

Emits a single JSON document to stdout: {meta, comparisons[], summary}. A short
human summary is written to stderr so it doesn't pollute the JSON on stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import timedelta

import httpx
import psycopg
from app.core.settings import get_settings

INDEX_ORDER = ["ndvi", "ndwi", "evi", "savi", "ndre", "gndvi", "ndmi"]

# SCL classes excluded as "cloud-affected" in Mode B (Sentinel-2 scene
# classification): 0 no-data, 1 saturated/defective, 3 cloud shadow,
# 8 cloud medium-prob, 9 cloud high-prob, 10 thin cirrus, 11 snow/ice.
_CLOUD_SCL = "(s.SCL==0||s.SCL==1||s.SCL==3||s.SCL==8||s.SCL==9||s.SCL==10||s.SCL==11)"

_INDEX_JS = """
  var ndvi=(s.B08+s.B04)==0?0:(s.B08-s.B04)/(s.B08+s.B04);
  var ndwi=(s.B03+s.B08)==0?0:(s.B03-s.B08)/(s.B03+s.B08);
  var evi=(s.B08+6*s.B04-7.5*s.B02+1)==0?0:2.5*(s.B08-s.B04)/(s.B08+6*s.B04-7.5*s.B02+1);
  var L=0.5;
  var savi=(s.B08+s.B04+L)==0?0:(1+L)*(s.B08-s.B04)/(s.B08+s.B04+L);
  var ndre=(s.B08+s.B05)==0?0:(s.B08-s.B05)/(s.B08+s.B05);
  var gndvi=(s.B08+s.B03)==0?0:(s.B08-s.B03)/(s.B08+s.B03);
  var ndmi=(s.B08+s.B11)==0?0:(s.B08-s.B11)/(s.B08+s.B11);
"""


def _evalscript(cloud_mask: bool) -> str:
    dm = f"s.dataMask*({_CLOUD_SCL}?0:1)" if cloud_mask else "s.dataMask"
    return f"""//VERSION=3
function setup() {{
  return {{
    input: [{{bands:["B02","B03","B04","B05","B08","B11","B12","SCL","dataMask"]}}],
    output: [{{id:"indices", bands:7, sampleType:"FLOAT32"}}, {{id:"dataMask", bands:1}}]
  }};
}}
function evaluatePixel(s) {{{_INDEX_JS}
  return {{indices:[ndvi,ndwi,evi,savi,ndre,gndvi,ndmi], dataMask:[{dm}]}};
}}
"""


def _token() -> str:
    r = httpx.post(
        os.environ["SENTINEL_HUB_OAUTH_URL"],
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["SENTINEL_HUB_CLIENT_ID"],
            "client_secret": os.environ["SENTINEL_HUB_CLIENT_SECRET"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _stats_url() -> str:
    return os.environ["SENTINEL_HUB_PROCESS_URL"].replace("/process", "/statistics")


def _call_stats(token: str, geom: dict, scene_time, cloud_mask: bool) -> dict | None:
    # ±12h window + leastCC, matching our fetch() so the same scene is selected.
    w_from = (scene_time - timedelta(hours=12)).astimezone().isoformat()
    w_to = (scene_time + timedelta(hours=12)).astimezone().isoformat()
    body = {
        "input": {
            "bounds": {
                "geometry": geom,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/32636"},
            },
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {"mosaickingOrder": "leastCC"}}],
        },
        "aggregation": {
            "timeRange": {"from": w_from, "to": w_to},
            "aggregationInterval": {"of": "P1D"},
            "resx": 10,
            "resy": 10,
            "evalscript": _evalscript(cloud_mask),
        },
        "calculations": {"indices": {"statistics": {"default": {"percentiles": {"k": [10, 50, 90]}}}}},
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # CDSE trial accounts are rate-limited (requests/min + processing-unit/min).
    # Back off on 429, honouring Retry-After when present.
    r = None
    for attempt in range(6):
        r = httpx.post(_stats_url(), json=body, headers=headers, timeout=120)
        if r.status_code != 429:
            break
        wait = float(r.headers.get("Retry-After", 0)) or min(60.0, 6.0 * (2**attempt))
        print(f"  . 429 rate-limited, sleeping {wait:.0f}s (attempt {attempt + 1})", file=sys.stderr)
        time.sleep(wait)
    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else "n/a"
        body_txt = r.text[:300] if r is not None else ""
        print(f"  ! stats HTTP {code}: {body_txt}", file=sys.stderr)
        return None
    data = r.json().get("data") or []
    if not data:
        return None
    # Pick the interval with the most valid pixels (defensive; usually one).
    best = max(data, key=lambda d: d["outputs"]["indices"]["bands"]["B0"]["stats"].get("sampleCount", 0))
    out = {}
    for i, code in enumerate(INDEX_ORDER):
        st = best["outputs"]["indices"]["bands"][f"B{i}"]["stats"]
        pct = st.get("percentiles", {})
        out[code] = {
            "mean": st.get("mean"),
            "min": st.get("min"),
            "max": st.get("max"),
            "p10": pct.get("10.0"),
            "p50": pct.get("50.0"),
            "p90": pct.get("90.0"),
            "std": st.get("stDev"),
            "count": st.get("sampleCount"),
            "nodata": st.get("noDataCount"),
        }
    out["_interval"] = best["interval"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", default="agrosina")
    ap.add_argument("--dates", default="")
    ap.add_argument("--auto-low", type=int, default=4)
    ap.add_argument("--auto-high", type=int, default=2)
    ap.add_argument("--blocks", default="")
    ap.add_argument("--no-mode-b", action="store_true")
    ap.add_argument("--sleep", type=float, default=3.0, help="seconds between API calls (rate-limit pacing)")
    args = ap.parse_args()

    s = get_settings()
    dsn = str(s.database_sync_url).replace("+psycopg", "")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT schema_name FROM public.tenants WHERE slug=%s", (args.tenant_slug,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"no tenant with slug {args.tenant_slug!r}")
        schema = row[0]
        cur.execute(f'SET search_path TO "{schema}", public')

        block_filter = [b.strip() for b in args.blocks.split(",") if b.strip()]
        cur.execute(
            "SELECT b.id, b.name, ST_AsGeoJSON(ST_Transform(b.boundary,32636)) "
            "FROM blocks b WHERE b.id IN (SELECT DISTINCT block_id FROM block_index_aggregates) "
            "ORDER BY b.name"
        )
        blocks = []
        for bid, name, gj in cur.fetchall():
            if block_filter and name not in block_filter:
                continue
            geom = json.loads(gj)
            geom.pop("crs", None)
            blocks.append({"id": bid, "name": name, "geom": geom})

        # Resolve the set of scene dates to compare.
        if args.dates.strip():
            dates = [d.strip() for d in args.dates.split(",") if d.strip()]
        else:
            cur.execute(
                "SELECT time::date AS d, avg(cloud_cover_pct) cc FROM block_index_aggregates "
                "GROUP BY 1 ORDER BY cc ASC"
            )
            by_cc = cur.fetchall()
            low = [str(r[0]) for r in by_cc[: args.auto_low]]
            high = [str(r[0]) for r in by_cc[::-1][: args.auto_high]]
            dates = sorted(set(low + high))

        # Pull our stored aggregates for the chosen sample.
        cur.execute(
            "SELECT block_id, index_code, time, mean, min, max, p10, p50, p90, std_dev, "
            "valid_pixel_count, cloud_cover_pct "
            "FROM block_index_aggregates WHERE time::date = ANY(%s) ORDER BY block_id, time",
            (dates,),
        )
        ours: dict[tuple, dict] = {}
        scene_time: dict[tuple, object] = {}
        for r in cur.fetchall():
            bid, code, t = r[0], r[1], r[2]
            key = (str(bid), str(t.date()))
            scene_time[key] = t
            ours.setdefault(key, {})[code] = {
                "mean": float(r[3]) if r[3] is not None else None,
                "min": float(r[4]) if r[4] is not None else None,
                "max": float(r[5]) if r[5] is not None else None,
                "p10": float(r[6]) if r[6] is not None else None,
                "p50": float(r[7]) if r[7] is not None else None,
                "p90": float(r[8]) if r[8] is not None else None,
                "std": float(r[9]) if r[9] is not None else None,
                "count": r[10],
                "cloud_cover_pct": float(r[11]) if r[11] is not None else None,
            }

    print(
        f"tenant={args.tenant_slug} schema={schema} blocks={len(blocks)} dates={dates}",
        file=sys.stderr,
    )

    token = _token()
    comparisons = []
    for blk in blocks:
        for d in dates:
            key = (str(blk["id"]), d)
            if key not in ours:
                continue
            st = scene_time[key]
            print(f"  ~ {blk['name']} {d} ...", file=sys.stderr)
            ref_a = _call_stats(token, blk["geom"], st, cloud_mask=False)
            time.sleep(args.sleep)
            ref_b = None
            if not args.no_mode_b:
                ref_b = _call_stats(token, blk["geom"], st, cloud_mask=True)
                time.sleep(args.sleep)
            comparisons.append(
                {
                    "block": blk["name"],
                    "date": d,
                    "cloud_cover_pct": next(iter(ours[key].values()))["cloud_cover_pct"],
                    "ours": ours[key],
                    "ref_replicate": ref_a,
                    "ref_cloudmask": ref_b,
                }
            )

    # --- summary: per-index error of OUR mean vs Mode A (replicate) ----------
    per_index: dict[str, list[float]] = {c: [] for c in INDEX_ORDER}
    cloudmask_shift: dict[str, list[float]] = {c: [] for c in INDEX_ORDER}
    count_ratio = []
    for cmp in comparisons:
        ra = cmp["ref_replicate"]
        rb = cmp["ref_cloudmask"]
        if not ra:
            continue
        for code in INDEX_ORDER:
            om = cmp["ours"].get(code, {}).get("mean")
            am = ra.get(code, {}).get("mean")
            if om is not None and am is not None:
                per_index[code].append(om - am)
            if rb and rb.get(code, {}).get("mean") is not None and am is not None:
                cloudmask_shift[code].append(rb[code]["mean"] - am)
        oc = cmp["ours"].get("ndvi", {}).get("count")
        ac = ra.get("ndvi", {}).get("count")
        if oc and ac:
            count_ratio.append(oc / ac)

    def _stats(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        n = len(xs)
        bias = sum(xs) / n
        mae = sum(abs(x) for x in xs) / n
        rmse = math.sqrt(sum(x * x for x in xs) / n)
        return {"n": n, "bias": bias, "mae": mae, "rmse": rmse, "max_abs": max(abs(x) for x in xs)}

    summary = {
        "replicate_mean_error_by_index": {c: _stats(per_index[c]) for c in INDEX_ORDER},
        "cloudmask_mean_shift_by_index": {c: _stats(cloudmask_shift[c]) for c in INDEX_ORDER},
        "our_vs_native_pixelcount_ratio": (
            {"mean": sum(count_ratio) / len(count_ratio), "min": min(count_ratio), "max": max(count_ratio)}
            if count_ratio
            else {}
        ),
    }

    doc = {
        "meta": {
            "tenant_slug": args.tenant_slug,
            "schema": schema,
            "reference": "CDSE Sentinel Hub Statistical API (sentinel-2-l2a, resx/resy=10m, leastCC, ±12h)",
            "dates": dates,
            "blocks": [b["name"] for b in blocks],
            "n_comparisons": len(comparisons),
        },
        "summary": summary,
        "comparisons": comparisons,
    }
    json.dump(doc, sys.stdout, indent=2, default=str)

    # Human summary to stderr.
    print("\n=== replicate (Mode A) mean error: ours - CDSE-native ===", file=sys.stderr)
    for c in INDEX_ORDER:
        st = summary["replicate_mean_error_by_index"][c]
        if st["n"]:
            print(
                f"  {c:6} n={st['n']:3d} bias={st['bias']:+.4f} mae={st['mae']:.4f} "
                f"rmse={st['rmse']:.4f} max={st['max_abs']:.4f}",
                file=sys.stderr,
            )
    pr = summary["our_vs_native_pixelcount_ratio"]
    if pr:
        print(
            f"  pixel-count ratio ours/native: mean={pr['mean']:.1f}x "
            f"({pr['min']:.1f}–{pr['max']:.1f})",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
