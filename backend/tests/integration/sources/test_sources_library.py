"""D27 on Postgres: the seeded library, aliases, and linking an entity."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.modules.sources.service import DuplicateDoiError, SourcesService


@pytest.mark.asyncio
async def test_seeded_library_resolves_document_numbers(admin_session: Any) -> None:
    service = SourcesService(admin_session)
    docs = {d["document_code"]: d["entries"] for d in await service.list_documents()}
    assert docs["medjool_manual_1_7"] == 82
    assert docs["medjool_trees_v2"] == 44

    first = await service.resolve_alias("medjool_manual_1_7", 1)
    assert first["citation"].startswith("FAO (2002). Date Palm Cultivation")
    # Deduplicated: the manual's [15] and the trees document's [41] are one source.
    a = await service.resolve_alias("medjool_manual_1_7", 15)
    b = await service.resolve_alias("medjool_trees_v2", 41)
    assert a["id"] == b["id"]

    found = await service.list_sources(
        q="red palm weevil", document_code=None, include_inactive=False, limit=50, offset=0
    )
    assert found
    assert all("aliases" in s for s in found)


@pytest.mark.asyncio
async def test_create_link_and_unlink(admin_session: Any) -> None:
    service = SourcesService(admin_session)
    doi = f"10.9999/agripulse-test-{uuid4().hex[:8]}"
    created = await service.create_source(
        {"citation": "Test source", "doi": doi, "kind": "article", "year": 2025}, None
    )
    with pytest.raises(DuplicateDoiError):
        await service.create_source({"citation": "Again", "doi": doi.upper()}, None)

    key = f"test_finding_{uuid4().hex[:6]}"
    link = await service.link(
        created["id"],
        {
            "entity_type": "finding",
            "entity_key": key,
            "detail": "",
            "confidence": "expert_inference",
            "note": None,
        },
        None,
    )
    assert link["confidence"] == "expert_inference"
    # Linking again updates the same row rather than adding a second one.
    again = await service.link(
        created["id"],
        {
            "entity_type": "finding",
            "entity_key": key,
            "detail": "",
            "confidence": "high",
            "note": "x",
        },
        None,
    )
    assert again["id"] == link["id"]
    assert again["confidence"] == "high"
    assert [x["id"] for x in await service.links_for(entity_type="finding", entity_key=key)] == [
        link["id"]
    ]

    await service.unlink(link["id"])
    assert await service.links_for(entity_type="finding", entity_key=key) == []
    retired = await service.update_source(created["id"], {"is_active": False}, None)
    assert retired["is_active"] is False
