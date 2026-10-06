"""Request and response bodies for investors, holdings, and ownership."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

InvestorType = Literal["person", "company"]
InvestorStatus = Literal["not_invited", "invited", "active", "suspended", "archived"]
Language = Literal["ar", "en"]
IdType = Literal["national_id", "passport", "commercial_register", "other"]
# What a writer may set. `archived` goes through the :archive action, and
# `sold` is never stored: it means "has a current owner" and is derived.
HoldingWritableStatus = Literal["draft", "available"]
HoldingStatus = Literal["draft", "available", "sold", "archived"]
AcquiredBy = Literal["purchase", "transfer", "inheritance", "other"]
EndedBy = Literal["resale", "buyback", "contract_end", "correction", "other"]


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


# ---- Investors -----------------------------------------------------------


class _InvestorFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investor_type: InvestorType | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    full_name_ar: str | None = Field(default=None, max_length=200)
    contact_person: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    national_id_type: IdType | None = None
    national_id_last4: str | None = Field(default=None, max_length=4)
    nationality: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    preferred_language: Language | None = None
    relationship_manager_id: UUID | None = None
    notes_internal: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "full_name_ar",
        "contact_person",
        "phone",
        "national_id_last4",
        "nationality",
        "country",
        "city",
        "notes_internal",
        mode="before",
    )
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return _blank_to_none(value)


class InvestorCreateRequest(_InvestorFields):
    code: str | None = Field(default=None, max_length=32)
    investor_type: InvestorType = "person"
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    preferred_language: Language = "ar"

    @field_validator("code", mode="before")
    @classmethod
    def _strip_code(cls, value: Any) -> Any:
        return _blank_to_none(value)


class InvestorUpdateRequest(_InvestorFields):
    """Profile fields only. Status follows the app login: see the
    :create-login, :resend-login, :disable-login and :enable-login actions."""


class InvestorResponse(BaseModel):
    id: UUID
    code: str
    investor_type: InvestorType
    full_name: str
    full_name_ar: str | None = None
    contact_person: str | None = None
    email: str
    phone: str | None = None
    national_id_type: IdType | None = None
    national_id_last4: str | None = None
    nationality: str | None = None
    country: str | None = None
    city: str | None = None
    preferred_language: Language
    user_id: UUID | None = None
    status: InvestorStatus
    relationship_manager_id: UUID | None = None
    notes_internal: str | None = None
    invited_at: datetime | None = None
    last_app_seen_at: datetime | None = None
    archived_at: datetime | None = None
    current_holdings_count: int = 0
    current_area_m2: Decimal = Decimal("0")
    created_at: datetime
    updated_at: datetime


# ---- Ownership -----------------------------------------------------------


class OwnershipResponse(BaseModel):
    id: UUID
    holding_id: UUID
    holding_code: str
    holding_name: str
    holding_name_ar: str | None = None
    farm_id: UUID
    farm_name: str | None = None
    farm_name_ar: str | None = None
    block_id: UUID
    block_code: str | None = None
    investor_id: UUID
    investor_code: str
    investor_name: str
    investor_name_ar: str | None = None
    start_date: date
    end_date: date | None = None
    acquired_by: AcquiredBy
    ended_by: EndedBy | None = None
    contract_ref: str | None = None
    # Derived against the platform clock: past, current, or future.
    period: Literal["past", "current", "future"]
    area_m2: Decimal
    created_at: datetime


class InvestorDetailResponse(InvestorResponse):
    ownerships: list[OwnershipResponse] = []


class OwnershipCreateRequest(BaseModel):
    """Give a holding an owner from ``start_date``.

    When the holding already has an open-ended owner, that ownership ends on
    the day before ``start_date`` with ``previous_ended_by``. That is a
    transfer, and it happens in one transaction.
    """

    model_config = ConfigDict(extra="forbid")

    investor_id: UUID
    start_date: date
    acquired_by: AcquiredBy = "purchase"
    contract_ref: str | None = Field(default=None, max_length=120)
    previous_ended_by: EndedBy = "resale"

    @field_validator("contract_ref", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return _blank_to_none(value)


class OwnershipEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_date: date
    ended_by: EndedBy


# ---- Holdings ------------------------------------------------------------


class HoldingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, max_length=200)
    boundary: dict[str, Any]
    tree_count: int | None = Field(default=None, ge=0, le=10_000_000)
    status: HoldingWritableStatus = "draft"
    notes_internal: str | None = Field(default=None, max_length=4000)

    @field_validator("code", "name_ar", "notes_internal", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return _blank_to_none(value)


class HoldingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, max_length=200)
    boundary: dict[str, Any] | None = None
    tree_count: int | None = Field(default=None, ge=0, le=10_000_000)
    status: HoldingWritableStatus | None = None
    notes_internal: str | None = Field(default=None, max_length=4000)

    @field_validator("name_ar", "notes_internal", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return _blank_to_none(value)


class HoldingOwnerSummary(BaseModel):
    ownership_id: UUID
    investor_id: UUID
    investor_code: str
    investor_name: str
    investor_name_ar: str | None = None
    since: date


class HoldingResponse(BaseModel):
    id: UUID
    code: str
    farm_id: UUID
    farm_name: str | None = None
    farm_name_ar: str | None = None
    block_id: UUID
    block_code: str | None = None
    block_name: str | None = None
    block_name_ar: str | None = None
    name: str
    name_ar: str | None = None
    # GeoJSON Polygon, SRID 4326.
    boundary: dict[str, Any]
    area_m2: Decimal
    block_area_m2: Decimal
    # holding area / block area * 100, both measured in the block's UTM zone.
    # Staff only: the investor app never receives it.
    share_pct: Decimal
    tree_count: int | None = None
    status: HoldingStatus
    notes_internal: str | None = None
    current_owner: HoldingOwnerSummary | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class HoldingDetailResponse(HoldingResponse):
    ownerships: list[OwnershipResponse] = []


class BlockHoldingsContextResponse(BaseModel):
    """What the draw screen needs: the block outline and its other holdings."""

    block_id: UUID
    block_code: str | None = None
    block_name: str | None = None
    block_name_ar: str | None = None
    farm_id: UUID
    boundary: dict[str, Any]
    block_area_m2: Decimal
    eligible: bool
    ineligible_reason: str | None = None
    holdings: list[HoldingResponse]
    sold_area_m2: Decimal
    unsold_area_m2: Decimal


# ---- App login -----------------------------------------------------------


class InvestorLoginResponse(BaseModel):
    investor: InvestorResponse
    # False when the set-password email could not be sent. Staff then hand
    # over `temporary_password` themselves.
    email_sent: bool
    temporary_password: str | None = None
    provisioning: str | None = None


# ---- Investments overview and farm map -----------------------------------


class OverviewFarmRow(BaseModel):
    farm_id: UUID
    farm_name: str
    farm_name_ar: str | None = None
    holdings: int
    sold: int
    for_sale: int
    draft: int
    area_sold_m2: Decimal
    block_area_m2: Decimal
    area_not_sold_m2: Decimal


class OverviewRecentRow(BaseModel):
    id: UUID
    start_date: date
    acquired_by: AcquiredBy
    created_at: datetime
    holding_id: UUID
    holding_code: str
    farm_id: UUID
    investor_id: UUID
    investor_code: str
    investor_name: str
    investor_name_ar: str | None = None
    previous_investor_code: str | None = None
    previous_ended_by: EndedBy | None = None


class InvestmentsOverviewResponse(BaseModel):
    investors: int
    holdings: int
    sold: int
    for_sale: int
    draft: int
    area_sold_m2: Decimal
    area_not_sold_m2: Decimal
    farms: list[OverviewFarmRow]
    recent: list[OverviewRecentRow]


class FarmMapBlock(BaseModel):
    id: UUID
    code: str
    name: str | None = None
    name_ar: str | None = None
    boundary: dict[str, Any]
    area_m2: Decimal
    # False for a pivot split into sectors: draw on a sector instead.
    eligible: bool


class FarmHoldingsMapResponse(BaseModel):
    farm_id: UUID
    blocks: list[FarmMapBlock]
    holdings: list[HoldingResponse]


# ---- Investor app (what the investor sees about themselves) ---------------
#
# Allowlists. Nothing here may carry a share, another holding, an internal
# note, a contract number, or anything about farm health. A test asserts the
# exact field sets.


class InvestorAppMeResponse(BaseModel):
    code: str
    full_name: str
    full_name_ar: str | None = None
    preferred_language: Language
    company_name: str | None = None


class InvestorAppHoldingResponse(BaseModel):
    holding_id: UUID
    code: str
    name: str
    name_ar: str | None = None
    farm_name: str | None = None
    farm_name_ar: str | None = None
    block_code: str | None = None
    block_name: str | None = None
    block_name_ar: str | None = None
    area_m2: Decimal
    tree_count: int | None = None
    crop_name_en: str | None = None
    crop_name_ar: str | None = None
    variety_name_en: str | None = None
    variety_name_ar: str | None = None
    planting_date: date | None = None
    start_date: date
    end_date: date | None = None
    period: Literal["past", "current", "future"]
    boundary: dict[str, Any]
    block_boundary: dict[str, Any]
