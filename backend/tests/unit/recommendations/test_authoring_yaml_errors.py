"""Author-supplied tree YAML must fail as a 4xx, not a 500.

The authoring endpoints compile the caller's YAML through the same loader
that validates the trees shipped with the server. That loader raises
``DecisionTreeParseError`` (500) because a broken *server fixture* is a
deployment fault. Re-raising it straight out of an authoring route turned
an ordinary typo in the editor — say a ``$params`` ref the tree never
declares — into a 500 with an internal source path in the message.

DB-less: covers the error translation the routes apply.
"""

from __future__ import annotations

from app.modules.recommendations.errors import (
    DecisionTreeParseError,
    InvalidTreeYamlError,
)


def test_parse_error_stays_a_500_for_server_fixtures() -> None:
    exc = DecisionTreeParseError(path="trees/mango.yaml", detail="missing 'root'")

    assert exc.status_code == 500
    assert exc.detail == "trees/mango.yaml: missing 'root'"


def test_authoring_wrapper_is_422() -> None:
    parse_error = DecisionTreeParseError(
        path="<api:my_tree>",
        detail="params ref 'rain_min_typo' is not declared in the tree's 'parameters' block",
    )

    wrapped = InvalidTreeYamlError.from_parse_error(parse_error)

    assert wrapped.status_code == 422
    assert wrapped.type.endswith("/invalid-tree-yaml")


def test_authoring_wrapper_drops_the_internal_source_path() -> None:
    """``<api:my_tree>`` is a loader implementation detail — an author
    reading the banner should see only what is wrong with their tree."""
    parse_error = DecisionTreeParseError(
        path="<api:my_tree>",
        detail="params ref 'rain_min_typo' is not declared in the tree's 'parameters' block",
    )

    wrapped = InvalidTreeYamlError.from_parse_error(parse_error)

    assert wrapped.detail == (
        "params ref 'rain_min_typo' is not declared in the tree's 'parameters' block"
    )
    assert "<api:" not in (wrapped.detail or "")


def test_wrapper_falls_back_when_reason_is_absent() -> None:
    """Defensive: a parse error raised without the newer attributes still
    produces a usable message rather than an empty banner."""
    parse_error = DecisionTreeParseError(path="<api:t>", detail="bad")
    del parse_error.reason

    wrapped = InvalidTreeYamlError.from_parse_error(parse_error)

    assert wrapped.status_code == 422
    assert wrapped.detail == "<api:t>: bad"
