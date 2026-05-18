"""Reverse UTF-8-as-cp1252 mojibake in a JSON i18n file.

Walks the JSON tree and, for each string leaf, tries to reverse the
"UTF-8 bytes saved as cp1252" corruption. Only applies the fix if (a)
the reverse-mojibake succeeds AND (b) the result actually contains
non-ASCII characters that look like real Arabic/Unicode (i.e. the
input was actually mojibake, not innocent ASCII). Leaves everything
else alone — handles files where only SOME values were mangled.

Usage:  python scripts/fix_mojibake.py <path>
"""

import json
import pathlib
import sys
from typing import Any

# Try cp1252 first (Windows default — bytes 0x80-0x9F map to specific
# Unicode chars like „, …, „). Fall back to latin-1 (pure 1:1 byte
# mapping) for strings whose bytes don't trigger the cp1252 specials.
_CODECS = ("cp1252", "latin-1")


def maybe_fix_string(s: str) -> str:
    """Return the un-mojibake'd string if applicable, else `s` unchanged."""
    if not any(ord(c) > 127 for c in s):
        return s  # pure ASCII
    for codec in _CODECS:
        try:
            candidate = s.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        # Heuristic: only accept if the result has Arabic (U+0600-U+06FF)
        # — keeps innocent " — " (em-dash) and other Western punctuation
        # from being "fixed" into garbage.
        if any(0x0600 <= ord(c) <= 0x06FF for c in candidate):
            return candidate
    return s


def walk(node: Any) -> Any:
    if isinstance(node, str):
        return maybe_fix_string(node)
    if isinstance(node, list):
        return [walk(x) for x in node]
    if isinstance(node, dict):
        return {k: walk(v) for k, v in node.items()}
    return node


if len(sys.argv) != 2:
    print("usage: python scripts/fix_mojibake.py <path>", file=sys.stderr)
    sys.exit(2)

p = pathlib.Path(sys.argv[1])
parsed = json.loads(p.read_text(encoding="utf-8"))
fixed_parsed = walk(parsed)
# Keep `ensure_ascii=False` so the rewritten file has the real Arabic
# bytes, not `ا`-style escapes — matches the original file shape.
p.write_text(
    json.dumps(fixed_parsed, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"OK rewrote {p}")
