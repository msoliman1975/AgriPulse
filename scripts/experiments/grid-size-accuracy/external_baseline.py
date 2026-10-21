#!/usr/bin/env python
"""Phase 2 — external baseline via the CDSE Sentinel Hub Statistical API.

Runs INSIDE the cluster (uses the pod's existing CDSE OAuth creds + network —
no Netskope, no new account). For each pilot block polygon (WGS84) it asks the
Statistical API to compute server-side zonal stats (mean/stDev/min/max/sampleCount)
for all 7 indices, per acquisition day, over the SAME S2 L2A data our pipeline
ingests. This is an INDEPENDENT ENGINE over the SAME SOURCE: differences isolate
clipping / aggregation / cloud-masking, not the sensor. The 7 index formulas below
are byte-for-byte the ones in app.modules.indices.computation.

Output: external_baseline.csv (block, date, index, sh_mean, sh_stdev, sh_min,
sh_max, sh_sample_count, sh_nodata_count). Raw JSON responses saved per block.

Usage (in-pod): python external_baseline.py --manifest wgs_manifest.json \
    --out external_baseline.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

INDICES = ["ndvi", "ndwi", "evi", "savi", "ndre", "gndvi", "ndmi"]

# Identical formulas to computation.py; SCL cloud/snow/shadow masked out via dataMask.
EVALSCRIPT = r"""//VERSION=3
function setup() {
  return {
    input: [{bands: ["B02","B03","B04","B05","B08","B11","SCL","dataMask"]}],
    output: [
      {id: "ndvi", bands: 1, sampleType: "FLOAT32"},
      {id: "ndwi", bands: 1, sampleType: "FLOAT32"},
      {id: "evi",  bands: 1, sampleType: "FLOAT32"},
      {id: "savi", bands: 1, sampleType: "FLOAT32"},
      {id: "ndre", bands: 1, sampleType: "FLOAT32"},
      {id: "gndvi",bands: 1, sampleType: "FLOAT32"},
      {id: "ndmi", bands: 1, sampleType: "FLOAT32"},
      {id: "dataMask", bands: 1}
    ]
  };
}
function sd(n, d) { return d == 0 ? 0 : n / d; }
function evaluatePixel(s) {
  var scl = s.SCL;
  // 0 nodata,1 defective,3 cloud shadow,8 cloud med,9 cloud high,10 cirrus,11 snow
  var bad = (scl==0||scl==1||scl==3||scl==8||scl==9||scl==10||scl==11);
  var m = (s.dataMask == 1 && !bad) ? 1 : 0;
  var nir=s.B08, red=s.B04, green=s.B03, blue=s.B02, re=s.B05, swir=s.B11;
  return {
    ndvi:  [sd(nir-red, nir+red)],
    ndwi:  [sd(green-nir, green+nir)],
    evi:   [2.5*(nir-red)/(nir + 6.0*red - 7.5*blue + 1.0)],
    savi:  [1.5*(nir-red)/(nir + red + 0.5)],
    ndre:  [sd(nir-re, nir+re)],
    gndvi: [sd(nir-green, nir+green)],
    ndmi:  [sd(nir-swir, nir+swir)],
    dataMask: [m]
  };
}
"""


def _post(url: str, data: bytes, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {exc.code} on {url}:\n{body}") from exc


def get_token() -> str:
    form = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["SENTINEL_HUB_CLIENT_ID"],
        "client_secret": os.environ["SENTINEL_HUB_CLIENT_SECRET"],
    }).encode()
    tok = _post(os.environ["SENTINEL_HUB_OAUTH_URL"], form,
                {"Content-Type": "application/x-www-form-urlencoded"})
    return tok["access_token"]


def stats_for_block(block: dict, token: str, stats_url: str) -> dict:
    dates = block["dates"]
    geom = dict(block["geometry"])
    geom.pop("crs", None)  # SH wants the CRS in properties, not a geometry member
    body = {
        "input": {
            "bounds": {
                "geometry": geom,
                # UTM 36N so resx/resy below are METRES, not degrees.
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/32636"},
            },
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {}}],
        },
        "aggregation": {
            "timeRange": {"from": f"{dates[0]}T00:00:00Z", "to": f"{dates[-1]}T23:59:59Z"},
            "aggregationInterval": {"of": "P1D"},
            "resx": 10, "resy": 10,
            "evalscript": EVALSCRIPT,
        },
        "calculations": {"default": {}},
    }
    return _post(stats_url, json.dumps(body).encode(),
                 {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    stats_url = os.environ["SENTINEL_HUB_PROCESS_URL"].replace("/process", "/statistics")
    print(f"[ext] statistics url = {stats_url}", flush=True)
    token = get_token()
    print("[ext] got OAuth token", flush=True)

    blocks = json.load(open(args.manifest, encoding="utf-8"))
    rows = 0
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["block", "date", "index", "sh_mean", "sh_stdev", "sh_min",
                    "sh_max", "sh_sample_count", "sh_nodata_count"])
        for block in blocks:
            resp = stats_for_block(block, token, stats_url)
            with open(f"/tmp/ext_raw_{block['block']}.json", "w") as rf:
                json.dump(resp, rf)
            intervals = resp.get("data", [])
            print(f"[ext] {block['block']}: {len(intervals)} intervals returned", flush=True)
            for iv in intervals:
                date = iv["interval"]["from"][:10]
                outputs = iv.get("outputs", {})
                for idx in INDICES:
                    st = outputs.get(idx, {}).get("bands", {}).get("B0", {}).get("stats")
                    if not st:
                        continue
                    w.writerow([block["block"], date, idx,
                                st.get("mean"), st.get("stDev"), st.get("min"),
                                st.get("max"), st.get("sampleCount"), st.get("noDataCount")])
                    rows += 1
            fh.flush()
    print(f"[ext] DONE rows={rows} -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
