"""Sources library service (D27). Reads are open to any signed-in user;
writes are platform-only and audited."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sources.repository import SourcesRepository


class SourceNotFoundError(Exception):
    pass


class DuplicateDoiError(Exception):
    pass


class SourcesService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = SourcesRepository(session)

    async def list_sources(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await self._repo.list_sources(**kwargs)

    async def list_documents(self) -> list[dict[str, Any]]:
        return await self._repo.list_documents()

    async def get_source(self, source_id: UUID) -> dict[str, Any]:
        source = await self._repo.get_source(source_id)
        if source is None:
            raise SourceNotFoundError(str(source_id))
        aliases = await self._repo.list_aliases(source_id)
        links = await self._repo.list_links(source_id=source_id)
        return {**source, "aliases": aliases, "links": links, "link_count": len(links)}

    async def links_for(self, *, entity_type: str, entity_key: str) -> list[dict[str, Any]]:
        return await self._repo.list_links(entity_type=entity_type, entity_key=entity_key)

    async def resolve_alias(self, document_code: str, ref_number: int) -> dict[str, Any]:
        source_id = await self._repo.resolve_alias(document_code, ref_number)
        if source_id is None:
            raise SourceNotFoundError(f"{document_code}#{ref_number}")
        return await self.get_source(source_id)

    async def create_source(self, fields: dict[str, Any], actor: UUID | None) -> dict[str, Any]:
        if fields.get("doi") and await self._repo.doi_taken(fields["doi"]):
            raise DuplicateDoiError(fields["doi"])
        source_id = await self._repo.create_source(fields, actor)
        return await self.get_source(source_id)

    async def update_source(
        self, source_id: UUID, fields: dict[str, Any], actor: UUID | None
    ) -> dict[str, Any]:
        if fields.get("doi") and await self._repo.doi_taken(fields["doi"], exclude_id=source_id):
            raise DuplicateDoiError(fields["doi"])
        if not await self._repo.update_source(source_id, fields, actor):
            raise SourceNotFoundError(str(source_id))
        return await self.get_source(source_id)

    async def link(
        self, source_id: UUID, fields: dict[str, Any], actor: UUID | None
    ) -> dict[str, Any]:
        if await self._repo.get_source(source_id) is None:
            raise SourceNotFoundError(str(source_id))
        link_id = await self._repo.upsert_link(source_id, fields, actor)
        links = await self._repo.list_links(source_id=source_id)
        return next(link for link in links if link["id"] == link_id)

    async def unlink(self, link_id: UUID) -> dict[str, Any]:
        removed = await self._repo.delete_link(link_id)
        if removed is None:
            raise SourceNotFoundError(str(link_id))
        return removed
