"""The attachment INSERT must not put a bind parameter inside ``IS NULL``.

Both attachment INSERTs used to read ``CASE WHEN :geo IS NULL THEN NULL ELSE
ST_GeomFromEWKT(:geo) END``. Postgres cannot infer a type for a parameter whose
only unambiguous use is a function call it never reaches during planning, so
the statement failed to prepare with ``could not determine data type of
parameter`` on every call, whatever ``:geo`` held. Farm and block attachments
were unusable for the whole life of the feature.

``ST_GeomFromEWKT`` is STRICT, so a NULL bind already returns NULL and the CASE
was never needed. This test pins the shape so it cannot come back. The
behaviour itself is covered by
``tests/integration/farms/test_attachments_insert.py``, which needs a real
database.
"""

from __future__ import annotations

from pathlib import Path

import app.modules.farms.repository as repo_mod


def test_attachment_inserts_do_not_bind_geo_inside_is_null() -> None:
    source = Path(repo_mod.__file__).read_text(encoding="utf-8")
    assert ":geo IS NULL" not in source
    # One for farm_attachments, one for block_attachments.
    assert source.count("ST_GeomFromEWKT(:geo)") == 2
