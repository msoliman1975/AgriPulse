"""Recompute a scene's statistics and diff them against what is stored.

**Nothing here writes to a pipeline table.** A drift verdict is a signal, not
a repair: the fix is a re-run from the Backfill Console, which owns provider
quota and progress reporting. Verification records what it found in its own
table and stops.

Two modes, and the difference matters when reading a verdict:

``fast``
    Reads the per-index COGs — single-band rasters the pipeline already
    wrote — and recomputes the aggregate from them. Masking is baked into
    those files, so this verifies **aggregation only**. A match here says the
    stored mean is a correct summary of the raster that was produced; it says
    nothing about whether the right pixels were masked.

``full``
    Reads the raw bands and re-runs the AOI mask, the SCL mask and the
    formulas. Verifies the whole chain, and is the only mode that can catch a
    masking-rule change.

The design doc proposed TiTiler's ``/cog/statistics`` for the fast path. This
reads the COG directly instead: rasterio is already in-process, so the HTTP
round-trip would add a failure mode and a second code path without saving
anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np
import rasterio
from shapely.geometry import shape

from app.core.logging import get_logger
from app.modules.imagery._rasterio_io import _gdal_s3_env
from app.modules.indices.computation import (
    compute_aggregates,
    compute_all_indices,
    scl_cloud_mask,
)

# How far a recomputed mean may sit from the stored one before it is drift.
#
# Stored means are NUMERIC(7,4), and the recomputation runs the same float64
# reduction, so an honest match is exact to the fourth decimal. The tolerance
# exists for the last-digit rounding of Decimal quantisation, not to absorb a
# methodology difference — 5e-5 is half a stored ulp, so a real change (the
# pre-SCL-mask rows run ~0.05 high) cannot hide under it.
MEAN_TOLERANCE = Decimal("0.00005")

# Valid-pixel counts are integers produced by the same reduction. Any
# difference at all is a different population of pixels, which is the thing
# worth knowing.
VALID_COUNT_TOLERANCE = 0

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SceneVerification:
    verdict: str
    per_index: dict[str, dict[str, Any]]
    error: str | None


def _verdict_for(
    stored_mean: Decimal | None,
    recomputed_mean: Decimal | None,
    stored_valid: int | None,
    recomputed_valid: int | None,
) -> str:
    """Compare one index's stored numbers against the recomputation.

    A stored row with no counterpart in the raster is `source_missing`, not
    `drift`: the distinction is between "this number is wrong" and "there is
    nothing left to check it against", and they call for different actions.
    """
    if recomputed_mean is None and recomputed_valid is None:
        return "source_missing"
    if stored_mean is None and stored_valid is None:
        return "source_missing"
    if (
        stored_valid is not None
        and recomputed_valid is not None
        and abs(stored_valid - recomputed_valid) > VALID_COUNT_TOLERANCE
    ):
        return "drift"
    if (
        stored_mean is not None
        and recomputed_mean is not None
        and abs(stored_mean - recomputed_mean) > MEAN_TOLERANCE
    ):
        return "drift"
    return "match"


def _worst(verdicts: list[str]) -> str:
    """Roll per-index verdicts up to one scene verdict.

    Ordered by how much attention each deserves, so a scene with six matches
    and one drift reports as drift. Averaging or majority-voting here would
    let a real defect disappear behind its neighbours.
    """
    for candidate in ("error", "drift", "source_missing"):
        if candidate in verdicts:
            return candidate
    return "match" if verdicts else "source_missing"


def verify_scene_full(
    *,
    raw_uri: str,
    band_names: tuple[str, ...],
    supported_indices: tuple[str, ...],
    aoi_geojson_utm: dict[str, Any],
    stored: dict[str, dict[str, Any]],
) -> SceneVerification:
    """Re-run masking and every formula from the raw bands, then diff.

    Deliberately mirrors `compute_indices` step for step — same reader, same
    masks, same `compute_aggregates` — minus the COG writes. Any divergence
    between this and the pipeline is a bug in one of them, which is precisely
    what the mode is for.
    """
    from rasterio.features import geometry_mask

    with _gdal_s3_env(), rasterio.open(raw_uri) as ds:
        n_science = len(band_names)
        arrays = {
            name: ds.read(idx + 1).astype(np.float32, copy=False)
            for idx, name in enumerate(band_names)
        }
        if ds.count == n_science + 1:
            cloud_mask = scl_cloud_mask(ds.read(n_science + 1).astype(np.float32, copy=False))
        else:
            cloud_mask = np.zeros((ds.height, ds.width), dtype=bool)
        aoi_mask = ~geometry_mask(
            [shape(aoi_geojson_utm)],
            out_shape=(ds.height, ds.width),
            transform=ds.transform,
            invert=False,
            all_touched=True,
        )

    try:
        computed = compute_all_indices(arrays)
    except KeyError as exc:
        return SceneVerification(
            verdict="error",
            per_index={},
            error=f"product is missing a band the formulas need: {exc}",
        )

    return _diff(
        recomputed={
            code: compute_aggregates(np.where(cloud_mask, np.float32("nan"), raster), aoi_mask)
            for code, raster in computed.items()
            if code in supported_indices
        },
        stored=stored,
    )


def verify_scene_fast(
    *,
    index_uris: dict[str, str],
    aoi_geojson_utm: dict[str, Any],
    stored: dict[str, dict[str, Any]],
) -> SceneVerification:
    """Recompute each index's aggregate from the index COG the pipeline wrote.

    Cheaper — one band per index instead of eight — but it can only confirm
    that the stored summary matches the raster. The raster already has the
    mask applied, so a masking-rule change is invisible to this mode. The
    verdict records `mode` alongside it so a "match" is never read as more
    than it is.
    """
    from rasterio.features import geometry_mask

    recomputed: dict[str, Any] = {}
    for code, uri in index_uris.items():
        try:
            with _gdal_s3_env(), rasterio.open(uri) as ds:
                raster = ds.read(1).astype(np.float32, copy=False)
                aoi_mask = ~geometry_mask(
                    [shape(aoi_geojson_utm)],
                    out_shape=(ds.height, ds.width),
                    transform=ds.transform,
                    invert=False,
                    all_touched=True,
                )
        except Exception as exc:
            # One missing index asset must not sink the whole scene: the
            # other six still have something to say. It is logged rather than
            # swallowed, and the missing index still reports `source_missing`
            # in the diff below — a silent gap would read as "verified".
            _log.info(
                "observer_verify_index_unreadable",
                index_code=code,
                uri=uri,
                error=str(exc)[:200],
            )
            continue
        recomputed[code] = compute_aggregates(raster, aoi_mask)

    return _diff(recomputed=recomputed, stored=stored)


def _diff(
    *,
    recomputed: dict[str, Any],
    stored: dict[str, dict[str, Any]],
) -> SceneVerification:
    per_index: dict[str, dict[str, Any]] = {}
    verdicts: list[str] = []

    for code in sorted(set(stored) | set(recomputed)):
        stored_row = stored.get(code, {})
        agg = recomputed.get(code)
        stored_mean = stored_row.get("mean")
        stored_valid = stored_row.get("valid_pixel_count")
        recomputed_mean = agg.mean if agg is not None else None
        recomputed_valid = agg.valid_pixel_count if agg is not None else None

        verdict = _verdict_for(stored_mean, recomputed_mean, stored_valid, recomputed_valid)
        verdicts.append(verdict)
        per_index[code] = {
            "stored_mean": _num(stored_mean),
            "recomputed_mean": _num(recomputed_mean),
            "delta_mean": (
                _num(recomputed_mean - stored_mean)
                if stored_mean is not None and recomputed_mean is not None
                else None
            ),
            "stored_valid": stored_valid,
            "recomputed_valid": recomputed_valid,
            "delta_valid": (
                recomputed_valid - stored_valid
                if stored_valid is not None and recomputed_valid is not None
                else None
            ),
            "verdict": verdict,
        }

    return SceneVerification(verdict=_worst(verdicts), per_index=per_index, error=None)


def _num(value: Decimal | float | None) -> float | None:
    """JSONB-safe number. Decimal is not JSON-serialisable."""
    return None if value is None else float(value)
