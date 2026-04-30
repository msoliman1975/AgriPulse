"""Unit tests for the S3 key builder."""

from __future__ import annotations

from uuid import UUID

from app.shared.storage import build_attachment_key

TENANT = UUID("11111111-1111-1111-1111-111111111111")
FARM = UUID("22222222-2222-2222-2222-222222222222")
ATTACHMENT = UUID("33333333-3333-3333-3333-333333333333")


def test_builds_tenant_scoped_key() -> None:
    key = build_attachment_key(
        tenant_id=TENANT,
        owner_kind="farms",
        owner_id=FARM,
        attachment_id=ATTACHMENT,
        original_filename="map.geojson",
    )
    assert key == (
        "tenants/11111111-1111-1111-1111-111111111111/"
        "farms/22222222-2222-2222-2222-222222222222/"
        "attachments/33333333-3333-3333-3333-333333333333/map.geojson"
    )


def test_sanitizes_unsafe_filenames() -> None:
    key = build_attachment_key(
        tenant_id=TENANT,
        owner_kind="blocks",
        owner_id=FARM,
        attachment_id=ATTACHMENT,
        original_filename="my photo (1).JPG",
    )
    assert key.endswith("/my_photo_1_.JPG")


def test_falls_back_to_default_when_filename_is_purely_special() -> None:
    key = build_attachment_key(
        tenant_id=TENANT,
        owner_kind="farms",
        owner_id=FARM,
        attachment_id=ATTACHMENT,
        original_filename="...",
    )
    assert key.endswith("/file")


def test_truncates_overlong_filename_preserving_extension() -> None:
    long_stem = "a" * 200
    key = build_attachment_key(
        tenant_id=TENANT,
        owner_kind="farms",
        owner_id=FARM,
        attachment_id=ATTACHMENT,
        original_filename=f"{long_stem}.pdf",
    )
    assert key.endswith(".pdf")
    # Tail-encoded filename portion is at most 80 chars including extension.
    tail = key.rsplit("/", 1)[-1]
    assert len(tail) <= 80
