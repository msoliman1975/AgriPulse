"""Render one real tile with and without the cutline, and compare.

For a shell inside the running image. Renders the same pass twice through
the app object itself, decodes both PNGs, and counts pixels that carry
colour. The cut one must carry strictly fewer, and the pixels it drops
must all sit at the border.

    PYTHONPATH=/tmp python /tmp/check_tile_in_pod.py <s3-uri> <aoi-hash> <z> <x> <y>
"""

from __future__ import annotations

import json
import sys

import numpy as np
from rio_tiler.models import ImageData
from starlette.testclient import TestClient

import agripulse_tiles.main as m


def render(client: TestClient, uri: str, z: str, x: str, y: str, aoi: str | None) -> np.ndarray:
    params = {"url": uri, "rescale": "-1,1", "tilesize": "512", "reproject": "bilinear"}
    if aoi:
        params["algorithm"] = "cutline"
        params["algorithm_params"] = json.dumps({"aoi": aoi})
    resp = client.get(f"/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png", params=params)
    if resp.status_code != 200:
        raise SystemExit(f"tile failed {resp.status_code}: {resp.text[:300]}")
    img = ImageData.from_bytes(resp.content)
    # The PNG's alpha band is the last one; a pixel with alpha 0 is not drawn.
    return np.asarray(img.array[-1]) > 0


def main() -> None:
    uri, aoi, z, x, y = sys.argv[1:6]
    client = TestClient(m.app)

    plain = render(client, uri, z, x, y, None)
    cut = render(client, uri, z, x, y, aoi)

    drawn_plain = int(plain.sum())
    drawn_cut = int(cut.sum())
    dropped = int((plain & ~cut).sum())
    added = int((cut & ~plain).sum())

    print(f"tile {z}/{x}/{y}")
    print(f"  drawn without cutline: {drawn_plain}")
    print(f"  drawn with cutline:    {drawn_cut}")
    print(f"  dropped by the cut:    {dropped}")
    print(f"  added by the cut:      {added}  (must be 0)")
    if drawn_plain:
        print(f"  share dropped:         {100.0 * dropped / drawn_plain:.2f}%")
    if added:
        raise SystemExit("the cut added pixels, which it must never do")
    if dropped == 0:
        raise SystemExit("the cut dropped nothing - the boundary was probably not read")
    print("OK")


if __name__ == "__main__":
    main()
