"""Guard the two clock call shapes across `backend/app`.

A demo-history replay only produces past timestamps if every place that
asks for the time goes through the movable clock. There are two of them:

* Python code calls `app.shared.clock.now()`, never `datetime.now(...)`.
* SQL calls `public.app_now()`, never bare `now()`.

One missed call site does not raise an error. It writes today's date into
a row that is supposed to be months old, and the only way to notice is to
read the data afterwards. This test is the check that runs first.

The SQL half reads string literals through the tokenizer, so a comment
that mentions `now()` in prose does not fail the test and a real query
cannot hide in one.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize

APP = pathlib.Path(__file__).resolve().parents[3] / "app"

# `now()` not preceded by a dot or a word character, so `datetime.now()`
# and `func.now()` do not match.
BARE_SQL_NOW = re.compile(r"(?<![\w.])now\(\)")

STRING_TOKENS = {tokenize.STRING}
if hasattr(tokenize, "FSTRING_MIDDLE"):  # Python 3.12+
    STRING_TOKENS.add(tokenize.FSTRING_MIDDLE)

# `app/shared/clock.py` is the one file allowed to read the real clock,
# and it names both shapes in its docstring.
ALLOWED = {APP / "shared" / "clock.py"}


def _python_files() -> list[pathlib.Path]:
    return sorted(p for p in APP.rglob("*.py") if p not in ALLOWED)


def _docstring_lines(tree: ast.AST) -> set[int]:
    """Return every line number covered by a docstring.

    Prose is allowed to name `now()` when it explains what changed. Only a
    string that could reach Postgres is checked.
    """
    lines: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def test_no_direct_datetime_now_calls() -> None:
    """Every Python call site uses `clock.now()`."""
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "now":
                owner = func.value
                if isinstance(owner, ast.Name) and owner.id == "datetime":
                    offenders.append(f"{path.relative_to(APP.parent)}:{node.lineno}")
    assert offenders == [], (
        "These call the real clock directly. Use `clock.now()` so a "
        "demo-history replay can move them: " + ", ".join(offenders)
    )


def test_no_bare_now_in_sql_strings() -> None:
    """Every SQL call site uses `public.app_now()`."""
    offenders: list[str] = []
    for path in _python_files():
        src = path.read_text(encoding="utf-8")
        if "now()" not in src:
            continue
        skip = _docstring_lines(ast.parse(src))
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.start[0] in skip:
                continue
            if tok.type in STRING_TOKENS and BARE_SQL_NOW.search(tok.string):
                offenders.append(f"{path.relative_to(APP.parent)}:{tok.start[0]}")
    assert offenders == [], (
        "These SQL strings call Postgres `now()` directly. Use "
        "`public.app_now()` so a demo-history replay can move them: " + ", ".join(offenders)
    )


def test_the_audit_columns_default_to_the_movable_clock() -> None:
    """`TimestampedMixin` is the default every audited table inherits."""
    from app.shared.db.base import TimestampedMixin

    for name in ("created_at", "updated_at"):
        default = getattr(TimestampedMixin, name).column.server_default
        assert default is not None, f"{name} lost its server default"
        rendered = str(default.arg)
        assert rendered == "public.app_now()", (
            f"{name} defaults to {rendered!r}; it must be public.app_now() so a "
            "demo-history replay reaches it"
        )
