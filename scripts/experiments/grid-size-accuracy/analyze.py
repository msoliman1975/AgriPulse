#!/usr/bin/env python
"""Analyze grid-size experiment results -> tables + plots + markdown report.

Reads the per-(block,scene,index,grid) CSV from regrid_experiment.py and builds
the three result panels the experiment was designed around:

  1. MEAN DRIFT      — weighted & unweighted block mean vs the full-res baseline,
                       across grid sizes. (Tests: weighted ~ invariant; unweighted
                       drifts via edge re-weighting.)
  2. HETEROGENEITY   — within-block spread of cell means (std / IQR / CoV) collapsing
                       as cells coarsen (spatial smoothing).
  3. EXTREMES/ANOMALY— range of cell means + peak |z| + anomalous-cell fraction
                       compressing toward the mean as cells coarsen.

Averages each metric over all scenes (dates) per (block, index, grid).
Outputs: summary CSVs + PNG plots + report.md under --outdir.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

GRID_ORDER = ["20", "30", "40", "50", "60", "70", "80", "block"]
KEY_INDICES = ["ndvi", "ndmi", "ndre", "evi", "savi", "gndvi", "ndwi"]


def _gridnum(g: str) -> float:
    return 999.0 if g == "block" else float(g)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    df = pd.read_csv(args.csv)
    df["grid_m"] = df["grid_m"].astype(str)
    df["gridnum"] = df["grid_m"].map(_gridnum)

    # Mean over all scenes per (block, index, grid).
    agg = (
        df.groupby(["block", "index", "grid_m", "gridnum"], as_index=False)
        .agg(
            scenes=("date", "nunique"),
            baseline_mean=("baseline_mean", "mean"),
            weighted_mean=("weighted_mean", "mean"),
            unweighted_mean=("unweighted_mean", "mean"),
            abs_w_drift=("w_minus_base", lambda s: s.abs().mean()),
            abs_u_drift=("u_minus_base", lambda s: s.abs().mean()),
            cellmean_std=("cellmean_std", "mean"),
            cellmean_iqr=("cellmean_iqr", "mean"),
            cellmean_cov=("cellmean_cov", "mean"),
            cellmean_range=("cellmean_range", "mean"),
            max_abs_z=("max_abs_z", "mean"),
            anom_frac_z2=("anom_frac_z2", "mean"),
            n_cells_valid=("n_cells_valid", "mean"),
            n_cells_dropped=("n_cells_dropped", "mean"),
        )
        .sort_values(["block", "index", "gridnum"])
    )
    agg.to_csv(os.path.join(args.outdir, "summary_by_grid.csv"), index=False)

    # Drift table (NDVI focus) — print to stdout for the report.
    def pivot(metric: str, index: str = "ndvi") -> pd.DataFrame:
        sub = agg[agg["index"] == index]
        p = sub.pivot_table(index="block", columns="grid_m", values=metric)
        return p.reindex(columns=[g for g in GRID_ORDER if g in p.columns])

    print("\n=== NDVI: mean ABS drift from baseline (x1000) ===")
    print((pivot("abs_w_drift") * 1000).round(3).to_string(), "  [weighted]")
    print((pivot("abs_u_drift") * 1000).round(3).to_string(), "  [unweighted]")
    print("\n=== NDVI: within-block std of cell means (heterogeneity) ===")
    print(pivot("cellmean_std").round(4).to_string())
    print("\n=== NDVI: cell-mean range (extremes spread) ===")
    print(pivot("cellmean_range").round(4).to_string())
    print("\n=== NDVI: peak |z| (anomaly strength) ===")
    print(pivot("max_abs_z").round(3).to_string())

    # ---- Plots (matplotlib optional) ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[analyze] matplotlib unavailable ({exc}); CSV/tables only.")
        return 0

    xpos = {g: i for i, g in enumerate(GRID_ORDER)}  # evenly-spaced categorical x
    xt_ticks = list(range(len(GRID_ORDER)))
    xt_labels = GRID_ORDER

    def line_plot(metric: str, title: str, ylabel: str, fname: str, indices=("ndvi",)):
        fig, ax = plt.subplots(figsize=(8, 5))
        for block in sorted(agg["block"].unique()):
            for idx in indices:
                sub = agg[(agg["block"] == block) & (agg["index"] == idx)].sort_values("gridnum")
                if sub.empty:
                    continue
                lbl = f"{block} · {idx}" if len(indices) > 1 else block
                ax.plot(sub["grid_m"].map(xpos), sub[metric], marker="o", label=lbl)
        ax.set_xticks(xt_ticks)
        ax.set_xticklabels(xt_labels)
        ax.set_xlabel("grid cell size (m)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(args.outdir, fname), dpi=120)
        plt.close(fig)

    # Panel 1: mean drift (weighted vs unweighted), NDVI.
    fig, ax = plt.subplots(figsize=(8, 5))
    for block in sorted(agg["block"].unique()):
        sub = agg[(agg["block"] == block) & (agg["index"] == "ndvi")].sort_values("gridnum")
        ax.plot(sub["grid_m"].map(xpos), sub["abs_w_drift"] * 1000, marker="o",
                label=f"{block} weighted")
        ax.plot(sub["grid_m"].map(xpos), sub["abs_u_drift"] * 1000, marker="s", linestyle="--",
                label=f"{block} unweighted")
    ax.set_xticks(xt_ticks); ax.set_xticklabels(xt_labels)
    ax.set_xlabel("grid cell size (m)"); ax.set_ylabel("mean |block − baseline| (×1000)")
    ax.set_title("Panel 1 · NDVI block-mean drift from full-res baseline")
    ax.grid(True, alpha=0.3); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "panel1_mean_drift.png"), dpi=120); plt.close(fig)

    # Panel 2: heterogeneity loss.
    line_plot("cellmean_std", "Panel 2 · NDVI within-block heterogeneity (std of cell means)",
              "std of cell means", "panel2_heterogeneity.png")
    # Panel 3: extremes / anomaly.
    line_plot("cellmean_range", "Panel 3a · NDVI cell-mean range (extremes spread)",
              "max−min of cell means", "panel3a_range.png")
    line_plot("max_abs_z", "Panel 3b · NDVI peak |z| (anomaly detectability)",
              "mean peak |z|", "panel3b_anomaly.png")
    # All-index heterogeneity small-multiple (std vs grid), heterogeneous block only.
    het_block = (agg.groupby("block")["cellmean_std"].mean().idxmax())
    line_plot("cellmean_std",
              f"Panel 2b · all indices, heterogeneity vs grid ({het_block})",
              "std of cell means", "panel2b_all_indices.png", indices=tuple(KEY_INDICES))

    print(f"\n[analyze] wrote plots + summary_by_grid.csv to {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
