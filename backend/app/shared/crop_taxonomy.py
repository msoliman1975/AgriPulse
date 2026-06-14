"""Crop-taxonomy path helpers.

The canonical hierarchical path code ``<crop>[.<variety>[.<strain>]]``
(e.g. ``mango.alphonso.short`` / ``cotton``) is the cross-consumer
targeting key. Targeting is by *path prefix on segment boundaries*:

  * ``mango``                → matches every Mango block
  * ``mango.alphonso``       → matches all Alphonso strains
  * ``mango.alphonso.short`` → matches exactly Short Alphonso

These functions are pure so engines (decision-tree selection) and tests
can use them without DB or I/O. Reports do the same prefix match in SQL
(``crop_path = :p OR crop_path LIKE :p || '.%'``).
"""

from __future__ import annotations


def path_matches(target: str | None, actual: str | None) -> bool:
    """True when ``actual`` falls under the ``target`` path prefix.

    A NULL/empty ``target`` is treated as "no path constraint" → matches
    anything (callers fall back to a coarser key like crop_id). A block
    with no ``actual`` path only matches the empty target.

    >>> path_matches("mango", "mango.alphonso.short")
    True
    >>> path_matches("mango.alphonso", "mango.alphonso.short")
    True
    >>> path_matches("mango.alphonso", "mango.eswwy.long")
    False
    >>> path_matches("mango.alph", "mango.alphonso")   # not a segment boundary
    False
    """
    if not target:
        return True
    if not actual:
        return False
    return actual == target or actual.startswith(target + ".")


def strain_code(path: str | None) -> str | None:
    """Return the strain segment of a 3-level path, else ``None``.

    >>> strain_code("mango.alphonso.short")
    'short'
    >>> strain_code("mango.alphonso")   # variety-level, no strain
    >>> strain_code("cotton")           # crop-only
    """
    if not path:
        return None
    segments = path.split(".")
    return segments[2] if len(segments) >= 3 else None
