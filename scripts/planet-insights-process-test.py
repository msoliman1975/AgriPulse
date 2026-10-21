#!/usr/bin/env python3
"""Probe whether the Planet Insights Platform (= Sentinel Hub commercial
deployment) can deliver 3 m PlanetScope through the Catalog + Process APIs.

This mirrors what backend/app/modules/imagery/providers/sentinel_hub.py
already does for CDSE Sentinel-2, but points at the *commercial* SH
deployment that carries PlanetScope, and asks for a PSScene collection.

It does three things, stopping at the first hard failure:
  1. OAuth client-credentials  -> proves the Insights client is valid.
  2. Catalog (STAC) search     -> proves PS scenes exist *and are
                                   accessible* over the AOI/time window.
  3. Process API (NDVI eval)   -> proves we can actually pull 3 m pixels;
                                   writes ps_ndvi_test.tiff on success.

Run:
  INSIGHTS_CLIENT_ID=...  INSIGHTS_CLIENT_SECRET=...  \
  PS_COLLECTION=byoc-XXXX  python scripts/planet-insights-process-test.py

Everything is overridable by env var (see CONFIG below). Netskope TLS
note: if OAuth/Catalog fail with cert errors, set INSECURE=1 to disable
verification for this throwaway probe (matches the --ssl-no-revoke we
use elsewhere on this machine).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta

import httpx

# --- CONFIG (env-overridable) ------------------------------------------------

CLIENT_ID = os.environ.get("INSIGHTS_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("INSIGHTS_CLIENT_SECRET", "")

# Planet Insights Platform == Sentinel Hub commercial deployment.
# These default to services.sentinel-hub.com; override if your account
# sits on a different Insights host.
OAUTH_URL = os.environ.get(
    "INSIGHTS_OAUTH_URL",
    "https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token",
)
CATALOG_URL = os.environ.get(
    "INSIGHTS_CATALOG_URL",
    "https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search",
)
PROCESS_URL = os.environ.get(
    "INSIGHTS_PROCESS_URL",
    "https://services.sentinel-hub.com/api/v1/process",
)

# The PlanetScope collection / data type as SH exposes it for YOUR account.
# This is the one value you almost certainly must set explicitly: depending
# on how Planet attaches PS to your plan it is either a managed collection
# id or a "byoc-<uuid>" Third Party Data Import. Find it in the dashboard
# under Data Collections, or via GET /api/v1/byoc/global. The catalog
# `collections` entry and the process `data[].type` use the SAME string.
PS_COLLECTION = os.environ.get("PS_COLLECTION", "byoc-PLANETSCOPE-COLLECTION-ID")

# AOI: ~0.8 km block near Suez/Ismailia (lon 32.64, lat 30.08), the one
# the earlier Subscriptions test used. WGS84 lon/lat.
AOI_LON, AOI_LAT = 32.64, 30.08
HALF = 0.004  # ~0.8 km box half-width in degrees
AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [AOI_LON - HALF, AOI_LAT - HALF],
            [AOI_LON + HALF, AOI_LAT - HALF],
            [AOI_LON + HALF, AOI_LAT + HALF],
            [AOI_LON - HALF, AOI_LAT + HALF],
            [AOI_LON - HALF, AOI_LAT - HALF],
        ]
    ],
}

# Search window: last N days (PS revisits ~daily, so a recent window
# should have scenes if the account can see PS at all).
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "30"))

INSECURE = os.environ.get("INSECURE", "") not in ("", "0", "false", "False")

# PlanetScope 8-band SR band names (PSB.SD instrument). For 4-band data
# use blue/green/red/nir only. Adjust if your catalog item lists others.
PS_RED = os.environ.get("PS_RED_BAND", "red")
PS_NIR = os.environ.get("PS_NIR_BAND", "nir")


def _fail(msg: str, *, body: str | None = None) -> None:
    print(f"\n[FAIL] {msg}")
    if body:
        print("---- response body (truncated) ----")
        print(body[:2000])
    sys.exit(1)


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        _fail(
            "Set INSIGHTS_CLIENT_ID and INSIGHTS_CLIENT_SECRET (OAuth client "
            "from the Planet Insights / Sentinel Hub dashboard, NOT the PLAK Data API key)."
        )
    if "PLANETSCOPE-COLLECTION-ID" in PS_COLLECTION:
        print(
            "[warn] PS_COLLECTION is still the placeholder. Catalog/Process will "
            "likely 404/400. Set it to your account's PlanetScope collection id."
        )

    verify = not INSECURE
    client = httpx.Client(timeout=httpx.Timeout(60.0), verify=verify)

    # 1) OAuth ----------------------------------------------------------------
    print(f"[1/3] OAuth -> {OAUTH_URL}")
    r = client.post(
        OAUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status_code != 200:
        _fail(f"OAuth HTTP {r.status_code}", body=r.text)
    token = r.json().get("access_token", "")
    if not token:
        _fail("OAuth 200 but no access_token", body=r.text)
    print("      OK - token issued")

    now = datetime.now(UTC)
    frm = now - timedelta(days=WINDOW_DAYS)
    auth = {"Authorization": f"Bearer {token}"}

    # 2) Catalog (STAC) -------------------------------------------------------
    print(f"[2/3] Catalog -> {CATALOG_URL}  collection={PS_COLLECTION}")
    cat_payload = {
        "collections": [PS_COLLECTION],
        "datetime": f"{frm.isoformat()}/{now.isoformat()}",
        "intersects": AOI,
        "limit": 20,
    }
    r = client.post(
        CATALOG_URL,
        json=cat_payload,
        headers={**auth, "Accept": "application/geo+json", "Content-Type": "application/json"},
    )
    if r.status_code != 200:
        _fail(
            f"Catalog HTTP {r.status_code} - likely the collection id is wrong, "
            "OR the Exploratory plan does not entitle PlanetScope data.",
            body=r.text,
        )
    features = r.json().get("features", []) or []
    print(f"      OK - {len(features)} PS scene(s) found in last {WINDOW_DAYS}d")
    if features:
        f0 = features[0]
        props = f0.get("properties", {})
        print(f"      newest: id={f0.get('id')} datetime={props.get('datetime')}")
    else:
        print(
            "      [warn] 0 scenes - either no PS captures over this AOI/window, "
            "or the plan returns an empty (no-access) result set. Process will likely be empty."
        )

    # 3) Process (NDVI) -------------------------------------------------------
    print(f"[3/3] Process -> {PROCESS_URL}  (NDVI over AOI)")
    evalscript = (
        "//VERSION=3\n"
        "function setup(){return{input:[{bands:[\"%s\",\"%s\"]}],"
        "output:{bands:1,sampleType:\"FLOAT32\"}};}\n"
        "function evaluatePixel(s){var d=s.%s+s.%s;return [d===0?0:(s.%s-s.%s)/d];}\n"
    ) % (PS_RED, PS_NIR, PS_NIR, PS_RED, PS_NIR, PS_RED)

    proc_payload = {
        "input": {
            "bounds": {"geometry": AOI, "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
            "data": [
                {
                    "type": PS_COLLECTION,
                    "dataFilter": {
                        "timeRange": {"from": frm.isoformat(), "to": now.isoformat()},
                        "mosaickingOrder": "leastCC",
                    },
                }
            ],
        },
        "output": {
            # ~3 m over a 0.8 km box -> ~270 px; cap for a quick probe.
            "width": 256,
            "height": 256,
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": evalscript,
    }
    r = client.post(
        PROCESS_URL,
        json=proc_payload,
        headers={**auth, "Accept": "image/tiff", "Content-Type": "application/json"},
    )
    if r.status_code != 200:
        _fail(
            f"Process HTTP {r.status_code} - if Catalog worked but this fails, it is "
            "usually band names (PS_RED_BAND/PS_NIR_BAND) or a processing-unit/quota limit.",
            body=r.text if "image" not in r.headers.get("content-type", "") else "<binary>",
        )
    out = "ps_ndvi_test.tiff"
    with open(out, "wb") as fh:
        fh.write(r.content)
    print(f"      OK - wrote {len(r.content)} bytes to {out}")
    print("\n[PASS] Process API CAN deliver 3 m PlanetScope for this account. 🎉")
    print("       Next: fold PS as a second product into the existing SentinelHubProvider.")


if __name__ == "__main__":
    main()
