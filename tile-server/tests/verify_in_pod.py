"""Run the cutline checks without pytest, for a shell inside the image.

`tests/test_cutline.py` is the suite CI runs. This file exists because the
running container has titiler, rio-tiler and rasterio but no pytest, and
the one question worth answering on the real runtime is whether the
algorithm masks the pixels it should against the real `ImageData`.

    PYTHONPATH=/tmp python /tmp/verify_in_pod.py
"""

from __future__ import annotations

import numpy as np
from rasterio.crs import CRS
from rio_tiler.models import ImageData

from agripulse_tiles import cutline as mod
from agripulse_tiles.cutline import Cutline

WGS84 = CRS.from_epsg(4326)
BOUNDS = (0.0, 0.0, 10.0, 10.0)
SQUARE = {
    "type": "Polygon",
    "coordinates": [[[2.0, 2.0], [8.0, 2.0], [8.0, 8.0], [2.0, 8.0], [2.0, 2.0]]],
}


def image(mask=None) -> ImageData:
    data = np.full((1, 10, 10), 0.5, dtype="float32")
    zeros = np.zeros_like(data, dtype=bool)
    return ImageData(
        np.ma.MaskedArray(data, mask=zeros if mask is None else mask),
        crs=WGS84,
        bounds=BOUNDS,
    )


def main() -> None:
    checks = []

    mod._load_cached = lambda aoi: SQUARE  # type: ignore[assignment]
    mod.reset_caches()
    mod._missing_since.clear()

    out = Cutline(aoi="abcd1234")(image())
    inside = ~out.array.mask[0]
    checks.append(("6x6 pixel centres kept", int(inside.sum()) == 36))
    checks.append(("centre kept", bool(inside[5, 5])))
    checks.append(("corner cut", not inside[0, 0]))
    checks.append(("row above the border cut", bool(out.array.mask[0][1].all())))

    cloudy = np.zeros((1, 10, 10), dtype=bool)
    cloudy[0, 5, 5] = True
    out = Cutline(aoi="abcd1234")(image(mask=cloudy))
    checks.append(("existing mask kept", bool(out.array.mask[0][5, 5])))

    far = ImageData(
        np.ma.MaskedArray(np.full((1, 10, 10), 0.5, dtype="float32")),
        crs=WGS84,
        bounds=(100.0, 40.0, 110.0, 50.0),
    )
    checks.append(("image clear of the farm fully cut", bool(Cutline(aoi="abcd1234")(far).array.mask.all())))

    mod._load_cached = lambda aoi: None  # type: ignore[assignment]
    mod.reset_caches()
    mod._missing_since.clear()
    img = image()
    checks.append(("no boundary means no change", Cutline(aoi="abcd1234")(img) is img))

    # A web-mercator tile, which is the shape the map actually asks for.
    mod._load_cached = lambda aoi: SQUARE  # type: ignore[assignment]
    mod.reset_caches()
    mod._missing_since.clear()
    mercator = ImageData(
        np.ma.MaskedArray(np.full((1, 512, 512), 0.5, dtype="float32")),
        crs=CRS.from_epsg(3857),
        bounds=(0.0, 0.0, 1_200_000.0, 1_200_000.0),
    )
    cut = Cutline(aoi="abcd1234")(mercator)
    kept = int((~cut.array.mask[0]).sum())
    checks.append(("reprojects into a 3857 tile", 0 < kept < 512 * 512))

    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failures = [n for n, ok in checks if not ok]
    if failures:
        raise SystemExit(f"{len(failures)} failed: {failures}")
    print(f"all {len(checks)} checks passed")


if __name__ == "__main__":
    main()
