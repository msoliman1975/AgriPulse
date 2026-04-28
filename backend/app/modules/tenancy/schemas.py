"""Pydantic request and response models for the tenancy admin API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9-]{3,32}$")


class CreateTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="URL-safe identifier, 3–32 chars, [a-z0-9-].")
    name: str = Field(min_length=1, max_length=255, description="Display name.")
    contact_email: EmailStr
    legal_name: str | None = None
    tax_id: str | None = None
    contact_phone: str | None = None
    default_locale: Literal["en", "ar"] = "en"
    default_unit_system: Literal["feddan", "acre", "hectare"] = "feddan"
    initial_tier: Literal["free", "standard", "premium", "enterprise"] = "free"

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        if not _SLUG_RE.fullmatch(value):
            raise ValueError("slug must match [a-z0-9-]{3,32}")
        return value


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    schema_name: str
    contact_email: str
    default_locale: str
    default_unit_system: str
    status: str
    created_at: datetime
