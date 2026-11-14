"""Wire shapes for crop documents (D29)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentKind = Literal["manual", "guide", "standard", "report", "other"]
DocumentLanguage = Literal["en", "ar", "other"]
Disposition = Literal["inline", "attachment"]

#: Stable across editions: the key a new edition supersedes the old one by.
DOCUMENT_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}$")

#: Largest file the upload accepts. Bound by the API ingress, which caps a
#: request body at 16 MB (`proxy-body-size` in infra/helm/api/values.yaml):
#: 15 MiB leaves room for the multipart envelope, so a too-large file gets
#: this API's 422 instead of nginx's bare 413. Raise both together.
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024

#: What may be uploaded, by extension. The extension decides the stored
#: content type, because a client's multipart part often says
#: `application/octet-stream` for anything but a PDF.
CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}

#: Types a browser renders itself, so "view" opens them inline. Everything
#: else is offered as a download even when the reader asked to view it.
INLINE_TYPES = frozenset({"application/pdf", "text/plain; charset=utf-8"})


def content_type_for(filename: str) -> str | None:
    _, dot, ext = filename.rpartition(".")
    if not dot:
        return None
    return CONTENT_TYPES.get(ext.lower())


def _required_text(value: str, *, what: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{what} must not be blank")
    return stripped


class CropDocumentFields(BaseModel):
    """The form fields of an upload, validated before any byte is stored."""

    model_config = ConfigDict(extra="forbid")

    crop_path: str = Field(min_length=1, max_length=200)
    document_code: str = Field(min_length=1, max_length=100)
    # Arabic is required on every new user-facing row (D26).
    title_en: str = Field(min_length=1, max_length=300)
    title_ar: str = Field(min_length=1, max_length=300)
    language: DocumentLanguage
    kind: DocumentKind
    edition: str = Field(min_length=1, max_length=50)

    @field_validator("crop_path", "edition")
    @classmethod
    def _strip(cls, value: str) -> str:
        return _required_text(value, what="value")

    @field_validator("title_en", "title_ar")
    @classmethod
    def _title(cls, value: str) -> str:
        return _required_text(value, what="title")

    @field_validator("document_code")
    @classmethod
    def _code(cls, value: str) -> str:
        code = value.strip()
        if not DOCUMENT_CODE_RE.match(code):
            raise ValueError(
                "document_code is lowercase letters, digits, '_', '.' or '-', "
                "starting with a letter or digit"
            )
        return code


class CropDocumentUpdateRequest(BaseModel):
    """Metadata a curator may correct without uploading a new edition."""

    model_config = ConfigDict(extra="forbid")

    title_en: str | None = Field(default=None, min_length=1, max_length=300)
    title_ar: str | None = Field(default=None, min_length=1, max_length=300)
    language: DocumentLanguage | None = None
    kind: DocumentKind | None = None
    edition: str | None = Field(default=None, min_length=1, max_length=50)
    #: True withdraws the document (it stops showing on blocks); false restores it.
    retired: bool | None = None

    @field_validator("title_en", "title_ar", "edition")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("omit the field instead of sending null")
        return _required_text(value, what="value")

    @field_validator("language", "kind", "retired", mode="before")
    @classmethod
    def _no_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("omit the field instead of sending null")
        return value


class CropDocument(BaseModel):
    id: UUID
    document_code: str
    crop_path: str
    title_en: str
    title_ar: str
    language: DocumentLanguage
    kind: DocumentKind
    edition: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    superseded_at: datetime | None = None
    superseded_by: UUID | None = None
    retired_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    #: Neither superseded nor retired: what a block shows.
    is_current: bool


class CropDocumentUploaded(CropDocument):
    #: The edition this upload replaced, or null for a first edition.
    superseded_id: UUID | None = None


class CropDocumentLink(BaseModel):
    """A time-limited URL to the stored file."""

    url: str
    expires_at: datetime
    disposition: Disposition


class BlockCropDocuments(BaseModel):
    """The documents a block's current crop path inherits."""

    block_id: UUID
    crop_path: str | None
    documents: list[CropDocument]
