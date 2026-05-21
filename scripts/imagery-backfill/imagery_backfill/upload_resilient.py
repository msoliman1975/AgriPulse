"""Wrapper around upload_to_local that survives flaky port-forwards.

`upload_to_local.main()` calls `psycopg.connect(...)` three times across
its lifetime (resolve / subscriptions / per-scene loop). Over a fragile
kubectl port-forward (especially through an SSM tunnel) the second open
often times out: the tunnel drops as soon as the first socket closes,
and the next connect spins for the libpq timeout before failing.

This module monkey-patches `psycopg.connect` to return a singleton that
ignores `__exit__()`-driven closes — so the upload script's three
`with psycopg.connect()` blocks all share one underlying TCP session.
We still respect commit/rollback boundaries (a `with` block that exits
cleanly commits; an exception rolls back) so resume semantics are
preserved.

Usage is identical to upload_to_local:

    python -m imagery_backfill.upload_resilient \
        --bundle ... --tenant-id ... --farm-id ... \
        --pg-dsn "host=localhost port=5433 user=agripulse dbname=agripulse" \
        --s3-mode aws --s3-bucket agripulse-imagery-dev \
        --aws-region eu-south-1 [--dry-run]
"""

from __future__ import annotations

import psycopg

from imagery_backfill import upload_to_local as _impl

# Capture the real `psycopg.connect` BEFORE we monkey-patch it, so the
# wrapper below can still reach the unpatched function. Without this we
# self-recurse the moment `_connect_once` tries to open the underlying
# connection.
_real_psycopg_connect = psycopg.connect

_real_conn: psycopg.Connection | None = None


class _PinnedConn:
    """Quacks like a psycopg connection but ignores ``with``-exit close.

    Commits/rollbacks still fire on context exit — matches psycopg's
    own ``with conn:`` semantics — but the underlying TCP session
    stays alive so subsequent ``with psycopg.connect(...)`` calls
    in the script reuse it.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str):  # noqa: ANN001 - dynamic delegation
        return getattr(self._conn, name)

    def cursor(self, *args, **kwargs):  # noqa: ANN001 - delegate
        return self._conn.cursor(*args, **kwargs)

    def __enter__(self) -> "_PinnedConn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        if exc_type is None:
            self._conn.commit()
        else:
            try:
                self._conn.rollback()
            except Exception:
                pass
        # Don't close — let the script use us again.
        return False


def _connect_once(*args, **kwargs) -> _PinnedConn:
    """Return the shared connection, opening it on first call.

    Drops kwargs that conflict with our once-and-done semantics:
    the first caller's row_factory + autocommit settings win, the
    upload script's later opens just inherit them via the same conn.
    """
    global _real_conn
    if _real_conn is None or _real_conn.closed:
        # Force the settings the write phase needs (the script's first
        # connect uses row_factory=dict_row; the second/third use
        # autocommit=False). Honor both regardless of what the caller
        # asked for so we don't depend on call order.
        from psycopg.rows import dict_row
        kwargs.setdefault("row_factory", dict_row)
        kwargs["autocommit"] = False
        _real_conn = _real_psycopg_connect(*args, **kwargs)
    return _PinnedConn(_real_conn)


def main() -> None:
    psycopg.connect = _connect_once  # type: ignore[assignment]
    try:
        _impl.main(standalone_mode=False)
    except SystemExit:
        # click raises SystemExit on --help / arg errors; let it through.
        raise
    finally:
        global _real_conn
        if _real_conn is not None:
            try:
                _real_conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
