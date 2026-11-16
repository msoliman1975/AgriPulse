"""Square WebP renditions of a crop image (64, 128, 256 px).

Pure image work plus storage reads and writes; the Celery task in `tasks.py`
is a thin shim over `make_renditions`.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

from app.shared.storage import RENDITION_SIZES, StorageClient, rendition_key

#: Refuse anything larger than this many pixels before decoding it: a 5 MB
#: PNG can still declare a huge canvas (a decompression bomb).
MAX_PIXELS = 40_000_000
WEBP_QUALITY = 85


class InvalidImageError(Exception):
    """The upload is not an image Pillow can read, or it is too large."""


def square_webp(data: bytes, sizes: tuple[int, ...] = RENDITION_SIZES) -> dict[int, bytes]:
    """Centre-crop to a square and encode one WebP per size."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            if width * height > MAX_PIXELS:
                raise InvalidImageError(f"{width}x{height} is more than {MAX_PIXELS} pixels")
            probe.load()
            # Phone photos carry their rotation in EXIF; apply it before cropping.
            image = ImageOps.exif_transpose(probe)
    except InvalidImageError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidImageError(str(exc)) from exc

    image = image.convert("RGBA")
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    square = image.crop((left, top, left + side, top + side))

    out: dict[int, bytes] = {}
    for size in sizes:
        buffer = io.BytesIO()
        square.resize((size, size), Image.Resampling.LANCZOS).save(
            buffer, format="WEBP", quality=WEBP_QUALITY, method=4
        )
        out[size] = buffer.getvalue()
    return out


def make_renditions(storage: StorageClient, original_key: str) -> list[str]:
    """Read the original, write every rendition next to it. Returns the keys written."""
    renditions = square_webp(storage.get_object(key=original_key))
    written: list[str] = []
    for size, body in renditions.items():
        key = rendition_key(original_key, size)
        storage.put_object(key=key, body=body, content_type="image/webp")
        written.append(key)
    return written
