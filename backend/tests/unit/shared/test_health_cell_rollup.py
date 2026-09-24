"""How cell verdicts become one block class, by the tenant's chosen rule.

Ten cells in every test here, so a share is a count: 2 of 10 is 20%.

  * ``worst``        the worst cell decides. The default, and the rule every
                     block was judged by before the choice existed.
  * ``share``        the worst status that covers at least the share of the
                     cells, counting worse statuses too, decides.
  * ``most_common``  the status on the most cells decides; a tie goes to the
                     worse status.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.modules.health.service import tenant_tier_from_settings
from app.modules.recommendations.status_codes import STATUS_DEFINITIONS
from app.shared.health_definition import (
    HealthDefinition,
    HealthDefinitionError,
    HealthInputs,
    VerdictEvidence,
    parse_definition,
    resolve_health,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
FRESH = NOW - timedelta(hours=2)


def _cells(**counts: int) -> HealthInputs:
    """``_cells(alert=1, good=9)``: that many cells in each status."""
    verdicts: list[VerdictEvidence] = []
    n = 0
    for code, count in counts.items():
        for _ in range(count):
            verdicts.append(VerdictEvidence(status_code=code, cell_id=f"c{n}"))
            n += 1
    return HealthInputs(verdicts=tuple(verdicts), verdict_last_evaluated_at=FRESH, total_cells=n)


def _resolve(inputs: HealthInputs, **definition: Any) -> tuple[str, str]:
    return resolve_health(HealthDefinition(**definition), inputs, now=NOW)


# ---- worst -----------------------------------------------------------------


def test_worst_one_alert_cell_makes_the_block_critical() -> None:
    assert _resolve(_cells(alert=1, good=9)) == ("critical", "verdict_alert")


# ---- share -----------------------------------------------------------------


def test_share_one_alert_cell_of_ten_does_not_recolour_the_block() -> None:
    """10% alert is under 20%. Alert plus issue is also only 10%, so good wins."""
    assert _resolve(_cells(alert=1, good=9), cell_rollup="share") == ("healthy", "verdict_good")


def test_share_two_alert_cells_of_ten_make_the_block_critical() -> None:
    assert _resolve(_cells(alert=2, good=8), cell_rollup="share") == ("critical", "verdict_alert")


def test_share_counts_worse_statuses_toward_a_milder_one() -> None:
    """1 alert + 1 issue is 20% at issue or worse, so the block is watch, and
    the reason says alert cells were held back rather than blaming an issue."""
    assert _resolve(_cells(alert=1, issue=1, good=8), cell_rollup="share") == (
        "watch",
        "cell_share",
    )


def test_share_reads_the_definition_share() -> None:
    inputs = _cells(alert=3, good=7)
    assert _resolve(inputs, cell_rollup="share", cell_critical_share=Decimal("0.5"))[0] == (
        "healthy"
    )
    assert _resolve(inputs, cell_rollup="share", cell_critical_share=Decimal("0.3"))[0] == (
        "critical"
    )


def test_a_block_scoped_alert_counts_in_full_under_share() -> None:
    inputs = _cells(good=10)
    inputs = HealthInputs(
        verdicts=(*inputs.verdicts, VerdictEvidence(status_code="alert", cell_id=None)),
        verdict_last_evaluated_at=FRESH,
        total_cells=10,
    )
    assert _resolve(inputs, cell_rollup="share") == ("critical", "verdict_alert")


def test_a_cell_two_trees_judged_counts_once_at_its_worst() -> None:
    """Two trees on one cell: alert and good. The cell is alert, once."""
    verdicts = [VerdictEvidence(status_code="alert", cell_id="c0")]
    verdicts += [VerdictEvidence(status_code="good", cell_id=f"c{i}") for i in range(10)]
    inputs = HealthInputs(verdicts=tuple(verdicts), verdict_last_evaluated_at=FRESH, total_cells=10)
    # 1 of 10 cells is alert: under the share.
    assert _resolve(inputs, cell_rollup="share")[0] == "healthy"


# ---- most_common -------------------------------------------------------------


def test_most_common_takes_the_status_on_most_cells() -> None:
    assert _resolve(_cells(alert=3, good=7), cell_rollup="most_common") == (
        "healthy",
        "verdict_good",
    )


def test_most_common_breaks_a_tie_toward_the_worse_status() -> None:
    assert _resolve(_cells(issue=5, good=5), cell_rollup="most_common") == (
        "watch",
        "verdict_issue",
    )


# ---- the definition --------------------------------------------------------


def test_an_unknown_rollup_is_refused_at_parse_time() -> None:
    with pytest.raises(HealthDefinitionError):
        parse_definition({"cell_rollup": "average"})


def test_the_status_ranks_match_the_decision_tree_list() -> None:
    from app.shared.health_definition import _STATUS_RANK

    assert {d.code: d.rank for d in STATUS_DEFINITIONS} == _STATUS_RANK


# ---- the tenant tier -------------------------------------------------------


def _setting(key: str, value: Any, overridden: bool) -> dict[str, Any]:
    return {"key": key, "value": value, "overridden": overridden}


def test_no_tenant_override_means_no_tenant_tier() -> None:
    rows = [
        _setting("health.cell_rollup", "worst", False),
        _setting("health.cell_share_pct", "20", False),
    ]
    assert tenant_tier_from_settings(rows) is None


def test_share_turns_the_percent_into_a_fraction() -> None:
    rows = [
        _setting("health.cell_rollup", "share", True),
        _setting("health.cell_share_pct", "35", False),
    ]
    tier = tenant_tier_from_settings(rows)
    assert tier == {"cell_rollup": "share", "cell_critical_share": "0.35"}
    assert parse_definition(tier).cell_critical_share == Decimal("0.35")


def test_worst_does_not_carry_the_share() -> None:
    """Under `worst` the share would hold alert cells back to watch, which a
    tenant choosing "the worst cell decides" did not ask for."""
    rows = [
        _setting("health.cell_rollup", "worst", True),
        _setting("health.cell_share_pct", "35", True),
    ]
    assert tenant_tier_from_settings(rows) == {"cell_rollup": "worst"}
