"""Domain errors for the signals module."""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.core.errors import APIError

_TYPE_BASE = "https://missionagre.io/problems/signals"


class SignalDefinitionNotFoundError(APIError):
    def __init__(self, ref: str | UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Signal definition not found",
            detail=f"No signal definition with ref {ref!r} in this tenant.",
            type_=f"{_TYPE_BASE}/definition-not-found",
            extras={"ref": str(ref)},
        )


class SignalCodeAlreadyExistsError(APIError):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Signal code already exists",
            detail=f"An active signal definition with code {code!r} already exists.",
            type_=f"{_TYPE_BASE}/code-exists",
            extras={"code": code},
        )


class SignalAssignmentNotFoundError(APIError):
    def __init__(self, assignment_id: UUID) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Signal assignment not found",
            detail=f"No signal assignment with id {assignment_id} in this tenant.",
            type_=f"{_TYPE_BASE}/assignment-not-found",
            extras={"assignment_id": str(assignment_id)},
        )


class InvalidSignalValueError(APIError):
    """An observation's value violates the definition's constraints
    (wrong kind, out of range, not in categorical_values, etc.)."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid signal value",
            detail=detail,
            type_=f"{_TYPE_BASE}/invalid-value",
        )


class AttachmentNotPermittedError(APIError):
    def __init__(self, *, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Attachment not permitted",
            detail=f"Signal {code!r} does not allow attachments.",
            type_=f"{_TYPE_BASE}/attachment-not-permitted",
            extras={"code": code},
        )


class AttachmentMissingError(APIError):
    def __init__(self, *, key: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Attachment not uploaded",
            detail=(
                "The referenced attachment_s3_key was not found in object "
                "storage. Upload the file via the presigned URL first."
            ),
            type_=f"{_TYPE_BASE}/attachment-missing",
            extras={"attachment_s3_key": key},
        )
