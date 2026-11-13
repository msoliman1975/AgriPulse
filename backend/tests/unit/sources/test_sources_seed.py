"""The D27 seed: every reference of the four Medjool lists, deduplicated."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.sources.schemas import SourceCreateRequest, SourceLinkRequest

_DATA = (
    Path(__file__).parents[3]
    / "migrations"
    / "public"
    / "versions"
    / "data"
    / "0105_sources_library.json"
)
SEED = json.loads(_DATA.read_text(encoding="utf-8"))


def test_every_reference_of_every_list_resolves_once() -> None:
    per_doc = Counter(doc for s in SEED["sources"] for doc, _ in s["aliases"])
    # Trees doc lists 45; its #3 "Expert inference" is a confidence level, not a source.
    assert per_doc == {
        "medjool_manual_1_7": 82,
        "medjool_manual_1_7_annex_a": 32,
        "medjool_manual_1_7_annex_b": 60,
        "medjool_trees_v2": 44,
    }
    for doc, total in (("medjool_manual_1_7", 82), ("medjool_trees_v2", 45)):
        numbers = sorted(n for s in SEED["sources"] for d, n in s["aliases"] if d == doc)
        expected = [n for n in range(1, total + 1) if (doc, n) != ("medjool_trees_v2", 3)]
        assert numbers == expected


def test_no_duplicate_doi_or_url() -> None:
    dois = [s["doi"] for s in SEED["sources"] if s["doi"]]
    urls = [s["url"] for s in SEED["sources"] if s["url"] and not s["doi"]]
    assert len(dois) == len(set(dois))
    assert len(urls) == len(set(urls))
    assert len(SEED["sources"]) == 152


def test_citations_are_clean_text() -> None:
    for s in SEED["sources"]:
        assert s["citation"]
        assert "](" not in s["citation"]
        assert "Confidence:" not in s["citation"]
        assert all(doc in SEED["documents"] for doc, _ in s["aliases"])


def test_doi_is_normalised_and_checked() -> None:
    req = SourceCreateRequest(citation="x", doi="https://doi.org/10.3390/Plants14203189")
    assert req.doi == "10.3390/plants14203189"
    with pytest.raises(ValidationError):
        SourceCreateRequest(citation="x", doi="not-a-doi")
    with pytest.raises(ValidationError):
        SourceCreateRequest(citation="x", url="ftp://example.org")


def test_link_confidence_includes_expert_inference() -> None:
    link = SourceLinkRequest(
        entity_type="tree_parameter",
        entity_key="date_palm_medjool_cold",
        detail="cold_irrigate_c",
        confidence="expert_inference",
    )
    assert link.confidence == "expert_inference"
    with pytest.raises(ValidationError):
        SourceLinkRequest(entity_type="finding", entity_key="x", confidence="certain")
