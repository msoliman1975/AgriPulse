#!/usr/bin/env python
"""Phase 2 analysis — compare our block means against the CDSE Statistical API.

Three sources joined on (block, date, index):
  * SH       — CDSE Statistical API, native 10 m, independent engine  (external_baseline.csv)
  * ours     — our harness full-res baseline, AOI-clipped             (grid_results.csv)
  * stored   — the persisted production block aggregate (AOI bug)      (stored_aggregates.csv)

Reports bias / MAE / RMSE / Pearson r of (ours vs SH) and (stored vs SH) per index,
plus scatter + time-series + RMSE-bar plots.
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

INDICES = ["ndvi", "ndmi", "ndre", "evi", "savi", "gndvi", "ndwi"]


def metrics(a: pd.Series, b: pd.Series) -> dict:
    d = (a - b).dropna()
    if len(d) < 2:
        return {"n": len(d), "bias": np.nan, "mae": np.nan, "rmse": np.nan, "r": np.nan}
    mask = a.notna() & b.notna()
    r = np.corrcoef(a[mask], b[mask])[0, 1] if mask.sum() >= 2 else np.nan
    return {"n": int(len(d)), "bias": float(d.mean()), "mae": float(d.abs().mean()),
            "rmse": float(np.sqrt((d ** 2).mean())), "r": float(r)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="out")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    sh = pd.read_csv("external_baseline.csv")[["block", "date", "index", "sh_mean", "sh_stdev"]]
    ours = pd.read_csv("grid_results.csv")
    ours = (ours.groupby(["block", "date", "index"], as_index=False)
            .agg(ours_mean=("baseline_mean", "first")))
    stored = pd.read_csv("stored_aggregates.csv")[["block", "date", "index", "stored_mean"]]

    df = sh.merge(ours, on=["block", "date", "index"], how="inner") \
           .merge(stored, on=["block", "date", "index"], how="left")
    df = df[df["sh_mean"].notna()]  # drop SH all-cloud days
    df.to_csv(os.path.join(args.outdir, "compare_joined.csv"), index=False)

    print(f"matched rows (SH finite): {len(df)}  dates/index/block\n")
    print("=== ours vs SH (independent 10 m baseline) ===")
    rows_o, rows_s = [], []
    for idx in INDICES:
        s = df[df["index"] == idx]
        mo = metrics(s["ours_mean"], s["sh_mean"])
        ms = metrics(s["stored_mean"], s["sh_mean"])
        rows_o.append([idx, mo["n"], f'{mo["bias"]:+.4f}', f'{mo["rmse"]:.4f}', f'{mo["r"]:.3f}'])
        rows_s.append([idx, ms["n"], f'{ms["bias"]:+.4f}', f'{ms["rmse"]:.4f}', f'{ms["r"]:.3f}'])
    cols = ["index", "n", "bias", "rmse", "r"]
    print(pd.DataFrame(rows_o, columns=cols).to_string(index=False))
    print("\n=== stored production vs SH (shows AOI-clip bug impact) ===")
    print(pd.DataFrame(rows_s, columns=cols).to_string(index=False))

    # ---- plots ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[compare] matplotlib unavailable ({exc})")
        return 0

    # Scatter ours vs SH (NDVI), both blocks.
    fig, ax = plt.subplots(figsize=(6, 6))
    n = df[df["index"] == "ndvi"]
    for blk, gg in n.groupby("block"):
        ax.scatter(gg["sh_mean"], gg["ours_mean"], label=blk, s=28)
    lo, hi = 0.0, max(n["sh_mean"].max(), n["ours_mean"].max()) * 1.1
    ax.plot([lo, hi], [lo, hi], "k--", lw=1, label="1:1")
    ax.set_xlabel("SH Statistical API NDVI (10 m)")
    ax.set_ylabel("our pipeline baseline NDVI")
    ax.set_title("Phase 2 · ours vs independent SH baseline (NDVI)")
    ax.legend(); ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "ext_scatter_ndvi.png"), dpi=120); plt.close(fig)

    # Time series for the heterogeneous block.
    blk = "AG-R01-C02"
    ts = df[(df["index"] == "ndvi") & (df["block"] == blk)].sort_values("date")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(ts["date"], ts["sh_mean"], marker="o", label="SH (10 m, independent)")
    ax.plot(ts["date"], ts["ours_mean"], marker="s", label="ours (AOI-clipped)")
    ax.plot(ts["date"], ts["stored_mean"], marker="^", linestyle="--", label="stored prod (AOI bug)")
    ax.set_title(f"Phase 2 · NDVI time series — {blk}")
    ax.set_ylabel("NDVI block mean"); ax.tick_params(axis="x", rotation=60, labelsize=7)
    ax.legend(); ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "ext_timeseries_ndvi.png"), dpi=120); plt.close(fig)

    # RMSE bars per index.
    rmse_o = [metrics(df[df["index"] == i]["ours_mean"], df[df["index"] == i]["sh_mean"])["rmse"]
              for i in INDICES]
    rmse_s = [metrics(df[df["index"] == i]["stored_mean"], df[df["index"] == i]["sh_mean"])["rmse"]
              for i in INDICES]
    x = np.arange(len(INDICES))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - 0.2, rmse_o, 0.4, label="ours vs SH")
    ax.bar(x + 0.2, rmse_s, 0.4, label="stored prod vs SH")
    ax.set_xticks(x); ax.set_xticklabels(INDICES)
    ax.set_ylabel("RMSE vs SH baseline"); ax.set_title("Phase 2 · agreement with independent baseline")
    ax.legend(); ax.grid(alpha=0.3, axis="y"); fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "ext_rmse_by_index.png"), dpi=120); plt.close(fig)

    print(f"\n[compare] wrote compare_joined.csv + 3 plots to {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
