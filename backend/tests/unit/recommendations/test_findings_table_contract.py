"""The two finding tables must agree with the code that writes to them.

Three copies of the status list exist: `status_codes.py`, the CHECK in
public migration 0090, and the CHECK in tenant migration 0094. Nothing
forces them to agree, and a code added on one side only would be accepted
by the API and then rejected at write time by a constraint nobody thought
about. The same drift already has a test for the verdict table
(`test_verdict_table_contract`); this is the same guard for the catalogue.

It also pins the status vocabulary itself. `default_status` is the
decision-tree leaf status list, not the reports module's
`normal / watch / stressed / unknown`, which classifies a baseline z-score
and which no tree ever writes. The two were confused once while this table
was being specified, so the distinction is asserted rather than left to a
comment.

These tests read the migration files as text, so they need no database.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.modules.recommendations.models import (
    DecisionTreeFinding,
    TenantDecisionTreeFinding,
)
from app.modules.recommendations.schemas import FINDING_CODE_PATTERN
from app.modules.recommendations.status_codes import STATUS_CODES

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations"
_PUBLIC = _VERSIONS / "public" / "versions" / "0090_decision_tree_findings.py"
_TENANT = _VERSIONS / "tenant" / "versions" / "0094_decision_tree_findings.py"

# The eight catalogue columns plus the four audit ones. Named here so a
# column dropped from one table and not the other fails loudly.
_EXPECTED_COLUMNS = {
    "code",
    "clause_en",
    "clause_ar",
    "name_en",
    "name_ar",
    "default_status",
    "description_en",
    "description_ar",
    "is_active",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
}


def _status_codes_in(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    match = re.search(r'^_STATUS_CODES = "(.+)"$', source, re.MULTILINE)
    assert match is not None, f"_STATUS_CODES not found in {path.name}"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def test_public_check_matches_the_platform_status_list() -> None:
    assert _status_codes_in(_PUBLIC) == set(STATUS_CODES)


def test_tenant_check_matches_the_platform_status_list() -> None:
    assert _status_codes_in(_TENANT) == set(STATUS_CODES)


def test_default_status_is_the_leaf_vocabulary_not_the_reports_one() -> None:
    """`na / very_good / good / issue / alert`, never `normal / stressed`.

    `reports.schemas.CropHealthStatus` is a different four-value list for a
    different feature: it classifies a baseline z-score, its only producer
    is `reports.service._status_from_z`, and no decision tree writes it.
    Section 5.5 says a finding's status replaces the leaf as the source of
    the health colour, and this is what a leaf resolves to.
    """
    from app.modules.reports.schemas import CropHealthStatus

    reports_vocabulary = set(CropHealthStatus.__args__)

    assert set(STATUS_CODES) == {"na", "very_good", "good", "issue", "alert"}
    assert _status_codes_in(_PUBLIC).isdisjoint(reports_vocabulary - {"unknown"})


def test_both_tables_carry_the_same_columns() -> None:
    """The platform and tenant rows go through one code path.

    `resolve_findings` reads both by attribute name, so a column on one
    table and not the other would be a KeyError at fold time and nowhere
    earlier.
    """
    platform = {c.name for c in DecisionTreeFinding.__table__.columns}
    tenant = {c.name for c in TenantDecisionTreeFinding.__table__.columns}

    assert platform == tenant == _EXPECTED_COLUMNS


def test_the_two_models_are_the_same_table_in_different_schemas() -> None:
    assert DecisionTreeFinding.__table__.schema == "public"
    # None, not "tenant": the session's search_path resolves it per request.
    assert TenantDecisionTreeFinding.__table__.schema is None
    assert DecisionTreeFinding.__table__.name == TenantDecisionTreeFinding.__table__.name


def test_the_api_code_pattern_matches_the_database_check() -> None:
    """The form and the CHECK must accept the same codes.

    A code the API accepts and the database refuses is a 500 on a valid
    form; one the API refuses and the database allows is a code that can
    only be created by a migration.
    """
    for path in (_PUBLIC, _TENANT):
        source = path.read_text(encoding="utf-8")
        assert "code ~ '^[a-z][a-z0-9_]*$'" in source, path.name

    assert FINDING_CODE_PATTERN == r"^[a-z][a-z0-9_]*$"
    assert re.match(FINDING_CODE_PATTERN, "ndvi_low")
    assert re.match(FINDING_CODE_PATTERN, "dry")
    assert not re.match(FINDING_CODE_PATTERN, "NDVI_low")
    assert not re.match(FINDING_CODE_PATTERN, "2dry")
    assert not re.match(FINDING_CODE_PATTERN, "with space")


def test_both_tables_refuse_a_clause_containing_a_comma() -> None:
    """Three CHECKs each: ASCII comma in both clauses, plus U+060C in Arabic.

    The fold joins clauses with commas, so a clause carrying its own is
    unreadable once composed and there is no way to tell the two kinds
    apart afterwards.
    """
    for path in (_PUBLIC, _TENANT):
        source = path.read_text(encoding="utf-8")
        assert "clause_en NOT LIKE '%,%'" in source, path.name
        assert "clause_ar NOT LIKE '%,%'" in source, path.name
        assert "clause_ar NOT LIKE '%،%'" in source, path.name


def test_the_migration_pair_chains_off_the_right_revisions() -> None:
    public = _PUBLIC.read_text(encoding="utf-8")
    tenant = _TENANT.read_text(encoding="utf-8")

    assert 'revision: str = "0090"' in public
    assert 'down_revision: str | Sequence[str] | None = "0089"' in public
    assert 'revision: str = "0094"' in tenant
    assert 'down_revision: str | Sequence[str] | None = "0093"' in tenant
