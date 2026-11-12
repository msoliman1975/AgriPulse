"""The latest-photo map layer: which bands are colour, and the tile URL."""

from __future__ import annotations

from app.modules.imagery.service import rgb_band_indexes


def test_sentinel2_band_order() -> None:
    bands = ["blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"]
    assert rgb_band_indexes(bands) == (3, 2, 1)


def test_follows_the_product_not_a_fixed_order() -> None:
    assert rgb_band_indexes(["red", "nir", "green", "blue"]) == (1, 3, 4)


def test_a_product_without_all_visible_bands_has_no_photo() -> None:
    # Landsat thermal: red and nir for the indices, no green or blue.
    assert rgb_band_indexes(["lwir11", "red", "nir08"]) is None


def test_photo_tile_url_draws_true_colour_cut_to_the_farm() -> None:
    from urllib.parse import parse_qs, urlsplit

    from app.modules.imagery.service import latest_photo_tile_url

    url = latest_photo_tile_url(
        tile_server_base_url="https://tiles.example/",
        s3_bucket="bucket",
        stac_item_id="sentinel_hub/s2_l2a/S2B_X/abcd1234",
        aoi_hash="abcd1234",
        rgb=(3, 2, 1),
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://tiles.example/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png"
    )
    q = parse_qs(parts.query)
    assert q["url"] == ["s3://bucket/sentinel_hub/s2_l2a/S2B_X/abcd1234/raw_bands.tif"]
    assert q["bidx"] == ["3", "2", "1"], "red, green, blue, in that order"
    assert q["rescale"] == ["0,0.42", "0,0.34", "0,0.26"], "one window per band"
    assert q["scale"] == ["2"], "512 px tiles; TiTiler has no tilesize parameter"
    assert q["algorithm"] == ["cutline"]
    assert q["algorithm_params"] == ['{"aoi":"abcd1234"}']
