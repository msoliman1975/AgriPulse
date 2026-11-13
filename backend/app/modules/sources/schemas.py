"""Wire shapes for the sources library (D27)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceKind = Literal[
    "article", "book", "report", "web", "standard", "thesis", "dataset", "internal", "other"
]
Confidence = Literal["high", "medium", "low", "expert_inference"]
EntityType = Literal[
    "finding",
    "decision_tree",
    "tree_parameter",
    "signal",
    "plan_template_activity",
    "reference_value",
    "input",
    "crop_attribute",
]


class SourceAlias(BaseModel):
    document_code: str
    document_title: str | None = None
    ref_number: int


class SourceSummary(BaseModel):
    id: UUID
    kind: SourceKind
    citation: str
    title: str | None = None
    authors: str | None = None
    year: int | None = None
    publisher: str | None = None
    doi: str | None = None
    url: str | None = None
    language: str | None = None
    notes: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    link_count: int = 0
    aliases: list[SourceAlias] = Field(default_factory=list)


class SourceLink(BaseModel):
    id: UUID
    source_id: UUID
    entity_type: EntityType
    entity_key: str
    detail: str
    confidence: Confidence
    note: str | None = None
    created_at: datetime
    citation: str
    url: str | None = None
    doi: str | None = None
    year: int | None = None
    kind: SourceKind


class SourceDetail(SourceSummary):
    links: list[SourceLink] = Field(default_factory=list)


class SourceDocument(BaseModel):
    document_code: str
    document_title: str | None = None
    entries: int


class _SourceFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: SourceKind | None = None
    title: str | None = Field(default=None, max_length=1000)
    authors: str | None = Field(default=None, max_length=2000)
    year: int | None = Field(default=None, ge=1800, le=2100)
    publisher: str | None = Field(default=None, max_length=500)
    doi: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, max_length=16)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("doi")
    @classmethod
    def _doi(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        value = value.removeprefix("https://doi.org/").removeprefix("doi:").strip()
        if not value.startswith("10."):
            raise ValueError("a DOI starts with '10.'")
        return value.lower()

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("a URL starts with http:// or https://")
        return value


class SourceCreateRequest(_SourceFields):
    citation: str = Field(min_length=1, max_length=4000)


class SourceUpdateRequest(_SourceFields):
    citation: str | None = Field(default=None, min_length=1, max_length=4000)
    is_active: bool | None = None


class SourceLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entity_type: EntityType
    entity_key: str = Field(min_length=1, max_length=255)
    detail: str = Field(default="", max_length=255)
    confidence: Confidence
    note: str | None = Field(default=None, max_length=2000)
